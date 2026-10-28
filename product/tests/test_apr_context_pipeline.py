"""Actual existing reader acceptance precedes deterministic local source authority."""
from dataclasses import replace
from pathlib import Path
from time import monotonic
import json
import pytest
from viva.ingest import capture_and_ingest,ReadResult
from viva.ingest.instrument_read import InstrumentReadFacts,parser_for
from viva.ingest.apr_context_local import extract_apr_context
from viva.ingest.instrument_observations import ObservationKind,Operation
from viva.ledger.instruments import encode_change,decode_change,reference_accounts,append_change,encode
from viva.ledger import LedgerProjection
from viva.read_store import ReadStore
from viva.read_store.instrument_authority import read_instrument_authority
from viva.read_store.instrument_authority_contracts import InstrumentRequest
from test_instrument_projector_b import setup,mortgage
from test_instrument_contracts import printed,refinance_json
from test_instrument_reader_b import _read

PDFROOT=Path(__file__).parents[2]/'output/pdf/synthetic_life_5y'


def numeric(*,apr=True,note=True):
    data=mortgage()
    data['terms']={'original_principal':printed('1000'),'originated':printed('2021-01-01'),
        'fixed_rate':True,'fixed_rate_source':{'page':1},'note_rate_basis':'simple_nominal','note_rate_basis_source':{'page':1}}
    if note:data['terms']['note_rate']=printed('5.25')
    if apr:data['terms']['disclosure_apr']=printed('5.25')
    return data


def original():
    path=PDFROOT/'D0012-mortgage-LOAN-A-2021-01-31.pdf'
    if not path.is_file():pytest.skip('campaign synthetic PDFs are not packaged product fixtures')
    return path.read_bytes()


def ingest_original(tmp_path,monkeypatch,*,data=None):
    raw,ledger=setup(tmp_path)
    calls=[]
    def read(blob,doc):
        result,adapter=_read(monkeypatch,blob,'mortgage_statement',doc,proposal=data or numeric())
        calls.extend(adapter.calls)
        return result
    result=capture_and_ingest(raw,ledger,original(),read)
    return raw,ledger,result,calls


def contexts(ledger):
    return [record['change'] for record in ledger.projection().core._instrument_observations.values()
        if not record['superseded'] and record['change'].kind==ObservationKind.APR_CONTEXT and record['change'].operation!=Operation.RETRACT]


def test_actual_reader_acceptance_local_observations_sql_quote_inputs_and_no_extra_call(tmp_path,monkeypatch):
    raw,ledger,result,calls=ingest_original(tmp_path,monkeypatch)
    assert len(calls)==2 # ordinary classification plus numeric extraction only
    assert result.action=='awaiting' # missing independent bank payment is not held terms
    context=contexts(ledger)
    assert len(context)==2 and all(change.payload.result.disposition=='accepted' for change in context)
    numeric_change=next(record['change'] for record in ledger.projection().core._instrument_observations.values()
        if record['change'].kind==ObservationKind.MORTGAGE_COMPONENTS)
    old_bytes=json.dumps(encode_change(numeric_change),sort_keys=True)
    for change in context:
        assert decode_change(encode_change(change))==change
        assert change.payload.numeric_terms_observation_id==numeric_change.observation_id
        assert change.payload.result.grounding.numeric_terms_observation_id==numeric_change.observation_id
    assert extract_apr_context(raw,ledger,result.doc_id,locale='en-US')['appended']==0
    assert json.dumps(encode_change(numeric_change),sort_keys=True)==old_bytes
    account=reference_accounts(ledger.projection(),'LOAN-A')[0]
    with ReadStore.create(tmp_path/'reads','synthetic-passphrase') as store:
        assert store.synchronize(ledger.store).state=='rebuilt'
        with store.open_reader() as revision:
            response=read_instrument_authority(revision,InstrumentRequest('terms',account,'USD',as_of='2021-01-31'),deadline=monotonic()+2)
            values={a.claim:a.value for a in response.assertions}
            assert values['disclosure_apr_status']=='owner_specified_fictional_input'
            assert 'not a computed legal lender disclosure' in values['disclosure_apr_context']
            assert next(f.value for f in response.figures if f.claim=='loan_disclosure_apr')=='0.0525'
        rebuilt=LedgerProjection(ledger.events())
        assert len(rebuilt.core._instrument_observations)==len(ledger.projection().core._instrument_observations)


def test_replacement_unavailable_apr_uses_note_anchor_without_manufacturing_rate(tmp_path,monkeypatch):
    raw,ledger=setup(tmp_path)
    path=PDFROOT/'D0326-mortgage-LOAN-B-2023-01-31.pdf'
    if not path.is_file():pytest.skip('campaign source unavailable')
    data=numeric(apr=False);data['identity']['account_reference']=printed('LOAN-B')
    data['terms']['note_rate']=printed('4.25')
    result=capture_and_ingest(raw,ledger,path.read_bytes(),lambda blob,doc:_read(monkeypatch,blob,'mortgage_statement',doc,proposal=data)[0])
    selected={change.payload.field:change.payload.result for change in contexts(ledger)}
    assert selected['status'].value=='unavailable'
    assert selected['context'].reason=='not_printed'
    assert selected['status'].grounding.numeric_apr_span is None


def test_no_accepted_anchor_never_reads_source_and_held_terms_never_contextualize(tmp_path,monkeypatch):
    raw,ledger,result,calls=ingest_original(tmp_path,monkeypatch,data=numeric(apr=False,note=False))
    monkeypatch.setattr(raw,'get_bounded',lambda *a,**k:pytest.fail('no accepted anchor must not search source'))
    response=extract_apr_context(raw,ledger,result.doc_id,locale='en-US')
    assert response['status']=='numeric_terms_unavailable'
    assert all(change.payload.result.disposition=='unavailable' for change in contexts(ledger))


def test_deadline_and_missing_locale_leave_numeric_bytes_unchanged(tmp_path,monkeypatch):
    raw,ledger,result,calls=ingest_original(tmp_path,monkeypatch)
    before=[encode_change(record['change']) for record in ledger.projection().core._instrument_observations.values()
        if record['change'].kind==ObservationKind.MORTGAGE_COMPONENTS]
    assert extract_apr_context(raw,ledger,result.doc_id,locale='en-US',deadline=0)['status']=='source_limit'
    assert extract_apr_context(raw,ledger,result.doc_id,locale='')['status']=='unsupported_representation'
    after=[encode_change(record['change']) for record in ledger.projection().core._instrument_observations.values()
        if record['change'].kind==ObservationKind.MORTGAGE_COMPONENTS]
    assert before==after


def test_numeric_retraction_invalidates_context_without_retarget(tmp_path,monkeypatch):
    raw,ledger,result,calls=ingest_original(tmp_path,monkeypatch)
    prior=next(record['change'] for record in ledger.projection().core._instrument_observations.values()
        if record['change'].kind==ObservationKind.MORTGAGE_COMPONENTS)
    append_change(ledger,replace(prior,observation_id='numeric-retracted',operation=Operation.RETRACT,prior_id=prior.observation_id,payload=None))
    assert extract_apr_context(raw,ledger,result.doc_id,locale='en-US')['status']=='numeric_terms_unavailable'
    account=reference_accounts(ledger.projection(),'LOAN-A')[0]
    with ReadStore.create(tmp_path/'reads','synthetic-passphrase') as store:
        store.synchronize(ledger.store)
        with store.open_reader() as revision:
            response=read_instrument_authority(revision,InstrumentRequest('terms',account,'USD',as_of='2021-01-31'),deadline=monotonic()+2)
            assert not any(a.claim in {'disclosure_apr_status','disclosure_apr_context'} for a in response.assertions)


def test_refinance_without_separate_accepted_terms_cannot_supply_context(tmp_path,monkeypatch):
    raw,ledger=setup(tmp_path)
    path=PDFROOT/'D0311-refinance-LOAN-B-2022-12-31.pdf'
    if not path.is_file():pytest.skip('campaign source unavailable')
    result=capture_and_ingest(raw,ledger,path.read_bytes(),lambda blob,doc:_read(monkeypatch,blob,'refinance_settlement',doc,proposal=refinance_json())[0])
    assert extract_apr_context(raw,ledger,result.doc_id,locale='en-US')['status']=='numeric_terms_unavailable'
    assert not contexts(ledger)


def test_field_local_conflict_correction_retraction_and_encrypted_rebuild(tmp_path,monkeypatch):
    from viva.ingest.apr_context_grounding import MeasuredPage,MeasuredSpan,construct_context
    from hashlib import sha256
    raw,ledger,result,calls=ingest_original(tmp_path,monkeypatch)
    status=next(change for change in contexts(ledger) if change.payload.field=='status')
    # Independent accepted-source records exercise projection conflict semantics;
    # source-grounding integrity itself is tested against measured PDF pages.
    alternate_value='x'*len(status.payload.result.value)
    receipt=status.payload.result.grounding
    measured=tuple(replace(span,text=span.text.replace(status.payload.result.value,alternate_value))
        if span.span_id==receipt.field_label_span else span for span in receipt.measured_spans)
    alternate=replace(status.payload.result,value=alternate_value,grounding=replace(receipt,measured_spans=measured))
    conflicting=replace(status,observation_id='conflicting-status',payload=replace(status.payload,result=alternate))
    append_change(ledger,conflicting)
    account=reference_accounts(ledger.projection(),'LOAN-A')[0]
    def answer(store):
        store.synchronize(ledger.store)
        with store.open_reader() as revision:
            return read_instrument_authority(revision,InstrumentRequest('terms',account,'USD',as_of='2021-01-31'),deadline=monotonic()+2)
    with ReadStore.create(tmp_path/'reads','synthetic-passphrase') as store:
        response=answer(store)
        assert any(d.component=='disclosure_apr_status' and d.disposition=='conflicted' for d in response.dispositions)
        assert any(a.claim=='disclosure_apr_context' for a in response.assertions)
        assert any(f.claim=='loan_disclosure_apr' for f in response.figures)
        corrected=replace(conflicting,observation_id='corrected-status',operation=Operation.CORRECT,prior_id=conflicting.observation_id,payload=status.payload)
        append_change(ledger,corrected)
        assert any(a.claim=='disclosure_apr_status' for a in answer(store).assertions)
        append_change(ledger,replace(corrected,observation_id='retracted-status',operation=Operation.RETRACT,prior_id=corrected.observation_id,payload=None))
        assert any(a.claim=='disclosure_apr_status' for a in answer(store).assertions)
    with ReadStore.open(tmp_path/'reads','synthetic-passphrase') as reopened:
        response=answer(reopened)
        assert any(a.claim=='disclosure_apr_status' for a in response.assertions)


def test_registered_terms_adapter_and_current_run_literal_binding(tmp_path,monkeypatch):
    from types import SimpleNamespace
    from viva.instrument_runtime import InstrumentRuntime
    from viva.tools.instruments import read_instrument_details
    from viva.tools.runner import _Ground
    from viva.tools.runner_binding import _bound
    raw,ledger,result,calls=ingest_original(tmp_path,monkeypatch)
    account=reference_accounts(ledger.projection(),'LOAN-A')[0]
    with ReadStore.create(tmp_path/'reads','synthetic-passphrase') as store:
        store.synchronize(ledger.store)
        runtime=InstrumentRuntime(store.open_reader)
        with runtime.execution(monotonic()+2):
            result=read_instrument_details(runtime,{'view':'terms','account':account,'currency':'USD','as_of':'2021-01-31'})
            assert result.ok
            ground=_Ground(question='What does the disclosure say?',instrument_token=runtime.run_token)
            ground.stamp(result)
            assertion=next(a for a in ground.instrument_assertions.values() if a['claim']=='disclosure_apr_context')
            written,reason,_=_bound(SimpleNamespace(type='instrument_text',name='context'),{'instrument_text':assertion['id']},ground,'en-US')
            assert not reason and 'fictional scenario input' in str(written)
            assert assertion['anchors'][0]['document_id']==result.record_ids[0]
