"""Canonical parity for SQL-native held and account-identity reads."""
import json
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path

import pytest

from viva.ingest.brokerage import BrokerageFacts, PositionFact
from viva.ingest.review import held_items as canonical_held_items
from viva.ingest.statement import StatementFacts, TxnFact
from viva.ledger import (EventStore, LedgerProjection, Provenance, account_opened,
                         closing_balance_observed, opening_balance_observed,
                         simple_transaction)
from viva.ledger.events import (account_alias_confirmed, account_identity_observed,
                                brokerage_activity_held,
                                brokerage_activity_resolved, question_declined,
                                position_observed, statement_held)
from viva.questions import open_questions
from viva.read_store import ReadStore
from viva.read_store import held as held_module
from viva.read_store import store as store_module


PASSWORD = "correct horse battery staple"


def _normal(value):
    if hasattr(value, "__dataclass_fields__"): value = asdict(value)
    if isinstance(value, dict): return {key: _normal(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)): return [_normal(item) for item in value]
    return str(value) if isinstance(value, Decimal) else value


def _store(path: Path, events):
    path.mkdir(parents=True, exist_ok=True)
    source = EventStore.open(path / "events.jsonl", PASSWORD)
    source.append_atomically(lambda _existing: tuple(events))
    return source


def _facts(doc_id="held-α", *, opening="100", closing="125", account_ref="Everyday"):
    return StatementFacts(doc_id, "checking_statement", 1, account_ref, "USD",
        Decimal(opening), "2026-02-01", Decimal(closing), "2026-02-28",
        [TxnFact("2026-02-15", "Deposit ☕", Decimal("25"))],
        account_number="••••1234", institution="Northbank")


def _held_dict(item):
    return item.to_dict()


@pytest.mark.parametrize("glyph", ["X", "雪"])
@pytest.mark.parametrize("column", ["facts_json", "finding_json"])
def test_held_json_refuses_exact_utf8_limit_plus_one_before_fetch(
        tmp_path, glyph, column):
    facts = _facts("held-byte-bound")
    canonical = _store(tmp_path, [statement_held(
        facts.doc_id, facts.to_dict(), {"message": "Held"}, "gap", "2026-02-28")])
    with ReadStore.create(tmp_path / "read-model", PASSWORD) as reads:
        reads.synchronize(canonical)
        with reads.open_reader() as revision:
            original = revision.connection.execute(
                f"SELECT {column} FROM document_holds LIMIT 1").fetchone()[0]
        base = json.loads(original)
        bound = held_module.MAX_ENCODED_HOLD_BYTES
        shell = json.dumps({**base, "padding": ""}, ensure_ascii=False)
        room = bound - len(shell.encode("utf-8"))
        width = len(glyph.encode("utf-8"))
        padding = glyph * (room // width) + "X" * (room % width)
        for extra in ("", "X"):
            encoded = json.dumps({**base, "padding": padding + extra},
                                 ensure_ascii=False)
            assert len(encoded.encode("utf-8")) == bound + len(extra)
            reads.publish(lambda connection: connection.execute(
                f"UPDATE document_holds SET {column}=?", (encoded,)),
                copy_current=True)
            with reads.open_reader() as revision:
                old_select = revision.connection.execute(
                    f"SELECT {column} FROM document_holds LIMIT 1").fetchone()[0]
                assert json.loads(old_select) == json.loads(encoded)
                traced = []
                revision.connection.set_trace_callback(traced.append)
                if extra:
                    with pytest.raises(store_module.ReadStoreError, match="byte bound"):
                        held_module._open_hold_rows(revision.connection, "2026-03-01")
                else:
                    held_module._open_hold_rows(revision.connection, "2026-03-01")
                revision.connection.set_trace_callback(None)
                bounded = [sql for sql in traced if "FROM document_holds" in sql
                           and "CASE WHEN length(CAST(h.facts_json AS BLOB))" in sql]
                assert len(bounded) == 1
                plan = " ".join(str(row[-1]) for row in revision.connection.execute(
                    "EXPLAIN QUERY PLAN " + bounded[0]).fetchall())
                assert "TEMP B-TREE" not in plan.upper()


def test_held_items_and_questions_match_canonical_with_identity_choices_and_decline(tmp_path):
    first, second = "acct:north:one", "acct:north:two"
    facts = _facts()
    events = [
        account_opened(first, "depository", "Everyday 000000001234", "USD",
                       "2026-01-01", institution="Northbank",
                       account_number="000000001234"),
        opening_balance_observed(first, "1000", "2026-01-01"),
        account_opened(second, "depository", "Everyday 999999991234", "USD",
                       "2026-01-01", institution="Northbank",
                       account_number="999999991234"),
        opening_balance_observed(second, "2500", "2026-01-01"),
        statement_held(facts.doc_id, facts.to_dict(), {
            "kind": "identity", "candidates": [first, second],
            "message": "Two accounts share these digits."}, "identity",
            "2026-02-28", Provenance(doc_id=facts.doc_id)),
    ]
    canonical = LedgerProjection(events, as_of="2026-03-01")
    expected_question = next(q for q in open_questions(
        canonical, as_of="2026-03-01", locale="en-US", limit=None)["questions"]
        if q["kind"] == "identity")
    events.append(question_declined(expected_question["id"], "identity", "2026-03-01",
                                    amount=expected_question["amount"], count=1))
    source = _store(tmp_path, events)
    with ReadStore.create(tmp_path / "read-model", PASSWORD) as reads:
        reads.synchronize(source)
        with reads.open_reader() as revision:
            actual_items = revision.held_items(as_of="2026-03-01")
            actual_questions = revision.open_questions(
                as_of="2026-03-01", locale="en-US", limit=None)
    expected_items = [_held_dict(item) for item in canonical_held_items(
        LedgerProjection(events, as_of="2026-03-01"))]
    assert [{k: v for k, v in row.items() if k != "source_sequence"}
            for row in actual_items] == expected_items
    expected = open_questions(LedgerProjection(events, as_of="2026-03-01"),
                              as_of="2026-03-01", locale="en-US", limit=None)
    identity_expected = [q for q in expected["questions"] if q["kind"] == "identity"]
    identity_actual = [q for q in actual_questions["questions"] if q["kind"] == "identity"]
    assert identity_actual == identity_expected == []
    assert actual_questions["pending"]["count"] >= 1


def test_holds_close_and_reopen_by_canonical_source_order_at_arbitrary_as_of(tmp_path):
    facts = _facts()
    brokerage = BrokerageFacts("broker", "brokerage_statement", 1, "Invest", "USD",
                               "2026-02-28", Decimal("10"), Decimal("20"),
                               [PositionFact("ABC", Decimal("1"), Decimal("10"))])
    events = [statement_held(facts.doc_id, facts.to_dict(), None, "gap", "2026-02-28"),
              brokerage_activity_held("broker", brokerage.to_dict(), {"message": "cash"}, "2026-02-28"),
              brokerage_activity_resolved("broker", "2026-03-01"),
              brokerage_activity_held("broker", brokerage.to_dict(), {"message": "again"}, "2026-03-02"),
              simple_transaction("acct", "25", "posted", "2026-03-03",
                                 provenance=Provenance(doc_id=facts.doc_id))]
    source = _store(tmp_path, events)
    with ReadStore.create(tmp_path / "read-model", PASSWORD) as reads:
        reads.synchronize(source)
        with reads.open_reader() as revision:
            before = revision.open_questions(as_of="2026-03-01", limit=None)
            after = revision.open_questions(as_of="2026-03-03", limit=None)
    for boundary, actual in (("2026-03-01", before), ("2026-03-03", after)):
        expected = open_questions(LedgerProjection(events, as_of=boundary),
                                  as_of=boundary, limit=None)
        expected_rows = [q for q in expected["questions"] if q["kind"] in ("identity", "reconciliation")]
        actual_rows = [q for q in actual["questions"] if q["kind"] in ("identity", "reconciliation")]
        assert actual_rows == expected_rows


def test_provenanced_closing_balance_closes_a_hold_at_exact_as_of_like_canonical(tmp_path):
    facts = _facts("closing-only")
    source_provenance = Provenance(doc_id=facts.doc_id)
    events = [
        statement_held(facts.doc_id, facts.to_dict(), None, "gap", "2026-02-28"),
        closing_balance_observed("acct", "125", "2026-03-01", source_provenance),
    ]
    source = _store(tmp_path, events)
    with ReadStore.create(tmp_path / "read-model", PASSWORD) as reads:
        reads.synchronize(source)
        with reads.open_reader() as revision:
            assert revision.connection.execute(
                "SELECT event_type,doc_id FROM posted_document_events").fetchall() == [
                    ("ClosingBalanceObserved", facts.doc_id)]
            for boundary in ("2026-02-28", "2026-03-01", "9999-12-31"):
                actual = revision.open_questions(as_of=boundary, limit=None)
                expected = open_questions(LedgerProjection(events, as_of=boundary),
                                          as_of=boundary, limit=None)
                assert [q for q in actual["questions"] if q["kind"] == "reconciliation"] == [
                    q for q in expected["questions"] if q["kind"] == "reconciliation"]


def test_identity_resolution_preserves_legacy_and_scoped_alias_semantics(tmp_path):
    account = "acct:north:1234"
    base = [account_opened(account, "depository", "Checking ••••1234", "USD",
                           "2026-01-01", institution="Northbank",
                           account_number="••••1234", account_names=["Holder One"])]
    legacy = _facts("legacy", account_ref="Savings")
    scoped = _facts("scoped", account_ref="Brokerage Cash")
    events = base + [
        account_alias_confirmed(account, account, "old", "2026-01-02"),
        statement_held(legacy.doc_id, legacy.to_dict(), {"candidate": account},
                       "identity", "2026-02-01"),
        account_alias_confirmed(account, account, "ruled", "2026-02-02",
                                match_names=["Different"], match_label="Savings",
                                kind="depository"),
        statement_held(scoped.doc_id, scoped.to_dict(), {"candidate": account},
                       "identity", "2026-02-03")]
    source = _store(tmp_path, events)
    with ReadStore.create(tmp_path / "read-model", PASSWORD) as reads:
        reads.synchronize(source)
        with reads.open_reader() as revision:
            actual = revision.open_questions(as_of="2026-03-01", limit=None)
    expected = open_questions(LedgerProjection(events, as_of="2026-03-01"),
                              as_of="2026-03-01", limit=None)
    assert [q for q in actual["questions"] if q["kind"] == "identity"] == [
        q for q in expected["questions"] if q["kind"] == "identity"]


def test_held_read_refuses_overflow_and_uses_indexed_no_offset_queries(tmp_path, monkeypatch):
    events = [statement_held(f"doc-{i}", _facts(f"doc-{i}").to_dict(), None,
                             "gap", "2026-02-28") for i in range(3)]
    source = _store(tmp_path, events)
    with ReadStore.create(tmp_path / "read-model", PASSWORD) as reads:
        reads.synchronize(source)
        with reads.open_reader() as revision:
            monkeypatch.setattr(held_module, "MAX_HELD_ROWS", 2)
            with pytest.raises(store_module.ReadStoreError, match="bound"):
                revision.held_items(as_of="2026-03-01")
            plan = " ".join(row[3] for row in revision.connection.execute(
                "EXPLAIN QUERY PLAN SELECT source_sequence FROM document_holds "
                "WHERE occurred_at<=? ORDER BY source_sequence LIMIT ?",
                ("2026-03-01", 10)).fetchall())
            assert "SCAN document_holds" in plan
    assert "OFFSET" not in Path(held_module.__file__).read_text()


def test_held_parity_survives_suffix_batches_restart_and_held_revision(tmp_path):
    events = [statement_held("a", _facts("a").to_dict(), None, "gap", "2026-02-01"),
              statement_held("b", _facts("b", closing="150").to_dict(), None,
                             "conflict", "2026-02-02")]
    source = EventStore.open(tmp_path / "events.jsonl", PASSWORD)
    reads = ReadStore.create(tmp_path / "read-model", PASSWORD)
    source.append_atomically(lambda _existing: (events[0],)); reads.synchronize(source)
    held = reads.open_reader(); snapshot = held.held_items(as_of="2026-03-01")
    source.append_atomically(lambda _existing: (events[1],)); reads.synchronize(source)
    with reads.open_reader() as current:
        assert len(current.held_items(as_of="2026-03-01")) == 2
    assert held.held_items(as_of="2026-03-01") == snapshot
    held.close(); reads.close()
    with ReadStore.open(tmp_path / "read-model", PASSWORD) as reopened:
        with reopened.open_reader() as revision:
            assert len(revision.held_items(as_of="2026-03-01")) == 2


@pytest.mark.parametrize("column,payload,message", [
    ("facts_json", {"padding": "é" * 500_001}, "held facts payload"),
    ("finding_json", {"padding": "é" * 500_001}, "held finding payload"),
])
def test_held_encoded_payloads_refuse_at_production_byte_limit_before_value_queries(
        tmp_path, column, payload, message):
    facts = _facts()
    source = _store(tmp_path, [statement_held(
        facts.doc_id, facts.to_dict(), {"candidate": "account"},
        "identity", "2026-02-28")])
    with ReadStore.create(tmp_path / "read-model", PASSWORD) as reads:
        reads.synchronize(source)
        reads.publish(lambda db: db.execute(
            f"UPDATE document_holds SET {column}=?", (json.dumps(payload),)),
            copy_current=True)
        with reads.open_reader() as revision:
            traced = []
            revision.connection.set_trace_callback(traced.append)
            with pytest.raises(store_module.ReadStoreError, match=message):
                revision.open_questions(as_of="2026-03-01", limit=None)
            revision.connection.set_trace_callback(None)
    assert not any("FROM positions" in query or "FROM postings" in query
                   for query in traced)


@pytest.mark.parametrize("candidate_count,message", [
    (held_module.MAX_IDENTITY_CANDIDATES_PER_FINDING + 1, "nested candidate"),
])
def test_identity_nested_candidate_production_limit_refuses_before_value_queries(
        tmp_path, candidate_count, message):
    facts = _facts()
    source = _store(tmp_path, [statement_held(facts.doc_id, facts.to_dict(), {
        "candidates": [f"account-{i}" for i in range(candidate_count)]},
        "identity", "2026-02-28")])
    with ReadStore.create(tmp_path / "read-model", PASSWORD) as reads:
        reads.synchronize(source)
        with reads.open_reader() as revision:
            traced = []
            revision.connection.set_trace_callback(traced.append)
            with pytest.raises(store_module.ReadStoreError, match=message):
                revision.open_questions(as_of="2026-03-01", limit=None)
            revision.connection.set_trace_callback(None)
    assert not any("FROM positions" in query or "FROM postings" in query
                   for query in traced)


def test_identity_candidate_key_and_total_production_limits_refuse_atomically(tmp_path):
    oversized = _facts("oversized-key")
    events = [statement_held(oversized.doc_id, oversized.to_dict(), {
        "candidates": ["é" * 257]}, "identity", "2026-02-01")]
    source = _store(tmp_path / "key", events)
    with ReadStore.create(tmp_path / "key-read", PASSWORD) as reads:
        reads.synchronize(source)
        with reads.open_reader() as revision:
            with pytest.raises(store_module.ReadStoreError, match="UTF-8 key"):
                revision.open_questions(as_of="2026-03-01", limit=None)

    many = []
    for doc_index in range(6):
        facts = _facts(f"total-{doc_index}")
        candidates = [f"account-{doc_index}-{index}" for index in range(200)]
        many.append(statement_held(facts.doc_id, facts.to_dict(),
            {"candidates": candidates}, "identity", "2026-02-01"))
    source = _store(tmp_path / "total", many)
    with ReadStore.create(tmp_path / "total-read", PASSWORD) as reads:
        reads.synchronize(source)
        with reads.open_reader() as revision:
            with pytest.raises(store_module.ReadStoreError, match="total candidate"):
                revision.open_questions(as_of="2026-03-01", limit=None)


@pytest.mark.parametrize("glyph", ["X", "雪"])
def test_account_alias_payload_refuses_at_production_byte_limit(tmp_path, glyph):
    account = "acct-one"
    events = [account_opened(account, "depository", "Everyday", "USD", "2026-01-01"),
              account_alias_confirmed(account, account, "same", "2026-01-02",
                                      match_names=["Holder"], match_label="Everyday",
                                      kind="depository")]
    source = _store(tmp_path, events)
    with ReadStore.create(tmp_path / "read-model", PASSWORD) as reads:
        reads.synchronize(source)
        bound = held_module.MAX_ENCODED_IDENTITY_BYTES
        shell = json.dumps([""], ensure_ascii=False)
        room = bound - len(shell.encode("utf-8"))
        width = len(glyph.encode("utf-8"))
        padding = glyph * (room // width) + "X" * (room % width)
        for extra in ("", "X"):
            encoded = json.dumps([padding + extra], ensure_ascii=False)
            assert len(encoded.encode("utf-8")) == bound + len(extra)
            reads.publish(lambda db: db.execute(
                "UPDATE account_alias_history SET match_names_json=?",
                (encoded,)), copy_current=True)
            with reads.open_reader() as revision:
                assert json.loads(revision.connection.execute(
                    "SELECT match_names_json FROM account_alias_history"
                ).fetchone()[0]) == json.loads(encoded)
                traced = []
                revision.connection.set_trace_callback(traced.append)
                if extra:
                    with pytest.raises(store_module.ReadStoreError,
                                       match="account alias identity payload"):
                        revision.open_questions(as_of="2026-03-01", limit=None)
                else:
                    revision.open_questions(as_of="2026-03-01", limit=None)
                revision.connection.set_trace_callback(None)
                selected = [sql for sql in traced
                            if "FROM account_alias_history" in sql
                            and "length(CAST(match_names_json AS BLOB))" in sql]
                assert len(selected) >= 1
                plan = " ".join(str(row[-1]) for row in revision.connection.execute(
                    "EXPLAIN QUERY PLAN " + selected[0]).fetchall())
                assert "TEMP B-TREE" not in plan.upper()


@pytest.mark.parametrize("glyph", ["X", "雪"])
@pytest.mark.parametrize("table,column", [
    ("accounts", "name"), ("account_names", "name"),
    ("account_alias_history", "match_label"),
])
def test_shared_identity_scalar_prefetch_exact_utf8_boundary_and_refusal(
        tmp_path, glyph, table, column):
    account = "acct-one"
    source = _store(tmp_path, [
        account_opened(account, "depository", "Everyday", "USD", "2026-01-01",
                       account_names=["Holder"]),
        account_alias_confirmed(account, account, "same", "2026-01-02",
                                match_names=["Holder"], match_label="Everyday",
                                kind="depository"),
    ])
    with ReadStore.create(tmp_path / "read-model", PASSWORD) as reads:
        reads.synchronize(source)
        with reads.open_reader() as revision:
            original = revision.connection.execute(
                f"SELECT {column} FROM {table} LIMIT 1").fetchone()[0]
        bound = held_module.MAX_IDENTITY_SCALAR_BYTES
        room = bound - len(original.encode("utf-8"))
        width = len(glyph.encode("utf-8"))
        padding = glyph * (room // width) + "X" * (room % width)
        for extra in ("", "X"):
            value = original + padding + extra
            assert len(value.encode("utf-8")) == bound + len(extra)
            reads.publish(lambda db: db.execute(
                f"UPDATE {table} SET {column}=?", (value,)), copy_current=True)
            with reads.open_reader() as revision:
                assert revision.connection.execute(
                    f"SELECT {column} FROM {table} LIMIT 1").fetchone()[0] == value
                traced = []
                revision.connection.set_trace_callback(traced.append)
                if extra:
                    with pytest.raises(store_module.ReadStoreError,
                                       match="identity scalar exceeds its byte bound"):
                        held_module._identity_core(revision.connection,
                                                   "2026-03-01")
                else:
                    held_module._identity_core(revision.connection,
                                               "2026-03-01")
                revision.connection.set_trace_callback(None)
                selected = [sql for sql in traced if f"FROM {table}" in sql
                            or (table == "accounts" and "FROM accounts a" in sql)
                            or (table == "account_names" and
                                "FROM account_names n" in sql)]
                bounded = [sql for sql in selected
                           if f"length(CAST({column} AS BLOB))" in sql or
                           f"length(CAST(a.{column} AS BLOB))" in sql or
                           f"length(CAST(n.{column} AS BLOB))" in sql]
                assert bounded
                plan = " ".join(str(row[-1]) for row in revision.connection.execute(
                    "EXPLAIN QUERY PLAN " + bounded[0]).fetchall())
                assert "TEMP B-TREE" not in plan.upper()


def test_held_result_production_limit_refuses_without_truncation(tmp_path):
    events = [statement_held(f"doc-{index}", _facts(f"doc-{index}").to_dict(),
                             None, "gap", "2026-02-28")
              for index in range(held_module.MAX_HELD_ROWS + 1)]
    source = _store(tmp_path, events)
    with ReadStore.create(tmp_path / "read-model", PASSWORD) as reads:
        reads.synchronize(source)
        with reads.open_reader() as revision:
            with pytest.raises(store_module.ReadStoreError, match="row read bound"):
                revision.open_questions(as_of="2026-03-01", limit=None)


def test_duplicate_identity_labels_batch_account_values_with_fixed_query_count(tmp_path):
    accounts = [f"acct-{index:03d}" for index in range(40)]
    facts = _facts()
    events = []
    for index, account in enumerate(accounts):
        events.extend((
            account_opened(account, "depository", "Everyday ••••1234", "USD",
                           "2026-01-01", institution="Northbank",
                           account_number=f"{index:08d}1234"),
            opening_balance_observed(account, str(index), "2026-01-01"),
        ))
    # A backfilled opening wins by date (and then earliest source), while a
    # tied closing wins by latest source.  The batched reduction must preserve
    # those canonical rules without depending on row arrival order.
    events.extend((
        opening_balance_observed(accounts[0], "900", "2025-12-31"),
        opening_balance_observed(accounts[0], "901", "2025-12-31"),
        closing_balance_observed(accounts[0], "50", "2026-02-01"),
        closing_balance_observed(accounts[0], "60", "2026-02-01"),
    ))
    events.append(statement_held(facts.doc_id, facts.to_dict(), {
        "kind": "identity", "candidates": accounts}, "identity", "2026-02-28"))
    source = _store(tmp_path, events)
    with ReadStore.create(tmp_path / "read-model", PASSWORD) as reads:
        reads.synchronize(source)
        with reads.open_reader() as revision:
            traced = []
            revision.connection.set_trace_callback(traced.append)
            actual = revision.open_questions(
                as_of="2026-03-01", locale="en-US", limit=None)
            revision.connection.set_trace_callback(None)
            value_queries = [query for query in traced if query.startswith("SELECT ") and
                             ("FROM balance_observations" in query or
                              "FROM postings" in query or "FROM positions" in query)]
            plans = [" ".join(row[3] for row in revision.connection.execute(
                     "EXPLAIN QUERY PLAN " + query)) for query in value_queries]
    expected = open_questions(LedgerProjection(events, as_of="2026-03-01"),
                              as_of="2026-03-01", locale="en-US", limit=None)
    assert [q for q in actual["questions"] if q["kind"] == "identity"] == [
        q for q in expected["questions"] if q["kind"] == "identity"]
    # Four fixed identity-value statements plus the two bounded expectation
    # balance inputs now composed by the complete queue.
    assert len(value_queries) == 6
    assert "closing_observations_by_account_date" in plans[0]
    assert "opening_observations_by_account_date" in plans[1]
    assert "postings_by_account" in plans[2]
    assert "positions_by_account_date" in plans[3]
    assert all("USE TEMP B-TREE" not in plan.upper() for plan in plans)


def _identity_overflow_events(case):
    account = "bounded-account"
    base = [account_opened(account, "depository", "Everyday", "USD",
                           "2026-01-01")]
    if case == "account":
        base.extend(account_identity_observed(account, "2026-01-02")
                    for _ in range(held_module.MAX_ACCOUNT_HISTORY_ROWS))
    elif case == "holder-name":
        base = [account_opened(account, "depository", "Everyday", "USD",
            "2026-01-01", account_names=[
                f"Holder {index}" for index in range(held_module.MAX_ACCOUNT_NAME_ROWS + 1)])]
    elif case == "alias":
        base.extend(account_alias_confirmed(
            f"alias-{index}", account, f"doc-alias-{index}", "2026-01-02")
            for index in range(held_module.MAX_ALIAS_HISTORY_ROWS + 1))
    elif case == "opening":
        base.extend(opening_balance_observed(account, str(index), "2026-01-02")
                    for index in range(held_module.MAX_OBSERVATION_HISTORY_ROWS + 1))
    elif case == "closing":
        base.extend(closing_balance_observed(account, str(index), "2026-01-02")
                    for index in range(held_module.MAX_OBSERVATION_HISTORY_ROWS + 1))
    elif case == "posting":
        base.extend(simple_transaction(account, "-1", f"row {index}", "2026-01-02")
                    for index in range(held_module.MAX_VALUE_ROWS_PER_ACCOUNT + 1))
    elif case == "position":
        base.extend(position_observed(account, f"FUND-{index}", "1", "1", "USD",
                                      "2026-01-02")
                    for index in range(held_module.MAX_VALUE_ROWS_PER_ACCOUNT + 1))
    facts = _facts("bounded-hold")
    base.append(statement_held(facts.doc_id, facts.to_dict(),
        {"kind": "identity", "candidates": [account]}, "identity", "2026-02-28"))
    return base


@pytest.mark.parametrize("case,message", [
    ("account", "account identity history"),
    ("holder-name", "account holder-name history"),
    ("alias", "account alias history"),
    ("opening", "identity opening-observation history"),
    ("closing", "identity closing-observation history"),
    ("posting", "identity posting input"),
    ("position", "identity position input"),
])
def test_each_identity_history_refuses_at_its_production_threshold(
        tmp_path, case, message):
    source = _store(tmp_path / case, _identity_overflow_events(case))
    with ReadStore.create(tmp_path / f"{case}-read", PASSWORD) as reads:
        if case in {"account", "holder-name", "alias", "posting"}:
            before_generation = reads.current_generation
            with pytest.raises(store_module.ReadStoreDegraded) as degraded:
                reads.synchronize(source)
            expected = ("10000-posting goal-view bound" if case == "posting"
                        else message)
            assert expected in str(degraded.value.__cause__)
            assert reads.current_generation == before_generation
            return
        reads.synchronize(source)
        with reads.open_reader() as revision:
            before = revision.connection.execute(
                "SELECT COUNT(*) FROM applied_events").fetchone()
            with pytest.raises(store_module.ReadStoreError, match=message):
                held_module.question_candidates(
                    revision.connection, as_of="2026-03-01")
            assert revision.connection.execute(
                "SELECT COUNT(*) FROM applied_events").fetchone() == before
