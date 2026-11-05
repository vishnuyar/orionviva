"""Private independently checked semantic checkpoints for automatic curated appends."""
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from decimal import Decimal, DecimalException, Inexact, localcontext
import hashlib
import hmac
import math
import os
import threading

from . import certified_state as certified
from . import application_history as history
from . import application_io as io
from .schema import TABLES, KEYS
from .store import AuthorityError, IntegrityError, canonical

_SEAL=object()


def _freeze(value):
    if value is None or type(value) in (str,int,bool,bytes):
        return ('scalar',value)
    if type(value) is float and math.isfinite(value):
        return ('scalar',value)
    if type(value) is Decimal:
        if not value.is_finite():
            raise IntegrityError('semantic checkpoint contains a nonfinite decimal')
        parts=value.as_tuple()
        return ('decimal',(parts.sign,tuple(parts.digits),parts.exponent))
    if type(value) is dict:
        return ('dict',tuple((_freeze(k),_freeze(v)) for k,v in value.items()))
    if type(value) in (list,tuple,set,frozenset):
        return (type(value).__name__,tuple(_freeze(v) for v in value))
    from ..ingest.brokerage import BrokerageFacts
    if type(value) is BrokerageFacts:
        return ('brokerage',canonical(value.to_dict()))
    raise IntegrityError('semantic checkpoint contains an unsupported mutable value')


def _thaw(value):
    tag,body=value
    if tag=='scalar':return body
    if tag=='decimal':
        if (type(body) is not tuple or len(body)!=3 or type(body[0]) is not int
                or body[0] not in (0,1) or type(body[1]) is not tuple or not body[1]
                or any(type(digit) is not int or not 0<=digit<=9 for digit in body[1])
                or type(body[2]) is not int):
            raise IntegrityError('invalid semantic decimal encoding')
        try:
            result=Decimal(body)
        except (DecimalException,ValueError,TypeError,OverflowError) as error:
            raise IntegrityError('invalid semantic decimal encoding') from error
        if not result.is_finite():
            raise IntegrityError('nonfinite semantic decimal encoding')
        return result
    if tag=='dict':return {_thaw(k):_thaw(v) for k,v in body}
    if tag=='brokerage':
        import json
        from .investment import decode
        return decode(json.loads(body))
    constructors={'list':list,'tuple':tuple,'set':set,'frozenset':frozenset}
    if tag not in constructors:raise IntegrityError('unknown semantic checkpoint encoding')
    return constructors[tag](_thaw(v) for v in body)


@dataclass(frozen=True)
class _Checkpoint:
    owner_id:int
    pid:int
    root_id:str
    proof:object
    state:tuple
    export:tuple
    investment:tuple
    payroll:tuple
    transfer:tuple
    decisions:tuple
    dependencies:tuple
    seal:object=field(repr=False,compare=False,default=None)


@dataclass(frozen=True)
class _AutomaticImport:
    owner_id:int
    pid:int
    root_id:str
    thread:int
    doc_id:str
    source_id:int
    source_identity:str
    original_sha256:str
    byte_count:int
    seal:object=field(repr=False,compare=False,default=None)


def _metrics(owner,key,reason=None):
    if reason is None:owner._incremental_metrics[key]+=1
    else:
        values=owner._incremental_metrics['fallbacks']
        values[reason]=values.get(reason,0)+1


def _owned(checkpoint,owner):
    if (type(checkpoint) is not _Checkpoint or checkpoint.seal is not _SEAL
            or checkpoint.owner_id!=id(owner) or checkpoint.pid!=os.getpid()
            or checkpoint.root_id!=owner._metadata['root_id']):
        raise IntegrityError('semantic checkpoint ownership differs')
    certified._owner(checkpoint.proof,owner)


def _capability(owner,doc_id=None):
    cap=owner._automatic_import
    if (type(cap) is not _AutomaticImport or cap.seal is not _SEAL
            or cap.owner_id!=id(owner) or cap.pid!=os.getpid()
            or cap.root_id!=owner._metadata['root_id'] or cap.thread!=threading.get_ident()
            or doc_id is not None and cap.doc_id!=doc_id):return False
    source=owner._engine._curated_owner
    from .curated import _owned as source_owned
    try:
        return source is not None and id(source)==cap.source_id and source_owned(source).identity==cap.source_identity
    except AuthorityError:
        return False


@contextmanager
def _automatic(store,original,source):
    from .application import _owned_binding
    from .curated import _member
    owner=None if store._application_binding is None else _owned_binding(store._application_binding,store)
    if owner is None:
        yield
        return
    if owner._automatic_import is not None:
        existing=owner._automatic_import
        same_thread=existing.thread==threading.get_ident()
        if same_thread:owner._automatic_import=None
        try:
            yield
        finally:
            if same_thread:owner._automatic_import=existing
        return
    if type(original) is not bytes:
        yield
        return
    doc=hashlib.sha256(original).hexdigest()
    try:
        issued,_document,_reading=_member(source,doc)
        eligible=source.original(doc)==original
    except (AuthorityError,OSError):
        eligible=False
    if not eligible:
        yield
        return
    cap=_AutomaticImport(id(owner),os.getpid(),owner._metadata['root_id'],threading.get_ident(),
        doc,id(source),issued.identity,doc,len(original),_SEAL)
    owner._automatic_import=cap
    try:
        yield
    except BaseException:
        owner._invalidate_certificates()
        raise
    finally:
        owner._automatic_import=None


def _dependencies(state,transfer,docs):
    docs=set(docs)
    projections={}
    for doc in sorted(docs):
        item=state['items'].get((doc,));physical='' if item is None else item['account_id']
        interpretation=state['interpretations'].get((doc,))
        payroll_source=(interpretation is not None and interpretation['facts_type']=='payroll' and (doc,) in state['payroll_facts'])
        if payroll_source:physical='' 
        component=state['investment_components'].get((doc,))
        ownership=None if component is None else {k:component[k] for k in ('snapshot_state','account_id','snapshot_id')}
        snapshot=None if ownership is None else state['investment_snapshots'].get((ownership['snapshot_id'],))
        projections[doc]=dict(interpretation=state['interpretations'].get((doc,)),
            payroll=state['payroll_facts'].get((doc,)),native=state['investment_facts'].get((doc,)),
            component=ownership,snapshot=snapshot,physical=physical,
            key=state['account_keys'].get((physical,)),
            kind=None if (physical,) not in state['accounts'] else state['accounts'][(physical,)]['kind'],
            transactions=sorted((r for r in state['transactions'].values() if r['doc_id']==doc),key=lambda r:r['line_index']))
    immutable_accounts={key:{k:row[k] for k in ('account_id','identity','kind','currency','number','normalized_number','institution','label','names')} for key,row in state['accounts'].items()}
    accepted={r['doc_id']:r['revision'] for r in state['validation_runs'].values() if r['state']=='accepted'}
    accepted.update({r['doc_id']:r['created_revision'] for r in state['investment_snapshots'].values()})
    return dict(transfer=projections,accounts=immutable_accounts,keys=state['account_keys'],claims=state['reference_claims'],
        periods=state['periods'],accepted=accepted,captured={doc:True for doc in docs})


def _dependencies_unchanged(checkpoint,state):
    old=_thaw(checkpoint.dependencies); oldstate=_thaw(checkpoint.state)
    oldtransfer=_thaw(checkpoint.transfer);candidate=_dependencies(state,oldtransfer,old['transfer'])
    for doc,value in old['transfer'].items():
        if candidate['transfer'].get(doc)!=value:return False
    for name in ('accounts','keys','claims','periods','accepted'):
        if any(candidate[name].get(key)!=value for key,value in old[name].items()):return False
    if any((doc,) not in state['documents'] for doc in old['captured']):return False
    revision=_thaw(checkpoint.export)['revision']
    if any(key not in oldstate['account_keys'] and row['creation_order']<=revision for key,row in state['account_keys'].items()):return False
    if any(key not in oldstate['reference_claims'] and row['claim_order']<=revision for key,row in state['reference_claims'].items()):return False
    if any(doc not in old['accepted'] and when<=revision for doc,when in candidate['accepted'].items()):return False
    return True


def _accepted_docs(store,export):
    import json
    from ..crypto import open_sealed
    docs=set()
    for revision,previous,envelope,_digest in export['records']:
        payload=json.loads(open_sealed(store._audit_key,json.loads(envelope),aad=canonical([revision,previous]).encode()))
        docs.update(op['row']['doc_id'] for op in payload['operations'] if op['table']=='items' and op['row']['state']=='accepted')
    return docs


def _checkpoint(owner,proof,state,export,investment,payroll,transfer,decisions,accepted_docs):
    # Every container is recursively copied into immutable primitives before retention.
    return _Checkpoint(id(owner),os.getpid(),owner._metadata['root_id'],proof,_freeze(state),_freeze(export),
        _freeze(investment),_freeze(payroll),_freeze(transfer),tuple(decisions),
        _freeze(_dependencies(state,transfer,accepted_docs)),_SEAL)


def _accept_full(owner,state,export,investment,payroll,transfer,decisions):
    proof=owner._pending_certificate or owner._certificate
    if proof is None:return
    checkpoint=_checkpoint(owner,proof,state,export,investment,payroll,transfer,decisions,_accepted_docs(owner._engine,export))
    if proof.representation.pending:owner._pending_incremental_checkpoint=checkpoint
    else:owner._incremental_checkpoint=checkpoint
    _metrics(owner,'full_bootstraps')


def _lock_identity(path,lock=None):
    info=io.regular(path)
    parent=io.identity(path.parent)
    if lock is not None:
        lock._check()
        if lock.file_identity!=(info.st_dev,info.st_ino):raise IntegrityError('document lock descriptor differs')
        if lock.parent_identity!=parent:raise IntegrityError('document lock parent differs')
    after=io.regular(path)
    if (info.st_dev,info.st_ino,info.st_mode,info.st_uid,info.st_nlink)!=(after.st_dev,after.st_ino,after.st_mode,after.st_uid,after.st_nlink):
        raise IntegrityError('document lock properties changed during checking')
    if io.identity(path.parent)!=parent:raise IntegrityError('document lock parent changed during checking')
    return (path.name,info.st_dev,info.st_ino,info.st_mode,info.st_uid,info.st_nlink,certified._digest(parent))


def _check_custody(owner,representation,expected_members):
    directory=owner.root/'sql'/'originals'
    if tuple(sorted(p.name for p in directory.iterdir()))!=tuple(sorted(expected_members)):
        raise IntegrityError('automatic representation membership differs')
    for name,*_rest in representation.locks:
        if _lock_identity(directory/name)!=next(row for row in representation.locks if row[0]==name):
            raise IntegrityError('checked document lock changed')
    for doc,digest,size in representation.originals:
        before=io.regular(directory/(doc+'.blob'))
        plain,actual=owner._engine._original_with_commitment(doc)
        after=io.regular(directory/(doc+'.blob'))
        if (actual!=digest or len(plain)!=size or
                (before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns,before.st_ctime_ns)!=(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns)):
            raise IntegrityError('checked old custody changed during append')
    if tuple(sorted(p.name for p in directory.iterdir()))!=tuple(sorted(expected_members)):
        raise IntegrityError('automatic representation membership changed during checking')


def _extend_lock(owner,oldproof,lock):
    certified._owner(oldproof,owner)
    path=lock.path;representation=oldproof.representation
    if not _capability(owner,path.stem):return False
    name=path.name
    members=representation.original_members
    locks=representation.locks
    checked=_lock_identity(path,lock)
    if name in members:
        if checked not in locks:raise IntegrityError('existing document lock differs from accepted identity')
    else:
        members=tuple(sorted(members+(name,)));locks=tuple(sorted(locks+(checked,)))
    updated=replace(oldproof,representation=replace(representation,original_members=members,locks=locks))
    with owner._engine._snapshot():owner._engine._bind_verified_state(updated)
    owner._certificate=updated
    if owner._incremental_checkpoint is not None:
        owner._incremental_checkpoint=replace(owner._incremental_checkpoint,proof=updated)
    if name not in representation.original_members:_metrics(owner,'lock_extensions')
    return True


def _prepared_representation(owner,oldproof,*,capture=None):
    representation=oldproof.representation
    owner._bind_history(representation)
    path,issued=owner._pending
    intent,inner=owner._history.read_intent(io.read(path/'intent.json'))
    if (intent['stage']!='prepared' or inner['issued']!=issued or inner['prepared_name']!='prepared-publication.json'
            or inner['superseded_name'] is not None or inner['superseded_sha256'] is not None
            or inner['prepared_sha256']!=history.digest(owner._extension)):
        raise IntegrityError('automatic preparation is not the actual authenticated pending operation')
    record,payload=owner._history._record_and_payload(owner._extension,previous=issued['prior_terminal'])
    if (payload['issued']!=issued or issued['prior_terminal']!={key:history.decode(representation.terminal_wire)[key] for key in history.BOUNDARY}
            or issued['prior_sql']!={'revision':history.decode(representation.terminal_wire)['sql_revision'],'head':history.decode(representation.terminal_wire)['sql_head']}):
        raise IntegrityError('automatic prepared record does not extend accepted boundary')
    originals=representation.originals;members=representation.original_members
    if capture is not None:
        doc,original=capture
        if not _capability(owner,doc):raise IntegrityError('custody extension lacks exact automatic ownership')
        cap=owner._automatic_import
        data,digest=owner._engine._original_with_commitment(doc)
        expected=dict(doc_id=doc,byte_count=len(original),blob_sha256=digest)
        if (record['kind']!='custody' or issued['kind']!='capture' or payload['body']!=expected
                or issued['capture']!={**expected,'blob_name':'prepared-original.blob'}
                or data!=original or len(data)!=cap.byte_count or hashlib.sha256(data).hexdigest()!=cap.original_sha256):
            raise IntegrityError('new custody does not match authenticated prepared source')
        if (doc+'.blob') in members:raise IntegrityError('new custody replaces an old member')
        originals=tuple(sorted(originals+((doc,digest,len(data)),)))
        members=tuple(sorted(members+(doc+'.blob',)))
    _check_custody(owner,representation,members)
    name=f"{record['sequence']:020d}.json"
    terminal=owner._history.terminal_bytes(record)
    return replace(representation,history=representation.history+((name,history.digest(owner._extension)),),
        terminal_wire=terminal,terminal_digest=history.digest(terminal),originals=originals,original_members=members,pending=True),record,payload


def _extend_custody(owner,oldproof,original):
    engine=owner._engine;checkpoint=owner._incremental_checkpoint
    if checkpoint is None:return False
    _owned(checkpoint,owner)
    previous=engine._verified_operation
    previous_verifying=engine._verifying
    previous_originals=engine._verification_originals
    try:
        with engine._snapshot():
            engine._verified_operation=True;engine._verifying=True;engine._verification_originals={}
            engine._fresh_physical_checks()
            export=engine._export_current()
            if engine._certified_sql_digest(export)!=oldproof.sql_digest:raise IntegrityError('custody changed old SQL')
            for table,columns in TABLES.items():
                actual=[dict(zip(columns,row)) for row in engine._db.execute('SELECT '+','.join('"'+c+'"' for c in columns)+' FROM '+table).fetchall()]
                if certified._table_digest(table,columns,actual)!=dict(oldproof.tables)[table]:raise IntegrityError('custody changed old materialized rows')
            representation,_record,_payload=_prepared_representation(owner,oldproof,capture=(owner._automatic_import.doc_id,original))
            observed=tuple(sorted((doc,digest,size) for doc,(digest,size) in engine._verification_originals.items()))
            if observed!=representation.originals:raise IntegrityError('custody source reads differ from checked buffers')
            owner._accept_full_verification(representation,oldproof.sql_digest,oldproof.tables)
            owner._pending_incremental_checkpoint=replace(checkpoint,proof=owner._pending_certificate)
        _metrics(owner,'custody_extensions')
        return True
    finally:
        engine._verification_originals=previous_originals;engine._verifying=previous_verifying;engine._verified_operation=previous


def _try_advance(owner):
    checkpoint=owner._incremental_checkpoint
    if not _capability(owner):
        _metrics(owner,'fallbacks','not_automatic');return False
    if checkpoint is None:
        _metrics(owner,'fallbacks','no_checkpoint');return False
    _owned(checkpoint,owner)
    engine=owner._engine
    export=engine._export_current();oldexport=_thaw(checkpoint.export)
    engine.check_export_structure(export)
    if (export['revision'] not in (oldexport['revision'],oldexport['revision']+1)
            or export['records'][:oldexport['revision']]!=oldexport['records']
            or export['commits'][:oldexport['revision']]!=oldexport['commits']):
        _metrics(owner,'fallbacks','non_append');return False
    if not hmac.compare_digest(export['mac'],engine._mac(export['revision'],export['head'])):raise IntegrityError('candidate audit MAC differs')
    previous=engine._verified_operation;engine._verified_operation=True
    previous_verifying=engine._verifying;engine._verifying=True
    previous_originals=engine._verification_originals;engine._verification_originals={}
    try:
        engine._fresh_physical_checks()
        state=_thaw(checkpoint.state)
        operations=[]
        if export['revision']>oldexport['revision']:
            operations=engine._advance_reconstruction(state,export['records'][-1],export['commits'][-1])
        engine._finish_reconstruction(state,export)
        representation,record,payload=_prepared_representation(owner,checkpoint.proof)
        if operations:
            if record['kind']!='sql_commit' or payload['body']!={'record':export['records'][-1],'commit':export['commits'][-1]}:
                raise IntegrityError('prepared SQL extension differs from actual append')
        elif record['kind']!='noop' or payload['body']!={'intent_sha256':history.digest(history.encoded(owner._pending[1]))}:
            raise IntegrityError('prepared noop differs from actual empty append')
        if record['sql_revision']!=export['revision'] or record['sql_head']!=export['head']:
            raise IntegrityError('prepared SQL terminal differs')
        if not _dependencies_unchanged(checkpoint,state):
            _metrics(owner,'fallbacks','historical_dependency');return False
        investment=_thaw(checkpoint.investment);payroll=_thaw(checkpoint.payroll);transfer=_thaw(checkpoint.transfer)
        from . import investment_verify,identity,payroll_verify,transfer_verify
        if operations:investment_verify._advance(engine,investment,export['revision'],operations)
        investment_verify._finish(investment,state)
        decisions=identity._advance_semantics(engine,state,checkpoint.decisions)
        memo=payroll_verify._NormalizationMemo()
        try:
            with localcontext() as arithmetic:
                arithmetic.prec=28;arithmetic.traps[Inexact]=True
                if operations:payroll_verify._advance(engine,payroll,export['revision'],operations,memo)
                payroll_verify._finish(payroll,state)
                transfer=transfer_verify._advance(engine,transfer,state,[operations] if operations else [])
        finally:memo.clear()
        tables=[]
        for table,columns in TABLES.items():
            actual={tuple(row[columns.index(key)] for key in KEYS[table]):dict(zip(columns,row)) for row in engine._db.execute('SELECT '+','.join('"'+c+'"' for c in columns)+' FROM '+table).fetchall()}
            if actual!=state[table]:raise IntegrityError('audited state mismatch: '+table)
            tables.append((table,certified._table_digest(table,columns,actual.values())))
        for key,document in state['documents'].items():
            if len(engine._original(key[0]))!=document['byte_count']:raise IntegrityError('source size mismatch')
        observed=tuple(sorted((doc,digest,size) for doc,(digest,size) in engine._verification_originals.items()))
        if observed!=representation.originals:raise IntegrityError('candidate source reads differ from checked custody')
        owner._accept_full_verification(representation,engine._certified_sql_digest(export),tuple(tables))
        accepted_docs=set(_thaw(checkpoint.dependencies)['transfer'])
        accepted_docs.update(op['row']['doc_id'] for op in operations if op['table']=='items' and op['row']['state']=='accepted')
        owner._pending_incremental_checkpoint=_checkpoint(owner,owner._pending_certificate,state,export,investment,payroll,transfer,decisions,accepted_docs)
        _metrics(owner,'advances')
        return True
    finally:
        engine._verification_originals=previous_originals;engine._verifying=previous_verifying;engine._verified_operation=previous
