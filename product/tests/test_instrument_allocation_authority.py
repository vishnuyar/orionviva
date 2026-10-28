from dataclasses import replace
from time import monotonic
import pytest
from viva.ledger.events import account_opened,document_captured,closing_balance_observed,position_observed,Provenance
from viva.ledger.instruments import append_change
from viva.ingest.instrument_observations import ObservationChange,ObservationKind,Operation
from viva.ingest.instrument_contracts import Source,SourcedDate,SourcedText,PositionClassification,Exposure,Vehicle
from viva.instrument_claims import ResolvedTargetPremise
from viva.read_store import ReadStore
from viva.read_store.instrument_authority import read_instrument_authority
from viva.read_store.instrument_authority_contracts import InstrumentRequest
from test_instrument_projector_b import setup


def snapshot(ledger,doc,*,dated='2025-12-31',bond='70',equity='20',cash='10',currency='USD'):
    source=Source(doc,1)
    ledger.append(document_captured(doc,'synthetic.pdf',10,'retirement_statement',1,dated))
    ledger.append(closing_balance_observed('PLAN',cash,dated,Provenance(doc,1)))
    for instrument,amount,exposure in [('BOND-HOLDING',bond,Exposure.BOND),('EQUITY-HOLDING',equity,Exposure.EQUITY)]:
        if amount is None:continue
        ledger.append(position_observed('PLAN',instrument,'1',amount,currency,dated,provenance=Provenance(doc,1)))
        append_change(ledger,ObservationChange(doc+instrument,'PLAN|'+instrument,ObservationKind.POSITION_CLASSIFICATION,
            SourcedDate(dated,source),Operation.CREATE,source,PositionClassification(SourcedText(instrument,source),
                exposure,Vehicle.MUTUAL_FUND,source,source)))


def read(tmp_path,ledger,*,target=False,as_of='2025-12-31',deadline=None,target_numerator=4,target_denominator=5):
    premise=ResolvedTargetPremise('premise','question','PLAN','USD','bond',as_of,target_numerator,target_denominator,(0,13),(14,18),'my 80% target','bond','%') if target else None
    request=InstrumentRequest('allocation','PLAN','USD',as_of=as_of,axis='exposure',target_premise_ref='premise' if target else None)
    with ReadStore.create(tmp_path/'reads','synthetic-passphrase') as store:
        store.synchronize(ledger.store)
        with store.open_reader() as revision:
            return read_instrument_authority(revision,request,deadline=deadline if deadline is not None else monotonic()+2,target_premise=premise)


def plan(tmp_path):
    raw,ledger=setup(tmp_path)
    ledger.append(account_opened('PLAN','investment','Synthetic plan','USD','2025-01-01'))
    return ledger


def test_complete_same_snapshot_cash_denominator_and_signed_premise(tmp_path):
    ledger=plan(tmp_path);snapshot(ledger,'doc')
    result=read(tmp_path,ledger,target=True)
    figures={f.claim:f for f in result.figures}
    assert figures['allocation_total_value'].value=='100'
    assert figures['allocation_exposure_bond_weight'].value=='0.7'
    assert figures['allocation_percentage_points'].value=='-10'
    assert figures['allocation_percentage_points'].grade is None and figures['allocation_percentage_points'].premise_ref=='premise'
    difference=figures['allocation_percentage_points']
    assert difference.operand_ids==(figures['allocation_exposure_bond_value'].record_id,
        figures['allocation_total_value'].record_id,figures['allocation_exposure_bond_weight'].record_id)
    assert figures['allocation_exposure_bond_weight'].operand_ids==difference.operand_ids[:2]
    assert figures['allocation_exposure_bond_value'].value=='70'
    assert figures['allocation_total_value'].value=='100' # Includes the separate ten-unit cash source.
    assert all(record_id in {figure.record_id for figure in result.figures} for record_id in difference.operand_ids)
    assert result.focus.account=='PLAN' and result.focus.snapshot_date=='2025-12-31'


def test_equal_independent_captures_pool_evidence_without_double_count(tmp_path):
    ledger=plan(tmp_path);snapshot(ledger,'first');snapshot(ledger,'second')
    result=read(tmp_path,ledger)
    figure=next(f for f in result.figures if f.claim=='allocation_total_value')
    assert figure.value=='100' and len(figure.anchor_ids)==2
    assert len([d for d in result.selection_dependencies if d.startswith('position:')])==4


@pytest.mark.parametrize('mutation',['conflict','currency','repeated_position'])
def test_same_date_capture_conflict_never_mixes_rows(tmp_path,mutation):
    ledger=plan(tmp_path);snapshot(ledger,'first')
    if mutation=='conflict':snapshot(ledger,'second',bond='71')
    elif mutation=='currency':snapshot(ledger,'second',currency='EUR')
    else:ledger.append(position_observed('PLAN','BOND-HOLDING','1','70','USD','2025-12-31',provenance=Provenance('first',1)))
    result=read(tmp_path,ledger)
    assert not result.figures and result.dispositions[0].disposition=='unavailable'


@pytest.mark.parametrize('operation',[Operation.CORRECT,Operation.RETRACT])
def test_current_classification_frontier_invalidates_exhaustive_weights(tmp_path,operation):
    ledger=plan(tmp_path);snapshot(ledger,'doc')
    prior=ledger.projection().core._instrument_observations['docBOND-HOLDING']['change']
    replacement=None if operation==Operation.RETRACT else replace(prior.payload,exposure=Exposure.UNKNOWN,exposure_source=None)
    append_change(ledger,replace(prior,observation_id='changed',operation=operation,prior_id=prior.observation_id,payload=replacement))
    result=read(tmp_path,ledger,target=True)
    assert not any(f.claim.endswith('_weight') or f.claim=='allocation_percentage_points' for f in result.figures)
    assert next(f.value for f in result.figures if f.claim=='allocation_unclassified_value')=='70'


def test_latest_cash_only_snapshot_does_not_reuse_old_positions(tmp_path):
    ledger=plan(tmp_path);snapshot(ledger,'old',dated='2025-11-30')
    snapshot(ledger,'latest',bond=None,equity=None,cash='25')
    result=read(tmp_path,ledger)
    figures={f.claim:f.value for f in result.figures}
    assert figures['allocation_total_value']=='25' and figures['allocation_exposure_cash_weight']=='1'


def test_deadline_refuses_before_query_and_zero_denominator_is_explicit(tmp_path):
    ledger=plan(tmp_path);snapshot(ledger,'zero',bond='0',equity='0',cash='0')
    result=read(tmp_path,ledger)
    assert not any(f.claim.endswith('_weight') for f in result.figures)


def test_rounded_display_weight_does_not_replace_sourced_point_operands(tmp_path):
    ledger=plan(tmp_path)
    snapshot(ledger,'source',bond='164129.58',equity='75973.3',cash='10')
    result=read(tmp_path,ledger,target=True,target_numerator=7,target_denominator=10)
    figures={figure.claim:figure for figure in result.figures}
    numerator=figures['allocation_exposure_bond_value'];total=figures['allocation_total_value']
    weight=figures['allocation_exposure_bond_weight'];difference=figures['allocation_percentage_points']
    assert (numerator.value,total.value,difference.value)==('164129.58','240112.88','-1.64482472')
    assert not weight.exact
    assert difference.operand_ids==(numerator.record_id,total.record_id,weight.record_id)
    assert difference.premise_ref=='premise' and difference.grade is None
    assert numerator.observation_ids==total.observation_ids==difference.observation_ids
