"""Shared result contracts and outcome vocabulary for document ingestion."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from vivacore.verify.arithmetic import CheckResult

from ..normalization_context import ExtractionNormalizationContext

from .diagnose import ReconciliationFinding
from .statement import StatementFacts

# Ingest actions — the outcome of one ingest, reportable verbatim.
POSTED = "posted"        # reconciled and written to the ledger
PARKED = "parked"        # captured and acknowledged; no projector for it yet
DUPLICATE = "duplicate"  # already ingested (same content hash)
CONFLICT = "conflict"    # recognized, but did not reconcile — not posted
GAP = "gap"              # opening does not continue from the balance held
IDENTITY = "identity"    # reconciles, but whose account is ambiguous — ask
AWAITING = "awaiting"    # a pay stub read + verified, waiting for its net-pay deposit


@dataclass
class ModelPhase:
    """One model interaction in a read — the classify pass or the extract pass —
    captured verbatim for the claims layer. Each is persisted as its own
    ReadRecorded, so a two-phase read yields two."""
    phase: str                       # "classify" | "extract"
    model: str
    prompt_version: str
    raw_text: str
    cost_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    input_mode: str = "text+image"
    parse_ok: bool = True
    error: str | None = None
    resolved_model: str = ""
    # Token counters are meaningful only if the provider response actually
    # carried usage. Adapter defaults of zero are not measurements.
    usage_reported: bool = False
    transport_receipt_ids: list[str] | None = None
    transport_complete: bool | None = None
    extraction_id: str = ""
    phase_attempt: int = 0
    normalization_context: ExtractionNormalizationContext | None = None


@dataclass
class ReadResult:
    """What a reader returns for one document: its classification, and — if it is
    a statement — the structured facts. A reader for a non-statement returns
    ``facts=None`` with the type it recognized (e.g. 'pay_stub').

    ``phases`` carries the per-call model records (classify, extract) that the
    pipeline persists to the claims layer. The flat ``raw_*``/``model`` fields are
    the single-call view, used by offline stubs; a two-phase read populates
    ``phases`` instead."""
    doc_type: str
    doc_type_confidence: float
    facts: StatementFacts | None = None
    error: str | None = None
    raw_text: str = ""
    model: str = ""
    prompt_version: str = ""
    input_mode: str = "text+image"
    cost_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    phases: list[ModelPhase] = field(default_factory=list)
    resolved_model: str = ""
    usage_reported: bool = False
    source_locale: str = ""
    acquisition: dict | None = None
    normalization_context: ExtractionNormalizationContext | None = None


@dataclass
class IngestResult:
    doc_id: str
    action: str
    doc_type: str
    account: str | None = None
    grade: str | None = None
    reconciliation: CheckResult | None = None
    finding: ReconciliationFinding | None = None   # why it failed / how it was fixed
    auto_corrected: bool = False
    message: str = ""



class DocumentTooLarge(ValueError):
    """A document costs more to read than any real statement should.

    Raised rather than handled by reading part of it: a statement posted over a
    subset of its own pages would reconcile against nothing and be graded like
    any other. The document is captured and parked with this as the reason."""

ReadFn = Callable[[bytes, str], ReadResult]




__all__ = ['POSTED', 'PARKED', 'DUPLICATE', 'CONFLICT', 'GAP', 'IDENTITY', 'AWAITING', 'ModelPhase', 'ReadResult', 'IngestResult', 'DocumentTooLarge', 'ReadFn']


# Confirmation tokens are local gesture admission, never financial evidence.
import base64
import hashlib
import hmac
import json
import secrets
import threading

RETAINED_READING_VERSION = 'retained-reading-v1'
_CONFIRMATION_DOMAIN = b'retained-confirmation-v1\x00'


def retained_source_identity(value):
    if type(value) is dict:
        count, head = value.get('count'), value.get('head')
    elif type(value) is tuple and len(value) == 3:
        count, head = value[:2]
    else:
        raise ValueError('evidence_unavailable')
    if (type(count) is not int or count < 0 or type(head) is not str
            or len(head) != 64 or any(c not in '0123456789abcdef' for c in head)):
        raise ValueError('evidence_unavailable')
    return {'count': count, 'head': head}


def _confirmation_json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode('ascii')


def retained_capture_commitment(document, filename, raw_type, capture_id):
    if any(type(v) is not str or not v for v in (document, filename, raw_type, capture_id)):
        raise ValueError('capture_conflict')
    return hashlib.sha256(_confirmation_json([document, filename, raw_type, capture_id])).hexdigest()


class _RetainedConfirmationState:
    def __init__(self):
        self.lock = threading.RLock()
        self.revoked = False
        self._rotate()

    def _rotate(self):
        self.secret = secrets.token_bytes(32)
        self.epoch = secrets.token_hex(16)
        self.consumed = set()

    def revoke(self):
        with self.lock:
            self.revoked = True
            self.secret = b''
            self.consumed.clear()

    def issue(self, document, capture, source):
        with self.lock:
            if self.revoked: raise ValueError('confirmation_unavailable')
            body = dict(v=1, epoch=self.epoch, nonce=secrets.token_hex(16),
                        document=document, capture=capture, source=retained_source_identity(source))
            encoded = _confirmation_json(body)
            tag = hmac.new(self.secret, _CONFIRMATION_DOMAIN + encoded, hashlib.sha256).hexdigest()
            token = base64.urlsafe_b64encode(_confirmation_json({'body': body, 'mac': tag})).decode('ascii').rstrip('=')
            if len(token) > 1024: raise ValueError('confirmation_unavailable')
            return token

    def _decode(self, token):
        try:
            if (type(token) is not str or not 0 < len(token) <= 1024
                    or any(c not in 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-' for c in token)):
                raise ValueError
            raw = base64.b64decode(token + '=' * (-len(token) % 4), altchars=b'-_', validate=True)
            value = json.loads(raw)
            if type(value) is not dict or set(value) != {'body', 'mac'}: raise ValueError
            body, mac = value['body'], value['mac']
            if (type(body) is not dict or set(body) != {'v', 'epoch', 'nonce', 'document', 'capture', 'source'}
                    or type(body['v']) is not int or body['v'] != 1 or type(mac) is not str or len(mac) != 64): raise ValueError
            if not hmac.compare_digest(mac, hmac.new(self.secret, _CONFIRMATION_DOMAIN + _confirmation_json(body), hashlib.sha256).hexdigest()): raise ValueError
            if raw != _confirmation_json(value) or base64.urlsafe_b64encode(raw).decode('ascii').rstrip('=') != token: raise ValueError
            for key, size in (('epoch',32),('nonce',32),('document',64),('capture',64)):
                if type(body[key]) is not str or len(body[key]) != size or any(c not in '0123456789abcdef' for c in body[key]): raise ValueError
            if type(body['source']) is not dict or set(body['source']) != {'count', 'head'}: raise ValueError
            retained_source_identity(body['source'])
            return body
        except Exception:
            raise ValueError('confirmation_unavailable') from None

    def consume(self, entries, source):
        # One bounded batch, one authenticated source identity, one linearization.
        with self.lock:
            if self.revoked: return ['confirmation_unavailable'] * len(entries)
            source = retained_source_identity(source() if callable(source) else source)
            results=[]; passing=[]
            for document, capture, token in entries:
                try:
                    body = self._decode(token)
                    if body['epoch'] != self.epoch: raise ValueError('confirmation_unavailable')
                    if body['document'] != document or body['capture'] != capture: raise ValueError('capture_conflict')
                    if body['source'] != source: raise ValueError('stale_confirmation')
                    if body['nonce'] in self.consumed: raise ValueError('confirmation_used')
                    if body['nonce'] in passing: raise ValueError('confirmation_used')
                    passing.append(body['nonce']); results.append(None)
                except ValueError as exc:
                    results.append(str(exc))
            if len(self.consumed) + len(passing) > 128:
                self._rotate()
                return ['confirmation_unavailable' if result is None else result for result in results]
            self.consumed.update(passing)
            return results


def retained_confirmation_owner(vault, *, create=False):
    with vault._retained_confirmation_lock:
        if vault._retained_confirmation_closed: raise ValueError('confirmation_unavailable')
        owner = vault._retained_confirmation_owner
        if owner is None and create:
            owner = _RetainedConfirmationState()
            vault._retained_confirmation_owner = owner
        if owner is None or owner.revoked: raise ValueError('confirmation_unavailable')
        return owner


def revoke_retained_confirmations(vault):
    with vault._retained_confirmation_lock:
        vault._retained_confirmation_closed = True
        if vault._retained_confirmation_owner is not None:
            vault._retained_confirmation_owner.revoke()
