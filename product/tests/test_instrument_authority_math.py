from decimal import Decimal, localcontext, Inexact
import pytest
from viva.read_store.instrument_math import (decimal_fraction, source_rate_fraction,
    allocation_points, rounded_points, InstrumentMathError)


def test_source_rate_converts_once_and_context_independent():
    with localcontext() as context:
        context.prec = 1
        context.traps[Inexact] = True
        assert source_rate_fraction(Decimal('5.25')) == '0.0525'
        assert allocation_points(Decimal('7'), Decimal('10'), 2, 3).value == '+3.33333333'


@pytest.mark.parametrize('value', ['-0', '1e999999', '0e-100', '0.0000000000000', '1'*31, 'NaN', 'Infinity'])
def test_representation_refuses_before_expansion(value):
    with pytest.raises(InstrumentMathError):
        decimal_fraction(Decimal(value))


@pytest.mark.parametrize('n,d,expected', [(1,200000000,'0'), (3,200000000,'+0.00000002'),
    (-3,200000000,'-0.00000002'), (100,1,'+100'),(-100,1,'-100'),
    (100000001,200000000,'+0.5'),(100000003,200000000,'+0.50000002')])
def test_direct_half_even(n,d,expected):
    assert rounded_points(n,d).value == expected


def test_exactness_and_bounded_intermediate():
    assert allocation_points(Decimal('7'),Decimal('10'),7,10).value == '0'
    assert allocation_points(Decimal('7'),Decimal('10'),7,10).exact
    with pytest.raises(InstrumentMathError, match='resource_limit'):
        rounded_points(1 << 511, (1 << 511) + 1)


@pytest.mark.parametrize('sign',[1,-1])
def test_former_decimal_intermediate_double_rounding_counterexample(sign):
    from decimal import ROUND_HALF_EVEN
    n=sign*(1234567885*10**33+1);d=10**42
    expected='+1.23456789' if sign>0 else '-1.23456789'
    assert rounded_points(n,d).value==expected
    with localcontext() as context:
        context.prec=40
        former=(Decimal(n)/Decimal(d)).quantize(Decimal('0.00000001'),rounding=ROUND_HALF_EVEN)
    assert str(former)!=expected.lstrip('+')


@pytest.mark.parametrize('n,d,expected',[(1234567885*10**5-1,10**14,'+1.23456788'),
    (1234567885*10**5+1,10**14,'+1.23456789'),
    (1234567895*10**5-1,10**14,'+1.23456789'),(1234567895*10**5+1,10**14,'+1.2345679')])
def test_above_and_below_even_and_odd_ties(n,d,expected):
    assert rounded_points(n,d).value==expected
