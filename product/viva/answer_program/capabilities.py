"""Fixed financial analyses over the existing deterministic read authorities."""

from __future__ import annotations

import copy
import datetime
from decimal import Decimal, localcontext, Inexact

from .. import quantity
from ..tools import ledger_tools
from ..tools.envelope import (COMPUTED, ROUNDED, EXACT, ToolResult, bounded,
                             figure, refusal, weakest)
from ..tools.ledger_common import (_eligible_period_accounts,
                                  _empty_period_evidence, _narrowed_to, _check_filters)
from ..tools.ledger_aggregates import _aggregate_income
from ..tools.registry import _validate


TOOL = "read_financial_analysis"
_STRING = {"type": "string", "minLength": 1}
_DATE = {"type": "string", "format": "date"}
ANALYSIS_PARAMS = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "view": {"type": "string", "enum": ["spending_comparison", "movement_search", "period_income", "spending_by_account"]},
        "from": _DATE, "to": _DATE,
        "baseline_from": _DATE, "baseline_to": _DATE,
        "include_percentage": {"type": "boolean"},
        "filters": {"type": "object", "additionalProperties": False,
                    "properties": {key: _STRING for key in
                                   ("account", "category", "merchant", "currency")}},
    },
    "required": ["view", "from", "to"],
}


def _validated(args, proj):
    if not isinstance(args, dict):
        return refusal(TOOL, "invalid_arguments", "Arguments must be an object.")
    defects = _validate(ANALYSIS_PARAMS, args)
    if defects:
        return refusal(TOOL, "invalid_arguments", "; ".join(defects))
    comparison = args["view"] == "spending_comparison"
    keys = {"baseline_from", "baseline_to", "include_percentage"}
    if comparison and not keys <= set(args):
        return refusal(TOOL, "invalid_arguments", "A comparison needs both baseline dates and a percentage flag.")
    if not comparison and keys & set(args):
        return refusal(TOOL, "invalid_arguments", "Movement search does not accept comparison arguments.")
    if comparison and type(args["include_percentage"]) is not bool:
        return refusal(TOOL, "invalid_arguments", "The percentage flag must be boolean.")
    for prefix in ("", "baseline_") if comparison else ("",):
        start, end = args[prefix + "from"], args[prefix + "to"]
        try:
            if (datetime.date.fromisoformat(start).isoformat() != start
                    or datetime.date.fromisoformat(end).isoformat() != end):
                raise ValueError
        except (ValueError, TypeError):
            return refusal(TOOL, "bad_date", "Every period edge must be an ISO date.")
        if start > end:
            return refusal(TOOL, "bad_date", "A period starts after it ends.")
    filters = args.get("filters", {})
    if args["view"] in {"period_income", "spending_by_account"} and set(filters) - {"currency"}:
        return refusal(TOOL, "invalid_arguments", "This analysis accepts only a currency filter.")
    if any(not value.strip() for value in filters.values()):
        return refusal(TOOL, "invalid_arguments", "Filters cannot be blank.")
    if filters.get("account") and filters["account"] not in proj.accounts():
        return refusal(TOOL, "unknown_account", "Select a canonical held account.")
    return None


def _total(result):
    matches = [item for item in result.figures
               if item["quantity"] == quantity.SPENDING
               and item["what"] == "total spending by category"]
    if len(matches) != 1 or Decimal(matches[0]["value"]) != Decimal(result.data["total"]):
        raise ValueError("The spending authority did not declare exactly one matching total.")
    return copy.deepcopy(matches[0])


def _account_labels(proj):
    rows = list(proj.account_infos())
    labels = {row.account: str(row.name or row.institution or row.account).strip()
              for row in rows}
    for row in rows:
        label = labels[row.account]
        if sum(str(other.name or other.institution or other.account).strip().casefold()
               == label.casefold() for other in rows) > 1:
            labels[row.account] = (f"{row.name} — {row.institution}"
                                   if row.name and row.institution else row.account)
    duplicate_labels = {value.casefold() for value in labels.values()
                        if sum(candidate.casefold() == value.casefold()
                               for candidate in labels.values()) > 1}
    for row in rows:
        if labels[row.account].casefold() in duplicate_labels:
            labels[row.account] = row.account
    return labels


def read_financial_analysis(proj, args, locale="", today=""):
    """Validate the closed boundary before dispatching any financial read."""
    problem = _validated(args, proj)
    if problem:
        return problem
    filters = copy.deepcopy(args.get("filters", {}))
    filters["window"] = {"from": args["from"], "to": args["to"]}
    if args["view"] == "spending_by_account":
        result = ledger_tools.query_ledger(proj, {
            "entity": "aggregate", "metric": "spending", "group_by": "account",
            "filters": filters}, locale, today)
        result = copy.deepcopy(result)
        result.tool = TOOL
        if result.ok:
            labels = _account_labels(proj)
            groups = set(result.data["by_group"])
            for item in result.figures:
                account = next((cut["value"] for cut in item["boundary"].get("cut", [])
                                if cut["kind"] == "account"), "")
                if account in groups and account in labels:
                    item["what"] = f"spending — {labels[account]}"
        return result
    if args["view"] == "period_income":
        bad = _check_filters(proj, filters)
        if bad:
            bad.tool = TOOL
            return bad
        result = _aggregate_income(proj, filters, attributed_only=True)
        result.tool = TOOL
        return result
    if args["view"] == "movement_search":
        result = ledger_tools.list_movements(proj, {"filters": filters}, today)
        result.tool = TOOL
        if not result.ok or result.data["total"]:
            return result
        evidence = _empty_period_evidence(
            proj, filters, _eligible_period_accounts(proj, filters))
        if evidence["status"] != "covered":
            tag = "partial_empty_scope" if evidence["status"] == "partial" else "unsupported_empty_scope"
            return refusal(TOOL, tag,
                           "Held statements do not cover the whole requested population and period; an empty search is not a measured zero.")
        result.record_ids = list(evidence["record_ids"])
        result.covers = list(evidence["covers"])
        for item in result.figures:
            item["record_ids"] = list(evidence["record_ids"])
        return result
    baseline_filters = {**filters, "window": {
        "from": args["baseline_from"], "to": args["baseline_to"]}}
    reads = [ledger_tools.query_ledger(proj, {
        "entity": "aggregate", "metric": "spending", "group_by": "category",
        "filters": selected}, locale, today)
        for selected in (filters, baseline_filters)]
    for result in reads:
        if not result.ok:
            result.tool = TOOL
            return result
    try:
        current, baseline = [_total(result) for result in reads]
    except (ValueError, KeyError, ArithmeticError):
        return refusal(TOOL, "inconsistent_spending_authority", "The period totals could not be matched to their numerical authority.")
    if not current["currency"] or current["currency"] != baseline["currency"]:
        return refusal(TOOL, "mixed_currencies", "The compared totals need the same known currency.")
    current["what"] = "recorded spending in the requested period"
    baseline["what"] = "recorded spending in the baseline period"
    records = sorted(set(current["record_ids"]) | set(baseline["record_ids"]))
    grade = weakest([current["grade"], baseline["grade"]]) if all(
        item["grade"] for item in (current, baseline)) else ""
    common = _narrowed_to(proj, args.get("filters", {}))
    boundary = bounded(whole=False, selected=common, cut=common)
    caveats = [*reads[0].caveats, *reads[1].caveats,
               f"Requested period: {args['from']} to {args['to']}; baseline period: {args['baseline_from']} to {args['baseline_to']}. Changes compare recorded spending, with each period's coverage limits."]
    with localcontext() as context:
        context.prec = 80
        now, before = Decimal(current["value"]), Decimal(baseline["value"])
        change = now - before
        figures = [current, baseline, figure(
            change, "change in recorded spending between the compared periods",
            quantity=quantity.SPENDING, kind=COMPUTED, grade=grade,
            currency=current["currency"], record_ids=records, boundary=boundary)]
        if args["include_percentage"]:
            if not before:
                caveats.append("Percentage change is undefined because baseline spending is zero.")
            else:
                context.clear_flags()
                percentage = change / before
                figures.append(figure(
                    percentage, "percentage change in recorded spending",
                    quantity=quantity.ratio_of(quantity.SPENDING), kind=COMPUTED,
                    grade=grade, record_ids=records, boundary=boundary,
                    exactness=ROUNDED if context.flags[Inexact] else EXACT))
    return ToolResult(
        tool=TOOL, ok=True, data={"view": "spending_comparison",
                                  "include_percentage": args["include_percentage"]},
        figures=figures, grade=grade, record_ids=records,
        identifiers=reads[0].identifiers, covers=[*reads[0].covers, *reads[1].covers],
        caveats=caveats, coverage="Recorded spending in two explicitly compared periods.",
        text="Recorded spending compared across two explicit periods.")


def _filters(parameters):
    return {("account" if key == "account_phrase" else key): value
            for key, value in parameters.items()
            if key in {"account_phrase", "category", "merchant", "currency"}}


def build_analysis(request, manifest):
    from .intents import _program, _read, _rows_binding, _rows_clause
    parameters = request.parameters
    family = request.family
    filters = _filters(parameters)
    if family != "recurring_spending":
        filters["window"] = {"from": parameters["from"], "to": parameters["to"]}
    if family in {"spending_comparison", "movement_search", "period_income", "spending_by_account"}:
        args = {"view": family, "from": parameters["from"], "to": parameters["to"],
                "filters": _filters(parameters)}
        if family == "spending_comparison":
            args.update({key: parameters[key] for key in ("baseline_from", "baseline_to")})
            args["include_percentage"] = "percentage_change" in request.requested_claims
        tool = TOOL
    else:
        tool = "query_ledger"
        metric = {"period_income": "income", "period_surplus": "surplus",
                  "recurring_spending": "recurring_spending"}.get(family, "spending")
        args = {"entity": "aggregate", "metric": metric, "filters": filters}
        if metric == "spending":
            args["group_by"] = {"spending_by_category": "category",
                                "spending_by_merchant": "merchant",
                                "spending_by_account": "account"}[family]
    text = {
        "spending_by_category": "Recorded spending by category and its total: {rows}.",
        "spending_by_merchant": "Recorded spending by merchant and its total: {rows}.",
        "spending_by_account": "Recorded spending by account and its total: {rows}.",
        "spending_comparison": "Recorded spending in the compared periods and its change: {rows}.",
        "movement_search": "Matching transactions and the number found in the held records: {rows}.",
        "period_income": "Attributed income and separately disclosed unexplained inflows: {rows}.",
        "period_surplus": "Attributed income, counted spending and their supported surplus: {rows}.",
        "recurring_spending": "Observed recurring spending patterns and their basis amounts: {rows}.",
    }[family]
    return _program(manifest, family, [_rows_clause("analysis", text, "rows")],
                    [_read("analysis", tool, args)], [_rows_binding("rows", "analysis")],
                    required=["analysis"])


def analysis_families():
    from .intents import SemanticFamily, _object
    dates = {"from": _DATE, "to": _DATE}
    families = {}
    copy = {
        "spending_by_category": ("Spending by category", "Show spending by category from 2026-01-01 to 2026-01-31."),
        "spending_by_merchant": ("Spending by merchant", "Where did I spend money from 2026-01-01 to 2026-01-31?"),
        "spending_by_account": ("Spending by account", "Show spending by account from 2026-01-01 to 2026-01-31."),
        "spending_comparison": ("Compare spending between periods", "Compare January 2026 spending with December 2025."),
        "movement_search": ("Find transactions", "Show transactions from 2026-01-01 to 2026-01-31."),
        "period_income": ("Income attributed to a source", "Show attributed income from 2026-01-01 to 2026-01-31."),
        "period_surplus": ("Income minus spending", "How much was income minus spending in January 2026?"),
        "recurring_spending": ("Costs that repeat in the records", "What costs repeat in my records?"),
    }
    for family, optional, required, claims in (
        ("spending_by_category", ("account_phrase", "currency"), tuple(dates), ("spending",)),
        ("spending_by_merchant", ("account_phrase", "currency"), tuple(dates), ("spending",)),
        ("spending_by_account", ("currency",), tuple(dates), ("spending",)),
        ("spending_comparison", ("account_phrase", "category", "merchant", "currency"),
         ("from", "to", "baseline_from", "baseline_to"), ("comparison", "percentage_change")),
        ("movement_search", ("account_phrase", "category", "merchant", "currency"), tuple(dates), ("movements",)),
        ("period_income", ("currency",), tuple(dates), ("income",)),
        ("period_surplus", ("currency",), tuple(dates), ("surplus",)),
        ("recurring_spending", ("currency",), (), ("patterns",)),
    ):
        properties = {key: _DATE for key in required}
        properties.update({key: _STRING for key in optional})
        families[family] = SemanticFamily(
            family, _object(properties, required), claims, build_analysis,
            user_label=copy[family][0], user_example=copy[family][1])
    return families


def analysis_samples():
    dates = {"from": "2000-01-01", "to": "2000-01-31"}
    return {family: ({**dates, "baseline_from": "1999-12-01", "baseline_to": "1999-12-31"}
                     if family == "spending_comparison" else
                     {} if family == "recurring_spending" else dict(dates))
            for family in analysis_families()}


_ANALYSIS_LIMIT_MESSAGES = {
    "unsupported_empty_scope": "Held statements do not cover the requested period, so an empty result cannot be zero. Ask about a covered period or add the relevant statement.",
    "partial_empty_scope": "Held statements cover only part of the requested period, so an empty result cannot be zero.",
    "insufficient_history": "There is not enough recorded history to establish that pattern.",
    "mixed_currencies": "Ask for one currency at a time; these records contain amounts in different currencies.",
}


def actionable_limit(program, execution, binding):
    """Preserve reviewed read limits without masking infrastructure or integrity."""
    if (program.question_kind not in {*analysis_families(), *measurement_projection_families(), *scenario_families()}
            or binding.result.answered
            or binding.result.refusal != "nothing_established"
            or execution.deadline_exceeded or execution.evidence_limit_exceeded
            or execution.figure_limit_exceeded):
        return None
    refused = [execution.nodes[node.id] for node in program.nodes
               if node.importance == "required" and node.id in execution.nodes
               and execution.nodes[node.id].status == "refused"]
    if not refused or any(record.refusal not in _ANALYSIS_LIMIT_MESSAGES for record in refused):
        return None
    tag = refused[0].refusal
    from ..tools.scenarios import scenario_request
    return tag, scenario_request(tag,program.question_kind) or _ANALYSIS_LIMIT_MESSAGES[tag]


def build_measurement_projection(request,manifest):
    from .intents import _program, _read, _rows_binding, _rows_clause
    family=request.family; parameters=request.parameters
    if family in {'recorded_cash','account_value_history'}:
        tool='read_account_measurements'; args={'view':family,'account':parameters['account_phrase']}
    elif family=='statement_period_coverage':
        tool='read_statement_coverage'; args={'account':parameters['account_phrase']}
    else:
        tool='read_financial_projections'; args={'view':family}
    args.update({key:value for key,value in parameters.items() if key != 'account_phrase'})
    introductions={
        'recorded_cash':'Recorded cash at its measurement date: {rows}.',
        'account_value_history':'Sourced account values at the recorded dates: {rows}.',
        'statement_period_coverage':'Held statement coverage and its limits: {rows}.',
        'known_remainder':'Hypothetical known remainder from the recorded inputs: {rows}.',
        'upcoming_obligations':'Next expected outgoing amounts and dates: {rows}.',
        'goal_progress':'Recorded local goal terms and hypothetical progress: {rows}.',
    }
    return _program(manifest,family,[_rows_clause('measurement',introductions[family],'rows')],
                    [_read('measurement',tool,args)],[_rows_binding('rows','measurement')],required=['measurement'])


def measurement_projection_families():
    from .intents import SemanticFamily,_object
    copy={
        'recorded_cash':('Recorded cash','Show recorded cash for Example Checking.'),
        'account_value_history':('Account values at recorded dates','Show account values for Example Checking from 2026-01-01 to 2026-03-31.'),
        'statement_period_coverage':('Statement coverage for a period','What statement coverage is held for Example Checking from 2026-01-01 to 2026-03-31?'),
        'known_remainder':('Known remainder from the recorded inputs','Show the known remainder for the next 30 days.'),
        'upcoming_obligations':('Next expected outgoing payments','Show the next expected outgoing payments within 30 days.'),
        'goal_progress':('Progress on local goals','Show progress on my local goals.'),
    }
    result={}
    for family in copy:
        properties={}; required=[]
        if family in {'recorded_cash','account_value_history','statement_period_coverage'}:
            properties['account_phrase']=_STRING; required.append('account_phrase')
        if family in {'account_value_history','statement_period_coverage'}:
            properties.update({'from':_DATE,'to':_DATE});required+=['from','to']
        if family!='statement_period_coverage': properties['currency']=_STRING
        if family in {'known_remainder','upcoming_obligations'}: properties['horizon_days']={'type':'string','pattern':'^[0-9]{1,3}$'}
        result[family]=SemanticFamily(family,_object(properties,required),(family,),build_measurement_projection,
            user_label=copy[family][0],user_example=copy[family][1])
    return result


def measurement_projection_samples():
    return {family:({'account_phrase':'account-held',**({'from':'2000-01-01','to':'2000-01-31'} if family!='recorded_cash' else {})}
                    if family in {'recorded_cash','account_value_history','statement_period_coverage'} else {})
            for family in measurement_projection_families()}


_ANALYSIS_LIMIT_MESSAGES.update({
    'projection_goal_sources_unavailable':'These recorded goal inputs do not have complete local source records. They cannot support this projection.',
    'cash_account_ineligible':'Recorded cash is available only for a depository account or the cash component of an investment account. Choose a supported account.',
    'cash_measurement_unavailable':'These records do not contain a dated, sourced cash measurement for this account. Missing cash cannot be zero.',
    'account_history_unavailable':'No sourced account measurements are held for the requested period. A later balance cannot fill this history.',
    'incomplete_investment_snapshot':'The held records do not establish a complete investment snapshot from one accepted statement. They cannot support a whole-account total.',
    'owed_value_not_debt':'The recorded liability value represents a credit rather than an amount owed. It cannot be turned into debt by changing its sign.',
    'history_row_limit':'This period has more measurements than one answer can display. Ask about a narrower period.',
    'statement_coverage_unavailable':'Held statements do not attest the requested period. This does not prove an issued statement is missing.',
    'no_eligible_liquid_balance':'There is no eligible recorded depository balance to start this projection. Add or review the relevant balance statement.',
    'no_upcoming_expectations':'No supported next outgoing expectation is held within this horizon. This does not establish that no payments are due.',
    'no_recorded_goals':'No recorded local goal is available in this scope. Create a local goal in Plans to track its progress.',
})

_ANALYSIS_LIMIT_MESSAGES.update({
    'projection_payload_limit':'These projection inputs are too large for one answer. Choose one currency or a shorter horizon.',
    'goal_progress_payload_limit':'These recorded goals are too large for one answer. Try one currency; if this already uses one currency, this tool cannot show the whole set.',
    'coverage_payload_limit':'These statement intervals are too large for one answer. Ask about a narrower period.',
})

_ANALYSIS_LIMIT_MESSAGES['measurement_source_context_conflict'] = 'These records disagree about the currency or account type of this measurement. They cannot support a compatible value.'
_ANALYSIS_LIMIT_MESSAGES['projection_start_unavailable'] = 'A sourced starting cash balance is missing or inconsistent with the accepted records. Review the relevant balance statement before using this projection.'
_ANALYSIS_LIMIT_MESSAGES.update({
    'history_payload_limit':'These measurements and source details are too large for one answer. Ask about a narrower period; a single measurement may still exceed the display limit.',
    'cash_payload_limit':'This cash measurement and its source details exceed the display limit. The complete sourced value cannot be shown.',
})


def build_scenario(request, manifest):
    from .intents import _program, _read, _rows_binding, _rows_clause
    parameters = request.parameters
    nodes = []
    args = {"view":request.family,"parameters":dict(parameters),
            "parameter_sources":copy.deepcopy(request.parameter_sources)}
    if "account_phrase" in parameters:
        view = "recorded_owed" if request.family == "loan_payoff_scenario" else "recorded_cash"
        nodes.append(_read("starting_measurement","read_account_measurements",
                           {"view":view,"account":parameters["account_phrase"],"currency":parameters["currency"]}))
        args["starting_figure"] = {"ref":{"node":"starting_measurement","value":"unique_figure_id"}}
    node = _read("scenario","simulate_scenario",args)
    node["depends_on"] = [row["id"] for row in nodes]
    nodes.append(node)
    return _program(manifest,request.family,
        [_rows_clause("scenario","Hypothetical scenario under the stated assumptions: {rows}.","rows")],
        nodes,[_rows_binding("rows","scenario")],required=["scenario"])


def scenario_families():
    from .intents import SemanticFamily, _object
    from ..tools.scenarios import INPUTS
    labels={"savings_scenario":"Simulate saving and monthly contributions",
            "loan_payoff_scenario":"Simulate monthly loan repayments",
            "cash_flow_scenario":"Simulate monthly cash endpoints"}
    result={}
    for family,names in INPUTS.items():
        properties={name:(_DATE if name=="start_date" else _STRING) for name in names}
        properties["account_phrase"]=_STRING
        required=tuple(name for name in names if name!=names[0])
        result[family]=SemanticFamily(family,_object(properties,required),(family,),build_scenario,
            user_label=labels[family],user_example=labels[family]+" from explicitly stated current-question amounts, currency, dates and monthly timing.")
    return result


def scenario_samples():
    from ..tools.scenarios import INPUTS
    return {family:{key:("2000-01-31" if key=="start_date" else "USD" if key=="currency" else "1") for key in names}
            for family,names in INPUTS.items()}


from ..tools.scenarios import SCENARIO_REQUESTS
_ANALYSIS_LIMIT_MESSAGES.update({tag:next(iter(requests.values())) for tag,requests in SCENARIO_REQUESTS.items()})
_ANALYSIS_LIMIT_MESSAGES.update({
    "owed_account_ineligible":"An amount owed requires a held liability account. Choose a supported liability account.",
    "owed_measurement_unavailable":"These records do not contain a dated, sourced amount owed for this account. Missing debt cannot be zero.",
    "owed_payload_limit":"This debt measurement and its source details exceed the display limit. The complete sourced amount owed cannot be shown.",
})

# Complete-result overflow is owned by the tool, never a model assumption tag.
_ANALYSIS_LIMIT_MESSAGES["scenario_payload_limit"] = "This scenario and its recorded source details are too large for one answer."
