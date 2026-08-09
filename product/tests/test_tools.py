"""The tool registry: validated calls, vault-vocabulary refusals, the cited
envelope, and the runner's composition gate."""

import hashlib
from decimal import Decimal

import pytest

from viva import quantity, render
from viva.ledger import (LedgerProjection, Provenance, account_opened,
                         closing_balance_observed, merchant_categorized,
                         opening_balance_observed, simple_transaction,
                         transfer_linked)
from viva.ledger.events import (CONFLICTED, CORROBORATED, UNVERIFIED, VERIFIED,
                                agent_acted, document_captured,
                                merchant_enriched, movement_tagged,
                                position_observed, question_declined,
                                read_recorded, statement_held)
from viva.ledger.projection import movement_key
from viva.tools import default_registry, ledger_tools, run, weakest
from viva.tools.envelope import ToolResult, figure
from viva.tools.registry import (PACKAGE as _PACKAGE, PROMPTS, Registry,
                                 ToolSpec, descriptions)
from viva.tools.shape import BadShape, Clause, Shape, Slot
from vivacore import promptstore
from vivacore import versions as _manifest

# The registry's description file is a released prompt: its text may never
# change. To edit a description, add a new version file and point the registry
# at it.
FROZEN_DESCRIPTIONS = {
    v: d for v, d in _manifest.manifest(_PACKAGE)["released"].items()
    if v.startswith("tools-")}


def _p(doc, page=1):
    return Provenance(doc, page, "r")


def _figure(results, what):
    """The figure whose description contains `what`. A planner reads numbers
    from here, not out of a payload — that is the whole contract."""
    for result in results:
        for f in result.get("figures") or []:
            if what in f["what"]:
                return f
    raise AssertionError(f"no figure described as {what!r} was emitted")


def _fig(results, what):
    """Its id — the only handle an answer is given for a number."""
    return _figure(results, what)["id"]


def _shape(*clauses):
    """A shape as a planner commits one: words with typed holes, no digits.

    Each clause is `(text, [(hole name, what it holds), ...])`, where a hole
    holding a magnitude adds what that magnitude is of. Written this way
    because every test below has to author its sentence before it has read
    anything, which is the property the whole mechanism rests on."""
    return Shape(clauses=tuple(
        Clause(text=text, slots=tuple(Slot(*slot) for slot in slots))
        for text, slots in clauses))


def _script(shape, *calls, bind=None):
    """A planner that commits `shape`, makes `calls` in order, then binds.

    `bind` is handed the results so far and returns the bindings map, so a test
    says which established thing fills which hole and never writes a value."""
    def planner(context):
        if not context["shaped"]:
            return {"shape": shape}
        done = [r for r in context["results"] if r["tool"] != "commit_shape"]
        if len(done) < len(calls):
            tool, args = calls[len(done)]
            return {"tool": tool, "args": args}
        return {"bindings": {} if bind is None else bind(context["results"])}
    return planner


def _entity(results, label):
    """The id of a thing a read spoke about, by the handle its figures use."""
    for result in results:
        for item in result.get("identifiers") or []:
            if label in item["label"]:
                return item["id"]
    raise AssertionError(f"no thing labelled {label!r} was established")


def _statement_reply(opening, opening_date, closing, closing_date):
    """What a model returned for a statement, in the shape the parser reads.
    Coverage is derived from this, so a fixture without it holds no period —
    which is the honest outcome, not a gap in the fixture."""
    import json
    return json.dumps({"opening": {"amount_raw": opening, "date_raw": opening_date},
                       "closing": {"amount_raw": closing, "date_raw": closing_date},
                       "transactions": []})


def _events():
    evs = [
        account_opened("chk", "depository", "Everyday Checking", "USD",
                       "2026-01-01", institution="Northgate Bank",
                       account_number="XX4417", account_names=["R VANCE"]),
        account_opened("card", "liability", "Signature Card", "USD",
                       "2026-01-01", institution="Meridian Cards",
                       account_number="XX2291", account_names=["R VANCE"]),
        account_opened("brk", "investment", "Brokerage", "USD",
                       "2026-01-01", institution="Vantage Invest",
                       account_number="XX7734", account_names=["R VANCE"]),
        document_captured("doc-jan", "jan.pdf", 100, "bank_statement", 0.9,
                          "2026-02-01"),
        document_captured("doc-held", "held.pdf", 90, "bank_statement", 0.5,
                          "2026-02-01"),
        statement_held("doc-held", {}, None, "gap", "2026-02-01"),
        document_captured("doc-limbo", "limbo.pdf", 80, "bank_statement", 0.4,
                          "2026-02-01"),
        read_recorded("doc-jan", "model", "extract-v1", "text",
                      _statement_reply("1000.00", "2026-01-01",
                                       "600.00", "2026-01-31"),
                      0.0, 1, 1, True, None, "2026-02-01"),
        opening_balance_observed("chk", "1000.00", "2026-01-01", _p("doc-jan")),
        simple_transaction("chk", "-40.00", "GREENFIELD MARKET",
                           "2026-01-05", provenance=_p("doc-jan")),
        simple_transaction("chk", "-60.00", "GREENFIELD MARKET",
                           "2026-01-20", provenance=_p("doc-jan")),
        simple_transaction("chk", "-300.00", "CARD PAYMENT XX2291",
                           "2026-01-15", provenance=_p("doc-jan")),
        closing_balance_observed("chk", "600.00", "2026-01-31", _p("doc-jan", 6)),
        simple_transaction("card", "-300.00", "PAYMENT RECEIVED",
                           "2026-01-15", provenance=_p("doc-card")),
        position_observed("brk", "ALPHA FUND", "10", "1500.00", "USD",
                          "2026-01-31", cost_basis="1200.00",
                          provenance=_p("doc-brk")),
        merchant_enriched("greenfield market", "groceries",
                          subcategory="supermarket", occurred_at="2026-02-02"),
        agent_acted("enrich_unknown", "enrich", "brands", "done",
                    "2026-02-03", calls=2),
        question_declined("q-1", "nature", "2026-02-03", amount="300.00"),
    ]
    a = movement_key("doc-jan", "chk", "2026-01-15", Decimal("-300.00"),
                     "CARD PAYMENT XX2291", 0)
    b = movement_key("doc-card", "card", "2026-01-15", Decimal("-300.00"),
                     "PAYMENT RECEIVED", 0)
    evs.append(transfer_linked(a, b, VERIFIED, {"decided_by": "test"},
                               "2026-02-04", by="human"))
    key = movement_key("doc-jan", "chk", "2026-01-20", Decimal("-60.00"),
                       "GREENFIELD MARKET", 0)
    evs.append(movement_tagged(key, ["pantry"], "2026-02-05"))
    return evs


@pytest.fixture()
def proj():
    return LedgerProjection(_events())


@pytest.fixture()
def registry(proj):
    return default_registry(proj)


# ------------------------------------------------------------- the contract

def test_descriptions_are_a_frozen_prompt_file():
    """Model-facing tool text lives in a versioned prompt file, never code,
    and a released version's text never changes."""
    for version_id, pinned in FROZEN_DESCRIPTIONS.items():
        text = promptstore.load(PROMPTS, version_id)
        digest = hashlib.sha256(text.encode()).hexdigest()[:16]
        assert digest == pinned, (
            f"{version_id}.txt changed — a released description file is "
            "immutable; add a new version file instead")
    named, version = descriptions("tools-v1")
    assert version == "tools-v1"
    assert set(named) >= {"query_ledger", "check_completeness",
                          "get_provenance", "get_transparency", "compute"}


def test_the_description_version_in_force_is_pinned():
    """A version bump that forgets its pin leaves the new text editable in
    place, and nothing else would notice."""
    from viva.tools.registry import DESCRIPTIONS_VERSION
    assert DESCRIPTIONS_VERSION in FROZEN_DESCRIPTIONS, (
        f"{DESCRIPTIONS_VERSION} is in force and unpinned — add its digest to "
        "FROZEN_DESCRIPTIONS in the same commit that releases the text")


def test_every_registered_tool_is_described(registry):
    described = {s["name"] for s in registry.schemas()}
    assert described == set(registry.names())
    assert all(s["description"] for s in registry.schemas())


def test_every_declared_array_says_what_it_holds(registry):
    """A provider validates the tool payload before it reads the question, and
    an array that does not declare its items is rejected there — the whole
    conversation dies on a schema, not on anything the model did. An object
    with no properties is deliberate (an open map of caller-named keys); an
    array with no items never is."""
    from viva.speak import _final_schema

    offenders: list[str] = []

    def walk(tool: str, node, path: str) -> None:
        if not isinstance(node, dict):
            return
        if node.get("type") == "array" and "items" not in node:
            offenders.append(f"{tool}.{path}" if path else tool)
        for name, child in (node.get("properties") or {}).items():
            walk(tool, child, f"{path}.{name}" if path else name)
        walk(tool, node.get("items"), f"{path}[]")

    for schema in registry.schemas() + [_final_schema()]:
        walk(schema["name"], schema["parameters"], "")

    assert not offenders, (
        f"{offenders} declare an array without items; a strict provider "
        "refuses the entire tool payload over it")


def test_a_tool_without_a_description_cannot_register():
    registry = Registry()
    with pytest.raises(ValueError):
        registry.register(ToolSpec(name="mystery_tool",
                                   params={"type": "object", "properties": {}},
                                   fn=lambda args: None))


def test_unknown_tool_is_a_refusal_not_an_exception(registry):
    result = registry.call("move_money", {})
    assert not result.ok and result.refusal == "unknown_tool"
    assert "query_ledger" in result.data["known_tools"]


def test_schema_violations_refuse_and_name_the_problem(registry):
    assert registry.call("query_ledger", {}).refusal == "invalid_arguments"
    bad_enum = registry.call("query_ledger", {"entity": "wishes"})
    assert not bad_enum.ok and "balances" in bad_enum.text
    unknown_field = registry.call("query_ledger",
                                  {"entity": "balances", "speed": "fast"})
    assert not unknown_field.ok and "speed" in unknown_field.text


# ------------------------------------------------------------- query_ledger

def test_balances_match_the_projection_and_carry_grades(proj, registry):
    result = registry.call("query_ledger", {"entity": "balances"})
    assert result.ok
    # The amount and its grade are what the figures assert; the row carries
    # what a figure cannot — which account it is, and why its grade is that.
    figures = {f["what"]: f for f in result.figures}
    chk = figures["Everyday Checking — balance"]
    assert chk["value"] == str(proj.balance("chk").amount)
    assert chk["grade"] == CORROBORATED
    # The card has no closing statement, so the composite is only as strong
    # as its weakest part.
    assert figures["Signature Card — balance"]["grade"] == UNVERIFIED
    assert result.grade == UNVERIFIED
    assert "doc-jan" in result.record_ids
    rows = {r["record_id"]: r for r in result.data["balances"]}
    assert "amount" not in rows["chk"] and "grade" not in rows["chk"]
    assert rows["chk"]["explanation"]


def test_unknown_account_refusal_names_the_known_ones(registry):
    result = registry.call("query_ledger", {"entity": "balances",
                                            "filters": {"account": "mystery"}})
    assert not result.ok and result.refusal == "unknown_account"
    assert "chk" in result.data["known_accounts"]


def test_unknown_category_refusal_names_the_vocabulary(registry):
    result = registry.call("query_ledger",
                           {"entity": "transactions",
                            "filters": {"category": "unicorns"}})
    assert not result.ok and result.refusal == "unknown_category"
    assert "groceries" in result.data["known_categories"]


def test_transactions_filter_by_nature_window_and_tag(proj, registry):
    spending = registry.call("query_ledger",
                             {"entity": "transactions",
                              "filters": {"nature": "spending"}})
    assert spending.ok and spending.data["count"] == 2   # card payment linked out
    tagged = registry.call("query_ledger", {"entity": "transactions",
                                            "filters": {"tag": "pantry"}})
    assert tagged.data["count"] == 1
    assert "transactions" not in tagged.data       # a summary returns no rows
    rows = registry.call("list_movements", {"filters": {"tag": "pantry"}})
    assert rows.data["movements"][0]["amount"] == "-60.00"
    windowed = registry.call("query_ledger",
                             {"entity": "transactions",
                              "filters": {"window": {"to": "2026-01-10"}}})
    assert windowed.data["count"] == 1
    bad = registry.call("query_ledger",
                        {"entity": "transactions",
                         "filters": {"window": {"to": "soon"}}})
    assert not bad.ok and bad.refusal == "bad_date"


def test_aggregate_spending_matches_the_projection(proj, registry):
    result = registry.call("query_ledger", {"entity": "aggregate",
                                            "metric": "spending"})
    assert result.ok
    expected = {k: str(v) for k, v in proj.spending_by_category().items()}
    assert result.data["by_group"] == expected
    assert result.data["total"] == "100.00"    # the linked card payment is out
    assert "doc-jan" in result.record_ids


def test_aggregate_needs_a_metric(registry):
    result = registry.call("query_ledger", {"entity": "aggregate"})
    assert not result.ok and result.refusal == "missing_metric"


def _two_currency_registry():
    """A vault holding two currencies, each with its own account and its own
    movements. Every value in it is synthetic."""
    evs = [
        account_opened("acct-a", "depository", "Account A", "USD",
                       "2026-01-01"),
        account_opened("acct-b", "depository", "Account B", "EUR",
                       "2026-01-01"),
        document_captured("doc-a", "a.pdf", 10, "bank_statement", 0.9,
                          "2026-02-01"),
        document_captured("doc-b", "b.pdf", 10, "bank_statement", 0.9,
                          "2026-02-01"),
        opening_balance_observed("acct-a", "500.00", "2026-01-01", _p("doc-a")),
        opening_balance_observed("acct-b", "300.00", "2026-01-01", _p("doc-b")),
        simple_transaction("acct-a", "-70.00", "COUNTERPARTY ONE",
                           "2026-01-05", provenance=_p("doc-a")),
        simple_transaction("acct-b", "-9.00", "COUNTERPARTY TWO",
                           "2026-01-06", provenance=_p("doc-b")),
    ]
    return default_registry(LedgerProjection(evs))


def test_a_summary_states_the_currency_of_what_it_summed(registry):
    """A total is an amount, and an amount is a value and a currency. Without
    the currency the same number is a bare magnitude, and arithmetic over it
    cannot tell money from a count."""
    result = registry.call("query_ledger", {"entity": "transactions"})
    assert result.ok
    figures = {f["what"]: f for f in result.figures}
    counts = ("movements matching", "months these movements span")
    for what, fig in figures.items():
        if any(c in what for c in counts):
            assert fig["currency"] == "", "a count is not an amount of anything"
        else:
            assert fig["currency"] == "USD", f"{what} states no currency"


def test_a_spending_total_states_a_real_currency_and_never_a_null(registry):
    """A spending read with no currency filter states a code on every amount
    and states nothing at all on a count. No figure holds a null, and none
    reaches the model carrying an empty currency."""
    result = registry.call("query_ledger", {"entity": "aggregate",
                                            "metric": "spending"})
    assert result.ok
    for fig in result.figures:
        assert fig["currency"] is not None
        if "counted" in fig["what"]:
            assert fig["currency"] == ""
        else:
            assert fig["currency"] == "USD"
    stated = result.to_dict()["figures"]
    assert all(f.get("currency") != "null" for f in stated)
    assert all("currency" not in f or f["currency"] for f in stated)


def test_a_total_across_currencies_refuses_rather_than_adding_them():
    """700 of one currency and 90 of another do not make 790 of anything.
    Nothing here converts, so the sum is not a weaker figure — it is a number
    that measures nothing, and it must not be emitted as a graded one."""
    mixed = _two_currency_registry()
    summary = mixed.call("query_ledger", {"entity": "transactions"})
    assert not summary.ok and summary.refusal == "mixed_currencies"
    assert set(summary.data["currencies"]) == {"USD", "EUR"}
    spending = mixed.call("query_ledger", {"entity": "aggregate",
                                           "metric": "spending"})
    assert not spending.ok and spending.refusal == "mixed_currencies"
    # Narrowed to one currency, both reads answer normally and say which.
    for args in ({"entity": "transactions", "filters": {"currency": "USD"}},
                 {"entity": "aggregate", "metric": "spending",
                  "filters": {"currency": "USD"}}):
        one = mixed.call("query_ledger", args)
        assert one.ok, one.text
        assert all(f["currency"] in ("", "USD") for f in one.figures)
        assert any(f["currency"] == "USD" for f in one.figures)


def test_income_refuses_a_window_rather_than_ignoring_it(registry):
    """A lifetime figure presented as the answer to a dated question is a
    wrong number; income refuses the filter instead."""
    result = registry.call("query_ledger",
                           {"entity": "aggregate", "metric": "income",
                            "filters": {"window": {"from": "2027-01-01"}}})
    assert not result.ok and result.refusal == "filter_unsupported"
    assert "currency" in result.data["supported_filters"]


def test_income_names_its_sources_and_says_it_is_lifetime(proj, registry):
    result = registry.call("query_ledger", {"entity": "aggregate",
                                            "metric": "income"})
    assert result.ok
    expected = {k: str(v) for k, v in proj.income_by_currency().items()}
    assert result.data["by_currency"] == expected
    assert any("lifetime" in c for c in result.caveats)


def test_filters_an_entity_would_ignore_are_refused(registry):
    """Accepted-and-dropped is the lie this test guards against: rows that
    are individually true still answer the wrong question."""
    by_category = registry.call("query_ledger",
                                {"entity": "balances",
                                 "filters": {"category": "groceries"}})
    assert not by_category.ok and by_category.refusal == "filter_unsupported"
    holdings = registry.call("query_ledger",
                             {"entity": "holdings",
                              "filters": {"tag": "pantry"}})
    assert not holdings.ok and holdings.refusal == "filter_unsupported"
    net_worth = registry.call("query_ledger",
                              {"entity": "aggregate", "metric": "net_worth",
                               "filters": {"account": "chk"}})
    assert not net_worth.ok and net_worth.refusal == "filter_unsupported"


def test_net_worth_point_comes_back_dated(registry):
    result = registry.call("query_ledger", {"entity": "aggregate",
                                            "metric": "net_worth"})
    assert result.ok and result.data["metric"] == "net_worth"
    assert result.dated == result.data["point"]["as_of"]


def test_as_of_outside_net_worth_is_refused(registry):
    result = registry.call("query_ledger", {"entity": "balances",
                                            "as_of": "2026-01-15"})
    assert not result.ok and result.refusal == "as_of_unsupported"


def test_holdings_are_dated_measurements(registry):
    result = registry.call("query_ledger", {"entity": "holdings"})
    assert result.ok and result.data["count"] == 1
    row = result.data["holdings"][0]
    assert row["market_value"] == "1500.00" and row["as_of"] == "2026-01-31"
    assert any("never" in c and "price" in c for c in result.caveats)


# ------------------------------------------------- completeness and provenance

def test_completeness_counts_the_held_document(registry):
    result = registry.call("check_completeness")
    assert result.ok
    assert result.data["awaiting"] == 2      # one held, one captured in limbo
    assert result.data["holds"][0]["doc_id"] == "doc-held"
    assert any(a["account"] == "chk" and a["grade"] == CORROBORATED
               for a in result.data["accounts"])


def test_provenance_states_say_what_actually_happened(registry):
    """posted: in the ledger. held: read and set aside for review.
    captured: received, not yet processed. Each must report as itself."""
    held = registry.call("get_provenance", {"record_id": "doc-held"})
    assert held.ok and held.data["state"] == "held"
    captured = registry.call("get_provenance", {"record_id": "doc-limbo"})
    assert captured.ok and captured.data["state"] == "captured"


def test_provenance_answers_for_document_account_and_movement(proj, registry):
    doc = registry.call("get_provenance", {"record_id": "doc-jan"})
    assert doc.ok and doc.data["state"] == "posted"
    acct = registry.call("get_provenance", {"record_id": "chk"})
    assert acct.ok and acct.grade == CORROBORATED
    assert acct.provenance[0]["doc_id"] == "doc-jan"
    key = next(m.key for m in proj.movements() if m.amount == Decimal("-300.00")
               and m.account == "chk")
    move = registry.call("get_provenance", {"record_id": key})
    assert move.ok and move.data["movement"]["nature"] == "transfer"
    missing = registry.call("get_provenance", {"record_id": "nothing"})
    assert not missing.ok and missing.refusal == "unknown_record"


def test_transparency_reads_the_agent_journal(registry):
    activity = registry.call("get_transparency", {"topic": "agent_activity"})
    assert activity.ok and activity.data["count"] == 1
    calls = registry.call("get_transparency", {"topic": "calls_spent"})
    assert calls.ok and calls.data["calls"] == 2
    declined = registry.call("get_transparency",
                             {"topic": "declined_questions"})
    assert declined.ok and "q-1" in declined.data["declined"]


# ------------------------------------------------- what every figure measures

def _probe_vault(factor="1", more=0):
    """One synthetic vault, twice parameterised: every amount is multiplied by
    `factor`, and `more` says how many further movements, documents, agent
    actions and set-aside questions it holds.

    Two probes fall out of it. An amount moves when the factor moves and does
    not care how many rows there are; a count is the opposite. That is what
    makes the check below an argument about each figure rather than a list of
    the figures we happen to emit today.

    A figure that is zero here moves under neither probe and is classified as
    neither, which says nothing about the figure. Every shape of amount a read
    can emit is therefore non-zero in this vault: money coming in as well as
    going out, and a liability as well as assets."""
    def scaled(amount):
        return str(Decimal(amount) * Decimal(factor))

    evs = [
        account_opened("chk", "depository", "Everyday", "USD", "2026-01-01"),
        account_opened("card", "liability", "Card", "USD", "2026-01-01"),
        account_opened("brk", "investment", "Brokerage", "USD", "2026-01-01"),
        document_captured("doc-one", "one.pdf", 10, "bank_statement", 0.9,
                          "2026-02-01"),
        opening_balance_observed("chk", scaled("1000.00"), "2026-01-01",
                                 _p("doc-one")),
        simple_transaction("chk", scaled("-40.50"), "COUNTERPARTY ONE",
                           "2026-01-05", provenance=_p("doc-one")),
        simple_transaction("chk", scaled("-60.25"), "COUNTERPARTY ONE",
                           "2026-01-20", provenance=_p("doc-one")),
        simple_transaction("chk", scaled("250.00"), "COUNTERPARTY THREE",
                           "2026-01-25", provenance=_p("doc-one")),
        closing_balance_observed("chk", scaled("1149.25"), "2026-01-31",
                                 _p("doc-one", 6)),
        opening_balance_observed("card", "0.00", "2026-01-01", _p("doc-one")),
        # A card's balance is money owed, held as a positive magnitude, and a
        # charge adds to it.
        simple_transaction("card", scaled("25.75"), "COUNTERPARTY TWO",
                           "2026-01-11", provenance=_p("doc-one")),
        closing_balance_observed("card", scaled("25.75"), "2026-01-31",
                                 _p("doc-one", 7)),
        position_observed("brk", "SYNTH FUND", "10", scaled("1500.00"), "USD",
                          "2026-01-31", cost_basis=scaled("1200.00"),
                          provenance=_p("doc-one")),
        merchant_enriched("counterparty one", "groceries",
                          subcategory="supermarket", occurred_at="2026-02-02"),
        agent_acted("enrich_unknown", "enrich", "brands", "done", "2026-02-03",
                    calls=2),
        question_declined("q-1", "nature", "2026-02-03",
                          amount=scaled("300.00")),
    ]
    evs.append(movement_tagged(
        movement_key("doc-one", "chk", "2026-01-20",
                     Decimal(scaled("-60.25")), "COUNTERPARTY ONE", 0),
        ["pantry"], "2026-02-05"))
    for n in range(more):
        evs.append(simple_transaction("chk", scaled("-40.50"),
                                      "COUNTERPARTY ONE",
                                      f"2026-01-{12 + n:02d}",
                                      provenance=_p("doc-one")))
        evs.append(account_opened(f"extra{n}", "depository", f"Extra {n}",
                                  "USD", "2026-01-01"))
        evs.append(opening_balance_observed(f"extra{n}", scaled("10.00"),
                                            "2026-01-01", _p("doc-one")))
        evs.append(position_observed("brk", f"SYNTH FUND {n}", "1",
                                     scaled("10.00"), "USD", "2026-01-31",
                                     provenance=_p("doc-one")))
        evs.append(document_captured(f"doc-more-{n}", f"more{n}.pdf", 10,
                                     "bank_statement", 0.9, "2026-02-01"))
        evs.append(agent_acted("enrich_unknown", "enrich", f"more-{n}", "done",
                               "2026-02-03", calls=1))
        evs.append(question_declined(f"q-more-{n}", "nature", "2026-02-03",
                                     amount=scaled("300.00")))
    proj = LedgerProjection(evs)
    return default_registry(proj), proj


def _enumerated_args(schema: dict) -> list:
    """Every combination of the enum-valued fields a tool's own schema
    declares, with each optional one also left out. A new entity, metric,
    group_by or topic is therefore exercised the day it is added, without this
    test being edited."""
    props = schema.get("properties") or {}
    required = set(schema.get("required") or ())
    combos = [{}]
    for name, spec in props.items():
        if "enum" not in spec:
            continue
        options = list(spec["enum"])
        if name not in required:
            options = [None] + options
        combos = [dict(combo) if value is None else dict(combo, **{name: value})
                  for combo in combos for value in options]
    return combos


def _every_figure(factor="1", more=0) -> dict:
    """Every figure every registered tool emits over one vault, by what it
    says it is. A tool no call here reaches fails the coverage check, so a new
    tool cannot join the registry unexercised."""
    registry, proj = _probe_vault(factor, more)
    movement = next(m.key for m in proj.movements())
    # What a schema cannot supply: the ids and expressions only a vault holds.
    from_the_vault = {
        "list_movements": [{"filters": {"account": "chk"}}],
        "get_provenance": [{"record_id": "chk"}, {"record_id": "doc-one"},
                           {"record_id": movement}],
    }
    out: dict = {}
    reached = set()
    book = _one_figure(registry, "query_ledger", {"entity": "balances"})
    money = next(f["id"] for f in book.values() if f["currency"])
    calls = [("compute", {"expression": "a * 2", "inputs": {"a": money}}),
             # An amount over an amount is the one figure only arithmetic
             # produces, so a check over every emitter has to reach it here.
             ("compute", {"expression": "a / a", "inputs": {"a": money}})]
    for schema in registry.schemas():
        name = schema["name"]
        for args in from_the_vault.get(name,
                                       _enumerated_args(schema["parameters"])):
            calls.append((name, args))
    for name, args in calls:
        result = registry.call(name, args, figures=book)
        if not result.ok:
            continue
        reached.add(name)
        for fig in result.figures:
            out[fig["what"]] = fig
    assert reached == set(registry.names()), (
        f"{sorted(set(registry.names()) - reached)} emitted nothing here; a "
        "tool this check never calls is a tool whose figures nothing measures")
    return out


def test_every_figure_a_tool_emits_says_what_it_measures():
    """The dimension of every figure must be readable off the figure itself:
    an amount states its currency, a count states none, and nothing states a
    null. Arithmetic reads money and plain numbers apart by exactly this, so a
    figure that will not say is one the arithmetic will silently mistake.

    Neither side is asserted from a list of today's figures. A figure whose
    value follows the amounts is money; one that follows the number of rows is
    a count; one that follows neither — a date, a zero — is left alone."""
    plain = _every_figure()
    scaled = _every_figure(factor="7")
    longer = _every_figure(more=2)
    assert len(plain) > 20 and set(plain) <= set(longer)
    assert set(plain) == set(scaled)
    for what, fig in plain.items():
        currency = fig["currency"]
        assert isinstance(currency, str), (
            f"{what!r} carries {currency!r} as its currency, which is neither "
            "a code nor nothing at all")
        if currency:
            Decimal(fig["value"])          # an amount is a number, or nothing
        if fig["value"] != scaled[what]["value"]:
            assert currency, (
                f"{what!r} follows the amounts, so it is money, and it states "
                "no currency")
        elif fig["value"] != longer.get(what, fig)["value"]:
            assert not currency, (
                f"{what!r} follows the number of rows, so it counts things, "
                f"and it claims to be an amount in {currency}")


def test_no_tool_can_emit_a_figure_that_does_not_say_what_it_measures():
    """This is what makes the closed vocabulary safe. Every figure that can
    reach a person comes from an emitter written here, so a quantity nobody
    thought of shows up as a red suite rather than as a refused answer in front
    of somebody. A vocabulary over language a model might produce could only
    ever fail the other way round."""
    for what, fig in _every_figure().items():
        assert fig["quantity"] in quantity.MEASURES, (
            f"{what!r} declares {fig['quantity']!r}, which says nothing about "
            "what the number is of")


def test_every_quantity_the_vocabulary_holds_can_be_asked_for():
    """The other half of the same completeness. A quantity nothing can ask for
    is a word a tool may declare that no sentence can ever be about, so the
    figure carrying it is unsayable — and it would be unsayable silently."""
    askable = {kind for kinds in render.QUANTITY_OF_TYPE.values()
               for kind in kinds}
    missing = sorted(set(quantity.KINDS) - askable)
    assert not missing, (
        f"{missing} can be measured and no hole can ask about it")


# ------------------------------------------------------------------- compute

def _one_figure(registry, tool, args):
    """The figure book after one call, as the runner would stamp it."""
    result = registry.call(tool, args)
    assert result.ok, result.text
    for i, fig in enumerate(result.figures, 1):
        fig["id"] = f"f{i}"
    return {f["id"]: f for f in result.figures}


def _shift(book, offset):
    """The same figures, renumbered as if a second call had emitted them."""
    out = {}
    for i, fig in enumerate(book.values(), offset + 1):
        fig["id"] = f"f{i}"
        out[fig["id"]] = fig
    return out


def test_compute_is_exact(registry):
    """The float-drift trap, and the reason arithmetic is a tool at all. If
    this passes while `compute` returns the wrong number, the suite is
    measuring everything about arithmetic except whether it is right."""
    book = {}
    for i, amount in enumerate(("0.10", "0.20"), 1):
        f = figure(amount, f"a tenth {i}", quantity=quantity.BALANCE,
                   grade=VERIFIED, currency="USD",
                   record_ids=["doc-jan"])
        f["id"] = f"f{i}"
        book[f["id"]] = f
    result = registry.call("compute",
                           {"expression": "a + b",
                            "inputs": {"a": "f1", "b": "f2"}}, figures=book)
    assert result.ok and result.figures[0]["value"] == "0.30"
    thirds = registry.call("compute",
                           {"expression": "a * 3",
                            "inputs": {"a": "f1"}}, figures=book)
    assert thirds.figures[0]["value"] == "0.30"


def test_compute_inherits_records_and_the_weakest_grade_from_its_operands(registry):
    """An operand is a figure, so provenance is carried rather than declared:
    the result stands on the same documents and can be no stronger than the
    weakest thing it was built from. Arithmetic is deterministic, so nothing is
    lost in the crossing — the result is a claim about money like its parts."""
    book = _one_figure(registry, "query_ledger", {"entity": "balances"})
    ids = [f["id"] for f in book.values() if "balance" in f["what"]]
    result = registry.call("compute",
                           {"expression": "a + b",
                            "inputs": {"a": ids[0], "b": ids[1]}},
                           figures=book)
    assert result.ok
    assert result.figures[0]["kind"] == "computed"
    assert result.grade == weakest(book[i]["grade"] for i in ids[:2])
    assert result.figures[0]["grade"] == result.grade
    assert set(result.record_ids) == {r for i in ids[:2]
                                      for r in book[i]["record_ids"]}


def test_compute_will_not_add_across_currencies(registry):
    """Every read here refuses to convert, for want of a rate with a date, a
    source and a grade of its own. Arithmetic may not do quietly what the reads
    will not do at all."""
    book = {}
    for i, currency in enumerate(("USD", "EUR"), 1):
        f = figure("100.00", f"balance {i}", quantity=quantity.BALANCE,
                   grade=VERIFIED, currency=currency,
                   record_ids=[f"doc-{i}"])
        f["id"] = f"f{i}"
        book[f["id"]] = f
    result = registry.call("compute", {"expression": "a + b",
                                       "inputs": {"a": "f1", "b": "f2"}},
                           figures=book)
    assert not result.ok and result.refusal == "mixed_currencies"


def test_compute_will_not_mix_what_the_agent_did_with_what_you_hold(registry):
    """A figure about the agent's own behaviour and a figure about money make a
    number of neither kind, and the emitting tool is the only thing allowed to
    decide a kind."""
    book = _one_figure(registry, "get_transparency", {"topic": "calls_spent"})
    book.update(_shift(_one_figure(registry, "query_ledger",
                                   {"entity": "balances"}), len(book)))
    activity = next(f["id"] for f in book.values() if f["kind"] == "activity")
    money = next(f["id"] for f in book.values() if "balance" in f["what"])
    result = registry.call("compute", {"expression": "a + b",
                                       "inputs": {"a": activity, "b": money}},
                           figures=book)
    assert not result.ok and result.refusal == "mixed_kinds"


def test_compute_comes_back_as_an_envelope_however_large_the_arithmetic(registry):
    """No arithmetic input makes the call raise across the boundary.

    A magnitude larger than the context can carry, a division by zero, a very
    long expression and a deeply nested one all come back as refusal envelopes.

    The huge case scales an amount by a plain number on purpose. An expression
    the walk turns away on its dimensions never reaches the arithmetic at all,
    so it would pass this test while measuring nothing about it — which is why
    the expected tags here are the arithmetic's own."""
    for args, question, expected in (
            ({"expression": "x * 10",
              "inputs": {"x": {"stipulated": "1e999999999"}}}, "1e999999999",
             ("bad_expression",)),
            ({"expression": "x / 0",
              "inputs": {"x": {"stipulated": "100"}}}, "100",
             ("division_by_zero",)),
            ({"expression": "+".join(["1"] * 1200), "inputs": {}}, "",
             ("bad_expression", "bad_input")),
            ({"expression": "1" + "*(1" * 400 + ")" * 400, "inputs": {}}, "",
             ("bad_expression", "bad_input"))):
        result = registry.call("compute", args, figures={}, question=question)
        assert not result.ok and result.refusal in expected, result.refusal


def test_a_magnitude_the_expression_invented_stands_on_no_document(registry):
    """Naming a figure and depending on it are different things. A magnitude
    typed into an expression carries none of the documents of a figure the call
    merely bound — one subtracted away, one multiplied by zero, one never
    referred to at all — so it stands on nothing and cannot be said."""
    book = _one_figure(registry, "query_ledger", {"entity": "balances"})
    balance = next(f["id"] for f in book.values() if "balance" in f["what"])
    for expression in ("a - a + 424242", "a * 0 + 999999"):
        refused = registry.call("compute",
                                {"expression": expression,
                                 "inputs": {"a": balance}}, figures=book)
        assert not refused.ok, f"{expression} came back as {refused.figures}"
        assert refused.refusal == "mixed_dimensions"
    # Subtracting a figure from itself is not the fabrication and is not
    # refused: zero really is what those documents say the difference is.
    zero = registry.call("compute", {"expression": "a - a",
                                     "inputs": {"a": balance}}, figures=book)
    assert zero.ok and Decimal(zero.figures[0]["value"]) == 0
    assert zero.record_ids == book[balance]["record_ids"]
    # A magnitude alone inherits nothing from a figure it never touched: no
    # records, no grade, and nothing saying what it is a magnitude of.
    alone = registry.call("compute", {"expression": "987654",
                                      "inputs": {"a": balance}}, figures=book)
    assert alone.ok and alone.figures[0]["record_ids"] == []
    assert alone.figures[0]["grade"] == ""
    assert alone.figures[0]["quantity"] == quantity.UNMEASURED

    shape = _shape(("That comes to {total}.", [("total", "count", "count")]))

    def planner(context):
        if not context["shaped"]:
            return {"shape": shape}
        done = [r for r in context["results"] if r["tool"] != "commit_shape"]
        if not done:
            return {"tool": "query_ledger", "args": {"entity": "balances"}}
        if len(done) == 1:
            return {"tool": "compute",
                    "args": {"expression": "987654",
                             "inputs": {"a": _fig(context["results"],
                                                  "balance")}}}
        return {"bindings": {"total": {"figure": _fig(context["results"],
                                                      "result of")}}}
    assert run("how much?", planner, registry).refusal == "wrong_quantity"


# ------------------------------------------ what a computed figure rests on

def _book(*specs):
    """A figure book as the runner would stamp one, built from
    `(value, what, grade, currency, records)`. Every value in it is
    synthetic.

    A spec stating a currency is an amount held, and one stating none counts
    things — which is what the specs below already mean, said once here so
    every one of them does not have to repeat it."""
    out = {}
    for i, (value, what, grade, currency, records) in enumerate(specs, 1):
        fig = figure(value, what, grade=grade, currency=currency,
                     quantity=quantity.BALANCE if currency else quantity.COUNT,
                     record_ids=records)
        fig["id"] = f"f{i}"
        out[fig["id"]] = fig
    return out


def _computed(registry, book, expression, **inputs):
    """One arithmetic call over a book, asserted to have come back."""
    result = registry.call("compute", {"expression": expression,
                                       "inputs": inputs}, figures=book)
    assert result.ok, f"{expression}: {result.refusal} — {result.text}"
    return result.figures[0]


TWO_AMOUNTS_AND_A_COUNT = (
    ("600.00", "an amount", VERIFIED, "USD", ["doc-one"]),
    ("200.00", "another amount", UNVERIFIED, "USD", ["doc-two"]),
    ("7", "a count of things", CONFLICTED, "", ["doc-three"]),
)


def test_a_magnitude_added_to_a_plain_number_takes_the_total_off_its_evidence(
        registry):
    """A count is a plain number, so a magnitude may be added to it with no
    dimension objecting. Adding is where a magnitude enters rather than
    rescales, so a term standing on no record leaves the total standing on
    none, and carrying no grade.

    That the other terms were well evidenced is what the assertion is about:
    their evidence says nothing about the number that came out."""
    book = _book(*TWO_AMOUNTS_AND_A_COUNT)
    for expression, inputs in (
            ("n - n + 424242", {"n": "f3"}),
            ("n * 0 + 777", {"n": "f3"}),
            ("(a / b) * 0 + 8888", {"a": "f1", "b": "f2"})):
        result = registry.call("compute", {"expression": expression,
                                           "inputs": inputs}, figures=book)
        assert result.ok, f"{expression} refused: {result.refusal}"
        fig = result.figures[0]
        assert fig["record_ids"] == [], f"{expression} cites {fig['record_ids']}"
        assert fig["grade"] == "", f"{expression} claims {fig['grade']}"
        assert result.record_ids == [] and result.grade == ""


def test_a_fabricated_total_is_refused_before_it_can_be_said(registry):
    """A computed figure is a claim about the person's money, so the gate that
    refuses a money figure citing no record is what turns "rests on nothing"
    into "cannot be said"."""
    shape = _shape(("That comes to {total}.", [("total", "count", "count")]))

    def planner(context):
        if not context["shaped"]:
            return {"shape": shape}
        done = [r for r in context["results"] if r["tool"] != "commit_shape"]
        if not done:
            return {"tool": "query_ledger", "args": {"entity": "balances"}}
        if len(done) == 1:
            return {"tool": "compute",
                    "args": {"expression": "n - n + 424242",
                             "inputs": {"n": _fig(context["results"],
                                                  "accounts holding")}}}
        return {"bindings": {"total": {"figure": _fig(context["results"],
                                                      "result of")}}}
    run_result = run("how much?", planner, registry)
    assert not run_result.answered
    assert run_result.refusal == "uncited_figure"
    # The count it was built from is a real figure with real documents, which
    # is what made the fabrication look attested in the first place.
    counted = _one_figure(registry, "query_ledger", {"entity": "balances"})
    count = next(f for f in counted.values() if "accounts holding" in f["what"])
    assert count["record_ids"] and count["grade"]


def test_scaling_a_figure_leaves_it_standing_where_it_stood(registry):
    """Multiplying or dividing by a plain magnitude changes the units, not the
    evidence: the result keeps the records and the grade of what was scaled.
    Annualising, halving, splitting per person and expressing a proportion are
    all this shape."""
    book = _book(*TWO_AMOUNTS_AND_A_COUNT)
    for expression, inputs, records, grade in (
            ("a * 3", {"a": "f1"}, ["doc-one"], VERIFIED),
            ("a / 3", {"a": "f1"}, ["doc-one"], VERIFIED),
            ("(a / b) * 100", {"a": "f1", "b": "f2"},
             ["doc-one", "doc-two"], UNVERIFIED)):
        fig = _computed(registry, book, expression, **inputs)
        assert fig["record_ids"] == records, expression
        assert fig["grade"] == grade, expression


def test_a_graded_count_hands_its_evidence_to_what_it_scales(registry):
    """A count is a figure like any other: it has documents behind it and a
    grade of its own. An amount nothing disputes, scaled by a count that
    disagrees with its own evidence, is conflicted and cites both sides — not
    verified, citing half of what it was built from."""
    book = _book(*TWO_AMOUNTS_AND_A_COUNT)
    fig = _computed(registry, book, "a * n", a="f1", n="f3")
    assert fig["record_ids"] == ["doc-one", "doc-three"]
    assert fig["grade"] == CONFLICTED
    assert fig["currency"] == "USD"


def test_a_total_of_attested_terms_keeps_them_all(registry):
    """Two figures added stand on both sets of documents at the weaker grade,
    and a figure subtracted from itself is a zero standing on its own
    document."""
    book = _book(*TWO_AMOUNTS_AND_A_COUNT)
    total = _computed(registry, book, "a + b", a="f1", b="f2")
    assert total["record_ids"] == ["doc-one", "doc-two"]
    assert total["grade"] == UNVERIFIED and total["currency"] == "USD"
    zero = _computed(registry, book, "a - a", a="f1")
    assert Decimal(zero["value"]) == 0
    assert zero["record_ids"] == ["doc-one"] and zero["grade"] == VERIFIED


def test_a_figure_bound_and_never_named_decides_nothing(registry):
    """What currency a computation is in is a property of the expression. A
    second currency bound to a name the arithmetic never reaches leaves a
    single-currency computation alone; two currencies the expression actually
    reaches refuse."""
    book = _book(("600.00", "an amount", VERIFIED, "USD", ["doc-one"]),
                 ("100.00", "an amount elsewhere", VERIFIED, "EUR",
                  ["doc-two"]))
    fig = _computed(registry, book, "a * 2", a="f1", elsewhere="f2")
    assert fig["currency"] == "USD" and fig["record_ids"] == ["doc-one"]
    crossed = registry.call("compute",
                            {"expression": "a + elsewhere",
                             "inputs": {"a": "f1", "elsewhere": "f2"}},
                            figures=book)
    assert not crossed.ok and crossed.refusal == "mixed_currencies"


def test_negating_a_figure_keeps_everything_true_of_it(registry):
    """A sign is not a provenance event. What the figure measures, what it
    stands on, how strong it is and how its arithmetic came out all survive the
    minus — the last of these because a negated approximation stated as an
    exact number is the same untruth as any other."""
    book = _book(*TWO_AMOUNTS_AND_A_COUNT)
    fig = _computed(registry, book, "-a", a="f1")
    assert Decimal(fig["value"]) == Decimal("-600.00")
    assert fig["currency"] == "USD"
    assert fig["record_ids"] == ["doc-one"] and fig["grade"] == VERIFIED
    assert fig["exactness"] == "exact"
    rounded = _computed(registry, book, "-(a / 7)", a="f1")
    assert rounded["exactness"] == "rounded"
    assert Decimal(rounded["value"]) == Decimal("-85.71")
    assert rounded["currency"] == "USD" and rounded["grade"] == VERIFIED
    assert rounded["record_ids"] == ["doc-one"]


def test_a_supposition_survives_being_computed_with_again(registry):
    """A figure derived from something the person supposed is hypothetical, and
    so is anything derived from that in turn, however many rounds of arithmetic
    separate them from the premise."""
    book = _one_figure(registry, "query_ledger", {"entity": "balances"})
    balance = next(f["id"] for f in book.values() if "balance" in f["what"])
    first = registry.call(
        "compute", {"expression": "have - trip",
                    "inputs": {"have": balance, "trip": {"stipulated": "250"}}},
        figures=book, question="what if a trip cost 250?")
    assert first.ok and first.figures[0]["kind"] == "hypothetical"
    assert first.figures[0]["grade"] == ""
    book.update(_shift({"x": first.figures[0]}, len(book)))
    again = _computed(registry, book, "supposed * 2",
                      supposed=first.figures[0]["id"])
    assert again["kind"] == "hypothetical" and again["grade"] == ""


# --------------------------------------------------- how the arithmetic went

def test_a_division_that_does_not_come_out_is_answered_not_refused(registry):
    """A quotient that does not terminate comes back rather than refusing. The
    value is written at the scale money is counted in, and the figure says of
    itself that it was rounded."""
    book = _book(("2000.00", "an amount", VERIFIED, "USD", ["doc-one"]))
    for expression, value in (("a / 52", "38.46"), ("a / 12", "166.67")):
        fig = _computed(registry, book, expression, a="f1")
        assert fig["value"] == value, expression
        assert fig["exactness"] == "rounded", expression
        assert fig["currency"] == "USD"


def test_how_the_arithmetic_went_never_moves_the_grade(registry):
    """A figure that had to be rounded stands on the same documents at the same
    grade as one that did not; only its account of the arithmetic differs."""
    book = _book(*TWO_AMOUNTS_AND_A_COUNT)
    exact = _computed(registry, book, "a / 3", a="f1")
    rounded = _computed(registry, book, "a / 7", a="f1")
    assert exact["exactness"] == "exact" and rounded["exactness"] == "rounded"
    assert rounded["grade"] == exact["grade"] == VERIFIED
    assert rounded["record_ids"] == exact["record_ids"] == ["doc-one"]
    # And it travels the other way too: an exact operation over a rounded
    # operand cannot pretend the result came out.
    book.update(_shift({"x": rounded}, len(book)))
    onward = _computed(registry, book, "r + b", r=rounded["id"], b="f2")
    assert onward["exactness"] == "rounded"


SMALL_AND_LARGE = (
    ("1.00", "a small amount", VERIFIED, "USD", ["doc-one"]),
    ("300000.00", "a large amount", VERIFIED, "USD", ["doc-two"]),
    ("1234.56", "an amount", VERIFIED, "USD", ["doc-three"]),
    ("98765.43", "another amount", VERIFIED, "USD", ["doc-four"]),
)


def test_a_ratio_is_written_to_significant_figures_and_never_down_to_zero(
        registry):
    """No dimensionless result that is not zero is written as zero, at any
    magnitude.

    Decimal places are money's scale, not a ratio's: a proportion smaller than
    a hundredth written at two decimal places becomes 0.00, which is not an
    approximation of it but a different claim — and one carrying the grade of
    the documents it was derived from. Counting from the leading digit instead
    cannot do that, whatever the magnitude."""
    book = _book(*SMALL_AND_LARGE)
    for expression, inputs in (
            ("a / b", {"a": "f1", "b": "f2"}),
            ("(a / b) * (a / b)", {"a": "f1", "b": "f2"}),
            ("(a / b) * (a / b) * (a / b)", {"a": "f1", "b": "f2"}),
            ("c / d", {"c": "f3", "d": "f4"}),
            ("d / c", {"c": "f3", "d": "f4"}),
            ("(d / c) * (d / c) * 1000000", {"c": "f3", "d": "f4"})):
        fig = _computed(registry, book, expression, **inputs)
        assert fig["exactness"] == "rounded", expression
        assert Decimal(fig["value"]) != 0, (
            f"{expression} came out as {fig['value']}, which is a claim about "
            "the world rather than an approximation of the answer")
        assert fig["currency"] == "" and fig["grade"] == VERIFIED, expression
        digits = len(Decimal(fig["value"]).as_tuple().digits)
        assert digits <= 6, f"{expression} kept {digits} significant figures"


def test_a_proportion_and_the_same_proportion_per_hundred_agree(registry):
    """The same quantity asked two ways gives the same answer. Counting
    significant figures from the leading digit means a power of ten moves the
    point without moving the digits, so scaling before or after the rounding
    cannot disagree."""
    book = _book(*SMALL_AND_LARGE)
    for over, inputs in (("a / b", {"a": "f1", "b": "f2"}),
                         ("c / d", {"c": "f3", "d": "f4"}),
                         ("d / c", {"c": "f3", "d": "f4"})):
        plain = _computed(registry, book, over, **inputs)
        hundred = _computed(registry, book, f"({over}) * 100", **inputs)
        assert (Decimal(hundred["value"]) == Decimal(plain["value"]) * 100), (
            f"{over} is {plain['value']} but per hundred is "
            f"{hundred['value']}")


def test_money_is_written_at_the_scale_money_is_counted_in(registry):
    """An amount of money is written to hundredths whatever the arithmetic did
    to it, because that is the precision money has."""
    book = _book(("2000.00", "a yearly amount", VERIFIED, "USD", ["doc-one"]))
    for expression, value in (("a / 52", "38.46"), ("a / 12", "166.67"),
                              ("a / 7", "285.71")):
        fig = _computed(registry, book, expression, a="f1")
        assert fig["value"] == value, expression
        assert fig["currency"] == "USD" and fig["exactness"] == "rounded"
        assert fig["grade"] == VERIFIED and fig["record_ids"] == ["doc-one"]


def test_a_rounding_is_taken_once_at_the_end(registry):
    """A third of an amount, tripled, comes back to the amount itself. It would
    not if the third had been written at two decimals before the walk carried
    it on."""
    book = _book(("100.00", "an amount", VERIFIED, "USD", ["doc-one"]))
    fig = _computed(registry, book, "a / 3 * 3", a="f1")
    assert Decimal(fig["value"]) == Decimal("100.00")
    assert fig["exactness"] == "rounded"


def test_an_exactness_nothing_recognises_is_refused_where_it_is_written():
    """A value outside the vocabulary raises where the figure is written. It
    would otherwise travel as an account of the arithmetic while meaning
    nothing to anything that reads it."""
    plain = dict(quantity=quantity.COUNT)
    assert figure("1", "a thing", **plain)["exactness"] == "exact"
    assert figure("1", "a thing", exactness="rounded",
                  **plain)["exactness"] == "rounded"
    with pytest.raises(ValueError):
        figure("1", "a thing", exactness="roughly", **plain)


def test_the_model_is_told_only_when_a_figure_has_something_to_say():
    """A figure whose arithmetic came out exactly omits the field; one that had
    to be rounded sends it. Every result is resent on every remaining call of
    the turn, so a field carrying the ordinary case is paid for repeatedly."""
    ordinary = ToolResult(tool="t", ok=True,
                          figures=[figure("1.00", "a thing", currency="USD",
                                          quantity=quantity.BALANCE,
                                          record_ids=["doc-one"])])
    assert "exactness" not in ordinary.to_dict()["figures"][0]
    approximate = ToolResult(tool="t", ok=True,
                             figures=[figure("1.00", "a thing", currency="USD",
                                             quantity=quantity.BALANCE,
                                             record_ids=["doc-one"],
                                             exactness="rounded")])
    assert approximate.to_dict()["figures"][0]["exactness"] == "rounded"


def _approximate_run(registry, shape, bind, expression="a / 7",
                     read=("balances", None), over="Everyday Checking"):
    """One run whose answer states a figure the arithmetic had to round.

    `read` is the entity the run looks at and `over` the figure of it the
    arithmetic is done on, so the same run can be had over an amount, over a
    number of things, or over a proportion of one by another.

    The second call is written by hand rather than scripted because it binds a
    figure id the first call produced."""
    entity, filters = read
    args = {"entity": entity}
    if filters:
        args["filters"] = filters

    def planner(context):
        if not context["shaped"]:
            return {"shape": shape}
        done = [r for r in context["results"] if r["tool"] != "commit_shape"]
        if not done:
            return {"tool": "query_ledger", "args": args}
        if len(done) == 1:
            return {"tool": "compute",
                    "args": {"expression": expression,
                             "inputs": {"a": _fig(context["results"], over)}}}
        return {"bindings": bind(context["results"])}
    return run("how much a week?", planner, registry)


def test_an_approximate_value_never_reaches_the_person_bare(registry):
    """A figure the arithmetic could not write exactly reaches the person
    carrying the term that says so.

    The shape asks for nothing of the kind and could not: it was written before
    any arithmetic happened, so hedging cannot be something the sentence
    remembered to do. The term travels with the figure, placed where the figure
    is placed."""
    spoken = _approximate_run(
        registry,
        _shape(("You spend {weekly} a week.", [("weekly", "money", "balance")])),
        lambda results: {"weekly": {"figure": _fig(results, "result of")}})
    assert spoken.answered, spoken.detail
    assert spoken.text == "You spend about USD 85.71 a week."
    # The figure itself is unchanged; only what was written from it is hedged.
    assert spoken.figures[0]["value"] == "85.71"
    assert spoken.figures[0]["exactness"] == "rounded"


def test_an_approximate_number_of_things_never_reaches_the_person_bare(
        registry):
    """And the same of a count, which is a magnitude like any other.

    A number of things the arithmetic could not write exactly is written to the
    nearest whole thing, and the digits shown are the digits of the value: a
    count cut off at the point would be a different number, always smaller, and
    said with no sign that it had been rounded at all."""
    spoken = _approximate_run(
        registry,
        _shape(("You make this many a week: {weekly}.",
                [("weekly", "count", "count")])),
        lambda results: {"weekly": {"figure": _fig(results, "result of")}},
        expression="a * 5 / 7", read=("transactions", None),
        over="movements matching the filters")
    assert spoken.answered, spoken.detail
    assert spoken.text == "You make this many a week: about 3."
    assert spoken.figures[0]["value"] == "2.85714"
    assert spoken.figures[0]["exactness"] == "rounded"


def test_an_approximate_proportion_never_reaches_the_person_bare(registry):
    """And of a proportion, which is the third and last kind of magnitude a
    hole can hold. A share written to fewer digits than it was carried at is
    still a share that did not come out exactly."""
    spoken = _approximate_run(
        registry,
        _shape(("That is {share} of it.",
                [("share", "rate", quantity.ratio_of(quantity.BALANCE))])),
        lambda results: {"share": {"figure": _fig(results, "result of")}},
        expression="a / a / 7")
    assert spoken.answered, spoken.detail
    # One seventh, carried as the quotient and written per hundred.
    assert spoken.text == "That is about 14.2857% of it."
    assert spoken.figures[0]["exactness"] == "rounded"


def test_only_the_value_that_was_rounded_is_hedged(registry):
    """The term reaches what the arithmetic could not write exactly, and
    nothing else.

    One sentence states an exact balance and an approximate weekly share of it,
    deliberately: a rule that hedged every amount would satisfy an assertion
    made with approximate figures alone."""
    spoken = _approximate_run(
        registry,
        _shape(("Of {held} you spend {weekly} a week.",
                [("held", "money", "balance"), ("weekly", "money", "balance")])),
        lambda results: {"held": {"figure": _fig(results, "Everyday Checking")},
                         "weekly": {"figure": _fig(results, "result of")}})
    assert spoken.answered, spoken.detail
    assert spoken.text == ("Of USD 600.00 you spend about USD 85.71 a week.")


# ------------------------------------ what a money figure is allowed to lack

def test_every_money_figure_a_tool_emits_stands_on_a_record():
    """Every figure stating a currency carries at least one record.

    The attestation rule uses "carries a record" as the proxy for "is
    attested", so an amount emitted with nothing behind it would let a
    magnitude added to it inherit an attestation nothing earned, or would
    strip a legitimate total of the evidence it did have."""
    for what, fig in _every_figure().items():
        if fig["currency"]:
            assert fig["record_ids"], (
                f"{what!r} is an amount of money standing on no record")


def test_a_quiet_window_is_still_an_amount_and_still_stands_on_something(
        registry):
    """A window in which nothing moved has a total, and that total is zero of a
    currency, resting on the accounts whose statements answer for the period.
    Saying neither would make the zero read as a plain number, which no balance
    can be put together with at all."""
    quiet = {"entity": "transactions",
             "filters": {"window": {"from": "2026-06-01", "to": "2026-06-30"}}}
    summary = registry.call("query_ledger", quiet)
    assert summary.ok and summary.data["count"] == 0
    net = next(f for f in summary.figures
               if f["what"] == "net movement over this set")
    assert net["currency"] == "USD" and net["record_ids"]
    book = _one_figure(registry, "query_ledger", {"entity": "balances"})
    book.update(_shift(_one_figure(registry, "query_ledger", quiet), len(book)))
    balance = next(f["id"] for f in book.values()
                   if "Everyday Checking" in f["what"])
    still = next(f["id"] for f in book.values()
                 if f["what"] == "net movement over this set")
    combined = _computed(registry, book, "a - b", a=balance, b=still)
    assert combined["currency"] == "USD" and combined["grade"]


def test_a_refusal_to_add_says_what_it_actually_saw(registry):
    """The refusal names what was observed — that one side states a currency
    and the other states none — rather than guessing at what the plain side
    counts or measures."""
    book = _book(("600.00", "an amount", VERIFIED, "USD", ["doc-one"]),
                 ("7", "a count of things", VERIFIED, "", ["doc-two"]))
    refused = registry.call("compute", {"expression": "a + n",
                                        "inputs": {"a": "f1", "n": "f2"}},
                            figures=book)
    assert not refused.ok and refused.refusal == "mixed_dimensions"
    assert "count or a ratio" not in refused.text
    assert "states a currency" in refused.text


def test_two_amounts_divide_into_a_ratio_and_never_into_money(registry):
    """Asking how a balance compares with a total is division, and its
    answer is "three times over", not "three dollars". A currency on a ratio is
    a claim about money that no money was ever measured for."""
    book = {}
    for i, (amount, grade) in enumerate((("600.00", VERIFIED),
                                         ("200.00", UNVERIFIED)), 1):
        f = figure(amount, f"an amount {i}", quantity=quantity.BALANCE,
                   grade=grade, currency="USD",
                   record_ids=[f"doc-{i}"])
        f["id"] = f"f{i}"
        book[f["id"]] = f
    ratio = registry.call("compute", {"expression": "a / b",
                                      "inputs": {"a": "f1", "b": "f2"}},
                          figures=book)
    assert ratio.ok and Decimal(ratio.figures[0]["value"]) == 3
    assert ratio.figures[0]["currency"] == ""
    assert set(ratio.record_ids) == {"doc-1", "doc-2"}
    assert ratio.figures[0]["grade"] == UNVERIFIED
    product = registry.call("compute", {"expression": "a * b",
                                        "inputs": {"a": "f1", "b": "f2"}},
                            figures=book)
    assert not product.ok and product.refusal == "mixed_dimensions"
    inverted = registry.call("compute", {"expression": "2 / a",
                                         "inputs": {"a": "f1"}}, figures=book)
    assert not inverted.ok and inverted.refusal == "mixed_dimensions"
    # Splitting an amount by a plain number is still an amount of money.
    split = registry.call("compute", {"expression": "a / 3",
                                      "inputs": {"a": "f1"}}, figures=book)
    assert split.ok and split.figures[0]["currency"] == "USD"
    assert split.figures[0]["grade"] == VERIFIED


def test_a_balance_still_combines_with_what_a_summary_totalled(registry):
    """The two questions a person actually asks across reads — a balance less
    what moved over a set, a balance less a total spent — are money and money,
    and they must go through. A total that failed to state its currency would
    read as a plain number and turn both into refusals."""
    book = _one_figure(registry, "query_ledger", {"entity": "balances"})
    book.update(_shift(_one_figure(registry, "query_ledger",
                                   {"entity": "transactions"}), len(book)))
    book.update(_shift(_one_figure(registry, "query_ledger",
                                   {"entity": "aggregate",
                                    "metric": "spending"}), len(book)))
    balance = next(f["id"] for f in book.values()
                   if "Everyday Checking" in f["what"])
    net = next(f["id"] for f in book.values()
               if f["what"] == "net movement over this set")
    spent = next(f["id"] for f in book.values()
                 if f["what"].startswith("total spending"))
    counted = next(f["id"] for f in book.values()
                   if f["what"] == "movements matching the filters")
    for expression, inputs in (("a - b", {"a": balance, "b": net}),
                               ("a - b", {"a": balance, "b": spent})):
        result = registry.call("compute", {"expression": expression,
                                           "inputs": inputs}, figures=book)
        assert result.ok, f"{expression}: {result.text}"
        assert result.figures[0]["currency"] == "USD"
        assert result.figures[0]["kind"] == "computed"
        assert result.figures[0]["grade"] and result.record_ids
    # And the two that must not: an amount times an amount, and a count added
    # to an amount.
    for expression, inputs in (("a * b", {"a": balance, "b": spent}),
                               ("a + b", {"a": balance, "b": counted})):
        refused = registry.call("compute", {"expression": expression,
                                            "inputs": inputs}, figures=book)
        assert not refused.ok, f"{expression} came back as {refused.figures}"
        assert refused.refusal == "mixed_dimensions"


def test_what_a_total_measures_follows_from_what_its_terms_measure(registry):
    """What is held taken together with what moved is still what is held, so a
    balance less what was spent is a balance and can be asked about as one.
    Two different flows are two different questions and their sum answers
    neither, so the arithmetic refuses rather than hand back a number whose
    meaning the reader would have to supply."""
    book = _one_figure(registry, "query_ledger", {"entity": "balances"})
    book.update(_shift(_one_figure(registry, "query_ledger",
                                   {"entity": "transactions"}), len(book)))
    book.update(_shift(_one_figure(registry, "query_ledger",
                                   {"entity": "aggregate",
                                    "metric": "spending"}), len(book)))
    of = {f["what"]: f["id"] for f in book.values()}
    balance = next(i for w, i in of.items() if "Everyday Checking" in w)
    spent = next(i for w, i in of.items() if w.startswith("total spending"))
    gross = of["money out over these movements"]

    left = registry.call("compute", {"expression": "a - b",
                                     "inputs": {"a": balance, "b": spent}},
                         figures=book)
    assert left.ok and left.figures[0]["quantity"] == quantity.BALANCE

    both = registry.call("compute", {"expression": "a + b",
                                     "inputs": {"a": spent, "b": gross}},
                         figures=book)
    assert not both.ok and both.refusal == "mixed_quantities"


def test_only_a_flow_taken_out_of_a_stock_is_still_that_stock(registry):
    """Which way round the two stand, and which way the operator runs, are both
    part of what the total measures.

    What is held, less what was spent, is what is left. Nothing else about that
    pair is a balance: what was spent less what is held is a magnitude with the
    wrong sign and no referent, and what is held plus what was spent is larger
    than anything the person has. Each of those, called a balance, is a true
    number under a false description — every record real, every grade earned,
    and the sentence a lie about what was measured. So they refuse."""
    book = _one_figure(registry, "query_ledger", {"entity": "balances"})
    book.update(_shift(_one_figure(registry, "query_ledger",
                                   {"entity": "aggregate",
                                    "metric": "spending"}), len(book)))
    of = {f["what"]: f["id"] for f in book.values()}
    held = next(i for w, i in of.items() if "Everyday Checking" in w)
    spent = next(i for w, i in of.items() if w.startswith("total spending"))
    left_over = Decimal(book[held]["value"]) - Decimal(book[spent]["value"])

    kept = registry.call("compute", {"expression": "held - spent",
                                     "inputs": {"held": held, "spent": spent}},
                         figures=book)
    assert kept.ok, kept.text
    assert kept.figures[0]["quantity"] == quantity.BALANCE
    assert Decimal(kept.figures[0]["value"]) == left_over

    for expression in ("spent - held", "held + spent", "spent + held"):
        refused = registry.call("compute",
                                {"expression": expression,
                                 "inputs": {"held": held, "spent": spent}},
                                figures=book)
        assert not refused.ok, (
            f"{expression} came back as "
            f"{refused.figures[0]['value']} of "
            f"{refused.figures[0]['quantity']}")
        assert refused.refusal == "mixed_quantities", expression


def test_splitting_a_quantity_leaves_it_the_quantity_it_was(registry):
    """A year's spending over its months is spending, so the answer to "on
    average" is bindable where the answer to "in total" is. What it must not
    become is a proportion: dividing by a count is splitting an amount up, not
    comparing two things."""
    book = _one_figure(registry, "query_ledger", {"entity": "transactions"})
    of = {f["what"]: f["id"] for f in book.values()}
    gross = of["money out over these movements"]
    months = of["months these movements span"]
    per_month = registry.call("compute", {"expression": "a / b",
                                          "inputs": {"a": gross, "b": months}},
                              figures=book)
    assert per_month.ok, per_month.text
    assert per_month.figures[0]["quantity"] == quantity.GROSS_FLOW
    assert per_month.figures[0]["currency"] == "USD"


def test_two_measured_things_divide_into_a_proportion(registry):
    """Comparing an amount with an amount, or a count with a count, gives a
    number of times over rather than an amount or a count of anything — which
    is what a proportion is, and it is the only way one is ever produced."""
    book = _one_figure(registry, "query_ledger", {"entity": "transactions"})
    of = {f["what"]: f["id"] for f in book.values()}
    for a, b in ((of["money out over these movements"],
                  of["net movement over this set"]),
                 (of["movements matching the filters"],
                  of["months these movements span"])):
        share = registry.call("compute", {"expression": "a / b",
                                          "inputs": {"a": a, "b": b}},
                              figures=book)
        assert share.ok, share.text
        assert quantity.is_ratio(share.figures[0]["quantity"])
        assert share.figures[0]["currency"] == ""


def test_a_quotient_carries_what_its_operands_measured(registry):
    """A quotient's quantity comes from its operands: two figures of one kind
    give a proportion of that kind, and two of different kinds give a bare
    proportion, since no single kind is true of it."""
    book = _one_figure(registry, "query_ledger", {"entity": "transactions"})
    of = {f["what"]: f["id"] for f in book.values()}

    def divide(a, b):
        got = registry.call("compute", {"expression": "a / b",
                                        "inputs": {"a": of[a], "b": of[b]}},
                            figures=book)
        assert got.ok, got.text
        return got.figures[0]["quantity"]

    assert divide("net movement on card", "net movement on chk") == \
        quantity.ratio_of(quantity.NET_MOVEMENT)
    assert divide("movements matching the filters",
                  "months these movements span") == \
        quantity.ratio_of(quantity.COUNT)
    assert divide("money out over these movements",
                  "net movement over this set") == quantity.RATIO


def test_a_proportion_of_one_thing_is_not_a_proportion_of_another(registry):
    """The quantity check, reached through division: the hole asks about
    spending and the operands are gross flows, so the number is real and the
    description of it is not, and the answer is refused. The check compares two
    declarations, so the division has to carry one of them."""
    shape = _shape(("That is {share} of what you spend.",
                    [("share", "rate", quantity.ratio_of(quantity.SPENDING))]))

    def planner(context):
        if not context["shaped"]:
            return {"shape": shape}
        done = [r for r in context["results"] if r["tool"] != "commit_shape"]
        if not done:
            return {"tool": "query_ledger", "args": {"entity": "transactions"}}
        if len(done) == 1:
            gross = _fig(done, "money out over")
            return {"tool": "compute",
                    "args": {"expression": "a / b",
                             "inputs": {"a": gross, "b": gross}}}
        return {"bindings": {"share": {"figure": _fig(context["results"],
                                                      "result of")}}}

    assert run("what share of my spending goes there?",
               planner, registry).refusal == "wrong_quantity"


def test_compute_refuses_a_number_typed_in_and_names_what_it_has(registry):
    """The dead end this ends: a model retyping values it read and computing
    over them succeeded call after call, and the answer was refused at the very
    end. Now the first call says no and says what the operands could be."""
    book = _one_figure(registry, "query_ledger", {"entity": "balances"})
    refused = registry.call("compute",
                            {"expression": "a", "inputs": {"a": "600.00"}},
                            figures=book)
    assert not refused.ok and refused.refusal == "bad_input"
    offered = {f["id"] for f in refused.data["available_figures"]}
    assert offered == set(book)


def test_compute_over_something_only_the_person_said_is_hypothetical(registry):
    """Arithmetic on the person's own premise is answerable and is not an
    evidence claim: it carries no grade, and it says which it is."""
    book = _one_figure(registry, "query_ledger", {"entity": "balances"})
    balance = next(f["id"] for f in book.values() if "balance" in f["what"])
    result = registry.call("compute",
                           {"expression": "have - trip",
                            "inputs": {"have": balance,
                                       "trip": {"stipulated": "250"}}},
                           figures=book, question="could I afford a 250 trip?")
    assert result.ok
    assert result.figures[0]["kind"] == "hypothetical"
    assert result.figures[0]["grade"] == ""
    # An amount they named is money in the currency of what it is set against,
    # so the subtraction goes through and the answer is an amount.
    assert (Decimal(result.figures[0]["value"])
            == Decimal(book[balance]["value"]) - 250)
    assert result.figures[0]["currency"] == "USD"


def test_compute_refuses_a_stipulation_the_person_never_made(registry):
    book = _one_figure(registry, "query_ledger", {"entity": "balances"})
    result = registry.call("compute",
                           {"expression": "trip",
                            "inputs": {"trip": {"stipulated": "854203"}}},
                           figures=book, question="could I afford a 250 trip?")
    assert not result.ok and result.refusal == "bad_input"


def test_compute_refuses_what_it_cannot_do_exactly(registry):
    def call(args):
        return registry.call("compute", args, figures={})
    assert call({"expression": "0.1 + 0.2",
                 "inputs": {}}).refusal == "bad_expression"
    assert call({"expression": "a + 1", "inputs": {}}).refusal == "bad_expression"
    assert call({"expression": "__import__('os')",
                 "inputs": {}}).refusal == "bad_expression"
    assert call({"expression": "1 / 0",
                 "inputs": {}}).refusal == "division_by_zero"


# ------------------------------------------------------- what a result costs

# The counterparties this ledger spends at — a pool a person could plausibly
# have over a year, cycled through, so that grouping by counterparty produces
# far more groups than one read may name. Every one is synthetic.
COUNTERPARTIES = [f"COUNTERPARTY {chr(65 + i // 26)}{chr(65 + i % 26)} DESCRIPTOR"
                  for i in range(60)]


def _ledger(accounts=6, months=12, per_month=3, docs=12, actions=0):
    """The read tools over a ledger a person could actually have."""
    return default_registry(LedgerProjection(
        _ledger_events(accounts, months, per_month, docs, actions)))


def _ledger_events(accounts=6, months=12, per_month=3, docs=12, actions=0):
    """A ledger built through the real event constructors, at a shape a person
    could actually have. Every value in it is synthetic."""
    evs, p = [], _p("doc-0000")
    for d in range(docs):
        evs.append(document_captured(f"doc-{d:04d}", f"s{d}.pdf", 10,
                                     "bank_statement", 0.9, "2026-02-01"))
    for a in range(accounts):
        evs.append(account_opened(f"acct{a}", "depository", f"Account {a}",
                                  "USD", "2025-01-01"))
        evs.append(opening_balance_observed(f"acct{a}", "1000.00",
                                            "2025-01-01", p))
        for m in range(1, months + 1):
            for d in range(per_month):
                evs.append(simple_transaction(
                    f"acct{a}", "-12.34",
                    COUNTERPARTIES[(a * 31 + m * 7 + d) % len(COUNTERPARTIES)],
                    f"2025-{m:02d}-{(d % 28) + 1:02d}", provenance=p))
    for i in range(actions):
        evs.append(agent_acted("enrich", "enrich", f"target-{i}", "done",
                               "2026-02-03", calls=1))
    return evs


def _payload(registry, tool, args):
    import json
    result = registry.call(tool, args)
    assert result.ok, result.text
    return len(json.dumps(result.to_dict()))


def test_what_a_read_costs_does_not_grow_with_the_ledger():
    """The defect that failed the first verification: a summary meant to shrink
    the payload carried one composite movement key per matching movement, on
    each of its figures, and grew instead. The guard has to scale its input or
    it measures a constant — this one holds the accounts and months fixed and
    multiplies the movements by ten."""
    from viva.tools.envelope import PAYLOAD_TARGET

    small = _payload(_ledger(per_month=3), "query_ledger",
                     {"entity": "transactions"})
    large = _payload(_ledger(per_month=30), "query_ledger",
                     {"entity": "transactions"})
    assert large < small * 1.2, (
        f"the summary grew from {small} to {large} when only the movement "
        "count changed; it is carrying the movements")
    assert large < PAYLOAD_TARGET


# The tools whose arguments no schema can enumerate, against what bounds each
# one instead. `list_movements` is the one read allowed past the budget and is
# held by its own row cap; the other two take a value only a run can supply — a
# record id another read emitted, or the figures a turn has already established
# — and each answers about exactly one of them. Every entry is measured by
# `test_what_the_sweep_cannot_enumerate_is_bounded_some_other_way`, so leaving
# a tool out of the sweep costs a bound rather than nothing.
UNENUMERABLE = ("list_movements", "get_provenance", "compute")


def _every_declared_call(registry) -> list:
    """Every call the registry's own schemas allow, generated from them.

    A parameter's enum IS the set of values a model may send, so the argument
    space is read off the schema rather than kept as a list beside it: a
    grouping or an entity added to a tool enters this sweep by existing.
    Optional fields are enumerated present and absent, and a field with no enum
    names a value only this vault could supply, so it is left unset."""
    import itertools
    calls = []
    for schema in registry.schemas():
        if schema["name"] in UNENUMERABLE:
            continue
        params = schema["parameters"]
        required = set(params.get("required", ()))
        choices = []
        for name, spec in sorted(params.get("properties", {}).items()):
            if "enum" not in spec:
                continue
            values = [{name: v} for v in spec["enum"]]
            if name not in required:
                values.append({})
            choices.append(values)
        for combination in itertools.product(*choices):
            args: dict = {}
            for part in combination:
                args.update(part)
            if required <= set(args):
                calls.append((schema["name"], args))
    return calls


def test_the_sweep_reaches_every_tool_or_says_which_it_does_not():
    """Every tool is either swept over its whole declared argument space or
    named in `UNENUMERABLE`, so what sits outside the sweep is written down
    rather than implied. A name in `UNENUMERABLE` that no tool answers to is a
    guard pointing at nothing, and fails here too."""
    registry = _ledger()
    named = {schema["name"] for schema in registry.schemas()}
    swept = {tool for tool, _ in _every_declared_call(registry)}

    assert set(UNENUMERABLE) <= named, sorted(set(UNENUMERABLE) - named)
    assert swept | set(UNENUMERABLE) == named, (
        "not swept and not declared unenumerable: "
        + str(sorted(named - swept - set(UNENUMERABLE))))


def test_what_the_sweep_cannot_enumerate_is_bounded_some_other_way():
    """Every name in `UNENUMERABLE` has a bound of its own, measured here
    against the largest input this vault can hand it: the capped read on every
    movement it holds, and the two run-supplied tools on a value a read actually
    emitted. Naming a tool unenumerable is what removes it from the budget
    sweep, so a tool added to the list with nothing measuring it fails here."""
    import json

    from viva.tools.envelope import PAYLOAD_TARGET
    from viva.tools.ledger_tools import MAX_ROWS

    registry = _ledger(per_month=30, docs=720)
    book = _one_figure(registry, "query_ledger", {"entity": "balances"})
    record = next(iter(book.values()))["record_ids"][0]
    measured = {
        "list_movements": registry.call("list_movements",
                                        {"filters": {"account": "acct0"}}),
        "get_provenance": registry.call("get_provenance", {"record_id": record}),
        "compute": registry.call(
            "compute", {"expression": "a", "inputs": {"a": "f1"}}, figures=book),
    }
    assert set(measured) == set(UNENUMERABLE), (
        "an unenumerable tool with nothing measuring it: "
        + str(sorted(set(UNENUMERABLE) - set(measured))))

    # Two bounds, and the wider one comes first: the whole ledger is not a
    # listing at all, and the widest listing there is stops at the row cap.
    assert not registry.call("list_movements", {}).ok
    rows = measured["list_movements"]
    assert rows.ok, rows.text
    assert len(rows.data["movements"]) <= MAX_ROWS
    assert rows.data["total"] > MAX_ROWS, "the fixture never reaches the cap"
    for tool in ("get_provenance", "compute"):
        result = measured[tool]
        assert result.ok, result.text
        assert len(json.dumps(result.to_dict())) <= PAYLOAD_TARGET, tool


def test_every_declared_call_answers_or_refuses_and_never_raises():
    """The read boundary's own contract, asserted over the argument space
    rather than over a sample: every call the schemas allow comes back as an
    envelope — an answer carrying the sentence a model reads, or a refusal
    carrying the machine tag that says which refusal it was. A tool that raises
    instead ends the turn with no sentence at all."""
    registry = _ledger()
    for tool, args in _every_declared_call(registry):
        result = registry.call(tool, args)
        if result.ok:
            assert result.text, f"{tool} {args} answered with no sentence"
        else:
            assert result.refusal, f"{tool} {args} refused with no machine tag"


def test_every_figure_the_argument_space_emits_matches_its_own_declaration():
    """Every figure the declared argument space emits names something, measures
    a known quantity, and agrees with itself: an amount of money states the
    currency it is in, and a number of things states none. Read over the whole
    space, so a grouping or an entity emitting a figure of a new kind cannot
    arrive disagreeing with its own declaration."""
    from viva import quantity
    from viva.render import COUNT, MONEY, QUANTITY_OF_TYPE

    registry = _ledger()
    seen = 0
    for tool, args in _every_declared_call(registry):
        for fig in registry.call(tool, args).figures:
            seen += 1
            assert fig["what"], f"{tool} {args} emitted a figure naming nothing"
            assert fig["quantity"] in quantity.MEASURES, (tool, args, fig)
            if fig["quantity"] in QUANTITY_OF_TYPE[MONEY]:
                assert fig["currency"], (tool, args, fig["what"])
            if fig["quantity"] in QUANTITY_OF_TYPE[COUNT]:
                assert not fig["currency"], (tool, args, fig["what"])
    assert seen, "the sweep emitted no figures to check"


def test_no_uncapped_read_exceeds_what_a_result_may_cost():
    """Every result is resent in full on every model call for the rest of the
    turn, so one oversized read is paid for as many times as the turn has left
    to run.

    What this proves: every combination of the enumerated arguments — each
    entity, each metric, each grouping, each transparency topic, present and
    absent — is inside the budget, generated from the schemas rather than
    listed here, so a read that fits under one grouping and not under another
    cannot pass by being absent from a list. What it does not reach: the
    parameters no enum bounds (filters, windows, accounts, record ids), and the
    three tools named in `UNENUMERABLE`."""
    import json

    from viva.tools.envelope import PAYLOAD_TARGET

    registry = _ledger(per_month=30, docs=720, actions=1000)
    calls = _every_declared_call(registry)
    assert len(calls) > 10, "the argument space collapsed to a handful of calls"
    for tool, args in calls:
        result = registry.call(tool, args)
        size = len(json.dumps(result.to_dict()))
        assert size <= PAYLOAD_TARGET, (
            f"{tool} {args} returned {size} characters, over {PAYLOAD_TARGET}")


def test_the_groups_a_capped_read_names_are_the_largest_ones():
    """Which groups a cap keeps is the honest half of capping.

    Naming ten groups and caveating away the rest is a true sentence whichever
    ten are named, so nothing about the payload's size can catch a read that
    keeps the smallest. What makes the cap answerable is that the money it
    names is the money there is most of, and that two reads of one ledger name
    the same ten."""
    proj = LedgerProjection(_ledger_events(per_month=30))
    result = default_registry(proj).call("query_ledger",
                                         {"entity": "aggregate",
                                          "metric": "spending",
                                          "group_by": "merchant"})
    everything, _ = ledger_tools._spending_rows(proj, {}, "merchant")
    named = {k: Decimal(v) for k, v in result.data["by_group"].items()}
    dropped = {k: v for k, v in everything.items() if k not in named}
    assert named and dropped
    assert min(named.values()) >= max(dropped.values())


def test_the_groups_a_cap_keeps_are_the_same_ones_on_every_read():
    """Ordered by magnitude, and ties broken by name — so a read repeated
    against an unchanged ledger names the same groups, and a person who asks
    twice is not told about two different sets of counterparties."""
    sized = {f"counterparty {chr(97 + i)}": Decimal(i) for i in range(30)}
    named, tail = ledger_tools._largest_groups(sized)
    assert len(named) == ledger_tools.MAX_GROUPS
    assert set(named) == set(sorted(sized, key=sized.get,
                                    reverse=True)[:ledger_tools.MAX_GROUPS])
    assert tail["count"] == len(sized) - len(named)
    assert tail["total"] == sum(v for k, v in sized.items() if k not in named)

    # All one size: nothing but the name can decide, and the name does — not
    # the order they happen to have been folded in.
    tied = {f"counterparty {chr(97 + i)}": Decimal("10")
            for i in reversed(range(30))}
    kept, _ = ledger_tools._largest_groups(tied)
    assert list(kept) == sorted(tied)[:ledger_tools.MAX_GROUPS]


def test_a_grouped_read_names_the_largest_and_caveats_the_tail_it_dropped():
    """A grouping is as wide as the vault's own vocabulary — by counterparty,
    the group count is the counterparty count — so a read that named every
    group would grow with the ledger. It names the largest, and what it did not
    name rides a caveat: the one thing a result carries that has an identity, can
    be placed in a sentence, and cannot be dropped from an answer that states a
    figure it sits behind. A coverage line would say it where nothing could
    speak it."""
    registry = _ledger(per_month=30)
    result = registry.call("query_ledger", {"entity": "aggregate",
                                            "metric": "spending",
                                            "group_by": "merchant"})
    assert result.ok
    groups = result.data["groups"]
    assert groups["total"] > ledger_tools.MAX_GROUPS
    assert groups["named"] == ledger_tools.MAX_GROUPS
    assert len(result.data["by_group"]) == ledger_tools.MAX_GROUPS
    dropped = groups["total"] - groups["named"]
    assert any(f"{dropped} smaller group(s)" in c for c in result.caveats)
    # The total is over everything counted, capped or not: what the cap dropped
    # is missing from the named groups, never from the sum.
    assert (sum(Decimal(v) for v in result.data["by_group"].values())
            < Decimal(result.data["total"]))


def test_the_row_cap_is_the_thing_that_bounds_a_detailed_read():
    """Not the announcement — the cap itself. Without it this read returns the
    whole ledger, which is the shape the whole cycle exists to end."""
    registry = _ledger(per_month=30)
    result = registry.call("list_movements", {"filters": {"account": "acct0"}})
    assert result.data["total"] > ledger_tools.MAX_ROWS
    assert result.data["shown"] == ledger_tools.MAX_ROWS
    assert len(result.data["movements"]) == ledger_tools.MAX_ROWS
    assert len(result.figures) == ledger_tools.MAX_ROWS


def test_a_summary_stands_on_the_documents_not_on_every_movement():
    """What a total rests on is the statements that attest the period. Naming
    every movement key instead is both a weaker claim to make and the shape
    that made this read grow; the individual keys belong to the read that
    returns individual rows."""
    registry = _ledger(per_month=30)
    summary = registry.call("query_ledger", {"entity": "transactions"})
    rows = registry.call("list_movements", {"filters": {"account": "acct0"}})
    keys = {r["record_id"] for r in rows.data["movements"]}
    assert keys and not (keys & set(summary.record_ids))
    assert all(r.startswith("doc-") or r.startswith("acct")
               for r in summary.record_ids)
    assert keys <= set(rows.record_ids)


def test_a_figures_records_do_not_travel_to_the_model():
    """The model cites an id; the runner resolves the records. Sending them
    would repeat a document id once per figure per result, on every model call
    for the rest of the turn — and the model could not use them if it had
    them."""
    registry = _ledger()
    result = registry.call("check_completeness", {})
    assert all(f["record_ids"] for f in result.figures)
    stated = result.to_dict()["figures"]
    assert all("record_ids" not in f for f in stated)
    assert all(f["records"] > 0 for f in stated)
    assert result.to_dict()["records"] == len(result.record_ids)


# -------------------------------------------------------------- the two reads

def test_a_date_a_read_asserted_may_be_said_without_declaring_it(registry):
    """`check_completeness` emits each account's as-of date as a figure whose
    value IS a date. A date the run's results carry may be written with no
    declaration; a date no result carries and no period covers still cannot be
    said at all."""
    dated = _one_figure(registry, "check_completeness", {})
    fig = next(f for f in dated.values() if "good as of" in f["what"])
    assert fig["value"] == "2026-01-31"

    shape = _shape(("Its evidence runs to {when}.", [("when", "date")]))

    def bind_to(iso):
        return lambda results: {"when": {"date": iso}}

    said = run("how current is it?",
               _script(shape, ("check_completeness", {}),
                       bind=bind_to("2026-01-31")), registry)
    assert said.answered, said.detail
    assert "2026-01-31" in said.text

    result = run("how current is it?",
                 _script(shape, ("check_completeness", {}),
                         bind=bind_to("2019-03-04")), registry)
    assert not result.answered and result.refusal == "unfounded_date"


def test_a_page_of_rows_can_be_written_without_declaring_every_date(registry):
    """A detailed read returns rows, and writing a row means writing its date.
    The read carries every one of those dates, so an answer listing them
    declares none.

    Only the dates are written here. A description is a statement's own words
    and may carry digits of its own, which no read licenses; a listing answer
    that writes one is refused."""
    shape = _shape(("They fell on {first} and {last}.",
                    [("first", "date"), ("last", "date")]))

    def planner(context):
        if not context["shaped"]:
            return {"shape": shape}
        done = [r for r in context["results"] if r["tool"] != "commit_shape"]
        if not done:
            return {"tool": "list_movements",
                    "args": {"filters": {"merchant": "greenfield market"}}}
        rows = done[0]["data"]["movements"]
        assert len(rows) > 1, "the fixture no longer returns several rows"
        return {"bindings": {"first": {"date": rows[0]["date"]},
                             "last": {"date": rows[-1]["date"]}}}
    spoken = run("when did I shop there?", planner, registry)
    assert spoken.answered, spoken.detail


def test_a_date_a_tool_echoed_from_its_own_arguments_is_not_thereby_sayable(registry):
    """A date a tool wrote into its own prose is not thereby sayable.

    A read that reports the `since` it was given writes that date into its own
    sentence, so dates are held out of the prose pool and the date rule alone
    decides whether one may be said."""
    echoed = registry.call("get_transparency",
                           {"topic": "calls_spent", "since": "2019-03-04"})
    assert "2019-03-04" in echoed.text, (
        "the fixture no longer echoes the caller's date into the tool's prose")

    shape = _shape(("Nothing since {when}.", [("when", "date")]))
    result = run("what have you spent?",
                 _script(shape,
                         ("get_transparency", {"topic": "calls_spent",
                                               "since": "2019-03-04"}),
                         bind=lambda r: {"when": {"date": "2019-03-04"}}),
                 registry)
    assert not result.answered and result.refusal == "unfounded_date"


def test_a_detailed_read_refuses_to_dump_the_whole_ledger(registry):
    """Whether the person asked to see rows is the model's judgment; that a
    read with no filter at all answers no question is not, so the code makes it
    inexpressible and names what would narrow it."""
    result = registry.call("list_movements", {"filters": {}})
    assert not result.ok and result.refusal == "too_broad"
    assert set(result.data["narrowing_filters"]) >= {"account", "category",
                                                     "merchant", "tag",
                                                     "window"}
    assert registry.call("list_movements",
                         {"filters": {"account": "chk"}}).ok


def test_a_capped_read_says_how_many_it_did_not_show(monkeypatch, registry):
    """A capped read says so in its own sentence, not only in a field.

    The sentence carries how many of how many were shown, in that order, and
    which filters reach the rest."""
    monkeypatch.setattr(ledger_tools, "MAX_ROWS", 1)
    result = registry.call("list_movements", {"filters": {"account": "chk"}})
    assert result.ok
    shown, total = result.data["shown"], result.data["total"]
    assert (shown, total) == (1, 3)
    said = result.text
    assert said.index(str(shown)) < said.index(str(total)), (
        "the sentence must say how many it showed, then how many there were")
    assert str(total) in said and "Narrow by" in said
    for name in ledger_tools.NARROWING:
        assert name in said, f"the sentence does not say it can narrow by {name}"
    # And the same sentence is what a model actually reads back.
    assert result.coverage == said


def test_the_transactions_read_returns_totals_and_no_rows(registry):
    """The read that returned a hundred and fifty thousand characters now
    answers in totals. Every one of them is a figure; none of the movements
    themselves comes back."""
    import json

    result = registry.call("query_ledger", {"entity": "transactions"})
    assert result.ok
    payload = json.dumps(result.to_dict())
    assert "transactions" not in result.data and "movements" not in result.data
    assert {"count", "money_in", "money_out", "net"} <= set(result.data)
    described = {f["what"] for f in result.figures}
    assert any("money in" in w for w in described)
    assert any("net movement" in w for w in described)
    assert len(payload) < 4000


def test_a_charge_on_a_card_is_money_out_of_the_summary():
    """The transactions summary reads direction off the account's kind, not off
    the posting's sign. A purchase on a liability is recorded positive — what is
    owed grew — and it is money gone, so a summary reading the sign alone gives
    every card purchase the right magnitude, the right records and the right
    grade under a false description of what it measures."""
    events = [
        account_opened("card", "liability", "Signature Card", "USD",
                       "2026-01-01", institution="Meridian Cards"),
        document_captured("doc-card", "card.pdf", 100, "card_statement", 0.9,
                          "2026-02-01"),
        simple_transaction("card", "500.00", "CITY GYM", "2026-01-08",
                           provenance=_p("doc-card")),
    ]
    result = default_registry(LedgerProjection(events)).call(
        "query_ledger", {"entity": "transactions"})
    assert result.ok, result.text
    assert result.data["money_out"] == "500.00"
    assert result.data["money_in"] == "0"
    assert result.data["net"] == "-500.00"
    of = {f["what"]: f["value"] for f in result.figures}
    assert of["money out over these movements"] == "500.00"
    assert of["money in over these movements"] == "0"
    assert of["net movement over this set"] == "-500.00"
    assert of["net movement on card"] == "-500.00"


def test_an_average_over_a_summary_has_a_divisor_it_can_cite(registry):
    """A summary states how many months it spans, as a figure with an id. It
    carries no currency, so dividing an amount by it yields an amount: that is
    what makes a per-month average expressible at all, since arithmetic takes
    figure ids and never a number the answer supplies."""
    book = _one_figure(registry, "query_ledger", {"entity": "transactions"})
    months = next(f for f in book.values()
                  if "months these movements span" in f["what"])
    assert months["value"] == "1" and months["currency"] == ""
    spent = next(f["id"] for f in book.values()
                 if "money out over these movements" in f["what"])
    result = registry.call("compute",
                           {"expression": "out / months",
                            "inputs": {"out": spent, "months": months["id"]}},
                           figures=book)
    assert result.ok, result.text
    assert result.figures[0]["currency"] == "USD", (
        "money divided by a count is money")


def test_weakest_grade_orders_conflicted_below_unverified():
    assert weakest([VERIFIED, CORROBORATED]) == CORROBORATED
    assert weakest([CORROBORATED, "conflicted", UNVERIFIED]) == "conflicted"
    assert weakest([]) == ""


def test_a_grade_off_the_ladder_is_refused_where_it_is_written():
    """`weakest` ignores a grade it does not recognise, so an invented one
    would reach the person as a strength claim while counting for nothing in
    composition. The figure is where that is caught, not the answer."""
    plain = dict(quantity=quantity.COUNT)
    assert figure("1", "a thing", grade=CORROBORATED,
                  **plain)["grade"] == CORROBORATED
    assert figure("1", "a thing", **plain)["grade"] == ""
    with pytest.raises(ValueError):
        figure("1", "a thing", grade="pretty solid", **plain)
    # A kind that carries no grade still clears one rather than refusing it.
    assert figure("1", "a thing", kind="activity", grade=VERIFIED,
                  **plain)["grade"] == ""


# -------------------------------------------------------------------- runner

def test_every_tag_the_runner_can_refuse_with_is_declared():
    """A refusal is spoken from the pack by its tag, so a tag the vocabulary
    does not hold has no words behind it and would fail in front of a person.
    Read from the source rather than from a list someone maintains: every tag
    handed to the refusal, and every tag a hole's own check returns."""
    import ast
    import pathlib

    from viva.tools import runner as runner_module

    tree = ast.parse(pathlib.Path(runner_module.__file__).read_text())
    emitted = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "_refused" and node.args
                and isinstance(node.args[0], ast.Constant)):
            emitted.add(node.args[0].value)
        if (isinstance(node, ast.Return) and isinstance(node.value, ast.Tuple)
                and len(node.value.elts) == 3
                and isinstance(node.value.elts[1], ast.Constant)):
            emitted.add(node.value.elts[1].value)
    undeclared = sorted(t for t in emitted
                        if t and t not in runner_module.REFUSAL_TAGS)
    assert not undeclared, (
        f"{undeclared} can end a turn and is not in REFUSAL_TAGS, so nothing "
        "in the pack answers for it")


def test_scripted_planner_produces_a_cited_answer(registry):
    """The whole mechanism, end to end. The sentence is authored while the run
    holds nothing; the read then happens; then one reference per hole. At no
    point does anything but the renderer write a character of the figure."""
    shape = _shape(("Your {which} stands at {balance}.",
                    [("which", "account"), ("balance", "money", "balance")]))
    result = run(
        "what is my checking balance?",
        _script(shape,
                ("query_ledger", {"entity": "balances",
                                  "filters": {"account": "chk"}}),
                bind=lambda results: {
                    "which": {"entity": _entity(results, "chk")},
                    "balance": {"figure": _fig(results, "balance")}}),
        registry)
    assert result.answered and result.calls == 2
    assert result.grade == CORROBORATED
    assert result.text == "Your Everyday Checking stands at USD 600.00."
    assert result.figures[0]["record_ids"]
    # And what was said is kept as the structure it was.
    assert result.shape == shape.to_dict()
    assert set(result.bindings) == {"which", "balance"}


def test_a_figure_id_the_run_never_produced_is_refused(registry):
    """The replacement for citing a record the run never read: a model can no
    longer name a record at all, only an id, and an id it made up matches
    nothing."""
    result = run(
        "balance?",
        _script(_shape(("You have {total}.", [("total", "money", "balance")])),
                ("query_ledger", {"entity": "balances"}),
                bind=lambda results: {"total": {"figure": "f99"}}),
        registry)
    assert not result.answered and result.refusal == "unknown_figure"


def test_a_number_in_a_payload_but_in_no_figure_cannot_be_said(registry):
    """Payload laundering, dead — now by construction rather than by scanning.

    A holding's cost basis rides in `data`; the read emits its market value as
    a figure and says nothing about what it cost. A hole is filled by a
    reference into what the run established, and a number sitting in a payload
    has no identity to be referred to by."""
    holdings = registry.call("query_ledger", {"entity": "holdings"})
    buried = holdings.data["holdings"][0]["cost_basis"]
    assert all(buried != f["value"] for f in holdings.figures)
    assert not any(buried == item.get("label")
                   for item in holdings.identifiers)

    result = run(
        "what did it cost?",
        _script(_shape(("You paid {cost} for it.",
                        [("cost", "money", "balance")])),
                ("query_ledger", {"entity": "holdings"}),
                bind=lambda results: {"cost": {"figure": "f99"}}),
        registry)
    assert not result.answered and result.refusal == "unknown_figure"


def test_a_financial_figure_standing_on_no_record_is_refused(registry):
    """A magnitude added to a counted thing leaves a number resting on no
    document: the term nothing measured injects a quantity rather than
    rescaling one, so the documents behind the count answer for a different
    number. It has an id, so it can be referred to — and it is refused anyway,
    because what a figure about money must stand on has not moved.

    This is the one rule carried over from the mechanism this replaced, word
    for word."""
    result = run(
        "how much?",
        _script(_shape(("That makes {total}.", [("total", "count", "count")])),
                ("check_completeness", {}),
                ("compute", {"expression": "n + 424242",
                             "inputs": {"n": "f1"}}),
                bind=lambda results: {
                    "total": {"figure": _fig(results, "result of")}}),
        registry)
    assert not result.answered and result.refusal == "uncited_figure"


def test_figure_ids_are_unique_across_tools_and_restart_each_turn(registry):
    seen = []
    shape = _shape(("Noted.", []))

    def planner(context):
        if not context["shaped"]:
            return {"shape": shape}
        done = [r for r in context["results"] if r["tool"] != "commit_shape"]
        if not done:
            return {"tool": "query_ledger", "args": {"entity": "balances"}}
        if len(done) == 1:
            return {"tool": "check_completeness", "args": {}}
        seen.extend(f["id"] for r in context["results"]
                    for f in r["figures"])
        return {"bindings": {}}

    first = run("what do you hold?", planner, registry)
    assert first.answered
    assert len(seen) == len(set(seen))
    assert seen[0] == "f1" and seen == [f"f{i}" for i in range(1, len(seen) + 1)]
    seen.clear()
    assert run("what do you hold?", planner, registry).answered
    assert seen[0] == "f1"                    # the id space is the turn's


def test_an_amount_the_person_never_said_cannot_be_echoed_back(registry):
    """A stipulation is the person's own number handed back to them. Its whole
    warrant is that they said it, so the gate checks the question itself."""
    shape = _shape(("The {trip} you mentioned is well within reach.",
                    [("trip", "supposed", "spending")]))
    result = run("could I afford a 3000 trip?",
                 _script(shape, ("check_completeness", {}),
                         bind=lambda r: {"trip": {"supposed": "5000"}}),
                 registry)
    assert not result.answered and result.refusal == "unfounded_stipulation"


def test_an_amount_the_person_did_say_may_be_said_back(registry):
    shape = _shape(("About the {trip} you mentioned — I can look at that.",
                    [("trip", "supposed", "spending")]))
    result = run("could I afford a 3000 trip?",
                 _script(shape, ("check_completeness", {}),
                         bind=lambda r: {"trip": {"supposed": "3000"}}),
                 registry)
    assert result.answered, result.detail
    assert "3000" in result.text
    assert result.grade == ""          # nothing here is an evidence claim


@pytest.mark.parametrize("part", ["300", "000", "00", "3"])
def test_a_piece_of_a_number_the_person_wrote_is_not_a_number_they_said(
        registry, part):
    """Their warrant is that they said it, and said it whole. A number matched
    inside another one lets a figure nobody named be handed back as the
    person's own — a tenth of what they asked about, or a hundredth, reading as
    something they themselves put on the table."""
    shape = _shape(("The {trip} you mentioned is well within reach.",
                    [("trip", "supposed", "spending")]))
    result = run("can I afford a 3000 trip?",
                 _script(shape, ("check_completeness", {}),
                         bind=lambda r: {"trip": {"supposed": part}}),
                 registry)
    assert not result.answered and result.refusal == "unfounded_stipulation"


def test_a_figure_the_person_supplied_is_written_as_theirs(registry):
    """A figure resting on their premise and on no record of theirs reads as
    one of ours unless something says otherwise, and "something in the sentence
    around it" is not a thing any check can hold anyone to. The marker is part
    of writing the value, so it cannot be left off."""
    from viva import persona, render

    shape = _shape(("About the {trip} you mentioned — I can look at that.",
                    [("trip", "supposed", "spending")]))
    result = run("could I afford a 3000 trip?",
                 _script(shape, ("check_completeness", {}),
                         bind=lambda r: {"trip": {"supposed": "3000"}}),
                 registry)
    assert result.answered, result.detail
    marked = persona.moment("supposed_amount",
                            amount=render.money("3000", locale=""))
    assert marked in result.text
    assert marked != "3000.00", "the marker adds nothing to the bare value"


def test_something_that_is_not_a_magnitude_cannot_arrive_as_a_supposition(
        registry):
    """The hole holds a figure the person supplied. Words are not a figure, and
    a hole that took them would be prose nobody reviewed reaching a person
    through the one binding that carries a value at all."""
    shape = _shape(("The {trip} you mentioned is well within reach.",
                    [("trip", "supposed", "spending")]))
    result = run("could I afford a 3000 trip?",
                 _script(shape, ("check_completeness", {}),
                         bind=lambda r: {"trip": {"supposed": "3000 or so, "
                                                  "whatever you think"}}),
                 registry)
    assert not result.answered and result.refusal == "unfounded_stipulation"


def test_a_hypothetical_figure_carries_no_grade_and_sets_none(registry):
    """Arithmetic over a premise is answerable and is not evidence. It can be
    spoken; it cannot make an answer look verified."""
    shape = _shape(("Supposing the {trip} trip, {left} would be left — that "
                    "rests on your figure, not on a statement.",
                    [("trip", "supposed", "spending"),
                     ("left", "money", "balance")]))

    def planner(context):
        if not context["shaped"]:
            return {"shape": shape}
        done = [r for r in context["results"] if r["tool"] != "commit_shape"]
        if not done:
            return {"tool": "query_ledger", "args": {"entity": "balances",
                                                     "filters": {"account": "chk"}}}
        if len(done) == 1:
            return {"tool": "compute",
                    "args": {"expression": "have - trip",
                             "inputs": {"have": _fig(context["results"],
                                                     "balance"),
                                        "trip": {"stipulated": "250"}}}}
        return {"bindings": {"trip": {"supposed": "250"},
                             "left": {"figure": _fig(context["results"],
                                                     "result of")}}}
    result = run("could I afford a 250 trip?", planner, registry)
    assert result.answered, result.text
    assert result.figures[0]["kind"] == "hypothetical"
    assert result.figures[0]["grade"] == ""
    assert result.grade == ""


def test_a_supposition_does_not_wear_off_after_one_hop(registry):
    """The label has to survive being carried. If it only lasts one step, a
    number the person made up passes through arithmetic once and comes out
    inside a figure the product calls verified — which is the laundering
    figure identity was adopted to make impossible, arriving by a longer
    route."""
    book = _one_figure(registry, "query_ledger", {"entity": "balances"})
    balance = next(f["id"] for f in book.values()
                   if "Everyday Checking" in f["what"])
    other = next(f["id"] for f in book.values()
                 if "Signature Card" in f["what"])
    first = registry.call("compute",
                          {"expression": "have - trip",
                           "inputs": {"have": balance,
                                      "trip": {"stipulated": "250"}}},
                          figures=book, question="could I afford a 250 trip?")
    supposed = first.figures[0]
    supposed["id"] = f"f{len(book) + 1}"
    book[supposed["id"]] = supposed
    assert supposed["kind"] == "hypothetical" and supposed["grade"] == ""

    second = registry.call("compute",
                           {"expression": "a + b",
                            "inputs": {"a": supposed["id"], "b": other}},
                           figures=book, question="and altogether?")
    assert second.figures[0]["kind"] == "hypothetical", (
        "a supposition wore off after one hop")
    assert second.figures[0]["grade"] == ""
    assert second.grade == ""


def test_an_answers_grade_ignores_activity_and_hypothetical_figures(registry):
    """A grade is an evidence claim. What the agent did, and what the person
    supposed, are neither — so neither may set or soften an answer's grade."""
    shape = _shape(("I have taken {actions} action(s); your balance is "
                    "{balance}.",
                    [("actions", "count", "count"),
                     ("balance", "money", "balance")]))

    def planner(context):
        if not context["shaped"]:
            return {"shape": shape}
        done = [r for r in context["results"] if r["tool"] != "commit_shape"]
        if not done:
            return {"tool": "get_transparency",
                    "args": {"topic": "agent_activity"}}
        if len(done) == 1:
            return {"tool": "query_ledger",
                    "args": {"entity": "balances", "filters": {"account": "chk"}}}
        return {"bindings": {
            "actions": {"figure": _fig(context["results"],
                                       "unattended actions")},
            "balance": {"figure": _fig(context["results"], "balance")}}}
    result = run("what have you done, and what is my balance?", planner, registry)
    assert result.answered, result.text
    kinds = {f["kind"] for f in result.figures}
    assert kinds == {"activity", "financial"}
    assert next(f for f in result.figures
                if f["kind"] == "activity")["record_ids"]
    # The load-bearing part: the activity figure is in the answer and its grade
    # is not. Give it a grade by hand — as a careless emitting tool would — and
    # the answer's grade must still be the balance's alone.
    activity = next(f for f in result.figures if f["kind"] == "activity")
    assert activity["grade"] == ""
    balance = next(f for f in result.figures if f["kind"] == "financial")
    assert result.grade == balance["grade"] == CORROBORATED

    from viva.tools.runner import _Ground, _gate
    ground = _Ground()
    for i, (kind, grade) in enumerate([("financial", CORROBORATED),
                                       ("activity", "conflicted")], 1):
        fig = figure("1", "a thing", quantity=quantity.COUNT, kind=kind,
                     record_ids=["r"])
        fig.update(id=f"f{i}", grade=grade)      # a tool that graded carelessly
        ground.book[fig["id"]] = fig
    both = _shape(("{a} and {b}.", [("a", "count", "count"),
                                    ("b", "count", "count")]))
    spoken = _gate({"bindings": {"a": {"figure": "f1"}, "b": {"figure": "f2"}}},
                   [], ground, both, "")
    assert spoken.answered, spoken.detail
    assert spoken.grade == CORROBORATED


def test_a_number_no_tool_returned_is_refused(registry):
    """A number no tool returned is not refused late, after a sentence has been
    written around it — it cannot be written at all. The words of a clause carry
    no digits, so the only route a magnitude has to a person is a hole, and a
    hole is filled from what the run established.

    Both halves are here: a shape that spells one out does not come into being,
    and a run whose planner tries it never reaches a read."""
    with pytest.raises(BadShape):
        _shape(("Your balance is about 9999.99.", []))

    def planner(context):
        if not context["shaped"]:
            return {"shape": {"clauses": [{"text": "About 9999.99.",
                                           "slots": []}]}}
        return {"bindings": {}}
    result = run("balance?", planner, registry)
    assert not result.answered and result.refusal == "bad_plan"


def test_a_ranging_read_reports_what_it_is_attested_for(registry):
    """A read that ranges over time says which account it is attested for and
    over what period; one that measures a moment carries its value-time
    instead."""
    ranging = registry.call("query_ledger", {"entity": "transactions"})
    assert ranging.ok and ranging.covers
    for entry in ranging.covers:
        assert entry["account"] and entry["from"] <= entry["to"]
    moment = registry.call("query_ledger", {"entity": "aggregate",
                                            "metric": "net_worth"})
    assert moment.ok and moment.covers == [] and moment.dated

def test_coverage_is_the_period_a_statement_attested_not_the_movement_dates(registry):
    """A statement posts only by reconciling, so its whole period is covered
    even where no movement falls. Reading the span off the movements instead
    would report a quiet fortnight as a hole in the evidence."""
    result = registry.call("query_ledger", {
        "entity": "aggregate", "metric": "spending",
        "filters": {"account": "chk",
                    "window": {"from": "2026-01-01", "to": "2026-01-31"}}})
    assert result.ok
    assert result.covers == [{"account": "chk", "from": "2026-01-01",
                              "to": "2026-01-31"}]
    assert not any("past the evidence" in c for c in result.caveats)


def test_a_window_reaching_past_what_is_attested_is_clipped_and_says_so(registry):
    result = registry.call("query_ledger", {
        "entity": "aggregate", "metric": "spending",
        "filters": {"account": "chk",
                    "window": {"from": "2020-01-01", "to": "2030-12-31"}}})
    assert result.ok
    assert result.covers == [{"account": "chk", "from": "2026-01-01",
                              "to": "2026-01-31"}]
    assert any("reaches past what its statements attest" in c
               for c in result.caveats)

def test_a_window_outside_what_is_attested_covers_nothing_and_says_which(registry):
    """Nothing spent and nothing attested must not read alike."""
    result = registry.call("query_ledger", {
        "entity": "aggregate", "metric": "spending",
        "filters": {"account": "chk",
                    "window": {"from": "2019-01-01", "to": "2019-12-31"}}})
    assert result.ok and result.covers == []
    assert any("none of which falls inside the window asked for" in c
               for c in result.caveats)


def test_a_filter_that_matches_nothing_still_reports_its_coverage(registry):
    """A category, tag, merchant or nature filter selects rows; it does not
    decide what the vault holds. A zero inside an attested period is money not
    spent, never evidence not held, and the two sentences are not
    interchangeable."""
    result = registry.call("query_ledger", {
        "entity": "aggregate", "metric": "spending",
        "filters": {"account": "chk", "nature": "transfer",
                    "window": {"from": "2026-01-01", "to": "2026-01-31"}}})
    assert result.ok
    assert result.covers == [{"account": "chk", "from": "2026-01-01",
                              "to": "2026-01-31"}]
    assert not any("no evidence" in c.lower() for c in result.caveats)


def test_an_account_with_no_statement_says_so_rather_than_guessing(registry):
    """An account whose period nothing attests borrows nothing from its
    movements: it reports no coverage and names itself."""
    result = registry.call("query_ledger", {"entity": "aggregate",
                                            "metric": "spending"})
    assert result.ok
    assert {c["account"] for c in result.covers} == {"chk"}
    assert any("No statement has posted for card" in c for c in result.caveats)

def test_the_window_asked_for_can_be_stated_in_the_answer(registry):
    """A span a read is attested for is a thing the read established, so the
    answer may say which period it is answering for — by referring to that
    span, never by writing its edges."""
    window = {"from": "2026-01-05", "to": "2026-01-20"}
    shape = _shape(("Over {span} you spent {total}.",
                    [("span", "period"), ("total", "money", "spending")]))
    result = run(
        "what did I spend then?",
        _script(shape,
                ("query_ledger", {"entity": "aggregate", "metric": "spending",
                                  "filters": {"window": window}}),
                bind=lambda results: {
                    "span": {"period": "p1"},
                    "total": {"figure": _fig(results, "total spending")}}),
        registry)
    assert result.answered, result.detail
    assert "2026-01-05 to 2026-01-20" in result.text


def test_a_period_a_read_is_attested_for_can_never_ground_a_figure(registry):
    """A period is scope — what a document answers for — and never a magnitude.
    It has its own kind, so binding one where an amount belongs is a type
    error rather than a matter of how the sentence was worded."""
    shape = _shape(("The figure is {total}.", [("total", "money", "balance")]))
    result = run(
        "?",
        _script(shape, ("query_ledger", {"entity": "aggregate",
                                         "metric": "spending"}),
                bind=lambda results: {"total": {"period": "p1"}}),
        registry)
    assert not result.answered and result.refusal == "wrong_kind"


def test_a_date_outside_everything_read_is_refused(registry):
    """A day none of this run's results carries cannot be said, and there is no
    longer any way to declare one into being."""
    shape = _shape(("Nothing to report since {when}.", [("when", "date")]))
    result = run(
        "when?",
        _script(shape, ("query_ledger", {"entity": "transactions"}),
                bind=lambda results: {"when": {"date": "2019-12-31"}}),
        registry)
    assert not result.answered and result.refusal == "unfounded_date"


def test_an_answer_has_no_way_to_name_a_record_at_all(registry):
    """This replaces the check that a figure citing an unread record is
    refused. That test guarded a rule the model could break; now it cannot
    reach the field. A cited figure is an id, and the records travel with the
    figure the tool emitted — so naming a record the run never read is not a
    thing an answer can express."""
    from viva.speak import FINAL_PARAMS
    from viva.tools.runner import BINDING_KEYS

    assert set(FINAL_PARAMS["properties"]) == {"bindings"}
    assert "record" not in BINDING_KEYS and "record_ids" not in BINDING_KEYS


def test_the_call_budget_ends_in_one_closing_attempt_then_refuses(registry):
    """Exhaustion spends one more model call with only the terminator on the
    table, because a turn holding a grounded figure should deliver it rather
    than die beside it. If that closing reply reaches for a tool anyway, the
    turn refuses — and the planner is not asked again."""
    closings = []
    shape = _shape(("Noted.", []))

    def planner(context):
        if not context["shaped"]:
            return {"shape": shape}
        closings.append(bool(context["final_call"]))
        return {"tool": "check_completeness", "args": {}}
    result = run("loop forever", planner, registry, max_calls=3)
    assert not result.answered and result.refusal == "call_budget_exhausted"
    assert result.calls == 3
    assert closings == [False, False, True]


def test_an_answer_delivered_on_the_closing_call_passes_the_gate_normally(registry):
    shape = _shape(("Your checking balance is {balance}.",
                    [("balance", "money", "balance")]))

    def planner(context):
        if not context["shaped"]:
            return {"shape": shape}
        if not context["final_call"]:
            return {"tool": "query_ledger", "args": {"entity": "balances",
                                                     "filters": {"account": "chk"}}}
        return {"bindings": {"balance": {"figure": _fig(context["results"],
                                                        "balance")}}}
    result = run("balance?", planner, registry, max_calls=3)
    assert result.answered and result.grade == CORROBORATED


def test_every_planner_context_says_how_many_calls_remain(registry):
    seen = []
    shape = _shape(("Noted.", []))

    def planner(context):
        seen.append(context["calls_remaining"])
        if not context["shaped"]:
            return {"shape": shape}
        if len(seen) < 3:
            return {"tool": "check_completeness", "args": {}}
        return {"bindings": {}}
    assert run("?", planner, registry, max_calls=4).answered
    assert seen == [4, 3, 2]


def test_a_refusal_result_flows_back_to_the_planner(registry):
    seen = {}
    shape = _shape(("It stands at {balance}.", [("balance", "money", "balance")]))

    def planner(context):
        if not context["shaped"]:
            return {"shape": shape}
        done = [r for r in context["results"] if r["tool"] != "commit_shape"]
        if not done:
            return {"tool": "query_ledger",
                    "args": {"entity": "balances",
                             "filters": {"account": "mystery"}}}
        seen["refusal"] = done[0]["refusal"]
        known = done[0]["data"]["known_accounts"][0]
        if len(done) == 1:
            return {"tool": "query_ledger", "args": {"entity": "balances",
                                                     "filters": {"account": known}}}
        return {"bindings": {"balance": {"figure": _figure(context["results"],
                                                           "balance")["id"]}}}
    result = run("balance of mystery?", planner, registry)
    assert seen["refusal"] == "unknown_account"
    assert result.answered and result.calls == 3


# ------------------------------------------------- what the statements attest

def _statement_doc(doc_id, account, opening, opening_date, closing,
                   closing_date, posted=None, read_at=None):
    """A document that declares its own period, the way ingestion records one.

    `posted` differs from `closing` when a person corrected a figure the model
    misread: the reply keeps what was read, the ledger carries what was
    accepted."""
    accepted = posted or closing
    return [document_captured(doc_id, f"{doc_id}.pdf", 2, "bank_statement", 0.9,
                              read_at or closing_date),
            read_recorded(doc_id, "model", "extract-v1", "text",
                          _statement_reply(opening, opening_date,
                                           closing, closing_date),
                          0.0, 1, 1, True, None, read_at or closing_date),
            closing_balance_observed(account, accepted, closing_date,
                                     _p(doc_id, 6))]


def _gapped_projection():
    """January and March held, February never ingested — and February's real
    net change is zero, so the balances continue across the hole."""
    evs = [account_opened("chk", "depository", "Everyday Checking", "USD",
                          "2026-01-01"),
           opening_balance_observed("chk", "1000.00", "2026-01-01", _p("d-jan"))]
    evs += _statement_doc("d-jan", "chk", "1000.00", "2026-01-01",
                          "900.00", "2026-01-31")
    evs += _statement_doc("d-mar", "chk", "900.00", "2026-03-01",
                          "800.00", "2026-03-31")
    return LedgerProjection(evs)


def test_statements_join_only_when_the_dates_meet_as_well_as_the_balances():
    """The ingest stitch joins on balances alone, so a missing month whose net
    change is zero passes it. Requiring the dates to meet is what keeps the
    missing statement visible."""
    proj = _gapped_projection()
    assert proj.attested_runs("chk") == [("2026-01-01", "2026-01-31"),
                                         ("2026-03-01", "2026-03-31")]


def test_a_window_inside_a_gap_between_statements_is_not_covered():
    """A window falling in a gap between statements is not reported as covered,
    and its zero is not reported as a fact."""
    registry = default_registry(_gapped_projection())
    result = registry.call("query_ledger", {
        "entity": "aggregate", "metric": "spending",
        "filters": {"account": "chk",
                    "window": {"from": "2026-02-01", "to": "2026-02-28"}}})
    assert result.ok and result.covers == []
    assert any("none of which falls inside the window" in c
               for c in result.caveats)


def test_a_window_spanning_a_gap_reports_both_periods_and_names_the_hole():
    registry = default_registry(_gapped_projection())
    result = registry.call("query_ledger", {
        "entity": "aggregate", "metric": "spending",
        "filters": {"account": "chk",
                    "window": {"from": "2026-01-01", "to": "2026-03-31"}}})
    assert result.covers == [
        {"account": "chk", "from": "2026-01-01", "to": "2026-01-31"},
        {"account": "chk", "from": "2026-03-01", "to": "2026-03-31"}]
    assert any("a statement between them is missing" in c
               for c in result.caveats)


def test_a_ledger_account_is_never_offered_as_one_with_no_statement(registry):
    """Only accounts a document opened are in scope. `Expenses:Uncategorized`
    is bookkeeping, and naming it in a caveat would be nonsense to a person."""
    result = registry.call("query_ledger", {"entity": "aggregate",
                                            "metric": "spending"})
    assert not any("Uncategorized" in c and "No statement" in c
                   for c in result.caveats)


def _uncategorized_projection():
    """One account and one spend nothing has categorized, so a spending read
    writes a caveat with an amount in it."""
    return LedgerProjection([
        account_opened("chk", "depository", "Everyday Checking", "USD",
                       "2026-01-01"),
        document_captured("doc-jan", "jan.pdf", 100, "bank_statement", 0.9,
                          "2026-02-01"),
        opening_balance_observed("chk", "5000.00", "2026-01-01", _p("doc-jan")),
        simple_transaction("chk", "-2665.44", "COUNTERPARTY ONE", "2026-01-05",
                           provenance=_p("doc-jan")),
        closing_balance_observed("chk", "2334.56", "2026-01-31",
                                 _p("doc-jan", 6)),
    ])


@pytest.mark.parametrize("locale", ["en-US", "de-DE"])
def test_an_amount_inside_a_caveat_is_written_like_every_other_amount(locale):
    """A caveat is a sentence a tool writes and an answer passes on verbatim,
    so an amount it spells for itself is a second convention arriving one line
    under the first. The read composes it through the same renderer, so the
    caveat and the answer above it write this person's money the same way."""
    from viva import render

    registry = default_registry(_uncategorized_projection(), locale)
    result = registry.call("query_ledger", {"entity": "aggregate",
                                            "metric": "spending",
                                            "group_by": "category"})
    assert result.ok
    written = render.money("2665.44", "USD", locale=locale)
    said = [c for c in result.caveats if "uncategorized" in c]
    assert said == [f"{written} is still uncategorized."]
    # And the figures the same read emits are written that way too, because
    # they go through the same function on their way to a hole.
    total = next(f for f in result.figures if f["what"].startswith("total"))
    assert render.money(total["value"], total["currency"],
                        locale=locale) == written


def _numbered_account_projection():
    """A vault whose account id carries the last four of its number, the shape
    `account_key` derives when a statement shows a number."""
    return LedgerProjection([
        account_opened("acct:northgate:4417", "depository", "Everyday Checking",
                       "USD", "2026-01-01", institution="Northgate Bank",
                       account_number="XX4417", account_names=["R VANCE"]),
        document_captured("doc-jan", "jan.pdf", 100, "bank_statement", 0.9,
                          "2026-02-01"),
        opening_balance_observed("acct:northgate:4417", "1000.00",
                                 "2026-01-01", _p("doc-jan")),
        closing_balance_observed("acct:northgate:4417", "600.00",
                                 "2026-01-31", _p("doc-jan", 6)),
    ])


def test_an_answer_may_name_the_account_it_is_about(registry):
    """An answer that cannot say which account it means answers nothing, and an
    account has several names — a ledger path, a name someone gave it, a masked
    number. It is one entity carrying all of them, so an answer refers to the
    entity and the renderer chooses the form. There is no second form to allow
    for, because there is no form the model gets to write."""
    numbered = default_registry(_numbered_account_projection())
    result = numbered.call("query_ledger", {"entity": "balances"})
    (account,) = result.identifiers
    assert account["kind"] == "account"
    assert account["account"] == "acct:northgate:4417"
    assert account["number_masked"] == "••••4417"
    assert account["name"] == "Everyday Checking"

    shape = _shape(("{which} holds {balance}.",
                    [("which", "account"), ("balance", "money", "balance")]))
    spoken = run("what do I have?",
                 _script(shape, ("query_ledger", {"entity": "balances"}),
                         bind=lambda results: {
                             "which": {"entity": _entity(results, "northgate")},
                             "balance": {"figure": _fig(results, "balance")}}),
                 numbered)
    assert spoken.answered, spoken.detail
    assert spoken.text == "Everyday Checking holds USD 600.00."
    # And the run of digits inside that name never reaches the person on its
    # own, because nothing but the renderer ever writes the name.
    assert "4417" not in spoken.text


def _twin_account_projection():
    """Two accounts a person gave the same name, at different institutions —
    the ordinary case of a name that does not tell one from another."""
    evs = []
    for key, inst, number, opening in (
            ("acct:northgate:4417", "Northgate Bank", "XX4417", "1000.00"),
            ("acct:meridian:9082", "Meridian Bank", "XX9082", "2500.00")):
        evs += [
            account_opened(key, "depository", "Everyday Checking", "USD",
                           "2026-01-01", institution=inst,
                           account_number=number),
            opening_balance_observed(key, opening, "2026-01-01", _p("doc-jan")),
        ]
    evs.insert(0, document_captured("doc-jan", "jan.pdf", 100, "bank_statement",
                                    0.9, "2026-02-01"))
    return LedgerProjection(evs)


def test_two_accounts_a_person_named_the_same_are_told_apart(registry):
    """A name that names two things names neither. Where the name a person gave
    an account does not tell it from another the run also spoke about, the
    masked number goes with it — and where nothing collides, the plain name
    stands, because a number shown for no reason is noise."""
    twins = default_registry(_twin_account_projection())
    shape = _shape(("{which} holds {balance}.",
                    [("which", "account"), ("balance", "money", "balance")]))

    def spoken_for(reg, handle):
        return run("what do I have?",
                   _script(shape, ("query_ledger", {"entity": "balances"}),
                           bind=lambda results: {
                               "which": {"entity": _entity(results, handle)},
                               "balance": {"figure": _fig(results, "balance")}}),
                   reg)

    ambiguous = spoken_for(twins, "northgate")
    assert ambiguous.answered, ambiguous.detail
    assert ambiguous.text.startswith("Everyday Checking ••••4417 holds")

    alone = spoken_for(default_registry(_numbered_account_projection()),
                       "northgate")
    assert alone.answered, alone.detail
    assert alone.text.startswith("Everyday Checking holds")


def test_an_account_two_reads_spoke_about_is_not_its_own_twin(registry):
    """One account named by two reads is one account.

    Given a second identity it would collide with itself, and the renderer that
    tells two same-named accounts apart would dutifully write the number out
    beside a name nothing was competing with — an account written twice in one
    breath because the run had counted it twice."""
    numbered = default_registry(_numbered_account_projection())
    shape = _shape(("{which} holds {balance}.",
                    [("which", "account"), ("balance", "money", "balance")]))

    spoken = run("what do I have?",
                 _script(shape,
                         ("query_ledger", {"entity": "balances"}),
                         ("query_ledger", {"entity": "balances"}),
                         bind=lambda results: {
                             "which": {"entity": _entity(results, "northgate")},
                             "balance": {"figure": _fig(results, "balance")}}),
                 numbered)
    assert spoken.answered, spoken.detail
    assert spoken.text == "Everyday Checking holds USD 600.00.", (
        "a second read of one account made it collide with itself")
    assert "4417" not in spoken.text


def test_two_reads_saying_the_same_thing_say_it_once(registry):
    """A caveat is a thing, not an occurrence of one.

    Every read of the same kind writes the same sentence about what its numbers
    do not cover. If each occurrence were its own caveat, an answer standing on
    four of those reads would have to say the identical sentence four times to
    get past the gate — and a sentence repeated four times reads as a machine
    stuttering, not as a limit being disclosed."""
    from viva.tools.envelope import ENTITY_ACCOUNT, ToolResult, entity
    from viva.tools.runner import _Ground

    def read():
        return ToolResult(
            tool="query_ledger", ok=True,
            caveats=["Each line is only as current as its stalest input."],
            identifiers=[entity(ENTITY_ACCOUNT, account="acct:northgate:4417",
                                name="Everyday Checking",
                                number_masked="••••4417")],
            figures=[figure("600.00", "Everyday Checking — balance",
                            quantity=quantity.BALANCE, currency="USD",
                            grade=VERIFIED, record_ids=["doc-jan"])])

    ground = _Ground(question="what do I have?")
    for _ in range(4):
        ground.stamp(read())

    assert list(ground.caveats) == ["c1"], "one sentence, one caveat"
    assert list(ground.entities) == ["a1"], "one account, one identity"
    # Four figures, though: each read established its own number, and every one
    # of them owes the one caveat, so placing it once answers for all four.
    assert len(ground.book) == 4
    assert {ids for ids in ground.owed.values()} == {("c1",)}


def _brokerage_reply():
    import json
    return json.dumps({"as_of_raw": "2026-01-31", "cash_raw": "100.00",
                       "total_raw": "1600.00",
                       "positions": [{"instrument": "ALPHA FUND",
                                      "units_raw": "10",
                                      "market_value_raw": "1500.00"}]})


def _corrected_projection():
    """Three consecutive months. February's closing was misread and a person
    corrected it, so what posted differs from what the reply still says."""
    evs = [account_opened("chk", "depository", "Everyday Checking", "USD",
                          "2026-01-01"),
           opening_balance_observed("chk", "1000.00", "2026-01-01", _p("d-1"))]
    evs += _statement_doc("d-1", "chk", "1000.00", "2026-01-01",
                          "900.00", "2026-01-31")
    evs += _statement_doc("d-2", "chk", "900.00", "2026-02-01",
                          "850.00", "2026-02-28", posted="800.00")
    evs += _statement_doc("d-3", "chk", "800.00", "2026-03-01",
                          "700.00", "2026-03-31")
    return LedgerProjection(evs)


def test_a_corrected_closing_does_not_invent_a_missing_statement():
    """The reply says what the model read; the ledger says what was accepted.
    Reading the reply's figure would break the join to the next month and
    announce a missing statement between two months that abut."""
    assert _corrected_projection().attested_runs("chk") == [
        ("2026-01-01", "2026-03-31")]


def test_the_register_is_the_same_live_as_replayed():
    """A projection built event by event and one replayed from the same log
    must describe the same vault. Dropping the cache on chosen events is what
    let the two disagree for the life of a process."""
    evs = [account_opened("chk", "depository", "Everyday Checking", "USD",
                          "2026-01-01"),
           opening_balance_observed("chk", "1000.00", "2026-01-01", _p("d-1"))]
    evs += _statement_doc("d-1", "chk", "1000.00", "2026-01-01",
                          "900.00", "2026-01-31")
    live = LedgerProjection(evs)
    assert live.attested_runs("chk")            # build the register, then move on
    # February's reply arrives while the register is cold, and only the posting
    # follows. A policy that watches for a new reading would miss this, which is
    # the shape a corrected or healed statement actually takes.
    early = _statement_doc("d-2", "chk", "900.00", "2026-02-01",
                           "800.00", "2026-02-28")
    read, posting = early[:2], early[2:]
    for event in read:
        live.apply(event)
    live.attested_runs("chk")                   # warm the register again
    for event in posting:
        live.apply(event)
    assert live.attested_runs("chk") == LedgerProjection(
        evs + early).attested_runs("chk") == [("2026-01-01", "2026-02-28")]


def test_an_as_of_read_never_attests_past_its_own_horizon():
    """A read as of a past date holds only the movements up to it. Attesting a
    period that runs past it would claim completeness for days it is
    deliberately not showing."""
    evs = [account_opened("chk", "depository", "Everyday Checking", "USD",
                          "2026-01-01"),
           opening_balance_observed("chk", "1000.00", "2026-01-01", _p("d-q"))]
    # read on 10 February, declaring a period that runs to the end of March —
    # so the reading is inside the horizon and the period it claims is not
    evs += _statement_doc("d-q", "chk", "1000.00", "2026-01-01",
                          "800.00", "2026-03-31", read_at="2026-02-10")
    assert LedgerProjection(evs).attested_runs("chk") == [("2026-01-01",
                                                          "2026-03-31")]
    assert LedgerProjection(evs, as_of="2026-02-15").attested_runs("chk") == []


def test_statements_are_ordered_by_period_not_by_document_id():
    """Document ids arrive in no meaningful order. Without an explicit sort the
    runs fragment and the answer announces missing statements that are held."""
    evs = [account_opened("chk", "depository", "Everyday Checking", "USD",
                          "2026-01-01"),
           opening_balance_observed("chk", "1000.00", "2026-01-01", _p("zzz"))]
    evs += _statement_doc("zzz", "chk", "1000.00", "2026-01-01",
                          "900.00", "2026-01-31")
    evs += _statement_doc("aaa", "chk", "900.00", "2026-02-01",
                          "800.00", "2026-02-28")
    evs += _statement_doc("mmm", "chk", "800.00", "2026-03-01",
                          "700.00", "2026-03-31")
    assert LedgerProjection(evs).attested_runs("chk") == [("2026-01-01",
                                                          "2026-03-31")]


def test_a_document_that_is_not_a_statement_attests_nothing_even_if_it_parses():
    """The register asks what kind of document declared a period, not whether
    something statement-shaped can be read out of it. A holdings document whose
    reply happens to parse must still attest nothing, because a snapshot says
    nothing about the days around it."""
    evs = [account_opened("brk", "investment", "Brokerage", "USD", "2026-01-01"),
           document_captured("d-x", "x.pdf", 2, "brokerage_statement", 0.9,
                             "2026-01-31"),
           read_recorded("d-x", "model", "extract-v1", "text",
                         _statement_reply("1000.00", "2026-01-01",
                                          "1600.00", "2026-01-31"),
                         0.0, 1, 1, True, None, "2026-01-31"),
           closing_balance_observed("brk", "1600.00", "2026-01-31", _p("d-x", 3))]
    assert LedgerProjection(evs).attested_runs("brk") == []


def test_statements_whose_balances_do_not_continue_are_two_periods():
    """Dates that meet are not enough. A February opening at a figure January
    did not close at means something between them is unaccounted for, and the
    two months are not one attested stretch."""
    evs = [account_opened("chk", "depository", "Everyday Checking", "USD",
                          "2026-01-01"),
           opening_balance_observed("chk", "1000.00", "2026-01-01", _p("d-1"))]
    evs += _statement_doc("d-1", "chk", "1000.00", "2026-01-01",
                          "900.00", "2026-01-31")
    evs += _statement_doc("d-2", "chk", "850.00", "2026-02-01",
                          "800.00", "2026-02-28")
    assert LedgerProjection(evs).attested_runs("chk") == [
        ("2026-01-01", "2026-01-31"), ("2026-02-01", "2026-02-28")]


def test_a_defect_among_the_transactions_does_not_remove_the_period():
    """The register reads the two boxes that bound a statement. A statement is
    in the ledger because it reconciled, so announcing it missing on account of
    an unreadable transaction would deny a month the vault fully holds."""
    import json
    broken = json.dumps({
        "opening": {"amount_raw": "900.00", "date_raw": "2026-02-01"},
        "closing": {"amount_raw": "800.00", "date_raw": "2026-02-28"},
        "transactions": [{"date_raw": "not a date", "amount_raw": "??",
                          "description": "unreadable"}]})
    evs = [account_opened("chk", "depository", "Everyday Checking", "USD",
                          "2026-01-01"),
           opening_balance_observed("chk", "1000.00", "2026-01-01", _p("d-1"))]
    evs += _statement_doc("d-1", "chk", "1000.00", "2026-01-01",
                          "900.00", "2026-01-31")
    evs += [document_captured("d-2", "d-2.pdf", 2, "bank_statement", 0.9,
                              "2026-02-28"),
            read_recorded("d-2", "model", "extract-v1", "text", broken,
                          0.0, 1, 1, True, None, "2026-02-28"),
            closing_balance_observed("chk", "800.00", "2026-02-28", _p("d-2", 6))]
    evs += _statement_doc("d-3", "chk", "800.00", "2026-03-01",
                          "700.00", "2026-03-31")
    assert LedgerProjection(evs).attested_runs("chk") == [("2026-01-01",
                                                          "2026-03-31")]
