"""Canonical ruling input stays unchanged while its projected view keeps history."""
import copy
import json
import threading
from types import SimpleNamespace

import pytest

from viva.ledger.events import (Event, Provenance, VERIFIED, UNVERIFIED,
    account_opened, ruling_recorded)
from viva.ledger.projection import LedgerProjection
from viva.ledger.projection.accounts import own_account_tokens
from viva.ledger.postings import paystub_decomposition, simple_transaction
from viva.investment.events import prefix
from viva.investment.contracts import EvidenceError, encode
from viva.investment.payroll import append_source, _records
from viva.ingest.paystub import from_paystub_json
from viva.interview import attributes

WHEN = '2021-01-25'
MISSING = object()


def wire(value):
    return json.loads(json.dumps(value))


def replay(rows):
    return tuple(Event.from_dict(wire(row)) for row in rows)


@pytest.mark.parametrize('body_date', [
    pytest.param(MISSING,id='missing'), pytest.param(None,id='none'),
    pytest.param('',id='empty'), pytest.param('2020-12-31',id='present')])
def test_projection_preserves_ruling_bytes_prefix_and_owned_view(body_date):
    event = ruling_recorded('account','public-checking',WHEN,said='original')
    if body_date is not MISSING:
        event.body['occurred_at'] = body_date
    original = wire(event.to_dict())
    proof = prefix((event,))
    for _ in range(2):
        projected = LedgerProjection((event,))
        view = projected.core._rulings[('account','public-checking')]
        expected = WHEN if body_date is MISSING else body_date
        assert view.get('occurred_at',MISSING) == expected
        assert view is not event.body
        assert event.to_dict() == original
        assert prefix((event,)) == proof


@pytest.mark.parametrize('first_grade,later_grade,expected', [
    pytest.param(VERIFIED,UNVERIFIED,'first',id='verified-beats-guess'),
    pytest.param(VERIFIED,VERIFIED,'later',id='later-verified'),
    pytest.param(UNVERIFIED,UNVERIFIED,'later',id='later-unverified'),
    pytest.param(UNVERIFIED,VERIFIED,'later',id='verified-upgrade')])
def test_existing_verified_precedence_is_preserved(first_grade,later_grade,expected):
    events = [ruling_recorded('account','public-checking',WHEN,grade=first_grade,said='first'),
              ruling_recorded('account','public-checking','2021-02-25',grade=later_grade,said='later')]
    original = wire([e.to_dict() for e in events])
    projection = LedgerProjection(events)
    assert projection.core._rulings[('account','public-checking')]['said'] == expected
    assert [e.to_dict() for e in events] == original


def test_attribute_history_and_dated_answers_keep_losing_rulings_in_order():
    events = [ruling_recorded('attribute','public-asset:worth',date,value=value,
        said='value '+value,currency='USD',grade=grade)
        for date,value,grade in [('2021-01-01','100',VERIFIED),
                                 ('2021-02-01','200',UNVERIFIED),
                                 ('2021-03-01','300',VERIFIED)]]
    projection = LedgerProjection(events[:2])
    assert projection.core._rulings[('attribute','public-asset:worth')]['value'] == '100'
    projection.apply(events[2])
    assert [r['value'] for r in projection._attribute_history] == ['100','200','300']
    assert attributes(projection,'public-asset','2020-12-31') == {}
    for date,value,grade in [('2021-01-31','100',VERIFIED),
                             ('2021-02-28','200',UNVERIFIED),
                             ('2021-03-31','300',VERIFIED)]:
        held = attributes(projection,'public-asset',date)['public-asset']['worth']
        assert (held['value'],held['grade']) == (value,grade)
    assert all('occurred_at' not in e.body for e in events)


def test_account_cache_is_invalidated_even_for_a_precedence_losing_guess():
    projection = LedgerProjection([account_opened('public-checking','depository','Public checking','USD',WHEN),
        ruling_recorded('account','public-checking',WHEN,grade=VERIFIED,said='first')])
    own_account_tokens(projection.core)
    assert projection.core._own_tokens_cache is not None
    projection.apply(ruling_recorded('account','public-checking','2021-02-25',grade=UNVERIFIED,said='later'))
    assert projection.core._rulings[('account','public-checking')]['said'] == 'first'
    assert projection.core._own_tokens_cache is None


@pytest.mark.parametrize('scope',['category','tag'])
def test_alias_updates_stay_outside_precedence_replacement(scope):
    events = [ruling_recorded(scope,'public:old',WHEN,same_as='public:first',grade=VERIFIED),
              ruling_recorded(scope,'public:old','2021-02-25',same_as='public:later',grade=UNVERIFIED)]
    projection = LedgerProjection(events)
    assert projection.core._rulings[(scope,'public:old')]['same_as'] == 'public:first'
    aliases = projection.core._category_alias_map if scope=='category' else projection.core._tag_alias_map
    assert aliases['public:old'] == 'public:later'
    if scope=='category':
        assert projection.core._subcategory_alias_map['public:old'] == 'public:later'


def payroll_facts():
    sf = lambda value:{'raw':value,'page':1}
    data = {'employer':'Public employer','pay_date_raw':WHEN,'period_start_raw':'2021-01-01',
        'period_end_raw':'2021-01-31','gross_raw':'100.00','net_raw':'80.00','gross_page':1,'net_page':1,
        'deductions':[{'label':'Public tax','amount_raw':'20.00','category':'tax'}],
        'payroll_source':{'schema':'payroll-source-v1','headers':{'source_reference':sf('PUBLIC-PAYROLL'),
            'currency':sf('USD'),'pay_date':sf(WHEN),'gross':sf('100.00'),'net':sf('80.00')},
            'deductions':[{'label':sf('Public tax'),'category':sf('tax'),'amount':sf('20.00'),
                'destination_reference':None,'contribution_reference':None}]}}
    facts,error = from_paystub_json(json.dumps(data),'public-payroll-doc','en-US','USD')
    assert error is None
    return facts


class MemoryStore:
    """Only new additions are serialized; existing committed wire is unchanged."""
    def __init__(self,rows):self.rows=wire(rows)
    def append_atomically(self,decide):
        additions=tuple(decide(replay(self.rows)))
        self.rows.extend(wire(event.to_dict()) for event in additions)
        return additions
    def _cached_identity(self):return ('public-memory',len(self.rows))


def admitted_payroll(variant):
    facts = payroll_facts()
    account = account_opened('public-checking','depository','Public checking','USD','2021-01-01')
    net = simple_transaction('public-checking','80.00','Public payroll deposit',WHEN,
        provenance=Provenance(doc_id='public-bank',page=1))
    movement = LedgerProjection((account,net)).movements()[0].key
    decomposition = paystub_decomposition(facts.gross,facts.net,facts.deductions,'Public payroll',WHEN,
        provenance=Provenance(doc_id=facts.doc_id,page=1),matched_movement_key=movement,matched_currency='USD')
    events = [account,net]
    if variant!='no-ruling':
        ruling = ruling_recorded('account','public-checking',WHEN)
        if variant=='already-dated':ruling.body['occurred_at']=WHEN
        events.append(ruling)
    events.append(decomposition)
    original=wire([event.to_dict() for event in events])
    store=MemoryStore(original)
    ledger=SimpleNamespace(store=store,_lock=threading.RLock(),_resolve_keys=None)
    assert len(append_source(ledger,facts))==1
    return store,original


@pytest.mark.parametrize('variant',['no-ruling','missing-date','already-dated'])
def test_payroll_append_proof_matches_pristine_committed_replay(variant):
    store,original=admitted_payroll(variant)
    assert store.rows[:-1]==original
    pristine=replay(store.rows)
    assert pristine[-1].body['prefix']==encode(prefix(pristine[:-1]))
    assert len(_records(pristine))==1
    for _ in range(2):
        LedgerProjection(pristine)
        assert [event.to_dict() for event in pristine[:-1]]==original
        assert len(_records(pristine))==1


def test_wrong_committed_prefix_still_refuses():
    store,_original=admitted_payroll('no-ruling')
    changed=copy.deepcopy(store.rows)
    changed[-1]['body']['prefix']['prefix_digest']='0'*64
    with pytest.raises(EvidenceError,match='payroll source committed prefix differs'):
        _records(replay(changed))
