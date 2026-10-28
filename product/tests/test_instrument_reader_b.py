"""Closed instrument proposals use the real two-phase reader and source parser."""
import json
from dataclasses import FrozenInstanceError
from decimal import Decimal

import pytest

from viva.ingest.registry import profile_for, can_project

FAMILIES=['term_deposit_statement','mortgage_statement','refinance_settlement','property_tax_receipt']


@pytest.mark.parametrize('family',FAMILIES)
def test_instrument_profiles_have_distinct_recoverable_prompt_families(family):
    profile=profile_for(family)
    assert profile is not None and profile.identity=='instrument'
    assert can_project(family)
    from viva.ingest.registry import doc_type_for_prompt_version, extraction_prompt_for
    text,version=extraction_prompt_for(family)
    assert doc_type_for_prompt_version(version)==family
    assert text and profile.extract_base.endswith('-base-v2' if family == 'mortgage_statement' else '-base-v1')



def _raw(value, page=1):
    return {'raw':str(value),'page':page}


def _identity(reference):
    return {name:_raw(value) for name,value in [('institution','Synthetic issuer'),
             ('account_reference',reference),('holder','Synthetic holder')]}


def _proposal(family):
    if family=='term_deposit_statement':
        return {'identity':_identity('CD-X'),'subtype':'opening',
                'terms':{'principal':_raw('100'),'opened':_raw('2026-01-01'),
                         'maturity':_raw('2026-12-31'),'rate':_raw('3%'),
                         'rate_basis':'simple_nominal','rate_basis_source':{'page':1},
                         'day_count':'equal_monthly_12','day_count_source':{'page':1},
                         'withdrawal_restriction':_raw('Restricted until sourced redemption')}}
    if family=='mortgage_statement':
        return {'identity':_identity('LOAN-X'),'start':_raw('2026-01-01'),'end':_raw('2026-01-31'),
                'opening_principal':_raw('1000'),'closing_principal':_raw('900'),
                'principal_movements':[{'kind':'principal_reduction','amount':_raw('100'),
                                       'dated':_raw('2026-01-31'),'reference':_raw('PAY-X')}],
                'payments':[{'dated':_raw('2026-01-31'),'reference':_raw('PAY-X'),
                    'principal':_raw('100'),'interest':_raw('200'),'escrow':_raw('300'),
                    'fees':_raw('0'),'total':_raw('600'),'funding_account_reference':_raw('CHECK-X')}],
                'escrow':{'identity':_identity('ESCROW-X'),'opening':_raw('0'),'closing':_raw('300'),
                          'continuity_reference':_raw('ESCROW-X'),
                          'withdrawal_restriction':_raw('Restricted escrow for taxes and insurance'),
                          'movements':[{'kind':'deposit','amount':_raw('300'),
                                        'dated':_raw('2026-01-31'),'reference':_raw('PAY-X')}]}}
    if family=='refinance_settlement':
        return {'dated':_raw('2026-01-31'),'reference':_raw('REFI-X'),
                'old_loan':_identity('LOAN-OLD'),'new_loan':_identity('LOAN-NEW'),
                'old_payoff_principal':_raw('1000'),'new_funded_principal':_raw('1000'),
                'borrower_contribution':_raw('25'),'cash_out':_raw('0'),'financed_costs':_raw('0'),
                'fees':[{'label':_raw('Closing fee'),'amount':_raw('25')}],'total_fees':_raw('25'),
                'fee_payment_reference':_raw('REFI-FEES-X'),'funding_account_reference':_raw('CHECK-X'),
                'fee_payment_date':_raw('2026-01-31')}
    return {'authority':_raw('Synthetic tax authority'),'property_reference':_raw('PROPERTY-X'),
            'tax_year':2026,'tax_year_source':{'page':1},'dated':_raw('2026-01-31'),
            'reference':_raw('TAX-X'),'amount':_raw('50'),'status':'paid','status_source':{'page':1},
            'source_account_reference':_raw('ESCROW-X')}


@pytest.mark.parametrize('family',FAMILIES)
def test_source_wrapper_roundtrip_retains_type_null_sections_and_source_identity(family):
    from viva.ingest.instrument_read import InstrumentReadFacts, parser_for, validate_sources
    facts,error=parser_for(family)(json.dumps(_proposal(family)),'actual-captured-source','en-US','USD')
    assert error is None and facts.doc_id=='actual-captured-source'
    assert facts.doc_type==family and facts.currency=='USD'
    validate_sources(facts.payload,'actual-captured-source',1)
    assert InstrumentReadFacts.from_dict(json.loads(json.dumps(facts.to_dict())))==facts
    assert facts.period_end=='2026-01-01' if family=='term_deposit_statement' else facts.period_end=='2026-01-31'
    if family=='term_deposit_statement':
        assert facts.payload.opening is None and facts.payload.closing is None
        assert facts.payload.start is None and facts.payload.end is None and facts.payload.movements is None
    with pytest.raises(FrozenInstanceError): facts.doc_id='another-source'
    stored=facts.to_dict();stored['doc_id']='foreign-capture'
    with pytest.raises(ValueError): InstrumentReadFacts.from_dict(stored)
    stored=facts.to_dict();stored['extra']='injected'
    with pytest.raises(ValueError): InstrumentReadFacts.from_dict(stored)


@pytest.mark.parametrize('mutation',['foreign_doc_id','boolean_page','unknown_field','nonfinite_amount','duplicate_field'])
def test_closed_source_parser_refuses_injected_or_unsourced_values(mutation):
    from viva.ingest.instrument_read import parser_for
    proposal=_proposal('term_deposit_statement')
    if mutation=='foreign_doc_id':proposal['identity']['holder']['doc_id']='foreign'
    if mutation=='boolean_page':proposal['identity']['holder']['page']=True
    if mutation=='unknown_field':proposal['accepted']=True
    if mutation=='nonfinite_amount':proposal['terms']['principal']['raw']='NaN'
    text=json.dumps(proposal)
    if mutation=='duplicate_field':text=text[:-1]+',"subtype":"maturity"}'
    facts,error=parser_for('term_deposit_statement')(text,'current-capture','en-US','USD')
    assert facts is None and error


@pytest.fixture(scope='module')
def source_pdfs():
    # Four ephemeral unit-test sources, separate from the campaign's 794 PDFs.
    # Each prints its complete synthetic proposal and is rendered by PDFium.
    from io import BytesIO
    import textwrap
    from reportlab.pdfgen import canvas
    out={}
    for family in FAMILIES:
        stream=BytesIO();page=canvas.Canvas(stream,pagesize=(612,792))
        page.setFont('Courier',5)
        for index,line in enumerate(textwrap.wrap(family+' '+json.dumps(_proposal(family)),175)):
            page.drawString(12,780-index*7,line)
        page.save();out[family]=stream.getvalue()
    return out


class _Adapter:
    def __init__(self,family,proposal=None,confidence=.97):
        self.family=family;self.proposal=proposal or _proposal(family);self.confidence=confidence;self.calls=[]
    def extract(self,pages,prompt):
        from vivacore.models.base import ModelResult
        self.calls.append((len(pages),prompt))
        text=(json.dumps({'doc_type':self.family,'doc_type_confidence':self.confidence})
              if len(self.calls)==1 else json.dumps(self.proposal))
        return ModelResult(text=text,resolved_model='synthetic-model',input_tokens=2,output_tokens=3,
                           cost_usd=0.0,latency_s=0.0,request={},response={'usage':{'prompt_tokens':2,'completion_tokens':3}})


def _read(monkeypatch,data,family,doc_id='actual-capture',proposal=None,confidence=.97):
    from types import SimpleNamespace
    from viva.ingest import reader
    adapter=_Adapter(family,proposal,confidence)
    monkeypatch.setattr(reader,'adapter_for',lambda spec:adapter)
    result=reader.read_statement(data,doc_id,SimpleNamespace(model='synthetic-model',json_mode=True),'en-US','USD')
    return result,adapter


@pytest.mark.parametrize('family',FAMILIES)
def test_actual_pdf_two_phase_parser_preserves_frozen_source_proposal(monkeypatch,source_pdfs,family):
    result,adapter=_read(monkeypatch,source_pdfs[family],family)
    assert result.error is None and result.facts is not None
    assert result.facts.doc_type_confidence==.97 and result.facts.doc_id=='actual-capture'
    assert len(adapter.calls)==2 and [count for count,prompt in adapter.calls]==[1,1]
    assert [phase.phase for phase in result.phases]==['classify','extract']
    assert all(phase.parse_ok for phase in result.phases)
    assert result.phases[-1].raw_text==json.dumps(_proposal(family))
    assert result.phases[0].prompt_version.startswith('classify-v3+')


@pytest.mark.parametrize('family',FAMILIES)
def test_actual_rendered_page_bounds_fail_inside_existing_retry(monkeypatch,source_pdfs,family):
    proposal=_proposal(family)
    target=proposal['identity']['holder'] if 'identity' in proposal else proposal['dated']
    target['page']=999
    result,adapter=_read(monkeypatch,source_pdfs[family],family,proposal=proposal)
    assert result.facts is None and result.error
    assert len(adapter.calls)==3
    assert [phase.parse_ok for phase in result.phases]==[True,False,False]
    assert 'outside the captured document' in result.error


def test_nonfinite_classification_cannot_start_instrument_extraction(monkeypatch,source_pdfs):
    result,adapter=_read(monkeypatch,source_pdfs[FAMILIES[0]],FAMILIES[0],confidence=float('nan'))
    assert result.facts is None and result.error
    assert len(adapter.calls)==1 and not result.phases[0].parse_ok


def test_prior_released_reader_prompts_are_byte_exact():
    from pathlib import Path
    import hashlib
    from viva.ingest import prompt_library
    frozen={'classify-v2':'b0068911c228303a','extract-base-v1':'93c67860a6626894',
            'extract-brokerage-base-v3':'49323639a9b48542'}
    # Known prior-release digests are constants, not read from the candidate manifest.
    for name,digest in frozen.items():
        assert hashlib.sha256((prompt_library.PROMPTS/(name+'.txt')).read_bytes()).hexdigest()[:16]==digest


@pytest.mark.parametrize('family',FAMILIES)
def test_stored_extract_recovers_family_with_frame_and_retry_suffixes(family):
    from viva.ingest.registry import extraction_prompt_for,doc_type_for_prompt_version
    from viva.rebuild import _parse
    text,version=extraction_prompt_for(family)
    assert doc_type_for_prompt_version(version+'+untrusted-frame-v1+retry-value-v1')==family
    facts,error=_parse(family,json.dumps(_proposal(family)),'stored-source','en-US','USD')
    assert error is None and facts.doc_type==family and facts.doc_id=='stored-source'
    assert facts.to_dict()['instrument_facts']


def test_ambiguous_stored_extract_profile_fragments_do_not_guess_family():
    from viva.ingest.registry import doc_type_for_prompt_version
    assert doc_type_for_prompt_version('extract:term-deposit-base-v1+term-deposit-v1+mortgage-v1')==''


def _bank_proposal():
    return {'account_ref':'Synthetic checking','account_number':'CHECK-X',
            'institution':'Synthetic issuer','account_names':['Synthetic holder'],
            'source_account_ref':'CHECK-X','source_account_ref_page':1,
            'opening':{'amount_raw':'100','date_raw':'2026-01-01','page':1},
            'closing':{'amount_raw':'110','date_raw':'2026-01-31','page':1},
            'transactions':[{'amount_raw':'10','date_raw':'2026-01-15','description':'Synthetic funding',
                             'balance_effect':'increase','page':1,'source_reference':'LINK-X',
                             'counterparty_reference':'SAVE-X'}]}


@pytest.mark.parametrize('which',['account','transaction'])
def test_balance_reference_pages_use_actual_rendered_bounds(monkeypatch,source_pdfs,which):
    proposal=_bank_proposal()
    if which=='account':proposal['source_account_ref_page']=999
    else:proposal['transactions'][0]['page']=999
    result,adapter=_read(monkeypatch,source_pdfs[FAMILIES[0]],'checking_statement',proposal=proposal)
    assert result.facts is None and 'outside the captured document' in result.error
    assert [phase.parse_ok for phase in result.phases]==[True,False,False]


def test_old_balance_json_needs_no_new_reference_metadata(monkeypatch,source_pdfs):
    proposal=_bank_proposal();proposal.pop('source_account_ref');proposal.pop('source_account_ref_page')
    for row in proposal['transactions']:
        row.pop('source_reference');row.pop('counterparty_reference')
    result,adapter=_read(monkeypatch,source_pdfs[FAMILIES[0]],'checking_statement',proposal=proposal)
    assert result.error is None and result.facts is not None
    assert result.facts.source_account_ref=='' and result.facts.source_account_ref_page is None
    assert result.facts.transactions[0].source_reference==''


def _brokerage_proposal():
    return {'account_ref':'Synthetic investments','account_number':'BROKER-X',
            'institution':'Synthetic issuer','account_names':['Synthetic holder'],
            'as_of_raw':'2026-01-31','cash_raw':'30','total_raw':'100',
            'positions':[{'instrument':'Bond Mutual Fund label','units_raw':'1','market_value_raw':'70',
                'page':1,'classification':{'exposure':'bond','vehicle':'mutual_fund',
                                          'exposure_page':1,'vehicle_page':1}}]}


def test_explicit_brokerage_classification_is_typed_sourced_and_roundtrips(monkeypatch,source_pdfs):
    from viva.ingest.brokerage import PositionFact
    result,adapter=_read(monkeypatch,source_pdfs[FAMILIES[0]],'brokerage_statement',proposal=_brokerage_proposal())
    assert result.error is None and result.facts is not None
    position=result.facts.positions[0]
    assert position.classification.exposure.value=='bond'
    assert position.classification.vehicle.value=='mutual_fund'
    assert position.classification.exposure_source.doc_id=='actual-capture'
    assert position.classification.exposure_source.page==1
    assert PositionFact.from_dict(position.to_dict())==position


@pytest.mark.parametrize('field',['exposure_page','vehicle_page'])
def test_classification_sources_are_bounded_by_actual_document_pages(monkeypatch,source_pdfs,field):
    proposal=_brokerage_proposal();proposal['positions'][0]['classification'][field]=999
    result,adapter=_read(monkeypatch,source_pdfs[FAMILIES[0]],'brokerage_statement',proposal=proposal)
    assert result.facts is None and 'outside the captured document' in result.error
    assert [phase.parse_ok for phase in result.phases]==[True,False,False]


def test_security_name_does_not_create_missing_source_classification(monkeypatch,source_pdfs):
    proposal=_brokerage_proposal();proposal['positions'][0].pop('classification')
    result,adapter=_read(monkeypatch,source_pdfs[FAMILIES[0]],'brokerage_statement',proposal=proposal)
    assert result.error is None and result.facts is not None
    assert result.facts.positions[0].classification is None


def test_stored_family_normalization_keeps_canonical_frozen_metadata():
    from viva.rebuild import _parse
    family='term_deposit_statement'
    facts,error=_parse('  TERM_DEPOSIT_STATEMENT  ',json.dumps(_proposal(family)),'source','en-US','USD')
    assert error is None and facts.doc_type==family


@pytest.mark.parametrize('family',FAMILIES)
def test_real_capture_post_stored_claim_and_rebuild_use_same_source_contract(
        monkeypatch,tmp_path,source_pdfs,family):
    import time
    import socket
    from types import SimpleNamespace
    from viva.vault import Vault
    from viva.ingest import reader, capture_and_ingest, DUPLICATE
    from viva.ingest.instrument_read import InstrumentReadFacts,validate_sources
    from viva.rebuild import rebuild,claims_by_doc,_parse
    from viva import env
    for name,child in [('HOME','home'),('MERCHANTCORE_HOME','merchant'),('VIVA_PROFILES','profiles')]:
        path=tmp_path/child;path.mkdir();monkeypatch.setenv(name,str(path))
    monkeypatch.setattr(env,'CONFIG_HOME',tmp_path/'config')
    empty=tmp_path/'empty.env';empty.write_text('');monkeypatch.setenv('VIVA_ENV_FILE',str(empty))
    monkeypatch.setenv('VIVA_CATALOG',str(tmp_path/'merchant/catalog.json'))
    def denied(*args,**kwargs):pytest.fail('provider/network use is forbidden in source replay test')
    monkeypatch.setattr(socket.socket,'connect',denied)
    monkeypatch.setattr(socket,'create_connection',denied)
    adapter=_Adapter(family);monkeypatch.setattr(reader,'adapter_for',lambda spec:adapter)
    spec=SimpleNamespace(model='synthetic-model',json_mode=True)
    data=source_pdfs[family];root=tmp_path/'source';phrase='synthetic-unit-test'
    vault=Vault.open(root,phrase)
    actual=[]
    def read(data,doc_id):
        result=reader.read_statement(data,doc_id,spec,'en-US','USD')
        actual.append(result.facts)
        return result
    try:
        result=capture_and_ingest(vault.raw,vault.ledger,data,read,
                                  filename=family+'.pdf',captured_at='2026-02-01')
        assert result.doc_type==family and 'no projector' not in result.message.lower()
        assert actual[0] is not None
        events=list(vault.ledger.events())
        captures=[event for event in events if event.event_type=='DocumentCaptured']
        assert len(captures)==1 and captures[0].body['doc_type']==family
        records=[event for event in events if event.event_type=='ReadRecorded']
        assert [record.body['phase'] for record in records]==['classify','extract']
        assert records[-1].body['response_text']==json.dumps(_proposal(family))
        assert vault.raw.get(result.doc_id)==data
        reread,error=_parse(family,records[-1].body['response_text'],result.doc_id,'en-US','USD')
        assert error is None and reread.payload==actual[0].payload
        assert InstrumentReadFacts.from_dict(actual[0].to_dict())==actual[0]
        validate_sources(reread.payload,result.doc_id,1)
        assert any(event.event_type=='InstrumentObservationRecorded' or
                   (event.event_type=='StatementHeld' and 'instrument_facts' in event.body.get('facts',{}))
                   for event in events)
        states=[state for state in vault.ledger.projection().core._instrument_component_states.values()
                if state.doc_id==result.doc_id]
        assert states
        dispositions={item.component:item.disposition.value for state in states for item in state.components}
        if family=='term_deposit_statement':
            assert dispositions['deposit_terms']=='accepted' and dispositions['deposit_balance']=='held'
            assert not [event for event in events if event.event_type in ('OpeningBalanceObserved','ClosingBalanceObserved')]
        if family=='mortgage_statement':
            assert dispositions['principal_balance']=='accepted' and dispositions['payment:PAY-X']=='held'
        assert capture_and_ingest(vault.raw,vault.ledger,data,read,filename='duplicate.pdf').action==DUPLICATE
        assert len(adapter.calls)==2
    finally:vault.close()
    # There is no provider callback available during actual stored-claim replay.
    monkeypatch.setattr(reader,'adapter_for',lambda spec:denied())
    started=time.perf_counter()
    rebuilt=rebuild(root,tmp_path/'rebuilt',phrase,locale='en-US',currency='USD',log=lambda text:None)
    elapsed=time.perf_counter()-started
    with (tmp_path/'rebuild-timing.txt').open('w') as evidence:evidence.write(str(elapsed))
    destination=Vault.open(tmp_path/'rebuilt',phrase,create=False)
    try:
        events=list(destination.ledger.events());claims=claims_by_doc(events)
        stored=claims[result.doc_id]['extract']
        assert stored['response_text']==json.dumps(_proposal(family))
        recovered,error=_parse(family,stored['response_text'],result.doc_id,'en-US','USD')
        assert error is None and recovered.payload==actual[0].payload
        assert any(event.event_type=='InstrumentObservationRecorded' or
                   (event.event_type=='StatementHeld' and 'instrument_facts' in event.body.get('facts',{}))
                   for event in events)
    finally:destination.close()


def test_stored_out_of_range_source_pages_never_heal_during_actual_rebuild(
        monkeypatch,tmp_path,source_pdfs):
    import socket
    from types import SimpleNamespace
    from viva import env
    from viva.vault import Vault
    from viva.ingest import reader,capture_and_ingest
    from viva.rebuild import rebuild,claims_by_doc
    for name,child in [('HOME','home'),('MERCHANTCORE_HOME','merchant'),('VIVA_PROFILES','profiles')]:
        path=tmp_path/child;path.mkdir();monkeypatch.setenv(name,str(path))
    monkeypatch.setattr(env,'CONFIG_HOME',tmp_path/'config')
    empty=tmp_path/'empty.env';empty.write_text('');monkeypatch.setenv('VIVA_ENV_FILE',str(empty))
    monkeypatch.setenv('VIVA_CATALOG',str(tmp_path/'merchant/catalog.json'))
    def denied(*args,**kwargs):pytest.fail('network/provider use forbidden')
    monkeypatch.setattr(socket.socket,'connect',denied);monkeypatch.setattr(socket,'create_connection',denied)
    family=FAMILIES[0];proposal=_proposal(family);proposal['terms']['principal']['page']=999
    adapter=_Adapter(family,proposal);monkeypatch.setattr(reader,'adapter_for',lambda spec:adapter)
    spec=SimpleNamespace(model='synthetic-model',json_mode=True)
    source=Vault.open(tmp_path/'source','synthetic-unit-test')
    try:
        result=capture_and_ingest(source.raw,source.ledger,source_pdfs[family],
            lambda data,doc:reader.read_statement(data,doc,spec,'en-US','USD'),
            filename='out-of-range.pdf',captured_at='2026-02-01')
        assert len(adapter.calls)==3
        events=list(source.ledger.events())
        assert not any(event.event_type=='InstrumentObservationRecorded' for event in events)
        assert claims_by_doc(events)[result.doc_id]['extract']['parse_ok'] is False
    finally:source.close()
    monkeypatch.setattr(reader,'adapter_for',lambda spec:denied())
    rebuild(tmp_path/'source',tmp_path/'rebuilt','synthetic-unit-test',locale='en-US',currency='USD',log=lambda text:None)
    destination=Vault.open(tmp_path/'rebuilt','synthetic-unit-test',create=False)
    try:
        events=list(destination.ledger.events())
        assert not any(event.event_type in ('InstrumentObservationRecorded','OpeningBalanceObserved',
                                             'ClosingBalanceObserved') for event in events)
        assert claims_by_doc(events)[result.doc_id]['extract']['parse_ok'] is False
    finally:destination.close()


@pytest.mark.parametrize('family',FAMILIES)
def test_actual_rebuild_recovers_extract_only_framed_instrument_claim(
        monkeypatch,tmp_path,source_pdfs,family):
    import socket
    from viva import env
    from viva.vault import Vault
    from viva.ingest import reader
    from viva.ingest.registry import extraction_prompt_for
    from viva.ingest.instrument_read import InstrumentReadFacts
    from viva.ledger.events import document_captured,read_recorded
    from viva.rebuild import rebuild,claims_by_doc,_parse
    for name,child in [('HOME','home'),('MERCHANTCORE_HOME','merchant'),('VIVA_PROFILES','profiles')]:
        path=tmp_path/child;path.mkdir();monkeypatch.setenv(name,str(path))
    monkeypatch.setattr(env,'CONFIG_HOME',tmp_path/'config')
    empty=tmp_path/'empty.env';empty.write_text('');monkeypatch.setenv('VIVA_ENV_FILE',str(empty))
    monkeypatch.setenv('VIVA_CATALOG',str(tmp_path/'merchant/catalog.json'))
    def denied(*args,**kwargs):pytest.fail('extract-only recovery must not call providers/network')
    monkeypatch.setattr(socket.socket,'connect',denied);monkeypatch.setattr(socket,'create_connection',denied)
    monkeypatch.setattr(reader,'adapter_for',lambda spec:denied())
    text=json.dumps(_proposal(family))
    # This is an absent-context historical claim, so retain its released v1 contract.
    base=('extract:mortgage-base-v1+mortgage-v1' if family=='mortgage_statement'
          else extraction_prompt_for(family)[1])
    version=base+'+frame-source-test+retry-v1'
    source=Vault.open(tmp_path/'source','synthetic-unit-test')
    try:
        data=source_pdfs[family];doc_id=source.raw.put(data)
        source.ledger.append(document_captured(doc_id,family+'.pdf',len(data),'unknown',0.0,'2026-02-01'))
        source.ledger.append(read_recorded(doc_id,'synthetic-model',version,'vision',text,
            0.0,0,0,False,'prior failed parser','2026-02-01'))
    finally:source.close()
    rebuild(tmp_path/'source',tmp_path/'rebuilt','synthetic-unit-test',locale='en-US',currency='USD',log=lambda text:None)
    destination=Vault.open(tmp_path/'rebuilt','synthetic-unit-test',create=False)
    try:
        events=list(destination.ledger.events())
        capture=next(event for event in events if event.event_type=='DocumentCaptured')
        assert capture.body['doc_type']==family and capture.body['doc_type_confidence']==1.0
        claim=claims_by_doc(events)[doc_id]['extract']
        assert claim['response_text']==text and claim['prompt_version']==version and claim['parse_ok']
        assert any(event.event_type=='InstrumentObservationRecorded' or
                   (event.event_type=='StatementHeld' and 'instrument_facts' in event.body.get('facts',{}))
                   for event in events)
        facts,error=_parse(family,claim['response_text'],doc_id,'en-US','USD')
        assert error is None and InstrumentReadFacts.from_dict(facts.to_dict())==facts
        if family=='term_deposit_statement':
            assert facts.payload.opening is None and facts.payload.closing is None
    finally:destination.close()
