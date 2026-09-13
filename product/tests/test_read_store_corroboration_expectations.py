"""Canonical parity for SQL-native corroboration and expectation questions."""
from pathlib import Path
import json

import pytest

from viva.interview import attributes as canonical_attributes
from viva.ledger import (EventStore, LedgerProjection, Posting, Provenance,
                         account_identity_observed, account_opened,
                         closing_balance_observed,
                         document_captured, opening_balance_observed,
                         transaction_recorded)
from viva.ledger.events import (SCOPE_ATTRIBUTE, SCOPE_MOVEMENT,
                                position_observed, question_declined,
                                ruling_recorded)
from viva.questions import open_questions
from viva.read_store import ReadStore
from viva.read_store import questions as sql_questions
from viva.read_store.rhythm import RhythmReadError
from viva.read_store.store import sqlcipher


PASSWORD = "correct horse battery staple"


def _store(path: Path, events):
    source = EventStore.open(path / "events.jsonl", PASSWORD)
    source.append_atomically(lambda _existing: tuple(events))
    return source


def _families(payload):
    return [row for row in payload["questions"]
            if row["kind"] in ("corroboration", "expectation")]


def _events():
    issuer = Provenance("cash-statement", 1, "account", "issuer")
    events = [
        account_opened("cash", "depository", "Daily ☕", "USD", "2025-01-01",
                       provenance=issuer),
        closing_balance_observed("cash", "1000", "2025-01-01", issuer),
        account_opened("broker", "investment", "Bróker", "USD", "2025-01-02",
                       jurisdiction="US"),
        transaction_recorded(
            [Posting("cash", "-50"), Posting("Assets:Retirement", "50")],
            "Retirement contribution", "2026-01-10", provenance=issuer),
        transaction_recorded(
            [Posting("cash", "20"), Posting("Income:Dividends", "-20")],
            "Dividend", "2026-01-11", provenance=issuer),
    ]
    movement = LedgerProjection(events).movements()[0]
    events.append(ruling_recorded(
        SCOPE_MOVEMENT, movement.key, "2026-01-12",
        legs=[{"major": "liability", "account": "Liabilities:Loan:Élan",
               "share": ""}], corroborates="closing disclosure"))
    return events


@pytest.mark.parametrize("glyph", ["X", "雪"])
def test_corroboration_ruling_legs_prefetch_exact_utf8_boundary_and_refusal(
        tmp_path, glyph):
    source = _store(tmp_path, _events())
    with ReadStore.create(tmp_path / "read-model", PASSWORD) as reads:
        reads.synchronize(source)
        with reads.open_reader() as revision:
            original = revision.connection.execute(
                "SELECT legs_json FROM ruling_history WHERE scope='movement' LIMIT 1"
            ).fetchone()[0]
        base = json.loads(original)
        bound = sql_questions.MAX_RULING_LEGS_BYTES
        shell = json.dumps([{**base[0], "padding": ""}], ensure_ascii=False)
        room = bound - len(shell.encode("utf-8"))
        width = len(glyph.encode("utf-8"))
        padding = glyph * (room // width) + "X" * (room % width)
        for extra in ("", "X"):
            encoded = json.dumps([{**base[0], "padding": padding + extra}],
                                 ensure_ascii=False)
            assert len(encoded.encode("utf-8")) == bound + len(extra)
            reads.publish(lambda db: db.execute(
                "UPDATE ruling_history SET legs_json=? WHERE scope='movement'",
                (encoded,)), copy_current=True)
            with reads.open_reader() as revision:
                assert json.loads(revision.connection.execute(
                    "SELECT legs_json FROM ruling_history WHERE scope='movement'"
                ).fetchone()[0]) == json.loads(encoded)
                traced = []
                revision.connection.set_trace_callback(traced.append)
                if extra:
                    with pytest.raises(RhythmReadError,
                                       match="ruling legs exceed their byte bound"):
                        revision.open_questions(as_of="2026-03-01", limit=None)
                else:
                    revision.open_questions(as_of="2026-03-01", limit=None)
                revision.connection.set_trace_callback(None)
                selected = [sql for sql in traced
                            if "FROM ruling_history ORDER BY source_sequence" in sql
                            and "length(CAST(legs_json AS BLOB))" in sql]
                assert len(selected) == 1
                plan = " ".join(str(row[-1]) for row in revision.connection.execute(
                    "EXPLAIN QUERY PLAN " + selected[0]).fetchall())
                assert "TEMP B-TREE" not in plan.upper()


@pytest.mark.parametrize("jurisdiction", ["US", "CA", ""])
def test_corroboration_and_expectations_match_canonical_by_jurisdiction(tmp_path, jurisdiction):
    events = _events()
    source = _store(tmp_path, events)
    expected = open_questions(LedgerProjection(events), as_of="2026-03-01",
                              jurisdiction=jurisdiction, locale="en-US", limit=None)
    with ReadStore.create(tmp_path / "read-model", PASSWORD) as reads:
        reads.synchronize(source)
        with reads.open_reader() as revision:
            actual = revision.open_questions(as_of="2026-03-01",
                jurisdiction=jurisdiction, locale="en-US", limit=None)
    assert _families(actual) == _families(expected)


def test_document_satisfaction_and_exact_decline_snapshot_match_canonical(tmp_path):
    events = _events()
    baseline = open_questions(LedgerProjection(events), as_of="2026-03-01",
                              jurisdiction="US", locale="en-US", limit=None)
    retirement = next(row for row in baseline["questions"]
                      if row["id"] == "expectation:retirement-statements")
    events += [
        question_declined(retirement["id"], retirement["kind"], "2026-03-02",
                          amount=retirement["amount"], count=retirement["count"]),
        document_captured("tax", "1099.pdf", 12, "form_1099_div", 1.0,
                          "2026-03-03"),
    ]
    source = _store(tmp_path, events)
    with ReadStore.create(tmp_path / "read-model", PASSWORD) as reads:
        reads.synchronize(source)
        with reads.open_reader() as revision:
            actual = revision.open_questions(as_of="2026-03-04",
                jurisdiction="US", locale="en-US", limit=None)
    expected = open_questions(LedgerProjection(events), as_of="2026-03-04",
                              jurisdiction="US", locale="en-US", limit=None)
    assert _families(actual) == _families(expected)
    assert actual["pending"] == expected["pending"]


def test_attribute_latest_by_value_time_and_document_account_attribution(tmp_path):
    provenance = Provenance("statement-α", 2, "identity", "issuer")
    events = [
        account_opened("acct:home:α", "asset", "Casa", "EUR", "2026-01-01",
                       provenance=provenance),
        ruling_recorded(SCOPE_ATTRIBUTE, "acct:home:α:use", "2026-03-01",
                        value="rental", said="rental", grade="corroborated"),
        ruling_recorded(SCOPE_ATTRIBUTE, "acct:home:α:use", "2026-02-01",
                        value="home", said="home", grade="verified"),
        ruling_recorded(SCOPE_ATTRIBUTE, "acct:home:α:use", "2026-03-01",
                        value="holiday", said="holiday", grade="verified"),
        # Canonical history is source ordered after the as-of filter: this
        # later-recorded backfill wins even though its value date is earlier.
        ruling_recorded(SCOPE_ATTRIBUTE, "acct:home:α:use", "2026-01-15",
                        value="backfill", said="backfill", grade="verified"),
    ]
    source = _store(tmp_path, events)
    with ReadStore.create(tmp_path / "read-model", PASSWORD) as reads:
        reads.synchronize(source)
        with reads.open_reader() as revision:
            for boundary in ("2026-01-31", "2026-02-01", "2026-03-01", "9999-12-31"):
                assert sql_questions.attribute_answers(
                    revision.connection, as_of=boundary) == canonical_attributes(
                        LedgerProjection(events), as_of=boundary)
            assert revision.connection.execute(
                "SELECT doc_id,account_id,role,provenance_doc_id,provenance_page,"
                "provenance_region,provenance_note FROM document_account_history"
            ).fetchall() == [("statement-α", "acct:home:α", "account",
                              "statement-α", 2, "identity", "issuer")]


def test_document_account_roles_are_event_typed_and_provenance_is_lossless(tmp_path):
    provenance = Provenance("doc-α", 4, "box:1", "attested")
    events = [
        account_opened("cash", "depository", "Cash", "USD", "2026-01-01",
                       provenance=provenance),
        account_identity_observed("cash", "2026-01-02", institution="Crédit α",
                                  account_number="••٤٢", account_names=["Café 現金"],
                                  provenance=provenance),
        opening_balance_observed("cash", "10", "2026-01-01", provenance),
        closing_balance_observed("cash", "12", "2026-01-31", provenance),
        transaction_recorded([Posting("cash", "1")], "credit", "2026-01-10",
                             provenance=provenance),
        position_observed("cash", "units", "1", "12", "USD", "2026-01-31",
                          cost_basis="10", provenance=provenance),
    ]
    source = _store(tmp_path, events)
    with ReadStore.create(tmp_path / "read-model", PASSWORD) as reads:
        reads.synchronize(source)
        with reads.open_reader() as revision:
            rows = revision.connection.execute(
                "SELECT event_type,role,provenance_doc_id,provenance_page,"
                "provenance_region,provenance_note FROM document_account_history "
                "ORDER BY source_sequence,account_index").fetchall()
            assert rows == [
                ("AccountOpened", "account", "doc-α", 4, "box:1", "attested"),
                ("AccountIdentityObserved", "account", "doc-α", 4, "box:1", "attested"),
                ("OpeningBalanceObserved", "opening", "doc-α", 4, "box:1", "attested"),
                ("ClosingBalanceObserved", "closing", "doc-α", 4, "box:1", "attested"),
                ("TransactionRecorded", "transaction", "doc-α", 4, "box:1", "attested"),
                ("PositionObserved", "position", "doc-α", 4, "box:1", "attested"),
            ]
            table_sql = revision.connection.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' "
                "AND name='document_account_history'").fetchone()[0]
    valid = {
        "AccountOpened": "account", "AccountIdentityObserved": "account",
        "OpeningBalanceObserved": "opening",
        "ClosingBalanceObserved": "closing",
        "TransactionRecorded": "transaction", "PositionObserved": "position",
    }
    for event_type, role in valid.items():
        for candidate in {"account", "opening", "closing", "transaction", "position"} - {role}:
            check = sqlcipher.connect(":memory:")
            check.execute("PRAGMA foreign_keys=ON")
            check.execute("CREATE TABLE applied_events(sequence INTEGER PRIMARY KEY, event_type TEXT, "
                          "UNIQUE(sequence,event_type))")
            check.execute("CREATE TABLE account_entities(account_id TEXT PRIMARY KEY)")
            check.execute(table_sql)
            check.execute("INSERT INTO applied_events VALUES(1,?)", (event_type,))
            check.execute("INSERT INTO account_entities VALUES('cash')")
            with pytest.raises(Exception, match="CHECK constraint"):
                check.execute("INSERT INTO document_account_history VALUES"
                              "(1,0,?,'2026-01-01','doc','cash',?,'doc',1,'r','n')",
                              (event_type, candidate))
            assert check.execute(
                "SELECT count(*) FROM document_account_history").fetchone() == (0,)
            check.close()
    check = sqlcipher.connect(":memory:")
    check.execute("PRAGMA foreign_keys=ON")
    check.execute("CREATE TABLE applied_events(sequence INTEGER PRIMARY KEY, event_type TEXT, "
                  "UNIQUE(sequence,event_type))")
    check.execute("CREATE TABLE account_entities(account_id TEXT PRIMARY KEY)")
    check.execute(table_sql)
    check.execute("INSERT INTO applied_events VALUES(1,'AccountOpened')")
    check.execute("INSERT INTO account_entities VALUES('cash')")
    with pytest.raises(Exception, match="FOREIGN KEY constraint"):
        check.execute("INSERT INTO document_account_history VALUES"
                      "(1,0,'PositionObserved','2026-01-01','doc','cash','position',"
                      "'doc',1,'r','n')")
        check.commit()
    check.rollback()
    assert check.execute("SELECT count(*) FROM document_account_history").fetchone() == (0,)
    check.close()


def test_corroborating_document_lookup_decodes_only_final_winners(monkeypatch):
    count = 500
    encoded = {}
    histories = []
    winning_documents = {}
    for index in range(count):
        key = f"subject:{index:04d}"
        account = f"Liabilities:Loan:{index}"
        # Most rows are overwritten, including a weaker row after verification.
        # The last verified row is the canonical winner for each mixed key.
        rows = [
            ("corroborated", f"old-{index}"),
            ("corroborated", f"newer-{index}"),
            ("verified", f"verified-{index}"),
            ("corroborated", f"ignored-{index}"),
            ("verified", f"winner-{index}"),
        ]
        for offset, (grade, document) in enumerate(rows):
            token = f"legs-{index}-{offset}"
            encoded[token] = [{"account": account}, {"account": account}]
            histories.append((index * len(rows) + offset, "movement", key,
                              token, grade, document))
        winning_documents[account] = f"winner-{index}"
    # Two different canonical keys address one account. Sorted-key traversal
    # must retain the first document even though its source row arrived later.
    shared = "Liabilities:Loan:shared"
    encoded["shared-z"] = [{"account": shared}]
    histories.append((len(histories), "movement", "zz-shared", "shared-z",
                      "verified", "later-key-document"))
    encoded["shared-a"] = [{"account": shared}]
    histories.append((len(histories), "movement", "aa-shared", "shared-a",
                      "verified", "first-key-document"))
    winning_documents[shared] = "first-key-document"
    final_winner_count = count + 2
    leg_visits = 0

    class CountedLegs(list):
        def __iter__(self):
            nonlocal leg_visits
            leg_visits += 1
            return super().__iter__()

    decoded = {key: CountedLegs(value) for key, value in encoded.items()}
    decode_calls = 0

    def decode(value):
        nonlocal decode_calls
        decode_calls += 1
        return decoded[value]

    monkeypatch.setattr(sql_questions.json, "loads", decode)
    documents = sql_questions._corroborating_documents(histories)

    assert decode_calls == final_winner_count
    assert leg_visits == final_winner_count
    assert documents == winning_documents

    lookup_calls = 0

    class CountedLookup(dict):
        def get(self, key, default=None):
            nonlocal lookup_calls
            lookup_calls += 1
            return super().get(key, default)

    lookup = CountedLookup(documents)
    rows = [{"ruling_account": account,
             "currency": "USD", "account_kind": "depository",
             "amount": -1, "nature": "settlement"}
            for account in winning_documents]
    monkeypatch.setattr(sql_questions, "_rows", lambda _connection: rows)
    monkeypatch.setattr(sql_questions, "_bounded", lambda *_args, **_kwargs: histories)
    monkeypatch.setattr(sql_questions, "_corroborating_documents",
                        lambda _histories: lookup)
    questions = sql_questions._corroboration_questions(object())
    assert len(questions) == len(winning_documents)
    assert lookup_calls == len(winning_documents)


def test_duplicate_and_contradictory_rulings_keep_canonical_first_document(tmp_path):
    events = _events()
    movement = LedgerProjection(events).movements()[0]
    events += [
        ruling_recorded(
            SCOPE_MOVEMENT, movement.key, "2026-01-13",
            legs=[{"major": "liability", "account": "Liabilities:Loan:Élan",
                   "share": ""},
                  {"major": "liability", "account": "Liabilities:Loan:Élan",
                   "share": ""}],
            grade="verified", corroborates="déclaration première 📄",
            provenance=Provenance("preuve-α", 7, "cadre:一", "émis")),
        # A weaker later duplicate must not displace the verified ruling.
        ruling_recorded(
            SCOPE_MOVEMENT, movement.key, "2026-01-14",
            legs=[{"major": "liability", "account": "Liabilities:Loan:Élan",
                   "share": ""}],
            grade="corroborated", corroborates="wrong later document"),
        # Canonical ruling-key order selects the matching key before a different key.
        # movement ruling first, independent of source order.
        ruling_recorded(
            SCOPE_MOVEMENT, "zzzz-duplicate", "2026-01-15",
            legs=[{"major": "liability", "account": "Liabilities:Loan:Élan",
                   "share": ""}],
            grade="verified", corroborates="duplicate second document"),
    ]
    source = _store(tmp_path, events)
    expected = open_questions(LedgerProjection(events), as_of="2026-03-01",
                              jurisdiction="US", locale="en-US", limit=None)
    with ReadStore.create(tmp_path / "read-model", PASSWORD) as reads:
        reads.synchronize(source)
        with reads.open_reader() as revision:
            actual = revision.open_questions(as_of="2026-03-01",
                jurisdiction="US", locale="en-US", limit=None)
            ruling_rows = revision.connection.execute(
                "SELECT grade,corroborates,provenance_doc_id,provenance_page,"
                "provenance_region,provenance_note FROM ruling_history "
                "WHERE subject=? ORDER BY source_sequence LIMIT 10", (movement.key,)
            ).fetchall()
    assert _families(actual) == _families(expected)
    question = next(row for row in actual["questions"]
                    if row["id"] == "corroboration:Liabilities:Loan:Élan")
    assert question["refs"]["document"] == "déclaration première 📄"
    assert ruling_rows[-2:] == [
        ("verified", "déclaration première 📄", "preuve-α", 7, "cadre:一", "émis"),
        ("corroborated", "wrong later document", "", None, "", ""),
    ]


def test_attribute_history_refuses_literal_cap_plus_one_before_reduction(tmp_path):
    events = [ruling_recorded(
        SCOPE_ATTRIBUTE, "acct:one:key", "2026-01-01", value=str(index),
        said=str(index), grade="verified") for index in range(10_001)]
    source = _store(tmp_path, events)
    with ReadStore.create(tmp_path / "read-model", PASSWORD) as reads:
        reads.synchronize(source)
        with reads.open_reader() as revision:
            with pytest.raises(RhythmReadError, match="10000-row read bound"):
                sql_questions.attribute_answers(revision.connection,
                                                as_of="9999-12-31")


@pytest.mark.parametrize("cuts", [(1, 3), (2, 5), (4, 7)])
def test_question_families_survive_suffix_partitions_restart_and_held_reader(tmp_path, cuts):
    events = _events()
    source = EventStore.open(tmp_path / "events.jsonl", PASSWORD)
    reads = ReadStore.create(tmp_path / "read-model", PASSWORD)
    cursor = 0
    held = None
    held_payload = None
    for end in (*cuts, len(events)):
        end = min(end, len(events))
        source.append_atomically(lambda _existing, batch=tuple(events[cursor:end]): batch)
        reads.synchronize(source)
        if held is None:
            held = reads.open_reader()
            held_payload = held.open_questions(
                as_of="2026-03-01", jurisdiction="US", locale="en-US", limit=None)
        cursor = end
    with reads.open_reader() as revision:
        actual = revision.open_questions(
            as_of="2026-03-01", jurisdiction="US", locale="en-US", limit=None)
    expected = open_questions(LedgerProjection(events), as_of="2026-03-01",
                              jurisdiction="US", locale="en-US", limit=None)
    assert _families(actual) == _families(expected)
    assert held.open_questions(as_of="2026-03-01", jurisdiction="US",
                               locale="en-US", limit=None) == held_payload
    held.close(); reads.close()
    with ReadStore.open(tmp_path / "read-model", PASSWORD) as reopened:
        assert reopened.synchronize(EventStore.open(source.path, PASSWORD)).state == "equal"
        with reopened.open_reader() as revision:
            assert _families(revision.open_questions(
                as_of="2026-03-01", jurisdiction="US", locale="en-US",
                limit=None)) == _families(expected)


def test_new_histories_refuse_overflow_and_plans_are_indexed_without_offset(tmp_path, monkeypatch):
    events = _events()
    source = _store(tmp_path, events)
    with ReadStore.create(tmp_path / "read-model", PASSWORD) as reads:
        reads.synchronize(source)
        with reads.open_reader() as revision:
            monkeypatch.setattr(sql_questions, "MAX_RULING_HISTORY_ROWS", 0)
            with pytest.raises(RhythmReadError, match="bound"):
                revision.open_questions(as_of="2026-03-01", jurisdiction="US")
            plans = " ".join(row[3] for row in revision.connection.execute(
                "EXPLAIN QUERY PLAN SELECT account_id,attribute_key,value_text FROM "
                "attribute_history WHERE occurred_at<=? ORDER BY account_id,attribute_key,"
                "occurred_at DESC,source_sequence DESC LIMIT ?", ("9999-12-31", 100)))
            assert "attributes_by_account_key_value_time" in plans
            schema_sql = " ".join(row[0] or "" for row in revision.connection.execute(
                "SELECT sql FROM sqlite_master WHERE type IN ('table','index')"))
            assert " OFFSET " not in schema_sql.upper()


def test_family_production_sql_counts_and_query_plans_are_bounded(tmp_path):
    source = _store(tmp_path, _events())
    with ReadStore.create(tmp_path / "read-model", PASSWORD) as reads:
        reads.synchronize(source)
        with reads.open_reader() as revision:
            connection = revision.connection

            def capture(call):
                statements = []
                connection.set_trace_callback(statements.append)
                try:
                    call()
                finally:
                    connection.set_trace_callback(None)
                selects = [sql for sql in statements
                           if sql.lstrip().upper().startswith("SELECT")]
                plans = [row[3] for sql in selects for row in
                         connection.execute("EXPLAIN QUERY PLAN " + sql).fetchall()]
                assert all("LIMIT" in sql.upper() for sql in selects)
                assert not any("USE TEMP B-TREE" in plan.upper() for plan in plans)
                return selects, plans

            corroboration, corroboration_plans = capture(
                lambda: sql_questions._corroboration_questions(connection))
            expectation, expectation_plans = capture(
                lambda: sql_questions._expectation_questions(
                    connection, as_of="2026-03-01", jurisdiction="US"))
            attribute, attribute_plans = capture(
                lambda: sql_questions.attribute_answers(
                    connection, as_of="2026-03-01"))
            document, document_plans = capture(lambda: connection.execute(
                "SELECT doc_id,account_id,role,provenance_doc_id,provenance_page,"
                "provenance_region,provenance_note FROM document_account_history "
                "WHERE account_id='cash' ORDER BY occurred_at,source_sequence,"
                "account_index LIMIT 201").fetchall())

            assert tuple(map(len, (corroboration, expectation, attribute, document))) == (2, 4, 2, 1)
            assert any("movements_by_question_order" in plan
                       for plan in corroboration_plans)
            assert any("accounts_by_source_date" in plan
                       for plan in expectation_plans)
            assert any("observations_by_source" in plan
                       for plan in expectation_plans)
            assert any("sqlite_autoindex_postings_1" in plan
                       for plan in expectation_plans)
            assert any("documents_by_source" in plan for plan in expectation_plans)
            assert any("attributes_by_eligible_time" in plan
                       for plan in attribute_plans)
            assert any("document_accounts_by_account" in plan
                       for plan in document_plans)
