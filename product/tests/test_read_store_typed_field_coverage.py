"""Field-level checks for typed rows and their ordered children."""

import json
from pathlib import Path

import pytest

from viva.ledger import EventStore, Posting, Provenance
from viva.ledger import events
from viva.read_store import ReadStore


PASSPHRASE = "correct horse battery staple"
TABLES = (
    "accounts", "account_names", "balance_observations", "transactions",
    "transaction_tags", "postings", "positions", "documents",
)


def _corpus():
    cited = Provenance("文書-α", 0, "表:一", "note ☕")
    uncited = Provenance()
    return [
        events.account_opened(
            "acct-α", "depository", "雪", "USD", "2026-01-01",
            institution="", account_number="", account_names=["李", "李", ""],
            provenance=cited),
        events.account_identity_observed(
            "acct-α", "2026-01-02", account_names=[], provenance=uncited),
        events.opening_balance_observed(
            "acct-α", "-999999999999.000000000001", "2026-01-03", cited),
        events.transaction_recorded(
            [Posting("acct-α", "-0.5000", "verified"),
             Posting("Expenses:X", "0.5000", "unverified"),
             Posting("acct-α", "-0.5000", "verified"),
             Posting("Expenses:X", "0.5000", "unverified")],
            "店 ☕", "2026-01-04", tags=["旅", "旅", ""], provenance=cited),
        events.closing_balance_observed(
            "acct-α", "0.0000", "2026-01-05", uncited, confirmed_by=""),
        events.position_observed(
            "acct-α", "FUND/世界", "1.2300", "999999999999.000000000001",
            "USD", "2026-01-06", cost_basis="0.0000", provenance=cited),
        events.position_observed(
            "acct-α", "NO-BASIS", "0.0000", "0.0000", "USD",
            "2026-01-07", cost_basis=None, provenance=uncited),
        events.document_captured(
            "doc-α", "résumé.pdf", 0, "", 0.0, "2026-01-08", cited),
    ]


def _snapshot(revision):
    return {table: revision.connection.execute(
        f"SELECT * FROM {table} ORDER BY 1,2").fetchall()
        for table in TABLES}


def _assert_fields(revision, corpus):
    db = revision.connection
    for sequence, event in enumerate(corpus):
        body = event.body
        provenance = (event.provenance.doc_id, event.provenance.page,
                      event.provenance.region, event.provenance.note)
        table = {
            "AccountOpened": "accounts",
            "AccountIdentityObserved": "accounts",
            "OpeningBalanceObserved": "balance_observations",
            "ClosingBalanceObserved": "balance_observations",
            "TransactionRecorded": "transactions",
            "PositionObserved": "positions",
            "DocumentCaptured": "documents",
        }[event.event_type]
        if event.event_type == "AccountOpened":
            fields = (body["account_id"], body["kind"], body["name"],
                      body["currency"], body["jurisdiction"], body["institution"],
                      body["account_number"], body["origin"])
        elif event.event_type == "AccountIdentityObserved":
            fields = (body["account_id"], None, None, None, None,
                      body["institution"], body["account_number"], None)
        elif event.event_type in ("OpeningBalanceObserved", "ClosingBalanceObserved"):
            fields = (body["account_id"], body["amount"],
                      body["confirmed_by"] if event.event_type == "ClosingBalanceObserved"
                      else None)
        elif event.event_type == "TransactionRecorded":
            fields = (body["description"],)
        elif event.event_type == "PositionObserved":
            fields = (body["account_id"], body["instrument"], body["units"],
                      body["market_value"], body["currency"], body["cost_basis"],
                      body["valuation_class"], body["grade"])
        else:
            fields = (body["doc_id"], body["filename"], body["byte_len"],
                      body["doc_type"],
                      json.dumps(body["doc_type_confidence"], separators=(",", ":")),
                      "captured")
        expected = (sequence, event.event_type)
        if table == "accounts":
            expected += fields[:1] + (event.occurred_at,) + fields[1:]
        elif table == "balance_observations":
            expected += fields[:1] + (event.occurred_at,) + fields[1:]
        elif table == "transactions":
            expected += (event.occurred_at,) + fields
        elif table == "positions":
            expected += fields[:1] + (event.occurred_at,) + fields[1:]
        else:
            expected += fields[:1] + (event.occurred_at,) + fields[1:]
        expected += provenance
        assert db.execute(f"SELECT * FROM {table} WHERE source_sequence=?",
                          (sequence,)).fetchone() == expected
    account = db.execute(
        "SELECT account_id,kind,name,currency,jurisdiction,institution,"
        "account_number,origin FROM accounts WHERE source_sequence=0").fetchone()
    assert account == ("acct-α", "depository", "雪", "USD", "", "", "", "issued")
    identity = db.execute(
        "SELECT kind,name,currency,jurisdiction,institution,account_number,origin "
        "FROM accounts WHERE source_sequence=1").fetchone()
    assert identity == (None, None, None, None, "", "", None)
    assert db.execute(
        "SELECT * FROM account_names WHERE source_sequence=0 "
        "ORDER BY name_index").fetchall() == [
            (0, 0, "李"), (0, 1, "李"), (0, 2, "")]
    assert db.execute(
        "SELECT name FROM account_names WHERE source_sequence=1").fetchall() == []
    assert db.execute(
        "SELECT amount_text,confirmed_by FROM balance_observations "
        "WHERE source_sequence=2").fetchone() == (
            "-999999999999.000000000001", None)
    assert db.execute(
        "SELECT amount_text,confirmed_by FROM balance_observations "
        "WHERE source_sequence=4").fetchone() == ("0.0000", "")
    assert db.execute(
        "SELECT * FROM transaction_tags WHERE source_sequence=3 "
        "ORDER BY tag_index").fetchall() == [
            (3, 0, "旅"), (3, 1, "旅"), (3, 2, "")]
    assert db.execute(
        "SELECT * FROM postings "
        "WHERE source_sequence=3 ORDER BY posting_index").fetchall() == [
            (3, 0, "acct-α", "-0.5000", "verified"),
            (3, 1, "Expenses:X", "0.5000", "unverified"),
            (3, 2, "acct-α", "-0.5000", "verified"),
            (3, 3, "Expenses:X", "0.5000", "unverified"),
        ]
    assert db.execute(
        "SELECT instrument_id,quantity_text,value_text,currency,"
        "cost_basis_text,valuation_class,grade FROM positions "
        "WHERE source_sequence=5").fetchone() == (
            "FUND/世界", "1.2300", "999999999999.000000000001", "USD",
            "0.0000", "measured", "corroborated")
    assert db.execute(
        "SELECT instrument_id,quantity_text,value_text,cost_basis_text "
        "FROM positions WHERE source_sequence=6").fetchone() == (
            "NO-BASIS", "0.0000", "0.0000", "")
    assert db.execute(
        "SELECT doc_id,filename,byte_len,doc_type,doc_type_confidence_text "
        "FROM documents WHERE source_sequence=7").fetchone() == (
            "doc-α", "résumé.pdf", 0, "", "0.0")


@pytest.mark.parametrize("cut", [1, 3, 5, 7])
def test_typed_fields_survive_suffix_restart_full_rebuild_and_held_reader(
        tmp_path: Path, cut: int):
    corpus = _corpus()
    canonical = EventStore.open(tmp_path / "events.jsonl", PASSPHRASE)
    for event in corpus[:cut]:
        canonical.append(event)
    split_path = tmp_path / "split"
    with ReadStore.create(split_path, PASSPHRASE) as split:
        assert split.synchronize(canonical).state == "rebuilt"
        held = split.open_reader()
        before = _snapshot(held)
        for event in corpus[cut:]:
            canonical.append(event)
        assert split.synchronize(canonical).state == "caught_up"
        assert _snapshot(held) == before
        held.close()
        with split.open_reader() as revision:
            _assert_fields(revision, corpus)
            complete = _snapshot(revision)
    with ReadStore.open(split_path, PASSPHRASE) as reopened:
        with reopened.open_reader() as revision:
            assert _snapshot(revision) == complete
    with ReadStore.create(tmp_path / "full", PASSPHRASE) as full:
        assert full.synchronize(canonical).state == "rebuilt"
        with full.open_reader() as revision:
            assert _snapshot(revision) == complete
