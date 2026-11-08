"""Accepted investment source boundaries, separate from cash activity coverage."""
from dataclasses import dataclass, replace
from decimal import Decimal
from hashlib import sha256
from datetime import date, timedelta


class SnapshotUnavailable(ValueError):
    """A selected investment source cannot establish a complete holdings set."""


@dataclass(frozen=True)
class SnapshotBoundary:
    account: str
    document: str
    closing_id: str
    sequence: int
    dated: str
    currency: str
    cash: Decimal
    total: Decimal
    grade: str
    read_id: str
    read_digest: str
    expected: tuple
    status: str = "complete"
    intervals: tuple = ()
    expected_count: int = -1
    expected_digest: str = ""

    @property
    def position_count(self):
        return len(self.expected) if self.expected_count < 0 else self.expected_count

    def status_at(self, horizon):
        if self.status not in {"complete", "legacy"}:
            return self.status
        if not self.intervals:
            return self.status if self.status == "complete" else "unavailable"
        matches = [status for left, right, status in self.intervals
                   if left <= horizon <= right]
        status = matches[0] if len(matches) == 1 else "unavailable"
        return "legacy" if self.status == "legacy" and status == "accepted" else status


class AcceptedInvestmentSources:
    """Freeze the successful source present when a native closing is accepted."""
    def __init__(self):
        self.captures = set()
        self.reads = {}

    def observe(self, event):
        body = event.body
        if event.event_type == "DocumentCaptured":
            if body.get("doc_id") == event.provenance.doc_id:
                self.captures.add(body["doc_id"])
        elif (event.event_type == "ReadRecorded"
              and body.get("phase", "extract") == "extract" and body.get("parse_ok")):
            document = body.get("doc_id", "")
            if not document or document != event.provenance.doc_id:
                return
            if "acquisition" in body:
                from ...sample.curation import decode_retained_input
                text = decode_retained_input(body)
            else:
                text = body.get("response_text", "")
            # Legacy extraction receipts did not persist a normalization locale.
            locale, currency = body.get("normalization_locale", "en-US"), body.get("source_currency")
            self.reads[document] = (event.event_id, sha256(text.encode()).hexdigest(),
                                   text, locale, currency,
                                   body.get("normalization_context"), "normalization_context" in body)

    def accepted(self, core, event, sequence):
        if event.event_type != "ClosingBalanceObserved":
            return
        account = event.body["account_id"]
        state = core._acct[account]
        document = event.provenance.doc_id
        source = self.reads.get(document)
        if state.kind != "investment" or document not in self.captures or source is None:
            return
        from ...ingest.brokerage import from_brokerage_json, resolve_sweep_cash, _find_json
        from vivacore.verify.arithmetic import check_brokerage_identity
        read_id, read_digest, text, locale, source_currency, descriptor, has_descriptor = source
        import json
        blob = _find_json(text)
        if blob is None:
            return
        try:
            declared = json.loads(blob)
        except json.JSONDecodeError:
            declared = None
        # A classification receipt does not assert a financial snapshot.
        if isinstance(declared, dict) and not {"cash_raw", "total_raw", "as_of_raw", "positions"}.intersection(declared):
            return
        unsupported = False
        if has_descriptor:
            from ...normalization_context import decode_context
            try:
                context = decode_context(descriptor)
                locale, source_currency = context.parser_locale, context.parser_currency
                unsupported = not source_currency
            except (ValueError, TypeError):
                unsupported = True
        facts, error = (None, "unsupported extraction normalization context") if unsupported else from_brokerage_json(
            text, document, locale, source_currency or state.currency)
        cash = Decimal(event.body["amount"])
        expected, total, status = (), cash, "unavailable"
        if not error and facts is not None:
            facts, _ = resolve_sweep_cash(facts)
            if (facts.as_of == event.occurred_at[:10] and facts.currency == state.currency
                    and facts.cash == cash and check_brokerage_identity(
                        [p.market_value for p in facts.positions], facts.cash, facts.total).passed):
                expected = tuple((p.instrument, p.units, p.market_value, p.cost_basis)
                                 for p in facts.positions)
                total, status = facts.total, "complete"
                if (any(not row[0] for row in expected)
                        or len({row[0] for row in expected}) != len(expected)):
                    status = "unavailable"
        state.investment_snapshots.append(SnapshotBoundary(
            account, document, event.event_id, sequence, event.occurred_at[:10],
            state.currency, cash, total,
            "verified" if event.body.get("confirmed_by") == "human" else "corroborated",
            read_id, read_digest, expected, status))


def _statement_matches(boundary, statement):
    if boundary.status == "legacy":
        # This only gates existing native observations; it supplies no snapshot.
        return (statement.account.value == boundary.account
                and statement.account.document == boundary.document
                and statement.currency.value == boundary.currency)
    if (statement.account.value != boundary.account or statement.account.document != boundary.document
            or statement.currency.value != boundary.currency or statement.end.value != boundary.dated
            or not statement.snapshot_complete or statement.closing_cash.status != "accepted"
            or Decimal(statement.closing_cash.value) != boundary.cash):
        return False
    if any(p.units.status != "accepted" or p.value.status != "accepted"
           or p.identifier.status != "accepted" for p in statement.positions):
        return False
    remaining = list(statement.positions)
    for name, units, value, _basis in boundary.expected:
        matches = [p for p in remaining
                   if name in {p.identifier.value, p.label.value if p.label is not None else ""}
                   and Decimal(p.units.value) == units and Decimal(p.value.value) == value]
        if len(matches) != 1:
            return False
        remaining.remove(matches[0])
    return not remaining


def bind_lifecycle(core, events, resolve_reference=None):
    """Validate once per owned revision; retain no prefix proof or source index."""
    relevant = [event for event in events if event.event_type in
                {"InvestmentActivityStatementObserved", "InvestmentEvidenceChanged"}]
    if not relevant:
        return
    from ...investment.events import source_index
    from ...investment.contracts import EvidenceError
    resolver = resolve_reference
    if resolver is None:
        from ...investment.funding import resolver as make_resolver
        resolver = make_resolver(events)
    try:
        index = source_index(events, resolver)
        documents = {s.account.document for s in index.statements.values()}
        core._measurement_sources.investment_documents = documents
        add_missing_binding_barriers(core, index.statements.values(), events)
        points = ["0001-01-01", *sorted({change.effective for _, change, _ in index.changes}
                                       - {"0001-01-01"})]
        intervals = []
        for offset, left in enumerate(points):
            right = ((date.fromisoformat(points[offset + 1]) - timedelta(days=1)).isoformat()
                     if offset + 1 < len(points) else "9999-12-31")
            intervals.append((left, right, index.select("positions", left)))
        for state in core._acct.values():
            bound = []
            for boundary in state.investment_snapshots:
                if boundary.document not in documents:
                    bound.append(boundary)
                    continue
                statuses = []
                for left, right, selections in intervals:
                    sources = [s for s in selections if s.statement.account.document == boundary.document]
                    matches = [s for s in sources if _statement_matches(boundary, s.statement)]
                    status = (matches[0].status if len(matches) == len(sources) == 1
                              else "retracted" if not sources else "unavailable")
                    statuses.append((left, right, status))
                bound.append(replace(boundary, intervals=tuple(statuses)))
            state.investment_snapshots = bound
    except (EvidenceError, ValueError, TypeError, KeyError, ArithmeticError):
        # Invalid lineage cannot regain authority through the native legacy path.
        core._measurement_sources.investment_lifecycle_invalid = True
        for state in core._acct.values():
            if state.kind == "investment":
                state.investment_lifecycle_invalid = True
            state.investment_snapshots = [replace(b, status="unavailable", intervals=())
                                          for b in state.investment_snapshots]


def selected_boundary(state, as_of="", check=None):
    """Select the newest source, retaining unresolved and explicit-empty states."""
    horizon = (as_of or getattr(state, "investment_horizon", "") or "9999-12-31")[:10]
    if getattr(state, "investment_lifecycle_invalid", False):
        raise SnapshotUnavailable("investment source lifecycle is invalid")
    # Acceptance order is authoritative within a document, even if a correction
    # moves its value date backwards. Only then compare different sources.
    by_document = {}
    for boundary in getattr(state, "investment_snapshots", ()):
        if check is not None:
            check()
        if boundary.dated > horizon:
            continue
        prior = by_document.get(boundary.document)
        if prior is None or boundary.sequence > prior.sequence:
            by_document[boundary.document] = boundary
    candidates = [b for b in by_document.values() if b.status != "legacy"]
    latest = max((b.dated for b in candidates), default="")
    selected_documents = set()
    for history in state.position_history.values():
        for row in history:
            if check is not None:
                check()
            if not row.get("is_cash") and row["as_of"][:10] <= horizon:
                dated = row["as_of"][:10]
                if dated > latest:
                    latest, selected_documents = dated, {row["provenance"].doc_id}
                elif dated == latest:
                    selected_documents.add(row["provenance"].doc_id)
    for guard in by_document.values():
        if (guard.status == "legacy"
                and (guard.dated >= latest or guard.document in selected_documents)
                and guard.status_at(horizon) != "legacy"):
            raise SnapshotUnavailable("legacy investment source lifecycle is unavailable")
    if not candidates:
        return None
    newest = max(b.dated for b in candidates)
    candidates = [b for b in candidates if b.dated == newest]
    if len(candidates) != 1:
        raise SnapshotUnavailable("conflicting investment snapshot sources")
    boundary = candidates[0]
    if boundary.status_at(horizon) not in {"complete", "accepted"}:
        raise SnapshotUnavailable("investment snapshot source is unavailable")
    return boundary


def boundary_positions(state, boundary, check=None):
    """Require exactly the native holdings belonging to this accepted source."""
    if boundary.status == "legacy":
        raise SnapshotUnavailable("legacy source guard supplies no holdings replacement")
    selected = {}
    stop = min((b.sequence for b in getattr(state, "investment_snapshots", ())
                if b.document == boundary.document and b.sequence > boundary.sequence),
               default=float("inf"))
    rows = []
    for name, history in state.position_history.items():
        for row in history:
            if check is not None:
                check()
            if (not row.get("is_cash") and row["provenance"].doc_id == boundary.document
                    and boundary.sequence < row.get("source_sequence", -1) < stop):
                rows.append((name, row))
    if len(rows) != boundary.position_count:
        raise SnapshotUnavailable("accepted investment holdings are incomplete")
    if any(row["as_of"][:10] != boundary.dated or row["currency"] != boundary.currency
           for _name, row in rows):
        raise SnapshotUnavailable("accepted investment holding date/currency mismatch")
    if boundary.expected_digest:
        actual = tuple((name, row["units"], row["market_value"], row["cost_basis"])
                       for name, row in rows)
        if terms_digest(actual) != boundary.expected_digest:
            raise SnapshotUnavailable("accepted investment holdings digest mismatch")
        if len({name for name, _ in rows}) != len(rows):
            raise SnapshotUnavailable("duplicate accepted investment holdings")
        return dict(rows)
    expected = {name: (units, value, basis) for name, units, value, basis in boundary.expected}
    for name, row in rows:
        if (name not in expected or name in selected or row["as_of"][:10] != boundary.dated
                or row["currency"] != boundary.currency
                or (row["units"], row["market_value"], row["cost_basis"]) != expected[name]):
            raise SnapshotUnavailable("accepted investment holdings differ from their source")
        selected[name] = row
    return selected


def terms_digest(terms):
    import json
    rows = sorted((name, str(units), str(value), None if basis is None else str(basis))
                  for name, units, value, basis in terms)
    return sha256(json.dumps(rows, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def add_missing_binding_barriers(core, statements, events):
    """Typed source authority without matching native acceptance is unresolved."""
    records = {event.body.get("observation_id"): (sequence, event.event_id)
               for sequence, event in enumerate(events)
               if event.event_type == "InvestmentActivityStatementObserved"}
    for statement in statements:
        state = core._acct.get(statement.account.value)
        if state is None or (core.as_of and statement.end.value > core.as_of):
            continue
        if any(b.status == "complete" and _statement_matches(b, statement)
               for b in state.investment_snapshots):
            continue
        sequence, event_id = records[statement.observation_id]
        if any(b.closing_id == event_id for b in state.investment_snapshots):
            continue
        cash = (Decimal(statement.closing_cash.value)
                if statement.closing_cash.status == "accepted" else Decimal(0))
        has_read_boundary = any(b.document == statement.account.document and b.status != "legacy"
                                and b.sequence <= sequence for b in state.investment_snapshots)
        status = "unavailable" if has_read_boundary else "legacy"
        state.investment_snapshots.append(SnapshotBoundary(
            statement.account.value, statement.account.document, event_id, sequence,
            statement.end.value, statement.currency.value, cash, cash, "", "", "", (), status))


def select_holdings_boundary(state, as_of="", check=None):
    """A retired row from a bound source cannot re-enter through legacy dates."""
    boundary = selected_boundary(state, as_of, check)
    if boundary is None:
        return None
    horizon = (as_of or getattr(state, "investment_horizon", "") or "9999-12-31")[:10]
    bound_documents = {b.document for b in getattr(state, "investment_snapshots", ())
                       if b.status != "legacy"}
    for history in state.position_history.values():
        for row in history:
            if check is not None:
                check()
            if (not row.get("is_cash") and row["provenance"].doc_id not in bound_documents
                    and boundary.dated < row["as_of"][:10] <= horizon):
                return None
    return boundary
