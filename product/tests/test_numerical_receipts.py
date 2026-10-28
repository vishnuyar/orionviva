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


import copy
import importlib
import json
from pathlib import Path
import pytest


def capacity_turn(count, groups=4, caveats=None):
    """Public hypothetical transport inputs, with distinct same-run endpoints."""
    figures=[]
    for index in range(count):
        account=f'capacity-account-{index:03}'
        value=figure(f'{index+1}.00','Hypothetical capacity value',quantity='balance',
            kind=HYPOTHETICAL,currency='USD',dated='2026-03-01',
            boundary=bounded(whole=False,selected=[{'kind':'account','value':account}]),
            subject={'account_id':account})
        value['id']=f'capacity-{index:03}';figures.append(value)
    producers=[ToolResult(tool='public_hypothetical_capacity',ok=True,
        figures=copy.deepcopy(figures[position::groups]),data={},caveats=caveats or [])
        for position in range(groups)]
    return SimpleNamespace(question='Public hypothetical capacity question.',
        result=SimpleNamespace(figures=figures,transcript=producers,answered=True,
            text='Public hypothetical transport capacity; no financial observation.',grade=''))


def capacity_surface(turn, identity='capacity-128'):
    return conversation(turn,{fig['id']:fig['value'] for fig in turn.result.figures},turn_id=identity)


def capacity_bytes(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()


@pytest.mark.parametrize('count',[101,113,114,128])
def test_capacity_accepts_new_bounded_counts(count):
    answer=capacity_surface(capacity_turn(count))
    assert len(answer['figures'])==count
    assert sum(bool(fig['receipt_ids']) for fig in answer['figures'])==count
    assert len({fig['id'] for fig in answer['figures']})==count
    assert len({fig['subject']['account_id'] for fig in answer['figures']})==count


@pytest.mark.parametrize('count',[1,50,100])
def test_existing_complete_surface_bytes_pair_exactly_at_old_and_new_capacity(monkeypatch,count):
    receipts=importlib.import_module('viva.surface.numerical_receipts')
    turn=capacity_turn(count)
    monkeypatch.setattr(receipts,'MAX_FIGURES',100);baseline=capacity_bytes(capacity_surface(turn))
    monkeypatch.setattr(receipts,'MAX_FIGURES',128);candidate=capacity_bytes(capacity_surface(turn))
    assert baseline==candidate


def test_answer_and_individual_producer_limits_are_both_128():
    receipts=importlib.import_module('viva.surface.numerical_receipts')
    assert receipts.MAX_FIGURES==128
    assert (receipts.MAX_RECEIPTS,receipts.MAX_RECORDS,receipts.MAX_SCALAR,
        receipts.MAX_RECEIPT_BYTES,receipts.MAX_ANSWER_RECEIPT_BYTES)==(32,500,4096,262144,524288)
    assert sum(bool(f['receipt_ids']) for f in capacity_surface(capacity_turn(128,1))['figures'])==128
    assert capacity_surface(capacity_turn(129,4))['numerical_receipts']==[]
    oversized_producer=capacity_turn(129,1)
    oversized_producer.result.figures=oversized_producer.result.figures[:1]
    assert capacity_surface(oversized_producer)['numerical_receipts']==[]


def capacity_guard_cases():
    cases={}
    cases['duplicate_producer']=capacity_turn(2,1)
    cases['duplicate_producer'].result.transcript*=2
    cases['typed_mismatch']=capacity_turn(2,1)
    cases['typed_mismatch'].result.transcript[0].figures[0]['value']='999.00'
    cases['transcript33']=capacity_turn(33,33)
    cases['per_receipt_bytes']=capacity_turn(1,1,['x'*4096]*100)
    cases['total_bytes']=capacity_turn(3,3,['x'*3000]*60)
    cases['record_count_mismatch']=capacity_turn(2,1)
    cases['record_count_mismatch'].result.transcript[0].figures[0]['records']=1
    for count in (500,501):
        turn=capacity_turn(1,1);ids=[f'unavailable-record-{i}' for i in range(count)]
        turn.result.figures[0]['record_ids']=ids
        turn.result.transcript[0].figures[0]['record_ids']=ids.copy()
        turn.result.transcript[0].figures[0]['records']=count
        cases[f'records{count}']=turn
    for name,field,value in [('nonfinite','value','NaN'),('unknown_quantity','kind','unknown'),
            ('hypothetical_grade','grade','verified'),('malformed_boundary','boundary',{'whole':'yes'}),
            ('scalar_overflow','currency','x'*4097)]:
        turn=capacity_turn(2,1)
        turn.result.figures[0][field]=value
        turn.result.transcript[0].figures[0][field]=copy.deepcopy(value)
        cases[name]=turn
    return cases


def test_all_unchanged_guards_are_byte_identical_and_keep_ordered_selection(monkeypatch):
    receipts=importlib.import_module('viva.surface.numerical_receipts')
    cases=capacity_guard_cases();paired=[]
    for cap in (100,128):
        monkeypatch.setattr(receipts,'MAX_FIGURES',cap)
        paired.append({name:capacity_surface(turn) for name,turn in cases.items()})
    assert capacity_bytes(paired[0])==capacity_bytes(paired[1])
    results=paired[1]
    for name in ('duplicate_producer','transcript33','per_receipt_bytes','records501'):
        assert results[name]['numerical_receipts']==[]
    for name in ('typed_mismatch','record_count_mismatch','nonfinite','unknown_quantity',
            'hypothetical_grade','malformed_boundary','scalar_overflow'):
        assert results[name]['figures'][0]['receipt_ids']==[]
        assert results[name]['figures'][1]['receipt_ids']
    assert results['records500']['figures'][0]['receipt_ids']
    retained=results['total_bytes']['numerical_receipts']
    assert [r['id'] for r in retained]==['conversation:capacity-128:numerical:0','conversation:capacity-128:numerical:1']
    assert sum(len(json.dumps(r,ensure_ascii=False).encode()) for r in retained)<=524288


def test_actual_128_backend_wire_matches_embedded_typescript_input():
    source=Path(__file__).resolve().parents[2]/'desktop/src/surface/adapters/numerical-receipts.test.ts'
    text=source.read_text();start='const capacityBackendWire = ';end=';\n// End capacity backend wire.'
    encoded=text.split(start,1)[1].split(end,1)[0]
    product=Path(__file__).resolve().parents[1]/'viva'
    pack=json.loads((product/'versions.json').read_text())['in_force']['persona_pack']['active']
    assert f'product/viva/persona/{pack}/moments.json' in text
    moment=json.loads((product/'persona'/pack/'moments.json').read_text())['conversation_voice_local_only']
    reference='personaMoments.conversation_voice_local_only'
    assert encoded.count(reference)==1
    encoded=encoded.replace(reference,json.dumps(moment,ensure_ascii=False))
    assert json.loads(encoded)==capacity_surface(capacity_turn(128))
    assert len(capacity_bytes(json.loads(encoded)))<524288


def test_128_figure_saved_conversation_reopens_with_exact_lineage(tmp_path):
    from viva.vault import Vault
    from viva.ledger.events import conversation_turn_opened,conversation_turn_settled
    from viva.desktop_bridge.vault_surface import OpenedVaultSurfaceProvider
    answer=capacity_surface(capacity_turn(128))
    vault=Vault.open(tmp_path/'vault','synthetic capacity persistence',create=True)
    try:
        vault.ledger.append(conversation_turn_opened('capacity-128','ask','Public hypothetical capacity question.','2026-02-01'))
        vault.ledger.append(conversation_turn_settled('capacity-128','completed',answer['text'],'2026-02-01',answer=answer))
    finally:vault.close()
    reopened=Vault.open(tmp_path/'vault','synthetic capacity persistence',create=False)
    try:
        reopened.synchronize_read_store()
        saved=OpenedVaultSurfaceProvider(reopened).read_surface('conversation',{})['turns'][0]['answer']
        assert capacity_bytes(saved['figures'])==capacity_bytes(answer['figures'])
        assert capacity_bytes(saved['numerical_receipts'])==capacity_bytes(answer['numerical_receipts'])
        assert len(saved['figures'])==128
    finally:reopened.close()
