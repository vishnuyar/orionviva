"""Emitter-owned identity metadata, independent of values and rendering prose."""
import copy
import pytest
from viva.tools.envelope import figure, ToolResult, MODEL_FACING_FIGURE
from viva.answer_program.eval import load_supplement_cases, _supplement_figure_matches


def test_subject_is_validated_defensively_copied_and_not_model_facing():
    subject={'account_id':'canonical-account'}
    emitted=figure('10','an actual measure',quantity='balance',subject=subject)
    subject['account_id']='changed'
    assert emitted['subject']=={'account_id':'canonical-account'}
    assert 'subject' not in MODEL_FACING_FIGURE
    assert 'subject' not in ToolResult(tool='fixture',ok=True,figures=[emitted]).to_dict()['figures'][0]
    assert 'subject' not in figure('10','legacy measure',quantity='balance')
    legacy=figure('10','an actual measure',quantity='balance')
    assert ToolResult(tool='fixture',ok=True,figures=[emitted]).to_dict()['figures']==ToolResult(tool='fixture',ok=True,figures=[legacy]).to_dict()['figures']
    for bad in ({'kind':'not-owned','value':'x'},{'account_id':'x','unexpected':'x'},{'grouping':'unknown'},{'merchant':''}):
        with pytest.raises(ValueError):figure('10','x',quantity='balance',subject=bad)


def _actual_figures(case):
    from viva.answer_program import AnswerResourcePolicy, CapabilityManifest, ProgramValidator
    from viva.answer_program.eval import resolve_case_fixture
    from viva.answer_program.intents import SemanticFamilyRegistry, SEMANTIC_REQUEST_VERSION
    from viva.answer_program.schema import QuestionContext
    from viva.answer_program.execute import ProgramExecutor
    factory,_=resolve_case_fixture(case);registry=factory()
    families=SemanticFamilyRegistry(registry.semantic_entities())
    raw=dict(request_version=SEMANTIC_REQUEST_VERSION,outcome='request',catalog_digest=families.catalog_digest,
             entity_catalog_digest=families.entity_catalog_digest,family=case.expected_family,
             parameters=copy.deepcopy(case.expected_parameters),parameter_sources=copy.deepcopy(case.parameter_sources),requested_claims=list(case.expected_claims))
    for name,proof in raw['parameter_sources'].items():
        if name=='account_phrase' and proof['derivation']=='catalog_selection':
            candidates=families._account_role_candidates(raw['parameters'][name]);assert len(candidates)==1
            raw['parameters'][name]=candidates[0]['id']
    context=QuestionContext(question=case.question,today=case.read_day,prior_turns=case.prior_turns)
    semantic=families.parse(raw,context)
    manifest=CapabilityManifest.from_registry(registry);policy=AnswerResourcePolicy()
    program=families.lower(semantic,manifest)
    assert ProgramValidator(manifest,policy).validate(program).ok
    execution=ProgramExecutor(registry,policy).execute(program,case.question)
    return [fig for result in execution.transcript for fig in result.figures]


SUBJECT_CASES=[(case,row) for case in load_supplement_cases() for row in case.supplement_contract['expected_figures'] if 'expected_subject' in row]


@pytest.mark.parametrize('case,expected',SUBJECT_CASES,ids=[case.id+':'+str(index) for index,(case,_) in enumerate(SUBJECT_CASES)])
def test_all_frozen_subject_expectations_have_actual_emitter_metadata(case,expected):
    actual=_actual_figures(case)
    compatible=[fig for fig in actual if _supplement_figure_matches(fig,expected)]
    assert compatible, 'no matching genuine emitted figure'
    assert any(fig.get('subject')==expected['expected_subject'] for fig in compatible)


def test_supplement_matcher_rejects_missing_wrong_or_extra_subject():
    case,expected=SUBJECT_CASES[0]
    boundary=expected['required_boundary']
    actual=dict(value=expected['value'],quantity=expected['quantity'],kind=expected['kind'],currency=expected['currency'],dated=expected['dated'],
                what=expected['what_exact'],grade=expected['required_grade'],record_ids=expected['required_sources']['record_ids'],
                boundary=dict(whole=boundary['whole'],selected=boundary.get('selected_exact',[]),cut=boundary.get('cut_exact',[])),subject=copy.deepcopy(expected['expected_subject']))
    assert _supplement_figure_matches(actual,expected)
    for replacement in (None,{'account_id':'wrong'},{**expected['expected_subject'],'extra':'not allowed'}):
        changed=copy.deepcopy(actual)
        if replacement is None:changed.pop('subject')
        else:changed['subject']=replacement
        assert not _supplement_figure_matches(changed,expected)
