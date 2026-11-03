"""Dated investment measurements and cash interest belong to native SQL state."""
from decimal import Decimal as D
import hashlib
import secrets

import pytest

from viva.ingest.brokerage import BrokerageFacts, BrokerageActivity, PositionFact
from viva.ingest.pipeline_models import ReadResult
from viva.ingest.registry import BROKERAGE_IDENTITY, INVESTMENT, profile_for
from viva.investment.extraction import HEADERS, POSITION, ROW, parse
from viva.ledger.events import Provenance
from viva.ledger.postings import brokerage_activity_transaction, brokerage_cash_effect
from viva.sql_authority import SQLAuthority
from vivacore.verify.arithmetic import check_balance_identity, check_brokerage_identity

from test_sql_authority_bank import ingest

pytestmark = pytest.mark.production_kdf


def test_investment_snapshot_and_interest_are_native_sql(tmp_path, record_property):
    bank_source = b"synthetic unrelated bank source"
    investment_original = b"synthetic investment snapshot and interest source"
    doc_id = hashlib.sha256(investment_original).hexdigest()

    with SQLAuthority.create(
        tmp_path.resolve() / "authority", secrets.token_urlsafe(48), verification="complete",
    ) as store:
        bank = ingest(store, bank_source)
        assert bank.status == "accepted"
        assert store.account(bank.account_id)["running_balance"] == "90"
        bank_transactions = store.transactions(bank.account_id)
        assert len(bank_transactions) == 1
        bank_postings = store.postings(bank.doc_id)
        assert [(leg["account"], leg["amount"], leg["grade"]) for leg in bank_postings] == [
            (bank.account_id, "-10", "verified"),
            ("Expenses:Uncategorized", "10", "unverified"),
        ]
        assert sum((D(leg["amount"]) for leg in bank_postings), D(0)) == 0
        assert all(leg["provenance"]["doc_id"] == bank.doc_id for leg in bank_postings)
        assert store.original(bank.doc_id) == bank_source
        assert store.receipt(bank.doc_id)["contract"] == "synthetic-balance-v1"
        assert store.verify()["verified"]

        def field(raw):
            return {"raw": raw, "page": 1}

        headers = dict.fromkeys(HEADERS)
        headers.update(
            account_reference=field("Synthetic Investment"), currency=field("USD"),
            period_start=field("2026-01-01"), period_end=field("2026-01-31"),
            as_of=field("2026-01-31"), opening_cash=field("9"), closing_cash=field("10"),
        )
        position_source = dict.fromkeys(POSITION)
        position_source.update(identifier=field("SYNTH-SEC"), label=field("Synthetic Security"),
                               units=field("2"), market_value=field("20"), cost_basis=field("18"))
        activity_source = dict.fromkeys(ROW)
        activity_source.update(date=field("2026-01-15"), kind=field("interest"), amount=field("1"))
        source_wire = {"schema": "investment-source-v1", "headers": headers,
                       "positions": [position_source], "rows": [activity_source]}
        source = parse(source_wire)
        assert source.to_dict() == source_wire
        assert parse(source.to_dict()).to_dict() == source_wire
        facts = BrokerageFacts(
            doc_id=doc_id, doc_type="brokerage_statement", doc_type_confidence=1.0,
            account_ref="Synthetic Investment", currency="USD", as_of="2026-01-31",
            cash=D("10"), total=D("30"),
            positions=[PositionFact("SYNTH-SEC", D("2"), D("20"), D("18"), page=1)],
            account_number="987654321", institution="Synthetic Investment Issuer",
            account_names=["Synthetic Person"], opening_cash=D("9"),
            activity=[BrokerageActivity("2026-01-15", "interest", D("1"), "Synthetic interest")],
            investment_source=source, validated_source_page_count=1,
        )
        assert BrokerageFacts.from_dict(facts.to_dict()).to_dict() == facts.to_dict()
        assert facts.doc_id == hashlib.sha256(investment_original).hexdigest()
        assert dict(source.headers)["account_reference"].raw == facts.account_ref
        assert dict(source.headers)["currency"].raw == facts.currency
        assert dict(source.headers)["as_of"].raw == facts.as_of
        assert D(dict(source.headers)["opening_cash"].raw) == facts.opening_cash
        assert D(dict(source.headers)["closing_cash"].raw) == facts.cash
        assert dict(source.positions[0])["identifier"].raw == facts.positions[0].instrument
        assert D(dict(source.positions[0])["units"].raw) == facts.positions[0].units
        assert D(dict(source.positions[0])["market_value"].raw) == facts.positions[0].market_value
        assert D(dict(source.positions[0])["cost_basis"].raw) == facts.positions[0].cost_basis
        assert dict(source.rows[0])["date"].raw == facts.activity[0].date
        assert dict(source.rows[0])["kind"].raw == facts.activity[0].kind
        assert D(dict(source.rows[0])["amount"].raw) == facts.activity[0].amount
        assert all(value.page == 1 for record in (source.headers, source.positions[0], source.rows[0])
                   for _name, value in record if value is not None)
        profile = profile_for(facts.doc_type)
        assert profile.identity == BROKERAGE_IDENTITY == "brokerage"
        assert profile.account_kind == INVESTMENT == "investment"
        assert check_brokerage_identity([position.market_value for position in facts.positions],
                                        facts.cash, facts.total).passed
        cash_effect = brokerage_cash_effect(facts.activity[0].kind, facts.activity[0].amount)
        assert cash_effect == D("1")
        assert check_balance_identity(facts.opening_cash, [cash_effect], facts.cash).passed
        interest = brokerage_activity_transaction(
            "synthetic-investment-cash", "interest", D("1"), "Synthetic interest", "2026-01-15",
            provenance=Provenance(doc_id, 1),
        )
        assert [(leg["account"], leg["amount"], leg["grade"]) for leg in interest.body["postings"]] == [
            ("synthetic-investment-cash", "1", "verified"),
            ("Income:Interest", "-1", "verified"),
        ]
        assert sum((D(leg["amount"]) for leg in interest.body["postings"]), D(0)) == 0
        record_property("positive_complete_sql_bank_and_typed_investment_contract", "passed")

        def reader(original, actual_doc_id):
            assert original == investment_original
            assert actual_doc_id == doc_id == facts.doc_id
            return ReadResult("brokerage_statement", 1.0, facts=facts)

        result = store.ingest(investment_original, reader, contract="synthetic-investment-v1")
        assert result.status == "accepted"

        account_id = result.account_id
        assert account_id and account_id != bank.account_id
        snapshot = store.investment_snapshot(account_id, as_of="2026-01-31")
        assert (snapshot["account_id"], snapshot["currency"], snapshot["as_of"], snapshot["doc_id"]) == (
            account_id, "USD", "2026-01-31", doc_id,
        )
        assert (snapshot["cash"], snapshot["total"]) == ("10", "30")
        assert len(snapshot["positions"]) == 1
        position = snapshot["positions"][0]
        assert (position["instrument"], position["units"], position["market_value"],
                position["cost_basis"], position["page"], position["grade"]) == (
            "SYNTH-SEC", "2", "20", "18", 1, "corroborated",
        )
        period = store.investment_cash_period(doc_id)
        assert (period["doc_id"], period["account_id"], period["period_start"], period["period_end"],
                period["opening_cash"], period["closing_cash"], period["state"]) == (
            doc_id, account_id, "2026-01-01", "2026-01-31", "9", "10", "accepted",
        )
        activity = store.investment_activity(doc_id)
        assert len(activity) == 1
        assert (activity[0]["doc_id"], activity[0]["date"], activity[0]["kind"],
                activity[0]["amount"], activity[0]["page"]) == (doc_id, "2026-01-15", "interest", "1", 1)
        postings = store.investment_postings(doc_id)
        assert [(leg["account"], leg["amount"], leg["currency"], leg["grade"]) for leg in postings] == [
            (account_id, "1", "USD", "verified"),
            ("Income:Interest", "-1", "USD", "verified"),
        ]
        assert sum((D(leg["amount"]) for leg in postings), D(0)) == 0
        assert all(leg["provenance"]["doc_id"] == doc_id and leg["provenance"]["page"] == 1 for leg in postings)
        assert store.original(doc_id) == investment_original
        receipt = store.receipt(doc_id)
        assert receipt["contract"] == "synthetic-investment-v1"
        assert receipt["facts"]["doc_id"] == doc_id
        assert receipt["facts"]["investment_source"] == source_wire
        assert store.account(bank.account_id)["running_balance"] == "90"
        assert store.transactions(bank.account_id) == bank_transactions
        assert store.postings(bank.doc_id) == bank_postings
        assert store.verify()["verified"]

        assert store.resume(doc_id).status == "accepted"
        assert store.investment_snapshot(account_id, as_of="2026-01-31") == snapshot
        assert store.investment_cash_period(doc_id) == period
        assert store.investment_activity(doc_id) == activity
        assert store.investment_postings(doc_id) == postings

        def duplicate_reader(*_args):
            pytest.fail("duplicate investment must use the retained reading")

        assert store.ingest(investment_original, duplicate_reader,
                            contract="synthetic-investment-v1").status == "accepted"
        assert store.investment_snapshot(account_id, as_of="2026-01-31") == snapshot
        assert store.investment_cash_period(doc_id) == period
        assert store.investment_activity(doc_id) == activity
        assert store.investment_postings(doc_id) == postings
        assert store.account(bank.account_id)["running_balance"] == "90"
        assert store.transactions(bank.account_id) == bank_transactions
        assert store.postings(bank.doc_id) == bank_postings
        assert store.verify()["verified"]


@pytest.fixture
def investment_store(tmp_path):
    with SQLAuthority.create(tmp_path.resolve() / 'native-investment', secrets.token_urlsafe(48), verification='complete') as store:
        yield store


def _investment(store, label=b'synthetic native investment', *, cash='10', total='30', opening='9',
                start='2026-01-01', end='2026-01-31', positions=None, activity=None,
                source_version='investment-source-v1', mutate_source=None, **overrides):
    def read(_original, doc):
        def field(value):
            return None if value is None else {'raw':str(value),'page':1}
        typed_positions=[PositionFact('SYNTH-SEC',D('2'),D('20'),D('18'),page=1)] if positions is None else positions
        typed_activity=[BrokerageActivity('2026-01-15','interest',D('1'),'Synthetic interest')] if activity is None else activity
        header=dict.fromkeys(HEADERS)
        header.update(account_reference=field('Synthetic Investment'),currency=field('USD'),period_start=field(start),
            period_end=field(end),as_of=field(end),opening_cash=field(opening),closing_cash=field(cash))
        population=[]
        for position in typed_positions:
            row=dict.fromkeys(POSITION)
            row.update(identifier=field(position.instrument),units=field(position.units),market_value=field(position.market_value),cost_basis=field(position.cost_basis))
            population.append(row)
        source_rows=[]
        for line in typed_activity:
            row=dict.fromkeys(ROW)
            row.update(date=field(line.date or end),kind=field(line.kind),amount=field(line.amount),
                security_identifier=field(line.instrument) if line.instrument else None,reported_realized_gain=field(line.realized_gain))
            source_rows.append(row)
        source={'schema':source_version,'headers':header,'positions':population,'rows':source_rows}
        if mutate_source:
            mutate_source(source)
        facts=BrokerageFacts(doc,'brokerage_statement',1.0,'Synthetic Investment','USD',end,D(cash),D(total),typed_positions,
            account_number='987654321',institution='Synthetic Investment Issuer',account_names=['Synthetic Person'],
            opening_cash=None if opening is None else D(opening),activity=typed_activity,investment_source=parse(source),validated_source_page_count=1)
        for name,value in overrides.items():
            setattr(facts,name,value)
        return ReadResult(facts.doc_type,1.0,facts=facts)
    return store.ingest(label,read,contract='synthetic-investment-v1')


@pytest.mark.parametrize('value,expected', [
    ('-0E+9999','0'),('1.2300','1.23'),('-0.01200','-0.012'),
    ('1E+20000','1e20000'),('1E-20000','1e-20000'),
    ('-123456789012345678901234567890.123456789','-123456789012345678901234567890.123456789'),
])
def test_compact_measurement_numbers_preserve_exact_value(value, expected):
    from viva.sql_authority.investment_numbers import display,scalar,key
    assert display(D(value))==expected
    assert scalar(expected)==D(value)
    assert key(D(value))==key(scalar(expected))


@pytest.mark.parametrize('values,expected', [
    (['1E+20000','-1E+20000'],True),(['1E+20000','-1E+20000','1E-20000'],False),
    (['1E-20000','-1E-20000','0'],True),(['-3.5','1.2','2.3'],True),
    (['9999999999999999999999999999','1','-1E+28'],True),
])
def test_sparse_decimal_cancellation_does_not_round(values, expected):
    from viva.sql_authority.investment_numbers import zero_sum
    assert zero_sum([D(v) for v in values]) is expected


def test_exact_decimal_identity_agrees_with_independent_bounded_integer_oracle():
    from viva.sql_authority.investment_numbers import zero_sum
    for first in (-913,-7,0,23,1011):
        for second in (-81,0,97):
            values=[D(first).scaleb(-3),D(second).scaleb(-2)]
            expected_integer=first+second*10
            assert zero_sum(values+[D(-expected_integer).scaleb(-3)])
            assert not zero_sum(values+[D(-expected_integer+1).scaleb(-3)])


def test_extreme_activity_with_reported_zero_gain_has_no_false_exponent_span():
    from viva.sql_authority.investment_numbers import posting_precision,zero_sum
    from decimal import localcontext,MAX_EMAX,MIN_EMIN
    amount=D('1E+20000')
    precision=posting_precision(amount,D('0'))
    assert precision<10
    with localcontext() as context:
        context.prec=precision;context.Emax=MAX_EMAX;context.Emin=MIN_EMIN
        event=brokerage_activity_transaction('synthetic-cash','sell',amount,'synthetic sale','2026-01-01',realized_gain=D(0))
    assert zero_sum([D(p['amount']) for p in event.body['postings']])
    assert D(event.body['postings'][0]['amount'])==amount


@pytest.mark.parametrize('source_version',['investment-source-v1','investment-source-v2'])
def test_native_investment_custom_source_wire_and_repeated_resume_are_retained(investment_store, source_version):
    store=investment_store
    result=_investment(store,source_version=source_version)
    assert result.status=='accepted'
    assert store.receipt(result.doc_id)['facts']['investment_source']['schema']==source_version
    assert store.investment_component(result.doc_id)['funding_state']=='unavailable'
    history=store.investment_history(result.doc_id)
    postings=store.investment_postings(result.doc_id)
    head=store.head
    assert store.resume(result.doc_id).status=='accepted'
    assert store.head==head
    assert store.investment_history(result.doc_id)==history
    assert store.investment_postings(result.doc_id)==postings
    assert store.verify()['verified']


def test_whole_copies_corroborate_without_duplicate_money(investment_store):
    store=investment_store
    first=_investment(store,b'synthetic investment original')
    second=_investment(store,b'synthetic independent identical copy')
    assert first.status==second.status=='accepted'
    assert first.account_id==second.account_id
    snapshot=store.investment_snapshot(first.account_id,as_of='2026-01-31')
    assert set(snapshot['source_docs'])=={first.doc_id,second.doc_id}
    assert store.investment_postings(second.doc_id)==[]
    assert len(store.investment_postings(first.doc_id))==2
    assert len(store.investment_history(second.doc_id)['witnesses'])==1
    assert store.verify()['verified']


def test_equal_activity_occurrences_are_distinct_money_and_copies_keep_multiplicity(investment_store):
    lines=[BrokerageActivity('2026-01-15','interest',D('1'),'same printed row') for _ in range(2)]
    first=_investment(investment_store,b'two equal genuine rows',opening='8',activity=lines)
    copy=_investment(investment_store,b'copy of two equal genuine rows',opening='8',activity=lines)
    postings=investment_store.investment_postings(first.doc_id)
    assert len(postings)==4
    assert len({p['effect_id'] for p in postings})==2
    assert investment_store.investment_postings(copy.doc_id)==[]
    assert [r['amount'] for r in investment_store.investment_activity(first.doc_id)]==['1','1']
    assert investment_store.verify()['verified']


def test_complete_zero_population_replaces_holdings_after_actual_sell_and_withdrawal(investment_store):
    store=investment_store
    first=_investment(store,b'funded population')
    closing=_investment(store,b'actual complete liquidation and withdrawal',cash='0',total='0',opening='10',start='2026-02-01',end='2026-02-28',positions=[],
        activity=[BrokerageActivity('2026-02-10','sell',D('20'),'Sell actual holding','SYNTH-SEC'),
                  BrokerageActivity('2026-02-12','withdrawal',D('30'),'Withdraw all cash')])
    assert closing.status=='accepted'
    assert closing.account_id==first.account_id
    current=store.investment_snapshot(first.account_id,as_of='2026-02-28')
    assert (current['cash'],current['total'],current['positions'])==('0','0',[])
    assert store.investment_snapshot(first.account_id,as_of='2026-01-31')['total']=='30'
    assert store.account(first.account_id)['running_balance']=='0'
    assert len(store.investment_activity(closing.doc_id))==2
    assert len(store.investment_postings(closing.doc_id))==4
    assert store.verify()['verified']


def test_late_root_releases_omitted_opening_with_a_gap_without_backdating(investment_store):
    store=investment_store
    late=_investment(store,b'initially unseeded later period',cash='11',total='31',opening=None,start='2026-03-01',end='2026-03-31',
        activity=[BrokerageActivity('2026-03-15','interest',D('1'))])
    assert late.status=='accepted'
    assert store.investment_component(late.doc_id)['activity_state']=='held'
    first=_investment(store,b'earlier actual printed opening source')
    assert first.account_id==late.account_id
    period=store.investment_cash_period(late.doc_id)
    assert (period['state'],period['opening_cash'],period['opening_kind'])==('accepted','10','carried')
    history=store.investment_history(late.doc_id)
    assert history['decisions'][0]['revision']>late.revision
    assert len(store.investment_postings(late.doc_id))==2
    assert store.verify()['verified']


def test_first_holdings_only_document_does_not_seed_later_activity(investment_store):
    store=investment_store
    first=_investment(store,b'holdings only',opening=None,activity=[])
    second=_investment(store,b'activity without a printed seed',cash='11',total='31',opening=None,start='2026-02-01',end='2026-02-28',activity=[BrokerageActivity('2026-02-15','interest',D('1'))])
    assert first.status==second.status=='accepted'
    assert store.investment_component(second.doc_id)['reason']=='seed_unavailable'
    assert store.investment_postings(second.doc_id)==[]
    assert store.verify()['verified']


@pytest.mark.parametrize('change',['reference','gain','amount'])
def test_changed_complete_period_keeps_conflicting_claims_and_reversal_history(investment_store, change):
    store=investment_store
    first=_investment(store,b'first cash claim')
    prior=store.investment_history(first.doc_id)
    original_basis=prior['decisions'][0]['basis_id']
    def changed_source(source):
        if change=='reference':
            source['rows'][0]['printed_reference']={'raw':'different reference','page':1}
    lines=[BrokerageActivity('2026-01-15','interest',D('2' if change=='amount' else '1'),realized_gain=D('0') if change=='gain' else None)]
    second=_investment(store,b'different '+change.encode(),opening='8' if change=='amount' else '9',activity=lines,mutate_source=changed_source)
    assert second.status=='accepted'
    assert store.investment_component(first.doc_id)['activity_state']=='conflicted'
    history=store.investment_history(first.doc_id)
    assert [d['action'] for d in history['decisions']]==['activate','deactivate']
    assert history['decisions'][1]['basis_id']==original_basis
    assert history['decisions'][1]['previous_ordinal']==history['decisions'][0]['ordinal']
    active=store._row('investment_active','group_id=?',(history['witnesses'][0]['group_id'],))
    assert active['active']==0 and active['basis_id'] is None
    legs=store.investment_postings(first.doc_id)
    assert len(legs)==4
    assert sum((D(p['amount']) for p in legs),D(0))==0
    assert store.investment_postings(second.doc_id)==[]
    assert store.verify()['verified']


def test_signed_positions_and_optional_unknown_cost_basis_survive(investment_store):
    result=_investment(investment_store,b'actual signed typed positions',total='-10',positions=[PositionFact('SHORT',D('-2'),D('-20'),None,page=1)])
    assert result.status=='accepted'
    position=investment_store.investment_snapshot(result.account_id,as_of='2026-01-31')['positions'][0]
    assert (position['units'],position['market_value'],position['cost_basis'])==('-2','-20',None)
    assert investment_store.verify()['verified']


@pytest.mark.parametrize('facet',['snapshot','activity','optional_basis'])
def test_source_field_conflicts_are_local_and_retained(investment_store, facet):
    def change(source):
        if facet=='snapshot':source['positions'][0]['market_value']['raw']='21'
        elif facet=='activity':source['rows'][0]['amount']['raw']='2'
        else:source['positions'][0]['cost_basis']['raw']='19'
    result=_investment(investment_store,b'conflicting '+facet.encode(),mutate_source=change)
    component=investment_store.investment_component(result.doc_id)
    conflicts=[f for f in component['fields'] if f['status']=='conflicted']
    assert conflicts and all(f['grade']=='conflicted' and f['value'] is None for f in conflicts)
    if facet=='snapshot':
        assert result.status=='pending'
        assert component['snapshot_state']=='conflicted'
    elif facet=='activity':
        assert result.status=='accepted' and component['snapshot_state']=='accepted'
        assert component['activity_state']=='conflicted'
        assert investment_store.investment_postings(result.doc_id)==[]
    else:
        assert result.status=='accepted' and component['activity_state']=='accepted'
    assert investment_store.verify()['verified']


@pytest.mark.parametrize('wire_change',['separate_amount','custom_schema','capture_type','page_extent'])
def test_retained_investment_wire_mismatch_is_held_without_native_money(investment_store,monkeypatch,wire_change):
    import json
    from viva.sql_authority.store import canonical
    put=investment_store._put
    def change(table,row):
        if table=='receipts':
            if wire_change=='capture_type':
                tags=json.loads(row['capture_types']);tags['decimals']=1
                row={**row,'capture_types':canonical(tags)}
            else:
                facts=json.loads(row['facts'])
                if wire_change=='separate_amount':facts['cash']='11'
                elif wire_change=='custom_schema':facts['investment_source']['schema']='unrecognized-source'
                else:facts['validated_source_page_count']=True
                row={**row,'facts':canonical(facts)}
        return put(table,row)
    monkeypatch.setattr(investment_store,'_put',change)
    result=_investment(investment_store,b'wire mismatch '+wire_change.encode())
    assert result.status=='pending'
    assert investment_store.investment_component(result.doc_id)['snapshot_state']=='unavailable'
    assert investment_store.investment_postings(result.doc_id)==[]
    assert investment_store.verify()['verified']


@pytest.mark.parametrize('target',['position','cash','source_field','source_body','active_basis','effect_owner'])
def test_authentically_audited_wrong_native_meaning_is_independently_refused(investment_store,monkeypatch,target):
    from viva.sql_authority.store import IntegrityError,canonical
    import json
    put=investment_store._put
    changed=[]
    foreign_basis=None
    if target=='active_basis':
        first=_investment(investment_store,b'prior genuine basis for forgery control')
        foreign_basis=investment_store.investment_history(first.doc_id)['bases'][0]['basis_id']
    def corrupt(table,row):
        if not changed or target=='cash':
            if target=='position' and table=='investment_positions':
                row={**row,'units':'3'};changed.append(table)
            elif target=='cash' and table=='accounts' and row['kind']=='investment':
                row={**row,'current_amount':'999'};changed.append(table)
            elif target=='source_field' and table=='investment_fields' and row['name']=='units':
                row={**row,'value':'3'};changed.append(table)
            elif target=='source_body' and table=='investment_facts':
                body=json.loads(row['body']);body['positions'][0]['units']='3'
                row={**row,'body':canonical(body)};changed.append(table)
            elif target=='active_basis' and table=='investment_active':
                # A syntactically valid active row with a foreign basis cannot
                # become a financial proof merely by entering the sealed audit.
                row={**row,'basis_id':foreign_basis};changed.append(table)
            elif target=='effect_owner' and table=='investment_effects':
                row={**row,'owner_ordinal':1};changed.append(table)
        return put(table,row)
    monkeypatch.setattr(investment_store,'_put',corrupt)
    with pytest.raises((IntegrityError,ValueError)):
        kwargs={}
        if target=='active_basis':
            kwargs=dict(cash='11',total='31',opening='10',start='2026-02-01',end='2026-02-28',activity=[BrokerageActivity('2026-02-15','interest',D('1'))])
        elif target=='effect_owner':
            kwargs=dict(opening='8',activity=[BrokerageActivity('2026-01-15','interest',D('1')) for _ in range(2)])
        _investment(investment_store,b'audited semantic corruption '+target.encode(),**kwargs)
    assert changed


def test_native_financial_transaction_rolls_back_with_same_history(investment_store):
    store=investment_store
    first=_investment(store,b'original durable cash flow')
    head=store.head
    original_history=store.investment_history(first.doc_id)
    original_postings=store.investment_postings(first.doc_id)
    def fault(point):
        if point=='before_commit':raise RuntimeError('synthetic interruption before commit')
    store._fault=fault
    with pytest.raises(RuntimeError,match='synthetic interruption'):
        _investment(store,b'rolled back independent source')
    store._fault=lambda _point:None
    assert store.head==head
    assert store.investment_history(first.doc_id)==original_history
    assert store.investment_postings(first.doc_id)==original_postings
    assert store.verify()['verified']


@pytest.mark.parametrize('fmt,version,accepted',[
    ('viva-sql-authority-prototype-v3',3,True),('viva-sql-authority-prototype-v4',4,True),
    ('viva-sql-authority-prototype-v5',5,True),('viva-sql-authority-prototype-v5',True,False),
    ('viva-sql-authority-prototype-v5','5',False),('viva-sql-authority-prototype-v4',5,False),
    ('viva-sql-authority-prototype-v5',4,False),
])
def test_native_investment_keyed_genesis_pairs_have_real_sealed_negative_boundary(tmp_path,fmt,version,accepted):
    from viva.sql_authority import application_history as history
    from viva.sql_authority.store import IntegrityError
    root_id,operation_id=secrets.token_hex(32),secrets.token_hex(32)
    keyed=history.History(tmp_path,root_id,secrets.token_bytes(32))
    keyless=history.History(tmp_path,root_id)
    issued=dict(version=1,root_id=root_id,operation_id=operation_id,kind='creation',prior_terminal=None,
        prior_sql={'revision':0,'head':'0'*64},capture=None)
    sql_head={'revision':0,'head':'0'*64}
    body=dict(metadata_sha256='1'*64,sql_metadata_sha256='2'*64,sql_format=fmt,sql_schema_version=version,schema_contract='3'*64)
    if accepted:
        data=keyed.make(issued,'genesis',body,sql_head)
        record=keyed.record(data)
        assert keyless.record(data)==record
        assert keyed.payload(record,previous=None)['body']==body
    else:
        with pytest.raises(IntegrityError,match='invalid genesis representation'):
            keyed.make(issued,'genesis',body,sql_head)
        valid=keyed.make(issued,'genesis',{**body,'sql_format':'viva-sql-authority-prototype-v5','sql_schema_version':5},sql_head)
        record=keyed.record(valid)
        content={name:value for name,value in record.items() if name not in {'payload','record_hash','mac'}}
        content['payload']=history.canonical(history.seal(keyed.keys['payload'],history.encoded({'issued':issued,'body':body}),aad=history.aad(content)))
        content['record_hash']=history.digest(history.encoded(content))
        content['mac']=history.mac(keyed.keys['history'],[root_id,content['sequence'],content['record_hash']])
        malformed=history.encoded(content)
        structural=keyless.record(malformed)
        assert structural['record_hash']==content['record_hash']
        with pytest.raises(IntegrityError,match='invalid genesis representation'):keyed.record(malformed)
        with pytest.raises(IntegrityError,match='invalid genesis representation'):keyed.payload(structural,previous=None)


def test_latest_conflicting_valuation_refuses_without_erasing_previous_as_of(investment_store):
    from viva.sql_authority.store import AuthorityError,IntegrityError
    store=investment_store
    first=_investment(store,b'initial known valuation')
    next_period=_investment(store,b'next known valuation',cash='11',total='31',opening='10',start='2026-02-01',end='2026-02-28',activity=[BrokerageActivity('2026-02-15','interest',D('1'))])
    changed=_investment(store,b'conflicting same-date value population',cash='11',total='32',opening='10',start='2026-02-01',end='2026-02-28',positions=[PositionFact('SYNTH-SEC',D('2'),D('21'),D('18'),page=1)],activity=[BrokerageActivity('2026-02-15','interest',D('1'))])
    assert first.status==next_period.status==changed.status=='accepted'
    with pytest.raises(AuthorityError) as error:
        store.investment_snapshot(first.account_id,as_of='2026-02-28')
    assert type(error.value) is AuthorityError and not isinstance(error.value,IntegrityError)
    assert store.investment_snapshot(first.account_id,as_of='2026-01-31')['total']=='30'
    assert store.account(first.account_id)['running_balance']=='11'
    assert store.verify()['verified']


@pytest.mark.parametrize('optional',['units','cost_basis'])
def test_optional_copy_conflict_preserves_known_market_composition(investment_store,optional):
    first=_investment(investment_store,b'first optional-value witness')
    position=PositionFact('SYNTH-SEC',D('3') if optional=='units' else D('2'),D('20'),D('19') if optional=='cost_basis' else D('18'),page=1)
    copied=_investment(investment_store,b'contradictory optional '+optional.encode(),positions=[position])
    snapshot=investment_store.investment_snapshot(first.account_id,as_of='2026-01-31')
    assert snapshot['total']=='30' and snapshot['positions'][0]['market_value']=='20'
    assert snapshot['positions'][0]['field_statuses'][optional]=='conflicted'
    assert snapshot['positions'][0][optional] is None
    assert investment_store.investment_postings(copied.doc_id)==[]
    assert investment_store.verify()['verified']


@pytest.mark.parametrize('printed_cash,total,expected_cash,accepted',[
    ('10','30','10',True),('0','30','10',True),('5','30',None,False),
])
def test_sweep_uses_exact_two_readings_and_counts_cash_once(investment_store,printed_cash,total,expected_cash,accepted):
    result=_investment(investment_store,b'sweep reading '+printed_cash.encode(),cash=printed_cash,total=total,opening=None,activity=[],
        positions=[PositionFact('SYNTH-SEC',D('2'),D('20'),None,page=1),PositionFact('cash sweep',D('1'),D('10'),None,page=1)])
    assert (result.status=='accepted') is accepted
    if accepted:
        snapshot=investment_store.investment_snapshot(result.account_id,as_of='2026-01-31')
        assert snapshot['cash']==expected_cash
        assert [p['instrument'] for p in snapshot['positions']]==['SYNTH-SEC']
    else:
        assert investment_store.investment_component(result.doc_id)['reason']=='snapshot_arithmetic'
    assert investment_store.verify()['verified']


def test_native_history_reopens_with_exact_expected_head_and_source(tmp_path):
    path=tmp_path.resolve()/'reopen-native-investment'
    passphrase=secrets.token_urlsafe(48)
    with SQLAuthority.create(path,passphrase,verification='complete') as store:
        result=_investment(store,b'durable synthetic native investment')
        head=store.head
        snapshot=store.investment_snapshot(result.account_id,as_of='2026-01-31')
        history=store.investment_history(result.doc_id)
        postings=store.investment_postings(result.doc_id)
    with SQLAuthority.open(path,passphrase,verification='complete') as reopened:
        assert reopened.verify(expected_head=head)['verified']
        assert reopened.investment_snapshot(result.account_id,as_of='2026-01-31')==snapshot
        assert reopened.investment_history(result.doc_id)==history
        assert reopened.investment_postings(result.doc_id)==postings
        assert reopened.original(result.doc_id)==b'durable synthetic native investment'


@pytest.fixture(scope='module')
def investment_curated_source():
    from viva.sql_authority import CuratedSource
    return CuratedSource.open()


def test_genuine_curated_activity_keeps_signed_original_cells_and_source_associations(investment_store,investment_curated_source):
    source=investment_curated_source
    document=next(d for d in source.documents if d['doc_type']=='brokerage_statement')
    result=investment_store.ingest_curated(source.original(document['sha256']),source)
    assert result.status=='accepted'
    receipt=investment_store.receipt(result.doc_id)
    source_wire=receipt['facts']['investment_source']
    assert source_wire['schema'] in {'investment-source-v1','investment-source-v2'}
    occurrences=investment_store.source_occurrences(result.doc_id)
    activity=investment_store.investment_activity(result.doc_id)
    assert len(occurrences)==len(activity)>0
    assert all(o['date']==a['date'] and o['event_id']==a['source_event_id'] for o,a in zip(occurrences,activity))
    assert any(o['raw'].startswith('-') for o in occurrences)
    assert all(D(a['amount'])>0 for a in activity)
    assert all(f['grade']!='verified' for f in investment_store.investment_component(result.doc_id)['fields'])
    assert investment_store.original(result.doc_id)==source.original(document['sha256'])
    assert investment_store.verify()['verified']


@pytest.mark.parametrize('missing',['activity_cell','event_id'])
def test_curated_activity_omission_is_refused(tmp_path,investment_curated_source,monkeypatch,missing):
    from viva.sample import curation
    from viva.sql_authority import curated
    from viva.sql_authority.investment_schema import TABLES as native_tables
    from viva.sql_authority.store import AuthorityError,IntegrityError,_encode
    import copy
    source=investment_curated_source
    document=next(d for d in source.documents if d['doc_type']=='brokerage_statement')
    original=source.original(document['sha256'])
    doc_id=hashlib.sha256(original).hexdigest()
    assert doc_id==document['sha256']
    expected_reading,expected_admission=curated.issue(source,original,doc_id)
    decode_envelope=curation.decode_envelope
    interpret_curated=curated.interpret_curated
    reason=('investment activity source cell multiplicity differs' if missing=='activity_cell'
            else 'investment source event multiplicity differs')
    def omit(text,doc_type):
        envelope=copy.deepcopy(decode_envelope(text,doc_type))
        if doc_type=='brokerage_statement':
            if missing=='activity_cell':
                envelope['source_cells']=[c for c in envelope['source_cells'] if c['field']!='/activity/0/amount_raw']
            else:
                envelope['source_event_ids']=envelope['source_event_ids'][1:]
        return envelope
    def retained_refusal(store,state):
        assert store.verify()['verified']
        assert store._row('documents','doc_id=?',(doc_id,))==dict(doc_id=doc_id,byte_count=len(original),contract=curation.CONTRACT)
        assert store.item(doc_id)['state']==state
        receipt=store.receipt(doc_id)
        assert receipt['contract']==curation.CONTRACT
        assert receipt['raw_reading']==_encode(expected_reading)
        admission=store.source_admission(doc_id)
        assert {k:v for k,v in admission.items() if k!='read_context_id'}==expected_admission
        assert store._row('read_contexts','context_id=?',(admission['read_context_id'],)) is not None
        assert store.investment_component(doc_id)['snapshot_state']=='unavailable'
        assert store.investment_postings(doc_id)==[]
        assert store.original(doc_id)==source.original(document['sha256'])==original
        assert all(store._read('SELECT count(*) FROM '+table)==[(0,)] for table in native_tables)
        interpretation=store._row('interpretations','doc_id=?',(doc_id,))
        if state=='staged':
            assert interpretation is None and receipt['facts_type']=='curated'
        else:
            assert state=='pending' and interpretation['facts_type']=='source_rejected'
            assert receipt['facts_type']=='source_rejected'
            assert store.item(doc_id)['reason']=='source_admission_requires_review'
        assert store.verify()['verified']
        return receipt,admission
    root_a=tmp_path.resolve()/('global-omission-'+missing)
    passphrase_a=secrets.token_urlsafe(48)
    with SQLAuthority.create(root_a,passphrase_a,verification='complete') as store:
        with monkeypatch.context() as patch:
            patch.setattr(curation,'decode_envelope',omit)
            with pytest.raises(IntegrityError,match='^source admission cannot be independently authenticated$') as caught:
                store.ingest_curated(original,source)
            assert type(caught.value.__cause__) is AuthorityError
            assert str(caught.value.__cause__)==reason
        assert curation.decode_envelope is decode_envelope
        receipt_a,admission_a=retained_refusal(store,'staged');head_a=store.head
    with SQLAuthority.open(root_a,passphrase_a,verification='complete',curated_source=source) as reopened:
        assert reopened.verify(expected_head=head_a)['verified']
        assert retained_refusal(reopened,'staged')==(receipt_a,admission_a)
    root_b=tmp_path.resolve()/('writer-omission-'+missing)
    passphrase_b=secrets.token_urlsafe(48)
    entries=[];refusals=[]
    def writer_interpret(owner,receipt,reading):
        entries.append(receipt['doc_id'])
        with monkeypatch.context() as patch:
            patch.setattr(curation,'decode_envelope',omit)
            try:
                return interpret_curated(owner,receipt,reading)
            except AuthorityError as error:
                assert str(error)==reason
                refusals.append(str(error))
                raise
    with SQLAuthority.create(root_b,passphrase_b,verification='complete') as store:
        with monkeypatch.context() as patch:
            patch.setattr(curated,'interpret_curated',writer_interpret)
            result=store.ingest_curated(source.original(document['sha256']),source)
        assert entries==[doc_id] and refusals==[reason]
        assert curated.interpret_curated is interpret_curated and curation.decode_envelope is decode_envelope
        assert result.status=='pending'
        assert store.investment_component(result.doc_id)['snapshot_state']=='unavailable'
        assert store.investment_postings(result.doc_id)==[]
        assert store.original(result.doc_id)==source.original(document['sha256'])
        receipt_b,admission_b=retained_refusal(store,'pending');head_b=store.head
    with SQLAuthority.open(root_b,passphrase_b,verification='complete',curated_source=source) as reopened:
        assert reopened.verify(expected_head=head_b)['verified']
        assert retained_refusal(reopened,'pending')==(receipt_b,admission_b)


def test_native_source_reference_decision_proves_actual_registration_frontier(investment_store):
    import json
    from viva.crypto import open_sealed
    from viva.sql_authority.store import canonical
    result=_investment(investment_store,b'numberless genuine source account',account_number='')
    assert result.status=='accepted'
    decision=investment_store.identity_decision(result.doc_id)
    assert decision['policy']=='investment_source_reference'
    assert decision['resolution']['verdict']=='new' and decision['promoted'] is True
    revision=investment_store._row('investment_facts','doc_id=?',(result.doc_id,))['created_revision']
    record=next(r for r in investment_store.export_audit()['records'] if r[0]==revision)
    operations=json.loads(open_sealed(investment_store._audit_key,json.loads(record[2]),aad=canonical([record[0],record[1]]).encode()))['operations']
    first=next(i for i,op in enumerate(operations) if op['table']=='accounts' and op['row']['account_id']==result.account_id)
    decision_index=next(i for i,op in enumerate(operations) if op['table']=='identity_decisions' and op['row']['doc_id']==result.doc_id)
    assert decision['known_operation']==first<decision_index
    assert [op['table'] for op in operations[first:decision_index]]==['accounts','account_keys','holder_index']
    copied=_investment(investment_store,b'numberless later same source',account_number='')
    same=investment_store.identity_decision(copied.doc_id)
    assert copied.account_id==result.account_id and same['resolution']['verdict']=='same'
    assert investment_store.verify()['verified']


@pytest.mark.parametrize('forgery',['frontier','mapping','interleaved_suffix'])
def test_native_resolver_cannot_use_favorable_frontier_or_registration_suffix(investment_store,monkeypatch,forgery):
    import json
    from viva.sql_authority.store import canonical,IntegrityError
    from viva.sql_authority import identity as identity_module
    changed=[]
    if forgery=='interleaved_suffix':
        mapped=identity_module.map_account
        def interleave(store,account,facts):
            store._item(facts.doc_id,'pending','synthetic unrelated interleaving')
            changed.append(True)
            return mapped(store,account,facts)
        monkeypatch.setattr(identity_module,'map_account',interleave)
    else:
        put=investment_store._put
        def alter(table,row):
            if table=='identity_decisions':
                body=json.loads(row['body'])
                if body['policy']=='investment_source_reference':
                    if forgery=='frontier':body['known_operation']+=1
                    else:body['logical_to_physical']={'forged':'acct:sql:foreign'}
                    row={**row,'body':canonical(body)};changed.append(True)
            return put(table,row)
        monkeypatch.setattr(investment_store,'_put',alter)
    with pytest.raises(IntegrityError,match='investment semantic mismatch'):
        _investment(investment_store,b'numberless '+forgery.encode(),account_number='')
    assert changed


def test_native_fact_creation_revision_is_immutable_across_pending_resume(investment_store):
    result=_investment(investment_store,b'immutable invalid tally',total='31')
    assert result.status=='pending'
    facts=investment_store._row('investment_facts','doc_id=?',(result.doc_id,))
    assert facts['created_revision']<=result.revision
    investment_store.resume(result.doc_id)
    assert investment_store._row('investment_facts','doc_id=?',(result.doc_id,))==facts
    assert investment_store.verify()['verified']


def test_missing_native_facts_cannot_be_recreated_with_a_resume_revision(investment_store):
    from viva.sql_authority import investment as module
    from viva.sql_authority.store import IntegrityError
    result=_investment(investment_store,b'actual immutable captured facts')
    interpretation=investment_store._row('interpretations','doc_id=?',(result.doc_id,))
    original_row=investment_store._row
    def missing(table,where,parameters):
        return None if table=='investment_facts' else original_row(table,where,parameters)
    # This fault is confined to intake's native-row lookup after the original
    # source has been genuinely admitted. It cannot manufacture a first input
    # operation in this unrelated writer.
    with investment_store._transaction():
        investment_store._row=missing
        try:
            with pytest.raises(IntegrityError,match='actual first interpretation'):
                module.intake(investment_store,interpretation)
        finally:
            investment_store._row=original_row
    assert investment_store.verify()['verified']


def test_forced_second_physical_registration_rolls_back_whole_native_writer(investment_store,monkeypatch):
    from dataclasses import replace
    from viva.sql_authority import investment as module
    from viva.sql_authority.store import IntegrityError
    bank=ingest(investment_store,b'independent committed bank before forced registration')
    assert bank.status=='accepted'
    bank_head=investment_store.head
    bank_postings=investment_store.postings(bank.doc_id)
    bind=module._bind
    injected=[]
    captured_frontier=[]
    def force_second(store,facts):
        if not captured_frontier:
            captured_frontier.append(store.head)
        account=bind(store,facts)
        if account is not None and not injected:
            injected.append(True)
            bind(store,replace(facts,account_number='876543210'))
        return account
    monkeypatch.setattr(module,'_bind',force_second)
    with pytest.raises(IntegrityError,match='second physical account'):
        _investment(investment_store,b'forced second native registration')
    assert injected
    assert investment_store.postings(bank.doc_id)==bank_postings
    assert investment_store.head==captured_frontier[0]
    assert investment_store.head['revision']>=bank_head['revision']
    assert investment_store._read("SELECT account_id FROM accounts WHERE kind='investment'")==[]
    assert investment_store._read('SELECT doc_id FROM investment_facts')==[]
    assert investment_store.verify()['verified']


def test_new_investment_engine_refuses_old_v2_before_connect_with_unchanged_files(tmp_path,monkeypatch):
    from viva.sql_authority import application,application_history as history
    from viva.sql_authority.store import IntegrityError
    passphrase=secrets.token_urlsafe(48)
    with SQLAuthority.create(tmp_path.resolve()/'fresh-v3-engine',passphrase,verification='complete',application=True) as owner:
        with owner._root_lock.hold():
            path=owner.root/'sql'/'authority.json'
            metadata=history.decode(path.read_bytes())
            assert metadata['format']=='viva-sql-application-engine-v3'
            metadata['format']='viva-sql-application-engine-v2'
            path.write_bytes(history.encoded(metadata))
            before={p.relative_to(owner.root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in owner.root.rglob('*') if p.is_file()}
            monkeypatch.setattr(application,'_connect',lambda *_a,**_kw:pytest.fail('old engine connected'))
            with pytest.raises(IntegrityError,match='application child identity differs'):
                owner._open_engine(passphrase)
            assert before=={p.relative_to(owner.root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in owner.root.rglob('*') if p.is_file()}


def test_first_printed_zero_opening_is_a_genuine_seed(investment_store):
    result=_investment(investment_store,b'genuine first zero opening',cash='1',total='21',opening='0')
    assert result.status=='accepted'
    period=investment_store.investment_cash_period(result.doc_id)
    assert (period['opening_cash'],period['closing_cash'],period['state'])==('0','1','accepted')
    assert len(investment_store.investment_postings(result.doc_id))==2
    assert investment_store.verify()['verified']


def test_seeded_explicit_empty_period_retains_no_money_and_does_not_invent_rows(investment_store):
    first=_investment(investment_store,b'prior genuine seed for empty period')
    def empty(source):source['headers']['no_activity']={'raw':'true','page':1}
    result=_investment(investment_store,b'explicit seeded no-activity period',opening='10',start='2026-02-01',end='2026-02-28',activity=[],mutate_source=empty)
    assert result.account_id==first.account_id
    assert investment_store.investment_cash_period(result.doc_id)['state']=='accepted'
    assert investment_store.investment_activity(result.doc_id)==[]
    assert investment_store.investment_postings(result.doc_id)==[]
    assert investment_store.verify()['verified']


def test_missing_activity_is_not_a_whole_cash_copy_or_an_empty_assertion(investment_store):
    first=_investment(investment_store,b'actual original cash activity')
    incomplete=_investment(investment_store,b'copy missing its activity population',activity=[])
    component=investment_store.investment_component(incomplete.doc_id)
    assert incomplete.status=='accepted' and component['snapshot_state']=='accepted'
    assert component['activity_state']=='unavailable' and component['reason']=='empty_activity_unproved'
    assert investment_store.investment_history(incomplete.doc_id)['witnesses']==[]
    assert investment_store.investment_postings(incomplete.doc_id)==[]
    assert len(investment_store.investment_postings(first.doc_id))==2
    assert investment_store.verify()['verified']


def test_constructor_resource_hold_does_not_erase_an_independent_complete_population(investment_store):
    result=_investment(investment_store,b'resource held gain split',activity=[BrokerageActivity('2026-01-15','sell',D('1'),realized_gain=D('1E-20000'))])
    component=investment_store.investment_component(result.doc_id)
    assert result.status=='accepted' and component['snapshot_state']=='accepted'
    assert component['activity_state']=='held' and component['reason']=='resource_limit'
    assert investment_store.investment_snapshot(result.account_id,as_of='2026-01-31')['total']=='30'
    assert investment_store.investment_postings(result.doc_id)==[]
    assert investment_store.verify()['verified']


def test_multiple_pending_sources_bind_same_writer_account_without_second_creation(investment_store):
    store=investment_store
    numbered=_investment(store,b'numbered holder rival',account_names=['Synthetic Holder One'])
    assert numbered.status=='accepted'
    pending=[]
    creation=[]
    for label in (b'first pending source',b'second pending source'):
        result=_investment(store,label,account_number='',account_names=['Synthetic Holder One'])
        assert result.status=='pending'
        assert store.identity_decision(result.doc_id)['resolution']['verdict']=='ambiguous'
        pending.append(result)
        creation.append(store._row('investment_facts','doc_id=?',(result.doc_id,))['created_revision'])
    # A source with no asserted holder does not supply a false holder match.
    # Its own eligible exact reference can establish the separate numberless
    # account, and the earlier genuinely pending captures can then bind to it.
    registered=_investment(store,b'new exact reference with unavailable holder',account_number='',account_names=[])
    assert registered.status=='accepted'
    assert registered.account_id!=numbered.account_id
    for prior,created in zip(pending,creation):
        item=store.item(prior.doc_id)
        decision=store.identity_decision(prior.doc_id)
        assert item['state']=='accepted' and item['account_id']==registered.account_id
        assert decision['resolution']['verdict']=='same' and decision['promoted'] is True
        assert store._row('investment_facts','doc_id=?',(prior.doc_id,))['created_revision']==created
    mapped=store._read('SELECT account_id,creation_order FROM account_keys ORDER BY creation_order')
    assert len(mapped)==2 and len({revision for _physical,revision in mapped})==2
    assert len(store.investment_postings(registered.doc_id))==2
    assert all(store.investment_postings(prior.doc_id)==[] for prior in pending)
    assert store.verify()['verified']


@pytest.mark.parametrize('defect,reason,state', [
    ('wrong_opening','source_activity_conflict','conflicted'),
    ('missing_opening','empty_activity_unproved','unavailable'),
    ('missing_closing','empty_activity_unproved','unavailable'),
    ('unreadable_opening','empty_activity_unproved','unavailable'),
    ('false_assertion','empty_activity_unproved','unavailable'),
    ('missing_assertion','empty_activity_unproved','unavailable'),
])
def test_empty_source_evidence_cannot_compete_with_genuine_money(investment_store,defect,reason,state):
    store=investment_store
    first=_investment(store,b'genuine seed before empty source negatives')
    genuine=_investment(store,b'genuine same-end nonempty period',opening='10',cash='10',total='30',
        start='2026-02-01',end='2026-02-28',activity=[
            BrokerageActivity('2026-02-10','interest',D('1')),
            BrokerageActivity('2026-02-11','fee',D('1'))])
    assert first.status==genuine.status=='accepted'
    money=store.investment_postings(genuine.doc_id)
    history=store.investment_history(genuine.doc_id)
    assert len(money)==4 and history['decisions'][-1]['action']=='activate'
    def source(wire):
        headers=wire['headers'];headers['no_activity']={'raw':'true','page':1}
        if defect=='wrong_opening':headers['opening_cash']={'raw':'20','page':1}
        elif defect=='missing_opening':headers['opening_cash']=None
        elif defect=='missing_closing':headers['closing_cash']=None
        elif defect=='unreadable_opening':headers['opening_cash']={'raw':'unreadable','page':1}
        elif defect=='false_assertion':headers['no_activity']={'raw':'false','page':1}
        elif defect=='missing_assertion':headers['no_activity']=None
    invalid=_investment(store,b'invalid empty source '+defect.encode(),opening='10',cash='10',total='30',
        start='2026-02-01',end='2026-02-28',activity=[],mutate_source=source)
    component=store.investment_component(invalid.doc_id)
    assert component['snapshot_state']=='accepted'
    assert (component['activity_state'],component['reason'])==(state,reason)
    assert store.investment_snapshot(invalid.account_id,as_of='2026-02-28')['total']=='30'
    invalid_history=store.investment_history(invalid.doc_id)
    assert invalid_history['bases']==invalid_history['witnesses']==invalid_history['effects']==invalid_history['decisions']==[]
    assert store.investment_postings(invalid.doc_id)==[]
    assert store.investment_history(genuine.doc_id)==history
    assert store.investment_postings(genuine.doc_id)==money
    assert store._read('SELECT count(*) FROM investment_groups WHERE account_id=? AND period_end=?',(genuine.account_id,'2026-02-28'))==[(1,)]
    assert store.verify()['verified']


def test_empty_carried_basis_requires_its_own_accepted_source_opening(investment_store):
    store=investment_store
    seed=_investment(store,b'printed seed before source backed empty carry')
    def source(wire):
        wire['headers']['opening_cash']={'raw':'10.000','page':1}
        wire['headers']['no_activity']={'raw':'true','page':1}
    child=_investment(store,b'genuine source backed empty carry',opening=None,cash='10',total='30',
        start='2026-02-01',end='2026-02-28',activity=[],mutate_source=source)
    history=store.investment_history(child.doc_id)
    assert child.status=='accepted' and store.investment_component(child.doc_id)['activity_state']=='accepted'
    assert history['bases'][0]['opening_kind']=='carried' and history['bases'][0]['opening']=='10'
    assert history['bases'][0]['predecessor_snapshot']==store.investment_component(seed.doc_id)['snapshot_id']
    assert history['bases'][0]['seed_group']==store.investment_component(seed.doc_id)['group_id']
    field=store._row('investment_fields','doc_id=? AND scope=? AND name=?',(child.doc_id,'header','opening_cash'))
    assert field['status']=='accepted' and field['grade']=='unverified' and field['raw']=='10.000'
    assert history['effects']==store.investment_postings(child.doc_id)==[]
    assert history['decisions'][0]['action']=='activate' and store.verify()['verified']


def test_empty_source_opening_cannot_disagree_with_selected_carried_basis(investment_store):
    store=investment_store
    first=_investment(store,b'genuine seed before contrary carried empty')
    def source(wire):
        wire['headers']['opening_cash']={'raw':'8','page':1}
        wire['headers']['no_activity']={'raw':'true','page':1}
    invalid=_investment(store,b'contrary actual source empty carry',opening=None,cash='10',total='30',
        start='2026-02-01',end='2026-02-28',activity=[],mutate_source=source)
    component=store.investment_component(invalid.doc_id)
    assert (component['snapshot_state'],component['activity_state'],component['reason'])==('accepted','conflicted','source_activity_conflict')
    assert store.investment_history(invalid.doc_id)['bases']==[]
    assert len(store.investment_postings(first.doc_id))==2 and store.verify()['verified']


def test_empty_source_closing_cannot_be_replaced_by_separate_sweep_cash(investment_store):
    store=investment_store
    _investment(store,b'root before empty sweep source discrepancy')
    def source(wire):wire['headers']['no_activity']={'raw':'true','page':1}
    # Typed cash and source closing agree at9. Sweep is genuinely separate in
    # total30, so the normalized cash is10. It cannot silently replace source9.
    result=_investment(store,b'empty separate sweep source discrepancy',opening='10',cash='9',total='30',
        start='2026-02-01',end='2026-02-28',activity=[],mutate_source=source,
        positions=[PositionFact('SYNTH-SEC',D('2'),D('20'),D('18'),page=1),
                   PositionFact('Cash Sweep',D('1'),D('1'),None,page=1)])
    component=store.investment_component(result.doc_id)
    assert (component['snapshot_state'],component['activity_state'],component['reason'])==('accepted','conflicted','source_activity_conflict')
    assert store.investment_history(result.doc_id)['witnesses']==[] and store.verify()['verified']


def _native_resealed_proof(store,exported,mutate):
    """Use real audit keys/grammar; call the mandatory independent prefix proof."""
    from test_sql_authority_integrity import _resealed_export
    from viva.sql_authority.investment_verify import verify
    changed=_resealed_export(store,exported,mutate)
    head={'revision':changed['revision'],'head':changed['head']}
    assert store.check_export_structure(changed,expected_head=head)['structural']
    state=store._reconstruct(changed,head)
    return changed,state,lambda:verify(store,state,changed)


def _native_basis_digest(basis):
    from viva.sql_authority.investment_numbers import key,scalar
    from viva.sql_authority.store import canonical
    values=['sql-investment-basis-v1',basis['doc_id'],key(scalar(basis['opening'])),basis['opening_kind'],basis['period_start'],basis['start_kind'],basis['seed_group'],basis['predecessor_snapshot'],basis['prior_basis'],basis['created_revision'],basis['known_operation'],basis['source_header_digest']]
    return hashlib.sha256(canonical(values).encode()).hexdigest()


@pytest.mark.parametrize('defect',['wrong_opening','missing_opening','missing_closing'])
def test_resealed_empty_group_requires_actual_source_evidence(investment_store,defect):
    import json
    from viva.sql_authority.store import IntegrityError,canonical
    store=investment_store
    _investment(store,b'seed before authenticated empty mutation')
    def source(wire):wire['headers']['no_activity']={'raw':'true','page':1}
    child=_investment(store,b'positive source associated empty group',opening='10',cash='10',total='30',
        start='2026-02-01',end='2026-02-28',activity=[],mutate_source=source)
    history=store.investment_history(child.doc_id);assert len(history['bases'])==len(history['witnesses'])==1
    assert store.investment_component(child.doc_id)['activity_state']=='accepted'
    original=store.export_audit()
    _,_,positive=_native_resealed_proof(store,original,lambda _payload:None);positive()
    basis=history['bases'][0];replacement=dict(basis)
    source_body=json.loads(store._row('investment_facts','doc_id=?',(child.doc_id,))['body'])
    headers=source_body['investment_source']['headers']
    headers['opening_cash']={'raw':'20','page':1} if defect=='wrong_opening' else headers['opening_cash']
    if defect=='missing_opening':headers['opening_cash']=None
    if defect=='missing_closing':headers['closing_cash']=None
    replacement['source_header_digest']=hashlib.sha256(canonical(headers).encode()).hexdigest()
    replacement['basis_id']=_native_basis_digest(replacement)
    def mutation(payload):
        for op in payload['operations']:
            row=op['row'];table=op['table']
            if table=='receipts' and row['doc_id']==child.doc_id:
                row['facts']=canonical(source_body);body=json.loads(row['body']);body['facts']=source_body;row['body']=canonical(body)
            elif table=='interpretations' and row['doc_id']==child.doc_id:row['facts']=canonical(source_body)
            elif table=='investment_facts' and row['doc_id']==child.doc_id:row['body']=canonical(source_body)
            if table=='investment_bases' and row['basis_id']==basis['basis_id']:row.update(replacement)
            elif row.get('basis_id')==basis['basis_id']:row['basis_id']=replacement['basis_id']
    changed,state,negative=_native_resealed_proof(store,original,mutation)
    assert state['investment_bases'][(replacement['basis_id'],)]['doc_id']==child.doc_id
    assert all((w['basis_id'],) in state['investment_bases'] for w in state['investment_witnesses'].values())
    assert changed['head']!=original['head']
    with pytest.raises(IntegrityError,match='empty basis lacks accepted compatible source opening/closing'):
        negative()
    assert store.verify()['verified']


def _genuine_native_rebind(store):
    a=_investment(store,b'A January printed root',opening='9',cash='10',total='30')
    child=_investment(store,b'February cash child of A',opening=None,cash='11',total='31',start='2026-02-01',end='2026-02-28',
        activity=[BrokerageActivity('2026-02-15','interest',D('1'))])
    before=store.investment_history(child.doc_id)
    assert len(before['bases'])==1 and before['decisions'][-1]['action']=='activate'
    b=_investment(store,b'B late December alternate printed root',opening='7',cash='8',total='28',start='2025-12-01',end='2025-12-31',
        activity=[BrokerageActivity('2025-12-15','interest',D('1'))])
    assert store.investment_history(child.doc_id)==before
    d=_investment(store,b'D contrary January start different end',opening='8',cash='10',total='30',start='2026-01-01',end='2026-01-15',
        activity=[BrokerageActivity('2026-01-10','interest',D('2'))])
    assert all(r.status=='accepted' for r in (a,child,b,d))
    after=store.investment_history(child.doc_id)
    assert len(after['bases'])==2 and [v['action'] for v in after['decisions']]==['activate','rebind']
    return a,child,b,d,before,after


def test_actual_native_rebind_keeps_cash_and_immutable_prior_history(tmp_path):
    root=tmp_path.resolve()/'genuine-rebind';passphrase=secrets.token_urlsafe(48)
    with SQLAuthority.create(root,passphrase,verification='complete') as store:
        a,child,b,d,before,after=_genuine_native_rebind(store)
        old,new=after['bases'];decision=after['decisions'][-1]
        assert new['prior_basis']==old['basis_id'] and old['prior_basis'] is None
        assert old['seed_group']==store.investment_component(a.doc_id)['group_id']
        assert new['seed_group']==store.investment_component(b.doc_id)['group_id']
        unchanged={'doc_id','opening','opening_kind','period_start','start_kind','predecessor_snapshot','source_header_digest'}
        assert all(old[k]==new[k] for k in unchanged)
        assert old['predecessor_snapshot']==store.investment_component(a.doc_id)['snapshot_id']
        assert old['opening']=='10' and old['opening_kind']=='carried'
        assert before['bases'][0] in after['bases'] and all(w in after['witnesses'] for w in before['witnesses'])
        assert before['decisions'][0] in after['decisions'] and after['effects']==before['effects']
        assert after['postings']==before['postings'] and len(after['postings'])==2
        assert decision['previous_ordinal']==before['decisions'][-1]['ordinal']
        active=store._row('investment_active','group_id=?',(store.investment_component(child.doc_id)['group_id'],))
        assert active['basis_id']==new['basis_id'] and active['decision_ordinal']==decision['ordinal'] and active['active']==1
        assert store._read('SELECT count(*) FROM investment_adjustments WHERE decision_ordinal=?',(decision['ordinal'],))==[(0,)]
        assert store.investment_history(a.doc_id)['decisions'][-1]['action']=='deactivate'
        reversals=store._read('SELECT effect_id,doc_id FROM investment_adjustments WHERE decision_ordinal IN (SELECT ordinal FROM investment_decisions WHERE action=?)',('deactivate',))
        assert reversals and all(doc==a.doc_id for _effect,doc in reversals)
        assert store.verify()['verified'];head=store.head
    with SQLAuthority.open(root,passphrase,verification='complete') as reopened:
        assert reopened.verify(expected_head=head)['verified']
        assert reopened.investment_history(child.doc_id)==after and reopened.verify()['verified']


@pytest.mark.parametrize('defect',['opening','predecessor','owner','changed_decision','omitted_decision','journal_money'])
def test_resealed_native_rebind_cannot_change_economics_or_history(investment_store,defect):
    import json
    from viva.sql_authority.store import IntegrityError
    store=investment_store
    a,child,b,d,before,after=_genuine_native_rebind(store)
    original=store.export_audit()
    _,_,positive=_native_resealed_proof(store,original,lambda _payload:None);positive()
    old,new=after['bases'];decision=after['decisions'][-1];replacement=dict(new)
    if defect=='opening':replacement['opening']='8'
    elif defect=='predecessor':replacement['predecessor_snapshot']=store.investment_component(b.doc_id)['snapshot_id']
    elif defect=='owner':
        replacement['doc_id']=b.doc_id
        replacement['source_header_digest']=store.investment_history(b.doc_id)['bases'][0]['source_header_digest']
    replacement['basis_id']=_native_basis_digest(replacement)
    changed_rows=[]
    def mutation(payload):
        ops=payload['operations']
        for op in ops:
            row=op['row'];table=op['table']
            if defect in {'opening','predecessor','owner'}:
                if table=='investment_bases' and row['basis_id']==new['basis_id']:row.update(replacement);changed_rows.append(table)
                elif row.get('basis_id')==new['basis_id']:row['basis_id']=replacement['basis_id']
            if table=='investment_decisions' and row['ordinal']==decision['ordinal'] and defect=='changed_decision':
                row['action']='activate';changed_rows.append(table)
        if defect=='omitted_decision':
            retained=[]
            for op in ops:
                row=op['row'];table=op['table']
                if (table=='investment_decisions' and row['ordinal']==decision['ordinal'] or table=='investment_active' and row['decision_ordinal']==decision['ordinal']):
                    changed_rows.append(table);continue
                if table=='investment_decisions':
                    if row['ordinal']>decision['ordinal']:row['ordinal']-=1
                    if row['previous_ordinal'] is not None and row['previous_ordinal']>decision['ordinal']:row['previous_ordinal']-=1
                elif table in {'investment_active','investment_adjustments'} and row['decision_ordinal']>decision['ordinal']:row['decision_ordinal']-=1
                retained.append(op)
            payload['operations']=retained
        if defect=='journal_money' and any(op['table']=='investment_decisions' and op['row']['ordinal']==decision['ordinal'] for op in ops):
            effect=after['effects'][0]
            legs=store._read('SELECT leg FROM investment_legs WHERE effect_id=? ORDER BY leg',(effect['effect_id'],))
            assert len(legs)==2
            for (ordinal,) in legs:
                leg=store._row('investment_legs','effect_id=? AND leg=?',(effect['effect_id'],ordinal))
                payload['operations'].append({'table':'investment_adjustments','row':dict(leg,decision_ordinal=decision['ordinal'],date=effect['date'])})
            changed_rows.append('investment_adjustments')
    changed,state,negative=_native_resealed_proof(store,original,mutation)
    assert changed_rows and changed['head']!=original['head']
    assert all((w['basis_id'],) in state['investment_bases'] and (w['group_id'],) in state['investment_groups'] and (w['doc_id'],) in state['investment_facts'] for w in state['investment_witnesses'].values())
    if defect in {'opening','predecessor','owner'}:
        expected='rebind changed economic opening or replaced a usable basis'
    elif defect=='changed_decision':expected='activation/reversal/rebind eligibility or prior basis differs'
    elif defect=='omitted_decision':expected='required basis rebind omitted'
    else:expected='immutable effect multiplicity/current pointers/signed history differs'
    with pytest.raises(IntegrityError,match=expected):negative()
    assert store.verify()['verified']
