"""Remembered treatment fills only explicitly default unknown purpose."""
import json
from decimal import Decimal
from types import SimpleNamespace

import pytest
from merchantcore.taxonomy import FALLBACK_CATEGORY, FALLBACK_SUBCATEGORY

from viva.accounting_intelligence import (active_rules, apply_learned_rules,
    context_key, correct_accounting, interpret_activity, undo_accounting)
from viva.ingest import assign_category
from viva.ledger import EventStore, Ledger, Posting
from viva.ledger.accounting import financial_statements
from viva.ledger.events import (Provenance, account_opened, category_assigned,
    merchant_enriched, accounting_rule_recorded, transaction_recorded)
from viva.ledger.postings import MAJOR_UNCATEGORIZED
from viva.vault import Vault

ACCOUNT = 'Liabilities:Card:Invented'
DESCRIPTION = 'SYNTHETIC PAYMENT TO INVENTED'


@pytest.fixture(autouse=True)
def isolated_environment(tmp_path, monkeypatch):
    home = tmp_path / 'home'
    home.mkdir()
    monkeypatch.setenv('HOME', str(home))
    monkeypatch.setenv('MERCHANTCORE_HOME', str(tmp_path / 'merchant'))
    monkeypatch.setenv('VIVA_ENV_FILE', str(home / 'synthetic.env'))


def vault(tmp_path):
    ledger = Ledger(EventStore.open(tmp_path / 'events', 'synthetic'))
    ledger.append(account_opened(ACCOUNT, 'liability', 'Invented', 'USD', '2026-01-01'))
    return SimpleNamespace(ledger=ledger)


def movement(v, day='2026-01-03', amount='-25', account=ACCOUNT,
             description=DESCRIPTION):
    v.ledger.append(transaction_recorded([Posting(account, amount, 'verified'),
        Posting('Expenses:Uncategorized', str(-Decimal(amount)), 'verified')],
        description, day, provenance=Provenance(doc_id='invented')))
    return next(m for m in v.ledger.projection().movements()
                if m.date == day and m.account == account and m.description == description)


def default(v, m, **attribution):
    event = category_assigned(m.key, m.description, FALLBACK_CATEGORY, 'unverified',
        m.date, by='default', subcategory=FALLBACK_SUBCATEGORY, **attribution)
    v.ledger.append(event)


def lesson(v, m, **scope):
    assign_category(v.ledger, m.key, 'transfers', by='human')
    result = correct_accounting(v, 'Use this debt repayment treatment for matching payments.',
        [m.key], interpret_fn=lambda _: json.dumps({'counterpart_mode':'ordinary',
            'legs':[{'major':'asset', 'account_hint':'', 'share':''}],
            'category':'debt_settlement', 'future_scope':'context', **scope}))
    assert result['ok'] and result['rule_id'], result
    return result


def rule(v, m, identity, *, purpose='transfers', major='asset', category='debt_settlement', **bounds):
    context = {**context_key(v.ledger.projection(), m), 'category':purpose,
               'subcategory':FALLBACK_SUBCATEGORY}
    v.ledger.append(accounting_rule_recorded(identity, 'invented-anchor', '2026-01-03',
        context, [{'major':major, 'account':MAJOR_UNCATEGORIZED[major], 'share':''}],
        '2026-01-03', category=category, said=identity, **bounds))


def ruling(v, m):
    return next((r for r in v.ledger.projection().rulings('movement')
                 if r['subject'] == m.key), None)


def test_future_default_payment_receives_existing_lesson_at_normal_entry(tmp_path):
    v = vault(tmp_path)
    first = movement(v)
    result = lesson(v, first)
    saved = active_rules(v.ledger)
    future = movement(v, day='2026-02-03')
    default(v, future)
    before = [e for e in v.ledger.events() if e.event_type == 'TransactionRecorded']
    prompts = []
    outcome = interpret_activity(v, extract_fn=lambda p: prompts.append(p))
    assert outcome['learned'] == 1
    assert prompts == []
    assert ruling(v, future)['by'] == 'human_rule'
    assert ruling(v, future)['legs'] == ruling(v, first)['legs']
    assert active_rules(v.ledger) == saved
    assert [e for e in v.ledger.events() if e.event_type == 'TransactionRecorded'] == before
    events = list(v.ledger.events())
    assert apply_learned_rules(v.ledger) == 0
    assert list(v.ledger.events()) == events
    assert undo_accounting(v, result['correction_id'])['changed'] == 2
    assert v.ledger.projection().derived_category(future)['by'] == 'default'
    assert not active_rules(v.ledger) and ruling(v, future) is None


@pytest.mark.parametrize('category_by,subcategory_by', [
    ('human','default'), ('model','default'), ('default','human'),
    ('default','model'), ('merchant','default'), ('default','merchant')])
def test_specific_attribution_blocks_unknown_compatibility(tmp_path, category_by, subcategory_by):
    v = vault(tmp_path)
    lesson(v, movement(v))
    future = movement(v, day='2026-02-03')
    default(v, future, category_by=category_by, subcategory_by=subcategory_by)
    assert apply_learned_rules(v.ledger) == 0
    assert ruling(v, future) is None


@pytest.mark.parametrize('category,subcategory,by', [
    (None,None,None), ('other','', 'default'), ('', 'unclassified','default'),
    ('food','unclassified','default'), ('other','tools','default'),
    ('other','unclassified','human'), ('other','unclassified','model')])
def test_absent_or_known_purpose_is_not_unknown(tmp_path, category, subcategory, by):
    v = vault(tmp_path)
    lesson(v, movement(v))
    future = movement(v, day='2026-02-03')
    if category is not None:
        v.ledger.append(category_assigned(future.key, future.description, category,
            'unverified', future.date, by=by, subcategory=subcategory))
    assert apply_learned_rules(v.ledger) == 0


def test_legacy_record_wide_default_attribution_remains_eligible(tmp_path):
    v = vault(tmp_path)
    lesson(v, movement(v))
    future = movement(v, day='2026-02-03')
    event = category_assigned(future.key, future.description, 'other', 'unverified',
        future.date, by='default', subcategory='unclassified')
    del event.body['category_by']
    del event.body['subcategory_by']
    v.ledger.append(event)
    assert apply_learned_rules(v.ledger) == 1


def test_effective_merchant_category_blocks_default_overlay(tmp_path):
    v = vault(tmp_path)
    first = movement(v, description='SYNTHETIC WORKSHOP')
    lesson(v, first)
    future = movement(v, day='2026-02-03', description=first.description)
    default(v, future)
    v.ledger.append(merchant_enriched(v.ledger.projection().merchant_key_of(future),
        'other', by='model', occurred_at='2026-02-03'))
    effective = v.ledger.projection().derived_category(future)
    assert effective['category_by'] == 'model' and effective['subcategory_by'] == 'default'
    assert apply_learned_rules(v.ledger) == 0


@pytest.mark.parametrize('difference', ['legs', 'category'])
@pytest.mark.parametrize('exact_first', [False, True])
def test_unknown_pool_refuses_conflicting_exact_and_compatible_outputs(tmp_path, difference, exact_first):
    v = vault(tmp_path)
    future = movement(v, day='2026-02-03')
    default(v, future)
    purposes = ('other','transfers') if exact_first else ('transfers','other')
    rule(v, future, 'earlier', purpose=purposes[0])
    rule(v, future, 'later', purpose=purposes[1],
         major='expense' if difference == 'legs' else 'asset',
         category='food' if difference == 'category' else 'debt_settlement')
    before = list(v.ledger.events())
    assert apply_learned_rules(v.ledger) == 0
    assert list(v.ledger.events()) == before
    outcome = interpret_activity(v, extract_fn=lambda _: json.dumps({'interpretations':[
        {'ref':'m0','majors':['income'], 'grounds':'Working baseline'}]}))
    assert outcome['learned'] == 0 and ruling(v, future)['by'] == 'model'


def test_same_outputs_keep_latest_rule_despite_different_unknown_context(tmp_path):
    v = vault(tmp_path)
    future = movement(v, day='2026-02-03')
    default(v, future)
    rule(v, future, 'earlier', purpose='other')
    rule(v, future, 'later', purpose='transfers')
    assert apply_learned_rules(v.ledger) == 1
    assert ruling(v, future)['said'] == 'later'


def test_known_purpose_keeps_exact_latest_precedence_despite_conflicting_outputs(tmp_path):
    v = vault(tmp_path)
    future = movement(v, day='2026-02-03')
    assign_category(v.ledger, future.key, 'transfers', by='model')
    rule(v, future, 'earlier')
    rule(v, future, 'later', major='expense', category='food')
    assert apply_learned_rules(v.ledger) == 1
    assert ruling(v, future)['said'] == 'later'


@pytest.mark.parametrize('fence', ['party', 'private', 'direction', 'source_role', 'source_account',
                                  'starts', 'ends', 'excluded', 'anchor', 'weekly', 'monthly', 'yearly'])
def test_unknown_route_keeps_identity_and_temporal_fences(tmp_path, fence):
    v = vault(tmp_path)
    future = movement(v, day='2026-02-13')
    default(v, future)
    rule(v, future, 'lesson')
    body = active_rules(v.ledger)[0]
    assert body['context']['private']
    if fence in body['context']:
        body['context'][fence] = (not body['context'][fence] if fence == 'private'
                                   else 'out' if fence == 'direction' else 'different')
    elif fence == 'starts':
        body['starts'] = '2026-02-15'
    elif fence == 'ends':
        body['ends'] = '2026-02-12'
    elif fence == 'excluded':
        body['excluded'] = [future.key]
    elif fence == 'anchor':
        body['anchor'] = future.key
    else:
        body['recurrence'] = fence
    # Persist the changed fence through the normal rule event.
    v.ledger.append(accounting_rule_recorded(**{k:body[k] for k in
        ('rule_id','anchor','anchor_date','context','legs','category','starts','ends','recurrence','excluded','said','prompt_version')},
        occurred_at='2026-01-04'))
    assert apply_learned_rules(v.ledger) == 0


def test_exclusions_human_precedence_and_later_correction_undo(tmp_path):
    v = vault(tmp_path)
    first = movement(v)
    old = movement(v, day='2026-01-04')
    default(v, old)
    result = lesson(v, first)
    future = movement(v, day='2026-02-03')
    default(v, future)
    exception = movement(v, day='2026-02-04')
    default(v, exception)
    manual = correct_accounting(v, 'This one is an expense.', [exception.key],
        interpret_fn=lambda _:json.dumps({'counterpart_mode':'ordinary',
            'legs':[{'major':'expense','account_hint':'','share':''}], 'future_scope':'one'}))
    assert manual['ok']
    # Corrections also enter normal interpretation for the rest of the vault.
    assert ruling(v, future)['by'] == 'human_rule'
    assert apply_learned_rules(v.ledger) == 0
    assert ruling(v, old) is None and ruling(v, exception)['by'] == 'human'
    later = correct_accounting(v, 'This one is an expense.', [future.key],
        interpret_fn=lambda _:json.dumps({'counterpart_mode':'ordinary',
            'legs':[{'major':'expense','account_hint':'','share':''}], 'future_scope':'one'}))
    assert later['ok']
    assert undo_accounting(v, result['correction_id'])['changed'] == 1
    assert ruling(v, future)['by'] == 'human'
    assert undo_accounting(v, later['correction_id'])['changed'] == 1
    assert ruling(v, future) is None


def test_compatible_application_reload_sql_and_undo_preserve_sources(tmp_path):
    directory = tmp_path / 'synthetic-vault'
    v = Vault.open(directory, 'synthetic')
    v.ledger.append(account_opened(ACCOUNT, 'liability', 'Invented', 'USD', '2026-01-01'))
    first = movement(v)
    result = lesson(v, first)
    future = movement(v, day='2026-02-03')
    default(v, future)
    previous_category = v.ledger.projection().derived_category(future)
    sources = [e for e in v.ledger.events() if e.event_type == 'TransactionRecorded']
    rules = active_rules(v.ledger)
    event_count = len(list(v.ledger.events()))
    v.close()
    v = Vault.open(directory, 'synthetic')
    assert len(list(v.ledger.events())) == event_count and ruling(v, future) is None
    assert active_rules(v.ledger) == rules
    assert apply_learned_rules(v.ledger) == 1
    after = financial_statements(v.ledger.fresh_projection(), end='2026-02-28')
    v.close()
    v = Vault.open(directory, 'synthetic')
    assert ruling(v, future)['by'] == 'human_rule'
    for stage in ('applied', 'undone'):
        expected = after if stage == 'applied' else financial_statements(v.ledger.fresh_projection(), end='2026-02-28')
        assert financial_statements(v.ledger.projection(), end='2026-02-28') == expected
        v.synchronize_read_store()
        with v.read_store.open_reader() as revision:
            assert financial_statements(revision.overview_projection(today='2026-02-28'), end='2026-02-28') == expected
        if stage == 'applied':
            assert undo_accounting(v, result['correction_id'])['changed'] == 2
            assert ruling(v, future) is None
            assert v.ledger.projection().derived_category(future) == previous_category
    assert [e for e in v.ledger.events() if e.event_type == 'TransactionRecorded'] == sources
    assert active_rules(v.ledger) == []
    v.close()


def test_equivalent_component_order_is_not_an_unknown_conflict(tmp_path):
    v = vault(tmp_path)
    future = movement(v, day='2026-02-03')
    default(v, future)
    context = context_key(v.ledger.projection(), future)
    legs = [{'major':'asset','account':MAJOR_UNCATEGORIZED['asset'],'share':''},
            {'major':'expense','account':MAJOR_UNCATEGORIZED['expense'],'share':''}]
    for identity, ordered in [('earlier', legs), ('later', list(reversed(legs)))]:
        v.ledger.append(accounting_rule_recorded(identity, 'invented-anchor', '2026-01-03',
            context, ordered, '2026-01-03', category='debt_settlement', said=identity))
    assert apply_learned_rules(v.ledger) == 1
    assert ruling(v, future)['said'] == 'later'
    assert all(leg['share'] == '' for leg in ruling(v, future)['legs'])


def test_ineligible_conflicting_rule_does_not_block_compatible_lesson(tmp_path):
    v = vault(tmp_path)
    future = movement(v, day='2026-02-03')
    default(v, future)
    rule(v, future, 'eligible')
    rule(v, future, 'expired-conflict', major='expense', ends='2026-02-02')
    assert apply_learned_rules(v.ledger) == 1
    assert ruling(v, future)['said'] == 'eligible'


def test_compatible_recurring_lesson_retains_recorded_history_policy(tmp_path):
    v = vault(tmp_path)
    first = movement(v)
    historical = movement(v, day='2026-01-10')
    default(v, historical)
    result = lesson(v, first, future_scope='recurring', recurrence='weekly',
                    starts='2026-01-03', ends='2026-02-01')
    assert active_rules(v.ledger)[0]['excluded'] == []
    assert apply_learned_rules(v.ledger) == 0
    assert ruling(v, historical)['by'] == 'human_rule'
    assert undo_accounting(v, result['correction_id'])['changed'] == 2


@pytest.mark.parametrize('field', ['category_by', 'subcategory_by'])
@pytest.mark.parametrize('specific', ['human', 'model', '', None])
def test_present_component_attribution_never_inherits_record_wide_default(tmp_path, field, specific):
    v = vault(tmp_path)
    first = movement(v)
    lesson(v, first)
    future = movement(v, day='2026-02-03')
    event = category_assigned(future.key, future.description, 'other', 'unverified',
        future.date, by='default', subcategory='unclassified')
    event.body[field] = specific
    v.ledger.append(event)
    assert apply_learned_rules(v.ledger) == 0
    assert ruling(v, future) is None


def test_effective_canonical_known_label_blocks_default_compatibility(tmp_path):
    from viva.ingest.categorize import rule_category_same_as
    v = vault(tmp_path)
    first = movement(v)
    lesson(v, first)
    future = movement(v, day='2026-02-03')
    default(v, future)
    rule_category_same_as(v.ledger, 'other', 'food')
    assert v.ledger.projection().derived_category(future)['category'] == 'food'
    assert apply_learned_rules(v.ledger) == 0
