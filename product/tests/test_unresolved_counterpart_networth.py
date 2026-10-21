"""Counterpart treatment identifies activity, not an additional holding."""
from decimal import Decimal

import pytest

from viva.ledger import LedgerProjection
from viva.ledger.events import (Posting, account_opened, closing_balance_observed,
                               ruling_recorded, transaction_recorded)
from viva.ledger.networth import net_worth
from viva.ledger.postings import MAJOR_UNCATEGORIZED


DATE = "2026-01-31"
GENERIC = MAJOR_UNCATEGORIZED["asset"]


def treated(*, actor="human", counterpart=GENERIC, kind="depository", amount="-150", legs=None):
    events = [account_opened("source", kind, "Source", "USD", "2026-01-01"),
              account_opened("destination", "investment", "Destination", "USD", "2026-01-01"),
              closing_balance_observed("source", "100", DATE),
              closing_balance_observed("destination", "200", DATE),
              transaction_recorded([Posting("source", Decimal(amount), "verified"),
                                    Posting("Transfers:Uncategorized", -Decimal(amount))],
                                   "Fabricated movement", "2026-01-10")]
    movement = LedgerProjection(events).movements()[0]
    events.append(ruling_recorded("movement", movement.key, "2026-01-11",
                                 legs=legs or [{"major": "asset", "account": counterpart, "share": ""}],
                                 by=actor, grade="verified" if actor == "human" else "unverified"))
    return events


@pytest.mark.parametrize("actor", ["model", "merchant_prior", "human"])
def test_generic_treatment_never_adds_a_holding(actor):
    point = net_worth(LedgerProjection(treated(actor=actor)), DATE)
    assert point.by_currency()["USD"]["net"] == Decimal("300")
    assert point.by_currency()["USD"]["provable"] == Decimal("300")
    assert not point.complete
    assert point.missing[0]["account"] == GENERIC
    assert "held" in point.missing[0]["why"]
    assert point.missing[0]["ask"] == ""


@pytest.mark.parametrize("kind,amount,net", [("depository", "-150", "300"),
                                              ("depository", "150", "300"),
                                              ("liability", "-150", "100"),
                                              ("liability", "150", "100")])
def test_source_roles_and_directions_do_not_establish_generic_holdings(kind, amount, net):
    point = net_worth(LedgerProjection(treated(kind=kind, amount=amount)), DATE)
    assert point.by_currency()["USD"]["net"] == Decimal(net)
    assert ("debt account" if kind == "liability" else "bank account") in point.missing[0]["why"]


def test_allocated_generic_component_still_has_no_holding_identity():
    legs = [{"major": "asset", "account": GENERIC, "share": "0.5"},
            {"major": "asset", "account": "Assets:Equipment:Cycle", "share": "0.5"}]
    point = net_worth(LedgerProjection(treated(legs=legs)), DATE)
    assert point.by_currency()["USD"]["net"] == Decimal("375")
    assert not point.complete
    assert next(line for line in point.lines if line.kind == "asserted").amount == Decimal("75")


@pytest.mark.parametrize("name", ["Assets:Equipment:Cycle", "Assets:Loans:Borrower", "Assets:Equipment:Uncategorized"])
def test_named_cost_and_refund_or_principal_and_repayment_survive(name):
    events = treated(counterpart=name)
    refund = transaction_recorded([Posting("source", "40", "verified"),
                                   Posting("Transfers:Uncategorized", "-40")],
                                  "Fabricated return", "2026-01-20")
    events.append(refund)
    movement = next(m for m in LedgerProjection(events).movements() if m.date == "2026-01-20")
    events.append(ruling_recorded("movement", movement.key, "2026-01-21",
                                 legs=[{"major": "asset", "account": name, "share": ""}]))
    point = net_worth(LedgerProjection(events), DATE)
    assert point.by_currency()["USD"]["net"] == Decimal("410")
    assert point.complete
    assert next(line for line in point.lines if line.account == name).amount == Decimal("110")


def test_alias_requires_holding_authority_not_just_text():
    from viva.ledger.events import account_alias_confirmed
    events = treated()
    name = "Assets:Equipment:Cycle"
    alias = account_alias_confirmed(GENERIC, name, "synthetic", "2026-01-12")
    unknown = net_worth(LedgerProjection(events + [alias]), DATE)
    assert unknown.by_currency()["USD"]["net"] == Decimal("300")
    assert not unknown.complete
    opened = account_opened(name, "asset", "Cycle", "USD", "2026-01-01", origin="asserted")
    known = net_worth(LedgerProjection(events + [opened, alias]), DATE)
    assert known.by_currency()["USD"]["net"] == Decimal("450")
    assert known.complete
    held_cash = account_opened(name, "depository", "Reserve", "USD", "2026-01-01", origin="asserted")
    balance = closing_balance_observed(name, "25", DATE, confirmed_by="human")
    measured_assertion = net_worth(LedgerProjection(events + [held_cash, balance, alias]), DATE)
    assert measured_assertion.by_currency()["USD"]["net"] == Decimal("325")
    assert measured_assertion.complete
    assert len([line for line in measured_assertion.lines if line.account == name]) == 1
    measured = account_alias_confirmed(GENERIC, "destination", "synthetic", "2026-01-12")
    point = net_worth(LedgerProjection(events + [measured]), DATE)
    assert point.by_currency()["USD"]["net"] == Decimal("300")
    assert point.complete


def test_live_link_closes_gap_and_unlink_reopens_it():
    from viva.ledger.events import transfer_linked, transfer_unlinked
    events = treated()
    events.append(transaction_recorded([Posting("destination", "150", "verified"),
                                       Posting("Transfers:Uncategorized", "-150")],
                                      "Fabricated destination", "2026-01-10"))
    movements = LedgerProjection(events).movements()
    a, b = [m.key for m in movements]
    events.append(transfer_linked(a, b, "verified", {}, "2026-01-12"))
    linked = net_worth(LedgerProjection(events), DATE)
    assert linked.by_currency()["USD"]["net"] == Decimal("300")
    assert linked.complete
    events.append(transfer_unlinked(a, b, "2026-01-13"))
    unlinked = net_worth(LedgerProjection(events), DATE)
    assert unlinked.by_currency()["USD"]["net"] == Decimal("300")
    assert not unlinked.complete


def test_sql_canonical_accounting_and_net_only_disclose_same_coverage(tmp_path):
    from viva.ledger import EventStore
    from viva.ledger.accounting import financial_statements
    from viva.read_store import ReadStore
    from viva.tools.ledger_aggregates import _aggregate_net_worth
    from viva.tools.boundary import account_written
    events = treated()
    canonical = LedgerProjection(events)
    source = EventStore.open(tmp_path / "events.jsonl", "synthetic-passphrase")
    source.append_atomically(lambda _existing: tuple(events))
    with ReadStore.create(tmp_path / "reads", "synthetic-passphrase") as reads:
        reads.synchronize(source)
        with reads.open_reader() as revision:
            sql = revision.overview_projection(today=DATE)
            assert net_worth(sql, DATE).to_dict() == net_worth(canonical, DATE).to_dict()
            actual = _aggregate_net_worth(sql, DATE, view="net_by_currency")
            expected = _aggregate_net_worth(canonical, DATE, view="net_by_currency")
            assert actual.to_dict() == expected.to_dict()
    assert expected.figures[0]["value"] == "300"
    assert expected.figures[0]["boundary"]["unmeasured"][0]["account"] == GENERIC
    assert expected.caveats and "already included" in expected.caveats[0]
    key = canonical.movements()[0].key
    assert key in expected.record_ids
    assert key not in expected.figures[0]["record_ids"]
    assert key not in expected.caveats[0]
    assert "unresolved transfer activity" in str(account_written(GENERIC, {}))
    balance_sheet = financial_statements(canonical, as_of=DATE)["balance_sheet"]
    assert balance_sheet["by_currency"]["USD"]["net"] == "300"
    assert not balance_sheet["complete"] and balance_sheet["missing"]


def test_explicit_held_cash_measurement_survives():
    events = treated() + [
        account_opened("Assets:Cash:Reserve", "depository", "Reserve", "USD", "2026-01-01", origin="asserted"),
        closing_balance_observed("Assets:Cash:Reserve", "25", DATE, confirmed_by="human")]
    point = net_worth(LedgerProjection(events), DATE)
    assert point.by_currency()["USD"]["net"] == Decimal("325")
    assert not point.complete
    assert next(line for line in point.lines if line.account == "Assets:Cash:Reserve").amount == Decimal("25")


def test_currency_and_historical_cutoff_preserve_source_boundary():
    events = treated() + [account_opened("other", "investment", "Other", "EUR", "2026-01-01"),
                          closing_balance_observed("other", "70", DATE)]
    point = net_worth(LedgerProjection(events), DATE)
    assert point.by_currency()["USD"]["net"] == Decimal("300")
    assert point.by_currency()["EUR"]["net"] == Decimal("70")
    assert "USD" in point.missing[0]["why"]
    before = net_worth(LedgerProjection(events), "2026-01-09")
    assert not before.missing and not before.lines


def test_correction_rebuild_and_restoration_reopen_same_gap():
    from viva.ledger.events import accounting_treatment_restored
    events = treated()
    projection = LedgerProjection(events)
    movement = projection.movements()[0]
    previous = projection.rulings("movement")[0]
    events.append(ruling_recorded("movement", movement.key, "2026-01-12",
                                 legs=[{"major": "asset", "account": "Assets:Equipment:Cycle", "share": ""}]))
    assert net_worth(LedgerProjection(events), DATE).by_currency()["USD"]["net"] == Decimal("450")
    events.append(accounting_treatment_restored(movement.key, previous, {}, "2026-01-13"))
    restored = net_worth(LedgerProjection(events), DATE)
    assert restored.to_dict() == net_worth(projection, DATE).to_dict()


@pytest.mark.parametrize("key", ["ledger_networth", "ledger_accounting", "financial_read_overview", "financial_surface_overview"])
def test_changed_financial_sources_change_admission_authority(monkeypatch, key):
    import inspect
    from pathlib import Path
    from viva.answer_program.intents import SemanticFamilyRegistry
    from viva.ledger import networth, accounting
    from viva.read_store import overview
    from viva.surface import overview as surface_overview
    modules = {"ledger_networth": networth, "ledger_accounting": accounting,
               "financial_read_overview": overview, "financial_surface_overview": surface_overview}
    before = SemanticFamilyRegistry._admitted_implementation_digests()
    read = Path.read_bytes
    target = inspect.getsourcefile(modules[key])
    monkeypatch.setattr(Path, "read_bytes", lambda path: read(path) + b"\n" if str(path) == target else read(path))
    after = SemanticFamilyRegistry._admitted_implementation_digests()
    assert after[key] != before[key]
    assert all(after[name] == digest for name, digest in before.items() if name != key)


@pytest.mark.parametrize("case", ["automatic", "allocated", "alias_text", "alias_measured", "liability_source"])
def test_sql_rebuild_preserves_eligibility_controls(tmp_path, case):
    from viva.ledger import EventStore
    from viva.ledger.events import account_alias_confirmed
    from viva.read_store import ReadStore
    if case == "automatic":
        events = treated(actor="model")
    elif case == "allocated":
        events = treated(legs=[{"major": "asset", "account": GENERIC, "share": "0.5"},
                               {"major": "asset", "account": "Assets:Equipment:Cycle", "share": "0.5"}])
    elif case == "liability_source":
        events = treated(kind="liability")
    else:
        events = treated()
        target = "Assets:Cash:Reserve"
        if case == "alias_measured":
            events += [account_opened(target, "depository", "Reserve", "USD", "2026-01-01", origin="asserted"),
                       closing_balance_observed(target, "25", DATE, confirmed_by="human")]
        events.append(account_alias_confirmed(GENERIC, target, "synthetic", "2026-01-12"))
    expected = net_worth(LedgerProjection(events), DATE)
    source = EventStore.open(tmp_path / "events.jsonl", "synthetic-passphrase")
    source.append_atomically(lambda _existing: tuple(events))
    with ReadStore.create(tmp_path / "reads", "synthetic-passphrase") as reads:
        reads.synchronize(source)
        with reads.open_reader() as revision:
            actual = net_worth(revision.overview_projection(today=DATE), DATE)
            assert actual.to_dict() == expected.to_dict()
            assert actual._unresolved_source_ids == expected._unresolved_source_ids
    net = {"allocated": "375", "liability_source": "100", "alias_measured": "325"}.get(case, "300")
    assert expected.by_currency()["USD"]["net"] == Decimal(net)
    assert expected.complete is (case == "alias_measured")


def test_unallocated_components_do_not_invent_named_cost_or_clear_generic_gap():
    point = net_worth(LedgerProjection(treated(legs=[
        {"major": "asset", "account": GENERIC, "share": ""},
        {"major": "asset", "account": "Assets:Equipment:Cycle", "share": ""}])), DATE)
    assert point.by_currency()["USD"]["net"] == Decimal("300")
    assert not point.complete
    assert {row["account"] for row in point.missing} == {GENERIC, "Assets:Equipment:Cycle"}
    assert not any(line.kind == "asserted" for line in point.lines)


def test_zero_allocated_generic_component_opens_no_unknown_holding():
    point = net_worth(LedgerProjection(treated(legs=[
        {"major": "asset", "account": GENERIC, "share": "0"},
        {"major": "asset", "account": "Assets:Equipment:Cycle", "share": "1"}])), DATE)
    assert point.by_currency()["USD"]["net"] == Decimal("450")
    assert point.complete


def test_generic_alias_measurement_in_another_currency_cannot_close_source_coverage():
    from viva.ledger.events import account_alias_confirmed
    events = treated() + [account_opened("foreign", "investment", "Foreign", "EUR", "2026-01-01"),
                          closing_balance_observed("foreign", "70", DATE),
                          account_alias_confirmed(GENERIC, "foreign", "synthetic", "2026-01-12")]
    point = net_worth(LedgerProjection(events), DATE)
    assert point.by_currency()["USD"]["net"] == Decimal("300")
    assert point.by_currency()["EUR"]["net"] == Decimal("70")
    assert not point.complete
    assert "USD" in point.missing[0]["why"]


@pytest.mark.parametrize("measured_generic", [False, True])
def test_overview_account_count_keeps_unknown_transfer_coverage_separate(tmp_path, measured_generic):
    from viva.ledger import EventStore
    from viva.persona import moment
    from viva.read_store import ReadStore
    from viva.surface.overview import overview
    events = treated()
    if measured_generic:
        events += [account_opened(GENERIC, "depository", "Reserve", "USD", "2026-01-01"),
                   closing_balance_observed(GENERIC, "25", DATE)]
    canonical = overview(LedgerProjection(events), "en-US", DATE)
    expected = moment("picture_accounts_all" if measured_generic else "picture_accounts_all_incomplete")
    assert canonical["picture"]["coverage"] == expected
    assert canonical["account_count"] == (3 if measured_generic else 2)
    if not measured_generic:
        assert canonical["picture"]["unplaced"]
        assert canonical["caveats"]
    source = EventStore.open(tmp_path / "events.jsonl", "synthetic-passphrase")
    source.append_atomically(lambda _existing: tuple(events))
    with ReadStore.create(tmp_path / "reads", "synthetic-passphrase") as reads:
        reads.synchronize(source)
        with reads.open_reader() as revision:
            actual = overview(revision.overview_projection(today=DATE), "en-US", DATE)
            assert actual == canonical


def test_transfer_component_disclosure_does_not_reclassify_the_whole_payment():
    events = treated(legs=[{"major": "asset", "account": GENERIC, "share": "0.5"},
                           {"major": "expense", "account": "Expenses:Equipment", "share": "0.5"}])
    point = net_worth(LedgerProjection(events), DATE)
    assert "includes a transfer component" in point.missing[0]["why"]
    assert "was treated as a transfer" not in point.missing[0]["why"]
    assert "bank account" in point.missing[0]["why"]
    assert "USD" in point.missing[0]["why"]
    assert point.by_currency()["USD"]["net"] == Decimal("300")


def test_independently_recorded_unmeasured_generic_account_keeps_inventory_place():
    from viva.persona import moment
    from viva import render
    from viva.surface.overview import overview
    events = treated() + [account_opened(GENERIC, "depository", "Reserve", "USD", "2026-01-01")]
    view = overview(LedgerProjection(events), "en-US", DATE)
    assert view["picture"]["coverage"] == moment("picture_accounts_some", counted=render.count(2), held=render.count(3))
    assert view["account_count"] == 3
    assert view["picture"]["unplaced"] or any(f["unmeasured"] for f in view["picture"]["figures"])


@pytest.mark.parametrize("actor", ["human", "model", "merchant_prior"])
@pytest.mark.parametrize("balance", ["25", "0", "-5"])
def test_direct_named_measured_cash_contributes_only_its_balance(actor, balance):
    name = "Assets:Cash:Reserve"
    events = treated(actor=actor, counterpart=name) + [
        account_opened(name, "depository", "Reserve", "USD", "2026-01-01", origin="asserted"),
        closing_balance_observed(name, balance, DATE, confirmed_by="human")]
    projection = LedgerProjection(events)
    (measured,) = projection.composed_values(name, DATE)
    point = net_worth(projection, DATE)
    assert point.by_currency()["USD"]["net"] == Decimal("300") + Decimal(balance)
    (line,) = [line for line in point.lines if line.account == name]
    assert line.kind == "depository" and line.amount == Decimal(balance)
    assert line.as_of == measured.as_of == DATE
    assert line.grade == measured.grade == "verified"
    assert line.proves == measured.proves
    assert line.origin == "asserted" and line.currency == measured.currency
    assert point.complete


def test_direct_named_cash_uses_only_same_currency_measurements_available_at_query():
    name = "Assets:Cash:Reserve"
    events = treated(counterpart=name) + [
        account_opened(name, "depository", "Reserve", "USD", "2026-01-01", origin="asserted"),
        closing_balance_observed(name, "25", "2026-02-01", confirmed_by="human")]
    projection = LedgerProjection(events)
    earlier = net_worth(projection, DATE)
    assert next(line for line in earlier.lines if line.account == name).amount == Decimal("150")
    later = net_worth(projection, "2026-02-01")
    assert [line.amount for line in later.lines if line.account == name] == [Decimal("25")]
    assert net_worth(projection, DATE).to_dict() == earlier.to_dict()
    foreign = treated(counterpart=name) + [
        account_opened(name, "depository", "Reserve", "EUR", "2026-01-01", origin="asserted"),
        closing_balance_observed(name, "25", DATE, confirmed_by="human")]
    point = net_worth(LedgerProjection(foreign), DATE)
    assert point.by_currency()["USD"]["net"] == Decimal("450")
    assert point.by_currency()["EUR"]["net"] == Decimal("25")


def test_direct_named_cash_keeps_last_measured_balance_without_extrapolating_flow():
    name = "Assets:Cash:Reserve"
    events = treated(counterpart=name) + [
        account_opened(name, "depository", "Reserve", "USD", "2026-01-01", origin="asserted"),
        closing_balance_observed(name, "25", "2026-01-05", confirmed_by="human")]
    point = net_worth(LedgerProjection(events), DATE)
    (line,) = [line for line in point.lines if line.account == name]
    assert line.amount == Decimal("25") and line.as_of == "2026-01-05"
    assert point.by_currency()["USD"]["net"] == Decimal("325")


def test_direct_named_measured_cash_canonical_and_sql_reads_agree(tmp_path):
    from viva.ledger import EventStore
    from viva.ledger.accounting import financial_statements
    from viva.read_store import ReadStore
    from viva.surface.overview import overview
    from viva.tools.ledger_aggregates import _aggregate_net_worth
    name = "Assets:Cash:Reserve"
    events = treated(counterpart=name) + [
        account_opened(name, "depository", "Reserve", "USD", "2026-01-01", origin="asserted"),
        closing_balance_observed(name, "25", DATE, confirmed_by="human")]
    canonical = LedgerProjection(events)
    expected = net_worth(canonical, DATE)
    assert expected.by_currency()["USD"]["net"] == Decimal("325")
    assert len([line for line in expected.lines if line.account == name]) == 1
    assert financial_statements(canonical, as_of=DATE)["balance_sheet"]["by_currency"]["USD"]["net"] == "325"
    source = EventStore.open(tmp_path / "events.jsonl", "synthetic-passphrase")
    source.append_atomically(lambda _existing: tuple(events))
    with ReadStore.create(tmp_path / "reads", "synthetic-passphrase") as reads:
        reads.synchronize(source)
        with reads.open_reader() as revision:
            sql = revision.overview_projection(today=DATE)
            assert net_worth(sql, DATE).to_dict() == expected.to_dict()
            assert overview(sql, "en-US", DATE) == overview(canonical, "en-US", DATE)
            actual = _aggregate_net_worth(sql, DATE, view="net_by_currency")
            assert actual.to_dict() == _aggregate_net_worth(canonical, DATE, view="net_by_currency").to_dict()
            assert actual.figures[0]["value"] == "325"
