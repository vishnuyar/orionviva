"""Shape vocabulary contracts."""

from _shape_test_support import *

# ------------------------------------------------- the vocabulary, both ways


def test_every_kind_of_thing_a_question_places_can_also_be_answered_with():
    """The completeness check: whatever the asking side needs, the answering
    side needs. A kind of thing only one direction can express means one
    direction cannot talk about something the other can, which is a hole in the
    design rather than an accident of what got built first."""
    asked = {kind for slots in INTENT_FIELDS.values() for kind in slots.values()}
    # Reviewed pack prose is not a kind of thing in the world; it nests one
    # reviewed template inside another, and it is deliberately not a hole.
    asked -= {render.PROSE}
    missing = sorted(asked - set(SLOT_TYPES))
    assert not missing, (
        f"{missing} can be placed in a question and not in an answer")
    unrenderable = sorted(k for k in asked if k not in render.RENDERED)
    assert not unrenderable, (
        f"{unrenderable} is declared as a kind of thing with nothing to write it")


def test_every_kind_a_hole_can_declare_has_exactly_one_way_to_be_written():
    """One renderer per kind, and the renderer is the only thing that makes
    one. A place that asks for an amount can therefore ask for it by type, and
    a string that formatted itself elsewhere cannot be passed off as one."""
    for kind in SLOT_TYPES:
        assert kind in render.RENDERED, kind
        produced = render.RENDERED[kind]
        assert not isinstance("just a string", produced), kind
    assert len(set(render.RENDERED.values())) == len(render.RENDERED)


def test_every_kind_of_magnitude_has_a_way_of_saying_it_was_rounded():
    """A kind of number with nowhere to say "about" is a kind of number that
    reaches a person looking exact when it is not. Which kinds hold a magnitude
    is already declared — they are the kinds that say what they measure — so a
    new one arriving without its own term fails here rather than in front of
    somebody."""
    from viva.tools.runner import APPROX_TERMS

    holders = {kind for kind in render.QUANTITY_OF_TYPE
               if kind != render.SUPPOSED}
    assert set(APPROX_TERMS) == holders, (
        f"only-in-terms={sorted(set(APPROX_TERMS) - holders)}, "
        f"only-in-vocabulary={sorted(holders - set(APPROX_TERMS))}")
    for kind, (key, name, produced) in APPROX_TERMS.items():
        assert produced is render.RENDERED[kind], kind
        # The term is a reviewed line in the pack that places the thing it is
        # about, and nothing else.
        assert moment(key, **{name: "x"}).strip(), key


@pytest.mark.parametrize("locale", ["en-US", "de-DE"])
def test_an_amount_written_by_a_hole_reads_back_as_the_same_amount(locale):
    written = render.money("1234.56", "USD", locale=locale)
    read = parse_amount(written, locale=locale, currency="USD")
    assert read.ok and read.decimal() == Decimal("1234.56")


def test_a_day_written_by_a_hole_reads_back_as_the_same_day():
    written = render.date("2026-01-31")
    read = parse_date(written)
    assert read.ok and read.value == "2026-01-31"


@pytest.mark.parametrize("locale", ["en-US", "de-DE"])
def test_a_proportion_written_by_a_hole_reads_back_as_the_same_proportion(locale):
    """A proportion written into a hole reads back as the same proportion. What
    the product carries is the quotient and what a person is shown is per
    hundred, so the round trip crosses that boundary and runs through the reader
    a reply goes through rather than through the number parser underneath it."""
    from viva.reply import Slot as ReplySlot
    from viva.reply import read_reply
    from viva.schemas import ANSWER_RATE

    written = render.rate("0.5", locale=locale)
    read = read_reply((ReplySlot(name="share", type=ANSWER_RATE, required=True),),
                      {"share": str(written)}, locale=locale)
    assert read.ok and Decimal(read.values["share"]) == Decimal("0.5")


def test_a_count_written_by_a_hole_reads_back_as_the_same_count():
    assert int(render.count(1200)) == 1200
    assert "," not in render.count(1200), (
        "a count is not an amount, and is not grouped like one")


def test_a_thing_is_written_by_its_attributes_and_read_back_as_a_reference():
    """The types that name a thing rather than measure one have no value to
    parse: the person names the thing and the parser resolves it to something
    the vault holds. So the round trip is a reference, and the renderer's job
    is only to choose which of the thing's names is shown."""
    account = {"account": "acct:northgate:4417", "name": "Everyday Checking",
               "number_masked": "••••4417"}
    assert render.account(account) == "Everyday Checking"
    assert render.account({"account": "Assets:Vehicles:The Estate"}) == "The Estate"
    assert render.merchant({"example": "GREENFIELD MARKET",
                            "key": "greenfield market"}) == "GREENFIELD MARKET"
    assert render.category("Groceries") == "Groceries"


def test_the_shape_prompt_teaches_every_kind_a_hole_can_declare():
    """A vocabulary the code knows and the instructions do not is a hole a
    model will never use; one the instructions know and the code does not is a
    shape that will always be refused."""
    from vivacore import promptstore

    from viva.speak import SHAPE_VERSION
    from viva.tools.registry import PROMPTS

    taught = promptstore.load(PROMPTS, SHAPE_VERSION)
    for kind in SLOT_TYPES:
        assert f"`{kind}`" in taught, f"the shape grammar never mentions {kind}"


def test_the_shape_and_its_bindings_are_kept(registry):
    """C-iii, and what keeps C-v open: what was said is recorded as the
    structure it was, so a sentence can be shown standing on what it stood on
    and the shapes a real conversation needs can accumulate."""
    shape = _shape(("Your balance is {total}.",
                   [("total", "money", "balance", "account")]))
    result = run("balance?",
                 _script(shape, BALANCES,
                         bind=lambda r: {"total": {"figure": "f1"}}),
                 registry)
    assert result.answered
    assert result.to_dict()["shape"] == shape.to_dict()
    assert result.to_dict()["bindings"] == {"total": {"figure": "f1"}}
