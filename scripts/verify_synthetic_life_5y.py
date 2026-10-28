#!/usr/bin/env python3
"""Independent Decimal/PDF oracle; never imports generator or product calculations."""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict, deque
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import json
from pathlib import Path
import re

ZERO = Decimal(0)
# Frozen campaign instrument semantics; independent of generator and product.
CLASSIFICATIONS = {
    'FXNAX': ('bond', 'mutual_fund'),
    'FSKAX': ('equity', 'mutual_fund'),
    'VTSAX': ('equity', 'mutual_fund'),
    'SWPPX': ('equity', 'mutual_fund'),
    'AAPL': ('equity', 'individual_security'),
    'MSFT': ('equity', 'individual_security'),
}

COUNTS = {'checking':60,'savings':60,'credit-card':300,'brokerage':120,'retirement':60,'payroll':60,'mortgage':60,'cd':60,'cd-opening':4,'cd-maturity':4,'refinance':1,'property-tax':5}

# These are the approved campaign's frozen source disclosures, not semantic
# keyword tests. An opposite or additional promise must not authenticate itself.
CD_RESTRICTION_DISCLOSURE = (
    'Principal and credited interest remain restricted in this term-deposit account '
    'until the sourced maturity redemption transfers them to SAVE-A.'
)
CD_CONVENTION_DISCLOSURE = (
    'Fictional twelve-equal-month year; each complete credited month earns principal '
    'times nominal annual percentage rate divided by 1200; only whole-month schedules '
    'supported. Not actual_365 or actual_360.'
)
RETIREMENT_ALLOCATION_DISCLOSURE = 'Contribution target only; market values drift'


def verify_closed_disclosures(facts, family, context):
    if family in {'cd-opening','cd','cd-maturity'}:
        need(facts.get('restriction_text')==CD_RESTRICTION_DISCLOSURE,
             f'{context}: CD restriction disclosure differs from approved closed source')
        need(facts.get('convention_definition')==CD_CONVENTION_DISCLOSURE,
             f'{context}: equal-month convention disclosure differs from approved closed source')
    if family=='retirement':
        need(facts.get('allocation_policy')==RETIREMENT_ALLOCATION_DISCLOSURE,
             f'{context}: allocation drift disclosure differs from approved closed source')


class VerificationError(ValueError):
    """A source fact, PDF, or completeness requirement failed."""

def need(condition, message):
    if not condition:
        raise VerificationError(message)

def D(value):
    need(isinstance(value, (str, int, Decimal)) and not isinstance(value, bool), f'Inexact decimal: {value!r}')
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise VerificationError(f'Invalid decimal {value!r}') from exc
    need(result.is_finite(), f'Nonfinite decimal: {value!r}')
    return result

def cents(value):
    return D(value).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)

def eq(actual, expected, context):
    need(D(actual) == D(expected), f'{context}: {actual} != {expected}')

def payment(principal, apr, months):
    rate = D(apr) / 12
    return cents(D(principal) * rate / (1 - (1 + rate) ** -int(months)))

def numeric_leaves(value):
    if isinstance(value, dict):
        for key, child in value.items():
            if isinstance(child, (dict, list)):
                yield from numeric_leaves(child)
            elif isinstance(child, str) and re.fullmatch(r'-?\d+(?:\.\d+)?', child):
                yield key, child
    elif isinstance(value, list):
        for child in value:
            yield from numeric_leaves(child)

def verify_transfers(events):
    groups = defaultdict(list)
    for e in events:
        if e.get('transfer_ref'):
            groups[e['transfer_ref']].append(e)
    need(groups, 'No mirrored transfers')
    for ref, legs in groups.items():
        if ref.startswith(('PAY-', 'RET-CONTRIB-', 'REFI-FEES')):
            need(len(legs) == 1, f'{ref}: expected one source event and document witness')
            continue
        need(len(legs) == 2, f'{ref}: transfer must have two legs')
        a,b = legs
        need(a['account_ref'] != b['account_ref'], f'{ref}: same account')
        need(a.get('counterpart_ref') == b['account_ref'] and b.get('counterpart_ref') == a['account_ref'], f'{ref}: counterpart mismatch')
        need(a['date'] == b['date'] and a['currency'] == b['currency'], f'{ref}: date/currency mismatch')
        kinds={a['kind'],b['kind']}
        if kinds == {'card_payment','payment'}:
            eq(a['amount'],b['amount'],f'{ref}: card settlement')
            need(D(a['amount']) < 0,f'{ref}: settlement sign')
        elif kinds == {'mortgage_payment','principal_payment'}:
            need(D(a['amount']) < 0 and D(b['amount']) < 0, f'{ref}: mortgage sign')
        else:
            eq(D(a['amount']) + D(b['amount']), ZERO, f'{ref}: transfer amounts')
    return groups

def verify_fifo(events, initial_positions=()):
    lots = defaultdict(deque)
    for p in initial_positions:
        lots[p['security']].append([D(p['units']), D(p['cost_basis'])])
    for e in sorted(events, key=lambda x:(x['date'],x['id'])):
        if e['kind'] not in {'buy','sell','purchase','sale','reinvest'}:
            continue
        qty,price = D(e['units']),D(e['unit_price'])
        need(qty > 0 and price > 0, f'{e["id"]}: nonpositive trade')
        gross,fee = cents(qty * price),D(e.get('fee','0'))
        queue = lots[e['security']]
        if e['kind'] in {'buy','purchase','reinvest'}:
            eq(e['amount'], -gross-fee, f'{e["id"]}: buy cash')
            queue.append([qty,gross+fee])
        else:
            eq(e['amount'], gross-fee, f'{e["id"]}: sell cash')
            remaining,basis = qty,ZERO
            while remaining > 0:
                need(bool(queue), f'{e["id"]}: uncovered sale')
                n,cost = queue[0]
                take = min(n,remaining)
                used = cost if take == n else cents(cost*take/n)
                basis += used
                remaining -= take
                if take == n:
                    queue.popleft()
                else:
                    queue[0] = [n-take,cost-used]
            eq(e['realized_gain'], gross-fee-basis, f'{e["id"]}: FIFO realized gain')
            if e.get('cost_basis'):
                eq(e['cost_basis'],basis,f'{e["id"]}: sold cost basis')
    return {s:(sum((x[0] for x in q),ZERO),sum((x[1] for x in q),ZERO)) for s,q in lots.items()}

def verify_pdf(path, doc, events):
    import fitz
    need(path.is_file(), f'Missing PDF {path}')
    with fitz.open(path) as pdf:
        need(len(pdf)>0, f'Empty PDF {path}')
        texts=[]
        for i,page in enumerate(pdf):
            text=page.get_text()
            need('SYNTHETIC TEST DOCUMENT' in text and 'NOT ISSUED BY THE NAMED INSTITUTION' in text, f'{path.name} page {i+1}: missing marker')
            for block in page.get_text('dict')['blocks']:
                for line in block.get('lines',[]):
                    for span in line.get('spans',[]):
                        x0,y0,x1,y1=span['bbox']
                        need(x0>=0 and y0>=0 and x1<=page.rect.width+.5 and y1<=page.rect.height+.5, f'{path.name}: clipped text {span["text"]!r}')
            texts.append(text)
        verify_printed_text('\n'.join(texts),doc,events,path.name)
        return len(pdf)


def escrow_row_text(row):
    source=row['source_event_id'] or 'none (existing escrow effect; not a new cash event)'
    return (f"{row['date']} / {row['kind']} Reference: {row['reference']} | "
            f"Escrow account: {row['escrow_account_ref']} | Source account: {row['source_account_ref']} | "
            f"Destination account: {row['destination_account_ref']} | Property: {row['property_ref']} | "
            f"Tax year: {row['tax_year']} | Source event: {source} {row['amount']}")


def fee_row_text(row):
    return f"Fee: {row['name']} | Amount: {row['amount']} USD | Reference: {row['reference']}"


def verify_printed_components(compact,doc,name):
    facts=doc['facts']
    rows=facts.get('escrow_components',[])
    actual_rows=re.findall(r'\b\d{4}-\d{2}-\d{2} / (?:deposit|property_tax_disbursement)\b',compact)
    need(len(actual_rows)==len(rows),f'{name}: printed escrow component count')
    for row in rows:
        target=escrow_row_text(row)
        need(re.search(re.escape(target)+r'(?![\w.])',compact),f'{name}: printed escrow component fields differ: {row["reference"]}')
    fees=facts.get('fee_items',[])
    need(len(re.findall(r'\bFee:',compact))==len(fees),f'{name}: printed itemized fee count')
    for fee in fees:
        need(re.search(re.escape(fee_row_text(fee))+r'(?![\w-])',compact),f'{name}: printed itemized fee fields differ')
    for row in facts.get('deductions',[]):
        if row['category']=='retirement':
            target=(f"{row['label']} | {row['category']} | {row['amount']} USD | "
                    f"Contribution reference: {row['contribution_ref']} | Retirement account: {row['retirement_account_ref']}")
            need(re.search(re.escape(target)+r'(?![\w-])',compact),f'{name}: printed retirement deduction contribution/plan reference')


def compact_source_text(text):
    compact=' '.join(text.split())
    compact=re.sub(r'SYNTHETIC TEST DOCUMENT [—-] NOT ISSUED BY THE NAMED INSTITUTION',' ',compact)
    compact=re.sub(r'Fictional Alex Morgan \| D[0-9]+ \| [A-Z][A-Z0-9-]+',' ',compact)
    compact=re.sub(r'\bPage [0-9]+\b',' ',compact)
    return ' '.join(compact.split())


def verify_printed_text(text, doc, events, name='extracted source'):
    """Check extracted source fields, preserving opening/closing and row boundaries.

    Security names are ordinary text inside their own row. Numeric fields are
    parsed from that row, never satisfied by values elsewhere on the statement.
    """
    verify_closed_disclosures(doc['facts'],doc.get('family'),name)
    verify_loan_apr_source(doc['facts'],doc.get('family'),doc['account_ref'],name)
    need(doc['account_ref'] in text, f'{name}: missing account')
    compact=compact_source_text(text)
    header=f"Document {doc['id']} | Account reference {doc['account_ref']} | {doc['currency']} | {doc['locale']}"
    need(re.search(re.escape(header)+r'(?![\w-])',compact),f'{name}: document/account/currency/locale header differs')
    period=f"Period {doc['period_start']} to {doc['period_end']} | As of {doc['as_of']}"
    need(re.search(re.escape(period)+r'(?![\w.-])',compact),f'{name}: source period/as-of differs')
    for key,title in [('opening_positions','Opening holdings'),('positions','Closing holdings')]:
        if key in doc['facts']:
            need(compact.count(title)==1,f'{name}: missing or repeated {title} boundary')
    scalar_spans=[]
    for key,value in doc['facts'].items():
        if isinstance(value,(dict,list)):
            continue
        label=key.replace('_',' ').capitalize()+': '
        matches=list(re.finditer(re.escape(label),compact))
        need(len(matches)==1,f'{name}: printed field {label!r} absent or duplicated')
        match=matches[0]
        scalar_spans.append((match.start(),match.end(),key,str(value)))
    boundaries=[m.start() for m in re.finditer(r'Opening holdings|Closing holdings|Current-period deductions|Restricted escrow component witnesses|Separately paid closing fees|Transactions - signed effect',compact)]
    scalar_starts=[x[0] for x in scalar_spans]
    for start,end,key,value in scalar_spans:
        limit=min([x for x in scalar_starts+boundaries if x>start]+[len(compact)])
        actual=compact[end:limit].strip()
        need(actual==value,f'{name}: printed field {key} differs: {actual!r} != {value!r}')
    for row in doc['facts'].get('deductions',[]):
        need(f"{row['label']} | {row['category']} | {row['amount']} USD" in compact,f'{name}: deduction differs')
    verify_printed_components(compact,doc,name)
    for key,title,next_title in [('opening_positions','Opening holdings','Closing holdings'),
                                 ('positions','Closing holdings','Transactions')]:
        if key not in doc['facts']:
            continue
        need(compact.count(title)==1,f'{name}: missing or repeated {title} boundary')
        section=compact.split(title,1)[1]
        if next_title in section:
            section=section.split(next_title,1)[0]
        # Eight decimal share quantities anchor each row even when a security
        # name wraps or contains a numeric index name such as S&P 500.
        pattern=r'\b([A-Z][A-Z0-9.]{1,7})\b\s+((?:(?!\d+\.\d{8}).)*?)' + \
                r'(-?\d+\.\d{8})\s+(-?\d+\.\d{2})\s+(-?\d+\.\d{2})\s+(-?\d+\.\d{2})(?![\d.])' + \
                r'\s+Exposure class: (bond|equity);\s+Vehicle: (mutual_fund|individual_security)\b'
        parsed={}
        for match in re.finditer(pattern,section):
            ticker,security_name,units,price,value,basis,exposure,vehicle=match.groups()
            # The first row may include the table headings before its ticker.
            tokens=security_name.split()
            if ticker=='Security' or ticker=='Units':
                continue
            need(ticker not in parsed,f'{name}: duplicate {title} security {ticker}')
            parsed[ticker]=(units,price,value,basis,exposure,vehicle)
        expected={p['security']:tuple(p[k] for k in ('units','unit_price','market_value','cost_basis','exposure_class','vehicle')) for p in doc['facts'][key]}
        need(parsed==expected,f'{name}: printed {title.lower()} rows differ: {parsed} != {expected}')
    transaction_heading='Transactions - signed effect'
    need(compact.count(transaction_heading)==(1 if events else 0),f'{name}: transaction evidence section count')
    transactions=compact.split(transaction_heading,1)[1] if events else ''
    starts=list(re.finditer(r'\bE[0-9]{6}\b',transactions))
    need(len(starts)==len(events),f'{name}: printed event count differs')
    rows={m.group():transactions[m.start():(starts[i+1].start() if i+1<len(starts) else len(transactions))] for i,m in enumerate(starts)}
    need(set(rows)=={e['id'] for e in events},f'{name}: printed event identity set differs')
    number=r'-?\d+(?:\.\d+)?'
    for e in events:
        row=rows[e['id']]
        need(re.search(re.escape(e['id'])+r' / '+re.escape(e['date'])+r'\b',row),f'{name}: event date')
        need(f"{e['description']} | Kind {e['kind']}" in row,f'{name}: event description/kind')
        if e['transfer_ref']:
            need(re.search(re.escape(f"Link {e['transfer_ref']} | Counterpart {e['counterpart_ref']}")+r'(?:\s+\||\s+-?\d)',row),f'{name}: printed transfer counterpart')
        if e['security']:
            need(re.search(r'Security '+re.escape(e['security'])+r'\b',row),f'{name}: event security')
        for field,label in [('units','Units'),('unit_price','Unit price'),('cost_basis','Cost basis'),('realized_gain','Realized gain'),('fee','Fee')]:
            if e.get(field) not in ('',None):
                match=re.search(r'(?:\|\s*)?'+label+r' ('+number+r')(?![\d.])',row)
                need(match is not None,f'{name}: missing {label} for {e["id"]}')
                eq(match.group(1),e[field],f'{name}: printed {e["id"]} {label}')
        # Locate the amount after all labelled detail fields, rather than letting
        # a trade price, basis or gain satisfy a missing final amount column.
        detail_labels=list(re.finditer(r'(?:Units|Unit price|Cost basis|Realized gain|Fee) '+number,row))
        if detail_labels:
            tail=row[detail_labels[-1].end():]
        elif e['security']:
            tail=row.split('Security '+e['security'],1)[1]
        elif e['transfer_ref']:
            tail=row.split('Counterpart '+e['counterpart_ref'],1)[1]
        else:
            tail=row.split('Kind '+e['kind'],1)[1]
        amount=re.search(r'(?<![\w.])('+number+r')(?![\w.])',tail)
        need(amount is not None,f'{name}: missing final event amount')
        eq(amount.group(1),e['amount'],f'{name}: printed {e["id"]} cash/balance effect')

def verify_salary(docs, events, complete):
    stubs=sorted([d for d in docs if d['family']=='payroll'],key=lambda d:d['period_end'])
    if not stubs:
        need(not complete,'No payroll stubs')
        return
    totals=defaultdict(lambda:ZERO)
    for doc in stubs:
        f=doc['facts']; ym=doc['period_end'][:7]
        employer,annual,plan=('Microsoft',220000,'RET-A') if ym<'2023-01' else (('Amazon',250000,'RET-B') if ym<'2024-07' else ('Salesforce',285000,'RET-C'))
        need(f['employer']==employer,f'{ym}: wrong employer')
        eq(f['annual_salary'],annual,f'{ym}: annual salary')
        need(f['retirement_account_ref']==plan,f'{ym}: retirement plan')
        deposits=[e for e in events if e['kind']=='payroll' and e['date']==f['pay_date']]
        need(len(deposits)==1,f'{ym}: unique payroll deposit')
        eq(deposits[0]['amount'],f['net'],f'{ym}: salary deposit')
        need(deposits[0]['account_ref']==f['deposit_account_ref'] and deposits[0]['counterpart_ref']==employer,f'{ym}: payroll source/destination')
        contributions=[e for e in events if e['kind']=='contribution' and e['transfer_ref'].startswith('RET-CONTRIB-') and e['date']==f['pay_date']]
        need(len(contributions)==1,f'{ym}: unique retirement contribution')
        contribution=contributions[0]
        need(contribution['account_ref']==plan and contribution['counterpart_ref']==doc['account_ref'],f'{ym}: contribution source/plan')
        eq(contribution['amount'],sum((D(x['amount']) for x in f['deductions'] if x['category']=='retirement'),ZERO),f'{ym}: payroll contribution')
        eq(contribution['amount'],1000,f'{ym}: contribution assumption')
        totals[doc['period_end'][:4]]+=D(f['gross'])
    if complete:
        pay_groups=defaultdict(list)
        for d in stubs:
            pay_groups[(d['facts']['employer'],d['period_end'][:4])].append(d)
        for group in pay_groups.values():
            annual=D(group[0]['facts']['annual_salary']); regular=cents(annual/12)
            for i,d in enumerate(group):
                expected=regular if i<len(group)-1 else annual*len(group)/12-regular*(len(group)-1)
                eq(d['facts']['gross'],expected,f'{d["id"]}: monthly salary accrual')
        need(dict(totals)=={y:D(n) for y,n in [('2021',220000),('2022',220000),('2023',250000),('2024',267500),('2025',285000)]},f'Annual salary totals: {dict(totals)}')
        eq(sum(totals.values()),1242500,'Five-year gross')
    rollovers=[e for e in events if e['transfer_ref'].startswith('ROLLOVER-')]
    if complete:
        need(len(rollovers)==4,'Expected two paired direct rollovers')
        need({e['account_ref'] for e in rollovers}=={'RET-A','RET-B','RET-C'},'Three rollover plans')
        need(all(e['counterpart_ref'].startswith('RET-') for e in rollovers),'Rollover leaked into checking')


def verify_loans(docs, events, complete):
    statements=sorted([d for d in docs if d['family']=='mortgage'],key=lambda d:d['period_end'])
    if not statements:
        need(not complete,'No mortgage statements')
        return
    balance=D('630000'); escrow=ZERO; installment=payment(balance,D('.0525'),360)
    annual_tax=defaultdict(lambda:ZERO); annual_escrow=defaultdict(lambda:ZERO)
    for i,doc in enumerate(statements):
        f=doc['facts']; old=i<24; apr=D('5.25') if old else D('4.25')
        ref='LOAN-A' if old else 'LOAN-B'; ident=doc['id']
        need(doc['account_ref']==ref,f'{ident}: loan identity')
        eq(f['opening'],balance,f'{ident}: independently amortized opening')
        eq(f['nominal_note_rate'],apr,f'{ident}: nominal mortgage note rate')
        interest=cents(balance*apr/1200); principal=installment-interest
        eq(f['interest'],interest,f'{ident}: interest')
        eq(f['principal'],principal,f'{ident}: principal')
        eq(f['principal_and_interest'],installment,f'{ident}: installment')
        eq(f['remaining_term'],359-i,f'{ident}: remaining months')
        eq(f['payment_number'],i+1 if old else i-23,f'{ident}: payment number')
        balance-=principal
        december=doc['period_end'][5:7]=='12'
        deposit=D('916.63') if december else D('916.67')
        tax=D('11000') if december else ZERO
        eq(f['escrow_opening'],escrow,f'{ident}: escrow opening')
        eq(f['escrow_deposit'],deposit,f'{ident}: escrow deposit')
        eq(f['property_tax_disbursement'],tax,f'{ident}: escrow tax disbursement')
        escrow+=deposit-tax
        eq(f['escrow_closing'],escrow,f'{ident}: escrow closing')
        eq(f['payment'],installment+deposit,f'{ident}: full payment')
        matches=[e for e in events if e['kind']=='mortgage_payment' and e['date'][:7]==doc['period_end'][:7]]
        need(len(matches)==1,f'{ident}: unique checking installment')
        eq(matches[0]['amount'],-installment-deposit,f'{ident}: checking mortgage amount')
        need(matches[0]['account_ref']=='CHECK-A' and matches[0]['counterpart_ref']==ref,f'{ident}: mortgage counterpart')
        reduction=[e for e in events if e['kind']=='principal_payment' and e['transfer_ref']==matches[0]['transfer_ref']]
        need(len(reduction)==1,f'{ident}: unique principal event')
        eq(reduction[0]['amount'],-principal,f'{ident}: principal event')
        annual_tax[doc['period_end'][:4]]+=tax
        annual_escrow[doc['period_end'][:4]]+=deposit
        if i==23:
            eq(f['refinance_payoff'],balance,f'{ident}: refinance payoff')
            eq(f['closing'],0,f'{ident}: retired loan zero')
            closings=[d for d in docs if d['family']=='refinance']
            need(len(closings)==1,'Unique refinance statement')
            closing=closings[0]; cf=closing['facts']
            need(closing['period_end']==doc['period_end'],'Refinance date')
            for k in ('closing','new_principal','prior_loan_payoff'):
                eq(cf[k],balance,f'Refinance {k}')
            eq(cf['cash_out'],0,'Refinance cash out')
            eq(cf['term_months'],336,'Refinance term')
            eq(cf['nominal_note_rate'],'4.25','Refinance nominal note rate')
            funding=[e for e in events if e['kind']=='refinance_funding']
            payoff=[e for e in events if e['kind']=='refinance_payoff']
            need(len(funding)==len(payoff)==1,'Unique refinance funding/payoff')
            eq(funding[0]['amount'],balance,'Refinance funded principal')
            eq(payoff[0]['amount'],-balance,'Refinance paid principal')
            fees=[e for e in events if e['kind']=='closing_fee']
            need(len(fees)==1 and fees[0]['account_ref']=='CHECK-A','Separate checking fee')
            eq(fees[0]['amount'],-D(cf['fees_paid_from_checking']),'Closing fee')
            installment=payment(balance,D('.0425'),336)
        else:
            eq(f['closing'],balance,f'{ident}: independently amortized closing')
    if complete:
        for y in map(str,range(2021,2026)):
            eq(annual_tax[y],11000,f'{y}: annual tax disbursement')
            eq(annual_escrow[y],11000,f'{y}: annual escrow funding')
        taxes=[d for d in docs if d['family']=='property-tax']
        need({d['facts']['tax_year'] for d in taxes}==set(annual_tax),'Tax years')
        for d in taxes:
            eq(d['facts']['tax_paid'],annual_tax[d['facts']['tax_year']],f'{d["id"]}: tax receipt')


def verify_cds(docs, events, complete):
    openings=[d for d in docs if d['family']=='cd-opening']
    if complete:
        need(len(openings)==4,'Four CD openings')
    for certificate in openings:
        ref=certificate['account_ref']; f=certificate['facts']
        principal,apr,term=D(f['principal']),D(f['nominal_annual_rate']),int(f['term_months'])
        need(principal>0 and apr>0 and term>0,f'{ref}: CD terms')
        monthly=sorted([d for d in docs if d['family']=='cd' and d['account_ref']==ref],key=lambda d:d['period_end'])
        need(len(monthly)==term,f'{ref}: CD active months')
        opened=certificate['period_end']
        ordinal=lambda date:int(date[:4])*12+int(date[5:7])
        need(ordinal(f['maturity_date'])-ordinal(opened)==term,f'{ref}: CD maturity term months')
        need(f['maturity_date'][8:10]=='01',f'{ref}: maturity day')
        interest=cents(principal*apr/1200); balance=ZERO
        for i,d in enumerate(monthly):
            facts=d['facts']
            need(ordinal(d['period_end'])==ordinal(opened)+i,f'{ref}: contiguous CD calendar')
            eq(facts['opening'],balance,f'{ref}: CD opening')
            balance+=interest+(principal if i==0 else ZERO)
            eq(facts['closing'],balance,f'{ref}: simple interest balance')
            eq(facts['interest_earned'],interest,f'{ref}: monthly interest')
            for k in ('principal','nominal_annual_rate','term_months'):
                eq(facts[k],f[k],f'{ref}: fixed {k}')
            need(facts['maturity_date']==f['maturity_date'],f'{ref}: maturity term')
        receipts=[d for d in docs if d['family']=='cd-maturity' and d['account_ref']==ref]
        need(len(receipts)==1,f'{ref}: unique maturity receipt')
        receipt=receipts[0]; rf=receipt['facts']
        need(receipt['period_end']==f['maturity_date'],f'{ref}: maturity date')
        eq(rf['opening'],balance,f'{ref}: maturity opening')
        eq(rf['closing'],0,f'{ref}: redeemed balance')
        eq(rf['proceeds'],balance,f'{ref}: maturity proceeds')
        eq(rf['total_interest'],interest*term,f'{ref}: lifetime CD interest')
        funding=[e for e in events if e['account_ref']==ref and e['kind']=='funding']
        redemption=[e for e in events if e['account_ref']==ref and e['kind']=='redemption']
        need(len(funding)==len(redemption)==1,f'{ref}: unique funding/redemption')
        eq(funding[0]['amount'],principal,f'{ref}: funded principal')
        eq(redemption[0]['amount'],-balance,f'{ref}: redemption amount')


def verify_classifications(positions, context):
    for p in positions:
        need(p['security'] in CLASSIFICATIONS,f'{context}: unknown instrument {p["security"]}')
        actual=(p.get('exposure_class'),p.get('vehicle'))
        need(actual==CLASSIFICATIONS[p['security']],f'{context}: incorrect source classification {p["security"]}: {actual}')


def verify_investments(docs, events, accounts):
    for account in accounts:
        if account['kind']!='investment':
            continue
        ref=account['ref']; seed=account.get('initial_positions',[])
        verify_classifications(seed,f'{ref} initial positions')
        history=sorted([d for d in docs if d['account_ref']==ref and d['family'] in {'retirement','brokerage'}],key=lambda d:d['period_end'])
        preceding=D(account.get('initial_cash',account.get('initial_balance','0')))
        previous_positions=seed
        for doc in history:
            f=doc['facts']; end=doc['period_end']
            verify_classifications(f.get('opening_positions',[]),f'{doc["id"]} opening positions')
            verify_classifications(f['positions'],f'{doc["id"]} closing positions')
            if 'opening_positions' in f:
                need(sorted(f['opening_positions'],key=lambda p:p['security'])==sorted(previous_positions,key=lambda p:p['security']),f'{doc["id"]}: opening positions continuity')
            previous_positions=f['positions']
            eq(f['opening_cash'],preceding,f'{doc["id"]}: investment cash continuity')
            preceding=D(f['cash'])
            replay=[e for e in events if e['account_ref']==ref and e['date']<=end]
            positions=verify_fifo(replay,seed)
            actual={p['security']:p for p in f['positions']}
            need(set(actual)=={s for s,(q,b) in positions.items() if q!=0},f'{doc["id"]}: security coverage')
            for security,p in actual.items():
                quantity,basis=positions[security]
                eq(p['units'],quantity,f'{doc["id"]} {security}: unit continuity')
                eq(p['cost_basis'],basis,f'{doc["id"]} {security}: FIFO remaining basis')
            activity=[e for e in events if e['id'] in doc['events']]
            need(f['activity']==activity,f'{doc["id"]}: duplicated activity differs')
            if doc['family']=='retirement':
                eq(f['contribution_bond_percent'],70,f'{doc["id"]}: bond contribution target')
                eq(f['contribution_equity_mutual_fund_percent'],30,f'{doc["id"]}: equity contribution target')
                verify_closed_disclosures(f,'retirement',doc['id'])
                buys=[e for e in activity if e['kind']=='buy' and e['description']=='Employee contribution investment']
                need({e['security'] for e in buys}=={'FXNAX','FSKAX'},f'{doc["id"]}: contribution instruments')
                for e in buys:
                    eq(e['amount'],-700 if e['security']=='FXNAX' else -300,f'{doc["id"]}: contribution split')

CONTINUOUS_ESCROW = 'one_continuous_synthetic_subaccount'
CD_REQUIRED = ('opened','maturity_date','nominal_annual_rate','rate_basis','day_count',
               'interest_crediting','compounding','restriction','restriction_text',
               'convention_definition','funding_ref','receiving_account_ref','principal','term_months')
NOTE_REQUIRED = ('nominal_note_rate','rate_basis','rate_type','origination_date',
                 'origination_date_basis','original_term_months','original_principal','disclosure_apr_status')
ESCROW_REQUIRED = ('escrow_account_ref','escrow_restriction','escrow_continuity')
COMPONENT_REQUIRED = ('date','kind','amount','reference','escrow_account_ref',
                      'source_account_ref','destination_account_ref','property_ref','tax_year','source_event_id')
REFI_REQUIRED = ('old_loan_ref','new_loan_ref','funded_principal','borrower_contribution',
                 'financed_fees','funding_reference','fee_payment_reference',
                 'borrower_contribution_reference','borrower_source_account_ref',
                 'borrower_contribution_event_id','fee_items','sources_total','uses_total','cash_out',
                 'first_payment_date','prior_loan_ref','new_principal','prior_loan_payoff','fees_paid_from_checking','term_months')
TAX_REQUIRED = ('paid_status','payment_date','payment_date_basis','payment_reference',
                'source_escrow_account_ref','property_ref','tax_year','tax_paid')


def require_keys(value, keys, context):
    need(isinstance(value,dict),f'{context}: expected structured fields')
    for key in keys:
        need(key in value,f'{context}: missing critical source field {key}')
        need(value[key] is not None and (not isinstance(value[key],str) or bool(value[key].strip()) or key=='source_event_id'),f'{context}: empty critical source field {key}')


ORIGINAL_APR_STATUS = 'owner_specified_fictional_input'
ORIGINAL_APR_BASIS = 'Owner-specified fictional scenario input; not a computed legal lender disclosure or real offer.'


def verify_loan_apr_source(facts,family,account_ref,context):
    if family not in {'mortgage','refinance'}:
        return
    need(account_ref in {'LOAN-A','LOAN-B'},f'{context}: unknown loan rate source')
    require_keys(facts,('nominal_note_rate','disclosure_apr_status'),context)
    need(not any(k in facts for k in ('apr','annual_percentage_rate')),f'{context}: source APR mislabeled as an ambiguous rate')
    # Amortization uses the separately declared note rate. The owner supplied an
    # original-loan APR, while the replacement's APR remains unknown.
    eq(facts['nominal_note_rate'],'5.25' if account_ref=='LOAN-A' else '4.25',f'{context}: independent nominal note rate')
    if family=='mortgage' and account_ref=='LOAN-A':
        require_keys(facts,('disclosure_apr','disclosure_apr_basis'),context)
        eq(facts['disclosure_apr'],'5.25',f'{context}: owner-specified original APR')
        need(facts['disclosure_apr_status']==ORIGINAL_APR_STATUS,f'{context}: original APR synthetic-input status')
        need(facts['disclosure_apr_basis']==ORIGINAL_APR_BASIS,f'{context}: original APR closed fictional-input basis')
    else:
        need(facts['disclosure_apr_status']=='unavailable',f'{context}: replacement APR remains unavailable')
        need('disclosure_apr' not in facts and 'disclosure_apr_basis' not in facts,f'{context}: numeric replacement APR or fictional-input basis must not be inferred')


def compare_apr_successor(previous,successor):
    """Permit exactly the approved original-APR fields and status correction."""
    from copy import deepcopy
    normalized=deepcopy(successor);changed=[]
    for d in normalized['documents']:
        if d['family']=='mortgage' and d['account_ref']=='LOAN-A':
            verify_loan_apr_source(d['facts'],d['family'],d['account_ref'],d['id'])
            del d['facts']['disclosure_apr']
            del d['facts']['disclosure_apr_basis']
            d['facts']['disclosure_apr_status']='unavailable'
            changed.append(d['id'])
    need(len(changed)==24,'Exactly 24 original APR source corrections')
    need(normalized==previous,'APR successor changed source history beyond the two authorized fields and restored status')
    return {'complete_source_equal_after_authorized_normalization':True,
            'original_apr_documents_corrected':len(changed),
            'events_preserved':len(previous['events']),
            'primary_identities_preserved':len(previous['accounts']),
            'document_identities_preserved':len(previous['documents'])}


def verify_manifest_artifacts(root,ledger,source_hash):
    import hashlib
    import fitz
    root=Path(root);manifest_path=root/'manifest.json'
    need(manifest_path.is_file(),f'Missing source manifest {manifest_path}')
    raw=manifest_path.read_bytes();manifest=json.loads(raw)
    need(manifest.get('rendered') is True,'Manifest must describe rendered PDFs')
    need(manifest['source_ledger_sha256']==source_hash,'Manifest/source hash binding')
    rows=manifest['documents'];documents={d['id']:d for d in ledger['documents']}
    need(len(rows)==len(documents)==manifest['document_count']==manifest['expected_document_count']==794,'Manifest document counts')
    need(Counter(r['id'] for r in rows)==Counter(documents.keys()),'Manifest document identities')
    need(Counter(manifest['family_counts'])==Counter(d['family'] for d in documents.values()),'Manifest family counts')
    need({p.name for p in root.glob('*.pdf')}=={d['file'] for d in documents.values()},'Manifest/PDF file set')
    pages=0;hashes={}
    for row in rows:
        doc=documents[row['id']]
        for key in ('id','file','account_ref','family','period_start','period_end'):
            need(row[key]==doc[key],f'{doc["id"]}: manifest source identity {key}')
        path=root/doc['file'];digest=hashlib.sha256(path.read_bytes()).hexdigest()
        need(digest==row['sha256'],f'{doc["id"]}: manifest PDF hash mismatch')
        with fitz.open(path) as pdf:
            need(len(pdf)==row['page_count'] and len(pdf)>0,f'{doc["id"]}: manifest page count')
            pages+=len(pdf)
        hashes[doc['id']]=digest
    return {'manifest_sha256':hashlib.sha256(raw).hexdigest(),'documents':len(rows),'pages':pages,'pdf_hashes':hashes}


def verify_apr_artifact_delta(previous_path,successor_root,successor,source_hash):
    import hashlib
    previous_path=Path(previous_path);raw=previous_path.read_bytes();previous=json.loads(raw)
    comparison=compare_apr_successor(previous,successor)
    old=verify_manifest_artifacts(previous_path.parent,previous,hashlib.sha256(raw).hexdigest())
    new=verify_manifest_artifacts(successor_root,successor,source_hash)
    expected={d['id'] for d in successor['documents'] if d['family']=='mortgage' and d['account_ref']=='LOAN-A'}
    changed={ident for ident,digest in new['pdf_hashes'].items() if digest!=old['pdf_hashes'][ident]}
    need(changed==expected,'APR successor changed PDFs outside the 24 original mortgage witnesses')
    comparison.update(pdf_files_changed=len(changed),pdf_files_byte_identical=len(new['pdf_hashes'])-len(changed),
                      previous_pages=old['pages'],successor_pages=new['pages'],
                      previous_manifest_sha256=old['manifest_sha256'],successor_manifest_sha256=new['manifest_sha256'])
    return comparison


def verify_source_completeness(ledger, complete=True):
    """Check terms and witness identities without inventing extra cash events."""
    from datetime import date
    docs,events,accounts=ledger['documents'],ledger['events'],ledger['accounts']
    em={e['id']:e for e in events}
    if complete:
        need(len(accounts)==22,'Expected 22 primary source identities (escrow is a source subaccount)')
        need(len(events)==3531,'Expected unchanged 3531 financial source events')
    subaccounts=ledger.get('source_subaccounts')
    need(isinstance(subaccounts,list) and len(subaccounts)==1,'Exactly one continuous source escrow subaccount is required')
    sub=subaccounts[0]
    require_keys(sub,('ref','kind','restriction','property_ref','loan_refs','continuity','initial_balance'),'Escrow source subaccount')
    need(sub['ref']=='ESCROW-A' and sub['kind']=='restricted_escrow','Escrow source identity/kind')
    need(sub['restriction']=='restricted_for_property_tax','Escrow restriction')
    need(sub['property_ref']=='PROPERTY-A' and sorted(sub['loan_refs'])==['LOAN-A','LOAN-B'],'Escrow property and linked loans')
    need(sub['continuity']==CONTINUOUS_ESCROW,'Escrow servicer continuity')
    eq(sub['initial_balance'],0,'Escrow source opening')
    need(sub['ref'] not in {a['ref'] for a in accounts},'Escrow source subaccount counted as primary identity')
    need(all(e['account_ref']!=sub['ref'] for e in events),'Corroborating escrow components became extra financial events')
    certificates={d['account_ref']:d for d in docs if d['family']=='cd-opening'}
    for d in docs:
        verify_closed_disclosures(d['facts'],d['family'],d['id'])
        if d['family'] not in {'cd-opening','cd','cd-maturity'}:
            continue
        f=d['facts']; context=d['id']
        require_keys(f,CD_REQUIRED,context)
        need('apr' not in f,f'{context}: nominal CD rate mislabeled APR')
        need(f['rate_basis']=='simple_nominal' and f['day_count']=='equal_monthly_12',f'{context}: CD rate/convention')
        need(f['interest_crediting']=='monthly' and f['compounding']=='none',f'{context}: CD crediting/compounding')
        need(f['restriction']=='restricted_until_redemption',f'{context}: CD restriction')
        cert=certificates.get(d['account_ref'])
        need(cert is not None,f'{context}: missing CD opening source')
        need(f['opened']==cert['period_start']==cert['period_end'],f'{context}: CD opening date')
        date.fromisoformat(f['opened']);date.fromisoformat(f['maturity_date'])
        for key in CD_REQUIRED:
            need(f[key]==cert['facts'].get(key),f'{context}: CD fixed source term {key} differs')
        funding=[e for e in events if e['kind']=='funding' and e['account_ref']==d['account_ref']]
        need(len(funding)==1,f'{context}: unique CD funding')
        need(f['funding_ref']==funding[0]['transfer_ref'],f'{context}: CD funding reference')
        need(f['receiving_account_ref']=='SAVE-A',f'{context}: CD receiving account')
        need(funding[0]['date']==f['opened'] and funding[0]['counterpart_ref']=='SAVE-A',f'{context}: CD funding identity/date')
        if d['family']=='cd-opening':
            need('opening' not in f and 'closing' not in f,f'{context}: certificate falsely fabricated balance snapshot')
        if d['family']=='cd-maturity':
            require_keys(f,('redemption_ref',),context)
            redemption=[e for e in events if e['kind']=='redemption' and e['account_ref']==d['account_ref']]
            need(len(redemption)==1 and f['redemption_ref']==redemption[0]['transfer_ref'],f'{context}: CD redemption reference')
            need(redemption[0]['counterpart_ref']==f['receiving_account_ref'],f'{context}: CD receiving witness')
    refinance=[d for d in docs if d['family']=='refinance']
    need(len(refinance)==1,'Exactly one source refinance')
    settlement=refinance[0]; sf=settlement['facts']
    require_keys(sf,REFI_REQUIRED,settlement['id'])
    need(sf['old_loan_ref']==sf['prior_loan_ref']=='LOAN-A' and sf['new_loan_ref']==settlement['account_ref']=='LOAN-B','Refinance source loan identities')
    first_new=min((d for d in docs if d['family']=='mortgage' and d['account_ref']=='LOAN-B'),key=lambda d:d['period_end'])
    need(sf['first_payment_date']==first_new['facts'].get('payment_date'),'Refinance first payment date witness')
    eq(sf['term_months'],336,'Refinance original replacement term')
    eq(sf['funded_principal'],sf['new_principal'],'Refinance funded/new principal')
    eq(sf['funded_principal'],sf['prior_loan_payoff'],'Refinance no cash-out payoff')
    eq(sf['borrower_contribution'],3000,'Refinance borrower contribution')
    eq(sf['financed_fees'],0,'Refinance financed fees')
    eq(sf['cash_out'],0,'Refinance cash out')
    fee_event=em.get(sf['borrower_contribution_event_id'])
    need(fee_event is not None and fee_event['kind']=='closing_fee','Refinance borrower contribution source event')
    need(fee_event['account_ref']==sf['borrower_source_account_ref']=='CHECK-A','Refinance borrower source account')
    need(sf['fee_payment_reference']==sf['borrower_contribution_reference']==fee_event['transfer_ref'],'Refinance fee/contribution references')
    eq(-D(fee_event['amount']),sf['borrower_contribution'],'Refinance checking fee payment')
    eq(sf['fees_paid_from_checking'],sf['borrower_contribution'],'Refinance separate fee source')
    need(fee_event['date']==settlement['period_end'],'Refinance contribution date')
    need(isinstance(sf['fee_items'],list) and bool(sf['fee_items']),'Refinance itemized fees missing')
    for item in sf['fee_items']:
        require_keys(item,('name','amount','reference'),'Refinance itemized fee')
        need(D(item['amount'])>0 and item['reference']==sf['fee_payment_reference'],'Refinance fee item amount/reference')
    fee_total=sum((D(i['amount']) for i in sf['fee_items']),ZERO)
    eq(fee_total,3000,'Refinance itemized fee total')
    sources=D(sf['funded_principal'])+D(sf['borrower_contribution'])
    uses=D(sf['prior_loan_payoff'])+fee_total+D(sf['cash_out'])
    eq(sf['sources_total'],sources,'Refinance sources total')
    eq(sf['uses_total'],uses,'Refinance uses total')
    eq(sources,uses,'Refinance sources equal uses')
    funding=[e for e in events if e['kind']=='refinance_funding']
    need(len(funding)==1 and sf['funding_reference']==funding[0]['transfer_ref'],'Refinance funding reference')
    need(funding[0]['account_ref']=='LOAN-B' and funding[0]['counterpart_ref']=='LOAN-A','Refinance direct funding identities')
    eq(sf['funded_principal'],funding[0]['amount'],'Refinance direct source funded amount')
    tax_rows={}
    for d in docs:
        if d['family'] not in {'mortgage','refinance'}:
            continue
        f=d['facts']; context=d['id']; ref=d['account_ref']
        require_keys(f,NOTE_REQUIRED+ESCROW_REQUIRED,context)
        verify_loan_apr_source(f,d['family'],ref,context)
        need(f['rate_basis']=='nominal_annual' and f['rate_type']=='fixed',f'{context}: fixed nominal note rate source')
        need(f['origination_date_basis']=='declared_synthetic',f'{context}: synthetic origination assumption')
        eq(f['nominal_note_rate'],'5.25' if ref=='LOAN-A' else '4.25',f'{context}: declared nominal note rate')
        expected_origination='2021-01-01' if ref=='LOAN-A' else settlement['period_end']
        need(f['origination_date']==expected_origination,f'{context}: loan origination date')
        eq(f['original_term_months'],360 if ref=='LOAN-A' else 336,f'{context}: original loan term')
        eq(f['original_principal'],630000 if ref=='LOAN-A' else sf['funded_principal'],f'{context}: original funded loan principal')
        need(f['escrow_account_ref']==sub['ref'] and f['escrow_restriction']==sub['restriction'] and f['escrow_continuity']==sub['continuity'],f'{context}: continuous restricted escrow identity')
        if d['family']=='refinance':
            continue
        require_keys(f,('payment_date','payment_reference','principal_event_id','checking_payment_event_id','escrow_components'),context)
        checking=em.get(f['checking_payment_event_id']);principal=em.get(f['principal_event_id'])
        need(checking is not None and principal is not None,f'{context}: payment source event IDs')
        need(checking['kind']=='mortgage_payment' and principal['kind']=='principal_payment',f'{context}: payment source event kinds')
        need(f['payment_reference']==checking['transfer_ref']==principal['transfer_ref'],f'{context}: payment reference witnesses')
        need(f['payment_date']==checking['date']==principal['date'],f'{context}: payment date witnesses')
        need(f['origination_date']<f['payment_date'],f'{context}: origination precedes installment')
        eq(-D(checking['amount']),f['payment'],f'{context}: payment source amount')
        eq(-D(principal['amount']),f['principal'],f'{context}: principal source amount')
        rows=f['escrow_components'];expected_rows=2 if D(f['property_tax_disbursement']) else 1
        need(isinstance(rows,list) and len(rows)==expected_rows,f'{context}: escrow corroborating component count')
        need(sum(1 for r in rows if r.get('kind')=='deposit')==1,f'{context}: unique escrow deposit component')
        for row in rows:
            require_keys(row,COMPONENT_REQUIRED,f'{context} escrow component')
            need(row['escrow_account_ref']==sub['ref'] and row['property_ref']==sub['property_ref'],f'{context}: escrow component/property identity')
            need(row['tax_year']==d['period_end'][:4],f'{context}: escrow component tax year')
            need(d['period_start']<=row['date']<=d['period_end'],f'{context}: escrow component date')
            date.fromisoformat(row['date'])
            if row['kind']=='deposit':
                need(row['reference']==f['payment_reference'] and row['date']==f['payment_date'],f'{context}: escrow deposit payment reference/date')
                need(row['source_event_id']==checking['id'],f'{context}: escrow deposit checking witness')
                need(row['source_account_ref']=='CHECK-A' and row['destination_account_ref']==sub['ref'],f'{context}: escrow deposit account identities')
                eq(row['amount'],f['escrow_deposit'],f'{context}: escrow deposit amount')
            else:
                need(row['kind']=='property_tax_disbursement',f'{context}: unexpected escrow component kind')
                require_keys(f,('escrow_disbursement_date_basis',),context)
                need(f['escrow_disbursement_date_basis']=='declared_synthetic',f'{context}: escrow disbursement date assumption')
                need(row['reference']==f'PROPERTY-TAX-PROPERTY-A-{row["tax_year"]}',f'{context}: property/year-specific tax reference')
                need(row['date']==d['period_end'] and row['date'].endswith('-12-31'),f'{context}: declared synthetic tax payment date')
                need(row['source_account_ref']==sub['ref'] and row['destination_account_ref']=='PROPERTY-A',f'{context}: escrow tax source/destination')
                need(row['source_event_id']=='',f'{context}: escrow tax component must not invent household cash event')
                eq(row['amount'],-D(f['property_tax_disbursement']),f'{context}: escrow tax amount')
                need(row['tax_year'] not in tax_rows,f'{context}: duplicate tax disbursement')
                tax_rows[row['tax_year']]=row
        eq(D(f['escrow_opening'])+sum((D(r['amount']) for r in rows),ZERO),f['escrow_closing'],f'{context}: escrow component balance bridge')
    for d in docs:
        f=d['facts']; context=d['id']
        if d['family']=='property-tax':
            require_keys(f,TAX_REQUIRED,context)
            row=tax_rows.get(f['tax_year'])
            need(row is not None,f'{context}: missing corresponding escrow disbursement')
            need(f['paid_status']=='paid' and f['payment_date_basis']=='declared_synthetic',f'{context}: paid tax/date source status')
            need(f['payment_date']==row['date'] and f['payment_reference']==row['reference'],f'{context}: tax payment date/reference witness')
            need(f['source_escrow_account_ref']==row['escrow_account_ref'] and f['property_ref']==row['property_ref'],f'{context}: tax source escrow/property witness')
            eq(f['tax_paid'],-D(row['amount']),f'{context}: tax receipt amount')
        if d['family']=='payroll':
            require_keys(f,('retirement_contribution_ref','retirement_account_ref'),context)
            retirement=[r for r in f['deductions'] if r['category']=='retirement']
            need(len(retirement)==1,f'{context}: unique retirement deduction')
            row=retirement[0]
            require_keys(row,('contribution_ref','retirement_account_ref'),f'{context} retirement deduction')
            contribution=[e for e in events if e['kind']=='contribution' and e['account_ref']==f['retirement_account_ref'] and e['date']==f['pay_date'] and e['transfer_ref'].startswith('RET-CONTRIB-')]
            need(len(contribution)==1,f'{context}: unique retirement contribution witness')
            need(row['contribution_ref']==f['retirement_contribution_ref']==contribution[0]['transfer_ref'],f'{context}: payroll contribution reference')
            need(row['retirement_account_ref']==f['retirement_account_ref']==contribution[0]['account_ref'],f'{context}: deduction/contribution plan identity')
    if complete:
        need(set(tax_rows)==set(map(str,range(2021,2026))),'Five source escrow tax disbursements')
    return {'primary_source_identities':len(accounts),'source_subaccounts':len(subaccounts)}


def verify_ledger(ledger, root=None, *, complete=True):
    need(ledger.get('schema_version')=='synthetic-life-v1','Unknown schema')
    accounts,events,docs=(ledger.get(k,[]) for k in ('accounts','events','documents'))
    need(accounts and events and docs,'Empty accounts, events, or documents')
    am={a['ref']:a for a in accounts}; em={e['id']:e for e in events}
    need(len(am)==len(accounts),'Duplicate account')
    need(len(em)==len(events),'Duplicate event')
    need(len({d['id'] for d in docs})==len(docs),'Duplicate document')
    need(len({d['file'] for d in docs})==len(docs),'Duplicate file')
    if complete:
        need(len(docs)==794,f'Expected 794 documents, got {len(docs)}')
        need(Counter(d['family'] for d in docs)==Counter(COUNTS),f'Wrong family counts: {dict(Counter(d["family"] for d in docs))}')
        months={f'{y}-{m:02d}' for y in range(2021,2026) for m in range(1,13)}
        for family,n in [('checking',1),('savings',1),('credit-card',5),('brokerage',2),('retirement',1),('payroll',1),('mortgage',1)]:
            need(Counter(d['period_end'][:7] for d in docs if d['family']==family)==Counter({m:n for m in months}),f'{family}: incomplete calendar')
    for e in events:
        need(e['account_ref'] in am,f'{e["id"]}: unknown account')
        need(e['currency']=='USD',f'{e["id"]}: wrong currency')
        D(e['amount'])
    completeness=verify_source_completeness(ledger,complete)
    transfers=verify_transfers(events)
    if complete:
        referenced={ref for d in docs for ref in d['events']}
        need(referenced==set(em),'Source events lack document witnesses')
    histories=defaultdict(list)
    for doc in docs:
        ident=doc['id']; f=doc['facts']
        need(doc['account_ref'] in am,f'{ident}: unknown account')
        need(doc['currency']=='USD' and doc['locale']=='en-US',f'{ident}: currency/locale')
        need(doc['period_start']<=doc['period_end']==doc['as_of'],f'{ident}: dates')
        need(len(set(doc['events']))==len(doc['events']),f'{ident}: duplicate event reference')
        need(all(ref in em for ref in doc['events']),f'{ident}: absent event')
        ev=[em[ref] for ref in doc['events']]
        need(all(e['account_ref']==doc['account_ref'] for e in ev),f'{ident}: event account')
        need(all(doc['period_start']<=e['date']<=doc['period_end'] for e in ev),f'{ident}: event dates')
        if 'opening' in f and 'closing' in f:
            eq(f['closing'],D(f['opening'])+sum((D(e['amount']) for e in ev),ZERO),f'{ident}: balance bridge')
            histories[doc['account_ref']].append(doc)
        if doc['family']=='payroll':
            eq(f['net'],D(f['gross'])-sum((D(x['amount']) for x in f['deductions']),ZERO),f'{ident}: payroll net')
        if doc['family'] in {'brokerage','retirement'}:
            eq(f['cash'],D(f['opening_cash'])+sum((D(e['amount']) for e in ev),ZERO),f'{ident}: cash bridge')
            for p in f['positions']:
                eq(p['market_value'],cents(D(p['units'])*D(p['unit_price'])),f'{ident}: position value')
            eq(f['total'],D(f['cash'])+sum((D(p['market_value']) for p in f['positions']),ZERO),f'{ident}: total')
        if root is not None:
            verify_pdf(Path(root)/doc['file'],doc,ev)
    verify_salary(docs,events,complete)
    verify_loans(docs,events,complete)
    verify_cds(docs,events,complete)
    verify_investments(docs,events,accounts)
    for ref,history in histories.items():
        monthly=sorted([d for d in history if d['family'] not in {'cd-opening','cd-maturity','refinance','property-tax'}],key=lambda d:(d['period_end'],d['id']))
        if monthly:
            prior=sorted([d for d in history if d['period_end']<monthly[0]['period_start']],key=lambda d:d['period_end'])
            seed=prior[-1]['facts']['closing'] if prior else am[ref].get('initial_balance','0')
            eq(monthly[0]['facts']['opening'],seed,f'{ref}: declared opening seed')
        for before,after in zip(monthly,monthly[1:]):
            eq(after['facts']['opening'],before['facts']['closing'],f'{ref}: continuity')
    return {'documents':len(docs),'events':len(events),'accounts':len(accounts),'transfer_pairs':len(transfers),**completeness}

def mutation_checks(ledger):
    """Demonstrate fail-closed behavior on fresh copies of actual source evidence."""
    from copy import deepcopy
    verify_ledger(ledger)
    outcomes={}
    for mutation in ('cent','unit','counterpart','payoff','class','empty','missing'):
        source=deepcopy(ledger)
        if mutation=='cent':
            d=next(d for d in source['documents'] if d['family']=='checking')
            d['facts']['closing']=str(D(d['facts']['closing'])+D('.01'))
        elif mutation=='unit':
            d=next(d for d in source['documents'] if d['family']=='brokerage' and d['facts']['positions'])
            d['facts']['positions'][0]['units']=str(D(d['facts']['positions'][0]['units'])+1)
        elif mutation=='counterpart':
            e=next(e for e in source['events'] if e['transfer_ref'].startswith('CD-FUND-'))
            e['counterpart_ref']='WRONG-ACCOUNT'
        elif mutation=='payoff':
            d=next(d for d in source['documents'] if 'refinance_payoff' in d['facts'])
            d['facts']['refinance_payoff']=str(D(d['facts']['refinance_payoff'])+D('.01'))
        elif mutation=='class':
            d=next(d for d in source['documents'] if d['family']=='retirement' and d['facts']['positions'])
            d['facts']['positions'][0]['exposure_class']='unclassified'
        elif mutation=='empty':
            source['documents']=[]
        elif mutation=='missing':
            source['documents'].pop()
        try:
            verify_ledger(source)
        except VerificationError as exc:
            outcomes[mutation]=str(exc)
        else:
            raise VerificationError(f'Mutation {mutation} escaped detection')
    return outcomes

def expected_document_dispositions(ledger):
    """Normative source expectations, independent of current product behavior."""
    dispositions={
        'checking':'balance_and_activity_reconciled',
        'savings':'balance_and_activity_reconciled',
        'credit-card':'liability_activity_and_settlement_reconciled',
        'brokerage':'cash_holdings_and_fifo_activity_reconciled',
        'retirement':'plan_holdings_contributions_and_rollovers_reconciled',
        'payroll':'linked_to_bank_deposit_and_plan_contribution',
        'mortgage':'principal_interest_and_escrow_reconciled',
        'cd':'principal_and_simple_interest_reconciled',
        'cd-opening':'funding_terms_reconciled_without_duplicate_activity',
        'cd-maturity':'redemption_reconciled_without_duplicate_income',
        'refinance':'replacement_and_payoff_reconciled_without_income',
        'property-tax':'annual_payment_linked_to_escrow_without_duplicate_expense',
    }
    result=[]
    for d in ledger['documents']:
        need(d['family'] in dispositions,f'No independent disposition for {d["family"]}')
        result.append(dict(document_id=d['id'],file=d['file'],family=d['family'],
                           expected_account_ref=d['account_ref'],
                           expected_read_status='supported',
                           expected_disposition=dispositions[d['family']],
                           expected_source_event_ids=d['events']))
        if d['family']=='retirement':
            values={'bond':ZERO,'equity':ZERO,'cash':D(d['facts']['cash'])}
            for p in d['facts']['positions']:
                verify_classifications([p],f'{d["id"]} allocation')
                values[p['exposure_class']]+=D(p['market_value'])
            total=D(d['facts']['total'])
            result[-1]['expected_actual_allocation']={
                'basis':'total_account_value_including_cash',
                'values':{key:str(value) for key,value in values.items()},
                'percentages':{key:str((value*100/total).quantize(Decimal('.00000001'),rounding=ROUND_HALF_UP)) if total else None for key,value in values.items()},
            }
    return result

def completeness_field_targets(ledger):
    """Cover every critical field type on each distinct source witness shape."""
    targets=[]
    selected=[]
    selectors=[('cd-opening',None),('cd',None),('cd-maturity',None),
               ('mortgage','LOAN-A'),('mortgage','LOAN-B'),('refinance',None),
               ('property-tax',None),('payroll',None)]
    for family,ref in selectors:
        selected.append(next(i for i,d in enumerate(ledger['documents']) if d['family']==family and (ref is None or d['account_ref']==ref)))
    december=next(i for i,d in enumerate(ledger['documents']) if d['family']=='mortgage' and d['period_end'].endswith('-12-31'))
    selected.append(december)
    for i in dict.fromkeys(selected):
        d=ledger['documents'][i];f=d['facts'];family=d['family'];base=('documents',i,'facts')
        keys=[]
        if family in {'cd-opening','cd','cd-maturity'}:
            keys+=list(CD_REQUIRED)
            if family=='cd-maturity':keys+=['redemption_ref']
        if family in {'mortgage','refinance'}:
            keys+=list(NOTE_REQUIRED+ESCROW_REQUIRED)
            if family=='mortgage' and d['account_ref']=='LOAN-A':
                keys+=['disclosure_apr','disclosure_apr_basis']
        if family=='mortgage':
            keys+=['payment_date','payment_reference','principal_event_id','checking_payment_event_id','escrow_components']
            if D(f['property_tax_disbursement']):keys+=['escrow_disbursement_date_basis']
            for j,row in enumerate(f['escrow_components']):
                targets += [(f'{d["id"]}.escrow_components.{j}.{k}',base+('escrow_components',j,k)) for k in COMPONENT_REQUIRED]
        if family=='refinance':
            keys+=list(REFI_REQUIRED)
            for j,row in enumerate(f['fee_items']):
                targets += [(f'{d["id"]}.fee_items.{j}.{k}',base+('fee_items',j,k)) for k in ('name','amount','reference')]
        if family=='property-tax':keys+=list(TAX_REQUIRED)
        if family=='payroll':
            keys+=['retirement_contribution_ref','retirement_account_ref']
            j=next(j for j,r in enumerate(f['deductions']) if r['category']=='retirement')
            targets += [(f'{d["id"]}.retirement_deduction.{k}',base+('deductions',j,k)) for k in ('contribution_ref','retirement_account_ref')]
        targets += [(f'{d["id"]}.{k}',base+(k,)) for k in dict.fromkeys(keys)]
    targets += [(f'source_subaccounts.{k}',('source_subaccounts',0,k)) for k in ('ref','kind','restriction','property_ref','loan_refs','continuity','initial_balance')]
    return targets


def corrupted_value(value,key):
    from datetime import date,timedelta
    if isinstance(value,list):return []
    if key=='name':return ''
    if isinstance(value,str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}',value):
        return str(date.fromisoformat(value)+timedelta(days=1))
    if isinstance(value,str) and re.fullmatch(r'-?\d+(?:\.\d+)?',value):
        return str(D(value)+D('.01'))
    return 'CORRUPTED'


def source_completeness_mutation_checks(ledger):
    from copy import deepcopy
    verify_source_completeness(ledger)
    outcomes={}
    for label,path in completeness_field_targets(ledger):
        for operation in ('missing','changed'):
            altered=deepcopy(ledger);parent=altered
            for key in path[:-1]:parent=parent[key]
            if operation=='missing':
                del parent[path[-1]]
            else:
                parent[path[-1]]=corrupted_value(parent[path[-1]],path[-1])
            try:
                verify_source_completeness(altered)
            except VerificationError as exc:
                outcomes[f'{label}:{operation}']=str(exc)
            else:
                raise VerificationError(f'Critical source mutation escaped detection: {label}:{operation}')
    return outcomes


def printed_completeness_mutation_checks(ledger,root,extracted_texts=None):
    """Mutate extracted actual PDF text; never create or modify a PDF."""
    if extracted_texts is None:
        import fitz
    by_id={d['id']:d for d in ledger['documents']}
    em={e['id']:e for e in ledger['events']};cache={};outcomes={}
    for label,path in completeness_field_targets(ledger):
        if path[0]!='documents':continue
        d=ledger['documents'][path[1]];f=d['facts'];inner=path[3:]
        if d['id'] not in cache:
            if extracted_texts is None:
                with fitz.open(Path(root)/d['file']) as pdf:
                    cache[d['id']]=compact_source_text(' '.join(p.get_text() for p in pdf))
            else:
                cache[d['id']]=compact_source_text(extracted_texts[d['id']])
            verify_printed_text(cache[d['id']],d,[em[e] for e in d['events']],d['file'])
        compact=cache[d['id']]
        if inner[0] in {'escrow_components','fee_items'}:
            if len(inner)==1:
                row=f[inner[0]][0]
                target=escrow_row_text(row) if inner[0]=='escrow_components' else fee_row_text(row)
                replacement='CORRUPTED REQUIRED COMPONENT ROW'
                missing_replacement=''
            else:
                from copy import deepcopy
                row=f[inner[0]][inner[1]];changed=deepcopy(row)
                changed[inner[2]]=corrupted_value(row[inner[2]],inner[2])
                row_text=escrow_row_text if inner[0]=='escrow_components' else fee_row_text
                target,replacement=row_text(row),row_text(changed)
                if inner[0]=='fee_items':
                    pieces={'name':f"Fee: {row['name']}",'amount':f"Amount: {row['amount']} USD",'reference':f"Reference: {row['reference']}"}
                    fragment=pieces[inner[2]]
                else:
                    labels={'reference':'Reference','escrow_account_ref':'Escrow account','source_account_ref':'Source account','destination_account_ref':'Destination account','property_ref':'Property','tax_year':'Tax year','source_event_id':'Source event'}
                    key=inner[2]
                    if key in labels:
                        value=row[key] or 'none (existing escrow effect; not a new cash event)'
                        fragment=f'{labels[key]}: {value}'
                    else:
                        fragment=row[key]
                missing_replacement=target.replace(fragment,'',1)
        elif inner[0]=='deductions':
            row=f['deductions'][inner[1]];key=inner[2]
            field='Contribution reference' if key=='contribution_ref' else 'Retirement account'
            target=f'{field}: {row[key]}';replacement=f'{field}: CORRUPTED';missing_replacement=''
        else:
            key=inner[0]
            target=f'{key.replace("_"," ").capitalize()}: {f[key]}'
            replacement=f'{key.replace("_"," ").capitalize()}: {corrupted_value(f[key],key)}'
            missing_replacement=''
        need(target in compact,f'Actual PDF control target missing: {label}: {target}')
        for operation,substitute in [('missing',missing_replacement),('changed',replacement)]:
            changed=compact.replace(target,substitute,1)
            need(changed!=compact,f'No actual PDF text mutation: {label}:{operation}')
            try:
                verify_printed_text(changed,d,[em[e] for e in d['events']],d['file'])
            except VerificationError as exc:
                outcomes[f'{label}:{operation}']=str(exc)
            else:
                raise VerificationError(f'Critical actual PDF text mutation escaped detection: {label}:{operation}')
    return outcomes


def compare_financial_history(before,after):
    """A source-semantic repair must preserve every existing financial movement."""
    need(before['events']==after['events'],'Source repair changed financial events')
    need(before['accounts']==after['accounts'],'Source repair changed primary identities/opening facts')
    old={d['id']:d for d in before['documents']};new={d['id']:d for d in after['documents']}
    need(old.keys()==new.keys(),'Source repair changed document identities')
    preserved=0
    for ident,d in old.items():
        n=new[ident]
        for key in ('file','family','doc_type','account_ref','institution','period_start','period_end','as_of','currency','locale','events'):
            need(d[key]==n[key],f'{ident}: source repair changed {key}')
        for key,value in d['facts'].items():
            if key in {'apr','original_principal'}:continue
            # All existing numeric fields and holdings/activity are immutable.
            if isinstance(value,str) and re.fullmatch(r'-?\d+(?:\.\d+)?',value):
                need(n['facts'].get(key)==value,f'{ident}: financial source value changed: {key}')
                preserved+=1
            elif key in {'positions','opening_positions','activity'}:
                need(n['facts'].get(key)==value,f'{ident}: source repair changed {key}')
            elif key=='deductions':
                need(len(value)==len(n['facts'][key]),f'{ident}: source repair changed deduction count')
                for a,b in zip(value,n['facts'][key]):
                    need(all(b.get(k)==v for k,v in a.items()),f'{ident}: source repair changed original deduction facts')
        if 'apr' in d['facts']:
            rate='nominal_annual_rate' if d['family'] in {'cd-opening','cd','cd-maturity'} else 'nominal_note_rate'
            eq(n['facts'][rate],d['facts']['apr'],f'{ident}: source rate renamed without amount change')
    return {'events_preserved':len(before['events']),'primary_identities_preserved':len(before['accounts']),
            'document_identities_preserved':len(old),'original_numeric_fields_preserved':preserved,
            'replacement_original_principal_terms_corrected':sum(1 for ident,d in old.items() if d['family']=='mortgage' and d['account_ref']=='LOAN-B' and d['facts']['original_principal']!=new[ident]['facts']['original_principal'])}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('ledger',type=Path)
    parser.add_argument('--pdf-root',type=Path)
    parser.add_argument('--report',type=Path)
    parser.add_argument('--mutation-checks',action='store_true')
    parser.add_argument('--previous-ledger',type=Path)
    parser.add_argument('--previous-apr-ledger',type=Path)
    args=parser.parse_args()
    try:
        import hashlib
        raw=args.ledger.read_bytes()
        ledger=json.loads(raw)
        result=verify_ledger(ledger,args.pdf_root)
        result['source_ledger_sha256']=hashlib.sha256(raw).hexdigest()
        if args.pdf_root:
            artifact=verify_manifest_artifacts(args.pdf_root,ledger,result['source_ledger_sha256'])
            result['manifest_verification']={k:v for k,v in artifact.items() if k!='pdf_hashes'}
        if args.previous_apr_ledger:
            if args.pdf_root:
                result['previous_apr_successor_comparison']=verify_apr_artifact_delta(args.previous_apr_ledger,args.pdf_root,ledger,result['source_ledger_sha256'])
            else:
                result['previous_apr_successor_comparison']=compare_apr_successor(json.loads(args.previous_apr_ledger.read_text()),ledger)
            try:
                verify_source_completeness(json.loads(args.previous_apr_ledger.read_text()))
            except VerificationError as exc:
                result['previous_apr_source_rejected']=str(exc)
            else:
                raise VerificationError('Prior APR-omitted source unexpectedly passes corrected owner-input contract')
        result['expected_document_dispositions']=expected_document_dispositions(ledger)
        if args.mutation_checks:
            result['rejected_mutations']=mutation_checks(ledger)
            result['rejected_source_completeness_mutations']=source_completeness_mutation_checks(ledger)
            if args.pdf_root:
                result['rejected_actual_pdf_text_mutations']=printed_completeness_mutation_checks(ledger,args.pdf_root)
        if args.previous_ledger:
            previous=json.loads(args.previous_ledger.read_text())
            result['previous_financial_history']=compare_financial_history(previous,ledger)
            missing=[]
            for label,path in completeness_field_targets(ledger):
                value=previous
                try:
                    for key in path:value=value[key]
                except (KeyError,IndexError):
                    missing.append(label)
            result['previous_missing_critical_source_fields']=missing
            try:
                verify_source_completeness(previous)
            except VerificationError as exc:
                result['previous_source_completeness_rejected']=str(exc)
            else:
                raise VerificationError('Old source unexpectedly passes new completeness contract')
    except (VerificationError,KeyError,OSError) as exc:
        parser.exit(1,f'FAIL: {exc}\n')
    output=json.dumps({'status':'pass',**result},indent=2)
    if args.report:
        args.report.write_text(output+'\n')
    print(output)

if __name__=='__main__':
    main()
