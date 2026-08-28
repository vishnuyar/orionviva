"""Obligations are forecasts with receipts, never renamed recurrence."""

from decimal import Decimal

from viva.ledger import account_opened, simple_transaction
from viva.ledger.events import (CORROBORATED, SCOPE_RHYTHM, category_assigned,
                                finding_set_aside, merchant_enriched,
                                rhythm_subject, ruling_recorded)
from viva.ledger.projection import LedgerProjection


def _prior(merchant="lumen streaming"):
    return merchant_enriched(
        merchant, "services", occurred_at="2026-01-01",
        grade=CORROBORATED,
        attributes={"counterparty_kind": "business", "billing": "standing",
                    "billing_period": "monthly"})


def _projection(rows, *, merchant="lumen streaming"):
    events = [account_opened("checking", "depository", "Checking", "USD",
                             "2026-01-01", institution="northbank")]
    events.extend(simple_transaction("checking", amount, description, when,
                                     kind="depository")
                  for when, description, amount in rows)
    events.append(_prior(merchant))
    return LedgerProjection(events)


def _monthly(n=4, amount="-14.99", description="LUMEN STREAMING"):
    return [(f"2026-{month:02d}-05", description, amount)
            for month in range(1, n + 1)]


def test_a_measured_monthly_obligation_has_a_dated_exact_expectation():
    projection = _projection(_monthly())

    (obligation,) = projection.obligations("2026-05-05")

    assert obligation.subject == "lumen streaming"
    assert obligation.expected_date == "2026-05-05"
    assert obligation.status == "due" and obligation.basis == "measured"
    assert obligation.exact
    assert obligation.amount_min == obligation.amount_max == Decimal("14.99")
    assert obligation.count == 4 and obligation.record_ids


def test_two_sightings_and_a_catalog_prior_are_expected_but_never_due():
    projection = _projection(_monthly(n=2))

    (obligation,) = projection.obligations("2026-03-05")

    assert obligation.status == "expected"
    assert obligation.basis == "observed"
    assert obligation.expected_date == "2026-03-05"


def test_person_confirmation_can_qualify_observed_intervals_without_three_rows():
    projection = _projection(_monthly(n=2))
    projection.apply(ruling_recorded(
        SCOPE_RHYTHM, rhythm_subject("lumen streaming", "out"),
        "2026-02-10", value="monthly", said="this is monthly"))

    (obligation,) = projection.obligations("2026-03-05")

    assert obligation.status == "due"
    assert obligation.basis == "confirmed"


def test_month_end_expectation_returns_to_the_anchor_day_after_february():
    projection = _projection([
        ("2025-12-31", "LUMEN STREAMING", "-14.99"),
        ("2026-01-31", "LUMEN STREAMING", "-14.99"),
        ("2026-02-28", "LUMEN STREAMING", "-14.99"),
    ])

    (obligation,) = projection.obligations("2026-03-01")

    assert obligation.expected_date == "2026-03-31"


def test_one_relationship_in_two_currencies_is_refused_without_an_fx_rate():
    events = [
        account_opened("usd", "depository", "USD account", "USD", "2026-01-01"),
        account_opened("eur", "depository", "EUR account", "EUR", "2026-01-01"),
    ]
    for month in range(1, 5):
        events.append(simple_transaction(
            "usd" if month % 2 else "eur", "-14.99", "LUMEN STREAMING",
            f"2026-{month:02d}-05", kind="depository"))
    events.append(_prior())
    projection = LedgerProjection(events)

    assert projection.obligations("2026-05-05") == []
    assert not {"amount_changed", "expected_outflow_missing",
                "recurring_obligation"} & {
                    finding.kind for finding in projection.findings("2026-07-10")}


def test_stale_evidence_stops_the_due_claim_and_becomes_a_missing_finding():
    projection = _projection(_monthly())

    assert projection.obligations("2026-07-10") == []
    missing = [finding for finding in projection.findings("2026-07-10")
               if finding.kind == "expected_outflow_missing"]
    assert len(missing) == 1
    assert missing[0].expected_date == "2026-05-05"


def test_incoming_rhythm_interruption_is_ranked_ahead_of_outgoing_noise():
    projection = _projection(_monthly(amount="2500.00", description="ACME PAYROLL"),
                             merchant="acme payroll")

    findings = projection.findings("2026-07-10")

    assert findings[0].kind == "income_interrupted"


def test_a_new_amount_outside_a_previously_fixed_run_is_a_change():
    projection = _projection(_monthly(n=2) + [
        ("2026-03-05", "LUMEN STREAMING", "-24.99")])

    changed = [finding for finding in projection.findings("2026-03-10")
               if finding.kind == "amount_changed"]

    assert len(changed) == 1
    assert changed[0].prior_amount == Decimal("14.99")
    assert changed[0].current_amount == Decimal("24.99")


def test_exact_same_account_day_merchant_and_amount_is_a_possible_duplicate():
    projection = _projection([
        ("2026-01-05", "LUMEN STREAMING", "-14.99"),
        ("2026-01-05", "LUMEN STREAMING", "-14.99"),
    ])

    duplicate = [finding for finding in projection.findings("2026-01-06")
                 if finding.kind == "possible_duplicate"]

    assert len(duplicate) == 1
    assert duplicate[0].amount == Decimal("14.99")


def test_resolved_fee_category_produces_a_fee_finding():
    projection = _projection([
        ("2026-01-05", "NORTHBANK ANNUAL FEE", "-60.00")],
        merchant="northbank annual fee")
    movement = projection.movements()[0]
    projection.apply(category_assigned(
        movement.key, movement.description, "fees", "verified",
        "2026-01-06", by="human"))

    fees = [finding for finding in projection.findings("2026-01-06")
            if finding.kind == "fee_observed"]

    assert len(fees) == 1 and fees[0].amount == Decimal("60.00")


def test_set_aside_is_a_stake_snapshot_and_new_evidence_wakes_the_finding():
    projection = _projection(_monthly())
    recurring = next(finding for finding in projection.findings("2026-04-10")
                     if finding.kind == "recurring_obligation")
    projection.apply(finding_set_aside(
        recurring.id, recurring.kind, recurring.stake, "2026-04-10"))

    assert recurring.id not in {
        finding.id for finding in projection.findings("2026-04-10")}

    projection.apply(simple_transaction(
        "checking", "-14.99", "LUMEN STREAMING", "2026-05-05",
        kind="depository"))
    returned = {finding.id: finding for finding in
                projection.findings("2026-05-10")}
    assert recurring.id in returned
    assert returned[recurring.id].stake != recurring.stake
