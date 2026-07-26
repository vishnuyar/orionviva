"""The eval's own tests — because a scorer that mis-grades is worse than none.

If this harness ever calls a fabricated split "ok", every model looks fine and
the one alarm the trust thesis rests on goes quiet. So the scorer is tested with
deliberately bad models, and the assertions are about the *ordering* of failure
severity, not just the counts.
"""

import json

from viva.eval_listen import OK, RUIN, SAFE, WEAK, WRONG, load_cases, report, run


def _model(fn):
    """A fake extract_fn: takes the sentence out of the prompt, returns JSON."""
    def extract(prompt):
        said = prompt.split("Their answer: ", 1)[1].split("\n", 1)[0]
        return json.dumps(fn(said))
    return extract


def _perfect(cases):
    """Answers every case with the key's first accepted reading."""
    by_said = {c["said"]: c for c in cases["cases"]}

    def answer(said):
        case = by_said[said]
        legs = [{"major": m, "account_hint": "x",
                 "share": "0.5" if case.get("shares_stated") else ""}
                for m in case["accept"][0]]
        return {"legs": legs, "kind": case.get("kind", "")}
    return _model(answer)


def test_a_perfect_model_scores_clean():
    cases = load_cases()
    r = run(_perfect(cases), cases)
    assert r["counts"][OK] == r["n"]
    assert r["confidently_wrong"] == 0
    assert "usable" in report(r)


def test_declining_is_safe_and_never_counted_as_confidently_wrong():
    """The asymmetry the whole harness exists to encode: silence costs a tap,
    fabrication costs the ledger's honesty."""
    cases = load_cases()
    r = run(_model(lambda said: {"legs": []}), cases)
    assert r["counts"][SAFE] == r["n"]
    assert r["confidently_wrong"] == 0        # declining is NOT an error
    assert "safe but weak" in report(r)


def test_an_invented_split_is_ruin_even_when_the_majors_are_right():
    """The failure that would put a wrong number in someone's finances: a model
    that reads the mortgage correctly and then guesses 60/40."""
    cases = load_cases()
    only = {"cases": [c for c in cases["cases"] if c["id"] == "mortgage-spelled"]}

    def guesser(said):
        return {"legs": [{"major": m, "account_hint": "x", "share": s} for m, s in
                         (("expense", "0.6"), ("liability", "0.3"), ("asset", "0.1"))]}
    r = run(_model(guesser), only)
    assert r["counts"][RUIN] == 1 and r["counts"][OK] == 0
    assert "invented a split" in r["rows"][0]["why"]
    assert "do not use this model" in report(r)


def test_an_amount_in_the_reply_is_ruin():
    cases = load_cases()
    only = {"cases": [c for c in cases["cases"] if c["id"] == "car-bought"]}
    r = run(_model(lambda said: {"legs": [{"major": "asset", "account_hint": "car",
                                           "amount": "42000.00"}]}), only)
    assert r["counts"][RUIN] == 1
    assert "emitted an amount" in r["rows"][0]["why"]


def test_a_stated_split_is_allowed_where_the_person_stated_it():
    """The mirror of the ruin test — honouring proportions a person gave is
    correct, and must not be punished."""
    cases = load_cases()
    only = {"cases": [c for c in cases["cases"] if c["id"] == "mortgage-split-stated"]}
    r = run(_model(lambda said: {"legs": [{"major": "expense", "share": "0.5"},
                                          {"major": "liability", "share": "0.5"}]}), only)
    assert r["counts"][OK] == 1


def test_collapsing_a_mortgage_is_weak_but_not_ruin():
    cases = load_cases()
    only = {"cases": [c for c in cases["cases"] if c["id"] == "mortgage-plain"]}
    r = run(_model(lambda said: {"legs": [{"major": "liability", "account_hint": "x"}]}), only)
    assert r["counts"][WRONG] == 1        # liability alone isn't in `accept` here
    only2 = {"cases": [dict(only["cases"][0], accept=[["liability"]], compound=True)]}
    r2 = run(_model(lambda said: {"legs": [{"major": "liability"}]}), only2)
    assert r2["counts"][WEAK] == 1 and r2["confidently_wrong"] == 0


def test_ambiguous_cases_accept_more_than_one_reading():
    """An ATM withdrawal is defensibly cash-you-still-have or money-spent. A key
    that insisted on one would measure obedience, not understanding."""
    cases = load_cases()
    only = {"cases": [c for c in cases["cases"] if c["id"] == "atm"]}
    for major in ("asset", "expense"):
        r = run(_model(lambda said, m=major: {"legs": [{"major": m}]}), only)
        assert r["counts"][OK] == 1, major


def test_repeat_surfaces_instability():
    """Two-out-of-three is a different product from always. A single run cannot
    tell them apart, so the harness names the cases that wobble."""
    cases = load_cases()
    only = {"cases": [c for c in cases["cases"] if c["id"] == "groceries"]}
    state = {"n": 0}

    def flaky(said):
        state["n"] += 1
        return {"legs": [{"major": "expense" if state["n"] % 2 else "income"}]}
    r = run(_model(flaky), only, repeat=4)
    assert r["unstable"] == ["groceries"]
    assert "unstable across runs" in report(r)


def test_the_key_carries_no_real_financial_data():
    """It ships in a public repo. Synthetic counterparties, no amounts, no
    account numbers, no names."""
    raw = (load_cases.__globals__["CASES"]).read_text()
    for leaked in ("chase", "amex", "wells fargo", "citi", "harborline", "servicerco"):
        assert leaked not in raw.lower()
    # Not "no digits" — "401k" is a plan type, not a value. What must never
    # appear is anything money- or account-shaped.
    import re
    money = re.compile(r"[$£€₹]|\d+\.\d{2}|\d,\d{3}|\d{4,}")
    for case in load_cases()["cases"]:
        blob = f"{case['said']} {case['descriptor']}"
        assert not money.search(blob), f"{case['id']}: {blob}"
