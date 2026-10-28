"""Active extraction requests source claims without changing their authority."""
import copy
import json
from pathlib import Path
from decimal import Decimal

import pytest

from viva.ingest.registry import extraction_prompt_for, profile_for
from viva.ingest.prompt_library import resolve
from viva.ingest.brokerage import from_brokerage_json, BrokerageFacts
from viva.investment.extraction import HEADERS, POSITION, ROW, parse
from viva.investment.contracts import EvidenceError, ROLES
from viva.investment.payroll_extraction import validate_pages
from test_extraction import fixture, legacy
from test_nonbank_funding import source_packet


def test_active_brokerage_and_retirement_request_closed_source_v2_shape():
    profile = profile_for('brokerage_statement')
    assert profile_for('401k_statement') is profile
    assert profile.profile_version == 'brk-v7'
    assert profile.type_fragment == 'brokerage-v2'
    text, version = extraction_prompt_for('401k_statement')
    assert version == 'extract:brokerage-base-v7+brokerage-v2'
    assert resolve(version) == text
    start = text.index('{\n  "investment_source"')
    example, _ = json.JSONDecoder().raw_decode(text[start:])
    assert set(example) == {'investment_source'}
    source = example['investment_source']
    assert source['schema'] == 'investment-source-v2'
    assert set(source['headers']) == set(HEADERS)
    assert set(source['positions'][0]) == set(POSITION)
    assert set(source['rows'][0]) == set(ROW)
    assert parse(source).to_dict() == source
    assert all(role in text for role in ROLES)
    for rule in ('SAME ORDER', 'page-one default', 'EXPLICITLY PRINTS',
                 'never computed', 'canonical account ids',
                 'duplicate printed lines', 'Do not truncate'):
        assert rule in text
    assert 'investment_source' not in resolve('brokerage-base-v4')


def test_source_v2_complete_packet_keeps_printed_row_reference_and_unknown_role():
    data = source_packet(True, role='unknown')
    data['investment_source']['rows'][0]['printed_row_reference'] = {
        'raw': 'PRINTED-ROW-A', 'page': 1}
    facts, error = from_brokerage_json(json.dumps(data), 'public-source', 'en-US', 'USD')
    assert error is None
    assert facts.investment_source.to_dict() == data['investment_source']
    assert BrokerageFacts.from_dict(facts.to_dict()).to_dict() == facts.to_dict()
    role = dict(facts.investment_source.rows[0])['funding_role']
    assert role.role == 'unknown'
    assert not hasattr(role, 'grade')
    bad = copy.deepcopy(data)
    bad['investment_source']['rows'][0]['funding_role']['role'] = 'accepted_funding'
    failed, error = from_brokerage_json(json.dumps(bad), 'public-source', 'en-US', 'USD')
    assert failed is None and error.startswith('investment source:')


def test_absent_extension_and_v1_stay_readable_after_profile_promotion():
    ordinary = legacy()
    facts, error = from_brokerage_json(json.dumps(ordinary), 'public-source', 'en-US', 'USD')
    assert error is None and facts.investment_source is None
    ordinary['investment_source'] = fixture()
    facts, error = from_brokerage_json(json.dumps(ordinary), 'public-source', 'en-US', 'USD')
    assert error is None
    assert facts.investment_source.schema == 'investment-source-v1'
    assert facts.investment_source.to_dict() == ordinary['investment_source']


def test_source_precision_signed_gain_missing_pages_and_duplicate_rows_are_not_repaired():
    data = legacy()
    data['positions'][0]['units_raw'] = '1.250000000001'
    data['activity'] = [{'date_raw': '01/25/2025', 'kind': 'sell',
                         'amount_raw': '25.00', 'instrument': 'TEST-SEC',
                         'realized_gain_raw': '-2.12345678', 'description': 'Sale'}]
    source = fixture()
    source['schema'] = 'investment-source-v2'
    source['positions'][0]['units']['raw'] = '1.250000000001'
    source['rows'][0]['kind']['raw'] = 'sell'
    source['rows'][0]['reported_realized_gain'] = {'raw': '-2.12345678', 'page': None}
    source['rows'].append(copy.deepcopy(source['rows'][0]))
    data['investment_source'] = source
    facts, error = from_brokerage_json(json.dumps(data), 'public-source', 'en-US', 'USD')
    assert error is None
    assert facts.positions[0].units == Decimal('1.250000000001')
    assert facts.activity[0].realized_gain == Decimal('-2.12345678')
    assert facts.investment_source.to_dict() == source
    assert len(facts.investment_source.rows) == 2
    assert dict(facts.investment_source.rows[0])['reported_realized_gain'].page is None
    bad = copy.deepcopy(source)
    bad['rows'][0]['amount']['page'] = 2
    with pytest.raises(EvidenceError):
        validate_pages(parse(bad), 1)


def test_empty_activity_is_not_a_printed_assertion_and_authority_fields_refuse():
    source = fixture()
    source['schema'] = 'investment-source-v2'
    source['rows'] = []
    actual = parse(source)
    assert dict(actual.headers)['no_activity'] is None
    source['headers']['no_activity'] = {'raw': 'No activity this period', 'page': 1}
    printed = parse(source)
    assert dict(printed.headers)['no_activity'].raw == 'No activity this period'
    for field in ('grade', 'status', 'canonical_account', 'cash_event_id', 'event_digest'):
        bad = copy.deepcopy(source)
        bad['headers'][field] = None
        with pytest.raises(EvidenceError):
            parse(bad)


def test_known_and_unknown_position_classes_keep_separate_source_pages():
    from viva.ingest.instrument_read import validate_sources
    data = legacy()
    data['positions'][0]['classification'] = {
        'exposure': 'bond', 'vehicle': 'mutual_fund',
        'exposure_page': 1, 'vehicle_page': 1}
    facts, error = from_brokerage_json(json.dumps(data), 'public-source', 'en-US', 'USD')
    assert error is None
    validate_sources([facts.positions[0].classification], 'public-source', 1)
    data['positions'][0]['classification']['vehicle_page'] = 2
    facts, error = from_brokerage_json(json.dumps(data), 'public-source', 'en-US', 'USD')
    assert error is None
    with pytest.raises(ValueError):
        validate_sources([facts.positions[0].classification], 'public-source', 1)
    data['positions'][0]['classification'] = {
        'exposure': 'unknown', 'vehicle': 'unknown',
        'exposure_page': None, 'vehicle_page': None}
    facts, error = from_brokerage_json(json.dumps(data), 'public-source', 'en-US', 'USD')
    assert error is None
    assert facts.positions[0].classification.exposure.value == 'unknown'
    assert facts.positions[0].classification.vehicle.value == 'unknown'


def _printed_brokerage_reading():
    sample = Path(__file__).parents[2] / 'viva/sample_data/five-year-life-v1/readings.json'
    records = json.loads(sample.read_text())['readings']
    reading = next(row for row in records if row['document_id'] == 'D0007')
    data = reading['envelope']['parser_input']
    return json.loads(data) if isinstance(data, str) else copy.deepcopy(data)


def _post_and_build(data, tmp_path):
    from viva.ingest.brokerage_projector import post_brokerage
    from viva.ledger.ledger import Ledger
    from viva.ledger.events import document_captured
    from viva.investment.projector import build
    facts, error = from_brokerage_json(json.dumps(data), 'printed-public', 'en-US', 'USD')
    assert error is None
    validate_pages(facts.investment_source, 1)
    ledger = Ledger.open(tmp_path / 'events.jsonl', 'synthetic-only')
    ledger.append(document_captured('printed-public', 'public.pdf', 1, 'UNKNOWN', 0.0,
                                    '2021-01-31'))
    posted = post_brokerage(ledger, facts)
    if posted.action != 'posted':
        return posted, None
    return posted, build(facts, posted.account, tuple(ledger.events()))


@pytest.mark.parametrize('instrument', ['AAPL', 'Apple Inc.'])
def test_exact_printed_identifier_or_separate_label_reaches_production_source_build(
        tmp_path, instrument):
    data = _printed_brokerage_reading()
    data['positions'][0]['instrument'] = instrument
    posted, statement = _post_and_build(data, tmp_path)
    assert posted.action == 'posted'
    assert statement.disposition == 'accepted_complete_nonempty'
    assert len(statement.positions) == 3 and len(statement.rows) == 7


@pytest.mark.parametrize('mutation,reason', [
    ('combined', 'position source identifier/label ambiguous'),
    ('case_changed', 'position source identifier/label ambiguous'),
    ('duplicate', 'position source identifier/label ambiguous'),
    ('missing', 'position source identifier unavailable'),
])
def test_prompt_promotion_preserves_exact_production_position_refusals(
        tmp_path, mutation, reason):
    data = _printed_brokerage_reading()
    if mutation == 'combined':
        data['positions'][0]['instrument'] = 'AAPL Apple Inc.'
    elif mutation == 'case_changed':
        data['positions'][0]['instrument'] = 'Apple inc.'
    elif mutation == 'duplicate':
        data['positions'][1]['instrument'] = 'AAPL'
    else:
        data['investment_source']['positions'][0]['identifier'] = None
    with pytest.raises(EvidenceError, match=reason):
        _post_and_build(data, tmp_path)


def test_activity_identity_is_local_to_its_printed_row_and_mismatch_stays_held(tmp_path):
    data = _printed_brokerage_reading()
    row = data['activity'][1]
    source = data['investment_source']['rows'][1]['security_identifier']
    assert row['instrument'] == source['raw']
    assert source['page'] == 1
    assert row['instrument'] != data['investment_source']['positions'][0]['identifier']['raw']
    row['instrument'] = 'AAPL'
    posted, statement = _post_and_build(data, tmp_path)
    assert posted.action == 'posted'
    assert statement.disposition == 'held' and not statement.rows


def test_numeric_contradiction_cannot_be_rescued_by_consistent_security_names(tmp_path):
    data = _printed_brokerage_reading()
    data['total_raw'] = '1.00'
    posted, statement = _post_and_build(data, tmp_path)
    assert posted.action != 'posted' and statement is None


def test_active_request_demands_printed_row_local_copy_without_inventing_identifiers():
    text, _ = extraction_prompt_for('brokerage_statement')
    for rule in ('ROW-LOCAL', 'COPY the same characters', 'EXACTLY equal',
                 'THAT activity row', 'source identifier null',
                 'Preserve descriptions AS PRINTED', 'Never\nrecase, abbreviate',
                 'do not concatenate identifier and name'):
        assert rule in text
