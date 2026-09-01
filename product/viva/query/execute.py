"""Deterministic Financial Query operators with evidence propagation."""

from __future__ import annotations

from dataclasses import dataclass
import calendar
import datetime
from decimal import Decimal, InvalidOperation

from ..tools.envelope import ToolResult, bounded, figure, weakest
from .schema import DOMAIN_OPERATORS, FinancialQuery


class QueryError(ValueError):
    pass


@dataclass(frozen=True)
class QueryRow:
    values: dict
    record_ids: tuple[str, ...] = ()
    grade: str = ""
    coverage: tuple[tuple[str, str], ...] = ()
    hypothetical: bool = False


@dataclass(frozen=True)
class QueryTable:
    rows: tuple[QueryRow, ...]
    fields: dict[str, str]
    group_keys: tuple[str, ...] = ()
    quantities: dict[str, str] = None
    currency_fields: dict[str, str] = None
    boundary_fields: dict[str, str] = None

    def __post_init__(self):
        object.__setattr__(self, "quantities", dict(self.quantities or {}))
        object.__setattr__(self, "currency_fields",
                           dict(self.currency_fields or {}))
        object.__setattr__(self, "boundary_fields",
                           dict(self.boundary_fields or {}))


def _decimal(value):
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise QueryError(f"{value!r} is not an exact decimal") from None


def _records(row):
    # Provenance enters through a source's declared evidence fields.  Values
    # such as a stable row key remain query data and can never become evidence
    # later merely because they happen to be named ``id`` or ``document``.
    return row.record_ids


def _evidence_ids(item, source):
    found = []
    for field in source.evidence_fields:
        if not str(source.fields.get(field, "")).startswith("RecordRef"):
            continue
        value = item.get(field)
        if isinstance(value, dict):
            value = value.get("document_id") or value.get("doc_id") or ""
        values = value if isinstance(value, (list, tuple, set)) else (value,)
        for one in values:
            if one and str(one) not in found:
                found.append(str(one))
    return tuple(found)


def _carried(table, rows, fields=None, group_keys=None, *, quantities=None,
             currency_fields=None, boundary_fields=None):
    return QueryTable(
        tuple(rows), dict(fields if fields is not None else table.fields),
        table.group_keys if group_keys is None else tuple(group_keys),
        dict(table.quantities if quantities is None else quantities),
        dict(table.currency_fields if currency_fields is None
             else currency_fields),
        dict(table.boundary_fields if boundary_fields is None
             else boundary_fields))


def _boundary(row, table, field):
    name = table.boundary_fields.get(field, "")
    value = row.values.get(name) if name else None
    return value if isinstance(value, dict) else None


def _same_boundary(left, right) -> bool:
    def normalized(value):
        out = dict(value)
        for name in ("selected", "cut", "unmeasured"):
            out[name] = sorted((dict(item) for item in out.get(name) or ()),
                               key=lambda item: tuple(sorted(item.items())))
        return out
    return normalized(left) == normalized(right)


def _ratio_boundary(numerator, denominator):
    """Boundary for a numerator slice divided by its containing population."""
    def axes(boundary, name):
        return {str(item.get("kind") or ""): (
                    str(item.get("value") or ""), str(item.get("to") or ""))
                for item in boundary.get(name) or ()}
    numerator_selected = axes(numerator, "selected")
    denominator_selected = axes(denominator, "selected")
    numerator_cut = axes(numerator, "cut")
    denominator_cut = axes(denominator, "cut")
    if bool(numerator.get("accounts")) != bool(denominator.get("accounts")):
        return None
    if not (all(numerator_selected.get(key) == value
                for key, value in denominator_selected.items())
            and all(numerator_cut.get(key) == value
                    for key, value in denominator_cut.items())
            and (not numerator.get("whole", False)
                 or denominator.get("whole", False))):
        return None
    out = dict(numerator)
    gaps = []
    for boundary in (numerator, denominator):
        for item in boundary.get("unmeasured") or ():
            held = dict(item)
            if held not in gaps:
                gaps.append(held)
    if gaps:
        out["unmeasured"] = gaps
    unposted = max(int(numerator.get("unposted", 0)),
                   int(denominator.get("unposted", 0)))
    if unposted:
        out["unposted"] = unposted
    accounts = [boundary.get("accounts") for boundary in
                (numerator, denominator) if boundary.get("accounts")]
    if accounts:
        out["accounts"] = {
            "counted": min(int(item.get("counted", 0)) for item in accounts),
            "held": max(int(item.get("held", 0)) for item in accounts)}
    return out


def _common_boundary(boundaries):
    """Conservative boundary shared by every row entering an aggregate."""
    if not boundaries:
        return {"whole": False}
    if all(_same_boundary(item, boundaries[0]) for item in boundaries):
        return dict(boundaries[0])
    out = {"whole": False}
    for name in ("selected", "cut"):
        common = {(str(item.get("kind") or ""), str(item.get("value") or ""),
                   str(item.get("to") or ""))
                  for item in boundaries[0].get(name) or ()}
        for boundary in boundaries[1:]:
            common &= {(str(item.get("kind") or ""),
                        str(item.get("value") or ""),
                        str(item.get("to") or ""))
                       for item in boundary.get(name) or ()}
        if common:
            out[name] = [{"kind": kind, "value": value,
                          **({"to": to} if to else {})}
                         for kind, value, to in sorted(common)]
    gaps = []
    for boundary in boundaries:
        for item in boundary.get("unmeasured") or ():
            held = dict(item)
            if held not in gaps:
                gaps.append(held)
    if gaps:
        out["unmeasured"] = gaps
    unposted = max(int(item.get("unposted", 0)) for item in boundaries)
    if unposted:
        out["unposted"] = unposted
    return out


def _narrowed(table, rows, selection=None):
    """Mark every carried financial boundary as a subset boundary."""
    adjusted = []
    for row in rows:
        values = dict(row.values)
        for name in set(table.boundary_fields.values()):
            held = values.get(name)
            if not isinstance(held, dict):
                continue
            boundary = dict(held)
            boundary["whole"] = False
            if selection:
                for key in ("selected", "cut"):
                    prior = [dict(item) for item in boundary.get(key) or ()
                             if item.get("kind") != selection["kind"]]
                    boundary[key] = [*prior, dict(selection)]
            values[name] = boundary
        adjusted.append(QueryRow(values, row.record_ids, row.grade,
                                 row.coverage, row.hypothetical))
    return _carried(table, adjusted)


class FinancialQueryExecutor:
    def __init__(self, sources, *, max_output_rows=500):
        self.sources = sources
        self.max_output_rows = max_output_rows

    def execute(self, raw_query, _graph=None) -> ToolResult:
        try:
            query = (raw_query if isinstance(raw_query, FinancialQuery)
                     else FinancialQuery.from_dict(raw_query))
            tables = {}
            for step in query.steps:
                inputs = [tables[item] for item in step.inputs]
                tables[step.id] = self._apply(step.op, inputs, step.args)
            return self._emit(tables[query.output], query.emit)
        except (QueryError, ValueError) as error:
            return ToolResult(tool="financial_query", ok=False,
                              refusal="invalid_financial_query", text=str(error))

    def _apply(self, op, inputs, args):
        if op == "scan":
            return self._scan(args)
        if op in DOMAIN_OPERATORS:
            return self._domain(op, args)
        if op == "filter":
            return self._filter(inputs[0], args)
        if op == "select":
            fields = list(args.get("fields") or [])
            self._known(inputs[0], fields)
            return _carried(inputs[0], (QueryRow({
                                             **{key: row.values.get(key)
                                                for key in fields},
                                             **({"boundary": row.values["boundary"]}
                                                if "boundary" in row.values else {}),
                                             **({"quantity": row.values["quantity"]}
                                                if "quantity" in row.values else {})},
                                             _records(row), row.grade, row.coverage,
                                             row.hypothetical)
                                    for row in inputs[0].rows),
                            {key: inputs[0].fields[key] for key in fields},
                            tuple(key for key in inputs[0].group_keys
                                  if key in fields),
                            quantities={key: value for key, value in
                                        inputs[0].quantities.items()
                                        if key in fields},
                            currency_fields={key: value for key, value in
                                             inputs[0].currency_fields.items()
                                             if key in fields and value in fields},
                            boundary_fields={key: value for key, value in
                                             inputs[0].boundary_fields.items()
                                             if key in fields})
        if op == "resolve":
            return self._resolve(inputs[0], args)
        if op == "group":
            keys = list(args["keys"])
            self._known(inputs[0], keys)
            return _carried(inputs[0], inputs[0].rows, group_keys=tuple(keys))
        if op == "aggregate":
            return self._aggregate(inputs[0], args)
        if op == "sort":
            return self._sort(inputs[0], args)
        if op == "limit":
            count = int(args.get("count", 0))
            if count <= 0 or count > self.max_output_rows:
                raise QueryError("limit is outside the admitted row bound")
            return _narrowed(inputs[0], inputs[0].rows[:count])
        if op == "rank":
            table = self._sort(inputs[0], args)
            field = str(args.get("field") or "rank")
            rows = tuple(QueryRow({**row.values, field: index}, _records(row),
                                  row.grade, row.coverage, row.hypothetical)
                         for index, row in enumerate(table.rows, 1))
            return _carried(table, rows, {**table.fields, field: "Count"})
        if op in ("top", "bottom"):
            table = self._sort(inputs[0], {
                "keys": args["keys"],
                "direction": "desc" if op == "top" else "asc"})
            return _narrowed(table, table.rows[:int(args["count"])])
        if op == "calendar_window":
            return self._calendar(inputs[0], args)
        if op == "rolling_window":
            return self._rolling(inputs[0], args)
        if op == "join":
            return self._join(inputs, args)
        if op in ("union_compatible", "difference", "intersection"):
            return self._set(op, inputs, args)
        if op in ("delta", "percentage_change", "ratio"):
            return self._arithmetic(op, inputs[0], args)
        if op == "compute":
            return self._compute(inputs[0], args)
        if op == "require_coverage":
            return self._require_coverage(inputs[0], args)
        if op == "require_grade":
            return self._require_grade(inputs[0], args)
        raise QueryError(f"operator {op!r} has no implementation")

    def _scan(self, args):
        name = str(args.get("source") or "")
        source = self.sources.get(name)
        if source is None:
            raise QueryError(f"unknown financial query source {name!r}")
        raw = list(source.read())
        if len(raw) > source.max_rows:
            raise QueryError(f"source {name!r} exceeded its row bound")
        rows = tuple(QueryRow(
            {**dict(item), **({} if "boundary" in item else {
                "boundary": {"whole": source.whole}})},
            (tuple(map(str, item.get("record_ids") or ()))
             or _evidence_ids(item, source)),
            str(item.get("grade") or "") if isinstance(item, dict) else "",
            tuple(tuple(span) for span in item.get("coverage", ()))
            if isinstance(item, dict) else (),
            bool(item.get("hypothetical", False)) if isinstance(item, dict) else False)
                     for item in raw)
        return QueryTable(rows, dict(source.fields), (),
                          dict(source.quantities), dict(source.currency_fields),
                          {field: "boundary" for field, _quantity
                           in source.quantities})

    def _domain(self, name, args):
        domain = self.sources.domain(name)
        if domain is None:
            raise QueryError(f"domain operator {name!r} is not installed")
        result = domain(dict(args.get("filters") or {}))
        if not result.ok:
            raise QueryError(result.refusal or result.text or "domain read refused")
        rows = []
        for item in result.figures:
            boundary = item.get("boundary") or {}
            coverage = tuple(
                (str(span.get("from") or ""), str(span.get("to") or ""))
                for span in result.covers if isinstance(span, dict))
            rows.append(QueryRow({
                "value": str(item.get("value") or ""),
                "currency": str(item.get("currency") or ""),
                "what": str(item.get("what") or ""),
                "quantity": str(item.get("quantity") or ""),
                "dated": str(item.get("dated") or ""),
                "boundary": boundary,
            }, tuple(map(str, item.get("record_ids") or ())),
                str(item.get("grade") or ""), coverage,
                item.get("kind") == "hypothetical"))
        return QueryTable(tuple(rows), {
            "value": "EvidenceMagnitude", "currency": "Enum", "what": "String",
            "quantity": "Enum", "dated": "Date", "boundary": "Boundary"},
            currency_fields={"value": "currency"},
            boundary_fields={"value": "boundary"})

    def _resolve(self, table, args):
        field = str(args["field"])
        self._known(table, [field])
        phrase = " ".join(str(args["phrase"]).casefold().split())
        matches = [row for row in table.rows
                   if " ".join(str(row.values.get(field) or "").casefold().split())
                   == phrase]
        if len(matches) != 1:
            raise QueryError("entity phrase did not resolve uniquely")
        return _narrowed(table, matches, self._selection(table, field, phrase))

    @staticmethod
    def _selection(table, field, value):
        kind = table.fields.get(field, "")
        if kind.startswith("EntityRef(") and kind.endswith(")"):
            kind = kind[len("EntityRef("):-1]
        elif field.casefold() in {
                "account", "category", "merchant", "subcategory", "tag",
                "currency", "kind"}:
            kind = field.casefold()
        else:
            return None
        if kind not in {"account", "category", "merchant", "subcategory",
                        "tag", "currency", "kind"}:
            return None
        return {"kind": kind, "value": str(value)}

    @staticmethod
    def _known(table, fields):
        unknown = [field for field in fields if field not in table.fields]
        if unknown:
            raise QueryError("unknown fields: " + ", ".join(unknown))

    def _filter(self, table, args):
        predicate = args.get("predicate")
        if not isinstance(predicate, dict):
            raise QueryError("filter needs one structured predicate")
        field = str(predicate.get("field") or "")
        self._known(table, [field])
        operator = predicate.get("op")
        wanted = predicate.get("value")

        def keep(row):
            held = row.values.get(field)
            if operator == "eq": return held == wanted
            if operator == "neq": return held != wanted
            if operator == "in": return held in (wanted if isinstance(wanted, list) else [])
            if operator in ("lt", "lte", "gt", "gte"):
                left, right = _decimal(held), _decimal(wanted)
                return {"lt": left < right, "lte": left <= right,
                        "gt": left > right, "gte": left >= right}[operator]
            raise QueryError(f"predicate operator {operator!r} is not admitted")
        selected = (self._selection(table, field, wanted)
                    if operator == "eq" else None)
        return _narrowed(table, (row for row in table.rows if keep(row)),
                         selected)

    def _aggregate(self, table, args):
        function = str(args.get("function") or "")
        field = str(args.get("field") or "")
        output = str(args.get("output") or function)
        groups = list(args.get("group_by") or table.group_keys)
        currency_field = str(args.get("currency_field") or "")
        self._known(table, groups + ([] if function == "count" else [field]))
        field_kind = table.fields.get(field, "")
        if function != "count" and field_kind not in {
                "Money", "Decimal", "Count", "Rate"}:
            raise QueryError("aggregate needs a statically typed numeric field")
        if function != "count" and field_kind == "Money":
            expected_currency = table.currency_fields.get(field, "")
            if not currency_field or currency_field != expected_currency:
                raise QueryError("a money aggregate must name its trusted currency field")
        if currency_field:
            self._known(table, [currency_field])
        buckets = {}
        for row in table.rows:
            key = tuple(row.values.get(name) for name in groups)
            buckets.setdefault(key, []).append(row)
        rows = []
        for key, held in sorted(buckets.items(), key=lambda item: str(item[0])):
            values = [row.values.get(field) for row in held]
            currencies = {str(row.values.get(currency_field) or "") for row in held}
            if currency_field and len(currencies) > 1:
                raise QueryError("a money aggregate cannot combine currencies")
            if function == "count": result = Decimal(len(held))
            elif function == "sum": result = sum((_decimal(item) for item in values), Decimal(0))
            elif function == "min": result = min(_decimal(item) for item in values)
            elif function == "max": result = max(_decimal(item) for item in values)
            elif function == "average":
                result = sum((_decimal(item) for item in values), Decimal(0)) / Decimal(len(values))
            else: raise QueryError(f"aggregate {function!r} is not admitted")
            row_values = {name: value for name, value in zip(groups, key)}
            if currency_field and currency_field not in row_values:
                row_values[currency_field] = next(iter(currencies), "")
            row_values[output] = str(result)
            boundary_field = (table.boundary_fields.get(field, "")
                              or next(iter(table.boundary_fields.values()), ""))
            boundaries = [row.values.get(boundary_field) for row in held]
            boundaries = [dict(item) for item in boundaries
                          if isinstance(item, dict)]
            boundary = _common_boundary(boundaries)
            if groups:
                boundary["whole"] = False
                cuts = [dict(item) for item in boundary.get("cut") or ()
                        if item.get("kind") not in {
                            "account", "merchant", "category", "currency"}]
                for name, value in zip(groups, key):
                    kind = table.fields.get(name, "")
                    if kind.startswith("EntityRef("):
                        cut_kind = kind[len("EntityRef("):-1]
                    elif "currency" in name.casefold():
                        cut_kind = "currency"
                    else:
                        continue
                    cuts.append({"kind": cut_kind, "value": str(value)})
                boundary["cut"] = cuts
            row_values["boundary"] = boundary
            records = tuple(sorted({record for row in held for record in _records(row)}))
            coverage_sets = [set(row.coverage) for row in held if row.coverage]
            coverage = tuple(sorted(set.intersection(*coverage_sets))) if coverage_sets else ()
            rows.append(QueryRow(row_values, records,
                                 weakest(row.grade for row in held), coverage,
                                 any(row.hypothetical for row in held)))
        kind = "Count" if function == "count" else field_kind or "Decimal"
        fields = {name: table.fields[name] for name in groups}
        if currency_field:
            fields[currency_field] = table.fields[currency_field]
        fields[output] = kind
        quantities = {}
        if function == "count":
            quantities[output] = "count"
        elif field in table.quantities:
            quantities[output] = table.quantities[field]
        currency_fields = ({output: currency_field}
                           if kind == "Money" and currency_field else {})
        return QueryTable(tuple(rows), fields, (), quantities, currency_fields,
                          {output: "boundary"})

    def _sort(self, table, args):
        keys = list(args.get("keys") or [])
        self._known(table, keys)
        reverse = args.get("direction") == "desc"
        def sortable(row, key):
            value = row.values.get(key, "")
            return (_decimal(value) if table.fields.get(key) in (
                "Money", "Decimal", "Count", "Rate") else str(value))
        rows = sorted(table.rows,
                      key=lambda row: tuple(sortable(row, key) for key in keys)
                      + (str(sorted(row.values.items())),), reverse=reverse)
        return _carried(table, rows)

    def _calendar(self, table, args):
        field = str(args.get("field") or "")
        self._known(table, [field])
        start, end = str(args.get("from") or ""), str(args.get("to") or "")
        if not start or not end or start > end:
            raise QueryError("calendar window needs ordered from and to dates")
        rows = []
        for row in table.rows:
            if not start <= str(row.values.get(field) or "") <= end:
                continue
            values = dict(row.values)
            boundary = dict(values.get("boundary") or {"whole": False})
            period = {"kind": "period", "value": start, "to": end}
            boundary["whole"] = False
            boundary["selected"] = [
                *[dict(item) for item in boundary.get("selected") or ()
                  if item.get("kind") != "period"], period]
            boundary["cut"] = [
                *[dict(item) for item in boundary.get("cut") or ()
                  if item.get("kind") != "period"], period]
            values["boundary"] = boundary
            rows.append(QueryRow(values, _records(row), row.grade, row.coverage,
                                 row.hypothetical))
        return _carried(table, rows)

    def _rolling(self, table, args):
        field = str(args["field"])
        self._known(table, [field])
        dates = [datetime.date.fromisoformat(str(row.values.get(field))[:10])
                 for row in table.rows if row.values.get(field)]
        if not dates and not args.get("anchor"):
            return _carried(table, ())
        end = datetime.date.fromisoformat(str(args.get("anchor") or max(dates)))
        width = int(args["width"])
        unit = args["unit"]
        if unit == "month":
            month_index = end.year * 12 + (end.month - 1) - width
            year, month0 = divmod(month_index, 12)
            month = month0 + 1
            start = datetime.date(
                year, month, min(end.day, calendar.monthrange(year, month)[1]))
            start += datetime.timedelta(days=1)
        else:
            days = width * {"day": 1, "week": 7}[unit]
            start = end - datetime.timedelta(days=days - 1)
        span = (start.isoformat(), end.isoformat())
        rows = tuple(row for row in table.rows
                     if row.values.get(field)
                     and start <= datetime.date.fromisoformat(
                         str(row.values[field])[:10]) <= end)
        if args["edge_policy"] == "require_full_coverage":
            rows = tuple(row for row in rows if span in row.coverage)
        adjusted = []
        for row in rows:
            values = dict(row.values)
            boundary = dict(values.get("boundary") or {"whole": False})
            period = {"kind": "period", "value": span[0], "to": span[1]}
            boundary["whole"] = False
            boundary["selected"] = [
                *[dict(item) for item in boundary.get("selected") or ()
                  if item.get("kind") != "period"], period]
            boundary["cut"] = [
                *[dict(item) for item in boundary.get("cut") or ()
                  if item.get("kind") != "period"], period]
            values["boundary"] = boundary
            adjusted.append(QueryRow(values, _records(row), row.grade,
                                     row.coverage, row.hypothetical))
        return _carried(table, adjusted)

    def _join(self, inputs, args):
        if len(inputs) != 2:
            raise QueryError("join needs two input tables")
        left, right = inputs
        left_key, right_key = str(args.get("left_key") or ""), str(args.get("right_key") or "")
        self._known(left, [left_key]); self._known(right, [right_key])
        prefix = str(args.get("right_prefix") or "right_")
        index = {}
        for row in right.rows:
            index.setdefault(row.values.get(right_key), []).append(row)
        rows = []
        for lrow in left.rows:
            matches = index.get(lrow.values.get(left_key), [])
            if not matches and args.get("join_kind") == "left": matches = [QueryRow({})]
            for rrow in matches:
                values = dict(lrow.values)
                values.update({prefix + key: value for key, value in rrow.values.items()})
                rows.append(QueryRow(values, tuple(sorted(set(_records(lrow)) | set(_records(rrow)))),
                                     weakest((lrow.grade, rrow.grade)),
                                     tuple(sorted(set(lrow.coverage) & set(rrow.coverage))),
                                     lrow.hypothetical or rrow.hypothetical))
        fields = {**left.fields, **{prefix + key: value for key, value in right.fields.items()}}
        quantities = {**left.quantities,
                      **{prefix + key: value for key, value in
                         right.quantities.items()}}
        currency_fields = {**left.currency_fields,
                           **{prefix + key: prefix + value for key, value in
                              right.currency_fields.items()}}
        boundary_fields = {**left.boundary_fields,
                           **{prefix + key: prefix + value for key, value in
                              right.boundary_fields.items()}}
        return QueryTable(tuple(rows), fields, (), quantities, currency_fields,
                          boundary_fields)

    def _set(self, op, inputs, args):
        if (len(inputs) != 2 or inputs[0].fields != inputs[1].fields
                or inputs[0].quantities != inputs[1].quantities
                or inputs[0].currency_fields != inputs[1].currency_fields
                or inputs[0].boundary_fields != inputs[1].boundary_fields):
            raise QueryError(f"{op} needs two compatible tables")
        keys = list(args.get("keys") or inputs[0].fields)
        self._known(inputs[0], keys)
        identity = lambda row: tuple(row.values.get(key) for key in keys)
        left, right = inputs
        right_ids = {identity(row) for row in right.rows}
        if op == "union_compatible":
            rows, seen = [], set()
            for row in left.rows + right.rows:
                if identity(row) not in seen:
                    rows.append(row); seen.add(identity(row))
        elif op == "difference": rows = [row for row in left.rows if identity(row) not in right_ids]
        else: rows = [row for row in left.rows if identity(row) in right_ids]
        return _narrowed(left, rows)

    def _arithmetic(self, op, table, args):
        left, right, output = (str(args.get(name) or "")
                               for name in ("left", "right", "output"))
        self._known(table, [left, right])
        left_kind, right_kind = table.fields[left], table.fields[right]
        if left_kind not in {"Money", "Decimal", "Count", "Rate"}:
            raise QueryError(f"{op} needs statically typed numeric operands")
        if left not in table.boundary_fields or right not in table.boundary_fields:
            raise QueryError(f"{op} needs operands with trusted financial boundaries")
        if left_kind != right_kind:
            raise QueryError(f"{op} needs operands of the same numeric type")
        if (op != "ratio" and table.quantities.get(left)
                and table.quantities.get(right)
                and table.quantities[left] != table.quantities[right]):
            raise QueryError(f"{op} cannot combine different quantities")
        rows = []
        output_boundary = f"__boundary_{output}"
        for row in table.rows:
            left_boundary = _boundary(row, table, left)
            right_boundary = _boundary(row, table, right)
            ratio_boundary = (_ratio_boundary(left_boundary, right_boundary)
                              if op == "ratio" and left_boundary is not None
                              and right_boundary is not None else None)
            compatible = (ratio_boundary is not None if op == "ratio"
                          else left_boundary is not None
                          and right_boundary is not None
                          and _same_boundary(left_boundary, right_boundary))
            if not compatible:
                raise QueryError(f"{op} cannot combine different financial boundaries")
            if left_kind == "Money":
                left_currency = table.currency_fields.get(left, "")
                right_currency = table.currency_fields.get(right, "")
                if (not left_currency or not right_currency
                        or row.values.get(left_currency)
                        != row.values.get(right_currency)):
                    raise QueryError(f"{op} cannot combine currencies")
            a, b = _decimal(row.values[left]), _decimal(row.values[right])
            if op == "delta": value = a - b
            elif op == "ratio":
                if b == 0: raise QueryError("ratio denominator is zero")
                value = a / b
            else:
                if b == 0: raise QueryError("percentage-change baseline is zero")
                value = (a - b) / abs(b)
            values = {**row.values, output: str(value)}
            if ratio_boundary is not None:
                values[output_boundary] = ratio_boundary
            rows.append(QueryRow(values, _records(row),
                                 row.grade, row.coverage, row.hypothetical))
        fields = {**table.fields,
                  output: "Rate" if op != "delta" else left_kind}
        quantities = dict(table.quantities)
        source_quantity = table.quantities.get(left, "")
        if source_quantity:
            quantities[output] = (
                source_quantity if op == "delta"
                else (f"ratio_of_{source_quantity}"
                      if source_quantity == table.quantities.get(right, "")
                      else "ratio"))
        currency_fields = dict(table.currency_fields)
        if op == "delta" and left_kind == "Money":
            currency_fields[output] = table.currency_fields[left]
        else:
            currency_fields.pop(output, None)
        boundary_fields = dict(table.boundary_fields)
        boundary_fields[output] = (output_boundary if op == "ratio"
                                   else table.boundary_fields[left])
        return _carried(table, rows, fields, quantities=quantities,
                        currency_fields=currency_fields,
                        boundary_fields=boundary_fields)

    def _compute(self, table, args):
        operation = args["operation"]
        left, output = (str(args[name]) for name in ("left", "output"))
        right = str(args.get("right") or "")
        self._known(table, [left] + ([right] if right else []))
        left_kind = table.fields[left]
        right_kind = table.fields.get(right, "") if right else ""
        numeric = {"Money", "Decimal", "Count", "Rate"}
        if left_kind not in numeric or (right and right_kind not in numeric):
            raise QueryError(f"{operation} needs statically typed numeric operands")
        if (right and (left not in table.boundary_fields
                       or right not in table.boundary_fields)):
            raise QueryError(
                f"{operation} needs operands with trusted financial boundaries")
        left_quantity = table.quantities.get(left, "")
        right_quantity = table.quantities.get(right, "") if right else ""
        if operation in ("add", "subtract"):
            if left_kind != right_kind:
                raise QueryError(f"{operation} needs operands of the same type")
            if left_quantity and right_quantity and left_quantity != right_quantity:
                raise QueryError(f"{operation} cannot combine different quantities")
        if operation == "multiply" and left_kind == right_kind == "Money":
            raise QueryError(f"{operation} cannot combine two money fields")
        rows = []
        output_boundary = f"__boundary_{output}"
        for row in table.rows:
            ratio_boundary = None
            if right:
                left_boundary = _boundary(row, table, left)
                right_boundary = _boundary(row, table, right)
                ratio_boundary = (
                    _ratio_boundary(left_boundary, right_boundary)
                    if operation == "divide" and left_boundary is not None
                    and right_boundary is not None
                    else None)
                compatible = (
                    ratio_boundary is not None if operation == "divide"
                    else left_boundary is not None and right_boundary is not None
                    and _same_boundary(left_boundary, right_boundary))
                if not compatible:
                    raise QueryError(
                        f"{operation} cannot combine different financial boundaries")
            if operation in ("add", "subtract", "divide") \
                    and left_kind == right_kind == "Money":
                left_currency = table.currency_fields.get(left, "")
                right_currency = table.currency_fields.get(right, "")
                if (not left_currency or not right_currency
                        or row.values.get(left_currency)
                        != row.values.get(right_currency)):
                    raise QueryError(f"{operation} cannot combine currencies")
            a = _decimal(row.values[left])
            b = _decimal(row.values[right]) if right else None
            if operation == "absolute": value = abs(a)
            elif operation == "add": value = a + b
            elif operation == "subtract": value = a - b
            elif operation == "multiply": value = a * b
            else:
                if b == 0: raise QueryError("compute denominator is zero")
                value = a / b
            values = {**row.values, output: str(value)}
            if ratio_boundary is not None:
                values[output_boundary] = ratio_boundary
            rows.append(QueryRow(values, _records(row),
                                 row.grade, row.coverage, row.hypothetical))
        if operation == "absolute" or operation in ("add", "subtract"):
            kind, output_quantity = left_kind, left_quantity
        elif operation == "multiply":
            if left_kind == "Money":
                kind, output_quantity = "Money", left_quantity
            elif right_kind == "Money":
                kind, output_quantity = "Money", right_quantity
            else:
                kind, output_quantity = left_kind, left_quantity
        elif left_kind == "Money" and right_kind != "Money":
            kind, output_quantity = "Money", left_quantity
        else:
            kind = "Rate"
            output_quantity = (
                f"ratio_of_{left_quantity}"
                if left_quantity and left_quantity == right_quantity
                else ("ratio" if left_quantity and right_quantity else ""))
        quantities = dict(table.quantities)
        if output_quantity:
            quantities[output] = output_quantity
        currency_fields = dict(table.currency_fields)
        if kind == "Money":
            source = left if left_kind == "Money" else right
            currency_fields[output] = table.currency_fields.get(source, "")
        else:
            currency_fields.pop(output, None)
        boundary_fields = dict(table.boundary_fields)
        source_boundary = left if left_kind == "Money" or not right else right
        if operation == "divide" and right:
            boundary_fields[output] = output_boundary
        elif source_boundary in table.boundary_fields:
            boundary_fields[output] = table.boundary_fields[source_boundary]
        return _carried(table, rows, {**table.fields, output: kind},
                        quantities=quantities,
                        currency_fields=currency_fields,
                        boundary_fields=boundary_fields)

    @staticmethod
    def _require_coverage(table, args):
        required = (str(args.get("from") or ""), str(args.get("to") or ""))
        return _narrowed(table,
                         (row for row in table.rows if required in row.coverage))

    @staticmethod
    def _require_grade(table, args):
        ladder = ("verified", "corroborated", "unverified", "conflicted")
        minimum = str(args.get("minimum") or "")
        if minimum not in ladder: raise QueryError("unknown evidence grade")
        return _narrowed(table, (row for row in table.rows
                                 if row.grade in ladder
                                 and ladder.index(row.grade)
                                 <= ladder.index(minimum)))

    def _emit(self, table, spec):
        value_field = str(spec.get("value_field") or "")
        what_field = str(spec.get("what_field") or "")
        quantity = str(spec.get("quantity") or "")
        currency_field = str(spec.get("currency_field") or "")
        dated_field = str(spec.get("dated_field") or "")
        self._known(table, [value_field] + ([what_field] if what_field else [])
                    + ([currency_field] if currency_field else [])
                    + ([dated_field] if dated_field else []))
        figures = []
        for row in table.rows[:self.max_output_rows]:
            trusted_quantity = (str(row.values.get("quantity") or "")
                                or table.quantities.get(value_field, ""))
            if not trusted_quantity or quantity != trusted_quantity:
                raise QueryError("emit quantity is not established by the query source and operators")
            dynamic_currency = str(row.values.get("currency") or "")
            if (table.fields.get(value_field) == "Money"
                    or (table.fields.get(value_field) == "EvidenceMagnitude"
                        and dynamic_currency)):
                trusted_currency = table.currency_fields.get(value_field, "")
                if not trusted_currency or currency_field != trusted_currency:
                    raise QueryError("money emission must use its trusted currency field")
            boundary_field = table.boundary_fields.get(value_field, "")
            inherited = row.values.get(boundary_field) if boundary_field else None
            if not isinstance(inherited, dict):
                raise QueryError("emit boundary is not established by the query source and operators")
            accounts = inherited.get("accounts") or {}
            boundary = bounded(
                whole=bool(inherited.get("whole", False)),
                counted=int(accounts.get("counted", 0)),
                held=int(accounts.get("held", 0)),
                selected=inherited.get("selected", ()),
                cut=inherited.get("cut", ()),
                unmeasured=inherited.get("unmeasured", ()),
                unposted=int(inherited.get("unposted", 0)))
            figures.append(figure(
                row.values[value_field],
                str(row.values.get(what_field) or spec.get("what") or quantity),
                quantity=trusted_quantity,
                kind="hypothetical" if row.hypothetical else "computed",
                grade=row.grade, currency=str(row.values.get(currency_field) or ""),
                dated=str(row.values.get(dated_field) or ""),
                record_ids=_records(row), boundary=boundary))
        return ToolResult(tool="financial_query", ok=True, figures=figures,
                          data={"rows": len(table.rows)})


__all__ = ["FinancialQueryExecutor", "QueryError", "QueryRow", "QueryTable"]
