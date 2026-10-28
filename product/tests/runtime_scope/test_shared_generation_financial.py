"""Two real native coordinators preserve financial generation during publication."""
import threading,json,os
from pathlib import Path
from viva.ledger import Ledger
from viva.ledger.events import account_opened,opening_balance_observed,Provenance
from viva.ledger.postings import simple_transaction
from viva.read_store import ReadStore

def test_native_active_publication_survives_external_cleanup_and_keeps_financial_truth(tmp_path):
 ledger=Ledger.open(tmp_path/'events.jsonl','synthetic-only')
 ledger.append(account_opened('checking','depository','Test checking','USD','2025-01-01'))
 ledger.append(opening_balance_observed('checking','100.00','2025-01-01',Provenance('issued-source',1)))
 ledger.append(simple_transaction('checking','-25.00','Test purchase','2025-01-02',provenance=Provenance('issued-source',1)))
 canonical=[e.to_dict() for e in ledger.events()]
 with ReadStore.create(tmp_path/'reads','synthetic-only') as foreground:
  foreground.synchronize(ledger.store)
  with ReadStore.open(tmp_path/'reads','synthetic-only') as writer:
   held=foreground.open_reader();current=held.generation;before=held.account_ledger_components('checking')
   entered=threading.Event();release=threading.Event();errors=[];published=[]
   def build(connection,entry):
    if entry.sequence==len(canonical)-1:entered.set();assert release.wait(5)
   def publish():
    try:published.append(writer.synchronize(ledger.store,apply_event=build,as_of_version='deterministic-full-rebuild-probe').generation)
    except Exception as error:errors.append(error)
   existing={p.name for p in (tmp_path/'reads/generations').iterdir()}
   thread=threading.Thread(target=publish);thread.start()
   assert entered.wait(5)
   building=[p for p in (tmp_path/'reads/generations').iterdir() if p.name not in existing]
   # One current ready revision plus exactly one still-active native writer.
   assert len(building)==1
   held.close();survived=building[0].exists();release.set();thread.join(5)
   with foreground.open_reader() as after:
    unchanged=after.account_ledger_components('checking')==before
    still_current=after.generation==current
   report={'live_building_generation_survived_external_reader_close':survived,'writer_errors':[{'type':type(e).__name__,'message':str(e),'cause_type':type(e.__cause__).__name__ if e.__cause__ else None,'cause_message':str(e.__cause__) if e.__cause__ else None} for e in errors],'published_generations':published,'old_financial_revision_unchanged':unchanged,'old_generation_still_current_after_failed_publication':still_current,'canonical_events_unchanged':[e.to_dict() for e in ledger.events()]==canonical,'financial_components':__import__('dataclasses').asdict(before)}
   out=Path(os.environ.get('CLEANUP_REPRO_REPORT',str(tmp_path/'REPORT.json')));out.write_text(json.dumps(report,indent=2,default=str)+'\n')
   assert survived and not errors,report
   assert unchanged and report['canonical_events_unchanged']
