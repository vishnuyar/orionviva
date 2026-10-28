"""Source proposals are closed, sourced and independently reconcilable."""
import json
from dataclasses import replace
from decimal import Decimal

import pytest

from viva.ingest import instrument_contracts as c
from viva.ingest.instrument_parser import parse_instrument_json
from viva.ingest.instrument_observations import (
    ObservationChange, ObservationKind, Operation, parse_observation_json,
    validate_transition,
)

S = c.Source("synthetic-source", 1)


def printed(raw):
    return {"raw": str(raw), "page": 1}


def identity(label="LOAN-A"):
    return {"institution": printed("Fixture Institution"),
            "account_reference": printed(label), "holder": printed("Synthetic Person")}


def deposit_json():
    return {"identity": identity("CD-A"), "subtype": "periodic",
            "start": printed("2021-01-01"), "end": printed("2021-01-31"),
            "opening": printed("1000"), "closing": printed("1010"),
            "movements": [{"kind": "interest_credit", "amount": printed("10"),
                           "dated": printed("2021-01-31"), "reference": printed("INT-A")}],
            "uncredited_interest": printed("7")}


def mortgage_json():
    return {"identity": identity(), "start": printed("2021-01-01"),
            "end": printed("2021-01-31"), "opening_principal": printed("1000"),
            "closing_principal": printed("900"),
            "principal_movements": [{"kind": "principal_reduction", "amount": printed("100"),
                "dated": printed("2021-01-15"), "reference": printed("PAY-A")}],
            "payments": [{"dated": printed("2021-01-15"), "reference": printed("PAY-A"),
                "principal": printed("100"), "interest": printed("200"),
                "escrow": printed("300"), "fees": printed("0"), "total": printed("600")}],
            "escrow": {"identity": identity("ESCROW-A"), "opening": printed("0"),
                "closing": printed("200"), "movements": [
                    {"kind": "deposit", "amount": printed("300"), "dated": printed("2021-01-15"), "reference": printed("PAY-A")},
                    {"kind": "tax_disbursement", "amount": printed("100"), "dated": printed("2021-01-20"), "reference": printed("TAX-A")} ]}}


def refinance_json():
    return {"dated": printed("2023-01-01"), "reference": printed("REFI-A"),
            "old_loan": identity("LOAN-A"), "new_loan": identity("LOAN-B"),
            "old_payoff_principal": printed("1000"), "new_funded_principal": printed("1000"),
            "borrower_contribution": printed("25"), "cash_out": printed("0"),
            "financed_costs": printed("0"), "fees": [{"label": printed("Closing fee"), "amount": printed("25")}],
            "total_fees": printed("25")}


def parse(data, kind):
    return parse_instrument_json(json.dumps(data), kind, "synthetic-source")


def test_deposit_reconciles_only_credited_interest_and_retains_source():
    facts = parse(deposit_json(), "term_deposit_statement")
    assert c.check_deposit(facts).disposition == c.Disposition.ACCEPTED
    assert facts.closing.value == Decimal("1010")
    assert facts.uncredited_interest.value == Decimal("7")
    assert facts.movements[0].amount.source == S
    bad = replace(facts, closing=replace(facts.closing, value=Decimal("1010.01")))
    assert c.check_deposit(bad).check.delta == "0.01"
    assert c.check_deposit(bad).disposition == c.Disposition.HELD


def test_deposit_redemption_balances_and_out_of_period_is_rejected():
    data = deposit_json()
    data.update(subtype="maturity", opening=printed("1010"), closing=printed("0"))
    data["movements"][0].update(kind="redemption", amount=printed("1010"))
    assert c.check_deposit(parse(data, "term_deposit_statement")).check.passed
    data["movements"][0]["dated"] = printed("2021-02-01")
    with pytest.raises(c.ContractError, match="outside"):
        c.check_deposit(parse(data, "term_deposit_statement"))


def test_payment_is_600_cash_but_only_100_principal():
    facts = parse(mortgage_json(), "mortgage_statement")
    results = c.check_mortgage(facts)
    assert all(r.disposition == c.Disposition.ACCEPTED for r in results)
    assert facts.opening_principal.value - facts.closing_principal.value == Decimal("100")
    assert facts.payments[0].total.value == Decimal("600")
    assert facts.escrow.closing.value == Decimal("200")


@pytest.mark.parametrize("mutated,expected", [("principal", "principal_balance"), ("payment", "payment:PAY-A"), ("escrow", "escrow_balance")])
def test_component_failure_does_not_promote_or_reject_other_components(mutated, expected):
    data = mortgage_json()
    if mutated == "principal":
        data["closing_principal"] = printed("900.01")
    elif mutated == "payment":
        data["payments"][0]["interest"] = printed("200.01")
    else:
        data["escrow"]["closing"] = printed("200.01")
    results = c.check_mortgage(parse(data, "mortgage_statement"))
    assert [r.component for r in results if r.disposition == c.Disposition.HELD] == [expected]
    assert sum(r.disposition == c.Disposition.ACCEPTED for r in results) == 2


def test_missing_escrow_is_unavailable_not_zero_or_failure():
    data = mortgage_json(); data.pop("escrow")
    results = c.check_mortgage(parse(data, "mortgage_statement"))
    assert results[0].check.passed
    assert results[-1].disposition == c.Disposition.UNAVAILABLE


def test_settlement_does_not_certify_old_zero_without_payoff_witness():
    facts = parse(refinance_json(), "refinance_settlement")
    results = c.check_refinance(facts)
    assert all(r.check.passed for r in results[:-1])
    assert results[-1].disposition == c.Disposition.UNAVAILABLE
    assert c.check_refinance(replace(facts, old_closing_principal=c.Money(Decimal("0"), "USD", c.Source("old-loan-paid-off", 1))))[-1].check.passed
    changed = replace(facts, old_payoff_principal=replace(facts.old_payoff_principal, value=Decimal("1000.01")))
    assert not c.check_refinance(changed)[0].check.passed


@pytest.mark.parametrize("basis", [c.RateBasis.NOMINAL_COMPOUNDED, c.RateBasis.EFFECTIVE_APY, c.RateBasis.UNKNOWN])
def test_retained_unsupported_deposit_basis_does_not_enable_calculation(basis):
    terms = c.DepositTerms(c.Money(Decimal("1000"), "USD", S), c.SourcedDate("2021-01-01", S),
        c.SourcedDate("2022-01-01", S), c.Rate(Decimal("5.25"), S), basis, c.DayCount.ACT_365,
        rate_basis_source=S, day_count_source=S)
    assert terms.calculation_issue() == "unsupported_rate_basis"
    assert replace(terms, rate_basis=c.RateBasis.SIMPLE_NOMINAL).calculation_issue() == ""
    assert replace(terms, rate_basis=c.RateBasis.SIMPLE_NOMINAL, day_count_source=None).calculation_issue()


def test_note_rate_is_not_apr_and_fixed_terms_require_evidence():
    terms = c.MortgageTerms(c.Money(Decimal("630000"), "USD", S), c.SourcedDate("2021-01-01", S),
        fixed_rate=True, note_rate=c.Rate(Decimal("5.25"), S), note_rate_basis=c.RateBasis.SIMPLE_NOMINAL,
        term_months=360, fixed_rate_source=S, note_rate_basis_source=S, term_months_source=S)
    assert terms.disclosure_apr is None
    assert terms.calculation_issue() == ""
    assert replace(terms, fixed_rate=False).calculation_issue() == "fixed_rate_required"
    assert replace(terms, fixed_rate_source=None).calculation_issue()
    assert replace(terms, note_rate_basis=c.RateBasis.EFFECTIVE_APY).calculation_issue()


@pytest.mark.parametrize("family,restriction", [(c.Family.DEPOSIT, c.Restriction.TERM), (c.Family.ESCROW, c.Restriction.ESCROW)])
def test_new_instrument_accounts_require_restrictions_and_never_become_available(family, restriction):
    with pytest.raises(c.ContractError):
        c.Availability(family)
    contract = c.Availability(family, restriction, S)
    assert not contract.permits_starting_cash(True)
    assert not contract.permits_starting_cash(False)


def test_ordinary_cash_preserves_existing_eligibility():
    contract = c.Availability(c.Family.ORDINARY)
    assert contract.permits_starting_cash(True)
    assert not contract.permits_starting_cash(False)


def event_identity(kind=c.MatchKind.DEPOSIT_TRANSFER):
    return c.FinancialIdentity(kind, "CD-A", "SAVINGS-A", "XFER-A", c.Money(Decimal("1000"), "USD", S), c.SourcedDate("2021-01-01", S))


@pytest.mark.parametrize("field,value", [("reference", ""), ("reference", "OTHER"), ("account_id", ""), ("counterparty_id", "OTHER")])
def test_amount_and_date_never_suffice_without_financial_identity(field, value):
    subject = event_identity()
    assert not c.compatible_counterpart(subject, replace(subject, **{field: value}))


def test_bounded_matching_and_ambiguity():
    subject = event_identity()
    within = replace(subject, dated=c.SourcedDate("2021-01-04", S))
    outside = replace(subject, dated=c.SourcedDate("2021-01-05", S))
    assert c.select_counterpart(subject, (within,))[0] == "matched"
    assert c.select_counterpart(subject, (outside,))[0] == "unmatched"
    assert c.select_counterpart(subject, (within, subject))[0] == "ambiguous"
    mortgage = replace(subject, kind=c.MatchKind.MORTGAGE_PAYMENT)
    assert c.compatible_counterpart(mortgage, replace(mortgage, dated=c.SourcedDate("2021-01-11", S)))
    assert not c.compatible_counterpart(mortgage, replace(mortgage, dated=c.SourcedDate("2021-01-12", S)))


def test_tax_match_requires_same_property_and_tax_year():
    subject = replace(event_identity(c.MatchKind.TAX_PAYMENT), property_id="PROPERTY-A", tax_year=2021)
    assert c.compatible_counterpart(subject, subject)
    assert not c.compatible_counterpart(subject, replace(subject, tax_year=2022))
    assert not c.compatible_counterpart(subject, replace(subject, property_id="PROPERTY-B"))
    assert not c.compatible_counterpart(replace(subject, property_id=""), replace(subject, property_id=""))


def test_tax_bill_is_not_a_paid_receipt():
    data = {"authority": printed("Fixture Tax Office"), "property_reference": printed("PROPERTY-A"),
            "tax_year": 2021, "dated": printed("2021-12-01"), "reference": printed("TAX-A"),
            "amount": printed("11000"), "status": "bill", "tax_year_source": {"page": 1}, "status_source": {"page": 1}}
    facts = parse(data, "property_tax_receipt")
    assert c.check_tax_receipt(facts).disposition == c.Disposition.UNAVAILABLE
    data["status"] = "paid"
    assert c.check_tax_receipt(parse(data, "property_tax_receipt")).disposition == c.Disposition.ACCEPTED


def test_legacy_classification_is_unknown_and_bond_fund_has_both_axes():
    unknown = parse({"instrument": printed("FXNAX")}, "position_classification")
    assert unknown.exposure == c.Exposure.UNKNOWN
    assert unknown.vehicle == c.Vehicle.UNKNOWN
    explicit = parse({"instrument": printed("Any printed instrument"), "exposure": "bond", "vehicle": "mutual_fund",
                      "exposure_source": {"page": 2}, "vehicle_source": {"page": 2}}, "position_classification")
    assert explicit.exposure == c.Exposure.BOND
    assert explicit.vehicle == c.Vehicle.MUTUAL_FUND
    assert explicit.exposure_source.page == 2
    with pytest.raises(c.ContractError):
        parse({"instrument": printed("FXNAX"), "exposure": "bond"}, "position_classification")


@pytest.mark.parametrize("mutate", [lambda d: d.update(extra="ignored?"),
    lambda d: d["closing"].update(raw="NaN"), lambda d: d["closing"].update(raw=1000.0),
    lambda d: d["closing"].update(page=True), lambda d: d["closing"].update(doc_id="forged"),
    lambda d: d["movements"][0].update(kind="arbitrary instruction"),
    lambda d: d["start"].update(raw="2021-02-30")])
def test_closed_source_parser_rejects_unknown_nonfinite_forged_and_malformed_fields(mutate):
    data = deposit_json(); mutate(data)
    with pytest.raises(c.ContractError):
        parse(data, "term_deposit_statement")


def test_duplicate_json_keys_and_mixed_currency_and_floats_fail():
    with pytest.raises(c.ContractError, match="duplicate"):
        parse_instrument_json('{"x":1,"x":2}', "mortgage_statement", "doc")
    facts = parse(deposit_json(), "term_deposit_statement")
    with pytest.raises(c.ContractError, match="currencies"):
        c.check_deposit(replace(facts, closing=replace(facts.closing, currency="EUR")))
    with pytest.raises(c.ContractError, match="Decimal"):
        c.Money(1.0, "USD", S)


def change(observation_id="A", operation=Operation.CREATE, prior_id=None, payload=None):
    return ObservationChange(observation_id, "CD-A", ObservationKind.AVAILABILITY,
        c.SourcedDate("2021-01-01", S), operation, S,
        payload or c.Availability(c.Family.DEPOSIT, c.Restriction.TERM, S), prior_id)


def test_observation_correction_frontier_rejects_forks_and_release():
    first = change(); second = change("B", Operation.CORRECT, "A")
    assert validate_transition(first, None) == first
    assert validate_transition(second, first) == second
    with pytest.raises(c.ContractError, match="stale"):
        validate_transition(change("C", Operation.CORRECT, "A"), second)
    with pytest.raises(c.ContractError, match="release"):
        validate_transition(change("B", Operation.CORRECT, "A", c.Availability(c.Family.ORDINARY)), first)
    with pytest.raises(c.ContractError, match="retracted"):
        ObservationChange("B", "CD-A", ObservationKind.AVAILABILITY,
            first.effective, Operation.RETRACT, S, None, "A")


def test_general_observation_correct_and_retract_retain_history_contract():
    payload = parse({"instrument": printed("Unknown instrument")}, "position_classification")
    first = ObservationChange("A", "RETIREMENT-A", ObservationKind.POSITION_CLASSIFICATION,
        c.SourcedDate("2021-01-01", S), Operation.CREATE, S, payload)
    corrected = replace(first, observation_id="B", operation=Operation.CORRECT, prior_id="A")
    retracted = replace(corrected, observation_id="C", operation=Operation.RETRACT, prior_id="B", payload=None)
    assert validate_transition(corrected, first) == corrected
    assert validate_transition(retracted, corrected) == retracted
    assert first.payload == payload
    with pytest.raises(c.ContractError):
        validate_transition(replace(corrected, prior_id="C", observation_id="D"), retracted)


def test_observation_parser_closed_payload_and_source_binding():
    data = {"observation_id": "A", "subject_id": "CD-A", "kind": "availability", "effective": printed("2021-01-01"),
        "operation": "create", "source": {"page": 1}, "payload": {"family": "term_deposit",
            "restriction": "restricted_term_deposit", "source": {"page": 1}}}
    first = parse_observation_json(json.dumps(data), "source-A")
    assert first.source.doc_id == first.payload.source.doc_id == "source-A"
    data["payload"]["free_form_instruction"] = "release all money"
    with pytest.raises(c.ContractError):
        parse_observation_json(json.dumps(data), "source-A")


def test_match_never_accepts_blank_reference_or_signed_magnitude():
    subject = event_identity()
    blank = replace(subject, reference="   ")
    assert not c.compatible_counterpart(blank, blank)
    negative = replace(subject, amount=replace(subject.amount, value=Decimal("-1000")))
    assert not c.compatible_counterpart(negative, negative)


def test_cash_eligibility_is_boolean_not_truthy_text():
    with pytest.raises(c.ContractError):
        c.Availability(c.Family.ORDINARY).permits_starting_cash("eligible")


def test_missing_payment_principal_preserves_snapshot_and_holds_only_payment():
    data = mortgage_json()
    del data["payments"][0]["principal"]
    facts = parse(data, "mortgage_statement")
    assert facts.payments[0].principal is None
    results = c.check_mortgage(facts)
    assert results[0].component == "principal_balance"
    assert results[0].disposition == c.Disposition.ACCEPTED
    payment = next(r for r in results if r.component == "payment:PAY-A")
    assert payment.disposition == c.Disposition.HELD
    assert "principal" in payment.reason
    assert payment.check is None
    assert results[-1].disposition == c.Disposition.ACCEPTED


def test_frozen_facts_reject_mutable_movement_containers():
    facts = parse(deposit_json(), "term_deposit_statement")
    rows = list(facts.movements)
    with pytest.raises(c.ContractError):
        replace(facts, movements=rows)
    assert c.check_deposit(facts).disposition == c.Disposition.ACCEPTED


def test_invalid_flow_enum_cannot_reconcile_or_enter_observation():
    facts = parse(deposit_json(), "term_deposit_statement")
    with pytest.raises(c.ContractError):
        bad = replace(facts, closing=facts.opening, movements=(replace(facts.movements[0], kind="not_a_flow",
            amount=replace(facts.movements[0].amount, value=Decimal("0"))),))
        observation = ObservationChange("bad", "CD-A", ObservationKind.DEPOSIT_COMPONENTS,
            facts.end, Operation.CREATE, S, bad)
        validate_transition(observation, None)
        c.check_deposit(bad)


@pytest.mark.parametrize("field,value", [("rate_basis", "simple_nominal"), ("day_count", "invented_convention"),
    ("rate_basis_source", "no source"), ("day_count_source", "no source")])
def test_terms_runtime_type_checks_cover_enum_and_source_provenance(field, value):
    terms = c.DepositTerms(c.Money(Decimal("1000"), "USD", S), c.SourcedDate("2021-01-01", S),
        c.SourcedDate("2022-01-01", S), c.Rate(Decimal("5.25"), S), c.RateBasis.SIMPLE_NOMINAL,
        c.DayCount.ACT_365, rate_basis_source=S, day_count_source=S)
    with pytest.raises(c.ContractError):
        replace(terms, **{field: value})


def test_observation_tax_year_uses_same_validation_as_document_parser():
    data = {"observation_id": "TAX", "subject_id": "PROPERTY-A", "kind": "tax_receipt", "effective": printed("2021-01-01"),
        "operation": "create", "source": {"page": 1}, "payload": {"authority": printed("Fixture Tax Office"),
            "property_reference": printed("PROPERTY-A"), "tax_year": 0, "dated": printed("2021-01-01"),
            "reference": printed("TAX-A"), "amount": printed("11000"), "status": "paid",
            "tax_year_source": {"page": 1}, "status_source": {"page": 1}}}
    with pytest.raises(c.ContractError):
        parse_observation_json(json.dumps(data), "source-A")


def test_nested_refinance_terms_reject_nonpositive_term():
    data = refinance_json()
    data["new_terms"] = {"original_principal": printed("1000"), "originated": printed("2023-01-01"), "term_months": 0}
    with pytest.raises(c.ContractError):
        parse(data, "refinance_settlement")


@pytest.mark.parametrize("year", [0, 10000, True])
def test_matching_financial_identity_rejects_non_calendar_tax_year(year):
    with pytest.raises(c.ContractError):
        replace(event_identity(c.MatchKind.TAX_PAYMENT), property_id="PROPERTY-A", tax_year=year)


@pytest.mark.parametrize("family", ["deposit", "principal", "escrow"])
def test_flow_rows_require_positive_amounts(family):
    zero = c.Money(Decimal("0"), "USD", S)
    with pytest.raises(c.ContractError):
        if family == "deposit":
            c.DepositMovement(c.DepositKind.INTEREST, zero, c.SourcedDate("2021-01-01", S), c.SourcedText("REF", S))
        elif family == "principal":
            c.PrincipalMovement(c.PrincipalKind.REDUCTION, zero, c.SourcedDate("2021-01-01", S), c.SourcedText("REF", S))
        else:
            c.EscrowMovement(c.EscrowKind.DEPOSIT, zero, c.SourcedDate("2021-01-01", S), c.SourcedText("REF", S))


@pytest.mark.parametrize("component", ["interest", "escrow", "fees", "total"])
def test_each_missing_payment_component_preserves_independent_snapshot(component):
    data = mortgage_json()
    del data["payments"][0][component]
    facts = parse(data, "mortgage_statement")
    assert getattr(facts.payments[0], component) is None
    results = c.check_mortgage(facts)
    assert results[0].disposition == c.Disposition.ACCEPTED
    assert results[1].disposition == c.Disposition.HELD
    assert component in results[1].reason
    assert results[2].disposition == c.Disposition.ACCEPTED


@pytest.mark.parametrize("defect", ["negative", "currency", "date"])
def test_invalid_payment_section_cannot_discard_valid_principal_snapshot(defect):
    facts = parse(mortgage_json(), "mortgage_statement")
    payment = facts.payments[0]
    if defect == "negative":
        payment = replace(payment, interest=replace(payment.interest, value=Decimal("-200")))
    elif defect == "currency":
        payment = replace(payment, total=replace(payment.total, currency="EUR"))
    else:
        payment = replace(payment, dated=c.SourcedDate("2021-02-01", S))
    results = c.check_mortgage(replace(facts, payments=(payment,)))
    assert results[0].disposition == c.Disposition.ACCEPTED
    assert results[1].disposition == c.Disposition.HELD
    assert results[2].disposition == c.Disposition.ACCEPTED


@pytest.mark.parametrize("missing", ["opening", "closing", "identity", "movements"])
def test_incomplete_escrow_section_preserves_principal_and_payment(missing):
    data = mortgage_json()
    del data["escrow"][missing]
    facts = parse(data, "mortgage_statement")
    results = c.check_mortgage(facts)
    assert results[0].disposition == c.Disposition.ACCEPTED
    assert results[1].disposition == c.Disposition.ACCEPTED
    assert results[2].disposition == c.Disposition.HELD
    assert missing in results[2].reason
    assert results[2].check is None


@pytest.mark.parametrize("missing", ["opening_principal", "closing_principal", "principal_movements"])
def test_incomplete_principal_section_preserves_other_independent_sections(missing):
    data = mortgage_json()
    del data[missing]
    facts = parse(data, "mortgage_statement")
    results = c.check_mortgage(facts)
    assert results[0].disposition == c.Disposition.HELD
    assert results[0].check is None
    assert missing in results[0].reason
    assert results[1].disposition == c.Disposition.ACCEPTED
    assert results[2].disposition == c.Disposition.ACCEPTED


def test_missing_payment_section_is_unavailable_without_discarding_other_sections():
    data = mortgage_json()
    del data["payments"]
    results = c.check_mortgage(parse(data, "mortgage_statement"))
    assert results[0].disposition == c.Disposition.ACCEPTED
    assert results[1].component == "payments"
    assert results[1].disposition == c.Disposition.UNAVAILABLE
    assert results[2].disposition == c.Disposition.ACCEPTED


@pytest.mark.parametrize("section,missing", [
    ("principal_movements", "kind"), ("principal_movements", "amount"),
    ("principal_movements", "dated"), ("principal_movements", "reference"),
    ("payments", "dated"), ("payments", "reference"),
    ("escrow", "kind"), ("escrow", "amount"),
    ("escrow", "dated"), ("escrow", "reference")])
def test_incomplete_nested_mortgage_row_holds_only_its_section(section, missing):
    data = mortgage_json()
    rows = data["escrow"]["movements"] if section == "escrow" else data[section]
    del rows[0][missing]
    results = c.check_mortgage(parse(data, "mortgage_statement"))
    expected = {"principal_movements": 0, "payments": 1, "escrow": 2}[section]
    assert results[expected].disposition == c.Disposition.HELD
    assert missing in results[expected].reason
    assert results[expected].check is None
    assert all(r.disposition == c.Disposition.ACCEPTED for i, r in enumerate(results) if i != expected)


@pytest.mark.parametrize("invalid", [
    lambda d: d["escrow"]["opening"].update(raw=12.5),
    lambda d: d["escrow"]["opening"].update(page="one"),
    lambda d: d["escrow"]["movements"][0].update(kind="not_a_kind"),
    lambda d: d["payments"][0].update(dated={"raw": "2021-01-01", "page": 0}),
    lambda d: d["principal_movements"][0].update(reference={"raw": "X", "page": False}),
])
def test_incomplete_section_support_never_coerces_invalid_supplied_values(invalid):
    data = mortgage_json()
    invalid(data)
    with pytest.raises(c.ContractError):
        parse(data, "mortgage_statement")


@pytest.mark.parametrize("missing", ["identity", "start", "end"])
def test_global_mortgage_source_context_still_required(missing):
    data = mortgage_json()
    del data[missing]
    with pytest.raises(c.ContractError):
        parse(data, "mortgage_statement")


@pytest.mark.parametrize("missing", ["original_principal", "originated"])
def test_partial_optional_loan_terms_cannot_discard_accepted_financial_sections(missing):
    data = mortgage_json()
    data["terms"] = {"original_principal": printed("630000"), "originated": printed("2021-01-01")}
    del data["terms"][missing]
    facts = parse(data, "mortgage_statement")
    assert all(r.disposition == c.Disposition.ACCEPTED for r in c.check_mortgage(facts))
    assert facts.terms.calculation_issue()
    assert getattr(facts.terms, missing) is None


def equal_month_source():
    data = deposit_json()
    data["terms"] = {"principal": printed("1000"), "opened": printed("2021-01-01"),
        "maturity": printed("2022-01-01"), "rate": printed("5.25%"),
        "rate_basis": "simple_nominal", "day_count": "equal_monthly_12",
        "compounding": printed("Credited monthly; no interest on interest"),
        "rate_basis_source": {"page": 1}, "day_count_source": {"page": 1}}
    return data


def test_fictional_equal_month_convention_normalizes_as_a_distinct_sourced_term():
    facts = parse(equal_month_source(), "term_deposit_statement")
    assert facts.terms.day_count.value == "equal_monthly_12"
    assert facts.terms.day_count not in (c.DayCount.ACT_365, c.DayCount.ACT_360)
    assert facts.terms.day_count_source == S
    assert facts.terms.rate.percent == Decimal("5.25")
    assert c.check_deposit(facts).disposition == c.Disposition.ACCEPTED


def test_equal_month_convention_is_a_closed_member_without_reinterpreting_old_conventions():
    convention = c.DayCount("equal_monthly_12")
    assert convention is c.DayCount.EQUAL_MONTHLY_12
    assert c.DayCount("actual_365") is c.DayCount.ACT_365
    assert c.DayCount("actual_360") is c.DayCount.ACT_360
    assert c.DayCount("unknown") is c.DayCount.UNKNOWN
    facts = parse(equal_month_source(), "term_deposit_statement")
    with pytest.raises(c.ContractError):
        replace(facts.terms, day_count="equal_monthly_12")


@pytest.mark.parametrize("invented", ["equal_monthly_13", "actual_monthly_12"])
def test_equal_month_vocabulary_does_not_admit_unrecognized_conventions(invented):
    data = equal_month_source()
    data["terms"]["day_count"] = invented
    with pytest.raises(c.ContractError):
        parse(data, "term_deposit_statement")
