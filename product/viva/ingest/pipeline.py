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
from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Callable

from vivacore.verify.arithmetic import CheckResult, check_balance_identity

from ..ledger.events import (Provenance, account_opened,
                             closing_balance_observed, document_captured,
                             opening_balance_observed, read_recorded,
                             statement_held)
from ..ledger.ledger import Ledger
from ..ledger.postings import simple_transaction
from .diagnose import FORCED, ReconciliationFinding, diagnose
from .identity import account_key
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
    """A stable account id anchored to the account number (institution + last-4),
    falling back to the label only when no number was extracted — so every month
    of the same account maps to the same ledger account regardless of how the
    statement labels it (Slice 1.5)."""
    return account_key(facts.institution, facts.account_number, facts.account_ref)


def _connects(facts: StatementFacts, proj) -> str:
    """How a reconciled statement attaches to its account's existing chain:
    'forward' (its opening = the current balance), 'backward' (its closing = the
    earliest opening — a backfill), or '' (a gap)."""
    account = account_id_for(facts)
    if facts.opening_amount == proj.running_balance(account):
        return "forward"
    if facts.closing_amount == proj.earliest_opening(account):
        return "backward"
    return ""


def heal_gaps(ledger: Ledger) -> int:
    """Re-post gap-held statements that now stitch onto their account's chain.

    Ingestion is order-independent *both ways*: a statement parked as a gap posts
    as soon as it connects — **forward** (its opening = the current balance) or
    **backward** (its closing = the earliest opening, a backfill). One post can
    unblock a neighbour, so this cascades until nothing more connects. Only gap
    holds are retried (they reconcile internally); conflict holds wait for a
    human."""
    posted_total = 0
    attempted: set[str] = set()
    while True:
        proj = ledger.projection()
        candidate = None
        for body in proj.gap_holds():
            doc_id = body["doc_id"]
            if doc_id in attempted:
                continue
            facts = StatementFacts.from_dict(body["facts"])
            if _connects(facts, proj):
                candidate = facts
                attempted.add(doc_id)
                break
        if candidate is None:
            return posted_total
        log.info("heal: previously-held %s now stitches — re-posting",
                 candidate.doc_id[:12])
        if post_statement(ledger, candidate).action == POSTED:
            posted_total += 1


def _reconciles(facts: StatementFacts) -> CheckResult:
    return check_balance_identity(
        facts.opening_amount, [t.amount for t in facts.transactions],
        facts.closing_amount)


def _apply_forced(facts: StatementFacts,
                  finding: ReconciliationFinding) -> StatementFacts:
    """Return a copy of the facts with a forced correction applied. Only ever
    called on a FORCED finding — a correction an independent identity implies."""
    if finding.kind == "amount_misread" and finding.target_index is not None:
        txns = list(facts.transactions)
        i = finding.target_index
        txns[i] = replace(txns[i], amount=Decimal(finding.implied))
        return replace(facts, transactions=txns)
    if finding.kind == "balance_misread":
        return replace(facts, closing_amount=Decimal(finding.implied))
    return facts


def post_statement(ledger: Ledger, facts: StatementFacts,
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
        return _post_reconciled(ledger, facts, recon, finding=None,
                                auto_corrected=False, confirmed_by=confirmed_by)

    finding = diagnose(facts)
    log.info("post_statement: did NOT reconcile (%s); diagnosis=%s/%s: %s",
             recon.explain(), finding.status, finding.kind, finding.message)
    if finding.status == FORCED:
        corrected = _apply_forced(facts, finding)
        recon2 = _reconciles(corrected)
        if recon2.passed:
            log.info("post_statement: forced correction applied -> reconciles")
            res = _post_reconciled(ledger, corrected, recon2, finding=finding,
                                   auto_corrected=True)
            if res.action == POSTED:
                res.message = f"{finding.message} {res.message}"
            return res

    log.info("post_statement: holding for review (doc_id=%s)", facts.doc_id[:12])
    ledger.append(statement_held(
        facts.doc_id, facts.to_dict(), finding.to_dict(), "conflict",
        facts.closing_date, Provenance(doc_id=facts.doc_id)))
    return IngestResult(
        doc_id=facts.doc_id, action=CONFLICT, doc_type=facts.doc_type,
        account=account_id_for(facts), grade="conflicted",
        reconciliation=recon, finding=finding,
        message=f"Not posted; held for your review. {finding.message}")


def _post_reconciled(ledger: Ledger, facts: StatementFacts, recon: CheckResult,
                     finding: ReconciliationFinding | None,
                     auto_corrected: bool, confirmed_by: str = "") -> IngestResult:
    """Write a statement that reconciles: seed a new account, stitch onto the end
    (forward), backfill in front (backward), or — if it connects to neither —
    hold it as a gap (never invent the gap)."""
    account = account_id_for(facts)
    proj = ledger.projection()

    if not proj.is_seeded(account):
        log.info("_post_reconciled: opening new account %s (%s %s) seeded at %s",
                 account, facts.account_ref, facts.currency, facts.opening_amount)
        ledger.append(account_opened(
            account, "depository", facts.account_ref or account,
            facts.currency, facts.opening_date))
        ledger.append(opening_balance_observed(
            account, facts.opening_amount, facts.opening_date,
            facts.opening_provenance()))
    else:
        how = _connects(facts, proj)
        if how == "forward":
            log.info("_post_reconciled: forward-stitching onto %s at %s",
                     account, facts.opening_amount)
            # no opening event — the prior closing already is this opening
        elif how == "backward":
            log.info("_post_reconciled: backfilling %s in front (opening %s "
                     "re-seats the OBE)", account, facts.opening_amount)
            ledger.append(opening_balance_observed(
                account, facts.opening_amount, facts.opening_date,
                facts.opening_provenance()))
        else:
            prior = proj.running_balance(account)
            log.info("_post_reconciled: GAP — opening %s / closing %s connect to "
                     "neither (held=%s, earliest=%s); holding", facts.opening_amount,
                     facts.closing_amount, prior, proj.earliest_opening(account))
            ledger.append(statement_held(
                facts.doc_id, facts.to_dict(), None, "gap",
                facts.closing_date, Provenance(doc_id=facts.doc_id)))
            return IngestResult(
                doc_id=facts.doc_id, action=GAP, doc_type=facts.doc_type,
                account=account, grade="conflicted", reconciliation=recon,
                message=(f"This statement ({facts.opening_date} – "
                         f"{facts.closing_date}) opens at {facts.opening_amount}, "
                         f"which doesn't continue from the balance I hold ({prior}). "
                         "A statement between them looks missing — held, so I don't "
                         "invent the gap; it will slot in when the connector arrives."))

    for t in facts.transactions:
        ledger.append(simple_transaction(
            account, t.amount, t.description, t.date,
            provenance=t.provenance(facts.doc_id)))
    ledger.append(closing_balance_observed(
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


def capture_and_ingest(raw: RawStore, ledger: Ledger, data: bytes,
                       read_fn: ReadFn, filename: str = "",
                       captured_at: str = "") -> IngestResult:
    """Raw-capture a file, read it, and either post it or park it — never lose it."""
    doc_id = raw.put(data)                       # (1) capture first, always
    log.info("ingest start: %s (%d bytes) doc_id=%s",
             filename or "<upload>", len(data), doc_id[:12])
    if ledger.projection().is_resolved(doc_id):
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

    ledger.append(document_captured(             # record that we hold it
        doc_id, filename, len(data), rr.doc_type, rr.doc_type_confidence,
        captured_at, Provenance(doc_id=doc_id)))

    # The claims layer: persist the verbatim model output for any real read.
    if rr.model:
        ledger.append(read_recorded(
            doc_id, rr.model, rr.prompt_version, rr.input_mode, rr.raw_text,
            rr.cost_usd, rr.input_tokens, rr.output_tokens,
            rr.facts is not None, rr.error, captured_at, Provenance(doc_id=doc_id)))
        log.info("ingest: stored ReadRecorded (model=%s cost=$%.4f parse_ok=%s "
                 "resp_chars=%d)", rr.model, rr.cost_usd, rr.facts is not None,
                 len(rr.raw_text))

    # (3) route by type — v0 projects checking statements, parks the rest.
    if rr.facts is not None and rr.doc_type in CHECKING_DOC_TYPES:
        res = post_statement(ledger, rr.facts)   # (4) the reconciliation gate
        if res.action == POSTED:
            healed = heal_gaps(ledger)           # a new post may unblock waiting statements
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
