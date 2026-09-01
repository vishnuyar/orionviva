"""Typed, bounded source registry for Financial Query IR."""

from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
import datetime


@dataclass(frozen=True)
class QuerySource:
    name: str
    fields: dict[str, str]
    read: object
    max_rows: int
    stable_key: str = ""
    date_fields: tuple[str, ...] = ()
    evidence_fields: tuple[str, ...] = ()
    quantities: tuple[tuple[str, str], ...] = ()
    currency_fields: tuple[tuple[str, str], ...] = ()
    whole: bool = False


class QuerySourceRegistry:
    def __init__(self):
        self._sources = {}
        self._domains = {}

    def register(self, source: QuerySource):
        if source.name in self._sources:
            raise ValueError(f"query source {source.name!r} is already registered")
        if source.max_rows <= 0:
            raise ValueError("a query source needs a positive row bound")
        for field in ((source.stable_key,) if source.stable_key else ()) + \
                source.date_fields + source.evidence_fields:
            if field not in source.fields:
                raise ValueError(f"query source {source.name!r} metadata names "
                                 f"unknown field {field!r}")
        for value_field, quantity in source.quantities:
            if value_field not in source.fields or not quantity:
                raise ValueError(f"query source {source.name!r} has an invalid "
                                 "quantity declaration")
        for value_field, currency_field in source.currency_fields:
            if (source.fields.get(value_field) != "Money"
                    or currency_field not in source.fields):
                raise ValueError(f"query source {source.name!r} has an invalid "
                                 "money/currency declaration")
        self._sources[source.name] = source

    def get(self, name):
        return self._sources.get(name)

    def register_domain(self, name, fn):
        if name in self._domains:
            raise ValueError(f"domain operator {name!r} is already registered")
        self._domains[name] = fn

    def domain(self, name):
        return self._domains.get(name)

    def domain_names(self):
        return tuple(self._domains)

    def manifest(self):
        return [{"name": source.name, "fields": dict(source.fields),
                 "max_rows": source.max_rows,
                 "stable_key": source.stable_key,
                 "date_fields": list(source.date_fields),
                 "evidence_fields": list(source.evidence_fields),
                 "quantities": dict(source.quantities),
                 "currency_fields": dict(source.currency_fields),
                 "whole": source.whole}
                for source in self._sources.values()]


def _plain(item):
    if hasattr(item, "to_dict"):
        return item.to_dict()
    if is_dataclass(item):
        return asdict(item)
    return dict(item)


def default_sources(projection, today: str = "") -> QuerySourceRegistry:
    """Initial typed views over existing projection authorities."""
    registry = QuerySourceRegistry()
    registry.register(QuerySource(
        "accounts", {"account": "EntityRef(account)", "kind": "Enum",
                     "currency": "Enum", "name": "String",
                     "opened_at": "Date"},
        lambda: [_plain(item) for item in projection.account_infos()], 1000,
        stable_key="account", date_fields=("opened_at",)))
    def movement_rows():
        from ..tools.envelope import bounded
        rows = []
        grades = projection.movement_grades()
        for movement in projection.movements():
            row = _plain(movement)
            row["grade"] = grades.get(movement.key, "")
            row["merchant"] = projection.merchant_key_of(movement)
            category = projection.category_of(row["merchant"]) or {}
            row["category"] = str(category.get("category") or "")
            row["subcategory"] = str(category.get("subcategory") or "")
            row["tags"] = list(projection.movement_tags_of(movement))
            row["quantity"] = "movement"
            row["boundary"] = bounded(
                whole=False,
                cut=[{"kind": "account", "value": movement.account},
                     {"kind": "merchant", "value": row["merchant"]}])
            rows.append(row)
        return rows

    registry.register(QuerySource(
        "movements", {"key": "RecordRef", "account": "EntityRef(account)",
                      "date": "Date", "amount": "Money", "currency": "Enum",
                      "description": "String", "nature": "Enum",
                      "provisional": "Boolean", "linked": "Boolean",
                      "merchant": "EntityRef(merchant)",
                      "category": "EntityRef(category)",
                      "subcategory": "EntityRef(category)", "tags": "EnumList",
                      "grade": "EvidenceGrade", "quantity": "Enum",
                      "boundary": "Boundary", "provenance": "RecordRef"},
        movement_rows, 100_000,
        stable_key="key", date_fields=("date",),
        evidence_fields=("key", "grade", "provenance"),
        quantities=(("amount", "movement"),),
        currency_fields=(("amount", "currency"),)))

    def supported_spending_rows():
        rows = {row["key"]: row for row in movement_rows()}
        out = []
        for movement in projection.movements():
            if not projection._counts_as_spending(movement):
                continue
            row = dict(rows[movement.key])
            row["amount"] = str(abs(movement.amount))
            row["period"] = str(row.get("date") or "")[:7]
            boundary = dict(row["boundary"])
            cuts = list(boundary.get("cut") or ())
            if row.get("category"):
                cuts.append({"kind": "category", "value": row["category"]})
            boundary["cut"] = cuts
            row["boundary"] = boundary
            out.append(row)
        return out

    registry.register(QuerySource(
        "supported_spending_movements",
        {"key": "RecordRef", "account": "EntityRef(account)",
         "date": "Date", "period": "String", "amount": "Money", "currency": "Enum",
         "description": "String", "nature": "Enum",
         "provisional": "Boolean", "linked": "Boolean",
         "merchant": "EntityRef(merchant)",
         "category": "EntityRef(category)",
         "subcategory": "EntityRef(category)", "tags": "EnumList",
         "grade": "EvidenceGrade", "quantity": "Enum",
         "boundary": "Boundary", "provenance": "RecordRef"},
        supported_spending_rows, 100_000, stable_key="key", date_fields=("date",),
        evidence_fields=("key", "grade", "provenance"),
        quantities=(("amount", "spending"),),
        currency_fields=(("amount", "currency"),)))

    def balance_rows():
        from ..tools.envelope import bounded
        rows = []
        for info in projection.account_infos():
            if info.kind not in ("depository", "liability", "investment"):
                continue
            account = info.account
            for value in projection.composed_values(account):
                rows.append({"key": f"{account}|{value.currency}|{value.as_of}",
                             "account": account, "amount": str(value.amount),
                             "kind": info.kind,
                             "side": ("owed" if info.kind == "liability"
                                      else "held"),
                             "currency": value.currency, "as_of": value.as_of,
                             "dates": list(value.dates), "grade": value.grade,
                             "provenance": value.proves,
                             "boundary": bounded(
                                 whole=False, cut=[{
                                     "kind": "account", "value": account}])})
        return rows

    registry.register(QuerySource(
        "dated_balances", {"key": "RecordRef", "account": "EntityRef(account)",
                           "amount": "Money", "kind": "Enum", "side": "Enum",
                           "currency": "Enum", "as_of": "Date",
                           "dates": "DateList", "grade": "EvidenceGrade",
                           "provenance": "RecordRef"},
        balance_rows, 10_000, stable_key="key", date_fields=("as_of",),
        evidence_fields=("grade", "provenance")))
    balance_fields = {"key": "RecordRef", "account": "EntityRef(account)",
                      "amount": "Money", "kind": "Enum", "side": "Enum",
                      "currency": "Enum", "as_of": "Date",
                      "dates": "DateList", "grade": "EvidenceGrade",
                      "provenance": "RecordRef", "boundary": "Boundary"}
    for source_name, side, quantity in (
            ("held_balances", "held", "balance"),
            ("owed_balances", "owed", "owed")):
        registry.register(QuerySource(
            source_name, balance_fields,
            lambda wanted=side: [row for row in balance_rows()
                                 if row["side"] == wanted],
            10_000, stable_key="key", date_fields=("as_of",),
            evidence_fields=("grade", "provenance"),
            quantities=(("amount", quantity),),
            currency_fields=(("amount", "currency"),), whole=False))

    def position_rows():
        from ..tools.envelope import bounded
        rows = []
        for item in projection.positions():
            row = _plain(item)
            row["key"] = f"{row['account']}|{row['instrument']}|{row['as_of']}"
            row["boundary"] = bounded(
                whole=False, cut=[{"kind": "account",
                                   "value": row["account"]}])
            rows.append(row)
        return rows

    registry.register(QuerySource(
        "positions", {"key": "RecordRef", "account": "EntityRef(account)",
                      "instrument": "String",
                      "market_value": "Money", "currency": "Enum",
                      "as_of": "Date", "grade": "EvidenceGrade",
                      "provenance": "RecordRef", "boundary": "Boundary"},
        position_rows, 10_000, stable_key="key",
        date_fields=("as_of",), evidence_fields=("grade", "provenance"),
        quantities=(("market_value", "balance"),),
        currency_fields=(("market_value", "currency"),), whole=False))
    registry.register(QuerySource(
        "documents", {"document": "RecordRef", "doc_type": "Enum"},
        lambda: [{"document": key, "doc_type": value}
                 for key, value in projection.captured_docs().items()], 10_000,
        stable_key="document", evidence_fields=("document",)))
    registry.register(QuerySource(
        "agent_activity", {"id": "RecordRef", "phase": "Enum",
                           "occurred_at": "Date", "model": "String",
                           "resolved_model": "String", "calls": "Count"},
        lambda: [{**dict(item), "id": str(item.get("id") or
                                           f"agent:{index}")}
                 for index, item in enumerate(projection.agent_log())], 100_000,
        stable_key="id", date_fields=("occurred_at",)))

    registry.register(QuerySource(
        "entity_rulings", {"key": "RecordRef", "scope": "Enum",
                           "subject": "String", "value": "String",
                           "grade": "EvidenceGrade", "occurred_at": "Date"},
        lambda: [{**dict(item), "key":
                  f"{item.get('scope', '')}|{item.get('subject', '')}"}
                 for item in projection.rulings()], 100_000,
        stable_key="key", date_fields=("occurred_at",),
        evidence_fields=("grade",)))

    registry.register(QuerySource(
        "merchant_categories", {"merchant": "EntityRef(merchant)",
                                "category": "EntityRef(category)",
                                "subcategory": "EntityRef(category)",
                                "grade": "EvidenceGrade"},
        lambda: [{"merchant": merchant, **dict(value)}
                 for merchant, value in sorted(
                     projection.merchant_categories().items())], 100_000,
        stable_key="merchant", evidence_fields=("grade",)))

    registry.register(QuerySource(
        "transfer_links", {"key": "RecordRef", "movement_a": "RecordRef",
                           "movement_b": "RecordRef", "grade": "EvidenceGrade",
                           "occurred_at": "Date"},
        lambda: [{"key": f"{item.get('a', '')}|{item.get('b', '')}",
                  "movement_a": item.get("a", ""),
                  "movement_b": item.get("b", ""), **dict(item)}
                 for item in projection.transfer_links()], 100_000,
        stable_key="key", date_fields=("occurred_at",),
        evidence_fields=("grade", "movement_a", "movement_b")))

    def coverage_rows():
        rows = []
        for account in projection.accounts():
            for index, run in enumerate(projection.attested_runs(account)):
                if isinstance(run, (tuple, list)) and len(run) == 2:
                    values = {"from": str(run[0]), "to": str(run[1]),
                              "provenance": ""}
                else:
                    values = _plain(run)
                rows.append({"key": f"{account}|{index}|{values}",
                             "account": account, **values})
        return rows

    registry.register(QuerySource(
        "statement_coverage", {"key": "RecordRef",
                               "account": "EntityRef(account)",
                               "from": "Date", "to": "Date",
                               "provenance": "RecordRef"},
        coverage_rows, 100_000, stable_key="key", date_fields=("from", "to"),
        evidence_fields=("provenance",)))

    def rhythm_rows():
        from ..tools.envelope import bounded
        return [{"key": item.subject, **_plain(item),
                 "boundary": bounded(whole=False, cut=[{
                     "kind": "merchant", "value": item.subject}])}
                for item in projection.rhythm_hypotheses()]

    registry.register(QuerySource(
        "recurring_rhythms", {"key": "RecordRef",
                              "merchant": "EntityRef(merchant)",
                              "direction": "Enum", "count": "Count",
                              "amount": "Money", "currency": "Enum",
                              "cadence": "Enum", "interval_days": "Count",
                              "measured": "Boolean", "steady": "Boolean",
                              "movements": "RecordRefList",
                              "boundary": "Boundary"},
        rhythm_rows, 100_000, stable_key="key", evidence_fields=("movements",)))
    registry.register(QuerySource(
        "recurring_spending_rhythms", {
            "key": "RecordRef", "merchant": "EntityRef(merchant)",
            "direction": "Enum", "count": "Count", "amount": "Money",
            "currency": "Enum", "cadence": "Enum", "interval_days": "Count",
            "measured": "Boolean", "steady": "Boolean",
            "movements": "RecordRefList", "boundary": "Boundary"},
        lambda: [row for row in rhythm_rows()
                 if str(row.get("direction") or "").casefold() in {
                     "out", "outflow", "spending"}],
        100_000, stable_key="key", evidence_fields=("movements",),
        quantities=(("amount", "spending"), ("count", "count")),
        currency_fields=(("amount", "currency"),), whole=False))

    read_day = today or datetime.date.today().isoformat()
    registry.register(QuerySource(
        "obligations", {"id": "RecordRef", "subject": "EntityRef(merchant)",
                        "cadence": "Enum", "expected_date": "Date",
                        "amount_min": "Money", "amount_max": "Money",
                        "currency": "Enum", "grade": "EvidenceGrade",
                        "record_ids": "RecordRefList"},
        lambda: [_plain(item) for item in projection.obligations(read_day)], 100_000,
        stable_key="id", date_fields=("expected_date",),
        evidence_fields=("grade", "record_ids")))
    # Named financial meanings call the existing projection/tool authorities;
    # the generic query engine never redefines spending, income or net worth.
    from ..tools import ledger_tools

    def authority_rows(metric, quantities=()):
        def read():
            args = {"entity": "aggregate", "metric": metric}
            if metric == "net_worth" and read_day:
                args["as_of"] = read_day
            result = ledger_tools.query_ledger(projection, args)
            if not result.ok:
                return []
            figures = [item for item in result.figures
                       if not quantities or item.get("quantity") in quantities]
            def period_of(item):
                return next((str(part.get("value") or "")[:7]
                             for part in (item.get("boundary") or {}).get(
                                 "selected", ()) if part.get("kind") == "period"), "")
            return [{"key": f"{metric}|{index}|{item.get('quantity', '')}",
                     "value": str(item.get("value") or ""),
                     "period": period_of(item),
                     "currency": str(item.get("currency") or ""),
                     "quantity": str(item.get("quantity") or ""),
                     "what": str(item.get("what") or ""),
                     "dated": str(item.get("dated") or ""),
                     "grade": str(item.get("grade") or ""),
                     "record_ids": list(item.get("record_ids") or ()),
                     "boundary": dict(item.get("boundary") or {})}
                    for index, item in enumerate(figures)]
        return read

    authority_fields = {"key": "RecordRef", "value": "Money",
                        "period": "String",
                        "currency": "Enum", "quantity": "Enum",
                        "what": "String", "dated": "Date",
                        "grade": "EvidenceGrade", "record_ids": "RecordRefList",
                        "boundary": "Boundary"}
    registry.register(QuerySource(
        "income_attribution", authority_fields,
        authority_rows("income", ("income",)), 1000,
        stable_key="key", date_fields=("dated",),
        evidence_fields=("grade", "record_ids"),
        quantities=(("value", "income"),),
        currency_fields=(("value", "currency"),), whole=True))
    registry.register(QuerySource(
        "net_worth_points", authority_fields,
        authority_rows("net_worth", ("net_worth",)), 1000,
        stable_key="key", date_fields=("dated",),
        evidence_fields=("grade", "record_ids"),
        quantities=(("value", "net_worth"),),
        currency_fields=(("value", "currency"),), whole=True))

    def aggregate(metric, *, quantities=()):
        def read(filters):
            result = ledger_tools.query_ledger(
                projection, {"entity": "aggregate", "metric": metric,
                             "filters": dict(filters)})
            if quantities and result.ok:
                result.figures = [item for item in result.figures
                                  if item.get("quantity") in quantities]
            return result
        return read

    for name, metric, quantities in (
        ("spending", "spending", ("spending",)),
        ("attributed_income", "income", ("income",)),
        ("unexplained_inflows", "income", ("gross_flow",)),
        ("surplus", "surplus", ("net_movement",)),
        ("net_worth", "net_worth", ("net_worth",)),
        ("recurring_spending", "recurring_spending", ("spending", "count")),
        ("evidence_staleness", "stalest_balance", ("balance", "owed", "count", "time")),
    ):
        registry.register_domain(name, aggregate(metric, quantities=quantities))

    def balances(quantities):
        def read(filters):
            args = {"entity": "balances"}
            if filters:
                args["filters"] = dict(filters)
            result = ledger_tools.query_ledger(projection, args)
            if result.ok:
                result.figures = [item for item in result.figures
                                  if item.get("quantity") in quantities]
            return result
        return read

    registry.register_domain("held_balance", balances(("balance",)))
    registry.register_domain("amount_owed", balances(("owed",)))
    registry.register_domain(
        "statement_completeness",
        lambda filters: ledger_tools.check_completeness(projection, {}))
    registry.register_domain(
        "transfer_excluded_flow",
        lambda filters: ledger_tools.get_transparency(projection, {}))
    return registry
