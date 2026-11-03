"""Pure exact bounded decimal aggregation and report protocol constants."""
from datetime import date
from decimal import Decimal, InvalidOperation, localcontext

from .investment_numbers import key,display

SCHEMA='sql-native-income-expense-v1'
LIMITATIONS=[
    'No household or net-worth parity.',
    'No human classification, rule or correction workflow parity.',
    'No investment funding certification or unknown-gain inference.',
    'No new PDF-field verification.',
]
TOTALS=('admitted_income','admitted_expenses','admitted_net','provisional_income','provisional_expenses')


def amount(value):
    if type(value) is not str:
        raise ValueError('admitted amount must be a finite decimal string')
    try:
        with localcontext():
            result=Decimal(value)
    except InvalidOperation as error:
        raise ValueError('admitted amount must be a finite decimal string') from error
    if not result.is_finite():
        raise ValueError('admitted amount must be finite')
    return result


def period(start,end):
    for value in (start,end):
        if type(value) is not str:
            raise ValueError('income/expense dates require plain strings')
        if value:
            try:
                if date.fromisoformat(value).isoformat()!=value:
                    raise ValueError('noncanonical date')
            except ValueError as error:
                raise ValueError('income/expense dates require canonical ISO dates') from error
    if start and end and start>end:
        raise ValueError('income/expense start follows end')


def total(values):
    """Cancel sparse coefficients before any exponent-sized allocation."""
    groups={}
    for value in values:
        sign,digits,exponent=key(amount(value))
        integer=0
        for offset in range(0,len(digits),256):
            part=digits[offset:offset+256]
            integer=integer*10**len(part)+int(part)
        if integer:
            groups[exponent]=groups.get(exponent,0)+(-integer if sign else integer)
    while True:
        normalized={}
        for exponent,integer in groups.items():
            if not integer:
                continue
            while integer%10==0:
                integer//=10;exponent+=1
            normalized[exponent]=normalized.get(exponent,0)+integer
        if normalized==groups:
            break
        groups=normalized
    if not groups:
        return '0'
    digits={exponent:Decimal(abs(integer)).as_tuple().digits for exponent,integer in groups.items()}
    low=min(groups)
    span=max(exponent+len(digits[exponent]) for exponent in groups)-low
    if span>16384:
        return None
    integer=sum(coefficient*10**(exponent-low) for exponent,coefficient in groups.items())
    if not integer:return '0'
    while integer%10==0:
        integer//=10;low+=1
    coefficient_digits=Decimal(abs(integer)).as_tuple().digits
    if len(coefficient_digits)>16384:return None
    return display(Decimal((int(integer<0),coefficient_digits,low)))


def json_value(value):
    """Only detached JSON primitives, arrays and string-keyed objects qualify."""
    if value is None or type(value) in (str,int,bool):return True
    if type(value) is list:return all(json_value(item) for item in value)
    if type(value) is dict:return all(type(key) is str and json_value(item) for key,item in value.items())
    return False
