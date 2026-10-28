"""Closed source-section presentation; no financial values or calculations."""
from dataclasses import fields,is_dataclass
from ..ingest import instrument_contracts as c
from .documents_page import DocumentsPageError

LABELS={
 'deposit_terms':'Deposit terms and maturity','deposit_balance':'Deposit balance',
 'mortgage_terms':'Mortgage contract terms','principal_balance':'Loan period principal balance',
 'loan_period':'Loan period','payments':'Mortgage payments','escrow_balance':'Escrow balance and disbursements',
 'settlement_sources_uses':'Refinance sources and uses','settlement_fees':'Refinance fee total',
 'financed_fees':'Financed closing costs','old_loan_zero':'Old loan closing balance',
 'settlement_relationship':'Old and replacement loan relationship','old_loan_payoff_link':'Old loan payoff witness',
 'settlement_cash_fee':'Separately paid closing fees','tax_paid':'Paid property-tax receipt',
 'tax_payment_link':'Property-tax disbursement match','maturity':'Maturity receipt',
}
OBSERVATIONS={
 'deposit_terms':'Deposit terms','mortgage_terms':'Mortgage contract terms',
 'availability':'Withdrawal restriction source','deposit_components':'Term deposit source',
 'mortgage_components':'Mortgage statement source','refinance':'Refinance settlement source',
 'tax_receipt':'Property-tax receipt source','position_classification':'Printed investment classification',
 'apr_context_v1':'APR disclosure context',
}
REASONS={
 'accepted':'The section passed its applicable source checks.',
 'missing_printed_fields':'Some required printed fields are missing or unreadable.',
 'unmatched_counterpart':'A unique compatible counterpart source has not been established.',
 'conflicting_source':'The source conflicts with a retained interpretation.',
 'identity_unresolved':'The source account identity or currency is unresolved.',
 'reconciliation_failed':'The printed section has not reconciled.',
 'source_unavailable':'This section is not supplied by the source.',
 'review_required':'This section remains unresolved. Inspect its source before relying on it.',
}


def source_pages(value,doc_id,fallback=None):
    pages=set();visited=0
    def walk(item):
        nonlocal visited
        visited+=1
        if visited>10000:raise DocumentsPageError('detail_resource_limit')
        if isinstance(item,c.Source):
            if item.doc_id!=doc_id or not 1<=item.page<=200:raise DocumentsPageError('invalid_detail_evidence')
            pages.add(item.page)
        elif is_dataclass(item):
            for field in fields(item):walk(getattr(item,field.name))
        elif type(item) in (tuple,list):
            for row in item:walk(row)
    walk(value)
    if not pages and fallback is not None:
        walk(fallback)
    if len(pages)>32:raise DocumentsPageError('detail_resource_limit')
    return [{'document_id':doc_id,'page':page,'label':f'Source page {page}'} for page in sorted(pages)]


def reason_view(component):
    reason=component.reason
    if component.disposition==c.Disposition.ACCEPTED:code='accepted'
    elif component.disposition==c.Disposition.UNAVAILABLE:code='source_unavailable'
    elif reason.startswith('missing printed components:'):code='missing_printed_fields'
    elif 'counterpart' in reason or 'witness required' in reason:code='unmatched_counterpart'
    elif 'conflict' in reason:code='conflicting_source'
    elif 'identity' in reason or 'currency binding' in reason:code='identity_unresolved'
    elif component.check is not None and not component.check.passed:code='reconciliation_failed'
    else:code='review_required'
    return code,REASONS[code]


def component_view(component,payload,doc_id,fallback):
    key=component.component;label=LABELS.get(key);kind=key;section=payload
    if key.startswith('payment:'):
        kind='payment';reference=key[len('payment:'):]
        if not reference or len(reference.encode('utf-8'))>512:raise DocumentsPageError('invalid_detail_evidence')
        payments=getattr(payload,'payments',None) or ()
        matched=tuple(row for row in payments if row.reference is not None and row.reference.value==reference)
        label=('Payment '+reference if matched else 'Payment with missing reference' if reference=='unresolved' else
            'Payment row '+reference[4:]+' (reference missing)' if reference.startswith('row:') and reference[4:].isdigit() else 'Payment '+reference)
        section=matched or payments
    elif key.startswith('counterpart:'):
        kind='counterpart';reference=key[len('counterpart:'):]
        if not reference or len(reference.encode('utf-8'))>512:raise DocumentsPageError('invalid_detail_evidence')
        movements=getattr(payload,'movements',None) or ()
        section=tuple(row for row in movements if row.reference is not None and row.reference.value==reference)
        label=('Maturity redemption match ' if section and all(row.kind==c.DepositKind.REDEMPTION for row in section) else 'Funding or redemption match ')+reference
    elif key in ('deposit_terms','mortgage_terms'):section=getattr(payload,'terms',None)
    elif key=='escrow_balance':section=getattr(payload,'escrow',None)
    elif key=='deposit_balance' and getattr(payload,'subtype',None)==c.DepositSubtype.MATURITY:label='Maturity deposit balance'
    if label is None:raise DocumentsPageError('unknown_source_component')
    code,reason=reason_view(component)
    return {'component':key,'kind':kind,'label':label,'disposition':component.disposition.value,
        'reason_code':code,'reason':reason,'source_pages':source_pages(section,doc_id,fallback)}
