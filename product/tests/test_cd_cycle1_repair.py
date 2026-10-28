"""Independent-boundary reproductions retained for the C/D first repair."""
import json
from types import SimpleNamespace
import pytest
from viva.tools.envelope import scoped_grade_sentence,scope_saved_grade
from viva.persona import moment
from viva.answer_program.intents import SemanticFamilyRegistry
from viva.tools import default_registry
from test_instrument_c_binding import fixture
from test_instrument_c_continuation import opened,actions,allocation_step,target_step,Q029


def test_private_currency_never_enters_labels_and_missing_or_ambiguous_authority_refuses(tmp_path):
    ledger,account=fixture(tmp_path);registry=default_registry(ledger.projection());catalog=registry.semantic_entities()
    assert all(set(row)=={'id','name','institution','kind'} for row in catalog['accounts'])
    assert 'currency' not in json.dumps(catalog).lower()
    plain=SemanticFamilyRegistry(catalog)
    with pytest.raises(ValueError):plain.resolve_instrument_currency(account)
    private=SemanticFamilyRegistry(catalog,currency_resolver=registry.instrument_currency)
    assert private.resolve_instrument_currency(account)=='USD'
    assert plain.entity_catalog_digest==private.entity_catalog_digest and plain.entity_catalog==private.entity_catalog
    with pytest.raises(ValueError):private.resolve_instrument_currency('foreign-account')
    for currencies in ([],['USD','EUR'],['usd'],['']):
        rows=[SimpleNamespace(account=account,currency=value) for value in currencies]
        held=default_registry(SimpleNamespace(account_infos=lambda:rows))
        with pytest.raises(ValueError):held.instrument_currency(account)


@pytest.mark.parametrize('target,hypothetical,ending',[(True,True,'User-stated targets and hypothetical results have no bank evidence grade.'),(True,False,'User-stated targets have no bank evidence grade.'),(False,True,'Hypothetical results have no bank evidence grade.')])
def test_grade_copy_selects_only_actually_delivered_categories_and_saved_scope(target,hypothetical,ending):
    figures=[{'kind':'financial','grade':'corroborated'}]+([{'kind':'hypothetical','grade':''}] if hypothetical else [])
    premises=[{'kind':'user_stated'}] if target else []
    expected='The sourced financial figures are corroborated. '+ending
    assert scoped_grade_sentence('corroborated',figures,premises)==expected
    old=moment('stood_behind_corroborated')
    answer={'grade':'corroborated','figures':figures,'target_premises':premises,'text':'Bound source and premise. '+old,'grade_sentence':old,'spoken':{'text':'Bound source and premise. '+old,'grade_sentence':old}}
    scope_saved_grade(answer)
    assert answer['text']=='Bound source and premise. '+expected and answer['grade_sentence']==answer['spoken']['grade_sentence']==expected
    assert old not in answer['text'] and old not in answer['spoken']['text']
    assert scoped_grade_sentence('corroborated',[{'kind':'financial','grade':'corroborated'}])==old
    assert scoped_grade_sentence('corroborated',[{'kind':'hypothetical','grade':''}],premises)==''
    assert scoped_grade_sentence('corroborated',[],premises,[{'grade':'corroborated'}]).startswith('The sourced assertions') if target else True


def test_genuine_target_answer_scope_is_consistent_in_text_speech_and_saved_reconstruction(opened):
    from viva.surface.conversation import _timeline_turn
    bridge=actions(opened,[allocation_step(),target_step()])
    first=bridge.ask({'question':'Show PLAN exposure allocation as of 2025-12-31','context_mode':'new_question'})
    assert first['kind']=='completed'
    answer=bridge.ask({'question':Q029,'context_mode':'follow_up'})['state']
    expected='The sourced financial figures are corroborated. User-stated targets and hypothetical results have no bank evidence grade.'
    assert expected in answer['text'] and answer['grade_sentence']==expected and answer['spoken']['grade_sentence']==expected
    assert moment('stood_behind_corroborated') not in answer['text']
    rows=opened.ledger.projection().conversation_turns();saved=_timeline_turn(rows[-1],{}, {},opened.ledger.projection())
    assert saved['answer']['grade_sentence']==expected and expected in saved['answer']['text']


def test_percentage_point_registered_writer_requires_sealed_hypothetical_evidence():
    from viva.tools.runner import _MAGNITUDE_WRITERS
    from viva import render
    from viva.instrument_evidence import _attest_figure
    writer=_MAGNITUDE_WRITERS[render.PERCENTAGE_POINTS]
    raw={'quantity':'allocation_percentage_points','claim':'allocation_percentage_points','kind':'hypothetical','grade':'','value':'+10','record_ids':['source-doc'],'subject':{'account_id':'account'},'boundary':{'selected':[{'kind':'account','value':'account'}]}}
    with pytest.raises(ValueError):writer(None,raw,'en-US')
    sealed=_attest_figure(raw,'allocation_percentage_points',run_token=object())
    assert str(writer(None,sealed,'en-US'))=='+10 percentage points'
    sealed['grade']='verified'
    with pytest.raises(ValueError):writer(None,sealed,'en-US')


def test_actual_native_recovery_dispatch_remains_closed_and_reaches_fresh_saved_authority(opened):
    from viva.desktop_bridge.rpc import dispatch_frame
    from viva.surface import CURRENT_PROTOCOL
    bridge=actions(opened,[allocation_step(),target_step()])
    first=bridge.ask({'question':'Show PLAN exposure allocation as of 2025-12-31','context_mode':'new_question'})
    row=opened.ledger.projection().conversation_turns()[-1]
    anchor={'version':'allocation-continuation-v1','turn_id':row['turn_id'],'answer_id':first['state']['answer_id']}
    def dispatch(payload):
        frame={'protocol':CURRENT_PROTOCOL.wire(),'request_id':'native-recovery','operation':'viva.conversation.ask','payload':payload}
        return json.loads(dispatch_frame(json.dumps(frame),{'viva.conversation.ask':bridge.ask}))
    good=dispatch({'question':Q029,'context_mode':'follow_up','continuation_recovery':anchor})
    assert good['ok'] and good['result']['kind']=='completed',good
    for bad in ({**anchor,'extra':'foreign'}, {**anchor,'version':'unreviewed'}):
        assert not dispatch({'question':Q029,'context_mode':'follow_up','continuation_recovery':bad})['ok']
    assert not dispatch({'question':Q029,'context_mode':'new_question','continuation_recovery':anchor})['ok']
