from dataclasses import replace
import pytest
from test_draft import fixture,resolve,ACCOUNT,f
from viva.ledger.ledger import Ledger
from viva.investment.contracts import EvidenceError,Request
from viva.investment.events import append_statement,committed_statements,source_index,retract_source,STATEMENT
from viva.investment.lifecycle import SourceChange
from viva.investment.authority import read


def setup(tmp_path):
 events,s=fixture();ledger=Ledger.open(tmp_path/'test.jsonl','synthetic-only')
 for event in events:ledger.append(event)
 append_statement(ledger,s,resolve)
 return ledger,s

def successor(s,identifier='replacement',held=False):
 return replace(s,observation_id=identifier,rows=tuple(replace(r,observation_id=identifier+'-'+str(i)) for i,r in enumerate(s.rows)),disposition='held' if held else s.disposition)

def test_accepted_supersession_keeps_original_and_distinguishes_effective_date_recorded_frontier(tmp_path):
 ledger,original=setup(tmp_path);old=tuple(ledger.events());new=successor(original)
 change=SourceChange('change','activity',original.observation_id,'source','2026-01-01','source_correction',new.observation_id)
 append_statement(ledger,new,resolve,(change,));current=tuple(ledger.events())
 assert [s.observation_id for s in committed_statements(old,resolve)]==[original.observation_id]
 assert [s.observation_id for s in committed_statements(current,resolve,effective_as_of='2025-12-31')]==[original.observation_id]
 assert [s.observation_id for s in committed_statements(current,resolve,effective_as_of='2026-01-01')]==[new.observation_id]
 assert sum(e.event_type==STATEMENT for e in current)==2
 assert source_index(current,resolve).project('positions','2026-01-01',resolve)[0].statement.observation_id==original.observation_id
 assert source_index(current,resolve).project('activity','2026-01-01',resolve)[0].statement.observation_id==new.observation_id


def test_pending_successor_preserves_prior_values_and_marks_activity_unresolved(tmp_path):
 ledger,s=setup(tmp_path);new=successor(s,held=True)
 change=SourceChange('change','activity',s.observation_id,'source','2025-12-31','source_correction',new.observation_id)
 append_statement(ledger,new,resolve,(change,));selected=source_index(tuple(ledger.events()),resolve).project('activity','2025-12-31',resolve)
 assert selected[0].statement.observation_id==s.observation_id and selected[0].statement.closing_cash.value=='133' and selected[0].status=='pending'
 with pytest.raises(EvidenceError):read(committed_statements(tuple(ledger.events()),resolve),Request('activity_totals',ACCOUNT,'USD',start='2025-01-01',end='2025-12-31',grouping='none'))
 assert source_index(tuple(ledger.events()),resolve).project('positions','2025-12-31',resolve)[0].status=='accepted'


def test_retraction_and_stale_document_account_predecessors_fail_closed(tmp_path):
 ledger,s=setup(tmp_path);retraction=SourceChange('retract','activity',s.observation_id,'source','2026-01-01','source_retraction')
 retract_source(ledger,retraction,resolve);assert committed_statements(tuple(ledger.events()),resolve)==()
 assert len(committed_statements(tuple(ledger.events()),resolve,effective_as_of='2025-12-31'))==1
 with pytest.raises(EvidenceError,match='not current'):retract_source(ledger,replace(retraction,change_id='again'),resolve)


def test_source_change_cannot_name_another_document_or_missing_atomic_change(tmp_path):
 ledger,s=setup(tmp_path);new=successor(s);bad=SourceChange('bad','activity',s.observation_id,'other-document','2025-12-31','source_correction',new.observation_id)
 before=len(tuple(ledger.events()))
 with pytest.raises(EvidenceError,match='document'):append_statement(ledger,new,resolve,(bad,))
 assert len(tuple(ledger.events()))==before
 good=replace(bad,prior_document='source');append_statement(ledger,new,resolve,(good,))
 events=tuple(ledger.events())
 with pytest.raises(EvidenceError,match='atomic'):committed_statements(events[:-1],resolve)


def test_retracted_dependency_withdraws_copy_certification_without_new_cash(tmp_path):
 ledger,s=setup(tmp_path);_,copy=fixture(doc='copy-source',sid='copy');append_statement(ledger,copy,resolve)
 before=sum(e.event_type=='TransactionRecorded' for e in ledger.events())
 retract_source(ledger,SourceChange('retract','activity',s.observation_id,'source','2025-12-31','source_retraction'),resolve)
 selected=source_index(tuple(ledger.events()),resolve).project('activity','2025-12-31',resolve)
 assert len(selected)==1 and selected[0].statement.observation_id=='copy' and selected[0].status=='dependency_unavailable'
 with pytest.raises(EvidenceError):read(committed_statements(tuple(ledger.events()),resolve),Request('activity_totals',ACCOUNT,'USD',start='2025-01-01',end='2025-12-31',grouping='year'))
 assert sum(e.event_type=='TransactionRecorded' for e in ledger.events())==before


def test_counterpart_identity_change_withholds_contribution_only(tmp_path):
 ledger,s=setup(tmp_path)
 current=committed_statements(tuple(ledger.events()),lambda field:'Assets:Different')
 result=read(current,Request('activity_totals',ACCOUNT,'USD',start='2025-01-01',end='2025-12-31',grouping='year'))
 assert {d['claim'] for d in result['dispositions']}=={'investment_contribution'}
 assert next(f for f in result['figures'] if f['claim']=='investment_dividend')['value']=='3'


def test_pending_then_accepted_retry_is_atomic_and_idempotent(tmp_path):
 ledger,s=setup(tmp_path);held=successor(s,'held',held=True);accepted=successor(s,'accepted')
 pending=SourceChange('pending','activity',s.observation_id,'source','2025-12-31','source_correction',held.observation_id)
 final=replace(pending,change_id='final',replacement_id=accepted.observation_id)
 append_statement(ledger,held,resolve,(pending,));append_statement(ledger,accepted,resolve,(final,))
 before=len(tuple(ledger.events()));assert append_statement(ledger,accepted,resolve,(final,))==[];assert len(tuple(ledger.events()))==before
 selected=source_index(tuple(ledger.events()),resolve).project('activity','2025-12-31',resolve)
 assert selected[0].status=='accepted' and selected[0].statement.observation_id=='accepted' and not selected[0].changes


def test_effective_segments_match_replay_and_select_one_history_version(tmp_path):
 import sqlite3
 from viva.investment.sql import materialize,read_sql
 ledger,s=setup(tmp_path);new=successor(s)
 change=SourceChange('change','activity',s.observation_id,'source','2025-12-31','source_correction',new.observation_id)
 append_statement(ledger,new,resolve,(change,));events=tuple(ledger.events());connection=sqlite3.connect(':memory:');frontier=materialize(connection,events,resolve)
 request=Request('activity_totals',ACCOUNT,'USD',start='2025-01-01',end='2025-12-31',grouping='year')
 assert read_sql(connection,request,frontier)==read(committed_statements(events,resolve,effective_as_of=request.end),request)
 result=read_sql(connection,request,frontier)
 assert [result['source_identities']['observations'][key] for key in next(f for f in result['figures'] if f['claim']=='sale_proceeds')['observation_ids']]==['replacement']
 segments=connection.execute('SELECT observation_id,effective_from,effective_to FROM investment_evidence_statements WHERE facet=\'activity\' ORDER BY effective_from').fetchall()
 assert segments==[('statement','0001-01-01','2025-12-30'),('replacement','2025-12-31','9999-12-31')]


def test_sql_pending_facet_never_falls_back_or_erases_other_facet(tmp_path):
 import sqlite3
 from viva.investment.sql import materialize,read_sql
 ledger,s=setup(tmp_path);new=successor(s,held=True)
 change=SourceChange('change','activity',s.observation_id,'source','2025-12-31','source_correction',new.observation_id)
 append_statement(ledger,new,resolve,(change,));connection=sqlite3.connect(':memory:');frontier=materialize(connection,tuple(ledger.events()),resolve)
 with pytest.raises(EvidenceError,match='unresolved'):read_sql(connection,Request('activity_totals',ACCOUNT,'USD',start='2025-01-01',end='2025-12-31',grouping='none'),frontier)
 assert len(read_sql(connection,Request('positions',ACCOUNT,'USD',as_of='2025-12-31'),frontier)['figures'])==4


def test_copy_dependency_invalidation_is_transitive(tmp_path):
 ledger,original=setup(tmp_path);_,copy=fixture(doc='copy-source',sid='copy');append_statement(ledger,copy,resolve)
 _,copy_of_copy=fixture(doc='source',sid='copy-of-copy');append_statement(ledger,copy_of_copy,resolve)
 raw=committed_statements(tuple(ledger.events()),resolve)
 assert next(s for s in raw if s.observation_id=='copy-of-copy').corroborates=='copy'
 retract_source(ledger,SourceChange('retract','activity',original.observation_id,'source','2025-12-31','source_retraction'),resolve)
 chosen=source_index(tuple(ledger.events()),resolve).project('activity','2025-12-31',resolve)
 assert {s.statement.observation_id:s.status for s in chosen}=={'copy':'dependency_unavailable','copy-of-copy':'dependency_unavailable'}


def test_activity_and_position_facets_can_advance_independently_without_erasing_history(tmp_path):
 import sqlite3
 from viva.investment.sql import materialize,read_sql
 ledger,original=setup(tmp_path);replacement=successor(original)
 from viva.ledger.events import position_observed,Provenance
 from viva.investment.contracts import digest
 observed=position_observed(ACCOUNT,'TEST-SEC','1.25','25','USD','2025-12-31',cost_basis='21',provenance=Provenance(doc_id='source',page=2))
 ledger.append(observed)
 replacement=replace(replacement,positions=(replace(replacement.positions[0],basis=f('21'),position_event_id=observed.event_id,position_body_digest=digest(observed.body)),))
 change=SourceChange('positions','positions',original.observation_id,'source','2025-12-31','source_correction',replacement.observation_id)
 before=sum(e.event_type=='TransactionRecorded' for e in ledger.events());append_statement(ledger,replacement,resolve,(change,))
 events=tuple(ledger.events());connection=sqlite3.connect(':memory:');frontier=materialize(connection,events,resolve)
 positions=read_sql(connection,Request('positions',ACCOUNT,'USD',as_of='2025-12-31'),frontier)
 assert next(f for f in positions['figures'] if f['claim']=='holding_cost_basis')['value']=='21'
 activity=read_sql(connection,Request('activity_totals',ACCOUNT,'USD',start='2025-01-01',end='2025-12-31',grouping='year'),frontier)
 assert [activity['source_identities']['observations'][key] for key in next(f for f in activity['figures'] if f['claim']=='sale_proceeds')['observation_ids']]==['statement']
 assert sum(e.event_type=='TransactionRecorded' for e in events)==before


@pytest.mark.parametrize('after_commit',[False,True])
def test_interrupted_source_append_recovers_without_second_cash_posting(tmp_path,monkeypatch,after_commit):
 import viva.ledger.store as module
 events,s=fixture();ledger=Ledger.open(tmp_path/'test.jsonl','synthetic-only')
 for event in events:ledger.append(event)
 before=tuple(ledger.events());cash=sum(e.event_type=='TransactionRecorded' for e in before);real=module.write_head
 def interrupted(*args,**kwargs):
  if after_commit:real(*args,**kwargs)
  raise OSError('synthetic source append interruption')
 monkeypatch.setattr(module,'write_head',interrupted)
 with pytest.raises(OSError):append_statement(ledger,s,resolve)
 monkeypatch.setattr(module,'write_head',real)
 reopened=Ledger.open(tmp_path/'test.jsonl','synthetic-only');recorded=tuple(reopened.events())
 assert sum(e.event_type=='TransactionRecorded' for e in recorded)==cash
 assert len(committed_statements(recorded,resolve))==(1 if after_commit else 0)
 append_statement(reopened,s,resolve)
 assert len(committed_statements(tuple(reopened.events()),resolve))==1
 assert sum(e.event_type=='TransactionRecorded' for e in reopened.events())==cash
 assert append_statement(reopened,s,resolve)==[]


def test_two_writers_cannot_both_replace_the_same_current_predecessor(tmp_path):
 from concurrent.futures import ThreadPoolExecutor
 from threading import Barrier
 ledger,original=setup(tmp_path);other=ledger.fork();barrier=Barrier(2)
 choices=[successor(original,'first'),successor(original,'second')]
 def run(writer,replacement):
  change=SourceChange(replacement.observation_id+'-change','activity',original.observation_id,'source','2025-12-31','source_correction',replacement.observation_id)
  barrier.wait(timeout=5)
  try:append_statement(writer,replacement,resolve,(change,))
  except EvidenceError as error:return ('refused',str(error))
  return ('accepted',replacement.observation_id)
 before=sum(e.event_type=='TransactionRecorded' for e in ledger.events())
 with ThreadPoolExecutor(max_workers=2) as pool:outcomes=list(pool.map(lambda args:run(*args),[(ledger,choices[0]),(other,choices[1])]))
 assert sorted(value[0] for value in outcomes)==['accepted','refused']
 assert 'not current' in next(value[1] for value in outcomes if value[0]=='refused')
 current=committed_statements(tuple(ledger.events()),resolve)
 assert [s.observation_id for s in current]==[next(value[1] for value in outcomes if value[0]=='accepted')]
 assert sum(e.event_type=='TransactionRecorded' for e in ledger.events())==before
