"""Dormant printed-principal authority through authenticated normal ingestion."""
import json
from dataclasses import asdict, replace
from time import monotonic
from contextlib import contextmanager
import pytest
from test_instrument_projector_b import setup as source_setup, bank, mortgage
from normalization.test_mortgage_context_maintenance import ingest
from test_instrument_contracts import printed
from viva.ledger.instruments import reference_accounts
from viva.read_store import ReadStore
from viva.read_store.instrument_authority_contracts import InstrumentRequest
import viva.read_store.instrument_authority as authority
from viva.instrument_runtime import InstrumentRuntime
from viva.tools.instruments import read_instrument_details


def request(account, *, annual=False, end='2021-01-31'):
    return InstrumentRequest('period_components',account,'USD',start='2021-01-01',end=end,
        grouping='year' if annual else 'month',component_set='annual_summary' if annual else 'payment_escrow')


def source(tmp_path, *, known=False, payoff=True, mutate=None, witness=True):
    raw,ledger=source_setup(tmp_path)
    data=mortgage()
    data['principal_movements'].append({'kind':'principal_reduction','amount':printed('50'),
        'dated':printed('2021-01-16'),'reference':printed('EXTRA-50')})
    data['closing_principal']=printed('850')
    if payoff:
        data['principal_movements'].append({'kind':'payoff','amount':printed('850'),
            'dated':printed('2021-01-31'),'reference':printed('SOURCE-PAYOFF')})
        data['closing_principal']=printed('0')
    if known:data['payments'][0]['fees']=None
    if mutate:mutate(data)
    document=ingest(raw,ledger,'gate-mortgage',data,'mortgage_statement')
    bank_document=bank(raw,ledger) if witness else None
    return ledger,reference_accounts(ledger.projection(),'LOAN-A')[0],document,bank_document


@contextmanager
def execution(tmp_path,ledger):
    with ReadStore.create(tmp_path/'reads','synthetic-passphrase') as store:
        store.synchronize(ledger.store)
        runtime=InstrumentRuntime(store.open_reader)
        with runtime.execution(monotonic()+15):yield runtime


def internal(runtime,req):
    from viva.tools.instruments import _instrument_authority_result
    deadline=min(runtime.deadline,runtime.started+2 if runtime.read_count==0 else monotonic()+2)
    runtime.read_count+=1;runtime.read_deadline=deadline
    result=authority.read_payment_principal_report_authority(runtime.revision,req,deadline=deadline)
    return result,_instrument_authority_result(runtime,req,result,deadline=deadline)


@pytest.mark.parametrize('known',[False,True])
def test_printed_principal_is_100_aggregate_150_and_payoff_850(tmp_path,known):
    ledger,account,document,bank_document=source(tmp_path,known=known)
    with execution(tmp_path,ledger) as runtime:
        req=request(account)
        generic=authority.read_instrument_authority(runtime.revision,replace(req,component_set='loan_principal'),deadline=monotonic()+2)
        assert {f.claim:f.value for f in generic.figures}['principal_repayment']=='150'
        assert {f.claim:f.value for f in generic.figures}['principal_payoff']=='850'
        result,tool=internal(runtime,req)
        principal=next(f for f in result.figures if f.claim=='payment_principal')
        assert principal.value=='100' and tool.ok
        snapshot=authority.source_snapshot(runtime.revision,req,monotonic()+2)
        if known:
            assert len(snapshot.known_allocations)==1
            allocation=snapshot.known_allocations[0]
            assert principal.operand_ids==allocation.receipt.operand_ids and len(principal.operand_ids)==4
            assert principal.grade==allocation.receipt.grade=='unverified'
            assert bank_document.doc_id in {a.document_id for a in result.anchors if a.anchor_id in principal.anchor_ids}
        assert document.doc_id in tool.record_ids
        generic=read_instrument_details(runtime,as_args(req))
        assert generic.ok and not any(f['claim']=='payment_principal' for f in generic.figures)


def as_args(req):
    return {'view':req.view,'account':req.account,'currency':req.currency,'from':req.start,'to':req.end,
        'grouping':req.grouping,'component_set':req.component_set}


def test_contract_and_helper_exist_but_cannot_be_selected_publicly():
    from viva.instrument_claims import CLAIMS
    from viva.tools import default_registry
    from viva.ledger import LedgerProjection
    from viva.answer_program.capability import CapabilityManifest
    from viva.answer_program.intents import SemanticFamilyRegistry
    assert CLAIMS['payment_principal'].quantity=='repayment'
    assert callable(authority.read_payment_principal_report_authority)
    manifest=CapabilityManifest.from_registry(default_registry(LedgerProjection([])))
    assert 'payment_principal' not in json.dumps(manifest.to_dict())
    assert 'payment_principal' not in json.dumps(SemanticFamilyRegistry().model_output_schema())
    with pytest.raises(ValueError):InstrumentRequest.from_dict({**as_args(request('a')),'payment_principal':True})


@pytest.mark.parametrize('mutation',['missing','unknown','empty','held','bank_reference','bank_absent','coverage','currency','account','date'])
def test_missing_or_ineligible_principal_never_becomes_zero(tmp_path,mutation):
    def mutate(data):
        if mutation=='missing':data['payments'][0]['principal']=None
        if mutation=='unknown':data['payments']=None
        if mutation=='empty':data['payments']=[]
        if mutation=='held':data['payments'][0]['interest']=printed('201')
        if mutation=='bank_reference':data['payments'][0]['funding_account_reference']=printed('OTHER-CHECK')
        if mutation=='date':data['payments'][0]['dated']=printed('2021-02-01')
    known=mutation in {'bank_reference','bank_absent'}
    ledger,account,_,_=source(tmp_path,known=known,mutate=mutate,witness=mutation!='bank_absent')
    with execution(tmp_path,ledger) as runtime:
        req=request(account,end='2021-02-28' if mutation=='coverage' else '2021-01-31')
        if mutation=='currency':req=replace(req,currency='EUR')
        if mutation=='account':req=replace(req,account='unknown-account')
        result,_=internal(runtime,req)
        assert not any(f.claim=='payment_principal' for f in result.figures)


def test_expired_deadline_unsupported_shape_and_non_authenticated_revision(tmp_path,monkeypatch):
    ledger,account,_,_=source(tmp_path)
    with execution(tmp_path,ledger) as runtime:
        req=request(account)
        with pytest.raises(ValueError):authority.read_payment_principal_report_authority(runtime.revision,replace(req,end='2021-04-30'),deadline=monotonic()+2)
        def forbidden(*a,**k):raise AssertionError('source query after expired deadline')
        monkeypatch.setattr(authority,'source_snapshot',forbidden)
        result=authority.read_payment_principal_report_authority(runtime.revision,req,deadline=monotonic()-1)
        assert not result.figures and result.dispositions[0].disposition=='resource_limit'
    with pytest.raises((ValueError,AttributeError)):
        authority.read_payment_principal_report_authority(object(),req,deadline=monotonic()+2)


def test_generic_routing_and_advertisement_counterfactuals_are_detected(tmp_path,monkeypatch):
    import viva.tools as tools
    import viva.instrument_claims as claims
    from viva.ledger import LedgerProjection
    from viva.answer_program.capability import CapabilityManifest
    def advertisement_control():
        assert 'payment_principal' not in json.dumps(CapabilityManifest.from_registry(tools.default_registry(LedgerProjection([]))).to_dict())
    advertisement_control()
    monkeypatch.setattr(claims,'INTERNAL_ONLY_CLAIMS',frozenset())
    with pytest.raises(AssertionError):advertisement_control()
    ledger,account,_,_=source(tmp_path)
    with execution(tmp_path,ledger) as runtime:
        original=authority.read_instrument_authority
        monkeypatch.setattr(authority,'read_instrument_authority',lambda rev,req,**kw:authority.read_payment_principal_report_authority(rev,req,deadline=kw['deadline']))
        tool=read_instrument_details(runtime,as_args(request(account)))
        with pytest.raises(AssertionError):assert not any(f['claim']=='payment_principal' for f in tool.figures)
        monkeypatch.setattr(authority,'read_instrument_authority',original)


def test_run_owned_stamp_accepts_genuine_and_rejects_serialized_or_mutated_principal(tmp_path):
    from viva.tools.runner import _Ground
    ledger,account,_,_=source(tmp_path,known=True)
    with execution(tmp_path,ledger) as runtime:
        _,tool=internal(runtime,request(account))
        ground=_Ground(question='Printed principal');ground.instrument_token=runtime.run_token
        ground.stamp(tool)
        assert ground.book
        for field,value in [('value','101'),('record_ids',['foreign-source'])]:
            _,tool=internal(runtime,request(account));principal=next(f for f in tool.figures if f['claim']=='payment_principal');principal[field]=value
            guard=_Ground(question='Printed principal');guard.instrument_token=runtime.run_token
            with pytest.raises(ValueError):guard.stamp(tool)


def test_internal_read_clock_keeps_first_acquisition_and_subsequent_windows(tmp_path,monkeypatch):
    ledger,account,_,_=source(tmp_path)
    with execution(tmp_path,ledger) as runtime:
        req=request(account);started=runtime.started
        runtime.started=started-3
        result,tool=internal(runtime,req)
        assert runtime.read_count==1 and runtime.read_deadline==runtime.started+2
        assert not result.figures and not tool.ok
        result,tool=internal(runtime,req)
        assert runtime.read_count==2 and tool.ok
        assert runtime.read_deadline<=runtime.deadline
        runtime.deadline=monotonic()-1
        result,tool=internal(runtime,req)
        assert runtime.read_count==3 and runtime.read_deadline==runtime.deadline and not tool.ok


def test_equal_printed_witnesses_pool_pages_without_doubling(tmp_path):
    ledger,account,_,_=source(tmp_path,known=False,payoff=False)
    from viva.ingest import RawStore
    # A second normal ingestion uses the same typed printed figures and distinct document bytes.
    raw=RawStore.open(tmp_path/'raw','synthetic-passphrase')
    data=mortgage()
    data['principal_movements'].append({'kind':'principal_reduction','amount':printed('50'),'dated':printed('2021-01-16'),'reference':printed('EXTRA-50')})
    data['closing_principal']=printed('850')
    duplicate=ingest(raw,ledger,'equal-independent-witness',data,'mortgage_statement')
    with execution(tmp_path,ledger) as runtime:
        result,tool=internal(runtime,request(account))
        principal=next(f for f in result.figures if f.claim=='payment_principal')
        assert principal.value=='100' and len(principal.observation_ids)==2
        assert duplicate.doc_id in {a.document_id for a in result.anchors if a.anchor_id in principal.anchor_ids}


def test_internal_source_rows_and_figures_keep_existing_bounds(tmp_path,monkeypatch):
    from viva.ingest import instrument_contracts as c
    from viva.read_store.instrument_authority_sql import AuthorityReadError
    ledger,account,_,_=source(tmp_path)
    with execution(tmp_path,ledger) as runtime:
        req=request(account)
        snapshot=authority.source_snapshot(runtime.revision,req,monotonic()+2)
        row=snapshot.observations[0]['change']
        # Typed injection is only a finite resource guard, never an acceptance positive.
        mortgage_row=next(record for record in snapshot.observations if isinstance(record['change'].payload,c.MortgageFacts))
        payload=mortgage_row['change'].payload
        oversized=replace(payload,payments=tuple(payload.payments)*1001)
        oversized_row={**mortgage_row,'change':replace(mortgage_row['change'],payload=oversized)}
        monkeypatch.setattr(authority,'source_snapshot',lambda *a,**kw:replace(snapshot,observations=(oversized_row,)))
        result=authority.read_payment_principal_report_authority(runtime.revision,req,deadline=monotonic()+2)
        assert not result.figures and result.dispositions[0].disposition=='resource_limit'


@pytest.mark.parametrize('mutation',['retracted','superseded','interpretation_tampered'])
def test_current_source_frontier_and_recorded_interpretation_remain_authoritative(tmp_path,mutation):
    from viva.ledger.instruments import append_change
    from viva.ingest.instrument_observations import Operation,ObservationKind
    from viva.ledger.events import Event
    from viva.ingest.instrument_projector import heal_instruments
    ledger,account,document,_=source(tmp_path,known=True)
    if mutation=='interpretation_tampered':
        prior=next(event for event in reversed(tuple(ledger.events())) if event.event_type=='ReadRecorded' and event.body['doc_id']==document.doc_id)
        body=json.loads(json.dumps(prior.body));body.pop('normalization_context')
        ledger.append(Event('ReadRecorded',prior.occurred_at,body,prior.provenance));heal_instruments(ledger)
    else:
        prior=next(row['change'] for row in ledger.projection().core._instrument_observations.values()
            if row['change'].kind==ObservationKind.MORTGAGE_COMPONENTS)
        payload=None if mutation=='retracted' else replace(prior.payload,payments=None)
        append_change(ledger,replace(prior,observation_id='gate-'+mutation,operation=Operation.RETRACT if payload is None else Operation.CORRECT,prior_id=prior.observation_id,payload=payload))
        heal_instruments(ledger)
    with execution(tmp_path,ledger) as runtime:
        result,tool=internal(runtime,request(account))
        assert not any(f.claim=='payment_principal' for f in result.figures)


def test_json_copy_cannot_carry_principal_authority(tmp_path):
    from viva.tools.runner import _Ground
    ledger,account,_,_=source(tmp_path,known=True)
    with execution(tmp_path,ledger) as runtime:
        _,tool=internal(runtime,request(account))
        tool.figures=[json.loads(json.dumps(f)) for f in tool.figures]
        ground=_Ground(question='Printed principal');ground.instrument_token=runtime.run_token
        with pytest.raises(ValueError):ground.stamp(tool)
