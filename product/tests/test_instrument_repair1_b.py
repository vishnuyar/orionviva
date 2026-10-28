"""Fresh independent Slice B findings: preserve currency and partial evidence."""
import json
from decimal import Decimal
import pytest

from test_instrument_projector_b import setup,ingest,mortgage
from test_instrument_contracts import deposit_json,printed,identity
from viva.ingest.instrument_parser import parse_instrument_json
from viva.ingest.instrument_read import InstrumentReadFacts
from viva.ingest import ReadResult,capture_and_ingest
from viva.ingest.instrument_projector import heal_instruments
from viva.ledger import LedgerProjection
from viva.ledger.events import account_opened,opening_balance_observed,closing_balance_observed,Provenance
from viva.ledger.instruments import reference_accounts,reference_event
from viva.ingest.instrument_contracts import Source


def euro(raw,ledger,label,data,kind):
    def read(blob,doc):
        f=InstrumentReadFacts(doc,kind,1.0,parse_instrument_json(json.dumps(data),kind,doc,currency='EUR'),'EUR')
        return ReadResult(kind,1.0,f)
    return capture_and_ingest(raw,ledger,label.encode(),read)


def feb_deposit():
    data=deposit_json();data.update(start=printed('2021-02-01'),end=printed('2021-02-28'),opening=printed('1010'),closing=printed('1020'))
    data['movements'][0].update(dated=printed('2021-02-28'),reference=printed('INT-B'))
    return data


def receipt():
    return {'authority':printed('Fixture County'),'property_reference':printed('PROPERTY-A'),'tax_year':2021,
        'dated':printed('2021-01-20'),'reference':printed('TAX-A'),'amount':printed('100'),
        'status':'paid','tax_year_source':{'page':1},'status_source':{'page':1},'source_account_reference':printed('ESCROW-A')}


def assert_sql_source_state(raw_path, ledger, doc_id, component):
    from viva.read_store import ReadStore
    from viva.read_store.overview import SQLOverviewProjection
    with ReadStore.create(raw_path, 'synthetic-passphrase') as reads:
        reads.synchronize(ledger.store)
        with reads.open_reader() as revision:
            sql = SQLOverviewProjection(revision, '2023-12-31')
            oracle = LedgerProjection(ledger.events())
            assert sql.account_restrictions() == oracle.account_restrictions()
            assert sql.spending_by_currency() == oracle.spending_by_currency()
            rows = revision.connection.execute('SELECT state_json FROM instrument_component_states ORDER BY source_sequence').fetchall()
            states = [json.loads(row[0]) for row in rows if json.loads(row[0])['doc_id'] == doc_id]
            assert states
            assert next(row for row in states[-1]['components'] if row['component'] == component)['disposition'] == 'held'


def test_existing_usd_cd_never_silently_relabels_eur_interest_and_hold_survives_sql(tmp_path):
    from viva.read_store import ReadStore
    from viva.read_store.overview import SQLOverviewProjection
    raw,ledger=setup(tmp_path);first=ingest(raw,ledger,'usd-jan',deposit_json(),'term_deposit_statement')
    result=euro(raw,ledger,'eur-feb',feb_deposit(),'term_deposit_statement')
    assert result.action=='awaiting'
    for p in (ledger.projection(),LedgerProjection(ledger.events())):
        assert p.running_balance(first.account)==Decimal('1010')
        assert p.account_info(first.account).currency=='USD'
        assert p.income_by_currency()=={'USD':Decimal('10')}
        assert p.is_resolved(result.doc_id)
        state=next(s for s in p.instrument_component_states().values() if s.doc_id==result.doc_id)
        assert any(r.disposition.value=='held' and 'currency' in r.reason for r in state.components)
    assert heal_instruments(ledger)==0
    with ReadStore.create(tmp_path/'read','synthetic-passphrase') as reads:
        reads.synchronize(ledger.store)
        with reads.open_reader() as revision:
            sql=SQLOverviewProjection(revision,'2021-02-28')
            assert sql.balance(first.account).amount==Decimal('1010')
            assert not any(m.description=='INT-B' for m in sql.movements())


def test_known_distinct_currency_binding_is_selected_without_ambiguity_or_usd_mutation(tmp_path):
    raw,ledger=setup(tmp_path);first=ingest(raw,ledger,'usd-jan',deposit_json(),'term_deposit_statement')
    source=Source(first.doc_id,1);prov=Provenance(first.doc_id,1)
    ledger.append(account_opened('explicit-eur','depository','CD-A','EUR','2021-01-01',
        institution='Fixture Institution',account_names=['Synthetic Person'],provenance=prov))
    ledger.append(reference_event('explicit-eur','CD-A','2021-01-01',source))
    ledger.append(opening_balance_observed('explicit-eur','1010','2021-01-31',prov))
    ledger.append(closing_balance_observed('explicit-eur','1010','2021-01-31',prov))
    result=euro(raw,ledger,'eur-feb',feb_deposit(),'term_deposit_statement')
    assert result.action=='posted' and result.account=='explicit-eur'
    assert ledger.projection().running_balance(first.account)==Decimal('1010')
    assert ledger.projection().running_balance('explicit-eur')==Decimal('1020')
    assert ledger.projection().account_info('explicit-eur').currency=='EUR'


@pytest.mark.parametrize('missing',['amount','dated','reference'])
def test_partial_held_escrow_row_never_crashes_or_certifies_receipt(tmp_path,missing):
    raw,ledger=setup(tmp_path);data=mortgage();del data['escrow']['movements'][1][missing]
    first=ingest(raw,ledger,'partial-escrow-'+missing,data,'mortgage_statement')
    result=ingest(raw,ledger,'receipt-'+missing,receipt(),'property_tax_receipt')
    assert result.action=='awaiting'
    p=ledger.projection();state=next(s for s in p.instrument_component_states().values() if s.doc_id==result.doc_id)
    assert next(r for r in state.components if r.component=='tax_payment_link').disposition.value=='held'
    assert p.running_balance(reference_accounts(p,'LOAN-A')[0])==Decimal('900')
    assert not any(m.description=='TAX-A' for m in p.movements())
    assert p.is_resolved(first.doc_id) and p.is_resolved(result.doc_id)
    assert LedgerProjection(ledger.events()).is_resolved(result.doc_id)
    assert_sql_source_state(tmp_path/'partial-read',ledger,result.doc_id,'tax_payment_link')
    assert heal_instruments(ledger)==0


def test_ambiguous_source_escrow_account_cannot_be_resolved_by_amount_or_reference(tmp_path):
    raw,ledger=setup(tmp_path);first=ingest(raw,ledger,'mortgage-source',mortgage(),'mortgage_statement')
    ledger.append(account_opened('second-escrow','depository','Other Escrow','USD','2021-01-01',
        institution='Other Servicer',account_names=['Synthetic Person'],provenance=Provenance(first.doc_id,1)))
    ledger.append(reference_event('second-escrow','ESCROW-A','2021-01-01',Source(first.doc_id,1)))
    result=ingest(raw,ledger,'ambiguous-receipt',receipt(),'property_tax_receipt')
    assert result.action=='awaiting'
    state=next(s for s in ledger.projection().instrument_component_states().values() if s.doc_id==result.doc_id)
    assert next(r for r in state.components if r.component=='tax_payment_link').disposition.value=='held'
    assert sum(m.description=='TAX-A' for m in ledger.projection().movements())==1
    assert_sql_source_state(tmp_path/'ambiguous-read',ledger,result.doc_id,'tax_payment_link')


def test_different_currency_new_loan_keeps_valid_principal_while_existing_escrow_currency_is_held(tmp_path):
    raw,ledger=setup(tmp_path);first=ingest(raw,ledger,'usd-loan',mortgage(),'mortgage_statement')
    old_escrow=reference_accounts(ledger.projection(),'ESCROW-A')[0]
    data=mortgage();data['identity']=identity('LOAN-EUR');data['identity']['institution']=printed('Replacement Servicer')
    data.update(start=printed('2021-02-01'),end=printed('2021-02-28'),opening_principal=printed('500'),closing_principal=printed('450'))
    data['principal_movements']=[{'kind':'principal_reduction','amount':printed('50'),'dated':printed('2021-02-15'),'reference':printed('PAY-EUR')}]
    data['payments']=[];data['escrow']['identity']['institution']=printed('Replacement Servicer')
    data['escrow'].update(opening=printed('200'),closing=printed('500'),movements=[{
        'kind':'deposit','amount':printed('300'),'dated':printed('2021-02-15'),'reference':printed('PAY-EUR')}])
    result=euro(raw,ledger,'eur-loan',data,'mortgage_statement')
    assert result.action=='awaiting'
    p=ledger.projection()
    assert p.running_balance(result.account)==Decimal('450') and p.account_info(result.account).currency=='EUR'
    assert p.running_balance(first.account)==Decimal('900') and p.account_info(first.account).currency=='USD'
    assert p.running_balance(old_escrow)==Decimal('200') and p.account_info(old_escrow).currency=='USD'
    assert len([a for a,r in p.account_restrictions().items() if r.family=='escrow'])==1
    assert_sql_source_state(tmp_path/'multi-read',ledger,result.doc_id,'escrow_balance')


def test_invalid_escrow_balance_section_does_not_crash_receipt_matching(tmp_path):
    raw,ledger=setup(tmp_path);data=mortgage();data['escrow']['opening']=printed('-1');data['escrow']['closing']=printed('199')
    first=ingest(raw,ledger,'invalid-escrow-balance',data,'mortgage_statement')
    assert first.action=='awaiting'
    result=ingest(raw,ledger,'receipt-invalid-escrow',receipt(),'property_tax_receipt')
    assert result.action=='awaiting'
    assert not any(m.description=='TAX-A' for m in ledger.projection().movements())
    assert_sql_source_state(tmp_path/'invalid-read',ledger,result.doc_id,'tax_payment_link')


@pytest.mark.parametrize('kind',['mortgage_statement','refinance_settlement'])
def test_existing_loan_currency_binding_is_not_reused_for_other_currency(tmp_path,kind):
    from test_instrument_contracts import refinance_json
    raw,ledger=setup(tmp_path)
    if kind=='mortgage_statement':
        first=ingest(raw,ledger,'usd-loan',mortgage(),kind)
        data=mortgage();data.update(start=printed('2021-02-01'),end=printed('2021-02-28'),
            opening_principal=printed('900'),closing_principal=printed('800'))
        for row in data['principal_movements']:row['dated']=printed('2021-02-15')
        for row in data['payments']:row['dated']=printed('2021-02-15')
        data['escrow']=None
        expected=Decimal('900')
    else:
        first=ingest(raw,ledger,'usd-refi',refinance_json(),kind)
        data=refinance_json();data['dated']=printed('2023-02-01')
        data['new_funded_principal']=printed('1010');data['old_payoff_principal']=printed('1010')
        expected=Decimal('1000')
    result=euro(raw,ledger,'eur-'+kind,data,kind)
    assert result.action=='awaiting'
    p=ledger.projection();assert p.running_balance(first.account)==expected and p.account_info(first.account).currency=='USD'
    state=next(s for s in p.instrument_component_states().values() if s.doc_id==result.doc_id)
    assert any(r.disposition.value=='held' and 'currency' in r.reason for r in state.components)


def test_ambiguous_same_currency_primary_identity_is_a_durable_hold(tmp_path):
    raw,ledger=setup(tmp_path);first=ingest(raw,ledger,'usd-jan',deposit_json(),'term_deposit_statement')
    prov=Provenance(first.doc_id,1)
    ledger.append(account_opened('other-usd','depository','CD-A','USD','2021-01-01',
        institution='Fixture Institution',account_names=['Synthetic Person'],provenance=prov))
    ledger.append(reference_event('other-usd','CD-A','2021-01-01',Source(first.doc_id,1)))
    result=ingest(raw,ledger,'ambiguous-primary',feb_deposit(),'term_deposit_statement')
    assert result.action=='identity'
    assert ledger.projection().is_resolved(result.doc_id)
    assert any(row['doc_id']==result.doc_id for row in ledger.projection().open_holds())
    assert ledger.projection().running_balance(first.account)==Decimal('1010')
