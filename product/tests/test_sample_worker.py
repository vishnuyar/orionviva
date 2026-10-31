"""Closed sample worker dispatch and command controls; no sample construction."""
from __future__ import annotations

import builtins
import io
import json
import os
from pathlib import Path
import runpy
import shutil
import sys
from types import ModuleType, SimpleNamespace

import pytest

from viva.sample import instances, worker
from viva.sample.resources import VERSION


@pytest.fixture
def instance(tmp_path):
    base = tmp_path/'base'; base.mkdir(mode=0o700)
    parent = base/'sample-vaults'; parent.mkdir(mode=0o700)
    version = parent/VERSION; version.mkdir(mode=0o700)
    path = version/('a'*32); path.mkdir(mode=0o700)
    for name in ('home','learned','learned/profiles','tmp'):
        (path/name).mkdir(mode=0o700)
    (path/'empty.env').touch(mode=0o600)
    staging = path/'sample-staging.json'
    staging.write_text(json.dumps({'version':VERSION,'instance_id':path.name}))
    staging.chmod(0o600)
    return path


def request(instance, operation='build', **extra):
    return json.dumps({'operation':operation,'instance':str(instance),**extra}).encode()


@pytest.mark.parametrize('operation',['build','restore','reopen'])
def test_closed_worker_dispatches_only_fixed_operations_in_key_free_environment(instance,monkeypatch,operation):
    if operation == 'reopen':
        (instance/'vault').mkdir(mode=0o700)
        (instance/'sample-instance.json').touch(mode=0o600)
    # Do not mutate the test runner's actual process environment.
    monkeypatch.setattr(os,'environ',{'MODEL_API_KEY':'synthetic-poison','_PYI_ARCHIVE_FILE':'foreign'})
    seen=[]
    def selected(path):
        seen.append(path)
        assert path==instance
        assert set(os.environ)=={'PATH','HOME','MERCHANTCORE_HOME','VIVA_PROFILES','VIVA_CATALOG','VIVA_ENV_FILE','LANG','TMPDIR'}
        assert os.environ['VIVA_ENV_FILE']==str(instance/'empty.env')
        assert os.environ['HOME']==str(instance/'home')
        return {'state':'controlled-dispatch'}
    def denied(*args):raise AssertionError('wrong operation dispatched')
    monkeypatch.setattr(instances,'_worker',selected if operation=='build' else denied)
    monkeypatch.setattr(instances,'_restore_worker',selected if operation=='restore' else denied)
    monkeypatch.setattr(instances,'_reopen_worker',selected if operation=='reopen' else denied)
    assert worker.run_request(request(instance,operation))=={'state':'controlled-dispatch'}
    assert seen==[instance]


@pytest.mark.parametrize('change',['extra','limit','credential','interpreter','importpath','bad_operation','relative','bad_hex','symlink','public_mode','staging','nonempty_env','existing_vault'])
def test_worker_refuses_unowned_or_open_requests_before_constructor(instance,monkeypatch,change):
    value={'operation':'build','instance':str(instance)}
    if change in ('extra','limit','credential','interpreter','importpath'):value[change]='rejected'
    elif change=='bad_operation':value['operation']='eval'
    elif change=='relative':value['instance']='relative/sample-vaults/'+VERSION+'/'+('a'*32)
    elif change=='bad_hex':
        target=instance.with_name('g'*32);instance.rename(target);value['instance']=str(target)
    elif change=='symlink':
        target=instance.with_name('b'*32);target.symlink_to(instance,target_is_directory=True);value['instance']=str(target)
    elif change=='public_mode':instance.chmod(0o755)
    elif change=='staging':(instance/'sample-staging.json').write_text('{}')
    elif change=='nonempty_env':(instance/'empty.env').write_text('MODEL_API_KEY=synthetic-poison')
    elif change=='existing_vault':(instance/'vault').mkdir(mode=0o700)
    monkeypatch.setattr(instances,'_worker',lambda *args:pytest.fail('constructor must not run'))
    monkeypatch.setattr(instances,'_reopen_worker',lambda *args:pytest.fail('reopen must not run'))
    with pytest.raises((ValueError,OSError)):
        worker.run_request(json.dumps(value).encode())


@pytest.mark.parametrize('encoded',[b'',b'x'*4097,b'[]',b'null',b'\xff',b'{"operation":"build","operation":"reopen","instance":"/tmp/x"}'])
def test_worker_request_bound_and_closed_json_before_constructor(encoded,monkeypatch):
    monkeypatch.setattr(instances,'_worker',lambda *args:pytest.fail('constructor must not run'))
    with pytest.raises((ValueError,OSError)):
        worker.run_request(encoded)


def test_main_reads_only_one_bounded_request_and_reports_generic_failure(monkeypatch):
    output=io.BytesIO();errors=io.StringIO()
    monkeypatch.setattr(sys,'stdin',SimpleNamespace(buffer=io.BytesIO(b'x'*4097)))
    monkeypatch.setattr(sys,'stdout',SimpleNamespace(buffer=output))
    monkeypatch.setattr(sys,'stderr',errors)
    assert worker.main()==1
    assert output.getvalue()==b''
    assert errors.getvalue()=='Sample worker could not complete its closed request.\n'


@pytest.mark.parametrize('frozen',[False,True])
def test_launch_uses_source_python_flags_or_exact_frozen_application_entry(instance,monkeypatch,frozen):
    monkeypatch.setattr(sys,'frozen',frozen,raising=False)
    identity={'controlled':'runtime'}
    monkeypatch.setattr(instances,'_runtime_identity',lambda:identity)
    calls=[]
    def run(command,**kwargs):
        calls.append((command,kwargs))
        return SimpleNamespace(returncode=0,stdout=json.dumps({'runtime_identity':identity}).encode())
    monkeypatch.setattr(instances.subprocess,'run',run)
    assert instances._launch(instance,'build')['runtime_identity']==identity
    command,options=calls[0]
    assert set(options['env'])=={'PATH','HOME','MERCHANTCORE_HOME','VIVA_PROFILES','VIVA_CATALOG','VIVA_ENV_FILE','LANG','TMPDIR'}
    assert options['cwd']==instance
    if frozen:
        assert command==[sys.executable,'--sample-worker']
        assert json.loads(options['input'])=={'operation':'build','instance':str(instance)}
        assert 'stdin' not in options
    else:
        assert command[:5]==[sys.executable,'-I','-S','-B','-c']
        assert command[-3:]==[str(instance),'build','']
        assert isinstance(json.loads(command[-4]),list)
        assert options['stdin']==instances.subprocess.DEVNULL and 'input' not in options


@pytest.mark.parametrize('operation,limit',[('build',1),('reopen',1),('unknown',None)])
def test_frozen_launch_rejects_partial_or_generic_execution(instance,monkeypatch,operation,limit):
    monkeypatch.setattr(sys,'frozen',True,raising=False)
    monkeypatch.setattr(instances.subprocess,'run',lambda *a,**k:pytest.fail('must not spawn'))
    with pytest.raises(instances.SampleBuildError):instances._launch(instance,operation,limit)


@pytest.fixture
def frozen_packages(tmp_path,monkeypatch):
    root=tmp_path/'extraction';root.mkdir()
    for name in ('viva','vivacore','merchantcore'):
        package=root/name;package.mkdir();(package/'__init__.py').write_text('raw package '+name)
        (package/'source.py').write_text('raw source '+name)
        module=ModuleType(name);module.__file__=str(package/'__init__.py')
        monkeypatch.setitem(sys.modules,name,module)
    executable=tmp_path/'application';executable.write_bytes(b'controlled-frozen-executable')
    monkeypatch.setattr(sys,'executable',str(executable))
    monkeypatch.setattr(sys,'frozen',True,raising=False)
    monkeypatch.setattr(sys,'_MEIPASS',str(root),raising=False)
    return root,executable


def test_frozen_identity_ignores_only_extraction_directory_name(frozen_packages,monkeypatch,tmp_path):
    root,executable=frozen_packages;before=instances._runtime_identity()
    other=tmp_path/'other-extraction';shutil.copytree(root,other)
    monkeypatch.setattr(sys,'_MEIPASS',str(other))
    for name in ('viva','vivacore','merchantcore'):
        monkeypatch.setattr(sys.modules[name],'__file__',str(other/name/'__init__.py'))
    assert instances._runtime_identity()==before
    assert before['roots']=={name:'frozen:'+name for name in ('viva','vivacore','merchantcore')}
    assert before['file_count']==6 and before['executable']==str(executable)


@pytest.mark.parametrize('change',['foreign_package','package_symlink','extraction_symlink'])
def test_frozen_identity_refuses_noncanonical_or_foreign_roots(frozen_packages,monkeypatch,tmp_path,change):
    root,_=frozen_packages
    if change=='foreign_package':
        foreign=tmp_path/'foreign';foreign.mkdir();(foreign/'__init__.py').write_text('foreign')
        monkeypatch.setattr(sys.modules['viva'],'__file__',str(foreign/'__init__.py'))
    elif change=='package_symlink':
        foreign=tmp_path/'foreign';(root/'viva').rename(foreign);(root/'viva').symlink_to(foreign,target_is_directory=True)
    else:
        alias=tmp_path/'alias';alias.symlink_to(root,target_is_directory=True);monkeypatch.setattr(sys,'_MEIPASS',str(alias))
    with pytest.raises(instances.SampleBuildError):instances._runtime_identity()


@pytest.mark.parametrize('change',['missing_raw','changed_raw','different_executable'])
def test_launch_refuses_changed_child_runtime_identity(instance,frozen_packages,monkeypatch,change):
    root,executable=frozen_packages
    def run(command,**kwargs):
        if change=='missing_raw':(root/'viva/source.py').unlink()
        elif change=='changed_raw':(root/'viva/source.py').write_text('changed raw bytes')
        else:executable.write_bytes(b'different executable')
        return SimpleNamespace(returncode=0,stdout=json.dumps({'runtime_identity':instances._runtime_identity()}).encode())
    monkeypatch.setattr(instances.subprocess,'run',run)
    with pytest.raises(instances.SampleBuildError,match='runtime identity does not match'):
        instances._launch(instance,'build')


@pytest.mark.parametrize('arguments',[['--sample-worker'],['--sample-worker','extra'],['--sample-worker=foreign']])
def test_application_worker_dispatch_precedes_configuration_and_vault(monkeypatch,arguments):
    entry=Path(instances.__file__).parent.parent/'desktop_bridge/__main__.py'
    monkeypatch.setattr(sys,'argv',['application',*arguments]);called=[]
    monkeypatch.setattr(worker,'main',lambda:called.append(True) or 7)
    original=builtins.__import__
    def guarded(name,*args,**kwargs):
        if name in ('viva.configuration','viva.vault','viva.desktop_bridge.handlers'):
            raise AssertionError('configuration/vault imported before worker dispatch')
        return original(name,*args,**kwargs)
    monkeypatch.setattr(builtins,'__import__',guarded)
    with pytest.raises(SystemExit) as result:runpy.run_path(str(entry),run_name='__main__')
    assert result.value.code==(7 if arguments==['--sample-worker'] else 'invalid sample worker arguments')
    assert called==([True] if arguments==['--sample-worker'] else [])


def test_real_isolated_source_parent_builds_only_one_engineering_document(tmp_path):
    """Actual -I -S parent and worker import dependencies without site startup."""
    import cryptography
    import subprocess

    root=Path(__file__).resolve().parents[2]
    dependency=Path(cryptography.__file__).resolve().parent.parent
    task=tmp_path/'isolated-source';task.mkdir(mode=0o700)
    for name in ('home','learned','profiles','tmp'):(task/name).mkdir(mode=0o700)
    empty=task/'empty.env';empty.touch(mode=0o600)
    environment={'PATH':'/usr/bin:/bin','HOME':str(task/'home'),
        'MERCHANTCORE_HOME':str(task/'learned'),'VIVA_PROFILES':str(task/'profiles'),
        'VIVA_CATALOG':str(task/'learned/catalog.json'),'VIVA_ENV_FILE':str(empty),
        'LANG':'en_US.UTF-8','TMPDIR':str(task/'tmp')}
    script='''import json,sys
from pathlib import Path
root=Path(sys.argv[1]);dependency=Path(sys.argv[2]);task=Path(sys.argv[3])
sys.path[:0]=[str(root/'product'),str(root/'core'),str(root/'merchant'),str(root/'bench'),str(dependency)]
assert sys.flags.isolated and sys.flags.no_site
from viva.sample.instances import build_instance
try:
    path,report=build_instance(task/'instances',engineering_document_limit=1)
except Exception:
    for log in task.glob('instances/sample-vaults/*/*/build-*-stderr.txt'):
        print(log.read_text(),file=sys.stderr)
    raise
print(json.dumps({'instance':str(path),'report':report},sort_keys=True))
'''
    completed=subprocess.run([sys.executable,'-I','-S','-B','-c',script,str(root),str(dependency),str(task)],
        env=environment,cwd=task,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    assert completed.returncode==0,completed.stderr.decode('utf-8','replace')
    value=json.loads(completed.stdout);report=value['report'];instance=Path(value['instance'])
    assert report['state']=='engineering_partial' and report['documents']==1
    assert len(report['outcomes'])==1 and report['outcomes'][0]['document_id']=='D0001'
    measured=report['outcomes'][0]
    assert measured['capture_seconds']>0 and measured['elapsed_seconds']>=measured['capture_seconds']
    assert measured['event_count']==report['event_identity'][0]
    assert report['capture_seconds']==measured['capture_seconds']
    assert report['replay_agreement']['state']=='equal'
    assert report['replay_agreement']['event_identity']==report['event_identity']
    assert set(report['phase_seconds'])=={'sweep','sql','source_completion'}
    assert not (instance/'sample-instance.json').exists()
    assert (instance/'sample-incomplete.json').is_file()
    assert not list((task/'instances').glob('**/five-year-sample-active.json'))


@pytest.mark.parametrize('defect',['file_symlink','package_symlink','spec_mismatch','relative','directory','nonpackage'])
def test_source_dependency_origin_rejects_noncanonical_or_nonordinary_paths(tmp_path,monkeypatch,defect):
    import cryptography

    package=tmp_path/('foreign' if defect=='nonpackage' else 'cryptography')
    package.mkdir();origin=package/'__init__.py';origin.write_text('synthetic dependency origin fixture')
    if defect=='file_symlink':
        target=tmp_path/'ordinary.py';target.write_text('synthetic');origin.unlink();origin.symlink_to(target)
    elif defect=='package_symlink':
        target=tmp_path/'ordinary-package';package.rename(target);package.symlink_to(target,target_is_directory=True)
    elif defect=='directory':origin.unlink();origin.mkdir()
    if defect=='relative':origin=Path('cryptography/__init__.py')
    monkeypatch.setattr(cryptography,'__file__',str(origin))
    monkeypatch.setattr(cryptography.__spec__,'origin','mismatch' if defect=='spec_mismatch' else str(origin))
    with pytest.raises(instances.SampleBuildError):instances._source_dependency_root()
