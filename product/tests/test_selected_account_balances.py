"""Selected reports retain each selected account and the actual valuation sources."""
from viva.answer_program.intents import SemanticFamilyRegistry


def test_selected_account_family_is_explicitly_available():
    family = SemanticFamilyRegistry().get("selected_account_balances")
    assert family is not None
    assert family.runtime_selectable
    assert set(family.parameter_schema["properties"]) == {f"account_phrase_{i}" for i in range(1, 8)}


def test_source_capture_is_an_explicit_opt_in_at_the_existing_valuation():
    import inspect
    from viva.ledger.projection.positions import composed_values
    assert "source_capture" in inspect.signature(composed_values).parameters


import copy
import gc
import inspect
import json
import textwrap
import weakref
import pytest


@pytest.fixture
def live_report(tmp_path):
    from contextlib import contextmanager
    from time import monotonic
    from viva.instrument_evidence import authenticated_assertion
    from viva.instrument_runtime import InstrumentRuntime
    from viva.ledger.instruments import reference_accounts
    from viva.read_store import ReadStore
    from viva.tools.account_balances import read_report
    from test_instrument_projector_b import setup, ingest, bank
    from test_instrument_contracts import deposit_json, printed

    raw, ledger = setup(tmp_path)
    data = deposit_json()
    data["terms"] = {"principal":printed("1000"), "opened":printed("2021-01-01"),
        "maturity":printed("2022-01-01"), "withdrawal_restriction":printed("No withdrawal until maturity")}
    ingest(raw, ledger, "selected-term", data, "term_deposit_statement")
    bank(raw, ledger)
    projection = ledger.projection()
    accounts = [reference_accounts(projection, ref)[0] for ref in ("CD-A", "CHECK-A")]
    with ReadStore.create(tmp_path / "read", "synthetic-passphrase") as store:
        store.synchronize(ledger.store)
        @contextmanager
        def supplier():
            with store.open_reader() as revision:
                yield revision
        supplier.source_identity = ledger.store.authenticated_identity
        supplier.expected_projection_identity = ledger._projection_identity
        runtime = InstrumentRuntime(supplier)
        with runtime.execution(monotonic() + 15):
            result = read_report(projection, runtime, "2021-01-31",
                {f"account_{i}":account for i,account in enumerate(accounts,1)})
            assert result.ok, (result.refusal, result.text, result.data)
            assert result.tool == "read_account_balance_report"
            assert len(result.instrument_assertions) == 1
            assertion = result.instrument_assertions[0]
            assert assertion["claim"] == "availability_restriction"
            assert authenticated_assertion(assertion)
            assert assertion._run_token is runtime.run_token
            from types import SimpleNamespace
            case = SimpleNamespace(result=result, runtime=runtime, accounts=accounts,
                projection=projection, store=store)
            del result, assertion
            yield case


def _graph(token):
    from viva.answer_program.evidence import EvidenceGraph
    graph = EvidenceGraph("Show selected accounts and recorded restrictions")
    graph.ground.instrument_token = token
    return graph


def _reject_without_evidence_mutation(result, token):
    graph = _graph(token)
    before = copy.deepcopy(graph.to_dict())
    result_id = result.id
    figure_ids = [item.get("id") for item in result.figures]
    assertion_ids = [item.get("id") for item in result.instrument_assertions]
    with pytest.raises(ValueError):
        graph.stamp("selected_balances", result)
    assert graph.to_dict() == before
    assert result.id == result_id
    assert [item.get("id") for item in result.figures] == figure_ids
    assert [item.get("id") for item in result.instrument_assertions] == assertion_ids


def test_real_restriction_report_crosses_existing_run_stamping_boundary(live_report):
    result = live_report.result
    original = json.dumps(result.to_dict(), sort_keys=True)
    graph = _graph(live_report.runtime.run_token)
    graph.stamp("selected_balances", result)
    assert len(graph.ground.instrument_assertions) == 1
    assert result.instrument_assertions[0]["id"]
    after = result.to_dict()
    after["id"] = ""
    for assertion in after["instrument_assertions"]:
        assertion["id"] = ""
    for identifier in after["identifiers"]:
        identifier["id"] = ""
    # Identity stamping is the only allowed source-assertion mutation.
    original_data = json.loads(original)
    assert json.loads(json.dumps(after["data"])) == original_data["data"]
    assert json.loads(json.dumps(after["instrument_assertions"])) == original_data["instrument_assertions"]


@pytest.mark.parametrize("change", ["other_tool", "ordinary_tool", "retirement_tool", "claim",
    "crossed_account", "unselected_account", "request_account", "wrong_assertion_token",
    "fake_assertion", "copy_assertion", "json_assertion", "changed_value", "changed_source",
    "copied_result", "constructed_result", "json_result", "source_membership",
    "trace_membership", "row_membership", "value_membership", "allocation_premise",
    "instrument_figure", "genuine_other_claim"])
def test_selected_report_negative_refuses_before_mutating_evidence(live_report, change):
    from viva.tools.envelope import ToolResult
    from viva.tools.instruments import read_instrument_details
    result = live_report.result
    assertion = result.instrument_assertions[0]
    if change == "other_tool":result.tool = "another_producer"
    elif change == "ordinary_tool":result.tool = "read_instrument_details"
    elif change == "retirement_tool":result.tool = "read_retirement_funding"
    elif change == "claim":assertion["claim"] = "deposit_maturity"
    elif change == "crossed_account":assertion["account"] = live_report.accounts[1]
    elif change == "unselected_account":assertion["account"] = "unselected-public-account"
    elif change == "request_account":assertion["selected_request_account"] = live_report.accounts[1]
    elif change == "wrong_assertion_token":assertion._run_token = object()
    elif change == "fake_assertion":result.instrument_assertions = [dict(assertion)]
    elif change == "copy_assertion":result.instrument_assertions = [copy.copy(assertion)]
    elif change == "json_assertion":result.instrument_assertions = [json.loads(json.dumps(assertion))]
    elif change == "changed_value":assertion["value"] = "restricted_escrow"
    elif change == "changed_source":assertion["anchors"][0]["page"] = 4
    elif change == "copied_result":
        result.selection_witness = {"accounts":live_report.accounts, "token":live_report.runtime.run_token}
        result = copy.copy(result)
    elif change == "constructed_result":
        fake = ToolResult("read_account_balance_report", True)
        fake.__dict__.update(result.__dict__)
        result = fake
    elif change == "json_result":
        result = ToolResult("read_account_balance_report", True,
            data=json.loads(json.dumps(result.data)),
            instrument_assertions=json.loads(json.dumps(result.instrument_assertions)))
    elif change == "source_membership":result.data["source_fields"]["selected_accounts"].reverse()
    elif change == "trace_membership":result.data["trace"]["selected_accounts"].reverse()
    elif change == "row_membership":result.data["rows"][0]["account"] = live_report.accounts[1]
    elif change == "value_membership":
        assert result.data["source_fields"]["values"]
        result.data["source_fields"]["values"][0]["account"] = live_report.accounts[1]
    elif change == "allocation_premise":result.instrument_premises = [{}]
    elif change in {"instrument_figure", "genuine_other_claim"}:
        ordinary = read_instrument_details(live_report.runtime, {"view":"terms", "account":live_report.accounts[0],
            "currency":"USD", "as_of":"2021-01-31"})
        assert ordinary.ok
        if change == "instrument_figure":
            assert ordinary.figures
            result.figures.append(ordinary.figures[0])
        else:
            result.instrument_assertions = [next(item for item in ordinary.instrument_assertions
                if item["claim"] == "deposit_maturity")]
    _reject_without_evidence_mutation(result, live_report.runtime.run_token)


def test_selected_report_stale_ground_token_refuses(live_report):
    _reject_without_evidence_mutation(live_report.result, object())
    _reject_without_evidence_mutation(live_report.result, None)


def test_genuine_report_assertion_cannot_escape_into_an_ordinary_result(live_report):
    from viva.tools.envelope import ToolResult
    fake = ToolResult("read_instrument_details", True,
        instrument_assertions=list(live_report.result.instrument_assertions))
    _reject_without_evidence_mutation(fake, live_report.runtime.run_token)


def test_private_result_witness_does_not_keep_result_alive(live_report):
    from viva.tools.account_balances import _REPORTS, _REPORT_ASSERTIONS
    from viva.tools.envelope import ToolResult
    result = live_report.result
    identity = id(result)
    assertion = result.instrument_assertions[0]
    reference = weakref.ref(result)
    assert _REPORTS[identity].result() is result
    live_report.result = None
    del result
    gc.collect()
    assert reference() is None
    assert identity not in _REPORTS
    assert _REPORT_ASSERTIONS[id(assertion)][0]() is assertion
    fake = ToolResult("read_instrument_details", True, instrument_assertions=[assertion])
    _reject_without_evidence_mutation(fake, live_report.runtime.run_token)
    fake.instrument_assertions = []
    assertion_id = id(assertion)
    del assertion
    gc.collect()
    assert assertion_id not in _REPORT_ASSERTIONS


def _preimage_stamp():
    import viva.tools.runner as runner
    source = textwrap.dedent(inspect.getsource(runner._Ground.stamp))
    before = '''    from .account_balances import selected_report_stamping_status
    selected_report = selected_report_stamping_status(result, self.instrument_token)
    if selected_report is False:
        raise ValueError("untrusted selected report at run stamping")
    for assertion in result.instrument_assertions:
        if selected_report is not True and (result.tool != ("read_retirement_funding" if assertion.get("claim") in RETIREMENT_CLAIMS else "read_instrument_details") or not authenticated_assertion(assertion) or assertion._run_token is not self.instrument_token):
            raise ValueError("untrusted instrument assertion at run stamping")'''
    after = '''    for assertion in result.instrument_assertions:
        if result.tool != ("read_retirement_funding" if assertion.get("claim") in RETIREMENT_CLAIMS else "read_instrument_details") or not authenticated_assertion(assertion) or assertion._run_token is not self.instrument_token:
            raise ValueError("untrusted instrument assertion at run stamping")'''
    assert source.count(before) == 1
    namespace = dict(vars(runner))
    exec(compile(source.replace(before, after), "<retained ordinary preflight>", "exec"), namespace)
    return namespace["stamp"]


def test_ordinary_instrument_same_live_revision_serialization_is_identical(live_report):
    from viva.tools.instruments import read_instrument_details
    args = {"view":"terms", "account":live_report.accounts[0], "currency":"USD", "as_of":"2021-01-31"}
    first = read_instrument_details(live_report.runtime, args)
    second = read_instrument_details(live_report.runtime, args)
    assert first.ok and first.instrument_assertions and second.ok
    baseline, candidate = _graph(live_report.runtime.run_token), _graph(live_report.runtime.run_token)
    _preimage_stamp()(baseline.ground, first)
    candidate.ground.stamp(second)
    assert baseline.to_dict() == candidate.to_dict()
    assert json.dumps(first.to_dict(), sort_keys=True) == json.dumps(second.to_dict(), sort_keys=True)


def test_retirement_and_instrument_same_authenticated_revision_keep_preimage_serialization(tmp_path, monkeypatch):
    from contextlib import contextmanager
    from pathlib import Path
    from time import monotonic
    from viva.ingest import RawStore
    from viva.instrument_runtime import InstrumentRuntime
    from viva.read_store import ReadStore
    from viva.tools.instruments import read_instrument_details
    from viva.retirement_funding.tool import runtime_spec
    from viva.ledger.instruments import reference_accounts
    from test_instrument_projector_b import ingest
    from test_instrument_contracts import deposit_json, printed
    monkeypatch.syspath_prepend(str(Path(__file__).parent / "investment_evidence"))
    from retirement_funding.retirement_wire_fixture import fixture

    ledger, plans = fixture(tmp_path / "life", tmp_path / "printed")
    raw = RawStore.open(tmp_path / "extra-raw", "synthetic-passphrase")
    data = deposit_json()
    data["terms"] = {"principal":printed("1000"), "opened":printed("2021-01-01"),
        "maturity":printed("2022-01-01"), "withdrawal_restriction":printed("No withdrawal until maturity")}
    ingest(raw, ledger, "compatibility-term", data, "term_deposit_statement")
    projection = ledger.projection()
    account = reference_accounts(projection, "CD-A")[0]
    with ReadStore.create(tmp_path / "read", "synthetic-passphrase") as store:
        store.synchronize(ledger.store)
        @contextmanager
        def supplier():
            with store.open_reader() as revision:
                yield revision
        runtime = InstrumentRuntime(supplier)
        with runtime.execution(monotonic() + 15):
            identity = store.authenticated_source_identity(runtime.revision)
            first = runtime_spec(runtime, "2025-01-01").fn({"view":"direct_rollovers",
                "plans":plans, "currency":"USD", "from":"2022-01-01", "to":"2024-12-31"})
            second = runtime_spec(runtime, "2025-01-01").fn({"view":"direct_rollovers",
                "plans":plans, "currency":"USD", "from":"2022-01-01", "to":"2024-12-31"})
            assert first.ok and second.ok, (first.to_dict(), second.to_dict())
            assert first.instrument_assertions
            baseline, candidate = _graph(runtime.run_token), _graph(runtime.run_token)
            _preimage_stamp()(baseline.ground, first)
            candidate.ground.stamp(second)
            assert baseline.to_dict() == candidate.to_dict()
            assert json.dumps(first.to_dict(), sort_keys=True) == json.dumps(second.to_dict(), sort_keys=True)
            args = {"view":"terms", "account":account, "currency":"USD", "as_of":"2021-01-31"}
            first, second = read_instrument_details(runtime, args), read_instrument_details(runtime, args)
            assert first.ok and second.ok and first.instrument_assertions
            baseline, candidate = _graph(runtime.run_token), _graph(runtime.run_token)
            _preimage_stamp()(baseline.ground, first)
            candidate.ground.stamp(second)
            assert baseline.to_dict() == candidate.to_dict()
            assert json.dumps(first.to_dict(), sort_keys=True) == json.dumps(second.to_dict(), sort_keys=True)
            assert identity == store.authenticated_source_identity(runtime.revision)


def test_two_genuine_selected_assertions_preflight_together_before_any_ids_change(tmp_path):
    from contextlib import contextmanager
    from time import monotonic
    from viva.instrument_runtime import InstrumentRuntime
    from viva.ledger.instruments import reference_accounts
    from viva.read_store import ReadStore
    from viva.tools.account_balances import read_report
    from test_instrument_projector_b import setup, ingest
    from test_instrument_contracts import deposit_json, printed
    raw, ledger = setup(tmp_path)
    for reference in ("CD-A", "CD-B"):
        data = deposit_json()
        data["identity"]["account_reference"] = printed(reference)
        data["terms"] = {"principal":printed("1000"), "opened":printed("2021-01-01"),
            "maturity":printed("2022-01-01"), "withdrawal_restriction":printed("No withdrawal until maturity")}
        ingest(raw, ledger, "two-assertions-" + reference, data, "term_deposit_statement")
    projection = ledger.projection()
    accounts = [reference_accounts(projection, ref)[0] for ref in ("CD-A", "CD-B")]
    with ReadStore.create(tmp_path / "read", "synthetic-passphrase") as store:
        store.synchronize(ledger.store)
        @contextmanager
        def supplier():
            with store.open_reader() as revision:
                yield revision
        supplier.source_identity = ledger.store.authenticated_identity
        supplier.expected_projection_identity = ledger._projection_identity
        runtime = InstrumentRuntime(supplier)
        with runtime.execution(monotonic() + 15):
            args = {f"account_{i}":account for i,account in enumerate(accounts,1)}
            positive = read_report(projection, runtime, "2021-01-31", args)
            assert positive.ok and len(positive.instrument_assertions) == 2
            graph = _graph(runtime.run_token)
            graph.stamp("selected_balances", positive)
            assert len(graph.ground.instrument_assertions) == 2
            negative = read_report(projection, runtime, "2021-01-31", args)
            assert negative.ok and len(negative.instrument_assertions) == 2
            negative.instrument_assertions[1]["anchors"][0]["page"] = 4
            _reject_without_evidence_mutation(negative, runtime.run_token)
            assert all(not assertion["id"] for assertion in negative.instrument_assertions)


@pytest.mark.parametrize("envelope", ["constructed", "copied_result"])
def test_copy_of_report_assertion_cannot_escape_through_ordinary_producer(live_report, envelope):
    from viva.tools.envelope import ToolResult
    from viva.instrument_evidence import authenticated_assertion
    original = live_report.result.instrument_assertions[0]
    cloned = copy.copy(original)
    assert cloned is not original
    assert authenticated_assertion(cloned)
    assert cloned._run_token is live_report.runtime.run_token
    forged = ToolResult('read_instrument_details', True, instrument_assertions=[cloned])
    if envelope == 'copied_result':
        forged = copy.copy(live_report.result)
        forged.tool = 'read_instrument_details'
        forged.instrument_assertions = [cloned]
    _reject_without_evidence_mutation(forged, live_report.runtime.run_token)


def test_independently_issued_same_value_ordinary_restriction_after_report_is_valid(live_report):
    from viva.tools.instruments import read_instrument_details
    from viva.instrument_evidence import authenticated_assertion
    original = live_report.result.instrument_assertions[0]
    ordinary = read_instrument_details(live_report.runtime,
        {'view':'terms', 'account':live_report.accounts[0], 'currency':'USD', 'as_of':'2021-01-31'})
    assert ordinary.ok
    restriction = next(a for a in ordinary.instrument_assertions if a['claim'] == 'availability_restriction')
    assert restriction is not original
    assert dict(restriction) == dict(original)
    assert restriction._proof == original._proof
    assert restriction._run_token is original._run_token is live_report.runtime.run_token
    assert authenticated_assertion(restriction)
    graph = _graph(live_report.runtime.run_token)
    graph.stamp('independent_ordinary_after_report', ordinary)
    assert restriction['id'] in graph.ground.instrument_assertions


def test_copied_report_origin_survives_original_result_and_assertion_lifetime(live_report):
    from viva.tools.envelope import ToolResult
    from viva.tools.account_balances import _REPORTS, _REPORT_ASSERTIONS
    original = live_report.result.instrument_assertions[0]
    original_id = id(original)
    result_id = id(live_report.result)
    cloned = copy.copy(original)
    twice = copy.copy(cloned)
    assert twice._selected_report_origin is cloned._selected_report_origin is original._selected_report_origin
    assert copy.deepcopy(original)._selected_report_origin is original._selected_report_origin
    original_ref, result_ref = weakref.ref(original), weakref.ref(live_report.result)
    live_report.result = None
    del original
    gc.collect()
    assert original_ref() is None and result_ref() is None
    assert result_id not in _REPORTS and original_id not in _REPORT_ASSERTIONS
    for assertion in (cloned, twice):
        envelope = ToolResult("read_instrument_details", True, instrument_assertions=[assertion])
        _reject_without_evidence_mutation(envelope, live_report.runtime.run_token)


def test_report_origin_private_attribute_copy_cannot_issue_a_result_witness(live_report):
    from viva.tools.envelope import ToolResult
    original = live_report.result
    fake = ToolResult("read_account_balance_report", True)
    fake.__dict__.update(original.__dict__)
    fake._selected_report_origin = original.instrument_assertions[0]._selected_report_origin
    _reject_without_evidence_mutation(fake, live_report.runtime.run_token)


def _selected_wire_source(tmp_path, holdings=20, component_padding=0, *, unmeasured_debt=False):
    """Normal synthetic ingestion for seven mixed-kind selected account rows."""
    from io import BytesIO
    from decimal import Decimal
    from reportlab.pdfgen.canvas import Canvas
    from viva.ingest import StatementFacts, BrokerageFacts, PositionFact, ReadResult, capture_and_ingest
    from viva.investment.extraction import parse, HEADERS, POSITION
    from test_instrument_projector_b import setup, ingest, bank, mortgage
    from test_instrument_contracts import deposit_json, printed
    raw, ledger = setup(tmp_path)
    bank(raw, ledger)
    ingest(raw, ledger, "seven-loan", mortgage(), "mortgage_statement")
    deposit = deposit_json()
    deposit["terms"] = {"principal":printed("1000"), "opened":printed("2021-01-01"),
        "maturity":printed("2022-01-01"), "withdrawal_restriction":printed("No withdrawal until maturity")}
    ingest(raw, ledger, "seven-deposit", deposit, "term_deposit_statement")
    from viva.ledger.instruments import reference_accounts
    projection = ledger.projection()
    selected = [reference_accounts(projection, ref)[0] for ref in ("CHECK-A", "CD-A", "LOAN-A")]
    def pdf(label):
        stream = BytesIO()
        canvas = Canvas(stream, invariant=1)
        for page in range(1, 5):
            canvas.drawString(30, 750, "SYNTHETIC TEST SOURCE — " + label + " — page " + str(page))
            canvas.showPage()
        canvas.save()
        return stream.getvalue()
    def capture(facts, label):
        def reading(blob, document):
            facts.doc_id = document
            return ReadResult(facts.doc_type, 1.0, facts)
        result = capture_and_ingest(raw, ledger, pdf(label), reading)
        assert result.action == "posted", result
        return result.account
    card = StatementFacts("", "credit_card_statement", 1.0, "Synthetic Card", "USD",
        Decimal("400"), "2021-01-01", Decimal("400"), "2021-01-31", [],
        opening_page=4, closing_page=4, account_number="SYNTHETIC-CARD",
        institution="Synthetic Card Issuer", account_names=["Synthetic Person"])
    selected.append(capture(card, "card"))
    for index in range(3):
        name = "Synthetic investment " + chr(65 + index)
        def source(cash, positions, when):
            headers = {key:None for key in HEADERS}
            headers.update(account_reference={"raw":"INV-"+str(index),"page":4},
                currency={"raw":"USD","page":4}, as_of={"raw":when,"page":4},
                closing_cash={"raw":str(cash),"page":4})
            lines = []
            for item in positions:
                row = {key:None for key in POSITION}
                row.update(identifier={"raw":item.instrument,"page":2}, label={"raw":item.instrument,"page":2},
                    units={"raw":str(item.units),"page":2}, market_value={"raw":str(item.market_value),"page":2})
                lines.append(row)
            return parse({"schema":"investment-source-v2","headers":headers,"positions":lines,"rows":[]})
        positions = [PositionFact("Synthetic holding " + str(j) + "x" * component_padding, Decimal("2"), Decimal("10"), page=2)
            for j in range(holdings)]
        facts = BrokerageFacts("", "brokerage_statement", 1.0, name, "USD", "2021-02-28",
            Decimal("100"), Decimal("100") + holdings * Decimal("10"), positions,
            account_number="INV-"+str(index), institution="Synthetic Investment Custodian",
            account_names=["Synthetic Person"], investment_source=source("100", positions, "2021-02-28"))
        account = capture(facts, name + " positions")
        newer = BrokerageFacts("", "brokerage_statement", 1.0, name, "USD", "2021-03-31",
            Decimal("100"), Decimal("100"), [], account_number="INV-"+str(index),
            institution="Synthetic Investment Custodian", account_names=["Synthetic Person"],
            investment_source=source("100", [], "2021-03-31"))
        assert capture(newer, name + " cash") == account
        selected.append(account)
    if unmeasured_debt:
        from viva.ledger import account_opened
        from viva.ledger.events import ASSERTED
        ledger.append(account_opened("synthetic-unmeasured-debt", "liability", "Synthetic unmeasured loan",
            "USD", "2021-01-01", origin=ASSERTED))
        selected[3] = "synthetic-unmeasured-debt"
    return ledger, selected


def _actual_selected_wire(tmp_path, holdings=20, component_padding=0, *, ordinary=False, configure=None, unmeasured_debt=False, session_mode=False):
    from contextlib import contextmanager
    from types import SimpleNamespace
    from viva.answer_program import (CapabilityManifest, ProgramValidator, ProgramExecutor,
        DeterministicBinder, AnswerResourcePolicy, QuestionContext)
    from viva.answer_program.intents import SemanticFamilyRegistry, SemanticRequest, SemanticOutcome
    from viva.answer_program.compiler import CompilationResult
    from viva.answer_program.runtime import AnswerProgramRuntime
    from viva.tools import default_registry
    from viva.surface.conversation import conversation
    from viva.read_store import ReadStore
    ledger, accounts = _selected_wire_source(tmp_path, holdings, component_padding, unmeasured_debt=unmeasured_debt)
    projection = ledger.projection()
    with ReadStore.create(tmp_path / "wire-read", "synthetic-passphrase") as store:
        store.synchronize(ledger.store)
        acquisitions = []
        phase = ["precompile_catalog"]
        @contextmanager
        def supplier(*, deadline=None):
            from time import monotonic
            acquisitions.append(dict(phase=phase[0], deadline=deadline, entered=monotonic()))
            with store.open_reader() as revision:
                yield revision
            acquisitions[-1]["exited"] = monotonic()
        supplier.deadline_aware = True
        supplier.source_identity = ledger.store.authenticated_identity
        supplier.expected_projection_identity = ledger._projection_identity
        registry = default_registry(projection, today="2021-04-01", instrument_scope=supplier)
        if configure is not None:
            configure(registry, projection, supplier)
        families = SemanticFamilyRegistry(registry.semantic_entities(), currency_resolver=registry.instrument_currency)
        manifest = CapabilityManifest.from_registry(registry)
        request = SemanticRequest("selected_account_balances",
            {f"account_phrase_{i}":account for i,account in enumerate(accounts,1)},
            ("account_report",), families.catalog_digest)
        if ordinary:
            request = SemanticRequest("instrument_terms", {"account_phrase":accounts[1],"as_of":"2021-04-01"},
                ("availability_restriction",), families.catalog_digest)
        outcome = SemanticOutcome("request", request)
        program = families.lower(outcome, manifest)
        policy = AnswerResourcePolicy()
        validation = ProgramValidator(manifest, policy).validate(program)
        assert validation.ok, [item.to_dict() for item in validation.defects]
        class Compiler:
            def compile(self, context):return CompilationResult(program, validation, (), outcome)
        runtime = AnswerProgramRuntime(Compiler(), ProgramExecutor(registry, policy), DeterministicBinder(registry, "en-US"))
        context = QuestionContext("Show the dated amounts, source pages, recorded restrictions and closure status for the selected accounts.",
            today="2021-04-01", locale="en-US")
        phase[0] = "financial_execution"
        normal_turn = None
        if session_mode:
            from viva.session import Session
            from viva.answer_program.compiler import AnswerProgramCompiler
            from test_answer_program_contracts import _turn
            names = {info.account:info.name for info in projection.account_infos()}
            question = "Show dated amounts, source pages, restrictions and closure for " + ", ".join(names[a] for a in accounts)
            class Adapter:
                calls = 0
                def converse(self, messages, tools):
                    self.calls += 1
                    reply = _turn({"parameters":{f"account_phrase_{i}":{"catalog_id":a}
                        for i,a in enumerate(accounts,1)},
                        "parameter_sources":{f"account_phrase_{i}":{"source":"question", "quote":names[a],
                            "derivation":"catalog_selection"} for i,a in enumerate(accounts,1)},
                        "requested_claims":["account_report"]},"select_selected_account_balances")
                    reply.cost_usd = 0
                    return reply
            adapter = Adapter()
            session = Session(registry,lambda validator,built,policy:AnswerProgramCompiler(adapter,validator,built,policy),
                ledger=ledger,model="synthetic-no-paid-model",today=lambda:"2021-04-01",locale="en-US")
            normal_turn = session.ask(question)
            assert adapter.calls == 1
            answered = SimpleNamespace(result=normal_turn.result,execution=normal_turn.instrument_execution)
            delivered = normal_turn
        else:
            answered = runtime.answer(context)
            delivered = SimpleNamespace(result=answered.result,question=context.question,
                instrument_execution=answered.execution)
        from viva.speak import _shown
        wire = conversation(delivered, _shown(answered.result),
            projection=projection, turn_id="selected-seven")
        return SimpleNamespace(answered=answered, wire=wire, program=program, validation=validation,
            accounts=accounts, ledger=ledger, projection=projection, acquisitions=acquisitions, normal_turn=normal_turn)


def test_seven_complete_selected_accounts_reach_existing_receipt_wire(tmp_path):
    from viva.tools.account_balances import complete_bytes
    actual = _actual_selected_wire(tmp_path)
    result = actual.answered.result
    assert result.status == "partial", (result.status, result.detail, [item.to_dict() for item in actual.answered.binding.unbound], [(item.node_id,item.status,item.refusal) for item in actual.answered.execution.nodes.values()])
    assert len(actual.program.nodes) == 8
    assert len(actual.program.shape.clauses) == 10
    producer = next(item for item in actual.answered.execution.transcript if item.tool == "read_account_balance_report")
    assert producer.ok, producer.to_dict()
    assert producer.data["trace"]["authority_invocations"] == 14
    assert complete_bytes(producer) <= 50000
    assert actual.answered.execution.graph.size_bytes <= 250000
    assert len(actual.wire["figures"]) == 7
    assert len(actual.wire["numerical_receipts"]) == 1
    assert all(figure["receipt_ids"] and figure["evidence_links"] for figure in actual.wire["figures"])
    assert {figure["subject"]["account_id"] for figure in actual.wire["figures"]} == set(actual.accounts)


def test_emit_complete_selected_wire_measurements(tmp_path):
    from viva.tools.account_balances import complete_bytes
    actual = _actual_selected_wire(tmp_path)
    producer = next(item for item in actual.answered.execution.transcript if item.tool == "read_account_balance_report")
    assert producer.ok and actual.answered.result.status == "partial"
    payload = {**producer.to_dict(), "complete_figures":[dict(f) for f in producer.figures]}
    source = producer.data["source_fields"]
    pairs = {(term["document"], term["page"]) for value in source["values"] for term in value["terms"]}
    measurement = {"complete_tool_result_bytes":complete_bytes(producer),
        "graph_bytes":actual.answered.execution.graph.size_bytes,
        "receipt_bytes":len(json.dumps(actual.wire["numerical_receipts"],ensure_ascii=False,separators=(",",":")).encode()),
        "answer_bytes":len(json.dumps(actual.wire,ensure_ascii=False,separators=(",",":")).encode()),
        "figures":len(producer.figures),"source_pairs":len(pairs),
        "terms":sum(len(value["terms"]) for value in source["values"]),
        "assertions":len(producer.instrument_assertions), "nodes":len(actual.program.nodes),
        "clauses":len(actual.program.shape.clauses),"trace":producer.data["trace"],
        "source_identity":source["source_identity"],"status":actual.answered.result.status}
    (tmp_path / "actual-wire.json").write_text(json.dumps(actual.wire,ensure_ascii=False,indent=2)+"\n")
    (tmp_path / "complete-tool-result.json").write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n")
    (tmp_path / "measurements.json").write_text(json.dumps(measurement,indent=2)+"\n")
    assert measurement["complete_tool_result_bytes"] <= 50000
    assert measurement["graph_bytes"] <= 250000
    assert measurement["figures"] == 7
    assert all(f["written"] for f in actual.wire["figures"])


@pytest.mark.parametrize("padding", [317, 318, 320])
def test_full_composed_wire_refuses_the_first_over_byte_envelope(tmp_path, padding, monkeypatch):
    import viva.tools.account_balances as adapter
    complete_bytes = adapter.complete_bytes
    measured = []
    def encoded(result):
        size = complete_bytes(result)
        measured.append(dict(stamped=bool(result.id), bytes=size,
            payload={**result.to_dict(), "complete_figures":[dict(f) for f in result.figures]}))
        return size
    monkeypatch.setattr(adapter, "complete_bytes", encoded)
    actual = _actual_selected_wire(tmp_path, component_padding=padding)
    produced = next(item for item in actual.answered.execution.transcript if item.tool == "read_account_balance_report")
    (tmp_path / "complete-measurements.json").write_text(json.dumps(measured,ensure_ascii=False,indent=2)+"\n")
    (tmp_path / "actual-wire.json").write_text(json.dumps(actual.wire,ensure_ascii=False,indent=2)+"\n")
    (tmp_path / "disposition.json").write_text(json.dumps({"padding":padding,"ok":produced.ok,
        "refusal":produced.refusal,"trace":produced.data["trace"],"graph_bytes":actual.answered.execution.graph.size_bytes,
        "receipt_bytes":len(json.dumps(actual.wire["numerical_receipts"],ensure_ascii=False,separators=(",",":")).encode()),
        "answer_bytes":len(json.dumps(actual.wire,ensure_ascii=False,separators=(",",":")).encode())},indent=2)+"\n")
    if produced.ok:
        assert complete_bytes(produced) <= 50000
        assert len(actual.wire["figures"]) == 7
        assert actual.answered.result.status == "partial"
    else:
        assert produced.refusal == "resource_limit"
        assert produced.data["trace"]["authority_invocations"] == 14
        assert not actual.answered.result.answered
        assert not actual.wire["figures"]
        assert not actual.wire["numerical_receipts"]


def test_precompile_metadata_and_financial_revision_acquisitions_are_counted_separately(tmp_path):
    baseline = _actual_selected_wire(tmp_path / "baseline", ordinary=True)
    candidate = _actual_selected_wire(tmp_path / "candidate")
    for actual in (baseline, candidate):
        assert [entry["phase"] for entry in actual.acquisitions] == ["precompile_catalog", "financial_execution"]
        for entry in actual.acquisitions:
            assert entry["deadline"] is not None
            assert 0 < entry["deadline"] - entry["entered"] <= 2
    assert candidate.answered.result.status == "partial"
    (tmp_path / "acquisitions.json").write_text(json.dumps({"baseline":baseline.acquisitions,
        "candidate":candidate.acquisitions, "whole_lifecycle_acquisitions_each":2,
        "metadata_catalog_acquisitions_each":1, "financial_execution_acquisitions_each":1},indent=2)+"\n")


def _semantic_selection(count=7):
    from viva.answer_program.intents import SemanticFamilyRegistry, SEMANTIC_REQUEST_VERSION
    from viva.answer_program import QuestionContext, CapabilityManifest
    from viva.ledger import LedgerProjection, account_opened
    from viva.tools import default_registry
    rows = [{"id":"account-"+chr(97+i), "name":"Synthetic account "+chr(65+i),
        "institution":"Synthetic Institute", "kind":("liability" if i == 1 else "investment" if i == 2 else "depository")}
        for i in range(7)]
    families = SemanticFamilyRegistry({"accounts":rows,"coverage":{"accounts":{"count":7,"complete":True}}})
    question = "Show " + ", ".join(row["name"] for row in rows[:count])
    raw = {"request_version":SEMANTIC_REQUEST_VERSION,"catalog_digest":families.catalog_digest,
        "entity_catalog_digest":families.entity_catalog_digest,"outcome":"request","family":"selected_account_balances",
        "parameters":{f"account_phrase_{i+1}":{"catalog_id":row["id"]} for i,row in enumerate(rows[:count])},
        "parameter_sources":{f"account_phrase_{i+1}":{"source":"question","quote":row["name"],"derivation":"catalog_selection"}
            for i,row in enumerate(rows[:count])},
        "requested_claims":["account_report"]}
    registry = default_registry(LedgerProjection([account_opened(row["id"],row["kind"],row["name"],"USD","2021-01-01") for row in rows]))
    return families, raw, QuestionContext(question), CapabilityManifest.from_registry(registry)


@pytest.mark.parametrize("count", [2,5,7])
def test_fixed_individually_grounded_selection_has_one_report_and_exact_resolvers(count):
    from viva.answer_program import ProgramValidator, AnswerResourcePolicy
    families, raw, context, manifest = _semantic_selection(count)
    outcome = families.parse(families.materialize_model_output(raw), context)
    program = families.lower(outcome, manifest)
    validation = ProgramValidator(manifest, AnswerResourcePolicy()).validate(program)
    assert validation.ok, [item.to_dict() for item in validation.defects]
    assert len(program.nodes) == count + 1
    assert len(program.shape.clauses) <= 10
    assert all(len(clause.text) <= 400 for clause in program.shape.clauses)
    assert validation.static_cost["max_authority_invocations"] == 14
    assert program.nodes[0].args == {f"account_{i+1}":"account-"+chr(97+i) for i in range(count)}
    assert len(program.bindings) <= 23


@pytest.mark.parametrize("change", ["hole", "eighth", "duplicate", "proof_swap", "stale_catalog", "stale_entities",
    "absent_quote", "wrong_prior_turn", "ambiguous_quote", "unknown_kind", "currency_argument"])
def test_invalid_selected_identity_contract_refuses_before_any_financial_read(change):
    from viva.answer_program.schema import ContractError
    families, raw, context, manifest = _semantic_selection()
    if change == "hole":
        del raw["parameters"]["account_phrase_4"]
        del raw["parameter_sources"]["account_phrase_4"]
    elif change == "eighth":
        raw["parameters"]["account_phrase_8"] = {"catalog_id":"account-h"}
        raw["parameter_sources"]["account_phrase_8"] = raw["parameter_sources"]["account_phrase_1"]
    elif change == "duplicate":
        raw["parameters"]["account_phrase_2"] = raw["parameters"]["account_phrase_1"]
        raw["parameter_sources"]["account_phrase_2"] = raw["parameter_sources"]["account_phrase_1"]
    elif change == "proof_swap":
        raw["parameter_sources"]["account_phrase_1"], raw["parameter_sources"]["account_phrase_2"] = raw["parameter_sources"]["account_phrase_2"], raw["parameter_sources"]["account_phrase_1"]
    elif change == "stale_catalog":raw["catalog_digest"] = "stale"
    elif change == "stale_entities":raw["entity_catalog_digest"] = "stale"
    elif change == "absent_quote":raw["parameter_sources"]["account_phrase_1"]["quote"] = "Unsaid account"
    elif change == "wrong_prior_turn":raw["parameter_sources"]["account_phrase_1"].update(source="prior_turn",turn=0)
    elif change == "ambiguous_quote":
        from viva.answer_program import QuestionContext
        context = QuestionContext(context.question + " at Synthetic Institute")
        raw["parameter_sources"]["account_phrase_1"]["quote"] = "Synthetic Institute"
    elif change == "unknown_kind":
        families._entity_rows["account_phrase"]["account-a"]["kind"] = "category"
    elif change == "currency_argument":
        raw["parameters"]["currency"] = "USD"
        raw["parameter_sources"]["currency"] = raw["parameter_sources"]["account_phrase_1"]
    with pytest.raises(ContractError):
        families.parse(families.materialize_model_output(raw), context)


def test_selected_grounded_aliases_canonicalize_then_reject_duplicates_and_prior_turn_proofs_work():
    from viva.answer_program import QuestionContext
    from viva.answer_program.schema import ContractError
    families, raw, context, manifest = _semantic_selection(2)
    for name in raw["parameters"]:
        raw["parameters"][name] = {"grounded_phrase":True}
        raw["parameter_sources"][name]["derivation"] = "verbatim"
    outcome = families.parse(families.materialize_model_output(raw), context)
    assert outcome.request.parameters == {"account_phrase_1":"account-a","account_phrase_2":"account-b"}
    for proof in raw["parameter_sources"].values():proof.update(source="prior_turn",turn=0)
    prior = QuestionContext("Use those selected accounts", prior_turns=((context.question,"A previous response"),))
    assert families.parse(families.materialize_model_output(raw), prior).kind == "request"
    raw["parameter_sources"]["account_phrase_2"] = dict(raw["parameter_sources"]["account_phrase_1"])
    with pytest.raises(ContractError):families.parse(families.materialize_model_output(raw), prior)


@pytest.mark.parametrize("change", ["extra_argument", "outside_family", "extra_report", "wrong_cost", "wrong_identity"])
def test_program_validator_preserves_the_closed_report_and_declared_authority_cost(change):
    from dataclasses import replace
    from viva.answer_program import ProgramValidator, AnswerResourcePolicy, AnswerProgram
    families, raw, context, manifest = _semantic_selection()
    program = families.lower(families.parse(families.materialize_model_output(raw), context), manifest)
    source = program.to_dict()
    if change == "extra_argument":source["nodes"][0]["args"]["currency"] = "USD"
    elif change == "outside_family":source["question_kind"] = "net_worth"
    elif change == "extra_report":
        another = copy.deepcopy(source["nodes"][0]);another["id"] = "other_report";source["nodes"].append(another)
    elif change == "wrong_identity":source["nodes"][1]["phrase"] = "account-b"
    elif change == "wrong_cost":
        capabilities = tuple(replace(item,bounds={**item.bounds,"max_authority_invocations":15})
            if item.name == "read_account_balance_report" else item for item in manifest.capabilities)
        manifest = replace(manifest,capabilities=capabilities)
        source["capability_manifest_digest"] = manifest.digest
    validation = ProgramValidator(manifest, AnswerResourcePolicy()).validate(AnswerProgram.from_dict(source))
    assert not validation.ok
    assert any(item.tag in {"invalid_capability_arguments","invalid_selected_report"} for item in validation.defects)


def test_actual_authority_calls_reuse_exact_cash_once_and_share_revision_deadline_and_thread(tmp_path, monkeypatch):
    import threading
    import viva.ledger.projection.balances as balances
    import viva.read_store.instrument_authority as authority
    observed = {"balances":[], "values":[], "dispatches":[]}
    def configure(registry, projection, supplier):
        original_balance = balances.balance
        def balance(core, account):
            value = original_balance(core, account)
            if core is projection.core:
                observed["balances"].append((account, value, threading.get_ident()))
            return value
        monkeypatch.setattr(balances,"balance",balance)
        original_values = projection.composed_values
        def values(account, *args, **kwargs):
            capture = kwargs.get("source_capture")
            if capture is not None:
                same = [value for selected,value,thread in observed["balances"] if selected == account]
                assert len(same) == 1 and capture.balance_answer is same[0]
                observed["values"].append(account)
            return original_values(account,*args,**kwargs)
        monkeypatch.setattr(projection,"composed_values",values)
        original_dispatch = authority.read_instrument_authority
        def dispatch(revision, request, *, deadline, **kwargs):
            runtime = registry.instrument_runtime
            assert revision is runtime.revision
            assert deadline == min(runtime.deadline,runtime.started+2)
            observed["dispatches"].append((request.account,id(revision),deadline,threading.get_ident()))
            return original_dispatch(revision,request,deadline=deadline,**kwargs)
        monkeypatch.setattr(authority,"read_instrument_authority",dispatch)
    actual = _actual_selected_wire(tmp_path, configure=configure)
    assert len(observed["balances"]) == len(observed["values"]) == len(observed["dispatches"]) == 7
    assert {account for account,value,thread in observed["balances"]} == set(actual.accounts)
    assert len({revision for account,revision,deadline,thread in observed["dispatches"]}) == 1
    assert len({deadline for account,revision,deadline,thread in observed["dispatches"]}) == 1
    assert {thread for account,value,thread in observed["balances"]} == {threading.get_ident()}
    assert {thread for account,revision,deadline,thread in observed["dispatches"]} == {threading.get_ident()}
    assert actual.answered.result.status == "partial"


@pytest.mark.parametrize("stage", ["source_collection", "stamped_serialization"])
def test_shared_financial_deadline_expiry_refuses_the_entire_report(tmp_path, monkeypatch, stage):
    import viva.tools.account_balances as adapter
    import viva.ledger.projection.positions as positions
    import viva.answer_program.execute as execution
    from time import monotonic as real_clock
    def configure(registry, projection, supplier):
        if stage == "source_collection":
            original = positions.SourceCapture.check
            calls = [0]
            def check(capture):
                calls[0] += 1
                return original(capture)
            monkeypatch.setattr(positions.SourceCapture,"check",check)
            monkeypatch.setattr(positions,"monotonic",lambda:real_clock()+3 if calls[0] > 30 else real_clock())
        else:
            expired = [False]
            original = adapter.complete_bytes
            def encoding(result):
                size = original(result)
                if result.id:expired[0] = True
                return size
            monkeypatch.setattr(adapter,"complete_bytes",encoding)
            monkeypatch.setattr(execution.time,"monotonic",lambda:real_clock()+3 if expired[0] else real_clock())
    actual = _actual_selected_wire(tmp_path, configure=configure)
    produced = next(item for item in actual.answered.execution.transcript if item.tool == "read_account_balance_report")
    assert not produced.ok and produced.refusal == "resource_limit"
    assert produced.data["trace"]["authority_invocations"] > 0
    assert not actual.answered.result.answered
    assert not actual.wire["figures"] and not actual.wire["numerical_receipts"]


@pytest.mark.parametrize("change", ["missing_expected", "missing_current", "changed_after_balance", "changed_during_encoding"])
def test_owned_report_refuses_unprovable_or_changed_supplier_identity(live_report, monkeypatch, change):
    import viva.tools.account_balances as adapter
    supplier = live_report.runtime.supplier
    if change == "missing_expected":del supplier.expected_projection_identity
    elif change == "missing_current":del supplier.source_identity
    elif change == "changed_after_balance":
        original = live_report.projection.balance
        def balance(account):
            result = original(account)
            supplier.source_identity = lambda:(999,"different-head")
            return result
        monkeypatch.setattr(live_report.projection,"balance",balance)
    else:
        original = adapter.complete_bytes
        def encoding(result):
            size = original(result)
            supplier.source_identity = lambda:(999,"different-head")
            return size
        monkeypatch.setattr(adapter,"complete_bytes",encoding)
    result = adapter.read_report(live_report.projection,live_report.runtime,"2021-01-31",
        {f"account_{i}":account for i,account in enumerate(live_report.accounts,1)})
    assert not result.ok and result.refusal == "current_data_unavailable"
    if change.startswith("missing"):
        assert result.data["trace"]["authority_invocations"] == 0
    else:
        assert result.data["trace"]["authority_invocations"] == 4


def test_same_count_independent_projection_and_read_revision_cannot_be_crossed(live_report, tmp_path):
    from viva.tools.account_balances import read_report
    from viva.read_store import ReadStore
    from test_instrument_projector_b import setup, ingest, bank
    from test_instrument_contracts import deposit_json, printed
    raw, ledger = setup(tmp_path / "other")
    data = deposit_json()
    data["terms"] = {"principal":printed("1000"),"opened":printed("2021-01-01"),
        "maturity":printed("2022-01-01"),"withdrawal_restriction":printed("No withdrawal until maturity")}
    ingest(raw,ledger,"selected-term",data,"term_deposit_statement")
    bank(raw,ledger)
    other_projection = ledger.projection()
    identity = live_report.runtime.revision._store.authenticated_source_identity(live_report.runtime.revision)
    other_identity = ledger.store.authenticated_identity()
    assert other_identity[0] == identity["count"] and other_identity[1] != identity["head"]
    args = {f"account_{i}":account for i,account in enumerate(live_report.accounts,1)}
    crossed_projection = read_report(other_projection,live_report.runtime,"2021-01-31",args)
    assert not crossed_projection.ok and crossed_projection.refusal == "current_data_unavailable"
    with ReadStore.create(tmp_path / "other-read","synthetic-passphrase") as store:
        store.synchronize(ledger.store)
        with store.open_reader() as revision:
            original = live_report.runtime.revision
            live_report.runtime.revision = revision
            try:crossed_revision = read_report(live_report.projection,live_report.runtime,"2021-01-31",args)
            finally:live_report.runtime.revision = original
    assert not crossed_revision.ok and crossed_revision.refusal == "current_data_unavailable"


@pytest.mark.parametrize("mode", ["terms", "pages"])
def test_capture_refuses_before_retaining_the_bound_plus_one_snapshot_row(mode):
    from decimal import Decimal
    from time import monotonic
    from viva.ledger import LedgerProjection, account_opened, closing_balance_observed, Provenance
    from viva.ledger.events import position_observed
    from viva.ledger.projection.positions import SourceCapture, CaptureLimit
    count = 1000 if mode == "terms" else 128
    events = [account_opened("bounded","investment","Synthetic bounded account","USD","2021-01-01"),
        closing_balance_observed("bounded","0","2021-01-31",Provenance("cash-source",4))]
    events += [position_observed("bounded","Synthetic holding "+str(i),"1","1","USD","2021-01-31",
        provenance=Provenance("holding-source-"+str(i) if mode == "pages" else "holding-source",2)) for i in range(count)]
    projection = LedgerProjection(events)
    cash = projection.balance("bounded")
    capture = SourceCapture("bounded",cash,monotonic()+2)
    attempts = []
    original = capture.before_position
    def attempted(size):
        attempts.append(size)
        return original(size)
    capture.before_position = attempted
    with pytest.raises(CaptureLimit):projection.composed_values("bounded",source_capture=capture)
    assert len(capture.terms) == 1
    assert max(attempts) == (999 if mode == "terms" else 127)
    assert len(attempts) == count
    assert projection.composed_values("bounded")[0].amount == Decimal(count)


@pytest.mark.parametrize("omission", ["account", "date", "source"])
def test_runtime_independently_discloses_missing_published_fields(tmp_path, monkeypatch, omission):
    from viva.answer_program.bind import DeterministicBinder
    original = DeterministicBinder.bind
    removed = []
    def bind(binder, program, execution):
        bound = original(binder, program, execution)
        if program.question_kind == "selected_account_balances" and bound.result.figures:
            figure = bound.result.figures[0]
            removed.append(figure["subject"]["account_id"])
            if omission == "account":bound.result.figures[:] = bound.result.figures[1:]
            elif omission == "date":figure.pop("dated", None)
            else:figure["record_ids"] = []
        return bound
    monkeypatch.setattr(DeterministicBinder,"bind",bind)
    actual = _actual_selected_wire(tmp_path)
    field = {"account":"amount","date":"date","source":"source"}[omission]
    assert actual.answered.result.status == "partial"
    assert any(item.get("account") == removed[0] and item.get("field") == field and
        item.get("disposition") == "unavailable" for item in actual.answered.result.missing)


@pytest.mark.parametrize("corruption", ["page", "missing_component", "cross_account", "missing_figure_source"])
def test_actual_composed_report_receipt_refuses_mutated_component_associations(tmp_path, corruption):
    from viva.tools.account_balances import source_digest
    from viva.surface.numerical_receipts import numerical_receipts
    actual = _actual_selected_wire(tmp_path)
    result = copy.deepcopy(actual.answered.result)
    report = next(item for item in result.transcript if item["tool"] == "read_account_balance_report")
    values = report["data"]["source_fields"]["values"]
    target = next(value for value in values if len(value["terms"]) > 2)
    if corruption == "page":target["terms"][0]["page"] = 201
    elif corruption == "missing_component":target["terms"].pop()
    elif corruption == "cross_account":target["terms"][0]["account"] = actual.accounts[0]
    else:result.figures[0].pop("balance_source_index")
    # A rehashed envelope still cannot change actual value/component/page closure.
    digest = source_digest(report["data"]["source_fields"])
    report["data"]["source_digest"] = digest
    for figure in [*report["figures"], *result.figures]:figure["balance_source_digest"] = digest
    from types import SimpleNamespace
    assert numerical_receipts(SimpleNamespace(result=result, question="Selected accounts",
        instrument_execution=actual.answered.execution), actual.projection, "mutated") == ([], {})


@pytest.mark.parametrize("defect", ["missing_date", "missing_document", "missing_page", "undated_debt"])
def test_missing_source_measurement_remains_unavailable_without_erasing_other_accounts(tmp_path, monkeypatch, defect):
    from dataclasses import replace
    from viva.ledger.projection.positions import SourceCapture
    removed = []
    def configure(registry, projection, supplier):
        if defect == "undated_debt":
            original = projection.balance
            def balance(account):
                value = original(account)
                if account == "acct:synthetic-card":
                    removed.append(account)
                    return replace(value, dated="")
                return value
            monkeypatch.setattr(projection,"balance",balance)
        else:
            original = SourceCapture.add
            def add(capture, *args, **kwargs):
                original(capture,*args,**kwargs)
                if capture.account == "acct:synthetic-card":
                    removed.append(capture.account)
                    capture.terms[-1][{"missing_date":"dated", "missing_document":"document", "missing_page":"page"}[defect]] = "" if defect != "missing_page" else 0
            monkeypatch.setattr(SourceCapture,"add",add)
    actual = _actual_selected_wire(tmp_path, configure=configure)
    assert removed
    assert len(actual.wire["figures"]) == 6
    assert not any(f["subject"]["account_id"] == removed[0] for f in actual.wire["figures"])
    assert any(item.get("account") == removed[0] and item.get("field") == "amount" and item.get("disposition") == "unavailable" for item in actual.answered.result.missing)
    report = next(item for item in actual.answered.execution.transcript if item.tool == "read_account_balance_report")
    assert report.ok and report.data["trace"]["authority_invocations"] == 14


@pytest.mark.parametrize("cash", ["0", "-40", "400"])
def test_opt_in_capture_preserves_dated_zero_credit_and_cross_currency_composition(cash):
    from decimal import Decimal
    from time import monotonic
    from viva.ledger import LedgerProjection, account_opened, closing_balance_observed, Provenance
    from viva.ledger.events import position_observed
    from viva.ledger.projection.positions import SourceCapture
    projection = LedgerProjection([
        account_opened("mixed", "investment", "Synthetic mixed currency", "USD", "2020-01-01"),
        closing_balance_observed("mixed", cash, "2020-01-31", Provenance("cash",4)),
        position_observed("mixed","Synthetic USD holding","2","20","USD","2021-02-28",provenance=Provenance("usd",2)),
        position_observed("mixed","Synthetic EUR holding","1","30","EUR","2021-02-28",provenance=Provenance("eur",3))])
    ordinary = projection.composed_values("mixed")
    capture = SourceCapture("mixed",projection.balance("mixed"),monotonic()+2)
    captured = projection.composed_values("mixed", source_capture=capture)
    assert [vars(v) for v in captured] == [vars(v) for v in ordinary]
    assert {v.currency:v.amount for v in captured} == {"USD":Decimal(cash)+20,"EUR":Decimal(30)}
    assert {v.currency:v.as_of for v in captured} == {"USD":"2020-01-31", "EUR":"2021-02-28"}
    assert capture.terms[0]["amount"] == cash and len(capture.terms) == 3


def test_genuine_owned_unmeasured_liability_is_unavailable_rather_than_zero(tmp_path):
    actual = _actual_selected_wire(tmp_path, unmeasured_debt=True)
    assert len(actual.wire["figures"]) == 6
    assert not any(f["subject"]["account_id"] == "synthetic-unmeasured-debt" for f in actual.wire["figures"])
    assert any(item.get("account") == "synthetic-unmeasured-debt" and item.get("field") == "amount" and
        item.get("disposition") == "unavailable" for item in actual.answered.result.missing)
    assert actual.answered.result.status == "partial"


def _mutate_valid_selected_source_page(result):
    from viva.tools.account_balances import source_digest
    report = next(item for item in result.transcript if item["tool"] == "read_account_balance_report")
    target = next(value for value in report["data"]["source_fields"]["values"]
                  if any(term["role"] == "holding" for term in value["terms"]))
    term = next(term for term in target["terms"] if term["role"] == "holding")
    assert term["page"] == 2
    term["page"] = 3
    digest = source_digest(report["data"]["source_fields"])
    report["data"]["source_digest"] = digest
    for figure in [*report["figures"], *result.figures]:figure["balance_source_digest"] = digest
    return report


@pytest.mark.parametrize("copy_result", [True, False])
def test_valid_wrong_page_rehash_refuses_with_genuine_execution_and_public_alias(tmp_path, copy_result):
    from types import SimpleNamespace
    from viva.surface.numerical_receipts import numerical_receipts
    from viva.tools.account_balances import selected_report_stamping_status
    actual = _actual_selected_wire(tmp_path)
    result = copy.deepcopy(actual.answered.result) if copy_result else actual.answered.result
    producer = next(item for item in actual.answered.execution.transcript if item.tool == "read_account_balance_report")
    row = next(item for item in result.transcript if item["tool"] == producer.tool)
    assert (row["data"] is producer.data) is (not copy_result)
    _mutate_valid_selected_source_page(result)
    if not copy_result:
        # A shallow public transcript mutation reaches the live dict, but the
        # immutable private issuance metadata still detects the changed page.
        assert selected_report_stamping_status(producer, actual.answered.execution.graph.ground.instrument_token) is False
    assert numerical_receipts(SimpleNamespace(result=result, question=actual.wire["question"],
        instrument_execution=actual.answered.execution), actual.projection, "valid-page") == ([], {})


def test_selected_json_transcript_roundtrip_keeps_original_origin_and_complete_receipts(tmp_path):
    from types import SimpleNamespace
    from viva.surface.numerical_receipts import numerical_receipts
    actual = _actual_selected_wire(tmp_path, component_padding=317)
    result = copy.deepcopy(actual.answered.result)
    origin = result._selected_report_origin
    assert origin is actual.answered.result._selected_report_origin
    serial = json.loads(json.dumps(result.to_dict()))
    assert "_selected_report_origin" not in serial
    result.figures = serial["figures"]
    result.transcript = serial["transcript"]
    receipts, refs = numerical_receipts(SimpleNamespace(result=result, question=actual.wire["question"],
        instrument_execution=actual.answered.execution), actual.projection, "selected-seven")
    assert result._selected_report_origin is origin
    assert receipts == actual.wire["numerical_receipts"] and len(refs) == 7
    # JSON-only data cannot mint a fresh answer origin by carrying the fields.
    detached = SimpleNamespace(figures=serial["figures"], transcript=serial["transcript"])
    assert numerical_receipts(SimpleNamespace(result=detached, question=actual.wire["question"],
        instrument_execution=actual.answered.execution), actual.projection, "detached") == ([], {})


@pytest.mark.parametrize("defect", ["missing", "wrong_token", "copied_producer", "cross_run"])
def test_selected_receipts_refuse_missing_stale_or_same_ledger_cross_run_execution(tmp_path, monkeypatch, defect):
    from types import SimpleNamespace
    from viva.surface.numerical_receipts import numerical_receipts
    actual = _actual_selected_wire(tmp_path)
    execution = actual.answered.execution
    if defect == "missing":execution = None
    elif defect == "wrong_token":monkeypatch.setattr(execution.graph.ground,"instrument_token",object())
    elif defect == "copied_producer":
        execution = copy.copy(execution)
        execution.transcript = [copy.copy(item) for item in execution.transcript]
    else:
        # Rerun exactly the same program against exactly the same live ledger;
        # all public source fields are identical, but origin/run must differ.
        from viva.answer_program import ProgramExecutor, AnswerResourcePolicy, DeterministicBinder
        from viva.answer_program.runtime import AnswerProgramRuntime
        from viva.answer_program.compiler import CompilationResult
        from viva.answer_program.schema import QuestionContext
        from viva.tools import default_registry
        from contextlib import contextmanager
        from viva.read_store import ReadStore
        with ReadStore.create(tmp_path/"cross-run-read", "synthetic-passphrase") as store:
            store.synchronize(actual.ledger.store)
            @contextmanager
            def supplier():
                with store.open_reader() as revision:yield revision
            supplier.source_identity = actual.ledger.store.authenticated_identity
            supplier.expected_projection_identity = actual.ledger._projection_identity
            registry = default_registry(actual.projection, today="2021-04-01", instrument_scope=supplier)
            class Compiler:
                def compile(self, context):return CompilationResult(actual.program,actual.validation,(),None)
            runtime = AnswerProgramRuntime(Compiler(),ProgramExecutor(registry,AnswerResourcePolicy()),DeterministicBinder(registry,"en-US"))
            other = runtime.answer(QuestionContext(actual.wire["question"],today="2021-04-01",locale="en-US"))
            execution = other.execution
            first = next(item for item in actual.answered.execution.transcript if item.tool == "read_account_balance_report")
            second = next(item for item in execution.transcript if item.tool == first.tool)
            assert second.ok and first.data["source_fields"] == second.data["source_fields"]
            assert other.result._selected_report_origin is not actual.answered.result._selected_report_origin
    assert numerical_receipts(SimpleNamespace(result=actual.answered.result,question=actual.wire["question"],
        instrument_execution=execution),actual.projection,"different-execution") == ([], {})


def test_delivered_selected_receipt_survives_saved_answer_reopen_without_resealing(tmp_path, monkeypatch):
    from viva.ledger import Ledger
    from viva.ledger.events import conversation_turn_opened, conversation_turn_settled
    from viva.surface.conversation import timeline
    import viva.tools.account_balances as adapter
    actual = _actual_selected_wire(tmp_path, component_padding=317)
    saved = json.loads(json.dumps(actual.wire))
    assert len(saved["numerical_receipts"]) == 1
    path = actual.ledger.store.path
    actual.ledger.append(conversation_turn_opened("selected-seven","ask",saved["question"],"2021-04-01"))
    actual.ledger.append(conversation_turn_settled("selected-seven","completed",saved["text"],"2021-04-01",answer=saved))
    producer = next(item for item in actual.answered.execution.transcript if item.tool == "read_account_balance_report")
    origin = actual.answered.result._selected_report_origin
    reference = weakref.ref(producer)
    del producer, actual
    gc.collect()
    assert reference() is None and origin.result() is None
    def no_reseal(*args, **kwargs):raise AssertionError("Saved receipt must not be reissued")
    monkeypatch.setattr(adapter,"receipt_provenance",no_reseal)
    reopened = Ledger.open(path,"synthetic-passphrase")
    loaded = timeline(reopened.projection(), {})["turns"][0]["answer"]
    assert loaded["numerical_receipts"] == saved["numerical_receipts"]
    for before, after in zip(saved["figures"], loaded["figures"]):
        for field in ("value","currency","quantity","dated","grade","subject","record_ids","evidence_links","receipt_ids"):
            assert after[field] == before[field]


def test_actual_session_turn_surface_preserves_selected_origin_full_wire_and_saved_receipt(tmp_path, monkeypatch):
    from viva.session import Turn
    from viva.tools.account_balances import complete_bytes
    from viva.ledger import Ledger
    from viva.ledger.events import conversation_turn_opened, conversation_turn_settled
    from viva.surface.conversation import timeline
    import viva.tools.account_balances as adapter
    actual = _actual_selected_wire(tmp_path, component_padding=317, session_mode=True)
    turn = actual.normal_turn
    assert isinstance(turn, Turn)
    assert turn.result._selected_report_origin.run_token is turn.instrument_execution.graph.ground.instrument_token
    assert turn.result.status == "partial" and len(actual.wire["figures"]) == 7
    assert len(actual.wire["numerical_receipts"]) == 1
    producer = next(item for item in turn.instrument_execution.transcript if item.tool == "read_account_balance_report")
    assert producer.ok and complete_bytes(producer) == 49_985
    assert producer.data["trace"]["authority_invocations"] == 14
    for fig in actual.wire["figures"]:
        assert fig["receipt_ids"] and fig["evidence_links"]
    assert all({int(link["page"]) for link in fig["evidence_links"]} == {2,4}
        for fig in actual.wire["figures"] if len(fig["record_ids"]) == 2)
    saved = json.loads(json.dumps(actual.wire))
    path = actual.ledger.store.path
    actual.ledger.append(conversation_turn_opened("session-selected","ask",saved["question"],"2021-04-01"))
    actual.ledger.append(conversation_turn_settled("session-selected","completed",saved["text"],"2021-04-01",answer=saved))
    del producer, turn, actual
    gc.collect()
    def no_reseal(*args,**kwargs):raise AssertionError("Session saved receipt must not be reissued")
    monkeypatch.setattr(adapter,"receipt_provenance",no_reseal)
    loaded = timeline(Ledger.open(path,"synthetic-passphrase").projection(),{})["turns"][0]["answer"]
    assert loaded["numerical_receipts"] == saved["numerical_receipts"]
    for original,restored in zip(saved["figures"],loaded["figures"]):
        for field in ("value","quantity","currency","dated","grade","record_ids","receipt_ids","evidence_links"):
            assert restored[field] == original[field]
