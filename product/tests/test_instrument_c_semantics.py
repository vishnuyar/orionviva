from viva.answer_program.intents import SemanticFamilyRegistry
from viva.tools import default_registry
from viva.answer_program import CapabilityManifest,ProgramValidator,AnswerResourcePolicy
from viva.answer_program.schema import QuestionContext
from test_instrument_c_binding import fixture

def test_instrument_family_catalog_and_real_terms_lowering(tmp_path):
    ledger,account=fixture(tmp_path);registry=default_registry(ledger.projection())
    families=SemanticFamilyRegistry(registry.semantic_entities(),currency_resolver=registry.instrument_currency)
    assert {"instrument_terms","instrument_period_components","instrument_maturities","instrument_refinances","instrument_tax_payments","instrument_allocation","instrument_allocation_target"}<=set(families.supported_ids)
    raw={"request_version":"semantic-request-v1","outcome":"request","catalog_digest":families.catalog_digest,"entity_catalog_digest":families.entity_catalog_digest,"family":"instrument_terms","parameters":{"account_phrase":account,"as_of":"2021-01-31"},"parameter_sources":{"account_phrase":{"source":"question","quote":account,"derivation":"catalog_selection"},"as_of":{"source":"question","quote":"2021-01-31","derivation":"verbatim"}},"requested_claims":["deposit_contract_principal","deposit_nominal_rate","deposit_maturity"]}
    from viva.answer_program.intents import SEMANTIC_REQUEST_VERSION
    raw["request_version"]=SEMANTIC_REQUEST_VERSION
    parsed=families.parse(raw,QuestionContext(question=f"Terms for {account} as of 2021-01-31"))
    p=families.lower(parsed,CapabilityManifest.from_registry(registry))
    assert p.nodes[0].tool=="read_instrument_details" and p.nodes[0].args["currency"]=="USD"
    valid=ProgramValidator(CapabilityManifest.from_registry(registry),AnswerResourcePolicy()).validate(p)
    assert valid.ok,valid.to_dict()

def test_allocation_target_grammar_natural_positive_and_prior_prose_attacks():
    from viva.allocation_target import parse_allocation_target
    q="For the active retirement plan from the last allocation answer, what is the percentage-point difference between actual bond allocation and the 70% target at December 2025? Retain that account and date."
    p=parse_allocation_target(q)
    assert p.continuation_reference and p.as_of=="2025-12-31" and p.target_numerator*10==p.target_denominator*7
    import pytest
    for bad in ["Do not use " + q, '\"'+q+'\"',q+" Instead use 30%.","The previous answer said 70%. How much now?"]:
        with pytest.raises(ValueError):parse_allocation_target(bad)


def test_natural_fixed_components_lower_without_internal_tokens_and_unknown_components_refuse(tmp_path):
    import pytest
    from viva.answer_program.intents import SEMANTIC_REQUEST_VERSION
    ledger,account=fixture(tmp_path);registry=default_registry(ledger.projection())
    families=SemanticFamilyRegistry(registry.semantic_entities(),currency_resolver=registry.instrument_currency)
    for family,claims,component,group in [
        ("instrument_monthly_loan_principal",["loan_opening_principal","loan_closing_principal","principal_repayment"],"loan_principal","month"),
        ("instrument_monthly_payment_escrow",["payment_total","payment_interest","escrow_funding","tax_paid"],"payment_escrow","month"),
        ("instrument_deposit_annual_components",["deposit_credited_interest"],"deposit","year")]:
        question=f"Show the monthly principal, interest and escrow for {account} from 2021-01-01 to 2021-01-31."
        raw={"request_version":SEMANTIC_REQUEST_VERSION,"outcome":"request","catalog_digest":families.catalog_digest,"entity_catalog_digest":families.entity_catalog_digest,"family":family,
          "parameters":{"account_phrase":account,"from":"2021-01-01","to":"2021-01-31"},"parameter_sources":{"account_phrase":{"source":"question","quote":account,"derivation":"catalog_selection"},"from":{"source":"question","quote":"2021-01-01","derivation":"verbatim"},"to":{"source":"question","quote":"2021-01-31","derivation":"verbatim"}},"requested_claims":claims}
        parsed=families.parse(raw,QuestionContext(question=question));p=families.lower(parsed,CapabilityManifest.from_registry(registry))
        assert p.nodes[0].args["component_set"]==component and p.nodes[0].args["grouping"]==group
        checked=ProgramValidator(CapabilityManifest.from_registry(registry),AnswerResourcePolicy()).validate(p)
        assert checked.ok,checked.to_dict()
        bad={**raw,"parameters":{**raw["parameters"],"component_set":"unreviewed"}}
        with pytest.raises(ValueError):families.parse(bad,QuestionContext(question=question))
        assert families.parse({**raw,"family":"instrument_unreviewed"},QuestionContext(question=question)).kind=="unsupported"


def test_added_admission_dependencies_are_each_authenticated_without_importing_tiers(monkeypatch,tmp_path):
    import pathlib,hashlib
    from viva.answer_program.intents import SemanticFamilyRegistry
    original=SemanticFamilyRegistry._admitted_source_only_paths
    baseline=SemanticFamilyRegistry._admitted_implementation_digests()
    for module in ("viva.read_store.instrument_authority","viva.allocation_continuation","viva.ingest.apr_context_local"):
        key="instrument_dependency:"+module
        source=tmp_path/(module.replace(".","_")+".py");source.write_bytes(b"# changed required dependency\n")
        def replaced(resources=None,*,chosen=key,path=source):
            paths=original(resources)
            return {**paths,chosen:path} if resources is not None else paths
        monkeypatch.setattr(SemanticFamilyRegistry,"_admitted_source_only_paths",staticmethod(replaced))
        changed=SemanticFamilyRegistry._admitted_implementation_digests()
        assert changed[key]==hashlib.sha256(source.read_bytes()).hexdigest()[:16] and changed[key]!=baseline[key]
        assert all(changed[k]==value for k,value in baseline.items() if k!=key)


def test_monthly_combined_family_has_only_grounded_account_and_period():
    families=SemanticFamilyRegistry()
    family=families.get('instrument_monthly_loan_payments')
    assert family is not None
    assert set(family.parameter_schema['properties'])=={'account_phrase','from','to'}
    assert set(family.claims)=={'principal_repayment','payment_total','payment_interest','escrow_funding'}


def test_generic_payment_escrow_rejects_unreachable_principal_claims(tmp_path):
    import pytest
    from viva.answer_program.intents import SEMANTIC_REQUEST_VERSION
    from viva.answer_program.schema import ContractError
    ledger,account=fixture(tmp_path);registry=default_registry(ledger.projection())
    families=SemanticFamilyRegistry(registry.semantic_entities(),currency_resolver=registry.instrument_currency)
    params={'account_phrase':account,'from':'2021-01-01','to':'2021-01-31','grouping':'month','component_set':'payment_escrow'}
    proofs={name:{'source':'question','quote':value,'derivation':'catalog_selection' if name=='account_phrase' else 'verbatim'} for name,value in params.items()}
    raw={'request_version':SEMANTIC_REQUEST_VERSION,'outcome':'request','catalog_digest':families.catalog_digest,'entity_catalog_digest':families.entity_catalog_digest,'family':'instrument_period_components','parameters':params,'parameter_sources':proofs,'requested_claims':['principal_repayment']}
    context=QuestionContext(question=' '.join(params.values()))
    for claim in ('principal_repayment','principal_payoff'):
        with pytest.raises(ContractError,match='component_claim_incompatible'):
            families.parse({**raw,'requested_claims':[claim]},context)
    assert families.parse({**raw,'requested_claims':['payment_total']},context).kind=='request'


_MONTHLY_CLAIMS=('principal_repayment','payment_total','payment_interest','escrow_funding')


def _monthly_source_fixture(tmp_path,*,defect=None,extra_principal=False):
    import json,calendar
    from test_instrument_projector_b import setup,ingest,mortgage
    from test_instrument_contracts import printed
    from viva.ingest import ReadResult,capture_and_ingest
    from viva.ingest.statement import from_model_json
    from viva.ledger.instruments import reference_accounts
    raw,ledger=setup(tmp_path)
    checking={'doc_type':'checking_statement','doc_type_confidence':1,'institution':'Fixture Bank','account_ref':'Fixture Checking','account_names':['Synthetic Person'],'source_account_ref':'CHECK-A','source_account_ref_page':1,
        'opening':{'amount_raw':'3000','date_raw':'2021-01-01','page':1},'closing':{'amount_raw':'1200','date_raw':'2021-03-31','page':1},
        'transactions':[{'amount_raw':'600','balance_effect':'decrease','date_raw':f'2021-{month:02d}-15','page':1,'description':'Printed mortgage payment','source_reference':f'PAY-{month}','counterparty_reference':'LOAN-A'} for month in (1,2,3)]}
    def read(blob,doc_id):
        facts,error=from_model_json(json.dumps(checking),doc_id,'en-US','USD');assert error is None
        return ReadResult('checking_statement',1.0,facts)
    capture_and_ingest(raw,ledger,b'public-three-month-checking',read)
    documents=[];sources=[];principal=1000
    for month in (1,2,3):
        if defect=='missing_month' and month==2:continue
        data=mortgage();end=f'2021-{month:02d}-{calendar.monthrange(2021,month)[1]}'
        data.update(start=printed(f'2021-{month:02d}-01'),end=printed(end),opening_principal=printed(principal),closing_principal=printed(principal-100))
        for item in data['principal_movements']+data['payments']:
            item.update(dated=printed(f'2021-{month:02d}-15'),reference=printed(f'PAY-{month}'))
        if extra_principal and month==2:
            data['principal_movements'].append({'kind':'principal_reduction','amount':printed('25'),'dated':printed('2021-02-21'),'reference':printed('EXTRA-2')})
            data['closing_principal']=printed(principal-125)
        principal-=125 if extra_principal and month==2 else 100
        data['escrow'].update(opening=printed((month-1)*200),closing=printed(month*200))
        for movement in data['escrow']['movements']:
            movement['dated']=printed(f'2021-{month:02d}-'+('15' if movement['kind']=='deposit' else '20'))
            movement['reference']=printed(f'PAY-{month}' if movement['kind']=='deposit' else f'TAX-{month}')
        if defect=='held_principal' and month==2:data['closing_principal']=printed(principal+1)
        if defect=='missing_escrow' and month==2:data['escrow'].pop('identity')
        source=ingest(raw,ledger,f'public-mortgage-{month}',data,'mortgage_statement')
        documents.append(source.doc_id);sources.append(data)
    return ledger,reference_accounts(ledger.projection(),'LOAN-A')[0],documents,sources


def _monthly_semantic_program(registry,account,*,mode='native',months=False,prior=False,mutate=None):
    import json
    from viva.answer_program.intents import SEMANTIC_REQUEST_VERSION
    from viva.tools.registry import _validate
    families=SemanticFamilyRegistry(registry.semantic_entities(),currency_resolver=registry.instrument_currency)
    question=f'Show monthly mortgage payments with principal, interest and escrow for {account} from '+('January 2021 through March 2021.' if months else '2021-01-01 through 2021-03-31.')
    proofs={'account_phrase':{'source':'question','quote':account,'derivation':'catalog_selection'},'from':{'source':'question','quote':'January 2021' if months else '2021-01-01','derivation':'calendar_month_start' if months else 'verbatim'},'to':{'source':'question','quote':'March 2021' if months else '2021-03-31','derivation':'calendar_month_end' if months else 'verbatim'}}
    context=QuestionContext(question=question)
    if prior:
        context=QuestionContext(question='Show that loan and period with monthly principal, payment total, interest and escrow.',prior_turns=(('Unrelated question.','Recorded.'),(question,'Please clarify the requested components.')))
        proofs={key:{**value,'source':'prior_turn','turn':1} for key,value in proofs.items()}
    output={'request_version':SEMANTIC_REQUEST_VERSION,'outcome':'request','catalog_digest':families.catalog_digest,'entity_catalog_digest':families.entity_catalog_digest,'family':'instrument_monthly_loan_payments','parameters':{'account_phrase':{'catalog_id':account},'from':'2021-01-01','to':'2021-03-31'},'parameter_sources':proofs,'requested_claims':list(_MONTHLY_CLAIMS)}
    if mutate:mutate(output)
    if mode=='native':
        tool=next(t for t in families.model_tools() if t['name']=='select_instrument_monthly_loan_payments')
        assert not _validate(tool['parameters'],{key:output[key] for key in ('parameters','parameter_sources','requested_claims')})
    else:
        assert not _validate(families.model_output_schema(),output)
        output=json.loads(json.dumps(output))
    outcome=families.parse(families.materialize_model_output(output),context)
    assert outcome.kind=='request',outcome.to_dict()
    manifest=CapabilityManifest.from_registry(registry);program=families.lower(outcome,manifest)
    validation=ProgramValidator(manifest,AnswerResourcePolicy()).validate(program)
    assert validation.ok,validation.to_dict()
    return program,context


def test_combined_monthly_real_three_source_path_and_one_revision(tmp_path,monkeypatch):
    from contextlib import contextmanager
    from time import monotonic
    from decimal import Decimal
    from viva.read_store import ReadStore
    from viva.answer_program import ProgramExecutor,DeterministicBinder
    import viva.read_store.instrument_authority as tool
    ledger,account,documents,sources=_monthly_source_fixture(tmp_path)
    observed=[];revisions=[];real=tool.read_instrument_authority
    def instrumented(revision,request,*,deadline,**kwargs):
        observed.append((id(revision),request,deadline,monotonic()))
        return real(revision,request,deadline=deadline,**kwargs)
    monkeypatch.setattr(tool,'read_instrument_authority',instrumented)
    with ReadStore.create(tmp_path/'read','synthetic-passphrase') as store:
        store.synchronize(ledger.store)
        @contextmanager
        def supplier():
            with store.open_reader() as revision:
                revisions.append(id(revision));yield revision
        registry=default_registry(ledger.projection(),instrument_scope=supplier)
        program,context=_monthly_semantic_program(registry,account,months=True)
        # Semantic currency resolution authenticates its own earlier read.
        assert len(revisions)==1
        semantic_revision_count=len(revisions)
        policy=AnswerResourcePolicy();execution=ProgramExecutor(registry,policy).execute(program,context.question)
        bound=DeterministicBinder(registry,'en-US').bind(program,execution)
        assert bound.result.answered,(bound.unbound,bound.result.detail)
        assert len(revisions)==semantic_revision_count+1 and len(observed)==2
        assert {r[0] for r in observed}=={revisions[-1]}
        assert all(0<deadline-now<=2 for _,_,deadline,now in observed)
        assert {r.component_set for _,r,_,_ in observed}=={'loan_principal','payment_escrow'}
        assert all((r.account,r.currency,r.start,r.end,r.grouping)==(account,'USD','2021-01-01','2021-03-31','month') for _,r,_,_ in observed)
        assert not execution.deadline_exceeded and not execution.figure_limit_exceeded and not execution.evidence_limit_exceeded
        assert len(bound.result.figures)==12
        for claim in _MONTHLY_CLAIMS:
            rows=[f for f in bound.result.figures if f['claim']==claim]
            assert len(rows)==3
            field={'payment_total':'total','payment_interest':'interest','escrow_funding':'escrow'}.get(claim)
            expected=[sum((Decimal(m['amount']['raw']) for m in source['principal_movements']),Decimal(0)) if field is None else Decimal(source['payments'][0][field]['raw']) for source in sources]
            assert sorted(Decimal(f['value']) for f in rows)==sorted(expected)
            periods={(cut['value'],cut['to']) for figure in rows for cut in figure['boundary']['cut'] if cut['kind']=='period'}
            assert periods=={(source['start']['raw'],source['end']['raw']) for source in sources}
            assert all(f['grade'] in {'verified','corroborated'} for f in rows)
            assert all(f['record_ids'] and set(f['record_ids'])<=set(documents) and f['observation_ids'] and f['anchor_ids'] for f in rows)
        assert registry.instrument_runtime.revision is None
        assert len({binding.source for binding in program.bindings})==2
        assert policy==AnswerResourcePolicy()


def test_combined_model_protocols_month_edges_and_supplied_prior_turns(tmp_path):
    from viva.read_store import ReadStore
    ledger,account,_,_=_monthly_source_fixture(tmp_path)
    registry=default_registry(ledger.projection())
    for mode in ('native','text'):
        for months in (False,True):
            for prior in (False,True):
                program,_=_monthly_semantic_program(registry,account,mode=mode,months=months,prior=prior)
                assert len(program.nodes)==2 and len(program.bindings)==4


def test_combined_bad_grounding_remains_rejected(tmp_path):
    import pytest
    from viva.answer_program.schema import ContractError
    ledger,account,_,_=_monthly_source_fixture(tmp_path);registry=default_registry(ledger.projection())
    attacks=[
        lambda d:d['parameters']['account_phrase'].update(catalog_id='forged-account'),
        lambda d:d['parameter_sources']['from'].update(derivation='calendar_month_end'),
        lambda d:d['parameter_sources']['from'].update(source='prior_turn',turn=8),
        lambda d:d['parameter_sources']['from'].update(quote='January ... 2021'),
        lambda d:d['parameter_sources']['from'].update(quote='first month of 2021'),
        lambda d:d['parameters'].update(**{'from':'2021-01-02'}),
    ]
    for attack in attacks:
        with pytest.raises((ContractError,AssertionError)):
            _monthly_semantic_program(registry,account,months=True,mutate=attack)


def test_combined_missing_or_held_sources_never_make_complete_zero_answer(tmp_path):
    from viva.read_store import ReadStore
    from viva.answer_program import ProgramExecutor,DeterministicBinder
    for defect in ('held_principal','missing_escrow','missing_month'):
        folder=tmp_path/defect;ledger,account,_,_=_monthly_source_fixture(folder,defect=defect)
        with ReadStore.create(folder/'read','synthetic-passphrase') as store:
            store.synchronize(ledger.store);registry=default_registry(ledger.projection(),instrument_scope=store.open_reader)
            program,context=_monthly_semantic_program(registry,account)
            answer=DeterministicBinder(registry,'en-US').bind(program,ProgramExecutor(registry,AnswerResourcePolicy()).execute(program,context.question)).result
            assert not answer.answered and not answer.figures


def test_combined_extra_principal_is_independent_monthly_series(tmp_path):
    from decimal import Decimal
    from viva.read_store import ReadStore
    from viva.answer_program import ProgramExecutor,DeterministicBinder
    ledger,account,_,_=_monthly_source_fixture(tmp_path,extra_principal=True)
    with ReadStore.create(tmp_path/'read','synthetic-passphrase') as store:
        store.synchronize(ledger.store);registry=default_registry(ledger.projection(),instrument_scope=store.open_reader)
        program,context=_monthly_semantic_program(registry,account)
        result=DeterministicBinder(registry,'en-US').bind(program,ProgramExecutor(registry,AnswerResourcePolicy()).execute(program,context.question)).result
        assert result.answered,result.detail
        assert sorted(Decimal(f['value']) for f in result.figures if f['claim']=='principal_repayment')==[Decimal(100),Decimal(100),Decimal(125)]
        assert {Decimal(f['value']) for f in result.figures if f['claim']=='payment_total'}=={Decimal(600)}


def test_combined_exact_selectors_and_citation_integrity_remain_required(tmp_path,monkeypatch):
    import copy
    from viva.read_store import ReadStore
    from viva.answer_program import ProgramExecutor,DeterministicBinder
    from viva.answer_program.schema import AnswerProgram
    import viva.tools.instruments as adapter
    ledger,account,_,_=_monthly_source_fixture(tmp_path)
    original=adapter.read_instrument_details
    mutation=[None]
    def changed(runtime,args):
        result=original(runtime,args)
        if result.ok and mutation[0]:
            for figure in result.figures:
                if figure['claim']=='principal_repayment':mutation[0](figure)
        return result
    monkeypatch.setattr(adapter,'read_instrument_details',changed)
    with ReadStore.create(tmp_path/'read','synthetic-passphrase') as store:
        store.synchronize(ledger.store);registry=default_registry(ledger.projection(),instrument_scope=store.open_reader)
        program,context=_monthly_semantic_program(registry,account)
        for name,value in [('currency','EUR'),('entity_ref',{'id':'foreign-account'}),('claim','principal_payoff')]:
            data=copy.deepcopy(program.to_dict());data['bindings'][0]['selector'][name]=value
            wrong=AnswerProgram.from_dict(data)
            validation=ProgramValidator(CapabilityManifest.from_registry(registry),AnswerResourcePolicy()).validate(wrong)
            if validation.ok:
                answer=DeterministicBinder(registry,'en-US').bind(wrong,ProgramExecutor(registry,AnswerResourcePolicy()).execute(wrong,context.question)).result
                assert not answer.answered and not answer.figures
        for attack in [lambda f:f.update(record_ids=[]),lambda f:f.update(record_ids=['foreign-document']),lambda f:f.update(anchor_ids=[]),lambda f:f.update(anchor_ids=['foreign-page-99'])]:
            mutation[0]=attack
            answer=DeterministicBinder(registry,'en-US').bind(program,ProgramExecutor(registry,AnswerResourcePolicy()).execute(program,context.question)).result
            assert not answer.answered and not answer.figures


def test_combined_source_identity_change_before_or_after_execution_refuses(tmp_path):
    from contextlib import contextmanager
    from viva.read_store import ReadStore
    from viva.answer_program import ProgramExecutor,DeterministicBinder
    ledger,account,_,_=_monthly_source_fixture(tmp_path)
    with ReadStore.create(tmp_path/'read','synthetic-passphrase') as store:
        store.synchronize(ledger.store)
        @contextmanager
        def supplier():
            with store.open_reader() as revision:yield revision
        registry=default_registry(ledger.projection(),instrument_scope=supplier)
        program,context=_monthly_semantic_program(registry,account)
        supplier.expected_projection_identity=ledger.store.authenticated_identity()
        for changed_at in (0,1):
            checks=[]
            def identity():
                checks.append(True)
                return supplier.expected_projection_identity if len(checks)<=changed_at else ('foreign-revision',)
            supplier.source_identity=identity
            execution=ProgramExecutor(registry,AnswerResourcePolicy()).execute(program,context.question)
            answer=DeterministicBinder(registry,'en-US').bind(program,execution).result
            assert not answer.answered and not answer.figures
            assert all(node.refusal=='current_data_unavailable' for node in execution.nodes.values())


def test_combined_complete_and_held_sources_through_actual_conversation_runtime(tmp_path):
    import json
    from decimal import Decimal
    from types import SimpleNamespace
    from viva.read_store import ReadStore
    from viva.answer_program import AnswerProgramCompiler,ProgramExecutor,DeterministicBinder
    from viva.answer_program.runtime import AnswerProgramRuntime
    from viva.persona import moment
    for defect in (None,'missing_escrow'):
        folder=tmp_path/('complete' if defect is None else defect)
        ledger,account,_,_=_monthly_source_fixture(folder,defect=defect)
        question=f'For {account}, show monthly principal, payment total, interest and escrow from January 2021 through March 2021.'
        class Adapter:
            def converse(self,messages,tools):
                arguments={'parameters':{'account_phrase':{'catalog_id':account},'from':'2021-01-01','to':'2021-03-31'},'parameter_sources':{'account_phrase':{'source':'question','quote':account,'derivation':'catalog_selection'},'from':{'source':'question','quote':'January 2021','derivation':'calendar_month_start'},'to':{'source':'question','quote':'March 2021','derivation':'calendar_month_end'}},'requested_claims':list(_MONTHLY_CLAIMS)}
                return SimpleNamespace(request={'messages':True},response={'usage':{'input_tokens':3}},input_tokens=3,output_tokens=2,cost_usd=0,latency_s=.01,resolved_model='synthetic-semantic',tool_calls=[{'function':{'name':'select_instrument_monthly_loan_payments','arguments':json.dumps(arguments)}}])
        with ReadStore.create(folder/'read','synthetic-passphrase') as store:
            store.synchronize(ledger.store);registry=default_registry(ledger.projection(),instrument_scope=store.open_reader)
            manifest=CapabilityManifest.from_registry(registry);policy=AnswerResourcePolicy()
            compiler=AnswerProgramCompiler(Adapter(),ProgramValidator(manifest,policy),manifest,policy)
            compiler.set_entity_catalog(registry.semantic_entities());compiler.set_instrument_currency_resolver(registry.instrument_currency)
            runtime=AnswerProgramRuntime(compiler,ProgramExecutor(registry,policy),DeterministicBinder(registry,'en-US'))
            result=runtime.answer(QuestionContext(question=question,capability_manifest_digest=manifest.digest))
            assert result.compilation.ok and result.execution is not None
            if defect is None:
                assert result.result.status=='answered' and len(result.result.figures)==12
            else:
                assert result.result.status=='missing_data' and not result.result.figures
                assert result.result.text and 'went astray' not in result.result.text.casefold()
                assert result.result.missing and all(item['reason']=='no_compatible_evidence' for item in result.result.missing)
                assert all(node.status=='completed' for node in result.execution.nodes.values())
                assert result.outcome.tag == 'unbound_evidence'
                assert result.result.text == 'I do not have enough supported information to answer that question.'
                principal = [figure for read in result.execution.transcript
                             for figure in read.figures if figure['claim'] == 'principal_repayment']
                assert len(principal) == 3
                assert sorted(Decimal(figure['value']) for figure in principal) == [Decimal(100)] * 3



def test_combined_single_branch_requests_keep_every_requested_effect(tmp_path):
    from dataclasses import replace
    from viva.answer_program.intents import SemanticOutcome
    ledger,account,_,_=_monthly_source_fixture(tmp_path);registry=default_registry(ledger.projection())
    families=SemanticFamilyRegistry(registry.semantic_entities(),currency_resolver=registry.instrument_currency)
    program,_=_monthly_semantic_program(registry,account)
    from viva.answer_program.intents import SemanticRequest
    for claims,component in [(('principal_repayment',),'loan_principal'),(('payment_interest','escrow_funding'),'payment_escrow')]:
        request=SemanticRequest('instrument_monthly_loan_payments',{'account_phrase':account,'currency':'USD','from':'2021-01-01','to':'2021-03-31'},claims,families.catalog_digest)
        lowered=families.lower(SemanticOutcome('request',request),CapabilityManifest.from_registry(registry))
        assert len(lowered.nodes)==1 and lowered.nodes[0].args['component_set']==component
        assert tuple(b.selector.claim for b in lowered.bindings)==claims
        assert len(lowered.result_policy["required_clauses"])==len(claims)


def test_outside_domain_retains_its_structure_with_truthful_generic_refusal():
    from types import SimpleNamespace
    from viva.answer_program.runtime import AnswerProgramRuntime
    result = AnswerProgramRuntime._non_answer(
        SimpleNamespace(mode="outside_domain"), SimpleNamespace(exchanges=[]))
    assert result.result.status == 'outside_domain'
    assert result.result.refusal == result.outcome.tag == 'outside_domain'
    assert not result.result.figures and result.execution is None
    assert result.result.text == result.outcome.text == 'I do not have enough supported information to answer that question.'
