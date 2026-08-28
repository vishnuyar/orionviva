"""The overview utility block is backend-ranked and completely worded."""

from viva.ledger import account_opened, simple_transaction
from viva.ledger.events import (CORROBORATED, category_assigned,
                                merchant_enriched)
from viva.ledger.projection import LedgerProjection
from viva.surface.obligations import utility


def _monthly_projection():
    events = [account_opened(
        "checking", "depository", "Checking", "USD", "2026-01-01")]
    events.extend(simple_transaction(
        "checking", "-14.99", "LUMEN STREAMING", f"2026-{month:02d}-05",
        kind="depository") for month in range(1, 5))
    events.append(merchant_enriched(
        "lumen streaming", "services", occurred_at="2026-01-01",
        grade=CORROBORATED,
        attributes={"counterparty_kind": "business", "billing": "standing",
                    "billing_period": "monthly"}))
    return LedgerProjection(events)


def test_due_obligation_carries_reviewed_copy_receipts_and_actions():
    read = utility(_monthly_projection(), "en-US", "2026-05-05")

    assert read["state"] == "ready"
    obligation = read["obligations"][0]
    assert obligation["status"] == "due"
    assert obligation["basis"] == "measured"
    assert obligation["expected_date"] == "2026-05-05"
    assert obligation["headline"] and obligation["explanation"]
    assert obligation["coverage"] and obligation["record_ids"]
    assert "ask_viva" in obligation["actions"]


def test_empty_utility_is_explicitly_absent():
    assert utility(LedgerProjection([]), "en-US", "2026-08-28") == {
        "state": "absent", "obligations": [], "findings": [],
        "finding_count": 0}


def test_surface_returns_only_the_top_three_while_counting_every_finding():
    projection = LedgerProjection([account_opened(
        "checking", "depository", "Checking", "USD", "2026-01-01")])
    for day in range(1, 5):
        projection.apply(simple_transaction(
            "checking", "-12.00", f"BANK FEE {day}",
            f"2026-08-{day:02d}", kind="depository"))
        movement = projection.movements()[-1]
        projection.apply(category_assigned(
            movement.key, movement.description, "fees", "verified",
            f"2026-08-{day:02d}", by="human"))

    read = utility(projection, "en-US", "2026-08-28")

    assert read["finding_count"] == 4
    assert len(read["findings"]) == 3
    assert all(row["kind"] == "fee_observed" for row in read["findings"])
    assert all(row["headline"] and row["explanation"] and row["coverage"]
               for row in read["findings"])
