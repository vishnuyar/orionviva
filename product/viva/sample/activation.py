"""Prepare and open the versioned original-document sample without provider work."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
from threading import RLock, Thread

from .resources import VERSION
from .instances import SampleBuildError, _ordinary, build_instance, reopen_instance

REFERENCE_DAY = '2026-01-01'
RECORDED_THROUGH = '2025-12-31'
TOTAL_DOCUMENTS = 794
_lock = RLock()
_threads: dict[str, Thread] = {}
_errors: set[str] = set()
_attempt_instances: dict[str, Path | None] = {}


def _base(base=None):
    from ..demo import demo_home
    # Preserve older built-in vaults. Their content and permissions are not a
    # versioned preparation directory and must never be reused as this sample.
    return (demo_home(base)/'versioned').absolute()


def _pointer(base):
    path=base/'five-year-sample-active.json'
    if not path.exists():
        return None
    _ordinary(path,False)
    value=json.loads(path.read_text())
    if (type(value) is not dict or set(value)!={'version','instance_id'}
            or value['version']!=VERSION or type(value['instance_id']) is not str
            or re.fullmatch('[0-9a-f]{32}',value['instance_id']) is None):
        raise SampleBuildError('sample activation receipt is invalid')
    instance=base/'sample-vaults'/VERSION/value['instance_id']
    _ordinary(instance)
    return instance


def _activate_pointer(base,instance):
    temporary=base/('sample-pointer-'+instance.name+'.tmp')
    fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w') as stream:
        json.dump({'version':VERSION,'instance_id':instance.name},stream)
        stream.flush();os.fsync(stream.fileno())
    os.replace(temporary,base/'five-year-sample-active.json')


def _status(base):
    key=str(base)
    # A retry begins before the worker allocates its new directory. Do not
    # publish the previous attempt's failure or counters during that interval.
    instance=(_pointer(base) if key not in _attempt_instances
              else _attempt_instances[key])
    progress=None
    if instance is not None:
        for path in sorted(instance.glob('progress-[0-9][0-9][0-9][0-9].json'),reverse=True):
            _ordinary(path,False)
            try:progress=json.loads(path.read_text())
            except (ValueError,OSError):continue
            break
    completed=progress.get('completed_documents',0) if progress else 0
    posted=progress.get('posted_documents',0) if progress else 0
    held=progress.get('held_documents',0) if progress else 0
    if any(type(value) is not int or not 0<=value<=TOTAL_DOCUMENTS for value in (completed,posted,held)):
        raise SampleBuildError('sample progress receipt is invalid')
    state='preparing';phase='capturing' if completed else 'validating'
    message='Preparing the original five-year sample documents.'
    if instance is not None and (instance/'sample-instance.json').exists():
        _ordinary(instance/'sample-instance.json',False)
        record=json.loads((instance/'sample-instance.json').read_text())
        from .resources import MANIFEST_SHA256,READINGS_SHA256
        if (record.get('state')!='ready' or record.get('documents')!=TOTAL_DOCUMENTS
                or record.get('version')!=VERSION or record.get('manifest_sha256')!=MANIFEST_SHA256
                or record.get('readings_sha256')!=READINGS_SHA256 or record.get('readiness_failures')):
            raise SampleBuildError('sample readiness receipt is incomplete')
        from .instances import _runtime_identity
        if record.get('runtime_identity')!=_runtime_identity():
            return {'state':'failed','sample_version':VERSION,'completed_documents':completed,
                'total_documents':TOTAL_DOCUMENTS,'posted_documents':posted,'held_documents':held,
                'phase':'failed','message':'The sample needs preparation for this application version.'}
        state=phase='ready';completed=TOTAL_DOCUMENTS
        message='The five-year sample is ready.'
    elif instance is not None and any((instance/name).exists() for name in ('sample-failed.json','sample-incomplete.json')):
        state=phase='failed'
        message='The sample could not complete its source checks. Its preparation records have been retained.'
    elif instance is not None and completed==TOTAL_DOCUMENTS:
        phase='checking';message='Checking source evidence and preparing the current financial view.'
    if instance is not None and state=='preparing':
        thread=_threads.get(key)
        if thread is None or not thread.is_alive():
            state=phase='failed'
            message='The retained sample preparation is incomplete. Its records have been retained.'
    if str(base) in _errors:
        state=phase='failed';message='The sample preparation could not complete. Its records have been retained.'
    return {'state':state,'sample_version':VERSION,'completed_documents':completed,
        'total_documents':TOTAL_DOCUMENTS,'posted_documents':posted,'held_documents':held,
        'phase':phase,'message':message}


def status(payload=None,*,base=None):
    if payload:
        raise ValueError('sample status does not accept fields')
    with _lock:
        try:return _status(_base(base))
        except (ValueError,OSError):
            return {'state':'failed','sample_version':VERSION,'completed_documents':0,
                'total_documents':TOTAL_DOCUMENTS,'posted_documents':0,'held_documents':0,
                'phase':'failed','message':'The retained sample preparation is unavailable.'}


def _prepare(base):
    instance=None
    def allocated(value):
        nonlocal instance
        with _lock:
            _activate_pointer(base,value)
            instance=value
            _attempt_instances[str(base)]=value
    try:
        build_instance(base,on_instance=allocated)
    except BaseException:
        # Worker retains its detailed failure privately. The status interface
        # exposes only the stable sanitized state, never paths or exception text.
        with _lock:_errors.add(str(base))
        if instance is not None and not any((instance/name).exists() for name in ('sample-failed.json','sample-incomplete.json')):
            from .instances import _write
            _write(instance/'sample-failed.json',{'state':'failed','reason':'preparation_failed'})


def prepare(payload=None,*,base=None):
    if payload:
        raise ValueError('sample preparation does not accept fields')
    root=_base(base);key=str(root)
    with _lock:
        current=_threads.get(key)
        if current is not None and current.is_alive():return _status(root)
        existing=_status(root)
        if existing['state']=='ready':return existing
        _errors.discard(key)
        _attempt_instances[key]=None
        thread=Thread(target=_prepare,args=(root,),name='five-year-sample-preparation',daemon=True)
        _threads[key]=thread;thread.start()
        return _status(root)


def open_ready(base=None):
    root=_base(base)
    with _lock:
        current=_status(root)
        if current['state']!='ready':
            raise SampleBuildError('sample preparation has not completed')
        instance=_pointer(root)
    reopen_instance(instance)
    from ..vault import Vault
    from .instances import PASSPHRASE
    from ..demo import _prepare_demo_read_store
    vault=Vault.open(instance/'vault',PASSPHRASE,create=False)
    try:
        _prepare_demo_read_store(vault)
        vault._sample_reference_day=REFERENCE_DAY
        vault._sample_recorded_through=RECORDED_THROUGH
        return vault,False
    except BaseException:
        vault.close();raise


def reference_day(vault):
    import datetime
    day=getattr(vault,'_sample_reference_day','')
    return day if day==REFERENCE_DAY else datetime.date.today().isoformat()
