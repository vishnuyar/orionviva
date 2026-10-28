"""Closed local curation proposals preserve original cells and normalization."""
from __future__ import annotations
from dataclasses import replace
from datetime import date
from decimal import Decimal
import hashlib
import json
import re
from ..ingest.pipeline_models import ReadResult

CONTRACT = 'curated-source-reading-v2'
MAX_CELLS = 3000
MAX_READING_BYTES = 2000000


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()


def _target(value, pointer):
    if type(pointer) is not str or re.fullmatch(r'(?:/(?:[a-z_]+|0|[1-9][0-9]*))+', pointer) is None:
        raise ValueError('invalid source cell field')
    for part in pointer.split('/')[1:]:
        value = value[int(part)] if type(value) is list else value[part]
    return value


def _requirements(payload, doc_type):
    required = {}
    if doc_type in ('checking_statement', 'savings_statement', 'credit_card_statement'):
        for i, row in enumerate(payload['transactions']):
            required[f'/transactions/{i}/amount_raw'] = ('magnitude', i, row['date_raw'])
            required[f'/transactions/{i}/balance_effect'] = ('balance_effect', i, row['date_raw'])
    elif doc_type in ('brokerage_statement', '401k_statement'):
        if len(payload['activity']) != len(payload['investment_source']['rows']):
            raise ValueError('investment source occurrence count differs')
        for i, row in enumerate(payload['activity']):
            required[f'/activity/{i}/amount_raw'] = ('magnitude', i, row['date_raw'])
            required[f'/investment_source/rows/{i}/amount/raw'] = ('identity', i, row['date_raw'])
    elif doc_type == 'term_deposit_statement':
        for i, row in enumerate(payload['movements']):
            required[f'/movements/{i}/amount/raw'] = ('magnitude', i, row['dated']['raw'])
    elif doc_type == 'mortgage_statement':
        for i, row in enumerate(payload['principal_movements']):
            required[f'/principal_movements/{i}/amount/raw'] = ('magnitude', i, row['dated']['raw'])
        for i, row in enumerate(payload['escrow']['movements']):
            required[f'/escrow/movements/{i}/amount/raw'] = ('magnitude', None, row['dated']['raw'])
    elif doc_type == 'refinance_settlement':
        required['/new_funded_principal/raw'] = ('identity', 0, payload['dated']['raw'])
    elif doc_type not in ('pay_stub', 'property_tax_receipt'):
        raise ValueError('unsupported curated document type')
    return required


def decode_envelope(text, doc_type):
    """Decode only the issued version; every directional cell owns an exact field."""
    if type(text) is not str or len(text.encode()) > MAX_READING_BYTES:
        raise ValueError('curated reading exceeds its byte bound')
    envelope = json.loads(text)
    if type(envelope) is not dict or set(envelope) != {'contract', 'parser_input', 'source_event_ids', 'source_cells'} or envelope['contract'] != CONTRACT:
        raise ValueError('unsupported curated reading envelope')
    payload = envelope['parser_input']; cells = envelope['source_cells']; identifiers = envelope['source_event_ids']
    if type(payload) is not dict or type(cells) is not list or len(cells) > MAX_CELLS or type(identifiers) is not list or len(identifiers) > 1000:
        raise ValueError('invalid curated reading shape')
    if len(set(identifiers)) != len(identifiers) or any(type(v) is not str or re.fullmatch(r'E[0-9]{6}', v) is None for v in identifiers):
        raise ValueError('invalid curated source occurrence identities')
    required = _requirements(payload, doc_type)
    if len(cells) != len(required): raise ValueError('curated source cell coverage differs')
    seen = set(); event_rows = {}; event_ids = set()
    for cell in cells:
        if type(cell) is not dict or set(cell) != {'field', 'raw', 'page', 'association', 'normalization', 'normalized'}:
            raise ValueError('invalid source cell shape')
        pointer = cell['field']
        if pointer not in required or pointer in seen: raise ValueError('foreign or repeated source cell field')
        seen.add(pointer); operation, ordinal, dated = required[pointer]
        if cell['normalization'] != operation or type(cell['raw']) is not str or re.fullmatch(r'[+-]?(?:0|[1-9][0-9]*)\.[0-9]{2}', cell['raw']) is None:
            raise ValueError('source cell normalization differs')
        if type(cell['page']) is not int or not 1 <= cell['page'] <= 200:
            raise ValueError('source cell page is invalid')
        amount = Decimal(cell['raw'])
        normalized = cell['raw'] if operation == 'identity' else str(abs(amount)) if operation == 'magnitude' else 'increase' if amount >= 0 else 'decrease'
        if cell['normalized'] != normalized or _target(payload, pointer) != normalized:
            raise ValueError('source cell does not normalize to its exact parser field')
        association = cell['association']
        if type(association) is not dict or association.get('date') != dated or date.fromisoformat(dated).isoformat() != dated:
            raise ValueError('source cell date association differs')
        if ordinal is not None:
            if set(association) != {'kind', 'row_reference', 'date'} or association['kind'] != 'event' or ordinal >= len(identifiers) or association['row_reference'] != identifiers[ordinal]:
                raise ValueError('source cell occurrence association differs')
            key = association['row_reference']; event_ids.add(key)
            witness = (dated, cell['raw'], cell['page'])
            if key in event_rows and event_rows[key] != witness: raise ValueError('source occurrence has conflicting cells')
            event_rows[key] = witness
            if pointer.startswith('/investment_source/'):
                row = payload['investment_source']['rows'][ordinal]
                if row['printed_row_reference']['raw'] != key or row['date']['raw'] != dated:
                    raise ValueError('investment occurrence source differs')
        else:
            if set(association) != {'kind', 'row_reference', 'date', 'row_kind'} or association['kind'] != 'escrow' or type(association['row_kind']) is not str or re.fullmatch(r'[a-z_]{1,80}', association['row_kind']) is None:
                raise ValueError('escrow occurrence association differs')
            i = int(pointer.split('/')[3]); row = payload['escrow']['movements'][i]
            if row['reference']['raw'] != association['row_reference']:
                raise ValueError('escrow source reference differs')
    if event_ids != set(identifiers): raise ValueError('source occurrence coverage is incomplete')
    return envelope


def decode_retained_input(body):
    """Return exact ordinary parser input from an authenticated local receipt."""
    from ..acquisition import local_read
    if not local_read(body): raise ValueError('retained reading is not local curation')
    envelope = decode_envelope(body['response_text'], body['doc_type'])
    return canonical(envelope['parser_input']).decode()


def validate_pdf_cells(data, envelope):
    """Associate signed source tokens with their original physical rows."""
    import pypdfium2 as pdfium
    if len(data) > 50 * 1024 * 1024: raise ValueError('source document exceeds its byte bound')
    document = pdfium.PdfDocument(data); pages = []
    try:
        if not 1 <= len(document) <= 200: raise ValueError('source page count is outside its bound')
        for number in range(len(document)):
            page = document[number]
            try:
                text = page.get_textpage()
                try:
                    if text.count_chars() > 256000: raise ValueError('source text exceeds its bound')
                    pages.append(text.get_text_range())
                finally: text.close()
            finally: page.close()
    finally: document.close()
    for cell in envelope['source_cells']:
        association = cell['association']
        if association['kind'] == 'event':
            pattern = re.compile(r'\b' + re.escape(association['row_reference']) + r'\s*/\s*' + re.escape(association['date']))
            boundary = r'\bE[0-9]{6}\s*/\s*[0-9]{4}-[0-9]{2}-[0-9]{2}'
        else:
            pattern = re.compile(re.escape(association['date']) + r'\s*/\s*' + re.escape(association['row_kind']) + r'\b')
            boundary = r'[0-9]{4}-[0-9]{2}-[0-9]{2}\s*/\s*[a-z_]+|Transactions - signed effect'
        matches = [(i + 1, match) for i, text in enumerate(pages) for match in pattern.finditer(text)]
        if len(matches) != 1 or matches[0][0] != cell['page']:
            raise ValueError('source cell is not on its associated physical row')
        number, match = matches[0]; text = pages[number - 1]; tail = text[match.end():]
        next_row = re.search(boundary, tail)
        if next_row: tail = tail[:next_row.start()]
        if association['kind'] == 'escrow' and association['row_reference'] not in tail:
            raise ValueError('escrow row source reference differs')
        values = re.findall(r'(?<![\d.])([+-]?[0-9]+\.[0-9]{2})(?![\d.])', tail)
        if not values or values[-1] != cell['raw']:
            raise ValueError('source cell signed token differs from the original row')
    return len(pages)


def _facts(data, doc_id, body):
    from ..rebuild import _parse
    from ..ingest.instrument_read import InstrumentReadFacts, validate_sources
    from ..investment.payroll_extraction import validate_pages
    text = decode_retained_input(body)
    envelope = decode_envelope(body['response_text'], body['doc_type'])
    page_count = validate_pdf_cells(data, envelope)
    facts, error = _parse(body['doc_type'], text, doc_id, body['normalization_locale'], body['source_currency'])
    if facts is not None:
        if isinstance(facts, InstrumentReadFacts): validate_sources(facts.payload, doc_id, page_count)
        else:
            validate_pages(getattr(facts, 'payroll_source', None), page_count)
            validate_pages(getattr(facts, 'investment_source', None), page_count)
            if hasattr(facts, 'validated_source_page_count'):
                reference_page = getattr(facts, 'source_account_ref_page', None)
                if reference_page is not None and (type(reference_page) is not int or not 1 <= reference_page <= page_count):
                    raise ValueError('reference evidence is outside the captured document')
                facts.validated_source_page_count = page_count
            facts.doc_type = body['doc_type']
    return facts, error


class RetainedCuratedReader:
    """Replay retained bytes and their closed reading without an installed bundle."""
    def __init__(self, body):
        decode_retained_input(body)
        self.body = json.loads(json.dumps(body))

    def __call__(self, data, doc_id):
        body = self.body
        if hashlib.sha256(data).hexdigest() != doc_id or body['doc_id'] != doc_id:
            raise ValueError('retained original does not match local reading')
        facts, error = _facts(data, doc_id, body)
        if facts is not None: facts = replace(facts, doc_type_confidence=None, acquisition=dict(body['acquisition']))
        return ReadResult(body['doc_type'], None, facts, error, raw_text=body['response_text'],
                          source_locale=body['normalization_locale'], acquisition=dict(body['acquisition']))


class CuratedReader:
    """Issue local readings only after the complete installed pack is validated."""
    def __init__(self, pack):
        from .resources import load_pack
        self.pack = load_pack(pack.root)

    def __call__(self, data, doc_id):
        from .resources import VERSION, MANIFEST_SHA256, READINGS_SHA256
        if hashlib.sha256(data).hexdigest() != doc_id or doc_id not in self.pack.readings:
            raise ValueError('document is not an installed sample source')
        row = self.pack.readings[doc_id]; text = canonical(row['envelope']).decode()
        source = {'kind': 'local-curation-v1', 'sample_version': VERSION,
                  'corpus_manifest_sha256': MANIFEST_SHA256, 'readings_sha256': READINGS_SHA256,
                  'reading_contract': CONTRACT, 'document_sha256': doc_id,
                  'reading_sha256': hashlib.sha256(text.encode()).hexdigest()}
        body = {'doc_id': doc_id, 'doc_type': row['doc_type'], 'response_text': text,
                'parse_ok': True, 'parse_error': None, 'phase': 'extract', 'acquisition': source,
                'normalization_locale': row['locale'], 'source_currency': row['currency']}
        return RetainedCuratedReader(body)(data, doc_id)
