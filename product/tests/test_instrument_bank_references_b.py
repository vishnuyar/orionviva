"""Printed counterpart identity survives capture, posting and durable replay."""
import json

from viva.ingest import RawStore, ReadResult, capture_and_ingest
from viva.ingest.statement import StatementFacts, from_model_json
from viva.ledger import EventStore, Ledger, LedgerProjection
from viva.ledger.instruments import reference_accounts


def reply():
    return json.dumps({"doc_type": "checking_statement", "doc_type_confidence": 1,
        "institution": "Fixture Bank", "account_ref": "Fixture Checking", "account_names": ["Synthetic Person"],
        "source_account_ref": "CHECK-A", "source_account_ref_page": 2,
        "opening": {"amount_raw": "1000", "date_raw": "2021-01-01", "page": 1},
        "closing": {"amount_raw": "400", "date_raw": "2021-01-31", "page": 1},
        "transactions": [{"amount_raw": "600", "balance_effect": "decrease", "date_raw": "2021-01-15", "page": 2,
            "description": "Loan installment", "source_reference": "PAY-A", "counterparty_reference": "LOAN-A"}]})


def test_statement_roundtrip_preserves_explicit_references():
    facts, error = from_model_json(reply(), "doc", "en-US", "USD")
    assert error is None
    reread = StatementFacts.from_dict(facts.to_dict())
    assert reread.source_account_ref == "CHECK-A"
    assert reread.source_account_ref_page == 2
    assert reread.transactions[0].source_reference == "PAY-A"
    assert reread.transactions[0].counterparty_reference == "LOAN-A"


def test_posted_bank_movement_and_account_reference_are_retained_on_replay(tmp_path):
    raw = RawStore.open(tmp_path / "raw", "synthetic-test")
    ledger = Ledger(EventStore.open(tmp_path / "events.jsonl", "synthetic-test"))
    def read(data, doc_id):
        facts, error = from_model_json(reply(), doc_id, "en-US", "USD")
        assert error is None
        return ReadResult("checking_statement", 1, facts)
    result = capture_and_ingest(raw, ledger, b"synthetic bank ref fixture", read)
    assert result.action == "posted"
    for projection in (ledger.projection(), LedgerProjection(ledger.events())):
        assert reference_accounts(projection, "CHECK-A") == (result.account,)
        refs = projection.core._instrument_bank_references
        assert ("PAY-A", "LOAN-A") in refs.values()


def test_reference_fields_never_coerce_forged_model_types():
    data = json.loads(reply())
    data["transactions"][0]["source_reference"] = {"pretend": "PAY-A"}
    facts, error = from_model_json(json.dumps(data), "doc", "en-US", "USD")
    assert facts is None and "source_reference" in error
