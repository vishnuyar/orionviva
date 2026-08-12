"""Streams — the deterministic half, and the invariant that makes it trustworthy.

There are no hypotheses here yet, deliberately, so every one of these tests can
be checked against a statement by hand. The one that matters most is
`test_ingest_order_never_changes_a_belief`: it is the property that lets one
person hand over a year in an afternoon and another hand over a statement a month
and both be served the same answers.

**What the descriptors below are and are not.** They are invented. They are
regression fixtures for behaviour already decided — they pin *this code's*
properties so a later change cannot silently alter them. They are **not evidence
about what institutions print**, and no rule in this package may be designed or
tuned by watching them come out right. That is circular: it validates a guess
about bank formats against the same guess.

Where a real layout is needed, it comes from a specification (the NACHA batch
header, ISO 8583 DE43) or from a real statement with names replaced — and the
test says which. Thresholds are never asserted here; they are calibrated against
a real vault by `viva.streams_report --calibrate`.
"""

import random
import types
from datetime import date
from decimal import Decimal

from merchantcore.descriptor import linted_example, split_ach_heads, word_owners
from merchantcore.profile import Profile, Template
from merchantcore.resolve import resolve_descriptor
from viva.ledger.streams import (ACTIVITY, COUNTERPARTY, IN, INTERNAL, MIXED,
                                 OUT, build_streams)


def M(d, amount, desc, account="chk"):
    """A movement in the shape the LEDGER actually emits.

    `MovementInfo.date` is an ISO **string**, not a `date` — every other
    projection compares them lexically. An earlier version of these fixtures used
    `date` objects, so the whole suite passed against a shape the system never
    produces and the first real vault raised `str - str`. Fixtures follow the
    real type; that is what makes them regression tests rather than wishes."""
    return types.SimpleNamespace(date=d.isoformat() if isinstance(d, date) else d,
                                 amount=Decimal(amount),
                                 account=account, description=desc)


def _life():
    """A small financial life: three card merchants, a payroll, a utility, rent."""
    mv = []
    for i in range(6):
        mv.append(M(date(2026, i + 1, 3), "-15.49",
                    f"CARD PURCHASE 0{i+1}/03 STREAMCO CA"))
        mv.append(M(date(2026, i + 1, 7), "-42.10",
                    f"CARD PURCHASE 0{i+1}/07 GOLDEN FORK BISTRO TX"))
        mv.append(M(date(2026, i + 1, 19), "-9.99",
                    f"CARD PURCHASE 0{i+1}/19 CLOUDSTORE WA"))
        mv.append(M(date(2026, i + 1, 1), "-2400.00", "RENT OAKRIDGE PROPERTY MGMT"))
    for i in range(12):
        mv.append(M(date(2026, (i // 2) + 1, (i % 2) * 14 + 5), "3120.55",
                    "Cedarline Holdings Payroll PPD ID: 1000000005"))
    for i, amt in enumerate(["-88.12", "-131.40", "-102.77", "-95.30"]):
        mv.append(M(date(2026, i + 2, 9), amt, "Utilityco Bill Pay PPD ID: 4001"))
    return mv


# --- the invariant ----------------------------------------------------------

def test_ingest_order_never_changes_a_belief():
    """The stream projection is a pure function of the SET of movements.

    Someone who loads a year in one afternoon and someone who loads one statement
    a month must reach identical conclusions about identical money. Every
    tempting optimisation in this module — incremental features, statistics
    cached by last-seen — breaks this quietly, so it is asserted rather than
    argued."""
    mv = _life()
    base = [s.to_dict() for s in build_streams(mv)]
    for seed in (1, 7, 42, 99):
        shuffled = mv[:]
        random.Random(seed).shuffle(shuffled)
        assert [s.to_dict() for s in build_streams(shuffled)] == base


def test_a_drip_user_and_a_bulk_user_converge():
    """Not the same as shuffling: the drip user genuinely has less evidence early
    and must not be *wrong*, only less certain. By the time the sets match, the
    conclusions must too."""
    mv = sorted(_life(), key=lambda m: m.date)
    early = build_streams(mv[:6])
    assert all(f.cadence_class in ("unknown", "irregular")           # honest
               for s in early for f in s.flows)
    assert [s.to_dict() for s in build_streams(mv)] == \
           [s.to_dict() for s in build_streams(list(reversed(mv)))]


# --- the key ----------------------------------------------------------------

def test_one_counterparty_on_two_rails_is_two_streams():
    # A retailer you subscribe to AND shop at, one institution taking both a
    # sweep and a repayment: keyed on counterparty alone, the interval and
    # amount statistics are computed over a mixture and describe nothing.
    mv = [M(date(2026, 1, 5), "-9.99", "CARD PURCHASE 01/05 CLOUDSTORE WA"),
          M(date(2026, 2, 5), "-9.99", "CARD PURCHASE 02/05 CLOUDSTORE WA"),
          M(date(2026, 1, 20), "-250.00", "Cloudstore Invoice PPD ID: 7788")]
    channels = {s.channel for s in build_streams(mv)}
    assert channels == {"card", "ach"}


def test_a_merchant_with_one_proven_channel_does_not_split_across_templates():
    """Where a counterparty's own lines prove exactly one rail, its unproven
    lines are keyed to that rail.

    A grammar claims a merchant's lines with several templates and only one of
    them carries the structure that proves a channel; purchase, recurring
    payment and refund are one stream on that channel, not three streams keyed
    by template."""
    prof = Profile("nb", "dep", "v1",
                   [Template("CARD PURCHASE {date} {brand} {region}"),
                    Template("RECURRING PAYMENT {brand}"),
                    Template("REFUND {brand}")])
    mv = [M("2026-01-05", "-9.99", "CARD PURCHASE 01/05 CLOUDSTORE WA"),
          M("2026-02-05", "-9.99", "RECURRING PAYMENT CLOUDSTORE"),
          M("2026-03-05", "9.99", "REFUND CLOUDSTORE")]
    (s,) = build_streams(mv, lambda m: prof)
    assert s.channel == "card" and s.n == 3


def test_an_atm_withdrawal_and_a_cheque_still_separate():
    """Where nothing about a counterparty proves a channel, the template stands
    in for the rail, so one counterparty on two templates is two streams — cash
    over a counter is not a cheque. A single line resolved with no corpus behind
    it gives the same answer."""
    prof = Profile("nb", "dep", "v1",
                   [Template("ATM WITHDRAWAL {date} {brand} {city}"),
                    Template("CHEQUE {reference} {brand}")])
    mv = [M("2026-01-05", "-100.00", "ATM WITHDRAWAL 01/05 OAKRIDGE PLANO"),
          M("2026-02-05", "-250.00", "CHEQUE AB1234 OAKRIDGE")]
    streams = build_streams(mv, lambda m: prof)
    assert {s.counterparty for s in streams} == {"oakridge"}     # one counterparty
    assert len(streams) == 2                                     # two rails
    assert all(s.channel.startswith("tmpl:") for s in streams)
    # And the same answer from one line with no corpus behind it.
    assert (resolve_descriptor("CHEQUE AB1234 OAKRIDGE", prof).rail
            == "tmpl:CHEQUE {reference} {brand}")


# Two parties, addressed each of the ways the closed vocabulary can name one.
_PARTIES = {"counterparty": ("ARJUN VARMA", "PRIYA NAIR"),
            "counterparty_handle": ("arjun@example.test", "priya@example.test"),
            "brand": ("CLOUDSTORE", "STREAMCO"),
            "contact": ("214-555-0142", "214-555-0199")}

# The words a bank prints around the party — including the ones naming the
# conduit the money crossed rather than whoever was at the other end of it.
_FRAMES = ("PAYMENT TO <party>",
           "PAYMENT VIA {institution} TO <party>",
           "{institution} TRANSFER <party> REF {reference}",
           "PAYMENT <party> {trace} VIA {institution}")

_FILLER = {"{institution}": "NORTHBANK", "{reference}": "AB1234",
           "{trace}": "990011"}


def _party_lines():
    """`(template, line, other line)` for every way this vocabulary names a
    party, in every frame. The two lines differ in the party and in nothing
    else."""
    for frame in _FRAMES:
        for slot, (one, two) in sorted(_PARTIES.items()):
            pattern = frame.replace("<party>", "{%s}" % slot)
            lines = []
            for value in (one, two):
                line = pattern.replace("{%s}" % slot, value)
                for hole, filler in _FILLER.items():
                    line = line.replace(hole, filler)
                lines.append(line)
            yield (pattern, *lines)


def test_a_stream_key_never_drops_the_party():
    """Two movements differing only in who was on the other side never land in
    one stream.

    Asserted over the shape of a template rather than over one bank's line: every
    slot the closed vocabulary can name a party with, in every frame a bank
    prints around one."""
    for pattern, one, two in _party_lines():
        prof = Profile("nb", "dep", "v1", [Template(pattern)])
        streams = build_streams([M("2026-01-05", "-10.00", one),
                                 M("2026-02-05", "-10.00", two)],
                                lambda m: prof)
        assert len({s.counterparty for s in streams}) == 2, pattern


def test_an_institution_never_occupies_the_brand_slot():
    """The same property at the layer that names a brand: a template naming an
    institution and no brand resolves to no brand, leaving the key on the whole
    line rather than on the conduit everyone reached that way shares."""
    for pattern, line, _other in _party_lines():
        if "{brand}" in pattern:
            continue
        res = resolve_descriptor(line, Profile("nb", "dep", "v1",
                                               [Template(pattern)]))
        assert res.brand == "", pattern


def test_word_recurrence_is_a_diagnostic_and_decides_nothing():
    """A rule that stripped "the bank's words" from brand candidates was removed
    on 2026-07-28, after a real vault falsified it.

    It classified a word as the bank's when it appeared under enough distinct
    counterparties. On 1,076 real movements the ranking interleaved three
    populations — the bank's sentence words, city names, and merchants — so no
    threshold separated them: cut high and the ACH markers are missed, cut low
    and merchant names are destroyed. The count was also circular, since
    normalization fragments one merchant into many keys and a merchant with
    fifteen spellings looked like fifteen counterparties agreeing.

    `word_owners` survives as evidence for the streams report. This test exists
    to keep it evidence: it must describe, and never decide."""
    owners = word_owners(m.description for m in _life())
    assert owners["purchase"] and owners["streamco"]      # it counts everything
    # and nothing in the resolution path consults it
    import merchantcore.resolve as R
    assert "word_owners" not in R.__dict__


def test_over_cleaning_a_brand_is_worse_than_under_cleaning_it():
    """The asymmetry that decided the removal, stated as a test.

    An unstripped key is ugly and still unique per counterparty — recoverable
    later by any better layer. A stripped key that lost the merchant's name is
    indistinguishable from every other line the bank prefixed the same way, and
    nothing downstream can tell that something was removed."""
    mv = [M("2026-01-05", "-9.99", "CARD PURCHASE 01/05 CLOUDSTORE WA"),
          M("2026-02-05", "-9.99", "CARD PURCHASE 02/05 CLOUDSTORE WA"),
          M("2026-01-09", "-42.10", "CARD PURCHASE 01/09 GOLDEN FORK BISTRO TX"),
          M("2026-02-09", "-42.10", "CARD PURCHASE 02/09 GOLDEN FORK BISTRO TX")]
    names = {s.counterparty for s in build_streams(mv)}
    assert len(names) == 2                       # still distinct, if inelegant


# --- direction -------------------------------------------------------------

def _two_way():
    """A counterparty money moves both ways with: six equal payments out on the
    same day of each month, and three unequal amounts back at no rhythm.

    The shape of a brokerage (contributions out, distributions in), of a loan to
    a friend (lent out, repaid in), of a mortgage."""
    line = "Northline Brokerage Contrib PPD ID: 5001"
    out = [M(date(2026, m, 5), "-500.00", line) for m in range(1, 7)]
    back = [M(date(2026, 2, 17), "120.40", line),
            M(date(2026, 3, 2), "38.10", line),
            M(date(2026, 6, 21), "902.55", line)]
    return out + back


def test_a_steady_outflow_keeps_its_rhythm_when_money_comes_back():
    """The outflow reports monthly and fixed while the inflows, whose dates
    interleave with it at no rhythm, report irregular and variable. The stream
    is recurring because one of its directions is."""
    (s,) = build_streams(_two_way())
    assert s.direction_mix == "both" and s.n == 9
    assert s.flow(OUT).cadence_class == "monthly"
    assert s.flow(OUT).amount_stability == "fixed"
    assert s.flow(OUT).day_of_month_is_stable
    assert s.flow(IN).cadence_class == "irregular"
    assert s.flow(IN).amount_stability == "variable"
    assert s.recurring                    # because one of its directions is


def test_one_relationship_stays_one_stream():
    """Direction splits the statistics and never the key. Two-way movement with
    one counterparty on one rail is one relationship — a refund belongs to the
    merchant that took the payment — so the split is in what is measured, not in
    what is counted."""
    streams = build_streams(_two_way())
    assert len(streams) == 1 and len(streams[0].flows) == 2


def test_no_rhythm_is_offered_across_two_directions():
    """Every rhythm statistic is on the flow and absent from the stream, so a
    figure averaged over both directions is not merely unused — it cannot be
    read at all."""
    (s,) = build_streams(_two_way())
    for name in ("cadence_class", "amount_stability", "amount_cv",
                 "interval_is_steady", "median_interval_days",
                 "day_of_month_is_stable"):
        assert not hasattr(s, name), name
        assert all(hasattr(f, name) for f in s.flows), name


# --- what a stream is allowed to say ---------------------------------------

def test_cadence_and_stability_are_measured_not_asked_for():
    streams = {s.counterparty: s for s in build_streams(_life())}
    utility = streams["utilityco bill pay"].flow(OUT)
    payroll = streams["cedarline holdings payroll"].flow(IN)
    assert utility.cadence_class == "monthly" and utility.amount_stability == "variable"
    assert payroll.cadence_class == "biweekly" and payroll.amount_stability == "fixed"


def test_below_the_floor_it_says_unknown_rather_than_guessing():
    mv = [M(date(2026, 1, 5), "-9.99", "CARD PURCHASE 01/05 CLOUDSTORE WA"),
          M(date(2026, 2, 5), "-9.99", "CARD PURCHASE 02/05 CLOUDSTORE WA")]
    (s,) = build_streams(mv)
    # Two observations is one interval, and one interval is not a rhythm.
    assert s.n == 2 and s.flow(OUT).cadence_class == "unknown" and not s.recurring


def test_dates_arrive_as_iso_strings_and_intervals_still_work():
    """The regression. The ledger stores ISO strings; a stream subtracts dates.

    This is the first place in the project where those two facts meet, and the
    fixtures that missed it were the ones using a type the ledger never emits."""
    mv = [M("2026-01-05", "-9.99", "CARD PURCHASE 01/05 CLOUDSTORE WA"),
          M("2026-02-05", "-9.99", "CARD PURCHASE 02/05 CLOUDSTORE WA"),
          M("2026-03-05", "-9.99", "CARD PURCHASE 03/05 CLOUDSTORE WA")]
    (s,) = build_streams(mv)
    assert s.flow(OUT).median_interval_days == 29.5
    assert s.flow(OUT).cadence_class == "monthly"


def test_a_movement_with_an_unreadable_date_is_skipped_not_defaulted():
    mv = [M("2026-01-05", "-9.99", "CARD PURCHASE 01/05 CLOUDSTORE WA"),
          M("", "-9.99", "CARD PURCHASE CLOUDSTORE WA"),
          M("2026-02-05", "-9.99", "CARD PURCHASE 02/05 CLOUDSTORE WA"),
          M("2026-03-05", "-9.99", "CARD PURCHASE 03/05 CLOUDSTORE WA")]
    (s,) = build_streams(mv)
    # Defaulting it to today would not add noise — it would make the cadence wrong.
    assert s.n == 3 and s.flow(OUT).cadence_class == "monthly"


def test_a_single_amount_has_no_variation_and_says_so():
    (s,) = build_streams([M(date(2026, 1, 5), "-9.99", "CARD PURCHASE 01/05 CLOUDSTORE WA")])
    # 0.0 would read as "perfectly fixed"; it means "nothing to compare".
    assert s.flow(OUT).amount_cv is None
    assert s.flow(OUT).amount_stability == "unknown"


def test_a_day_of_month_anchor_survives_weekend_drift():
    mv = [M(date(2026, m, d), "-2400.00", "RENT OAKRIDGE PROPERTY MGMT")
          for m, d in ((1, 1), (2, 2), (3, 1), (4, 3), (5, 1))]
    (s,) = build_streams(mv)
    assert s.flow(OUT).day_of_month_is_stable
    assert s.flow(OUT).cadence_class == "monthly"


def test_money_that_never_left_your_life_is_marked_not_measured():
    """From a real vault: the two largest streams by count were a person paying
    their own credit cards, and dozens of singletons were brokerage activity
    lines. A capital-gain phrase minted a stream key of its own.

    Both were already decided elsewhere — `linked` by the transfer matcher,
    `nature` by the five-rung derivation — so a stream that ignored them re-asked
    a question the ledger had answered. Marked rather than dropped: dropping
    hides movements the totals still contain."""
    card_payment = M("2026-01-10", "-250.00", "PAYMENT TO CARD ENDING IN 0000")
    card_payment.linked = True
    ruled = M("2026-01-11", "-500.00", "TRANSFER TO SAVINGS")
    ruled.linked = True
    activity = M("2026-01-12", "8774.75", "You Sold Short-term loss: $548.74")
    ordinary = M("2026-01-13", "-15.49", "GOLDEN FORK BISTRO PLANO TX")
    streams = build_streams([card_payment, ruled, activity, ordinary],
                            kind_for=lambda m: "investment"
                            if m is activity else "depository")
    roles = {s.counterparty: s.role for s in streams}
    assert roles["payment to card ending in"] == INTERNAL
    assert roles["transfer to savings"] == INTERNAL
    assert roles["you sold short term loss 74"] == ACTIVITY
    assert roles["golden fork bistro"] == COUNTERPARTY
    assert len(streams) == 4          # all four still present


def test_a_partly_linked_counterparty_is_ONE_stream_reported_as_mixed():
    """The correction. Role was part of the key, and a real vault split one
    counterparty in two the moment the transfer matcher linked some of its
    movements and not others — the same money twice under one name, which is
    the failure this module exists to prevent.

    A stream whose occurrences disagree is `mixed`, and `linked_share` is the
    size of the gap. That is a finding about the transfer matcher, not a second
    counterparty."""
    a = M("2026-01-10", "-250.00", "ACME SERVICES")
    a.linked = True
    b = M("2026-01-20", "-40.00", "ACME SERVICES")
    (st,) = build_streams([a, b])
    assert st.role == MIXED and st.linked_share == 0.5


def test_role_never_consults_a_spending_judgement():
    """A mortgage servicer came back `internal` because `nature` said transfer.

    `nature` answers "does this count as spending?"; role answers "is there
    someone on the other side?" A mortgage payment is not spending and still has
    a party. Only a live transfer link proves the other side is yours."""
    m = M("2026-01-01", "-4395.38", "LONGCREEK-SERVIC ACH PMT PPD ID: 1000000004")
    m.nature = "transfer"            # deliberately set, and deliberately ignored
    (st,) = build_streams([m])
    assert st.role == COUNTERPARTY


def test_a_single_word_merchant_behind_a_bank_prefix_is_NOT_recovered():
    """A known, accepted loss — recorded so it is not rediscovered as a surprise.

    Layer 0 claims the token before a trailing region code as the city, because
    DE43 says that is where a city goes. When a bank prefixes its own sentence
    AND the merchant is a single word, the merchant lands in the city slot and
    what remains is the bank's prefix. Both lines below therefore key alike.

    A rule that stripped 'the bank's words' was tried and removed: on a real
    vault, bank words, city names and merchant names interleave by frequency, so
    no cut separates them, and a cut low enough to catch the ACH markers deletes
    merchant names. Under-cleaning leaves an ugly key that is still unique per
    counterparty; over-cleaning silently merges unrelated merchants. This is the
    cost of choosing the recoverable error.

    An induced grammar removes the loss entirely — the bank's prefix becomes
    literal template text and the merchant becomes `{brand}`."""
    mv = [M("2026-01-05", "-9.99", "CARD PURCHASE 01/05 CLOUDSTORE WA"),
          M("2026-02-05", "-4.99", "CARD PURCHASE 02/05 STREAMCO CA")]
    assert len(build_streams(mv)) == 1              # merged, and we know why
    # A multi-word merchant survives, which is why a real vault still shows
    # many distinct card streams rather than one.
    mv2 = [M("2026-01-09", "-42.10", "CARD PURCHASE 01/09 GOLDEN FORK BISTRO TX"),
           M("2026-01-11", "-63.00", "CARD PURCHASE 01/11 NORTHGATE FUEL CO TX")]
    assert len(build_streams(mv2)) == 2


# --- the boundary -----------------------------------------------------------

def test_a_grammar_names_the_person_and_the_rail_together():
    prof = Profile("nb", "dep", "v1",
                   [Template("ZELLE PAYMENT FROM {counterparty} {reference}")])
    r = resolve_descriptor("ZELLE PAYMENT FROM ARJUN VARMA BACV0WJMIHFE", prof)
    assert r.is_person and r.counterparty == "ARJUN VARMA"
    # The rail is peer because a SLOT said a person is on the other end — not
    # because an app name was on a list. That list does not survive a new country.
    assert r.channel == "p2p"
    assert r.example() == "" and "counterparty" not in r.shareable()


def test_a_wire_is_refused_every_layer_and_offers_nothing():
    r = resolve_descriptor("WIRE TRANSFER VIA: SOMEBANK A/C: TITLE LLC "
                           "REF: 800/9021 SOME DRIVE IMAD: 0214X")
    assert r.refused and r.layer == "refused" and r.example() == ""


def test_no_digit_reaches_the_boundary():
    # Repair-list C2: the raw descriptor used to cross verbatim and persist in
    # plain JSON. A store number has never helped identify a brand.
    for d in ("COSTCO WHSE #0664 PLANO TX",
              "Longcreek-Servic ACH Pmt PPD ID: 1000000004",
              "AMZN Mktp US*RA30Z3BP0 AMZN.COM/BILL WA",
              "02/22 Payment To Meridian Card Ending IN 9911"):
        assert not any(c.isdigit() for c in linted_example(d))


def test_the_ach_entry_description_is_recovered_from_the_statement():
    """Layout from the NACHA specification; originator names invented.

    Company Name (16) then Company Entry Description (10) then the SEC code —
    fixed-width in the file, and the padding is gone from any display line. The
    statement still holds the boundary, because the description recurs across
    originators and the name does not. That property is what is asserted; the
    particular words are not."""
    lines = ["Tallgrass Ops Direct Dep PPD ID: 1000000000",
             "Northline Corp Direct Dep PPD ID: 1000000001",
             "Oakfield Mgmt Assn Dues PPD ID: 1000000003",
             "Ridgeview Grp Assn Dues PPD ID: 1000000002"]
    split = split_ach_heads(lines)
    assert split[lines[0]] == ("Tallgrass Ops", "Direct Dep")
    assert split[lines[2]] == ("Oakfield Mgmt", "Assn Dues")


def test_a_word_two_originators_share_in_their_NAMES_is_absorbed_wrongly():
    """A known limitation, pinned so it is discovered here and not on a vault.

    The split rests on "the description recurs, the name does not". When two
    originators happen to share a word in their *names* — two homeowners'
    associations both printing `Hoa` — that word recurs too, and it is pulled
    into the description. The result is still lossless (nothing is dropped) and
    still stable, but the boundary is one word off.

    Recorded rather than fixed: fixing it means deciding what a company name can
    contain, which is a vocabulary of company words, which is the kind of table
    this codebase keeps deleting. The honest mitigation is that Layer 1 splits
    these correctly once a grammar exists, because the bank's literal text is
    exactly what a template captures."""
    lines = ["Oakfield Hoa Assn Dues PPD ID: 1000000003",
             "Ridgeview Hoa Assn Dues PPD ID: 1000000002",
             "Tallgrass Ops Direct Dep PPD ID: 1000000000",
             "Northline Corp Direct Dep PPD ID: 1000000001"]
    name, entry = split_ach_heads(lines)[lines[0]]
    assert (name, entry) == ("Oakfield", "Hoa Assn Dues")     # one word off
    assert f"{name} {entry}" == "Oakfield Hoa Assn Dues"      # but lossless


def test_an_originator_seen_once_is_not_split_on_a_guess():
    lines = ["Solo Company Unique Words PPD ID: 1", "Other Co Direct Dep PPD ID: 2",
             "Third Co Direct Dep PPD ID: 3"]
    name, entry = split_ach_heads(lines)[lines[0]]
    assert entry == "" and name == "Solo Company Unique Words"
