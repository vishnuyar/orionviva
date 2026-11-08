"""Dated measurements selected by accepted source before measurement time.

This view deliberately never fills a historical point from the composed latest
balance. Investment totals require the accepted statement's complete snapshot.
"""
from dataclasses import dataclass
from decimal import Decimal
from datetime import date

from .positions import _composed_grade


@dataclass(frozen=True)
class Measurement:
    amount: Decimal
    currency: str
    dated: str
    grade: str
    doc_id: str
    component_sources: tuple[str, ...] = ()
    source_sequence: int = 0
    kind: str = ""
    context_conflict: bool = False


class MeasurementSources:
    """Source terms in replay order; metadata edits never relabel old sources."""
    def __init__(self, *, validate_lifecycle=True):
        self.validate_lifecycle = validate_lifecycle
        self.accounts = {}
        self.accepted = {}
        self.investment_documents = set()
        self.investment_lifecycle_invalid = False
        from .investment_snapshots import AcceptedInvestmentSources
        self.snapshots = AcceptedInvestmentSources()

    def observe_source(self, event):
        self.snapshots.observe(event)

    def after_event(self, core, event, sequence):
        self.apply(event)
        self.snapshots.accepted(core, event, sequence)

    def finish(self, core, events):
        if self.validate_lifecycle:
            from .investment_snapshots import bind_lifecycle
            bind_lifecycle(core, events)

    def apply(self, event):
        if event.event_type not in {"AccountOpened", "ClosingBalanceObserved"}:
            return
        body = event.body or {}
        account = body.get("account_id", "")
        doc = event.provenance.doc_id
        if event.event_type == "AccountOpened":
            self.accounts[account] = (body.get("currency", ""), body.get("kind", ""), doc)
        elif event.event_type == "ClosingBalanceObserved" and doc:
            currency, kind, metadata_source = self.accounts.get(account, ("", "", ""))
            prior = self.accepted.get((account, doc))
            # Explicit accepted account terms from this same source may resolve
            # a correction. Unrelated current metadata has no such authority.
            terms = (currency, kind) if prior is None or metadata_source == doc else prior[:2]
            self.accepted[account, doc] = (*terms, terms != (currency, kind))


def accepted_closings(core, account):
    """Last observation per document; corrections may move the value date back."""
    state = core._acct[account]
    selected = {}
    context = getattr(core, "_measurement_sources", None)
    for sequence, (dated, amount, grade, doc) in enumerate(state.closings):
        if not doc or (doc not in core._captured and not any(
                b.document == doc and b.read_id and b.read_digest
                for b in getattr(state, "investment_snapshots", ()))):
            continue
        accepted = core._doc_closing.get(doc)
        if accepted is None:
            continue
        source_terms = context.accepted.get((account, doc)) if context else None
        if not source_terms:
            continue
        currency, kind, conflict = source_terms
        accepted_amount, accepted_date = accepted
        if Decimal(accepted_amount) != amount or accepted_date != dated:
            continue
        try:
            if date.fromisoformat(dated[:10]).isoformat() != dated[:10] or not amount.is_finite() or not currency or kind not in {"depository", "liability", "investment"}:
                continue
        except (ValueError, TypeError):
            continue
        # Traversal is source order, including a grade-only correction.
        selected[doc] = Measurement(amount, currency, dated[:10], grade, doc, (doc,), sequence, kind, conflict)
    return sorted(selected.values(), key=lambda row: (row.dated, row.source_sequence))


def investment_snapshot(core, account, closing, locale='en-US'):
    """Match normalized statement components to accepted observations, never dates alone."""
    from .investment_snapshots import boundary_positions, SnapshotUnavailable
    state = core._acct[account]
    matches = [b for b in state.investment_snapshots if b.document == closing.doc_id
               and b.dated == closing.dated and b.cash == closing.amount]
    if not matches:
        return None
    boundary = max(matches, key=lambda b: b.sequence)
    if boundary.status_at(core.as_of or "9999-12-31") not in {"complete", "accepted"}:
        return None
    try:
        observed = boundary_positions(state, boundary)
    except SnapshotUnavailable:
        return None
    grade = _composed_grade([closing.grade, *(p["grade"] for p in observed.values())])
    return Measurement(boundary.total, closing.currency, closing.dated, grade,
                       closing.doc_id, (closing.doc_id,), closing.source_sequence,
                       closing.kind, closing.context_conflict)


def measurements(core, account, *, cash=False, locale='en-US'):
    rows = accepted_closings(core, account)
    if cash:
        return rows, ()
    complete, incomplete = [], []
    for row in rows:
        snapshot = investment_snapshot(core, account, row, locale) if row.kind == 'investment' and not row.context_conflict else row
        (complete if snapshot else incomplete).append(snapshot or row)
    return complete, tuple(incomplete)
