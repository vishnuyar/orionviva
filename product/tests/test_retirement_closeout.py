"""An accepted complete empty holdings snapshot replaces old measurements."""
import json
from decimal import Decimal
import pytest
from viva.ingest import RawStore,ReadResult,capture_and_ingest
from viva.ingest.brokerage import from_brokerage_json
from viva.ledger import EventStore,Ledger,LedgerProjection


# Leading zeros are significant in this unmasked synthetic full number.
SYNTHETIC_RETIREMENT_NUMBER = '00003311'


def ingest_snapshot(raw,ledger,label,*,dated,cash,total,positions,opening=None,activity=()):
    packet={'doc_type':'brokerage_statement','doc_type_confidence':1.0,'institution':'Synthetic Securities',
            'account_ref':'Synthetic retirement','account_number':SYNTHETIC_RETIREMENT_NUMBER,'currency':'USD',
            'as_of_raw':dated,'cash_raw':cash,'total_raw':total,'positions':positions,'activity':list(activity)}
    if opening is not None:packet.update(opening_cash_raw=opening,period_start_raw='2025-02-01')
    text=json.dumps(packet)
    def reader(blob,did):
        facts,error=from_brokerage_json(text,did,'en-US','USD');assert error is None,error
        return ReadResult('brokerage_statement',1.0,facts,model='synthetic-fixture-no-provider',raw_text=text)
    return capture_and_ingest(raw,ledger,label.encode(),reader,captured_at='2025-03-05')


@pytest.mark.parametrize('cash,withdrawal,total',[('0.00','100.00','0.00'),('25.00','75.00','25.00')])
def test_accepted_empty_closeout_clears_holdings_without_erasing_cash_history(tmp_path,cash,withdrawal,total):
    raw=RawStore.open(tmp_path/'raw','synthetic-passphrase');ledger=Ledger(EventStore.open(tmp_path/'events.jsonl','synthetic-passphrase'))
    first=ingest_snapshot(raw,ledger,'Synthetic opening holdings',dated='2025-01-31',cash='100.00',total='200.00',positions=[{'instrument':'Synthetic fund','units_raw':'10','market_value_raw':'100.00','page':1}])
    assert first.action=='posted'
    before=[e.to_dict() for e in ledger.events() if e.event_type in {'PositionObserved','TransactionRecorded','ClosingBalanceObserved'}]
    final=ingest_snapshot(raw,ledger,'Synthetic closeout',dated='2025-02-28',cash=cash,total=total,positions=[],opening='100.00',activity=[{'date_raw':'2025-02-20','kind':'withdrawal','amount_raw':withdrawal,'description':'Synthetic withdrawal'}])
    assert final.action=='posted'
    account=final.account;proj=ledger.projection()
    assert proj.positions(account)==[]
    assert proj.account_value(account)==Decimal(total)
    assert proj.composed_values(account)[0].as_of=='2025-02-28'
    assert LedgerProjection(ledger.events()).account_value(account)==Decimal(total)
    earlier=ledger.projection_as_of('2025-01-31');assert earlier.account_value(account)==Decimal('200.00')
    assert len(earlier.positions(account))==1
    assert ledger.projection_as_of('2025-02-28').account_value(account)==Decimal(total)
    after={e.event_id:e.to_dict() for e in ledger.events()}
    assert all(after[e['event_id']]==e for e in before)
