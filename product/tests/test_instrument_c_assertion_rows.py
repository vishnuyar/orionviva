import copy
import pytest
from dataclasses import replace
from types import SimpleNamespace
from time import monotonic
from viva.read_store import ReadStore
from viva.tools import default_registry
from viva.answer_program import CapabilityManifest,ProgramValidator,ProgramExecutor,DeterministicBinder,AnswerResourcePolicy
from viva.answer_program.schema import AnswerProgram
from viva.ledger.instruments import reference_accounts
from test_instrument_projector_b import setup,ingest,mortgage
from test_instrument_contracts import printed
from test_instrument_c_binding import program

def test_multiple_source_dates_references_and_properties_use_closed_authenticated_rows(tmp_path):
    raw,ledger=setup(tmp_path);f=mortgage();second=copy.deepcopy(f["escrow"]["movements"][1]);second.update(reference=printed("TAX-B"),dated=printed("2021-01-25"));f["escrow"]["movements"].append(second);f["escrow"]["closing"]=printed("100")
    ingest(raw,ledger,"tax-source",f,"mortgage_statement");account=reference_accounts(ledger.projection(),"ESCROW-A")[0]
    with ReadStore.create(tmp_path/"reads","synthetic-passphrase") as store:
        store.synchronize(ledger.store);registry=default_registry(ledger.projection(),instrument_scope=store.open_reader);manifest=CapabilityManifest.from_registry(registry)
        args={"view":"tax_payments","account":account,"currency":"USD","from":"2021-01-01","to":"2021-01-31","grouping":"none"}
        with registry.instrument_runtime.execution(monotonic()+2):
            read=registry.call("read_instrument_details",args)
        assert read.ok and len([a for a in read.instrument_assertions if a["claim"]=="tax_payment_date"])==2
        data=program(manifest,account,["tax_payment_date","tax_payment_reference","property_identity"]).to_dict();data["nodes"][0]["args"]=args
        for clause,binding in zip(data["shape"]["clauses"],data["bindings"]):
            clause["slots"][0]["type"]="rows";binding["selector"]["cardinality"]="all"
        p=AnswerProgram.from_dict(data);validated=ProgramValidator(manifest,AnswerResourcePolicy()).validate(p)
        assert validated.ok,validated.defects
        execution=ProgramExecutor(registry,AnswerResourcePolicy()).execute(p,"Show the actual tax payment dates, references and property source evidence.")
        answer=DeterministicBinder(registry,"en-US").bind(p,execution).result
        assert answer.answered and "2021-01-20" in answer.text and "2021-01-25" in answer.text and "TAX-A" in answer.text and "TAX-B" in answer.text
        assert all(a["anchors"] and a["observation_ids"] and a["written"] for a in answer.source_assertions)
        assert {a["claim"] for a in answer.source_assertions}=={"tax_payment_date","tax_payment_reference","property_identity"}
        by_record={}
        for receipt in answer.source_assertions:
            assert receipt["record_association"]
            by_record.setdefault(receipt["record_association"],{})[receipt["claim"]]=receipt["value"]
        assert {(r["tax_payment_date"],r["tax_payment_reference"],r["property_identity"]) for r in by_record.values()}=={("2021-01-20","TAX-A","PROPERTY-A"),("2021-01-25","TAX-B","PROPERTY-A")}
        from viva.tools.runner_binding import _bound
        ground=execution.graph.ground;key=next(k for k,g in ground.instrument_assertion_groups.items() if g.claim=="tax_payment_date")
        group=ground.instrument_assertion_groups[key];slot=SimpleNamespace(type="rows",name="dates",quantity="",scope=())
        for changed in (replace(group,run_token=object()),replace(group,claim="deposit_maturity"),replace(group,account="another-account")):
            ground.instrument_assertion_groups[key]=changed
            assert _bound(slot,{"instrument_date":key},ground,"en-US")[1]=="instrument_authority_required"
        ground.instrument_assertion_groups[key]=group
        aid=group.assertion_ids[0];original=ground.instrument_assertions[aid]
        ground.instrument_assertions[aid]=dict(original)
        assert _bound(slot,{"instrument_date":key},ground,"en-US")[1]=="instrument_authority_required"
        ground.instrument_assertions[aid]=original
        assert _bound(slot,{"instrument_date":key},ground,"en-US")[0] is not None



def test_source_row_and_complete_group_byte_bounds_refuse_without_truncation():
    from viva.instrument_evidence import SourceAssertionGroup,_attest_assertion
    from viva.tools.runner import _Ground
    from viva.tools.runner_binding import _bound
    token=object();ground=_Ground(question="Source evidence");ground.instrument_token=token
    def receipt(i,anchors):
        value={"id":"i"+str(i),"receipt_id":"receipt"+str(i),"claim":"property_identity","value_type":"literal_text","value":"X"*240,"account":"account","effective_date":"2021-01-31","disposition":"accepted","grade":"corroborated",
            "anchors":[{"anchor_id":"anchor"+str(n),"document_id":format(n,"064x"),"page":1} for n in range(anchors)],"anchor_ids":tuple("anchor"+str(n) for n in range(anchors)),"observation_ids":["observation"],"component_ids":["escrow_balance"]}
        return _attest_assertion(value,run_token=token)
    ground.instrument_assertions["i0"]=receipt(0,30)
    ground.instrument_assertion_groups["group"]=SourceAssertionGroup(("i0",),"property_identity","account","instrument_text",token)
    slot=SimpleNamespace(type="rows",name="source",quantity="",scope=())
    assert _bound(slot,{"instrument_text":"group"},ground,"en-US")[1]=="resource_limit"
    ground.instrument_assertions={"i"+str(i):receipt(i,17) for i in range(40)}
    ground.instrument_assertion_groups["group"]=SourceAssertionGroup(tuple(ground.instrument_assertions),"property_identity","account","instrument_text",token)
    value,tag,_=_bound(slot,{"instrument_text":"group"},ground,"en-US")
    assert value is None and tag=="resource_limit"
    with pytest.raises(ValueError):SourceAssertionGroup(tuple("id"+str(i) for i in range(81)),"property_identity","account","instrument_text",token)
