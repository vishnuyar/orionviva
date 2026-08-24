"""Tool contract contracts."""

from _tool_test_support import *

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
    # A card measures what is owed, and it is written and declared as that.
    assert figures["Signature Card — owed"]["grade"] == UNVERIFIED


def test_an_unmeasured_asserted_liability_is_not_reported_as_zero(proj):
    from viva.ledger import LedgerProjection, account_opened
    from viva.ledger.events import ASSERTED

    asserted = account_opened(
        "Liabilities:Mortgage:Home", "liability", "Home Mortgage", "USD",
        "2026-02-01", origin=ASSERTED)
    projection = LedgerProjection([*_events(), asserted])

    result = ledger_tools.query_ledger(projection, {"entity": "balances"})

    assert result.ok
    assert not any(f["what"] == "Home Mortgage — owed"
                   for f in result.figures)
    assert any("not reported as zero" in caveat for caveat in result.caveats)
    assert any(item.get("account") == "Liabilities:Mortgage:Home"
               for item in result.identifiers)
    assert result.grade == UNVERIFIED
    assert "doc-jan" in result.record_ids
    rows = {r["record_id"]: r for r in result.data["balances"]}
    assert "amount" not in rows["chk"] and "grade" not in rows["chk"]
    assert rows["chk"]["evidence_limitation"]


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


def test_transactions_filter_by_window_and_tag(proj, registry):
    tagged = registry.call("query_ledger", {"entity": "transactions",
                                            "filters": {"tag": "pantry"}})
    assert tagged.data["count"] == 1
    assert "transactions" not in tagged.data       # a summary returns no rows
    rows = registry.call("list_movements", {"filters": {"tag": "pantry"}})
    # The row carries which way the money went, never the raw posting sign: a
    # model reading rows can no longer call a card purchase money received.
    row = rows.data["movements"][0]
    assert "amount" not in row
    assert row["effect"] == "-60.00"
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


def test_income_honours_a_window_instead_of_returning_lifetime(registry):
    """A dated question gets a dated zero, not a lifetime figure."""
    result = registry.call("query_ledger",
                           {"entity": "aggregate", "metric": "income",
                            "filters": {"window": {"from": "2027-01-01"}}})
    assert result.ok
    assert result.data["window"] == {"from": "2027-01-01"}
    assert result.data["by_currency"] == {"USD": "0"}
    assert any("2027-01-01" in fig["what"] for fig in result.figures)


def test_income_names_its_sources_and_says_it_is_lifetime(proj, registry):
    result = registry.call("query_ledger", {"entity": "aggregate",
                                            "metric": "income"})
    assert result.ok
    expected = {k: str(v) for k, v in proj.income_by_currency().items()}
    assert result.data["by_currency"] == expected
    assert any("lifetime" in c for c in result.caveats)


def test_latest_complete_calendar_month_resolves_to_explicit_dates(registry):
    args = {"filters": {"window": {
        "preset": "latest_complete_calendar_month"}}}

    summary = registry.call(
        "query_ledger", {"entity": "aggregate", "metric": "spending",
                         **args})
    rows = registry.call("list_movements", args)

    expected = {"from": "2026-01-01", "to": "2026-01-31"}
    assert summary.ok and summary.data["total"] == "100.00"
    assert summary.covers
    assert rows.ok and rows.data["window"] == expected
    assert rows.data["total"] == 4


def test_windowed_income_separates_sources_from_unexplained_inflows():
    projection = LedgerProjection([
        *_events(),
        transaction_recorded([
            Posting("chk", "1000.00", VERIFIED),
            Posting("Income:Salary", "-1000.00", VERIFIED),
        ], "PAYROLL", "2026-01-10", provenance=_p("doc-jan")),
        transaction_recorded([
            Posting("chk", "40.00", CORROBORATED),
            Posting("Income:Uncategorized", "-40.00", UNVERIFIED),
        ], "UNEXPLAINED CREDIT", "2026-01-18", provenance=_p("doc-jan")),
        transaction_recorded([
            Posting("chk", "900.00", VERIFIED),
            Posting("Income:Salary", "-900.00", VERIFIED),
        ], "PAYROLL", "2026-02-10", provenance=_p("doc-feb")),
    ])
    result = default_registry(projection, today="2026-03-01").call(
        "query_ledger", {"entity": "aggregate", "metric": "income",
                         "filters": {"window": {
                             "preset": "latest_complete_calendar_month"}}})

    assert result.ok
    assert result.data["window"] == {
        "from": "2026-01-01", "to": "2026-01-31"}
    assert result.data["by_source"] == {"Income:Salary": "1000.00"}
    assert result.data["by_currency"] == {"USD": "1000.00"}
    assert result.data["unexplained_inflows"] == "40.00"
    assert any(fig["quantity"] == quantity.GROSS_FLOW
               and fig["value"] == "40.00" for fig in result.figures)


def test_income_and_surplus_never_add_or_relabel_different_currencies():
    """Currency filters select transaction lines before income is summed."""
    projection = LedgerProjection([
        account_opened("usd", "depository", "USD account", "USD",
                       "2026-01-01"),
        account_opened("eur", "depository", "EUR account", "EUR",
                       "2026-01-01"),
        transaction_recorded([
            Posting("usd", "100.00", VERIFIED),
            Posting("Income:Salary", "-100.00", VERIFIED),
        ], "USD PAY", "2026-01-10", provenance=_p("doc-usd")),
        transaction_recorded([
            Posting("eur", "200.00", VERIFIED),
            Posting("Income:Salary", "-200.00", VERIFIED),
        ], "EUR PAY", "2026-01-10", provenance=_p("doc-eur")),
    ])
    registry = default_registry(projection, today="2026-02-01")

    all_income = registry.call(
        "query_ledger", {"entity": "aggregate", "metric": "income"})
    usd_income = registry.call(
        "query_ledger", {"entity": "aggregate", "metric": "income",
                         "filters": {"currency": "USD"}})
    eur_income = registry.call(
        "query_ledger", {"entity": "aggregate", "metric": "income",
                         "filters": {"currency": "EUR"}})

    assert all_income.data["by_currency"] == {"EUR": "200.00",
                                               "USD": "100.00"}
    assert usd_income.data["by_currency"] == {"USD": "100.00"}
    assert eur_income.data["by_currency"] == {"EUR": "200.00"}
    assert all(f["currency"] in ("", "USD") for f in usd_income.figures)

    usd_surplus = registry.call(
        "query_ledger", {"entity": "aggregate", "metric": "surplus",
                         "filters": {"currency": "USD"}})
    assert usd_surplus.ok
    assert usd_surplus.data["attributed_income"] == "100.00"
    assert usd_surplus.data["surplus"] == "100.00"

    unexplained = LedgerProjection([
        account_opened("usd", "depository", "USD account", "USD",
                       "2026-01-01"),
        account_opened("eur", "depository", "EUR account", "EUR",
                       "2026-01-01"),
        transaction_recorded([
            Posting("usd", "10.00", VERIFIED),
            Posting("Income:Uncategorized", "-10.00", UNVERIFIED),
        ], "USD CREDIT", "2026-01-10", provenance=_p("doc-usd")),
        transaction_recorded([
            Posting("eur", "20.00", VERIFIED),
            Posting("Income:Uncategorized", "-20.00", UNVERIFIED),
        ], "EUR CREDIT", "2026-01-10", provenance=_p("doc-eur")),
    ])
    mixed_surplus = default_registry(unexplained).call(
        "query_ledger", {"entity": "aggregate", "metric": "surplus"})
    assert not mixed_surplus.ok
    assert mixed_surplus.refusal == "mixed_currencies"
    assert set(mixed_surplus.data["currencies"]) == {"USD", "EUR"}


def test_weakest_evidence_ranks_accounts_and_transactions_together(registry):
    result = registry.call(
        "query_ledger", {"entity": "aggregate",
                         "metric": "weakest_evidence"})

    assert result.ok
    records = result.data["records"]
    assert {row["record_type"] for row in records} == {
        "account", "movement"}
    assert records == sorted(records, key=lambda row: row["rank"])
    assert records[0]["grade"] == UNVERIFIED
    assert result.data["ordering"] == (
        "weakest grade, then largest absolute magnitude")
    assert all("amount" not in row for row in records)
    assert result.figures


def test_stalest_balance_returns_date_age_amount_and_unbounded_impact(proj):
    result = default_registry(proj, today="2026-03-01").call(
        "query_ledger", {"entity": "aggregate", "metric": "stalest_balance"})

    assert result.ok
    assert result.data["account"] == "brk"
    assert result.data["date"] == "2026-01-31"
    assert result.data["age_days"] == 29
    assert {figure["quantity"] for figure in result.figures} >= {
        quantity.BALANCE, quantity.TIME, quantity.COUNT}
    assert any("no supported upper bound" in caveat
               for caveat in result.caveats)


def test_period_surplus_has_its_own_quantity_and_excludes_unexplained_inflows():
    projection = LedgerProjection([
        *_events(),
        transaction_recorded([
            Posting("chk", "1000.00", VERIFIED),
            Posting("Income:Salary", "-1000.00", VERIFIED),
        ], "PAYROLL", "2026-01-10", provenance=_p("doc-jan")),
        transaction_recorded([
            Posting("chk", "40.00", CORROBORATED),
            Posting("Income:Uncategorized", "-40.00", UNVERIFIED),
        ], "UNEXPLAINED CREDIT", "2026-01-18", provenance=_p("doc-jan")),
    ])
    result = default_registry(projection, today="2026-03-01").call(
        "query_ledger", {"entity": "aggregate", "metric": "surplus",
                         "filters": {"window": {
                             "preset": "latest_complete_calendar_month"}}})

    assert result.ok
    assert result.data["attributed_income"] == "1000.00"
    assert result.data["counted_spending"] == "100.00"
    assert result.data["surplus"] == "900.00"
    assert result.data["unexplained_inflows"] == "40.00"
    assert any(figure["quantity"] == quantity.NET_MOVEMENT
               and figure["value"] == "900.00" for figure in result.figures)


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


def test_the_counts_of_what_the_agent_holds_on_file_are_not_claims_about_money(
        registry):
    """Sorted by what a wrong number here would move. Documents held, posted
    and awaiting review, and counterparties with no category yet, all move the
    account the agent gives of its own paperwork and no figure about what the
    person holds — so each is activity and carries no grade, and nothing can
    lend one through composition.

    The account dates in the same read are the other side of the test: a wrong
    one moves what a balance is good as of, so they stay financial and keep
    their grades."""
    result = registry.call("check_completeness", {})
    counted = [f for f in result.figures if f["quantity"] == quantity.COUNT]
    assert len(counted) == 4
    for fig in counted:
        assert fig["kind"] == "activity", fig["what"]
        assert fig["grade"] == "", fig["what"]
    dated = [f for f in result.figures if f["quantity"] == quantity.TIME]
    assert dated and all(f["kind"] == "financial" and f["grade"] for f in dated)


def test_a_count_of_the_agents_paperwork_cannot_be_mixed_into_a_money_figure(
        registry):
    """What the kind buys. Arithmetic refuses to combine a claim about the
    agent with a claim about the person's money, because the result would be a
    claim of neither kind — so a document count can no longer be divided into a
    spending total."""
    result = run(
        "how much per document?",
        _script(_shape(("That is {each} each.",
                       [("each", "money", "balance", "whole")])),
                ("check_completeness", {}),
                ("query_ledger", {"entity": "balances"}),
                ("compute", {"expression": "held / docs",
                             "inputs": {"held": "f6", "docs": "f1"}}),
                bind=lambda results: {"each": {"figure": "f99"}}),
        registry)
    assert not result.answered
    mixed = next(r for r in result.transcript if r["tool"] == "compute")
    assert not mixed["ok"] and mixed["refusal"] == "mixed_kinds"


def test_an_empty_vault_can_say_it_holds_nothing():
    """A count of nothing is a true thing to say. As the agent's account of its
    own paperwork it stands on the documents it counted and cites none, which
    is sayable; a financial figure of zero citing no record would be a claim
    about money standing on nothing, and the whole answer would be refused."""
    empty = default_registry(LedgerProjection([]))
    result = run("what have you got?",
                 _script(_shape(("I am holding {many} document(s).",
                                 [("many", "count", "count", "whole")])),
                         ("check_completeness", {}),
                         bind=lambda r: {"many": {"figure": "f1"}}),
                 empty)
    assert result.answered, result.detail
    assert result.text.startswith("I am holding 0 document(s).")


def test_the_completeness_read_offers_one_account_of_what_is_unidentified(
        registry):
    """Two reads measure counterparties awaiting attention over different sets,
    both correctly. Only one of them reaches a model from here, so there is no
    pair of irreconcilable numbers in one payload for it to choose between, and
    the figure it can speak is named for the set it actually counts."""
    result = registry.call("check_completeness", {})
    assert "tiers" not in result.data
    named = [f["what"] for f in result.figures]
    assert "counterparties with no category yet" in named


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
        evs.append(opening_balance_observed(f"extra{n}", "0.00",
                                            "2026-01-01", _p("doc-one")))
        evs.append(position_observed("brk", f"SYNTH FUND {n}", "1",
                                     "0.00", "USD", "2026-01-31",
                                     provenance=_p("doc-one")))
        evs.append(document_captured(f"doc-more-{n}", f"more{n}.pdf", 10,
                                     "bank_statement", 0.9, "2026-02-01"))
        evs.append(agent_acted("enrich_unknown", "enrich", f"more-{n}", "done",
                               "2026-02-03", calls=1))
        evs.append(question_declined(f"q-more-{n}", "nature", "2026-02-03",
                                     amount="0.00"))
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


def _every_figure(factor="1", more=0, stable_only=False) -> dict:
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
        # Capped rankings and winner selections can replace labels when records
        # are added, so the monotonic-label set excludes those reads.
        if (stable_only and name == "query_ledger"
                and args.get("metric") in {
                    "weakest_evidence", "stalest_balance"}):
            continue
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
    stable_plain = _every_figure(stable_only=True)
    stable_longer = _every_figure(more=2, stable_only=True)
    # Every stable figure remains reachable when records are added.
    assert set(stable_plain) <= set(stable_longer)
    assert set(plain) == set(scaled)
    for what, fig in plain.items():
        currency = fig["currency"]
        assert isinstance(currency, str), (
            f"{what!r} carries {currency!r} as its currency, which is neither "
            "a code nor nothing at all")
        if currency:
            value = Decimal(fig["value"])  # an amount is a number, or nothing
            if value:
                assert fig["value"] != scaled[what]["value"], (
                    f"{what!r} claims {currency}, but does not follow the "
                    "amounts; it is a count wearing a currency label")
        else:
            assert fig["value"] == scaled[what]["value"], (
                f"{what!r} follows the amounts, so it is money, and it states "
                "no currency")
    for what, fig in stable_plain.items():
        currency = fig["currency"]
        if fig["value"] != stable_longer[what]["value"] and currency:
            # Adding records can also change money. A changed value that calls
            # itself money must independently follow the amount-scaling probe;
            # otherwise it is really a row count wearing a currency label.
            assert fig["value"] != scaled[what]["value"], (
                f"{what!r} follows the number of rows but not their amounts, "
                f"so it counts things and cannot claim {currency}")


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


def test_no_read_states_what_is_owed_as_what_is_held():
    """The rule over every read there is, rather than over the emitters that
    were written with it in mind.

    A liability's magnitude is always what is owed and never what is held.
    Checked here as a property of the figures: over a vault holding accounts of
    both sides, any figure standing at a moment — a balance, a debt, a line of
    a net-worth point — whose records name only accounts someone is owed on
    declares `owed`. A figure naming both sides is a total over them and is not
    what this rule is about, and a movement is a flow rather than something
    standing at a moment."""
    registry, proj = _probe_vault()
    infos = proj.account_infos()
    owed_on = {i.account for i in infos if i.kind == "liability"}
    accounts = {i.account for i in infos}
    assert owed_on and accounts - owed_on, (
        "a vault with only one side cannot tell the two apart")

    movement = next(m.key for m in proj.movements())
    from_the_vault = {
        "list_movements": [{"filters": {"account": a}} for a in sorted(accounts)],
        "get_provenance": [{"record_id": r} for r in
                           sorted(accounts | {"doc-one", movement})],
    }
    calls = []
    for schema in registry.schemas():
        name = schema["name"]
        for args in from_the_vault.get(name,
                                       _enumerated_args(schema["parameters"])):
            calls.append((name, args))

    seen = 0
    for name, args in calls:
        result = registry.call(name, args)
        if not result.ok:
            continue
        for fig in result.figures:
            named = {r for r in fig["record_ids"] if r in accounts}
            if not named or not named <= owed_on:
                continue
            if fig["quantity"] not in quantity.STOCKS:
                continue
            seen += 1
            assert fig["quantity"] == quantity.OWED, (
                f"{name} states {fig['what']!r} as {fig['quantity']!r}, and it "
                "is a magnitude of what is owed")
    assert seen >= 3, (
        "no read here emitted what is owed on an account, so this proves "
        "nothing")


def test_every_quantity_the_vocabulary_holds_can_be_asked_for():
    """The other half of the same completeness. A quantity nothing can ask for
    is a word a tool may declare that no sentence can ever be about, so the
    figure carrying it is unsayable — and it would be unsayable silently."""
    askable = {kind for kinds in render.QUANTITY_OF_TYPE.values()
               for kind in kinds}
    missing = sorted(set(quantity.KINDS) - askable)
    assert not missing, (
        f"{missing} can be measured and no hole can ask about it")
