"""The answer-key scorer, and the failures it must not manufacture.

`diff_rulings` asks the only question that matters about the implication work:
**does Viva now propose what the person previously had to type by hand?**
CONTRADICTED is reserved for the one dangerous failure, "the product confidently
disagrees with its user", and is printed under READ THESE FIRST.

A spending CATEGORY and a structural RELATIONSHIP are different axes, and a
counterparty is routinely *both things at once*: a car maker's ACH is transport
spending AND a car loan; a wire is a down payment AND a property purchase.
Comparing across axes manufactures disagreement out of agreement, so those pairs
are INCOMPARABLE. Nothing will ever imply anything about a cash withdrawal, so
that is UNKNOWABLE rather than a miss — it grades the design, not the build.

So these tests exist to keep an instrument honest: **graceful degradation
belongs in the product, never in the thing that measures it** — and a
measurement that errs toward *accusation* is not the safe kind of wrong.
"""

from collections import Counter

from viva.diff_rulings import (ANTICIPATED, CONTRADICTED, INCOMPARABLE, MISSED,
                               PROPOSED, UNKNOWABLE, _verdict, report, score)

from test_tiers import LOAN_OUT, _enrich, _vault


def _ruling(subject, **body):
    return {"event_type": "RulingRecorded", "body": {"subject": subject, **body}}


def _verdicts(rows):
    return {r["subject"]: r["verdict"] for r in rows}


LENDER = "NORTHWIND MOTORS NW MOTO PPD ID"
ATM = "ATM WITHDRAWAL 03 15 MAIN ST ANYTOWN TX"
BUSINESS = "BRIGHTPATH TUTORING SALE WEB ID"


def _projection(tmp_path):
    ledger = _vault(tmp_path, [("2026-03-05", LENDER, "-1200.00"),
                               ("2026-03-15", ATM, "-300.00"),
                               ("2026-03-20", BUSINESS, "-150.00")])
    # A lender that implies a loan, a cash machine that implies nothing and
    # never can, and a business we know the category of but have taught no
    # implication for.
    _enrich(ledger, "northwind motors nw moto ppd id", "loan_payments", LOAN_OUT,
            sub="auto")
    _enrich(ledger, "atm withdrawal 03 15 main st anytown tx", "cash",
            kind="instrument")
    _enrich(ledger, "brightpath tutoring sale web id", "services")
    return ledger.projection()


def test_a_category_answer_is_not_a_contradiction_of_a_relationship(tmp_path):
    """The car-loan case. Both statements are true, so neither refutes the other."""
    proj = _projection(tmp_path)
    rows = score(proj, [_ruling(LENDER,
                                category="transport")])
    assert _verdicts(rows)["northwind motors nw moto ppd id"] == INCOMPARABLE


def test_a_major_answer_that_agrees_is_anticipated(tmp_path):
    """Same axis, same conclusion — this is what the work was actually for."""
    proj = _projection(tmp_path)
    rows = score(proj, [_ruling(LENDER,
                                legs=[{"major": "liability"}])])
    assert _verdicts(rows)["northwind motors nw moto ppd id"] == ANTICIPATED


def test_a_major_answer_that_disagrees_is_still_contradicted(tmp_path):
    """The alarm must keep working. Same axis, different answer: say so loudly."""
    proj = _projection(tmp_path)
    rows = score(proj, [_ruling(LENDER,
                                legs=[{"major": "asset"}])])
    assert _verdicts(rows)["northwind motors nw moto ppd id"] == CONTRADICTED


def test_a_peer_or_instrument_is_unknowable_not_missed(tmp_path):
    """Sending a cash withdrawal to the commons is forbidden, so enrichment can
    never see it and no implication can ever exist. Silence is the design."""
    proj = _projection(tmp_path)
    rows = score(proj, [_ruling(ATM,
                                category="transfers")])
    verdict = _verdicts(rows)["atm withdrawal 03 15 main st anytown tx"]
    assert verdict == UNKNOWABLE, "an ATM withdrawal is not a miss, it is unknowable"


def test_a_business_we_have_not_learned_yet_is_still_a_miss(tmp_path):
    """The honest to-do must survive. A shareable business with no implication
    is a genuine gap in world knowledge, and the list of them is the value."""
    proj = _projection(tmp_path)
    rows = score(proj, [_ruling(BUSINESS,
                                category="services")])
    assert _verdicts(rows)["brightpath tutoring sale web id"] == MISSED


def test_the_score_counts_only_what_could_have_been_anticipated():
    """A denominator holding un-anticipatable things measures the design."""
    counts = Counter({ANTICIPATED: 3, MISSED: 1,
                      UNKNOWABLE: 12, INCOMPARABLE: 4})
    text = _verdict(counts, sum(counts.values()))
    assert "75%" in text, text          # 3 of 4 scorable, not 3 of 20
    assert "doing its job" in text


def test_the_report_names_why_something_was_not_scored():
    """An excluded row must say why, or the exclusion is just a smaller number."""
    rows = [{"verdict": UNKNOWABLE, "subject": "check # 1201", "yours": "expense",
             "viva": "", "type": "RulingRecorded"},
            {"verdict": INCOMPARABLE, "subject": "northwind motors", "yours": "category:transport",
             "viva": "auto loan", "type": "RulingRecorded"}]
    text = report(rows)
    assert "different axes" in text
    assert "correctly silent" in text
    assert "READ THESE FIRST" not in text, "nothing here is a contradiction"


def test_one_subject_ruled_twice_is_not_graded_on_two_axes(tmp_path):
    """A subject carrying two rulings must not appear in BOTH the CONTRADICTED
    and the ANTICIPATED list, which is what happens when each ruling is compared
    against the same implication on a different axis."""
    proj = _projection(tmp_path)
    rows = score(proj, [_ruling(LENDER,
                                category="transport"),
                        _ruling(LENDER,
                                legs=[{"major": "liability"}])])
    verdicts = sorted(r["verdict"] for r in rows)
    assert verdicts == sorted([INCOMPARABLE, ANTICIPATED])
    assert CONTRADICTED not in verdicts
