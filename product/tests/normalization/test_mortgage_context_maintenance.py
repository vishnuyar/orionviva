"""Known printed components never manufacture an unavailable fee."""
from dataclasses import replace
from decimal import Decimal, localcontext
import pytest
from test_instrument_projector_b import setup, bank, mortgage
import json
from viva.ingest import capture_and_ingest, ReadResult
from viva.ingest.instrument_read import InstrumentReadFacts
from viva.ingest.instrument_parser import parse_instrument_json

def ingest(raw,ledger,label,data,kind):
    from viva.ingest.reader import read_with_retry
    from viva.ingest.instrument_read import parser_for
    from vivacore.models.base import ModelResult
    def read(blob,doc_id):
        text=json.dumps(data)
        def extract(prompt):
            return ModelResult(text,'offline-resolved',0,0,0,0,{}, {})
        return read_with_retry(extract,'offline fixture',doc_id,'en-US','USD',
            prompt_version='test',parse_fn=parser_for(kind),configured_model='offline-source-fixture')
    return capture_and_ingest(raw,ledger,label.encode(),read)

from viva.ingest import instrument_contracts as c

@pytest.mark.parametrize('bank_first',[True,False])
def test_missing_fee_reconciled_components_allocate_once(tmp_path, bank_first):
    raw, ledger=setup(tmp_path)
    data=mortgage();data['payments'][0]['fees']=None
    if bank_first: bank(raw,ledger)
    ingest(raw,ledger,'known-components',data,'mortgage_statement')
    if not bank_first:bank(raw,ledger)
    allocations=ledger.projection().instrument_allocations()
    assert len(allocations)==1
    allocation=next(iter(allocations.values()))
    assert allocation.payment.fees is None
    assert allocation.spending==Decimal('200')
    assert allocation.receipt.residual_cents==0

def test_sql_reads_supported_components_and_derived_receipt_but_never_fee(tmp_path):
    from test_instrument_authority_views import run
    from viva.ledger.instruments import reference_accounts
    from viva.read_store.instrument_authority_contracts import InstrumentRequest
    raw,ledger=setup(tmp_path);bank(raw,ledger)
    data=mortgage();data['payments'][0]['fees']=None
    ingest(raw,ledger,'known-components',data,'mortgage_statement')
    account=reference_accounts(ledger.projection(),'LOAN-A')[0]
    request=InstrumentRequest('period_components',account,'USD',start='2021-01-01',end='2021-01-31',grouping='month',component_set='payment_escrow')
    result=run(tmp_path,ledger,request)
    values={f.claim:f.value for f in result.figures}
    assert values['payment_total']=='600'
    assert values['payment_interest']=='200'
    assert values['escrow_funding']=='300'
    assert values['payment_net_unallocated']=='0'
    assert 'payment_fees' not in values
    residual=next(f for f in result.figures if f.claim=='payment_net_unallocated')
    assert len(residual.operand_ids)==4
    assert residual.calculation_context=='printed_payment_net_residual_v1'

@pytest.mark.parametrize('value',['600.01','599.99','600.001','-0','1e99999','0e-100','1'*31])
def test_bounded_residual_refuses_without_rounding(value):
    from viva.ingest.mortgage_known_allocation import residual
    from viva.ingest.instrument_parser import parse_instrument_json
    data=mortgage();data['payments'][0]['fees']=None
    payment=parse_instrument_json(json.dumps(data),'mortgage_statement','synthetic-source').payments[0]
    with pytest.raises(ValueError):
        residual(replace(payment,total=c.Money(Decimal(value),'USD',payment.total.source)))


def test_exact_residual_is_independent_of_decimal_context():
    from viva.ingest.mortgage_known_allocation import residual
    from viva.ingest.instrument_parser import parse_instrument_json
    from decimal import Inexact
    data=mortgage();data['payments'][0]['fees']=None
    payment=parse_instrument_json(json.dumps(data),'mortgage_statement','synthetic-source').payments[0]
    with localcontext() as context:
        context.prec=1;context.traps[Inexact]=True
        assert residual(payment)==0

@pytest.mark.parametrize('field',['principal','interest','escrow','total','dated','reference','funding_account_reference'])
def test_missing_operand_or_identity_holds_only_allocation(tmp_path,field):
    raw,ledger=setup(tmp_path);bank(raw,ledger)
    data=mortgage();data['payments'][0].update(fees=None)
    data['payments'][0][field]=None
    ingest(raw,ledger,'missing-'+field,data,'mortgage_statement')
    assert not ledger.projection().instrument_allocations()
    from viva.ledger.instruments import reference_accounts
    assert ledger.projection().running_balance(reference_accounts(ledger.projection(),'LOAN-A')[0])==900

@pytest.mark.parametrize('field,value',[('fees',{'raw':'not a number','page':1}),('fee_credit',{'raw':'10','page':1}),('adjustments',[{'raw':'-10','page':1}])])
def test_invalid_or_extra_raw_component_cannot_be_silently_absent(field,value):
    from viva.ingest.instrument_parser import parse_instrument_json
    data=mortgage();data['payments'][0]['fees']=None
    data['payments'][0][field]=value
    with pytest.raises(ValueError):parse_instrument_json(json.dumps(data),'mortgage_statement','synthetic-source')


def test_unaccepted_reread_retires_known_allocation_without_reposting_cash(tmp_path):
    from viva.ledger.events import read_recorded
    from viva.ingest.instrument_projector import heal_instruments
    from viva.ledger import LedgerProjection
    raw,ledger=setup(tmp_path);bank(raw,ledger)
    data=mortgage();data['payments'][0]['fees']=None
    result=ingest(raw,ledger,'known-components',data,'mortgage_statement')
    before=[event.to_dict() for event in ledger.events() if event.event_type=='TransactionRecorded']
    ledger.append(read_recorded(result.doc_id,'offline-source-fixture','test','text','bad source',0,0,0,False,'parse failed','2021-01-31'))
    assert not ledger.projection().instrument_allocations()
    assert not LedgerProjection(ledger.events()).instrument_allocations()
    assert heal_instruments(ledger)>=0
    assert not ledger.projection().instrument_allocations()
    after=[event.to_dict() for event in ledger.events() if event.event_type=='TransactionRecorded']
    assert before==after


def test_conflicting_source_retires_previous_known_interpretation(tmp_path):
    raw,ledger=setup(tmp_path);bank(raw,ledger)
    data=mortgage();data['payments'][0]['fees']=None
    ingest(raw,ledger,'known-original',data,'mortgage_statement')
    assert len(ledger.projection().instrument_allocations())==1
    changed=json.loads(json.dumps(data))
    changed['payments'][0]['principal']['raw']='101'
    changed['payments'][0]['interest']['raw']='199'
    ingest(raw,ledger,'known-conflicting',changed,'mortgage_statement')
    assert not ledger.projection().instrument_allocations()


def test_ambiguous_later_cash_retires_known_interpretation(tmp_path):
    raw,ledger=setup(tmp_path);bank(raw,ledger)
    data=mortgage();data['payments'][0]['fees']=None
    ingest(raw,ledger,'known-original',data,'mortgage_statement')
    assert len(ledger.projection().instrument_allocations())==1
    from viva.ledger.events import Event
    original=next(event for event in ledger.events() if event.event_type=='TransactionRecorded'
        and event.body.get('source_reference')=='PAY-A')
    ledger.append(Event('TransactionRecorded',original.occurred_at,json.loads(json.dumps(original.body)),original.provenance))
    assert not ledger.projection().instrument_allocations()

@pytest.mark.parametrize('field,value',[('normalization_context',None),('schema_version',2),('normalization_rules_version','nv2'),('parser_currency',None),('parser_currency','EUR')])
def test_missing_or_foreign_normalization_context_cannot_be_guessed(tmp_path,field,value):
    from viva.ledger.events import Event
    from viva.ingest.instrument_projector import heal_instruments
    raw,ledger=setup(tmp_path);bank(raw,ledger)
    data=mortgage();data['payments'][0]['fees']=None
    result=ingest(raw,ledger,'known-original',data,'mortgage_statement')
    source=next(event for event in reversed(tuple(ledger.events())) if event.event_type=='ReadRecorded' and event.body['doc_id']==result.doc_id)
    body={**source.body}
    if field=='normalization_context':body.pop('normalization_context')
    else:body['normalization_context']={**source.body['normalization_context'],field:value}
    ledger.append(Event('ReadRecorded',source.occurred_at,body,source.provenance))
    heal_instruments(ledger)
    assert not ledger.projection().instrument_allocations()

@pytest.mark.parametrize('field,value',[('loan_account','foreign-loan'),('escrow_account','foreign-escrow'),('funding_account','foreign-checking'),('cash_body_digest','0'*64),('source_read_digest','0'*64)])
def test_receipt_identity_or_digest_forgery_never_becomes_effective(tmp_path,field,value):
    from viva.ingest.mortgage_known_allocation import validate_core_binding
    raw,ledger=setup(tmp_path);bank(raw,ledger)
    data=mortgage();data['payments'][0]['fees']=None
    ingest(raw,ledger,'known-original',data,'mortgage_statement')
    allocation=next(iter(ledger.projection().instrument_allocations().values()))
    forged=replace(allocation,receipt=replace(allocation.receipt,**{field:value}))
    with pytest.raises(ValueError):validate_core_binding(forged,ledger.projection().core)


def test_residual_cannot_bind_a_generic_net_movement_slot(tmp_path):
    from viva.tools.runner_binding import _figure_bound
    from viva.instrument_evidence import _attest_figure
    from viva.tools.envelope import figure,bounded
    from types import SimpleNamespace
    plain=figure('0','Payment net unallocated',quantity='net_movement',currency='USD',grade='unverified',
        record_ids=['source'],boundary=bounded(whole=False),subject={'account_id':'loan'})
    stamped=_attest_figure(plain,'payment_net_unallocated',run_token=object())
    slot=SimpleNamespace(type='money',quantity='net_movement',name='generic',scope=())
    assert _figure_bound(slot,stamped,'en-US')[1]=='mortgage_claim_scope_required'


def test_derived_receipt_cannot_promote_its_grade(tmp_path):
    raw,ledger=setup(tmp_path);bank(raw,ledger)
    data=mortgage();data['payments'][0]['fees']=None
    ingest(raw,ledger,'known-original',data,'mortgage_statement')
    allocation=next(iter(ledger.projection().instrument_allocations().values()))
    with pytest.raises(ValueError):replace(allocation.receipt,grade='verified')


def test_real_semantic_program_binder_delivers_supported_claims_without_optional_fee(tmp_path):
    from viva.tools import default_registry
    from viva.answer_program import CapabilityManifest,ProgramValidator,ProgramExecutor,DeterministicBinder,AnswerResourcePolicy
    from viva.answer_program.intents import SemanticFamilyRegistry,SEMANTIC_REQUEST_VERSION
    from viva.answer_program.schema import QuestionContext
    from viva.read_store import ReadStore
    from viva.ledger.instruments import reference_accounts
    raw,ledger=setup(tmp_path);bank(raw,ledger)
    data=mortgage();data['payments'][0]['fees']=None
    ingest(raw,ledger,'known-original',data,'mortgage_statement')
    account=reference_accounts(ledger.projection(),'LOAN-A')[0]
    with ReadStore.create(tmp_path/'read','synthetic-passphrase') as store:
        store.synchronize(ledger.store)
        registry=default_registry(ledger.projection(),instrument_scope=store.open_reader)
        families=SemanticFamilyRegistry(registry.semantic_entities(),currency_resolver=registry.instrument_currency)
        question=f'Payment components for {account} from 2021-01-01 to 2021-01-31'
        request={'request_version':SEMANTIC_REQUEST_VERSION,'outcome':'request','catalog_digest':families.catalog_digest,
            'entity_catalog_digest':families.entity_catalog_digest,'family':'instrument_monthly_payment_escrow',
            'parameters':{'account_phrase':account,'from':'2021-01-01','to':'2021-01-31'},
            'parameter_sources':{'account_phrase':{'source':'question','quote':account,'derivation':'catalog_selection'},
                'from':{'source':'question','quote':'2021-01-01','derivation':'verbatim'},
                'to':{'source':'question','quote':'2021-01-31','derivation':'verbatim'}},
            'requested_claims':['payment_total','payment_interest','escrow_funding','payment_fees','payment_net_unallocated']}
        parsed=families.parse(request,QuestionContext(question=question))
        manifest=CapabilityManifest.from_registry(registry);program=families.lower(parsed,manifest)
        validation=ProgramValidator(manifest,AnswerResourcePolicy()).validate(program)
        assert validation.ok,validation.to_dict()
        execution=ProgramExecutor(registry,AnswerResourcePolicy()).execute(program,question)
        bound=DeterministicBinder(registry,'en-US').bind(program,execution)
        assert bound.result.answered,(bound.unbound,bound.result.detail)
        assert {f['claim'] for f in bound.result.figures}=={'payment_total','payment_interest','escrow_funding','payment_net_unallocated'}
        assert all(f['claim']!='payment_fees' for f in bound.result.figures)


def test_correction_retraction_sql_reopen_and_locked_frontier(tmp_path):
    from viva.read_store import ReadStore
    from viva.read_store.overview import SQLOverviewProjection
    from viva.ledger import LedgerProjection
    from viva.ledger.events import document_captured,read_recorded,Event
    from viva.ledger.instruments import append_change
    from viva.ingest.instrument_projector import post_instrument,heal_instruments
    from viva.ingest.instrument_observations import ObservationKind,Operation
    raw,ledger=setup(tmp_path);bank(raw,ledger)
    data=mortgage();data['payments'][0]['fees']=None
    ingest(raw,ledger,'known-original',data,'mortgage_statement')
    reads=ReadStore.create(tmp_path/'read','synthetic-passphrase')
    def check():
        reads.synchronize(ledger.store)
        with reads.open_reader() as revision:
            sql=SQLOverviewProjection(revision,'2021-02-28')
            oracle=LedgerProjection(ledger.events(),as_of='2021-02-28')
            assert sql.instrument_allocations()==oracle.instrument_allocations()
            assert sql.spending_by_currency()==oracle.spending_by_currency()
    check()
    prior=next(row['change'] for row in ledger.projection().core._instrument_observations.values()
        if row['change'].kind==ObservationKind.MORTGAGE_COMPONENTS)
    changed=json.loads(json.dumps(data));changed['payments'][0]['principal']['raw']='150'
    changed['payments'][0]['interest']['raw']='150';changed['principal_movements'][0]['amount']['raw']='150'
    changed['closing_principal']['raw']='850'
    doc='corrected-synthetic-source';ledger.append(document_captured(doc,'correction.pdf',100,'mortgage_statement',1,'2021-01-31'))
    text=json.dumps(changed);event=read_recorded(doc,'offline-source-fixture','test','text',text,0,0,0,True,None,'2021-01-31')
    phase=_completed_phase(text,doc,'mortgage_statement')
    from viva.normalization_context import encode_context
    event.body['normalization_context']=encode_context(phase.normalization_context);ledger.append(event)
    facts=InstrumentReadFacts(doc,'mortgage_statement',1.0,parse_instrument_json(text,'mortgage_statement',doc),'USD')
    result=post_instrument(ledger,facts,prior_id=prior.observation_id)
    assert len(ledger.projection().instrument_allocations())==1
    assert next(iter(ledger.projection().instrument_allocations().values())).spending==150
    check()
    corrected=next(row['change'] for row in ledger.projection().core._instrument_observations.values()
        if row['change'].prior_id==prior.observation_id)
    with pytest.raises(ValueError):append_change(ledger,replace(corrected,observation_id='stale-correction'))
    append_change(ledger,replace(corrected,observation_id='retract-known',operation=Operation.RETRACT,
        prior_id=corrected.observation_id,payload=None))
    heal_instruments(ledger)
    assert not ledger.projection().instrument_allocations()
    check();reads.close()
    with ReadStore.open(tmp_path/'read','synthetic-passphrase') as reopened:
        assert reopened.synchronize(ledger.store).state=='equal'
        with reopened.open_reader() as revision:
            assert not SQLOverviewProjection(revision,'2021-02-28').instrument_allocations()


def assert_known_sql_parity(tmp_path,ledger,label):
    from viva.read_store import ReadStore
    from viva.read_store.overview import SQLOverviewProjection
    from viva.ledger import LedgerProjection
    with ReadStore.create(tmp_path/label,'synthetic-passphrase') as store:
        store.synchronize(ledger.store)
        with store.open_reader() as revision:
            sql=SQLOverviewProjection(revision,'2021-02-28')
            oracle=LedgerProjection(ledger.events(),as_of='2021-02-28')
            assert sql.instrument_allocations()==oracle.instrument_allocations()
            assert sql.spending_by_currency()==oracle.spending_by_currency()


@pytest.mark.parametrize('amount',['1','-1','0.001'])
def test_later_explicit_fee_blocks_known_route_in_event_and_sql(tmp_path,amount):
    raw,ledger=setup(tmp_path);bank(raw,ledger)
    data=mortgage();data['payments'][0]['fees']=None
    ingest(raw,ledger,'known-original',data,'mortgage_statement')
    original_cash=[event.to_dict() for event in ledger.events() if event.event_type=='TransactionRecorded']
    other=json.loads(json.dumps(data));other['payments'][0]['fees']={'raw':amount,'page':1}
    ingest(raw,ledger,'explicit-inconsistent-'+amount,other,'mortgage_statement')
    assert not ledger.projection().instrument_allocations()
    assert_known_sql_parity(tmp_path,ledger,'held-fee-read')
    assert original_cash==[event.to_dict() for event in ledger.events() if event.event_type=='TransactionRecorded']


def test_later_printed_zero_uses_original_path_once_and_retraction_restores_known(tmp_path):
    from viva.ingest.instrument_effects import PaymentAllocation
    from viva.ingest.mortgage_known_allocation import KnownPaymentAllocation
    from viva.ingest.instrument_observations import Operation,ObservationKind
    from viva.ledger.instruments import append_change
    from viva.ingest.instrument_projector import heal_instruments
    raw,ledger=setup(tmp_path);bank(raw,ledger)
    data=mortgage();data['payments'][0]['fees']=None
    first=ingest(raw,ledger,'known-original',data,'mortgage_statement')
    original_cash=[event.to_dict() for event in ledger.events() if event.event_type=='TransactionRecorded']
    other=json.loads(json.dumps(data));other['payments'][0]['fees']={'raw':'0','page':1}
    second=ingest(raw,ledger,'explicit-zero',other,'mortgage_statement')
    allocations=ledger.projection().instrument_allocations()
    assert len(allocations)==1
    allocation=next(iter(allocations.values()))
    assert type(allocation) is PaymentAllocation and allocation.payment.fees.value==0
    assert_known_sql_parity(tmp_path,ledger,'zero-read')
    assert original_cash==[event.to_dict() for event in ledger.events() if event.event_type=='TransactionRecorded']
    explicit=next(row['change'] for row in ledger.projection().core._instrument_observations.values()
        if row['change'].source.doc_id==second.doc_id and row['change'].kind==ObservationKind.MORTGAGE_COMPONENTS)
    append_change(ledger,replace(explicit,observation_id='retract-explicit-zero',operation=Operation.RETRACT,
        prior_id=explicit.observation_id,payload=None))
    heal_instruments(ledger)
    allocations=ledger.projection().instrument_allocations()
    assert len(allocations)==1 and type(next(iter(allocations.values()))) is KnownPaymentAllocation
    assert_known_sql_parity(tmp_path,ledger,'known-restored-read')
    assert original_cash==[event.to_dict() for event in ledger.events() if event.event_type=='TransactionRecorded']


@pytest.mark.parametrize('section,kind',[('principal_movements','increase_adjustment'),('principal_movements','decrease_adjustment'),('escrow','increase_adjustment'),('escrow','decrease_adjustment')])
def test_other_same_payment_adjustment_retires_known_even_with_same_four_operands(tmp_path,section,kind):
    raw,ledger=setup(tmp_path);bank(raw,ledger)
    data=mortgage();data['payments'][0]['fees']=None
    ingest(raw,ledger,'known-original',data,'mortgage_statement')
    other=json.loads(json.dumps(data))
    row={'kind':kind,'amount':{'raw':'1','page':1},'dated':{'raw':'2021-01-15','page':1},'reference':{'raw':'PAY-A','page':1}}
    rows=other['principal_movements'] if section=='principal_movements' else other['escrow']['movements']
    rows.append(row)
    ingest(raw,ledger,'same-payment-'+section+kind,other,'mortgage_statement')
    assert not ledger.projection().instrument_allocations()
    assert_known_sql_parity(tmp_path,ledger,'adjusted-read')


@pytest.mark.parametrize('change',[{'fees':{'raw':'invalid present fee','page':1}},{'credit':{'raw':'1','page':1}},{'adjustments':[{'raw':'-1','page':1}]}])
def test_current_retained_raw_extra_component_cannot_hide_behind_typed_none(tmp_path,change):
    from viva.ledger.events import Event
    from viva.ingest.instrument_projector import heal_instruments
    raw,ledger=setup(tmp_path);bank(raw,ledger)
    data=mortgage();data['payments'][0]['fees']=None
    first=ingest(raw,ledger,'known-original',data,'mortgage_statement')
    second=ingest(raw,ledger,'same-payment-independent-witness',data,'mortgage_statement')
    raw_conflict=json.loads(json.dumps(data));raw_conflict['payments'][0].update(change)
    prior=next(event for event in reversed(tuple(ledger.events())) if event.event_type=='ReadRecorded' and event.body['doc_id']==second.doc_id)
    ledger.append(Event('ReadRecorded',prior.occurred_at,{**prior.body,'response_text':json.dumps(raw_conflict)},prior.provenance))
    heal_instruments(ledger)
    assert not ledger.projection().instrument_allocations()
    assert_known_sql_parity(tmp_path,ledger,'raw-conflict-read')


def test_same_occurrence_conflicting_funding_identity_cannot_keep_known_allocation(tmp_path):
    raw,ledger=setup(tmp_path);bank(raw,ledger)
    data=mortgage();data['payments'][0]['fees']=None
    ingest(raw,ledger,'known-original',data,'mortgage_statement')
    other=json.loads(json.dumps(data));other['payments'][0]['funding_account_reference']={'raw':'OTHER-CHECK','page':1}
    ingest(raw,ledger,'conflicting-funding-source',other,'mortgage_statement')
    assert not ledger.projection().instrument_allocations()
    assert_known_sql_parity(tmp_path,ledger,'funding-conflict-read')


def test_conflict_retirement_restores_contextual_first_post_read_claims(tmp_path):
    from viva.ledger.events import document_captured,read_recorded
    from viva.ingest.instrument_projector import post_instrument,heal_instruments
    from viva.ingest.instrument_observations import ObservationKind,Operation
    from viva.ledger.instruments import append_change,reference_accounts
    from viva.read_store.instrument_authority_contracts import InstrumentRequest
    from test_instrument_authority_views import run
    raw,ledger=setup(tmp_path);bank(raw,ledger)
    data=mortgage();data['payments'][0]['fees']=None
    doc='contextual-initial-source'
    ledger.append(document_captured(doc,'synthetic.pdf',100,'mortgage_statement',1.0,'2021-01-31'))
    text=json.dumps(data);reading=read_recorded(doc,'offline-source-fixture','test','text',text,0,0,0,True,None,'2021-01-31')
    phase=_completed_phase(text,doc,'mortgage_statement')
    from viva.normalization_context import encode_context
    reading.body['normalization_context']=encode_context(phase.normalization_context);ledger.append(reading)
    facts=InstrumentReadFacts(doc,'mortgage_statement',1.0,parse_instrument_json(text,'mortgage_statement',doc),'USD')
    post_instrument(ledger,facts)
    assert len(ledger.projection().instrument_allocations())==1
    original_cash=[event.to_dict() for event in ledger.events() if event.event_type=='TransactionRecorded']
    account=reference_accounts(ledger.projection(),'LOAN-A')[0]
    from viva.ledger import Ledger,EventStore
    for cycle in range(2):
        conflicting=json.loads(json.dumps(data));conflicting['payments'][0]['fees']={'raw':'1','page':1}
        second=ingest(raw,ledger,'conflict-source-'+str(cycle),conflicting,'mortgage_statement')
        assert not ledger.projection().instrument_allocations()
        change=next(row['change'] for row in ledger.projection().core._instrument_observations.values()
            if row['change'].source.doc_id==second.doc_id and row['change'].kind==ObservationKind.MORTGAGE_COMPONENTS)
        append_change(ledger,replace(change,observation_id='retract-conflicting-fee-'+str(cycle),operation=Operation.RETRACT,
            prior_id=change.observation_id,payload=None));heal_instruments(ledger)
        result=run(tmp_path/('restored-authority-'+str(cycle)),ledger,InstrumentRequest('period_components',account,'USD',start='2021-01-01',end='2021-01-31',grouping='month',component_set='payment_escrow'))
        assert next((figure.value for figure in result.figures if figure.claim=='payment_total'),None)=='600'
        assert next((figure.value for figure in result.figures if figure.claim=='payment_net_unallocated'),None)=='0'
        assert not any(figure.claim=='payment_fees' for figure in result.figures)
        allocation=next(iter(ledger.projection().instrument_allocations().values()))
        current=ledger.projection().instrument_component_states()[allocation.receipt.observation_id]
        assert any(part.component=='known_allocation:PAY-A' and part.disposition.value=='accepted' for part in current.components)
        source=ledger.projection().core._instrument_observations[allocation.receipt.observation_id]
        assert not source['superseded'] and source['change'].source.doc_id==doc
        count=len(tuple(ledger.events()))
        assert heal_instruments(ledger)==0 and len(tuple(ledger.events()))==count
        reopened=Ledger(EventStore.open(tmp_path/'events.jsonl','synthetic-passphrase'))
        assert reopened.projection().instrument_allocations()==ledger.projection().instrument_allocations()
        assert heal_instruments(reopened)==0 and len(tuple(reopened.events()))==count
        assert original_cash==[event.to_dict() for event in reopened.events() if event.event_type=='TransactionRecorded']
        assert_known_sql_parity(tmp_path,reopened,'restored-sql-'+str(cycle))
        ledger=reopened


def _completed_phase(text,doc,kind):
    from viva.ingest.reader import read_with_retry
    from viva.ingest.instrument_read import parser_for
    from vivacore.models.base import ModelResult
    result=read_with_retry(lambda prompt:ModelResult(text,'offline-resolved',0,0,0,0,{},{}),
        'offline fixture',doc,'en-US','USD',parse_fn=parser_for(kind),configured_model='offline-source-fixture')
    assert result.facts is not None,result.error
    return result.phases[0]
