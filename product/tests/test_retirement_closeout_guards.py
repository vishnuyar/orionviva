"""Accepted holdings boundaries preserve source custody and native/SQL parity."""
import json
from dataclasses import replace
from decimal import Decimal
import pytest

from viva.ingest import RawStore, ReadResult, capture_and_ingest
from viva.ingest.brokerage import from_brokerage_json
from viva.ledger import EventStore, Ledger, LedgerProjection
from viva.ledger.events import read_recorded, closing_balance_observed, Provenance
from viva.ledger.projection.investment_snapshots import SnapshotUnavailable
from viva.read_store import ReadStore
from test_retirement_closeout import ingest_snapshot


def opening(tmp_path):
    raw = RawStore.open(tmp_path / "raw", "synthetic-passphrase")
    ledger = Ledger(EventStore.open(tmp_path / "events.jsonl", "synthetic-passphrase"))
    result = ingest_snapshot(raw, ledger, "Synthetic initial securities", dated="2025-01-31",
        cash="100.00", total="200.00", positions=[{"instrument": "Synthetic fund",
        "units_raw": "10", "market_value_raw": "100.00", "page": 1}])
    assert result.action == "posted"
    return raw, ledger, result


def reread(document, *, positions=(), total="100.00", parse_ok=True):
    text = json.dumps({"as_of_raw": "2025-01-31", "cash_raw": "100.00",
                       "total_raw": total, "positions": list(positions)})
    return read_recorded(document, "synthetic-no-provider", "fixture", "text", text,
                         0, 0, 0, parse_ok, None, "2025-04-01")


def test_later_unaccepted_reread_does_not_reinterpret_accepted_holdings(tmp_path):
    _raw, ledger, initial = opening(tmp_path)
    ledger.append(reread(initial.doc_id))
    assert ledger.projection().account_value(initial.account) == Decimal("200.00")
    assert len(ledger.projection().positions(initial.account)) == 1
    assert LedgerProjection(ledger.events()).account_value(initial.account) == Decimal("200.00")


def test_new_native_acceptance_can_use_new_read_without_erasing_old_positions(tmp_path):
    _raw, ledger, initial = opening(tmp_path)
    old_rows = [e.to_dict() for e in ledger.events() if e.event_type == "PositionObserved"]
    ledger.append(reread(initial.doc_id))
    ledger.append(closing_balance_observed(initial.account, "100.00", "2025-01-31", Provenance(initial.doc_id)))
    assert ledger.projection().positions(initial.account) == []
    assert ledger.projection().account_value(initial.account) == Decimal("100.00")
    assert [e.to_dict() for e in ledger.events() if e.event_type == "PositionObserved"] == old_rows


def test_failed_reread_before_acceptance_preserves_last_successful_source(tmp_path):
    _raw, ledger, initial = opening(tmp_path)
    events = list(ledger.events())
    index = next(i for i, e in enumerate(events) if e.event_type == "ClosingBalanceObserved")
    events.insert(index, reread(initial.doc_id, parse_ok=False))
    projection = LedgerProjection(events)
    assert projection.account_value(initial.account) == Decimal("200.00")
    assert len(projection.positions(initial.account)) == 1


@pytest.mark.parametrize("defect", ["missing_positions", "cash_mismatch", "currency_mismatch", "date_mismatch"])
def test_incompatible_source_never_turns_into_empty_holdings(tmp_path, defect):
    _raw, ledger, initial = opening(tmp_path)
    event = reread(initial.doc_id)
    data = json.loads(event.body["response_text"])
    if defect == "missing_positions":
        data.pop("positions")
    elif defect == "cash_mismatch":
        data.update(cash_raw="0.00", total_raw="0.00")
    elif defect == "currency_mismatch":
        event.body["source_currency"] = "EUR"
    else:
        data["as_of_raw"] = "2025-02-28"
    event.body["response_text"] = json.dumps(data)
    ledger.append(event)
    ledger.append(closing_balance_observed(initial.account, "100.00", "2025-01-31", Provenance(initial.doc_id)))
    with pytest.raises(SnapshotUnavailable):
        ledger.projection().positions(initial.account)


def test_closing_before_its_nonempty_position_rows_is_unavailable(tmp_path):
    _raw, ledger, initial = opening(tmp_path)
    events = list(ledger.events())
    index = next(i for i, e in enumerate(events) if e.event_type == "ClosingBalanceObserved")
    prefix = LedgerProjection(events[:index + 1])
    with pytest.raises(SnapshotUnavailable):
        prefix.account_value(initial.account)
    assert LedgerProjection(events).account_value(initial.account) == Decimal("200.00")


def test_bare_zero_cash_closing_does_not_establish_empty_holdings(tmp_path):
    _raw, ledger, initial = opening(tmp_path)
    ledger.append(closing_balance_observed(initial.account, "0", "2025-02-28", Provenance("synthetic-unread")))
    assert len(ledger.projection().positions(initial.account)) == 1
    assert ledger.projection().account_value(initial.account) == Decimal("100.00")


def test_duplicate_native_holding_and_mutated_public_source_fail_closed(tmp_path):
    _raw, ledger, initial = opening(tmp_path)
    events = list(ledger.events())
    position = next(e for e in events if e.event_type == "PositionObserved")
    duplicate = replace(position, event_id="synthetic-distinct-position-event")
    with pytest.raises(SnapshotUnavailable):
        LedgerProjection([*events, duplicate]).positions(initial.account)
    published = ledger.projection()
    published.core._replies[initial.doc_id] = "{}"
    assert published.account_value(initial.account) == Decimal("200.00")
    assert LedgerProjection(ledger.events()).account_value(initial.account) == Decimal("200.00")


@pytest.mark.parametrize("cash,total", [("0.00", "0.00"), ("25.00", "25.00")])
def test_sql_catchup_historical_and_held_revision_match_native_empty_snapshot(tmp_path, cash, total):
    raw, ledger, initial = opening(tmp_path)
    with ReadStore.create(tmp_path / "reads", "synthetic-passphrase") as store:
        store.synchronize(ledger.store)
        with store.open_reader() as old_revision:
            old = old_revision.overview_projection(today="2025-03-05")
            assert old.composed_values(initial.account)[0].amount == Decimal("200.00")
            final = ingest_snapshot(raw, ledger, "Synthetic final securities", dated="2025-02-28",
                                    cash=cash, total=total, positions=[])
            assert final.action == "posted"
            result = store.synchronize(ledger.store)
            assert result.state == "caught_up"
            assert old.composed_values(initial.account)[0].amount == Decimal("200.00")
            with store.open_reader() as revision:
                for horizon in ("2025-01-31", "2025-02-28"):
                    native = ledger.projection_as_of(horizon)
                    sql = revision.historical_overview_projection(as_of=horizon, today="2025-03-05")
                    assert sql.composed_values(initial.account) == native.composed_values(initial.account)
                current = revision.overview_projection(today="2025-03-05")
                assert current.composed_values(initial.account) == ledger.projection().composed_values(initial.account)
    with ReadStore.open(tmp_path / "reads", "synthetic-passphrase") as reopened:
        with reopened.open_reader() as revision:
            assert revision.overview_projection(today="2025-03-05").composed_values(initial.account)[0].amount == Decimal(total)


def test_old_projector_rebuild_and_failed_publication_preserve_previous_generation(tmp_path):
    raw, ledger, initial = opening(tmp_path)
    with ReadStore.create(tmp_path / "reads", "synthetic-passphrase") as store:
        store.synchronize(ledger.store, projector_version="synthetic-old-projector")
        assert store.synchronize(ledger.store).state == "rebuilt"
        prior = store.current_generation
        final = ingest_snapshot(raw, ledger, "Synthetic final securities", dated="2025-02-28",
                                cash="0.00", total="0.00", positions=[])
        assert final.action == "posted"
        from viva.read_store import ReadStoreDegraded
        with pytest.raises(ReadStoreDegraded):
            store.synchronize(ledger.store, fail_at="before_metadata_advance")
        assert store.current_generation == prior
        with store.open_reader() as revision:
            assert revision.overview_projection(today="2025-03-05").composed_values(initial.account)[0].amount == Decimal("200.00")
        assert store.synchronize(ledger.store).state == "caught_up"


def typed_snapshot(raw, ledger, label, *, dated, cash, total, positions):
    from viva.investment.extraction import HEADERS, POSITION
    def printed(value):
        return {"raw": value, "page": 1}
    headers = {key: None for key in HEADERS}
    headers.update(account_reference=printed("SYNTHETIC-TYPED-RETIREMENT"),
        currency=printed("USD"), period_start=printed(dated[:8] + "01"),
        period_end=printed(dated), as_of=printed(dated), opening_cash=printed(cash),
        closing_cash=printed(cash), no_activity=printed("No activity"))
    typed_positions = []
    for position in positions:
        fields = {key: None for key in POSITION}
        fields.update(identifier=printed(position["instrument"]), label=printed(position["instrument"]),
            units=printed(position["units_raw"]), market_value=printed(position["market_value_raw"]))
        typed_positions.append(fields)
    packet = {"doc_type": "brokerage_statement", "doc_type_confidence": 1,
        "institution": "Synthetic Typed Securities", "account_ref": "SYNTHETIC-TYPED-RETIREMENT",
        "currency": "USD", "as_of_raw": dated, "cash_raw": cash, "total_raw": total,
        "positions": positions, "activity": [], "investment_source": {
            "schema": "investment-source-v1", "headers": headers, "positions": typed_positions, "rows": []}}
    text = json.dumps(packet)
    def reader(_blob, document):
        facts, error = from_brokerage_json(text, document, "en-US", "USD")
        assert error is None
        facts.validated_source_page_count = 1
        return ReadResult("brokerage_statement", 1, facts,
                          model="synthetic-fixture-no-provider", raw_text=text)
    result = capture_and_ingest(raw, ledger, label.encode(), reader, captured_at="2025-03-05")
    assert result.action == "posted"
    return result


@pytest.mark.parametrize("facet", ["positions", "activity"])
def test_typed_retraction_is_source_facet_specific_and_sql_agrees(tmp_path, facet):
    from viva.investment.events import STATEMENT, retract_source
    from viva.investment.lifecycle import SourceChange
    raw = RawStore.open(tmp_path / "raw", "synthetic-passphrase")
    ledger = Ledger(EventStore.open(tmp_path / "events.jsonl", "synthetic-passphrase"))
    first = typed_snapshot(raw, ledger, "Synthetic typed first", dated="2025-01-31",
        cash="100.00", total="200.00", positions=[{"instrument": "SYNTHETIC-FUND",
        "units_raw": "10", "market_value_raw": "100.00", "page": 1}])
    # No cash activity is a separate facet: this statement still holds securities.
    assert len(ledger.projection().positions(first.account)) == 1
    final = typed_snapshot(raw, ledger, "Synthetic typed closeout", dated="2025-02-28",
                           cash="0.00", total="0.00", positions=[])
    assert ledger.projection().account_value(final.account) == Decimal(0)
    statement = next(event for event in ledger.events()
                     if event.event_type == STATEMENT and event.provenance.doc_id == final.doc_id)
    before_cash = [event.to_dict() for event in ledger.events()
                   if event.event_type in {"TransactionRecorded", "ClosingBalanceObserved"}]
    retract_source(ledger, SourceChange("synthetic-retirement-retraction", facet,
        statement.body["observation_id"], final.doc_id, "2025-03-01", "source_retraction"))
    assert [event.to_dict() for event in ledger.events()
            if event.event_type in {"TransactionRecorded", "ClosingBalanceObserved"}] == before_cash
    assert ledger.projection_as_of("2025-02-28").account_value(final.account) == Decimal(0)
    with ReadStore.create(tmp_path / "reads", "synthetic-passphrase") as store:
        store.synchronize(ledger.store)
        with store.open_reader() as revision:
            historic = revision.historical_overview_projection(as_of="2025-02-28", today="2025-03-05")
            assert historic.composed_values(final.account) == ledger.projection_as_of("2025-02-28").composed_values(final.account)
            if facet == "positions":
                with pytest.raises(SnapshotUnavailable):
                    ledger.projection().account_value(final.account)
                with pytest.raises(SnapshotUnavailable):
                    revision.overview_projection(today="2025-03-05").composed_values(final.account)
            else:
                assert ledger.projection().account_value(final.account) == Decimal(0)
                assert revision.overview_projection(today="2025-03-05").composed_values(final.account)[0].amount == Decimal(0)


def test_same_document_acceptance_date_correction_retires_old_later_boundary(tmp_path):
    _raw, ledger, initial = opening(tmp_path)
    reading = reread(initial.doc_id)
    data = json.loads(reading.body["response_text"])
    data["as_of_raw"] = "2025-01-30"
    reading.body["response_text"] = json.dumps(data)
    ledger.append(reading)
    ledger.append(closing_balance_observed(initial.account, "100.00", "2025-01-30", Provenance(initial.doc_id)))
    for projection in (ledger.projection(), LedgerProjection(ledger.events())):
        assert projection.positions(initial.account) == []
        assert projection.account_value(initial.account) == Decimal("100.00")
        assert projection.composed_values(initial.account)[0].as_of == "2025-01-30"
    with ReadStore.create(tmp_path / "reads", "synthetic-passphrase") as store:
        store.synchronize(ledger.store)
        with store.open_reader() as revision:
            assert revision.overview_projection(today="2025-04-01").composed_values(initial.account) == ledger.projection().composed_values(initial.account)


@pytest.mark.parametrize("decision", ["pending", "retracted"])
def test_later_native_closing_cannot_bypass_existing_typed_lineage(tmp_path, decision):
    from viva.investment.events import STATEMENT, append_statement, retract_source, decode_statement
    from viva.investment.lifecycle import SourceChange
    raw = RawStore.open(tmp_path / "raw", "synthetic-passphrase")
    ledger = Ledger(EventStore.open(tmp_path / "events.jsonl", "synthetic-passphrase"))
    final = typed_snapshot(raw, ledger, "Synthetic unresolved typed source", dated="2025-02-28",
                           cash="0.00", total="0.00", positions=[])
    record = next(e for e in ledger.events() if e.event_type == STATEMENT)
    statement = decode_statement(record.body["statement"])
    if decision == "retracted":
        retract_source(ledger, SourceChange("synthetic-retracted-source", "positions",
            statement.observation_id, final.doc_id, "2025-03-01", "source_retraction"))
    else:
        pending = replace(statement, observation_id="synthetic-pending-source", snapshot_complete=False)
        append_statement(ledger, pending, changes=(SourceChange("synthetic-pending-change", "positions",
            statement.observation_id, final.doc_id, "2025-03-01", "source_correction", pending.observation_id),))
    ledger.append(closing_balance_observed(final.account, "0.00", "2025-02-28", Provenance(final.doc_id)))
    for projection in (ledger.projection(), LedgerProjection(ledger.events())):
        with pytest.raises(SnapshotUnavailable):
            projection.account_value(final.account)
    with ReadStore.create(tmp_path / "reads", "synthetic-passphrase") as store:
        store.synchronize(ledger.store)
        with store.open_reader() as revision:
            with pytest.raises(SnapshotUnavailable):
                revision.overview_projection(today="2025-04-01").composed_values(final.account)


@pytest.mark.parametrize("field,value", [("currency", "EUR"), ("as_of", "2025-01-30")])
def test_sql_digest_binding_keeps_native_currency_and_date_guards(tmp_path, field, value):
    _raw, ledger, initial = opening(tmp_path)
    with ReadStore.create(tmp_path / "reads", "synthetic-passphrase") as store:
        store.synchronize(ledger.store)
        with store.open_reader() as revision:
            projection = revision.overview_projection(today="2025-04-01")
            row = next(iter(projection._states[initial.account].position_history.values()))[0]
            row[field] = value
            with pytest.raises(SnapshotUnavailable):
                projection.composed_values(initial.account)


def test_missing_sql_closeout_binding_cannot_fall_back_to_old_holdings(tmp_path):
    import sqlite3
    from viva.read_store.investment_bindings import load
    from viva.read_store import ReadStoreError
    from viva.ledger.projection.core import _AccountState
    raw, ledger, initial = opening(tmp_path)
    final = ingest_snapshot(raw, ledger, "Synthetic missing SQL boundary", dated="2025-02-28",
                            cash="0.00", total="0.00", positions=[])
    assert final.action == "posted"
    with ReadStore.create(tmp_path / "reads", "synthetic-passphrase") as store:
        store.synchronize(ledger.store)
        with store.open_reader() as revision, sqlite3.connect(":memory:") as damaged:
            damaged.execute("CREATE TABLE projection_meta(singleton,source_count,source_head)")
            count, head = revision.connection.execute("SELECT source_count,source_head FROM projection_meta").fetchone()
            damaged.execute("INSERT INTO projection_meta VALUES(1,?,?)", (count, head))
            damaged.execute("CREATE TABLE investment_binding_frontier(singleton,source_count,source_head,binding_count,binding_digest)")
            frontier = revision.connection.execute("SELECT * FROM investment_binding_frontier").fetchone()
            damaged.execute("INSERT INTO investment_binding_frontier VALUES(?,?,?,?,?)", frontier)
            damaged.execute("CREATE TABLE investment_accepted_bindings(source_sequence,account_id,doc_id,dated,binding_json)")
            rows = revision.connection.execute("SELECT * FROM investment_accepted_bindings").fetchall()
            damaged.executemany("INSERT INTO investment_accepted_bindings VALUES(?,?,?,?,?)", rows)
            states = {initial.account: _AccountState()}
            load(damaged, states, "9999-12-31")
            assert len(states[initial.account].investment_snapshots) == 2
            damaged.execute("DELETE FROM investment_accepted_bindings WHERE doc_id=?", (final.doc_id,))
            with pytest.raises(ReadStoreError, match="incomplete or changed"):
                load(damaged, {initial.account: _AccountState()}, "9999-12-31")


def test_classification_only_zero_closing_cannot_replace_holdings_snapshot(tmp_path):
    from viva.ledger.events import document_captured
    _raw, ledger, initial = opening(tmp_path)
    document = "synthetic-classification-only"
    metadata = json.dumps({"doc_type": "brokerage_statement", "confidence": 1})
    ledger.append(document_captured(document, "Synthetic metadata", len(metadata),
                                   "brokerage_statement", 1, "2025-03-05"))
    ledger.append(read_recorded(document, "synthetic-no-provider", "fixture", "text", metadata,
                               0, 0, 0, True, None, "2025-03-05"))
    ledger.append(closing_balance_observed(initial.account, "0.00", "2025-02-28", Provenance(document)))
    for projection in (ledger.projection(), LedgerProjection(ledger.events())):
        assert len(projection.positions(initial.account)) == 1
        assert projection.account_value(initial.account) == Decimal("100.00")
        assert all(boundary.document != document for boundary in projection.core._acct[initial.account].investment_snapshots)
    with ReadStore.create(tmp_path / "reads", "synthetic-passphrase") as store:
        store.synchronize(ledger.store)
        with store.open_reader() as revision:
            assert revision.overview_projection(today="2025-03-05").composed_values(initial.account) == ledger.projection().composed_values(initial.account)


def legacy_native_post(ledger, *, empty=False, document="synthetic-legacy-investment", dated="2025-01-31"):
    from test_investment_evidence_source_projector import facts as source_facts
    from viva.ingest.brokerage_projector import post_brokerage
    from viva.investment.extraction import parse
    facts = source_facts()
    extension = facts.investment_source.to_dict()
    headers = extension["headers"]
    headers.update(period_start={"raw": dated[:8] + "01", "page": 1},
                   period_end={"raw": dated, "page": 1}, as_of={"raw": dated, "page": 1})
    if empty:
        extension.update(positions=[], rows=[])
        headers.update(opening_cash={"raw": "0.00", "page": 1},
                       closing_cash={"raw": "0.00", "page": 1},
                       no_activity={"raw": "No activity", "page": 1})
        facts = replace(facts, cash=Decimal(0), total=Decimal(0), positions=[],
                        opening_cash=Decimal(0), activity=[])
    facts = replace(facts, doc_id=document, as_of=dated, investment_source=parse(extension))
    posted = post_brokerage(ledger, facts)
    assert posted.action == "posted"
    assert not any(event.event_type in {"DocumentCaptured", "ReadRecorded"} for event in ledger.events())
    return posted


@pytest.mark.parametrize("empty", [False, True])
def test_uncaptured_legacy_typed_source_guards_preserve_native_financial_results(tmp_path, empty):
    from viva.ledger.projection.investment_snapshots import boundary_positions
    from viva.ledger.projection.measurements import accepted_closings
    ledger = Ledger.open(tmp_path / "events.jsonl", "synthetic-passphrase")
    posted = legacy_native_post(ledger, empty=empty)
    expected = Decimal(0) if empty else Decimal("25.00")
    for projection in (ledger.projection(), LedgerProjection(ledger.events())):
        assert projection.account_value(posted.account) == expected
        guards = projection.core._acct[posted.account].investment_snapshots
        assert guards and all(guard.status == "legacy" and not guard.read_id and not guard.read_digest for guard in guards)
        assert accepted_closings(projection.core, posted.account) == []
        with pytest.raises(SnapshotUnavailable, match="no holdings replacement"):
            boundary_positions(projection.core._acct[posted.account], guards[0])
    with ReadStore.create(tmp_path / "reads", "synthetic-passphrase") as store:
        store.synchronize(ledger.store)
        with store.open_reader() as revision:
            assert revision.overview_projection(today="2025-03-05").composed_values(posted.account) == ledger.projection().composed_values(posted.account)


def test_uncaptured_legacy_empty_source_cannot_clear_prior_native_holdings(tmp_path):
    ledger = Ledger.open(tmp_path / "events.jsonl", "synthetic-passphrase")
    first = legacy_native_post(ledger)
    final = legacy_native_post(ledger, empty=True, document="synthetic-legacy-transfer", dated="2025-02-28")
    assert final.account == first.account
    assert len(ledger.projection().positions(final.account)) == 1
    assert ledger.projection().account_value(final.account) == Decimal("25.00")
    assert ledger.projection().composed_values(final.account)[0].as_of == "2025-01-31"
    with ReadStore.create(tmp_path / "reads", "synthetic-passphrase") as store:
        store.synchronize(ledger.store)
        with store.open_reader() as revision:
            assert revision.overview_projection(today="2025-03-05").composed_values(final.account) == ledger.projection().composed_values(final.account)


@pytest.mark.parametrize("decision", ["pending", "retracted"])
def test_legacy_native_results_do_not_bypass_unresolved_positions_lifecycle(tmp_path, decision):
    from viva.investment.events import STATEMENT, decode_statement, append_statement, retract_source
    from viva.investment.lifecycle import SourceChange
    ledger = Ledger.open(tmp_path / "events.jsonl", "synthetic-passphrase")
    posted = legacy_native_post(ledger)
    record = next(event for event in ledger.events() if event.event_type == STATEMENT)
    source = decode_statement(record.body["statement"])
    if decision == "retracted":
        retract_source(ledger, SourceChange("synthetic-legacy-retraction", "positions",
            source.observation_id, source.account.document, "2025-02-01", "source_retraction"))
    else:
        pending = replace(source, observation_id="synthetic-legacy-pending", snapshot_complete=False,
                          rows=tuple(replace(row, observation_id="synthetic-pending-row-" + str(index))
                                     for index, row in enumerate(source.rows)))
        append_statement(ledger, pending, changes=(SourceChange("synthetic-legacy-pending-change", "positions",
            source.observation_id, source.account.document, "2025-02-01", "source_correction", pending.observation_id),))
    assert ledger.projection_as_of("2025-01-31").account_value(posted.account) == Decimal("25.00")
    for projection in (ledger.projection(), LedgerProjection(ledger.events())):
        with pytest.raises(SnapshotUnavailable):
            projection.account_value(posted.account)
    with ReadStore.create(tmp_path / "reads", "synthetic-passphrase") as store:
        store.synchronize(ledger.store)
        with store.open_reader() as revision:
            with pytest.raises(SnapshotUnavailable):
                revision.overview_projection(today="2025-03-05").composed_values(posted.account)
            assert revision.historical_overview_projection(as_of="2025-01-31", today="2025-03-05").composed_values(posted.account)[0].amount == Decimal("25.00")


@pytest.mark.parametrize("descriptor", [
    {"schema_version": 2, "normalization_rules_version": "nv1", "parser_locale": "en-US", "parser_currency": "USD"},
    {"schema_version": 1, "normalization_rules_version": "unsupported", "parser_locale": "en-US", "parser_currency": "USD"},
])
def test_unsupported_context_does_not_break_cash_fold_or_supply_investment_authority(tmp_path, descriptor):
    from viva.ledger.events import account_opened, document_captured
    bank = Ledger.open(tmp_path / "bank.jsonl", "synthetic-passphrase")
    bank.append(account_opened("synthetic-bank", "depository", "Synthetic cash", "USD", "2025-01-01"))
    event = reread("synthetic-bank-reading")
    event.body["normalization_context"] = descriptor
    bank.append(document_captured(event.provenance.doc_id, "Synthetic cash source", 1, "bank_statement", 1, "2025-01-31"))
    bank.append(event)
    bank.append(closing_balance_observed("synthetic-bank", "100.00", "2025-01-31", event.provenance))
    assert bank.projection().account_value("synthetic-bank") == Decimal("100.00")
    _raw, ledger, initial = opening(tmp_path / "investment")
    bad = reread(initial.doc_id)
    bad.body["normalization_context"] = descriptor
    ledger.append(bad)
    assert ledger.projection().account_value(initial.account) == Decimal("200.00")
    ledger.append(closing_balance_observed(initial.account, "100.00", "2025-01-31", Provenance(initial.doc_id)))
    with pytest.raises(SnapshotUnavailable):
        ledger.projection().positions(initial.account)


@pytest.mark.parametrize("empty", [False, True])
def test_older_retired_legacy_guard_does_not_hide_newer_captured_complete_source(tmp_path, empty):
    from test_investment_evidence_source_projector import facts as source_facts
    from viva.investment.events import STATEMENT, retract_source
    from viva.investment.lifecycle import SourceChange
    ledger = Ledger.open(tmp_path / "events.jsonl", "synthetic-passphrase")
    raw = RawStore.open(tmp_path / "raw", "synthetic-passphrase")
    first = legacy_native_post(ledger)
    original = next(event for event in ledger.events() if event.event_type == STATEMENT)
    retract_source(ledger, SourceChange("synthetic-older-retraction", "positions",
        original.body["observation_id"], original.provenance.doc_id, "2025-02-01", "source_retraction"))
    identity = source_facts()
    packet = {"doc_type": "brokerage_statement", "doc_type_confidence": 1,
        "institution": identity.institution, "account_ref": identity.account_ref,
        "account_number": identity.account_number, "as_of_raw": "2025-02-28",
        "cash_raw": "50.00", "total_raw": "50.00" if empty else "75.00",
        "positions": [] if empty else [{"instrument": "SYNTHETIC-NEW-HOLDING",
            "units_raw": "1", "market_value_raw": "25.00", "page": 1}]}
    text = json.dumps(packet)
    def reader(_body, document):
        facts, error = from_brokerage_json(text, document, "en-US", "USD")
        assert error is None
        return ReadResult("brokerage_statement", 1, facts,
                          model="synthetic-fixture-no-provider", raw_text=text)
    final = capture_and_ingest(raw, ledger, ("Synthetic newer source " + str(empty)).encode(),
                               reader, captured_at="2025-03-05")
    assert final.action == "posted" and final.account == first.account
    expected = Decimal("50.00") if empty else Decimal("75.00")
    for projection in (ledger.projection(), LedgerProjection(ledger.events())):
        assert projection.account_value(final.account) == expected
        assert projection.composed_values(final.account)[0].as_of == "2025-02-28"
    with ReadStore.create(tmp_path / "reads", "synthetic-passphrase") as store:
        store.synchronize(ledger.store)
        with store.open_reader() as revision:
            assert revision.overview_projection(today="2025-03-05").composed_values(final.account) == ledger.projection().composed_values(final.account)


@pytest.mark.parametrize("retract", [False, True])
def test_backdated_legacy_guard_still_owns_later_native_position_rows(tmp_path, retract):
    from viva.investment.events import STATEMENT, decode_statement, append_statement, retract_source
    from viva.investment.lifecycle import SourceChange
    ledger = Ledger.open(tmp_path / "events.jsonl", "synthetic-passphrase")
    posted = legacy_native_post(ledger)
    record = next(event for event in ledger.events() if event.event_type == STATEMENT)
    source = decode_statement(record.body["statement"])
    pending = replace(source, observation_id="synthetic-backdated-legacy-pending", snapshot_complete=False,
        positions=(), end=replace(source.end, value="2025-01-30", raw="2025-01-30"),
        as_of=replace(source.as_of, value="2025-01-30", raw="2025-01-30") if source.as_of is not None else None,
        rows=tuple(replace(row, observation_id="synthetic-backdated-row-" + str(index))
                   for index, row in enumerate(source.rows)))
    append_statement(ledger, pending, changes=(SourceChange("synthetic-backdated-legacy-change", "positions",
        source.observation_id, source.account.document, "2025-02-01", "source_correction", pending.observation_id),))
    if retract:
        retract_source(ledger, SourceChange("synthetic-backdated-legacy-retract", "positions",
            source.observation_id, source.account.document, "2025-02-02", "source_retraction"))
    assert ledger.projection_as_of("2025-01-31").account_value(posted.account) == Decimal("25.00")
    for projection in (ledger.projection(), LedgerProjection(ledger.events())):
        with pytest.raises(SnapshotUnavailable):
            projection.account_value(posted.account)
    with ReadStore.create(tmp_path / "reads", "synthetic-passphrase") as store:
        store.synchronize(ledger.store)
        with store.open_reader() as revision:
            with pytest.raises(SnapshotUnavailable):
                revision.overview_projection(today="2025-03-05").composed_values(posted.account)
