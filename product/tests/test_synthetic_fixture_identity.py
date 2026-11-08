"""Privacy-minimal fixture numbers retain full numeric identity semantics."""
from decimal import Decimal
import json,secrets
import pytest
from viva.ingest import BrokerageFacts,RawStore,ReadResult,capture_and_ingest
from viva.ledger import Ledger,LedgerProjection
from viva.ledger.identity import usable_full_number,number_key,account_key,account_tokens,masked
from test_cash_source_page_provenance import brokerage_facts,SYNTHETIC_BROKER_NUMBER
from test_retirement_closeout import ingest_snapshot,SYNTHETIC_RETIREMENT_NUMBER


def test_fixture_successors_actually_emit_the_declared_full_numbers(tmp_path):
    assert brokerage_facts().account_number==SYNTHETIC_BROKER_NUMBER
    secret=secrets.token_urlsafe(32)
    raw=RawStore.open(tmp_path/'raw',secret);ledger=Ledger.open(tmp_path/'events.jsonl',secret)
    result=ingest_snapshot(raw,ledger,'Synthetic identity observation',dated='2025-01-31',cash='10.00',total='10.00',positions=[])
    assert result.action=='posted'
    reads=[e for e in ledger.events()if e.event_type=='ReadRecorded'and e.body.get('doc_id')==result.doc_id]
    assert len(reads)==1
    assert json.loads(reads[0].body['response_text'])['account_number']==SYNTHETIC_RETIREMENT_NUMBER


@pytest.mark.parametrize('number,tail',[(SYNTHETIC_BROKER_NUMBER,'1234'),(SYNTHETIC_RETIREMENT_NUMBER,'3311')])
def test_full_numeric_repeat_collision_and_masked_boundaries(tmp_path,number,tail):
    assert len(number)==8 and number.isascii() and number.isdigit()
    assert usable_full_number(number)==number and number_key(number)==tail
    issuer='Synthetic fixture issuer';label='Synthetic fixture account';owner=['Synthetic fixture owner']
    assert account_key(issuer,number,label)=='acct:synthetic-fixture-issuer:'+tail
    assert tail in account_tokens(issuer,number,label)
    assert usable_full_number(masked(number))==''
    assert usable_full_number('SYNTHETIC-'+tail)==''
    rival='8765'+tail
    assert rival!=number and usable_full_number(rival)==rival and number_key(rival)==tail
    secret=secrets.token_urlsafe(32)
    raw=RawStore.open(tmp_path/'raw',secret);ledger=Ledger.open(tmp_path/'events.jsonl',secret)
    def ingest(full,label_bytes,dated):
        def reader(_original,doc):
            facts=BrokerageFacts(doc_id=doc,doc_type='brokerage_statement',doc_type_confidence=0.98,
                account_ref=label,currency='USD',as_of=dated,cash=Decimal('10.00'),total=Decimal('10.00'),
                positions=[],account_number=full,institution=issuer,account_names=owner)
            return ReadResult('brokerage_statement',0.98,facts=facts)
        return capture_and_ingest(raw,ledger,label_bytes,reader,captured_at='2025-03-05')
    first=ingest(number,b'synthetic first full identity','2025-01-31')
    second=ingest(rival,b'synthetic distinct same-tail full identity','2025-01-31')
    repeat=ingest(number,b'synthetic repeated full identity','2025-02-28')
    assert first.action==second.action==repeat.action=='posted'
    assert first.account==repeat.account and first.account!=second.account
    replay=LedgerProjection(ledger.events())
    assert len(replay.account_infos())==2
    assert replay.resolve(issuer,number,label,owner,kind='investment').account_id==first.account
    assert replay.resolve(issuer,rival,label,owner,kind='investment').account_id==second.account
