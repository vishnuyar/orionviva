"""Encrypted, contract-bound document continuations; never a financial authority."""
from dataclasses import fields
from functools import lru_cache
import hashlib
import hmac
import os
import stat
import importlib
import json
import marshal

from ..crypto import open_sealed, seal
from ..ingest.raw_store import _durable_json
from ..ingest.pipeline_models import ReadResult, ModelPhase
from ..normalization_context import encode_context, decode_context

VERSION = 'document-continuation-v1'


@lru_cache(maxsize=1)
def extraction_contract():
    """Bind trusted result snapshots to installed parser and reader code."""
    digest = hashlib.sha256(VERSION.encode())
    names = ('viva.desktop_bridge.import_checkpoints', 'viva.rebuild', 'viva.ingest.reader', 'viva.ingest.statement', 'viva.ingest.paystub',
             'viva.ingest.brokerage', 'viva.ingest.instrument_read',
             'viva.ingest.instrument_contracts', 'viva.ingest.registry',
             'viva.normalization_context', 'viva.investment.payroll_extraction',
             'viva.retirement_funding.payroll_v2', 'vivacore.verify.normalize')
    for name in names:
        module = importlib.import_module(name)
        spec = module.__spec__
        code = spec.loader.get_code(name)
        if code is None:
            raise ValueError('extraction contract unavailable')
        digest.update(name.encode()); digest.update(marshal.dumps(code))
    return digest.hexdigest()


def _result_body(result):
    values = {field.name: getattr(result, field.name) for field in fields(ReadResult)
              if field.name not in {'facts', 'phases', 'normalization_context'}}
    facts = result.facts
    values['facts'] = None if facts is None else {'kind': type(facts).__name__, 'body': facts.to_dict()}
    values['normalization_context'] = (None if result.normalization_context is None
                                       else encode_context(result.normalization_context))
    values['phases'] = []
    for phase in result.phases:
        value = {field.name: getattr(phase, field.name) for field in fields(ModelPhase)
                 if field.name != 'normalization_context'}
        value['normalization_context'] = (None if phase.normalization_context is None
                                          else encode_context(phase.normalization_context))
        values['phases'].append(value)
    return values


def _restore_result(body):
    from ..ingest.statement import StatementFacts
    from ..ingest.paystub import PayStubFacts
    from ..ingest.brokerage import BrokerageFacts
    from ..ingest.instrument_read import InstrumentReadFacts
    kinds = {kind.__name__: kind for kind in
             (StatementFacts, PayStubFacts, BrokerageFacts, InstrumentReadFacts)}
    value = dict(body)
    facts = value['facts']
    value['facts'] = None if facts is None else kinds[facts['kind']].from_dict(facts['body'])
    context = value['normalization_context']
    value['normalization_context'] = None if context is None else decode_context(context)
    phases = []
    for item in value['phases']:
        item = dict(item)
        context = item['normalization_context']
        item['normalization_context'] = None if context is None else decode_context(context)
        phases.append(ModelPhase(**item))
    value['phases'] = phases
    return ReadResult(**value)


class ImportCheckpoints:
    def __init__(self, vault):
        self.vault = vault
        self.directory = vault.directory / 'import-work'
        self.key = hmac.digest(vault.raw._key, VERSION.encode(), 'sha256')

    def _path(self, document):
        if (type(document) is not str or len(document) != 64
                or any(c not in '0123456789abcdef' for c in document)):
            raise ValueError('invalid document identity')
        return self.directory / (document + '.work')

    def read(self, document):
        path = self._path(document)
        if not path.exists():
            return None
        self._directory()
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, 'rb') as source:
            info = os.fstat(source.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                    or info.st_mode & 0o077 or info.st_size > 24 * 1024 * 1024):
                raise ValueError('continuation envelope unavailable')
            encoded = source.read(24 * 1024 * 1024 + 1)
        if len(encoded) > 24 * 1024 * 1024:
            raise ValueError('continuation exceeds bound')
        body = json.loads(open_sealed(self.key, json.loads(encoded),
                                     aad=(VERSION + ':' + document).encode()))
        if (body.get('version') != VERSION or body.get('document') != document
                or body.get('contract') != extraction_contract()):
            raise ValueError('continuation contract changed')
        return body

    def _directory(self):
        self.directory.mkdir(mode=0o700, exist_ok=True)
        info = self.directory.lstat()
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
                or info.st_mode & 0o077):
            raise ValueError('continuation storage unavailable')

    def write(self, document, body):
        self._directory()
        body = {**body, 'version': VERSION, 'document': document,
                'contract': extraction_contract()}
        encoded = json.dumps(body, ensure_ascii=False, separators=(',', ':')).encode()
        if len(encoded) > 16 * 1024 * 1024:
            raise ValueError('continuation exceeds bound')
        _durable_json(self._path(document), seal(self.key, encoded,
                      aad=(VERSION + ':' + document).encode()))

    def begin(self, owner):
        self.write(owner.document, {'state': 'reading', 'filename': owner.filename,
            'retained': owner.retained, 'original_audit': owner.original_audit,
            'original_captures': owner.original_captures, 'known_type': owner.known_type})

    def complete(self, owner, result):
        from ..ingest.pipeline import _validate_bulk_read
        _validate_bulk_read(owner, result)
        self.write(owner.document, {'state': 'completed', 'filename': owner.filename,
            'dated': owner.dated, 'capture': owner.capture, 'records': owner.records,
            'responses': owner.responses, 'audit_order': owner.audit_order,
            'retained': owner.retained, 'original_audit': owner.original_audit,
            'original_captures': owner.original_captures, 'known_type': owner.known_type,
            'result': _result_body(result)})

    def mark(self, document, state, outcome=None):
        body = self.read(document)
        if body is None:
            raise ValueError('continuation missing')
        self.write(document, {**body, 'state': state, 'outcome': outcome})

    def resume(self, owner, body):
        """Restore only a completed read whose canonical audit remains exact."""
        from ..ingest.pipeline import _audit_bytes, _validate_bulk_read
        source = tuple(owner.ledger.events())
        if body['state'] == 'reading':
            original_ids = {record['event_id'] for record in body.get('original_audit', ())}
            own = [event.to_dict() for event in source if event.body.get('doc_id') == owner.document]
            captures = [record for record in own if record['event_type'] == 'DocumentCaptured']
            if not captures or (not body.get('retained') and len(captures) != 1):
                raise ValueError('capture population unavailable')
            owner.capture = captures[-1]; owner.filename = body['filename']; owner.dated = captures[-1]['occurred_at']
            owner.retained = body.get('retained', False); owner.known_type = body.get('known_type', 'unknown')
            owner.original_audit = tuple(body.get('original_audit', ()))
            owner.original_captures = tuple(body.get('original_captures', ()))
            owner.audit_order = [record for record in own if record['event_type'] in
                {'ReadRecorded', 'ModelExtractionResponseRecorded'} and record['event_id'] not in original_ids]
            owner.records = [record for record in owner.audit_order if record['event_type'] == 'ReadRecorded']
            owner.responses = [record for record in owner.audit_order if record['event_type'] == 'ModelExtractionResponseRecorded']
            if owner.retained:owner.original_prefix = tuple(_audit_bytes(event) for event in source)
            result = _completed_audit_result(owner, source)
            _validate_bulk_read(owner, result)
            self.complete(owner, result)
            body = self.read(owner.document)
        if body['state'] not in {'completed', 'settling'}:
            raise ValueError('external request requires explicit review')
        allowed = {'DocumentCaptured', 'ReadRecorded', 'ModelExtractionResponseRecorded'}
        for event in source:
            if (event.provenance.doc_id == owner.document or event.body.get('doc_id') == owner.document):
                if event.event_type not in allowed:
                    raise ValueError('partial financial settlement requires review')
        owner.filename = body['filename']; owner.dated = body['dated']
        owner.capture = body['capture']; owner.records = body['records']
        owner.responses = body['responses']; owner.audit_order = body['audit_order']
        owner.retained = body['retained']; owner.original_audit = tuple(body['original_audit'])
        owner.original_captures = tuple(body['original_captures']); owner.known_type = body['known_type']
        if owner.retained:
            owner.original_prefix = tuple(_audit_bytes(event) for event in source)
        result = _restore_result(body['result'])
        _validate_bulk_read(owner, result)
        return result


def _completed_audit_result(owner, source):
    """Reparse an acknowledged extraction without another external request."""
    from ..ingest.reader import _peek_classification, _render_and_read_text
    from ..rebuild import _parse_claim
    from ..extraction_responses import validate_links
    from ..ingest.registry import profile_for, INSTRUMENT_IDENTITY, BALANCE_IDENTITY, BROKERAGE_IDENTITY, PAYSTUB_IDENTITY
    bodies = [record['body'] for record in owner.records]
    if (not bodies or bodies[-1].get('phase') != 'extract'
            or bodies[-1].get('parse_ok') is not True):
        raise ValueError('no acknowledged completed extraction')
    phases = []
    linked = []
    for body in bodies:
        if (body.get('transport_complete') is not True or not body.get('transport_receipt_ids')
                or not body.get('extraction_id')):
            raise ValueError('uncertain external extraction')
        validate_links(body, source)
        linked.extend(body['transport_receipt_ids'])
        phases.append(ModelPhase(phase=body['phase'], model=body['model'], prompt_version=body['prompt_version'],
            raw_text=body['response_text'], cost_usd=body.get('cost_usd', 0),
            input_tokens=body.get('input_tokens', 0), output_tokens=body.get('output_tokens', 0),
            input_mode=body.get('input_mode', 'text+image'), parse_ok=body['parse_ok'],
            error=body.get('parse_error'), resolved_model=body.get('resolved_model', ''),
            usage_reported=body.get('usage_reported', False), transport_receipt_ids=body['transport_receipt_ids'],
            transport_complete=True, extraction_id=body['extraction_id'], phase_attempt=body['phase_attempt'],
            normalization_context=(decode_context(body['normalization_context']) if 'normalization_context' in body else None)))
    if linked != [record['event_id'] for record in owner.responses]:
        raise ValueError('unacknowledged external response')
    classified = [body for body in bodies if body.get('phase') == 'classify']
    if not classified:
        raise ValueError('classification unavailable')
    kind, confidence = _peek_classification(classified[-1]['response_text'])
    extract = bodies[-1]
    if 'normalization_context' not in extract:
        raise ValueError('extraction interpretation unavailable')
    context = decode_context(extract['normalization_context'])
    pages, _ = _render_and_read_text(owner.data)
    facts, error, context = _parse_claim(kind, extract, owner.document,
        context.parser_locale, context.parser_currency, page_count=len(pages))
    if facts is None or error:
        raise ValueError('acknowledged extraction cannot be reproduced')
    profile = profile_for(kind)
    identity = profile.identity if profile else ''
    from ..ingest.instrument_read import validate_sources
    from ..investment.payroll_extraction import validate_pages
    if identity == INSTRUMENT_IDENTITY:
        from dataclasses import replace
        facts = replace(facts, doc_type_confidence=confidence)
        validate_sources(facts.payload, owner.document, len(pages))
    else:
        facts.doc_type = kind; facts.doc_type_confidence = confidence
        if identity == PAYSTUB_IDENTITY:
            from ..retirement_funding.payroll_v2 import invalidate_period_pages
            facts = invalidate_period_pages(facts, len(pages)); validate_pages(facts.payroll_source, len(pages))
        elif identity == BROKERAGE_IDENTITY:
            validate_pages(facts.investment_source, len(pages))
            validate_sources([getattr(position, 'classification', None) for position in facts.positions], owner.document, len(pages))
        elif identity == BALANCE_IDENTITY:
            refs = [getattr(facts, 'source_account_ref_page', None)]
            refs += [row.page for row in facts.transactions if row.source_reference or row.counterparty_reference]
            if any(page is not None and (type(page) is not int or not 1 <= page <= len(pages)) for page in refs):
                raise ValueError('reference evidence outside original')
        if identity in (BALANCE_IDENTITY, BROKERAGE_IDENTITY):
            facts.validated_source_page_count = len(pages)
    return ReadResult(kind, confidence, facts=facts, phases=phases,
        source_locale=context.parser_locale, normalization_context=context)
