"""The row renderer accepts only exact source-authenticated security quantities."""
import copy
import pytest
from _source_emitter_support import source_emitter_results
from viva import render
from viva.tools.runner_binding import _MAGNITUDE_WRITERS


def test_security_units_row_writer_uses_actual_source_and_refuses_mutations():
    result=next(item for item in source_emitter_results() if item.tool=='read_investment_evidence')
    figure=next(item for item in result.figures if item['quantity']=='security_units')
    writer=_MAGNITUDE_WRITERS[render.SECURITY_UNITS]
    assert writer(figure['value'],figure,'en-US')==render.security_units(figure['value'],locale='en-US')
    for key,value in [('value','2'),('currency','USD'),('quantity','count'),('exactness','approximate')]:
        changed=copy.deepcopy(figure);changed[key]=value
        with pytest.raises(ValueError):writer(changed['value'],changed,'en-US')


def test_security_model_entity_uses_its_canonical_security_identity():
    from viva.tools.envelope import _named
    result=next(item for item in source_emitter_results() if item.tool=='read_investment_evidence')
    item=result.identifiers[0]
    assert item['kind']=='security'
    assert _named(item)['label']==item['security_id']
    assert _named({'kind':'account','account':'Assets:Checking','name':'Friendly'})['label']=='Assets:Checking'
