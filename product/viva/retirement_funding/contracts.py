"""Closed selections for recorded retirement funding, never financial accounts."""
from dataclasses import dataclass
from datetime import date
import re
from viva.investment.contracts import EvidenceError, day, digest, text

TOOL = 'read_retirement_funding'
ANNUAL = 'annual_employee_contributions'
ROLLOVERS = 'direct_rollovers'
NUMERIC_CLAIMS = {'employee_retirement_contributions': 'investment_contribution',
                  'direct_rollover_amount': 'investment_contribution',
                  'rollover_source_outflow': 'gross_flow',
                  'rollover_destination_inflow': 'gross_flow',
                  'rollover_checking_receipts': 'gross_flow',
                  'rollover_attributed_income': 'income'}
ASSERTION_CLAIMS = {'rollover_date': 'instrument_date',
                    'rollover_reference': 'instrument_text',
                    'rollover_source_account': 'instrument_text',
                    'rollover_destination_account': 'instrument_text'}

@dataclass(frozen=True)
class Request:
    view: str
    plans: tuple[str, ...]
    currency: str
    year: int | None = None
    start: str | None = None
    end: str | None = None

    def __post_init__(self):
        if type(self.plans) is not tuple or not 1 <= len(self.plans) <= 3:
            raise EvidenceError('select one to three canonical retirement plans')
        if len(set(self.plans)) != len(self.plans):
            raise EvidenceError('duplicate selected plan')
        for plan in self.plans:
            text(plan)
        if re.fullmatch('[A-Z]{3}', self.currency or '') is None:
            raise EvidenceError('invalid selected currency')
        if self.view == ANNUAL:
            if type(self.year) is not int or not 1 <= self.year <= 9998 or self.start is not None or self.end is not None:
                raise EvidenceError('select one calendar year')
        elif self.view == ROLLOVERS:
            if self.year is not None:
                raise EvidenceError('unexpected annual selection')
            day(self.start); day(self.end)
            if not 0 <= (date.fromisoformat(self.end) - date.fromisoformat(self.start)).days < 3660:
                raise EvidenceError('invalid selected rollover interval')
        else:
            raise EvidenceError('unknown retirement funding view')

    @property
    def beginning(self):
        return f'{self.year:04d}-01-01' if self.view == ANNUAL else self.start

    @property
    def ending(self):
        return f'{self.year:04d}-12-31' if self.view == ANNUAL else self.end

    @property
    def subject_id(self):
        return 'retirement-set:' + digest(('retirement_plans', sorted(self.plans)))

    @property
    def subject(self):
        return {'account_set_id': self.subject_id, 'set_type': 'retirement_plans', 'member_ids': sorted(self.plans)}

    @classmethod
    def from_dict(cls, value):
        if type(value) is not dict:
            raise EvidenceError('closed retirement request required')
        expected = {'view', 'plans', 'currency', 'year'} if value.get('view') == ANNUAL else {'view', 'plans', 'currency', 'from', 'to'}
        if set(value) != expected or type(value.get('plans')) is not list:
            raise EvidenceError('closed retirement selection required')
        args = dict(value); args['plans'] = tuple(args['plans'])
        if 'from' in args:
            args['start'] = args.pop('from'); args['end'] = args.pop('to')
        return cls(**args)


def valid_subject(subject):
    if type(subject) is not dict or set(subject) not in ({'account_set_id','set_type','member_ids'},{'account_set_id','set_type','member_ids','relationship_id','source_account_id','destination_account_id'}):
        raise EvidenceError('closed retirement subject required')
    members=subject['member_ids']
    if type(members) is not list or members!=sorted(members):
        raise EvidenceError('sorted canonical retirement members required')
    expected=Request(ANNUAL,tuple(members),'USD',year=2000).subject
    if {key:subject[key] for key in expected}!=expected:
        raise EvidenceError('retirement selected set identity differs')
    if 'relationship_id' in subject:
        if subject['source_account_id'] not in members or subject['destination_account_id'] not in members or subject['source_account_id']==subject['destination_account_id']:
            raise EvidenceError('retirement relationship endpoints differ from selected plans')
        relationship=subject['relationship_id']
        if type(relationship) is not str or re.fullmatch('retirement-rollover:[0-9a-f]{64}',relationship) is None:
            raise EvidenceError('invalid retirement relationship identity')
    return True
