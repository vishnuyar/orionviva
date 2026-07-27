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


def test_a_broken_pipe_is_never_reported_as_a_clean_result():
    """A run whose every call fails before reaching the model must not report as
    clean. An eval that cannot tell a declining model from a broken connection
    is worse than no eval, because it is *reassuring*. So: BROKEN is its own
    verdict, it is excluded from the denominator, and the confidently-wrong rate
    becomes None rather than zero — an unknown rate is not a good one."""
    from viva.eval_listen import BROKEN

    cases = load_cases()

    def dead(prompt):
        raise ConnectionError("model 'qwen3:4b' not found, try pulling it first")

    r = run(dead, cases)
    assert r["counts"][BROKEN] == r["n"]
    assert r["counts"][SAFE] == 0             # NOT laundered into the safe bucket
    assert r["scored"] == 0
    assert r["confidently_wrong"] is None     # unknown, not zero

    text = report(r)
    assert "NOTHING WAS MEASURED" in text
    assert "not found" in text                # the actual cause, surfaced
    assert "ollama list" in text              # and what to do about it
    for misleading in ("clean", "safe but weak", "usable", "VERDICT: do not use"):
        assert misleading not in text


def test_a_partly_broken_run_scores_only_what_it_measured():
    """Half a run is not a result either — say so rather than quietly averaging."""
    from viva.eval_listen import BROKEN

    cases = load_cases()
    state = {"n": 0}

    def flaky(prompt):
        state["n"] += 1
        if state["n"] % 2:
            raise ConnectionError("connection reset")
        return json.dumps({"legs": [{"major": "expense"}]})

    r = run(flaky, cases)
    assert 0 < r["counts"][BROKEN] < r["n"]
    assert r["scored"] == r["n"] - r["counts"][BROKEN]
    assert "never reached the model" in report(r)
    assert "Fix the connection" in report(r)


def test_a_declining_model_is_still_distinguished_from_a_broken_one():
    """Both produce no legs. They mean opposite things."""
    from viva.eval_listen import BROKEN

    cases = load_cases()
    declined = run(_model(lambda said: {"legs": []}), cases)
    assert declined["counts"][SAFE] == declined["n"]
    assert declined["counts"][BROKEN] == 0
    assert declined["confidently_wrong"] == 0     # measured, and genuinely zero


# ------------------------------------------ implications: the new ruin case


def test_inventing_structure_where_none_exists_is_the_new_ruin():
    """Inventing structure is the invented split's equivalent, and worse.

    A fabricated ratio corrupts one payment. A fabricated IMPLICATION — deciding
    a coffee shop means a loan — creates an account nobody has, applies it to
    every transaction with that counterparty, and propagates into every vault
    that ever syncs the record. So `[]` must be the easy answer, and anything
    outside the closed vocabulary is dropped rather than trusted."""
    from merchantcore.enrich import clean_implications

    # Silence is a first-class, correct answer — not a parse failure.
    assert clean_implications(None) == []
    assert clean_implications([]) == []
    assert clean_implications("nope") == []
    assert clean_implications([{"relationship": "a loan"}]) == []   # no major → gone

    # A major outside the four is dropped, not coerced into the nearest one.
    for bad in ("equity", "spending", "", "assets", "liability payment"):
        assert clean_implications([{"major": bad, "relationship": "x"}]) == [], bad
    # Whitespace and case ARE tolerated — that is transport noise, not a claim.
    assert clean_implications([{"major": " Asset "}])[0]["major"] == "asset"

    good = clean_implications([{
        "relationship": "a home loan", "major": "liability", "on": "outflow",
        "account_group": "Mortgage", "compound": True, "confidence": "forced",
        "documents": "1098", "ask": "Set it up?"}])
    assert good[0]["major"] == "liability" and good[0]["confidence"] == "forced"


def test_an_unreadable_confidence_or_direction_degrades_to_the_cautious_value():
    """Unrecognised input must land on the side that ASKS, never the side that
    acts. `suggested` proposes; `forced` applies — so an unknown value becoming
    `forced` would let a garbled reply change a ledger unprompted."""
    from merchantcore.enrich import clean_implications

    (row,) = clean_implications([{"major": "asset", "confidence": "definitely",
                                  "on": "sideways"}])
    assert row["confidence"] == "suggested"      # ask, don't act
    assert row["on"] == "both"                   # apply to neither direction blindly


def test_the_enrichment_prompt_makes_silence_the_default():
    """The prompt is where the ruin case is actually prevented. If it does not
    say plainly that MOST merchants imply nothing, a helpful model will invent
    relationships to be useful."""
    from merchantcore.enrich import _PROMPT

    # Collapse wrapping: the prompt is hand-wrapped prose, and a phrase split
    # across two lines is still the same instruction to a model.
    low = " ".join(_PROMPT.lower().split())
    assert "almost always the answer is nothing" in low
    assert "correct and expected answer" in low
    assert "far worse than saying nothing" in low
    # And direction is stated as the crux, not an afterthought.
    assert "money going out to a lender repays borrowing" in low
