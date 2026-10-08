"""Pure monthly scenarios with explicit cent and calendar conventions."""
from decimal import Decimal, localcontext, ROUND_HALF_EVEN
from datetime import date
import calendar
import re

CENTS = Decimal('0.01')
_DECIMAL = re.compile(r'\+?[0-9]{1,15}(?:\.[0-9]{1,6})?\Z', re.ASCII)
_INTEGER = re.compile(r'[0-9]{1,3}\Z', re.ASCII)


class ScenarioError(ValueError):
    def __init__(self, tag):
        self.tag = tag
        super().__init__(tag)


def decimal(value):
    if not isinstance(value, str) or not _DECIMAL.fullmatch(value):
        raise ScenarioError('scenario_premise_source_mismatch')
    return Decimal(value)


def horizon(value):
    if not isinstance(value, str) or not _INTEGER.fullmatch(value) or not 1 <= int(value) <= 600:
        raise ScenarioError('scenario_premise_source_mismatch')
    return int(value)


def anchor(value):
    try:
        held = date.fromisoformat(value)
        if held.isoformat() != value:
            raise ValueError
        return held
    except (TypeError, ValueError):
        raise ScenarioError('scenario_premise_source_mismatch') from None


def advance(start, months):
    index = start.year * 12 + start.month - 1 + months
    year, month = divmod(index, 12)
    month += 1
    if not 1 <= year <= 9999:
        raise ScenarioError('scenario_calendar_range_unavailable')
    return date(year, month, min(start.day, calendar.monthrange(year, month)[1])).isoformat()


def _inputs(money, rate, months, start_date):
    exact = {name: decimal(value) for name, value in money.items()}
    annual = decimal(rate)
    if annual > 100:
        raise ScenarioError('scenario_premise_source_mismatch')
    count = horizon(months)
    start = anchor(start_date)
    modeled = {name: value.quantize(CENTS, rounding=ROUND_HALF_EVEN) for name, value in exact.items()}
    return modeled, annual / Decimal(1200), count, start


def _finish(result, rows, modeled, landmarks=()):
    keep = {0, len(rows)-1, *landmarks}
    keep.update(range(len(rows)) if len(rows)<=24 else (round(i*(len(rows)-1)/23) for i in range(24)))
    if len(keep) > 24:
        optional = sorted(keep - {0, len(rows)-1, *landmarks})
        keep.difference_update(optional[:len(keep)-24])
    result.update(modeled_inputs={name:str(value) for name,value in modeled.items()},
                  trajectory=[rows[i] for i in sorted(keep)],
                  trajectory_sampled=len(rows)>len(keep), total_periods=len(rows))
    return result


def savings(initial_amount, monthly_contribution, nominal_annual_rate_percent, months, start_date):
    with localcontext() as ctx:
        ctx.prec = 80
        ctx.rounding = ROUND_HALF_EVEN
        modeled, rate, count, start = _inputs({'initial_amount':initial_amount,'monthly_contribution':monthly_contribution}, nominal_annual_rate_percent,months,start_date)
        balance = principal = modeled['initial_amount']
        growth = Decimal('0.00')
        rows = []
        for month in range(1,count+1):
            interest = (balance*rate).quantize(CENTS)
            growth += interest
            principal += modeled['monthly_contribution']
            balance = (balance+interest+modeled['monthly_contribution']).quantize(CENTS)
            rows.append({'month':month,'date':advance(start,month),'balance':str(balance),'interest':str(interest),'contribution':str(modeled['monthly_contribution'])})
        return _finish({'final_balance':str(balance),'contributed_principal':str(principal),'growth':str(growth),'horizon_date':rows[-1]['date']}, rows, modeled)


def loan_payoff(principal, monthly_payment, nominal_annual_rate_percent, months, start_date):
    with localcontext() as ctx:
        ctx.prec = 80
        ctx.rounding = ROUND_HALF_EVEN
        modeled, rate, count, start = _inputs({'principal':principal,'monthly_payment':monthly_payment},nominal_annual_rate_percent,months,start_date)
        balance = modeled['principal']
        payment = modeled['monthly_payment']
        if balance > 0 and decimal(monthly_payment)>0 and payment == 0:
            raise ScenarioError('scenario_payment_rounds_to_zero')
        if balance > 0 and rate > 0 and payment <= (balance*rate).quantize(CENTS):
            raise ScenarioError('scenario_non_amortizing_payment')
        interest_paid = repayments = Decimal('0.00')
        payments = 0
        payoff = ''
        rows = []
        for month in range(count):
            dated = advance(start,month)
            interest = (balance*rate).quantize(CENTS)
            applied = min(payment,balance+interest)
            balance = (balance+interest-applied).quantize(CENTS)
            interest_paid += interest
            repayments += applied
            payments += int(applied>0)
            if modeled['principal']>0 and balance == 0 and not payoff:
                payoff = dated
            rows.append({'month':month+1,'date':dated,'remaining_debt':str(balance),'interest':str(interest),'payment':str(applied)})
        landmarks = [i for i,row in enumerate(rows) if row['date']==payoff]
        return _finish({'remaining_debt':str(balance),'interest_paid':str(interest_paid),'repayments_paid':str(repayments),'payment_count':payments,'payoff_date':payoff,'horizon_date':rows[-1]['date']},rows,modeled,landmarks)


def cash_flow(initial_cash, monthly_income, monthly_outflow, one_off_outflow, one_off_month, months, start_date):
    with localcontext() as ctx:
        ctx.prec = 80
        ctx.rounding = ROUND_HALF_EVEN
        modeled, _rate, count, start = _inputs({'initial_cash':initial_cash,'monthly_income':monthly_income,'monthly_outflow':monthly_outflow,'one_off_outflow':one_off_outflow},'0',months,start_date)
        one_off = horizon(one_off_month)
        if one_off > count:
            raise ScenarioError('scenario_premise_source_mismatch')
        balance = modeled['initial_cash']
        rows = []
        for month in range(1,count+1):
            outgoing = modeled['one_off_outflow'] if month==one_off else Decimal('0.00')
            balance = (balance+modeled['monthly_income']-modeled['monthly_outflow']-outgoing).quantize(CENTS)
            rows.append({'month':month,'date':advance(start,month),'balance':str(balance),'one_off_outflow':str(outgoing)})
        minimum = min(range(len(rows)),key=lambda i:Decimal(rows[i]['balance']))
        first = next((i for i,row in enumerate(rows) if Decimal(row['balance'])<0),None)
        return _finish({'final_cash':str(balance),'minimum_cash':rows[minimum]['balance'],'minimum_date':rows[minimum]['date'],'first_negative_date':rows[first]['date'] if first is not None else '', 'horizon_date':rows[-1]['date']},rows,modeled,[minimum,*([first] if first is not None else [])])
