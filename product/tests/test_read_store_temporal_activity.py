"""Direct historical Activity SQL input and overlay folds."""

import pytest
import json
from decimal import Decimal

from viva.ledger.events import (Posting, account_opened, category_assigned,
                                merchant_enriched, movement_tagged,
                                ruling_recorded,
                                transaction_recorded, transfer_linked,
                                transfer_suggested, transfer_unlinked)
from viva.read_store.store import ReadStoreError
from viva.demo import build_demo_vault
from viva.surface.activity import activity
from viva.read_store.temporal_activity import (MAX_TEMPORAL_ROWS,
                                               _FAMILIES,
                                               category_overlays,
                                               eligible_family,
                                               eligible_postings,
                                               movement_base,
                                               merchant_state,
                                               tag_state,
                                               transfer_state)
from viva.vault import Vault


def _vault(tmp_path):
    vault = Vault.open(tmp_path / "vault", "pw")
    vault.ledger.append(account_opened("cash", "depository", "Cash", "USD",
                                      "2026-01-01"))
    vault.ledger.append(transaction_recorded([
        Posting("cash", "-10.00", "verified"),
        Posting("Expenses:Unknown", "10.00", "unverified")],
        "Synthetic merchant", "2026-01-10"))
    key = vault.ledger.projection().movements()[0].key
    vault.ledger.append(category_assigned(
        key, "Synthetic merchant", "Groceries", "verified", "2026-01-11"))
    vault.ledger.append(category_assigned(
        key, "Synthetic merchant", "Food", "verified", "2026-02-01"))
    vault.ledger.append(category_assigned(
        key, "Synthetic merchant", "Utilities", "verified", "2026-01-11"))
    vault.synchronize_read_store()
    return vault, key


@pytest.mark.parametrize("glyph", ["X", "雪"])
def test_historical_merchant_json_refuses_before_python_fetch(tmp_path, glyph):
    from viva.read_store import temporal_activity as temporal

    vault, _key = _vault(tmp_path)
    vault.ledger.append(merchant_enriched(
        "synthetic merchant", "Food", grade="corroborated",
        occurred_at="2026-01-11", attributes={"nature": "spending"}))
    with vault.read_store.open_reader() as revision:
        original = revision.connection.execute(
            "SELECT attributes_json FROM merchant_history LIMIT 1").fetchone()[0]
    base = json.loads(original)
    bound = temporal.MAX_OVERLAY_JSON_BYTES
    shell = json.dumps({**base, "padding": ""}, ensure_ascii=False)
    room = bound - len(shell.encode("utf-8"))
    width = len(glyph.encode("utf-8"))
    padding = glyph * (room // width) + "X" * (room % width)
    for extra in ("", "X"):
        encoded = json.dumps({**base, "padding": padding + extra},
                             ensure_ascii=False)
        assert len(encoded.encode("utf-8")) == bound + len(extra)
        vault.read_store.publish(lambda db: db.execute(
            "UPDATE merchant_history SET attributes_json=?", (encoded,)),
            copy_current=True)
        with vault.read_store.open_reader() as revision:
            assert json.loads(revision.connection.execute(
                "SELECT attributes_json FROM merchant_history LIMIT 1"
            ).fetchone()[0]) == json.loads(encoded)
            traced = []
            revision.connection.set_trace_callback(traced.append)
            if extra:
                with pytest.raises(ReadStoreError,
                                   match="historical Activity JSON exceeds"):
                    eligible_family(revision, "merchant_history", "2026-01-15")
            else:
                assert eligible_family(revision, "merchant_history", "2026-01-15")
            revision.connection.set_trace_callback(None)
            selected = [sql for sql in traced if "FROM merchant_history" in sql
                        and "length(CAST(attributes_json AS BLOB))" in sql]
            assert len(selected) == 1
            plan = " ".join(str(row[-1]) for row in revision.connection.execute(
                "EXPLAIN QUERY PLAN " + selected[0]).fetchall())
            assert "TEMP B-TREE" not in plan.upper()


@pytest.mark.parametrize("glyph", ["X", "雪"])
def test_historical_resolver_profile_refuses_before_python_fetch(tmp_path, glyph):
    import sqlite3
    from types import SimpleNamespace
    from viva.read_store import temporal_activity as temporal

    vault = build_demo_vault(tmp_path / "sample")
    with vault.read_store.open_reader() as revision:
        original = revision.connection.execute(
            "SELECT profile_json FROM resolver_profiles LIMIT 1").fetchone()[0]
    base = json.loads(original)
    bound = temporal.MAX_OVERLAY_JSON_BYTES
    shell = json.dumps({**base, "padding": ""}, ensure_ascii=False)
    room = bound - len(shell.encode("utf-8"))
    width = len(glyph.encode("utf-8"))
    padding = glyph * (room // width) + "X" * (room % width)
    connection = sqlite3.connect(":memory:")
    connection.execute("CREATE TABLE resolver_profiles("
                       "institution TEXT,account_kind TEXT,profile_json TEXT)")
    connection.execute("CREATE INDEX resolver_profiles_by_identity "
                       "ON resolver_profiles(institution,account_kind)")
    for extra in ("", "X"):
        encoded = json.dumps({**base, "padding": padding + extra},
                             ensure_ascii=False)
        assert len(encoded.encode("utf-8")) == bound + len(extra)
        connection.execute("DELETE FROM resolver_profiles")
        connection.execute("INSERT INTO resolver_profiles VALUES(?,?,?)",
                           ("", "depository", encoded))
        assert json.loads(connection.execute(
            "SELECT profile_json FROM resolver_profiles LIMIT 1"
        ).fetchone()[0]) == json.loads(encoded)
        traced = []
        connection.set_trace_callback(traced.append)
        revision = SimpleNamespace(connection=connection)
        if extra:
            with pytest.raises(ReadStoreError,
                               match="historical resolver profile exceeds"):
                temporal._resolver_profiles(revision)
        else:
            temporal._resolver_profiles(revision)
        connection.set_trace_callback(None)
        selected = [sql for sql in traced if "FROM resolver_profiles" in sql
                    and "length(CAST(profile_json AS BLOB))" in sql]
        assert len(selected) == 1
        plan = " ".join(str(row[-1]) for row in connection.execute(
            "EXPLAIN QUERY PLAN " + selected[0]).fetchall())
        assert "TEMP B-TREE" not in plan.upper()


def test_temporal_category_fold_filters_then_applies_source_order(tmp_path):
    vault, key = _vault(tmp_path)
    with vault.read_store.open_reader() as revision:
        rows = eligible_family(revision, "category_history", "2026-01-15")
        assert [row["category"] for row in rows] == ["Groceries", "Utilities"]
        assert [row["source_sequence"] for row in rows] == sorted(
            row["source_sequence"] for row in rows)
        assert category_overlays(rows)[key]["category"] == "Utilities"
        assert category_overlays(eligible_family(
            revision, "category_history", "2026-02-01"))[key]["category"] == "Utilities"
        postings = eligible_postings(revision, "2026-01-15")
        assert len(postings) == 2
        assert {row["description"] for row in postings} == {"Synthetic merchant"}


def test_held_temporal_inputs_ignore_later_publication(tmp_path):
    vault, key = _vault(tmp_path)
    held = vault.read_store.open_reader()
    before = eligible_family(held, "category_history", "2026-01-15")
    vault.ledger.append(category_assigned(
        key, "Synthetic merchant", "Travel", "verified", "2026-01-12"))
    assert eligible_family(held, "category_history", "2026-01-15") == before
    with vault.read_store.open_reader() as current:
        after = eligible_family(current, "category_history", "2026-01-15")
    assert [row["category"] for row in after] == ["Groceries", "Utilities", "Travel"]
    held.close()


def test_temporal_movement_identity_matches_canonical_backfill_and_duplicates(tmp_path):
    vault, _key = _vault(tmp_path)
    for date, amount in (("2026-01-10", "-10.00"),
                         ("2026-01-08", "-25.00"),
                         ("2026-02-03", "-50.00")):
        vault.ledger.append(transaction_recorded([
            Posting("cash", amount, "verified"),
            Posting("Expenses:Unknown", str(-Decimal(amount)), "unverified")],
            "Synthetic merchant", date))
    vault.synchronize_read_store()
    canonical = vault.ledger.projection_as_of("2026-01-15")
    expected = canonical.movements()
    with vault.read_store.open_reader() as revision:
        actual, grades = movement_base(revision, "2026-01-15")
        payload = activity(revision.historical_activity_projection(as_of="2026-01-15"),
                           "en-US", 10)
    def identity(movement):
        return (movement.key, movement.account, movement.kind, movement.date,
                movement.amount, movement.description, movement.currency,
                movement.provenance)
    assert [identity(row) for row in actual] == [identity(row) for row in expected]
    assert grades == canonical.movement_grades()
    assert len(actual) == 3
    assert payload == activity(canonical, "en-US", 10)


@pytest.mark.parametrize("as_of,limit", [
    ("2026-03-31", 5), ("2026-08-29", 10), ("2026-01-01", 5),
])
def test_historical_activity_direct_sql_matches_complete_canonical_payload(
        tmp_path, as_of, limit):
    vault = build_demo_vault(tmp_path / "sample")
    expected = activity(vault.ledger.projection_as_of(as_of), "en-US", limit)
    with vault.read_store.open_reader() as revision:
        actual = activity(revision.historical_activity_projection(as_of=as_of),
                          "en-US", limit)
    assert actual == expected


def test_historical_activity_direct_sql_keeps_backfilled_overlays_and_focus(
        tmp_path):
    vault, key = _vault(tmp_path)
    vault.ledger.append(merchant_enriched(
        "synthetic merchant", "Food", grade="corroborated",
        occurred_at="2026-01-11", attributes={"nature": "spending"},
        aliases=["synthetic merchant"]))
    vault.ledger.append(movement_tagged(
        "synthetic merchant", ["shared"], "2026-01-11", scope="merchant"))
    vault.ledger.append(movement_tagged(key, ["own"], "2026-01-11"))
    vault.ledger.append(transfer_suggested(
        key, ["missing-counterpart"], {"rule": "candidate"}, "2026-01-11"))
    vault.ledger.append(category_assigned(
        key, "Synthetic merchant", "Travel", "verified", "2026-02-01"))
    vault.ledger.append(category_assigned(
        key, "Synthetic merchant", "Food", "verified", "2026-01-11"))
    vault.synchronize_read_store()
    as_of = "2026-01-15"
    expected = activity(vault.ledger.projection_as_of(as_of), "en-US", 1,
                        focus=key)
    with vault.read_store.open_reader() as revision:
        actual = activity(revision.historical_activity_projection(as_of=as_of),
                          "en-US", 1, focus=key)
    assert actual == expected


def test_historical_activity_direct_sql_keeps_ruling_nature_and_aliases(tmp_path):
    vault, key = _vault(tmp_path)
    vault.ledger.append(ruling_recorded(
        "movement", key, "2026-01-12",
        legs=[{"major": "asset", "account": "Assets:Loans:Alex"}]))
    vault.ledger.append(movement_tagged(key, ["own"], "2026-01-12"))
    vault.ledger.append(ruling_recorded(
        "category", "Groceries", "2026-01-12", same_as="Food"))
    vault.ledger.append(ruling_recorded(
        "tag", "own", "2026-01-12", same_as="personal"))
    vault.ledger.append(ruling_recorded(
        "movement", key, "2026-02-01", legs=[{"major": "expense"}]))
    vault.synchronize_read_store()
    as_of = "2026-01-15"
    expected = activity(vault.ledger.projection_as_of(as_of), "en-US", 10)
    with vault.read_store.open_reader() as revision:
        actual = activity(revision.historical_activity_projection(as_of=as_of),
                          "en-US", 10)
    assert actual == expected
    assert actual["items"][0]["nature"] == "transfer"


def test_historical_activity_direct_reader_is_canonical_and_raw_independent(
        tmp_path, monkeypatch):
    vault, _key = _vault(tmp_path)
    monkeypatch.setattr(vault.ledger, "projection_as_of",
                        lambda *_args: pytest.fail("canonical projection replay"))
    monkeypatch.setattr(vault.ledger.store, "snapshot_events",
                        lambda: pytest.fail("EventStore snapshot"))
    monkeypatch.setattr(vault.raw, "doc_ids",
                        lambda: pytest.fail("RawStore enumeration"))
    with vault.read_store.open_reader() as revision:
        payload = activity(revision.historical_activity_projection(as_of="2026-01-15"),
                           "en-US", 10)
    assert payload["state"] == "ready"


def test_historical_activity_direct_reader_holds_full_old_payload(tmp_path):
    vault, key = _vault(tmp_path)
    held = vault.read_store.open_reader()
    before = activity(held.historical_activity_projection(as_of="2026-01-15"),
                      "en-US", 10)
    vault.ledger.append(ruling_recorded(
        "movement", key, "2026-01-12",
        legs=[{"major": "asset", "account": "Assets:Loans:Alex"}]))
    again = activity(held.historical_activity_projection(as_of="2026-01-15"),
                     "en-US", 10)
    with vault.read_store.open_reader() as current:
        after = activity(current.historical_activity_projection(as_of="2026-01-15"),
                         "en-US", 10)
    assert again == before
    assert after != before
    held.close()


def test_temporal_transfer_fold_matches_historical_link_and_suggestion_state(tmp_path):
    vault, key = _vault(tmp_path)
    other = "synthetic-counterpart"
    vault.ledger.append(transfer_suggested(
        key, [other], {"rule": "candidate"}, "2026-01-11"))
    vault.ledger.append(transfer_linked(
        key, other, "verified", {"decided_by": "human"}, "2026-01-12"))
    vault.ledger.append(transfer_unlinked(key, other, "2026-02-01"))
    vault.synchronize_read_store()
    canonical = vault.ledger.projection_as_of("2026-01-15")
    with vault.read_store.open_reader() as revision:
        links, suggestions, linked = transfer_state(eligible_family(
            revision, "transfer_history", "2026-01-15"))
    assert links == canonical.transfer_links()
    assert suggestions == canonical.transfer_suggestions() == []
    assert linked == {key, other}


def test_temporal_merchant_and_tag_folds_filter_future_and_keep_late_backfills(tmp_path):
    vault, key = _vault(tmp_path)
    vault.ledger.append(merchant_enriched(
        "synthetic merchant", "Food", grade="corroborated",
        occurred_at="2026-01-11", aliases=["alias-one"]))
    vault.ledger.append(merchant_enriched(
        "synthetic merchant", "Travel", grade="verified",
        occurred_at="2026-02-01", aliases=["alias-two"]))
    vault.ledger.append(merchant_enriched(
        "synthetic merchant", "Groceries", grade="corroborated",
        occurred_at="2026-01-11", aliases=["alias-three"]))
    vault.ledger.append(movement_tagged(key, ["home"], "2026-01-11"))
    vault.ledger.append(movement_tagged(key, ["future"], "2026-02-01"))
    vault.ledger.append(movement_tagged(key, ["late"], "2026-01-11"))
    vault.synchronize_read_store()
    with vault.read_store.open_reader() as revision:
        merchants = merchant_state(eligible_family(
            revision, "merchant_history", "2026-01-15"))
        tags = tag_state(eligible_family(
            revision, "tag_history", "2026-01-15"))
    assert merchants["synthetic merchant"]["category"] == "Groceries"
    assert merchants["synthetic merchant"]["aliases"] == ["alias-one", "alias-three"]
    assert tags[("movement", key)] == ["late"]


def test_temporal_input_is_explicitly_bounded(tmp_path, monkeypatch):
    vault, _key = _vault(tmp_path)
    import viva.read_store.temporal_activity as temporal
    monkeypatch.setattr(temporal, "MAX_TEMPORAL_ROWS", 1)
    with vault.read_store.open_reader() as revision:
        with pytest.raises(ReadStoreError, match="row bound"):
            eligible_family(revision, "category_history", "2026-01-15")
        with pytest.raises(ValueError, match="unknown temporal"):
            eligible_family(revision, "applied_events", "2026-01-15")


def test_temporal_category_query_uses_source_order_primary_key(tmp_path):
    vault, _key = _vault(tmp_path)
    with vault.read_store.open_reader() as revision:
        plans = {}
        for family, columns in _FAMILIES.items():
            plans[family] = " ".join(str(row[-1]) for row in revision.connection.execute(
                f"EXPLAIN QUERY PLAN SELECT {columns} FROM {family} "
                "WHERE occurred_at<=? ORDER BY source_sequence LIMIT ?",
                ("2026-01-15", MAX_TEMPORAL_ROWS + 1)).fetchall())
        postings_plan = " ".join(str(row[-1]) for row in revision.connection.execute(
            "EXPLAIN QUERY PLAN SELECT p.source_sequence,p.posting_index "
            "FROM postings p JOIN transactions t "
            "ON t.source_sequence=p.source_sequence WHERE t.occurred_at<=? "
            "ORDER BY p.source_sequence,p.posting_index LIMIT ?",
            ("2026-01-15", 50_001)).fetchall())
    assert all("SCAN" in plan for plan in plans.values())
    assert all("TEMP B-TREE" not in plan for plan in plans.values())
    assert "SCAN p" in postings_plan
    assert "SEARCH t USING INTEGER PRIMARY KEY" in postings_plan
    assert "TEMP B-TREE" not in postings_plan


@pytest.mark.parametrize("family", sorted(_FAMILIES))
def test_each_temporal_family_refuses_n_plus_one_before_folding(monkeypatch, family):
    import viva.read_store.temporal_activity as temporal
    monkeypatch.setattr(temporal, "MAX_TEMPORAL_ROWS", 1)
    class Connection:
        def execute(self, query, parameters):
            assert f"FROM {family}" in query
            assert "WHERE occurred_at<=? ORDER BY source_sequence LIMIT ?" in query
            json_columns = [name for name in _FAMILIES[family].split(",")
                            if name.endswith("_json")]
            bound = (temporal.MAX_TRANSFER_PAYLOAD_BYTES
                     if family == "transfer_history"
                     else temporal.MAX_OVERLAY_JSON_BYTES)
            assert parameters == ((bound,) * len(json_columns)
                                  + ((4096,) * 4 if family == "transactions" else ())
                                  + ("2026-01-15", 2))
            return self
        def fetchall(self):
            return [(), ()]
    revision = type("Revision", (), {"connection": Connection()})()
    with pytest.raises(ReadStoreError, match="row bound"):
        eligible_family(revision, family, "2026-01-15")


def test_temporal_postings_refuse_n_plus_one_before_folding(monkeypatch):
    import viva.read_store.temporal_activity as temporal
    monkeypatch.setattr(temporal, "MAX_TEMPORAL_POSTINGS", 1)
    class Connection:
        def execute(self, query, parameters):
            assert "JOIN transactions t" in query
            assert "WHERE t.occurred_at<=?" in query
            assert parameters == (4096,) * 8 + ("2026-01-15", 2)
            return self
        def fetchall(self):
            return [(), ()]
    revision = type("Revision", (), {"connection": Connection()})()
    with pytest.raises(ReadStoreError, match="postings exceed"):
        eligible_postings(revision, "2026-01-15")
