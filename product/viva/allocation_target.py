"""Complete positive target-role grammars, invoked after semantic selection."""
from dataclasses import dataclass
import calendar
from datetime import date
import re

_PERCENT=r"(?:0|[1-9][0-9]{0,2})(?:\.[0-9]{1,12})?"
_TARGET=rf"(?P<role>(?:my|the)\s+(?P<number>{_PERCENT})\s*(?P<unit>%|percent)\s+target)"
_EXPOSURE=r"(?P<exposure>bond|equity|cash|other)"
_DATE=r"(?P<date>[A-Za-z]+\s+[0-9]{4}|[0-9]{4}-[0-9]{2}-[0-9]{2})"
_FOR=r"(?P<account>[^?\r\n]{1,256}?)"
_FIRST=re.compile(rf"How\s+far\s+is\s+my\s+{_EXPOSURE}\s+allocation\s+from\s+{_TARGET}(?:\s+for\s+{_FOR})?(?:\s+as\s+of\s+{_DATE})?\?",re.I)
_SECOND=re.compile(rf"(?:For\s+{_FOR},\s+)?What\s+is\s+the\s+percentage-point\s+difference\s+between\s+(?:actual|my)\s+{_EXPOSURE}\s+allocation\s+and\s+{_TARGET}(?:\s+(?:at|as\s+of)\s+{_DATE})?\?(?:\s+Retain\s+that\s+account\s+and\s+date\.)?",re.I)
_MONTHS={name.casefold():i for i,name in enumerate(calendar.month_name) if name}
_CONTINUATION=frozenset(('the active retirement plan from the last allocation answer','the account from the last allocation answer'))

@dataclass(frozen=True)
class ParsedAllocationTarget:
    question: str
    exposure: str
    target_numerator: int
    target_denominator: int
    percent_unit: str
    target_role_span: tuple[int,int]
    exposure_span: tuple[int,int]
    target_role_text: str
    exposure_text: str
    account_text: str | None
    account_span: tuple[int,int] | None
    as_of: str | None
    date_text: str | None
    date_span: tuple[int,int] | None
    month_end_derived: bool
    continuation_reference: bool


def parse_allocation_target(question):
    if type(question) is not str or not question or len(question.encode('utf-8'))>2048:
        raise ValueError('allocation target question exceeds its bound')
    match=_FIRST.fullmatch(question) or _SECOND.fullmatch(question)
    if match is None:
        raise ValueError('clarify the intended allocation target comparison')
    literal=match['number'];role=match['role'];account=match.groupdict().get('account');date_text=match.groupdict().get('date')
    if len(literal.encode())>32 or len(role.encode())>64 or (account and len(account.encode())>256):
        raise ValueError('allocation target source span exceeds its bound')
    if account and any(c in account for c in ('"','“','”','‘','’',';','?')):
        raise ValueError('invalid allocation account source span')
    whole,_,fraction=literal.partition('.')
    scale=10**len(fraction);numerator=int(whole)*scale+(int(fraction) if fraction else 0);denominator=100*scale
    if numerator>denominator:
        raise ValueError('allocation target must lie between zero and a hundred percent')
    derived=False;as_of=None
    if date_text:
        if re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}",date_text):
            as_of=date.fromisoformat(date_text).isoformat()
        else:
            month_text,year_text=re.split(r"\s+",date_text);month=_MONTHS.get(month_text.casefold());year=int(year_text)
            if month is None or not 1<=year<=9999:
                raise ValueError('clarify the allocation snapshot date')
            as_of=date(year,month,calendar.monthrange(year,month)[1]).isoformat();derived=True
    normalized=' '.join(account.casefold().split()) if account else ''
    return ParsedAllocationTarget(question,match['exposure'].casefold(),numerator,denominator,
        match['unit'].casefold(),match.span('role'),match.span('exposure'),role,match['exposure'],
        account,match.span('account') if account else None,as_of,date_text,match.span('date') if date_text else None,
        derived,normalized in _CONTINUATION)
