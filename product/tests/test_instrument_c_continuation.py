from types import SimpleNamespace
import pytest
from viva.vault import Vault
from viva.ledger.events import account_opened,read_recorded
from viva.session import Session
from viva.tools import default_registry
from viva.instrument_runtime import vault_revision_supplier
from viva.desktop_bridge.conversation_actions import ConversationActions
from viva.answer_program.intents import SemanticFamilyRegistry,SEMANTIC_REQUEST_VERSION
from viva.answer_program.compiler import CompilationResult,CompileExchange
from test_instrument_allocation_authority import snapshot

Q029="For the active retirement plan from the last allocation answer, what is the percentage-point difference between actual bond allocation and the 70% target at December 2025? Retain that account and date."

class SourceCompiler:
    def __init__(self,validator,manifest,steps):self.validator=validator;self.manifest=manifest;self.steps=steps
    def set_entity_catalog(self,catalog):self.families=SemanticFamilyRegistry(catalog)
    def set_instrument_currency_resolver(self,resolver):self.families._currency_resolver=resolver
    def set_instrument_context(self,context):self.families.instrument_context=context
    def compile(self,context):
        family,params,sources,claims=self.steps.pop(0)
        raw={"request_version":SEMANTIC_REQUEST_VERSION,"outcome":"request","catalog_digest":self.families.catalog_digest,"entity_catalog_digest":self.families.entity_catalog_digest,"family":family,"parameters":params,"parameter_sources":sources,"requested_claims":claims}
        out=self.families.parse(raw,context);program=self.families.lower(out,self.manifest)
        return CompilationResult(program,self.validator.validate(program),(CompileExchange("synthetic-local",{"question":context.question},{"family":family}),),out)

def source(quote,derivation="verbatim"):return {"source":"question","quote":quote,"derivation":derivation}
def allocation_step():return ("instrument_allocation",{"account_phrase":"PLAN","as_of":"2025-12-31","axis":"exposure"},{"account_phrase":source("PLAN","catalog_selection"),"as_of":source("2025-12-31"),"axis":source("exposure")},["allocation_exposure_bond_weight","allocation_exposure_equity_weight","allocation_total_value"])
def target_step():return ("instrument_allocation_target",{"exposure":"bond","target_percent":"70","as_of":"2025-12-31"},{"exposure":source("bond"),"target_percent":source("the 70% target"),"as_of":source("December 2025","calendar_month_end")},["actual_allocation","user_target","percentage_point_difference"])

@pytest.fixture
def opened(tmp_path,monkeypatch):
    from viva import env
    for key,name in [("HOME","home"),("MERCHANTCORE_HOME","merchant"),("VIVA_PROFILES","profiles")]:
        path=tmp_path/name;path.mkdir();monkeypatch.setenv(key,str(path))
    monkeypatch.setattr(env,"CONFIG_HOME",tmp_path/"config")
    empty=tmp_path/"empty.env";empty.write_text("");monkeypatch.setenv("VIVA_ENV_FILE",str(empty));monkeypatch.setenv("VIVA_CATALOG",str(tmp_path/"merchant/catalog.json"))
    vault=Vault.open(tmp_path/"synthetic-vault","synthetic-passphrase")
    vault.ledger.append(account_opened("PLAN","investment","RET-C","USD","2025-01-01"))
    import io
    from reportlab.pdfgen import canvas
    output=io.BytesIO();pdf=canvas.Canvas(output);pdf.drawString(72,720,"Synthetic retirement source: bonds 60, equity 30, cash 10, USD, December 31 2025.");pdf.save()
    doc=vault.raw.put(output.getvalue())
    snapshot(vault.ledger,doc,bond="60",equity="30",cash="10")
    assert vault.wait_for_read_store(timeout=2)
    yield vault
    vault.close()

def actions(vault,steps):
    bridge=ConversationActions(vault)
    def opened(mode,turn_id):
        def factory(v,m,p):return SourceCompiler(v,m,steps)
        return Session(default_registry(vault.ledger.projection(),"en-US",instrument_scope=vault_revision_supplier(vault)),factory,ledger=vault.ledger,locale="en-US")
    bridge._opened=opened
    return bridge

def test_real_opened_bridge_delivery_context_target_signed_answer_and_anchored_reload(opened):
    bridge=actions(opened,[allocation_step(),target_step()])
    first=bridge.ask({"question":"Show PLAN exposure allocation as of 2025-12-31","context_mode":"new_question"})
    assert first["kind"]=="completed",first
    assert first["state"]["continuation_eligible"] and len(first["state"]["allocation_selection_ids"])==1
    row=opened.ledger.projection().conversation_turns()[-1]
    anchor={"version":"allocation-continuation-v1","turn_id":row["turn_id"],"answer_id":first["state"]["answer_id"]}
    answer=bridge.ask({"question":Q029,"context_mode":"follow_up"})
    assert answer["kind"]=="completed",answer
    assert "60%" in answer["state"]["text"] and "70%" in answer["state"]["text"] and "-10 percentage points" in answer["state"]["text"]
    point=next(f for f in answer["state"]["figures"] if f.get("quantity")=="allocation_percentage_points")
    assert point["kind"]=="hypothetical" and not point["grade"]
    assert answer["state"]["target_premises"][0]["kind"]=="user_stated"
    import json
    from pathlib import Path
    Path("/private/tmp/instrument-c-exact-negative-response.json").write_text(json.dumps(answer,indent=2)+"\n")
    replacement=actions(opened,[target_step(),target_step()])
    recovered=replacement.ask({"question":Q029,"context_mode":"follow_up","continuation_recovery":anchor})
    assert recovered["kind"]=="completed",recovered
    ids=replacement._instrument_context.registry.eligible_ids()
    replacement._instrument_context.recover(__import__("viva.allocation_continuation",fromlist=["RecoveryAnchor"]).RecoveryAnchor.from_dict(anchor))
    assert replacement._instrument_context.registry.eligible_ids()==ids

def test_absent_anchor_does_not_reconstruct_saved_selection_and_new_question_resets(opened):
    bridge=actions(opened,[allocation_step()]);bridge.ask({"question":"Show PLAN exposure allocation as of 2025-12-31","context_mode":"new_question"})
    replacement=actions(opened,[target_step()])
    from viva.answer_program.schema import ContractError
    refused=replacement.ask({"question":Q029,"context_mode":"follow_up"})
    assert refused["kind"]=="refused" and refused["state"]["status"]=="needs_clarification"
    assert not replacement._instrument_context.registry.eligible_ids()

def test_recovery_rejects_mismatched_anchor_and_changed_snapshot(opened):
    bridge=actions(opened,[allocation_step()]);first=bridge.ask({"question":"Show PLAN exposure allocation as of 2025-12-31","context_mode":"new_question"})
    row=opened.ledger.projection().conversation_turns()[-1]
    anchor={"version":"allocation-continuation-v1","turn_id":row["turn_id"],"answer_id":first["state"]["answer_id"]}
    other=actions(opened,[])
    bad=other.ask({"question":Q029,"context_mode":"follow_up","continuation_recovery":{**anchor,"turn_id":"other-turn"}})
    assert bad["kind"]=="refused" and bad["reason"]=="allocation_recovery_unavailable"
    snapshot(opened.ledger,"conflicting-new-row",bond="61",equity="30",cash="10")
    changed=other.ask({"question":Q029,"context_mode":"follow_up","continuation_recovery":anchor})
    assert changed["kind"]=="refused" and changed["reason"]=="allocation_recovery_unavailable"


def test_public_ret_c_exact_values_flow_through_real_delivery_and_recovery(opened):
    from viva.ledger.events import position_observed,document_captured,closing_balance_observed,Provenance
    from viva.ledger.instruments import append_change
    from viva.ingest.instrument_observations import ObservationChange,ObservationKind,Operation
    from viva.ingest.instrument_contracts import Source,SourcedText,SourcedDate,PositionClassification,Exposure,Vehicle
    opened.ledger.append(account_opened("RET-C","investment","Current retirement plan","USD","2025-01-01"))
    import io
    from reportlab.pdfgen import canvas
    output=io.BytesIO();pdf=canvas.Canvas(output);pdf.drawString(72,720,"Synthetic RET-C December 2025: bonds USD164129.58; equity USD75983.30; cash USD0; total USD240112.88.");pdf.save()
    blob=output.getvalue();doc=opened.raw.put(blob);src=Source(doc,1)
    opened.ledger.append(document_captured(doc,"ret-c.pdf",100,"retirement_statement",1,"2025-12-31"))
    opened.ledger.append(closing_balance_observed("RET-C","0","2025-12-31",Provenance(doc,1)))
    for instrument,value,exposure in [("bond-holding","164129.58",Exposure.BOND),("equity-holding","75983.30",Exposure.EQUITY)]:
        opened.ledger.append(position_observed("RET-C",instrument,"1",value,"USD","2025-12-31",provenance=Provenance(doc,1)))
        append_change(opened.ledger,ObservationChange(doc+instrument,"RET-C|"+instrument,ObservationKind.POSITION_CLASSIFICATION,SourcedDate("2025-12-31",src),Operation.CREATE,src,PositionClassification(SourcedText(instrument,src),exposure,Vehicle.MUTUAL_FUND,src,src)))
    first_step=allocation_step();first_step[1]["account_phrase"]="RET-C";first_step[2]["account_phrase"]=source("RET-C","catalog_selection")
    bridge=actions(opened,[first_step,target_step()])
    first=bridge.ask({"question":"Show RET-C exposure allocation as of 2025-12-31","context_mode":"new_question"})
    assert first["kind"]=="completed",first
    answer=bridge.ask({"question":Q029,"context_mode":"follow_up"})
    assert answer["kind"]=="completed",answer
    point=next(f for f in answer["state"]["figures"] if f["quantity"]=="allocation_percentage_points")
    actual=next(f for f in answer["state"]["figures"] if f["quantity"]=="ratio_of_balance")
    assert point["value"]=="-1.64482472" and point["grade"]=="" and point["kind"]=="hypothetical"
    assert actual["value"]=="0.6835517528255877" and actual["grade"] and actual["kind"]=="financial"
    assert "about -1.64482472 percentage points" in answer["state"]["text"] and "70%" in answer["state"]["target_premises"][0]["written"]
    receipt=answer["state"]["numerical_receipts"][0]
    assert receipt["premises"][0]["quote"]=="the 70% target"
    context={item["label"]:item["value"] for item in receipt["context"]}
    assert context["Accepted exposure market-value numerator"]=="164129.58" and context["Accepted cash-inclusive market-value denominator"]=="240112.88"
    assert "HALF_EVEN" in context["Arithmetic convention"]
    import json
    from pathlib import Path
    Path("/private/tmp/instrument-c-public-ret-c-response.json").write_text(json.dumps(answer,indent=2)+"\n")
    assert any(e.event_type=="ReadRecorded" and e.body.get("phase")=="speak" for e in opened.ledger.store.events())


def test_real_export_restore_recovers_anchor_with_fresh_vault_and_session_handles(opened,tmp_path):
    from viva.vault_transfer import export_vault,restore_vault
    bridge=actions(opened,[allocation_step()])
    first=bridge.ask({"question":"Show PLAN exposure allocation as of 2025-12-31","context_mode":"new_question"})
    assert first["kind"]=="completed" and first["state"]["continuation_eligible"]
    turn=opened.ledger.projection().conversation_turns()[-1]
    anchor={"version":"allocation-continuation-v1","turn_id":turn["turn_id"],"answer_id":first["state"]["answer_id"]}
    old_id=first["state"]["allocation_selection_ids"][0]
    archive=tmp_path/"synthetic.orionvault";export_vault(opened.directory,archive)
    result=restore_vault(archive,tmp_path/"restored-vault","synthetic-passphrase")
    assert result.chain_intact and result.blobs_readable and result.blob_count==1
    restored=Vault.open(tmp_path/"restored-vault","synthetic-passphrase",create=False)
    try:
        new=actions(restored,[target_step()])
        assert new._instrument_context.registry.vault_id!=bridge._instrument_context.registry.vault_id
        with pytest.raises(ValueError):new._instrument_context.registry.resolve(old_id,vault_id=new._instrument_context.registry.vault_id,session_id=new._instrument_context.registry.session_id,validate=lambda _:True)
        answer=new.ask({"question":Q029,"context_mode":"follow_up","continuation_recovery":anchor})
        assert answer["kind"]=="completed",answer
        assert "-10 percentage points" in answer["state"]["text"]
        assert old_id not in new._instrument_context.registry.eligible_ids()
    finally:restored.close()
