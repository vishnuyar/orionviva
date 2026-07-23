"""The ingest pipeline: capture → classify → verify → post.

The shape the whole product turns on, and the place the model finally meets the
trust core. Every file that arrives is:

  1. **Captured raw and encrypted, first, unconditionally** (ADR-003/T3). Nothing
     is judged before it is safely held. Content-addressed, so a re-upload is a
     no-op, not a duplicate.
  2. **Read by a model** — the one place a model is in this path. The read is a
     *proposal*, never trusted on its own.
  3. **Routed by type.** v0 has exactly one projector — checking statements. A
     recognized checking statement goes to the reconciliation gate; anything else
     is *parked*: held and acknowledged ("I have this; I can't read it yet"),
     never discarded. As later slices add projectors, parked documents light up
     retroactively — no re-upload.
  4. **Gated by deterministic reconciliation.** A statement posts to the ledger
     only if opening + its transactions reconcile to the printed closing, to the
     cent. Fail, and it is surfaced as a conflict, not posted. The model reads;
     arithmetic certifies (ADR-010).

Across months of the same account the pipeline *stitches*: a later statement's
opening must equal the balance we already hold, or the gap is surfaced (a likely
missing statement) rather than papered over.

The model read is injected (``read_fn``), so everything here is testable offline
with fixtures. Only the real reader touches the network.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, replace
from typing import Callable

from vivacore.verify.arithmetic import CheckResult, check_balance_identity

from ..ledger.events import (Provenance, account_opened,
                             closing_balance_observed, document_captured,
                             opening_balance_observed, read_recorded,
                             statement_held)
from ..ledger.postings import simple_transaction
from ..ledger.projection import LedgerProjection
from ..ledger.store import EventStore
from .diagnose import FORCED, ReconciliationFinding, diagnose
from .raw_store import RawStore
from .statement import StatementFacts

log = logging.getLogger(__name__)

# v0's single projector keys off these classified types. This set is the seed of
# the type registry (data, not code) that later slices grow.
CHECKING_DOC_TYPES = frozenset({
    "checking_statement", "checking", "bank_statement", "combined_bank_statement",
})

# Ingest actions, each an honest outcome the caller can report verbatim.
POSTED = "posted"        # reconciled and written to the ledger
PARKED = "parked"        # captured and acknowledged; no projector for it yet
DUPLICATE = "duplicate"  # already ingested (same content hash)
CONFLICT = "conflict"    # recognized, but did not reconcile — not posted
GAP = "gap"              # opening does not continue from the balance we hold


@dataclass
class ReadResult:
    """What a reader returns for one document: its classification, and — if it is
    a statement — the structured facts. A reader for a non-statement returns
    ``facts=None`` with the type it recognized (e.g. 'pay_stub').

    The ``raw_*`` fields carry the verbatim model output and call metadata so the
    pipeline can persist the claims layer (a real read sets ``model``; a stub
    leaves it empty and nothing extra is recorded)."""
    doc_type: str
    doc_type_confidence: float
    facts: StatementFacts | None = None
    error: str | None = None
    raw_text: str = ""
    model: str = ""
    prompt_version: str = ""
    input_mode: str = "text+image"
    cost_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class IngestResult:
    doc_id: str
    action: str
    doc_type: str
    account: str | None = None
    grade: str | None = None
    reconciliation: CheckResult | None = None
    finding: ReconciliationFinding | None = None   # why it failed / how it was fixed
    auto_corrected: bool = False
    message: str = ""


ReadFn = Callable[[bytes, str], ReadResult]


def account_id_for(facts: StatementFacts) -> str:
    """A stable account id from how the statement names the account, so every
    month of the same account maps to the same ledger account."""
    slug = re.sub(r"[^a-z0-9]+", "-", facts.account_ref.strip().lower()).strip("-")
    return f"acct:{slug or 'unknown'}"


def _posted_doc_ids(store: EventStore) -> set[str]:
    ids: set[str] = set()
    for e in store.events():
        if e.event_type in ("TransactionRecorded", "ClosingBalanceObserved",
                            "OpeningBalanceObserved") and e.provenance.doc_id:
            ids.add(e.provenance.doc_id)
    return ids


def heal_gaps(store: EventStore) -> int:
    """Re-post gap-held statements that now stitch onto their account's chain.

    Ingestion is order-independent in the forward direction: a statement whose
    opening didn't match the balance we held is parked as a *gap*, and when the
    connecting statement later posts (raising the balance to that opening), this
    sweep slots the waiting one in — cascading down a run. Returns how many
    posted. Only ``gap`` holds are retried (they already reconcile internally);
    conflict holds wait for a human."""
    posted_total = 0
    attempted: set[str] = set()
    while True:
        proj = LedgerProjection(store.events())
        resolved = _posted_doc_ids(store)
        candidate = None
        for e in store.events():
            if e.event_type != "StatementHeld" or e.body.get("reason") != "gap":
                continue
            doc_id = e.body["doc_id"]
            if doc_id in resolved or doc_id in attempted:
                continue
            facts = StatementFacts.from_dict(e.body["facts"])
            bal = proj.running_balance(account_id_for(facts))
            if bal is not None and facts.opening_amount == bal:
                candidate = (doc_id, facts)
                break
        if candidate is None:
            return posted_total
        doc_id, facts = candidate
        attempted.add(doc_id)
        log.info("heal: previously-held %s now stitches — re-posting", doc_id[:12])
        if post_statement(store, facts).action == POSTED:
            posted_total += 1
    # (loop returns from inside)


def _is_resolved(store: EventStore, doc_id: str) -> bool:
    """A document is 'done' only once it reached a terminal state — posted, or
    held for review. A document that merely *parked* (captured but not read into
    anything) is NOT done: re-uploading it should re-read it, since the reader or
    parser may have improved. This is what lets a fixed parse heal a parked doc."""
    for e in store.events():
        did = e.provenance.doc_id
        if e.event_type in ("TransactionRecorded", "ClosingBalanceObserved",
                            "OpeningBalanceObserved") and did == doc_id:
            return True
        if e.event_type == "StatementHeld" and e.body.get("doc_id") == doc_id:
            return True
    return False


def _reconciles(facts: StatementFacts) -> CheckResult:
    return check_balance_identity(
        facts.opening_amount, [t.amount for t in facts.transactions],
        facts.closing_amount)


def _apply_forced(facts: StatementFacts,
                  finding: ReconciliationFinding) -> StatementFacts:
    """Return a copy of the facts with a forced correction applied. Only ever
    called on a FORCED finding — a correction an independent identity implies."""
    from decimal import Decimal
    if finding.kind == "amount_misread" and finding.target_index is not None:
        txns = list(facts.transactions)
        i = finding.target_index
        txns[i] = replace(txns[i], amount=Decimal(finding.implied))
        return replace(facts, transactions=txns)
    if finding.kind == "balance_misread":
        return replace(facts, closing_amount=Decimal(finding.implied))
    return facts


def post_statement(store: EventStore, facts: StatementFacts,
                   confirmed_by: str = "") -> IngestResult:
    """Reconcile a checking statement and, only if it holds, post it. The gate.

    On failure, diagnose deterministically (no model call). A *forced* correction
    — one an independent identity implies and which closes the reconciliation —
    is auto-applied and posted at `corroborated`, and reported. Anything merely
    *suggested* or unlocalized is *held for review* (persisted, never posted).

    ``confirmed_by='human'`` (used when a person has ruled on a held statement)
    posts the closing at `verified`."""
    log.info("post_statement: account=%s opening=%s closing=%s txns=%d",
             account_id_for(facts), facts.opening_amount, facts.closing_amount,
             len(facts.transactions))
    recon = _reconciles(facts)
    if recon.passed:
        log.info("post_statement: reconciles on first read")
        return _post_reconciled(store, facts, recon, finding=None,
                                auto_corrected=False, confirmed_by=confirmed_by)

    finding = diagnose(facts)
    log.info("post_statement: did NOT reconcile (%s); diagnosis=%s/%s: %s",
             recon.explain(), finding.status, finding.kind, finding.message)
    if finding.status == FORCED:
        corrected = _apply_forced(facts, finding)
        recon2 = _reconciles(corrected)
        if recon2.passed:
            log.info("post_statement: forced correction applied -> reconciles")
            res = _post_reconciled(store, corrected, recon2, finding=finding,
                                   auto_corrected=True)
            if res.action == POSTED:
                res.message = f"{finding.message} {res.message}"
            return res

    log.info("post_statement: holding for review (doc_id=%s)", facts.doc_id[:12])
    store.append(statement_held(
        facts.doc_id, facts.to_dict(), finding.to_dict(), "conflict",
        facts.closing_date, Provenance(doc_id=facts.doc_id)))
    return IngestResult(
        doc_id=facts.doc_id, action=CONFLICT, doc_type=facts.doc_type,
        account=account_id_for(facts), grade="conflicted",
        reconciliation=recon, finding=finding,
        message=f"Not posted; held for your review. {finding.message}")


def _post_reconciled(store: EventStore, facts: StatementFacts, recon: CheckResult,
                     finding: ReconciliationFinding | None,
                     auto_corrected: bool, confirmed_by: str = "") -> IngestResult:
    """Write a statement that reconciles: seed a new account or stitch onto an
    existing one (surfacing a gap rather than inventing it), then post."""
    account = account_id_for(facts)
    proj = LedgerProjection(store.events())
    if proj.is_seeded(account):
        prior = proj.running_balance(account)
        log.info("_post_reconciled: stitching onto %s (held=%s, new opening=%s)",
                 account, prior, facts.opening_amount)
        if facts.opening_amount != prior:
            log.info("_post_reconciled: GAP — opening %s != held %s; holding",
                     facts.opening_amount, prior)
            store.append(statement_held(
                facts.doc_id, facts.to_dict(),
                finding.to_dict() if finding else None, "gap",
                facts.closing_date, Provenance(doc_id=facts.doc_id)))
            return IngestResult(
                doc_id=facts.doc_id, action=GAP, doc_type=facts.doc_type,
                account=account, grade="conflicted", reconciliation=recon,
                finding=finding,
                message=(f"This statement opens at {facts.opening_amount}, but "
                         f"the last balance I hold is {prior}. Likely a missing "
                         "statement between them — held for your review, so I "
                         "don't invent the gap."))
    else:
        log.info("_post_reconciled: opening new account %s (%s %s) seeded at %s",
                 account, facts.account_ref, facts.currency, facts.opening_amount)
        store.append(account_opened(
            account, "depository", facts.account_ref or account,
            facts.currency, facts.opening_date))
        store.append(opening_balance_observed(
            account, facts.opening_amount, facts.opening_date,
            facts.opening_provenance()))

    for t in facts.transactions:
        store.append(simple_transaction(
            account, t.amount, t.description, t.date,
            provenance=t.provenance(facts.doc_id)))
    store.append(closing_balance_observed(
        account, facts.closing_amount, facts.closing_date,
        facts.closing_provenance(), confirmed_by=confirmed_by))
    log.info("_post_reconciled: posted %d transactions + closing %s to %s%s",
             len(facts.transactions), facts.closing_amount, account,
             " (human-confirmed)" if confirmed_by == "human" else "")

    grade = "verified" if confirmed_by == "human" else "corroborated"
    return IngestResult(
        doc_id=facts.doc_id, action=POSTED, doc_type=facts.doc_type,
        account=account, grade=grade, reconciliation=recon,
        finding=finding, auto_corrected=auto_corrected,
        message=(f"Posted and reconciled: balance {facts.closing_amount} as of "
                 f"{facts.closing_date}."))


def capture_and_ingest(raw: RawStore, store: EventStore, data: bytes,
                       read_fn: ReadFn, filename: str = "",
                       captured_at: str = "") -> IngestResult:
    """Raw-capture a file, read it, and either post it or park it — never lose it."""
    doc_id = raw.put(data)                       # (1) capture first, always
    log.info("ingest start: %s (%d bytes) doc_id=%s",
             filename or "<upload>", len(data), doc_id[:12])
    if _is_resolved(store, doc_id):
        log.info("ingest: doc_id=%s already posted/held — skipping", doc_id[:12])
        return IngestResult(doc_id=doc_id, action=DUPLICATE, doc_type="",
                            message="Already posted or held (same content); no change.")

    try:
        rr = read_fn(data, doc_id)               # (2) the model read (a proposal)
    except Exception as e:                       # a read that threw is recorded, not orphaned
        log.warning("ingest: read raised for doc_id=%s: %s", doc_id[:12], e)
        rr = ReadResult("unknown", 0.0, None, error=f"read failed: {e}",
                        model="(read error)")
    log.info("ingest: read doc_id=%s -> doc_type=%r conf=%.2f facts=%s error=%s",
             doc_id[:12], rr.doc_type, rr.doc_type_confidence,
             rr.facts is not None, rr.error)

    store.append(document_captured(              # record that we hold it
        doc_id, filename, len(data), rr.doc_type, rr.doc_type_confidence,
        captured_at, Provenance(doc_id=doc_id)))

    # The claims layer: persist the verbatim model output for any real read.
    if rr.model:
        store.append(read_recorded(
            doc_id, rr.model, rr.prompt_version, rr.input_mode, rr.raw_text,
            rr.cost_usd, rr.input_tokens, rr.output_tokens,
            rr.facts is not None, rr.error, captured_at, Provenance(doc_id=doc_id)))
        log.info("ingest: stored ReadRecorded (model=%s cost=$%.4f parse_ok=%s "
                 "resp_chars=%d)", rr.model, rr.cost_usd, rr.facts is not None,
                 len(rr.raw_text))

    # (3) route by type — v0 projects checking statements, parks the rest.
    if rr.facts is not None and rr.doc_type in CHECKING_DOC_TYPES:
        res = post_statement(store, rr.facts)    # (4) the reconciliation gate
        if res.action == POSTED:
            healed = heal_gaps(store)            # a new post may unblock waiting statements
            if healed:
                log.info("ingest: healed %d previously-held statement(s)", healed)
        log.info("ingest done: doc_id=%s -> %s (%s)", doc_id[:12], res.action, res.grade)
        return res

    reason = rr.error or f"no projector yet for '{rr.doc_type or 'unknown'}'"
    log.info("ingest done: doc_id=%s -> parked (%s)", doc_id[:12], reason)
    return IngestResult(
        doc_id=doc_id, action=PARKED, doc_type=rr.doc_type,
        message=(f"Captured and held; not yet readable ({reason}). It will be "
                 "understood when a projector for its type arrives."))
