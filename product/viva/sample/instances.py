"""Construct isolated sample instances without switching the caller's stores."""
from __future__ import annotations
import fcntl
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import uuid
from .resources import VERSION

PASSPHRASE = 'a-sample-vault-anybody-may-open'

class SampleBuildError(ValueError): pass

def _ordinary(path, directory=True):
    info=path.lstat()
    if (stat.S_ISLNK(info.st_mode) or (directory and not stat.S_ISDIR(info.st_mode))
            or (not directory and not stat.S_ISREG(info.st_mode))
            or info.st_uid!=os.getuid() or info.st_mode & 0o077):
        raise SampleBuildError('sample object is not private and ordinary')

def _write(path,value):
    temporary=path.with_name(path.name+'.writing-'+uuid.uuid4().hex)
    fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    try:
        with os.fdopen(fd,'w') as stream:
            json.dump(value,stream,sort_keys=True);stream.flush();os.fsync(stream.fileno())
        # Publish a complete receipt atomically, while preserving exclusive
        # historical names: an existing receipt is never overwritten.
        os.link(temporary,path)
        directory_fd = os.open(path.parent, os.O_RDONLY|os.O_NOFOLLOW)
        try: os.fsync(directory_fd)
        finally: os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)

def _runtime_identity():
    import hashlib
    import viva, vivacore, merchantcore
    rows = {}
    roots = {}
    frozen = getattr(sys, 'frozen', False) is True
    if frozen:
        extraction = Path(sys._MEIPASS)
        if (not extraction.is_absolute() or not extraction.is_dir()
                or extraction.resolve(strict=True) != extraction):
            raise SampleBuildError('sample frozen extraction root is not canonical')
    for module in (viva, vivacore, merchantcore):
        root = Path(module.__file__).resolve().parent
        if frozen:
            origin = Path(module.__file__)
            expected = extraction / module.__name__
            if (not origin.is_absolute() or origin.resolve() != origin
                    or root != expected or not root.is_dir()
                    or root.resolve(strict=True) != root):
                raise SampleBuildError('sample frozen package root is foreign or noncanonical')
            # One-file children can extract the same executable to another
            # private temporary directory. Identity remains bound to every
            # package byte and the executable, rather than that temporary name.
            roots[module.__name__] = 'frozen:' + module.__name__
        else:
            roots[module.__name__] = str(root)
        for member in root.rglob('*'):
            if '__pycache__' in member.parts or member.suffix == '.pyc': continue
            if member.is_symlink(): raise SampleBuildError('sample runtime contains a symlink')
            if member.is_file():
                key = module.__name__ + '/' + str(member.relative_to(root))
                rows[key] = hashlib.sha256(member.read_bytes()).hexdigest()
                if len(rows)>10000: raise SampleBuildError('sample runtime exceeds its file bound')
    encoded = json.dumps(rows,sort_keys=True,separators=(',',':')).encode()
    executable = Path(sys.executable).resolve()
    return {'roots':roots,'files_sha256':hashlib.sha256(encoded).hexdigest(),
            'file_count':len(rows),'python':sys.version,
            'executable':str(executable),'executable_sha256':hashlib.sha256(executable.read_bytes()).hexdigest()}


def completion_failures(pack, projection):
    """Require actual supported source facets, preserving explicit unavailable facts."""
    from decimal import Decimal
    from ..ledger.instruments import reference_accounts
    states = {}
    for state in projection.instrument_component_states().values():
        if state.doc_id in states:
            raise SampleBuildError('sample source has ambiguous component state')
        states[state.doc_id] = state
    posted = projection.posted_doc_ids()
    allocations = tuple(projection.instrument_allocations().values())
    failures = []
    for document in pack.documents:
        identifier = document['sha256']; row = pack.readings[identifier]
        payload = row['envelope']['parser_input']
        family = document['family']
        if family not in ('cd-opening', 'cd', 'cd-maturity', 'mortgage', 'refinance', 'property-tax'):
            if identifier not in posted:
                failures.append({'document_id':document['id'],'reason':'ordinary_source_unposted'})
            continue
        state = states.get(identifier)
        if state is None:
            failures.append({'document_id':document['id'],'reason':'source_components_missing'})
            continue
        names=[component.component for component in state.components]
        required=set()
        if family in ('cd-opening','cd','cd-maturity'):
            required={'deposit_balance'}
            if payload.get('terms') is not None: required.add('deposit_terms')
            if family!='cd-opening':
                required.update('counterpart:'+movement['reference']['raw']
                    for movement in payload.get('movements',())
                    if movement['kind'] in ('funding','redemption'))
        elif family=='mortgage':
            required={'principal_balance','escrow_balance'}
            if payload.get('terms') is not None: required.add('mortgage_terms')
            required.update('payment:'+payment['reference']['raw'] for payment in payload.get('payments',()))
            required.update('known_allocation:'+payment['reference']['raw']
                for payment in payload.get('payments',()) if payment.get('fees') is None)
        elif family=='refinance':
            required={'settlement_sources_uses','settlement_fees','financed_fees','old_loan_zero'}
            if payload.get('fee_payment_reference') is not None: required.add('settlement_cash_fee')
        elif family=='property-tax': required={'tax_paid','tax_payment_link'}
        if len(names)!=len(set(names)) or not required.issubset(names):
            failures.append({'document_id':document['id'],'reason':'required_source_component_set_incomplete'})
        for component in state.components:
            certificate_absence = (family == 'cd-opening' and payload.get('subtype') == 'opening'
                and payload.get('opening') is None and payload.get('closing') is None
                and component.component == 'deposit_balance'
                and component.disposition.value == 'held'
                and component.reason == 'missing printed components: opening, closing')
            settlement_absence = (family == 'refinance' and payload.get('old_closing_principal') is None
                and component.component == 'old_loan_zero'
                and component.disposition.value == 'unavailable'
                and component.reason == 'payoff witness required')
            known_payment_absence = False
            if (family == 'mortgage' and component.disposition.value == 'held'
                    and component.reason == 'missing printed components: fees'):
                for payment in payload.get('payments',()):
                    reference=payment['reference']['raw']
                    if component.component != 'payment:'+reference or payment.get('fees') is not None:
                        continue
                    matches=[allocation for allocation in allocations if hasattr(allocation,'receipt')
                        and allocation.payment.total.source.doc_id == identifier
                        and allocation.payment.reference.value == reference]
                    accepted=any(item.component=='known_allocation:'+reference
                        and item.disposition.value=='accepted' for item in state.components)
                    if len(matches)==1 and accepted:
                        actual=matches[0].payment
                        known_payment_absence=(actual.fees is None
                            and actual.dated.value==payment['dated']['raw']
                            and actual.funding_account_reference.value==payment['funding_account_reference']['raw']
                            and all(getattr(actual,name).value==Decimal(payment[name]['raw'])
                                and getattr(actual,name).currency==row['currency']
                                for name in ('total','principal','interest','escrow')))
            if component.disposition.value != 'accepted' and not (certificate_absence or settlement_absence or known_payment_absence):
                failures.append({'document_id':document['id'],'component':component.component,
                                 'reason':'required_source_component_unaccepted'})
        if family == 'refinance':
            old = payload['old_loan']; reference = old['account_reference']['raw']
            candidates = [account for account in reference_accounts(projection, reference)
                if projection.account_info(account).kind == 'liability'
                and projection.account_info(account).currency == row['currency']
                and projection.account_info(account).institution.casefold().strip() == old['institution']['raw'].casefold().strip()
                and old['holder']['raw'].casefold().strip() in {name.casefold().strip() for name in projection.account_info(account).names}]
            witnesses = []
            for other in pack.documents:
                if other['family'] != 'mortgage' or other['account_ref'] != reference: continue
                source = pack.readings[other['sha256']]['envelope']['parser_input']
                closing = source.get('closing_principal')
                if closing is None or Decimal(closing['raw']) != 0: continue
                matching = [movement for movement in source['principal_movements']
                    if movement['kind'] == 'payoff'
                    and movement['reference']['raw'] == payload['reference']['raw']
                    and movement['dated']['raw'] == payload['dated']['raw']
                    and Decimal(movement['amount']['raw']) == Decimal(payload['old_payoff_principal']['raw'])]
                current = states.get(other['sha256'])
                if matching and current is not None and any(component.component == 'principal_balance'
                        and component.disposition.value == 'accepted' for component in current.components):
                    witnesses.append(other['sha256'])
            if len(candidates) != 1 or not witnesses or projection.running_balance(candidates[0]) != 0:
                failures.append({'document_id':document['id'],'reason':'refinance_closeout_unproven'})
    return failures


def verify_replay_agreement(ledger):
    """Require the live fold to equal a fresh authenticated financial replay."""
    import time
    from ..ledger.projection import LedgerProjection
    started = time.monotonic()
    with ledger._lock:
        before = ledger.store.authenticated_identity()
        current = ledger.projection()
        events, identity = ledger.store.fork().snapshot_events_with_identity()
        replay = LedgerProjection(events, resolve_keys=current.core._resolve_keys)
        if identity != before:
            raise SampleBuildError('sample replay revision changed')
        families = []
        def same(name, actual, expected):
            if actual != expected:
                raise SampleBuildError('sample replay disagrees: '+name)
            families.append(name)
        same('accounts', current.accounts(), replay.accounts())
        same('balances', {account:current.balance(account) for account in current.accounts()},
                        {account:replay.balance(account) for account in replay.accounts()})
        same('movements', current.movements(), replay.movements())
        same('positions', current.positions(), replay.positions())
        same('instrument_allocations', current.instrument_allocations(), replay.instrument_allocations())
        same('instrument_component_states', current.instrument_component_states(), replay.instrument_component_states())
        # Lazy query caches and callable ownership guards carry no financial
        # facts; event-folded dependency indexes remain part of the comparison.
        ephemeral = {'apply', '_resolve_keys', '_mkeys', '_mkeys_of', '_statements',
                     '_own_tokens_cache', '_measurement_sources'}
        current_state = vars(current.core); replay_state = vars(replay.core)
        names = (set(current_state)|set(replay_state))-ephemeral
        for name in sorted(names):
            if name not in current_state or name not in replay_state:
                raise SampleBuildError('sample replay state family differs')
            same('core'+name, current_state[name], replay_state[name])
        same('measurement_source_accounts', current.core._measurement_sources.accounts,
                                           replay.core._measurement_sources.accounts)
        same('measurement_source_accepted', current.core._measurement_sources.accepted,
                                           replay.core._measurement_sources.accepted)
        if ledger.store.authenticated_identity() != identity:
            raise SampleBuildError('sample replay revision changed')
    return {'state':'equal', 'families':families, 'family_count':len(families),
            'event_identity':list(identity), 'seconds':time.monotonic()-started}


def _worker(instance, limit=None):
    import time
    from datetime import datetime, timezone
    from .resources import load_pack, MANIFEST_SHA256, READINGS_SHA256
    from .curation import CuratedReader
    from ..vault import Vault
    from ..ingest import capture_and_ingest, sweep
    from ..demo import _prepare_demo_read_store
    started=time.monotonic();runtime=_runtime_identity();vault=None;outcomes=[]
    try:
        pack=load_pack();resources_done=time.monotonic()
        vault=Vault.open(instance/'vault',PASSPHRASE)
        reader=CuratedReader(pack)
        for document in pack.documents[:limit]:
            original = pack.original(document)
            document_started = time.monotonic()
            result=capture_and_ingest(vault.raw,vault.ledger,original,reader,
                filename=document['file'],captured_at=datetime.now(timezone.utc).isoformat())
            capture_finished = time.monotonic()
            event_count = vault.ledger.store.authenticated_identity()[0]
            outcomes.append({'document_id':document['id'],'doc_id':result.doc_id,
                'action':result.action,'message':result.message,'grade':result.grade,
                'capture_seconds':capture_finished-document_started,
                'elapsed_seconds':capture_finished-started, 'event_count':event_count})
            posted_count=len(vault.ledger.projection().posted_doc_ids())
            _write(instance/f'progress-{len(outcomes):04d}.json',{
                **outcomes[-1], 'completed_documents':len(outcomes),
                'posted_documents':min(posted_count,len(outcomes)),
                'held_documents':max(0,len(outcomes)-posted_count)})
            if result.action=='parked' or result.doc_type=='unknown':
                raise SampleBuildError('required sample source could not be parsed')
        sweep_started = time.monotonic()
        swept=sweep(vault.ledger)
        sweep_seconds = time.monotonic()-sweep_started
        projection=vault.ledger.projection()
        captures=set(projection.captured_docs())
        expected={doc['sha256'] for doc in pack.documents[:limit]}
        if captures!=expected or set(vault.raw.doc_ids())!=expected:
            raise SampleBuildError('sample capture closure is incomplete')
        agreement = verify_replay_agreement(vault.ledger)
        sql_started = time.monotonic()
        _prepare_demo_read_store(vault)
        sql_seconds = time.monotonic()-sql_started
        identity=vault.ledger.store.authenticated_identity()
        checks_started = time.monotonic()
        failures=completion_failures(pack,projection) if limit is None else []
        checks_seconds = time.monotonic()-checks_started
        state='engineering_partial' if limit is not None else 'source_checks_failed' if failures else 'ready'
        report={'contract':'sample-instance-v1','version':VERSION,
            'state':state,'readiness_failures':failures,
            'manifest_sha256':MANIFEST_SHA256,'readings_sha256':READINGS_SHA256,
            'reference_day':'2026-01-01','recorded_through':'2025-12-31',
            'documents':len(captures),'outcomes':outcomes,'sweep':swept,
            'event_identity':list(identity),'runtime_identity':runtime,'resources_seconds':resources_done-started,
            'complete_seconds':time.monotonic()-started,
            'capture_seconds':sum(row['capture_seconds'] for row in outcomes),
            'phase_seconds':{'sweep':sweep_seconds,'sql':sql_seconds,'source_completion':checks_seconds},
            'replay_agreement':agreement,
            'open_holds':projection.open_holds()}
        if _runtime_identity()!=runtime: raise SampleBuildError('sample runtime changed during construction')
        filename='sample-instance.json' if state=='ready' else 'sample-incomplete.json'
        _write(instance/filename,report)
        return report
    except BaseException as error:
        _write(instance/'sample-failed.json',{'state':'failed','completed_documents':len(outcomes),
            'error_type':type(error).__name__,'message':str(error)[:1000]})
        raise
    finally:
        if vault is not None: vault.close()

def _restore_worker(instance, limit=None):
    from .snapshot import restore
    try:
        return restore(instance)
    except BaseException:
        _write(instance/'sample-failed.json', {'state':'failed', 'reason':'prepared_snapshot_invalid'})
        raise


def _source_dependency_root():
    """Use the installed dependency actually imported by this source runtime."""
    import cryptography
    origin = Path(cryptography.__file__)
    specification = cryptography.__spec__
    if (not origin.is_absolute() or origin.name != '__init__.py'
            or origin.parent.name != 'cryptography'
            or specification is None or specification.origin != str(origin)
            or origin.resolve(strict=True) != origin
            or not stat.S_ISREG(origin.lstat().st_mode)):
        raise SampleBuildError('sample dependency origin is not canonical and ordinary')
    root = origin.parent.parent
    if (root.resolve(strict=True) != root or not root.is_dir()
            or not stat.S_ISDIR(root.lstat().st_mode)
            or not stat.S_ISDIR(origin.parent.lstat().st_mode)):
        raise SampleBuildError('sample dependency root is not canonical and ordinary')
    return str(root)


def _launch(instance,operation,limit=None):
    frozen = getattr(sys, 'frozen', False) is True
    if frozen:
        if operation not in ('build', 'restore', 'reopen') or limit is not None:
            raise SampleBuildError('frozen sample worker accepts only complete build, restore or reopen')
        command=[sys.executable, '--sample-worker']
        request=json.dumps({'operation':operation,'instance':str(instance)},sort_keys=True).encode('utf-8')
        if len(request)>4096: raise SampleBuildError('sample worker request exceeds its bound')
    else:
        import viva, vivacore, merchantcore
        roots=[str(Path(module.__file__).resolve().parent.parent) for module in (viva,vivacore,merchantcore)]
        roots.append(_source_dependency_root())
        roots=list(dict.fromkeys(roots))
        if any(not Path(root).is_dir() or str(Path(root).resolve())!=root for root in roots):
            raise SampleBuildError('sample runtime roots are not ordinary installed directories')
        script='import sys,json;sys.path[:0]=json.loads(sys.argv[1]);from viva.sample.instances import _worker,_restore_worker,_reopen_worker;result=({"build":_worker,"restore":_restore_worker,"reopen":_reopen_worker}[sys.argv[3]])(__import__("pathlib").Path(sys.argv[2]),None if sys.argv[4]=="" else int(sys.argv[4]));print(json.dumps(result,sort_keys=True))'
        command=[sys.executable,'-I','-S','-B','-c',script,json.dumps(roots),str(instance),operation,'' if limit is None else str(limit)]
    environment={'PATH':'/usr/bin:/bin','HOME':str(instance/'home'),
        'MERCHANTCORE_HOME':str(instance/'learned'),'VIVA_PROFILES':str(instance/'learned/profiles'),
        'VIVA_CATALOG':str(instance/'learned/catalog.json'),'VIVA_ENV_FILE':str(instance/'empty.env'),
        'LANG':'en_US.UTF-8','TMPDIR':str(instance/'tmp')}
    runtime=_runtime_identity()
    stderr=instance/f'{operation}-{uuid.uuid4().hex}-stderr.txt'
    with stderr.open('xb') as errors:
        os.chmod(stderr,0o600)
        options={'input':request} if frozen else {'stdin':subprocess.DEVNULL}
        completed=subprocess.run(command,env=environment,cwd=instance,stdout=subprocess.PIPE,stderr=errors,**options)
    if completed.returncode:
        raise SampleBuildError(f'sample {operation} failed; retained instance: {instance}')
    if len(completed.stdout)>4000000: raise SampleBuildError('sample report exceeds its bound')
    report=json.loads(completed.stdout)
    if report.get('runtime_identity')!=runtime:
        raise SampleBuildError('sample child runtime identity does not match')
    return report

def build_instance(base: Path, *, engineering_document_limit=None, on_instance=None, prepared=False):
    """Build a fresh owned instance; no active-sample manifest is changed."""
    if engineering_document_limit is not None and (type(engineering_document_limit) is not int or not 1<=engineering_document_limit<794):
        raise SampleBuildError('invalid engineering document limit')
    if prepared and engineering_document_limit is not None:
        raise SampleBuildError('prepared sample requires its complete source closure')
    base=Path(base).absolute()
    for ancestor in (base,*base.parents):
        if ancestor.is_symlink(): raise SampleBuildError('sample base traverses a symlink')
    base.mkdir(mode=0o700,parents=True,exist_ok=True)
    _ordinary(base)
    parent=base/'sample-vaults'
    if parent.exists() or parent.is_symlink(): _ordinary(parent)
    else: parent.mkdir(mode=0o700)
    root=parent/VERSION
    if root.exists() or root.is_symlink(): _ordinary(root)
    else: root.mkdir(mode=0o700)
    lock=root/'preparation.lock'
    fd=os.open(lock,os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    try:
        _ordinary(lock,False)
        try: fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError: raise SampleBuildError('sample preparation is busy') from None
        instance=root/uuid.uuid4().hex;instance.mkdir(mode=0o700)
        for directory in ('home','learned','learned/profiles','tmp'):
            (instance/directory).mkdir(mode=0o700,parents=True,exist_ok=True)
        (instance/'empty.env').touch(mode=0o600)
        _write(instance/'sample-staging.json',{'version':VERSION,'instance_id':instance.name})
        if on_instance is not None:
            on_instance(instance)
        report=_launch(instance,'restore' if prepared else 'build',engineering_document_limit)
        return instance,report
    finally: os.close(fd)

def _reopen_worker(instance,limit=None):
    import time
    from ..vault import Vault
    from ..demo import _prepare_demo_read_store
    from .resources import load_pack,MANIFEST_SHA256,READINGS_SHA256
    started=time.monotonic();pack=load_pack();resources_done=time.monotonic()
    record=json.loads((instance/'sample-instance.json').read_text())
    if record['version']!=VERSION or record['manifest_sha256']!=MANIFEST_SHA256 or record['readings_sha256']!=READINGS_SHA256 or record['state']!='ready':
        raise SampleBuildError('sample instance version is incompatible or incomplete')
    if record.get('runtime_identity')!=_runtime_identity():
        raise SampleBuildError('sample instance belongs to another application version')
    _ordinary(instance/'vault')
    open_started=time.monotonic()
    vault=Vault.open(instance/'vault',PASSPHRASE,create=False)
    open_seconds=time.monotonic()-open_started
    try:
        validation_started=time.monotonic()
        before=vault.ledger.store.authenticated_identity()
        if not {doc['sha256'] for doc in pack.documents} <= set(vault.ledger.projection().captured_docs()):
            raise SampleBuildError('sample source closure is incomplete')
        for doc in pack.documents:
            if vault.raw.get(doc['sha256'])!=pack.original(doc): raise SampleBuildError('sample original differs')
        if completion_failures(pack,vault.ledger.projection()):
            raise SampleBuildError('sample source checks no longer hold')
        validation_seconds=time.monotonic()-validation_started
        sql_started=time.monotonic()
        _prepare_demo_read_store(vault)
        sql_seconds=time.monotonic()-sql_started
        after=vault.ledger.store.authenticated_identity()
        if before!=after: raise SampleBuildError('sample reopen unexpectedly changed history')
        return {'version':VERSION,'state':'ready','event_identity':list(after),'runtime_identity':_runtime_identity(),'reopen_seconds':time.monotonic()-started,
            'phase_seconds':{'resources':resources_done-started,
                'runtime_and_receipt_validation':open_started-resources_done,
                'vault_open':open_seconds,'source_validation':validation_seconds,'sql':sql_seconds}}
    finally: vault.close()

def reopen_instance(instance: Path):
    instance=Path(instance).absolute();_ordinary(instance)
    for name in ('sample-instance.json','sample-staging.json','empty.env'):_ordinary(instance/name,False)
    for ancestor in (instance.parent,instance.parent.parent): _ordinary(ancestor)
    if instance.parent.name!=VERSION or instance.parent.parent.name!='sample-vaults' or len(instance.name)!=32:
        raise SampleBuildError('invalid versioned sample path')
    return _launch(instance,'reopen')
