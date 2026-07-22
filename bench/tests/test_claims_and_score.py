"""Tests for claim parsing, answer-key freeze/hash, and the scorer."""

import json

from vivacore.claims import AnswerKey, KeyEntry, parse_claims
from vivabench.score import grade_run, build_scorecards


# ------------------------------------------------------------ claim parsing


def _wrap(claims):
    return json.dumps({"claims": claims})


def test_parse_plain_json():
    out = _wrap([{"type": "amount", "label": "closing balance",
                  "value_raw": "$1,234.56", "confidence": 0.9, "page": 1}])
    claims, err = parse_claims(out)
    assert err is None and len(claims) == 1
    assert claims[0].value_raw == "$1,234.56"


def test_parse_fenced_json_with_prose():
    out = "Here is what I found:\n```json\n" + _wrap(
        [{"type": "date", "label": "statement date", "value_raw": "2026-01-31"}]
    ) + "\n```\nHope that helps."
    claims, err = parse_claims(out)
    assert err is None and claims[0].type == "date"


def test_parse_rejects_unknown_type():
    out = _wrap([{"type": "nonsense", "label": "x", "value_raw": "1"}])
    claims, err = parse_claims(out)
    assert err is None and claims == []


def test_parse_failure_is_data_not_exception():
    claims, err = parse_claims("the model refused and wrote only prose")
    assert claims == [] and err is not None


# ------------------------------------------------------------ key freeze/hash


def _key():
    return AnswerKey(
        doc_id="d1", doc_sha256="abc", locale="en-US", currency="USD",
        entries=[
            KeyEntry("amount", "closing balance", "$1,234.56", "en-US", "USD"),
            KeyEntry("date", "statement date", "2026-01-31", "en-US"),
        ],
    )


def test_hash_is_order_independent():
    k1 = _key()
    k2 = _key()
    k2.entries.reverse()
    assert k1.canonical_hash() == k2.canonical_hash()


def test_hash_changes_with_content():
    k1 = _key()
    k2 = _key()
    k2.entries[0] = KeyEntry("amount", "closing balance", "$1,234.57", "en-US", "USD")
    assert k1.canonical_hash() != k2.canonical_hash()


def test_roundtrip_dict():
    k = _key()
    k2 = AnswerKey.from_dict(json.loads(json.dumps(k.to_dict())))
    assert k2.canonical_hash() == k.canonical_hash()


# ------------------------------------------------------------ scoring


def test_grade_perfect_run():
    key = _key()
    out = _wrap([
        {"type": "amount", "label": "closing balance", "value_raw": "$1,234.56", "confidence": 0.95},
        {"type": "date", "label": "statement date", "value_raw": "2026-01-31", "confidence": 0.9},
    ])
    g = grade_run("d1", "m1", 1, out, key)
    assert g.parse_ok and g.n_correct == 2 and not g.missed
    assert g.accuracy == 1.0 and g.recall == 1.0


def test_grade_normalized_match_counts_correct():
    key = _key()
    # "1234.56" (no symbol/commas) is semantically the closing balance.
    out = _wrap([{"type": "amount", "label": "Closing Balance", "value_raw": "1234.56"}])
    g = grade_run("d1", "m1", 1, out, key)
    correct = [x for x in g.grades if x.matched]
    assert len(correct) == 1 and not correct[0].strict  # right value, not char-exact


def test_grade_catches_silent_omission():
    key = _key()
    out = _wrap([{"type": "amount", "label": "closing balance", "value_raw": "$1,234.56"}])
    g = grade_run("d1", "m1", 1, out, key)
    assert "statement date" in g.missed
    assert g.recall == 0.5


def test_grade_wrong_value_not_counted():
    key = _key()
    out = _wrap([{"type": "amount", "label": "closing balance", "value_raw": "$9,999.99"}])
    g = grade_run("d1", "m1", 1, out, key)
    assert g.n_correct == 0


def test_parse_fail_run_scores_zero_recall():
    key = _key()
    g = grade_run("d1", "m1", 1, "prose only", key)
    assert not g.parse_ok and g.recall == 0.0 and len(g.missed) == 2


def test_scorecards_group_and_calibrate():
    key = _key()
    runs = []
    # A model that is right but claims 0.5 confidence -> underconfident (ECE > 0).
    for i in range(1, 6):
        out = _wrap([
            {"type": "amount", "label": "closing balance", "value_raw": "$1,234.56", "confidence": 0.5},
            {"type": "date", "label": "statement date", "value_raw": "2026-01-31", "confidence": 0.5},
        ])
        runs.append(grade_run("d1", "m1", i, out, key))
    cards = build_scorecards(runs, {"d1": "combined_bank_statement"}, {"d1": "en-US"})
    assert len(cards) == 1
    c = cards[0]
    assert c.candidate == "m1" and c.doc_type == "combined_bank_statement"
    assert c.accuracy == 1.0 and c.recall == 1.0
    assert c.self_consistency == 1.0          # unanimous across runs
    assert c.ece is not None and c.ece > 0.3   # said 50%, was 100% -> badly calibrated
    assert c.system_confidently_wrong == 0.0
