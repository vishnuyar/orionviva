import io,json,textwrap
from contextlib import closing
from decimal import Decimal
from dataclasses import replace
import pytest
from viva.vault import Vault
from viva.ingest.pipeline import capture_and_ingest
from viva.ingest.reader import read_statement,read_with_retry
from viva.ingest.instrument_read import parser_for
from viva.ledger.events import read_recorded
from viva.ledger.instruments import reference_accounts
from test_instrument_projector_b import mortgage
from test_reader_context import response


def pdf(payload):
    """One real rendered synthetic page containing the entire proposed source."""
    from reportlab.pdfgen.canvas import Canvas
    stream=io.BytesIO();canvas=Canvas(stream,pagesize=(800,1100),invariant=True)
    canvas.setFont('Courier',6)
    for ordinal,line in enumerate(textwrap.wrap(json.dumps(payload,ensure_ascii=True),150)):
        canvas.drawString(15,1080-ordinal*9,line)
    canvas.showPage();canvas.save();return stream.getvalue()


def genuine_reader(monkeypatch,payload,kind):
    from viva.ingest import reader
    from types import SimpleNamespace
    class Adapter:
        def __init__(self):self.calls=0
        def extract(self,pages,prompt):
            self.calls+=1
            return response(json.dumps({'doc_type':kind,'doc_type_confidence':1.0}) if self.calls==1 else json.dumps(payload))
    monkeypatch.setattr(reader,'adapter_for',lambda spec:Adapter())
    return lambda data,doc:read_statement(data,doc,SimpleNamespace(model='configured',json_mode=True),'en-US','USD')


def cash_payload():
    return {'doc_type':'checking_statement','doc_type_confidence':1,
        'institution':'Fixture Bank','account_ref':'Fixture Checking','account_names':['Synthetic Person'],
        'source_account_ref':'CHECK-A','source_account_ref_page':1,
        'opening':{'amount_raw':'2000','date_raw':'2021-01-01','page':1},
        'closing':{'amount_raw':'1400','date_raw':'2021-01-31','page':1},
        'transactions':[{'amount_raw':'600','balance_effect':'decrease','date_raw':'2021-01-15','page':1,
            'description':'Printed source payment','source_reference':'PAY-A','counterparty_reference':'LOAN-A'}]}


def append_completed_attempt(ledger,doc,text,ok):
    rr=read_with_retry(lambda prompt:response(text),'retained test',doc,'en-US','USD',
        parse_fn=parser_for('mortgage_statement'),configured_model='configured',max_retries=0)
    assert (rr.facts is not None)==ok
    ph=rr.phases[0]
    event=read_recorded(doc,ph.model,ph.prompt_version,ph.input_mode,ph.raw_text,
        ph.cost_usd,ph.input_tokens,ph.output_tokens,ph.parse_ok,ph.error,'2021-01-31',
        resolved_model=ph.resolved_model,usage_reported=ph.usage_reported,
        normalization_context=ph.normalization_context)
    ledger.append(event);return event


@pytest.mark.parametrize('by_date',[False,True])
@pytest.mark.parametrize('history',['accepted_failed','failed_accepted'])
def test_actual_rebuild_latest_attempt_original_ids_costs_and_recorded_context(tmp_path,monkeypatch,by_date,history):
    from viva import rebuild
    source=tmp_path/'source';dest=tmp_path/'destination'
    vault=Vault.open(source,'synthetic-passphrase')
    cash=cash_payload();data=mortgage();data['payments'][0]['fees']=None
    capture_and_ingest(vault.raw,vault.ledger,pdf(cash),genuine_reader(monkeypatch,cash,'checking_statement'))
    result=capture_and_ingest(vault.raw,vault.ledger,pdf(data),genuine_reader(monkeypatch,data,'mortgage_statement'))
    if history=='accepted_failed':append_completed_attempt(vault.ledger,result.doc_id,'not json',False)
    else:
        append_completed_attempt(vault.ledger,result.doc_id,'not json',False)
        append_completed_attempt(vault.ledger,result.doc_id,json.dumps(data),True)
    original=[event.to_dict() for event in vault.ledger.events() if event.event_type=='ReadRecorded']
    source_money=[event.to_dict() for event in vault.ledger.events() if event.event_type=='TransactionRecorded']
    vault.close()
    parse_calls=[];ordinary=rebuild._parse
    def tracked(*args):parse_calls.append(args);return ordinary(*args)
    monkeypatch.setattr(rebuild,'_parse',tracked)
    rebuild.rebuild(source,dest,'synthetic-passphrase',locale='de-DE',currency='EUR',by_date=by_date,log=lambda *args:None)
    assert len(parse_calls)==(4 if by_date else 2)
    assert all(args[-2:]==('en-US','USD') for args in parse_calls)
    with closing(Vault.open(dest,'synthetic-passphrase')) as rebuilt:
        actual=[event.to_dict() for event in rebuilt.ledger.events() if event.event_type=='ReadRecorded']
        assert actual==original
        assert len({event['event_id'] for event in actual})==len(actual)
        assert sum(event['body']['cost_usd'] for event in actual)==sum(event['body']['cost_usd'] for event in original)
        projection=rebuilt.ledger.projection()
        checking=reference_accounts(projection,'CHECK-A')[0]
        assert projection.running_balance(checking)==Decimal('1400')
        # Rebuild selects the latest claim, whereas the source has older posted
        # instrument activity. A later unparsable extraction must not recreate
        # those earlier postings by falling back to the successful attempt.
        assert len([event for event in rebuilt.ledger.events() if event.event_type=='TransactionRecorded'])==(1 if history=='accepted_failed' else len(source_money))
        if history=='accepted_failed':assert not projection.instrument_allocations()
        else:
            assert len(projection.instrument_allocations())==1
            assert projection.running_balance(reference_accounts(projection,'LOAN-A')[0])==Decimal('900')
        from viva.read_store.overview import SQLOverviewProjection
        rebuilt.read_store.synchronize(rebuilt.ledger.store)
        with rebuilt.read_store.open_reader() as revision:
            assert SQLOverviewProjection(revision,'2021-01-31').instrument_allocations()==projection.instrument_allocations()
    # Reopen preserves exact original source receipts and current allocation result.
    with closing(Vault.open(dest,'synthetic-passphrase')) as reopened:
        assert [event.to_dict() for event in reopened.ledger.events() if event.event_type=='ReadRecorded']==original
        assert bool(reopened.ledger.projection().instrument_allocations())==(history=='failed_accepted')


def test_failed_audit_status_not_rewritten_when_current_financial_reparse_succeeds(tmp_path,monkeypatch):
    from viva import rebuild
    source=tmp_path/'source';destination=tmp_path/'destination'
    data=mortgage();data['payments'][0]['fees']=None;cash=cash_payload()
    with closing(Vault.open(source,'synthetic-passphrase')) as vault:
        capture_and_ingest(vault.raw,vault.ledger,pdf(cash),genuine_reader(monkeypatch,cash,'checking_statement'))
        result=capture_and_ingest(vault.raw,vault.ledger,pdf(data),genuine_reader(monkeypatch,data,'mortgage_statement'))
        def completed_then_raised(*args):
            facts,error=parser_for('mortgage_statement')(*args)
            assert facts is not None and error is None
            raise RuntimeError('historical post-parse metadata exception')
        rr=read_with_retry(lambda prompt:response(json.dumps(data)),'retained',result.doc_id,'en-US','USD',
            parse_fn=completed_then_raised,configured_model='configured')
        ph=rr.phases[0]
        failed=read_recorded(result.doc_id,ph.model,ph.prompt_version,ph.input_mode,ph.raw_text,
            ph.cost_usd,ph.input_tokens,ph.output_tokens,ph.parse_ok,ph.error,'2021-01-31',
            resolved_model=ph.resolved_model,usage_reported=ph.usage_reported,normalization_context=ph.normalization_context)
        vault.ledger.append(failed)
        originals=[event.to_dict() for event in vault.ledger.events() if event.event_type=='ReadRecorded']
    rebuild.rebuild(source,destination,'synthetic-passphrase',locale='de-DE',currency='EUR',log=lambda *a:None)
    with closing(Vault.open(destination,'synthetic-passphrase')) as vault:
        projection=vault.ledger.projection()
        assert projection.running_balance(reference_accounts(projection,'LOAN-A')[0])==Decimal('900')
        assert not projection.instrument_allocations()
        assert [event.to_dict() for event in vault.ledger.events() if event.event_type=='ReadRecorded']==originals
        assert originals[-1]['body']['parse_ok'] is False


def test_repeated_actual_context_rebuild_is_financially_and_audit_idempotent(tmp_path,monkeypatch):
    from viva import rebuild
    source=tmp_path/'source';destination=tmp_path/'destination'
    data=mortgage();data['payments'][0]['fees']=None;cash=cash_payload()
    with closing(Vault.open(source,'synthetic-passphrase')) as vault:
        for payload,kind in [(cash,'checking_statement'),(data,'mortgage_statement')]:
            capture_and_ingest(vault.raw,vault.ledger,pdf(payload),genuine_reader(monkeypatch,payload,kind))
    def state():
        with closing(Vault.open(destination,'synthetic-passphrase')) as vault:
            return ([event.to_dict() for event in vault.ledger.events() if event.event_type in {'ReadRecorded','TransactionRecorded'}],
                vault.ledger.projection().instrument_allocations())
    rebuild.rebuild(source,destination,'synthetic-passphrase',locale='de-DE',currency='EUR',log=lambda *a:None)
    before=state();assert len(before[1])==1
    rebuild.rebuild(source,destination,'synthetic-passphrase',locale='fr-FR',currency='JPY',log=lambda *a:None)
    assert state()==before


def brokerage_source_payload(ordinary, typed):
    from test_extraction import fixture, legacy
    data=legacy();data['doc_type']='brokerage_statement'
    data['activity']=[{'date_raw':'01/25/2025','kind':'buy','amount_raw':ordinary,
        'instrument':'TEST-SEC','description':'Printed buy','realized_gain_raw':'-2.12345678'}]
    data['investment_source']=fixture()
    data['investment_source']['rows'][0].update(amount={'raw':typed,'page':1},
        printed_row_reference={'raw':'PRINTED-ROW-A','page':1},
        reported_realized_gain={'raw':'-2.12345678','page':1})
    return data


def retained_source_reader(payload, kind, version):
    from viva.ingest.pipeline import ReadResult
    from viva.normalization_context import ExtractionNormalizationContext
    from vivacore.verify.normalize import RULES_VERSION
    text=json.dumps(payload)
    context=ExtractionNormalizationContext(1,RULES_VERSION,'en-US','USD')
    def read(_data,doc):
        from viva.ingest.brokerage import from_brokerage_json
        from viva.ingest.paystub import from_paystub_json
        parse=from_brokerage_json if kind=='brokerage_statement' else from_paystub_json
        facts,error=parse(text,doc,'en-US','USD')
        assert error is None
        return ReadResult(kind,1,facts,raw_text=text,model='synthetic-model',
            prompt_version=version,normalization_context=context,cost_usd=0.0003,
            input_tokens=41,output_tokens=73,input_mode='text+image')
    return read


@pytest.mark.parametrize('version',['extract:brokerage-base-v6+brokerage-v2','extract:brokerage-base-v7+brokerage-v2'])
@pytest.mark.parametrize('printed',['25.00','-25.00'])
def test_normal_brokerage_source_rebuild_preserves_recorded_signs_context_and_audit(tmp_path,monkeypatch,version,printed):
    from viva import rebuild
    from viva.normalization_context import encode_context
    payload=brokerage_source_payload(printed,printed)
    with closing(Vault.open(tmp_path/'source','synthetic-passphrase')) as vault:
        capture_and_ingest(vault.raw,vault.ledger,pdf(payload),
            retained_source_reader(payload,'brokerage_statement',version))
        original=[e.to_dict() for e in vault.ledger.events() if e.event_type=='ReadRecorded']
        assert len(original)==1 and original[0]['body']['cost_usd']==0.0003
        assert original[0]['body']['input_mode']=='text+image'
    parsed=[];parse=rebuild._parse_claim
    def tracked(*args,**kwargs):
        result=parse(*args,**kwargs);parsed.append(result);return result
    monkeypatch.setattr(rebuild,'_parse_claim',tracked)
    rebuild.rebuild(tmp_path/'source',tmp_path/'destination','synthetic-passphrase',
        locale='de-DE',currency='EUR',by_date=False,log=lambda _:None)
    assert len(parsed)==1
    facts,error,context=parsed[0]
    assert error is None and facts.currency=='USD'
    assert facts.activity[0].amount==Decimal('25.00')
    assert facts.activity[0].realized_gain==Decimal('-2.12345678')
    row=dict(facts.investment_source.rows[0])
    assert row['amount'].raw==printed and row['amount'].page==1
    assert row['printed_row_reference'].raw=='PRINTED-ROW-A'
    assert row['reported_realized_gain'].raw=='-2.12345678'
    assert encode_context(context)==original[0]['body']['normalization_context']
    for _ in range(2):
        with closing(Vault.open(tmp_path/'destination','synthetic-passphrase')) as vault:
            assert [e.to_dict() for e in vault.ledger.events() if e.event_type=='ReadRecorded']==original


def test_normal_brokerage_rebuild_parks_invalid_source_page_and_preserves_audit(tmp_path):
    from viva.rebuild import rebuild
    payload=brokerage_source_payload('-25.00','-25.00')
    payload['investment_source']['rows'][0]['amount']['page']=2
    # A retained reading can predate page validation; recovery checks the PDF again.
    with closing(Vault.open(tmp_path/'source','synthetic-passphrase')) as vault:
        capture_and_ingest(vault.raw,vault.ledger,pdf(payload),retained_source_reader(
            payload,'brokerage_statement','extract:brokerage-base-v6+brokerage-v2'))
        original=[e.to_dict() for e in vault.ledger.events() if e.event_type=='ReadRecorded']
    logs=[]
    result=rebuild(tmp_path/'source',tmp_path/'destination','synthetic-passphrase',
        locale='en-US',by_date=False,log=logs.append)
    assert result=={'parked':1}
    assert any('source field is outside the captu' in line for line in logs)
    with closing(Vault.open(tmp_path/'destination','synthetic-passphrase')) as vault:
        assert [e.to_dict() for e in vault.ledger.events() if e.event_type=='ReadRecorded']==original
        assert not any(e.event_type=='TransactionRecorded' for e in vault.ledger.events())
        assert not vault.ledger.projection().posted_doc_ids()


@pytest.mark.parametrize('schema,invalid_period,invalid_gross',[
    ('payroll-source-v1',False,False),('payroll-source-v2',True,False),
    ('payroll-source-v2',False,True)])
def test_normal_payroll_source_rebuild_retains_period_invalidation_and_page_validation(
        tmp_path,monkeypatch,schema,invalid_period,invalid_gross):
    from viva import rebuild
    from test_payroll_counterpart import payroll_data, sf
    payload=payroll_data();source=payload['payroll_source'];source['schema']=schema
    if schema=='payroll-source-v2':
        source['headers'].update(period_start=sf('2021-01-01',2 if invalid_period else 1),
            period_end=sf('2021-01-31'))
    if invalid_gross:source['headers']['gross']['page']=2
    version='extract:paystub-base-v2+paystub-v2' if schema=='payroll-source-v2' else 'extract:paystub-base-v1+paystub-v1'
    with closing(Vault.open(tmp_path/'source','synthetic-passphrase')) as vault:
        capture_and_ingest(vault.raw,vault.ledger,pdf(payload),retained_source_reader(payload,'pay_stub',version))
        original=[e.to_dict() for e in vault.ledger.events() if e.event_type=='ReadRecorded']
    from viva import ingest as ingest_package
    returned=[];ingest=ingest_package.capture_and_ingest
    def tracked(raw,ledger,data,reader,**kwargs):
        def observed(blob,doc):
            result=reader(blob,doc);returned.append(result);return result
        return ingest(raw,ledger,data,observed,**kwargs)
    monkeypatch.setattr(ingest_package,'capture_and_ingest',tracked)
    result=rebuild.rebuild(tmp_path/'source',tmp_path/'destination','synthetic-passphrase',
        locale='de-DE',currency='EUR',by_date=False,log=lambda _:None)
    assert len(returned)==1
    if invalid_gross:
        assert result=={'parked':1} and returned[0].facts is None
        assert 'source field is outside the captured document' in returned[0].error
    else:
        assert returned[0].facts is not None and returned[0].error is None
        headers=dict(returned[0].facts.payroll_source.headers)
        assert headers['gross'].raw==source['headers']['gross']['raw']
        if invalid_period:assert headers['period_start'] is None
    with closing(Vault.open(tmp_path/'destination','synthetic-passphrase')) as vault:
        assert [e.to_dict() for e in vault.ledger.events() if e.event_type=='ReadRecorded']==original
        if invalid_gross:assert not any(e.event_type=='TransactionRecorded' for e in vault.ledger.events())
