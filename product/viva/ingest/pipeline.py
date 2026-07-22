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

import re
from dataclasses import dataclass
from typing import Callable

from vivacore.verify.arithmetic import CheckResult, check_balance_identity

from ..ledger.events import (Provenance, account_opened,
                             closing_balance_observed, document_captured,
                             opening_balance_observed)
from ..ledger.postings import simple_transaction
from ..ledger.projection import LedgerProjection
from ..ledger.store import EventStore
from .raw_store import RawStore
from .statement import StatementFacts

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
    ``facts=None`` with the type it recognized (e.g. 'pay_stub')."""
    doc_type: str
    doc_type_confidence: float
    facts: StatementFacts | None = None
    error: str | None = None


@dataclass
class IngestResult:
    doc_id: str
    action: str
    doc_type: str
    account: str | None = None
    grade: str | None = None
    reconciliation: CheckResult | None = None
    message: str = ""


ReadFn = Callable[[bytes, str], ReadResult]


def account_id_for(facts: StatementFacts) -> str:
    """A stable account id from how the statement names the account, so every
    month of the same account maps to the same ledger account."""
    slug = re.sub(r"[^a-z0-9]+", "-", facts.account_ref.strip().lower()).strip("-")
    return f"acct:{slug or 'unknown'}"


def _already_captured(store: EventStore, doc_id: str) -> bool:
    for e in store.events():
        if e.event_type == "DocumentCaptured" and e.body.get("doc_id") == doc_id:
            return True
    return False


def post_statement(store: EventStore, facts: StatementFacts) -> IngestResult:
    """Reconcile a checking statement and, only if it holds, post it. The gate."""
    account = account_id_for(facts)
    recon = check_balance_identity(
        facts.opening_amount, [t.amount for t in facts.transactions],
        facts.closing_amount)

    if not recon.passed:
        return IngestResult(
            doc_id=facts.doc_id, action=CONFLICT, doc_type=facts.doc_type,
            account=account, grade="conflicted", reconciliation=recon,
            message=("Statement did not reconcile, so nothing was posted: "
                     f"{recon.explain()}. Held for review."))

    proj = LedgerProjection(store.events())
    if proj.is_seeded(account):
        prior = proj.running_balance(account)
        if facts.opening_amount != prior:
            return IngestResult(
                doc_id=facts.doc_id, action=GAP, doc_type=facts.doc_type,
                account=account, grade="conflicted", reconciliation=recon,
                message=(f"This statement opens at {facts.opening_amount}, but "
                         f"the last balance I hold is {prior}. Likely a missing "
                         "statement between them — not posted, so I don't invent "
                         "the gap."))
    else:
        # First statement for this account: register it and seed Opening Balance
        # Equity from the attested opening figure.
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
        facts.closing_provenance()))

    return IngestResult(
        doc_id=facts.doc_id, action=POSTED, doc_type=facts.doc_type,
        account=account, grade="corroborated", reconciliation=recon,
        message=(f"Posted and reconciled: balance {facts.closing_amount} as of "
                 f"{facts.closing_date}."))


def capture_and_ingest(raw: RawStore, store: EventStore, data: bytes,
                       read_fn: ReadFn, filename: str = "",
                       captured_at: str = "") -> IngestResult:
    """Raw-capture a file, read it, and either post it or park it — never lose it."""
    doc_id = raw.put(data)                       # (1) capture first, always
    if _already_captured(store, doc_id):
        return IngestResult(doc_id=doc_id, action=DUPLICATE, doc_type="",
                            message="Already ingested (same content); no change.")

    rr = read_fn(data, doc_id)                   # (2) the model read (a proposal)
    store.append(document_captured(              # record that we hold it
        doc_id, filename, len(data), rr.doc_type, rr.doc_type_confidence,
        captured_at, Provenance(doc_id=doc_id)))

    # (3) route by type — v0 projects checking statements, parks the rest.
    if rr.facts is not None and rr.doc_type in CHECKING_DOC_TYPES:
        return post_statement(store, rr.facts)   # (4) the reconciliation gate

    reason = rr.error or f"no projector yet for '{rr.doc_type or 'unknown'}'"
    return IngestResult(
        doc_id=doc_id, action=PARKED, doc_type=rr.doc_type,
        message=(f"Captured and held; not yet readable ({reason}). It will be "
                 "understood when a projector for its type arrives."))
