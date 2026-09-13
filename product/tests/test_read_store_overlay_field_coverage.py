"""Exact event-to-row evidence for the overlay history families."""

import json
from pathlib import Path

import pytest

from viva.ledger import EventStore, Posting, Provenance
from viva.ledger import events
from viva.ledger.projection import LedgerProjection
from viva.read_store import ReadStore
from viva.read_store import store as read_store_module


PASSPHRASE = "correct horse battery staple"
TABLES = (
    "transfer_history", "category_history", "merchant_history",
    "tag_history", "ruling_history", "attribute_history",
    "account_alias_history",
)
FAMILY_TABLE = {
    "TransferSuggested": "transfer_history",
    "TransferLinked": "transfer_history",
    "TransferUnlinked": "transfer_history",
    "CategoryAssigned": "category_history",
    "MerchantCategorized": "merchant_history",
    "MerchantEnriched": "merchant_history",
    "MovementTagged": "tag_history",
    "RulingRecorded": "ruling_history",
    "AccountAliasConfirmed": "account_alias_history",
}


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _corpus():
    cited = Provenance("文書-α", 0, "位置", "note ☕")
    uncited = Provenance()
    base = [
        events.account_opened("account-a", "depository", "A", "USD",
                              "2026-01-01", provenance=cited),
        events.account_opened("account-b", "depository", "B", "USD",
                              "2026-01-01", provenance=uncited),
        events.transaction_recorded(
            [Posting("account-a", "-1.2300"), Posting("account-b", "1.2300")],
            "店 ☕", "2026-01-02", provenance=cited),
        events.document_captured("doc-a", "doc.pdf", 0, "", 0.0,
                                 "2026-01-02", cited),
    ]
    movements = LedgerProjection(base).movements()
    left, right = movements[0].key, movements[1].key
    same_day = "2026-01-03"
    return base + [
        events.transfer_suggested(left, [right, right],
                                  {"decided_by": "", "nested": [None, 0, ""]},
                                  same_day, cited),
        events.transfer_linked(left, right, "verified",
                               {"decided_by": "human", "amount": "1.2300"},
                               same_day, provenance=uncited),
        events.transfer_unlinked(left, right, same_day, provenance=cited),
        events.category_assigned(left, "店 ☕", "Food", "verified", same_day,
                                 subcategory="", nature="spending", provenance=cited),
        events.category_assigned(left, "店 ☕", "Travel", "corroborated", same_day,
                                 subcategory="Rail", provenance=uncited),
        events.merchant_categorized("店 ☕", "Food", "unverified", same_day,
                                    provenance=cited),
        events.merchant_enriched(
            "店 ☕", "Travel", "Rail", "商店", {"zero": 0, "null": None,
            "items": ["雪", "雪"]}, "verified", same_day,
            aliases=["店", "店", ""], provenance=uncited),
        events.movement_tagged(left, ["旅", "旅", ""], same_day,
                               provenance=cited),
        events.ruling_recorded(
            events.SCOPE_MOVEMENT, left, same_day,
            legs=[{"major": "expense", "account": "Expenses:X", "share": "0.5000"},
                  {"major": "asset", "account": "Assets:Y", "share": "0.5000"}],
            said="I split it", prompt_version="v1", provenance=uncited),
        events.ruling_recorded(
            events.SCOPE_ATTRIBUTE, "account-a:value", same_day,
            value="999999999999.000000001", currency="USD",
            said="It is 999999999999.000000001", provenance=cited),
        events.account_alias_confirmed(
            "alias-a", "account-a", "doc-a", same_day,
            match_names=None, provenance=uncited),
        events.account_alias_confirmed(
            "alias-b", "account-b", "doc-a", same_day, learn_signal=False,
            match_names=["李", "李", ""], match_label="", kind="depository",
            provenance=cited),
    ]


def _expected(event, sequence):
    body = event.body
    kind = event.event_type
    provenance = (event.provenance.doc_id, event.provenance.page,
                  event.provenance.region, event.provenance.note)
    prefix = (sequence, kind, event.occurred_at)
    if kind.startswith("Transfer"):
        evidence = body.get("evidence") or {}
        fields = (body.get("a", ""), body.get("b"),
                  _json(body.get("candidates") or []), body.get("status", ""),
                  body.get("grade", ""), evidence.get("decided_by", ""),
                  body.get("by", ""), _json(evidence))
    elif kind == "CategoryAssigned":
        fields = (body["movement_key"], body["descriptor"], body["category"],
                  body.get("subcategory", ""), body["nature"], body["grade"],
                  body["by"], body["category_grade"], body["subcategory_grade"],
                  body["category_by"], body["subcategory_by"])
    elif kind in ("MerchantCategorized", "MerchantEnriched"):
        fields = (body["merchant"], body["category"], body.get("subcategory", ""),
                  body.get("canonical_name", ""), _json(body.get("attributes") or {}),
                  _json(body.get("aliases") or []), body["grade"], body["by"],
                  body.get("category_grade", body["grade"]),
                  body.get("subcategory_grade", body["grade"]),
                  body.get("category_by", body["by"]),
                  body.get("subcategory_by", body["by"]))
    elif kind == "MovementTagged":
        fields = (body["scope"], body["subject"], _json(body["tags"]), body["by"])
    elif kind == "RulingRecorded":
        fields = (body["scope"], body["subject"], _json(body["legs"]),
                  body["by"], body["grade"], body["said"], body["corroborates"],
                  body["same_as"], str(body["value"]), body["currency"],
                  body["prompt_version"])
    else:
        scoped = any(key in body for key in ("match_names", "match_label", "kind"))
        fields = (body["alias_key"], body["account_id"], body["doc_id"],
                  body["by"], int(body["learn_signal"]),
                  _json(body.get("match_names") or []), body.get("match_label", ""),
                  body.get("kind", ""), int(scoped))
    return prefix + fields + provenance


def _snapshot(revision):
    return {table: revision.connection.execute(
        f"SELECT * FROM {table} ORDER BY source_sequence").fetchall()
        for table in TABLES}


@pytest.mark.parametrize("cut", [4, 7, 10, 14])
def test_overlay_fields_match_events_across_suffix_rebuild_restart_and_held(
        tmp_path: Path, cut: int):
    corpus = _corpus()
    canonical = EventStore.open(tmp_path / "events.jsonl", PASSPHRASE)
    for event in corpus[:cut]:
        canonical.append(event)
    path = tmp_path / "split"
    with ReadStore.create(path, PASSPHRASE) as split:
        assert split.synchronize(canonical).state == "rebuilt"
        held = split.open_reader()
        before = _snapshot(held)
        for event in corpus[cut:]:
            canonical.append(event)
        assert split.synchronize(canonical).state == "caught_up"
        assert _snapshot(held) == before
        held.close()
        with split.open_reader() as revision:
            complete = _snapshot(revision)
            for sequence, event in enumerate(corpus):
                table = FAMILY_TABLE.get(event.event_type)
                if table:
                    assert revision.connection.execute(
                        f"SELECT * FROM {table} WHERE source_sequence=?",
                        (sequence,)).fetchone() == _expected(event, sequence)
            attribute = corpus[13]
            assert attribute.event_type == "RulingRecorded"
            assert revision.connection.execute(
                "SELECT * FROM attribute_history WHERE source_sequence=13").fetchone() == (
                    13, "RulingRecorded", attribute.occurred_at, "account-a", "value",
                    attribute.body["value"], "USD", "verified", attribute.body["said"],
                    "human", attribute.provenance.doc_id, attribute.provenance.page,
                    attribute.provenance.region, attribute.provenance.note)
            assert revision.connection.execute(
                "PRAGMA foreign_key_check").fetchall() == []
    with ReadStore.open(path, PASSPHRASE) as restarted:
        with restarted.open_reader() as revision:
            assert _snapshot(revision) == complete
    with ReadStore.create(tmp_path / "full", PASSPHRASE) as full:
        assert full.synchronize(canonical).state == "rebuilt"
        with full.open_reader() as revision:
            assert _snapshot(revision) == complete


@pytest.mark.parametrize("sequence,wrong_type", [
    (4, "CategoryAssigned"),
    (7, "TransferLinked"),
    (9, "MovementTagged"),
    (11, "MerchantEnriched"),
    (12, "AccountAliasConfirmed"),
    (14, "RulingRecorded"),
])
def test_overlay_rows_refuse_wrong_authenticated_family(
        tmp_path: Path, sequence: int, wrong_type: str):
    canonical = EventStore.open(tmp_path / "events.jsonl", PASSPHRASE)
    for event in _corpus():
        canonical.append(event)
    with ReadStore.create(tmp_path / "read-model", PASSPHRASE) as reads:
        assert reads.synchronize(canonical).state == "rebuilt"
        generation = reads.current_generation

        def substitute(connection):
            connection.execute(
                "UPDATE applied_events SET event_type=? WHERE sequence=?",
                (wrong_type, sequence))

        with pytest.raises(read_store_module.sqlcipher.IntegrityError,
                           match="FOREIGN KEY constraint failed"):
            reads.publish(substitute, copy_current=True)
        assert reads.current_generation == generation


def test_overlay_named_reads_are_source_bounded_and_tie_ordered(tmp_path: Path):
    canonical = EventStore.open(tmp_path / "events.jsonl", PASSPHRASE)
    subject = events.rhythm_subject("商店", "out")
    for number in range(3):
        canonical.append(events.ruling_recorded(
            events.SCOPE_RHYTHM, subject, "2026-02-01",
            value="monthly", said=f"monthly {number}"))
    with ReadStore.create(tmp_path / "read-model", PASSPHRASE) as reads:
        assert reads.synchronize(canonical).state == "rebuilt"
        with reads.open_reader() as revision:
            seen = []
            before = None
            for _ in range(3):
                page = revision.obligation_control_history(
                    as_of="2026-02-01", limit=1, before=before)
                assert len(page) == 1
                seen.append(page[0]["source_sequence"])
                before = (page[0]["occurred_at"], page[0]["source_sequence"])
            assert seen == [2, 1, 0]
            assert revision.obligation_control_history(
                as_of="2026-02-01", limit=1, before=before) == []
            for limit in (0, 201, True):
                with pytest.raises(ValueError):
                    revision.obligation_control_history(
                        as_of="2026-02-01", limit=limit)
                with pytest.raises(ValueError):
                    revision.transfer_links(limit=limit)
                with pytest.raises(ValueError):
                    revision.transfer_suggestions(limit=limit)
            plan = revision.connection.execute(
                "EXPLAIN QUERY PLAN SELECT source_sequence FROM ruling_history "
                "WHERE scope='rhythm' AND occurred_at<=? "
                "ORDER BY occurred_at DESC,source_sequence DESC LIMIT ?",
                ("2026-02-01", 1)).fetchall()
            assert any("ruling_history_by_scope_order" in row[-1] for row in plan)
            assert not any("TEMP B-TREE" in row[-1] for row in plan)
