"""Immutable source-only payroll deduction extension; no model authority."""
from dataclasses import dataclass
from .extraction import SourceField,source_field,source_record
from .contracts import EvidenceError,canonical

HEADERS=('source_reference','currency','pay_date','gross','net')
DEDUCTION=('label','category','amount','destination_reference','contribution_reference')

@dataclass(frozen=True)
class PayrollSourceExtraction:
    headers: tuple
    deductions: tuple
    def __post_init__(self):
        if type(self.headers) is not tuple or type(self.deductions) is not tuple:raise EvidenceError('immutable payroll source required')
        if len(self.deductions)>1000:raise EvidenceError('payroll deduction resource bound')
        if tuple(k for k,v in self.headers)!=HEADERS:raise EvidenceError('closed payroll headers required')
        for record in (self.headers,*self.deductions):
            if type(record) is not tuple or any(type(pair) is not tuple or len(pair)!=2 for pair in record) or any(type(v) is not SourceField and v is not None for k,v in record):raise EvidenceError('typed payroll source fields required')
        if any(tuple(k for k,v in record)!=DEDUCTION for record in self.deductions):raise EvidenceError('closed payroll deduction required')
    def to_dict(self):
        def record(values):return {k:None if v is None else v.to_dict() for k,v in values}
        return {'schema':'payroll-source-v1','headers':record(self.headers),'deductions':[record(row) for row in self.deductions]}

def parse(data):
    if data is None:return None
    if type(data) is dict and data.get('schema')=='payroll-source-v2':
        from viva.retirement_funding.payroll_v2 import parse as parse_v2
        return parse_v2(data)
    if type(data) is not dict or set(data)!={'schema','headers','deductions'} or data['schema']!='payroll-source-v1':raise EvidenceError('unsupported payroll source schema')
    if type(data['deductions']) is not list or len(data['deductions'])>1000:raise EvidenceError('payroll deduction resource bound')
    if len(canonical(data))>262144:raise EvidenceError('payroll source byte bound')
    return PayrollSourceExtraction(source_record(data['headers'],HEADERS),tuple(source_record(row,DEDUCTION) for row in data['deductions']))

def validate_pages(source,page_count):
    if source is None:return
    if type(page_count) is not int or not 1<=page_count<=200:raise EvidenceError('captured source page bound unavailable')
    from viva.retirement_funding.payroll_v2 import PayrollSourceExtractionV2
    if type(source) in (PayrollSourceExtraction,PayrollSourceExtractionV2):records=(source.headers,*source.deductions)
    else:records=(source.headers,*source.positions,*source.rows)
    for record in records:
        for name,value in record:
            if value is not None and value.page is not None and value.page>page_count:raise EvidenceError('source field is outside the captured document')
