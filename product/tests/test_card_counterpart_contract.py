"""Synthetic checks of counterpart dispatch, contract retirement and source numbers."""
import hashlib
import json
from types import SimpleNamespace

import pytest

from viva import accounting_intelligence as intelligence
from viva.ledger import EventStore, Ledger
from viva.ledger.accounting import financial_statements
from viva.ledger.events import (Posting, Provenance, account_opened,
                               closing_balance_observed, opening_balance_observed,
                               document_captured, read_recorded,
                               merchant_enriched, ruling_recorded,
                               transaction_recorded)
from vivacore import versions


def card_vault(tmp_path, count=2):
    ledger = Ledger(EventStore.open(tmp_path / "events", "synthetic"))
    account = "Liabilities:Cards:Synthetic"
    ledger.append(account_opened(account, "liability", "Synthetic Card", "CAD", "2026-01-01"))
    ledger.append(document_captured("synthetic-doc", "synthetic.txt", 1, "credit_card_statement",
                                   0.98, "2026-02-01"))
    ledger.append(read_recorded(doc_id="synthetic-doc", model="synthetic", prompt_version="synthetic",
        input_mode="text", response_text=json.dumps({"doc_type": "credit_card_statement",
            "opening": {"date_raw": "2026-01-01", "amount_raw": "0"},
            "closing": {"date_raw": "2026-01-31", "amount_raw": str(11 + 15 * (count - 1))}}),
        cost_usd=0, input_tokens=0, output_tokens=0,
        parse_ok=True, parse_error=None, occurred_at="2026-02-01"))
    ledger.append(opening_balance_observed(account, "0", "2026-01-01",
                                          provenance=Provenance("synthetic-doc")))
    for index in range(count):
        amount = "11.00" if index == 0 else "15.00"
        ledger.append(transaction_recorded([
            Posting(account, amount, grade="verified"),
            Posting("Expenses:Uncategorized", "-" + amount, grade="verified")],
            "SYNTHETIC GROCER", f"2026-01-{index + 2:02d}",
            provenance=Provenance("synthetic-doc", 1)))
    ledger.append(closing_balance_observed(account, str(11 + 15 * (count - 1)),
                                          "2026-01-31",
                                          provenance=Provenance("synthetic-doc")))
    proj = ledger.projection()
    ledger.append(merchant_enriched(proj.merchant_key_of(proj.movements()[0]), "groceries",
                                   subcategory="supermarket", occurred_at="2026-02-01"))
    return SimpleNamespace(ledger=ledger)


def old_compound(v, *, version="accounting-interpret-v2", by="model", grade="unverified",
                 majors=("expense", "liability"), shares=None):
    for movement in v.ledger.projection().movements():
        context = intelligence._envelope(v.ledger.projection(), [movement])["movements"][0]
        signature = hashlib.sha256(json.dumps({"context": context, "version": version},
                                             sort_keys=True).encode()).hexdigest()
        accounts = {"expense": "Expenses:Uncategorized", "liability": "Liabilities:Uncategorized",
                    "asset": "Assets:Uncategorized"}
        v.ledger.append(ruling_recorded("movement", movement.key, "2026-02-01",
            legs=[{"major": major, "account": accounts[major],
                   "share": shares[index] if shares else ""} for index, major in enumerate(majors)],
            by=by, grade=grade, prompt_version=version, evidence_signature=signature,
            source_refs=["old-raw-claim"], provenance=Provenance("old-raw-claim")))


def expenses(v):
    return financial_statements(v.ledger.projection())["profit_loss"]


def test_older_compound_restores_before_unavailable_reread(tmp_path, monkeypatch):
    v = card_vault(tmp_path)
    before = list(v.ledger.store.snapshot_events())
    old_compound(v)
    assert len(expenses(v)["unresolved_components"]) == 2
    def unavailable():
        assert not v.ledger.projection().rulings("movement")
        assert expenses(v)["by_currency"]["CAD"]["expenses"] == "26.00"
        return None
    monkeypatch.setattr(intelligence, "_configured_extractor", unavailable)
    result = intelligence.interpret_activity(v)
    assert result["status"] == "not_configured"
    assert not v.ledger.projection().rulings("movement")
    assert expenses(v)["by_currency"]["CAD"]["expenses"] == "26.00"
    assert list(v.ledger.store.snapshot_events())[:len(before)] == before
    assert v.ledger.fresh_projection().movements() == v.ledger.projection().movements()


@pytest.mark.parametrize("response", ["omitted", "malformed", "failure", "invalid"])
def test_retired_compound_stays_restored_after_unsuccessful_reread(tmp_path, response):
    v = card_vault(tmp_path)
    old_compound(v)
    original = list(v.ledger.store.snapshot_events())
    def read(prompt):
        assert not v.ledger.projection().rulings("movement")
        if response == "failure":
            raise RuntimeError("synthetic unavailable")
        return {"omitted": '{"interpretations": []}', "malformed": "{",
                "invalid": '{"interpretations": [{"ref":"m0","majors":["expense"],"grounds":"x","amount":"11"}]}'}[response]
    result = intelligence.interpret_activity(v, extract_fn=read)
    assert result["applied"] == 0
    assert result["status"] == ("completed" if response == "omitted" else "failed")
    assert not v.ledger.projection().rulings("movement")
    assert expenses(v)["by_currency"]["CAD"]["expenses"] == "26.00"
    events = list(v.ledger.store.snapshot_events())
    assert events[:len(original)] == original
    assert sum(e.event_type == "AccountingTreatmentRestored" for e in events) == 2
    assert events[-1].event_type == "ReadRecorded"
    assert v.ledger.fresh_projection().rulings("movement") == []
    reopened = Ledger(EventStore.open(v.ledger.store.path, "synthetic"))
    assert reopened.projection().movements() == v.ledger.projection().movements()


@pytest.mark.parametrize("majors", [("expense",), ("asset",), ("liability",),
                                   ("expense", "liability"), ("liability", "expense"),
                                   ("expense", "expense")])
def test_new_contract_preserves_provisional_inference_without_context_gate(tmp_path, majors):
    v = card_vault(tmp_path)
    old_compound(v)
    prompts = []
    raw = json.dumps({"interpretations": [
        {"ref": f"m{i}", "majors": list(majors), "grounds": "Synthetic inference."}
        for i in range(2)]})
    def read(prompt):
        assert not v.ledger.projection().rulings("movement")
        prompts.append(prompt)
        return raw
    result = intelligence.interpret_activity(v, extract_fn=read)
    assert result["status"] == "completed" and result["applied"] == 2
    assert '"compound": false' in prompts[0] and '"implied_major": ""' in prompts[0]
    assert "counterpart treatment" in prompts[0]
    rulings = v.ledger.projection().rulings("movement")
    assert all(r["prompt_version"] == "accounting-interpret-v3" for r in rulings)
    assert all(tuple(leg["major"] for leg in r["legs"]) == majors for r in rulings)
    claims = [e for e in v.ledger.store.snapshot_events() if e.event_type == "ReadRecorded"]
    assert json.loads(claims[-1].body["response_text"])["text"] == raw
    assert all(claims[-1].body["doc_id"] in r["source_refs"] for r in rulings)
    again = intelligence.interpret_activity(v, extract_fn=lambda _: pytest.fail("unchanged v3 reread"))
    assert again["status"] == "local_evidence" and again["applied"] == 0
    assert v.ledger.projection().rulings("movement") == rulings
    if len(majors) > 1:
        assert len(expenses(v)["unresolved_components"]) == 2
    elif majors[0] == "expense":
        assert expenses(v)["by_currency"]["CAD"]["expenses"] == "26.00"


@pytest.mark.parametrize("options", [
    {"by": "human"}, {"by": "human_rule"}, {"by": "document"},
    {"by": "merchant_prior"}, {"grade": "verified"},
    {"shares": ("0.8", "0.2")}, {"majors": ("asset",)},
    {"majors": ("liability",)}, {"version": "accounting-interpret-v3"},
    {"version": ""},
])
def test_contract_retirement_preserves_protected_treatments(tmp_path, monkeypatch, options):
    v = card_vault(tmp_path)
    old_compound(v, **options)
    before = v.ledger.projection().rulings("movement")
    monkeypatch.setattr(intelligence, "_configured_extractor", lambda: None)
    intelligence.interpret_activity(v)
    assert v.ledger.projection().rulings("movement") == before
    assert not any(e.event_type == "AccountingTreatmentRestored" for e in v.ledger.store.snapshot_events())


@pytest.mark.parametrize("scope,by,grade,majors,shares,inferred", [
    ("movement", "model", "unverified", ("expense",), None, True),
    ("movement", "model", "unverified", ("expense", "liability"), None, True),
    ("merchant", "merchant_prior", "unverified", ("expense", "liability"), None, True),
    ("movement", "human", "verified", ("expense", "liability"), None, False),
    ("merchant", "human", "verified", ("expense", "liability"), None, False),
    ("movement", "model", "verified", ("expense", "liability"), None, False),
    ("movement", "human", "verified", ("expense", "liability"), ("0.8", "0.2"), False),
])
def test_activity_inference_copy_has_canonical_current_and_historical_parity(
        tmp_path, scope, by, grade, majors, shares, inferred):
    from viva.read_store.store import ReadStore
    from viva.surface.activity import activity
    from viva.persona import moment
    v = card_vault(tmp_path, count=1)
    baseline = v.ledger.projection()
    original_grades = baseline.movement_grades()
    original_balance = baseline.balance("Liabilities:Cards:Synthetic")
    movement = baseline.movements()[0]
    subject = movement.key if scope == "movement" else baseline.merchant_key_of(movement)
    accounts = {"expense": "Expenses:Uncategorized", "liability": "Liabilities:Uncategorized"}
    v.ledger.append(ruling_recorded(scope, subject, "2026-02-01",
        legs=[{"major": major, "account": accounts[major],
               "share": shares[index] if shares else ""} for index, major in enumerate(majors)],
        by=by, grade=grade))
    canonical = v.ledger.projection()
    expected = activity(canonical, "en-US")
    key = ("activity_inferred_expense" if len(majors) == 1 else
           "activity_inferred_compound" if inferred else "activity_unsettled")
    assert expected["items"][0]["sentence"] == moment(key)
    assert expected["items"][0]["sentence"].startswith("Inferred") is inferred
    report = financial_statements(canonical)
    with ReadStore.create(tmp_path / "reads", "synthetic") as reads:
        reads.synchronize(v.ledger.store)
        with reads.open_reader() as revision:
            assert activity(revision.activity_projection(), "en-US") == expected
            assert activity(revision.historical_activity_projection(as_of="2026-02-01"), "en-US") == expected
            assert financial_statements(revision.overview_projection(today="2026-02-01")) == report
    assert canonical.movement_grades() == original_grades
    assert canonical.balance("Liabilities:Cards:Synthetic") == original_balance


def test_retirement_refreshes_baseline_for_omitted_and_deferred_rows(tmp_path, monkeypatch):
    v = card_vault(tmp_path, count=3)
    old_compound(v)
    monkeypatch.setattr(intelligence, "MAX_ITEMS", 1)
    result = intelligence.interpret_activity(v, extract_fn=lambda _: '{"interpretations": []}')
    assert result["deferred"] == 2 and result["applied"] == 0
    assert expenses(v)["by_currency"]["CAD"]["expenses"] == "41.00"
    assert not v.ledger.projection().rulings("movement")


def test_new_prompt_and_persona_are_active_with_original_versions_intact():
    assert versions.active(intelligence.PACKAGE, "accounting_interpret") == "accounting-interpret-v3"
    assert versions.active(intelligence.PACKAGE, "persona_pack") == "pack-v53"
    for name in ("accounting-interpret-v1", "accounting-interpret-v2", "pack-v50", "pack-v51"):
        assert versions.fingerprint(versions.path_of(intelligence.PACKAGE, name)) == versions.pin(intelligence.PACKAGE, name)


def test_old_single_signature_dispatches_new_prompt_without_retiring_treatment(tmp_path):
    v = card_vault(tmp_path)
    old_compound(v, majors=("asset",))
    before = v.ledger.projection().rulings("movement")
    calls = []
    def read(prompt):
        assert v.ledger.projection().rulings("movement") == before
        calls.append(prompt)
        return '{"interpretations": []}'
    result = intelligence.interpret_activity(v, extract_fn=read)
    assert len(calls) == 1 and result["status"] == "completed"
    assert not any(e.event_type == "AccountingTreatmentRestored" for e in v.ledger.store.snapshot_events())
    assert v.ledger.projection().rulings("movement") == before


def test_mixed_batch_keeps_inferred_compound_and_single_treatment_separate(tmp_path):
    v = card_vault(tmp_path)
    result = intelligence.interpret_activity(v, extract_fn=lambda _: json.dumps({"interpretations": [
        {"ref": "m0", "majors": ["expense"], "grounds": "Purchase"},
        {"ref": "m1", "majors": ["asset", "expense"], "grounds": "Inferred compound"}]}))
    assert result["applied"] == 2
    report = expenses(v)
    assert report["by_currency"]["CAD"]["expenses"] == "11.00"
    assert len(report["unresolved_components"]) == 1
    assert report["unresolved_components"][0]["amount"] == "15.00"


def test_restoration_reporting_and_spending_match_encrypted_reads_after_correction_undo(tmp_path, monkeypatch):
    from viva.accounting_intelligence import undo_accounting
    from viva.engine import record_ruling
    from viva.listen import Interpretation
    from viva.read_store import ReadStore
    from viva.surface.spending import spending_breakdown
    v = card_vault(tmp_path)
    original_movements = v.ledger.projection().movements()
    original_grades = v.ledger.projection().movement_grades()
    original_balance = v.ledger.projection().balance("Liabilities:Cards:Synthetic")
    old_compound(v)
    monkeypatch.setattr(intelligence, "_configured_extractor", lambda: None)
    intelligence.interpret_activity(v)
    with ReadStore.create(tmp_path / "reads", "synthetic") as reads:
        def parity():
            canonical = v.ledger.projection()
            report = financial_statements(canonical, start="2026-01-02", end="2026-01-03")
            chart = spending_breakdown(canonical, "en-US", "2026-02-01")
            reads.synchronize(v.ledger.store)
            with reads.open_reader() as revision:
                assert financial_statements(revision.overview_projection(today="2026-02-01"),
                    start="2026-01-02", end="2026-01-03") == report
                assert spending_breakdown(revision.spending_projection(today="2026-02-01", locale="en-US"),
                    "en-US", "2026-02-01") == chart
            assert canonical.movement_grades() == original_grades
            assert canonical.balance("Liabilities:Cards:Synthetic") == original_balance
            return report, chart
        baseline, chart = parity()
        assert chart["sections"][0]["total_display"] == "CAD 26.00"
        assert baseline["profit_loss"]["by_currency"]["CAD"]["provisional_expenses"] == "26.00"
        movement = v.ledger.projection().movements()[0]
        correction = record_ruling(v, Interpretation(legs=[{"major": "asset", "account_hint": "Equipment"}],
            said="This one was equipment", future_scope="one"), movement.description, movement_key=movement.key)
        corrected, chart = parity()
        assert chart["sections"][0]["total_display"] == "CAD 15.00"
        assert corrected["profit_loss"]["by_currency"]["CAD"]["expenses"] == "15.00"
        undo_accounting(v, correction["correction_id"])
        assert parity()[0] == baseline
    assert v.ledger.projection().movements() == original_movements
