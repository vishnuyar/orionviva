"""Exact printed references attach new readings without rewriting posted identity."""
from dataclasses import replace
from decimal import Decimal as D

import pytest

from viva.ingest.statement import StatementFacts
from viva.ingest.brokerage import BrokerageFacts
from viva.ingest.statement_projector import post_statement, _resolve, _source_identity
from viva.ingest.brokerage_projector import post_brokerage, _post_brokerage_cash_and_snapshot
from viva.investment.extraction import InvestmentSource, SourceField
from viva.ledger import Ledger, LedgerProjection
from viva.ledger.events import document_captured, account_opened, account_alias_confirmed
from viva.ledger.identity import SourceAccountIdentity, account_key
from viva.ledger.instruments import reference_event
from viva.ingest.instrument_contracts import Source
from viva.read_store import ReadStore


class PublicLog:
    def __init__(self): self.rows = []
    def projection(self): return LedgerProjection(self.rows)
    def events(self): return iter(self.rows)
    def append(self, event): self.rows.append(event)


def facts(family='card', label='Aurora', ref='PUBLIC-A', month='01', doc=None, **changes):
    doc = doc or f'{family}-{month}'
    if family == 'broker':
        values = {'account_reference': ref, 'currency': 'USD',
            'period_start': f'2025-{month}-01', 'period_end': f'2025-{month}-28',
            'as_of': f'2025-{month}-28', 'opening_cash': '0', 'closing_cash': '0',
            'activity_complete': 'true', 'no_activity': 'true'}
        extension = InvestmentSource(tuple((key, SourceField(value, 1)) for key, value in values.items()), (), ())
        value = BrokerageFacts(doc, 'brokerage_statement', 1, label, 'USD',
            f'2025-{month}-28', D('0'), D('0'), [], investment_source=extension,
            institution='Example Issuer', account_names=['Synthetic Holder'],
            validated_source_page_count=1)
    else:
        value = StatementFacts(doc, 'credit_card_statement' if family == 'card' else 'checking_statement',
            1, label, 'USD', D('0'), f'2025-{month}-01', D('0'), f'2025-{month}-28', [],
            institution='Example Issuer', account_names=['Synthetic Holder'],
            source_account_ref=ref, source_account_ref_page=1, validated_source_page_count=1,
            opening_page=1, closing_page=1)
    return replace(value, **changes)


def capture(log, value):
    log.append(document_captured(value.doc_id, 'synthetic.pdf', 1, value.doc_type, 1, '2025-01-01'))


def post(log, value, *, evidence=False):
    capture(log, value)
    fn = post_brokerage if evidence else _post_brokerage_cash_and_snapshot
    return fn(log, value) if isinstance(value, BrokerageFacts) else post_statement(log, value)


@pytest.mark.parametrize('family', ['card', 'bank', 'broker'])
@pytest.mark.parametrize('months', [('01', '02'), ('02', '01')])
def test_same_printed_reference_reuses_persisted_id_across_labels_and_order(family, months):
    log = PublicLog()
    first = post(log, facts(family, month=months[0]))
    second = post(log, facts(family, label='Family Reserve', month=months[1]))
    assert first.action == second.action == 'posted'
    assert first.account == second.account
    assert log.projection().accounts() == [first.account]
    closes = [e for e in log.rows if e.event_type == 'ClosingBalanceObserved']
    assert {e.provenance.doc_id for e in closes} == {f'{family}-01', f'{family}-02'}
    assert {e.body['account_id'] for e in closes} == {first.account}
    assert LedgerProjection(log.rows).accounts() == [first.account]


@pytest.mark.parametrize('family', ['card', 'bank', 'broker'])
def test_different_exact_references_keep_equal_labels_separate(family):
    log = PublicLog()
    first = post(log, facts(family))
    second = post(log, facts(family, ref='PUBLIC-B', month='02'))
    assert first.action == second.action == 'posted'
    assert first.account != second.account
    assert len(log.projection().accounts()) == 2
    third = post(log, facts(family, label='Other Label', ref='PUBLIC-B', month='03'))
    assert third.account == second.account


@pytest.mark.parametrize('change', [dict(currency='EUR'), dict(institution='Distinct Issuer'),
    dict(account_names=['Other Holder']), dict(doc_type='checking_statement')])
def test_same_reference_does_not_cross_compatible_scope(change):
    log = PublicLog()
    first = post(log, facts())
    second = post(log, facts(month='02', **change))
    assert first.account != second.account
    assert len(log.projection().accounts()) == 2


@pytest.mark.parametrize('raw,page,bound', [('', 1, 1), ('   ', 1, 1), ('UNKNOWN', 1, 1),
    ('PUBLIC-A', None, 1), ('PUBLIC-A', 2, 1), ('PUBLIC-A', True, 1),
    ('PUBLIC-A', 1, None), ('PUBLIC-A', 1, True), ('**2468', 1, 1),
    ('123456', 1, 1), ('AB1234', 1, 1)])
def test_missing_uncertain_lossy_and_unvalidated_references_grant_no_exception(raw, page, bound):
    log = PublicLog()
    first = post(log, facts())
    value = facts(label='Family Reserve', month='02', source_account_ref=raw,
        source_account_ref_page=page, validated_source_page_count=bound)
    capture(log, value)
    assert _source_identity(value) is None
    assert _resolve(log.projection(), value).account_id != first.account


def test_untyped_or_uncaptured_claim_cannot_resolve_an_account():
    log = PublicLog(); first = post(log, facts())
    value = facts(label='Other Label', month='02')
    assert _resolve(log.projection(), value).account_id != first.account
    projection = log.projection()
    assert projection.resolve('Example Issuer', '', 'Other Label', ['Synthetic Holder'],
        kind='liability', doc_id=value.doc_id, currency='USD', source_identity='PUBLIC-A').verdict == 'new'


@pytest.mark.parametrize('family', ['card', 'broker'])
@pytest.mark.parametrize('number', ['12345678', '**5678'])
def test_numeric_signals_keep_precedence_over_contradictory_reference(number, family):
    log = PublicLog()
    first = post(log, facts(family, account_number=number))
    value = facts(family, month='02', ref='PUBLIC-B', account_number=number)
    assert post(log, value).account == first.account
    # A different full number remains separate even when the printed reference agrees.
    if number == '12345678':
        result = post(log, facts(family, month='03', account_number='87654321'))
        assert result.account != first.account


def test_conflicting_numeric_signals_remain_held_before_printed_reference():
    log = PublicLog(); post(log, facts())
    value = facts(month='02', label='ending in 2468', account_number='12345678')
    result = post(log, value)
    assert result.action == 'identity'


def test_multiple_reference_candidates_and_conflicting_history_remain_held():
    log = PublicLog()
    for aid in ('existing-a', 'existing-b'):
        value = facts(doc=aid)
        capture(log, value)
        log.append(account_opened(aid, 'liability', 'Different', 'USD', '2025-01-01',
            institution=value.institution, account_names=value.account_names))
        log.append(reference_event(aid, 'PUBLIC-A', '2025-01-01', Source(aid, 1), identity_page_count=1))
    incoming = facts(month='02'); capture(log, incoming)
    resolution = _resolve(log.projection(), incoming)
    assert resolution.verdict == 'ambiguous'
    assert set(resolution.candidates) == {'existing-a', 'existing-b'}
    single = PublicLog(); post(single, facts())
    account = single.projection().accounts()[0]
    single.append(reference_event(account, 'PUBLIC-B', '2025-01-01', Source('card-01', 1), identity_page_count=1))
    capture(single, incoming)
    assert _resolve(single.projection(), incoming).verdict == 'ambiguous'


@pytest.mark.parametrize('family', ['card', 'broker'])
def test_exact_document_ruling_and_safe_learned_ruling_retain_precedence(family):
    log = PublicLog(); first = post(log, facts(family))
    value = facts(family, month='02', ref='PUBLIC-B', label='Other Label')
    capture(log, value)
    log.append(account_alias_confirmed(account_key(value.institution, '', value.account_ref),
        first.account, value.doc_id, '2025-02-28', learn_signal=False))
    assert _resolve(log.projection(), value).account_id == first.account
    later = facts(family, month='03', ref='PUBLIC-C', label='Other Label')
    capture(log, later)
    log.append(account_alias_confirmed(account_key(value.institution, '', value.account_ref),
        first.account, value.doc_id, '2025-02-28', match_names=value.account_names,
        match_label=value.account_ref, kind='investment' if family == 'broker' else 'liability'))
    assert _resolve(log.projection(), later).account_id == first.account


@pytest.mark.parametrize('family', ['card', 'broker'])
def test_duplicate_and_retry_use_the_same_identity_boundary(family, tmp_path):
    log = Ledger.open(tmp_path / 'events.jsonl', 'synthetic-test-password')
    first = post(log, facts(family), evidence=True)
    second = post(log, facts(family, label='Family Reserve', doc='duplicate'), evidence=True)
    assert first.action == 'posted' and second.action == 'duplicate'
    assert log.projection().accounts() == [first.account]
    if family == 'broker':
        replay = post_brokerage(log, facts(family, label='Family Reserve', doc='duplicate'))
        assert replay.action == 'duplicate' and replay.account == first.account
        from viva.investment.events import STATEMENT
        observations = [e for e in log.events() if e.event_type == STATEMENT]
        assert {e.body['statement']['account']['value'] for e in observations} == {first.account}
        assert {e.provenance.doc_id for e in observations} == {'broker-01', 'duplicate'}


@pytest.mark.parametrize('family', ['card', 'broker'])
def test_encrypted_reopen_replay_sql_coverage_and_source_assignment(family, tmp_path):
    password = 'synthetic-test-password'
    path = tmp_path / 'events.jsonl'
    log = Ledger.open(path, password)
    first = post(log, facts(family), evidence=True)
    second = post(log, facts(family, label='Family Reserve', month='02'), evidence=True)
    before = [e.to_dict() for e in log.events()]
    reopened = Ledger.open(path, password)
    assert [e.to_dict() for e in reopened.events()] == before
    assert first.account == second.account
    assert LedgerProjection(reopened.events()).accounts() == [first.account]
    with ReadStore.create(tmp_path / 'sql', password) as reads:
        reads.synchronize(reopened.store)
        with reads.open_reader() as revision:
            overview = revision.overview_projection(today='2025-03-01')
            assert overview.accounts() == [first.account]
            rows = revision.statement_period_history(as_of='2025-03-01')
            assert {r['account_id'] for r in rows} == {first.account}
            assert {r['provenance_doc_id'] for r in rows} == {f'{family}-01', f'{family}-02'}
            assert len(revision.statement_coverage(as_of='2025-03-01')) == 2
            references = revision.connection.execute('SELECT account_id, reference, doc_id, page FROM instrument_account_references').fetchall()
            assert {(r[0], r[1], r[2], r[3]) for r in references} == {
                (first.account, 'PUBLIC-A', f'{family}-01', 1),
                (first.account, 'PUBLIC-A', f'{family}-02', 1)}
    assert [e.to_dict() for e in reopened.events()] == before


@pytest.mark.parametrize('family', ['card', 'broker'])
def test_legacy_facts_encoding_and_legacy_posted_assignments_are_preserved(family):
    value = facts(family, validated_source_page_count=None)
    encoded = value.to_dict()
    assert 'validated_source_page_count' not in encoded
    assert type(value).from_dict(encoded).to_dict() == encoded
    log = PublicLog()
    old = post(log, value)
    new = post(log, facts(family, label='Family Reserve', month='02'))
    assert old.account != new.account
    before = [e.to_dict() for e in log.rows]
    assert len(LedgerProjection(log.rows).accounts()) == 2
    assert [e.to_dict() for e in log.rows] == before


@pytest.mark.parametrize('reference', ['public-a', 'PUBLIC.A', 'PUBLIC-A '])
def test_printed_reference_comparison_preserves_case_punctuation_and_whitespace(reference):
    log = PublicLog(); first = post(log, facts())
    second = post(log, facts(ref=reference, month='02'))
    assert second.account != first.account


def test_full_brokerage_boundary_does_not_mistake_a_colliding_new_id_for_duplicate(tmp_path):
    log = Ledger.open(tmp_path / 'events.jsonl', 'synthetic-test-password')
    first = post(log, facts('broker'), evidence=True)
    second = post(log, facts('broker', ref='PUBLIC-B', doc='other-account'), evidence=True)
    assert first.action == second.action == 'posted'
    assert first.account != second.account
    assert len(log.projection().accounts()) == 2


@pytest.mark.parametrize('family', ['card', 'broker'])
def test_rendered_page_bound_is_local_reader_metadata_and_survives_held_encoding(monkeypatch, family):
    import json
    from types import SimpleNamespace
    from viva.ingest import reader
    from vivacore.models.base import ModelResult, PageImage
    value = facts(family)
    if family == 'card':
        proposal = {'account_ref': value.account_ref, 'institution': value.institution,
            'account_names': value.account_names, 'source_account_ref': 'PUBLIC-A',
            'source_account_ref_page': 1, 'opening': {'amount_raw': '0', 'date_raw': '2025-01-01', 'page': 1},
            'closing': {'amount_raw': '0', 'date_raw': '2025-01-28', 'page': 1}, 'transactions': []}
    else:
        proposal = {'account_ref': value.account_ref, 'institution': value.institution,
            'account_names': value.account_names, 'as_of_raw': '2025-01-28', 'cash_raw': '0',
            'total_raw': '0', 'positions': [], 'activity': [], 'investment_source': value.investment_source.to_dict()}
    proposal['validated_source_page_count'] = 199
    class Adapter:
        def __init__(self): self.calls = 0
        def extract(self, pages, prompt):
            self.calls += 1
            text = json.dumps({'doc_type': value.doc_type, 'doc_type_confidence': 1} if self.calls == 1 else proposal)
            return ModelResult(text=text, resolved_model='synthetic-model', input_tokens=0,
                output_tokens=0, cost_usd=0, latency_s=0, request={}, response={})
    adapter = Adapter()
    monkeypatch.setattr(reader, 'adapter_for', lambda spec: adapter)
    result = reader.read_prepared_statement((PageImage(1, b'synthetic', 'page'),), '', 'capture',
        SimpleNamespace(model='synthetic-model', json_mode=True), 'en-US', 'USD')
    assert result.error is None
    assert result.facts.validated_source_page_count == 1
    assert _source_identity(result.facts).page_count == 1
    assert type(result.facts).from_dict(result.facts.to_dict()).validated_source_page_count == 1


@pytest.mark.parametrize('raw,page,bound', [('', 1, 1), ('UNKNOWN', 1, 1),
    ('PUBLIC-A', None, 1), ('PUBLIC-A', 2, 1), ('PUBLIC-A', 1, None),
    ('**2468', 1, 1)])
def test_brokerage_unavailable_or_lossy_header_cannot_supply_identity(raw, page, bound):
    log = PublicLog(); first = post(log, facts('broker'))
    value = facts('broker', label='Other Label', month='02', validated_source_page_count=bound)
    headers = dict(value.investment_source.headers)
    headers['account_reference'] = SourceField(raw, page)
    value = replace(value, investment_source=replace(value.investment_source, headers=tuple(headers.items())))
    capture(log, value)
    assert _source_identity(value) is None
    assert _resolve(log.projection(), value).account_id != first.account


@pytest.mark.parametrize('family', ['card', 'broker'])
def test_legacy_reference_can_contradict_but_cannot_grant_new_identity(family):
    from viva.ingest.review import held_items
    from viva.ledger.events import statement_held
    log = PublicLog(); first = post(log, facts(family))
    log.append(reference_event(first.account, 'PUBLIC-B', '2025-01-28', Source(f'{family}-01', 1)))
    incoming = facts(family, label='Changed Label', month='02'); capture(log, incoming)
    result = _resolve(log.projection(), incoming)
    assert result.verdict == 'ambiguous' and result.candidates == (first.account,)
    assert post(log, incoming).action == 'identity'
    assert log.projection().open_holds()[0]['finding']['candidate'] == first.account
    assert held_items(log.projection())[0].held_balance is None
    # A legacy claim alone never grants a reference-based merge.
    unmarked = PublicLog(); old = post(unmarked, facts(family, validated_source_page_count=None))
    capture(unmarked, incoming)
    assert _resolve(unmarked.projection(), incoming).account_id != old.account


@pytest.mark.parametrize('which', ['same-changed-label', 'distinct-same-label'])
def test_actual_gap_held_balance_and_questions_keep_canonical_sql_identity_parity(which, tmp_path):
    from viva.ingest.review import held_items
    from viva.questions import _held_questions
    from viva.read_store.held import question_candidates
    password = 'synthetic-test-password'; path = tmp_path / 'events.jsonl'
    log = Ledger.open(path, password)
    first = post(log, facts(doc='first', opening_amount=D('50'), closing_amount=D('50')))
    if which == 'distinct-same-label':
        second = post(log, facts(ref='PUBLIC-B', doc='second', opening_amount=D('100'), closing_amount=D('100')))
        assert first.account != second.account
        incoming = facts(ref='PUBLIC-B', month='02', opening_amount=D('150'), closing_amount=D('150'))
        expected = '100'
    else:
        incoming = facts(label='Changed Label', month='02', opening_amount=D('75'), closing_amount=D('75'))
        expected = '50'
    assert post(log, incoming).action == 'gap'
    before = [e.to_dict() for e in log.events()]
    reopened = Ledger.open(path, password)
    canonical = reopened.projection()
    assert held_items(canonical)[0].held_balance == expected
    with ReadStore.create(tmp_path / 'reads', password) as reads:
        reads.synchronize(reopened.store)
        with reads.open_reader() as revision:
            item = revision.held_items(as_of='2025-03-01')[0]
            assert item['held_balance'] == expected
            actual = question_candidates(revision.connection, as_of='2025-03-01')
            assert actual == [q.to_dict() for q in _held_questions(canonical)]
    assert [e.to_dict() for e in reopened.events()] == before


def test_mixed_legacy_reference_history_remains_ambiguous_in_sql_held_reads(tmp_path):
    from viva.ledger.events import statement_held
    from viva.read_store.held import _identity_core
    from viva.ledger.projection.accounts import resolve
    log = Ledger.open(tmp_path / 'events.jsonl', 'synthetic-test-password')
    first = post(log, facts())
    log.append(reference_event(first.account, 'PUBLIC-B', '2025-01-28', Source('card-01', 1)))
    incoming = facts(label='Changed Label', month='02'); capture(log, incoming)
    log.append(statement_held(incoming.doc_id, incoming.to_dict(), {}, 'identity', '2025-02-28'))
    with ReadStore.create(tmp_path / 'reads', 'synthetic-test-password') as reads:
        reads.synchronize(log.store)
        with reads.open_reader() as revision:
            core = _identity_core(revision.connection, '2025-03-01')
            resolution = resolve(core, incoming.institution, '', incoming.account_ref,
                incoming.account_names, kind='liability', doc_id=incoming.doc_id,
                currency=incoming.currency, source_identity=_source_identity(incoming))
            assert resolution.verdict == 'ambiguous' and resolution.candidates == (first.account,)
            rows = revision.connection.execute('SELECT identity_page_count FROM instrument_account_references ORDER BY source_sequence').fetchall()
            assert rows == [(1,), (None,)]


@pytest.mark.parametrize('which', ['capture-rows', 'reference-rows', 'reference-bytes'])
def test_sql_identity_source_inputs_keep_bounded_read_guards(tmp_path, monkeypatch, which):
    from viva.read_store import held as held_module
    from viva.read_store.store import ReadStoreError
    log = Ledger.open(tmp_path / 'events.jsonl', 'synthetic-test-password')
    first = post(log, facts())
    if which == 'capture-rows':
        from viva.ledger.events import statement_held
        incoming = facts(doc='second-capture', month='02')
        capture(log, incoming)
        log.append(statement_held(incoming.doc_id, incoming.to_dict(), {}, 'gap', incoming.closing_date))
    elif which == 'reference-rows':
        log.append(reference_event(first.account, 'PUBLIC-B', '2025-01-28', Source('card-01', 1)))
    with ReadStore.create(tmp_path / 'reads', 'synthetic-test-password') as reads:
        reads.synchronize(log.store)
        if which == 'reference-bytes':
            reads.publish(lambda connection: connection.execute(
                'UPDATE instrument_account_references SET reference=?', ('X' * (held_module.MAX_IDENTITY_SCALAR_BYTES + 1),)), copy_current=True)
        else:
            monkeypatch.setattr(held_module, 'MAX_ACCOUNT_HISTORY_ROWS', 1)
        with reads.open_reader() as revision:
            with pytest.raises(ReadStoreError, match='source capture history|source reference history|scalar exceeds'):
                held_module._identity_core(revision.connection, '2025-03-01')


@pytest.mark.parametrize('which', ['same-changed-label', 'distinct-same-label'])
def test_adjacent_identity_bridge_suppresses_only_its_source_account_gap(which, tmp_path):
    from viva.ledger.events import statement_held
    from viva.questions import _held_questions
    from viva.read_store.held import question_candidates
    log = Ledger.open(tmp_path / 'events.jsonl', 'synthetic-test-password')
    first = post(log, facts(doc='first', opening_amount=D('50'), closing_amount=D('50')))
    if which == 'distinct-same-label':
        target = post(log, facts(ref='PUBLIC-B', doc='second', opening_amount=D('100'), closing_amount=D('100'))).account
        bridge = facts(ref='PUBLIC-B', month='02', doc='bridge', opening_amount=D('100'), closing_amount=D('150'))
        gap = facts(ref='PUBLIC-B', month='03', doc='gap', opening_amount=D('150'), closing_amount=D('150'))
    else:
        target = first.account
        bridge = facts(month='02', doc='bridge', opening_amount=D('50'), closing_amount=D('75'))
        gap = facts(label='Changed Label', month='03', doc='gap', opening_amount=D('75'), closing_amount=D('75'))
    capture(log, bridge)
    log.append(statement_held('bridge', bridge.to_dict(), {'candidate': target, 'candidates': [target]},
        'identity', bridge.closing_date))
    assert post(log, gap).action == 'gap'
    expected = [q.to_dict() for q in _held_questions(log.projection())]
    assert [q['refs']['doc_id'] for q in expected] == ['bridge']
    with ReadStore.create(tmp_path / 'reads', 'synthetic-test-password') as reads:
        reads.synchronize(log.store)
        with reads.open_reader() as revision:
            assert question_candidates(revision.connection, as_of='2025-04-01') == expected



def test_duplicate_capture_multiplicity_preserves_source_aware_held_balance_and_raw_history(tmp_path):
    from viva.ingest.review import held_items
    from viva.read_store.held import _identity_core
    password = 'synthetic-test-password'
    log = Ledger.open(tmp_path / 'events.jsonl', password)
    first = post(log, facts(doc='first', opening_amount=D('50'), closing_amount=D('50')))
    incoming = facts(doc='held', label='Changed Label', month='02',
        opening_amount=D('75'), closing_amount=D('75'))
    assert post(log, incoming).action == 'gap'
    log.store.append_atomically(lambda _events: tuple(
        document_captured('first', 'synthetic.pdf', 1, 'credit_card_statement', 1, '2025-01-01')
        for _ in range(10_001)))
    reopened = Ledger.open(tmp_path / 'events.jsonl', password)
    assert held_items(reopened.projection())[0].held_balance == '50'
    assert reopened.projection().accounts() == [first.account]
    with ReadStore.create(tmp_path / 'reads', password) as reads:
        reads.synchronize(reopened.store)
        with reads.open_reader() as revision:
            assert revision.held_items(as_of='2025-03-01')[0]['held_balance'] == '50'
            assert set(_identity_core(revision.connection, '2025-03-01')._captured) == {'first', 'held'}
            assert revision.connection.execute('SELECT COUNT(*) FROM documents').fetchone()[0] == 10_003
            assert revision.connection.execute('SELECT COUNT(*) FROM document_library').fetchone()[0] == 2



def test_reference_membership_accepts_existing_ten_thousand_row_boundary_then_refuses_one_more(tmp_path):
    from viva.read_store.held import _identity_core
    from viva.read_store.store import ReadStoreDegraded
    password = 'synthetic-test-password'
    log = Ledger.open(tmp_path / 'events.jsonl', password)
    first = post(log, facts(doc='first'))
    # Only the first document is captured; unavailable sources gain no authority.
    log.store.append_atomically(lambda _events: tuple(
        reference_event(first.account, 'PUBLIC-A', '2025-01-01',
            Source(f'uncaptured-source-{index}', 1), identity_page_count=1)
        for index in range(9_999)))
    with ReadStore.create(tmp_path / 'reads', password) as reads:
        reads.synchronize(log.store)
        with reads.open_reader() as revision:
            statements = []
            revision.connection.set_trace_callback(statements.append)
            core = _identity_core(revision.connection, '2025-03-01')
            revision.connection.set_trace_callback(None)
            assert len(core._instrument_account_refs[first.account]) == 10_000
            assert set(core._captured) == {'first'}
            captures = [sql for sql in statements if 'FROM documents d WHERE' in sql]
            assert len(captures) == 1
            plan = ' '.join(str(row[3]) for row in revision.connection.execute(
                'EXPLAIN QUERY PLAN ' + captures[0]))
            assert 'documents_by_doc' in plan
            assert 'USE TEMP B-TREE' not in plan and 'AUTOMATIC' not in plan.upper()
        log.store.append_atomically(lambda _events: (reference_event(first.account,
            'PUBLIC-A', '2025-01-01', Source('uncaptured-extra-source', 1), identity_page_count=1),))
        with pytest.raises(ReadStoreDegraded) as failure:
            reads.synchronize(log.store)
        assert 'identity source reference history' in str(failure.value.__cause__)


def test_source_capture_membership_preserves_reference_and_capture_as_of_boundaries(tmp_path):
    from viva.read_store.held import _identity_core
    log = Ledger.open(tmp_path / 'events.jsonl', 'synthetic-test-password')
    first = post(log, facts(doc='first'))
    for doc, captured, referenced in [('future-reference', '2025-01-01', '2025-04-01'),
                                      ('future-capture', '2025-04-01', '2025-02-01')]:
        log.append(document_captured(doc, 'synthetic.pdf', 1, 'credit_card_statement', 1, captured))
        log.append(reference_event(first.account, 'PUBLIC-A', referenced, Source(doc, 1), identity_page_count=1))
    log.append(document_captured('unrelated-capture', 'synthetic.pdf', 1, 'unknown', 0, '2025-01-01'))
    with ReadStore.create(tmp_path / 'reads', 'synthetic-test-password') as reads:
        reads.synchronize(log.store)
        with reads.open_reader() as revision:
            past = _identity_core(revision.connection, '2025-03-01')
            current = _identity_core(revision.connection, '2025-05-01')
            assert set(past._captured) == {'first'}
            assert set(current._captured) == {'first', 'future-reference', 'future-capture'}
