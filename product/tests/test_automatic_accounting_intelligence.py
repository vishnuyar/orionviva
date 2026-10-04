"""Automatic meaning never allocates measurements or generalizes a merchant."""
import json
from types import SimpleNamespace

from viva.accounting_intelligence import (active_rules, apply_learned_rules,
    correct_accounting, interpret_activity, undo_accounting)
from viva.ingest import assign_default_categories
from viva.ledger import EventStore, Ledger
from viva.ledger.events import account_opened, transaction_recorded, Posting, Provenance
from viva.ledger.postings import EXPENSE_UNCATEGORIZED
from viva.listen import Interpretation
from viva.engine import record_ruling
from viva.questions import open_questions


def vault(tmp_path):
    ledger = Ledger(EventStore.open(tmp_path / 'events', 'synthetic'))
    ledger.append(account_opened('Assets:Bank:Synthetic', 'depository', 'Synthetic', 'USD', '2026-01-01'))
    return SimpleNamespace(ledger=ledger)


def movement(v, description='SYNTHETIC SHOP', amount='-15', day='2026-01-03', account='Assets:Bank:Synthetic', doc='doc'):
    v.ledger.append(transaction_recorded(
        [Posting(account, amount, grade="verified"), Posting(EXPENSE_UNCATEGORIZED, str(-__import__('decimal').Decimal(amount)))], description, day,
        provenance=Provenance(doc_id=doc)))
    return v.ledger.projection().movements()[-1]


def test_defaults_do_not_require_review(tmp_path):
    v = vault(tmp_path)
    m = movement(v, 'PAYMENT TO SYNTHETIC PERSON')
    assign_default_categories(v.ledger, 'doc')
    assert v.ledger.projection().derived_category(m)['category'] == 'other'
    assert open_questions(v.ledger)['total'] == 0
    assert v.ledger.projection().movements()[0].provisional


def test_model_envelope_has_no_private_money_or_descriptors(tmp_path):
    v = vault(tmp_path)
    movement(v, 'PRIVATE SENTINEL DESCRIPTION', '-731.29')
    prompts = []
    def model(prompt):
        prompts.append(prompt)
        return json.dumps({'interpretations':[{'ref':'m0','majors':['expense'],'grounds':'ordinary payment'}]})
    result = interpret_activity(v, extract_fn=model)
    assert result['status'] == 'completed'
    assert len(prompts) == 1
    assert 'PRIVATE SENTINEL' not in prompts[0] and '731.29' not in prompts[0]
    assert 'Assets:Bank:Synthetic' not in prompts[0]
    assert v.ledger.projection().movements()[0].provisional
    assert v.ledger.fresh_projection().rulings('movement') == v.ledger.projection().rulings('movement')


def test_bad_output_preserves_postings(tmp_path):
    v = vault(tmp_path)
    movement(v)
    before = v.ledger.projection().movements()[0].amount
    result = interpret_activity(v, extract_fn=lambda p: json.dumps({'interpretations':[
        {'ref':'m0','majors':['asset'],'grounds':'claim','amount':'9000'}]}))
    assert result['status'] == 'failed'
    assert not v.ledger.projection().rulings('movement')
    assert v.ledger.projection().movements()[0].amount == before


def test_correction_immediate_scoped_future_and_one_off_undo(tmp_path):
    v = vault(tmp_path)
    m = movement(v)
    result = record_ruling(v, Interpretation(legs=[{'major':'asset','account_hint':'Workshop equipment'}],
        said='These recurring payments buy my equipment', future_scope='recurring'),
        m.description, movement_key=m.key, currency='USD')
    assert result['ok'] and not result['confirm'] and result['rule_id']
    next_m = movement(v, day='2026-02-03', doc='next')
    assert apply_learned_rules(v.ledger) == 1
    expense = Interpretation(legs=[{'major':'expense','account_hint':''}], said='This one was a repair', future_scope='one')
    exception = record_ruling(v, expense, next_m.description, movement_key=next_m.key)
    assert len(active_rules(v.ledger)) == 1
    assert undo_accounting(v, exception['correction_id'])['ok']
    assert v.ledger.projection().rulings('movement')[-1]['legs'][0]['major'] == 'asset'
    assert undo_accounting(v, result['correction_id'])['ok']
    assert not active_rules(v.ledger)
    assert not v.ledger.projection().rulings('movement')


def test_opposite_direction_does_not_learn_rule(tmp_path):
    v = vault(tmp_path)
    m = movement(v)
    record_ruling(v, Interpretation(legs=[{'major':'asset','account_hint':'Equipment'}],said='Equipment',future_scope='recurring'),m.description,movement_key=m.key)
    movement(v, amount='15', day='2026-02-03')
    assert apply_learned_rules(v.ledger) == 0


def test_selected_conversation_no_confirmation(tmp_path):
    v = vault(tmp_path)
    m = movement(v)
    result = correct_accounting(v, 'This one was my equipment', [m.key], interpret_fn=lambda p: json.dumps({
        'legs':[{'major':'asset','account_hint':'equipment'}], 'future_scope':'one'}))
    assert result['ok'] and not result['confirm']
    assert result['correction_id']


def test_conversation_cannot_invent_loan_allocation(tmp_path):
    v = vault(tmp_path)
    m = movement(v)
    result = correct_accounting(v, 'This was a loan payment', [m.key],
        interpret_fn=lambda p: json.dumps({'legs':[
            {'major':'liability', 'account_hint':'Loan', 'share':'80%'},
            {'major':'expense', 'share':'20%'}], 'future_scope':'one'}))
    assert result['ok']
    ruling = v.ledger.projection().rulings('movement')[0]
    assert all(not leg['share'] for leg in ruling['legs'])
    from viva.ledger.networth import recorded_shares
    assert recorded_shares(ruling) is None


def test_conversation_honors_explicit_percentages(tmp_path):
    v = vault(tmp_path)
    m = movement(v)
    result = correct_accounting(v, 'This loan payment was 80% principal and 20% interest',
        [m.key], interpret_fn=lambda p: json.dumps({'legs':[
            {'major':'liability', 'account_hint':'Loan', 'share':'80%'},
            {'major':'expense', 'share':'20%'}], 'future_scope':'one'}))
    assert result['ok']
    ruling = v.ledger.projection().rulings('movement')[0]
    assert [leg['share'] for leg in ruling['legs']] == ['0.8', '0.2']


def test_conversation_honors_explicit_whole_percentage(tmp_path):
    v = vault(tmp_path)
    m = movement(v)
    result = correct_accounting(v, 'This was 100% principal for my loan', [m.key],
        interpret_fn=lambda p: json.dumps({'legs':[
            {'major':'liability', 'account_hint':'Loan', 'share':'100%'}],
            'future_scope':'one'}))
    assert result['ok']
    assert v.ledger.projection().rulings('movement')[0]['legs'][0]['share'] == '1'


def test_conversation_cannot_repeat_one_stated_percentage_or_use_money(tmp_path):
    v = vault(tmp_path)
    m = movement(v)
    for said in ('50% of this payment was principal',
                 'This payment had $50 principal and $50 interest'):
        result = correct_accounting(v, said, [m.key],
            interpret_fn=lambda p: json.dumps({'legs':[
                {'major':'liability', 'account_hint':'Loan', 'share':'50%'},
                {'major':'expense', 'share':'50%'}], 'future_scope':'one'}))
        assert result['ok']
        assert all(not leg['share'] for leg in
                   v.ledger.projection().rulings('movement')[0]['legs'])


def test_learning_remembers_loan_relationship_without_reusing_allocation(tmp_path):
    v = vault(tmp_path)
    m = movement(v)
    result = correct_accounting(v, 'These recurring loan payments: this one was 80% principal and 20% interest',
        [m.key], interpret_fn=lambda p: json.dumps({'legs':[
            {'major':'liability', 'account_hint':'Loan', 'share':'80%'},
            {'major':'expense', 'share':'20%'}], 'future_scope':'recurring'}))
    assert result['ok']
    assert [leg['share'] for leg in active_rules(v.ledger)[0]['legs']] == ['', '']
    future = movement(v, day='2026-02-03', doc='next')
    assert apply_learned_rules(v.ledger) == 1
    rulings = {r['subject']:r for r in v.ledger.projection().rulings('movement')}
    assert [leg['share'] for leg in rulings[m.key]['legs']] == ['0.8', '0.2']
    assert [leg['share'] for leg in rulings[future.key]['legs']] == ['', '']
    assert undo_accounting(v, result['correction_id'])['changed'] == 2
    assert not v.ledger.projection().rulings('movement')


def test_allocation_tokens_cannot_be_signed_or_punctuation_tails(tmp_path):
    v = vault(tmp_path)
    m = movement(v)
    for token in ('-5%', '- 5%', '-\n5%', '−5%', '− 5%', '- +5%',
                  '80,5%', '80, 5%', '4/5%', '4 / 5%', '4*5%', '4 * 5%'):
        result = correct_accounting(v, f'95% principal and {token} interest', [m.key],
            interpret_fn=lambda p: json.dumps({'legs':[
                {'major':'liability', 'account_hint':'Loan', 'share':'95%'},
                {'major':'expense', 'share':'5%'}], 'future_scope':'one'}))
        assert result['ok']
        assert all(not leg['share'] for leg in
                   v.ledger.projection().rulings('movement')[0]['legs']), token


def test_undo_preserves_identical_later_independent_correction(tmp_path):
    v = vault(tmp_path)
    m = movement(v)
    def correct():
        return record_ruling(v, Interpretation(legs=[{'major':'asset','account_hint':'Workshop'}],
            said='Equipment', future_scope='one'), m.description, movement_key=m.key)
    first, second = correct(), correct()
    assert undo_accounting(v, first['correction_id'])['changed'] == 0
    assert v.ledger.projection().rulings('movement')[0]['legs'][0]['major'] == 'asset'
    assert undo_accounting(v, second['correction_id'])['changed'] == 1
    assert not v.ledger.projection().rulings('movement')


def test_undo_never_resurrects_already_undone_predecessor(tmp_path):
    v = vault(tmp_path)
    m = movement(v)
    first = record_ruling(v, Interpretation(legs=[{'major':'asset','account_hint':'Workshop'}],
        said='Equipment', future_scope='one'), m.description, movement_key=m.key)
    second = record_ruling(v, Interpretation(legs=[{'major':'expense','account_hint':''}],
        said='Supplies', future_scope='one'), m.description, movement_key=m.key)
    assert undo_accounting(v, first['correction_id'])['changed'] == 0
    assert v.ledger.projection().rulings('movement')[0]['said'] == 'Supplies'
    assert undo_accounting(v, second['correction_id'])['changed'] == 1
    assert not v.ledger.projection().rulings('movement')
    assert v.ledger.fresh_projection().rulings('movement') == []


def test_purpose_context_prevents_same_merchant_overgeneralization(tmp_path):
    from viva.ingest import assign_category
    v = vault(tmp_path)
    first = movement(v)
    assign_category(v.ledger, first.key, 'equipment', subcategory='tools', by='model')
    record_ruling(v, Interpretation(legs=[{'major':'asset','account_hint':'Workshop'}],
        said='These payments acquire workshop equipment', future_scope='recurring'),
        first.description, movement_key=first.key)
    second = movement(v, day='2026-02-03')
    assign_category(v.ledger, second.key, 'food', subcategory='supplies', by='model')
    assert apply_learned_rules(v.ledger) == 0
    assert len(v.ledger.projection().rulings('movement')) == 1


def test_undo_restores_original_category_and_inference_provenance(tmp_path):
    from viva.ingest import assign_category
    v = vault(tmp_path)
    first = movement(v)
    assign_category(v.ledger, first.key, 'other', subcategory='unclassified', by='default')
    interpret_activity(v, extract_fn=lambda p: json.dumps({'interpretations':[
        {'ref':'m0','majors':['expense'],'grounds':'fallback'}]}))
    before = v.ledger.projection().rulings('movement')
    original_category = v.ledger.projection().derived_category(first)
    result = record_ruling(v, Interpretation(legs=[{'major':'asset','account_hint':'Workshop'}],
        category='equipment', said='This one was equipment', future_scope='one'),
        first.description, movement_key=first.key)
    undo_accounting(v, result['correction_id'])
    assert v.ledger.projection().rulings('movement') == before
    assert v.ledger.projection().derived_category(first) == original_category
    assert v.ledger.fresh_projection().rulings('movement') == before


def test_source_named_components_are_never_overwritten_by_automatic_reasoning(tmp_path):
    v = vault(tmp_path)
    v.ledger.append(transaction_recorded([Posting('Assets:Bank:Synthetic', '25', grade='verified'),
        Posting('Income:Salary', '-25', grade='verified')], 'SYNTHETIC PAY', '2026-01-04'))
    prompts = []
    result = interpret_activity(v, extract_fn=lambda p: prompts.append(p))
    assert not prompts and result['status'] == 'local_evidence'
    assert not v.ledger.projection().rulings('movement')


def test_compound_prior_remains_unresolved_without_invented_split(tmp_path):
    from viva.ledger.events import merchant_enriched
    v = vault(tmp_path)
    first = movement(v)
    v.ledger.append(merchant_enriched(v.ledger.projection().merchant_key_of(first), 'housing',
        attributes={'counterparty_kind':'business','implies':[
            {'major':'liability','on':'outflow','compound':True,'confidence':'suggested'}]},
        occurred_at='2026-01-04'))
    result = interpret_activity(v, extract_fn=lambda p: None)
    ruling = v.ledger.projection().rulings('movement')[0]
    assert result['applied'] == 1
    assert {r['major'] for r in ruling['legs']} == {'liability','expense'}
    assert all(not r['share'] for r in ruling['legs'])
    assert v.ledger.projection().movements()[0].nature == 'mixed'


def test_human_correction_wins_later_model_run(tmp_path):
    v = vault(tmp_path)
    first = movement(v)
    record_ruling(v, Interpretation(legs=[{'major':'asset','account_hint':'Workshop'}],
        said='Workshop equipment',future_scope='one'),first.description,movement_key=first.key)
    before = v.ledger.projection().rulings('movement')
    result = interpret_activity(v, extract_fn=lambda p: None)
    assert result['status'] == 'local_evidence'
    assert v.ledger.projection().rulings('movement') == before


def test_later_compound_evidence_replaces_generic_model_inference(tmp_path):
    from viva.ledger.events import merchant_enriched
    v = vault(tmp_path)
    first = movement(v)
    calls = []
    def model(prompt):
        calls.append(prompt)
        return json.dumps({'interpretations':[{'ref':'m0','majors':['expense'],'grounds':'Ordinary fallback.'}]})
    interpret_activity(v, extract_fn=model)
    interpret_activity(v, extract_fn=model)
    assert len(calls) == 1
    v.ledger.append(merchant_enriched(v.ledger.projection().merchant_key_of(first),'housing',
        occurred_at='2026-01-05', attributes={'implies':[
            {'major':'liability','on':'outflow','compound':True,'confidence':'suggested'}]}))
    interpret_activity(v, extract_fn=model)
    ruling = v.ledger.projection().rulings('movement')[0]
    assert ruling['by'] == 'merchant_prior'
    assert {leg['major'] for leg in ruling['legs']} == {'liability','expense'}
    assert v.ledger.projection().movements()[0].nature == 'mixed'
    assert len(calls) == 1


def test_raw_claim_precedes_applied_ruling_and_retains_grounds(tmp_path):
    v = vault(tmp_path)
    movement(v)
    interpret_activity(v, extract_fn=lambda p: json.dumps({'interpretations':[
        {'ref':'m0','majors':['expense'],'grounds':'Categorical ordinary spending inference.'}]}))
    events = list(v.ledger.store.snapshot_events())
    ruling = next(e for e in events if e.event_type == 'RulingRecorded')
    claim = next(e for e in events if e.event_type == 'ReadRecorded' and e.body['phase'] == 'accounting')
    assert events.index(claim) < events.index(ruling)
    assert ruling.body['grounds'] == 'Categorical ordinary spending inference.'
    assert claim.body['doc_id'] in ruling.body['source_refs']
    assert ruling.provenance.doc_id == claim.body['doc_id']


def test_one_off_correction_supplies_sanitized_example_without_blanket_rule(tmp_path):
    v = vault(tmp_path)
    first = movement(v, description='PRIVATE EXAMPLE SENTINEL')
    result = record_ruling(v, Interpretation(legs=[{'major':'asset','account_hint':'Workshop'}],
        said='Private explanation sentinel. This one was my equipment', future_scope='one'),
        first.description, movement_key=first.key)
    assert not result['rule_id'] and not active_rules(v.ledger)
    second = movement(v, description='PRIVATE EXAMPLE SENTINEL', day='2026-02-03')
    assert apply_learned_rules(v.ledger) == 0
    prompts = []
    def model(prompt):
        prompts.append(prompt)
        return json.dumps({'interpretations':[{'ref':'m0','majors':['expense'],'grounds':'ordinary later payment'}]})
    interpret_activity(v, extract_fn=model)
    assert '"correction_examples": [{"majors": ["asset"], "scope": "one_off"}]' in prompts[0]
    assert 'PRIVATE EXAMPLE SENTINEL' not in prompts[0]
    assert 'Private explanation sentinel' not in prompts[0]
    assert 'Workshop' not in prompts[0]
    later_ruling = next(r for r in v.ledger.projection().rulings('movement') if r['subject'] == second.key)
    assert later_ruling['by'] == 'model' and later_ruling['legs'][0]['major'] == 'expense'
    undo_accounting(v, result['correction_id'])
    from viva.accounting_intelligence import correction_examples
    assert not correction_examples(v.ledger, v.ledger.projection(), second)


def test_automatic_envelope_omits_private_custom_categories_with_numbers(tmp_path):
    from viva.ingest import assign_category
    v = vault(tmp_path)
    first = movement(v)
    assign_category(v.ledger, first.key, 'Synthetic personal account 731.29',
                    subcategory='Account 123456789', by='human')
    prompts = []
    def model(prompt):
        prompts.append(prompt)
        return json.dumps({'interpretations':[{'ref':'m0','majors':['expense'],'grounds':'ordinary'}]})
    interpret_activity(v, extract_fn=model)
    assert len(prompts) == 1
    assert '731.29' not in prompts[0] and '123456789' not in prompts[0]
    assert 'Synthetic personal account' not in prompts[0]
    assert '"category": "other"' in prompts[0]


def test_invalid_future_rule_is_rejected_before_account_or_treatment_write(tmp_path):
    v = vault(tmp_path)
    first = movement(v)
    before = list(v.ledger.events())
    result = record_ruling(v, Interpretation(legs=[{'major':'asset','account_hint':'Workshop'}],
        said='Workshop equipment', future_scope='recurring', recurrence='invalid'),
        first.description, movement_key=first.key)
    assert result['ok'] is False and result['why'] == 'invalid_scope'
    assert list(v.ledger.events()) == before


def test_undo_marks_only_orphan_correction_created_account_inactive(tmp_path):
    v = vault(tmp_path)
    first = movement(v)
    result = record_ruling(v, Interpretation(legs=[{'major':'asset','account_hint':'Workshop'}],
        said='This was equipment', future_scope='one'), first.description, movement_key=first.key)
    account = 'Assets:Other:Workshop'
    assert v.ledger.projection().inactive_accounting_accounts() == set()
    undo_accounting(v, result['correction_id'])
    assert account in v.ledger.projection().accounts(), 'append-only source history remains available'
    assert v.ledger.projection().inactive_accounting_accounts() == {account}
    assert v.ledger.fresh_projection().inactive_accounting_accounts() == {account}


def test_undo_preserves_correction_account_reused_by_another_active_correction(tmp_path):
    v = vault(tmp_path)
    first = movement(v)
    second = movement(v, day='2026-02-03')
    interp = Interpretation(legs=[{'major':'asset','account_hint':'Workshop'}],
        said='Workshop equipment', future_scope='one')
    creating = record_ruling(v, interp, first.description, movement_key=first.key)
    reusing = record_ruling(v, interp, second.description, movement_key=second.key)
    undo_accounting(v, creating['correction_id'])
    assert not v.ledger.projection().inactive_accounting_accounts()
    assert v.ledger.projection().seen_account('Assets:Other:Workshop')
    assert reusing['ok']


def test_undo_preserves_independently_described_correction_account(tmp_path):
    from viva.ledger.events import ruling_recorded
    v = vault(tmp_path)
    first = movement(v)
    result = record_ruling(v, Interpretation(legs=[{'major':'asset','account_hint':'Workshop'}],
        said='Workshop equipment', future_scope='one'),first.description,movement_key=first.key)
    account = 'Assets:Other:Workshop'
    v.ledger.append(ruling_recorded('attribute', account + ':nickname', '2026-10-04',
                                   value='Tools', said='Tools'))
    undo_accounting(v, result['correction_id'])
    assert not v.ledger.projection().inactive_accounting_accounts()


def test_undo_restores_fixed_date_balance_sheet_without_ghost_account(tmp_path, monkeypatch):
    from viva import engine, accounting_intelligence
    monkeypatch.setattr(engine, "_today", lambda: "2026-01-15")
    monkeypatch.setattr(accounting_intelligence, "_today", lambda: "2026-01-15")
    from viva.ledger.accounting import financial_statements
    v = vault(tmp_path)
    first = movement(v)
    before = financial_statements(v.ledger.projection(), as_of='2026-01-31')['balance_sheet']
    result = record_ruling(v, Interpretation(legs=[{'major':'asset','account_hint':'Workshop'}],
        said='Workshop equipment', future_scope='one'),first.description,movement_key=first.key)
    undo_accounting(v, result['correction_id'])
    after = financial_statements(v.ledger.projection(), as_of='2026-01-31')['balance_sheet']
    assert after == before


def test_undo_preserves_independently_reopened_asserted_account(tmp_path):
    v = vault(tmp_path)
    first = movement(v)
    result = record_ruling(v, Interpretation(legs=[{'major':'asset','account_hint':'Workshop'}],
        said='Workshop equipment',future_scope='one'),first.description,movement_key=first.key)
    account = 'Assets:Other:Workshop'
    v.ledger.append(account_opened(account,'asset','Workshop','USD','2026-01-20', origin='asserted'))
    undo_accounting(v, result['correction_id'])
    assert not v.ledger.projection().inactive_accounting_accounts()


def test_undo_never_suppresses_existing_independent_asserted_account(tmp_path):
    v = vault(tmp_path)
    account = 'Assets:Other:Workshop'
    v.ledger.append(account_opened(account,'asset','Workshop','USD','2026-01-01', origin='asserted'))
    first = movement(v)
    result = record_ruling(v, Interpretation(legs=[{'major':'asset','account_hint':'Workshop'}],
        said='Workshop equipment',future_scope='one'),first.description,movement_key=first.key)
    undo_accounting(v, result['correction_id'])
    assert not v.ledger.projection().inactive_accounting_accounts()
