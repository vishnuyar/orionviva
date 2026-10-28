"""Generate a deterministic, explicitly fictional five-year financial corpus.

The source ledger is independent of product code. No paid model or credentials
are used. By default only JSON specifications are emitted; --render-pdfs is an
explicit second step after the campaign's PDF artifact marker is recorded.
"""
from __future__ import annotations

import argparse
import calendar
import hashlib
import json
from datetime import date, timedelta
from decimal import (Context, Decimal, DivisionByZero, InvalidOperation, Overflow,
                     ROUND_HALF_EVEN, ROUND_HALF_UP, localcontext)
from pathlib import Path

D = Decimal
_GENERATION_CONTEXT = Context(prec=40, rounding=ROUND_HALF_EVEN,
                              Emin=-999999, Emax=999999, capitals=1, clamp=0,
                              flags=[], traps=[InvalidOperation, DivisionByZero, Overflow])
CENT = D('0.01')
UNIT = D('0.00000001')
SCHEMA = 'synthetic-life-v1'
EXPECTED_DOCUMENTS = 794
DEFAULT_OUT = Path(__file__).resolve().parents[1] / 'output/pdf/synthetic_life_5y'
SECURITY_NAMES = {
    'AAPL': 'Apple Inc.', 'MSFT': 'Microsoft Corporation',
    'VTSAX': 'Vanguard Total Stock Market Index Fund Admiral Shares',
    'SWPPX': 'Schwab S&P 500 Index Fund',
    'FXNAX': 'Fidelity U.S. Bond Index Fund',
    'FSKAX': 'Fidelity Total Market Index Fund',
}
SECURITY_CLASSIFICATIONS = {
    'AAPL': dict(exposure_class='equity', vehicle='individual_security'),
    'MSFT': dict(exposure_class='equity', vehicle='individual_security'),
    'VTSAX': dict(exposure_class='equity', vehicle='mutual_fund'),
    'SWPPX': dict(exposure_class='equity', vehicle='mutual_fund'),
    'FXNAX': dict(exposure_class='bond', vehicle='mutual_fund'),
    'FSKAX': dict(exposure_class='equity', vehicle='mutual_fund'),
}
ESCROW_REF = 'ESCROW-A'
ESCROW_CONTINUITY = 'one_continuous_synthetic_subaccount'
CD_RESTRICTION = ('Principal and credited interest remain restricted in this term-deposit '
                  'account until the sourced maturity redemption transfers them to SAVE-A.')
CD_CONVENTION = ('Fictional twelve-equal-month year; each complete credited month earns '
                 'principal times nominal annual percentage rate divided by 1200; only '
                 'whole-month schedules supported. Not actual_365 or actual_360.')


def cd_terms(opened, term, annual_rate, ref):
    return dict(opened=str(month_date(opened)),
                maturity_date=str(month_date(opened+term)),
                nominal_annual_rate=money(annual_rate), rate_basis='simple_nominal',
                day_count='equal_monthly_12', term_months=str(term),
                interest_crediting='monthly', compounding='none',
                restriction='restricted_until_redemption', restriction_text=CD_RESTRICTION,
                convention_definition=CD_CONVENTION,
                funding_ref=f'CD-FUND-{ref}', receiving_account_ref='SAVE-A')


def money(value):
    return str(D(value).quantize(CENT, rounding=ROUND_HALF_UP))


def units(value):
    return str(D(value).quantize(UNIT, rounding=ROUND_HALF_UP))


def month_date(index, day=1):
    return date(2021 + index // 12, index % 12 + 1, day)


def month_end(index):
    first = month_date(index)
    return first.replace(day=calendar.monthrange(first.year, first.month)[1])


def following_day(index):
    return month_end(index) + timedelta(days=1)


def weekday(day, forward=False):
    """Choose a weekday for synthetic settled trade activity."""
    while day.weekday() >= 5:
        day += timedelta(days=1 if forward else -1)
    return day


def payment(principal, apr, months):
    with localcontext(_GENERATION_CONTEXT):
        rate = D(apr) / D(1200)
        return D(money(D(principal) * rate / (1 - (1 + rate) ** (-months))))


class Life:
    def __init__(self):
        self.events = []
        self.documents = []
        self.accounts = []
        self._event_index = {}

    def account(self, ref, name, institution, kind):
        self.accounts.append(dict(ref=ref, name=name, institution=institution, kind=kind,
                                  initial_balance='0.00', initial_positions=[]))

    def event(self, day, account_ref, kind, amount, description,
              counterpart_ref='', transfer_ref='', security='', quantity='',
              unit_price='', realized_gain='', cost_basis=''):
        event = dict(id=f'E{len(self.events)+1:06d}', date=str(day),
                     account_ref=account_ref, kind=kind, amount=money(amount),
                     currency='USD', description=description,
                     counterpart_ref=counterpart_ref, transfer_ref=transfer_ref,
                     security=security, units=units(quantity) if quantity != '' else '',
                     unit_price=money(unit_price) if unit_price != '' else '',
                     realized_gain=money(realized_gain) if realized_gain != '' else '',
                     cost_basis=money(cost_basis) if cost_basis != '' else '')
        self.events.append(event)
        self._event_index[event['id']] = event
        return event

    def document(self, family, doc_type, ref, institution, start, end, facts, events=()):
        identifier = f'D{len(self.documents)+1:04d}'
        doc = dict(id=identifier, file=f'{identifier}-{family}-{ref}-{end}.pdf',
                   family=family, doc_type=doc_type, account_ref=ref,
                   institution=institution, period_start=str(start), period_end=str(end),
                   as_of=str(end), currency='USD', locale='en-US', facts=facts,
                   events=[event['id'] for event in events])
        self.documents.append(doc)
        return doc

    def balance_doc(self, family, dtype, ref, institution, idx, opening, events, **extra):
        closing = D(opening) + sum((D(e['amount']) for e in events), D(0))
        self.document(family, dtype, ref, institution, month_date(idx), month_end(idx),
                      dict(opening=money(opening), closing=money(closing), **extra), events)
        return closing


def _price(symbol, index):
    base, step = {'AAPL': ('120', '0.70'), 'MSFT': ('220', '1.10'),
                  'VTSAX': ('90', '0.45'), 'SWPPX': ('55', '0.30'),
                  'FXNAX': ('10', '0.01'), 'FSKAX': ('100', '0.80')}[symbol]
    return D(base) + D(step) * D(index + 1)


def _trade(life, lots, day, ref, kind, symbol, quantity, price, description):
    quantity = D(quantity)
    price = D(price)
    amount = D(money(quantity * price))
    basis = D(0)
    if kind == 'buy':
        lots.setdefault(symbol, []).append([quantity, amount])
    else:
        left = quantity
        while left:
            if not lots.get(symbol):
                raise ValueError(f'short sale forbidden: {ref} {symbol}')
            lot = lots[symbol][0]
            take = min(left, lot[0])
            part = lot[1] if take == lot[0] else D(money(lot[1] * take / lot[0]))
            basis += part
            lot[0] -= take
            lot[1] -= part
            left -= take
            if lot[0] == 0:
                lots[symbol].pop(0)
    return life.event(day, ref, kind, -amount if kind == 'buy' else amount,
                      description, security=symbol, quantity=quantity, unit_price=price,
                      realized_gain=amount-basis if kind == 'sell' else '',
                      cost_basis=amount if kind == 'buy' else basis)


def _positions(lots, index):
    result = []
    for symbol in sorted(lots):
        quantity = sum((lot[0] for lot in lots[symbol]), D(0))
        if quantity == 0:
            continue
        price = _price(symbol, index) + (D('1.00') if symbol in ('AAPL', 'MSFT') else D(0))
        result.append(dict(security=symbol, units=units(quantity), unit_price=money(price),
                           market_value=money(quantity * price),
                           cost_basis=money(sum((lot[1] for lot in lots[symbol]), D(0))),
                           **SECURITY_CLASSIFICATIONS[symbol]))
    return result


def _investment_doc(life, ref, institution, index, opening_cash, events, lots, start=None,
                    **extra):
    cash = D(opening_cash) + sum((D(event['amount']) for event in events), D(0))
    if cash < 0:
        raise ValueError(f'negative investment cash {ref} {index}')
    positions = _positions(lots, index)
    total = cash + sum((D(p['market_value']) for p in positions), D(0))
    facts = dict(opening_cash=money(opening_cash), cash=money(cash),
                 total=money(total), positions=positions, activity=events,
                 classification_note='Exposure class and vehicle are declared synthetic source facts, not inferred from ticker names.',
                 **extra)
    life.document('retirement' if ref.startswith('RET') else 'brokerage',
                  '401k_statement' if ref.startswith('RET') else 'brokerage_statement',
                  ref, institution, start or month_date(index), month_end(index), facts, events)
    return cash


def build_life():
    """Return a complete source-ledger dictionary; this function writes nothing."""
    with localcontext(_GENERATION_CONTEXT):
        return _build_life()


def _build_life():
    life = Life()
    life.account('CHECK-A', 'Chase Total Checking', 'Chase', 'depository')
    life.account('SAVE-A', 'Ally Savings Account', 'Ally Bank', 'depository')
    cards = [('CARD-A', 'Chase Freedom Unlimited', 'Chase'),
             ('CARD-B', 'American Express Blue Cash Everyday', 'American Express'),
             ('CARD-C', 'Citi Double Cash', 'Citi'),
             ('CARD-D', 'Discover it Cash Back', 'Discover'),
             ('CARD-E', 'Capital One Quicksilver', 'Capital One')]
    for ref, name, institution in cards:
        life.account(ref, name, institution, 'liability')
    for ref, institution in [('BROKER-A', 'Fidelity Investments'),
                             ('BROKER-B', 'Charles Schwab')]:
        life.account(ref, 'Individual Taxable Brokerage', institution, 'investment')
    for ref, employer in [('RET-A', 'Microsoft'), ('RET-B', 'Amazon'), ('RET-C', 'Salesforce')]:
        life.account(ref, f'{employer} Synthetic 401(k) Plan', 'Fidelity Investments', 'investment')
    for employer in ('Microsoft', 'Amazon', 'Salesforce'):
        life.account(f'PAY-{employer}', f'{employer} payroll source', employer, 'document-only')
    life.account('PROPERTY-A', 'Synthetic primary residence tax source', 'Collin County Tax Assessor-Collector', 'document-only')
    life.account('LOAN-A', 'Original Mortgage', 'Rocket Mortgage', 'liability')
    life.account('LOAN-B', 'Refinanced Mortgage', 'loanDepot', 'liability')
    cd_schedule = [('CD-A', 0, 12, D('20000'), D('3.00')),
                   ('CD-B', 15, 18, D('30000'), D('3.50')),
                   ('CD-C', 30, 24, D('25000'), D('4.00')),
                   ('CD-D', 48, 6, D('15000'), D('4.25'))]
    for ref, *_ in cd_schedule:
        life.account(ref, 'Ally Bank Certificate of Deposit', 'Ally Bank', 'depository')
    checking, savings = D('100000'), D('150000')
    card_balances = {ref: D(0) for ref, *_ in cards}
    brokerage_cash = {'BROKER-A': D('100000'), 'BROKER-B': D('100000')}
    brokerage_lots = {'BROKER-A': {}, 'BROKER-B': {}}
    retirement_cash = D(0)
    retirement_lots = {'FXNAX': [[D('10500'), D('105000')]],
                       'FSKAX': [[D('450'), D('45000')]]}
    pending_rollover = None
    loan_balance = D('630000')
    replacement_original_principal = None
    loan_payment = payment(loan_balance, '5.25', 360)
    escrow = D(0)
    cd_balances = {ref: D(0) for ref, *_ in cd_schedule}
    annual_payroll = {}
    merchants = ['Costco', 'Walmart', 'Target', 'Amazon', 'Starbucks', 'Shell',
                 'AT&T', 'Netflix', 'Home Depot', 'Whole Foods Market']
    for index in range(60):
        start, end = month_date(index), month_end(index)
        checking_events, savings_events = [], []
        employer, annual, retirement_ref = (('Microsoft', D('220000'), 'RET-A') if index < 24 else
                                            ('Amazon', D('250000'), 'RET-B') if index < 42 else
                                            ('Salesforce', D('285000'), 'RET-C'))
        # The last payroll in each calendar year carries the rounding remainder.
        gross = D(money(annual / 12))
        key = (employer, start.year)
        annual_payroll[key] = annual_payroll.get(key, D(0))
        employer_last = index in (23, 41, 59)
        if start.month == 12 or employer_last:
            active_months = (12 if employer != 'Salesforce' or start.year == 2025 else 6)
            if employer == 'Amazon' and start.year == 2024:
                active_months = 6
            gross = annual * D(active_months) / 12 - annual_payroll[key]
        annual_payroll[key] += gross
        deductions = [dict(label='Federal income tax withholding (assumed)', category='tax', amount=money(gross*D('.19'))),
                      dict(label='Payroll tax withholding (assumed)', category='tax', amount=money(gross*D('.06'))),
                      dict(label='Employee 401(k) contribution', category='retirement', amount='1000.00'),
                      dict(label='Health insurance premium (assumed)', category='insurance', amount='300.00')]
        deductions[2].update(contribution_ref=f'RET-CONTRIB-{index:03d}',
                             retirement_account_ref=retirement_ref)
        net = gross - sum((D(row['amount']) for row in deductions), D(0))
        payroll_date = start.replace(day=25)
        checking_events.append(life.event(payroll_date, 'CHECK-A', 'payroll', net,
                                          f'{employer} payroll direct deposit', employer,
                                          f'PAY-{index+1:03d}'))
        life.document('payroll', 'pay_stub', f'PAY-{employer}', employer, start, end,
                      dict(gross=money(gross), deductions=deductions, net=money(net),
                           employer=employer, pay_date=str(payroll_date),
                           annual_salary=money(annual), deposit_account_ref='CHECK-A',
                           retirement_account_ref=retirement_ref,
                           retirement_contribution_ref=f'RET-CONTRIB-{index:03d}'))
        # Pay prior card balances; each settlement is witnessed in checking.
        for card_index, (ref, name, institution) in enumerate(cards):
            old_balance = card_balances[ref]
            card_events = []
            if old_balance:
                transfer = f'CARD-PAY-{ref}-{index:03d}'
                day = start.replace(day=5+card_index)
                card_events.append(life.event(day, ref, 'payment', -old_balance,
                                               f'Payment from Chase CHECK-A', 'CHECK-A', transfer))
                checking_events.append(life.event(day, 'CHECK-A', 'card_payment', -old_balance,
                                                  f'Payment to {institution} {ref}', ref, transfer))
            for purchase in range(4):
                amount = D(80 + card_index*21 + purchase*17 + index % 11)
                card_events.append(life.event(start.replace(day=12+purchase*4), ref, 'purchase', amount,
                                               merchants[(index+card_index+purchase) % len(merchants)]))
            if index % 10 == card_index:
                card_events.append(life.event(start.replace(day=27), ref, 'refund', D('-25'),
                                               f'{merchants[(index+card_index) % len(merchants)]} refund'))
            card_balances[ref] = life.balance_doc('credit-card', 'credit_card_statement', ref,
                                                 institution, index, old_balance, card_events,
                                                 product_name=name)
        transfer = f'SAVINGS-{index:03d}'
        day = start.replace(day=10)
        checking_events.append(life.event(day, 'CHECK-A', 'transfer', -500,
                                          'Transfer to Ally Bank SAVE-A', 'SAVE-A', transfer))
        savings_events.append(life.event(day, 'SAVE-A', 'transfer', 500,
                                         'Transfer from Chase CHECK-A', 'CHECK-A', transfer))
        savings_events.append(life.event(end, 'SAVE-A', 'interest', 50,
                                         'Assumed savings interest credit'))
        checking_events.extend([life.event(start.replace(day=17), 'CHECK-A', 'expense', -300, 'AT&T'),
                                life.event(start.replace(day=18), 'CHECK-A', 'expense', -200, 'State Farm')])
        # Taxable investing: four stock trades plus a mutual-fund purchase monthly.
        for broker_index, (ref, institution, fund) in enumerate([
                ('BROKER-A', 'Fidelity Investments', 'VTSAX'),
                ('BROKER-B', 'Charles Schwab', 'SWPPX')]):
            activity = []
            transfer = f'INVEST-{ref}-{index:03d}'
            day = start.replace(day=11+broker_index)
            checking_events.append(life.event(day, 'CHECK-A', 'transfer', -1000,
                                              f'Transfer to {institution} {ref}', ref, transfer))
            activity.append(life.event(day, ref, 'contribution', 1000,
                                       'Contribution from Chase CHECK-A', 'CHECK-A', transfer))
            lots = brokerage_lots[ref]
            opening_positions = _positions(lots, index-1)
            for trade_day, kind, symbol, quantity in [(13, 'buy', 'AAPL', '10'),
                                                       (15, 'sell', 'AAPL', '4'),
                                                       (18, 'buy', 'MSFT', '5'),
                                                       (20, 'sell', 'MSFT', '2')]:
                price = _price(symbol, index) + (D('2') if kind == 'sell' else D(0))
                activity.append(_trade(life, lots, weekday(start.replace(day=trade_day)), ref, kind,
                                       symbol, quantity, price, f'{kind.title()} {symbol} settled trade'))
            activity.append(_trade(life, lots, weekday(start.replace(day=22)), ref, 'buy', fund, '2',
                                   _price(fund, index), f'Buy {fund} mutual fund'))
            activity.append(life.event(start.replace(day=24), ref, 'dividend', D(15+broker_index),
                                       f'AAPL cash dividend', security='AAPL'))
            brokerage_cash[ref] = _investment_doc(life, ref, institution, index,
                                                  brokerage_cash[ref], activity, lots,
                                                  opening_positions=opening_positions)
        # Retirement contributions and rollover witnesses stay outside checking.
        retirement_events = []
        retire_start = start
        opening_retirement_positions = _positions(retirement_lots, index-1)
        if pending_rollover is not None:
            day, source_ref, amount, transfer = pending_rollover
            retire_start = day
            retirement_events.append(life.event(day, retirement_ref, 'contribution', amount,
                                                 f'Direct rollover from {source_ref}', source_ref, transfer))
            for symbol, share in [('FXNAX', D('.70')), ('FSKAX', D('.30'))]:
                allocation = D(money(amount*share)) if symbol == 'FXNAX' else amount-D(money(amount*D('.70')))
                quantity = D(units(allocation / _price(symbol, index)))
                retirement_events.append(_trade(life, retirement_lots, weekday(start, forward=True),
                                                 retirement_ref, 'buy', symbol, quantity,
                                                 _price(symbol, index), 'Reinvest direct rollover'))
            pending_rollover = None
        retirement_events.append(life.event(start.replace(day=25), retirement_ref, 'contribution', 1000,
                                             f'{employer} employee payroll contribution',
                                             f'PAY-{employer}', f'RET-CONTRIB-{index:03d}'))
        for symbol, amount in [('FXNAX', D('700')), ('FSKAX', D('300'))]:
            quantity = D(units(amount/_price(symbol, index)))
            retirement_events.append(_trade(life, retirement_lots, weekday(start.replace(day=26)), retirement_ref,
                                             'buy', symbol, quantity, _price(symbol, index),
                                             'Employee contribution investment'))
        if index in (23, 41):
            for symbol in sorted(retirement_lots):
                quantity = sum((lot[0] for lot in retirement_lots[symbol]), D(0))
                retirement_events.append(_trade(life, retirement_lots, weekday(end), retirement_ref,
                                                 'sell', symbol, quantity, _price(symbol, index),
                                                 'Liquidation for direct trustee-to-trustee rollover'))
            amount = retirement_cash + sum((D(e['amount']) for e in retirement_events), D(0))
            target_ref = 'RET-B' if index == 23 else 'RET-C'
            transfer = f'ROLLOVER-{index:03d}'
            retirement_events.append(life.event(end, retirement_ref, 'withdrawal', -amount,
                                                 f'Direct rollover to {target_ref}', target_ref, transfer))
            pending_rollover = (end, retirement_ref, amount, transfer)
        retirement_cash = _investment_doc(life, retirement_ref, 'Fidelity Investments', index,
                                          retirement_cash, retirement_events, retirement_lots,
                                          start=retire_start, employer=employer,
                                          contribution_bond_percent='70.00',
                                          contribution_equity_mutual_fund_percent='30.00',
                                          allocation_policy='Contribution target only; market values drift',
                                          opening_positions=opening_retirement_positions)
        # CD openings, monthly accrual and maturity receipts.
        for ref, opened, term, principal, apr in cd_schedule:
            if index == opened:
                transfer = f'CD-FUND-{ref}'
                savings_events.append(life.event(start, 'SAVE-A', 'transfer', -principal,
                                                 f'Open Ally Bank {ref}', ref, transfer))
                funding = life.event(start, ref, 'funding', principal,
                                     'Certificate principal from Ally SAVE-A', 'SAVE-A', transfer)
                life.document('cd-opening', 'cd_certificate', ref, 'Ally Bank', start, start,
                              dict(principal=money(principal), **cd_terms(opened,term,apr,ref)),
                              [funding])
            if opened <= index < opened+term:
                opening = cd_balances[ref]
                events = [life.event(end, ref, 'interest', D(money(principal*apr/1200)),
                                     'Monthly simple interest credited')]
                # First statement witnesses its opening principal funding.
                if index == opened:
                    funding = next(e for e in reversed(life.events) if e['transfer_ref'] == f'CD-FUND-{ref}' and e['account_ref'] == ref)
                    events.insert(0, funding)
                cd_balances[ref] = life.balance_doc('cd', 'cd_statement', ref, 'Ally Bank', index,
                                                   opening, events, principal=money(principal),
                                                   **cd_terms(opened,term,apr,ref),
                                                   interest_earned=money(principal*apr/1200))
            if index == opened+term:
                balance = cd_balances[ref]
                transfer = f'CD-MATURE-{ref}'
                redemption = life.event(start, ref, 'redemption', -balance,
                                        'Maturity proceeds to Ally SAVE-A', 'SAVE-A', transfer)
                savings_events.append(life.event(start, 'SAVE-A', 'transfer', balance,
                                                 f'Maturity proceeds Ally Bank {ref}', ref, transfer))
                life.document('cd-maturity', 'cd_maturity_receipt', ref, 'Ally Bank', start, start,
                              dict(opening=money(balance), closing='0.00', principal=money(principal),
                                   total_interest=money(balance-principal), proceeds=money(balance),
                                   redemption_ref=transfer, **cd_terms(opened,term,apr,ref)),
                              [redemption])
                cd_balances[ref] = D(0)
        # Principal-only liability effects; full cash payments are separate.
        ref, institution, apr = ('LOAN-A', 'Rocket Mortgage', D('5.25')) if index < 24 else ('LOAN-B', 'loanDepot', D('4.25'))
        opening_loan = loan_balance
        interest = D(money(loan_balance*apr/1200))
        principal_payment = loan_payment-interest
        loan_balance -= principal_payment
        escrow_opening = escrow
        escrow_deposit = D('916.67') if start.month != 12 else D('916.63')
        escrow += escrow_deposit
        tax_disbursement = D('11000') if start.month == 12 else D(0)
        escrow -= tax_disbursement
        full_payment = loan_payment+escrow_deposit
        transfer = f'MORTGAGE-{index:03d}'
        checking_payment = life.event(start.replace(day=28), 'CHECK-A', 'mortgage_payment', -full_payment,
                                       f'{institution} {ref} mortgage installment', ref, transfer)
        checking_events.append(checking_payment)
        loan_events = [life.event(start.replace(day=28), ref, 'principal_payment', -principal_payment,
                                 'Scheduled principal reduction', 'CHECK-A', transfer)]
        facts = dict(opening=money(opening_loan), closing=money(loan_balance),
                     payment=money(full_payment), principal=money(principal_payment),
                     interest=money(interest), principal_and_interest=money(loan_payment),
                     escrow_deposit=money(escrow_deposit), escrow_opening=money(escrow_opening),
                     escrow_closing=money(escrow), property_tax_disbursement=money(tax_disbursement),
                     nominal_note_rate=money(apr), rate_basis='nominal_annual', rate_type='fixed',
                     disclosure_apr_status='unavailable',
                     origination_date='2021-01-01' if index < 24 else '2022-12-31',
                     origination_date_basis='declared_synthetic',
                     original_term_months='360' if index < 24 else '336',
                     remaining_term=str((360-index-1) if index < 24 else (336-(index-24)-1)),
                     original_principal='630000.00' if index < 24 else money(replacement_original_principal),
                     payment_number=str(index+1 if index < 24 else index-23),
                     payment_date=str(start.replace(day=28)), payment_reference=transfer,
                     principal_event_id=loan_events[0]['id'], checking_payment_event_id=checking_payment['id'],
                     escrow_account_ref=ESCROW_REF, escrow_restriction='restricted_for_property_tax',
                     escrow_continuity=ESCROW_CONTINUITY,
                     escrow_components=[dict(date=str(start.replace(day=28)),kind='deposit',
                                             amount=money(escrow_deposit),reference=transfer,
                                             escrow_account_ref=ESCROW_REF,source_account_ref='CHECK-A',
                                             destination_account_ref=ESCROW_REF,property_ref='PROPERTY-A',
                                             tax_year=str(start.year),source_event_id=checking_payment['id'])])
        if ref=='LOAN-A':
            facts.update(disclosure_apr='5.25',
                         disclosure_apr_status='owner_specified_fictional_input',
                         disclosure_apr_basis='Owner-specified fictional scenario input; not a computed legal lender disclosure or real offer.')
        tax_reference=f'PROPERTY-TAX-PROPERTY-A-{start.year}'
        if tax_disbursement:
            facts['escrow_components'].append(dict(date=str(end),kind='property_tax_disbursement',
                                                   amount=money(-tax_disbursement),reference=tax_reference,
                                                   escrow_account_ref=ESCROW_REF,source_account_ref=ESCROW_REF,
                                                   destination_account_ref='PROPERTY-A',property_ref='PROPERTY-A',
                                                   tax_year=str(start.year),source_event_id=''))
            facts['escrow_disbursement_date_basis']='declared_synthetic'
        if index == 23:
            payoff = loan_balance
            replacement_original_principal = payoff
            loan_events.append(life.event(end, 'LOAN-A', 'refinance_payoff', -payoff,
                                          'Direct lender payoff by loanDepot LOAN-B', 'LOAN-B', 'REFI-001'))
            loan_events_new = [life.event(end, 'LOAN-B', 'refinance_funding', payoff,
                                         'New loan proceeds paid directly to Rocket Mortgage LOAN-A', 'LOAN-A', 'REFI-001')]
            fees = D('3000')
            fee_event=life.event(end, 'CHECK-A', 'closing_fee', -fees,
                                 'loanDepot refinance closing costs', 'LOAN-B', 'REFI-FEES')
            checking_events.append(fee_event)
            facts['closing'] = '0.00'
            facts['refinance_payoff'] = money(payoff)
            life.document('refinance', 'refinance_statement', 'LOAN-B', 'loanDepot', end, end,
                          dict(opening='0.00', closing=money(payoff), new_principal=money(payoff),
                               prior_loan_payoff=money(payoff), cash_out='0.00',
                               fees_paid_from_checking=money(fees),nominal_note_rate='4.25',
                               rate_basis='nominal_annual',rate_type='fixed',disclosure_apr_status='unavailable',
                               origination_date=str(end),origination_date_basis='declared_synthetic',
                               original_term_months='336',original_principal=money(payoff),term_months='336',
                               first_payment_date='2023-01-28', prior_loan_ref='LOAN-A',
                               old_loan_ref='LOAN-A',new_loan_ref='LOAN-B',
                               funded_principal=money(payoff),borrower_contribution=money(fees),
                               financed_fees='0.00',funding_reference='REFI-001',
                               fee_payment_reference='REFI-FEES',borrower_contribution_reference='REFI-FEES',
                               borrower_source_account_ref='CHECK-A',borrower_contribution_event_id=fee_event['id'],
                               fee_items=[dict(name='Origination services (synthetic)',amount='2000.00',reference='REFI-FEES'),
                                          dict(name='Title and settlement (synthetic)',amount='1000.00',reference='REFI-FEES')],
                               sources_total=money(payoff+fees),uses_total=money(payoff+fees),
                               escrow_account_ref=ESCROW_REF,escrow_restriction='restricted_for_property_tax',
                               escrow_continuity=ESCROW_CONTINUITY), loan_events_new)
            loan_payment = payment(payoff, '4.25', 336)
        life.document('mortgage', 'mortgage_statement', ref, institution, start, end, facts, loan_events)
        if start.month == 12:
            life.document('property-tax', 'property_tax_statement', 'PROPERTY-A',
                          'Collin County Tax Assessor-Collector', date(start.year, 1, 1), end,
                          dict(annual_property_tax='11000.00', tax_paid='11000.00',
                               paid_from='Mortgage escrow', property_ref='PROPERTY-A',
                               tax_year=str(start.year), tax_convention='Fictional fixed annual assessment; no historical rate claim',
                               paid_status='paid',payment_date=str(end),payment_date_basis='declared_synthetic',
                               payment_reference=tax_reference,source_escrow_account_ref=ESCROW_REF))
        checking_events.sort(key=lambda e: (e['date'], e['id']))
        savings_events.sort(key=lambda e: (e['date'], e['id']))
        checking = life.balance_doc('checking', 'checking_statement', 'CHECK-A', 'Chase', index,
                                    checking, checking_events, product_name='Chase Total Checking')
        savings = life.balance_doc('savings', 'savings_statement', 'SAVE-A', 'Ally Bank', index,
                                   savings, savings_events, product_name='Ally Savings Account')
        if min(checking, savings) < 0:
            raise ValueError('Persona cannot fund its spending')
    seed_cash = {'CHECK-A':'100000.00','SAVE-A':'150000.00','BROKER-A':'100000.00','BROKER-B':'100000.00','LOAN-A':'630000.00'}
    for account in life.accounts:
        account['initial_balance'] = seed_cash.get(account['ref'], '0.00')
        if account['kind'] == 'investment':
            account['initial_cash'] = account['initial_balance']
        if account['ref'] == 'RET-A':
            account['initial_positions'] = [dict(security='FXNAX',units='10500.00000000',unit_price='10.00',market_value='105000.00',cost_basis='105000.00'),dict(security='FSKAX',units='450.00000000',unit_price='100.00',market_value='45000.00',cost_basis='45000.00')]
            for position in account['initial_positions']:
                position.update(SECURITY_CLASSIFICATIONS[position['security']])
    if len(life.documents) != EXPECTED_DOCUMENTS:
        raise ValueError(f'Expected {EXPECTED_DOCUMENTS} documents, built {len(life.documents)}')
    return dict(schema_version=SCHEMA,
                persona=dict(name='Alex Morgan', fictional=True, currency='USD', locale='en-US',
                             period_start='2021-01-01', period_end='2025-12-31',
                             address='SYNTHETIC ADDRESS - NOT DELIVERABLE'),
                assumptions=dict(prices='Invented deterministic prices; not historical market data',
                                 tax='Invented withholding amounts; not tax advice or actual tax liability',
                                 employment='Fictional employment and retirement plans; real company names only',
                                 document_mark='SYNTHETIC TEST DOCUMENT - NOT ISSUED BY THE NAMED INSTITUTION',
                                 rounding='Decimal ROUND_HALF_UP, money cents, units eight decimals; monthly payroll rounding remainder in final active calendar-year payroll',
                                 cd='60 active monthly statements across terms 12,18,24,6 whole equal_monthly_12 months; monthly simple interest principal*nominal annual percent/1200; maturity first day after final active month',
                                 retirement='Three distinct employer plans; liquidation/direct trustee cash rollover with matching boundary dates and no checking deposit; new first statement includes prior month-end rollover as explicit boundary opening evidence; 70:30 contribution targets with disclosed valuation drift',
                                 mortgage='30-year630000 at5.25%; refinance after24payments to4.25%remaining336months; no cashout;3000fees paid separately',
                                 seed_balances={'CHECK-A':'100000.00','SAVE-A':'150000.00','BROKER-A':'100000.00','BROKER-B':'100000.00','RET-A':'150000.00'},
                                 annual_property_tax='11000.00', employer_match='0.00',
                                 expected_five_year_gross='1242500.00'),
                security_names=SECURITY_NAMES,
                source_subaccounts=[dict(ref=ESCROW_REF,kind='restricted_escrow',
                                         restriction='restricted_for_property_tax',initial_balance='0.00',
                                         property_ref='PROPERTY-A',loan_refs=['LOAN-A','LOAN-B'],
                                         continuity=ESCROW_CONTINUITY)],
                accounts=life.accounts, events=life.events, documents=life.documents)


def _pretty_label(label):
    return label.replace('_', ' ').capitalize()


def render_document(path, doc, ledger):
    """Render readable source fields and every transaction, with a page watermark."""
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from xml.sax.saxutils import escape
    styles = getSampleStyleSheet()
    styles['Normal'].fontSize = 8
    styles['Normal'].leading = 11
    story = []
    def para(value, style='Normal'):
        return Paragraph(escape(str(value)), styles[style])
    story.extend([para(doc['institution'], 'Title'),
                  para(_pretty_label(doc['family'])+' - Alex Morgan', 'Heading2'),
                  para(f"Document {doc['id']} | Account reference {doc['account_ref']} | USD | en-US"),
                  para(f"Period {doc['period_start']} to {doc['period_end']} | As of {doc['as_of']}"),
                  para('All activity, employment, prices and terms are fictional scenario assumptions.'),
                  Spacer(1, .12*inch)])
    for key, value in doc['facts'].items():
        if isinstance(value, (list, dict)):
            continue
        story.append(para(f'{_pretty_label(key)}: {value}'))
    if 'deductions' in doc['facts']:
        story.append(para('Current-period deductions', 'Heading3'))
        for row in doc['facts']['deductions']:
            detail=f"{row['label']} | {row['category']} | {row['amount']} USD"
            if row.get('contribution_ref'):
                detail+=f" | Contribution reference: {row['contribution_ref']} | Retirement account: {row['retirement_account_ref']}"
            story.append(para(detail))
    if 'escrow_components' in doc['facts']:
        story.append(para('Restricted escrow component witnesses', 'Heading3'))
        story.append(para('These rows explain the existing installment and escrow effects; they are not additional household cash transactions.'))
        rows=[['Date / kind','References / source evidence','Effect USD']]
        for row in doc['facts']['escrow_components']:
            detail=(f"Reference: {row['reference']} | Escrow account: {row['escrow_account_ref']}"
                    f" | Source account: {row['source_account_ref']} | Destination account: {row['destination_account_ref']}"
                    f" | Property: {row['property_ref']} | Tax year: {row['tax_year']}"
                    f" | Source event: {row['source_event_id'] or 'none (existing escrow effect; not a new cash event)'}")
            rows.append([para(f"{row['date']} / {row['kind']}"),para(detail),para(row['amount'])])
        table=Table(rows,repeatRows=1,colWidths=[110,325,65])
        table.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),('GRID',(0,0),(-1,-1),.25,colors.lightgrey),('FONTSIZE',(0,0),(-1,-1),7)]))
        story.extend([table,Spacer(1,.1*inch)])
    if 'fee_items' in doc['facts']:
        story.append(para('Separately paid closing fees', 'Heading3'))
        for row in doc['facts']['fee_items']:
            story.append(para(f"Fee: {row['name']} | Amount: {row['amount']} USD | Reference: {row['reference']}"))
    for holding_key in ('opening_positions', 'positions'):
        if holding_key not in doc['facts']:
            continue
        title = 'Opening holdings' if holding_key == 'opening_positions' else 'Closing holdings'
        story.append(para(title+' - synthetic prices; market value is not a cash movement', 'Heading3'))
        rows = [['Security','Units','Unit price','Market value','Cost basis','Exposure / vehicle']]
        rows += [[para(p['security']+' '+SECURITY_NAMES[p['security']]),p['units'],p['unit_price'],p['market_value'],p['cost_basis'],
                  para(f"Exposure class: {p['exposure_class']}; Vehicle: {p['vehicle']}")]
                 for p in doc['facts'][holding_key]]
        table = Table(rows, repeatRows=1, colWidths=[110,80,65,80,80,105])
        table.setStyle(TableStyle([('FONTSIZE',(0,0),(-1,-1),7),('GRID',(0,0),(-1,-1),.25,colors.lightgrey)]))
        story.extend([table,Spacer(1,.1*inch)])
    index = {e['id']:e for e in ledger['events']}
    if doc['events']:
        story.append(para('Transactions - signed effect on printed balance / investment cash', 'Heading3'))
        if doc['family'] == 'mortgage':
            story.append(para('Loan transactions affect principal only. The installment also pays the separately stated interest and escrow.'))
        rows = [['Event / date','Description / source reference','Effect USD']]
        for event_id in doc['events']:
            event = index[event_id]
            detail = f"{event['description']} | Kind {event['kind']}"
            if event['transfer_ref']:
                detail += f" | Link {event['transfer_ref']} | Counterpart {event['counterpart_ref']}"
            if event['security']:
                detail += f" | Security {event['security']} {SECURITY_NAMES[event['security']]}"
            if event['units']:
                detail += f" | Units {event['units']} | Unit price {event['unit_price']} | Cost basis {event['cost_basis']}"
            if event['realized_gain']:
                detail += f" | Realized gain {event['realized_gain']}"
            rows.append([para(f"{event['id']} / {event['date']}"),para(detail),para(event['amount'])])
        table = Table(rows, repeatRows=1, colWidths=[105,280,65])
        table.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),('GRID',(0,0),(-1,-1),.25,colors.lightgrey),('BACKGROUND',(0,0),(-1,0),colors.whitesmoke)]))
        story.append(table)
    def mark(canvas, document):
        canvas.saveState()
        canvas.setFont('Helvetica-Bold', 8)
        canvas.setFillColor(colors.HexColor('#8b2020'))
        canvas.drawCentredString(306, 770, 'SYNTHETIC TEST DOCUMENT - NOT ISSUED BY THE NAMED INSTITUTION')
        canvas.setFont('Helvetica', 7)
        canvas.drawString(40, 27, f"Fictional Alex Morgan | {doc['id']} | {doc['account_ref']}")
        canvas.drawRightString(572, 27, f'Page {document.page}')
        canvas.restoreState()
    document = SimpleDocTemplate(str(path), pagesize=(612,792), topMargin=40,
                                 bottomMargin=40, leftMargin=40,rightMargin=40,
                                 invariant=1,title=f"Synthetic {doc['id']}",author='Synthetic campaign')
    document.build(story, onFirstPage=mark, onLaterPages=mark)


def generate(out, render_pdfs=False):
    ledger = build_life()
    out.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(ledger, indent=2, sort_keys=True)+'\n').encode()
    (out/'source-ledger.json').write_bytes(raw)
    counts = {}
    for doc in ledger['documents']:
        counts[doc['family']] = counts.get(doc['family'],0)+1
    manifest = dict(schema_version=SCHEMA, generator_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), source_ledger_sha256=hashlib.sha256(raw).hexdigest(),
                    expected_document_count=EXPECTED_DOCUMENTS, document_count=len(ledger['documents']),
                    family_counts=counts, rendered=render_pdfs,
                    documents=[dict(id=d['id'],file=d['file'],family=d['family'],
                                    account_ref=d['account_ref'],period_start=d['period_start'],
                                    period_end=d['period_end']) for d in ledger['documents']])
    if render_pdfs:
        from pypdf import PdfReader
        for doc, row in zip(ledger['documents'],manifest['documents']):
            path=out/doc['file']
            render_document(path,doc,ledger)
            row['sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
            row['page_count']=len(PdfReader(path).pages)
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2,sort_keys=True)+'\n')
    return manifest


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out-dir',type=Path,default=DEFAULT_OUT)
    parser.add_argument('--render-pdfs',action='store_true',help='Create PDFs only after recording the PDF artifact marker')
    args=parser.parse_args()
    manifest=generate(args.out_dir,args.render_pdfs)
    print(json.dumps({k:v for k,v in manifest.items() if k!='documents'},sort_keys=True))


if __name__=='__main__':
    main()
