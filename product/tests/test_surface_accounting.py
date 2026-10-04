"""Report surfaces retain exact ledger results and format them once."""
from viva.surface.accounting import accounting


def test_report_surface_formats_hierarchy_and_keeps_evidence(monkeypatch):
    supplied = {
        'balance_sheet': {'by_currency': {'AAA': {'assets': '101', 'net': '101'}}, 'lines': []},
        'profit_loss': {'by_currency': {'AAA': {'income': '70', 'net': '53'}},
                        'lines': [{'amount': '17', 'currency': 'AAA', 'amount_evidence': {'grade': 'verified'}, 'classification_evidence': {'reason': 'inference'}}],
                        'unresolved_components': [{'amount': '9', 'currency': 'AAA'}],
                        'hierarchy': [], 'hierarchy_tree': [{'currency': 'AAA', 'roots': [{'label': 'expenses', 'amount': '17', 'children': [{'label': 'Household', 'amount': '17', 'children': []}]}]}]},
    }
    calls = []
    def project(projection, **kwargs):
        calls.append(kwargs)
        return supplied
    monkeypatch.setattr('viva.surface.accounting.financial_statements', project)
    result = accounting(object(), 'en_US', '2026-09-30', start='2026-09-01', end='2026-09-20')
    assert calls == [{'start': '2026-09-01', 'end': '2026-09-20', 'as_of': '2026-09-20'}]
    assert result['profit_loss']['lines'][0]['amount'] == '17'
    assert result['profit_loss']['lines'][0]['classification_evidence'] == {'reason': 'inference'}
    assert result['profit_loss']['hierarchy_tree'][0]['roots'][0]['children'][0]['display']
    assert 'display' not in supplied['profit_loss']['lines'][0]


def test_conflicting_document_discloses_components_and_only_captured_sources(monkeypatch):
    class Projection:
        def captured_docs(self):
            return ['payroll-document', 'deposit-document', 'component-document']
    result = {
        'balance_sheet': {'by_currency': {}, 'lines': []},
        'profit_loss': {'by_currency': {}, 'lines': [], 'unresolved_components': [{
            'amount': '70', 'currency': 'AAA',
            'amount_evidence': {'provenance': {'doc_id': 'payroll-document'}},
            'classification_evidence': {'source_refs': ['accounting-claim'],
                'existing_treatment': {'said': 'This was a gift.', 'source_refs': ['accounting-claim']},
                'related_sources': [{'provenance': {'doc_id': 'deposit-document'}}]},
            'supporting_components': [{'account': 'Income:Salary', 'amount': '-90',
                                       'provenance': {'doc_id': 'component-document'}}],
        }], 'hierarchy': [], 'hierarchy_tree': []},
    }
    monkeypatch.setattr('viva.surface.accounting.financial_statements', lambda *args, **kwargs: result)
    surfaced = accounting(Projection(), 'en_US', '2026-09-30')['profit_loss']['unresolved_components'][0]
    assert surfaced['document_ids'] == ['component-document', 'deposit-document', 'payroll-document']
    assert surfaced['supporting_components'][0]['display']
    assert surfaced['supporting_components'][0]['amount'] == '-90'
    assert surfaced['classification_evidence']['existing_treatment']['said'] == 'This was a gift.'
