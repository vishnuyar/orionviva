"""Repeated account evidence cannot silently replace valid bank provenance."""
from copy import deepcopy
from dataclasses import dataclass, replace
from decimal import Decimal

import pytest

from test_source_projector import contribution_facts
from viva.ingest.brokerage_projector import post_brokerage
from viva.ingest.instrument_contracts import Source
from viva.investment.authority import read
from viva.investment.contracts import Field, Request
from viva.investment.events import committed_statements, source_index
from viva.investment.funding import bind_funding, resolver
from viva.investment.healing import heal_after_source
from viva.ledger import Ledger
from viva.ledger.events import Provenance, account_opened
from viva.ledger.instruments import reference_event
from viva.ledger.postings import simple_transaction


def prepared(tmp_path):
    ledger = Ledger.open(tmp_path / 'events.jsonl', 'synthetic-only')
    result = post_brokerage(ledger, contribution_facts())
    ledger.append(account_opened('Assets:BankTest', 'depository', 'Test bank', 'USD', '2025-01-01'))
    ledger.append(reference_event('Assets:BankTest', 'BANK-REF', '2025-01-01', Source('bank-source', 1)))
    ledger.append(simple_transaction('Assets:BankTest', '-100.00', 'Bank funding', '2025-01-25',
        provenance=Provenance(doc_id='bank-source', page=1), source_reference='PRINTED-X',
        counterparty_reference='BROKER-REF'))
    assert heal_after_source(ledger, 'bank-source') == 1
    events = tuple(ledger.events())
    statement = source_index(events, resolver(events)).project('activity', '9999-12-31', resolver(events))[0].statement
    row = statement.rows[0]
    return ledger, statement, row, Request('activity_totals', result.account, 'USD',
        start='2025-01-01', end='2025-01-31', grouping='none')


def bind(events, statement, row, preferred):
    fields = {'printed_reference': row.funding_reference, 'counterpart_reference': row.counterpart_reference,
              'date': row.date, 'amount': row.amount, 'funding_role': row.funding_role_source}
    return bind_funding(fields, events, destination_account=statement.account.value,
        destination_reference=replace(statement.account, value=statement.account.raw),
        currency=statement.currency.value, preferred_witness=preferred)


def repeated(ledger, *, document='later-reference', page=2):
    ledger.append(reference_event('Assets:BankTest', 'BANK-REF', '2025-02-01', Source(document, page)))
    return tuple(ledger.events())


def test_repeated_equivalent_references_retain_identity_exact_witness_and_financial_answer(tmp_path):
    ledger, statement, row, request = prepared(tmp_path)
    original = tuple(ledger.events())
    answer = read(committed_statements(original, resolver(original)), request)
    cash = deepcopy(tuple(event for event in original if event.event_type == 'TransactionRecorded'))
    for document, page in [('later-reference', 2), ('newer-reference', 3), ('bank-source', 1)]:
        events = repeated(ledger, document=document, page=page)
        before = len(events)
        assert heal_after_source(ledger, document) == 0
        current = tuple(ledger.events())
        assert len(current) == before
        selected = source_index(current, resolver(current)).project('activity', '9999-12-31', resolver(current))[0].statement
        assert selected.observation_id == statement.observation_id
        assert selected.rows[0].funding_witness == row.funding_witness
        assert tuple(event for event in current if event.event_type == 'TransactionRecorded') == cash
        assert read(committed_statements(current, resolver(current)), request) == answer
    reopened = Ledger.open(tmp_path / 'events.jsonl', 'synthetic-only')
    assert heal_after_source(reopened, 'newer-reference') == 0


@pytest.mark.parametrize('attribute,value', [
    ('document', 'forged-document'), ('page', 2), ('raw', 'forged-raw'),
    ('anchor', 'forged-anchor'), ('grade', 'verified'), ('status', 'unavailable'),
    ('value', 'OTHER-REFERENCE'),
])
def test_unsupported_counterpart_field_uses_existing_latest_fallback(tmp_path, attribute, value):
    ledger, statement, row, _ = prepared(tmp_path)
    events = repeated(ledger)
    preferred = replace(row.funding_witness, counterpart_reference=replace(
        row.funding_witness.counterpart_reference, **{attribute: value}))
    actual = bind(events, statement, row, preferred)['funding_witness']
    assert actual == bind(events, statement, row, None)['funding_witness']
    assert actual.counterpart_reference.document == 'later-reference'


@pytest.mark.parametrize('attribute,value', [
    ('role', 'external_party'), ('counterpart_account', 'Assets:OtherBank'),
    ('transaction_id', 'other-cash'), ('transaction_digest', '0' * 64),
    ('source_row_event_id', 'forged-row'),
])
def test_changed_economic_or_source_identity_cannot_preserve_preference(tmp_path, attribute, value):
    ledger, statement, row, _ = prepared(tmp_path)
    events = repeated(ledger)
    preferred = replace(row.funding_witness, **{attribute: value})
    assert bind(events, statement, row, preferred) == bind(events, statement, row, None)


def test_changed_printed_reference_lineage_or_missing_historical_support_uses_fallback(tmp_path):
    ledger, statement, row, _ = prepared(tmp_path)
    events = repeated(ledger)
    forged = replace(row.funding_witness, reference=replace(row.funding_witness.reference, page=2))
    assert bind(events, statement, row, forged) == bind(events, statement, row, None)
    missing = tuple(event for event in events if not (
        event.event_type == 'FinancialAccountReferenceObserved' and event.provenance.doc_id == 'bank-source'))
    assert bind(missing, statement, row, row.funding_witness) == bind(missing, statement, row, None)


@pytest.mark.parametrize('ambiguity', ['account', 'cash'])
def test_preferred_witness_never_masks_new_current_ambiguity(tmp_path, ambiguity):
    ledger, statement, row, _ = prepared(tmp_path)
    repeated(ledger)
    if ambiguity == 'account':
        ledger.append(account_opened('Assets:OtherBank', 'depository', 'Other bank', 'USD', '2025-01-01'))
        ledger.append(reference_event('Assets:OtherBank', 'BANK-REF', '2025-02-01', Source('conflicting-reference', 1)))
    else:
        events = tuple(ledger.events())
        cash = next(event for event in events if event.event_id == row.funding_witness.transaction_id)
        ledger.append(replace(cash, event_id='second-matching-cash'))
    assert bind(tuple(ledger.events()), statement, row, row.funding_witness) == {}


@pytest.mark.parametrize('change', ['missing-cash', 'amount', 'date', 'account-kind'])
def test_preference_does_not_bypass_changed_current_dependencies(tmp_path, change):
    ledger, statement, row, _ = prepared(tmp_path)
    events = repeated(ledger)
    cash_id = row.funding_witness.transaction_id
    if change == 'missing-cash':
        changed = tuple(event for event in events if event.event_id != cash_id)
    elif change == 'amount':
        changed = tuple(replace(event, body={**event.body, 'postings': [
            {**posting, 'amount': str(2 * Decimal(posting['amount']))}
            for posting in event.body['postings']]}) if event.event_id == cash_id else event
            for event in events)
    elif change == 'date':
        changed = tuple(replace(event, occurred_at='2025-01-26') if event.event_id == cash_id else event
                        for event in events)
    else:
        changed = tuple(replace(event, body={**event.body, 'kind': 'investment'})
                        if event.event_type == 'AccountOpened' and event.body['account_id'] == 'Assets:BankTest'
                        else event for event in events)
    assert bind(changed, statement, row, row.funding_witness) == {}


def test_only_account_scoped_retained_field_support_can_preserve_preference(tmp_path):
    ledger, statement, row, _ = prepared(tmp_path)
    events = repeated(ledger)
    changed = tuple(replace(event, body={**event.body, 'scope': 'institution'})
                    if event.event_type == 'FinancialAccountReferenceObserved'
                    and event.provenance.doc_id == 'bank-source' else event for event in events)
    actual = bind(changed, statement, row, row.funding_witness)
    assert actual == bind(changed, statement, row, None)
    assert actual['funding_witness'].counterpart_reference.document == 'later-reference'


@pytest.mark.parametrize('field_name', ['reference', 'counterpart_reference'])
@pytest.mark.parametrize('variant', ['object', 'subclass'])
def test_non_field_or_subclass_equality_cannot_forge_exact_source_support(tmp_path, field_name, variant):
    ledger, statement, row, _ = prepared(tmp_path)
    events = repeated(ledger)
    class EqualAnything:
        def __eq__(self, other):
            return True
    class LyingField(Field):
        def __eq__(self, other):
            return True
    field = getattr(row.funding_witness, field_name)
    forged = EqualAnything() if variant == 'object' else LyingField(**vars(field))
    preferred = replace(row.funding_witness, **{field_name: forged})
    actual = bind(events, statement, row, preferred)['funding_witness']
    assert type(actual.reference) is Field and type(actual.counterpart_reference) is Field
    assert actual.counterpart_reference.document == 'later-reference'


@pytest.mark.parametrize('location', ['role', 'reference-grade', 'counterpart-grade', 'counterpart-status'])
def test_unsupported_nested_equality_objects_cannot_forge_encoded_proof(tmp_path, location):
    ledger, statement, row, _ = prepared(tmp_path)
    events = repeated(ledger)
    class EqualAnything:
        def __eq__(self, other):
            return other != 'conflicted'
    forged = EqualAnything()
    if location == 'role':
        preferred = replace(row.funding_witness, role=forged)
    else:
        field_name = 'reference' if location.startswith('reference') else 'counterpart_reference'
        attribute = 'status' if location.endswith('status') else 'grade'
        preferred = replace(row.funding_witness, **{field_name: replace(
            getattr(row.funding_witness, field_name), **{attribute: forged})})
    actual = bind(events, statement, row, preferred)['funding_witness']
    assert actual.role == 'own_bank'
    assert type(actual.role) is str
    assert type(actual.counterpart_reference.grade) is str
    assert actual.counterpart_reference.document == 'later-reference'


@pytest.mark.parametrize('variant', ['mixed-keys', 'cycle'])
def test_preference_serialization_failure_uses_existing_fallback(tmp_path, variant):
    ledger, statement, row, _ = prepared(tmp_path)
    events = repeated(ledger)
    @dataclass
    class UnsupportedRole:
        payload: object
        def __eq__(self, other):
            return other == 'own_bank'
    role = UnsupportedRole({1: 'a', 'b': 'c'})
    if variant == 'cycle':
        role.payload = role
    preferred = replace(row.funding_witness, role=role)
    actual = bind(events, statement, row, preferred)['funding_witness']
    assert type(actual.role) is str and actual.role == 'own_bank'
    assert actual.counterpart_reference.document == 'later-reference'
