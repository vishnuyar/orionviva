"""Exact parity and work bounds for the SQL-native Overview prerequisite."""
from decimal import Decimal
from pathlib import Path

import pytest

from viva.ledger import (EventStore, Ledger, LedgerProjection, Provenance, account_opened,
                         closing_balance_observed, opening_balance_observed,
                         simple_transaction)
from viva.ledger.events import (SCOPE_ATTRIBUTE, VERIFIED, document_captured,
                                category_assigned, position_observed,
                                read_recorded, ruling_recorded,
                                transfer_suggested)
from viva.read_store import ReadStore
from viva.ingest import (PARKED, POSTED, RawStore, ReadResult, StatementFacts,
                         capture_and_ingest)
from viva.read_store import overview as sql_overview
from viva.surface.overview import overview
from viva.surface.activity import activity
from viva.surface.spending import spending_breakdown
from viva.surface.review import review

from test_read_store_composition import PASSPHRASE, _composition_events


def _source(path: Path, events=()):
    source = EventStore.open(path / "events.jsonl", PASSPHRASE)
    if events:
        source.append_atomically(lambda _existing: tuple(events))
    return source


def test_complete_current_sql_overview_matches_the_surface_oracle(tmp_path):
    events = _composition_events() + [
        account_opened("Assets:Property:Cottage", "asset", "Cottage", "USD",
                       "2026-01-01", jurisdiction="US", origin="asserted"),
        ruling_recorded(SCOPE_ATTRIBUTE,
                       "Assets:Property:Cottage:purchase_price", "2026-01-02",
                       by="human", grade=VERIFIED, said="250000", value="250000",
                       currency="USD"),
        ruling_recorded(SCOPE_ATTRIBUTE,
                       "Assets:Property:Cottage:acquired_on", "2026-01-02",
                       by="human", grade=VERIFIED, said="2019-06-01",
                       value="2019-06-01"),
    ]
    source = _source(tmp_path, events)
    with ReadStore.create(tmp_path / "read-model", PASSPHRASE) as reads:
        reads.synchronize(source)
        with reads.open_reader() as revision:
            actual = overview(revision.overview_projection(today="2026-05-01"),
                              "en-US", "2026-05-01")
    expected_projection = LedgerProjection(events)
    assert actual == overview(expected_projection, "en-US", "2026-05-01")


def test_current_activity_and_spending_sql_match_the_surface_oracles(tmp_path):
    events = _composition_events()
    source = _source(tmp_path, events)
    canonical = LedgerProjection(events)
    with ReadStore.create(tmp_path / "read-model", PASSPHRASE) as reads:
        reads.synchronize(source)
        with reads.open_reader() as revision:
            actual_activity = activity(
                revision.activity_projection(), "en-US", limit=5)
            actual_spending = spending_breakdown(
                revision.spending_projection(today="2026-05-01"),
                "en-US", "2026-05-01", period="current_month")
    assert actual_activity == activity(canonical, "en-US", limit=5)
    assert actual_spending == spending_breakdown(
        canonical, "en-US", "2026-05-01", period="current_month")


def test_sql_statement_register_preserves_declared_period_and_exact_decimals(tmp_path):
    provenance = Provenance("jan", 3, "summary", "issuer")
    response = ('{"opening":{"amount_raw":"1000.0000","date_raw":"2026-01-01"},'
                '"closing":{"amount_raw":"987.6600","date_raw":"2026-01-31"},'
                '"transactions":[]}')
    events = [
        document_captured("jan", "jan.pdf", 1, "checking_statement", 1,
                          "2026-02-01", provenance),
        read_recorded("jan", "route", "v1", "text", response, 0, 0, 0,
                      True, None, "2026-02-01", provenance),
        account_opened("cash", "depository", "Cash", "USD", "2026-01-01",
                       provenance=provenance),
        opening_balance_observed("cash", "1000.0000", "2026-01-01", provenance),
        simple_transaction("cash", "-12.3400", "MARKET", "2026-01-15",
                           kind="depository", provenance=provenance),
        closing_balance_observed("cash", "987.6600", "2026-01-31", provenance),
    ]
    movement = LedgerProjection(events).movements()[0]
    events.append(category_assigned(
        movement.key, movement.description, "groceries", VERIFIED,
        "2026-02-02", nature="spending", subcategory="market"))
    source = _source(tmp_path, events)
    with ReadStore.create(tmp_path / "read-model", PASSPHRASE) as reads:
        reads.synchronize(source)
        with reads.open_reader() as revision:
            traced = []
            revision.connection.set_trace_callback(traced.append)
            sql = revision.spending_projection(today="2026-02-15", locale="en-US")
            revision.connection.set_trace_callback(None)
            record = sql.statements("cash").records[0]
            actual = spending_breakdown(
                sql, "en-US", "2026-02-15", period="latest_complete_month")
            statement_sql = next(statement for statement in traced
                                 if "statement_periods p INDEXED" in statement)
            plan = " ".join(str(row[3]) for row in revision.connection.execute(
                "EXPLAIN QUERY PLAN " + statement_sql).fetchall())
    assert str(record.opening_amount) == "1000.0000"
    assert str(record.closing_amount) == "987.6600"
    assert "statement_periods_by_account_date" in plan
    assert "documents_by_doc" in plan
    assert "document_reads_by_doc_phase_source" in plan
    assert "TEMP B-TREE" not in plan
    assert actual == spending_breakdown(
        LedgerProjection(events), "en-US", "2026-02-15",
        period="latest_complete_month")


def test_statement_register_preserves_each_account_order_without_sort(tmp_path):
    records = []
    for account in ("account-a", "account-z"):
        for month, opening, closing in (
            ("01", "10.0000", "10.0000"),
            ("02", "10.0000", "10.0000"),
        ):
            doc = f"{account}-{month}"
            provenance = Provenance(doc, 0, "summary", "issuer")
            response = (
                '{"opening":{"amount_raw":"' + opening +
                '","date_raw":"2026-' + month + '-01"},'
                '"closing":{"amount_raw":"' + closing +
                '","date_raw":"2026-' + month + '-28"},'
                '"transactions":[]}')
            records.extend([
                document_captured(doc, f"{doc}.pdf", 1,
                                  "checking_statement", 1, f"2026-{month}-28",
                                  provenance),
                read_recorded(doc, "route", "v1", "text", response, 0,
                              0, 0, True, None, f"2026-{month}-28", provenance),
            ])
            if month == "01":
                records.append(account_opened(
                    account, "depository", account, "USD", "2026-01-01",
                    provenance=provenance))
                records.append(opening_balance_observed(
                    account, opening, "2026-01-01", provenance))
            records.append(closing_balance_observed(
                account, closing, f"2026-{month}-28", provenance))
    source = _source(tmp_path, records)
    canonical = LedgerProjection(records)
    with ReadStore.create(tmp_path / "read-model", PASSPHRASE) as reads:
        assert reads.synchronize(source).state == "rebuilt"
        with reads.open_reader() as revision:
            traced = []
            revision.connection.set_trace_callback(traced.append)
            sql = revision.spending_projection(today="2026-03-01")
            revision.connection.set_trace_callback(None)
            for account in ("account-a", "account-z"):
                assert sql.statements(account).records == canonical.statements(account).records
            assert overview(sql, "en-US", "2026-03-01") == overview(
                canonical, "en-US", "2026-03-01")
            query = next(statement for statement in traced
                         if "statement_periods p INDEXED" in statement)
            plan = " ".join(str(row[3]) for row in revision.connection.execute(
                "EXPLAIN QUERY PLAN " + query).fetchall())
            assert "statement_periods_by_account_date" in plan
            assert "TEMP B-TREE" not in plan


def test_parked_read_retry_uses_latest_document_evidence_once(tmp_path):
    raw = RawStore.open(tmp_path / "raw", PASSPHRASE)
    source = _source(tmp_path)
    ledger = Ledger(source)
    data = b"synthetic-statement"

    def failed(_data, _doc_id):
        raise RuntimeError("synthetic read failure")

    first = capture_and_ingest(raw, ledger, data, failed,
                               filename="statement.pdf", captured_at="2026-02-01")
    assert first.action == PARKED
    response = ('{"opening":{"amount_raw":"100.00","date_raw":"2026-01-01"},'
                '"closing":{"amount_raw":"100.00","date_raw":"2026-01-31"},'
                '"transactions":[]}')

    def recovered(_data, doc_id):
        facts = StatementFacts(
            doc_id=doc_id, doc_type="checking_statement", doc_type_confidence=1.0,
            account_ref="Synthetic Checking", currency="USD",
            opening_amount=Decimal("100.00"), opening_date="2026-01-01",
            closing_amount=Decimal("100.00"), closing_date="2026-01-31",
            transactions=[])
        return ReadResult("checking_statement", 1.0, facts, raw_text=response,
                          model="synthetic")

    second = capture_and_ingest(raw, ledger, data, recovered,
                                filename="statement.pdf", captured_at="2026-02-02")
    assert second.action == POSTED
    events = tuple(ledger.events())
    assert sum(event.event_type == "DocumentCaptured" for event in events) == 2
    assert sum(event.event_type == "ClosingBalanceObserved" for event in events) == 1
    canonical = LedgerProjection(events)
    with ReadStore.create(tmp_path / "read-model", PASSPHRASE) as reads:
        reads.synchronize(source)
        with reads.open_reader() as revision:
            traced = []
            revision.connection.set_trace_callback(traced.append)
            sql_spending = revision.spending_projection(
                today="2026-02-15", locale="en-US")
            sql_review = revision.review_projection(locale="en-US")
            revision.connection.set_trace_callback(None)
            actual_spending = spending_breakdown(
                sql_spending, "en-US", "2026-02-15", period="latest_complete_month")
            actual_review = review(sql_review, "en-US")
            statement_sql = next(statement for statement in traced
                                 if "statement_periods p INDEXED" in statement)
            plan = " ".join(str(row[3]) for row in revision.connection.execute(
                "EXPLAIN QUERY PLAN " + statement_sql).fetchall())
    assert actual_spending == spending_breakdown(
        canonical, "en-US", "2026-02-15", period="latest_complete_month")
    assert actual_review == review(canonical, "en-US")
    assert "statement_periods_by_account_date" in plan
    assert "documents_by_doc" in plan
    assert "document_reads_by_doc_phase_source" in plan
    assert "TEMP B-TREE" not in plan


def test_activity_page_is_pending_first_exact_focused_and_index_planned(tmp_path):
    events = [account_opened(
        "cash", "depository", "Cash", "USD", "2026-01-01")]
    events.extend(simple_transaction(
        "cash", str(-number), f"ROW {number}", f"2026-01-{number:02d}",
        kind="depository") for number in range(1, 6))
    movements = LedgerProjection(events).movements()
    events.append(transfer_suggested(
        movements[0].key, [movements[1].key], {"reason": "amount"},
        "2026-02-01"))
    source = _source(tmp_path, events)
    with ReadStore.create(tmp_path / "read-model", PASSPHRASE) as reads:
        reads.synchronize(source)
        with reads.open_reader() as revision:
            projection = revision.activity_projection()
            page, beyond = projection.activity_page(2)
            focused, focused_beyond = projection.activity_page(
                2, movements[2].key)
            plan = " ".join(str(row[3]) for row in revision.connection.execute(
                "EXPLAIN QUERY PLAN SELECT m.movement_key FROM movements m "
                "INDEXED BY movements_by_activity_order JOIN transfer_suggestions s "
                "ON s.movement_a=m.movement_key ORDER BY m.occurred_at DESC,"
                "m.movement_key DESC LIMIT 2").fetchall())
    assert [item.key for item in page] == [movements[0].key, movements[-1].key]
    assert beyond == 3
    assert movements[2].key in {item.key for item in focused}
    assert focused_beyond == 3
    assert "movements_by_activity_order" in plan
    assert "TEMP B-TREE" not in plan


def test_current_activity_revision_is_immutable_across_later_publication(tmp_path):
    source = _source(tmp_path, [
        account_opened("cash", "depository", "Cash", "USD", "2026-01-01"),
        simple_transaction("cash", "-1.00", "ONE", "2026-01-02",
                           kind="depository"),
    ])
    reads = ReadStore.create(tmp_path / "read-model", PASSPHRASE)
    reads.synchronize(source)
    held = reads.open_reader()
    before = activity(held.activity_projection(), "en-US")
    source.append(simple_transaction(
        "cash", "-2.00", "TWO", "2026-01-03", kind="depository"))
    reads.synchronize(source)
    with reads.open_reader() as current:
        after = activity(current.activity_projection(), "en-US")

    assert activity(held.activity_projection(), "en-US") == before
    assert len(after["items"]) == len(before["items"]) + 1
    held.close()
    reads.close()


def test_current_overview_folds_future_dated_and_late_backfilled_evidence(tmp_path):
    """Read-on dates the answer; it does not hide committed current evidence."""
    events = _composition_events() + [
        account_opened("future", "depository", "Future", "USD", "2027-01-01"),
        closing_balance_observed("future", "70", "2027-01-02"),
        simple_transaction("cash-us", "5", "late append, old value date",
                           "2025-10-01", kind="depository"),
        opening_balance_observed("future", "65", "2026-12-31"),
    ]
    source = _source(tmp_path, events)
    with ReadStore.create(tmp_path / "read-model", PASSPHRASE) as reads:
        reads.synchronize(source)
        with reads.open_reader() as revision:
            actual = overview(revision.overview_projection(today="2026-05-01"),
                              "en-US", "2026-05-01")
    assert actual == overview(LedgerProjection(events), "en-US", "2026-05-01")


def test_position_snapshot_uses_newest_date_and_last_same_day_source(tmp_path):
    events = [
        account_opened("broker", "investment", "Broker", "USD", "2026-01-01"),
        position_observed("broker", "AAA", "1", "10", "USD", "2026-03-01"),
        position_observed("broker", "BBB", "1", "20", "USD", "2026-03-01"),
        position_observed("broker", "AAA", "1", "11", "USD", "2026-03-01"),
        position_observed("broker", "OLD", "1", "999", "USD", "2026-02-01"),
        position_observed("broker", "CASH", "1", "3", "USD", "2026-02-15"),
        position_observed("broker", "CASH", "1", "4", "USD", "2026-02-15"),
    ]
    source = _source(tmp_path, events)
    with ReadStore.create(tmp_path / "read-model", PASSPHRASE) as reads:
        reads.synchronize(source)
        with reads.open_reader() as revision:
            sql = revision.overview_projection(today="2026-01-15")
            actual = sql.composed_values("broker")
    expected = LedgerProjection(events).composed_values("broker")
    assert actual == expected
    assert actual[0].amount == 35


def test_overview_survives_suffix_batches_restart_and_held_reader(tmp_path):
    events = _composition_events()
    source = _source(tmp_path)
    root = tmp_path / "read-model"
    reads = ReadStore.create(root, PASSPHRASE)
    source.append_atomically(lambda _existing: tuple(events[:8]))
    reads.synchronize(source)
    held = reads.open_reader()
    held_payload = overview(held.overview_projection(today="2026-05-01"),
                            "en-US", "2026-05-01")
    for start, stop in ((8, 17), (17, len(events))):
        source.append_atomically(
            lambda _existing, batch=tuple(events[start:stop]): batch)
        reads.synchronize(source)
    with reads.open_reader() as current:
        assert overview(current.overview_projection(today="2026-05-01"),
                        "en-US", "2026-05-01") == overview(
            LedgerProjection(events), "en-US", "2026-05-01")
    assert overview(held.overview_projection(today="2026-05-01"),
                    "en-US", "2026-05-01") == held_payload
    held.close(); reads.close()
    with ReadStore.open(root, PASSPHRASE) as reopened:
        with reopened.open_reader() as revision:
            assert overview(revision.overview_projection(today="2026-05-01"),
                            "en-US", "2026-05-01") == overview(
                LedgerProjection(events), "en-US", "2026-05-01")


def test_overview_runtime_never_opens_canonical_or_raw_storage(tmp_path, monkeypatch):
    events = _composition_events()
    source = _source(tmp_path, events)
    with ReadStore.create(tmp_path / "read-model", PASSPHRASE) as reads:
        reads.synchronize(source)
        from viva.ingest.raw_store import RawStore
        from viva.ledger.projection import LedgerProjection as ProjectionType
        monkeypatch.setattr(EventStore, "open", classmethod(
            lambda *_args, **_kwargs: pytest.fail("Overview opened EventStore")))
        monkeypatch.setattr(RawStore, "open", classmethod(
            lambda *_args, **_kwargs: pytest.fail("Overview opened RawStore")))
        monkeypatch.setattr(ProjectionType, "__init__",
                            lambda *_args, **_kwargs: pytest.fail(
                                "Overview constructed LedgerProjection"))
        with reads.open_reader() as revision:
            payload = overview(revision.overview_projection(today="2026-05-01"),
                               "en-US", "2026-05-01")
    assert payload["account_count"] == len(payload["accounts"])


@pytest.mark.parametrize("constant,label", [
    ("MAX_OVERVIEW_ACCOUNTS", "account"),
    ("MAX_OVERVIEW_OBSERVATIONS", "observation"),
    ("MAX_OVERVIEW_POSITIONS", "position"),
    ("MAX_OVERVIEW_MOVEMENTS", "movement"),
    ("MAX_OVERVIEW_DOCUMENT_LINKS", "document"),
    ("MAX_OVERVIEW_RULINGS", "ruling"),
])
def test_overview_refuses_every_input_family_whole(tmp_path, monkeypatch,
                                                   constant, label):
    events = _composition_events() + [
        position_observed("broker", "AAA", "1", "10", "USD", "2026-03-01"),
        position_observed("broker", "BBB", "1", "20", "USD", "2026-03-01"),
        document_captured("doc-a", "a.pdf", 1, "bank_statement", .9, "2026-01-01"),
        document_captured("doc-b", "b.pdf", 1, "bank_statement", .9, "2026-01-02"),
        ruling_recorded(SCOPE_ATTRIBUTE, "a:x", "2026-01-01", by="human",
                        grade=VERIFIED, said="1", value="1"),
        ruling_recorded(SCOPE_ATTRIBUTE, "a:y", "2026-01-02", by="human",
                        grade=VERIFIED, said="2", value="2"),
    ]
    source = _source(tmp_path, events)
    with ReadStore.create(tmp_path / "read-model", PASSPHRASE) as reads:
        reads.synchronize(source)
        monkeypatch.setattr(sql_overview, constant, 1)
        with reads.open_reader() as revision:
            with pytest.raises(Exception, match=f"(?i){label}.*bound|bound.*{label}"):
                overview(revision.overview_projection(today="2026-05-01"),
                         "en-US", "2026-05-01")


def test_overview_queries_are_bounded_indexed_and_offset_free(tmp_path):
    source = _source(tmp_path, _composition_events())
    with ReadStore.create(tmp_path / "read-model", PASSPHRASE) as reads:
        reads.synchronize(source)
        with reads.open_reader() as revision:
            statements = []
            revision.connection.set_trace_callback(statements.append)
            revision.overview_projection(today="2026-05-01")
            revision.connection.set_trace_callback(None)
            selects = [sql for sql in statements
                       if sql.lstrip().upper().startswith(("SELECT", "WITH"))]
            plans = [" ".join(str(row[3]) for row in revision.connection.execute(
                "EXPLAIN QUERY PLAN " + sql).fetchall()) for sql in selects]
    assert len(selects) == 15
    assert all("SCAN" in plan or "SEARCH" in plan for plan in plans)
    assert all("USE TEMP B-TREE" not in plan for plan in plans)
    assert all("AUTOMATIC" not in plan.upper() for plan in plans)
    # The history PK supplies source/account order; the persistent document
    # lookup index supplies the join without asking SQLite to build one.
    assert any("documents_by_doc" in plan for plan in plans)
    assert not any("WITH RECURSIVE" in sql.upper() for sql in selects)
    assert "OFFSET" not in Path(sql_overview.__file__).read_text()


def test_overview_query_count_is_fixed_for_current_corpus(tmp_path):
    source = _source(tmp_path, _composition_events())
    with ReadStore.create(tmp_path / "read-model", PASSPHRASE) as reads:
        reads.synchronize(source)
        with reads.open_reader() as revision:
            statements = []
            revision.connection.set_trace_callback(statements.append)
            overview(revision.overview_projection(today="2026-05-01"),
                     "en-US", "2026-05-01")
            revision.connection.set_trace_callback(None)
    selects = [sql for sql in statements
               if sql.lstrip().upper().startswith(("SELECT", "WITH"))]
    # The complete Overview query budget is independent of account count.
    assert len(selects) <= 70, "\n".join(selects)


def test_overview_prerequisite_query_count_does_not_grow_per_account(tmp_path):
    events = [account_opened(f"a-{number}", "depository", f"A {number}",
                             "USD", "2026-01-01")
              for number in range(40)]
    source = _source(tmp_path, events)
    with ReadStore.create(tmp_path / "read-model", PASSPHRASE) as reads:
        reads.synchronize(source)
        with reads.open_reader() as revision:
            statements = []
            revision.connection.set_trace_callback(statements.append)
            revision.overview_projection(today="2026-05-01")
            revision.connection.set_trace_callback(None)
    selects = [sql for sql in statements
               if sql.lstrip().upper().startswith(("SELECT", "WITH"))]
    assert len(selects) == 15
