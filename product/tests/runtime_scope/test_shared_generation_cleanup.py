"""Native generation publication must survive another handle's reader close."""
import threading
from viva.read_store import ReadStore

def test_live_building_generation_is_not_quarantined_by_other_reader_close(tmp_path):
 with ReadStore.create(tmp_path/'reads','synthetic-only') as foreground,ReadStore.open(tmp_path/'reads','synthetic-only') as writer:
  held=foreground.open_reader();current=held.generation
  entered=threading.Event();release=threading.Event();errors=[];published=[]
  def build(connection):
   connection.execute('CREATE TABLE publication_witness(value TEXT)')
   connection.execute("INSERT INTO publication_witness VALUES('complete')")
   entered.set();assert release.wait(5)
  def publish():
   try:published.append(writer.publish(build))
   except Exception as error:errors.append(error)
  thread=threading.Thread(target=publish);thread.start()
  try:
   assert entered.wait(5)
   building=[p for p in (tmp_path/'reads/generations').iterdir() if p.name!=current]
   assert len(building)==1
   held.close()
   assert building[0].exists(),'reader cleanup quarantined a live writer generation'
  finally:
   release.set();thread.join(5)
  assert not thread.is_alive() and not errors,errors
  with foreground.open_reader() as revised:
   assert revised.generation==published[0]
   assert revised.connection.execute('SELECT value FROM publication_witness').fetchone()==('complete',)
