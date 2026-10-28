"""Dedicated source meanings cannot pass through generic numerical authorities."""
from decimal import Decimal
from types import SimpleNamespace
import pytest
from viva import quantity
from viva.tools.compute import compute
from viva.tools.runner_binding import _figure_bound
from viva.query.execute import FinancialQueryExecutor,QueryTable,QueryRow,QueryError

NEW=("deposit_contract_principal","loan_original_principal","instrument_rate","allocation_percentage_points")
def raw(quantity):
    return dict(id="f1",value="0.0525" if quantity=="instrument_rate" else "100",currency="" if quantity in NEW[2:] else "USD",quantity=quantity,kind="financial",grade="verified",record_ids=["doc"],dated="2025-12-31",exactness="exact",boundary={},what="Source value",claim="loan_note_rate" if quantity=="instrument_rate" else quantity)

@pytest.mark.parametrize('kind',NEW)
def test_dedicated_quantities_have_permanent_names(kind):
    assert kind in quantity.KINDS
    assert kind not in quantity.COMPARABLE

@pytest.mark.parametrize('kind',NEW)
@pytest.mark.parametrize('expression',['a','a+a','a-a','a*1','a/1','a/a','-a'])
def test_generic_compute_refuses_every_dedicated_operand(kind,expression):
    result=compute({'expression':expression,'inputs':{'a':'f1'}},{'f1':raw(kind)})
    assert not result.ok
    assert result.refusal=='dedicated_authority_required'

@pytest.mark.parametrize('kind',NEW)
def test_generic_query_cannot_aggregate_dedicated_money_or_ratios(kind):
    is_money=kind in NEW[:2]
    row=QueryRow({'value':Decimal('100'),'currency':'USD'},('doc',),'verified')
    table=QueryTable((row,),{'value':'Money' if is_money else 'Decimal','currency':'Currency'},quantities={'value':kind},currency_fields={'value':'currency'} if is_money else {})
    with pytest.raises(QueryError,match='dedicated'):
        FinancialQueryExecutor(None)._apply('aggregate',[table],{'field':'value','function':'sum','output':'total','currency_field':'currency' if is_money else ''})

@pytest.mark.parametrize('kind',NEW)
def test_raw_json_cannot_forge_a_dedicated_bound_figure(kind):
    slot=SimpleNamespace(name='value',type='money' if kind in NEW[:2] else 'rate',quantity=kind,scope=())
    written,reason,_=_figure_bound(slot,raw(kind),'en-US')
    assert written is None
    assert reason=='instrument_authority_required'


@pytest.mark.parametrize("kind",NEW)
def test_admitted_vocabulary_compute_guard_removed_counterfactual_detects_laundering(kind,monkeypatch):
    # Unlike the original unknown-enum baseline, this reaches numerical code
    # with every new quantity admitted. Removing only the dedicated guard is
    # the deliberately unsafe counterfactual; the normal assertion must fail it.
    assert kind in quantity.KINDS
    normal=compute({"expression":"a","inputs":{"a":"f1"}},{"f1":raw(kind)})
    assert not normal.ok and normal.refusal=="dedicated_authority_required"
    monkeypatch.setattr(quantity,"DEDICATED",frozenset())
    unsafe=compute({"expression":"a","inputs":{"a":"f1"}},{"f1":raw(kind)})
    assert unsafe.ok and unsafe.figures[0]["quantity"]==kind

@pytest.mark.parametrize("kind",NEW)
def test_admitted_query_emission_guard_removed_counterfactual_detects_laundering(kind,monkeypatch):
    is_money=kind in NEW[:2]
    boundary={"whole":True,"accounts":{"counted":1,"held":1},"selected":[],"cut":[]}
    row=QueryRow({"value":Decimal("100"),"currency":"USD" if is_money else "","boundary":boundary},("doc",),"verified")
    table=QueryTable((row,),{"value":"Money" if is_money else "Decimal","currency":"Currency","boundary":"Boundary"},quantities={"value":kind},currency_fields={"value":"currency"} if is_money else {},boundary_fields={"value":"boundary"})
    spec={"value_field":"value","quantity":kind,"currency_field":"currency" if is_money else ""}
    with pytest.raises(QueryError,match="dedicated"):FinancialQueryExecutor(None)._emit(table,spec)
    monkeypatch.setattr(quantity,"DEDICATED",frozenset())
    unsafe=FinancialQueryExecutor(None)._emit(table,spec)
    assert unsafe.ok and unsafe.figures[0]["quantity"]==kind

@pytest.mark.parametrize("kind",NEW)
def test_admitted_binder_authentication_guard_removed_counterfactual(kind,monkeypatch):
    from viva import instrument_evidence
    fig=raw(kind)
    if kind=="allocation_percentage_points":fig.update(kind="hypothetical",grade="",value="+10")
    slot=SimpleNamespace(name="value",type="money" if kind in NEW[:2] else "percentage_points" if kind==NEW[3] else "rate",quantity=kind,scope=())
    assert _figure_bound(slot,fig,"en-US")[1]=="instrument_authority_required"
    monkeypatch.setattr(instrument_evidence,"authenticated_figure",lambda _:True)
    written,tag,_=_figure_bound(slot,fig,"en-US")
    assert written is not None and not tag


@pytest.mark.parametrize("kind",NEW)
def test_dynamic_query_row_quantity_cannot_bypass_dedicated_guard(kind):
    row=QueryRow({"value":Decimal("100"),"quantity":kind,"currency":"USD"},("doc",),"verified")
    table=QueryTable((row,),{"value":"EvidenceMagnitude","quantity":"Quantity","currency":"Currency"})
    with pytest.raises(QueryError,match="dedicated"):
        FinancialQueryExecutor(None)._apply("select",[table],{"fields":["value"]})
    with pytest.raises(QueryError,match="dedicated"):
        FinancialQueryExecutor(None)._emit(table,{"value_field":"value","quantity":kind})
