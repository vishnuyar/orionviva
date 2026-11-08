"""Printed source references reach the actual native transfer scan and P&L."""
import json
from decimal import Decimal
import pytest
from viva.ingest import RawStore,ReadResult,capture_and_ingest
from viva.ingest.statement import from_model_json
from viva.ledger import EventStore,Ledger
from viva.ledger.accounting import financial_statements


def upload_statement(raw,ledger,label,*,kind,reference,counterparty,amount,opening,closing,transaction_reference='SYNTHETIC-PAIR'):
    data={'doc_type':kind,'doc_type_confidence':1.0,'institution':'Synthetic Institution',
          'account_ref':label,'account_names':['Synthetic Person'],'source_account_ref':reference,'source_account_ref_page':1,
          'currency':'USD','opening':{'amount_raw':opening,'date_raw':'2025-01-01','page':1},
          'closing':{'amount_raw':closing,'date_raw':'2025-01-31','page':1},
          'transactions':[{'date_raw':'2025-01-10','amount_raw':str(abs(Decimal(amount))),
              'balance_effect':'decrease' if Decimal(amount)<0 else 'increase','description':'Opaque printed cash line',
              'source_reference':transaction_reference,'counterparty_reference':counterparty,'page':1}]}
    def read(blob,did):
        facts,error=from_model_json(json.dumps(data),did,'en-US','USD');assert error is None
        # This fixture supplies one authoritative synthetic page, outside model JSON.
        facts.validated_source_page_count=1
        return ReadResult(kind,1.0,facts)
    return capture_and_ingest(raw,ledger,label.encode(),read,captured_at='2025-02-01')


@pytest.mark.parametrize('destination_kind,destination_amount,opening,closing',[
    ('savings_statement','100.00','0.00','100.00'),
    ('credit_card_statement','-100.00','100.00','0.00'),
])
def test_structured_counterparty_links_only_native_pair_and_removes_internal_pnl(tmp_path,destination_kind,destination_amount,opening,closing):
    raw=RawStore.open(tmp_path/'raw','synthetic-passphrase')
    ledger=Ledger(EventStore.open(tmp_path/'events.jsonl','synthetic-passphrase'))
    source=upload_statement(raw,ledger,'Synthetic source',kind='checking_statement',reference='SOURCE-REF',counterparty='DESTINATION-REF',amount='-100.00',opening='500.00',closing='400.00')
    destination=upload_statement(raw,ledger,'Synthetic destination',kind=destination_kind,reference='DESTINATION-REF',counterparty='SOURCE-REF',amount=destination_amount,opening=opening,closing=closing)
    assert source.action==destination.action=='posted'
    proj=ledger.projection();assert len([m for m in proj.movements() if m.linked])==2
    links=[e for e in ledger.events() if e.event_type=='TransferLinked'];assert len(links)==1
    assert links[0].body['evidence']['decided_by']=='source_account_reference'
    assert links[0].body['grade']=='corroborated'
    assert proj.spending_by_currency()=={}
    report=financial_statements(proj)['profit_loss']
    assert not [line for line in report['lines'] if line['root'] in {'expenses','income'} and Decimal(line['amount'])]


def accepted_pair(tmp_path,monkeypatch):
    from viva.ingest import transfers
    raw=RawStore.open(tmp_path/'raw','synthetic-passphrase');ledger=Ledger(EventStore.open(tmp_path/'events.jsonl','synthetic-passphrase'))
    with monkeypatch.context() as patch:
        patch.setattr(transfers,'link_transfers',lambda *a,**k:{'linked':0,'auto':0,'suggested':0})
        upload_statement(raw,ledger,'Synthetic source',kind='checking_statement',reference='SOURCE-REF',counterparty='DESTINATION-REF',amount='-100.00',opening='500.00',closing='400.00')
        upload_statement(raw,ledger,'Synthetic destination',kind='savings_statement',reference='DESTINATION-REF',counterparty='SOURCE-REF',amount='100.00',opening='0.00',closing='100.00')
    return ledger


@pytest.mark.parametrize('defect',['missing_dependency','missing_reference','literal_case','source_uncaptured','destination_uncaptured','source_bound','destination_bound','ambiguous_owner'])
def test_source_reference_custody_refuses_unsupported_evidence(tmp_path,monkeypatch,defect):
    from viva.ingest.transfers import _structured_destinations
    ledger=accepted_pair(tmp_path,monkeypatch);proj=ledger.projection();core=proj.core
    source=next(m for m in proj.movements() if m.amount<0);destination=next(m for m in proj.movements() if m.amount>0)
    key=next(k for k,v in core._instrument_bank_references.items() if v[1]=='DESTINATION-REF')
    assert _structured_destinations(proj)[source.key]==destination.account
    if defect=='missing_dependency':core._instrument_cash_dependencies.pop(key)
    elif defect=='missing_reference':core._instrument_bank_references[key]=('', 'DESTINATION-REF')
    elif defect=='literal_case':core._instrument_bank_references[key]=('SYNTHETIC-PAIR','destination-ref')
    elif defect=='source_uncaptured':core._captured.pop(source.provenance.doc_id)
    elif defect=='destination_uncaptured':core._captured.pop(destination.provenance.doc_id)
    elif defect in {'source_bound','destination_bound'}:
        account=source.account if defect=='source_bound' else destination.account
        for row in core._instrument_account_refs[account]:row['identity_page_count']=None
    elif defect=='ambiguous_owner':core._instrument_account_refs[source.account].append(dict(core._instrument_account_refs[destination.account][0]))
    assert source.key not in _structured_destinations(proj)
    # The published view is cached until the next append; only the private fold
    # may supply the newly published view after a canonical event.
    from viva.ledger.events import agent_acted
    ledger.append(agent_acted('synthetic-isolation','read-only','synthetic','done','2025-02-02'))
    assert _structured_destinations(ledger.projection())[source.key]==destination.account


def test_human_spending_ruling_blocks_new_automatic_relationship(tmp_path,monkeypatch):
    from viva.ingest.transfers import link_transfers
    from viva.ledger.events import category_assigned
    ledger=accepted_pair(tmp_path,monkeypatch);source=next(m for m in ledger.projection().movements() if m.amount<0)
    ledger.append(category_assigned(source.key,source.description,'Synthetic expense','verified','2025-01-11',by='human',nature='spending'))
    assert link_transfers(ledger,profile_for=lambda m:None)['auto']==0
    assert not any(m.linked for m in ledger.projection().movements())
    assert ledger.projection().spending_by_currency()=={'USD':Decimal('100.00')}


def test_native_link_preserves_postings_is_idempotent_and_sql_activity_agrees(tmp_path,monkeypatch):
    from viva.ingest.transfers import link_transfers
    from viva.read_store import ReadStore
    from viva.ledger import LedgerProjection
    from viva.sql_authority.transfer_schema import valid_body
    from viva.ledger.transfer_admission import recognized_link_origin
    ledger=accepted_pair(tmp_path,monkeypatch)
    before=[(e.event_id,json.dumps(e.body,sort_keys=True),e.provenance.to_dict()) for e in ledger.events() if e.event_type=='TransactionRecorded']
    assert link_transfers(ledger,profile_for=lambda m:None)['auto']==1
    assert link_transfers(ledger,profile_for=lambda m:None)['auto']==0
    after=[(e.event_id,json.dumps(e.body,sort_keys=True),e.provenance.to_dict()) for e in ledger.events() if e.event_type=='TransactionRecorded'];assert after==before
    link=next(e for e in ledger.events() if e.event_type=='TransferLinked');assert valid_body('TransferLinked',link.body)
    for rule in ('source_account_reference','source_account_reference+printed_date'):
        body={**link.body,'evidence':{**link.body['evidence'],'decided_by':rule}}
        assert valid_body('TransferLinked',body)
        assert recognized_link_origin({'by':'auto','grade':'corroborated','decided_by':rule})=='auto'
    bad={**link.body,'evidence':{**link.body['evidence'],'decided_by':'invented_rule'}};assert not valid_body('TransferLinked',bad)
    canonical=ledger.projection();replay=LedgerProjection(ledger.events());assert [(m.key,m.linked,m.nature) for m in replay.movements()]==[(m.key,m.linked,m.nature) for m in canonical.movements()]
    with ReadStore.create(tmp_path/'read','synthetic-passphrase') as store:
        store.synchronize(ledger.store)
        with store.open_reader() as revision:
            for sql in (revision.activity_projection(),revision.historical_activity_projection(as_of='2025-01-31')):
                assert sorted((m.key,m.linked,m.nature) for m in sql.movements())==sorted((m.key,m.linked,m.nature) for m in canonical.movements())
                assert sql.transfer_links()
