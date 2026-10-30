"""A finite selected-account report over one authenticated owned revision."""
from __future__ import annotations

from dataclasses import asdict, replace, dataclass
from decimal import Decimal
import hashlib
import json
import weakref
from time import monotonic

from .envelope import ToolResult, figure, refusal, bounded, weakest
from .ledger_common import REAL_KINDS, _identifiers, _measure_of
from .ledger_movements import _captured_balance
from .instruments import _instrument_authority_result
from ..ledger.ledger import _owned_projection_identity
from ..ledger.projection.positions import CaptureLimit

TOOL = "read_account_balance_report"
SCHEMA = "selected-account-balance-sources-v1"
PARAMS = {"type": "object", "additionalProperties": False,
    "properties": {f"account_{i}": {"type": "string", "minLength": 1}
                   for i in range(1, 8)}, "required": ["account_1", "account_2"]}


@dataclass(frozen=True)
class _ReportOrigin:
    result: object
    run_token: object

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self


@dataclass(frozen=True)
class _SelectionWitness:
    result: object
    run_token: object
    accounts: tuple
    assertions: tuple
    metadata: tuple
    origin: _ReportOrigin


_REPORTS = {}
_REPORT_ASSERTIONS = {}


def _membership_metadata(result):
    data = result.data
    source = data["source_fields"]
    if (type(source["selected_accounts"]) is not list
            or type(data["trace"]["selected_accounts"]) is not list
            or type(data["rows"]) is not list or type(source["values"]) is not list):
        raise ValueError("selected report membership metadata is not canonical")
    return (tuple(source["selected_accounts"]), tuple(data["trace"]["selected_accounts"]),
        tuple(row["account"] for row in data["rows"]),
        tuple(row["account"] for row in source["values"]), source_digest(source), data["source_digest"])


def _issue_selection_witness(result, accounts, run_token):
    """Bind the successful adapter result to its actual canonical call selection."""
    identity = id(result)
    def released(reference):
        current = _REPORTS.get(identity)
        if current is not None and current.result is reference:
            _REPORTS.pop(identity, None)
    reference = weakref.ref(result, released)
    origin = _ReportOrigin(reference, run_token)
    witness = _SelectionWitness(reference, run_token, tuple(accounts),
        tuple(result.instrument_assertions), _membership_metadata(result), origin)
    _REPORTS[identity] = witness
    for assertion in result.instrument_assertions:
        assertion._selected_report_origin = origin
        assertion_id = id(assertion)
        def assertion_released(reference, identity=assertion_id):
            current = _REPORT_ASSERTIONS.get(identity)
            if current is not None and current[0] is reference:
                _REPORT_ASSERTIONS.pop(identity, None)
        _REPORT_ASSERTIONS[assertion_id] = (weakref.ref(assertion, assertion_released), reference)


def selected_report_stamping_status(result, run_token):
    """None for ordinary producers; exact-object authority for selected reports."""
    witness = _REPORTS.get(id(result))
    owned_assertions = any(type(getattr(assertion, "_selected_report_origin", None)) is _ReportOrigin
        or ((record := _REPORT_ASSERTIONS.get(id(assertion))) is not None and record[0]() is assertion)
        for assertion in result.instrument_assertions)
    if result.tool != TOOL and witness is None and not owned_assertions:
        return None
    try:
        from ..instrument_evidence import authenticated_assertion
        if (witness is None or witness.result() is not result or result.tool != TOOL
                or witness.run_token is not run_token or run_token is None
                or not result.ok or result.instrument_premises
                or _membership_metadata(result) != witness.metadata
                or tuple(result.data["source_fields"]["selected_accounts"]) != witness.accounts
                or len(result.instrument_assertions) != len(witness.assertions)):
            return False
        for assertion, original in zip(result.instrument_assertions, witness.assertions):
            if (assertion is not original
                    or getattr(assertion, "_selected_report_origin", None) is not witness.origin
                    or witness.origin.result() is not result or witness.origin.run_token is not run_token
                    or assertion.get("claim") != "availability_restriction"
                    or assertion.get("account") not in witness.accounts
                    or assertion.get("selected_request_account") != assertion.get("account")
                    or assertion.get("instrument_relationship") is not None
                    or assertion.get("disposition") != "accepted"
                    or not authenticated_assertion(assertion) or assertion._run_token is not run_token):
                return False
        return True
    except (ValueError, TypeError, KeyError, AttributeError):
        return False


def selected_accounts(args):
    if not isinstance(args, dict) or set(args) - set(PARAMS["properties"]):
        raise ValueError("unknown selected account argument")
    accounts = tuple(args.get(f"account_{i}") for i in range(1, len(args) + 1))
    if (not 2 <= len(accounts) <= 7 or len(set(accounts)) != len(accounts)
            or any(not isinstance(a, str) or not a for a in accounts)):
        raise ValueError("selected accounts require a distinct contiguous prefix")
    return accounts


def source_digest(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def _pair(identity):
    if isinstance(identity, dict):
        return identity.get("count"), identity.get("head")
    if isinstance(identity, tuple) and len(identity) >= 2:
        return identity[:2]
    return None


def source_matches(projection, runtime, *, revision=True):
    owned = _owned_projection_identity(projection)
    supplier = getattr(runtime, "supplier", None)
    expected = _pair(getattr(supplier, "expected_projection_identity", None))
    check = getattr(supplier, "source_identity", None)
    if owned is None or expected != owned or not callable(check):
        return False
    try:
        if _pair(check()) != owned:
            return False
        if revision:
            current = runtime.revision
            if current is None or _pair(current._store.authenticated_source_identity(current)) != owned:
                return False
    except Exception:
        return False
    return _owned_projection_identity(projection) == owned


def complete_bytes(result):
    return len(json.dumps({**result.to_dict(),
        "complete_figures": [dict(f) for f in result.figures]},
        ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode())


def read_report(projection, runtime, read_day, args):
    trace = {"selected_accounts": [], "authority_invocations": 0,
             "balance_attempts": [], "restriction_attempts": [], "cash_reuse": []}
    def refuse(tag, text):
        return refusal(TOOL, tag, text, trace=trace)
    try:
        accounts = selected_accounts(args)
    except ValueError as error:
        return refuse("invalid_arguments", str(error))
    trace["selected_accounts"] = list(accounts)
    if runtime is None or runtime.revision is None or not source_matches(projection, runtime):
        return refuse("current_data_unavailable", "The selected balances do not belong to the authenticated current source.")
    deadline = min(runtime.deadline, runtime.started + 2)
    def check():
        if monotonic() >= deadline:
            raise CaptureLimit("selected account report deadline")
    infos = {info.account: info for info in projection.account_infos()}
    held = sum(info.kind in REAL_KINDS for info in infos.values())
    if any(a not in infos or infos[a].kind not in ("depository", "investment", "liability") for a in accounts):
        return refuse("invalid_arguments", "Every selected identity must be a balance-holding account.")
    captured = projection.captured_docs()
    figures, assertions, rows, source_rows = [], [], [], []
    pairs = set()
    anchor_rows = []
    try:
        from ..read_store.instrument_authority import read_instrument_authority
        from ..read_store.instrument_authority_contracts import InstrumentRequest
        for account in accounts:
            check()
            info = infos[account]
            row = dict(account=account, amount="unavailable", date="unavailable",
                source="unavailable", restriction="unavailable", closure="unavailable")
            trace["authority_invocations"] += 1
            trace["balance_attempts"].append(account)
            ba, values, capture = _captured_balance(projection, account, deadline)
            trace["cash_reuse"].append(dict(account=account, reused=capture.cash_reused))
            check()
            eligible = bool(values) and all(v.as_of for v in values)
            eligible = eligible and all(t["dated"] and t["grade"] in {"verified", "corroborated", "conflicted"}
                and t["document"] in captured and type(t["page"]) is int
                and 1 <= t["page"] <= 200 for t in capture.terms)
            account_pairs = set()
            if eligible:
                for value in values:
                    terms = [t for t in capture.terms if t["currency"] == value.currency]
                    selected_pairs = {(t["document"], t["page"]) for t in terms}
                    if len(pairs | selected_pairs) > 512 or len(figures) >= 32:
                        raise CaptureLimit("selected account report source or figure bound")
                    pairs.update(selected_pairs)
                    account_pairs.update(selected_pairs)
                    documents = sorted({doc for doc, page in selected_pairs})
                    magnitude = figure(value.amount,
                        f"{info.name or account} — {_measure_of(info.kind)} · as of {value.as_of}",
                        quantity=_measure_of(info.kind), grade=value.grade,
                        dated=value.as_of, currency=value.currency, record_ids=documents,
                        subject={"account_id": account}, boundary=bounded(whole=False,
                            counted=1, held=held, selected=[{"kind":"account","value":account}],
                            cut=[{"kind":"account","value":account}]))
                    source = dict(account=account, value=str(value.amount), currency=value.currency,
                        dated=value.as_of, grade=value.grade, quantity=magnitude["quantity"],
                        dates=list(value.dates), terms=terms)
                    magnitude["balance_source_index"] = len(source_rows)
                    source_rows.append(source)
                    figures.append(magnitude)
                status = "conflicted" if any(v.grade == "conflicted" for v in values) else "accepted"
                row.update(amount=status, date="accepted", source="accepted")
            trace["authority_invocations"] += 1
            trace["restriction_attempts"].append(account)
            request = InstrumentRequest("terms", account, info.currency, as_of=read_day)
            runtime.read_count += 1
            authority = read_instrument_authority(runtime.revision, request, deadline=deadline)
            check()
            selected = tuple(a for a in authority.assertions if a.claim == "availability_restriction")
            if len(selected) > 1:
                raise CaptureLimit("selected account restriction assertion bound")
            anchor_ids = {identity for assertion in selected for identity in assertion.anchor_ids}
            filtered = replace(authority, figures=(), assertions=selected,
                anchors=tuple(a for a in authority.anchors if a.anchor_id in anchor_ids),
                relationships=(), focus=None, selection_dependencies=())
            if selected:
                formatted = _instrument_authority_result(runtime, request, filtered, deadline=deadline)
                if not formatted.ok:
                    raise ValueError("selected account restriction envelope unavailable")
                selected_anchors = formatted.data["anchors"]
                restriction_pairs = {(anchor["document_id"], anchor["page"]) for anchor in selected_anchors}
                if (len(account_pairs | restriction_pairs) > 128
                        or len(pairs | restriction_pairs) > 512):
                    raise CaptureLimit("selected account restriction source page bound")
                if any(document not in captured or type(page) is not int or not 1 <= page <= 200
                        for document, page in restriction_pairs):
                    raise ValueError("selected account restriction source pages unavailable")
                pairs.update(restriction_pairs)
                assertions.extend(formatted.instrument_assertions)
                anchor_rows.extend(selected_anchors)
                row["restriction"] = "conflicted" if selected[0].grade == "conflicted" else "accepted"
            elif any(d.disposition == "resource_limit" for d in authority.dispositions):
                raise CaptureLimit("selected account restriction source bound")
            elif any(d.disposition == "conflicted" for d in authority.dispositions):
                row["restriction"] = "conflicted"
            row["restriction_dispositions"] = [asdict(d) for d in authority.dispositions]
            rows.append(row)
            check()
        owned = _owned_projection_identity(projection)
        lineage = dict(schema=SCHEMA, selected_accounts=list(accounts),
            source_identity={"count":owned[0], "head":owned[1]}, values=source_rows)
        digest = source_digest(lineage)
        for magnitude in figures:
            magnitude["balance_source_digest"] = digest
        data = dict(source_fields=lineage, source_digest=digest, read_day=read_day,
            rows=rows, trace=trace, anchors=anchor_rows)
        documents = sorted({doc for doc, page in pairs} | {a["document_id"] for a in anchor_rows})
        result = ToolResult(TOOL, True, data=data, figures=figures,
            identifiers=_identifiers(projection, accounts), instrument_assertions=assertions,
            record_ids=documents, provenance=[{"doc_id":doc,"page":page} for doc,page in sorted(pairs)],
            grade=weakest(f["grade"] for f in figures),
            caveats=["Accepted records do not establish closure status for the selected accounts.",
                "Restriction status is unavailable where no accepted restriction statement is held.",
                "Restriction evidence is read through " + read_day + "; its own effective date remains distinct from each amount date."])
        check()
        if complete_bytes(result) > 50000:
            return refuse("resource_limit", "The complete selected-account report exceeds its byte bound.")
        check()
        if not source_matches(projection, runtime):
            return refuse("current_data_unavailable", "The selected account source changed during the report.")
        check()
        _issue_selection_witness(result, accounts, runtime.run_token)
        check()
        return result
    except (ValueError, TypeError, KeyError) as error:
        return refuse("resource_limit" if isinstance(error, CaptureLimit)
            else "account_evidence_unavailable", str(error))


def _bind_receipt_origin(result, producer, run_token):
    """Propagate the existing issued origin onto its genuinely bound answer."""
    if selected_report_stamping_status(producer, run_token) is not True:
        raise ValueError("selected account answer lacks an issued producer")
    origin = _REPORTS[id(producer)].origin
    previous = getattr(result, "_selected_report_origin", None)
    if previous is not None and previous is not origin:
        raise ValueError("selected account answer already belongs to another run")
    result._selected_report_origin = origin


def receipt_provenance(data, figures, *, producer=None, run_token=None, origin=None):
    """Consume the genuine same-run producer before serialized source metadata.

    The public digest checks consistency, not issuance. The existing private
    result/selection witness retains the actual authenticated source lineage;
    JSON copies may describe that lineage but cannot issue another one.
    """
    if (not isinstance(producer, ToolResult)
            or selected_report_stamping_status(producer, run_token) is not True
            or origin is not _REPORTS[id(producer)].origin):
        raise ValueError("selected account source producer is not current-run authority")
    if (data.get("source_fields") != producer.data.get("source_fields")
            or data.get("source_digest") != producer.data.get("source_digest")):
        raise ValueError("selected account source differs from its issued producer")
    issued = {figure.get("id"):figure for figure in producer.figures}
    lineage = data.get("source_fields")
    if (not isinstance(lineage, dict) or set(lineage) != {"schema", "selected_accounts", "source_identity", "values"}
            or lineage["schema"] != SCHEMA or source_digest(lineage) != data.get("source_digest")):
        raise ValueError("selected account source lineage changed")
    accounts = lineage["selected_accounts"]
    if not isinstance(accounts, list) or not 2 <= len(accounts) <= 7 or len(set(accounts)) != len(accounts):
        raise ValueError("selected account source population changed")
    values = lineage["values"]
    if not isinstance(values, list) or len(values) > 32:
        raise ValueError("selected account source value bound")
    out = {}
    for fig in figures:
        original = issued.get(fig.get("id"))
        if (original is None or any(fig.get(key) != original.get(key) for key in
                ("subject", "value", "currency", "dated", "grade", "quantity", "record_ids",
                 "balance_source_index", "balance_source_digest"))):
            raise ValueError("selected account figure differs from its issued producer")
        index = fig.get("balance_source_index")
        if type(index) is not int or not 0 <= index < len(values) or fig.get("balance_source_digest") != data["source_digest"]:
            raise ValueError("selected account figure source unavailable")
        value = values[index]
        if (not isinstance(value, dict) or set(value) != {"account", "value", "currency", "dated", "grade", "quantity", "dates", "terms"}
                or value["account"] not in accounts or fig.get("subject") != {"account_id":value["account"]}
                or any(fig.get(k) != value[k] for k in ("value", "currency", "dated", "grade", "quantity"))):
            raise ValueError("selected account source association changed")
        terms = value["terms"]
        if not isinstance(terms, list) or not 1 <= len(terms) <= 1000:
            raise ValueError("selected account source terms unavailable")
        pages = set()
        for term in terms:
            if (not isinstance(term, dict) or set(term) != {"account", "role", "component", "amount", "currency", "dated", "grade", "document", "page"}
                    or term["account"] != value["account"] or term["currency"] != value["currency"]
                    or term["role"] not in {"cash", "position_cash", "holding"}
                    or not term["document"] or type(term["page"]) is not int or not 1 <= term["page"] <= 200):
                raise ValueError("selected account component membership changed")
            pages.add((term["document"], term["page"]))
        if ({document for document, page in pages} != set(fig.get("record_ids", []))
                or sum((Decimal(t["amount"]) for t in terms), Decimal(0)) != Decimal(value["value"])
                or sorted({t["dated"] for t in terms if t["dated"]}) != value["dates"]
                or not value["dates"] or value["dated"] != value["dates"][0]
                or weakest(t["grade"] for t in terms) != value["grade"]):
            raise ValueError("selected account component closure changed")
        out[fig["id"]] = [dict(document_id=doc, page=page) for doc, page in sorted(pages)]
    return out
