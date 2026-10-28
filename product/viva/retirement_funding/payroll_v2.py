"""Versioned printed payroll periods; legacy economic source bytes stay unchanged."""
from dataclasses import dataclass, replace
from viva.investment.contracts import Field, EvidenceError, canonical, day
from viva.investment.extraction import SourceField, source_record
from viva.investment.payroll_extraction import PayrollSourceExtraction, HEADERS, DEDUCTION

V2_HEADERS = (*HEADERS, 'period_start', 'period_end')

@dataclass(frozen=True)
class PayrollSourceExtractionV2:
    headers: tuple
    deductions: tuple

    def __post_init__(self):
        if type(self.headers) is not tuple or tuple(k for k, v in self.headers) != V2_HEADERS:
            raise EvidenceError('closed v2 payroll headers required')
        legacy(self)
        if any(type(v) is not SourceField and v is not None for k, v in self.headers):
            raise EvidenceError('typed payroll period fields required')

    def to_dict(self):
        def record(values):
            return {k: None if v is None else v.to_dict() for k, v in values}
        return {'schema': 'payroll-source-v2', 'headers': record(self.headers), 'deductions': [record(row) for row in self.deductions]}


def legacy(value):
    if type(value) is not PayrollSourceExtractionV2:
        raise EvidenceError('explicit v2 source projection required')
    return PayrollSourceExtraction(tuple((k, v) for k, v in value.headers if k in HEADERS), value.deductions)


def parse(data):
    if type(data) is not dict or set(data) != {'schema', 'headers', 'deductions'} or data['schema'] != 'payroll-source-v2':
        raise EvidenceError('unsupported payroll period schema')
    if type(data['deductions']) is not list or len(data['deductions']) > 1000 or len(canonical(data)) > 262144:
        raise EvidenceError('payroll source resource bound')
    return PayrollSourceExtractionV2(source_record(data['headers'], V2_HEADERS), tuple(source_record(row, DEDUCTION) for row in data['deductions']))


def economic_facts(facts):
    """Explicit source-version conversion supplies only the existing witness fields."""
    return replace(facts, payroll_source=legacy(facts.payroll_source))


def periods(facts, locale='en-US'):
    from vivacore.verify.normalize import parse_date
    if type(facts.payroll_source) is not PayrollSourceExtractionV2:
        raise EvidenceError('new sourced payroll period required')
    headers = dict(facts.payroll_source.headers)
    result = []
    for name in ('period_start', 'period_end'):
        raw = headers[name]
        expected = getattr(facts, name)
        status = 'unavailable'
        if raw is not None:
            normalized = parse_date(raw.raw, locale)
            if normalized.ok and raw.page is not None:
                status = 'accepted' if normalized.value == expected else 'conflicted'
            result.append(Field(expected, facts.doc_id, raw.page, status=status, raw=raw.raw))
        else:
            result.append(Field(expected, facts.doc_id, None, status=status))
    if all(field.status == 'accepted' for field in result):
        day(result[0].value); day(result[1].value)
        if result[0].value > result[1].value:
            result = [replace(field, status='conflicted') for field in result]
    return tuple(result)


def invalidate_period_pages(facts,page_count):
    """Only unsupported new period anchors are removed; raw reading stays retained."""
    if type(facts.payroll_source) is not PayrollSourceExtractionV2:
        return facts
    if type(page_count) is not int or not 1<=page_count<=200:
        raise EvidenceError('actual captured payroll page bound unavailable')
    source=facts.payroll_source
    headers=tuple((key,None if key in ('period_start','period_end') and value is not None and value.page is not None and value.page>page_count else value) for key,value in source.headers)
    if headers==source.headers:return facts
    return replace(facts,payroll_source=replace(source,headers=headers))
