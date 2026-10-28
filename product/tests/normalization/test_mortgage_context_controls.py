import json
from decimal import Decimal
import pytest
from viva.ledger.events import Event
from viva.ingest.instrument_projector import heal_instruments
from viva.ledger.instruments import reference_accounts,encode
from viva.ingest.instrument_parser import parse_instrument_json
from test_mortgage_context_maintenance import ingest
from test_instrument_projector_b import setup,bank,mortgage


@pytest.mark.parametrize('mutation',['locale','printed_currency_conflict','legacy_only','other_full_payload'])
def test_actual_known_allocation_uses_only_one_recorded_full_interpretation(tmp_path,mutation):
    raw,ledger=setup(tmp_path);bank(raw,ledger)
    data=mortgage();data['payments'][0]['fees']=None
    if mutation=='locale':data['opening_principal']['raw']='1,000'
    if mutation=='printed_currency_conflict':data['payments'][0]['total']['raw']='$600'
    result=ingest(raw,ledger,'known-'+mutation,data,'mortgage_statement')
    projection=ledger.projection()
    assert len(projection.instrument_allocations())==1
    original_cash=[event.to_dict() for event in ledger.events() if event.event_type=='TransactionRecorded']
    prior=next(event for event in reversed(tuple(ledger.events())) if event.event_type=='ReadRecorded' and event.body['doc_id']==result.doc_id)
    body=json.loads(json.dumps(prior.body))
    if mutation=='locale':
        before=parse_instrument_json(body['response_text'],'mortgage_statement',result.doc_id,'en-US','USD')
        after=parse_instrument_json(body['response_text'],'mortgage_statement',result.doc_id,'de-DE','USD')
        assert before.opening_principal.value==1000 and after.opening_principal.value==1
        assert encode(before)!=encode(after)
        body['normalization_context']['parser_locale']='de-DE'
    elif mutation=='printed_currency_conflict':
        with pytest.raises(ValueError):parse_instrument_json(body['response_text'],'mortgage_statement',result.doc_id,'en-US','EUR')
        body['normalization_context']['parser_currency']='EUR'
    elif mutation=='legacy_only':
        body.pop('normalization_context');body.update(normalization_locale='en-US',source_currency='USD')
    else:
        changed=json.loads(body['response_text']);changed['identity']['institution']['raw']='Different printed institution'
        body['response_text']=json.dumps(changed)
    ledger.append(Event('ReadRecorded',prior.occurred_at,body,prior.provenance));heal_instruments(ledger)
    projection=ledger.projection()
    assert not projection.instrument_allocations()
    assert projection.running_balance(reference_accounts(projection,'LOAN-A')[0])==Decimal('900')
    assert original_cash==[event.to_dict() for event in ledger.events() if event.event_type=='TransactionRecorded']
    from viva.ledger import Ledger,EventStore
    reopened=Ledger(EventStore.open(tmp_path/'events.jsonl','synthetic-passphrase'))
    assert not reopened.projection().instrument_allocations()
    assert heal_instruments(reopened)==0
