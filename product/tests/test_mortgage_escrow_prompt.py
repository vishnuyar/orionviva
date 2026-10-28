"""Public offline source mapping; handcrafted replies do not prove model compliance."""
import copy
import hashlib
import itertools
import json
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
import pytest
from viva.ingest import instrument_contracts as c
from viva.ingest.instrument_read import parser_for
from viva.ingest.registry import extraction_prompt_for, profile_for
from viva.normalization_context import ExtractionNormalizationContext as Context, MORTGAGE_SOURCE_CONTRACT, encode_context, source_contract_for_claim
from test_mortgage_principal_source_v2 import CONTEXT, proposal, response
from test_instrument_projector_b import mortgage, setup, bank

PROMPTS = Path(__file__).resolve().parents[1] / 'viva/prompts'
OLD = 'extract:mortgage-base-v2+mortgage-v2'
NEW = 'extract:mortgage-base-v2+mortgage-v3'
SUPPORT = ('untrusted-frame-v1', 'retry-syntax-v1', 'retry-value-v2')


def test_active_selection_and_complete_immutable_schema():
    text, version = extraction_prompt_for('mortgage_statement')
    assert version == NEW
    profile = profile_for('mortgage_statement')
    assert (profile.extract_base, profile.profile_version, profile.instrument_source_contract) == ('mortgage-base-v2', MORTGAGE_SOURCE_CONTRACT, MORTGAGE_SOURCE_CONTRACT)
    hashes = {
        'extract-mortgage-base-v1.txt': '29a79b9e206648a79862b70d51d5f1277c346314c821482950a8524b88fde3a4',
        'extract-mortgage-base-v2.txt': '0ec7df8a06cae5df8c5ca2273e6976208124e7ea9a3cc3cc9031f1ab62bd196b',
        'extract-mortgage-v1.txt': 'dfb77fddc9726cfa22cda858c16ac72d787894d099f891d0ce538264510eed24',
        'extract-mortgage-v2.txt': 'c117aaf8db10ec1a9a238f4f1b27727a72cc8a2cd23708487b528e07621b657e',
    }
    for name, digest in hashes.items():
        assert hashlib.sha256((PROMPTS / name).read_bytes()).hexdigest() == digest
    assert (PROMPTS / 'extract-mortgage-base-v2.txt').read_text() in text


def test_fragment_preserves_old_paragraphs_and_printed_scope():
    old = (PROMPTS / 'extract-mortgage-v2.txt').read_text()
    new = (PROMPTS / 'extract-mortgage-v3.txt').read_text()
    assert new.startswith(old)
    for clause in ('escrow.identity describes the escrow subaccount', 'institution, account_reference and holder only from printed facts', 'unambiguously governs the escrow section as well as the loan', 'actual page of each field', 'names competing holders/institutions', 'absent, unreadable or ambiguous, keep escrow.identity null', "escrow's explicitly printed account identifier", 'never substitute the loan account, payment reference, property reference or continuity text', 'Do not infer an institution or holder from a lender name', 'never merely because there is one likely candidate'):
        assert clause in new
    assert all(fixture not in new for fixture in ('LOAN-A', 'ESCROW-A', 'Rocket Mortgage', 'Alex Morgan'))


@pytest.mark.parametrize('version', [OLD, NEW])
def test_exact_pairs_accept_every_unique_support_suffix_order(version):
    for size in range(4):
        for suffixes in itertools.permutations(SUPPORT, size):
            assert source_contract_for_claim(CONTEXT, 'mortgage_statement', version + ''.join('+' + part for part in suffixes)) == MORTGAGE_SOURCE_CONTRACT


@pytest.mark.parametrize('version', ['extract:mortgage-base-v1+mortgage-v3', 'extract:mortgage-base-v2+mortgage-v1', 'extract:mortgage-v3+mortgage-base-v2', 'extract:mortgage-base-v2+mortgage-v999', NEW + '+mortgage-v2', NEW + '+unknown', *(NEW + '+' + part + '+' + part for part in SUPPORT), 'extract:term-deposit-base-v1+term-deposit-v1'])
def test_unsupported_pairs_reject(version):
    with pytest.raises(ValueError): source_contract_for_claim(CONTEXT, 'mortgage_statement', version)


@pytest.mark.parametrize('version', [OLD, NEW])
@pytest.mark.parametrize('context', [None, Context(1, 'nv1', 'en-US', 'USD')])
def test_new_contract_fragments_require_context(version, context):
    with pytest.raises(ValueError): source_contract_for_claim(context, 'mortgage_statement', version)


@pytest.mark.parametrize('version', [OLD, NEW])
def test_other_document_family_rejects(version):
    with pytest.raises(ValueError): source_contract_for_claim(CONTEXT, 'term_deposit_statement', version)


@pytest.mark.parametrize('prepared', [False, True])
def test_ordinary_and_prepared_readers_select_new_fragment(monkeypatch, prepared):
    from viva.ingest import reader
    text = json.dumps(proposal()); calls = []
    class Adapter:
        def extract(self, pages, prompt):
            calls.append(prompt)
            return response(json.dumps({'doc_type': 'mortgage_statement', 'doc_type_confidence': 1}) if len(calls) == 1 else text)
    monkeypatch.setattr(reader, 'adapter_for', lambda _: Adapter())
    monkeypatch.setattr(reader, '_render_and_read_text', lambda _: ([object()], 'public printed text'))
    spec = SimpleNamespace(model='offline-configured', json_mode=True)
    result = (reader.read_prepared_statement((object(),), 'public printed text', 'public-source', spec, 'en-US', 'USD', permit=lambda: True) if prepared else reader.read_statement(b'public original', 'public-source', spec, 'en-US', 'USD'))
    assert result.facts is not None, result.error
    phase = result.phases[-1]
    assert phase.prompt_version.split('+untrusted-frame-v1')[0] == NEW
    assert phase.normalization_context == CONTEXT and phase.raw_text == text
    assert (PROMPTS / 'extract-mortgage-v3.txt').read_text() in calls[-1]
    assert result.facts.payload.principal_movements[0].amount.value == Decimal('100')


@pytest.mark.parametrize('version', [OLD, NEW])
@pytest.mark.parametrize('has_identity', [True, False])
def test_retained_pair_and_ordinary_parser_preserve_identity_pages_and_null(version, has_identity):
    from viva.rebuild import _parse_claim
    value = proposal()
    if not has_identity: value['escrow']['identity'] = None
    else:
        value['escrow']['identity']['institution']['page'] = 2
        value['escrow']['identity']['holder']['page'] = 3
    raw = json.dumps(value); before = copy.deepcopy(value)
    facts, error, context = _parse_claim('mortgage_statement', {'response_text': raw, 'prompt_version': version, 'normalization_context': encode_context(CONTEXT), 'parse_ok': True}, 'public-source', 'fr-FR', 'EUR')
    assert error is None and context == CONTEXT
    ordinary, error = parser_for('mortgage_statement', source_contract=MORTGAGE_SOURCE_CONTRACT, page_count=3)(raw, 'public-source', 'en-US', 'USD')
    assert error is None and ordinary.payload == facts.payload
    parsed = facts.payload; result = c.check_escrow(parsed.escrow)
    assert value == before and raw == json.dumps(value)
    if has_identity:
        identity = parsed.escrow.identity
        assert identity.account_reference.value != parsed.identity.account_reference.value
        for name, page in [('institution', 2), ('holder', 3), ('account_reference', 1)]:
            field = getattr(identity, name)
            assert field.value == value['escrow']['identity'][name]['raw'] and field.source == c.Source('public-source', page)
        assert result.disposition == c.Disposition.ACCEPTED
    else:
        assert parsed.escrow.identity is None and result.disposition == c.Disposition.HELD
        assert result.reason == 'missing printed components: identity'


def test_eligible_allocation_keeps_one_household_cash_movement(tmp_path):
    from viva.ingest import ReadResult, capture_and_ingest
    from viva.ledger.instruments import reference_accounts
    from viva.ingest.instrument_projector import heal_instruments
    raw, ledger = setup(tmp_path); bank(raw, ledger); data = mortgage()
    row = data['principal_movements'][0]; row.pop('amount')
    row.update(signed_effect={'raw': '-100', 'page': 1}, effect_basis='principal_balance_effect-v1', kind_source={'page': 1})
    text = json.dumps(data)
    def read(blob, doc_id):
        facts, error = parser_for('mortgage_statement', source_contract=MORTGAGE_SOURCE_CONTRACT, page_count=1)(text, doc_id, 'en-US', 'USD')
        assert error is None
        return ReadResult('mortgage_statement', 1, facts)
    result = capture_and_ingest(raw, ledger, b'public escrow source', read); proj = ledger.projection()
    assert len(proj.instrument_allocations()) == 1
    assert proj.running_balance(reference_accounts(proj, 'ESCROW-A')[0]) == Decimal('200')
    cash = [m for m in proj.movements() if m.account == reference_accounts(proj, 'CHECK-A')[0]]
    assert len(cash) == 1 and cash[0].amount == Decimal('-600')
    assert heal_instruments(ledger) == 0
    assert capture_and_ingest(raw, ledger, b'public escrow source', read).action == 'duplicate'
    assert result.action in {'posted', 'awaiting'}


from test_bulk_upload import setup_bulk


def test_actual_bulk_coordinator_selects_new_fragment(setup_bulk, monkeypatch):
    from viva.ingest import reader
    from viva.desktop_bridge.bulk_documents import BulkDocuments
    from viva.desktop_bridge.jobs import JobRegistry
    sample = setup_bulk
    class Adapter:
        def __init__(self): self.calls = 0
        def extract(self, pages, prompt):
            self.calls += 1
            if self.calls == 1:
                return response(json.dumps({'doc_type': 'mortgage_statement', 'doc_type_confidence': 1}))
            assert (PROMPTS / 'extract-mortgage-v3.txt').read_text() in prompt
            return response(json.dumps(proposal()))
    monkeypatch.setattr(reader, 'adapter_for', lambda _: Adapter())
    result = BulkDocuments(sample.vault, JobRegistry()).run({'paths': sample.paths})
    assert len(result['rows']) == 3
    extracts = [e.body for e in sample.vault.ledger.events() if e.event_type == 'ReadRecorded' and e.body['phase'] == 'extract']
    assert len(extracts) == 3 and all(e['parse_ok'] for e in extracts), result
    assert all(e['prompt_version'].startswith(NEW + '+') for e in extracts)
    assert all(e['normalization_context'] == encode_context(CONTEXT) for e in extracts)
    assert all(json.loads(e['response_text'])['principal_movements'][0]['signed_effect']['raw'] == '-100' for e in extracts)
