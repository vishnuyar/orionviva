"""Scoped SQL movement and statement components for account-ledger reads."""

import base64
import json

import pytest

from viva.demo import build_demo_vault
from viva.ledger import account_opened, simple_transaction
from viva.ledger import EventStore
from viva.ledger.events import (Provenance, closing_balance_observed,
                                document_captured, read_recorded,
                                transfer_linked)
from viva.surface.account_ledger import _coverage, _deduplicate, _overlap
from viva.surface.account_ledger import AccountLedgerIdentityError
from viva.surface.account_ledger import (AccountLedgerCursorError,
                                         account_ledger, sql_account_ledger_page)
from viva.read_store import ReadStoreError
from viva.vault import Vault
from viva.read_store import ReadStore, ReadStoreDegraded
from viva.desktop_bridge.vault_surface import OpenedVaultSurfaceProvider


@pytest.fixture(autouse=True)
def _stable_locale(monkeypatch):
    monkeypatch.setenv("VIVA_LOCALE", "en-US")


def _page(revision, *args, **kwargs):
    return sql_account_ledger_page(revision.account_ledger_page(*args, **kwargs))


def _identity(movement):
    return (movement.key, movement.account, movement.kind, movement.date,
            movement.amount, movement.description, movement.currency,
            movement.provenance, movement.linked, movement.nature,
            movement.nature_reason, movement.provisional,
            movement.ruling_account)


def test_account_components_match_canonical_sample_semantics(tmp_path):
    vault = build_demo_vault(tmp_path / "sample")
    canonical = vault.ledger.projection()
    for account in canonical.accounts():
        expected_movements = [movement for movement in canonical.movements()
                              if movement.account == account]
        statements = canonical.statements(account)
        records = list(statements.records) if statements else []
        expected_entries, expected_dedup = _deduplicate(expected_movements, records)
        expected_coverage = _coverage(records, list(statements.runs) if statements else [])
        expected_overlap = _overlap(records)
        expected_overlap["deduplication"] = expected_dedup
        with vault.read_store.open_reader() as revision:
            actual = revision.account_ledger_components(account)
        assert sorted(map(_identity, actual.movements)) == sorted(
            map(_identity, expected_movements))
        assert actual.statements == statements
        assert actual.coverage == expected_coverage
        assert actual.overlap == expected_overlap
        def members(entries):
            return {entry["movement"].key: [member.key for member in entry["members"]]
                    for entry in entries}
        assert members(actual.entries) == members(expected_entries)


def test_indexed_keyset_matches_complete_sample_payload_page_by_page(tmp_path):
    vault = build_demo_vault(tmp_path / "sample")
    projection = vault.ledger.projection()
    secret = b"ledger-page-test-secret-key-32-bytes!"
    with vault.read_store.open_reader() as revision:
        source_head = revision.connection.execute(
            "SELECT source_head FROM projection_meta WHERE singleton=1").fetchone()[0]
        for info in projection.account_infos():
            if not info.number:
                continue
            expected_cursor = actual_cursor = ""
            while True:
                expected = account_ledger(
                    projection, info.account, "en-US", source_head,
                    cursor_secret=secret, limit=1, cursor=expected_cursor)
                actual = _page(revision,
                    info.account, cursor_secret=secret, limit=1,
                    cursor=actual_cursor)
                assert {**actual, "page": {**actual["page"], "next_cursor": None}} == {
                    **expected, "page": {**expected["page"], "next_cursor": None}}
                actual_cursor = actual["page"]["next_cursor"] or ""
                expected_cursor = expected["page"]["next_cursor"] or ""
                if not actual_cursor:
                    assert not expected_cursor
                    break


def test_indexed_cursor_refuses_forgery_noncanonical_account_and_stale(tmp_path):
    vault = build_demo_vault(tmp_path / "sample")
    secret = b"ledger-page-test-secret-key-32-bytes!"
    account = "acct:everyday-checking"
    held = vault.read_store.open_reader()
    first = _page(held, account, cursor_secret=secret, limit=1)
    cursor = first["page"]["next_cursor"]
    assert cursor
    for bad in (cursor + "A", cursor + "=", "!" * 9000):
        with pytest.raises(AccountLedgerCursorError):
            _page(held, account, cursor_secret=secret,
                                     limit=1, cursor=bad)
    envelope = json.loads(base64.urlsafe_b64decode(
        cursor + "=" * (-len(cursor) % 4)))
    noncanonical = base64.urlsafe_b64encode(
        json.dumps(envelope, indent=2).encode()).decode().rstrip("=")
    with pytest.raises(AccountLedgerCursorError, match="malformed"):
        _page(held, account, cursor_secret=secret,
                                 limit=1, cursor=noncanonical)
    with pytest.raises(AccountLedgerCursorError, match="another account"):
        _page(held, "acct:rainy-day-savings", cursor_secret=secret,
                                 limit=1, cursor=cursor)
    vault.ledger.append(simple_transaction(
        account, "-3.00", "NEW", "2026-07-01", kind="depository"))
    assert _page(held, account, cursor_secret=secret,
                                    limit=1, cursor=cursor)["page"]["returned"] == 1
    with vault.read_store.open_reader() as current:
        with pytest.raises(AccountLedgerCursorError, match="stale"):
            _page(current, account, cursor_secret=secret,
                                        limit=1, cursor=cursor)
    held.close()


def test_indexed_page_has_explicit_limit_locale_and_index_plan(tmp_path):
    vault = build_demo_vault(tmp_path / "sample")
    secret = b"ledger-page-test-secret-key-32-bytes!"
    with vault.read_store.open_reader() as revision:
        with pytest.raises(ValueError, match="between 1 and 100"):
            _page(revision, "acct:everyday-checking",
                                         cursor_secret=secret, limit=101)
        with pytest.raises(ReadStoreError, match="locale"):
            _page(revision, "acct:everyday-checking", locale="fr-FR",
                                         cursor_secret=secret)
        traced = []
        revision.connection.set_trace_callback(traced.append)
        _page(revision, "acct:everyday-checking",
                                     cursor_secret=secret, limit=1)
        revision.connection.set_trace_callback(None)
        selects = [statement for statement in traced
                   if statement.lstrip().upper().startswith("SELECT")]
        assert not any(" OFFSET " in statement.upper() for statement in selects)
        assert not any("FROM movements INDEXED BY movements_by_account_ledger_order"
                       in statement for statement in selects)
        page_sql = next(statement for statement in selects
                        if "FROM account_ledger_component_index INDEXED BY"
                        in statement and "ORDER BY" in statement)
        assert "LIMIT 2" in page_sql
        plan = " ".join(str(row[3]) for row in revision.connection.execute(
            "EXPLAIN QUERY PLAN " + page_sql).fetchall())
        assert "account_ledger_components_by_page" in plan
        assert "USE TEMP B-TREE" not in plan


def test_indexed_page_never_invokes_account_component_replay(tmp_path, monkeypatch):
    vault = build_demo_vault(tmp_path / "sample")
    monkeypatch.setattr("viva.read_store.account_ledger.components",
                        lambda *_a, **_kw: pytest.fail("account replayed per page"))
    monkeypatch.setattr(vault.ledger, "projection",
                        lambda: pytest.fail("canonical projection replay"))
    monkeypatch.setattr(vault.ledger.store, "snapshot_events",
                        lambda: pytest.fail("canonical event prefix"))
    monkeypatch.setattr(vault.raw, "doc_ids",
                        lambda: pytest.fail("raw enumeration"))
    with vault.read_store.open_reader() as revision:
        page = _page(revision,
            "acct:everyday-checking", cursor_secret=b"x" * 32, limit=1)
    assert page["page"]["returned"] == 1


def test_global_component_bound_refuses_new_generation_without_losing_old(
        tmp_path, monkeypatch):
    vault = build_demo_vault(tmp_path / "sample")
    held = vault.read_store.open_reader()
    account = "acct:everyday-checking"
    secret = b"x" * 32
    before = _page(held, account, cursor_secret=secret)
    monkeypatch.setattr("viva.read_store.account_ledger.MAX_INDEX_COMPONENTS", 0)
    vault.ledger.append(simple_transaction(
        account, "-1.00", "LATE", "2026-07-02", kind="depository"))
    assert vault.synchronize_read_store() in {"stale", "degraded"}
    assert _page(held, account, cursor_secret=secret) == before
    held.close()


def test_account_components_are_scoped_before_read_and_refuse_n_plus_one(
        tmp_path, monkeypatch):
    vault = Vault.open(tmp_path / "vault", "pw")
    vault.ledger.append(account_opened("a", "depository", "A", "USD", "2026-01-01"))
    vault.ledger.append(account_opened("b", "depository", "B", "USD", "2026-01-01"))
    for account in ("a", "b"):
        for number in range(2):
            vault.ledger.append(simple_transaction(
                account, "-1", f"ROW {account}{number}", "2026-01-02",
                kind="depository"))
    vault.synchronize_read_store()
    assert vault.read_store_lifecycle in {"equal", "rebuilt", "caught_up"}
    monkeypatch.setattr("viva.read_store.account_ledger.MAX_ACCOUNT_MOVEMENTS", 1)
    with vault.read_store.open_reader() as revision:
        with pytest.raises(Exception, match="movements exceed.*bound"):
            revision.account_ledger_components("a")


def _overlap_vault(tmp_path):
    vault = Vault.open(tmp_path / "vault", "pw")
    vault.ledger.append(account_opened(
        "a", "depository", "A", "USD", "2026-01-01",
        account_number="000000004417"))
    for doc, start, opening in (("jan", "2026-01-01", "100"),
                                ("overlap", "2026-01-15", "95")):
        provenance = Provenance(doc, 1, "statement")
        response = (
            '{"opening":{"amount_raw":"' + opening + '","date_raw":"' + start + '"},'
            '"closing":{"amount_raw":"90","date_raw":"2026-01-31"},'
            '"transactions":[]}')
        vault.ledger.append(document_captured(
            doc, doc + ".pdf", 1, "checking_statement", 1,
            "2026-02-01", provenance))
        vault.ledger.append(read_recorded(
            doc, "route", "v1", "text", response, 0, 0, 0, True, None,
            "2026-02-01", provenance))
        vault.ledger.append(simple_transaction(
            "a", "-10.00", "SAME MERCHANT", "2026-01-20",
            kind="depository", provenance=provenance))
        vault.ledger.append(closing_balance_observed(
            "a", "90", "2026-01-31", provenance))
    vault.synchronize_read_store()
    return vault


@pytest.mark.parametrize("glyph", ["X", "雪"])
def test_account_statement_response_refuses_utf8_limit_plus_one_before_fetch(
        tmp_path, glyph):
    from viva.read_store import account_ledger as sql_ledger

    vault = _overlap_vault(tmp_path)
    with vault.read_store.open_reader() as revision:
        original = revision.connection.execute(
            "SELECT response_text FROM document_reads WHERE doc_id='jan' LIMIT 1"
        ).fetchone()[0]
    base = json.loads(original)
    bound = sql_ledger.MAX_STATEMENT_RESPONSE_BYTES
    shell = json.dumps({**base, "padding": ""}, ensure_ascii=False)
    room = bound - len(shell.encode("utf-8"))
    width = len(glyph.encode("utf-8"))
    padding = glyph * (room // width) + "X" * (room % width)
    for extra in ("", "X"):
        encoded = json.dumps({**base, "padding": padding + extra},
                             ensure_ascii=False)
        assert len(encoded.encode("utf-8")) == bound + len(extra)
        vault.read_store.publish(lambda connection: connection.execute(
            "UPDATE document_reads SET response_text=? WHERE doc_id='jan'",
            (encoded,)), copy_current=True)
        with vault.read_store.open_reader() as revision:
            old_select = revision.connection.execute(
                "SELECT response_text FROM document_reads WHERE doc_id='jan' LIMIT 1"
            ).fetchone()[0]
            assert json.loads(old_select) == json.loads(encoded)
            traced = []
            revision.connection.set_trace_callback(traced.append)
            if extra:
                with pytest.raises(ReadStoreError, match="statement response exceeds its byte bound"):
                    sql_ledger._statements(revision.connection, "a", "en-US")
            else:
                assert sql_ledger._statements(revision.connection, "a", "en-US")
            revision.connection.set_trace_callback(None)
            bounded = [sql for sql in traced if "FROM statement_periods p" in sql
                       and "CASE WHEN length(CAST(r.response_text AS BLOB))" in sql]
            assert len(bounded) == 1
            plan = " ".join(str(row[-1]) for row in revision.connection.execute(
                "EXPLAIN QUERY PLAN " + bounded[0]).fetchall())
            assert "TEMP B-TREE" not in plan.upper()


@pytest.mark.parametrize("glyph", ["X", "雪"])
def test_cross_account_ownership_response_refuses_before_fetch_and_preserves_empty(
        tmp_path, glyph):
    from viva.read_store import account_ledger as sql_ledger

    vault = _overlap_vault(tmp_path)
    vault.ledger.append(account_opened(
        "b", "depository", "B", "USD", "2026-01-01"))
    vault.ledger.append(closing_balance_observed(
        "b", "90", "2026-01-31", Provenance("jan", 1, "statement")))
    vault.synchronize_read_store()
    with vault.read_store.open_reader() as revision:
        original = revision.connection.execute(
            "SELECT response_text FROM document_reads WHERE doc_id='jan' LIMIT 1"
        ).fetchone()[0]
        ownership_records = list(sql_ledger._statements(
            revision.connection, "a", "en-US").records)
    base = json.loads(original)
    bound = sql_ledger.MAX_STATEMENT_RESPONSE_BYTES
    shell = json.dumps({**base, "padding": ""}, ensure_ascii=False)
    room = bound - len(shell.encode("utf-8"))
    width = len(glyph.encode("utf-8"))
    padding = glyph * (room // width) + "X" * (room % width)
    for extra in ("", "X"):
        encoded = json.dumps({**base, "padding": padding + extra},
                             ensure_ascii=False)
        assert len(encoded.encode("utf-8")) == bound + len(extra)
        vault.read_store.publish(lambda connection: connection.execute(
            "UPDATE document_reads SET response_text=? WHERE doc_id='jan'",
            (encoded,)), copy_current=True)
        with vault.read_store.open_reader() as revision:
            old_select = revision.connection.execute(
                "SELECT response_text FROM document_reads WHERE doc_id='jan' LIMIT 1"
            ).fetchone()[0]
            assert json.loads(old_select) == json.loads(encoded)
            traced = []
            revision.connection.set_trace_callback(traced.append)
            with pytest.raises(
                    ReadStoreError if extra else AccountLedgerIdentityError,
                    match="byte bound" if extra else "belongs to another account"):
                sql_ledger._check_ownership(
                    revision.connection, "a", [], ownership_records, "en-US")
            revision.connection.set_trace_callback(None)
            bounded = [sql for sql in traced if "p.account_id<>" in sql
                       and "CASE WHEN length(CAST(r.response_text AS BLOB))" in sql]
            assert len(bounded) == 1
            plan = " ".join(str(row[-1]) for row in revision.connection.execute(
                "EXPLAIN QUERY PLAN " + bounded[0]).fetchall())
            assert "TEMP B-TREE" not in plan.upper()
    vault.read_store.publish(lambda connection: connection.execute(
        "UPDATE document_reads SET response_text='' WHERE doc_id='jan'"),
        copy_current=True)
    with vault.read_store.open_reader() as revision:
        sql_ledger._check_ownership(
            revision.connection, "a", [], ownership_records, "en-US")


def test_account_components_collapse_only_exact_overlapping_statement_rows(tmp_path):
    vault = _overlap_vault(tmp_path)
    canonical = vault.ledger.projection()
    with vault.read_store.open_reader() as revision:
        actual = revision.account_ledger_components("a")
    assert actual.statements == canonical.statements("a")
    expected_entries, expected_dedup = _deduplicate(
        canonical.movements(), canonical.statements("a").records)
    assert len(actual.entries) == len(expected_entries) == 1
    assert actual.overlap["deduplication"] == expected_dedup
    assert actual.overlap["deduplication"]["state"] == "exact_duplicates_collapsed"
    assert len(actual.entries[0]["members"]) == 2


def test_desktop_sql_page_preserves_statement_overlap_coverage_and_evidence(tmp_path):
    vault = _overlap_vault(tmp_path)
    provider = OpenedVaultSurfaceProvider(vault, cursor_secret=b"x" * 32)
    with vault.read_store.open_reader() as revision:
        head = revision.connection.execute(
            "SELECT source_head FROM projection_meta WHERE singleton=1").fetchone()[0]
    expected = account_ledger(
        vault.ledger.projection(), "a", "en-US", head, cursor_secret=b"x" * 32)
    actual = provider.read_surface("account_ledger", {"account_id": "a"})
    assert actual == expected
    assert actual["sources"] == [
        {"document_id": "jan", "account_id": "a", "filename": "jan.pdf",
         "relation": "statement_and_movement_evidence",
         "period": {"from": "2026-01-01", "to": "2026-01-31"}},
        {"document_id": "overlap", "account_id": "a",
         "filename": "overlap.pdf",
         "relation": "statement_and_movement_evidence",
         "period": {"from": "2026-01-15", "to": "2026-01-31"}},
    ]
    assert (actual["reconciliation"]["overlap"]["deduplication"]["state"]
            == "exact_duplicates_collapsed")


def test_account_ledger_optional_statement_and_movement_only_sources_have_full_parity(
        tmp_path):
    vault = Vault.open(tmp_path / "vault", "pw")
    vault.ledger.append(account_opened(
        "a", "depository", "A", "USD", "2026-01-01",
        account_number="000000004417"))
    statement = Provenance("statement", 1, "period")
    receipt = Provenance("receipt", 1, "transaction")
    vault.ledger.append(document_captured(
        "statement", "statement.pdf", 1, "checking_statement", 1,
        "2026-02-01", statement))
    vault.ledger.append(read_recorded(
        "statement", "route", "v1", "text",
        '{"opening":{"amount_raw":"100","date_raw":"2026-01-01"},'
        '"closing":{"amount_raw":"90","date_raw":"2026-01-31"},'
        '"transactions":[]}', 0, 0, 0, True, None, "2026-02-01", statement))
    vault.ledger.append(closing_balance_observed(
        "a", "90", "2026-01-31", statement))
    vault.ledger.append(document_captured(
        "receipt", "receipt.png", 1, "receipt", 1,
        "2026-02-01", receipt))
    vault.ledger.append(simple_transaction(
        "a", "-10", "RECEIPT PURCHASE", "2026-01-20",
        kind="depository", provenance=receipt))
    vault.ledger.append(simple_transaction(
        "a", "-1", "UNCAPTURED EVIDENCE", "2026-01-21",
        kind="depository", provenance=Provenance("uncaptured", 1, "note")))
    vault.synchronize_read_store()
    with vault.read_store.open_reader() as revision:
        head = revision.connection.execute(
            "SELECT source_head FROM projection_meta WHERE singleton=1"
        ).fetchone()[0]
    secret = b"x" * 32
    expected = account_ledger(
        vault.ledger.projection(), "a", "en-US", head,
        cursor_secret=secret)
    actual = OpenedVaultSurfaceProvider(
        vault, cursor_secret=secret).read_surface(
            "account_ledger", {"account_id": "a"})
    assert actual == expected
    assert actual["sources"] == [
        {"document_id": "receipt", "account_id": "a",
         "filename": "receipt.png", "relation": "movement_evidence",
         "period": None},
        {"document_id": "statement", "account_id": "a",
         "filename": "statement.pdf", "relation": "statement",
         "period": {"from": "2026-01-01", "to": "2026-01-31"}},
        {"document_id": "uncaptured", "account_id": "a",
         "filename": "", "relation": "movement_evidence",
         "period": None},
    ]


def test_account_statement_components_refuse_n_plus_one(tmp_path, monkeypatch):
    vault = _overlap_vault(tmp_path)
    monkeypatch.setattr("viva.read_store.account_ledger.MAX_ACCOUNT_STATEMENTS", 1)
    with vault.read_store.open_reader() as revision:
        with pytest.raises(Exception, match="statements exceed.*bound"):
            revision.account_ledger_components("a")


def test_account_component_queries_are_scoped_and_index_planned(tmp_path):
    vault = _overlap_vault(tmp_path)
    with vault.read_store.open_reader() as revision:
        traced = []
        revision.connection.set_trace_callback(traced.append)
        revision.account_ledger_components("a")
        revision.connection.set_trace_callback(None)
        selects = [statement for statement in traced
                   if statement.lstrip().upper().startswith("SELECT")]
        plans = [" ".join(str(row[3]) for row in revision.connection.execute(
            "EXPLAIN QUERY PLAN " + statement).fetchall())
            for statement in selects]
    assert len(selects) <= 5
    assert any("movements_by_account_ledger_order" in plan for plan in plans)
    assert any("statement_periods_by_account_date" in plan for plan in plans)
    assert all("AUTOMATIC" not in plan.upper() for plan in plans)
    movement_plans = [plan for statement, plan in zip(selects, plans)
                      if "FROM movements INDEXED BY movements_by_account_ledger_order"
                      in statement]
    assert len(movement_plans) == 1
    assert "USE TEMP B-TREE" not in movement_plans[0]
    assert all(" WHERE account_id=" in statement or "WHERE p.account_id=" in statement
               or "WHERE p.doc_id IN" in statement
               for statement in selects)


def test_account_components_direct_read_does_not_open_canonical_or_raw(
        tmp_path, monkeypatch):
    vault = _overlap_vault(tmp_path)
    monkeypatch.setattr(vault.ledger, "projection",
                        lambda: pytest.fail("projection replay"))
    monkeypatch.setattr(vault.ledger.store, "snapshot_events",
                        lambda: pytest.fail("event prefix"))
    monkeypatch.setattr(vault.raw, "doc_ids",
                        lambda: pytest.fail("raw enumeration"))
    with vault.read_store.open_reader() as revision:
        result = revision.account_ledger_components("a")
    assert result.entries


def test_account_components_refuse_valid_statement_owned_by_another_account(
        tmp_path):
    vault = _overlap_vault(tmp_path)
    vault.ledger.append(account_opened("b", "depository", "B", "USD", "2026-01-01"))
    vault.ledger.append(closing_balance_observed(
        "b", "90", "2026-01-31", Provenance("jan", 1, "statement")))
    vault.synchronize_read_store()
    assert vault.read_store_lifecycle in {"equal", "rebuilt", "caught_up"}
    canonical = vault.ledger.projection()
    assert canonical.statements("b") is not None
    with vault.read_store.open_reader() as revision:
        assert revision.connection.execute(
            "SELECT COUNT(*) FROM statement_periods WHERE account_id='b'").fetchone()[0] == 1
        with pytest.raises(AccountLedgerIdentityError, match="another account"):
            revision.account_ledger_components("a")
        status = revision.connection.execute(
            "SELECT status FROM account_ledger_component_state WHERE account_id='a'").fetchone()
    assert status == ("identity_error",)


def test_generation_persists_exact_deduplicated_component_and_summary_rows(tmp_path):
    vault = _overlap_vault(tmp_path)
    with vault.read_store.open_reader() as revision:
        direct = revision.account_ledger_components("a")
        state = revision.connection.execute(
            "SELECT locale,status,component_count,coverage_json,overlap_json "
            "FROM account_ledger_component_state WHERE account_id=?", ("a",)).fetchone()
        rows = revision.connection.execute(
            "SELECT occurred_at,canonical_movement_key,members_json "
            "FROM account_ledger_component_index "
            "INDEXED BY account_ledger_components_by_page WHERE account_id=? "
            "ORDER BY occurred_at DESC,canonical_movement_key DESC", ("a",)).fetchall()
    assert state[:3] == ("en-US", "ready", 1)
    assert json.loads(state[3]) == direct.coverage
    assert json.loads(state[4]) == direct.overlap
    assert rows == [(direct.entries[0]["movement"].date,
                     direct.entries[0]["movement"].key,
                     json.dumps([member.key for member in direct.entries[0]["members"]],
                                separators=(",", ":"), ensure_ascii=False))]


def test_component_index_is_generation_held_across_later_append(tmp_path):
    vault = _overlap_vault(tmp_path)
    held = vault.read_store.open_reader()
    def identities(revision):
        return revision.connection.execute(
            "SELECT canonical_movement_key FROM account_ledger_component_index "
            "WHERE account_id='a' ORDER BY occurred_at DESC,canonical_movement_key DESC"
        ).fetchall()
    before = identities(held)
    vault.ledger.append(simple_transaction(
        "a", "-2.00", "NEW", "2026-02-05", kind="depository"))
    assert identities(held) == before
    with vault.read_store.open_reader() as current:
        after = identities(current)
    assert len(after) == len(before) + 1
    held.close()


def test_component_index_keyset_order_uses_named_index_without_temp_sort(tmp_path):
    vault = _overlap_vault(tmp_path)
    with vault.read_store.open_reader() as revision:
        plan = " ".join(str(row[3]) for row in revision.connection.execute(
            "EXPLAIN QUERY PLAN SELECT canonical_movement_key,members_json "
            "FROM account_ledger_component_index "
            "INDEXED BY account_ledger_components_by_page "
            "WHERE account_id=? AND (occurred_at<? OR "
            "(occurred_at=? AND canonical_movement_key<?)) "
            "ORDER BY occurred_at DESC,canonical_movement_key DESC LIMIT ?",
            ("a", "2026-03-01", "2026-03-01", "z", 51)).fetchall())
    assert "account_ledger_components_by_page" in plan
    assert "USE TEMP B-TREE" not in plan


def test_component_index_schema_version_rebuilds_and_binds_locale(
        tmp_path, monkeypatch):
    source = EventStore.open(tmp_path / "events.jsonl", "pw")
    source.append(account_opened("a", "depository", "A", "USD", "2026-01-01"))
    monkeypatch.setenv("VIVA_LOCALE", "de-DE")
    with ReadStore.create(tmp_path / "read-model", "pw") as reads:
        older = reads.synchronize(source, schema_version=25)
        rebuilt = reads.synchronize(source)
        assert older.generation != rebuilt.generation
        assert rebuilt.state == "rebuilt"
        with reads.open_reader() as revision:
            state = revision.connection.execute(
                "SELECT locale,status,component_count "
                "FROM account_ledger_component_state WHERE account_id='a'").fetchone()
    assert state == ("de-DE", "ready", 0)


def test_component_index_failure_never_publishes_partial_generation(
        tmp_path, monkeypatch):
    source = EventStore.open(tmp_path / "events.jsonl", "pw")
    source.append(account_opened("a", "depository", "A", "USD", "2026-01-01"))
    with ReadStore.create(tmp_path / "read-model", "pw") as reads:
        reads.synchronize(source)
        prior = reads.current_generation
        source.append(simple_transaction(
            "a", "-1", "LATER", "2026-01-02", kind="depository"))
        monkeypatch.setattr("viva.read_store.account_ledger.materialize_component_index",
                            lambda _connection: (_ for _ in ()).throw(
                                RuntimeError("injected component failure")))
        with pytest.raises(ReadStoreDegraded):
            reads.synchronize(source)
        assert reads.current_generation == prior
        with reads.open_reader() as revision:
            count = revision.connection.execute(
                "SELECT component_count FROM account_ledger_component_state "
                "WHERE account_id='a'").fetchone()[0]
        assert count == 0


def test_invalid_locale_is_typed_projection_failure_not_process_exit(
        tmp_path, monkeypatch):
    source = EventStore.open(tmp_path / "events.jsonl", "pw")
    source.append(account_opened("a", "depository", "A", "USD", "2026-01-01"))
    monkeypatch.setenv("VIVA_LOCALE", "not a locale")
    with ReadStore.create(tmp_path / "read-model", "pw") as reads:
        with pytest.raises(ReadStoreDegraded) as failure:
            reads.synchronize(source)
    assert "locale is invalid" in str(failure.value.__cause__)
    assert source.authenticated_identity()[0] == 1


def test_component_payload_overflow_is_account_refusal_not_partial_index(
        tmp_path, monkeypatch):
    source = EventStore.open(tmp_path / "events.jsonl", "pw")
    source.append(account_opened("a", "depository", "A", "USD", "2026-01-01"))
    source.append(simple_transaction(
        "a", "-1", "ONE", "2026-01-02", kind="depository"))
    monkeypatch.setattr("viva.read_store.account_ledger.MAX_COMPONENT_JSON_BYTES", 2)
    with ReadStore.create(tmp_path / "read-model", "pw") as reads:
        reads.synchronize(source)
        with reads.open_reader() as revision:
            state = revision.connection.execute(
                "SELECT status,component_count FROM account_ledger_component_state "
                "WHERE account_id='a'").fetchone()
            indexed = revision.connection.execute(
                "SELECT COUNT(*) FROM account_ledger_component_index "
                "WHERE account_id='a'").fetchone()[0]
    assert state == ("refused", 0)
    assert indexed == 0


@pytest.mark.parametrize("glyph", ["X", "雪"])
@pytest.mark.parametrize("column", [
    "coverage_json", "overlap_json", "records_json", "account_json", "balance_json",
])
def test_page_state_json_refuses_exact_utf8_plus_one_before_fetch(
        tmp_path, glyph, column):
    from viva.read_store import account_ledger_page as sql_page

    vault = _overlap_vault(tmp_path)
    secret = b"ledger-page-test-secret-key-32-bytes!"
    with vault.read_store.open_reader() as revision:
        original = revision.connection.execute(
            f"SELECT {column} FROM account_ledger_component_state "
            "WHERE account_id='a'").fetchone()[0]
    base = json.loads(original)
    def padded(value):
        if column == "account_json":
            return {**base, "name": base["name"] + value}
        if column == "records_json":
            return [{**base[0], "padding": value}, *base[1:]]
        return {**base, "padding": value}
    bound = sql_page.MAX_COMPONENT_JSON_BYTES
    shell = json.dumps(padded(""), ensure_ascii=False)
    room = bound - len(shell.encode("utf-8"))
    width = len(glyph.encode("utf-8"))
    padding = glyph * (room // width) + "X" * (room % width)
    for extra in ("", "X"):
        encoded = json.dumps(padded(padding + extra), ensure_ascii=False)
        assert len(encoded.encode("utf-8")) == bound + len(extra)
        vault.read_store.publish(lambda connection: connection.execute(
            f"UPDATE account_ledger_component_state SET {column}=? "
            "WHERE account_id='a'", (encoded,)), copy_current=True)
        with vault.read_store.open_reader() as revision:
            old_select = revision.connection.execute(
                f"SELECT {column} FROM account_ledger_component_state "
                "WHERE account_id='a'").fetchone()[0]
            assert json.loads(old_select) == json.loads(encoded)
            traced = []
            revision.connection.set_trace_callback(traced.append)
            if extra:
                with pytest.raises(ReadStoreError, match="byte bound"):
                    revision.account_ledger_page(
                        "a", locale="en-US", cursor_secret=secret, limit=1)
            else:
                with pytest.raises(ReadStoreError, match="scalar byte bound"):
                    revision.account_ledger_page(
                        "a", locale="en-US", cursor_secret=secret, limit=1)
            revision.connection.set_trace_callback(None)
            selected = [sql for sql in traced if "FROM account_ledger_component_state" in sql
                        and "length(CAST(coverage_json AS BLOB))" in sql]
            assert len(selected) == 1
            plan = " ".join(str(row[-1]) for row in revision.connection.execute(
                "EXPLAIN QUERY PLAN " + selected[0]).fetchall())
            assert "TEMP B-TREE" not in plan.upper()


@pytest.mark.parametrize("glyph", ["X", "雪"])
def test_page_component_members_refuse_plus_one_without_partial_page(tmp_path, glyph):
    from viva.read_store import account_ledger_page as sql_page

    vault = _overlap_vault(tmp_path)
    secret = b"ledger-page-test-secret-key-32-bytes!"
    with vault.read_store.open_reader() as revision:
        row = revision.connection.execute(
            "SELECT canonical_movement_key,members_json "
            "FROM account_ledger_component_index WHERE account_id='a' LIMIT 1"
        ).fetchone()
    key, original = row
    assert key in json.loads(original)
    bound = sql_page.MAX_COMPONENT_JSON_BYTES
    shell = json.dumps([key, ""], ensure_ascii=False)
    room = bound - len(shell.encode("utf-8"))
    width = len(glyph.encode("utf-8"))
    padding = glyph * (room // width) + "X" * (room % width)
    for extra in ("", "X"):
        encoded = json.dumps([key, padding + extra], ensure_ascii=False)
        assert len(encoded.encode("utf-8")) == bound + len(extra)
        vault.read_store.publish(lambda connection: connection.execute(
            "UPDATE account_ledger_component_index SET members_json=? "
            "WHERE canonical_movement_key=?", (encoded, key)), copy_current=True)
        with vault.read_store.open_reader() as revision:
            old_select = revision.connection.execute(
                "SELECT members_json FROM account_ledger_component_index "
                "WHERE canonical_movement_key=?", (key,)).fetchone()[0]
            assert json.loads(old_select) == [key, padding + extra]
            traced = []
            revision.connection.set_trace_callback(traced.append)
            page, _remaining = sql_page._index_page(revision, "a", 100, None)
            revision.connection.set_trace_callback(None)
            selected = [sql for sql in traced if "FROM account_ledger_component_index" in sql
                        and "length(CAST(members_json AS BLOB))" in sql]
            assert len(selected) == 1
            plan = " ".join(str(row[-1]) for row in revision.connection.execute(
                "EXPLAIN QUERY PLAN " + selected[0]).fetchall())
            assert "account_ledger_components_by_page" in plan
            assert "TEMP B-TREE" not in plan.upper()
            selected_row = next(item for item in page if item[1] == key)
            if extra:
                assert selected_row[2] is None
                with pytest.raises(ReadStoreError, match="byte bound"):
                    revision.account_ledger_page(
                        "a", locale="en-US", cursor_secret=secret, limit=100)
            else:
                assert selected_row[2] == encoded
                with pytest.raises(ReadStoreError, match="scalar byte bound"):
                    sql_page._json(selected_row[2], list, "component members")


@pytest.mark.parametrize("glyph", ["X", "雪"])
def test_counterpart_account_json_refuses_before_fetch(tmp_path, glyph):
    from viva.read_store import account_ledger_page as sql_page

    vault = _overlap_vault(tmp_path)
    vault.ledger.append(account_opened("b", "depository", "B", "USD", "2026-01-01"))
    vault.ledger.append(simple_transaction(
        "b", "10.00", "TRANSFER IN", "2026-01-20", kind="depository"))
    movements = vault.ledger.projection().movements()
    a_key = next(item.key for item in movements if item.account == "a")
    b_key = next(item.key for item in movements if item.account == "b")
    vault.ledger.append(transfer_linked(
        a_key, b_key, "verified", {}, "2026-02-02"))
    vault.synchronize_read_store()
    secret = b"ledger-page-test-secret-key-32-bytes!"
    with vault.read_store.open_reader() as revision:
        original = revision.connection.execute(
            "SELECT account_json FROM account_ledger_component_state "
            "WHERE account_id='b'").fetchone()[0]
    base = json.loads(original)
    bound = sql_page.MAX_COMPONENT_JSON_BYTES
    shell = json.dumps(base, ensure_ascii=False)
    room = bound - len(shell.encode("utf-8"))
    width = len(glyph.encode("utf-8"))
    padding = glyph * (room // width) + "X" * (room % width)
    for extra in ("", "X"):
        encoded = json.dumps({**base, "name": base["name"] + padding + extra},
                             ensure_ascii=False)
        assert len(encoded.encode("utf-8")) == bound + len(extra)
        vault.read_store.publish(lambda connection: connection.execute(
            "UPDATE account_ledger_component_state SET account_json=? "
            "WHERE account_id='b'", (encoded,)), copy_current=True)
        with vault.read_store.open_reader() as revision:
            old_select = revision.connection.execute(
                "SELECT account_json FROM account_ledger_component_state "
                "WHERE account_id='b'").fetchone()[0]
            assert json.loads(old_select) == json.loads(encoded)
            traced = []
            revision.connection.set_trace_callback(traced.append)
            if extra:
                with pytest.raises(ReadStoreError, match="byte bound"):
                    revision.account_ledger_page(
                        "a", locale="en-US", cursor_secret=secret, limit=100)
            else:
                with pytest.raises(ReadStoreError, match="scalar byte bound"):
                    revision.account_ledger_page(
                        "a", locale="en-US", cursor_secret=secret, limit=100)
            revision.connection.set_trace_callback(None)
            selected = [sql for sql in traced if "FROM account_ledger_component_state" in sql
                        and "WHERE account_id IN" in sql
                        and "length(CAST(account_json AS BLOB))" in sql]
            assert len(selected) == 1
            plan = " ".join(str(row[-1]) for row in revision.connection.execute(
                "EXPLAIN QUERY PLAN " + selected[0]).fetchall())
            assert "TEMP B-TREE" not in plan.upper()


def test_nested_component_json_refuses_whole_page_before_formatting(tmp_path):
    vault = _overlap_vault(tmp_path)
    nested = "leaf"
    for _ in range(32):
        nested = [nested]
    vault.read_store.publish(lambda connection: connection.execute(
        "UPDATE account_ledger_component_state SET coverage_json=? "
        "WHERE account_id='a'", (json.dumps({"runs": [], "nested": nested}),)),
        copy_current=True)
    with vault.read_store.open_reader() as revision:
        with pytest.raises(ReadStoreError, match="nested work bound"):
            revision.account_ledger_page(
                "a", locale="en-US", cursor_secret=b"x" * 32, limit=1)
    provider = OpenedVaultSurfaceProvider(vault, cursor_secret=b"x" * 32)
    with pytest.raises(Exception, match="could not answer account ledger"):
        provider.read_surface("account_ledger", {"account_id": "a", "limit": 1})


def test_page_member_cap_plus_one_refuses_without_truncated_groups(tmp_path, monkeypatch):
    from viva.read_store import account_ledger_page as sql_page

    vault = _overlap_vault(tmp_path)
    with vault.read_store.open_reader() as revision:
        assert any(len(json.loads(encoded)) > 1 for (encoded,) in
                   revision.connection.execute(
                       "SELECT members_json FROM account_ledger_component_index "
                       "WHERE account_id='a'"))
        monkeypatch.setattr(sql_page, "MAX_PAGE_MEMBERS", 1)
        with pytest.raises(ReadStoreError, match="page members exceed"):
            revision.account_ledger_page(
                "a", locale="en-US", cursor_secret=b"x" * 32, limit=100)


@pytest.mark.parametrize("column,mutate", [
    ("coverage_json", lambda body: {**body, "runs": [
        {**body["runs"][0], "from": "2025-12-01"}]}),
    ("coverage_json", lambda body: {**body, "runs": [
        {**body["runs"][0], "to": "2026-01-30"}]}),
    ("coverage_json", lambda body: {**body, "runs": [
        {**body["runs"][0], "statement_ids": ["missing-source"]}]}),
    ("coverage_json", lambda body: {**body, "runs": [
        {**body["runs"][0], "statement_ids":
         body["runs"][0]["statement_ids"] * 2}]}),
    ("coverage_json", lambda body: {**body, "gaps": [{"from": "2026-01-02"}]}),
    ("overlap_json", lambda body: {**body, "groups": [
        {**body["groups"][0], "document_ids": ["missing-source"]}]}),
    ("overlap_json", lambda body: {**body, "deduplication": {
        **body["deduplication"], "collapsed": [{"member_movement_ids": []}]}}),
    ("overlap_json", lambda body: {**body, "deduplication": {
        **body["deduplication"], "state": "none"}}),
])
def test_ledger_optional_evidence_shape_refuses_whole_page_and_held_reader_stays_exact(
        tmp_path, column, mutate):
    vault = _overlap_vault(tmp_path)
    secret = b"x" * 32
    held = vault.read_store.open_reader()
    expected = sql_account_ledger_page(held.account_ledger_page(
        "a", locale="en-US", cursor_secret=secret, limit=100))
    original = held.connection.execute(
        f"SELECT {column} FROM account_ledger_component_state WHERE account_id='a'"
    ).fetchone()[0]
    changed = json.dumps(mutate(json.loads(original)), ensure_ascii=False)
    assert json.loads(changed) != json.loads(original)
    vault.read_store.publish(lambda connection: connection.execute(
        f"UPDATE account_ledger_component_state SET {column}=? WHERE account_id='a'",
        (changed,)), copy_current=True)
    with vault.read_store.open_reader() as current:
        with pytest.raises(ReadStoreError, match="statement evidence is invalid"):
            current.account_ledger_page(
                "a", locale="en-US", cursor_secret=secret, limit=100)
    assert sql_account_ledger_page(held.account_ledger_page(
        "a", locale="en-US", cursor_secret=secret, limit=100)) == expected
    held.close()


@pytest.mark.parametrize("column,mutate,message", [
    ("account_json", lambda body: {**body, "names": "not-a-list"},
     "account identity is invalid"),
    ("account_json", lambda body: {**body, "extra": "unmapped"},
     "account identity is invalid"),
    ("balance_json", lambda body: {**body, "amount": "NaN"},
     "balance is invalid"),
    ("balance_json", lambda body: {**body, "reconciliation": "unknown"},
     "balance is invalid"),
])
def test_ledger_optional_identity_and_balance_shapes_refuse_without_partial_page(
        tmp_path, column, mutate, message):
    vault = _overlap_vault(tmp_path)
    with vault.read_store.open_reader() as revision:
        original = revision.connection.execute(
            f"SELECT {column} FROM account_ledger_component_state WHERE account_id='a'"
        ).fetchone()[0]
    changed = json.dumps(mutate(json.loads(original)), ensure_ascii=False)
    assert json.loads(changed) != json.loads(original)
    vault.read_store.publish(lambda connection: connection.execute(
        f"UPDATE account_ledger_component_state SET {column}=? WHERE account_id='a'",
        (changed,)), copy_current=True)
    with vault.read_store.open_reader() as revision:
        with pytest.raises(ReadStoreError, match=message):
            revision.account_ledger_page(
                "a", locale="en-US", cursor_secret=b"x" * 32, limit=100)


@pytest.mark.parametrize("glyph", ["X", "雪"])
@pytest.mark.parametrize("field", ["filename", "description", "account_name"])
def test_ledger_formatter_scalar_exact_utf8_boundary_and_whole_page_refusal(
        tmp_path, glyph, field):
    from viva.read_store import account_ledger_page as sql_page

    vault = _overlap_vault(tmp_path)
    secret = b"ledger-page-test-secret-key-32-bytes!"
    table = ("documents" if field == "filename" else
             "movements" if field == "description" else
             "account_ledger_component_state")
    column = "account_json" if field == "account_name" else field
    predicate = ("doc_id='jan'" if field == "filename" else
             "account_id='a'" if field == "account_name" else
             "account_id='a' AND description='SAME MERCHANT'")
    with vault.read_store.open_reader() as revision:
        if field == "description":
            movement_key = revision.connection.execute(
                "SELECT movement_key FROM movements WHERE " + predicate + " LIMIT 1"
            ).fetchone()[0]
            predicate = f"movement_key='{movement_key}'"
        original = revision.connection.execute(
            f"SELECT {column} FROM {table} WHERE {predicate} LIMIT 1").fetchone()[0]
    if field == "account_name":
        base = json.loads(original)
        seed = base["name"]
    else:
        seed = original
    room = sql_page.MAX_FORMATTER_SCALAR_BYTES - len(seed.encode("utf-8"))
    width = len(glyph.encode("utf-8"))
    padding = glyph * (room // width) + "X" * (room % width)
    for extra in ("", "X"):
        value = seed + padding + extra
        assert len(value.encode("utf-8")) == sql_page.MAX_FORMATTER_SCALAR_BYTES + len(extra)
        encoded = (json.dumps({**base, "name": value}, ensure_ascii=False)
                   if field == "account_name" else value)
        vault.read_store.publish(lambda connection: connection.execute(
            f"UPDATE {table} SET {column}=? WHERE {predicate}", (encoded,)),
            copy_current=True)
        with vault.read_store.open_reader() as revision:
            assert revision.connection.execute(
                f"SELECT {column} FROM {table} WHERE {predicate} LIMIT 1"
            ).fetchone()[0] == encoded
            traced = []
            revision.connection.set_trace_callback(traced.append)
            if extra:
                with pytest.raises(ReadStoreError, match="scalar byte bound"):
                    revision.account_ledger_page(
                        "a", locale="en-US", cursor_secret=secret, limit=100)
            else:
                assert revision.account_ledger_page(
                    "a", locale="en-US", cursor_secret=secret, limit=100)
            revision.connection.set_trace_callback(None)
            if field != "account_name":
                bounded = [sql for sql in traced if f"FROM {table}" in sql
                           and f"{field} AS BLOB))" in sql]
                assert bounded
                for sql in bounded:
                    plan = " ".join(str(row[-1]) for row in revision.connection.execute(
                        "EXPLAIN QUERY PLAN " + sql).fetchall())
                    assert "TEMP B-TREE" not in plan.upper()
