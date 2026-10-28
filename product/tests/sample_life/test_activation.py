"""Lifecycle/control contracts; these are not financial or full-corpus proofs."""
import json
from pathlib import Path
from types import SimpleNamespace
import pytest

from viva.sample import activation,instances


def test_atomic_receipt_publication_preserves_history(tmp_path,monkeypatch):
    target=tmp_path/'receipt.json';real=instances.os.link;seen=[]
    def publish(source,destination):
        assert not target.exists()
        seen.append(json.loads(Path(source).read_text()))
        return real(source,destination)
    monkeypatch.setattr(instances.os,'link',publish)
    instances._write(target,{'state':'checking'})
    assert seen==[{'state':'checking'}] and json.loads(target.read_text())==seen[0]
    monkeypatch.setattr(instances.os,'link',real)
    with pytest.raises(FileExistsError):instances._write(target,{'state':'forged-ready'})
    assert json.loads(target.read_text())=={'state':'checking'}
    assert list(tmp_path.glob('*.writing-*'))==[]


def test_prepare_starts_one_background_control_job_and_status_never_opens_vault(tmp_path,monkeypatch):
    jobs=[]
    class HeldThread:
        def __init__(self,**kwargs):self.kwargs=kwargs;self.alive=False;jobs.append(self)
        def start(self):self.alive=True
        def is_alive(self):return self.alive
    monkeypatch.setattr(activation,'Thread',HeldThread)
    monkeypatch.setattr(activation,'_threads',{})
    first=activation.prepare({},base=tmp_path);second=activation.prepare({},base=tmp_path)
    assert first==second and first['state']=='preparing' and first['total_documents']==794
    assert first['completed_documents']==first['posted_documents']==first['held_documents']==0
    assert len(jobs)==1
    with pytest.raises(instances.SampleBuildError):activation.open_ready(tmp_path)
    with pytest.raises(ValueError):activation.prepare({'directory':'foreign'},base=tmp_path)
    with pytest.raises(ValueError):activation.status({'passphrase':'foreign'},base=tmp_path)


def test_legacy_sample_location_is_preserved(tmp_path):
    legacy=tmp_path/'sample-vault';legacy.mkdir();(legacy/'events.jsonl').write_text('legacy retained')
    assert activation._base(tmp_path)==legacy/'versioned'
    assert (legacy/'events.jsonl').read_text()=='legacy retained'


def test_retry_does_not_republish_previous_failed_instance(tmp_path,monkeypatch):
    root=activation._base(tmp_path)
    previous=root/'sample-vaults'/instances.VERSION/('a'*32)
    previous.mkdir(parents=True,mode=0o700)
    root.chmod(0o700)
    instances._write(previous/'sample-failed.json',{'state':'failed'})
    activation._activate_pointer(root,previous)
    class HeldThread:
        def __init__(self,**kwargs):self.alive=False
        def start(self):self.alive=True
        def is_alive(self):return self.alive
    monkeypatch.setattr(activation,'Thread',HeldThread)
    monkeypatch.setattr(activation,'_threads',{})
    monkeypatch.setattr(activation,'_errors',set())
    monkeypatch.setattr(activation,'_attempt_instances',{})
    assert activation.status(base=tmp_path)['state']=='failed'
    current=activation.prepare(base=tmp_path)
    assert current['state']=='preparing' and current['completed_documents']==0
    assert activation.status(base=tmp_path)==current
    assert json.loads((previous/'sample-failed.json').read_text())=={'state':'failed'}


def test_preallocation_failure_retains_previous_receipt_and_fails_new_attempt(tmp_path,monkeypatch):
    root=activation._base(tmp_path)
    previous=root/'sample-vaults'/instances.VERSION/('b'*32)
    previous.mkdir(parents=True,mode=0o700);root.chmod(0o700)
    activation._activate_pointer(root,previous)
    monkeypatch.setattr(activation,'_attempt_instances',{str(root):None})
    monkeypatch.setattr(activation,'_errors',set())
    def fail(*args,**kwargs):raise RuntimeError('private failure detail')
    monkeypatch.setattr(activation,'build_instance',fail)
    activation._prepare(root)
    current=activation.status(base=tmp_path)
    assert current['state']=='failed' and current['completed_documents']==0
    assert not (previous/'sample-failed.json').exists()
    assert 'private failure detail' not in current['message']


def test_incomplete_retained_preparation_without_live_worker_fails_closed(tmp_path,monkeypatch):
    root=activation._base(tmp_path)
    previous=root/'sample-vaults'/instances.VERSION/('c'*32)
    previous.mkdir(parents=True,mode=0o700);root.chmod(0o700)
    activation._activate_pointer(root,previous)
    monkeypatch.setattr(activation,'_threads',{})
    monkeypatch.setattr(activation,'_attempt_instances',{})
    current=activation.status(base=tmp_path)
    assert current['state']=='failed' and current['phase']=='failed'


def test_sample_reference_is_backend_owned_and_regular_vault_uses_wallclock():
    import datetime
    assert activation.reference_day(SimpleNamespace(_sample_reference_day='2026-01-01'))=='2026-01-01'
    assert activation.reference_day(SimpleNamespace())==datetime.date.today().isoformat()
    assert activation.reference_day(SimpleNamespace(_sample_reference_day='1900-01-01'))==datetime.date.today().isoformat()


def test_session_financial_reference_does_not_retime_audit():
    from viva.session import Session
    from viva.ledger import LedgerProjection
    from viva.tools import default_registry
    from viva.answer_program.compiler import CompilationResult,CompileExchange
    contexts=[];events=[]
    class Compiler:
        def compile(self,context):
            contexts.append(context)
            return CompilationResult(None,None,(CompileExchange('fixture',{},'refused'),),failure_tag='fixture_refusal')
    session=Session(default_registry(LedgerProjection([])),lambda *args:Compiler(),
        ledger=SimpleNamespace(append=lambda event:events.append(event)),
        today=lambda:'2030-04-02',reference_today=lambda:'2026-01-01')
    session.ask('A control question with no financial answer.')
    assert contexts[0].today=='2026-01-01'
    assert len(events)==1 and events[0].event_type=='ReadRecorded'
    assert events[0].occurred_at=='2030-04-02' and events[0].body['phase']=='speak'


def test_opened_sample_initial_and_refreshed_registries_bind_financial_reference(monkeypatch):
    import datetime
    from viva.desktop_bridge.conversation_actions import _session_for
    from viva.ledger import LedgerProjection
    from viva.investment import tool as investment_tool
    from viva.retirement_funding import tool as retirement_tool
    from viva.tools.envelope import refusal
    projection=LedgerProjection([])
    dates=[]
    monkeypatch.setattr(projection,'obligations',lambda day:dates.append(('query',day)) or [])
    def capture(kind):
        def read(runtime,args,today):
            dates.append((kind,today))
            return refusal('read_'+kind,'control','Date binding control; no financial result.')
        return read
    monkeypatch.setattr(investment_tool,'runtime_result',capture('investment'))
    def retirement_result(connection,frontier,args,run_token,today,**kwargs):
        dates.append(('retirement',today))
        return refusal('read_retirement_funding','control','Date binding control; no financial result.')
    monkeypatch.setattr(retirement_tool,'result',retirement_result)
    vault=SimpleNamespace(_sample_reference_day='2026-01-01',
        ledger=SimpleNamespace(projection=lambda:projection))
    session=_session_for(vault,SimpleNamespace(model=''),lambda *args:None,None)
    for registry in (session._registry,session._registry_factory()):
        registry.instrument_runtime.revision=SimpleNamespace()
        registry.query_executor.sources.get('obligations').read()
        registry._specs['read_investment_evidence'].fn({})
        registry._specs['read_retirement_funding'].fn({})
    assert dates==[('query','2026-01-01'),('investment','2026-01-01'),
        ('retirement','2026-01-01')]*2
    assert session._today()==datetime.date.today().isoformat()


def test_bridge_preparation_status_are_explicit_and_open_refuses_before_ready(monkeypatch):
    import io
    from viva.desktop_bridge.__main__ import Sidecar
    from viva.surface import CURRENT_PROTOCOL
    seen=[]
    waiting={'state':'preparing','sample_version':instances.VERSION,'completed_documents':2,
        'total_documents':794,'posted_documents':1,'held_documents':1,'phase':'capturing','message':'Preparing.'}
    def prepare(payload):seen.append(('prepare',payload));return waiting
    def status(payload):seen.append(('status',payload));return waiting
    monkeypatch.setattr(activation,'prepare',prepare)
    monkeypatch.setattr(activation,'status',status)
    def not_ready(*args,**kwargs):raise instances.SampleBuildError('sample preparation has not completed')
    monkeypatch.setattr(activation,'open_ready',not_ready)
    bridge=Sidecar(io.StringIO())
    def call(name):
        frame={'protocol':CURRENT_PROTOCOL.wire(),'request_id':name,'operation':name,'payload':{}}
        return json.loads(bridge.handle(json.dumps(frame))[0])
    for name in ('bridge.sample.prepare','bridge.sample.status'):
        response=call(name)
        assert response['ok'] and response['result']==waiting
    response=call('bridge.open_demo_vault')
    assert not response['ok'] and response['error']['code']=='sample_vault_unopened'
    assert seen==[('prepare',{}),('status',{})] and bridge._vault is None
