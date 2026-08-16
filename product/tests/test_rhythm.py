"""What kind of arrangement is this — the first hypothesis Viva forms.

Two things meet, and each does one half of the work. The catalog's billing
model is impersonal world knowledge, and all it may do is license a question.
The ledger's own measurement is the only thing that may claim a cadence, and
where there is not enough of it, nothing claims one.

So these tests assert the difference between what was counted and what is
merely supposed, and that the queue can be driven to empty on this axis: a
question answered is a question that does not come back.
"""

import types
from decimal import Decimal

import pytest
from merchantcore.enrich import (BILLING_PERIODS, BILLINGS, KIND_BUSINESS,
                                 KIND_INSTRUMENT, KIND_PEER, KINDS)
from merchantcore.profile import Profile, Template
from viva import persona
from viva.engine import _write_answer, record_rhythm
from viva.ledger import EventStore, Ledger, account_opened, simple_transaction
from viva.ledger.events import (CORROBORATED, PERIODICITIES, SCOPE_ATTRIBUTE,
                                SCOPE_RHYTHM, UNVERIFIED, VERIFIED,
                                merchant_enriched, ruling_recorded)
from viva.ledger.merchant_keys import resolve_keys
from viva.ledger.projection import LedgerProjection
from viva.ledger.projection import rhythm as rhythm_read
from viva.ledger.streams import MIN_FOR_CADENCE, Flow, Occurrence, _as_date
from viva.persona import say
from viva.questions import (RHYTHM, find_question, open_questions,
                            pending_questions)
from viva.render import count as render_count
from viva.render import money as render_money
from viva.reply import Reply

# A synthetic card grammar, so a brand key and a descriptor key can differ the
# way they do once a grammar has been induced for an institution.
GRAMMAR = Profile("northbank", "depository", "v1", [
    Template("CARD PURCHASE {date} {brand} {city} {region}"),
])
NOISY = "CARD PURCHASE 03/05 LUMEN STREAMING PLANO TX"
# The same brand written a second way, because one brand covers as many
# descriptors as there are places its name was printed.
ALSO_NOISY = "CARD PURCHASE 04/12 LUMEN STREAMING AUSTIN TX"
BRAND = "lumen streaming"


def _resolver(grammar=GRAMMAR):
    return lambda rows: resolve_keys(rows, profile_for=lambda i, k: grammar)


# The two accounts these fixtures post to, and the kind of each. A purchase on
# the card account posts positive, because what is owed grew.
ACCOUNT_KINDS = {"chk": "depository", "card": "liability"}


def _events(txns, currency="USD"):
    """The ledger a fixture describes: the accounts it posts to, then its
    movements.

    A txn is `(when, description, amount)`, or `(when, description, amount,
    account)` to put it on an account other than `chk`. Only the accounts a
    fixture actually uses are opened."""
    used = ["chk"] + [a for a in ("card",)
                      if any(len(t) > 3 and t[3] == a for t in txns)]
    evs = [account_opened(account, ACCOUNT_KINDS[account],
                          account.title(), currency, "2026-01-01",
                          institution="northbank") for account in used]
    for when, description, amount, *rest in txns:
        account = rest[0] if rest else "chk"
        evs.append(simple_transaction(account, amount, description, when,
                                      kind=ACCOUNT_KINDS[account]))
    return evs


def _proj(txns, resolver=None, extra=()):
    proj = LedgerProjection([], resolve_keys=resolver)
    for event in list(_events(txns)) + list(extra):
        proj.apply(event)
    return proj


def _ledger(tmp_path, txns, resolver=None):
    ledger = Ledger(EventStore.open(tmp_path / "events.jsonl", "pw"),
                    resolve_keys=resolver)
    for event in _events(txns):
        ledger.append(event)
    return ledger


def _prior(merchant, billing="", period="", kind=KIND_BUSINESS,
           grade=CORROBORATED):
    """A catalog record for a merchant, as enrichment would have synced it.

    An empty ``kind`` writes no ``counterparty_kind`` at all, which is the
    record a reply naming a kind outside the closed set leaves behind."""
    attributes = {"counterparty_kind": kind} if kind else {}
    if billing:
        attributes["billing"] = billing
    if period:
        attributes["billing_period"] = period
    return merchant_enriched(merchant, "other", grade=grade,
                             occurred_at="2026-04-01", by="model",
                             attributes=attributes)


def _monthly(n=4, amount="-14.99", description="LUMEN STREAMING"):
    """`n` movements a month apart, rolling into the next year as needed."""
    return [(f"{2026 + (month - 1) // 12}-{(month - 1) % 12 + 1:02d}-05",
             description, amount) for month in range(1, 1 + n)]


def _rhythm_questions(source):
    return [q for q in open_questions(source, as_of="2026-06-01")["questions"]
            if q["kind"] == RHYTHM]


def _vault(ledger):
    """What the write paths need of a vault: its ledger, and nothing else."""
    return types.SimpleNamespace(ledger=ledger)


# --- the prior licenses the question, and nothing else does -----------------

def test_a_merchant_with_no_billing_prior_is_never_asked_about(tmp_path):
    """Silence is the default. Without world knowledge that an arrangement is
    even possible, a run of payments is a run of payments."""
    proj = _proj(_monthly(), extra=[_prior("lumen streaming")])
    assert proj.rhythm_hypotheses() == []
    assert _rhythm_questions(proj) == []


def test_a_merchant_billed_only_per_purchase_is_never_asked_about():
    """The settled rung on a new axis: a business one only ever buys from
    implies no arrangement, however many times it was bought from."""
    proj = _proj(_monthly(n=6, description="CORNER COFFEE"),
                 extra=[_prior("corner coffee", "per_purchase")])
    assert _rhythm_questions(proj) == []


def test_a_standing_prior_raises_one_grouped_proposal_per_pair():
    proj = _proj(_monthly(), extra=[_prior(BRAND, "standing", "monthly")])
    (q,) = _rhythm_questions(proj)
    assert q["scope"] == "pattern"
    assert q["refs"]["merchant"] == BRAND and q["refs"]["direction"] == "out"
    assert q["count"] == 4
    assert q["id"] == f"{RHYTHM}:{BRAND}|out"


# --- what was measured, and what is merely supposed -------------------------

def _measured_says() -> str:
    """The measured sentence's own words, up to the figure it places — so a
    test asserts on the pack rather than on a phrasing copied into it."""
    return persona.load()["phrasings"]["rhythm_measured"].split("{days}")[0]


def test_an_unmeasured_proposal_states_no_cadence():
    """Two sightings cannot make a rhythm. The sentence may say who they are
    and how many there have been, and must not say how often."""
    proj = _proj(_monthly(n=2), extra=[_prior(BRAND, "standing", "monthly")])
    (q,) = _rhythm_questions(proj)
    assert q["refs"]["measured"] is False and q["refs"]["cadence"] == ""
    assert _measured_says() not in q["text"]
    assert say("rhythm_prior_standing") in q["text"]
    assert say("rhythm_prior_period_monthly") in q["text"]
    assert q["why"] == say("rhythm_why_prior")


def test_a_measured_rhythm_says_what_the_records_measured():
    proj = _proj(_monthly(), extra=[_prior(BRAND, "standing", "annual")])
    (q,) = _rhythm_questions(proj)
    assert q["refs"]["measured"] is True and q["refs"]["cadence"] == "monthly"
    assert _measured_says() in q["text"]
    # The measurement is what is proposed where the two disagree: the prior
    # says a year, the ledger says a month, and the ledger wins.
    assert q["refs"]["billing_period"] == "annual"
    assert q["refs"]["proposed"] == ["monthly"]
    assert q["why"] == say("rhythm_why_measured")


def test_a_steady_rhythm_the_vocabulary_cannot_name_proposes_nothing_from_it():
    """A confirmable arrangement is one of four words. A flow measured steady
    at an interval none of them names states what it measured and proposes
    nothing — neither rounded to a neighbouring word, nor handed back to the
    prior it outranked.

    The prior here says monthly, so that the ledger winning a disagreement is
    distinguishable from there being nothing to beat."""
    weekly = [(f"2026-01-{day:02d}", "LUMEN STREAMING", "-14.99")
              for day in (5, 12, 19, 26)]
    proj = _proj(weekly, extra=[_prior(BRAND, "standing", "monthly")])
    (q,) = _rhythm_questions(proj)
    assert q["refs"]["measured"] is True and q["refs"]["cadence"] == "weekly"
    assert q["refs"]["billing_period"] == "monthly"
    assert q["refs"]["proposed"] == []
    # And the sentence says what it measured rather than what was supposed.
    assert _measured_says() in q["text"]
    assert say("rhythm_prior_period_monthly") not in q["text"]
    assert q["why"] == say("rhythm_why_measured")


def test_a_quarterly_arrangement_states_its_interval_and_proposes_nothing():
    """The same rule at the other end of the vocabulary. A quarter is a real
    arrangement and a steady one, and `quarterly` is not one of the four words
    a person may confirm — so the reading states the interval it measured and
    proposes nothing from it, rather than rounding a quarter to a month or
    falling back on what the world says about the merchant."""
    quarterly = [(when, "LUMEN STREAMING", "-149.00") for when in
                 ("2026-01-05", "2026-04-05", "2026-07-05", "2026-10-05",
                  "2027-01-05")]
    proj = _proj(quarterly, extra=[_prior(BRAND, "standing", "monthly")])
    (q,) = _rhythm_questions(proj)
    assert q["refs"]["measured"] is True and q["refs"]["cadence"] == "quarterly"
    assert q["refs"]["proposed"] == []
    assert _measured_says() in q["text"]
    assert say("rhythm_prior_period_monthly") not in q["text"]
    assert q["why"] == say("rhythm_why_measured")


def _irregular(description="BOREA MARKET"):
    """Twelve movements whose gaps never settle and whose amounts never repeat
    — one thing, measured, and what was measured is that there is no rhythm."""
    when = ("2026-01-03", "2026-01-09", "2026-02-02", "2026-02-19", "2026-02-20",
            "2026-03-15", "2026-04-01", "2026-04-27", "2026-05-02", "2026-05-24",
            "2026-06-15", "2026-06-16")
    amounts = ("-11.20", "-49.05", "-7.65", "-128.40", "-23.75", "-99.40",
               "-34.55", "-212.90", "-18.30", "-61.85", "-145.20", "-86.10")
    return [(d, description, a) for d, a in zip(when, amounts)]


def test_a_flow_with_no_rhythm_in_it_measured_that_and_says_so():
    """Enough observations means something was measured, and where the spacing
    never settles the thing measured is that these do not come round on a
    pattern. `irregular` is one of the four words a person may confirm, so it
    is what the reading proposes — and no interval is stated, because none
    held."""
    proj = _proj(_irregular(), extra=[_prior("borea market", "either", "monthly")])
    (q,) = _rhythm_questions(proj)
    assert q["count"] == 12
    assert q["refs"]["measured"] is True and q["refs"]["steady"] is False
    assert q["refs"]["cadence"] == "irregular"
    assert q["refs"]["proposed"] == ["irregular"]
    assert say("rhythm_irregular") in q["text"]
    assert say("rhythm_irregular_ask") in q["text"]
    assert _measured_says() not in q["text"]
    assert q["why"] == say("rhythm_why_irregular")


def test_a_measured_absence_of_rhythm_beats_what_the_world_says():
    """The ledger wins where the two disagree, and an absence of rhythm is
    something the ledger said. A prior of monthly against twelve movements that
    settle into nothing proposes irregular, never monthly, and never tells a
    person holding twelve records that there is not enough here to see a
    pattern of their own."""
    proj = _proj(_irregular(), extra=[_prior("borea market", "standing", "monthly")])
    (q,) = _rhythm_questions(proj)
    assert q["refs"]["billing_period"] == "monthly"
    assert q["refs"]["proposed"] == ["irregular"]
    for supposed in ("rhythm_prior_standing", "rhythm_prior_either",
                     "rhythm_prior_period_monthly", "rhythm_why_prior"):
        assert say(supposed) not in q["text"]
    assert q["why"] != say("rhythm_why_prior")


def test_the_prior_speaks_only_where_there_was_nothing_to_measure():
    """Where the supposing sentence may appear, tested by shape. It rests on
    world knowledge instead of this relationship, so it is honest only below
    the floor at which a relationship can be measured at all — and every vault
    here that reaches it has fewer movements than that floor."""
    vaults = [
        _proj(_irregular(), extra=[_prior("borea market", "either", "monthly")]),
        _proj(_mixture(), extra=[_prior("borea market", "either")]),
        _proj(_monthly(n=5), extra=[_prior(BRAND, "standing", "monthly")]),
        _proj(_monthly(n=3), extra=[_prior(BRAND, "standing", "annual")]),
        _proj(_monthly(n=2), extra=[_prior(BRAND, "standing", "monthly")]),
        _proj(_monthly(n=1), extra=[_prior(BRAND, "either", "either")]),
    ]
    poverty = say("rhythm_why_prior")
    seen = set()
    for vault in vaults:
        for q in _rhythm_questions(vault):
            supposing = q["why"] == poverty
            seen.add(supposing)
            if supposing:
                assert q["count"] < MIN_FOR_CADENCE
                assert q["refs"]["measured"] is False
            else:
                assert poverty not in q["text"]
    assert seen == {True, False}, "the battery must contain both shapes"


def test_the_same_merchant_seen_once_and_seen_often_asks_the_same_question():
    """Both arrival paths, one mechanism. A first sighting and a data dump ask
    the same kind of question with the same answer space — and say visibly
    different things, because they know different amounts."""
    once = _proj(_monthly(n=1), extra=[_prior(BRAND, "standing", "monthly")])
    often = _proj(_monthly(n=14), extra=[_prior(BRAND, "standing", "monthly")])
    (first,) = _rhythm_questions(once)
    (dump,) = _rhythm_questions(often)
    assert first["kind"] == dump["kind"] == RHYTHM
    assert first["slots"] == dump["slots"]
    assert first["text"] != dump["text"]
    assert first["refs"]["measured"] is False and dump["refs"]["measured"] is True


def test_a_question_is_ranked_on_money_already_measured():
    """A stake is a ranking key, never a spoken figure — and never a projection
    about what a relationship will move next."""
    proj = _proj(_monthly(n=3), extra=[_prior(BRAND, "standing")])
    (q,) = _rhythm_questions(proj)
    population = [m for m in proj.movements()
                  if proj.merchant_key_of(m) == BRAND and m.amount < 0]
    assert Decimal(q["amount"]) == sum(abs(m.amount) for m in population)
    assert q["count"] == len(population)


# --- a counterparty that is two things at once ------------------------------

def _fixed_says() -> str:
    """The sameness-of-amount sentence, from the pack."""
    return persona.load()["phrasings"]["rhythm_measured_fixed"]


def _mixture(subscription="-14.99", visits=("-38.20", "-71.45", "-19.90",
                                            "-104.10", "-52.75")):
    """One merchant that is two things: a repeating amount on the 1st of the
    month, and a run of separate decisions on the 16th."""
    txns = [(f"2026-{month:02d}-01", "BOREA MARKET", subscription)
            for month in range(1, 6)]
    txns += [(f"2026-{month:02d}-16", "BOREA MARKET", amount)
             for month, amount in zip(range(1, 6), visits)]
    return sorted(txns)


def test_a_counterparty_that_is_two_things_gets_no_cadence_over_the_mixture():
    """A merchant that is both a repeating charge on the 1st and a shop visit
    on the 16th has a pooled interval of fifteen days and no arrangement that
    runs every fifteen days. No cadence, interval or sameness of amount is
    claimed over the two together."""
    proj = _proj(_mixture(), extra=[_prior("borea market", "either")])
    (q,) = _rhythm_questions(proj)
    assert _measured_says() not in q["text"]
    assert _fixed_says() not in q["text"]
    assert q["refs"]["measured"] is False
    assert q["refs"]["cadence"] == "" and q["refs"]["proposed"] == []


def test_a_mixture_states_what_it_saw_of_each_part_and_asks_which_is_which():
    """It does not go silent either: the reading names the mixture, states the
    count and the money of each part, and asks. Of neither part does it assert
    that the part is an arrangement — that is what is being asked."""
    proj = _proj(_mixture(), extra=[_prior("borea market", "either")])
    (q,) = _rhythm_questions(proj)
    assert say("rhythm_mixture_lead") in q["text"]
    assert say("rhythm_mixture_ask") in q["text"]
    assert q["why"] == say("rhythm_why_mixture")
    assert say("rhythm_ask") not in q["text"]

    repeating, varying = q["refs"]["components"]
    assert (repeating["count"], repeating["amount_stability"]) == (5, "fixed")
    assert (varying["count"], varying["amount_stability"]) == (5, "variable")
    assert Decimal(q["amount"]) == (Decimal(repeating["amount"])
                                    + Decimal(varying["amount"]))
    # Every movement is in exactly one part, and the parts are the whole.
    parts = [k for part in q["refs"]["components"] for k in part["movements"]]
    assert sorted(parts) == sorted(q["refs"]["movements"])
    assert len(parts) == len(set(parts)) == q["count"]


def test_a_mixture_with_plenty_of_records_never_claims_there_is_too_little():
    """A mixture is a reading of what the records do show, so it never borrows
    the sentence that exists for having seen almost nothing: a person holding
    twelve movements is not told there is too little here to see a pattern."""
    twelve = [(f"2026-{month:02d}-01", "BOREA MARKET", "-14.99")
              for month in range(1, 7)]
    twelve += [(f"2026-{month:02d}-16", "BOREA MARKET", amount)
               for month, amount in zip(range(1, 7),
                                        ("-38.20", "-71.45", "-19.90",
                                         "-104.10", "-52.75", "-27.30"))]
    proj = _proj(sorted(twelve), extra=[_prior("borea market", "either")])
    (q,) = _rhythm_questions(proj)
    assert q["count"] == 12 and q["refs"]["measured"] is False
    assert q["why"] == say("rhythm_why_mixture")
    poverty = say("rhythm_why_prior")
    assert poverty != q["why"] and poverty not in q["text"]


def test_every_statistic_belongs_to_the_part_it_was_measured_over():
    """A component is the largest set anything may describe. The repeating part
    is monthly because its own five dates are a month apart, not because the
    ten movements together were called anything."""
    proj = _proj(_mixture(), extra=[_prior("borea market", "either")])
    (h,) = proj.rhythm_hypotheses()
    assert h.mixed is True and h.interval_days is None
    assert h.amount_stability == "" and h.cadence == ""
    repeating, varying = h.components
    assert repeating.count == 5 and repeating.cadence == "monthly"
    # Its own five dates are a month apart. The ten together are fifteen days
    # apart, and that figure appears nowhere.
    assert repeating.interval_days > 15
    assert varying.amount_stability == "variable"


def test_a_relationship_that_is_one_thing_is_still_described_as_one():
    """The decomposition is not a new way of going quiet. Where every amount
    repeats, or where none of them does, there is one thing to describe and it
    is described exactly as it was before."""
    same = _proj(_monthly(n=5), extra=[_prior(BRAND, "standing")])
    (one,) = _rhythm_questions(same)
    assert len(one["refs"]["components"]) == 1
    assert _measured_says() in one["text"] and _fixed_says() in one["text"]

    varied = _proj([(f"2026-{m:02d}-05", "LUMEN STREAMING", a) for m, a in
                    zip(range(1, 5), ("-10.00", "-31.00", "-64.00", "-119.00"))],
                   extra=[_prior(BRAND, "standing")])
    (other,) = _rhythm_questions(varied)
    assert len(other["refs"]["components"]) == 1
    assert _measured_says() in other["text"] and _fixed_says() not in other["text"]


def _flow_over(proj, movement_keys, direction) -> Flow:
    """Step 1's own reading of the movements a part of a sentence is about.

    Asked of `Flow` rather than re-derived here, so a claim in a sentence is
    checked against the measurement it is supposed to rest on and not against
    the reading's own word for that measurement."""
    held = {m.key: m for m in proj.movements()}
    return Flow(direction=direction,
                occurrences=[Occurrence(date=_as_date(held[k].date),
                                        amount=held[k].amount,
                                        account=held[k].account,
                                        kind=held[k].kind,
                                        description=held[k].description)
                             for k in movement_keys])


def test_no_sentence_claims_a_shape_over_movements_not_measured_as_one():
    """The rule, tested by shape rather than by fixture.

    A cadence, an interval and a sameness of amount are claims about one thing.
    Across every arrangement of a relationship these tests can build, either a
    question's movements decomposed into one component and it may make those
    claims, or they did not and it makes none of them.

    Every figure and every claim is then checked against the flow it is about:
    the opening sentence states the count and the money of every movement the
    question covers, a part states its own count and its own money and says of
    its amounts only what they were measured to be, an interval stated is the
    interval that was measured, and a claim of steadiness appears only over
    intervals that were measured steady. Every one of those figures is read by
    a person as a fact about their own money, and each is checked here against
    the measurement it is supposed to be, not against the reading's word for
    it."""
    from viva.render import merchant as render_merchant

    vaults = [
        _proj(_mixture(), extra=[_prior("borea market", "either")]),
        _proj(_mixture(visits=("-38.20", "-38.30", "-71.45", "-19.90", "-52.75")),
              extra=[_prior("borea market", "either")]),
        _proj(_monthly(n=5) + [("2026-03-20", "LUMEN STREAMING", "-79.00")],
              extra=[_prior(BRAND, "standing", "monthly")]),
        _proj(_monthly(n=5), extra=[_prior(BRAND, "standing")]),
        _proj(_irregular(), extra=[_prior("borea market", "either", "monthly")]),
        _proj(_monthly(n=2), extra=[_prior(BRAND, "standing", "annual")]),
        _proj(_monthly(n=1), extra=[_prior(BRAND, "either", "either")]),
    ]
    claims = (_measured_says(), _fixed_says())
    # Which sentence describes a part, restated here on purpose: a guard that
    # imported the mapping the reading uses would agree with any change to it,
    # including one that told a person a varying part repeats.
    part_says = {"fixed": "rhythm_mixture_part_repeating",
                 "variable": "rhythm_mixture_part_varying",
                 "unknown": "rhythm_mixture_part_lone"}
    seen = set()
    for vault in vaults:
        for q in _rhythm_questions(vault):
            parts = q["refs"]["components"]
            flows = [_flow_over(vault, part["movements"], q["refs"]["direction"])
                     for part in parts]
            seen.add(len(parts) > 1)
            # The opening sentence is about the whole relationship, mixture or
            # not, so its two figures are the count and the money of every
            # movement the question covers — never one part's share of them.
            whole = _flow_over(vault, q["refs"]["movements"],
                               q["refs"]["direction"])
            assert say("rhythm_head", count=render_count(whole.n),
                       example=render_merchant(
                           {"example": q["refs"]["descriptor"]}),
                       money=render_money(whole.total, q["currency"],
                                          locale="en-US")) in q["text"]
            if len(parts) > 1:
                assert not any(claim in q["text"] for claim in claims)
                assert q["refs"]["cadence"] == "" and not q["refs"]["proposed"]
                for flow in flows:
                    assert say(part_says[flow.amount_stability],
                               count=render_count(flow.n),
                               money=render_money(flow.total, q["currency"],
                                                  locale="en-US")) in q["text"]
            for claim in claims:
                if claim in q["text"]:
                    assert len(parts) == 1 and q["refs"]["measured"] is True
            if _measured_says() in q["text"]:
                assert flows[0].interval_is_steady
                # And the interval spoken is the one that was measured over
                # those movements, rather than a number near it.
                assert say("rhythm_measured",
                           days=render_count(flows[0].median_interval_days)
                           ) in q["text"]
            if _fixed_says() in q["text"]:
                assert flows[0].amount_is_fixed
    assert seen == {True, False}, "the battery must contain both shapes"


def test_which_is_which_is_recorded_as_one_set_valued_ruling(tmp_path):
    """"The fixed ones are monthly, the rest is just shopping" has a vessel
    already: one subject, one value carrying both words. No new event type, no
    second subject, and nothing claiming which movements are which — the ruling
    says what the person knows about the relationship, which is that it holds
    both."""
    ledger = _ledger(tmp_path, _mixture())
    ledger.append(_prior("borea market", "either"))
    (q,) = _rhythm_questions(ledger)
    asked = find_question(ledger, q["id"], as_of="2026-08-01")
    parsed = Reply(True, values={"periods": [{"period": "monthly"},
                                             {"period": "irregular"}]})
    out = _write_answer(_vault(ledger), asked, parsed,
                        "the fixed ones are monthly, the rest is just shopping")
    assert out["ok"] and out["periods"] == ["monthly", "irregular"]
    assert ledger.projection().rhythm_of("borea market", "out") == (
        "monthly", "irregular")
    assert not _rhythm_questions(ledger)
    (recorded,) = [e for e in ledger.events() if e.event_type == "RulingRecorded"]
    assert recorded.body["subject"] == "borea market|out"
    assert recorded.body["value"] == "monthly+irregular"


def test_the_decomposition_does_not_depend_on_the_order_movements_arrived():
    forwards = _proj(_mixture(), extra=[_prior("borea market", "either")])
    backwards = _proj(list(reversed(_mixture())),
                      extra=[_prior("borea market", "either")])
    assert (forwards.rhythm_hypotheses()[0].components
            == backwards.rhythm_hypotheses()[0].components)


# --- direction is part of the subject ---------------------------------------

def test_money_out_and_money_back_are_two_arrangements():
    """One relationship, two rhythms. A brokerage taking contributions and
    paying distributions is the case this exists for."""
    both = _monthly(n=3) + [("2026-02-20", "LUMEN STREAMING", "9.00")]
    proj = _proj(both, extra=[_prior(BRAND, "standing")])
    subjects = {q["refs"]["direction"] for q in _rhythm_questions(proj)}
    assert subjects == {"in", "out"}


def _half_on_a_card(months=12):
    """One subscription, the first half paid from checking and the second half
    on a card, where the same charge posts positive because what is owed grew."""
    half = months // 2
    return ([(f"2026-{month:02d}-05", "LUMEN STREAMING", "-14.99")
             for month in range(1, half + 1)]
            + [(f"2026-{month:02d}-05", "LUMEN STREAMING", "14.99", "card")
               for month in range(half + 1, months + 1)])


def test_a_merchant_paid_from_two_account_kinds_is_one_arrangement():
    """One subscription is one relationship, whichever account paid it.

    Six months from checking and six on a card form one outflow of twelve,
    measured monthly, under the subject it would have had if checking had paid
    every month — one total over the whole relationship, and one sentence
    describing it."""
    proj = _proj(_half_on_a_card(), extra=[_prior(BRAND, "standing")])
    (h,) = proj.rhythm_hypotheses()
    assert h.direction == "out" and h.subject == f"{BRAND}|out"
    assert h.count == 12 and h.amount == Decimal("179.88")
    assert h.measured and h.cadence == "monthly"
    (q,) = _rhythm_questions(proj)
    assert q["refs"]["direction"] == "out"
    assert len(q["refs"]["movements"]) == 12
    assert say("rhythm_direction_out") in q["text"]


def test_confirming_one_direction_leaves_the_other_asked(tmp_path):
    both = _monthly(n=3) + [("2026-02-20", "LUMEN STREAMING", "9.00")]
    ledger = _ledger(tmp_path, both)
    ledger.append(_prior(BRAND, "standing"))
    record_rhythm(_vault(ledger), BRAND, "out", ["monthly"], said="monthly")
    still = _rhythm_questions(ledger)
    assert [q["refs"]["direction"] for q in still] == ["in"]


# --- a question that was answered does not come back ------------------------

def test_an_answered_rhythm_question_is_never_asked_again(tmp_path):
    """The queue can be driven to empty on this axis.

    A rhythm ruling covers the whole pair the question was asked about, so
    answering it ends it — in the open list and in the set-aside list alike,
    rather than attaching while the question returns."""
    ledger = _ledger(tmp_path, _monthly())
    ledger.append(_prior(BRAND, "standing", "monthly"))
    (before,) = _rhythm_questions(ledger)

    record_rhythm(_vault(ledger), BRAND, "out", ["monthly"], said="every month")

    after = _rhythm_questions(ledger)
    assert before["id"] not in [q["id"] for q in after] and not after
    assert not [q for q in pending_questions(ledger)["questions"]
                if q["kind"] == RHYTHM]
    assert find_question(ledger, before["id"], as_of="2026-06-01") is None


def test_more_of_the_same_money_does_not_reopen_a_confirmed_rhythm(tmp_path):
    """And it stays answered as the relationship goes on. A decline returns
    when its stake moves; a confirmation does not, because it was an answer."""
    ledger = _ledger(tmp_path, _monthly())
    ledger.append(_prior(BRAND, "standing", "monthly"))
    record_rhythm(_vault(ledger), BRAND, "out", ["monthly"], said="every month")
    ledger.append(simple_transaction("chk", "-14.99", "LUMEN STREAMING",
                                     "2026-05-05"))
    assert not _rhythm_questions(ledger)


def test_a_confirmed_pair_is_still_carried_by_the_hypothesis(tmp_path):
    """Suppressed from the queue, and not hidden from the read: what was
    confirmed and what is measured sit beside each other in one read."""
    ledger = _ledger(tmp_path, _monthly())
    ledger.append(_prior(BRAND, "standing", "monthly"))
    record_rhythm(_vault(ledger), BRAND, "out", ["monthly"], said="every month")
    (h,) = ledger.projection().rhythm_hypotheses()
    assert h.confirmed == ("monthly",) and h.measured is True


# --- one subject, several arrangements, and a way to take one back ----------

def test_a_relationship_can_hold_two_periodicities_at_once(tmp_path):
    ledger = _ledger(tmp_path, _monthly())
    ledger.append(_prior(BRAND, "standing"))
    record_rhythm(_vault(ledger), BRAND, "out", ["monthly", "annual"],
                  said="one monthly, one yearly")
    assert ledger.projection().rhythm_of(BRAND, "out") == ("monthly", "annual")


def test_re_answering_replaces_rather_than_accumulates(tmp_path):
    """A correction is an ordinary re-answer on one subject: the later value
    is what answers, and nothing accumulates."""
    ledger = _ledger(tmp_path, _monthly())
    ledger.append(_prior(BRAND, "standing"))
    record_rhythm(_vault(ledger), BRAND, "out", ["monthly"], said="monthly")
    record_rhythm(_vault(ledger), BRAND, "out", ["annual"],
                  said="no, it's yearly")
    assert ledger.projection().rhythm_of(BRAND, "out") == ("annual",)


def test_the_written_value_does_not_depend_on_the_order_of_an_answer(tmp_path):
    ledger = _ledger(tmp_path, _monthly())
    one = record_rhythm(_vault(ledger), BRAND, "out", ["annual", "monthly"])
    two = record_rhythm(_vault(ledger), "borea", "out", ["monthly", "annual"])
    assert one["periods"] == two["periods"] == ["monthly", "annual"]


# --- a key change must not orphan a ruling ----------------------------------

def test_a_ruling_under_a_descriptor_key_answers_after_the_brand_is_named():
    """A merchant key can change under a recorded ruling — a grammar induced
    later names the brand — and a brand covers every descriptor its name was
    printed in. The answer survives the rename from either of them, so a ruling
    recorded under one descriptor is still reachable once the brand is named
    and the person who gave it is not asked again."""
    from viva.ledger.merchants import normalize_merchant

    descriptors = [normalize_merchant(d) for d in (NOISY, ALSO_NOISY)]
    assert len(set(descriptors)) == 2 and BRAND not in descriptors
    txns = [(f"2026-{month:02d}-05", NOISY if month % 2 else ALSO_NOISY,
             "-14.99") for month in range(1, 7)]

    for held in descriptors:
        ruling = ruling_recorded(SCOPE_RHYTHM, f"{held}|out",
                                 "2026-04-02", by="human", grade=VERIFIED,
                                 said="monthly", value="monthly")
        before = _proj(txns, extra=[_prior(held, "standing"), ruling])
        assert before.rhythm_of(held, "out") == ("monthly",)

        after = _proj(txns, resolver=_resolver(),
                      extra=[_prior(BRAND, "standing"), ruling])
        assert {after.merchant_key_of(m) for m in after.movements()} == {BRAND}
        assert after.rhythm_of(BRAND, "out") == ("monthly",)
        assert not _rhythm_questions(after)


def test_the_latest_thing_a_person_said_is_the_one_that_answers():
    """One relationship, two descriptors, two answers — and the one that
    stands is the one said last.

    Both are the person's own word, so grade cannot separate them, and
    whichever descriptor happens to sort first is not a reason to believe one
    over the other. A correction is an ordinary re-answer on one relationship;
    if the earlier statement won, a person could restate their arrangement and
    never find out that nothing changed, because the answer suppresses the
    question that would have shown them."""
    from viva.ledger.merchants import normalize_merchant

    first_alphabetically, said_later = sorted(
        normalize_merchant(d) for d in (NOISY, ALSO_NOISY))
    assert first_alphabetically != said_later
    txns = [(f"2026-{month:02d}-05", NOISY if month % 2 else ALSO_NOISY,
             "-14.99") for month in range(1, 7)]

    stale = ruling_recorded(SCOPE_RHYTHM, f"{first_alphabetically}|out",
                            "2026-04-02", by="human", grade=VERIFIED,
                            said="every month", value="monthly")
    fresh = ruling_recorded(SCOPE_RHYTHM, f"{said_later}|out",
                            "2026-05-09", by="human", grade=VERIFIED,
                            said="no, once a year", value="annual")
    proj = _proj(txns, resolver=_resolver(),
                 extra=[_prior(BRAND, "standing"), stale, fresh])
    assert {proj.merchant_key_of(m) for m in proj.movements()} == {BRAND}
    assert proj.rhythm_of(BRAND, "out") == ("annual",)
    assert not _rhythm_questions(proj)

    # The same two statements the other way round: what answers follows what
    # was said last and not the order the events arrived in.
    shuffled = _proj(txns, resolver=_resolver(),
                     extra=[_prior(BRAND, "standing"), fresh, stale])
    assert shuffled.rhythm_of(BRAND, "out") == ("annual",)


def test_a_prior_under_a_descriptor_key_survives_a_grammar_naming_the_brand():
    """The same crack, on the other half of the question.

    A merchant enriched before a grammar existed carries its record under the
    descriptor key; inducing a grammar then changes what the movements resolve
    to. A prior read on the current key alone would switch the question off the
    day the maintenance agent did its routine work — silently, because a
    question that stops being asked reports nothing."""
    from viva.ledger.merchants import normalize_merchant

    descriptor_key = normalize_merchant(NOISY)
    assert descriptor_key != BRAND
    txns = [(f"2026-{month:02d}-05", NOISY, "-14.99") for month in range(1, 5)]
    prior = _prior(descriptor_key, "standing", "monthly")

    before = _proj(txns, extra=[prior])
    assert [q["refs"]["merchant"] for q in _rhythm_questions(before)] == [
        descriptor_key]

    after = _proj(txns, resolver=_resolver(), extra=[prior])
    assert after.merchant_key_of(after.movements()[0]) == BRAND
    (q,) = _rhythm_questions(after)
    assert q["refs"]["merchant"] == BRAND and q["refs"]["billing"] == "standing"
    assert q["refs"]["billing_period"] == "monthly"


# --- what the ledger will accept --------------------------------------------

def test_a_periodicity_outside_the_closed_set_raises_at_construction():
    with pytest.raises(ValueError):
        ruling_recorded(SCOPE_RHYTHM, f"{BRAND}|out", "2026-04-02",
                        value="fortnightly", said="every other week")
    with pytest.raises(ValueError):
        # One good word does not carry a bad one in with it.
        ruling_recorded(SCOPE_RHYTHM, f"{BRAND}|out", "2026-04-02",
                        value="monthly+whenever", said="")


def test_a_rhythm_ruling_with_nothing_confirmed_raises():
    with pytest.raises(ValueError):
        ruling_recorded(SCOPE_RHYTHM, f"{BRAND}|out", "2026-04-02", value="")


def test_a_rhythm_subject_names_a_counterparty_and_a_direction():
    with pytest.raises(ValueError):
        ruling_recorded(SCOPE_RHYTHM, BRAND, "2026-04-02", value="monthly")
    with pytest.raises(ValueError):
        ruling_recorded(SCOPE_RHYTHM, "|out", "2026-04-02", value="monthly")


def test_a_direction_outside_the_two_the_ledger_measures_raises():
    """Both halves of the subject are closed, for one reason. Money moves one
    of two ways and the statistics are measured one of two ways, so a subject
    naming any other direction is one no read could ever answer — and in an
    append-only log with a permanent subject format, it would stand for ever."""
    from viva.ledger.events import RHYTHM_DIRECTIONS

    assert set(RHYTHM_DIRECTIONS) == {"in", "out"}
    with pytest.raises(ValueError):
        ruling_recorded(SCOPE_RHYTHM, f"{BRAND}|sideways", "2026-04-02",
                        value="monthly", said="monthly")
    for direction in RHYTHM_DIRECTIONS:
        assert ruling_recorded(SCOPE_RHYTHM, f"{BRAND}|{direction}",
                               "2026-04-02", value="monthly", said="monthly")


def test_the_value_fence_still_holds_everywhere_else():
    """Admitting rhythm scope is a net tightening, not a hole: every other
    scope still carries no value at all."""
    with pytest.raises(ValueError):
        ruling_recorded("merchant", BRAND, "2026-04-02", value="monthly",
                        said="monthly")
    # And attribute scope keeps its own guard, unchanged.
    with pytest.raises(ValueError):
        ruling_recorded(SCOPE_ATTRIBUTE, "Assets:Home:Cottage:cost",
                        "2026-04-02", value="250000", said="I paid a lot")


# --- the boundary, and the shape of the read --------------------------------

def test_a_person_shaped_stream_reaches_no_prompt_no_catalog_and_no_question():
    """A stream a grammar named as a person never crosses to enrichment, so it
    can hold no billing prior, so it can raise no question. The fence is that
    nothing about a person is ever asked of a model in the first place."""
    from viva.ledger.hints import enrichment_hints
    from viva.ledger.streams import build_streams

    grammar = Profile("northbank", "depository", "v1", [
        Template("PEER PAYMENT TO {counterparty} REF {reference}"),
    ])
    txns = [(f"2026-{month:02d}-05", "PEER PAYMENT TO ALEX MORGAN REF 88231",
             "-40.00") for month in range(1, 5)]
    proj = _proj(txns, resolver=lambda rows: resolve_keys(
        rows, profile_for=lambda i, k: grammar))
    streams = build_streams(proj.movements(), lambda m: grammar,
                            lambda m: m.kind)
    assert any(s.is_person for s in streams)
    assert enrichment_hints(streams) == {}
    assert _rhythm_questions(proj) == []


# One bank's peer rail, written two ways: a template whose slot names a party
# and a template whose slot names a brand. The only difference between the two
# runs of payments below is which kind of slot was filled.
PEER_GRAMMAR = Profile("northbank", "depository", "v1", [
    Template("TRANSFER TO {counterparty} REF {reference}"),
    Template("SUBSCRIPTION TO {brand} REF {reference}"),
])
STEADY_PERSON = "TRANSFER TO ROHAN IYER REF 4417"
ERRATIC_PERSON = "TRANSFER TO PRIYA NAIR REF 5502"
PEER_RAIL_BRAND = "SUBSCRIPTION TO ORBIT ATLAS REF 6690"


def _peer_txns():
    """Three runs on one rail: a person paid the same amount every month, a
    person paid odd amounts at odd intervals, and a business paid the same
    amount every month."""
    steady = [(f"2026-{month:02d}-05", STEADY_PERSON, "-250.00")
              for month in range(1, 7)]
    erratic = [("2026-01-11", ERRATIC_PERSON, "-40.00"),
               ("2026-01-29", ERRATIC_PERSON, "-115.50"),
               ("2026-03-02", ERRATIC_PERSON, "-8.25"),
               ("2026-05-19", ERRATIC_PERSON, "-620.00")]
    brand = [(f"2026-{month:02d}-07", PEER_RAIL_BRAND, "-19.00")
             for month in range(1, 7)]
    return steady + erratic + brand


def _key_for(proj, description):
    return next(proj.merchant_key_of(m) for m in proj.movements()
                if m.description == description)


def test_a_slot_declared_person_contributes_no_flow_however_steady_or_licensed():
    """A person a grammar slot declared is out of the measurement itself: no
    flow, no hypothesis, no question — for the steady monthly run and the
    erratic one alike, each carrying a record that says everything a record can
    say.

    The declaration is the whole of the guarantee. A person's name a template
    put in a `{brand}` slot is declared a person by nothing, and contributes a
    flow like any other counterparty."""
    txns = _peer_txns()
    plain = _proj(txns, resolver=_resolver(PEER_GRAMMAR))
    priors = [_prior(_key_for(plain, line), "standing", "monthly")
              for line in (STEADY_PERSON, ERRATIC_PERSON)]
    proj = _proj(txns, resolver=_resolver(PEER_GRAMMAR), extra=priors)

    assert proj.rhythm_hypotheses() == []
    assert _rhythm_questions(proj) == []


def test_a_merchant_on_the_same_rail_still_reaches_a_rhythm_question():
    """The same bank, the same rail and the same monthly shape still propose an
    arrangement where a slot named a brand rather than a party."""
    txns = _peer_txns()
    plain = _proj(txns, resolver=_resolver(PEER_GRAMMAR))
    brand_key = _key_for(plain, PEER_RAIL_BRAND)
    person_keys = {_key_for(plain, line)
                   for line in (STEADY_PERSON, ERRATIC_PERSON)}
    proj = _proj(txns, resolver=_resolver(PEER_GRAMMAR),
                 extra=[_prior(k, "standing", "monthly")
                        for k in person_keys | {brand_key}])

    (hypothesis,) = proj.rhythm_hypotheses()
    assert hypothesis.merchant == brand_key and hypothesis.count == 6
    (q,) = _rhythm_questions(proj)
    assert q["refs"]["merchant"] == brand_key
    # And no subject a person could be answered under exists anywhere in it.
    assert not person_keys & {h.merchant for h in proj.rhythm_hypotheses()}


# --- what kind of counterparty, the second half of the licence --------------

# Every grade a catalog record can be written at, and every combination of
# billing values a record can carry.
_ANY_GRADE = (VERIFIED, CORROBORATED, UNVERIFIED)
_ANY_BILLING = (("standing", "monthly"), ("standing", "annual"),
                ("either", "either"), ("either", ""), ("per_purchase", ""))
# One sighting, and enough of them to clear the cadence floor and be measured.
_ANY_COUNT = (1, 2, MIN_FOR_CADENCE, MIN_FOR_CADENCE + 3)


@pytest.mark.parametrize("kind", [KIND_PEER, KIND_INSTRUMENT])
def test_a_counterparty_that_is_not_a_business_is_asked_nothing(kind):
    """An arrangement is a thing one has with a business. A record naming any
    other kind of counterparty raises no hypothesis and no question, whatever
    the world says about how they bill, however the record is graded, and on
    either side of the cadence floor — so neither a long steady run nor a
    confident grade can talk the read into proposing one."""
    for grade in _ANY_GRADE:
        for billing, period in _ANY_BILLING:
            for n in _ANY_COUNT:
                proj = _proj(_monthly(n=n), extra=[
                    _prior(BRAND, billing, period, kind=kind, grade=grade)])
                where = (kind, grade, billing, period, n)
                assert proj.rhythm_hypotheses() == [], where
                assert _rhythm_questions(proj) == [], where


def test_a_record_that_names_no_counterparty_kind_licenses_nothing():
    """The fence fails closed. A reply naming a kind outside the closed set
    leaves a record carrying its billing model and no kind at all, and that
    record licenses nothing: what is missing withholds rather than passes."""
    from merchantcore.enrich import parse_enrichment

    garbled = '{"%s": {"counterparty_kind": "sole trader", "billing": "standing"}}'
    (record,) = parse_enrichment(garbled % BRAND, [BRAND], "test").values()
    assert "counterparty_kind" not in record.attributes
    assert record.attributes["billing"] == "standing"

    for grade in _ANY_GRADE:
        for billing, period in _ANY_BILLING:
            for n in _ANY_COUNT:
                proj = _proj(_monthly(n=n), extra=[
                    _prior(BRAND, billing, period, kind="", grade=grade)])
                where = (grade, billing, period, n)
                assert proj.rhythm_hypotheses() == [], where
                assert _rhythm_questions(proj) == [], where


def test_a_business_record_still_reaches_both_branches_of_the_read():
    """The licensed kind is the ordinary case, and it reaches both branches.
    Above the floor the measurement speaks and below it the world's knowledge
    does, and both arrive as one question."""
    measured = _proj(_monthly(n=4), extra=[_prior(BRAND, "standing", "monthly")])
    (h,) = measured.rhythm_hypotheses()
    assert h.measured and h.steady and h.cadence == "monthly"
    assert h.count == 4 and h.proposed == ("monthly",)
    (q,) = _rhythm_questions(measured)
    assert q["refs"]["measured"] is True and q["why"] == say("rhythm_why_measured")

    supposed = _proj(_monthly(n=1), extra=[_prior(BRAND, "standing", "monthly")])
    (h,) = supposed.rhythm_hypotheses()
    assert not h.measured and h.count == 1 and h.proposed == ("monthly",)
    (q,) = _rhythm_questions(supposed)
    assert q["refs"]["measured"] is False and q["why"] == say("rhythm_why_prior")


def _flow_shapes(proj):
    """Every flow the ledger formed, as `{pair: (count, total, movements)}` —
    what a measurement of a relationship consists of."""
    return {pair: (flow.n, flow.total, tuple(m.key for m in movements))
            for pair, (flow, movements) in
            rhythm_read._flows_by_merchant(proj._core).items()}


def test_the_flows_the_ledger_measures_do_not_depend_on_the_catalog():
    """What is withheld is the question, never the measurement.

    The same movements form the same flows, holding the same counts and the
    same amounts, whatever the catalog says the counterparty is — including
    where it says nothing, and where there is no record at all."""
    txns = _monthly(n=5)
    catalogs = {
        "no record": [],
        "no kind": [_prior(BRAND, "standing", "monthly", kind="")],
        **{kind: [_prior(BRAND, "standing", "monthly", kind=kind)]
           for kind in KINDS},
    }
    shapes = {name: _flow_shapes(_proj(txns, extra=extra))
              for name, extra in catalogs.items()}
    baseline = shapes["no record"]
    assert len(baseline) == 1 and next(iter(baseline.values()))[0] == 5
    for name, shape in shapes.items():
        assert shape == baseline, name

    # And the withheld case is measured all the same: the flow is there, with
    # its count and its amount, and only the proposal is absent.
    peer = _proj(txns, extra=catalogs[KIND_PEER])
    (measured,) = _flow_shapes(peer).values()
    assert measured == next(iter(baseline.values()))
    assert measured[0] == 5 and measured[1] != Decimal("0")
    assert peer.rhythm_hypotheses() == [] and _rhythm_questions(peer) == []


def _licensed(proj):
    """What the read proposes, as `{(subject, count, amount, proposed)}`."""
    return {(h.subject, h.count, h.amount, h.proposed)
            for h in proj.rhythm_hypotheses()}


def test_no_catalog_value_licenses_a_pair_the_billing_prior_alone_would_not(
        monkeypatch):
    """The conjunction property, over every combination of catalog values.

    Reading a second fact off the record can only ever withhold a proposal.
    For every kind, billing model, period and movement count, what the two
    facts license is a subset of what the billing model licenses on its own:
    no combination of catalog values raises a pair the billing model alone
    would not have raised."""
    kinds = ("", *KINDS)
    narrowed_somewhere = False
    for kind in kinds:
        for billing in ("", *BILLINGS):
            for period in ("", *BILLING_PERIODS):
                for n in (1, MIN_FOR_CADENCE + 1):
                    proj = _proj(_monthly(n=n), extra=[
                        _prior(BRAND, billing, period, kind=kind)])
                    where = (kind, billing, period, n)
                    both = _licensed(proj)
                    # Opening the kind test to every value a record can carry
                    # is the licensing the billing prior does on its own.
                    monkeypatch.setattr(rhythm_read, "LICENSED_KINDS", kinds)
                    billing_alone = _licensed(proj)
                    monkeypatch.undo()
                    assert both <= billing_alone, where
                    narrowed_somewhere |= both != billing_alone
    assert narrowed_somewhere, "the second fact never withheld anything"


def test_a_withheld_pair_stays_withheld_whatever_order_the_ledger_filled_in():
    """The fence is part of a pure function of the movement set: a person who
    loads a year in one afternoon and a person who loads a statement a month
    reach the same silence, and a record arriving after the movements changes
    nothing either."""
    txns = _monthly(n=5)
    for kind in (KIND_PEER, KIND_INSTRUMENT, ""):
        prior = _prior(BRAND, "standing", "monthly", kind=kind)
        forwards = _proj(txns, extra=[prior])
        backwards = _proj(list(reversed(txns)), extra=[prior])
        assert forwards.rhythm_hypotheses() == backwards.rhythm_hypotheses() == []
        assert _flow_shapes(forwards) == _flow_shapes(backwards)

        late = LedgerProjection([])
        for event in list(_events(txns)) + [prior]:
            late.apply(event)
        assert late.rhythm_hypotheses() == []


def test_the_hypothesis_is_a_pure_function_of_the_movement_set():
    """Order in, same beliefs out — a person who loads a year in one afternoon
    and a person who loads a statement a month reach the same reading."""
    txns = _monthly(n=5)
    prior = _prior(BRAND, "standing", "monthly")
    forwards = _proj(txns, extra=[prior]).rhythm_hypotheses()
    backwards = _proj(list(reversed(txns)), extra=[prior]).rhythm_hypotheses()
    assert forwards == backwards
    # And the prior arriving after the movements changes nothing either.
    late = LedgerProjection([])
    for event in _events(txns):
        late.apply(event)
    late.apply(prior)
    assert late.rhythm_hypotheses() == forwards


def test_the_read_writes_nothing_and_adds_no_event_type(tmp_path):
    ledger = _ledger(tmp_path, _monthly())
    ledger.append(_prior(BRAND, "standing", "monthly"))
    n_before = len(list(ledger.events()))
    open_questions(ledger, as_of="2026-06-01")
    assert len(list(ledger.events())) == n_before

    record_rhythm(_vault(ledger), BRAND, "out", ["monthly"], said="monthly")
    # The whole event vocabulary this axis may use. A confirmed rhythm rides
    # the generic scoped ruling; nothing here earns a type of its own.
    assert {e.event_type for e in ledger.events()} <= {
        "AccountOpened", "TransactionRecorded", "MerchantEnriched",
        "RulingRecorded"}
    (recorded,) = [e for e in ledger.events() if e.event_type == "RulingRecorded"]
    assert recorded.body["scope"] == SCOPE_RHYTHM
    assert recorded.body["subject"] == f"{BRAND}|out"
    assert recorded.body["value"] == "monthly"
    assert recorded.body["by"] == "human" and recorded.body["grade"] == VERIFIED
    assert recorded.body["said"] == "monthly"


# --- the answer path --------------------------------------------------------

def test_an_answer_to_a_rhythm_question_routes_to_one_ruling(tmp_path):
    """The declared slot holds SEVERAL periodicities, and what comes back
    through it is what is recorded — nothing re-reads the sentence."""
    ledger = _ledger(tmp_path, _monthly())
    ledger.append(_prior(BRAND, "standing", "monthly"))
    (q,) = _rhythm_questions(ledger)
    (periods,) = [s for s in q["slots"] if s["name"] == "periods"]
    (period,) = periods["parts"]
    assert period["choices"] == ["monthly", "annual", "one_time", "irregular"]

    asked = find_question(ledger, q["id"], as_of="2026-06-01")
    parsed = Reply(True, values={"periods": [{"period": "monthly"},
                                             {"period": "annual"}]})
    out = _write_answer(_vault(ledger), asked, parsed,
                        "one every month and one every year")
    assert out["ok"] and out["periods"] == ["monthly", "annual"]
    assert ledger.projection().rhythm_of(BRAND, "out") == ("monthly", "annual")
    assert not _rhythm_questions(ledger)


def test_every_word_a_person_may_confirm_can_be_read_back_into_the_slot(tmp_path):
    """The reading path for this question, through the slots it really
    declares.

    Each of the four stored words is a whole answer on its own, so each must be
    landable on its own, and each must be told to the reader in terms that say
    what it means: `one_time` is nobody's word for anything, and `irregular` is
    what a person means by nothing being arranged. A word the reader cannot
    place is not merely awkward — it comes back as no answer at all, and the
    question is asked again, which is exactly what confirming it was supposed
    to stop."""
    from viva.reply import _render_slots, read_reply

    ledger = _ledger(tmp_path, _monthly())
    ledger.append(_prior(BRAND, "standing", "monthly"))
    (q,) = _rhythm_questions(ledger)
    asked = find_question(ledger, q["id"], as_of="2026-06-01")

    told = _render_slots(asked.slots)
    for period in PERIODICITIES:
        assert f"{period} (" in told, f"{period} is offered as a bare token"
        read = read_reply(asked.slots, {"periods": [{"period": period}]})
        assert read.ok, (period, read.why)
        assert [m["period"] for m in read.values["periods"]] == [period]

    # And the slot holds several of them, which is why it holds parts at all.
    both = read_reply(asked.slots, {"periods": [{"period": "monthly"},
                                                {"period": "annual"}]})
    assert both.ok
    assert [m["period"] for m in both.values["periods"]] == ["monthly", "annual"]

    # A word outside the closed set is refused rather than recorded, and the
    # refusal is the whole answer: nothing half-lands.
    outside = read_reply(asked.slots, {"periods": [{"period": "fortnightly"}]})
    assert not outside.ok


def test_an_answer_that_landed_no_periodicity_records_nothing(tmp_path):
    ledger = _ledger(tmp_path, _monthly())
    ledger.append(_prior(BRAND, "standing", "monthly"))
    n_before = len(list(ledger.events()))
    out = record_rhythm(_vault(ledger), BRAND, "out", [], said="I'm not sure")
    assert not out["ok"] and out["message"]
    assert len(list(ledger.events())) == n_before


def test_every_sentence_of_a_rhythm_question_comes_from_the_pack(tmp_path):
    """Nothing here writes words. The queue supplies the figures and the
    evidence; the pack supplies every sentence, in order."""
    from viva.render import merchant as render_merchant
    from viva.render import money as render_money

    ledger = _ledger(tmp_path, _monthly(n=2))
    ledger.append(_prior(BRAND, "standing", "monthly"))
    (q,) = _rhythm_questions(ledger)
    said = [say("rhythm_head", count=render_count(2),
                example=render_merchant({"example": "LUMEN STREAMING"}),
                money=render_money(Decimal("29.98"), "USD", locale="en-US")),
            say("rhythm_direction_out"), say("rhythm_prior_standing"),
            say("rhythm_prior_period_monthly"), say("rhythm_ask")]
    assert q["text"] == " ".join(said)
    assert q["why"] == say("rhythm_why_prior")
