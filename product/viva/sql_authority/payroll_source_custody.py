"""Backend page metadata requires authenticated physical source and parser inputs."""
from __future__ import annotations

import hashlib

from ..normalization_context import decode_context, source_contract_for_claim
from ..ingest.paystub import from_paystub_json
from ..investment.payroll_extraction import validate_pages
from ..retirement_funding.payroll_v2 import invalidate_period_pages
from .store import MAX_SOURCE_BYTES


def _physical_page_count(store, doc_id):
    data, _commitment = store._original_with_commitment(doc_id)
    if (type(data) is not bytes or not 0 < len(data) <= MAX_SOURCE_BYTES
            or hashlib.sha256(data).hexdigest() != doc_id):
        raise ValueError('payroll original differs from its authenticated address')
    import pypdfium2 as pdfium
    document = None
    try:
        document = pdfium.PdfDocument(data)
        count = len(document)
        if type(count) is not int or not 1 <= count <= 200:
            raise ValueError('payroll physical page extent is outside the supported bound')
        return count
    except Exception as error:
        raise ValueError('payroll physical PDF extent is unavailable') from error
    finally:
        if document is not None:
            document.close()


def _parser_context(reading, facts):
    value = reading.get('normalization_context')
    if type(value) is not dict:
        raise ValueError('count-bearing payroll requires captured parser inputs')
    value = dict(value)
    # SQL dataclass capture retains its default None; encoded native records
    # omit that field for schema one. These are the two declared closed forms.
    if value.get('schema_version') == 1 and 'instrument_source_contract' in value:
        if value['instrument_source_contract'] is not None:
            raise ValueError('payroll parser contract differs')
        value.pop('instrument_source_contract')
    context = decode_context(value)
    if (context.schema_version != 1
            or context.parser_locale != reading.get('source_locale')
            or type(context.parser_currency) is not str
            or not context.parser_currency.strip()
            or context.parser_currency != facts.currency):
        raise ValueError('payroll captured parser inputs differ')
    source_contract_for_claim(context, 'pay_stub', reading.get('prompt_version', ''))
    return context


def _bounded_pages(facts, count):
    for page in (facts.gross_page, facts.net_page):
        if page is not None and (type(page) is not int or not 1 <= page <= count):
            raise ValueError('payroll financial page is outside the captured document')
    validate_pages(facts.payroll_source, count)


def reparse_physically_bound_payroll(store, doc_id, reading, facts):
    """Independently prove a count before reannotating newly parsed facts.

    Both interpretation and semantic audit call this against authenticated raw
    originals. It never trusts a model-supplied count or edits captured facts.
    """
    count = _physical_page_count(store, doc_id)
    if type(facts.validated_source_page_count) is not int or facts.validated_source_page_count != count:
        raise ValueError('captured payroll count differs from physical PDF extent')
    context = _parser_context(reading, facts)
    if type(reading.get('raw_text')) is not str or not reading['raw_text']:
        raise ValueError('count-bearing payroll requires its retained raw response')
    _bounded_pages(facts, count)
    parsed, error = from_paystub_json(reading['raw_text'], doc_id,
                                    context.parser_locale, context.parser_currency)
    if parsed is None or error:
        raise ValueError('payroll raw response cannot normalize')
    parsed = invalidate_period_pages(parsed, count)
    _bounded_pages(parsed, count)
    parsed.validated_source_page_count = count
    return parsed
