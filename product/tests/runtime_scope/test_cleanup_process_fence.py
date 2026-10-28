"""Real second-process publication owns every building/ready/temp cleanup path."""
import json,subprocess,sys,time
from pathlib import Path
import pytest
from viva.read_store import ReadStore
from viva.read_store.store import ReadStoreBusy

CHILD='''import sys,json
from pathlib import Path
from viva.read_store import ReadStore
from viva.read_store import store as module
request=json.loads(sys.stdin.readline())
with ReadStore.open(Path(request['directory']),request['passphrase']) as writer:
 phase=request['phase']
 original=writer._inject
 def pause():
  sys.stdout.write(json.dumps({'phase':phase,'source':module.__file__})+'\\n');sys.stdout.flush()
  if sys.stdin.readline().strip()!='release':raise RuntimeError('barrier not released')
 def inject(failure,label):
  if (phase=='ready' and label=='after_ready') or (phase=='manifest' and label=='before_manifest_replace'):pause()
  return original(failure,label)
 writer._inject=inject
 def build(connection):
  connection.execute('CREATE TABLE process_witness(value TEXT)')
  connection.execute("INSERT INTO process_witness VALUES('complete')")
  if phase=='building':pause()
 generation=writer.publish(build)
 sys.stdout.write(json.dumps({'published':generation})+'\\n');sys.stdout.flush()
'''

@pytest.mark.parametrize('phase',['building','ready','manifest'])
def test_external_cleanup_defers_without_touching_other_process_publication(tmp_path,phase):
 with ReadStore.create(tmp_path/'reads','synthetic-only') as foreground:
  held=foreground.open_reader();current=held.generation
  process=subprocess.Popen([sys.executable,'-c',CHILD],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
  process.stdin.write(json.dumps({'directory':str(tmp_path/'reads'),'passphrase':'synthetic-only','phase':phase})+'\n');process.stdin.flush()
  try:
   # Bounded pipe wait is a test barrier, never a race based on elapsed sleep.
   import queue,threading
   reply=queue.Queue()
   receiver=threading.Thread(target=lambda:reply.put(process.stdout.readline()),daemon=True);receiver.start()
   signal=json.loads(reply.get(timeout=5));receiver.join(1);assert signal['phase']==phase
   from viva.read_store import store as source
   assert signal['source']==source.__file__
   def snapshot():return {str(p.relative_to(tmp_path/'reads')) for p in (tmp_path/'reads').rglob('*') if p.name!='writer.lock'}
   before=snapshot();started=time.monotonic();held.close()
   with pytest.raises(ReadStoreBusy):foreground.cleanup()
   with ReadStore.open(tmp_path/'reads','synthetic-only') as other:
    assert other.cleanup_error.startswith('ReadStoreBusy:')
   assert time.monotonic()-started<1
   assert snapshot()==before
   if phase=='manifest':assert any(name.startswith('current.g-') and name.endswith('.tmp') for name in before)
   process.stdin.write('release\n');process.stdin.flush()
   stdout,stderr=process.communicate(timeout=5);assert process.returncode==0,stderr
   published=json.loads(stdout)['published']
   with foreground.open_reader() as revised:
    assert revised.generation==published!=current
    assert revised.connection.execute('SELECT value FROM process_witness').fetchone()==('complete',)
   foreground.cleanup()
  finally:
   if not held._closed:held.close()
   if process.poll() is None:process.kill();process.communicate(timeout=3)


def test_deferred_cleanup_retries_abandoned_artifacts_and_retains_bounds(tmp_path):
 from viva.read_store.store import _WriterLock,LOCK_NAME,DATABASE_NAME,RETAIN_SUPERSEDED_GENERATIONS,RETAIN_QUARANTINED_GENERATIONS,WRITER_LOCK_TIMEOUT_SECONDS,MANIFEST_REPLACE_TIMEOUT_SECONDS
 import uuid
 assert (RETAIN_SUPERSEDED_GENERATIONS,RETAIN_QUARANTINED_GENERATIONS,WRITER_LOCK_TIMEOUT_SECONDS,MANIFEST_REPLACE_TIMEOUT_SECONDS)==(2,2,5.0,2.0)
 with ReadStore.create(tmp_path/'reads','synthetic-only') as store:
  reader=store.open_reader();current=reader.generation
  abandoned=tmp_path/'reads/generations'/('g-'+uuid.uuid4().hex)
  with _WriterLock(tmp_path/'reads'/LOCK_NAME,0):
   abandoned.mkdir();(abandoned/DATABASE_NAME).write_bytes(b'incomplete interrupted native build')
   reader.close()
   assert abandoned.exists()
   with pytest.raises(ReadStoreBusy):store.cleanup()
  store.cleanup();assert not abandoned.exists()
  assert (tmp_path/'reads/generations'/current).exists()
  for i in range(7):store.publish()
  assert len(list((tmp_path/'reads/generations').iterdir()))<=3
  assert len(list((tmp_path/'reads/quarantine').iterdir()))<=2
