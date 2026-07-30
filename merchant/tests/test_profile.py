"""The descriptor grammar: a closed vocabulary, a lossless match, a frozen pack.

The point of these tests is not that templates match strings. It is that the
three properties the design leans on are enforced by the code rather than by
whoever writes the next prompt: the vocabulary is closed, a match explains the
whole line, and a released grammar cannot be edited.
"""

import json

import pytest
from merchantcore.induce import (build_induction_prompt, parse_induction,
                                 sample_descriptors, skeletons, narrow_templates,
                                 drift, holdout_split, Inducer,
                                 vocabulary_block)
from merchantcore.profile import (INDUCIBLE_KINDS, PERSONAL_SLOTS, SLOTS,
                                  Profile, ProfileError, ProfileStore,
                                  Template, is_inducible, validate)


def _profile(*patterns, institution="northbank", kind="depository", version="v1"):
    return Profile(institution=institution, kind=kind, version=version,
                   templates=[Template(p) for p in patterns])


# --- the closed vocabulary -------------------------------------------------

def test_only_names_from_the_vocabulary_compile():
    Template("ZELLE TO {counterparty} {reference}").compile()
    with pytest.raises(ProfileError):
        Template("ZELLE TO {name}").compile()            # not in the vocabulary


def test_the_model_cannot_smuggle_in_a_regex():
    # A shape is a NAME, and an unknown one is refused rather than passed
    # through — otherwise a template could carry arbitrary pattern text.
    with pytest.raises(ProfileError):
        Template("{brand:[A-Z]+}").compile()
    with pytest.raises(ProfileError):
        Template("{brand:anything}").compile()


def test_a_template_with_no_holes_is_an_example_not_a_grammar():
    """Still refused — but by the check that has the evidence to say so, and
    only when the line it matches occurred once."""
    from merchantcore.profile import validate_evidence
    with pytest.raises(ProfileError):
        validate_evidence(_profile("COSTCO WHSE PLANO TX"),
                          {"COSTCO WHSE PLANO TX": 1})


def test_format_validation_admits_a_frozen_fixed_phrase():
    """`validate` runs at LOAD time, where there is no evidence. If it still
    refused slotless templates, a grammar containing a legitimate fixed phrase
    could be written and then never read back."""
    validate(_profile("PAYMENT THANK YOU - WEB"))


def test_a_fixed_phrase_the_bank_repeats_passes_the_evidence_check():
    from merchantcore.profile import validate_evidence
    validate_evidence(_profile("PAYMENT THANK YOU - WEB"),
                      {"PAYMENT THANK YOU - WEB": 78})


def test_a_slot_may_not_appear_twice_in_one_template():
    with pytest.raises(ProfileError):
        Template("{brand} AND {brand}").compile()


def test_a_profile_with_no_templates_explains_nothing():
    with pytest.raises(ProfileError):
        validate(_profile())


def test_the_prompt_is_rendered_from_the_same_dict_the_validator_enforces():
    # If these drifted apart, a call could be spent on a grammar that cannot be
    # accepted, or a slot the code allows could be invisible to the model.
    block = vocabulary_block()
    for name in SLOTS:
        assert "{" + name + "}" in block
    prompt, version = build_induction_prompt(["ANY LINE"])
    assert "{counterparty}" in prompt and "regular expressions" in prompt
    assert version.startswith("induce-profile-")
    # Every name the validator accepts must be offered, or the model has nowhere
    # to put a field it can plainly see — which is exactly how a person
    # addressed by phone number ended up in a merchant's contact slot.
    assert "{counterparty_handle}" in prompt


# --- losslessness is structural, not checked afterwards ---------------------

def test_a_match_explains_the_whole_line():
    p = _profile("CARD PURCHASE {date} {brand} {city} {region}")
    assert p.apply("CARD PURCHASE 03/14 SAFEHARBOR MARKET PLANO TX")
    # Trailing text nothing claims: no partial parse, no match at all.
    assert p.apply("CARD PURCHASE 03/14 SAFEHARBOR MARKET PLANO TX 998877") is None


def test_date_slot_means_a_date():
    # The spelling a model would obviously reach for must mean what it looks
    # like; a vocabulary whose obvious form is the wrong one is a trap.
    p = _profile("PAID {date} {brand}")
    assert p.apply("PAID 03/14 SAFEHARBOR") is not None
    assert p.apply("PAID SOMEDAY SAFEHARBOR") is None


def test_adjacent_word_slots_give_the_brand_the_most_words():
    # `{brand} {city} {region}` is the commonest card shape there is, and the
    # split between three adjacent word slots is decided by greediness rather
    # than by anything the model said. The bias has to be the right one: a brand
    # runs to several words far more often than a city does.
    m = _profile("{brand} {city} {region}").apply("SAFEHARBOR MARKET PLANO TX")
    assert m.slots["brand"] == "SAFEHARBOR MARKET"
    assert m.slots["city"] == "PLANO" and m.slots["region"] == "TX"


def test_first_template_wins_so_order_is_part_of_the_grammar():
    p = _profile("ZELLE TO {counterparty} {reference}", "ZELLE TO {brand}")
    assert p.apply("ZELLE TO JOHN SMITH 22334455").template.endswith("{reference}")


def test_no_template_matching_is_a_legitimate_answer():
    assert _profile("ZELLE TO {counterparty}").apply("SOMETHING NEVER SEEN") is None


# --- privacy is a slot name -------------------------------------------------

def test_personal_and_shareable_are_decided_by_slot_not_by_text():
    p = _profile("ZELLE TO {counterparty} {reference}")
    m = p.apply("ZELLE TO JOHN SMITH 22334455")
    assert m.personal() == {"counterparty": "JOHN SMITH"}
    assert m.shareable() == {"reference": "22334455"}
    # The same words in a brand slot are shareable — the slot decides, not the
    # string, which is exactly what the substring gate could not do.
    m2 = _profile("PAID {brand}").apply("PAID JOHN SMITH")
    assert m2.shareable() == {"brand": "JOHN SMITH"} and m2.personal() == {}


def test_an_account_number_never_reaches_the_shareable_side():
    m = _profile("ONLINE TRANSFER TO {institution} {account_ref}").apply(
        "ONLINE TRANSFER TO NORTHBANK SAVINGS 8802")
    assert m.shareable() == {"institution": "NORTHBANK SAVINGS"}
    assert m.personal() == {"account_ref": "8802"}
    assert set(PERSONAL_SLOTS) <= set(SLOTS)


def test_noise_is_carried_but_never_shared():
    m = _profile("{brand} {noise}").apply("SAFEHARBOR MARKET PPD ID")
    assert "noise" not in m.shareable()


# --- coverage is measured on everything, not the sample ---------------------

def test_coverage_reports_the_lines_it_cannot_explain():
    p = _profile("CARD PURCHASE {date} {brand} {city} {region}")
    share, unmatched = p.coverage(["CARD PURCHASE 03/14 SAFEHARBOR PLANO TX",
                                   "CARD PURCHASE 04/02 GOLDEN FORK FRISCO TX",
                                   "ATM WITHDRAWAL 200"])
    assert round(share, 2) == 0.67 and unmatched == ["ATM WITHDRAWAL 200"]


def test_a_person_is_a_person_however_they_were_addressed():
    """The first real induction found the gap. Rule 7 said `{counterparty}` is
    for a person "you would recognise by name"; a phone number is not a name, so
    the model reached for `{contact}` — a merchant's public phone, declared
    shareable. The template it wrote could never fire (a bare number does not
    match the contact shape), so nothing leaked and nothing parsed either.

    A peer payment addresses the other party by name, phone, email or username.
    All four are the same thing, and all four are personal."""
    named = _profile("ZELLE TO {counterparty} {reference}").apply(
        "ZELLE TO MARIA GARCIA ABC123")
    by_phone = _profile("ZELLE TO {counterparty_handle} {reference}").apply(
        "ZELLE TO 7015550137 ABC123")
    by_email = _profile("ZELLE TO {counterparty_handle} {reference}").apply(
        "ZELLE TO maria@example.com ABC123")
    for m in (named, by_phone, by_email):
        assert m is not None and m.party()
        assert not (set(m.shareable()) & {"counterparty", "counterparty_handle"})
    assert by_phone.personal() == {"counterparty_handle": "7015550137"}


def test_a_contact_where_the_party_belongs_is_personal_by_STRUCTURE():
    """A released profile is never edited, so grammars already frozen keep their
    `{contact}` templates. This closes those without reading a character of the
    extracted value.

    A template describes a payment, and a payment has a party. A template naming
    no party at all — no brand, no institution, no counterparty — is a template
    whose remaining slot IS the party."""
    party = _profile("ZELLE TO {contact} {reference}").apply(
        "ZELLE TO 508-496-2249 ABC123")
    assert party.personal() == {"contact": "508-496-2249"}     # promoted
    assert party.shareable() == {"reference": "ABC123"}
    # ...and the same slot beside a brand is the MERCHANT's public number.
    merchant = _profile("CARD PURCHASE {date} {brand} {contact} {region}").apply(
        "CARD PURCHASE 01/18 STRONG HOME MTG 571-443-2000 VA")
    assert merchant.shareable()["contact"] == "571-443-2000"
    assert merchant.personal() == {}


# --- the pack: versioned, never edited -------------------------------------

def test_a_released_profile_cannot_be_overwritten(tmp_path):
    store = ProfileStore(tmp_path)
    store.write(_profile("ZELLE TO {counterparty}"))
    with pytest.raises(ProfileError):
        store.write(_profile("ZELLE TO {brand}"))         # same id, new meaning
    assert store.next_version("northbank", "depository") == "v2"
    store.write(_profile("ZELLE TO {brand}", version="v2"))
    assert store.latest("northbank", "depository").version == "v2"


def test_a_missing_version_is_raised_not_defaulted(tmp_path):
    store = ProfileStore(tmp_path)
    assert store.latest("northbank", "depository") is None      # nothing yet
    with pytest.raises(ProfileError):
        store.load("northbank-depository-v1")


def test_a_stored_profile_round_trips_and_is_validated_on_load(tmp_path):
    store = ProfileStore(tmp_path)
    path = store.write(_profile("CARD PURCHASE {date} {brand} {city} {region}"))
    back = store.load("northbank-depository-v1")
    assert back.apply("CARD PURCHASE 03/14 SAFEHARBOR PLANO TX")
    bad = json.loads(path.read_text())
    bad["templates"] = ["ZELLE TO {name}"]
    path.write_text(json.dumps(bad))
    with pytest.raises(ProfileError):
        store.load("northbank-depository-v1")            # refused at the door


def test_a_kind_whose_lines_name_no_party_gets_no_grammar(tmp_path):
    """An investment activity line describes a trade against a security, not a
    payment to anybody. There is no party in it for a slot to hold.

    Every name in this vocabulary asserts something about a party or a place, so
    a model shown trade activity must either miss the gate or force a realized
    gain into `{purpose}` and a security into `{brand}` — confidently, on every
    line that institution ever prints. Refused at the store, not at each call
    site, so the profile that should never have existed cannot be applied by
    whoever forgets."""
    store = ProfileStore(tmp_path)
    with pytest.raises(ProfileError):
        store.write(_profile("YOU SOLD {brand} {purpose}", kind="investment"))
    assert is_inducible("depository") and is_inducible("liability")
    assert not is_inducible("investment") and not is_inducible("")


def test_a_grammar_is_never_served_for_an_ineligible_kind(tmp_path):
    store = ProfileStore(tmp_path)
    store.write(_profile("ZELLE TO {counterparty}", kind="depository"))
    assert store.latest_for("northbank", "depository") is not None
    # Even if a file were placed by hand, the door refuses to open it.
    assert store.latest_for("northbank", "investment") is None
    assert set(INDUCIBLE_KINDS) == {"depository", "liability"}


def test_the_holdout_is_stable_so_two_runs_measure_the_same_thing():
    """Split by hash of the line, not at random and not by position.

    A random split makes today's number and next month's incomparable. A
    positional split moves when a dict is built differently. And a descriptor
    must keep its side as the vault grows, or the holdout stops being a holdout
    the moment it contains a line an earlier grammar was induced on."""
    counts = {f"LINE {chr(65 + i)}{chr(65 + j)} SOMETHING": i + j + 1
              for i in range(14) for j in range(14)}
    train, held = holdout_split(counts)
    assert train and held and len(held) / len(counts) == pytest.approx(0.2, abs=0.06)
    assert set(holdout_split(dict(reversed(list(counts.items()))))[1]) == set(held)
    grown = dict(counts, **{"A BRAND NEW LINE": 1})
    assert set(held) <= set(holdout_split(grown)[1])       # sides are sticky


def test_a_grammar_is_gated_on_lines_that_never_helped_choose_it():
    """`--best-of N` selects the best of N candidates. Selecting on the same set
    you then report turns an estimate into a maximum, and the bias grows with N.

    So the gate reads the holdout: lines the model never saw AND that took no
    part in choosing this grammar over another."""
    good = "ZELLE TO {counterparty} {reference}"
    lines = {f"ZELLE TO PERSON{chr(65+i)}{chr(65+j)} REF{i}{j}9": 2
             for i in range(12) for j in range(12)}
    ind = Inducer(lambda _p: json.dumps({"templates": [good]}),
                  rounds=1).induce("northbank", "depository", lines)
    assert ind.holdout is not None and ind.holdout_lines > 0
    assert ind.scored == ind.holdout            # the gate reads the honest one
    assert "withheld" in ind.verdict


def test_a_grammar_that_memorised_its_own_lines_is_caught_by_the_holdout():
    # Templates that reproduce the training lines exactly and generalise to
    # nothing: perfect where it was induced, useless where it was not.
    lines = {f"PAID SHOP{chr(65 + i)} PLANO TX": 1 for i in range(26)}
    train, held = holdout_split(lines)
    memorised = _profile(*[f"PAID {d.split()[1]} {{city}} {{region}}"
                           for d in sorted(train)])
    assert memorised.weighted_coverage(train) == 1.0
    assert memorised.weighted_coverage(held) == 0.0


def test_drift_shows_up_in_the_recent_number_long_before_the_lifetime_one():
    """The check the design claimed and the code never ran.

    Coverage was computed once and frozen into the profile, so a grammar could
    fall to half its measured number and still carry the number it had on the
    day it was written. And the lifetime figure is the slow one: old lines
    outnumber new, so a bank that changed its composition shows barely a dent
    there while the recent slice collapses."""
    p = _profile("ZELLE TO {counterparty} {reference}")
    p.measured = 1.0
    old = {f"ZELLE TO PERSON{chr(65+i)} REF{i}9": 5 for i in range(20)}
    new = {f"NEW SHAPE {chr(65+i)} XYZ": 5 for i in range(8)}
    d = drift(p, dict(old, **new), new)
    assert d["recent"] == 0.0 and d["recent_drop"] == 1.0    # collapsed
    assert d["now"] > 0.65                                   # barely dented
    assert d["drop"] < d["recent_drop"]


def test_a_grammar_is_verified_by_behaviour_not_by_provenance(tmp_path):
    """Why a grammar does not have to be induced once per user.

    A profile is slots and literals with no values in it — the bank's
    composition, identical for every customer of that bank. So a grammar
    somebody else induced is safe to try: apply it to your own lines and read
    the number. It either explains them or it does not.

    That check is what a merchant catalog cannot offer, and it is the reason
    only the FIRST customer of an institution has to pay for a model call."""
    store = ProfileStore(tmp_path)
    theirs = _profile("ZELLE PAYMENT TO {counterparty} {reference}",
                      "CARD PURCHASE {date} {brand} {city} {region}")
    store.write(theirs)

    mine = {"ZELLE PAYMENT TO MARIA GARCIA XY22": 10,
            "CARD PURCHASE 03/14 SAFEHARBOR MARKET PLANO TX": 5,
            "SOMETHING THIS BANK NEVER PRINTS": 1}
    downloaded = store.load("northbank-depository-v1")
    assert downloaded.weighted_coverage(mine) == 15 / 16     # no model call
    # ...and a grammar from the wrong bank says so, in the same number.
    wrong = _profile("PAIEMENT PAR CARTE {date} {brand}")
    assert wrong.weighted_coverage(mine) == 0.0


# --- induction ---------------------------------------------------------------

def test_lines_differing_only_in_a_date_are_one_shape_not_twenty_one():
    # The defect the first dry run exposed. Grouping on the raw line makes every
    # posting date its own group, so one template claims half the sample and the
    # rest of the statement is never shown.
    counts = {f"{m:02d}/{d:02d} PAYMENT TO CARD ENDING IN 0000": 1
              for m, d in [(1, 10), (1, 14), (2, 4), (2, 22), (3, 9), (12, 8)]}
    counts["ZELLE TO JOHN SMITH ABC123"] = 4
    assert len(skeletons(counts)) == 2


def test_a_word_printed_once_is_a_filler_and_a_word_repeated_is_a_literal():
    # Parameter-free, and it needs no list of known words — which is the whole
    # point, because a list of known words is the thing this design deleted.
    counts = {"LONGCREEK-SERVIC ACH PMT PPD ID: 1000000004": 3,
              "MEALPLANCO ACH PMT PPD ID: 1000000005": 2}
    (spine,) = skeletons(counts)
    # The two brand words occur once each, so both mask; every other word is
    # printed on both lines, so every other word survives as the literal spine.
    assert spine == "* ach pmt ppd id: #"


def test_the_sample_shows_every_shape_before_it_shows_any_shape_twice():
    counts = {f"ZELLE TO PERSON{i:02d} REF{i:04d}": 5 for i in range(30)}
    counts.update({f"CARD PURCHASE 03/{i:02d} SHOP TX": 1 for i in range(1, 4)})
    sample = sample_descriptors(counts, limit=6)
    assert sample[0].startswith("ZELLE") and sample[1].startswith("CARD")
    assert sample == sample_descriptors(counts, limit=6)      # deterministic


def test_within_a_shape_the_picks_are_unlike_each_other_not_the_commonest():
    # LogBatcher measured similarity-based selection at 7.7% worse than
    # diversity; a model learns where the hole is by seeing different fillers.
    counts = {"PAID ALPHA BETA GAMMA DELTA": 99, "PAID ALPHA BETA GAMMA EPSILON": 98,
              "PAID ZETA": 1}
    assert "PAID ZETA" in sample_descriptors(counts, limit=2)


def test_a_template_is_judged_by_what_it_MATCHES_not_by_its_words():
    """Replaces a check that flagged literal words appearing in one descriptor.

    On a real vault that fired nine times and was mostly wrong: it flagged
    `Payroll` in `{brand} Payroll PPD ID: {company_id}`, which is a genuine NACHA
    Company Entry Description and exactly the field the template was right to
    make literal — it only looked baked-in because one originator used it.

    Counting matches is the honest form of the same worry. Rule 4's "an example,
    not a grammar" is measurable; a name baked into literal text lands here too,
    because it can only ever match its own line."""
    corpus = ["ZELLE PAYMENT FROM ARJUN VARMA ABC1",
              "ZELLE PAYMENT FROM MARIA GARCIA XY22",
              "ZELLE PAYMENT FROM LI WEI QQ31"]
    narrow = narrow_templates(
        _profile("ZELLE PAYMENT FROM ARJUN {counterparty} {reference}"), corpus)
    assert narrow == {"ZELLE PAYMENT FROM ARJUN {counterparty} {reference}": 1}
    assert not narrow_templates(
        _profile("ZELLE PAYMENT FROM {counterparty} {reference}"), corpus)
    # A template matching NOTHING is the clearest case of all.
    assert narrow_templates(_profile("NEVER SEEN {brand}"), corpus) == {
        "NEVER SEEN {brand}": 0}


def test_a_worse_rerun_cannot_silently_become_the_grammar(tmp_path):
    """Induction is stochastic. The same prompt over the same forty lines gave
    27 templates at 84% one run and 33 at 82% the next, and the second was
    written because the gate is absolute — while `latest` wins by version number,
    so the weaker grammar went into use.

    A version must beat the one it succeeds, on the same measurement over the
    same lines."""
    counts = {"ZELLE TO JOHN SMITH 22334455": 40, "MYSTERY LINE 4": 60}
    store = ProfileStore(tmp_path)
    good = _profile("ZELLE TO {counterparty} {reference}", "MYSTERY LINE {reference}")
    store.write(good, against=counts)
    worse = _profile("ZELLE TO {counterparty} {reference}", version="v2")
    with pytest.raises(ProfileError):
        store.write(worse, against=counts)
    assert store.latest("northbank", "depository").version == "v1"   # unchanged
    # Deliberate is allowed; silent is not.
    store.write(worse, against=counts, force=True)
    assert store.latest("northbank", "depository").version == "v2"


def test_coverage_has_one_meaning(tmp_path):
    # Two numbers were printed under the same word — one weighted by movements
    # at induction time, one weighting every distinct line equally when
    # reporting an existing profile. 84% and 88% for the same grammar.
    counts = {"ZELLE TO JOHN SMITH 22334455": 99, "MYSTERY LINE 4": 1}
    p = _profile("MYSTERY LINE {reference}")
    unweighted, _ = p.coverage(list(counts))
    assert unweighted == 0.5                       # half the distinct lines
    assert p.weighted_coverage(counts) == 0.01     # one percent of the money


def test_an_unusable_template_is_dropped_without_sinking_the_call():
    reply = json.dumps({"templates": ["ZELLE TO {counterparty}",
                                      "ZELLE TO {name}",          # unknown slot
                                      "FIXED LINE"]})             # no holes
    p = parse_induction(reply, "northbank", "depository", "induce-profile-v1+prof-v1")
    assert [t.pattern for t in p.templates] == ["ZELLE TO {counterparty}"]


def test_nothing_usable_returns_none_rather_than_an_empty_grammar():
    assert parse_induction("no json here", "n", "d", "v") is None
    assert parse_induction('{"templates": ["FIXED LINE"]}', "n", "d", "v") is None


def test_a_wire_is_refused_a_grammar_however_good_the_template_looks():
    # An operator free-text field cannot honour any slot name, so the shape is
    # refused before templates are consulted — not after, or the refusal would
    # only be as strong as the templates that happen to exist today.
    wire = ("02/14 ONLINE DOMESTIC WIRE TRANSFER VIA: SOMEBANK NA/111014325 "
            "A/C: SOME TITLE LLC REF: 8000362/9021 SOME DRIVE IMAD: 0214X")
    assert _profile("{purpose} {noise}").apply(wire) is None
    # One marker is not a wire: an ordinary line may print "Ref" and still be
    # an ordinary line, and sweeping it up would refuse grammars for no reason.
    assert _profile("{purpose} {noise}").apply("PAYMENT REF 4429") is not None


def test_a_refused_line_is_excluded_from_coverage_not_counted_against_it():
    wire = ("WIRE TRANSFER VIA: SOMEBANK A/C: SOME LLC REF: X IMAD: 0214X")
    lines = {"ZELLE TO JOHN SMITH 22334455": 10, wire: 90}
    ind = Inducer(lambda _p: json.dumps(
        {"templates": ["ZELLE TO {counterparty} {trace}"]})).induce("n", "d", lines)
    # 90 of 100 movements are wires. Counted against the grammar it would score
    # 10%; excluded, the grammar explains everything it was ever allowed to.
    assert ind.accepted and ind.coverage == 1.0 and ind.refused == [wire]


def test_two_ids_on_one_line_are_two_names_not_one_name_twice():
    m = _profile("{brand} {purpose} {trace} WEB ID: {company_id}").apply(
        "MERIDIAN AUTOPAY PAYMENT 100200300400500 WEB ID: MERIDIANAP")
    assert m.slots["trace"] == "100200300400500"
    assert m.slots["company_id"] == "MERIDIANAP"
    assert m.personal() == {}          # both are the originator's, not yours


def test_an_account_ref_the_bank_masked_itself_still_matches():
    m = _profile("TRANSFER TO {institution} {account_ref}").apply(
        "TRANSFER TO NORTHBANK #####4321")
    assert m.personal() == {"account_ref": "#####4321"}
    # ...but the shape still needs a digit, so it cannot swallow a bare word.
    assert _profile("TRANSFER TO {account_ref}").apply("TRANSFER TO SAVINGS") is None


def test_the_loop_shows_each_round_only_what_the_last_one_missed():
    lines = {"ZELLE TO JOHN SMITH 22334455": 50, "ATM WITHDRAWAL 0412 PLANO TX": 50}
    seen, replies = [], iter([
        json.dumps({"templates": ["ZELLE TO {counterparty} {reference}"]}),
        json.dumps({"templates": ["ATM WITHDRAWAL {store_number} {city} {region}"]})])

    def fake(prompt):
        seen.append(prompt)
        return next(replies)

    ind = Inducer(fake, rounds=3).induce("northbank", "depository", lines)
    assert ind.rounds == 2 and ind.coverage == 1.0
    assert "JOHN SMITH" in seen[0] and "ATM WITHDRAWAL" in seen[0]   # round 1: all
    assert "JOHN SMITH" not in seen[1]                  # round 2: only leftovers
    assert "ATM WITHDRAWAL 0412" in seen[1]
    assert len(ind.profile.templates) == 2


def test_the_loop_stops_when_a_round_adds_nothing_new():
    lines = {"ZELLE TO JOHN SMITH 22334455": 5, "MYSTERY 4": 5}
    calls = []

    def fake(prompt):
        calls.append(prompt)
        return json.dumps({"templates": ["ZELLE TO {counterparty} {reference}"]})

    ind = Inducer(fake, rounds=3, min_coverage=0.4).induce("n", "d", lines)
    assert len(calls) == 2 and ind.rounds == 2       # not 3 — it stopped early
    assert ind.accepted and ind.unmatched == ["MYSTERY 4"]


def test_a_grammar_that_explains_the_rare_lines_and_misses_the_mass_fails():
    """Coverage is weighted by movements, on both sides of the split.

    A template that explains twenty rare lines and misses the daily one is not
    most-of-the-way right; it is wrong about nearly all the money. The corpus
    below gives the heavy shape many variants so the holdout cannot land it all
    on one side — the guard has to hold however the split falls."""
    lines = {f"CARD PURCHASE 03/{i + 1:02d} SHOP{chr(65 + i)} PLANO TX": 1
             for i in range(20)}
    lines.update({f"ATM WITHDRAWAL {chr(65 + i)} PLANO TX": 40 for i in range(20)})
    ind = Inducer(lambda _p: json.dumps(
        {"templates": ["CARD PURCHASE {date} {brand} {city} {region}"]}),
        sample_size=40, min_coverage=0.80, rounds=1).induce(
            "northbank", "depository", lines)
    assert not ind.accepted and ind.scored < 0.10
    assert "below the" in ind.verdict


def test_an_accepted_grammar_carries_its_number_and_its_leftovers():
    lines = {"ZELLE TO JOHN SMITH 22334455": 30,
             "ZELLE TO MARIA GARCIA 99887766": 10,
             "MYSTERY LINE 4": 1}
    ind = Inducer(lambda _p: json.dumps(
        {"templates": ["ZELLE TO {counterparty} {reference}"]}),
        min_coverage=0.80, rounds=1).induce("northbank", "depository", lines)
    assert ind.accepted and ind.unmatched == ["MYSTERY LINE 4"]
    assert round(ind.coverage, 3) == round(40 / 41, 3)
    assert ind.profile.induced_from == 3


# --------------------------------------- rule 4 and the bank's fixed phrases


def _reply(*templates):
    import json
    return json.dumps({"templates": list(templates)})


def test_a_fee_line_is_a_grammar_when_the_bank_prints_it_repeatedly():
    """A fee has no variable part. `Payment Thank You - Web` is the identical
    string every month, and that constancy is what the line IS. Rule 4 refused
    every slotless template; on the first live agent run those were proposed
    correctly and dropped twenty-odd times, burning a round of calls per attempt
    and leaving the commonest line on a card statement unexplained."""
    from merchantcore.induce import parse_induction
    counts = {"Payment Thank You - Web": 14,
              "Card Purchase 03/04 Shop A Plano TX": 9}
    p = parse_induction(_reply("Payment Thank You - Web"), "Chase", "liability",
                        "v", counts=counts)
    assert p is not None and len(p.templates) == 1
    assert p.apply("Payment Thank You - Web") is not None


def test_a_line_seen_once_is_still_an_example_not_a_grammar():
    """The half of rule 4 that was always right: a template that reproduces one
    line memorised the sample, and a name baked into literal text lands here too
    because it can only ever match its own line."""
    from merchantcore.induce import parse_induction
    counts = {"Some One Off Line": 1}
    assert parse_induction(_reply("Some One Off Line"), "Chase", "liability",
                           "v", counts=counts) is None


def test_a_truncated_template_explains_nothing_and_is_still_dropped():
    """`Non-Chase ATM Fee-With` — the model's own truncation of a real line. It
    is still refused, now for the reason that is actually true of it rather than
    for having no slots."""
    from merchantcore.induce import parse_induction
    counts = {"Non-Chase ATM Fee-Withdrawal": 22}
    assert parse_induction(_reply("Non-Chase ATM Fee-With"), "Chase",
                           "depository", "v", counts=counts) is None


def test_without_counts_the_old_rule_still_holds():
    """No evidence means no exception. A caller that cannot say how often a line
    occurs gets the conservative answer, not the permissive one."""
    from merchantcore.induce import parse_induction
    assert parse_induction(_reply("Payment Thank You - Web"), "Chase",
                           "liability", "v") is None


def test_the_pack_rules_version_is_not_the_storage_format():
    """Bumping PROFILE_FORMAT to announce a rule change would make every grammar
    already on disk unloadable and reshuffle the holdout salt — punishing the
    work for the improvement. PACK_RULES says what a fresh induction would now
    do differently; nothing loads by it and nothing is salted by it."""
    from merchantcore.induce import machinery_version
    from merchantcore.profile import PACK_RULES, PROFILE_FORMAT
    assert PACK_RULES != PROFILE_FORMAT
    assert PACK_RULES in machinery_version() and PROFILE_FORMAT in machinery_version()


# ---------------------------- the rules are written twice; keep them agreeing


def test_the_prompt_and_the_code_agree_about_fixed_phrases():
    """The pack rules exist in two forms — STATED in the prompt and ENFORCED in
    code — and only the enforcement carries `PACK_RULES`. They diverged once:
    the code was taught that a bank's fixed phrase is a template while rule 4 of
    the prompt went on calling it useless, so the single largest unexplained
    line in a real vault was being discouraged and then accepted when the model
    disobeyed. This is the cheapest guard against that happening silently
    again."""
    import re
    from merchantcore.induce import INDUCTION_VERSION, build_induction_prompt
    prompt, version = build_induction_prompt(["ANY LINE"])
    assert version.startswith(INDUCTION_VERSION)
    # Whitespace-normalised: the prompt is hard-wrapped for a human to read, and
    # a test that broke when a line was rewrapped would be a test about wrapping.
    low = re.sub(r"\s+", " ", prompt.lower())
    # The exception must be stated, not merely tolerated by the parser.
    assert "no holes at all" in low
    assert "fee" in low and "identical string every time" in low
    # And the two failures the first live run produced.
    assert "at most once" in low, "a repeated hole name discards the template"
    assert "truncated" in low, "a shortened fixed phrase matches nothing"


def test_every_recorded_prompt_version_still_resolves():
    """T8: a recorded version must always resolve. A superseded prompt is kept,
    never edited over — a grammar induced under v1 names v1, and that name has
    to keep meaning the text it meant."""
    from vivacore import promptstore
    from merchantcore.induce import PROMPTS
    have = set(promptstore.ids(PROMPTS))
    assert {"induce-profile-v1", "induce-profile-v2"} <= have
    assert promptstore.load(PROMPTS, "induce-profile-v1") != \
        promptstore.load(PROMPTS, "induce-profile-v2")


# ------------------------------------ {brand} must be able to hold a merchant


def _brand_city_region():
    return Template("{brand} {city} {region}")


def test_a_card_merchant_name_fits_in_the_brand_slot():
    """The finding that explained a whole account. On a real credit card
    statement the merchant IS the line, so a merchant the vocabulary cannot
    express is a completely unexplained line — which is why one account sat at
    79% against an 80% gate through six independent inductions."""
    rx = _brand_city_region().compile()
    for line, brand in (
            ("278 BRAUMS STORE ALLEN TX", "278 BRAUMS STORE"),
            ("4977 GREAT CLIPS AT SIGNA PLANO TX", "4977 GREAT CLIPS AT SIGNA"),
            ("QUALITY INN & SUITES PEARL MS", "QUALITY INN & SUITES"),
            ("TST* TEXAS CARD HOUSE - D Dallas TX", "TST* TEXAS CARD HOUSE - D"),
            ("SPICE RACK GROCERY PLANO TX", "SPICE RACK GROCERY")):
        m = rx.match(line)
        assert m, f"{line!r} matched nothing"
        assert m.group("brand") == brand, f"{line!r} slotted as {m.group('brand')!r}"
        assert m.group("region") in ("TX", "MS")


def test_a_hash_is_left_out_because_it_slots_wrongly():
    """`CIRCLE K # 03453 WEST MONROE LA` matches once `#` is admitted, and files
    the brand as `CIRCLE K # 03453 WEST` with the city as `MONROE`. A confident
    wrong answer where a miss was honest. The right fix is a template writing
    `#` as literal text with {store_number} after it."""
    assert _brand_city_region().compile().match("CIRCLE K # 03453 WEST MONROE LA") is None
    ok = Template("{brand} # {store_number} {city} {region}").compile()
    m = ok.match("CIRCLE K # 03453 WEST MONROE LA")
    assert m and m.group("brand") == "CIRCLE K" and m.group("store_number") == "03453"
    assert m.group("city") == "WEST MONROE"


def test_a_name_may_not_start_with_a_digit_and_a_merchant_string_may():
    """The distinction the two shapes exist to draw.

    A counterparty is a person's NAME and a city is a place's; letting either
    begin with a digit would let them swallow a store id or a date fragment. A
    merchant string genuinely does — `278 BRAUMS STORE` — and so does filler:
    a UK card line ends `ON 12 MAR`."""
    from merchantcore.profile import DEFAULT_SHAPE, SLOT_SHAPE, shape_for
    assert shape_for("brand", None) == shape_for("noise", None) == "merchant"
    assert shape_for("counterparty", None) == DEFAULT_SHAPE == "words"
    assert shape_for("city", None) == shape_for("institution", None) == "words"
    assert sorted(k for k, v in SLOT_SHAPE.items() if v == "merchant") == \
        ["brand", "noise"]

    import re
    from merchantcore.profile import SHAPES
    name, string = re.compile(SHAPES["words"]), re.compile(SHAPES["merchant"])
    assert not name.fullmatch("12 MAR") and string.fullmatch("12 MAR")
    assert name.fullmatch("HDFC0000123"), "a bank code is a name with digits in it"


def test_a_wider_shape_only_ever_matches_more():
    """Why PROFILE_FORMAT stays prof-v1. Every grammar already on disk still
    loads and still means what it meant, and the holdout salt does not move —
    which is what makes a before/after measurement comparable at all."""
    import re
    from merchantcore.profile import PROFILE_FORMAT, SHAPES
    assert PROFILE_FORMAT == "prof-v1"
    narrow, wide = re.compile(SHAPES["words"]), re.compile(SHAPES["merchant"])
    for s in ("SPICE RACK GROCERY", "CARENOW ALLEN", "MVP FOODS", "WHOOP"):
        assert narrow.fullmatch(s) and wide.fullmatch(s)


# ------------------------------- the vocabulary outside the United States


CROSS_COUNTRY = [
    ("US card",    "SPICE RACK GROCERY PLANO TX", "{brand} {city} {region}"),
    ("US card",    "TST* TEXAS CARD HOUSE - D Dallas TX", "{brand} {city} {region}"),
    ("IN UPI",     "UPI-SWIGGY-SWIGGY@YBL-YESB0000001-123456789012",
                   "UPI-{brand}-{counterparty_handle}-{institution}-{trace}"),
    ("IN POS",     "POS 4213XXXXXXXX1234 RELIANCE SMART BAZAAR",
                   "POS {account_ref} {brand}"),
    ("IN NEFT",    "NEFT-CITIN12345678-RAHUL SHARMA-HDFC0000123",
                   "NEFT-{trace}-{counterparty}-{institution}"),
    ("IN IMPS",    "IMPS/P2A/123456789012/RAHUL/SBIN0001234",
                   "IMPS/{noise}/{trace}/{counterparty}/{institution}"),
    ("UK card",    "CARD PAYMENT TO TESCO STORES 3286 ON 12 MAR",
                   "CARD PAYMENT TO {brand} ON {noise}"),
    ("UK DD",      "DIRECT DEBIT PAYMENT TO BRITISH GAS REF 1234567",
                   "DIRECT DEBIT PAYMENT TO {brand} REF {reference}"),
    ("UK FPS",     "FASTER PAYMENT TO J SMITH REF RENT",
                   "FASTER PAYMENT TO {counterparty} REF {purpose}"),
    ("DE SEPA",    "SEPA-LASTSCHRIFT DEUTSCHE TELEKOM MANDAT M12345",
                   "SEPA-LASTSCHRIFT {brand} MANDAT {reference}"),
    ("FR carte",   "CARTE 12/03 CARREFOUR MARKET PARIS",
                   "CARTE {date} {brand} {city}"),
    ("DE accents", "CAFÉ MÜLLER MÜNCHEN DE", "{brand} {city} {region}"),
    ("BR accents", "MERCADO LIVRE SÃO PAULO BR", "{brand} {city} {region}"),
    ("IN script",  "स्विगी बेंगलुरु KA",
                   "{brand} {city} {region}"),
    ("JP script",  "セブンイレブン 東京 JP",
                   "{brand} {city} {region}"),
]


def test_the_vocabulary_can_express_a_statement_line_from_five_countries():
    """The regression test for a US-shaped assumption.

    Every shape here was `[A-Za-z]`, and on this list eight of fifteen could not
    be expressed AT ALL — accented Latin, Devanagari, Japanese, and every Indian
    rail whose bank code is letters followed by digits. Induction is
    country-agnostic in principle because the templates come from a model; the
    vocabulary was the only thing stopping it, and this is that claim measured
    rather than asserted."""
    cannot = [(tag, line) for tag, line, tmpl in CROSS_COUNTRY
              if not Template(tmpl).compile().match(line)]
    assert not cannot, f"inexpressible: {cannot}"
