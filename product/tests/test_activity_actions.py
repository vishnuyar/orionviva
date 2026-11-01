"""Activity v3 corrections validate live state and append exact overlays."""

import json
from dataclasses import replace
from decimal import Decimal
from importlib import import_module

import pytest

from viva.desktop_bridge.activity_actions import ActivityActions
from viva.desktop_bridge.handlers import (ACTIVITY_OPERATIONS, BridgeRequestError,
                                          default_handlers,
                                          handlers_for_opened_vault)
from viva.desktop_bridge.rpc import dispatch_frame
from viva.ingest import (ReadResult, StatementFacts, TxnFact, assign_category,
                         capture_and_ingest, rule_category_same_as,
                         rule_tag_same_as, tag_merchant, tag_movement)
from viva.ledger import (account_opened, simple_transaction, transfer_linked,
                         transfer_suggested)
from viva.ledger.events import (SCOPE_CATEGORY, SCOPE_TAG, VERIFIED,
                                merchant_enriched, ruling_recorded)
from viva.ledger.projection import LedgerProjection
from viva.surface.activity import TRANSFER_CANDIDATE_LIMIT, activity
from viva.surface.capabilities import TrustEffect, capability_for
from viva.vault import Vault


def _vault(tmp_path):
    vault = Vault.open(tmp_path / "vault", "pw")
    facts = StatementFacts(
        doc_id="", doc_type="checking_statement", doc_type_confidence=0.98,
        account_ref="Checking 1122", currency="USD",
        opening_amount=Decimal("1000.00"), opening_date="2026-03-01",
        closing_amount=Decimal("970.00"), closing_date="2026-03-31",
        transactions=[TxnFact("2026-03-05", "FIRST SHOP", Decimal("-10.00")),
                      TxnFact("2026-03-06", "SECOND SHOP", Decimal("-20.00"))],
        account_number="000000001122", institution="Acme")

    def read(_data, doc_id):
        facts.doc_id = doc_id
        return ReadResult(facts.doc_type, 0.98, facts)

    capture_and_ingest(vault.raw, vault.ledger, b"statement", read,
                       captured_at="2026-04-01")
    return vault


def _events(vault, event_type):
    return [event for event in vault.events() if event.event_type == event_type]


def _fail_after_durable_first_batch_line(monkeypatch):
    """Inject the complete-prefix write the batch boundary must roll back."""
    store_module = import_module("viva.ledger.store")
    real_write = store_module._write_batch
    failed = False

    def write_first(stream, content):
        nonlocal failed
        if failed:
            return real_write(stream, content)
        failed = True
        lines = content.splitlines(keepends=True)
        assert len(lines) >= 2, "the regression requires a multi-event batch"
        assert stream.write(lines[0]) == len(lines[0])
        stream.flush()
        store_module.os.fsync(stream.fileno())
        raise OSError("synthetic durable first-line short write")

    monkeypatch.setattr(store_module, "_write_batch", write_first)


def _transfer_vault(tmp_path, *, linked=False, candidates=1):
    vault = Vault.open(tmp_path / "transfer-vault", "pw")
    vault.ledger.append(account_opened(
        "acct:source", "depository", "Everyday", "USD", "2026-03-01",
        account_number="1111"))
    vault.ledger.append(simple_transaction(
        "acct:source", "-125.00", "payment from everyday", "2026-03-05"))
    for index in range(candidates):
        account = f"acct:destination-{index}"
        vault.ledger.append(account_opened(
            account, "depository", f"Savings {index}", "USD", "2026-03-01",
            account_number=str(2200 + index)))
        vault.ledger.append(simple_transaction(
            account, "125.00", f"payment into savings {index}",
            "2026-03-06"))
    vault.ledger.append(account_opened(
        "acct:ordinary", "depository", "Ordinary", "USD", "2026-03-01",
        account_number="9999"))
    vault.ledger.append(simple_transaction(
        "acct:ordinary", "-10.00", "ordinary shop", "2026-03-07"))
    movements = {movement.description: movement.key
                 for movement in vault.ledger.projection().movements()}
    source = movements["payment from everyday"]
    counterpart_keys = [movements[f"payment into savings {index}"]
                        for index in range(candidates)]
    if linked:
        vault.ledger.append(transfer_linked(
            source, counterpart_keys[0], "corroborated",
            {"decided_by": "named_account"}, "2026-03-07", by="auto"))
    else:
        vault.ledger.append(transfer_suggested(
            source, counterpart_keys, {"verdict": "suggested"},
            "2026-03-07"))
    return vault, source, counterpart_keys, movements["ordinary shop"]


def test_activity_v3_carries_current_category_tag_choices_and_actions(tmp_path):
    vault = _vault(tmp_path)
    first, second = vault.ledger.projection().movements()
    assign_category(vault.ledger, first.key, "groceries")
    tag_movement(vault.ledger, second.key, ["japan", "shared"])

    read = activity(vault.ledger.projection())
    row = next(item for item in read["items"] if item["id"] == second.key)

    assert {item["id"] for item in
            read["vocabularies"]["categories"]["items"]} >= {"groceries"}
    assert read["vocabularies"]["tags"]["items"] == [
        {"id": "japan", "label": "japan"},
        {"id": "shared", "label": "shared"}]
    assert row["category"] == {"id": "other", "label": "other"}
    assert row["account_id"] == second.account
    assert "Checking" in row["account_name"]
    assert row["subcategory"] == {
        "id": "unclassified", "label": "unclassified"}
    assert row["classification"] == {
        "grade": "unverified", "provenance": "default"}
    assert row["evidence_links"] == [{
        "document_id": second.provenance.doc_id, "label": "",
        "relation": "attests", "page": "", "region": ""}]
    assert row["tags"] == read["vocabularies"]["tags"]["items"]
    assert row["actions"] == ["assign_category", "assign_meaning", "replace_tags"]
    category = next(item for item in read["items"] if item["id"] == first.key)
    advertised = {item["id"]: item
                  for item in read["vocabularies"]["categories"]["items"]}
    assert category["category"] == advertised["groceries"]
    assert category["subcategory"] == {
        "id": "unclassified", "label": "unclassified"}
    assert category["classification"] == {
        "grade": "unverified", "provenance": "mixed"}


def test_activity_v3_carries_none_suggested_and_exact_reviewed_relationship(tmp_path):
    vault, source, counterparts, ordinary = _transfer_vault(tmp_path)

    read = activity(vault.ledger.projection())
    source_row = next(item for item in read["items"] if item["id"] == source)
    ordinary_row = next(item for item in read["items"] if item["id"] == ordinary)
    transfer = source_row["transfer"]

    assert ordinary_row["transfer"] == {"state": "none"}
    assert not ({"confirm_transfer", "reject_transfer", "unlink_transfer"}
                & set(ordinary_row["actions"]))
    assert transfer["state"] == "suggested"
    assert transfer["complete"] is True
    assert transfer["limit"] == TRANSFER_CANDIDATE_LIMIT
    assert [candidate["id"] for candidate in transfer["candidates"]] == counterparts
    candidate = transfer["candidates"][0]
    assert set(candidate) == {"id", "date", "description", "account",
                              "account_id", "account_name", "direction",
                              "exact_value", "currency", "display", "relationship"}
    assert candidate["account_id"].startswith("acct:destination-")
    assert "Savings 0" in candidate["account_name"]
    assert candidate["direction"] == "in"
    assert all(str(value).strip() for value in candidate.values())
    assert "payment from everyday" in candidate["relationship"]
    assert "payment into savings 0" in candidate["relationship"]
    assert "Everyday" in candidate["relationship"]
    assert "Savings 0" in candidate["relationship"]
    assert {"confirm_transfer", "reject_transfer"} <= set(source_row["actions"])
    assert "unlink_transfer" not in source_row["actions"]


def test_activity_v3_carries_an_exact_live_link_and_only_unlink(tmp_path):
    vault, source, counterparts, _ordinary = _transfer_vault(tmp_path, linked=True)

    rows = {item["id"]: item for item in activity(vault.ledger.projection())["items"]}
    source_transfer = rows[source]["transfer"]
    counterpart_transfer = rows[counterparts[0]]["transfer"]

    assert source_transfer["state"] == "linked"
    assert source_transfer["counterpart"]["id"] == counterparts[0]
    assert source_transfer["counterpart"]["description"] == "payment into savings 0"
    assert source_transfer["relationship"]
    assert counterpart_transfer["state"] == "linked"
    assert counterpart_transfer["counterpart"]["id"] == source
    assert "unlink_transfer" in rows[source]["actions"]
    assert not ({"confirm_transfer", "reject_transfer"} & set(rows[source]["actions"]))


def test_incomplete_duplicate_or_over_limit_suggestion_never_authorizes_transfer(
        tmp_path):
    vault, source, counterparts, _ordinary = _transfer_vault(
        tmp_path, candidates=TRANSFER_CANDIDATE_LIMIT + 1)
    row = next(item for item in activity(vault.ledger.projection())["items"]
               if item["id"] == source)

    assert row["transfer"]["state"] == "suggested"
    assert row["transfer"]["complete"] is False
    assert len(row["transfer"]["candidates"]) == TRANSFER_CANDIDATE_LIMIT
    assert not ({"confirm_transfer", "reject_transfer"} & set(row["actions"]))
    before = len(list(vault.events()))
    assert ActivityActions(vault).confirm_transfer({
        "movement_key": source, "counterpart_key": counterparts[0]
    })["kind"] == "stale"
    assert ActivityActions(vault).reject_transfer({
        "movement_key": source
    })["kind"] == "stale"
    assert len(list(vault.events())) == before

    vault.ledger.append(transfer_suggested(
        source, [counterparts[0], counterparts[0]], {}, "2026-03-08"))
    duplicate = next(item for item in activity(vault.ledger.projection())["items"]
                     if item["id"] == source)
    assert duplicate["transfer"]["complete"] is False
    assert len(duplicate["transfer"]["candidates"]) == 1
    assert not ({"confirm_transfer", "reject_transfer"}
                & set(duplicate["actions"]))

    ordinary_id = _ordinary
    vault.ledger.append(transfer_suggested(
        source, [ordinary_id], {}, "2026-03-09"))
    mismatched = next(item for item in activity(vault.ledger.projection())["items"]
                      if item["id"] == source)
    assert ordinary_id not in {candidate["id"]
                               for candidate in mismatched["transfer"]["candidates"]}
    assert mismatched["transfer"]["complete"] is False
    assert not ({"confirm_transfer", "reject_transfer"}
                & set(mismatched["actions"]))


def test_impossible_self_or_overlapping_links_expose_no_unlink_authority(tmp_path):
    overlap, source, counterparts, _ordinary = _transfer_vault(
        tmp_path / "overlap", candidates=2)
    overlap.ledger.append(transfer_linked(
        source, counterparts[0], "verified", {}, "2026-03-08", by="human"))
    overlap.ledger.append(transfer_linked(
        source, counterparts[1], "verified", {}, "2026-03-09", by="human"))

    rows = {item["id"]: item
            for item in activity(overlap.ledger.projection())["items"]}
    assert rows[source]["transfer"] == {"state": "none"}
    assert rows[counterparts[0]]["transfer"] == {"state": "none"}
    assert "unlink_transfer" not in rows[source]["actions"]
    before = len(list(overlap.events()))
    assert ActivityActions(overlap).unlink_transfer({
        "movement_key": source,
        "counterpart_key": counterparts[0]})["kind"] == "stale"
    assert len(list(overlap.events())) == before

    self_link, self_source, _counterparts, _ordinary = _transfer_vault(
        tmp_path / "self")
    self_link.ledger.append(transfer_linked(
        self_source, self_source, "verified", {}, "2026-03-08", by="human"))
    self_row = next(item for item in activity(self_link.ledger.projection())["items"]
                    if item["id"] == self_source)
    assert self_row["transfer"] == {"state": "none"}
    assert "unlink_transfer" not in self_row["actions"]


@pytest.mark.parametrize(("grade", "by", "evidence"), [
    ("unverified", "model", {}),
    ("verified", "auto", {"decided_by": "named_account"}),
    ("corroborated", "human", {}),
    ("corroborated", "auto", {}),
    ("corroborated", "auto", {"decided_by": "invented_rule"}),
    ("verified", "human", {"decided_by": "named_account"}),
])
def test_unsupported_link_provenance_cannot_claim_evidence_or_authorize_unlink(
        tmp_path, grade, by, evidence):
    vault, source, counterparts, _ordinary = _transfer_vault(tmp_path)
    vault.ledger.append(transfer_linked(
        source, counterparts[0], grade, evidence, "2026-03-08", by=by))

    rows = {item["id"]: item
            for item in activity(vault.ledger.projection())["items"]}
    assert rows[source]["transfer"] == {"state": "none"}
    assert rows[counterparts[0]]["transfer"] == {"state": "none"}
    assert "unlink_transfer" not in rows[source]["actions"]
    assert "corroborating transfer evidence" not in str(rows[source])
    before = len(list(vault.events()))
    assert ActivityActions(vault).unlink_transfer({
        "movement_key": source,
        "counterpart_key": counterparts[0]})["kind"] == "stale"
    assert len(list(vault.events())) == before


def test_category_action_appends_one_verified_movement_overlay_and_replays(tmp_path):
    vault = _vault(tmp_path)
    first, target = vault.ledger.projection().movements()
    assign_category(vault.ledger, first.key, "groceries")
    before = len(_events(vault, "CategoryAssigned"))

    outcome = ActivityActions(vault).assign_category(
        {"movement_key": target.key, "category_id": "groceries"})

    assert outcome["kind"] == "completed"
    assert outcome["state"] is None, "actions do not bundle a private partial read"
    assert set(outcome) == {"kind", "message", "state", "reason"}
    assert len(_events(vault, "CategoryAssigned")) == before + 1
    written = vault.ledger.projection().category_of(target.key)
    assert written["category"] == "groceries"
    assert written["grade"] == "unverified"
    assert written["category_grade"] == "verified"
    assert written["subcategory_grade"] == "unverified"
    assert not written.get("nature"), "category correction cannot smuggle nature"
    replayed = LedgerProjection(vault.events())
    assert replayed.category_of(target.key)["category"] == "groceries"


def test_meaning_action_turns_one_outflow_into_a_named_loan_receivable(tmp_path):
    vault = _vault(tmp_path)
    target = vault.ledger.projection().movements()[0]

    outcome = ActivityActions(vault).assign_meaning({
        "movement_key": target.key,
        "meaning": "loan",
        "counterparty": "Sam",
    })

    assert outcome["kind"] == "completed"
    projection = vault.ledger.projection()
    corrected = next(item for item in projection.movements()
                     if item.key == target.key)
    assert corrected.nature == "transfer"
    assert corrected.ruling_account == "Assets:Loans:Sam"
    assert projection.derived_category(corrected)["category"] == "transfers"
    corrected_row = next(item for item in activity(projection)["items"]
                         if item["id"] == target.key)
    assert corrected_row["treatment"] == {"kind": "loan", "name": "Sam"}
    assert not any(event.event_type == "AccountOpened"
                   and event.body.get("account_id") == "Assets:Loans:Sam"
                   for event in vault.events())


def test_recorrecting_a_loan_as_spending_replaces_its_transfer_filing(tmp_path):
    vault = _vault(tmp_path)
    target = vault.ledger.projection().movements()[0]
    actions = ActivityActions(vault)
    assert actions.assign_meaning({
        "movement_key": target.key, "meaning": "loan",
        "counterparty": "Sam"})["kind"] == "completed"

    outcome = actions.assign_meaning({
        "movement_key": target.key, "meaning": "spending",
        "counterparty": ""})

    assert outcome["kind"] == "completed"
    projection = vault.ledger.projection()
    corrected = next(item for item in projection.movements()
                     if item.key == target.key)
    assert corrected.nature == "spending"
    assert corrected.ruling_account == ""
    assert projection.derived_category(corrected)["category"] == "other"
    assert "transfers" not in projection.spending_by_category()


def test_meaning_action_requires_a_name_for_a_loan(tmp_path):
    vault = _vault(tmp_path)
    target = vault.ledger.projection().movements()[0]

    outcome = ActivityActions(vault).assign_meaning({
        "movement_key": target.key,
        "meaning": "loan",
        "counterparty": "",
    })

    assert outcome["kind"] == "refused"
    assert outcome["reason"] == "movement_meaning_invalid"


def test_meaning_action_refuses_impossible_direction_and_unbacked_repayment(
        tmp_path):
    vault, outgoing, incoming, _ordinary = _transfer_vault(tmp_path)
    incoming = incoming[0]
    actions = ActivityActions(vault)
    before = len(list(vault.events()))

    requests = [
        {"movement_key": incoming, "meaning": "spending", "counterparty": ""},
        {"movement_key": incoming, "meaning": "loan", "counterparty": "Sam"},
        {"movement_key": outgoing, "meaning": "loan_repayment",
         "counterparty": "Sam"},
        {"movement_key": incoming, "meaning": "loan_repayment",
         "counterparty": "Sam"},
    ]

    assert [actions.assign_meaning(request)["kind"] for request in requests] == [
        "refused", "refused", "refused", "refused"]
    assert len(list(vault.events())) == before


def test_meaning_action_accepts_repayment_only_after_matching_principal(tmp_path):
    vault, outgoing, incoming, _ordinary = _transfer_vault(tmp_path)
    actions = ActivityActions(vault)

    lent = actions.assign_meaning({
        "movement_key": outgoing, "meaning": "loan", "counterparty": "Sam"})
    repaid = actions.assign_meaning({
        "movement_key": incoming[0], "meaning": "loan_repayment",
        "counterparty": "Sam"})

    assert lent["kind"] == "completed"
    assert repaid["kind"] == "completed"
    rows = {row["id"]: row for row in activity(vault.ledger.projection())["items"]}
    assert rows[outgoing]["treatment"] == {"kind": "loan", "name": "Sam"}
    assert rows[incoming[0]]["treatment"] == {
        "kind": "loan_repayment", "name": "Sam"}


def test_repayment_is_not_advertised_before_the_principal_was_lent(tmp_path):
    vault = Vault.open(tmp_path / "dated-loan-vault", "pw")
    vault.ledger.append(account_opened(
        "acct:checking", "depository", "Checking", "USD", "2026-01-01",
        account_number="1122"))
    vault.ledger.append(simple_transaction(
        "acct:checking", "100.00", "early incoming", "2026-01-01"))
    vault.ledger.append(simple_transaction(
        "acct:checking", "-100.00", "later loan", "2026-01-10"))
    movements = {movement.description: movement.key
                 for movement in vault.ledger.projection().movements()}
    actions = ActivityActions(vault)
    assert actions.assign_meaning({
        "movement_key": movements["later loan"],
        "meaning": "loan",
        "counterparty": "Sam",
    })["kind"] == "completed"

    row = next(item for item in activity(vault.ledger.projection())["items"]
               if item["id"] == movements["early incoming"])
    refused = actions.assign_meaning({
        "movement_key": movements["early incoming"],
        "meaning": "loan_repayment",
        "counterparty": "Sam",
    })

    assert row["loan_repayment_choices"] == []
    assert "assign_meaning" not in row["actions"]
    assert refused["kind"] == "refused"
    assert refused["reason"] == "no_matching_open_loan"
    assert refused["state"] is None


def test_tag_replacement_removes_by_one_append_survives_replay_and_keeps_partition(tmp_path):
    vault = _vault(tmp_path)
    target = vault.ledger.projection().movements()[0]
    assign_category(vault.ledger, target.key, "groceries")
    tag_movement(vault.ledger, target.key, ["japan", "shared"])
    before_category = vault.ledger.projection().spending_by_category()
    before = len(_events(vault, "MovementTagged"))

    outcome = ActivityActions(vault).replace_tags(
        {"movement_key": target.key, "tag_ids": ["japan"]})

    assert outcome["kind"] == "completed"
    assert outcome["state"] is None, "the desktop must request the full fresh read"
    assert len(_events(vault, "MovementTagged")) == before + 1
    assert vault.ledger.projection().tags_of(target) == ["japan"]
    assert vault.ledger.projection().spending_by_category() == before_category
    replayed = LedgerProjection(vault.events())
    replayed_target = next(item for item in replayed.movements() if item.key == target.key)
    assert replayed.tags_of(replayed_target) == ["japan"]


def test_compound_classification_assigns_the_exact_selection_atomically(tmp_path):
    vault = _vault(tmp_path)
    first, second = vault.ledger.projection().movements()
    before = len(_events(vault, "CategoryAssigned"))

    outcome = ActivityActions(vault).assign_classification({
        "movement_ids": [second.key],
        "category_id": " Groceries ",
        "subcategory_id": "SuperMarket",
    })

    assert outcome["kind"] == "completed"
    assert len(_events(vault, "CategoryAssigned")) == before + 1
    projection = vault.ledger.projection()
    assert projection.category_of(first.key)["by"] == "default"
    written = projection.category_of(second.key)
    assert written["category"] == "groceries"
    assert written["subcategory"] == "supermarket"
    assert written["grade"] == "verified"
    assert written["by"] == "human"
    row = next(item for item in activity(projection)["items"]
               if item["id"] == second.key)
    assert row["category"]["id"] == "groceries"
    assert row["subcategory"]["id"] == "supermarket"
    replayed = LedgerProjection(vault.events())
    assert replayed.category_of(second.key)["subcategory"] == "supermarket"


def test_compound_classification_can_assign_many_without_generalizing_a_merchant(
        tmp_path):
    vault = _vault(tmp_path)
    movements = vault.ledger.projection().movements()
    keys = [movement.key for movement in movements]

    outcome = ActivityActions(vault).assign_classification({
        "movement_ids": keys,
        "category_id": "dining",
        "subcategory_id": "restaurant",
    })

    assert outcome["kind"] == "completed"
    assert len(_events(vault, "CategoryAssigned")) == 2 * len(keys)
    projection = vault.ledger.projection()
    assert all(projection.category_of(key)["subcategory"] == "restaurant"
               for key in keys)
    assert not _events(vault, "MerchantCategorized")
    assert not _events(vault, "MerchantEnriched")


def test_matching_merchant_inheritance_still_records_the_exact_movement(tmp_path):
    vault = _vault(tmp_path)
    first = vault.ledger.projection().movements()[0]
    merchant = vault.ledger.projection().merchant_key_of(first)
    vault.ledger.append(merchant_enriched(
        merchant, "groceries", subcategory="supermarket", grade=VERIFIED,
        occurred_at="2026-03-07", by="human"))
    assert vault.ledger.projection().category_of(first.key)["by"] == "default"
    before = len(_events(vault, "CategoryAssigned"))

    outcome = ActivityActions(vault).assign_classification({
        "movement_ids": [first.key],
        "category_id": "groceries",
        "subcategory_id": "supermarket",
    })

    assert outcome["kind"] == "completed"
    assert len(_events(vault, "CategoryAssigned")) == before + 1
    assert vault.ledger.projection().category_of(first.key)["subcategory"] == \
        "supermarket"


def test_catalog_only_custom_pair_is_valid_for_an_exact_movement(tmp_path):
    vault = _vault(tmp_path)
    first = vault.ledger.projection().movements()[0]
    vault.ledger.append(merchant_enriched(
        "catalog-only-merchant", "Household Spending",
        subcategory="Artisan Market", occurred_at="2026-03-07"))

    outcome = ActivityActions(vault).assign_classification({
        "movement_ids": [first.key],
        "category_id": "HOUSEHOLD SPENDING",
        "subcategory_id": "Artisan-Market",
    })

    assert outcome["kind"] == "completed"
    written = vault.ledger.projection().category_of(first.key)
    assert (written["category"], written["subcategory"]) == (
        "household spending", "artisan market")


def test_subcategory_alias_repeat_is_a_canonical_movement_noop(tmp_path):
    vault = _vault(tmp_path)
    first = vault.ledger.projection().movements()[0]
    actions = ActivityActions(vault)
    assert actions.assign_classification({
        "movement_ids": [first.key],
        "category_id": "groceries",
        "subcategory_id": "supermarket",
    })["kind"] == "completed"
    rule_category_same_as(vault.ledger, "supermarket", "grocery store")
    before = len(_events(vault, "CategoryAssigned"))

    repeated = actions.assign_classification({
        "movement_ids": [first.key],
        "category_id": "groceries",
        "subcategory_id": "supermarket",
    })

    assert repeated["kind"] == "completed"
    assert len(_events(vault, "CategoryAssigned")) == before
    effective = vault.ledger.projection().derived_category(first)
    assert effective["subcategory"] == "grocery store"


def test_category_alias_is_applied_to_pair_validation_and_the_written_overlay(
        tmp_path):
    vault = _vault(tmp_path)
    first = vault.ledger.projection().movements()[0]
    vault.ledger.append(merchant_enriched(
        "catalog-only-merchant", "household spending",
        subcategory="artisan market", occurred_at="2026-03-07"))
    rule_category_same_as(vault.ledger, "household spending", "home costs")

    outcome = ActivityActions(vault).assign_classification({
        "movement_ids": [first.key],
        "category_id": "household spending",
        "subcategory_id": "artisan market",
    })

    assert outcome["kind"] == "completed"
    written = vault.ledger.projection().category_of(first.key)
    assert written["category"] == "home costs"
    assert written["subcategory"] == "artisan market"


def test_historical_mixed_case_category_alias_resolves_to_canonical_target(
        tmp_path):
    vault = _vault(tmp_path)
    first = vault.ledger.projection().movements()[0]
    vault.ledger.append(merchant_enriched(
        "catalog-only-merchant", "HOUSEHOLD SPENDING",
        subcategory="Artisan Market", occurred_at="2026-03-07"))
    vault.ledger.append(ruling_recorded(
        SCOPE_CATEGORY, "Household Spending", "2026-03-08",
        same_as="HOME COSTS"))

    outcome = ActivityActions(vault).assign_classification({
        "movement_ids": [first.key],
        "category_id": "HOUSEHOLD SPENDING",
        "subcategory_id": "ARTISAN-MARKET",
    })

    assert outcome["kind"] == "completed"
    written = vault.ledger.projection().category_of(first.key)
    assert (written["category"], written["subcategory"]) == (
        "home costs", "artisan market")


def test_historical_case_only_category_alias_is_a_noop_not_a_cycle(tmp_path):
    vault = _vault(tmp_path)
    first = vault.ledger.projection().movements()[0]
    actions = ActivityActions(vault)
    vault.ledger.append(ruling_recorded(
        SCOPE_CATEGORY, "Groceries", "2026-03-08", same_as="GROCERIES"))

    outcome = actions.assign_classification({
        "movement_ids": [first.key], "category_id": "GROCERIES",
        "subcategory_id": "supermarket",
    })
    before_repeat = len(_events(vault, "CategoryAssigned"))
    repeated = actions.assign_classification({
        "movement_ids": [first.key], "category_id": "groceries",
        "subcategory_id": "supermarket",
    })

    assert outcome["kind"] == "completed"
    assert repeated["kind"] == "completed"
    assert len(_events(vault, "CategoryAssigned")) == before_repeat
    written = vault.ledger.projection().category_of(first.key)
    assert (written["category"], written["subcategory"]) == (
        "groceries", "supermarket")


def test_historical_mixed_case_subcategory_alias_resolves_to_canonical_target(
        tmp_path):
    vault = _vault(tmp_path)
    first = vault.ledger.projection().movements()[0]
    vault.ledger.append(ruling_recorded(
        SCOPE_CATEGORY, "SuperMarket", "2026-03-08",
        same_as="GROCERY STORE"))

    outcome = ActivityActions(vault).assign_classification({
        "movement_ids": [first.key], "category_id": "GROCERIES",
        "subcategory_id": "SUPERMARKET",
    })

    assert outcome["kind"] == "completed"
    written = vault.ledger.projection().category_of(first.key)
    assert (written["category"], written["subcategory"]) == (
        "groceries", "grocery store")


def test_historical_separator_only_subcategory_alias_is_not_a_cycle(tmp_path):
    vault = _vault(tmp_path)
    first = vault.ledger.projection().movements()[0]
    actions = ActivityActions(vault)
    vault.ledger.append(merchant_enriched(
        "catalog-only-merchant", "groceries", subcategory="market stall",
        occurred_at="2026-03-07"))
    vault.ledger.append(ruling_recorded(
        SCOPE_CATEGORY, "market-stall", "2026-03-08",
        same_as="market stall"))

    outcome = actions.assign_classification({
        "movement_ids": [first.key], "category_id": "groceries",
        "subcategory_id": "market_stall",
    })
    before_repeat = len(_events(vault, "CategoryAssigned"))
    repeated = actions.assign_classification({
        "movement_ids": [first.key], "category_id": "groceries",
        "subcategory_id": "market-stall",
    })

    assert outcome["kind"] == "completed"
    assert repeated["kind"] == "completed"
    assert len(_events(vault, "CategoryAssigned")) == before_repeat
    written = vault.ledger.projection().category_of(first.key)
    assert (written["category"], written["subcategory"]) == (
        "groceries", "market stall")


def test_classification_alias_cycles_and_normalized_collisions_are_refused(
        tmp_path):
    vault = _vault(tmp_path)
    first = vault.ledger.projection().movements()[0]
    actions = ActivityActions(vault)
    rule_category_same_as(vault.ledger, "cycle a", "cycle b")
    rule_category_same_as(vault.ledger, "cycle b", "cycle a")
    before_cycle = len(list(vault.events()))

    cycle = actions.assign_classification({
        "movement_ids": [first.key], "category_id": "cycle a",
        "subcategory_id": "anything",
    })
    assert cycle["kind"] == "refused"
    assert cycle["reason"] == "classification_alias_ambiguous"
    assert len(list(vault.events())) == before_cycle

    vault.ledger.append(ruling_recorded(
        SCOPE_CATEGORY, "Collision Parent", "2026-03-08",
        same_as="one parent"))
    vault.ledger.append(ruling_recorded(
        SCOPE_CATEGORY, "collision parent", "2026-03-09",
        same_as="another parent"))
    before_collision = len(list(vault.events()))
    collision = actions.assign_classification({
        "movement_ids": [first.key], "category_id": "collision parent",
        "subcategory_id": "anything",
    })
    assert collision["kind"] == "refused"
    assert collision["reason"] == "classification_alias_ambiguous"
    assert len(list(vault.events())) == before_collision


def test_subcategory_alias_cycles_and_identity_collisions_are_refused(
        tmp_path):
    vault = _vault(tmp_path)
    first = vault.ledger.projection().movements()[0]
    actions = ActivityActions(vault)
    rule_category_same_as(vault.ledger, "child a", "child b")
    rule_category_same_as(vault.ledger, "child b", "child a")
    before_cycle = len(list(vault.events()))

    cycle = actions.assign_classification({
        "movement_ids": [first.key], "category_id": "groceries",
        "subcategory_id": "child a",
    })
    assert cycle["kind"] == "refused"
    assert cycle["reason"] == "classification_alias_ambiguous"
    assert len(list(vault.events())) == before_cycle

    vault.ledger.append(ruling_recorded(
        SCOPE_CATEGORY, "Collision_Sub", "2026-03-08",
        same_as="first child"))
    vault.ledger.append(ruling_recorded(
        SCOPE_CATEGORY, "collision-sub", "2026-03-09",
        same_as="second child"))
    before_collision = len(list(vault.events()))

    collision = actions.assign_classification({
        "movement_ids": [first.key], "category_id": "groceries",
        "subcategory_id": "collision sub",
    })
    assert collision["kind"] == "refused"
    assert collision["reason"] == "classification_alias_ambiguous"
    assert len(list(vault.events())) == before_collision


def test_compound_classification_rejects_wrong_parent_and_stale_batch_without_writes(
        tmp_path):
    vault = _vault(tmp_path)
    first, second = vault.ledger.projection().movements()
    actions = ActivityActions(vault)
    before = len(list(vault.events()))

    wrong_parent = actions.assign_classification({
        "movement_ids": [first.key, second.key],
        "category_id": "dining",
        "subcategory_id": "supermarket",
    })
    stale = actions.assign_classification({
        "movement_ids": [first.key, "missing-movement"],
        "category_id": "groceries",
        "subcategory_id": "supermarket",
    })

    assert wrong_parent["kind"] == "refused"
    assert wrong_parent["reason"] == "invalid_category_subcategory_pair"
    assert stale["kind"] == "stale"
    assert stale["reason"] == "movement_selection_stale"
    assert len(list(vault.events())) == before


def test_compound_classification_prepares_the_whole_batch_before_append(
        tmp_path, monkeypatch):
    vault = _vault(tmp_path)
    movement_ids = [movement.key
                    for movement in vault.ledger.projection().movements()]
    module = import_module("viva.desktop_bridge.activity_actions")
    real_factory = module.category_assigned
    calls = 0

    def fail_on_second(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("synthetic second-event failure")
        return real_factory(*args, **kwargs)

    monkeypatch.setattr(module, "category_assigned", fail_on_second)
    before = len(list(vault.events()))

    with pytest.raises(RuntimeError, match="second-event"):
        ActivityActions(vault).assign_classification({
            "movement_ids": movement_ids,
            "category_id": "groceries",
            "subcategory_id": "supermarket",
        })

    assert len(list(vault.events())) == before


def test_classification_durable_prefix_failure_commits_none_and_stays_none(
        tmp_path, monkeypatch):
    vault = _vault(tmp_path)
    movement_ids = [movement.key
                    for movement in vault.ledger.projection().movements()]
    _fail_after_durable_first_batch_line(monkeypatch)

    with pytest.raises(OSError, match="durable first-line"):
        ActivityActions(vault).assign_classification({
            "movement_ids": movement_ids,
            "category_id": "groceries",
            "subcategory_id": "supermarket",
        })

    assert all(vault.ledger.projection().category_of(key)["by"] == "default"
               for key in movement_ids)
    reopened = Vault.open(vault.directory, "pw")
    assert all(reopened.ledger.projection().category_of(key)["by"] == "default"
               for key in movement_ids)
    reopened.ledger.append(account_opened(
        "sentinel", "depository", "Sentinel", "USD", "2026-04-02"))
    replayed = Vault.open(vault.directory, "pw").ledger.projection()
    assert all(replayed.category_of(key)["by"] == "default"
               for key in movement_ids)


def test_batch_tag_add_remove_preserves_unrelated_tags_and_normalizes_case(tmp_path):
    vault = _vault(tmp_path)
    first, second = vault.ledger.projection().movements()
    tag_movement(vault.ledger, first.key, ["Trip", "tax"])
    tag_movement(vault.ledger, second.key, ["family"])
    actions = ActivityActions(vault)

    added = actions.add_tags({
        "movement_ids": [first.key, second.key],
        "tag_ids": [" WORK ", "trip"],
    })
    after_add = vault.ledger.projection()
    added_movements = {movement.key: movement for movement in after_add.movements()}

    assert added["kind"] == "completed"
    assert after_add.movement_tags_of(added_movements[first.key]) == [
        "tax", "trip", "work"]
    assert after_add.movement_tags_of(added_movements[second.key]) == [
        "family", "trip", "work"]

    removed = actions.remove_tags({
        "movement_ids": [first.key, second.key],
        "tag_ids": ["TrIp"],
    })
    after_remove = vault.ledger.projection()
    removed_movements = {movement.key: movement
                         for movement in after_remove.movements()}

    assert removed["kind"] == "completed"
    assert after_remove.movement_tags_of(removed_movements[first.key]) == [
        "tax", "work"]
    assert after_remove.movement_tags_of(removed_movements[second.key]) == [
        "family", "work"]


def test_batch_tag_commands_are_repeatable_and_one_stale_id_rolls_back_all(tmp_path):
    vault = _vault(tmp_path)
    first, second = vault.ledger.projection().movements()
    tag_movement(vault.ledger, first.key, ["held"])
    actions = ActivityActions(vault)

    assert actions.add_tags({
        "movement_ids": [first.key], "tag_ids": ["held"]})["kind"] == "completed"
    unchanged = len(list(vault.events()))
    stale = actions.add_tags({
        "movement_ids": [first.key, "missing-movement"],
        "tag_ids": ["new"],
    })

    assert stale["kind"] == "stale"
    assert stale["reason"] == "movement_selection_stale"
    assert len(list(vault.events())) == unchanged
    projection = vault.ledger.projection()
    movements = {movement.key: movement for movement in projection.movements()}
    assert projection.movement_tags_of(movements[first.key]) == ["held"]
    assert projection.movement_tags_of(movements[second.key]) == []


def test_batch_tags_decide_from_the_locked_fresh_projection(
        tmp_path, monkeypatch):
    vault = _vault(tmp_path)
    first, second = vault.ledger.projection().movements()
    external = vault.ledger.fork()
    append_atomically = vault.ledger.append_atomically
    calls = 0

    def append_after_external_write(decide):
        nonlocal calls
        calls += 1
        tag_movement(external, first.key, ["externally-added"])
        return append_atomically(decide)

    monkeypatch.setattr(
        vault.ledger, "append_atomically", append_after_external_write)

    outcome = ActivityActions(vault).add_tags({
        "movement_ids": [first.key, second.key],
        "tag_ids": ["requested"],
    })

    projection = vault.ledger.projection()
    movements = {movement.key: movement for movement in projection.movements()}
    assert outcome["kind"] == "completed"
    assert calls == 1
    assert projection.movement_tags_of(movements[first.key]) == [
        "externally-added", "requested"]
    assert projection.movement_tags_of(movements[second.key]) == ["requested"]


def test_batch_tags_prepare_every_event_before_the_atomic_append(
        tmp_path, monkeypatch):
    vault = _vault(tmp_path)
    movement_ids = [movement.key
                    for movement in vault.ledger.projection().movements()]
    module = import_module("viva.desktop_bridge.activity_actions")
    real_factory = module.movement_tagged
    calls = 0

    def fail_on_second(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("synthetic second-tag-event failure")
        return real_factory(*args, **kwargs)

    monkeypatch.setattr(module, "movement_tagged", fail_on_second)
    before = len(list(vault.events()))

    with pytest.raises(RuntimeError, match="second-tag-event"):
        ActivityActions(vault).add_tags({
            "movement_ids": movement_ids,
            "tag_ids": ["requested"],
        })

    assert len(list(vault.events())) == before


def test_add_tags_durable_prefix_failure_commits_none_and_stays_none(
        tmp_path, monkeypatch):
    vault = _vault(tmp_path)
    movement_ids = [movement.key
                    for movement in vault.ledger.projection().movements()]
    _fail_after_durable_first_batch_line(monkeypatch)

    with pytest.raises(OSError, match="durable first-line"):
        ActivityActions(vault).add_tags({
            "movement_ids": movement_ids, "tag_ids": ["trip"]})

    projection = vault.ledger.projection()
    assert all(projection.movement_tags_of(movement) == []
               for movement in projection.movements())
    reopened = Vault.open(vault.directory, "pw")
    assert all(reopened.ledger.projection().movement_tags_of(movement) == []
               for movement in reopened.ledger.projection().movements())
    reopened.ledger.append(account_opened(
        "sentinel", "depository", "Sentinel", "USD", "2026-04-02"))
    replayed = Vault.open(vault.directory, "pw").ledger.projection()
    assert all(replayed.movement_tags_of(movement) == []
               for movement in replayed.movements()
               if movement.key in movement_ids)


def test_remove_tags_durable_prefix_failure_commits_none_and_stays_none(
        tmp_path, monkeypatch):
    vault = _vault(tmp_path)
    movements = vault.ledger.projection().movements()
    movement_ids = [movement.key for movement in movements]
    for movement_id in movement_ids:
        tag_movement(vault.ledger, movement_id, ["held"])
    _fail_after_durable_first_batch_line(monkeypatch)

    with pytest.raises(OSError, match="durable first-line"):
        ActivityActions(vault).remove_tags({
            "movement_ids": movement_ids, "tag_ids": ["held"]})

    projection = vault.ledger.projection()
    assert all(projection.movement_tags_of(movement) == ["held"]
               for movement in projection.movements())
    reopened = Vault.open(vault.directory, "pw")
    assert all(reopened.ledger.projection().movement_tags_of(movement) == ["held"]
               for movement in reopened.ledger.projection().movements())
    reopened.ledger.append(account_opened(
        "sentinel", "depository", "Sentinel", "USD", "2026-04-02"))
    replayed = Vault.open(vault.directory, "pw").ledger.projection()
    assert all(replayed.movement_tags_of(movement) == ["held"]
               for movement in replayed.movements()
               if movement.key in movement_ids)


def test_batch_requests_reject_duplicate_empty_and_out_of_bounds_inputs(tmp_path):
    vault = _vault(tmp_path)
    first = vault.ledger.projection().movements()[0]
    actions = ActivityActions(vault)
    before = len(list(vault.events()))
    invalid = [
        lambda: actions.add_tags({"movement_ids": [], "tag_ids": ["one"]}),
        lambda: actions.add_tags({
            "movement_ids": [" padded-movement-id "], "tag_ids": ["one"]}),
        lambda: actions.add_tags({
            "movement_ids": [first.key, first.key], "tag_ids": ["one"]}),
        lambda: actions.add_tags({
            "movement_ids": [first.key], "tag_ids": ["Trip", "trip"]}),
        lambda: actions.remove_tags({
            "movement_ids": [first.key], "tag_ids": []}),
        lambda: actions.add_tags({
            "movement_ids": [first.key], "tag_ids": ["x" * 81]}),
        lambda: actions.add_tags({
            "movement_ids": [first.key],
            "tag_ids": [f"tag-{index}" for index in range(41)]}),
        lambda: actions.add_tags({
            "movement_ids": [f"missing-{index}" for index in range(101)],
            "tag_ids": ["one"]}),
    ]

    for call in invalid:
        with pytest.raises(BridgeRequestError):
            call()
    assert len(list(vault.events())) == before


def test_batch_tag_identity_refuses_two_aliases_of_one_tag_atomically(tmp_path):
    vault = _vault(tmp_path)
    first, second = vault.ledger.projection().movements()
    rule_tag_same_as(vault.ledger, "journey", "trip")
    before = len(list(vault.events()))

    outcome = ActivityActions(vault).add_tags({
        "movement_ids": [first.key, second.key],
        "tag_ids": ["journey", "trip"],
    })

    assert outcome["kind"] == "refused"
    assert outcome["reason"] == "duplicate_tag_ids"
    assert len(list(vault.events())) == before


def test_historical_mixed_case_tag_alias_resolves_to_canonical_target(tmp_path):
    vault = _vault(tmp_path)
    first = vault.ledger.projection().movements()[0]
    vault.ledger.append(ruling_recorded(
        SCOPE_TAG, "Trip", "2026-03-08", same_as="JOURNEY"))

    outcome = ActivityActions(vault).add_tags({
        "movement_ids": [first.key], "tag_ids": ["TRIP"]})

    assert outcome["kind"] == "completed"
    movement = next(item for item in vault.ledger.projection().movements()
                    if item.key == first.key)
    assert vault.ledger.projection().movement_tags_of(movement) == ["journey"]


def test_historical_case_only_tag_alias_is_a_noop_not_a_cycle(tmp_path):
    vault = _vault(tmp_path)
    first = vault.ledger.projection().movements()[0]
    actions = ActivityActions(vault)
    vault.ledger.append(ruling_recorded(
        SCOPE_TAG, "Trip", "2026-03-08", same_as="TRIP"))

    outcome = actions.add_tags({
        "movement_ids": [first.key], "tag_ids": ["TRIP"]})
    before_repeat = len(_events(vault, "MovementTagged"))
    repeated = actions.add_tags({
        "movement_ids": [first.key], "tag_ids": ["trip"]})

    assert outcome["kind"] == "completed"
    assert repeated["kind"] == "completed"
    assert len(_events(vault, "MovementTagged")) == before_repeat
    movement = next(item for item in vault.ledger.projection().movements()
                    if item.key == first.key)
    assert vault.ledger.projection().movement_tags_of(movement) == ["trip"]


def test_historical_tag_alias_collision_and_cycle_are_refused_atomically(
        tmp_path):
    vault = _vault(tmp_path)
    first = vault.ledger.projection().movements()[0]
    actions = ActivityActions(vault)
    vault.ledger.append(ruling_recorded(
        SCOPE_TAG, "Trip", "2026-03-08", same_as="journey"))
    vault.ledger.append(ruling_recorded(
        SCOPE_TAG, "trip", "2026-03-09", same_as="vacation"))
    before_collision = len(list(vault.events()))

    collision = actions.add_tags({
        "movement_ids": [first.key], "tag_ids": ["trip"]})

    assert collision["kind"] == "refused"
    assert collision["reason"] == "tag_alias_ambiguous"
    assert len(list(vault.events())) == before_collision

    vault.ledger.append(ruling_recorded(
        SCOPE_TAG, "cycle a", "2026-03-10", same_as="cycle b"))
    vault.ledger.append(ruling_recorded(
        SCOPE_TAG, "cycle b", "2026-03-11", same_as="cycle a"))
    before_cycle = len(list(vault.events()))

    cycle = actions.add_tags({
        "movement_ids": [first.key], "tag_ids": ["cycle a"]})

    assert cycle["kind"] == "refused"
    assert cycle["reason"] == "tag_alias_ambiguous"
    assert len(list(vault.events())) == before_cycle


def test_batch_tag_alias_cannot_expand_past_the_written_length_bound(tmp_path):
    vault = _vault(tmp_path)
    first, second = vault.ledger.projection().movements()
    rule_tag_same_as(vault.ledger, "short", "x" * 81)
    before = len(list(vault.events()))

    outcome = ActivityActions(vault).add_tags({
        "movement_ids": [first.key, second.key],
        "tag_ids": ["short"],
    })

    assert outcome["kind"] == "refused"
    assert outcome["reason"] == "tag_label_out_of_bounds"
    assert len(list(vault.events())) == before


def test_batch_remove_refuses_an_inherited_tag_without_touching_any_selection(
        tmp_path):
    vault = _vault(tmp_path)
    first, second = vault.ledger.projection().movements()
    merchant = vault.ledger.projection().merchant_key_of(first)
    tag_merchant(vault.ledger, merchant, ["merchant-wide"])
    tag_movement(vault.ledger, second.key, ["merchant-wide", "private"])
    before = len(list(vault.events()))

    outcome = ActivityActions(vault).remove_tags({
        "movement_ids": [first.key, second.key],
        "tag_ids": ["merchant-wide"],
    })

    assert outcome["kind"] == "refused"
    assert outcome["reason"] == "inherited_tags_not_movement_scoped"
    assert len(list(vault.events())) == before


def test_confirm_transfer_writes_one_verified_link_survives_replay_and_is_idempotent(
        tmp_path):
    vault, source, counterparts, _ordinary = _transfer_vault(tmp_path)
    before = len(_events(vault, "TransferLinked"))

    outcome = ActivityActions(vault).confirm_transfer({
        "movement_key": source, "counterpart_key": counterparts[0]})

    assert outcome["kind"] == "completed"
    assert outcome["state"] is None
    assert set(outcome) == {"kind", "message", "state", "reason"}
    assert len(_events(vault, "TransferLinked")) == before + 1
    link = vault.ledger.projection().transfer_links()[0]
    assert link["grade"] == "verified"
    assert link["by"] == "human"
    assert {link["a"], link["b"]} == {source, counterparts[0]}
    replayed = LedgerProjection(vault.events())
    assert {source, counterparts[0]} <= replayed.linked_keys()
    linked_row = next(item for item in activity(vault.ledger.projection())["items"]
                      if item["id"] == source)
    assert linked_row["transfer"]["state"] == "linked"
    assert "unlink_transfer" in linked_row["actions"]

    after = len(list(vault.events()))
    duplicate = ActivityActions(vault).confirm_transfer({
        "movement_key": source, "counterpart_key": counterparts[0]})
    assert duplicate["kind"] == "stale"
    assert duplicate["reason"] == "transfer_state_changed"
    assert len(list(vault.events())) == after


def test_consumed_candidate_keeps_free_choice_actionable_and_preserves_other_pair(
        tmp_path):
    vault, source, counterparts, _ordinary = _transfer_vault(tmp_path, candidates=2)
    try:
        vault.ledger.append(account_opened(
            "acct:separate-source", "depository", "Reserve", "USD", "2026-03-01",
            account_number="3300"))
        vault.ledger.append(simple_transaction(
            "acct:separate-source", "-125.00", "reserve payment", "2026-03-05"))
        projection = vault.ledger.projection()
        separate_source = next(movement.key for movement in projection.movements()
                               if movement.description == "reserve payment")
        vault.ledger.append(transfer_linked(
            separate_source, counterparts[0], "verified", {"kind": "confirmed"},
            "2026-03-08", by="human"))
        projection = vault.ledger.projection()
        original_link = projection.transfer_links()[0]
        original_suggestion = projection.transfer_suggestions()[0]
        original_events = list(vault.events())
        balances = {account: projection.balance(account).amount
                    for account in projection.accounts()}
        assert original_suggestion["a"] == source
        assert original_suggestion["candidates"] == counterparts
        assert projection.linked_keys() == {separate_source, counterparts[0]}

        rows = {item["id"]: item for item in activity(projection)["items"]}
        transfer = rows[source]["transfer"]
        assert transfer["complete"] is True
        assert [candidate["id"] for candidate in transfer["candidates"]] == [
            counterparts[1]]
        assert {"confirm_transfer", "reject_transfer"} <= set(rows[source]["actions"])
        assert rows[counterparts[0]]["transfer"]["counterpart"]["id"] == separate_source

        outcome = ActivityActions(vault).confirm_transfer({
            "movement_key": source, "counterpart_key": counterparts[1]})
        assert outcome["kind"] == "completed"
        events = list(vault.events())
        assert events[:len(original_events)] == original_events
        assert len(events) == len(original_events) + 1
        assert events[-1].event_type == "TransferLinked"
        assert _events(vault, "TransferSuggested")[0] == next(
            event for event in original_events if event.event_type == "TransferSuggested")
        for current in (vault.ledger.projection(), LedgerProjection(events)):
            links = current.transfer_links()
            assert original_link in links
            new_link = next(link for link in links if source in {link["a"], link["b"]})
            assert {new_link["a"], new_link["b"]} == {source, counterparts[1]}
            assert new_link["by"] == "human"
            assert new_link["grade"] == "verified"
            assert len(links) == 2
            assert {account: current.balance(account).amount for account in balances} == balances
    finally:
        vault.close()


def _partly_consumed_transfer_vault(tmp_path):
    vault, source, candidates, _ordinary = _transfer_vault(tmp_path, candidates=3)
    vault.ledger.append(account_opened(
        "acct:reserve", "depository", "Reserve", "USD", "2026-03-01",
        account_number="3300"))
    vault.ledger.append(simple_transaction(
        "acct:reserve", "-125.00", "reserve payment", "2026-03-05"))
    other = next(movement.key for movement in vault.ledger.projection().movements()
                 if movement.description == "reserve payment")
    vault.ledger.append(transfer_linked(
        other, candidates[1], "verified", {}, "2026-03-08", by="human"))
    return vault, source, candidates, other


class _TransferProjectionOverride:
    def __init__(self, projection, **overrides):
        self.projection = projection
        self.overrides = overrides

    def __getattr__(self, name):
        if name in self.overrides:
            value = self.overrides[name]
            return value if callable(value) else lambda: value
        return getattr(self.projection, name)


def _transfer_read(projection, source):
    movement = next(item for item in projection.movements() if item.key == source)
    return import_module("viva.surface.activity")._transfer_state(
        projection, movement, "en-US")


def test_consumed_choice_is_stale_and_unlink_restores_original_order_and_history(tmp_path):
    vault, source, candidates, other = _partly_consumed_transfer_vault(tmp_path)
    try:
        original = list(vault.events())
        state, actions = _transfer_read(vault.ledger.projection(), source)
        assert state["complete"] is True
        assert [item["id"] for item in state["candidates"]] == [candidates[0], candidates[2]]
        assert actions == ["confirm_transfer", "reject_transfer"]
        assert ActivityActions(vault).confirm_transfer({
            "movement_key": source, "counterpart_key": candidates[1]})["kind"] == "stale"
        assert list(vault.events()) == original
        assert ActivityActions(vault).unlink_transfer({
            "movement_key": other, "counterpart_key": candidates[1]})["kind"] == "completed"
        restored_events = list(vault.events())
        assert restored_events[:len(original)] == original
        assert restored_events[-1].event_type == "TransferUnlinked"
        for projection in (vault.ledger.projection(), LedgerProjection(restored_events)):
            state, actions = _transfer_read(projection, source)
            assert state["complete"] is True
            assert [item["id"] for item in state["candidates"]] == candidates
            assert actions == ["confirm_transfer", "reject_transfer"]
            assert projection.transfer_suggestions()[0]["candidates"] == candidates
        path = tmp_path / "transfer-vault"
        vault.close()
        vault = Vault.open(path, "pw")
        state, actions = _transfer_read(vault.ledger.projection(), source)
        assert [item["id"] for item in state["candidates"]] == candidates
        assert actions == ["confirm_transfer", "reject_transfer"]
        assert list(vault.events()) == restored_events
    finally:
        vault.close()


@pytest.mark.parametrize("damage", [
    "unknown", "blank", "non-string", "duplicate", "self", "not-list",
    "source-linked", "source-flag", "candidate-flag", "candidate-key",
    "missing-link", "overlap", "self-link", "missing-endpoint", "unknown-origin",
    "endpoint-flag", "unseen-account", "currency", "amount", "date", "direction",
    "incomplete-reference", "pair-currency", "pair-amount", "pair-date",
])
def test_invalid_candidate_evidence_blocks_whole_question_beside_free_choices(tmp_path, damage):
    vault, source, candidates, other = _partly_consumed_transfer_vault(tmp_path)
    try:
        projection = vault.ledger.projection()
        movements = list(projection.movements())
        suggestions = [dict(projection.transfer_suggestions()[0])]
        suggestions[0]["candidates"] = list(candidates)
        links = [dict(item) for item in projection.transfer_links()]
        keys = set(projection.linked_keys())
        account_lookup = projection.account_info
        raw = suggestions[0]["candidates"]
        if damage == "unknown": raw.append("missing-movement")
        elif damage == "blank": raw.append(" ")
        elif damage == "non-string": raw.append(None)
        elif damage == "duplicate": raw.append(candidates[0])
        elif damage == "self": raw.append(source)
        elif damage == "not-list": suggestions[0]["candidates"] = tuple(raw)
        elif damage == "source-linked": keys.add(source)
        elif damage == "candidate-key": keys.remove(candidates[1])
        elif damage == "missing-link": links = []
        elif damage == "overlap": links.append(dict(links[0], a=candidates[0], b=other))
        elif damage == "self-link": links[0].update(a=candidates[1], b=candidates[1])
        elif damage == "missing-endpoint": links[0].update(a="missing-movement")
        elif damage == "unknown-origin": links[0].update(by="auto", grade="verified")
        elif damage == "unseen-account":
            account = next(item.account for item in movements if item.key == candidates[1])
            def account_lookup(identity):
                if identity == account:
                    raise LookupError("synthetic account is unseen")
                return projection.account_info(identity)
        else:
            target = source if damage == "source-flag" else (
                other if damage.startswith("pair-") or damage == "endpoint-flag" else candidates[1])
            changes = {
                "source-flag": {"linked": True}, "candidate-flag": {"linked": False},
                "endpoint-flag": {"linked": False}, "currency": {"currency": "EUR"},
                "amount": {"amount": Decimal("126")}, "date": {"date": "2026-04-01"},
                "direction": {"amount": Decimal("-125")},
                "incomplete-reference": {"description": ""},
                "pair-currency": {"currency": "EUR"}, "pair-amount": {"amount": Decimal("-126")},
                "pair-date": {"date": "2026-04-01"},
            }[damage]
            movements = [replace(item, **changes) if item.key == target else item
                         for item in movements]
        view = _TransferProjectionOverride(projection, movements=movements,
            transfer_suggestions=suggestions, transfer_links=links, linked_keys=keys,
            account_info=account_lookup)
        state, actions = _transfer_read(view, source)
        assert state.get("complete") is not True
        assert actions == []
    finally:
        vault.close()


@pytest.mark.parametrize("by,grade,evidence", [
    ("human", "verified", {}),
    *[("auto", "corroborated", {"decided_by": rule}) for rule in (
        "named_account", "named_account+printed_date", "account_ref_slot",
        "account_ref_slot+printed_date")],
])
def test_consumption_accepts_only_existing_recognized_origins(tmp_path, by, grade, evidence):
    vault, source, candidates, other = _partly_consumed_transfer_vault(tmp_path)
    try:
        projection = vault.ledger.projection()
        links = [dict(projection.transfer_links()[0], by=by, grade=grade,
                      decided_by=evidence.get("decided_by", ""))]
        state, actions = _transfer_read(_TransferProjectionOverride(
            projection, transfer_links=links), source)
        assert state["complete"] is True
        assert [item["id"] for item in state["candidates"]] == [candidates[0], candidates[2]]
        assert actions == ["confirm_transfer", "reject_transfer"]
    finally:
        vault.close()


def test_all_consumed_has_no_actions_and_raw_limit_precedes_filtering(tmp_path):
    vault, source, candidates, other = _partly_consumed_transfer_vault(tmp_path)
    try:
        projection = vault.ledger.projection()
        stored = dict(projection.transfer_suggestions()[0], candidates=[candidates[1]])
        state, actions = _transfer_read(_TransferProjectionOverride(
            projection, transfer_suggestions=[stored]), source)
        assert state["complete"] is False
        assert state["candidates"] == []
        assert actions == []

        class BoundedList(list):
            def __getitem__(self, index):
                assert isinstance(index, slice) and index.stop <= TRANSFER_CANDIDATE_LIMIT
                return super().__getitem__(index)

            def __iter__(self):
                raise AssertionError("oversized raw list must not be traversed")

        raw = BoundedList([candidates[1]] * TRANSFER_CANDIDATE_LIMIT + [candidates[0]])
        stored["candidates"] = raw
        state, actions = _transfer_read(_TransferProjectionOverride(
            projection, transfer_suggestions=[stored]), source)
        assert state["complete"] is False
        assert actions == []
    finally:
        vault.close()


def test_reject_partly_consumed_question_retains_other_pair_and_suggestion_history(tmp_path):
    vault, source, candidates, other = _partly_consumed_transfer_vault(tmp_path)
    try:
        original = list(vault.events())
        original_links = vault.ledger.projection().transfer_links()
        assert ActivityActions(vault).reject_transfer({"movement_key": source})["kind"] == "completed"
        events = list(vault.events())
        assert events[:len(original)] == original
        assert len(events) == len(original) + 1
        assert events[-1].event_type == "TransferUnlinked"
        for projection in (vault.ledger.projection(), LedgerProjection(events)):
            assert projection.transfer_links() == original_links
            assert projection.transfer_suggestions() == []
        assert len(_events(vault, "TransferSuggested")) == 1
    finally:
        vault.close()


@pytest.mark.parametrize("consumed", [False, True])
def test_transfer_current_and_historical_sql_match_complete_canonical_context(tmp_path, consumed):
    if consumed:
        vault, source, candidates, _other = _partly_consumed_transfer_vault(tmp_path)
        expected_candidates = [candidates[0], candidates[2]]
    else:
        vault, source, candidates, _ordinary = _transfer_vault(tmp_path, candidates=2)
        expected_candidates = candidates
    try:
        cutoff = "2026-03-31"
        canonical = activity(vault.ledger.projection_as_of(cutoff), "en-US")
        row = next(item for item in canonical["items"] if item["id"] == source)
        assert row["transfer"]["complete"] is True
        assert [item["id"] for item in row["transfer"]["candidates"]] == expected_candidates
        assert {"confirm_transfer", "reject_transfer"} <= set(row["actions"])
        canonical_identity = vault.ledger.store.authenticated_identity()
        assert canonical_identity[0] > 0 and canonical_identity[1]
        vault.synchronize_read_store()
        with vault.read_store.open_reader() as revision:
            published = vault.read_store.authenticated_source_identity(revision)
            assert (published["count"], published["head"]) == canonical_identity[:2]
            current = revision.activity_projection()
            historical = revision.historical_activity_projection(as_of=cutoff)
            assert source in {item.key for item in current.movements()}
            assert source in {item.key for item in historical.movements()}
            assert current.account_info("acct:source").account == "acct:source"
            assert historical.account_info("acct:source").account == "acct:source"
            assert not hasattr(historical, "accounts")
            assert activity(current, "en-US") == canonical
            assert activity(historical, "en-US") == canonical
    finally:
        vault.close()


@pytest.mark.parametrize("context", ["free", "linked", "missing-other-pair"])
def test_actual_account_ledger_context_presents_relationships_and_strips_actions(tmp_path, context):
    from viva.surface.account_ledger import sql_account_ledger_page

    if context == "missing-other-pair":
        vault, source, candidates, _other = _partly_consumed_transfer_vault(tmp_path)
    else:
        vault, source, candidates, _ordinary = _transfer_vault(
            tmp_path, linked=context == "linked")
    try:
        canonical_identity = vault.ledger.store.authenticated_identity()
        assert canonical_identity[0] > 0 and canonical_identity[1]
        vault.synchronize_read_store()
        with vault.read_store.open_reader() as revision:
            published = vault.read_store.authenticated_source_identity(revision)
            assert (published["count"], published["head"]) == canonical_identity[:2]
            parts = revision.account_ledger_page("acct:source", locale="en-US",
                cursor_secret=b"synthetic-account-ledger-secret!!")
            assert parts.info.account == "acct:source"
            assert parts.projection.account_info("acct:source").account == "acct:source"
            assert source in {item.key for item in parts.projection.movements()}
            assert not hasattr(parts.projection, "accounts")
            payload = sql_account_ledger_page(parts)
            row = next(item for group in payload["groups"] for item in group["movements"]
                       if item["id"] == source)
            assert row["actions"] == []
            if context == "free":
                assert row["transfer"]["complete"] is True
                assert [item["id"] for item in row["transfer"]["candidates"]] == candidates
            elif context == "linked":
                assert row["transfer"]["state"] == "linked"
                assert row["transfer"]["counterpart"]["id"] == candidates[0]
            else:
                assert row["transfer"]["state"] == "suggested"
                assert row["transfer"]["complete"] is False
                assert not parts.projection.transfer_links()
    finally:
        vault.close()


@pytest.mark.parametrize("endpoint", ["source", "candidate", "consuming-pair"])
@pytest.mark.parametrize("damage", ["unseen", "mismatch", "missing-identity", "unreadable"])
def test_transfer_account_lookup_requires_exact_readable_identity(tmp_path, endpoint, damage):
    from types import SimpleNamespace

    vault, source, candidates, other = _partly_consumed_transfer_vault(tmp_path)
    try:
        projection = vault.ledger.projection()
        key = {"source": source, "candidate": candidates[0], "consuming-pair": other}[endpoint]
        account = next(item.account for item in projection.movements() if item.key == key)
        def lookup(identity):
            info = projection.account_info(identity)
            if identity != account:
                return info
            if damage == "unseen":
                raise LookupError("synthetic account is unseen")
            if damage == "mismatch":
                return replace(info, account="acct:different")
            if damage == "missing-identity":
                return SimpleNamespace(name="Synthetic account", number="4400")
            return SimpleNamespace(account=identity)
        state, actions = _transfer_read(_TransferProjectionOverride(
            projection, account_info=lookup), source)
        assert state["complete"] is False
        assert actions == []
    finally:
        vault.close()


def test_reject_transfer_appends_history_dismisses_live_suggestion_and_replays(
        tmp_path):
    vault, source, _counterparts, _ordinary = _transfer_vault(tmp_path)

    outcome = ActivityActions(vault).reject_transfer({"movement_key": source})

    assert outcome["kind"] == "completed"
    assert outcome["state"] is None
    assert len(_events(vault, "TransferSuggested")) == 1
    assert len(_events(vault, "TransferUnlinked")) == 1
    assert vault.ledger.projection().transfer_suggestions() == []
    assert LedgerProjection(vault.events()).transfer_suggestions() == []

    after = len(list(vault.events()))
    assert ActivityActions(vault).reject_transfer(
        {"movement_key": source})["kind"] == "stale"
    assert len(list(vault.events())) == after


def test_unlink_transfer_appends_without_deleting_original_link_and_replays(tmp_path):
    vault, source, counterparts, _ordinary = _transfer_vault(tmp_path, linked=True)

    outcome = ActivityActions(vault).unlink_transfer({
        "movement_key": source, "counterpart_key": counterparts[0]})

    assert outcome["kind"] == "completed"
    assert outcome["state"] is None
    assert len(_events(vault, "TransferLinked")) == 1
    assert len(_events(vault, "TransferUnlinked")) == 1
    assert vault.ledger.projection().transfer_links() == []
    replayed = LedgerProjection(vault.events())
    assert replayed.transfer_links() == []

    after = len(list(vault.events()))
    assert ActivityActions(vault).unlink_transfer({
        "movement_key": source,
        "counterpart_key": counterparts[0]})["kind"] == "stale"
    assert len(list(vault.events())) == after


def test_transfer_actions_revalidate_exact_candidate_and_live_relationship(tmp_path):
    vault, source, counterparts, ordinary = _transfer_vault(tmp_path, candidates=2)
    actions = ActivityActions(vault)
    before = len(list(vault.events()))
    assert actions.confirm_transfer({
        "movement_key": source,
        "counterpart_key": ordinary})["kind"] == "stale"
    assert actions.unlink_transfer({
        "movement_key": source,
        "counterpart_key": counterparts[0]})["kind"] == "stale"
    assert len(list(vault.events())) == before

    # Evidence moved after display: a different actor linked the source. The
    # remembered confirmation may not append a second, unseen relationship.
    vault.ledger.append(transfer_linked(
        source, counterparts[1], "verified", {"kind": "confirmed"},
        "2026-03-08", by="human"))
    changed = len(list(vault.events()))
    assert actions.confirm_transfer({
        "movement_key": source,
        "counterpart_key": counterparts[0]})["kind"] == "stale"
    assert actions.unlink_transfer({
        "movement_key": source,
        "counterpart_key": counterparts[0]})["kind"] == "stale"
    assert len(list(vault.events())) == changed


def test_transfer_requests_are_closed_nonself_and_cannot_smuggle_a_grade(tmp_path):
    vault, source, counterparts, _ordinary = _transfer_vault(tmp_path)
    actions = ActivityActions(vault)
    before = len(list(vault.events()))

    with pytest.raises(BridgeRequestError, match="unexpected: grade"):
        actions.confirm_transfer({
            "movement_key": source, "counterpart_key": counterparts[0],
            "grade": "verified"})
    with pytest.raises(BridgeRequestError, match="another movement"):
        actions.confirm_transfer({
            "movement_key": source, "counterpart_key": source})
    with pytest.raises(BridgeRequestError, match="unexpected: counterpart_key"):
        actions.reject_transfer({
            "movement_key": source, "counterpart_key": counterparts[0]})
    assert len(list(vault.events())) == before


def test_stale_intent_writes_nothing_and_a_new_tag_can_bootstrap(tmp_path):
    vault = _vault(tmp_path)
    target = vault.ledger.projection().movements()[0]
    tag_movement(vault.ledger, target.key, ["known"])
    before = len(list(vault.events()))
    actions = ActivityActions(vault)

    assert actions.assign_category(
        {"movement_key": "moved-away", "category_id": "known"})["kind"] == "stale"
    assert len(list(vault.events())) == before
    assert actions.replace_tags(
        {"movement_key": target.key, "tag_ids": ["minted"]})["kind"] == "completed"
    assert vault.ledger.projection().movement_tags_of(target) == ["minted"]


def test_identical_category_and_tag_intents_are_completed_without_duplicate_append(tmp_path):
    vault = _vault(tmp_path)
    target = vault.ledger.projection().movements()[0]
    assign_category(vault.ledger, target.key, "groceries")
    tag_movement(vault.ledger, target.key, ["known"])
    before = len(list(vault.events()))
    actions = ActivityActions(vault)

    assert actions.assign_category(
        {"movement_key": target.key, "category_id": "groceries"})["kind"] == "completed"
    assert actions.replace_tags(
        {"movement_key": target.key, "tag_ids": ["known"]})["kind"] == "completed"
    assert len(list(vault.events())) == before


def test_closed_requests_and_bounds_cannot_smuggle_nature_or_labels(tmp_path):
    vault = _vault(tmp_path)
    target = vault.ledger.projection().movements()[0]
    actions = ActivityActions(vault)
    before = len(list(vault.events()))

    with pytest.raises(BridgeRequestError, match="unexpected: nature"):
        actions.assign_category({"movement_key": target.key,
                                 "category_id": "groceries", "nature": "transfer"})
    refused = actions.replace_tags(
        {"movement_key": target.key, "tag_ids": ["x" * 81]})
    assert refused["kind"] == "refused"
    assert len(list(vault.events())) == before


def test_inherited_tags_remain_visible_but_movement_replacement_is_unavailable(tmp_path):
    vault = _vault(tmp_path)
    target = vault.ledger.projection().movements()[0]
    merchant = vault.ledger.projection().merchant_key_of(target)
    tag_merchant(vault.ledger, merchant, ["merchant-wide"])
    before = len(list(vault.events()))

    row = next(item for item in activity(vault.ledger.projection())["items"]
               if item["id"] == target.key)
    assert row["tags"] == [{"id": "merchant-wide", "label": "merchant-wide"}]
    assert "replace_tags" not in row["actions"]
    outcome = ActivityActions(vault).replace_tags(
        {"movement_key": target.key, "tag_ids": []})
    assert outcome["kind"] == "refused"
    assert outcome["reason"] == "inherited_tags_not_movement_scoped"
    assert len(list(vault.events())) == before


def test_truncated_vocabularies_keep_current_data_visible_and_withhold_actions(
        tmp_path, monkeypatch):
    vault = _vault(tmp_path)
    first, second = vault.ledger.projection().movements()
    assign_category(vault.ledger, first.key, "groceries")
    assign_category(vault.ledger, second.key, "dining")
    tag_movement(vault.ledger, first.key, ["one", "two"])
    monkeypatch.setattr(import_module("viva.surface.activity"),
                        "VOCABULARY_LIMIT", 1)

    read = activity(vault.ledger.projection())
    row = next(item for item in read["items"] if item["id"] == first.key)

    assert read["vocabularies"]["categories"]["complete"] is False
    assert read["vocabularies"]["tags"]["complete"] is False
    assert row["category"]["id"] == "groceries"
    assert {tag["id"] for tag in row["tags"]} == {"one", "two"}
    assert row["actions"] == ["assign_meaning"]
    before = len(list(vault.events()))
    assert ActivityActions(vault).assign_category(
        {"movement_key": first.key, "category_id": "dining"})["kind"] == "refused"
    assert ActivityActions(vault).replace_tags(
        {"movement_key": first.key, "tag_ids": ["one"]})["kind"] == "refused"
    assert len(list(vault.events())) == before


def test_activity_actions_are_declared_allowlisted_and_write_scoped(tmp_path):
    capability = capability_for("activity.movements")
    assert capability.contract == "ActivityMovements.v3"
    assert capability.actions == (
        "assign_category", "assign_classification", "assign_meaning",
        "replace_tags", "add_tags", "remove_tags", "confirm_transfer",
        "reject_transfer", "unlink_transfer")
    assert capability.trust_effect == (TrustEffect.READS_DATA, TrustEffect.WRITES_EVENT)
    handlers = handlers_for_opened_vault(_vault(tmp_path)).handlers
    assert ACTIVITY_OPERATIONS == {
        "assign_category": "viva.activity.assign_category",
        "assign_classification": "viva.activity.assign_classification",
        "assign_meaning": "viva.activity.assign_meaning",
        "replace_tags": "viva.activity.replace_tags",
        "add_tags": "viva.activity.add_tags",
        "remove_tags": "viva.activity.remove_tags",
        "confirm_transfer": "viva.activity.confirm_transfer",
        "reject_transfer": "viva.activity.reject_transfer",
        "unlink_transfer": "viva.activity.unlink_transfer"}
    assert set(ACTIVITY_OPERATIONS.values()) <= set(handlers)
    cold = default_handlers().handlers
    assert not set(ACTIVITY_OPERATIONS.values()) & set(cold)
    denied = json.loads(dispatch_frame(
        '{"protocol":"2.0","request_id":"cold","operation":'
        '"viva.activity.add_tags","payload":{"movement_ids":["m"],'
        '"tag_ids":["trip"]}}', cold))
    assert denied["error"]["code"] == "operation_not_allowed"


def test_batch_bridge_handlers_return_typed_outcomes_and_structured_input_errors(
        tmp_path):
    vault = _vault(tmp_path)
    first, second = vault.ledger.projection().movements()
    handlers = handlers_for_opened_vault(vault).handlers

    accepted = json.loads(dispatch_frame(json.dumps({
        "protocol": "2.0", "request_id": "batch-ok",
        "operation": "viva.activity.assign_classification",
        "payload": {
            "movement_ids": [first.key, second.key],
            "category_id": "groceries",
            "subcategory_id": "supermarket",
        },
    }), handlers))
    before_invalid = len(list(vault.events()))
    invalid = json.loads(dispatch_frame(json.dumps({
        "protocol": "2.0", "request_id": "batch-invalid",
        "operation": "viva.activity.add_tags",
        "payload": {
            "movement_ids": [first.key, first.key],
            "tag_ids": ["trip"],
        },
    }), handlers))

    assert accepted["ok"] is True
    assert accepted["result"]["kind"] == "completed"
    assert invalid["ok"] is False
    assert invalid["error"]["code"] == "invalid_request"
    assert "duplicates" in invalid["error"]["message"]
    assert len(list(vault.events())) == before_invalid


def test_action_coverage_detects_one_declared_handler_removed(tmp_path):
    handlers = dict(handlers_for_opened_vault(_vault(tmp_path)).handlers)
    missing_operation = ACTIVITY_OPERATIONS["unlink_transfer"]
    handlers.pop(missing_operation)
    declared = set(ACTIVITY_OPERATIONS.values())

    assert declared - set(handlers) == {missing_operation}


def test_an_existing_tag_outside_the_label_bound_stays_visible_but_not_writable(tmp_path):
    vault = _vault(tmp_path)
    target = vault.ledger.projection().movements()[0]
    long_tag = "x" * 81
    tag_movement(vault.ledger, target.key, [long_tag])

    read = activity(vault.ledger.projection())
    row = next(item for item in read["items"] if item["id"] == target.key)

    assert row["tags"] == [{"id": long_tag, "label": long_tag}]
    assert read["vocabularies"]["tags"]["complete"] is False
    assert "replace_tags" not in row["actions"]
