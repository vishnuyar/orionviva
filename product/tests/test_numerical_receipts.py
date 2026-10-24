"""Conversation preserves genuine same-run numerical evidence, never guesses."""
from types import SimpleNamespace
from viva.surface.conversation import conversation
from viva.tools.envelope import ToolResult, figure, bounded, HYPOTHETICAL


def make_turn():
    value=figure('100.00','hypothetical balance',quantity='balance',kind=HYPOTHETICAL,currency='USD',dated='2026-03-01',boundary=bounded(whole=False))
    value['id']='f1'
    produced=ToolResult(tool='test_ordinary_producer',ok=True,figures=[value],data={},caveats=['A fixed source limitation.'])
    result=SimpleNamespace(figures=[value],transcript=[produced],answered=True,text='A hypothetical balance.',grade='')
    return SimpleNamespace(result=result,question='A current question.')


def test_typed_hypothetical_figure_survives_surface_and_has_same_run_receipt():
    turn=make_turn(); answer=conversation(turn,{'f1':'USD100.00'},turn_id='turn-1')
    shown=answer['figures'][0]
    for key in ('value','quantity','kind','currency','dated','boundary'):
        assert shown[key]==turn.result.figures[0][key]
    assert shown['grade']==''
    assert shown['receipt_ids']==['conversation:turn-1:numerical:0']
    assert answer['numerical_receipts'][0]['figure_ids']==['f1']


def test_figure_without_matching_same_run_producer_has_no_receipt():
    turn=make_turn();turn.result.transcript=[]
    answer=conversation(turn,{'f1':'USD100.00'},turn_id='turn-1')
    assert answer['figures'][0]['receipt_ids']==[]
    assert answer['numerical_receipts']==[]


def test_actual_serialized_model_facing_transcript_preserves_binding():
    turn=make_turn();turn.result.transcript=[turn.result.transcript[0].to_dict()]
    answer=conversation(turn,{'f1':'USD100.00'},turn_id='turn-1')
    assert answer['figures'][0]['receipt_ids']
    assert answer['numerical_receipts'][0]['caveats']==['A fixed source limitation.']


def test_duplicate_or_changed_producer_refuses_receipt():
    import copy
    turn=make_turn();turn.result.transcript*=2
    assert conversation(turn,{},turn_id='turn-1')['numerical_receipts']==[]
    turn=make_turn();produced=copy.deepcopy(turn.result.transcript[0].to_dict());produced['figures'][0]['value']='101.00';turn.result.transcript=[produced]
    assert conversation(turn,{},turn_id='turn-1')['numerical_receipts']==[]


def test_source_registry_has_no_id_string_classification_or_event_replay():
    from viva.surface.numerical_receipts import _source_registry
    class Projection:
        core=SimpleNamespace(_acct={},_goals={})
        def captured_docs(self):return {'real-captured-source':'text'}
        def movements(self):return []
        def events(self):raise AssertionError('canonical replay')
    sources,local=_source_registry(Projection(),{'real-captured-source','doc-looking-id','cap-goal-looking-id'})
    assert sources['real-captured-source']['kind']=='document'
    assert sources['doc-looking-id']==dict(record_id='doc-looking-id',kind='unavailable',document_id=None)
    assert sources['cap-goal-looking-id']['kind']=='unavailable'
    assert local=={}


def test_movement_bounds_checked_before_materialization():
    from viva.surface.numerical_receipts import _source_registry, MAX_MOVEMENTS
    class Projection:
        core=SimpleNamespace(_acct={'account':SimpleNamespace(lines=range(MAX_MOVEMENTS+1))},_goals={})
        def captured_docs(self):return []
        def movements(self):raise AssertionError('overbound movement materialization')
    sources,_=_source_registry(Projection(),{'unknown'})
    assert sources['unknown']['kind']=='unavailable'


def test_actual_five_compiled_wire_examples_have_typed_receipts():
    import json
    from pathlib import Path
    examples=json.loads((Path(__file__).parent/'fixtures/numerical_receipts/actual-backend-wire-v1.json').read_text())['examples']
    assert len(examples)==5
    for example in examples:
        answer=example['answer']
        assert answer['numerical_receipts']
        receipts={row['id']:row for row in answer['numerical_receipts']}
        for fig in answer['figures']:
            assert fig['receipt_ids']
            for receipt in fig['receipt_ids']:
                assert fig['id'] in receipts[receipt]['figure_ids']
        if example['case_id']=='fc-v1:checking_savings_zero_rate':
            assert answer['numerical_receipts'][0]['observed_inputs']
        assert all(field['label']!='Goal kind' for receipt in answer['numerical_receipts'] for item in receipt['local_inputs'] for field in item['fields'])
        if example['case_id']=='fc-v1:known-remainder':
            assert {row['kind'] for row in answer['numerical_receipts'][0]['source_records']}=={'document','movement','local_activity'}


def test_receipts_persist_without_recalculation_and_legacy_is_not_migrated(tmp_path):
    from viva.vault import Vault
    from viva.ledger.events import conversation_turn_opened, conversation_turn_settled
    from viva.desktop_bridge.vault_surface import OpenedVaultSurfaceProvider
    vault=Vault.open(tmp_path/'vault','synthetic receipt persistence',create=True)
    answer=conversation(make_turn(),{'f1':'USD100.00'},turn_id='typed')
    legacy={'text':'A legacy answer.','figures':[{'id':'old','written':'USD1','grade':'','record_ids':[]}]}
    try:
        for identity,payload in [('typed',answer),('legacy',legacy)]:
            vault.ledger.append(conversation_turn_opened(identity,'ask','Question','2026-02-01'))
            vault.ledger.append(conversation_turn_settled(identity,'completed',payload['text'],'2026-02-01',answer=payload))
    finally:vault.close()
    reopened=Vault.open(tmp_path/'vault','synthetic receipt persistence',create=False)
    try:
        reopened.synchronize_read_store()
        turns=OpenedVaultSurfaceProvider(reopened).read_surface('conversation',{})['turns']
        assert turns[0]['answer']['numerical_receipts']==answer['numerical_receipts']
        for field in ('value','quantity','kind','currency','dated','boundary','grade','receipt_ids'):
            assert turns[0]['answer']['figures'][0][field]==answer['figures'][0][field]
        assert 'numerical_receipts' not in turns[1]['answer']
        assert 'value' not in turns[1]['answer']['figures'][0]
    finally:reopened.close()


def test_unrecognized_boundary_and_unsupported_grade_do_not_get_receipts():
    turn=make_turn();turn.result.figures[0]['boundary']['private_extra']='do not transmit'
    answer=conversation(turn,{},turn_id='turn-1')
    assert answer['numerical_receipts']==[]
    assert 'boundary' not in answer['figures'][0]
    turn=make_turn();turn.result.figures[0]['grade']='verified'
    answer=conversation(turn,{},turn_id='turn-1')
    assert answer['numerical_receipts']==[]
    assert answer['figures'][0]['grade']==''


def test_required_assumption_proof_not_from_current_question_is_unavailable():
    turn=make_turn();turn.result.transcript[0].data={'assumption_receipt':dict(current_question_only=True,
        exact_parameters={'currency':'USD'},exact_proofs={'currency':{'source':'question','quote':'ABSENT','derivation':'verbatim'}},
        exact_numeric_inputs={},modeled_inputs={})}
    assert conversation(turn,{},turn_id='turn-1')['numerical_receipts']==[]


def test_subject_uses_owned_closed_vocabulary_and_unknown_keeps_answer():
    turn=make_turn();turn.result.figures[0]['subject']={'kind':'account','value':'recorded-account'}
    answer=conversation(turn,{},turn_id='turn-1')
    assert answer['figures'][0]['subject']==turn.result.figures[0]['subject']
    assert answer['numerical_receipts']
    turn=make_turn();turn.result.figures[0]['subject']={'kind':'future-unknown-kind','value':'unavailable'}
    answer=conversation(turn,{},turn_id='turn-1')
    assert answer['text']==turn.result.text
    assert answer['figures'][0]['receipt_ids']==[]
    assert answer['numerical_receipts']==[]
