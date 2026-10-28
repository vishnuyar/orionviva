"""Bounded exact instrument arithmetic independent of Decimal contexts."""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from math import gcd
import re


class InstrumentMathError(ValueError):
    """An operand exceeds the accepted numeric representation or resource bound."""


def _bounded(value):
    if type(value) is not int or value.bit_length() > 512:
        raise InstrumentMathError("resource_limit")
    return value


def _mul(a, b):
    if a and b and abs(a).bit_length() + abs(b).bit_length() > 512:
        if abs(a)==1:return _bounded(b if a>0 else -b)
        if abs(b)==1:return _bounded(a if b>0 else -a)
        raise InstrumentMathError("resource_limit")
    return _bounded(a * b)


def rational(numerator, denominator=1):
    _bounded(numerator); _bounded(denominator)
    if denominator <= 0:
        raise InstrumentMathError("invalid denominator")
    common = gcd(numerator, denominator)
    return numerator // common, denominator // common


def decimal_fraction(value, *, rate=False):
    """Inspect representation before expansion or integer-power construction."""
    if type(value) is str:
        if len(value) > 64 or not value.isascii() or not re.fullmatch(r'[+]?[0-9]+(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?', value):
            raise InstrumentMathError("invalid decimal representation")
        try:
            value = Decimal(value)
        except InvalidOperation:
            raise InstrumentMathError("invalid decimal") from None
    if type(value) is not Decimal or not value.is_finite():
        raise InstrumentMathError("finite Decimal required")
    sign, digits, exponent = value.as_tuple()
    if (sign or len(digits) > 30 or not -12 <= exponent <= 18
            or max(len(digits) + exponent, 0) > 18 or max(-exponent, 0) > 12):
        raise InstrumentMathError("invalid decimal representation")
    coefficient = 0
    for digit in digits:
        coefficient = _bounded(_mul(coefficient, 10) + digit)
    n, d = (coefficient, 10 ** -exponent) if exponent < 0 else (_mul(coefficient, 10 ** exponent), 1)
    n, d = rational(n, d)
    if rate and n > _mul(100, d):
        raise InstrumentMathError("rate outside [0,100]")
    return n, d


def _decimal_text(n, d, *, signed=False):
    negative = n < 0
    n = abs(n)
    whole, remainder = divmod(n, d)
    decimals = []
    while remainder:
        remainder = _mul(remainder, 10)
        digit, remainder = divmod(remainder, d)
        decimals.append(str(digit))
        if len(decimals) > 64:
            raise InstrumentMathError("nonterminating decimal")
    prefix = '-' if negative else '+' if signed and n else ''
    return prefix + str(whole) + ('.' + ''.join(decimals) if decimals else '')


def source_rate_fraction(value):
    n, d = decimal_fraction(value, rate=True)
    return _decimal_text(*rational(n, _mul(d, 100)))


@dataclass(frozen=True)
class PointDifference:
    value: str
    exact: bool
    numerator: int
    denominator: int


def rounded_points(n, d):
    """Round the exact rational directly to eight fractional point digits."""
    n, d = rational(n, d)
    if abs(n) > _mul(100, d):
        raise InstrumentMathError("points outside [-100,100]")
    scaled = _mul(abs(n), 100000000)
    quotient, remainder = divmod(scaled, d)
    doubled = _mul(remainder, 2)
    if doubled > d or (doubled == d and quotient % 2):
        quotient = _bounded(quotient + 1)
    value = _decimal_text(-quotient if n < 0 else quotient, 100000000, signed=True)
    if len(value) > 13:
        raise InstrumentMathError("resource_limit")
    return PointDifference(value, remainder == 0, n, d)


def allocation_points(numerator, total, target_n, target_d):
    n, d = decimal_fraction(numerator)
    total_n, total_d = decimal_fraction(total)
    target_n, target_d = rational(target_n, target_d)
    if not total_n or target_n < 0 or target_n > target_d:
        raise InstrumentMathError("invalid allocation denominator or target")
    actual_n, actual_d = rational(_mul(n, total_d), _mul(d, total_n))
    if actual_n > actual_d:
        raise InstrumentMathError("allocation numerator exceeds denominator")
    result_n = _bounded(_mul(actual_n, target_d) - _mul(target_n, actual_d))
    result_d = _mul(actual_d, target_d)
    return rounded_points(_mul(result_n, 100), result_d)
