"""Bounded model reads with one durable capture and settlement owner."""
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from dataclasses import dataclass,field
import copy
import json
from pathlib import Path
from queue import Queue,Empty
from threading import Event
from time import monotonic

from .handlers import BridgeRequestError
from ..ingest.pipeline import (ReadResult,_begin_bulk_read,_retain_bulk_phase,_retain_bulk_original,
                                _retain_bulk_response,_begin_retained_bulk_read,_validate_bulk_history)


@dataclass
class _Message:
    document: str
    phase: object=None
    response: object=None
    response_id: str|None=None
    doc_type: str='unknown'
    confidence: float=0.0
    done: Event=field(default_factory=Event)
    allowed: bool=False
    error: object=None


def _reading_task(read,pages,text,document,messages):
    def exchange(phase=None,doc_type='unknown',confidence=0.0):
        message=_Message(document,phase=copy.deepcopy(phase),doc_type=doc_type,confidence=confidence)
        messages.put(message)
        message.done.wait()
        if message.error is not None:raise message.error
        return message.allowed
    def receive(body):
        message=_Message(document,response=copy.deepcopy(body))
        messages.put(message);message.done.wait()
        if message.error is not None:raise message.error
        return message.response_id
    try:
        return read(tuple(pages),text,document,phase_sink=exchange,permit=exchange,
                    response_sink=receive)
    except Exception:
        # No completed response is invented for a request that never returned.
        return ReadResult('unknown',0.0,None,error='read request failed')


def _paths(payload):
    if type(payload) is not dict or set(payload)!={'paths'}:
        raise BridgeRequestError('upload_many accepts only paths')
    paths=payload['paths']
    if type(paths) is not list or not 1<=len(paths)<=3:
        raise BridgeRequestError('upload_many needs one to three paths')
    if any(type(path) is not str or not path.strip() or len(path.encode('utf-8'))>4096 for path in paths):
        raise BridgeRequestError('bounded nonempty paths required')
    if len(json.dumps(payload,ensure_ascii=False,separators=(',',':')).encode())>16384:
        raise BridgeRequestError('upload_many request exceeds bound')
    return [Path(path) for path in paths]


def _retained(payload):
    if type(payload) is not dict or set(payload)!={'retained_documents','confirm_reading'} or payload['confirm_reading'] is not True:
        raise BridgeRequestError('closed confirmed retained reading required')
    entries=payload['retained_documents']
    if type(entries) is not list or not 1<=len(entries)<=3:
        raise BridgeRequestError('one to three retained documents required')
    for entry in entries:
        if type(entry) is not dict or set(entry)!={'document_id','confirmation_token'}:
            raise BridgeRequestError('closed retained document selector required')
        doc=entry['document_id'];token=entry['confirmation_token']
        if type(doc) is not str or len(doc)!=64 or any(c not in '0123456789abcdef' for c in doc):
            raise BridgeRequestError('invalid retained identity')
        if type(token) is not str or not 0<len(token)<=1024 or not token.isascii():
            raise BridgeRequestError('invalid retained confirmation')
    if len({entry['document_id'] for entry in entries})!=len(entries) or len({entry['confirmation_token'] for entry in entries})!=len(entries):
        raise BridgeRequestError('distinct retained selectors required')
    if len(json.dumps(payload,ensure_ascii=True,separators=(',',':')).encode())>16384:
        raise BridgeRequestError('upload_many request exceeds bound')
    return entries


def _row(ordinal,document=None,action='failed',disposition=None,reason=None):
    return dict(ordinal=ordinal,document_id=document,action=action,disposition=disposition,reason=reason)


class BulkDocuments:
    def __init__(self,vault,jobs):
        self.vault=vault;self.jobs=jobs;self.messages=Queue(maxsize=3)
        self.stopped=Event();self.owners={};self.job_id=None;self.fatal=None;self.last_pulse=monotonic();self.retained_mode=False

    def stop(self):
        self.stopped.set()
        if self.job_id is not None:self.jobs.cancel(self.job_id)

    def _pump(self):
        if self.retained_mode and self.vault._retained_confirmation_closed:
            self.stopped.set()
        # Only this coordinator reads the transport. A stop remains pending
        # until all started calls and durable receipts have drained.
        try:
            if self.jobs._pump is not None:self.jobs._pump()
        except (BrokenPipeError,OSError):self.stopped.set()
        except Exception as exc:self.fatal=exc;self.stopped.set()
        if self.job_id is not None and monotonic()-self.last_pulse>=10:
            self.last_pulse=monotonic()
            try:self.jobs._move(self.job_id,'progress')
            except (BrokenPipeError,OSError):self.stopped.set()
        if self.job_id is not None and self.jobs.cancel_requested(self.job_id):self.stopped.set()

    def _service(self,wait=False):
        self._pump()
        while True:
            try:message=self.messages.get(timeout=.02 if wait else 0)
            except Empty:return
            try:
                if message.response is not None:
                    message.response_id=_retain_bulk_response(self.owners[message.document],message.response)
                if message.phase is not None:
                    _retain_bulk_phase(self.owners[message.document],message.phase,
                                       message.doc_type,message.confidence)
                message.allowed=not self.stopped.is_set() and self.fatal is None
            except BaseException as exc:
                self.fatal=exc;self.stopped.set();message.error=exc
            finally:message.done.set()
            wait=False

    def run(self,payload):
        from .document_actions import _refusal
        from ..ingest.reader import build_reader,ReadStopped
        from ..engine import upload,_today
        retained=_retained(payload) if type(payload) is dict and 'retained_documents' in payload else None
        self.retained_mode=retained is not None
        paths=None if retained is not None else _paths(payload)
        reader,configured=build_reader()
        job=self.jobs.open('viva.documents.upload_many',('checked','opened','read','settled'))
        self.job_id=job.job_id
        rows=[None]*len(retained if retained is not None else paths);futures={};duplicates={};held=[]
        with job:
            executor=ThreadPoolExecutor(max_workers=3,thread_name_prefix='document-model-read')
            try:
                entries=[]
                if retained is not None:
                    from ..ingest.pipeline_models import retained_confirmation_owner
                    by_document={entry['document_id']:(ordinal,entry) for ordinal,entry in enumerate(retained)}
                    for document in sorted(by_document):
                        ordinal,entry=by_document[document]
                        self._service()
                        if not configured:
                            rows[ordinal]=_row(ordinal,document,'refused',reason='no_model');continue
                        if self.stopped.is_set():
                            rows[ordinal]=_row(ordinal,document,'cancelled',reason='job_cancelled');continue
                        try:
                            owner=_begin_retained_bulk_read(self.vault.raw,self.vault.ledger,document,_today())
                            held.append(owner);self.owners[document]=owner
                        except Exception as exc:
                            safe={'already_accepted','financial_review','uncertain_audit','capture_conflict','evidence_unavailable'}
                            reason=str(exc) if str(exc) in safe else 'missing_original' if isinstance(exc,(FileNotFoundError,OverflowError)) else 'evidence_unavailable'
                            rows[ordinal]=_row(ordinal,document,'refused',reason=reason)
                    admitted=[(ordinal,entry,self.owners[entry['document_id']]) for ordinal,entry in enumerate(retained) if rows[ordinal] is None]
                    try:
                        authority=retained_confirmation_owner(self.vault)
                        reasons=authority.consume([(owner.document,owner.capture_commitment,entry['confirmation_token'])
                            for ordinal,entry,owner in admitted],self.vault.ledger.store.authenticated_identity)
                    except Exception:
                        reasons=['confirmation_unavailable']*len(admitted)
                    for (ordinal,entry,owner),reason in zip(admitted,reasons):
                        if reason is not None:rows[ordinal]=_row(ordinal,owner.document,'refused',reason=reason)
                        else:entries.append((ordinal,Path(owner.filename),owner.data,owner.document))
                for ordinal,path in enumerate(paths or []):
                    self._service()
                    if self.stopped.is_set():
                        rows[ordinal]=_row(ordinal,action='cancelled',reason='job_cancelled');continue
                    refused=_refusal(path)
                    if refused is not None:
                        rows[ordinal]=_row(ordinal,action='refused',reason=refused.reason);continue
                    try:data=path.read_bytes()
                    except OSError:
                        rows[ordinal]=_row(ordinal,action='refused',reason='file_unreadable');continue
                    from ..ingest.reader import MAX_BYTES
                    if len(data)>MAX_BYTES:
                        rows[ordinal]=_row(ordinal,action='refused',reason='file_over_size_limit');continue
                    document=self.vault.raw.fingerprint(data)
                    entries.append((ordinal,path,data,document))
                job.reached('checked')
                # Canonical acquisition order prevents overlapping multi-document
                # importers from holding the same lock set in opposite orders.
                unique={}
                for ordinal,path,data,document in entries:unique.setdefault(document,(path,data))
                for document in sorted(unique) if retained is None else ():
                    self._service()
                    path,data=unique[document]
                    owner=_begin_bulk_read(self.vault.raw,self.vault.ledger,data,path.name,_today())
                    held.append(owner);self.owners[document]=owner
                dispatched=set()
                for ordinal,path,data,document in entries:
                    self._service()
                    owner=self.owners[document]
                    if document in dispatched:
                        duplicates[ordinal]=document;continue
                    dispatched.add(document)
                    if self.stopped.is_set():
                        _retain_bulk_original(owner)
                        rows[ordinal]=_row(ordinal,document,action='cancelled',reason='job_cancelled');continue
                    if retained is None and (self.vault.ledger.projection().is_resolved(document)
                            or document in self.vault.ledger.projection().captured_docs()):
                        rows[ordinal]=_row(ordinal,document,'duplicate');continue
                    if not configured:
                        futures[ordinal]=(None,owner,reader(data,document));continue
                    try:
                        def checkpoint():
                            self._service()
                            if self.stopped.is_set():raise ReadStopped()
                        pages,text=reader.prepare(data,checkpoint=checkpoint)
                    except Exception:
                        futures[ordinal]=(None,owner,ReadResult('unknown',0.0,None,error='read preparation failed'))
                        continue
                    context=copy_context()
                    future=executor.submit(context.run,_reading_task,reader.read_prepared,
                                           tuple(pages),text,document,self.messages)
                    futures[ordinal]=(future,owner,None)
                job.reached('opened')
                # Do not settle anything while another reading can need an ack.
                while any(future is not None and not future.done() for future,_,_ in futures.values()):
                    self._service(wait=True)
                self._service()
                executor.shutdown(wait=True)
                job.reached('read')
                for ordinal,(future,owner,cached) in futures.items():
                    self._pump()
                    result=cached if future is None else future.result()
                    if owner.retained:
                        try:_validate_bulk_history(owner)
                        except Exception as exc:
                            self.fatal=exc;self.stopped.set()
                    if self.fatal is not None or (self.retained_mode and self.vault._retained_confirmation_closed):
                        rows[ordinal]=_row(ordinal,owner.document,'failed',reason='outcome_unknown');continue
                    # A late transport failure may have already retained real
                    # phases; preserve those exact bodies, never fabricate one.
                    if not result.phases and (owner.records or owner.responses):
                        rows[ordinal]=_row(ordinal,owner.document,'failed',
                            disposition='read_yielded_nothing',reason='read_failed');continue
                    try:
                        outcome=upload(self.vault,owner.filename,owner.data,
                            lambda data,document,cached=result:cached,_bulk_audit=owner)
                    except Exception as exc:
                        self.fatal=exc;self.stopped.set()
                        rows[ordinal]=_row(ordinal,owner.document,'failed',reason='outcome_unknown')
                        continue
                    reason=('no_model' if not configured else 'job_cancelled' if self.stopped.is_set()
                            and result.facts is None else 'read_failed' if result.error else None)
                    rows[ordinal]=_row(ordinal,owner.document,outcome['action'],outcome['reading'],reason)
                for ordinal,document in duplicates.items():rows[ordinal]=_row(ordinal,document,'duplicate')
                if self.fatal is not None:
                    from ..persona import moment
                    job.fail(moment('documents_recovery_blocked'))
                else:job.reached('settled')
                if self.stopped.is_set() and self.fatal is None:
                    # Mark cancellation only after the promised drain/settlement.
                    self.jobs.cancel(job.job_id)
                    try:job.checkpoint(pump=False)
                    except Exception:pass
            finally:
                # Even an owner failure must acknowledge all completed phases
                # and let running calls return before any vault lock is released.
                self.stopped.set()
                while any(future is not None and not future.done() for future,_,_ in futures.values()):
                    self._service(wait=True)
                self._service();executor.shutdown(wait=True)
                for owner in reversed(held):owner.close()
        if any(row is None for row in rows):raise RuntimeError('incomplete bulk terminal population')
        return {'job_id':job.job_id,'rows':rows}
