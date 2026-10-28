from dataclasses import replace
import pytest
from test_instrument_c_continuation import opened,actions,allocation_step,target_step,Q029
from test_instrument_allocation_authority import snapshot

def extra_plan(vault):
    from viva.ledger.events import account_opened,document_captured,closing_balance_observed,position_observed,Provenance
    from viva.ledger.instruments import append_change
    from viva.ingest.instrument_observations import ObservationChange,ObservationKind,Operation
    from viva.ingest.instrument_contracts import Source,SourcedDate,SourcedText,PositionClassification,Exposure,Vehicle
    ledger=vault.ledger;doc="other-plan-source";source=Source(doc,1)
    ledger.append(account_opened("OTHER-PLAN","investment","Old retirement plan","USD","2025-01-01"));ledger.append(document_captured(doc,"old-plan.pdf",1,"retirement_statement",1,"2025-12-31"));ledger.append(closing_balance_observed("OTHER-PLAN","10","2025-12-31",Provenance(doc,1)))
    ledger.append(position_observed("OTHER-PLAN","bond-fund","1","90","USD","2025-12-31",provenance=Provenance(doc,1)))
    append_change(ledger,ObservationChange(doc,"OTHER-PLAN|bond-fund",ObservationKind.POSITION_CLASSIFICATION,SourcedDate("2025-12-31",source),Operation.CREATE,source,PositionClassification(SourcedText("bond-fund",source),Exposure.BOND,Vehicle.MUTUAL_FUND,source,source)))

def test_last_explicit_delivered_allocation_focus_supersedes_other_accounts_without_prose_inference(opened):
    extra_plan(opened);other=allocation_step();other[1]["account_phrase"]="OTHER-PLAN";other[2]["account_phrase"]={"source":"question","quote":"OTHER-PLAN","derivation":"catalog_selection"};other[3][:]=["allocation_exposure_bond_weight"]
    bridge=actions(opened,[other,allocation_step(),target_step()])
    assert bridge.ask({"question":"Show OTHER-PLAN exposure allocation as of 2025-12-31","context_mode":"new_question"})["kind"]=="completed"
    last=bridge.ask({"question":"Show PLAN exposure allocation as of 2025-12-31","context_mode":"follow_up"})
    assert last["kind"]=="completed"
    result=bridge.ask({"question":Q029,"context_mode":"follow_up"})
    assert result["kind"]=="completed",result
    assert next(f for f in result["state"]["figures"] if f["quantity"]=="allocation_percentage_points")["value"]=="-10"

@pytest.mark.parametrize("race",["financial_source","context_reset"])
def test_source_or_context_change_between_binding_and_durable_delivery_refuses(opened,monkeypatch,race):
    import viva.surface.conversation as view
    original=view.conversation
    bridge=actions(opened,[allocation_step()])
    def changed(*args,**kwargs):
        result=original(*args,**kwargs)
        if race=="financial_source":snapshot(opened.ledger,"concurrent-correction",bond="61",equity="30",cash="10")
        else:bridge._instrument_context.reset()
        return result
    monkeypatch.setattr(view,"conversation",changed)
    result=bridge.ask({"question":"Show PLAN exposure allocation as of 2025-12-31","context_mode":"new_question"})
    assert result["kind"]=="refused",result
    assert not result["state"].get("figures") and not result["state"].get("allocation_selection_manifest")
    assert not bridge._instrument_context.registry.eligible_ids()
    assert opened.ledger.projection().conversation_turns()[-1]["outcome"]=="refused"
