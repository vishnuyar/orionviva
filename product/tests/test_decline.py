""""Not now" is an answer.

The decline event extends settled → silence to the questions themselves: a
question the person set aside stays quiet — not for some arbitrary number of
days, but until NEW EVIDENCE changes what the question would say. The stake
snapshot (amount, count) is the whole policy: same stake → silence; changed
stake → the question has genuinely changed, so it may return.
"""

from decimal import Decimal

from viva.ingest import RawStore, ReadResult, StatementFacts, TxnFact, capture_and_ingest
from viva.ledger import EventStore, Ledger
from viva.questions import open_questions
from viva.vault import Vault
from viva import engine


def _stamp(f, doc_id):
    f.doc_id = doc_id
    return ReadResult(f.doc_type, 0.98, f)


def _vault(tmp_path):
    raw = RawStore.open(tmp_path / "raw", "pw")
    ledger = Ledger(EventStore.open(tmp_path / "events.jsonl", "pw"))
    return Vault(ledger=ledger, raw=raw, directory=tmp_path)


def _checking(vault, txns, opening, dates, tag):
    total = sum(Decimal(a) for _, _, a in txns)
    facts = StatementFacts(
        doc_id="", doc_type="checking_statement", doc_type_confidence=0.98,
        account_ref="Chase Total Checking", currency="USD",
        opening_amount=Decimal(opening), opening_date=dates[0],
        closing_amount=Decimal(opening) + total, closing_date=dates[1],
        transactions=[TxnFact(d, desc, Decimal(a)) for d, desc, a in txns],
        account_number="000000001122", institution="Chase")
    return capture_and_ingest(vault.raw, vault.ledger, tag,
                              lambda data, did: _stamp(facts, did),
                              captured_at="2026-05-01")


def _merchant_question(vault, needle):
    qs = open_questions(vault.ledger, limit=1000)
    return next((q for q in qs["questions"] if needle in q["text"]), None)


def test_declined_question_goes_quiet(tmp_path):
    vault = _vault(tmp_path)
    _checking(vault, [("2026-03-05", "ACME SUB SHOP", "-120.00")],
              "10000.00", ("2026-03-01", "2026-03-31"), b"chk1")
    q = _merchant_question(vault, "ACME SUB SHOP")
    assert q is not None
    before = open_questions(vault.ledger, limit=1000)["total"]

    r = engine.decline_question(vault, q["id"], "not_now")
    assert r["ok"] and r["message"], "the ack speaks — silence was the old bug"

    after = open_questions(vault.ledger, limit=1000)
    assert _merchant_question(vault, "ACME SUB SHOP") is None
    assert after["total"] == before - 1, "declined means gone, not re-ranked"


def test_declined_question_returns_on_new_evidence(tmp_path):
    """The snapshot rule: silence while the stake is unchanged, return the
    moment a new statement moves it. No timers anywhere."""
    vault = _vault(tmp_path)
    _checking(vault, [("2026-03-05", "ACME SUB SHOP", "-120.00")],
              "10000.00", ("2026-03-01", "2026-03-31"), b"chk1")
    q = _merchant_question(vault, "ACME SUB SHOP")
    engine.decline_question(vault, q["id"], "not_now")
    assert _merchant_question(vault, "ACME SUB SHOP") is None

    # A second statement, continuing the balance chain, adds another ACME
    # transaction — the stake (count and amount) changes.
    _checking(vault, [("2026-04-10", "ACME SUB SHOP", "-80.00")],
              "9880.00", ("2026-04-01", "2026-04-30"), b"chk2")
    back = _merchant_question(vault, "ACME SUB SHOP")
    assert back is not None, "new evidence must bring the question back"
    assert back["count"] == 2


def test_dont_know_is_recorded_with_its_reason(tmp_path):
    """"I don't know" and "not now" are different moments in the relationship —
    the ledger keeps which one it was."""
    vault = _vault(tmp_path)
    _checking(vault, [("2026-03-05", "ACME SUB SHOP", "-120.00")],
              "10000.00", ("2026-03-01", "2026-03-31"), b"chk1")
    q = _merchant_question(vault, "ACME SUB SHOP")
    r = engine.decline_question(vault, q["id"], "dont_know")
    assert r["ok"]
    declined = vault.ledger.projection().declined_questions()
    assert declined[q["id"]]["reason"] == "dont_know"
    assert declined[q["id"]]["pack_version"], "the voice that asked is recorded"


def test_declining_a_question_that_is_not_open_is_a_said_no_op(tmp_path):
    vault = _vault(tmp_path)
    r = engine.decline_question(vault, "merchant:nothing-here", "not_now")
    assert r["ok"] is False and "no longer open" in r["message"]
    assert vault.ledger.projection().declined_questions() == {}
