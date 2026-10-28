from time import monotonic
import pytest
from viva.read_store import ReadStore
from viva.tools import default_registry
from viva.answer_program import CapabilityManifest,ProgramExecutor,AnswerResourcePolicy,DeterministicBinder
from viva.tools.runner import _Ground
from test_instrument_c_binding import fixture,program

def test_foreign_run_cached_tool_receipt_refuses_at_real_program_stamping(tmp_path):
    ledger,account=fixture(tmp_path)
    with ReadStore.create(tmp_path/"reads","synthetic-passphrase") as store:
        store.synchronize(ledger.store);registry=default_registry(ledger.projection(),instrument_scope=store.open_reader)
        with registry.instrument_runtime.execution(monotonic()+2):
            cached=registry.call("read_instrument_details",{"view":"terms","account":account,"currency":"USD","as_of":"2021-01-31"})
        registry._specs["read_instrument_details"].fn=lambda _:cached
        p=program(CapabilityManifest.from_registry(registry),account,["deposit_contract_principal"])
        result=ProgramExecutor(registry,AnswerResourcePolicy()).execute(p,"What principal?")
        assert not result.graph.book and result.transcript[0].refusal=="instrument_authority_required"
        assert not DeterministicBinder(registry,"en-US").bind(p,result).result.answered

def test_assertion_preflight_failure_never_leaves_partial_current_run_evidence(tmp_path):
    ledger,account=fixture(tmp_path)
    with ReadStore.create(tmp_path/"reads","synthetic-passphrase") as store:
        store.synchronize(ledger.store);registry=default_registry(ledger.projection(),instrument_scope=store.open_reader)
        with registry.instrument_runtime.execution(monotonic()+2):
            result=registry.call("read_instrument_details",{"view":"terms","account":account,"currency":"USD","as_of":"2021-01-31"})
            assert len(result.instrument_assertions)>1
            result.instrument_assertions[1]["value"]="changed after acceptance"
            ground=_Ground(question="Source terms");ground.instrument_token=registry.instrument_runtime.run_token
            with pytest.raises(ValueError,match="untrusted"):ground.stamp(result)
            assert not ground.instrument_assertions and not ground.instrument_premises and not ground.book
