"""Saved classifier evidence supplies routing metadata without changing source claims."""
import copy,json
from dataclasses import replace
import pytest
from viva.ledger import LedgerProjection
from viva.ledger.events import document_captured,read_recorded,model_extraction_response_recorded
from viva.extraction_responses import response_body
from viva.ledger.projection.coverage import classified_claim


def capture(kind='unknown'):
    return document_captured('public-doc','public.pdf',1,kind,.4,'2026-01-01')


def classify(kind='pay_stub', confidence=.9, **kwargs):
    return read_recorded('public-doc','public-model','public-prompt','text+image',
        json.dumps({'doc_type':kind,'doc_type_confidence':confidence}),0,0,0,
        kwargs.pop('parse_ok',True),kwargs.pop('parse_error',None),'2026-01-01',
        phase=kwargs.pop('phase','classify'),**kwargs)


def receipt(attempt=0, **changes):
    body=response_body('public-doc','public-extraction','classify',0,attempt,
        'openai_compatible','public-model','public-prompt','text+image',200,b'{}')
    body.update(changes)
    return model_extraction_response_recorded(body,'2026-01-01')


def scoped(links, **changes):
    event=classify(transport_receipt_ids=list(links),transport_complete=True,
                   extraction_id='public-extraction',phase_attempt=0)
    return replace(event,body={**event.body,**changes})


@pytest.mark.parametrize('kind',['checking_statement','pay_stub','brokerage_statement','utility_bill'])
def test_saved_success_recovers_type_without_certifying_read(kind):
    events=[capture(),classify(kind)]
    before=copy.deepcopy([event.to_dict() for event in events])
    projection=LedgerProjection(events)
    assert projection.captured_docs()=={'public-doc':kind}
    assert projection.read_parsed_docs()==set() and projection.posted_doc_ids()==set()
    assert projection._core._captured=={'public-doc':'unknown'}
    assert [event.to_dict() for event in events]==before


@pytest.mark.parametrize('changes',[
    {'parse_ok':False},{'parse_error':'failed'},{'phase':'extract'},
    {'response_text':'garbage'},{'response_text':'{"doc_type":"unknown"}'},
    {'response_text':'{"doc_type":""}'},{'acquisition':{}},
    {'response_text':'{"doc_type":"mortgage_statement","doc_type_confidence":2}'},
    {'response_text':'{"doc_type":"mortgage_statement","doc_type_confidence":"NaN"}'},
    {'response_text':'{"doc_type":"mortgage_statement","doc_type_confidence":"Infinity"}'},
])
def test_ineligible_claim_keeps_raw_unknown(changes):
    event=classify();event=replace(event,body={**event.body,**changes})
    assert classified_claim(event,[]) is None
    # Explicit local acquisition validity belongs to its own producer, not classifier eligibility.
    if 'acquisition' not in changes:
        assert LedgerProjection([capture(),event]).captured_docs()=={'public-doc':'unknown'}


def test_known_capture_remains_authoritative_with_conflicting_classifier():
    assert LedgerProjection([capture('checking_statement'),classify('pay_stub')]).captured_docs()=={'public-doc':'checking_statement'}


def test_agreement_ambiguity_and_prefix_replay_do_not_pick_a_winner():
    events=[capture(),classify('pay_stub'),classify('pay_stub')]
    before=copy.deepcopy([event.to_dict() for event in events])
    assert LedgerProjection(events).captured_docs()=={'public-doc':'pay_stub'}
    extended=[*events,classify('brokerage_statement')]
    assert LedgerProjection(extended).captured_docs()=={'public-doc':'unknown'}
    assert LedgerProjection(events).captured_docs()=={'public-doc':'pay_stub'}
    assert [event.to_dict() for event in events]==before
    assert LedgerProjection([*events,classify('unknown'),classify(parse_ok=False)]).captured_docs()=={'public-doc':'pay_stub'}


def test_instrument_alias_canonicalization_agrees_with_live_reader(monkeypatch):
    from viva.ingest import registry,reader
    profile=registry.profile_for('mortgage_statement')
    monkeypatch.setitem(registry._INDEX,'public_instrument_alias',profile)
    from viva.ledger.projection.coverage import canonical_classification
    assert canonical_classification('public_instrument_alias',.8)==('mortgage_statement',.8,None)
    assert reader._peek_classification('{"doc_type":"PUBLIC_INSTRUMENT_ALIAS","doc_type_confidence":0.8}')==('public_instrument_alias',.8)
    assert LedgerProjection([capture(),classify('public_instrument_alias'),classify('mortgage_statement')]).captured_docs()=={'public-doc':'mortgage_statement'}


def test_scoped_complete_empty_population_and_unscoped_are_both_eligible():
    assert classified_claim(classify(),[])[0]=='pay_stub'
    assert classified_claim(scoped([]),[])[0]=='pay_stub'
    raw=receipt()
    assert classified_claim(scoped([raw.event_id]),[raw])[0]=='pay_stub'
    assert classified_claim(scoped([]),[raw]) is None
    assert classified_claim(scoped([raw.event_id]),[]) is None


@pytest.mark.parametrize('field,value',[
    ('doc_id','other'),('extraction_id','other'),('phase_attempt',1),
    ('phase','extract'),('model','other'),('prompt_version','other'),
    ('input_mode','other'),('transport_complete',False),
])
def test_scoped_identity_configuration_and_completion_must_match(field,value):
    raw=receipt()
    assert classified_claim(scoped([raw.event_id],**{field:value}),[raw]) is None


@pytest.mark.parametrize('field',['transport_complete','transport_receipt_ids','extraction_id','phase_attempt'])
def test_partial_scoped_never_falls_back_to_legacy(field):
    event=scoped([]);body=dict(event.body);body.pop(field)
    assert classified_claim(replace(event,body=body),[]) is None


def test_reordered_or_orphaned_receipts_cannot_supply_type():
    first,second=receipt(0),receipt(1)
    assert classified_claim(scoped([first.event_id,second.event_id]),[first,second]) is not None
    assert classified_claim(scoped([second.event_id,first.event_id]),[first,second]) is None
    assert classified_claim(scoped([first.event_id]),[first,second]) is None
    assert classified_claim(scoped([first.event_id,second.event_id]),[second,first]) is None


def test_classification_provenance_keeps_all_agreeing_claims_and_receipts():
    raw=receipt();first=scoped([raw.event_id]);second=classify()
    projection=LedgerProjection([capture(),raw,first,second])
    evidence=projection._core._classified_types['public-doc']
    assert set(evidence)=={first.event_id,second.event_id}
    assert evidence[first.event_id][2]==(raw.event_id,)
    assert evidence[second.event_id][2]==()
    assert projection._core._capture_event_ids['public-doc']
    assert projection._core._classification_revision==(4,second.event_id)


def test_noninstrument_aliases_keep_live_capture_semantics_and_disagree():
    from viva.ledger.projection.coverage import canonical_classification
    assert canonical_classification('pay_slip',.8)==('pay_slip',.8,None)
    assert LedgerProjection([capture(),classify('pay_slip')]).captured_docs()=={'public-doc':'pay_slip'}
    assert LedgerProjection([capture(),classify('pay_slip'),classify('pay_stub')]).captured_docs()=={'public-doc':'unknown'}


def test_account_evidence_and_knowledge_arrival_share_effective_type():
    from types import SimpleNamespace
    from viva.knowledge import _doc_type_seen
    projection=LedgerProjection([capture(),classify('pay_slip')])
    projection._core._acct['Assets:Public']=SimpleNamespace(doc_ids={'public-doc'})
    assert projection.document_types_of('Assets:Public')=={'pay_stub'}
    assert _doc_type_seen(projection,['pay_slip']) is True
    assert _doc_type_seen(projection,['brokerage_statement']) is False


def test_newly_posted_balance_branch_uses_effective_type_without_historical_sync(monkeypatch):
    from types import SimpleNamespace
    from viva import engine,enrich,ingest
    projection=LedgerProjection([capture(),classify('checking_statement')])
    projection._core._posted.add('public-doc')
    vault=SimpleNamespace(ledger=SimpleNamespace(projection=lambda:projection))
    from viva import accounting_intelligence
    monkeypatch.setattr(accounting_intelligence,'interpret_activity',lambda _vault:None)
    calls=[]
    monkeypatch.setattr(enrich,'sync_installed_merchants',lambda _vault,doc:calls.append(('sync',doc)))
    monkeypatch.setattr(enrich,'enrich_live_merchants',lambda _vault:calls.append(('live',)))
    monkeypatch.setattr(ingest,'assign_default_categories',lambda _ledger,doc:calls.append(('categories',doc)))
    engine._finalize_new_documents(vault,set())
    assert calls==[('sync','public-doc'),('categories','public-doc'),('live',)]
    calls.clear();engine._finalize_new_documents(vault,{'public-doc'})
    assert calls==[]


@pytest.mark.parametrize('confidence',[2.0,float('nan'),float('inf')])
def test_rejected_instrument_alias_keeps_live_canonical_capture_type(monkeypatch,confidence):
    from types import SimpleNamespace
    from viva.ingest import reader,registry
    from vivacore.models.base import PageImage,ModelResult
    monkeypatch.setitem(registry._INDEX,'public_instrument_alias',registry.profile_for('mortgage_statement'))
    class Adapter:
        def extract(self,images,prompt):
            text=json.dumps({'doc_type':'public_instrument_alias','doc_type_confidence':confidence})
            return ModelResult(text,'public-model',0,0,0,0,{}, {})
    monkeypatch.setattr(reader,'adapter_for',lambda spec:Adapter())
    seen=[]
    result=reader.read_prepared_statement((PageImage(1,b'public','hash'),),'public',
        'public-doc',SimpleNamespace(model='public-model'),'en-US','USD',
        phase_sink=lambda phase,kind,conf:seen.append((phase.parse_ok,kind,conf)))
    assert result.facts is None
    assert seen[0]==(False,'mortgage_statement',0.0)
    assert result.phases[0].error=='invalid instrument classification confidence'
    assert classified_claim(classify('public_instrument_alias',confidence),[]) is None
