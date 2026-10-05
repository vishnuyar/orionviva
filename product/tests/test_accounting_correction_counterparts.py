"""Dedicated corrections consume generic counterpart meaning before persistence."""
import json
from types import SimpleNamespace

import pytest
from vivacore import versions
from viva import engine
from viva.accounting_intelligence import (PACKAGE, active_rules, apply_learned_rules,
    correct_accounting, undo_accounting)
from viva.ledger import EventStore, Ledger, Posting
from viva.ledger.events import account_opened, transaction_recorded, Provenance
from viva.ledger.postings import MAJOR_UNCATEGORIZED
from viva.ledger.projection.movements import counts_as_spending
from viva.ledger.accounting import financial_statements
from viva.listen import Interpretation, propose, resolve_account
from viva.reply import INTERPRET_VERSION
from viva.vault import Vault


def synthetic(tmp_path):
    ledger = Ledger(EventStore.open(tmp_path / 'events', 'synthetic'))
    for path, kind in [('Assets:Bank:Invented', 'depository'),
                       ('Liabilities:Card:Invented', 'liability')]:
        ledger.append(account_opened(path, kind, 'Invented source', 'USD', '2026-01-01'))
    return SimpleNamespace(ledger=ledger)


def movement(v, account='Liabilities:Card:Invented', amount='-25', day='2026-01-03',
             description='SYNTHETIC REPAYMENT', doc='synthetic'):
    from decimal import Decimal
    v.ledger.append(transaction_recorded([Posting(account, amount, 'verified'),
        Posting('Expenses:Uncategorized', str(-Decimal(amount)), 'verified')],
        description, day, provenance=Provenance(doc_id=doc)))
    return next(m for m in v.ledger.projection().movements()
                if m.account == account and m.date == day and m.description == description
                and m.amount == Decimal(amount))


def correct(v, keys, payload, said='This repays the debt from my bank account.', prompts=None):
    def model(prompt):
        if prompts is not None:
            prompts.append(prompt)
        return json.dumps(payload)
    return correct_accounting(v, said, keys, interpret_fn=model)


def ordinary(major, **extra):
    return {'counterpart_mode': 'ordinary', 'legs': [
        {'major': major, 'account_hint': '', 'share': ''}], **extra}


@pytest.mark.parametrize('account,major,nature,direction', [
    ('Liabilities:Card:Invented', 'asset', 'transfer', 'in'),
    ('Assets:Bank:Invented', 'liability', 'settlement', 'out')])
def test_ordinary_repayment_is_one_counterpart_without_holdings(tmp_path, account, major, nature, direction):
    v = synthetic(tmp_path)
    selected = movement(v, account)
    before = [e for e in v.ledger.events() if e.event_type == 'TransactionRecorded']
    accounts = set(v.ledger.projection().accounts())
    prompts = []
    result = correct(v, [selected.key], ordinary(major), prompts=prompts)
    assert result['ok'] and not result['confirm'] and result['rule_id']
    assert 'You can undo' in result['message']
    proj = v.ledger.projection()
    current = proj.movements()[0]
    assert current.nature == nature and not counts_as_spending(current)
    assert current.amount == selected.amount and current.currency == selected.currency
    assert set(proj.accounts()) == accounts
    assert [e for e in v.ledger.events() if e.event_type == 'TransactionRecorded'] == before
    expected = [{'major': major, 'account': MAJOR_UNCATEGORIZED[major], 'share': ''}]
    assert proj.rulings('movement')[0]['legs'] == expected
    assert active_rules(v.ledger)[0]['legs'] == expected
    assert proj.rulings('movement')[0]['prompt_version'] == versions.active(PACKAGE, 'accounting_correction')
    assert f'- direction: {direction}' in prompts[0]
    assert v.ledger.fresh_projection().rulings('movement') == proj.rulings('movement')
    for event in v.ledger.events():
        if event.event_type in ('RulingRecorded', 'AccountingRuleRecorded', 'AccountingCorrectionRecorded'):
            assert 'counterpart_mode' not in json.dumps(event.body)
            assert 'ordinary_counterpart' not in json.dumps(event.body)
    assert undo_accounting(v, result['correction_id'])['changed'] == 1
    assert not active_rules(v.ledger) and not v.ledger.projection().rulings('movement')
    assert set(v.ledger.projection().accounts()) == accounts


@pytest.mark.parametrize('payload', [
    {'counterpart_mode': mode, 'legs': [{'major': 'asset'}]}
    for mode in ('other', '', None, [], {'value': 'ordinary'}, 'Ordinary')
] + [
    {'counterpart_mode': 'ordinary', 'legs': legs} for legs in (
        [], [{'major': 'asset'}, {'major': 'liability'}],
        [{'major': 'asset'}, {'major': 'invalid'}],
        [{'major': 'asset'}, None], [{'major': 'invalid'}],
        [{'major': 'asset', 'account_hint': 'Bank account'}],
        [{'major': 'asset', 'account_hint': None}],
        [{'major': 'asset', 'share': '100%'}],
        [{'major': 'asset', 'share': 'unstated'}],
        [{'major': 'asset', 'share': None}],
        {'major': 'asset'},
    )
])
def test_invalid_mode_or_ordinary_shape_never_applies_a_prefix(tmp_path, payload):
    v = synthetic(tmp_path)
    selected = movement(v)
    before = list(v.ledger.events())
    prompts = []
    result = correct(v, [selected.key], payload, prompts=prompts)
    assert not result['ok']
    assert len(prompts) == 1
    assert list(v.ledger.events()) == before


@pytest.mark.parametrize('mode', ['components', None])
@pytest.mark.parametrize('major', ['asset', 'liability'])
def test_unnamed_holding_and_legacy_empty_hint_require_identity(tmp_path, mode, major):
    v = synthetic(tmp_path)
    selected = movement(v)
    payload = {'legs': [{'major': major, 'account_hint': '', 'share': ''}]}
    if mode is not None:
        payload['counterpart_mode'] = mode
    before = list(v.ledger.events())
    result = correct(v, [selected.key], payload)
    assert not result['ok'] and result['why'] == 'needs_name'
    assert list(v.ledger.events()) == before
    assert resolve_account(v.ledger.projection(), major, '').verdict == 'unnamed'
    assert propose(v.ledger.projection(), Interpretation(legs=payload['legs']),
                   selected.description, movement_key=selected.key).needs_name == [major]


@pytest.mark.parametrize('mode', ['components', None])
@pytest.mark.parametrize('majors', [('asset',), ('liability',),
    ('asset', 'liability'), ('liability', 'liability')])
def test_genuine_named_holdings_same_role_and_compounds_remain(tmp_path, mode, majors):
    v = synthetic(tmp_path)
    selected = movement(v)
    legs = [{'major': major, 'account_hint': f'Workshop relationship {i}', 'share': ''}
            for i, major in enumerate(majors)]
    payload = {'legs': legs, 'future_scope': 'one'}
    if mode is not None:
        payload['counterpart_mode'] = mode
    result = correct(v, [selected.key], payload, said='These are distinct holdings and debts.')
    assert result['ok'], result
    ruling = v.ledger.projection().rulings('movement')[0]
    assert [leg['major'] for leg in ruling['legs']] == list(majors)
    assert all(leg['share'] == '' for leg in ruling['legs'])
    assert len([e for e in v.ledger.events() if e.event_type == 'AccountOpened']) == 2 + len(majors)
    assert not active_rules(v.ledger)


def test_components_keep_ambiguous_target_identification(tmp_path):
    v = synthetic(tmp_path)
    selected = movement(v)
    for name in ('Workshop equipment east', 'Workshop equipment west'):
        v.ledger.append(account_opened(f'Assets:Other:{name}', 'asset', name, 'USD', '2026-01-01'))
    before = list(v.ledger.events())
    result = correct(v, [selected.key], {'counterpart_mode': 'components',
        'legs': [{'major': 'asset', 'account_hint': 'Workshop equipment'}]})
    assert not result['ok'] and result['why'] == 'account_required'
    assert list(v.ledger.events()) == before


def test_components_keep_exact_existing_holding_without_opening_account(tmp_path):
    v = synthetic(tmp_path)
    selected = movement(v)
    v.ledger.append(account_opened('Assets:Other:Workshop equipment', 'asset', 'Workshop equipment', 'USD', '2026-01-01'))
    before = set(v.ledger.projection().accounts())
    result = correct(v, [selected.key], {'counterpart_mode': 'components',
        'legs': [{'major': 'asset', 'account_hint': 'Workshop equipment'}]})
    assert result['ok'] and set(v.ledger.projection().accounts()) == before
    assert v.ledger.projection().rulings('movement')[0]['legs'][0]['account'] == 'Assets:Other:Workshop equipment'


@pytest.mark.parametrize('share,said,expected', [
    ('80%', 'This was 80% principal and 20% interest.', ['0.8', '0.2']),
    ('80%', 'This was principal and interest.', ['', ''])])
def test_components_preserve_only_explicit_numeric_allocations(tmp_path, share, said, expected):
    v = synthetic(tmp_path)
    selected = movement(v, 'Assets:Bank:Invented')
    result = correct(v, [selected.key], {'counterpart_mode': 'components', 'legs': [
        {'major': 'liability', 'account_hint': 'Workshop loan', 'share': share},
        {'major': 'expense', 'account_hint': 'interest', 'share': '20%'}]}, said=said)
    assert result['ok'], result
    assert [l['share'] for l in v.ledger.projection().rulings('movement')[0]['legs']] == expected
    assert [l['share'] for l in active_rules(v.ledger)[0]['legs']] == ['', '']


@pytest.mark.parametrize('major,nature,said', [
    ('expense', 'spending', 'This is an ordinary refund reversing my expense.'),
    ('income', 'spending', 'This is an ordinary reward.'),
    ('income', 'spending', 'This is legitimate income.'),
    ('asset', 'transfer', 'This is an ordinary transfer.')])
def test_other_ordinary_meanings_remain_available(tmp_path, major, nature, said):
    v = synthetic(tmp_path)
    selected = movement(v, 'Assets:Bank:Invented', amount='25')
    result = correct(v, [selected.key], ordinary(major, future_scope='one'), said=said)
    assert result['ok'], result
    assert v.ledger.projection().movements()[0].nature == nature
    assert len([e for e in v.ledger.events() if e.event_type == 'AccountOpened']) == 2


def test_outbound_addition_is_only_categorical_role_direction_count(tmp_path):
    v = synthetic(tmp_path)
    selected = movement(v, amount='-731.29', description='PRIVATE SOURCE SENTINEL')
    prompts = []
    said = 'Explicitly submitted explanation sentinel'
    assert correct(v, [selected.key], ordinary('asset'), said=said, prompts=prompts)['ok']
    context = prompts[0].split('What is already known:\n')[1].split('\n\nFill exactly')[0]
    assert context == '- selected_transactions: 1\n- source_role: liability\n- direction: in'
    assert said in prompts[0]
    for private in (selected.key, selected.account, selected.description, '731.29', selected.date):
        assert private not in prompts[0]


def test_mixed_context_lists_preserve_order_and_incompatible_response_writes_nothing(tmp_path):
    v = synthetic(tmp_path)
    card = movement(v)
    bank = movement(v, 'Assets:Bank:Invented')
    before = list(v.ledger.events())
    prompts = []
    result = correct(v, [bank.key, card.key, bank.key],
        {'counterpart_mode': 'components', 'legs': []}, prompts=prompts)
    assert not result['ok'] and result['why'] == 'unanswered'
    assert len(prompts) == 1
    assert '- selected_transactions: 2' in prompts[0]
    assert '- source_role: ["depository", "liability"]' in prompts[0]
    assert '- direction: ["out", "in"]' in prompts[0]
    assert list(v.ledger.events()) == before


def test_homogeneous_batch_applies_to_all_selected_and_learns_narrowly(tmp_path):
    from viva.ingest import assign_category
    v = synthetic(tmp_path)
    first = movement(v)
    second = movement(v, day='2026-01-04')
    old = movement(v, day='2026-01-05')
    prompts = []
    result = correct(v, [first.key, second.key], ordinary('asset'), prompts=prompts)
    assert result['ok'] and result['changed'] == 2
    assert '- source_role: liability' in prompts[0]
    assert '- selected_transactions: 2' in prompts[0]
    assert {r['subject'] for r in v.ledger.projection().rulings('movement')} == {first.key, second.key}
    future = movement(v, day='2026-02-03')
    opposite = movement(v, amount='25', day='2026-02-04')
    other_role = movement(v, 'Assets:Bank:Invented', day='2026-02-05')
    other_purpose = movement(v, day='2026-02-06')
    assign_category(v.ledger, other_purpose.key, 'food', by='human')
    assert apply_learned_rules(v.ledger) == 1
    rulings = {r['subject']: r for r in v.ledger.projection().rulings('movement')}
    assert rulings[future.key]['legs'] == rulings[first.key]['legs']
    assert all(m.key not in rulings for m in (old, opposite, other_role, other_purpose))
    assert undo_accounting(v, result['correction_id'])['changed'] == 3
    assert not v.ledger.projection().rulings('movement')


def test_dedicated_prompt_preserves_general_interpreter_and_automatic_bytes():
    assert INTERPRET_VERSION == 'interpret-v4'
    assert versions.active(PACKAGE, 'accounting_interpret') == 'accounting-interpret-v3'
    assert versions.fingerprint(PACKAGE / 'prompts/interpret-v4.txt') == 'e91e7d9afd9e132c'
    assert versions.fingerprint(PACKAGE / 'prompts/accounting-interpret-v3.txt') == 'd766cd9532288de8'
    assert versions.audit(PACKAGE) == []


@pytest.mark.parametrize('account,kind,major,nature', [
    ('Liabilities:Card:Invented', 'liability', 'asset', 'transfer'),
    ('Assets:Bank:Invented', 'depository', 'liability', 'settlement')])
def test_ordinary_counterpart_reload_sql_parity_and_undo(tmp_path, monkeypatch, account, kind, major, nature):
    from viva import accounting_intelligence
    monkeypatch.setattr(engine, '_today', lambda: '2026-01-15')
    monkeypatch.setattr(accounting_intelligence, '_today', lambda: '2026-01-15')
    directory = tmp_path / 'synthetic-vault'
    v = Vault.open(directory, 'synthetic')
    v.ledger.append(account_opened(account, kind, 'Invented', 'USD', '2026-01-01'))
    selected = movement(v, account)
    baseline = financial_statements(v.ledger.projection(), end='2026-01-31')
    result = correct(v, [selected.key], ordinary(major))
    assert result['ok'], result
    expected = financial_statements(v.ledger.fresh_projection(), end='2026-01-31')
    v.close()
    v = Vault.open(directory, 'synthetic')
    assert v.ledger.projection().movements()[0].nature == nature
    assert financial_statements(v.ledger.projection(), end='2026-01-31') == expected
    for report in (expected, baseline):
        v.synchronize_read_store()
        with v.read_store.open_reader() as revision:
            assert financial_statements(revision.overview_projection(today='2026-01-31'), end='2026-01-31') == report
        if report is expected:
            assert undo_accounting(v, result['correction_id'])['changed'] == 1
            assert financial_statements(v.ledger.fresh_projection(), end='2026-01-31') == baseline
    v.close()


def test_ordinary_correction_preserves_linked_transfer_and_source_postings(tmp_path):
    from viva.ledger.events import transfer_linked
    v = synthetic(tmp_path)
    card = movement(v)
    bank = movement(v, 'Assets:Bank:Invented')
    v.ledger.append(transfer_linked(card.key, bank.key, 'verified', {}, '2026-01-04'))
    before = [e for e in v.ledger.events() if e.event_type in ('TransactionRecorded', 'TransferLinked')]
    result = correct(v, [card.key], ordinary('asset'))
    assert result['ok']
    assert all(m.linked and m.nature_reason == 'linked' and not counts_as_spending(m)
               for m in v.ledger.projection().movements())
    assert [e for e in v.ledger.events() if e.event_type in ('TransactionRecorded', 'TransferLinked')] == before
    assert undo_accounting(v, result['correction_id'])['changed'] == 1
    assert all(m.linked for m in v.ledger.projection().movements())
