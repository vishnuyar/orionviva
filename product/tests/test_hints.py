"""What crosses to enrichment — the boundary, rebuilt on slots instead of words.

Every test here is about something NOT crossing, or about two things becoming
one. That is the whole change: enrichment used to be keyed on a descriptor and
gated by a substring list, and it is now keyed on a brand and gated by what a
slot declared.
"""

import types
from decimal import Decimal

from merchantcore.profile import Profile, Template
from viva.ledger.hints import enrichment_hints
from viva.ledger.streams import build_streams


def M(d, amount, desc, **kw):
    return types.SimpleNamespace(date=d, amount=Decimal(amount), account="chk",
                                 description=desc, **kw)


GRAMMAR = Profile("northbank", "depository", "v1", [
    Template("ZELLE PAYMENT TO {counterparty} {reference}"),
    Template("ZELLE PAYMENT TO {counterparty_handle} {reference}"),
    Template("ZELLE PAYMENT FROM {brand} {reference}"),
    Template("{brand} PAYROLL PPD ID: {company_id}"),
    Template("{brand} ASSN DUES PPD ID: {company_id}"),
    Template("CARD PURCHASE {date} {brand} {city} {region} CARD {account_ref}"),
])


def _hints(movements, grammar=GRAMMAR):
    return enrichment_hints(build_streams(movements, lambda m: grammar))


# --- what becomes one -------------------------------------------------------

def test_two_locations_of_one_brand_are_one_key_and_one_call():
    """The done-criterion the design claimed for days and the catalog never met.

    Keyed on the descriptor, a chain is one row per city: N enrichment calls, N
    commons rows, N chances to disagree with itself. Keyed on the brand slot, it
    is one of each."""
    mv = [M("2026-01-05", "-42.10",
            "CARD PURCHASE 01/05 GOLDEN FORK BISTRO PLANO TX CARD 0000"),
          M("2026-02-05", "-38.00",
            "CARD PURCHASE 02/05 GOLDEN FORK BISTRO FRISCO TX CARD 0000")]
    hints = _hints(mv)
    assert list(hints) == ["golden fork bistro"]
    assert hints["golden fork bistro"].movements == 2


def test_context_travels_only_where_the_brand_agreed():
    """What varies belongs to the visit; what does not belongs to the brand.

    A shop seen once in one city keeps its city, and that genuinely helps
    identify it. A chain seen in two has no city — and that absence is the right
    answer, not a missing value. The same rule retires store numbers without
    needing a rule about store numbers."""
    chain = [M("2026-01-05", "-42.10",
               "CARD PURCHASE 01/05 GOLDEN FORK BISTRO PLANO TX CARD 0000"),
             M("2026-02-05", "-38.00",
               "CARD PURCHASE 02/05 GOLDEN FORK BISTRO FRISCO TX CARD 0000")]
    local = [M("2026-01-09", "-19.00",
               "CARD PURCHASE 01/09 CORNER COFFEE PLANO TX CARD 0000"),
             M("2026-02-09", "-21.00",
               "CARD PURCHASE 02/09 CORNER COFFEE PLANO TX CARD 0000")]
    assert "city" not in _hints(chain)["golden fork bistro"].context
    assert _hints(chain)["golden fork bistro"].context["region"] == "TX"
    assert _hints(local)["corner coffee"].context["city"] == "PLANO"


def test_the_originators_own_word_for_itself_is_passed_on():
    """The NACHA Company Entry Description — the most informative field in an ACH
    line, far more than the SEC code, which says only that the debit was
    prearranged.

    Two originators per description, because the boundary between Company Name
    and Entry Description is fixed-width in the file and gone from any display
    line: it is recovered from the statement, on the property that a description
    recurs across originators and a name does not. One originator using a
    description of its own cannot be split, and is honestly left unsplit.

    A grammar usually makes the description part of its LITERAL text, which is
    correct and which removes it from the slots — so the split is consulted on
    the grammar path too, or the better layer would return less than the worse."""
    mv = [M("2026-01-15", "3120.55", "CEDARLINE HOLDINGS PAYROLL PPD ID: 1000000005"),
          M("2026-01-16", "2100.00", "NORTHLINE CORP PAYROLL PPD ID: 1000000006"),
          M("2026-01-11", "-450.00", "OAKFIELD MGMT ASSN DUES PPD ID: 1000000009"),
          M("2026-01-12", "-380.00", "RIDGEVIEW GRP ASSN DUES PPD ID: 1000000010")]
    hints = _hints(mv)
    assert "PAYROLL" in hints["cedarline holdings"].example().upper()
    assert "ASSN DUES" in hints["oakfield mgmt"].example().upper()


# --- what never crosses -----------------------------------------------------

def test_a_person_never_crosses_however_they_were_addressed():
    """The gate is a slot name, not a word list. `is_shareable` refused any
    descriptor containing " to " and admitted a name in any other language."""
    mv = [M("2026-01-20", "-2000.00", "ZELLE PAYMENT TO MARIA GARCIA ABC123"),
          M("2026-01-21", "-500.00", "ZELLE PAYMENT TO 7015550137 XYZ789")]
    assert _hints(mv) == {}
    blob = str([h.to_dict() for h in _hints(mv).values()])
    assert "MARIA" not in blob.upper() and "7015550137" not in blob


def test_an_organisation_on_the_SAME_rail_does_cross():
    # The case the old list got exactly backwards: a company paying you by peer
    # rail is not a person, and a peer rail is not evidence of one.
    mv = [M("2026-01-29", "2116.13", "ZELLE PAYMENT FROM BRIGHTFORD LABS INC 191346536")]
    assert list(_hints(mv)) == ["brightford labs inc"]


def test_a_wire_never_crosses():
    mv = [M("2026-02-14", "-23512.08",
            "WIRE TRANSFER VIA: SOMEBANK A/C: TITLE LLC REF: 9021 SOME DRIVE "
            "IMAD: 0214X")]
    assert _hints(mv) == {}


def test_your_own_card_and_your_brokerage_are_not_merchants():
    # There is nothing for a model to say about "Chase" when the movement is you
    # paying your own card, and nothing at all about a capital-gain phrase.
    own_card = M("2026-01-10", "-250.00", "PAYMENT TO CARD ENDING IN 0000")
    own_card.linked = True
    activity = M("2026-01-12", "8774.75", "YOU SOLD SHORT-TERM LOSS: $548.74")
    streams = build_streams([own_card, activity],
                            kind_for=lambda m: "investment" if m is activity
                            else "depository")
    assert enrichment_hints(streams) == {}


def test_a_partly_linked_counterparty_still_crosses():
    # `mixed` is one counterparty with some links missing. The merchant behind
    # it is as real as any other, and withholding it would hide a party behind a
    # gap in the transfer matcher.
    a = M("2026-01-10", "-250.00", "ACME SERVICES PAYROLL PPD ID: 1000000001")
    a.linked = True
    b = M("2026-01-20", "-40.00", "ACME SERVICES PAYROLL PPD ID: 1000000001")
    assert list(_hints([a, b])) == ["acme services"]


def test_with_no_grammar_the_conservative_list_still_guards_a_peer_payment():
    """The hole an agent would fall into, caught by an old test.

    Without a grammar there is no slot, so nothing can say a line holds a
    person, and a peer payment is indistinguishable from a shop. The word list
    was wrong as the PRIMARY mechanism — it answered, with substrings and in one
    language, the question enrichment exists to answer. It is right as the answer
    to "we cannot tell", because then its errors cost enrichment coverage rather
    than somebody's name.

    It over-blocks on purpose. Inducing a grammar for that institution retires
    it there."""
    mv = [M("2026-01-20", "-2000.00", "VENMO PAYMENT TO JOHN"),
          M("2026-01-21", "-40.00", "CORNER COFFEE PLANO TX")]
    without = _hints(mv, grammar=None)
    assert "venmo payment to john" not in without      # withheld, not knowing
    assert "corner coffee" in without                  # still offered

    # With a grammar the same line is judged by its slot, and an ORGANISATION on
    # the same rail crosses where the list would have refused it.
    # Order is part of a grammar: first match wins, so the more specific
    # template goes first. Reversed, `{counterparty}` swallows "ACMEWORKS INC"
    # and a company is classified as a person — which is rule 6 of the induction
    # prompt earning its place, and a reason a human reads the templates.
    g = Profile("northbank", "depository", "v1", [
        Template("VENMO PAYMENT TO {brand} INC"),
        Template("VENMO PAYMENT TO {counterparty}")])
    org = [M("2026-01-22", "-90.00", "VENMO PAYMENT TO ACMEWORKS INC")]
    assert "acmeworks" in _hints(org, grammar=g)


# --- how sure we are about the name ----------------------------------------

def test_a_grammars_reading_of_a_brand_outranks_a_published_rules():
    # The same brand reached two ways: the catalog should record how well it
    # knows what it was told rather than treating every key as equally sure.
    by_grammar = M("2026-01-15", "1.00", "MERIDIAN CO PAYROLL PPD ID: 1000000002")
    (h,) = _hints([by_grammar]).values()
    assert h.layer == "grammar"
    (h2,) = _hints([by_grammar], grammar=None).values()
    assert h2.layer == "published"


def test_the_example_is_composed_in_a_fixed_order():
    # Two vaults that saw the same merchant must compose the same string, or the
    # commons key drifts on presentation rather than on content.
    mv = [M("2026-01-09", "-19.00",
            "CARD PURCHASE 01/09 CORNER COFFEE PLANO TX CARD 0000")]
    # `rail=grammar` rather than `rail=card`: this bank ends its card lines with
    # the cardholder's last four, so DE43's trailing region rule never fires and
    # no published rule proves the rail. The template proves it instead.
    assert _hints(mv)["corner coffee"].example() == \
        "CORNER COFFEE · city=PLANO · region=TX · rail=grammar"
