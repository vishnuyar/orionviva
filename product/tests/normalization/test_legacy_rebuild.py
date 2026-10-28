from contextlib import closing
import json
from decimal import Decimal
from viva.vault import Vault
from viva.ingest.pipeline import capture_and_ingest,ReadResult
from viva.ingest.statement import from_model_json
from test_rebuild_context import cash_payload,pdf


def test_context_free_ordinary_rebuild_keeps_requested_defaults_and_old_receipt_shape(tmp_path,monkeypatch):
    from viva import rebuild
    payload=cash_payload();text=json.dumps(payload)
    def legacy_reader(data,doc):
        facts,error=from_model_json(text,doc,'en-US','USD')
        assert error is None
        return ReadResult('checking_statement',1,facts,raw_text=text,model='legacy-route',cost_usd=.123)
    with closing(Vault.open(tmp_path/'source','synthetic-passphrase')) as source:
        capture_and_ingest(source.raw,source.ledger,pdf(payload),legacy_reader)
        old=[event for event in source.ledger.events() if event.event_type=='ReadRecorded'][0]
        assert 'normalization_context' not in old.body
    calls=[];parse=rebuild._parse
    def tracked(*args):calls.append(args);return parse(*args)
    monkeypatch.setattr(rebuild,'_parse',tracked)
    rebuild.rebuild(tmp_path/'source',tmp_path/'destination','synthetic-passphrase',
        locale='de-DE',currency='EUR',by_date=False,log=lambda *args:None)
    assert len(calls)==1 and calls[0][-2:]==('de-DE','EUR')
    with closing(Vault.open(tmp_path/'destination','synthetic-passphrase')) as destination:
        receipts=[event for event in destination.ledger.events() if event.event_type=='ReadRecorded']
        assert len(receipts)==1 and 'normalization_context' not in receipts[0].body
        assert receipts[0].event_id!=old.event_id
        assert receipts[0].body['input_mode']=='replay' and receipts[0].body['cost_usd']==0
        accounts=destination.ledger.projection().accounts()
        checking=next(account for account in accounts if destination.ledger.projection().account_info(account).kind=='depository')
        assert destination.ledger.projection().account_info(checking).currency=='EUR'
        assert destination.ledger.projection().running_balance(checking)==Decimal('1400')
