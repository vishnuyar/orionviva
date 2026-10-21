"""Independent literal-source checks for the frozen date-only admission case."""
from __future__ import annotations

import copy
import json
from pathlib import Path

from vivacore import versions


def date_only_case(case):
    return (case.expected_family == 'named_account_balance'
            and set(case.required_claims) == {'measurement_date'}
            and set(case.allowed_claims) == {'measurement_date'})


def independent_expectation(case):
    package = Path(__file__).resolve().parent.parent
    version = versions.active(package, 'date_only_expectations')
    path = versions.path_of(package, version)
    if versions.fingerprint(path) != versions.pin(package, version):
        raise ValueError('date-only independent expectation fingerprint differs')
    data = json.loads(path.read_text(encoding='utf-8'))
    if data.get('version') != version or case.id not in data.get('cases', {}):
        raise ValueError('date-only case has no independent source expectation')
    return copy.deepcopy(data['cases'][case.id])


def _require(condition):
    if not condition:
        raise ValueError("date-only source contract differs")


def date_contract_defects(case, runtime):
    """Check delivery and reproduce originating evidence without using a binder."""
    from .eval import resolve_case_fixture
    from .capability import CapabilityManifest
    from .execute import ProgramExecutor
    from .schema import AnswerResourcePolicy
    from .validate import ProgramValidator

    try:
        expected = independent_expectation(case)
        result = runtime.result
        program = runtime.compilation.program
        request = runtime.compilation.semantic_outcome.request
        _require(case.oracle.get('date_contract') == expected)
        _require(set(request.requested_claims) == {'measurement_date'})
        _require(result.answered and result.status == 'answered')
        _require(result.figures == expected['delivered_figures'] == [])
        _require(result.grade == expected['grade'])
        _require(list(result.disclosures) == expected['disclosures'])
        _require(result.written == {'date': expected['date']})
        _require(result.text == expected['text'])
        _require(not result.gaps and not result.missing and not result.caveats)
        _require(program.mode == 'answer')
        _require(program.shape.to_dict() == {'clauses': [expected['clause']]})
        _require(result.shape == program.shape.to_dict())
        _require(not program.assumptions and program.clarification is None)
        _require(program.result_policy == {'allow_partial': False,
                                         'required_clauses': ['measurement_date']})
        _require(len(program.nodes) == len(program.bindings) == 1)
        node, binding = program.nodes[0], program.bindings[0]
        _require(node.kind == 'tool_read' and node.importance == 'required')
        _require(node.tool == 'query_ledger' and not node.depends_on)
        _require(node.args == {'entity': 'balances',
                             'filters': {'account': expected['account']}})
        _require(binding.source == node.id and binding.hole == 'date')
        _require(binding.reference_kind == 'measurement_date_of')
        _require(binding.selector.to_dict() == {
            'cardinality': 'one', 'quantity': 'balance', 'scope': ['account']})
        factory, _ = resolve_case_fixture(case)
        registry, policy = factory(), AnswerResourcePolicy()
        manifest = CapabilityManifest.from_registry(registry)
        _require(ProgramValidator(manifest, policy).validate(program).ok)
        execution = ProgramExecutor(registry, policy,
            query_executor=getattr(registry, 'query_executor', None)).execute(program, case.question)
        _require(not any((execution.deadline_exceeded, execution.evidence_limit_exceeded,
                        execution.figure_limit_exceeded)))
        _require(execution.nodes[node.id].status == 'completed')
        _require(len(execution.transcript) == len(result.transcript) == 1)
        original = execution.transcript[0]
        fresh = {**original.to_dict(), 'figures': copy.deepcopy(original.figures),
                 'identifiers': copy.deepcopy(original.identifiers),
                 'record_ids': list(original.record_ids)}
        read = result.transcript[0]
        _require(read == fresh and read['ok'] and read['tool'] == node.tool)
        supports = [f for f in read['figures'] if f.get('quantity') == 'balance']
        _require(len(supports) == expected['support_cardinality'] == 1)
        support = supports[0]
        for key in ('quantity', 'kind', 'grade', 'value', 'currency', 'record_ids'):
            _require(support[key] == expected[key])
        _require(support['dated'] == expected['date'])
        boundary = support['boundary']
        account_cut = [{'kind': 'account', 'value': expected['account']}]
        _require(boundary['selected'] == boundary['cut'] == account_cut)
        _require(boundary['whole'] is False)
        _require(result.bindings == {'date': {'measurement_date_of': support['id']}})
        _require(support['id'] in execution.graph.references(node.id, 'figure'))
        balances = read['data']['balances']
        _require(len(balances) == 1)
        _require(balances[0]['account'] == balances[0]['record_id'] == expected['account'])
        _require(balances[0]['provenance'] == expected['provenance'])
        _require(balances[0]['latest_evidence_date'] == expected['date'])
        _require(balances[0]['evidence_grade'] == read['grade'] == expected['grade'])
    except (AssertionError, AttributeError, KeyError, IndexError, TypeError, ValueError):
        return ('invalid_date_only_contract',)
    return ()
