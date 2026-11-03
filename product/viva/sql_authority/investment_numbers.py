"""Exact compact decimal identities and allocation-bounded posting arithmetic."""
from decimal import Decimal, Inexact, localcontext, MAX_EMAX, MIN_EMIN


def key(value):
    if type(value) is not Decimal or not value.is_finite():
        raise ValueError('investment amounts require finite Decimal values')
    sign, digits, exponent = value.as_tuple()
    coefficient = ''.join(str(digit) for digit in digits).lstrip('0')
    if not coefficient:
        return [0, '0', 0]
    trailing = len(coefficient) - len(coefficient.rstrip('0'))
    return [sign, coefficient.rstrip('0'), exponent + trailing]


def display(value):
    sign, coefficient, exponent = key(value)
    if coefficient == '0':
        return '0'
    prefix = '-' if sign else ''
    length = len(coefficient)
    fixed_length = (len(prefix) + length + exponent if exponent >= 0
                    else len(prefix) + length + 1 if length + exponent > 0
                    else len(prefix) + 2 - exponent)
    if fixed_length > 128:
        return prefix + coefficient + 'e' + str(exponent)
    if exponent >= 0:
        return prefix + coefficient + '0' * exponent
    split = length + exponent
    if split > 0:
        return prefix + coefficient[:split] + '.' + coefficient[split:]
    return prefix + '0.' + '0' * (-split) + coefficient


def scalar(value):
    if type(value) is not str or len(value.encode()) > 16384:
        raise ValueError('invalid investment number scalar')
    result = Decimal(value)
    if display(result) != value:
        raise ValueError('noncanonical investment number scalar')
    return result


def valid_key(value):
    if (type(value) is not list or len(value) != 3
            or type(value[0]) is not int or value[0] not in (0, 1)
            or type(value[1]) is not str or not value[1].isascii()
            or not value[1].isdigit() or not value[1]
            or type(value[2]) is not int):
        return False
    if value[1] == '0':
        return value == [0, '0', 0]
    return value[1][0] != '0' and value[1][-1] != '0'


def zero_sum(values):
    """Cancel sparse decimal terms without expanding gaps between exponents."""
    terms = {}
    for value in values:
        sign, coefficient, exponent = key(value)
        if coefficient == '0':
            continue
        # Avoid Python's decimal-string integer conversion limit for genuine
        # typed legacy measurements: fold bounded chunks instead.
        integer = 0
        for offset in range(0, len(coefficient), 256):
            chunk = coefficient[offset:offset + 256]
            integer = integer * 10 ** len(chunk) + int(chunk)
        terms[exponent] = terms.get(exponent, 0) + (-integer if sign else integer)
    while terms:
        exponent = min(terms)
        coefficient = terms.pop(exponent)
        if not coefficient:
            continue
        while coefficient % 10 == 0:
            coefficient //= 10
            exponent += 1
        if exponent in terms:
            terms[exponent] += coefficient
            continue
        # A higher decimal exponent cannot cancel this nonzero final digit.
        if not terms or exponent < min(terms):
            return False
        terms[exponent] = coefficient
    return True


def negate(value):
    """Negation does not consult the ambient Decimal context."""
    return value.copy_negate()


def exact_sum(values):
    values = tuple(values)
    nonzero = [key(value) for value in values if key(value)[1] != '0']
    if not nonzero:
        return Decimal(0)
    precision = max(e + len(c) for _, c, e in nonzero) - min(e for _, c, e in nonzero) + 2
    if precision > 16384:
        raise ValueError('investment arithmetic resource_limit')
    with localcontext() as context:
        context.Emax, context.Emin = MAX_EMAX, MIN_EMIN
        context.prec = max(1, precision)
        context.traps[Inexact] = True
        return sum(values, Decimal(0))


def posting_precision(amount, gain=None):
    values = [amount] + ([] if gain is None else [gain])
    keys = [key(value) for value in values]
    if any(len(display(value).encode()) > 16384 for value in values):
        raise ValueError('investment activity resource_limit')
    nonzero = [(c, e) for _, c, e in keys if c != '0']
    if not nonzero or amount <= 0:
        raise ValueError('investment activity requires positive magnitude')
    precision = max(1, max(e + len(c) for c, e in nonzero) - min(e for _, e in nonzero) + 2)
    if precision > 16384:
        raise ValueError('investment activity resource_limit')
    return precision
