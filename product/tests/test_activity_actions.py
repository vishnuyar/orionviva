"""Activity v3 corrections validate live state and append exact overlays."""

from decimal import Decimal
from importlib import import_module

import pytest

from viva.desktop_bridge.activity_actions import ActivityActions
from viva.desktop_bridge.handlers import (ACTIVITY_OPERATIONS, BridgeRequestError,
                                          handlers_for_opened_vault)
from viva.ingest import (ReadResult, StatementFacts, TxnFact, assign_category,
                         capture_and_ingest, tag_merchant, tag_movement)
from viva.ledger import (account_opened, simple_transaction, transfer_linked,
                         transfer_suggested)
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
    assert row["category"] == {"id": None, "label": "Uncategorized"}
    assert row["tags"] == read["vocabularies"]["tags"]["items"]
    assert row["actions"] == ["assign_category", "assign_meaning", "replace_tags"]
    category = next(item for item in read["items"] if item["id"] == first.key)
    advertised = {item["id"]: item
                  for item in read["vocabularies"]["categories"]["items"]}
    assert category["category"] == advertised["groceries"]


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
    assert set(candidate) == {"id", "date", "description", "account", "direction",
                              "exact_value", "currency", "display", "relationship"}
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
    assert written["grade"] == "verified"
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


def test_stale_or_unadvertised_intent_writes_nothing(tmp_path):
    vault = _vault(tmp_path)
    target = vault.ledger.projection().movements()[0]
    tag_movement(vault.ledger, target.key, ["known"])
    before = len(list(vault.events()))
    actions = ActivityActions(vault)

    assert actions.assign_category(
        {"movement_key": "moved-away", "category_id": "known"})["kind"] == "stale"
    assert actions.replace_tags(
        {"movement_key": target.key, "tag_ids": ["minted"]})["kind"] == "refused"
    assert len(list(vault.events())) == before


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
        "assign_category", "assign_meaning", "replace_tags", "confirm_transfer",
        "reject_transfer", "unlink_transfer")
    assert capability.trust_effect == (TrustEffect.READS_DATA, TrustEffect.WRITES_EVENT)
    handlers = handlers_for_opened_vault(_vault(tmp_path)).handlers
    assert ACTIVITY_OPERATIONS == {
        "assign_category": "viva.activity.assign_category",
        "assign_meaning": "viva.activity.assign_meaning",
        "replace_tags": "viva.activity.replace_tags",
        "confirm_transfer": "viva.activity.confirm_transfer",
        "reject_transfer": "viva.activity.reject_transfer",
        "unlink_transfer": "viva.activity.unlink_transfer"}
    assert set(ACTIVITY_OPERATIONS.values()) <= set(handlers)


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
