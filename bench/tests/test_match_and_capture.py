"""Tests for verify.match and the hash-chained capture store."""

import json

from vivabench.capture import RunStore
from vivabench.verify.match import match_amount, match_date, match_text


# ------------------------------------------------------------------ matching


def test_amount_strict_and_normalized_both_pass():
    r = match_amount("$1,234.56", "$1,234.56", "en-US", "USD")
    assert r.strict and r.normalized


def test_amount_normalized_passes_when_strict_fails():
    # Model wrote "1234.56" for printed "$1,234.56": semantically right,
    # fidelity note only.
    r = match_amount("1234.56", "$1,234.56", "en-US", "USD")
    assert not r.strict
    assert r.normalized
    assert r.correct


def test_amount_wrong_value_fails():
    r = match_amount("$1,234.65", "$1,234.56", "en-US", "USD")
    assert not r.correct
    assert "differs" in r.detail


def test_german_amount_cross_format():
    r = match_amount("1234.56", "1.234,56", "de-DE", "EUR")
    # extracted uses dot-decimal; under de-DE rules "1234.56" -> single '.' with
    # 2 trailing digits -> decimal. Equal after normalization.
    assert r.normalized


def test_unparseable_truth_flags_key_review():
    r = match_amount("100.00", "not-a-number", "en-US", "USD")
    assert r.normalized is None
    assert "key needs review" in r.detail


def test_date_cross_format_match():
    r = match_date("03/04/2025", "2025-03-04", "en-US")
    assert r.normalized and not r.strict


def test_text_match_case_whitespace():
    r = match_text("STARBUCKS  #1234", "Starbucks #1234")
    assert r.normalized and not r.strict


# ------------------------------------------------------------------- capture


def test_chain_appends_and_verifies(tmp_path):
    store = RunStore(tmp_path / "runs.jsonl")
    store.append({"doc_id": "d1", "candidate": "m1", "run_index": 1, "status": "ok", "cost_usd": 0.01})
    store.append({"doc_id": "d1", "candidate": "m1", "run_index": 2, "status": "ok", "cost_usd": 0.02})
    intact, checked = store.verify_chain()
    assert intact and checked == 2
    assert abs(store.spent_usd - 0.03) < 1e-9


def test_resume_skips_completed(tmp_path):
    path = tmp_path / "runs.jsonl"
    store = RunStore(path)
    store.append({"doc_id": "d1", "candidate": "m1", "run_index": 1, "status": "ok", "cost_usd": 0.0})
    store.append({"doc_id": "d1", "candidate": "m1", "run_index": 2, "status": "error", "cost_usd": 0.0})
    # Reload from disk, as a fresh process would.
    store2 = RunStore(path)
    assert store2.is_done("d1", "m1", 1)
    assert not store2.is_done("d1", "m1", 2)  # errors are retried


def test_tampering_breaks_the_chain(tmp_path):
    path = tmp_path / "runs.jsonl"
    store = RunStore(path)
    store.append({"doc_id": "d1", "candidate": "m1", "run_index": 1, "status": "ok", "cost_usd": 1.00})
    store.append({"doc_id": "d1", "candidate": "m1", "run_index": 2, "status": "ok", "cost_usd": 2.00})

    # Adversary edits a cost in place.
    lines = path.read_text().splitlines()
    record = json.loads(lines[0])
    record["cost_usd"] = 0.0
    lines[0] = json.dumps(record, ensure_ascii=False)
    path.write_text("\n".join(lines) + "\n")

    intact, _ = RunStore(path).verify_chain()
    assert not intact
