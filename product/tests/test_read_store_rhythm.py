"""Parity and work bounds for SQL-native merchant rhythms and obligations."""
from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
import sqlite3

import pytest

from viva.ledger import EventStore, LedgerProjection, account_opened, simple_transaction
from viva.ledger import account_identity_observed
from viva.ledger.events import (CORROBORATED, SCOPE_RHYTHM, merchant_enriched,
                                ruling_recorded, transfer_linked,
                                transfer_unlinked)
from viva.read_store import ReadStore
from viva.read_store import rhythm as sql_rhythm
from merchantcore.profile import Profile, ProfileStore, Template


PASSPHRASE = "correct horse battery staple"


def _normal(value):
    if hasattr(value, "__dataclass_fields__"):
        value = asdict(value)
    if isinstance(value, dict):
        value = {key: _normal(item) for key, item in value.items()}
        value.pop("subject", None) if "components" in value else None
        return value
    if isinstance(value, (tuple, list)):
        return [_normal(item) for item in value]
    return str(value) if value.__class__.__name__ == "Decimal" else value


def _events(amounts=("-10.00", "-10.00", "-10.00", "-10.00"),
            dates=("2026-01-05", "2026-02-05", "2026-03-05", "2026-04-05"),
            *, currency="USD", description="LUMEN STREAMING"):
    events = [account_opened("cash", "depository", "Cash", currency,
                             "2025-12-01")]
    events += [simple_transaction("cash", amount, description, when,
                                  kind="depository")
               for amount, when in zip(amounts, dates)]
    events.append(merchant_enriched(
        "lumen streaming", "other", grade=CORROBORATED,
        occurred_at="2026-04-06", by="model",
        attributes={"counterparty_kind": "business", "billing": "standing",
                    "billing_period": "monthly"}))
    return events


def _store(path: Path, events):
    canonical = EventStore.open(path / "events.jsonl", PASSPHRASE)
    for event in events:
        canonical.append(event)
    return canonical


@pytest.mark.parametrize("today", ["2026-04-06", "2026-05-05", "2026-08-06"])
def test_sql_rhythms_and_obligations_match_canonical(tmp_path: Path, today: str):
    events = _events()
    canonical = _store(tmp_path, events)
    with ReadStore.create(tmp_path / "read-model", PASSPHRASE) as reads:
        reads.synchronize(canonical)
        with reads.open_reader() as revision:
            actual_rhythms = revision.rhythm_hypotheses(as_of=today)
            actual_obligations = revision.obligations(today=today)
    projection = LedgerProjection(events, as_of=today)
    assert _normal(actual_rhythms) == _normal(projection.rhythm_hypotheses())
    assert _normal(actual_obligations) == _normal(projection.obligations(today))


def test_irregular_sparse_confirmed_and_multicurrency_edges(tmp_path: Path):
    irregular = _events(
        dates=("2026-01-01", "2026-01-09", "2026-03-20", "2026-04-01"))
    sparse = _events(amounts=("-5", "-5"), dates=("2026-01-05", "2026-02-05"),
                     description="SMALL SERVICE")
    sparse.append(ruling_recorded(
        SCOPE_RHYTHM, "small service|out", "2026-02-06", value="monthly",
        grade="verified", by="human"))
    euro = [account_opened("eur", "depository", "Euro", "EUR", "2025-12-01")]
    euro += [simple_transaction("eur", "-10", "LUMEN STREAMING", when,
                                kind="depository")
             for when in ("2026-01-05", "2026-02-05", "2026-03-05")]
    events = irregular + sparse[1:] + euro
    canonical = _store(tmp_path, events)
    with ReadStore.create(tmp_path / "read-model", PASSPHRASE) as reads:
        reads.synchronize(canonical)
        with reads.open_reader() as revision:
            actual_rhythms = revision.rhythm_hypotheses(as_of="2026-05-01")
            actual_obligations = revision.obligations(today="2026-05-01")
    projection = LedgerProjection(events, as_of="2026-05-01")
    assert _normal(actual_rhythms) == _normal(projection.rhythm_hypotheses())
    assert _normal(actual_obligations) == _normal(projection.obligations("2026-05-01"))


def test_transfer_reversal_suffix_restart_and_revision_isolation(tmp_path: Path):
    events = _events()
    projection = LedgerProjection(events)
    movement_keys = [movement.key for movement in projection.movements()]
    events.append(transfer_linked(movement_keys[0], movement_keys[1], "verified",
                                  {"decided_by": "test"}, "2026-04-07", by="human"))
    events.append(transfer_unlinked(movement_keys[0], movement_keys[1],
                                    "2026-04-08", by="human"))
    canonical = _store(tmp_path, events[:-2])
    with ReadStore.create(tmp_path / "read-model", PASSPHRASE) as reads:
        reads.synchronize(canonical)
        held = reads.open_reader()
        before = held.rhythm_hypotheses(as_of="2026-05-01")
        canonical.append(events[-2])
        reads.synchronize(canonical)
        with reads.open_reader() as linked:
            assert linked.rhythm_hypotheses(as_of="2026-05-01") != before
        canonical.append(events[-1])
        reads.synchronize(canonical)
        assert held.rhythm_hypotheses(as_of="2026-05-01") == before
        held.close()
    with ReadStore.open(tmp_path / "read-model", PASSPHRASE) as reopened:
        with reopened.open_reader() as revision:
            actual = revision.rhythm_hypotheses(as_of="2026-05-01")
    expected = LedgerProjection(events, as_of="2026-05-01").rhythm_hypotheses()
    assert _normal(actual) == _normal(expected)


def test_tied_dates_and_high_scale_decimal_keep_exact_parity(tmp_path: Path):
    events = _events(
        amounts=("-1234567890.123456789",) * 3,
        dates=("2026-01-05",) * 3)
    canonical = _store(tmp_path, events)
    with ReadStore.create(tmp_path / "read-model", PASSPHRASE) as reads:
        reads.synchronize(canonical)
        with reads.open_reader() as revision:
            actual = revision.rhythm_hypotheses(as_of="2026-04-06")
    expected = LedgerProjection(events, as_of="2026-04-06").rhythm_hypotheses()
    assert _normal(actual) == _normal(expected)
    assert str(actual[0]["amount"]) == "3703703670.370370367"


def test_temporal_boundary_does_not_leak_later_catalog_or_ruling(tmp_path: Path):
    events = _events()[:-1]
    events += [merchant_enriched(
        "lumen streaming", "other", grade=CORROBORATED,
        occurred_at="2026-06-01", by="model",
        attributes={"counterparty_kind": "business", "billing": "standing",
                    "billing_period": "monthly"}),
        ruling_recorded(SCOPE_RHYTHM, "lumen streaming|out", "2026-07-01",
                        value="annual", grade="verified", by="human")]
    canonical = _store(tmp_path, events)
    with ReadStore.create(tmp_path / "read-model", PASSPHRASE) as reads:
        reads.synchronize(canonical)
        with reads.open_reader() as revision:
            assert revision.rhythm_hypotheses(as_of="2026-05-31") == []
            actual = revision.rhythm_hypotheses(as_of="2026-06-15")
    expected = LedgerProjection(events, as_of="2026-06-15").rhythm_hypotheses()
    assert _normal(actual) == _normal(expected)


@pytest.mark.parametrize("glyph", ["X", "雪"])
@pytest.mark.parametrize("column", ["attributes_json", "aliases_json"])
def test_rhythm_json_inputs_refuse_limit_plus_one_before_decoding(
        tmp_path: Path, glyph: str, column: str):
    canonical = _store(tmp_path, _events())
    with ReadStore.create(tmp_path / "read-model", PASSPHRASE) as reads:
        reads.synchronize(canonical)
        base = ({"counterparty_kind": "business", "billing": "standing",
                 "billing_period": "monthly"} if column == "attributes_json"
                else ["LUMEN STREAMING"])
        table, predicate = "merchant_history", "merchant_key='lumen streaming'"
        envelope = ({**base, "padding": ""} if isinstance(base, dict)
                    else [*base, ""])
        shell = json.dumps(envelope, ensure_ascii=False)
        bound = 1_000_000
        room = bound - len(shell.encode("utf-8"))
        padding = glyph * (room // len(glyph.encode("utf-8"))) + "X" * (room % len(glyph.encode("utf-8")))
        if isinstance(base, dict):
            payload = {**base, "padding": padding}
        else:
            payload = [*base, padding]
        at_limit = json.dumps(payload, ensure_ascii=False)
        assert len(at_limit.encode("utf-8")) == bound
        reads.publish(lambda connection: connection.execute(
            f"UPDATE {table} SET {column}=? WHERE {predicate}", (at_limit,)),
            copy_current=True)
        with reads.open_reader() as revision:
            revision.rhythm_hypotheses(as_of="2026-05-01")
        oversized = json.dumps(
            {**payload, "padding": padding + "X"} if isinstance(payload, dict)
            else [*base, padding + "X"], ensure_ascii=False)
        assert len(oversized.encode("utf-8")) == bound + 1
        reads.publish(lambda connection: connection.execute(
            f"UPDATE {table} SET {column}=? WHERE {predicate}", (oversized,)),
            copy_current=True)
        with reads.open_reader() as revision:
            old_select = revision.connection.execute(
                f"SELECT {column} FROM {table} WHERE {predicate}").fetchone()[0]
            assert len(old_select.encode("utf-8")) == bound + 1
            assert json.loads(old_select) == json.loads(oversized)
            with pytest.raises(sql_rhythm.RhythmReadError, match="byte bound"):
                revision.rhythm_hypotheses(as_of="2026-05-01")


@pytest.mark.parametrize("glyph", ["X", "雪"])
def test_rhythm_canonical_profile_exact_utf8_byte_bound_refuses_before_decoding(glyph):
    connection = sqlite3.connect(":memory:")
    connection.executescript(
        "CREATE TABLE accounts(event_type TEXT, account_id TEXT, kind TEXT, "
        "currency TEXT, institution TEXT, occurred_at TEXT, source_sequence INTEGER);"
        "CREATE INDEX accounts_by_source_date ON accounts(source_sequence, occurred_at);"
        "CREATE TABLE transactions(source_sequence INTEGER, occurred_at TEXT, "
        "description TEXT, provenance_doc_id TEXT, provenance_page INTEGER, "
        "provenance_region TEXT, provenance_note TEXT);"
        "CREATE TABLE postings(source_sequence INTEGER, posting_index INTEGER, "
        "account_id TEXT, amount_text TEXT, grade TEXT);"
        "CREATE TABLE resolver_profiles(institution TEXT, account_kind TEXT, "
        "profile_json TEXT);")
    try:
        base = Profile("Bound Bank", "depository", "v1",
                       templates=[Template("PAY {brand}")])
        shell = json.dumps(base.to_dict(), sort_keys=True, separators=(",", ":"))
        bound = sql_rhythm.MAX_RHYTHM_JSON_BYTES
        glyph_bytes = len(glyph.encode("utf-8"))
        room = bound - len(shell.encode("utf-8"))
        padding = glyph * (room // glyph_bytes) + "X" * (room % glyph_bytes)
        for extra in ("", "X"):
            institution = base.institution
            profile = Profile(institution, "depository", "v1",
                              templates=[Template("PAY {brand}" + padding + extra)])
            encoded = json.dumps(profile.to_dict(), sort_keys=True,
                                 separators=(",", ":"), ensure_ascii=False)
            assert len(encoded.encode("utf-8")) == bound + len(extra)
            connection.execute("DELETE FROM resolver_profiles")
            connection.execute(
                "INSERT INTO resolver_profiles VALUES(?,?,?)",
                (institution, "depository", encoded))
            old_select = connection.execute(
                "SELECT profile_json FROM resolver_profiles ORDER BY institution,account_kind"
            ).fetchone()[0]
            assert Profile.from_dict(json.loads(old_select)).to_dict() == profile.to_dict()
            if extra:
                with pytest.raises(sql_rhythm.RhythmReadError, match="byte bound"):
                    sql_rhythm._movement_rows(connection, "2026-05-01")
            else:
                sql_rhythm._movement_rows(connection, "2026-05-01")
    finally:
        connection.close()


def test_work_bounds_and_query_plans_are_explicit(tmp_path: Path, monkeypatch):
    canonical = _store(tmp_path, _events())
    with ReadStore.create(tmp_path / "read-model", PASSPHRASE) as reads:
        reads.synchronize(canonical)
        with reads.open_reader() as revision:
            traced = []
            revision.connection.set_trace_callback(traced.append)
            revision.rhythm_hypotheses(as_of="2026-05-01")
            revision.connection.set_trace_callback(None)
            plans = [revision.connection.execute(
                "EXPLAIN QUERY PLAN " + sql).fetchall() for sql in traced
                if sql.lstrip().upper().startswith(("SELECT", "WITH"))]
            plan_text = "\n".join(str(row) for plan in plans for row in plan)
            assert "transactions_by_date_source" in plan_text
            assert "accounts_by_source_date" in plan_text
            assert "merchant_history_by_date_source" in plan_text
            assert "transfer_history_by_date_source" in plan_text
            assert "ruling_history_by_scope_order" in plan_text
            merchant_plans = [plan for sql, plan in zip(
                (sql for sql in traced if sql.lstrip().upper().startswith(("SELECT", "WITH"))),
                plans) if "FROM merchant_history" in sql]
            assert len(merchant_plans) == 1
            assert "TEMP B-TREE" not in str(merchant_plans[0]).upper()
            profile_plans = [plan for sql, plan in zip(
                (sql for sql in traced if sql.lstrip().upper().startswith(("SELECT", "WITH"))),
                plans) if "FROM resolver_profiles" in sql]
            assert len(profile_plans) == 1
            assert "TEMP B-TREE" not in str(profile_plans[0]).upper()
            assert "OFFSET" not in "\n".join(traced).upper()
            selected = [sql for sql in traced
                        if sql.lstrip().upper().startswith(("SELECT", "WITH"))]
            assert selected
            assert all("LIMIT" in sql.upper() for sql in selected), selected
            monkeypatch.setattr(sql_rhythm, "MAX_RHYTHM_POSTING_ROWS", 2)
            with pytest.raises(sql_rhythm.RhythmReadError, match="2-row read bound"):
                revision.rhythm_hypotheses(as_of="2026-05-01")
            account_plan = " ".join(row[3] for row in revision.connection.execute(
                "EXPLAIN QUERY PLAN SELECT event_type,account_id,kind,currency,institution "
                "FROM accounts INDEXED BY accounts_by_source_date "
                "WHERE occurred_at<=? ORDER BY source_sequence LIMIT ?",
                ("2026-05-01", 10)))
            assert "accounts_by_source_date" in account_plan
            assert "TEMP B-TREE" not in account_plan.upper()
            plan = " ".join(row[3] for row in revision.connection.execute(
                "EXPLAIN QUERY PLAN SELECT t.source_sequence FROM transactions t "
                "JOIN postings p ON p.source_sequence=t.source_sequence "
                "WHERE t.occurred_at>=? AND t.occurred_at<=? "
                "ORDER BY t.occurred_at,t.source_sequence,p.posting_index LIMIT ?",
                ("2016-04-24", "2026-05-01", 10)))
            assert "transactions_by_date_source" in plan
            assert "OFFSET" not in plan.upper()


def _assert_bound(tmp_path, monkeypatch, events, constant, message, *, profiles=False):
    if profiles:
        directory = tmp_path / "profiles"
        directory.mkdir()
        monkeypatch.setenv("VIVA_PROFILES", str(directory))
        ProfileStore(directory).write(Profile(
            "Bound Bank", "depository", "v1",
            templates=[Template("PAY {brand}")]))
    canonical = _store(tmp_path, events)
    with ReadStore.create(tmp_path / "read-model", PASSPHRASE) as reads:
        reads.synchronize(canonical)
        monkeypatch.setattr(sql_rhythm, constant, 0)
        with reads.open_reader() as revision:
            with pytest.raises(sql_rhythm.RhythmReadError, match=message):
                revision.rhythm_hypotheses(as_of="2026-05-01")


@pytest.mark.parametrize(("constant", "message", "extra"), [
    ("MAX_RHYTHM_ACCOUNTS", "account history", ()),
    ("MAX_MERCHANT_HISTORY", "merchant history", ()),
    ("MAX_TRANSFER_HISTORY", "transfer history",
     (transfer_linked("left", "right", "verified", {}, "2026-04-07"),)),
    ("MAX_RHYTHM_RULINGS", "rhythm ruling history",
     (ruling_recorded(SCOPE_RHYTHM, "lumen streaming|out", "2026-04-07",
                      value="monthly", grade="verified", by="human"),)),
    ("MAX_RHYTHM_POSTING_ROWS", "rhythm joined posting input", ()),
])
def test_each_sql_rhythm_input_cap_refuses_independently(
        tmp_path: Path, monkeypatch, constant, message, extra):
    _assert_bound(tmp_path, monkeypatch, _events() + list(extra), constant, message)


def test_resolver_profile_input_cap_refuses_independently(tmp_path: Path, monkeypatch):
    events = _events()
    events[0] = account_opened(
        "cash", "depository", "Cash", "USD", "2025-12-01",
        institution="Bound Bank")
    _assert_bound(tmp_path, monkeypatch, events, "MAX_RESOLVER_PROFILES",
                  "resolver profile input", profiles=True)


def test_group_per_group_result_and_window_caps_refuse_independently(
        tmp_path: Path, monkeypatch):
    canonical = _store(tmp_path, _events())
    with ReadStore.create(tmp_path / "read-model", PASSPHRASE) as reads:
        reads.synchronize(canonical)
        with reads.open_reader() as revision:
            with monkeypatch.context() as scoped:
                scoped.setattr(sql_rhythm, "MAX_RHYTHM_GROUPS", 0)
                with pytest.raises(sql_rhythm.RhythmReadError, match="group read bound"):
                    revision.rhythm_hypotheses(as_of="2026-05-01")
            with monkeypatch.context() as scoped:
                scoped.setattr(sql_rhythm, "MAX_GROUP_MOVEMENTS", 1)
                with pytest.raises(sql_rhythm.RhythmReadError, match="movement bound"):
                    revision.rhythm_hypotheses(as_of="2026-05-01")

    two = _events() + [
        simple_transaction("cash", "-7", "SECOND SERVICE", when,
                           kind="depository")
        for when in ("2026-01-06", "2026-02-06", "2026-03-06")]
    two.append(merchant_enriched(
        "second service", "other", grade=CORROBORATED,
        occurred_at="2026-04-06", by="model",
        attributes={"counterparty_kind": "business", "billing": "standing",
                    "billing_period": "monthly"}))
    canonical = _store(tmp_path / "two", two)
    with ReadStore.create(tmp_path / "two" / "read-model", PASSPHRASE) as reads:
        reads.synchronize(canonical)
        with reads.open_reader() as revision:
            with pytest.raises(sql_rhythm.RhythmReadError, match="requested 1-row bound"):
                revision.rhythm_hypotheses(as_of="2026-05-01", limit=1)

    old = _events() + [simple_transaction(
        "cash", "-1", "ANCIENT", "2010-01-01", kind="depository")]
    canonical = _store(tmp_path / "old", old)
    with ReadStore.create(tmp_path / "old" / "read-model", PASSPHRASE) as reads:
        reads.synchronize(canonical)
        with reads.open_reader() as revision:
            with pytest.raises(sql_rhythm.RhythmReadError, match="candidate window"):
                revision.rhythm_hypotheses(as_of="2026-05-01")


def _additional_service(name: str, amount: str):
    key = name.lower()
    events = [simple_transaction("cash", amount, name, when, kind="depository")
              for when in ("2026-01-05", "2026-02-05", "2026-03-05")]
    events.append(merchant_enriched(
        key, "other", grade=CORROBORATED, occurred_at="2026-04-06", by="model",
        attributes={"counterparty_kind": "business", "billing": "standing",
                    "billing_period": "monthly"}))
    return events


def test_many_incoming_rhythms_cannot_hide_a_valid_outgoing_obligation(tmp_path: Path):
    events = _events()
    for left in "abcdefgh":
        for right in "abcdefghijklmnopqrstuvwxyz":
            if len(events) >= 6 + (201 * 4):
                break
            events += _additional_service(f"INBOUND {left}{right}", "5.00")
        if len(events) >= 6 + (201 * 4):
            break
    canonical = _store(tmp_path, events)
    with ReadStore.create(tmp_path / "read-model", PASSPHRASE) as reads:
        reads.synchronize(canonical)
        with reads.open_reader() as revision:
            with pytest.raises(sql_rhythm.RhythmReadError, match="rhythm result"):
                revision.rhythm_hypotheses(as_of="2026-05-01")
            actual = revision.obligations(today="2026-05-01", limit=1)
    expected = LedgerProjection(events, as_of="2026-05-01").obligations("2026-05-01")
    assert len(actual) == 1
    assert _normal(actual) == _normal(expected)


def test_obligation_candidate_and_result_caps_refuse_independently(
        tmp_path: Path, monkeypatch):
    events = _events() + _additional_service("SECOND SERVICE", "-7.00")
    canonical = _store(tmp_path, events)
    with ReadStore.create(tmp_path / "read-model", PASSPHRASE) as reads:
        reads.synchronize(canonical)
        with reads.open_reader() as revision:
            with pytest.raises(sql_rhythm.RhythmReadError, match="obligation result"):
                revision.obligations(today="2026-05-01", limit=1)
            with monkeypatch.context() as scoped:
                scoped.setattr(sql_rhythm, "MAX_OBLIGATION_RHYTHMS", 1)
                with pytest.raises(sql_rhythm.RhythmReadError,
                                   match="obligation rhythm candidates"):
                    revision.obligations(today="2026-05-01")


def test_identity_evolution_alias_conflicts_backfills_and_missing_provenance_match_oracle(
        tmp_path: Path, monkeypatch):
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    monkeypatch.setenv("VIVA_PROFILES", str(profiles))
    ProfileStore(profiles).write(Profile(
        "Evolving Bank", "depository", "v1",
        templates=[Template("PAY {brand}")]))
    events = [
        account_opened("cash", "depository", "Cash", "USD", "2025-12-01"),
        # Identity arrives after the account was opened; the resolver must use
        # the strengthened institution for every historical descriptor.
        account_identity_observed("cash", "2026-01-02", institution="Evolving Bank"),
        # Canonical order differs from append order and two identical siblings
        # have no provenance. Their stable occurrence keys must still agree.
        simple_transaction("cash", "-10.00", "PAY LUMEN", "2026-03-05",
                           kind="depository"),
        simple_transaction("cash", "-10.00", "PAY LUMEN", "2026-01-05",
                           kind="depository"),
        simple_transaction("cash", "-10.00", "PAY LUMEN", "2026-02-05",
                           kind="depository"),
        simple_transaction("cash", "-10.00", "PAY LUMEN", "2026-02-05",
                           kind="depository"),
        merchant_enriched(
            "lumen", "other", aliases=["pay lumen"], grade=CORROBORATED,
            occurred_at="2026-03-06", by="model",
            attributes={"counterparty_kind": "business", "billing": "standing",
                        "billing_period": "monthly"}),
        # Equal-grade competing ownership makes the alias conflicted rather
        # than allowing source order to choose a merchant silently.
        merchant_enriched(
            "other lumen", "other", aliases=["pay lumen"], grade=CORROBORATED,
            occurred_at="2026-03-07", by="model",
            attributes={"counterparty_kind": "business", "billing": "standing",
                        "billing_period": "monthly"}),
    ]
    canonical = EventStore.open(tmp_path / "events.jsonl", PASSPHRASE)
    with ReadStore.create(tmp_path / "read-model", PASSPHRASE) as reads:
        # Exercise arbitrary suffix batch boundaries and restart publication.
        start = 0
        for count in (2, 5, len(events)):
            for event in events[start:count]:
                canonical.append(event)
            reads.synchronize(canonical)
            start = count
        with reads.open_reader() as revision:
            actual = revision.rhythm_hypotheses(as_of="2026-04-01")
    expected = LedgerProjection(
        events, as_of="2026-04-01",
        resolve_keys=__import__("viva.ledger.merchant_keys", fromlist=["installed_resolver"])
        .installed_resolver()).rhythm_hypotheses()
    assert _normal(actual) == _normal(expected)

    with ReadStore.open(tmp_path / "read-model", PASSPHRASE) as reopened:
        with reopened.open_reader() as revision:
            assert _normal(revision.rhythm_hypotheses(as_of="2026-04-01")) == \
                   _normal(expected)


def test_frozen_profile_and_changed_profile_rebuild_remain_oracle_equivalent(
        tmp_path: Path, monkeypatch):
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    monkeypatch.setenv("VIVA_PROFILES", str(profiles))
    profile_store = ProfileStore(profiles)
    institution = "Profile Bank"
    profile_store.write(Profile(institution, "depository", "v1",
                               templates=[Template("PAY {brand}")]))
    events = _events(description="PAY LUMEN")
    events[0] = account_opened("cash", "depository", "Cash", "USD",
                               "2025-12-01", institution=institution)
    # Catalog both possible resolver outputs so the profile change exercises
    # identity without changing whether the cadence is licensed.
    attributes = {"counterparty_kind": "business", "billing": "standing",
                  "billing_period": "monthly"}
    events[-1] = merchant_enriched("lumen", "other", grade=CORROBORATED,
                                   occurred_at="2026-04-06", by="model",
                                   attributes=attributes)
    events.append(merchant_enriched("pay lumen", "other", grade=CORROBORATED,
                                    occurred_at="2026-04-06", by="model",
                                    attributes=attributes))
    canonical = _store(tmp_path, events)
    resolve = __import__("viva.ledger.merchant_keys", fromlist=["installed_resolver"])
    with ReadStore.create(tmp_path / "read-model", PASSPHRASE) as reads:
        reads.synchronize(canonical)
        old = reads.open_reader()
        old_value = old.rhythm_hypotheses(as_of="2026-05-01")
        profile_store.write(Profile(institution, "depository", "v2",
                                   templates=[Template("{counterparty}")]))
        # The held revision keeps its frozen v1 profile.
        assert old.rhythm_hypotheses(as_of="2026-05-01") == old_value
        assert reads.synchronize(canonical).state == "rebuilt"
        with reads.open_reader() as revision:
            actual = revision.rhythm_hypotheses(as_of="2026-05-01")
        old.close()
    expected = LedgerProjection(
        events, as_of="2026-05-01",
        resolve_keys=resolve.installed_resolver()).rhythm_hypotheses()
    assert _normal(actual) == _normal(expected)
