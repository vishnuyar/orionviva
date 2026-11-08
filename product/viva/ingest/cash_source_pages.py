"""Printed cash anchors are used only when their bounded facts agree."""
from vivacore.verify.normalize import parse_amount, parse_date
from ..investment.extraction import InvestmentSource, SourceField
from ..investment.payroll_extraction import validate_pages


def _bounded_source(facts, source):
    count = getattr(facts, 'validated_source_page_count', None)
    if type(count) is not int or not 1 <= count <= 200 or source is None:
        return None
    try:
        validate_pages(source, count)
    except (ValueError, TypeError, AttributeError):
        return None
    return count


def _page(field, count):
    if (type(field) is SourceField and type(field.page) is int
            and 1 <= field.page <= count):
        return field.page
    return None


def _supported(field):
    return type(field) is SourceField and type(field.page) is int and 1 <= field.page <= 200


def _text(field, expected):
    return _supported(field) and field.raw == expected


def _amount(field, expected, currency, *, magnitude=False):
    if not _supported(field):
        return False
    parsed = parse_amount(field.raw, 'en-US', currency)
    if not parsed.ok:
        return False
    value = parsed.decimal()
    return (value.copy_abs() if magnitude else value) == expected


def _date(field, expected):
    if not _supported(field):
        return False
    parsed = parse_date(field.raw, 'en-US')
    return parsed.ok and parsed.value == expected


def _activity_matches(row, activity, facts):
    if (not _date(row.get('date'), activity.date or facts.as_of)
            or not _text(row.get('kind'), activity.kind)
            or not _amount(row.get('amount'), activity.amount, facts.currency,
                           magnitude=True)):
        return False
    security = row.get('security_identifier')
    if activity.instrument:
        if not _text(security, activity.instrument):
            return False
    elif security is not None and (type(security) is not SourceField or security.raw):
        return False
    gain = row.get('reported_realized_gain')
    if activity.realized_gain is not None:
        return _amount(gain, activity.realized_gain, facts.currency)
    return gain is None or (type(gain) is SourceField and not gain.raw)


def brokerage_activity_pages(facts):
    """Resolve the accepted ordered batch once; repeated equal rows need one page."""
    unavailable = (None,) * len(facts.activity)
    source = facts.investment_source
    if type(source) is not InvestmentSource:
        return unavailable
    count = _bounded_source(facts, source)
    if count is None:
        return unavailable
    headers = dict(source.headers)
    if (not _text(headers.get('currency'), facts.currency)
            or not _date(headers.get('as_of'), facts.as_of)
            or not _date(headers.get('period_end'), facts.as_of)
            or not _amount(headers.get('closing_cash'), facts.cash, facts.currency)):
        return unavailable
    opening = headers.get('opening_cash')
    if facts.opening_cash is not None:
        if not _amount(opening, facts.opening_cash, facts.currency):
            return unavailable
    elif opening is not None:
        return unavailable
    period = headers.get('period_start')
    if not _supported(period):
        return unavailable
    start = parse_date(period.raw, 'en-US')
    if not start.ok or start.value > facts.as_of or len(source.rows) != len(facts.activity):
        return unavailable
    rows = [dict(record) for record in source.rows]
    pages_by_identity = {}
    identities = []
    for row, activity in zip(rows, facts.activity):
        if (not _activity_matches(row, activity, facts)
                or not start.value <= (activity.date or facts.as_of) <= facts.as_of):
            return unavailable
        identity = (activity.date or facts.as_of, activity.kind, activity.amount,
                    activity.instrument, activity.realized_gain)
        identities.append(identity)
        pages_by_identity.setdefault(identity, set()).add(_page(row.get('amount'), count))
    return tuple(next(iter(pages_by_identity[key]))
                 if len(pages_by_identity[key]) == 1 and None not in pages_by_identity[key]
                 else None for key in identities)


def payroll_decomposition_page(facts):
    source = facts.payroll_source
    count = _bounded_source(facts, source)
    if count is None:
        return None
    headers = dict(source.headers)
    if (not _text(headers.get('currency'), facts.currency)
            or not _date(headers.get('pay_date'), facts.pay_date)
            or not _amount(headers.get('gross'), facts.gross, facts.currency)
            or not _amount(headers.get('net'), facts.net, facts.currency)
            or len(source.deductions) != len(facts.deductions)):
        return None
    for record, deduction in zip(source.deductions, facts.deductions):
        row = dict(record)
        if (not _text(row.get('label'), deduction.label)
                or not _text(row.get('category'), deduction.category)
                or not _amount(row.get('amount'), deduction.amount, facts.currency)):
            return None
    return _page(headers.get('gross'), count)
