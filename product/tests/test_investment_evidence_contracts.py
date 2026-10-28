from dataclasses import replace
from decimal import Decimal,localcontext
from time import monotonic
from pathlib import Path
import pytest
from viva.ledger.ledger import Ledger
from viva.ledger.events import account_opened,Provenance,Event,position_observed
from viva.ledger.postings import brokerage_activity_transaction,simple_transaction
from viva.investment.contracts import *
from viva.investment.events import *
from viva.investment.authority import read
from viva.investment.units import *

ACCOUNT='Assets:BrokerTest';BANK='Assets:BankTest'
def f(value,doc='source',page=2,**kwargs):return Field(str(value),doc,page,**kwargs)
def fixture(account=ACCOUNT,doc='source',sid='statement',start='2025-01-01',end='2025-12-31',funding=True,gain='-5',rows=True):
 events=[account_opened(account,'investment','Test broker','USD',start),account_opened(BANK,'depository','Test bank','USD',start)]
 rowitems=[]
 for index,(kind,amount,rg) in enumerate([('contribution','100',None),('dividend','3',None),('sell','30',gain)] if rows else []):
  date=end;description=kind+' source row'
  cash=brokerage_activity_transaction(account,kind,amount,description,date,instrument='TEST-SEC' if kind=='sell' else '',realized_gain=rg,provenance=Provenance(doc_id=doc,page=2))
  events.append(cash)
  extra={}
  if kind=='contribution':
   transfer=simple_transaction(BANK,'-100','source funding',date,provenance=Provenance(doc_id='fund-source',page=1),source_reference='PRINTED-X')
   events.append(transfer)
   if funding:extra={'funding_status':'accepted','funding_role':'own_bank','funding_role_source':f('own_bank',doc),'funding_reference':f('PRINTED-X',doc),'counterpart_reference':f('BANK-REF',doc),'funding_witness':FundingWitness(f('PRINTED-X','fund-source',1),f('BANK-REF','fund-source',1),BANK,'own_bank',transfer.event_id,digest(transfer.body))}
  rowitems.append(Row(sid+'-row'+str(index),str(index),index,f(date,doc),f(kind,doc),f(amount,doc),f('TEST-SEC',doc) if kind=='sell' else None,f(rg,doc) if rg is not None else None,cash.event_id,digest(cash.body),description,**extra))
 observed=position_observed(account,'TEST-SEC','1.25','25','USD',end,cost_basis='20',provenance=Provenance(doc_id=doc,page=2))
 events.append(observed)
 positions=(Position(security_identity(account,'TEST-SEC'),f('TEST-SEC',doc),f('1.25',doc),f('25',doc),f('20',doc),position_event_id=observed.event_id,position_body_digest=digest(observed.body)),)
 s=Statement(sid,f(account,doc),f('USD',doc),f(start,doc),f(end,doc),f('0',doc),f('133' if rows else '0',doc),tuple(rowitems),'accepted_complete_nonempty' if rows else 'accepted_complete_empty',explicit_empty=None if rows else f('true',doc),positions=positions,snapshot_complete=True)
 return events,s

def resolve(field):return BANK if field.value=='BANK-REF' else None

def test_units_and_basis_distinct_complete_receipts():
 _,s=fixture();r=read((s,),Request('positions',ACCOUNT,'USD',as_of='2025-12-31'))
 assert [(x['quantity'],x['value']) for x in r['figures']]==[('security_units','1.25'),('balance','25'),('holding_cost_basis','20'),('count','1')]
 assert r['figures'][0]['security'] and all(x['as_of']=='2025-12-31' for x in r['figures'])
 assert all(x['anchor_ids'] for x in r['figures'])

def test_activity_loss_and_derived_basis_with_both_operands():
 events,s=fixture();validate_statement(s,events,resolve)
 r=read((s,),Request('activity_totals',ACCOUNT,'USD',start='2025-01-01',end='2025-12-31',grouping='year'))
 values={v['claim']:v['value'] for v in r['figures']}
 assert values==dict(zip(QUANTITIES[2:],['100','3','30','35','-5']))
 basis=next(v for v in r['figures'] if v['claim']=='disposed_cost_basis')
 assert basis['operands'][0]['proceeds']=='30' and basis['operands'][0]['reported_realized_gain']=='-5'
 assert len(basis['operands'][0]['anchor_ids'])==2

def test_encrypted_append_reopen_idempotent_and_no_new_cash(tmp_path):
 events,s=fixture();ledger=Ledger.open(tmp_path/'events.jsonl','synthetic-only')
 for e in events:ledger.append(e)
 count=sum(e.event_type=='TransactionRecorded' for e in ledger.events())
 records=append_statement(ledger,s,resolve);assert len(records)==4
 assert append_statement(ledger,s,resolve)==[]
 reopened=Ledger.open(tmp_path/'events.jsonl','synthetic-only')
 assert committed_statements(tuple(reopened.events()),resolve)==(s,)
 assert sum(e.event_type=='TransactionRecorded' for e in reopened.events())==count
 assert ledger.projection().core is not None

@pytest.mark.parametrize('mutator',[
 lambda s:replace(s,closing_cash=f('134')),
 lambda s:replace(s,rows=(replace(s.rows[0],cash_body_digest='0'*64),*s.rows[1:])),
 lambda s:replace(s,rows=(replace(s.rows[0],funding_reference=f('WRONG')),*s.rows[1:])),
 lambda s:replace(s,rows=(replace(s.rows[0],counterpart_reference=f('WRONG')),*s.rows[1:])),
 lambda s:replace(s,rows=(replace(s.rows[0],funding_role='other_broker'),*s.rows[1:])),
 lambda s:replace(s,rows=(replace(s.rows[0],amount=f('101')),*s.rows[1:])),
 lambda s:replace(s,account=f('Assets:Other')),
 lambda s:replace(s,currency=f('EUR')),
])
def test_cash_or_funding_dependency_mutations_refuse(mutator):
 events,s=fixture()
 with pytest.raises(EvidenceError):validate_statement(mutator(s),events,resolve)

@pytest.mark.parametrize('value,expected', [('1.25','1.25'),('0.00000001','0.00000001'),('999999999999999999.999999999999','999,999,999,999,999,999.999999999999'),('-0.000','0'),(Decimal('1E-12'),'0.000000000001'),('1000.0100','1,000.01')])
def test_faithful_units(value,expected):
 with localcontext() as ctx:
  ctx.prec=2
  assert units(value)==expected

@pytest.mark.parametrize('value',[True,False,1.25,'NaN','Infinity','1e2','1,000.1','1.0000000000001','1000000000000000000','-0.1',Decimal('1E999999999'),Decimal('NaN'),object()])
def test_unsupported_units(value):
 with pytest.raises(UnsupportedUnits):units(value)

def test_missing_gain_is_not_zero_but_source_zero_is_supported():
 _,s=fixture(gain=None)
 r=read((s,),Request('activity_totals',ACCOUNT,'USD',start='2025-01-01',end='2025-12-31',grouping='none'))
 assert {d['claim'] for d in r['dispositions']}=={'disposed_cost_basis','realized_gain'}
 assert any(x['claim']=='sale_proceeds' for x in r['figures'])
 _,s=fixture(gain='0');r=read((s,),Request('activity_totals',ACCOUNT,'USD',start='2025-01-01',end='2025-12-31',grouping='none'))
 assert next(x for x in r['figures'] if x['claim']=='realized_gain')['value']=='0'

def test_unknown_funding_does_not_certify_contribution():
 events,s=fixture(funding=False);validate_statement(s,events,resolve)
 r=read((s,),Request('activity_totals',ACCOUNT,'USD',start='2025-01-01',end='2025-12-31',grouping='none'))
 assert r['dispositions']==[{'claim':'investment_contribution','from':'2025-01-01','to':'2025-12-31','status':'incomplete'}]
 assert not any(x['claim']=='investment_contribution' for x in r['figures'])

def test_explicit_empty_and_parser_empty_are_distinct():
 events,s=fixture(rows=False);validate_statement(s,events,resolve)
 r=read((s,),Request('activity_totals',ACCOUNT,'USD',start='2025-01-01',end='2025-12-31',grouping='none'))
 assert len(r['figures'])==5 and all(x['value']=='0' for x in r['figures'])
 with pytest.raises(EvidenceError):validate_statement(replace(s,explicit_empty=None),events,resolve)

def test_selected_account_excludes_other_broker():
 _,a=fixture();_,b=fixture(account='Assets:BrokerOther',doc='other',sid='other')
 r=read((a,b),Request('activity_totals',ACCOUNT,'USD',start='2025-01-01',end='2025-12-31',grouping='none'))
 assert next(x for x in r['figures'] if x['claim']=='investment_contribution')['value']=='100'
 assert all(x['account']==ACCOUNT for x in r['figures'])

@pytest.mark.parametrize('disposition',['held','incomplete','conflicted'])
def test_holdings_independent_of_activity(disposition):
 _,s=fixture();s=replace(s,disposition=disposition)
 assert len(read((s,),Request('positions',ACCOUNT,'USD',as_of='2025-12-31'))['figures'])==4
 with pytest.raises(EvidenceError):read((s,),Request('activity_totals',ACCOUNT,'USD',start='2025-01-01',end='2025-12-31',grouping='none'))

def test_missing_periods_refuse():
 _,s=fixture(start='2025-02-01')
 with pytest.raises(EvidenceError):read((s,),Request('activity_totals',ACCOUNT,'USD',start='2025-01-01',end='2025-12-31',grouping='none'))

def test_equivalent_copies_coalesce_without_deleting_witnesses():
 _,s=fixture();_,copy=fixture(doc='copy',sid='copy')
 r=read((s,copy),Request('activity_totals',ACCOUNT,'USD',start='2025-01-01',end='2025-12-31',grouping='none'))
 assert next(x for x in r['figures'] if x['claim']=='sale_proceeds')['value']=='30'
 assert any(a['document']=='copy' for a in r['anchors'].values())
 assert all({r['source_identities']['observations'][key] for key in x['observation_ids']}=={'statement','copy'} for x in r['figures'])

def test_deadline_and_statement_limit_refuse_without_partial():
 _,s=fixture()
 with pytest.raises(ResourceLimit):read((s,),Request('positions',ACCOUNT,'USD',as_of='2025-12-31'),deadline=monotonic()-1)
 with pytest.raises(ResourceLimit):read((s,)*121,Request('activity_totals',ACCOUNT,'USD',start='2025-01-01',end='2025-12-31',grouping='none'))

@pytest.mark.parametrize('args',[
 {'view':'positions','account':ACCOUNT,'currency':'USD','as_of':'2025-12-31','limit':3},
 {'view':'positions','account':ACCOUNT,'currency':'USD','as_of':'2025-12-31','from':'2025-01-01'},
 {'view':'activity_totals','account':ACCOUNT,'currency':'USD','from':'2025-01-01','to':'2025-12-31','grouping':'month'},
])
def test_closed_request(args):
 with pytest.raises(EvidenceError):Request.from_dict(args)


def test_conflicting_funding_does_not_drop_accepted_dividend_or_cash(tmp_path):
 events,s=fixture();s=replace(s,rows=(replace(s.rows[0],funding_reference=f('WRONG')),*s.rows[1:]))
 ledger=Ledger.open(tmp_path/'events.jsonl','synthetic-only')
 for e in events:ledger.append(e)
 before=sum(e.event_type=='TransactionRecorded' for e in ledger.events())
 append_statement(ledger,s,resolve)
 statements=committed_statements(tuple(ledger.events()),resolve)
 assert statements[0].rows[0].funding_status=='conflicted'
 result=read(statements,Request('activity_totals',ACCOUNT,'USD',start='2025-01-01',end='2025-12-31',grouping='none'))
 assert next(v for v in result['figures'] if v['claim']=='investment_dividend')['value']=='3'
 assert not any(v['claim']=='investment_contribution' for v in result['figures'])
 assert sum(e.event_type=='TransactionRecorded' for e in ledger.events())==before

@pytest.mark.parametrize('role',['other_broker','retirement_rollover'])
def test_nonbank_funding_requires_accepted_opposing_row_not_new_cash_fields(tmp_path,role):
 events,s=fixture();s=replace(s,account=replace(s.account,raw='DEST-REF'));source_cash=brokerage_activity_transaction(BANK,'withdrawal','100','outgoing source','2025-12-31',provenance=Provenance(doc_id='fund-source',page=1))
 events=[replace(e,body={**e.body,'kind':'investment'}) if e.event_type=='AccountOpened' and e.body['account_id']==BANK else e for e in events]
 events=[source_cash if e.event_id==s.rows[0].funding_witness.transaction_id else e for e in events]
 outgoing=Row('opposing-row','row',0,f('2025-12-31','fund-source',1),f('withdrawal','fund-source',1),f('100','fund-source',1),None,None,source_cash.event_id,digest(source_cash.body),'outgoing source',funding_reference=f('PRINTED-X','fund-source',1),counterpart_reference=f('DEST-REF','fund-source',1),funding_role_source=f(role,'fund-source',1))
 source=Statement('opposing-statement',replace(f(BANK,'fund-source',1),raw='BANK-REF'),f('USD','fund-source',1),f('2025-01-01','fund-source',1),f('2025-12-31','fund-source',1),f('100','fund-source',1),f('0','fund-source',1),(outgoing,),'accepted_complete_nonempty',snapshot_complete=True)
 from viva.ledger.events import closing_balance_observed
 events.append(closing_balance_observed(BANK,'0','2025-12-31',provenance=Provenance(doc_id='fund-source',page=1)))
 ledger=Ledger.open(tmp_path/'events.jsonl','synthetic-only')
 for e in events:ledger.append(e)
 append_statement(ledger,source,resolve)
 source_row=next(e for e in ledger.events() if e.event_type==ROW and e.body['statement_id']=='opposing-statement')
 old=s.rows[0].funding_witness;w=replace(old,reference=outgoing.funding_reference,counterpart_reference=replace(source.account,value='BANK-REF'),role=role,transaction_id=source_cash.event_id,transaction_digest=digest(source_cash.body),source_row_event_id=source_row.event_id)
 incoming=replace(s.rows[0],funding_role=role,funding_role_source=f(role),funding_witness=w)
 append_statement(ledger,replace(s,rows=(incoming,*s.rows[1:])),resolve)
 result=read(committed_statements(tuple(ledger.events()),resolve),Request('activity_totals',ACCOUNT,'USD',start='2025-01-01',end='2025-12-31',grouping='none'))
 figure=next(v for v in result['figures'] if v['claim']=='investment_contribution')
 assert figure['value']=='100' and figure['funding_roles']==[role]
 assert 'source_reference' not in source_cash.body
 from viva.investment.lifecycle import SourceChange
 cash_count=sum(e.event_type=='TransactionRecorded' for e in ledger.events())
 retract_source(ledger,SourceChange('funding-retract','activity','opposing-statement','fund-source','2025-12-31','source_retraction'),resolve)
 current=read(committed_statements(tuple(ledger.events()),resolve),Request('activity_totals',ACCOUNT,'USD',start='2025-01-01',end='2025-12-31',grouping='none'))
 assert {d['claim'] for d in current['dispositions']}=={'investment_contribution'}
 assert next(f for f in current['figures'] if f['claim']=='investment_dividend')['value']=='3'
 assert sum(e.event_type=='TransactionRecorded' for e in ledger.events())==cash_count


def test_short_units_refuse_only_affected_field():
 _,s=fixture();p=replace(s.positions[0],units=f('-1.25'))
 result=read((replace(s,positions=(p,)),),Request('positions',ACCOUNT,'USD',as_of='2025-12-31'))
 assert result['dispositions']==[{'security':p.security_id,'claim':'security_units','status':'unsupported_units'}]
 assert {v['quantity'] for v in result['figures']}=={'balance','holding_cost_basis','count'}


def test_account_local_security_identity_is_not_cross_account_ticker_equality():
 events,s=fixture();assert security_identity(ACCOUNT,'TEST-SEC')!=security_identity('Assets:Other','TEST-SEC')
 assert security_identity(ACCOUNT,'TEST-SEC')!=security_identity(ACCOUNT,'test-sec')
 with pytest.raises(EvidenceError,match='security identity'):
  validate_statement(replace(s,positions=(replace(s.positions[0],security_id=security_identity('Assets:Other','TEST-SEC')),)),events,resolve)


def test_source_frontier_missing_atomic_row_and_changed_prefix_refuse(tmp_path):
 import copy
 events,s=fixture();ledger=Ledger.open(tmp_path/'events.jsonl','synthetic-only')
 for e in events:ledger.append(e)
 before=tuple(ledger.events());assert committed_statements(before,resolve)==()
 append_statement(ledger,s,resolve);after=tuple(ledger.events())
 missing=tuple(e for e in after if not (e.event_type==ROW and e.body['row']['ordinal']==1))
 with pytest.raises(EvidenceError):committed_statements(missing,resolve)
 changed=list(copy.deepcopy(after));target=next(e for e in changed if e.event_id==s.rows[0].cash_event_id);target.body['description']='different source'
 with pytest.raises(EvidenceError,match='prefix'):committed_statements(tuple(changed),resolve)


def test_same_value_rows_preserve_multiplicity_and_equivalent_reordered_copy():
 _,s=fixture();duplicate=replace(s.rows[1],observation_id='extra-dividend',local_id='extra',ordinal=3)
 s=replace(s,rows=(*s.rows,duplicate),closing_cash=f('136'))
 copy=replace(s,observation_id='copy',rows=tuple(reversed(s.rows)))
 result=read((s,copy),Request('activity_totals',ACCOUNT,'USD',start='2025-01-01',end='2025-12-31',grouping='none'))
 dividend=next(v for v in result['figures'] if v['claim']=='investment_dividend')
 assert dividend['value']=='6' and {'extra-dividend',s.rows[1].observation_id}<={result['source_identities']['rows'][key] for key in dividend['row_ids']}


def test_rows_groups_positions_and_complete_byte_caps():
 _,s=fixture()
 with pytest.raises(ResourceLimit):replace(s,rows=(s.rows[0],)*1001)
 with pytest.raises(ResourceLimit):Request('activity_totals',ACCOUNT,'USD',start='2020-12-31',end='2030-01-01',grouping='year')
 positions=tuple(Position(security_identity(ACCOUNT,'SEC-'+str(i)),f('SEC-'+str(i),anchor='identity-'+str(i)+'x'*240),f('1',anchor='units-'+str(i)+'x'*240),f('25',anchor='value-'+str(i)+'x'*240),f('20',anchor='basis-'+str(i)+'x'*240)) for i in range(20))
 with pytest.raises(ResourceLimit):replace(s,positions=(*positions,positions[0]))
 with pytest.raises(ResourceLimit,match='bytes'):read((replace(s,positions=positions),),Request('positions',ACCOUNT,'USD',as_of='2025-12-31'))


def test_many_source_anchors_on_one_page_still_enforce_complete_byte_cap():
 _,s=fixture();base=s.rows[1]
 rows=tuple(replace(base,observation_id='row-'+str(i),local_id=str(i),ordinal=i,date=f('2025-12-31',anchor='date-'+str(i)),kind=f('dividend',anchor='kind-'+str(i)),amount=f('3',anchor='amount-'+str(i))) for i in range(180))
 s=replace(s,rows=rows,closing_cash=f('540'))
 with pytest.raises(ResourceLimit,match='bytes'):read((s,),Request('activity_totals',ACCOUNT,'USD',start='2025-01-01',end='2025-12-31',grouping='none'))


def test_different_document_equivalent_copy_binds_existing_cash_without_posting(tmp_path):
 events,original=fixture();ignored,copy=fixture(doc='copy-source',sid='copy-statement')
 ledger=Ledger.open(tmp_path/'events.jsonl','synthetic-only')
 for event in events:ledger.append(event)
 append_statement(ledger,original,resolve);before=sum(e.event_type=='TransactionRecorded' for e in ledger.events())
 append_statement(ledger,copy,resolve)
 statements=committed_statements(tuple(ledger.events()),resolve);assert len(statements)==2
 bound=next(s for s in statements if s.observation_id=='copy-statement');assert bound.corroborates==original.observation_id
 assert [r.cash_event_id for r in bound.rows]==[r.cash_event_id for r in original.rows]
 assert sum(e.event_type=='TransactionRecorded' for e in ledger.events())==before
 result=read(statements,Request('activity_totals',ACCOUNT,'USD',start='2025-01-01',end='2025-12-31',grouping='year'))
 assert next(f for f in result['figures'] if f['claim']=='investment_contribution')['value']=='100'
 assert {'source','copy-source'}<=set(a['document'] for a in result['anchors'].values())
 assert all({result['source_identities']['observations'][key] for key in f['observation_ids']}=={'statement','copy-statement'} for f in result['figures'])


def test_copy_multiplicity_cent_reference_and_partial_coverage_cannot_bind_old_cash(tmp_path):
 from viva.investment.identity import bind_corroborating_copy
 events,original=fixture();_,copy=fixture(doc='copy-source',sid='copy-statement')
 for changed in [replace(copy,closing_cash=f('133.01','copy-source')),replace(copy,rows=copy.rows[:-1]),replace(copy,start=f('2025-02-01','copy-source')),replace(copy,printed_reference=f('OTHER-STATEMENT','copy-source'))]:
  assert bind_corroborating_copy(changed,(original,),tuple(events)).corroborates is None
  with pytest.raises(EvidenceError):validate_statement(changed,tuple(events),resolve)


def test_copy_same_source_reference_conflicting_cash_occurrences_refuse():
 from viva.investment.identity import bind_corroborating_copy
 _,original=fixture();_,other=fixture(doc='other-source',sid='other-statement');_,copy=fixture(doc='copy-source',sid='copy-statement')
 with pytest.raises(EvidenceError,match='different accepted cash'):bind_corroborating_copy(copy,(original,other),())


def test_unavailable_gain_keeps_sale_proceeds_and_cash_coverage():
 events,s=fixture();sale=replace(s.rows[2],realized_gain=f('',status='unavailable'))
 changed=replace(s,rows=(*s.rows[:2],sale));validate_statement(changed,events,resolve)
 result=read((changed,),Request('activity_totals',ACCOUNT,'USD',start='2025-01-01',end='2025-12-31',grouping='year'))
 assert next(v for v in result['figures'] if v['claim']=='sale_proceeds')['value']=='30'
 assert {v['claim'] for v in result['dispositions']}=={'realized_gain','disposed_cost_basis'}


def test_source_fields_cannot_borrow_header_or_row_capture_pages():
 events,s=fixture()
 wrong=replace(s,rows=(replace(s.rows[0],date=f(s.end.value,'other-source')),*s.rows[1:]))
 with pytest.raises(EvidenceError,match='another source capture'):validate_statement(wrong,events,resolve)


def test_negative_implied_basis_does_not_emit_gain_or_basis_total():
 _,s=fixture(gain='31');result=read((s,),Request('activity_totals',ACCOUNT,'USD',start='2025-01-01',end='2025-12-31',grouping='year'))
 assert {v['claim'] for v in result['dispositions']}=={'realized_gain','disposed_cost_basis'}
 assert next(v for v in result['figures'] if v['claim']=='sale_proceeds')['value']=='30'

@pytest.mark.parametrize('role',['own_bank','reinvestment'])
def test_bare_funding_role_never_certifies_or_emits_complete_zero(role):
 events,s=fixture()
 incoming=replace(s.rows[0],funding_role=role,funding_role_source=None,funding_witness=None)
 s=replace(s,rows=(incoming,*s.rows[1:]))
 certified=certify_funding(s,events,resolve)
 assert certified.rows[0].funding_status!='accepted'
 result=read((certified,),Request('activity_totals',ACCOUNT,'USD',start='2025-01-01',end='2025-12-31',grouping='none'))
 assert not any(f['claim']=='investment_contribution' for f in result['figures'])
 assert {d['claim'] for d in result['dispositions']}=={'investment_contribution'}

def test_explicit_sourced_reinvestment_excludes_boundary_contribution_and_keeps_anchor():
 events,s=fixture()
 incoming=replace(s.rows[0],funding_role='reinvestment',funding_role_source=f('reinvestment'),funding_witness=None,funding_reference=None,counterpart_reference=None)
 certified=certify_funding(replace(s,rows=(incoming,*s.rows[1:])),events,resolve)
 assert certified.rows[0].funding_status=='accepted'
 result=read((certified,),Request('activity_totals',ACCOUNT,'USD',start='2025-01-01',end='2025-12-31',grouping='none'))
 figure=next(f for f in result['figures'] if f['claim']=='investment_contribution')
 assert figure['value']=='0'
 from viva.investment.authority import field_id
 from viva.investment.lineage import expand_anchors
 assert field_id(incoming.funding_role_source) in {digest(expand_anchors(result)[key]) for key in figure['anchor_ids']}

def test_missing_units_page_does_not_drop_independent_basis_or_value():
 _,s=fixture();p=s.positions[0]
 s=replace(s,positions=(replace(p,units=f('unreadable',page=None,status='unavailable')),))
 result=read((s,),Request('positions',ACCOUNT,'USD',as_of='2025-12-31'))
 assert {x['claim'] for x in result['figures']}=={'balance','holding_cost_basis','count'}
 assert result['dispositions']==[{'security':p.security_id,'claim':'security_units','status':'unavailable'}]
 with pytest.raises(EvidenceError):f('1.25',page=None)

def test_position_copy_basis_conflict_is_field_local_and_order_independent():
 _,s=fixture();_,copy=fixture(doc='copy',sid='copy')
 copy=replace(copy,positions=(replace(copy.positions[0],basis=f('21','copy')),))
 result=read((s,copy),Request('positions',ACCOUNT,'USD',as_of='2025-12-31'))
 assert {x['claim'] for x in result['figures']}=={'security_units','balance','count'}
 assert result['dispositions']==[{'security':s.positions[0].security_id,'claim':'holding_cost_basis','status':'conflicted'}]
 assert all([result['source_identities']['observations'][key] for key in x['observation_ids']]==['statement','copy'] for x in result['figures'])


def test_over512_actual_document_page_pairs_refuse_complete_result():
 import calendar
 statements=[]
 for month in range(1,4):
  document='source-month-'+str(month);end='2025-'+str(month).zfill(2)+'-'+str(calendar.monthrange(2025,month)[1]);start='2025-'+str(month).zfill(2)+'-01'
  rows=tuple(Row('source-'+str(month)+'-row-'+str(i),str(i),i,f(end,document,3*i+1),f('dividend',document,3*i+2),f('3',document,3*i+3),None,None,'cash-'+str(month)+'-'+str(i),'0'*64) for i in range(60))
  statements.append(Statement('statement-'+str(month),f(ACCOUNT,document,186),f('USD',document,185),f(start,document,189),f(end,document,190),f('0',document,188),f('180',document,187),rows,'accepted_complete_nonempty'))
 with pytest.raises(ResourceLimit,match='document/page anchor'):
  read(tuple(statements),Request('activity_totals',ACCOUNT,'USD',start='2025-01-01',end='2025-03-31',grouping='none'))
