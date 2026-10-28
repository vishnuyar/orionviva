"""Closed accepted investment source evidence; model JSON never grants a grade."""
from dataclasses import dataclass, fields, is_dataclass
from datetime import date
from decimal import Decimal
from hashlib import sha256
import json
import math
import re

QUANTITIES=('security_units','holding_cost_basis','investment_contribution','investment_dividend','sale_proceeds','disposed_cost_basis','realized_gain')
KINDS=('contribution','withdrawal','dividend','interest','fee','buy','sell')
ROLES=('own_bank','other_broker','retirement_rollover','external_party','reinvestment','unknown')
GRADES=('verified','corroborated','unverified','conflicted')
DISPOSITIONS=('accepted_complete_nonempty','accepted_complete_empty','held','incomplete','conflicted')

class EvidenceError(ValueError):
 pass

class ResourceLimit(EvidenceError):
 pass

def text(value, limit=256, empty=False):
 if type(value) is not str or (not value and not empty) or len(value.encode('utf-8'))>limit or any(ord(c)<32 for c in value):
  raise EvidenceError('invalid bounded source text')
 return value

def day(value):
 if type(value) is not str or len(value)!=10:
  raise EvidenceError('invalid source date')
 try: parsed=date.fromisoformat(value)
 except ValueError: raise EvidenceError('invalid source date') from None
 if parsed.isoformat()!=value: raise EvidenceError('noncanonical source date')
 return value

def decimal(value, signed=False):
 if type(value) is str:
  if len(value)>64 or re.fullmatch(r'[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)',value.strip()) is None:
   raise EvidenceError('invalid decimal source')
  value=Decimal(value.strip())
 elif type(value) is int: value=Decimal(value)
 elif type(value) is not Decimal: raise EvidenceError('unsupported decimal source')
 if not value.is_finite() or (not signed and value<0): raise EvidenceError('invalid finite source magnitude')
 sign,digits,exponent=value.as_tuple()
 if len(digits)>48 or exponent < -24 or exponent>18: raise EvidenceError('decimal source resource limit')
 return value

def encode(value):
 if is_dataclass(value):
  # Optional new payroll evidence must not rewrite old cash-witness bodies.
  return {f.name:encode(getattr(value,f.name)) for f in fields(value) if not ((type(value) is FundingWitness and f.name=='payroll_dependency' and value.payroll_dependency is None) or (type(value).__module__=='viva.investment.payroll' and type(value).__name__=='PayrollDependency' and f.name=='net_deposit_date' and value.net_deposit_date is None))}
 if type(value) is Decimal: return str(value)
 if type(value) in (tuple,list): return [encode(v) for v in value]
 if type(value) is dict: return {k:encode(v) for k,v in value.items()}
 if type(value) is float and math.isfinite(value):return value
 if value is None or type(value) in (str,int,bool): return value
 raise EvidenceError('unsupported storage value')

def canonical(value):
 return json.dumps(encode(value),sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode('utf-8')

def digest(value): return sha256(canonical(value)).hexdigest()

@dataclass(frozen=True)
class Field:
 value: str
 document: str
 page: int | None
 grade: str='unverified'
 status: str='accepted'
 anchor: str=''
 raw: str=''
 def __post_init__(self):
  text(self.value,2048,True);text(self.document);text(self.anchor,256,True);text(self.raw,2048,True)
  if self.page is None:
   if self.status=='accepted':raise EvidenceError('missing accepted field page')
  elif type(self.page) is not int or not 1<=self.page<=200:raise EvidenceError('invalid field page')
  if self.grade not in GRADES or self.status not in ('accepted','unavailable','conflicted'): raise EvidenceError('invalid field disposition')
  if self.status=='accepted' and self.grade=='conflicted': raise EvidenceError('conflicted field cannot be accepted')

@dataclass(frozen=True)
class FundingWitness:
 reference: Field
 counterpart_reference: Field
 counterpart_account: str
 role: str
 transaction_id: str
 transaction_digest: str
 source_row_event_id: str=""
 payroll_dependency: "PayrollDependency | None"=None
 def __post_init__(self):
  if self.role not in ROLES: raise EvidenceError('unknown funding role')
  for value in (self.counterpart_account,self.transaction_id,self.transaction_digest): text(value)
  text(self.source_row_event_id,256,True)
  if self.payroll_dependency is not None:
   from .payroll import PayrollDependency
   if type(self.payroll_dependency) is not PayrollDependency or self.role!='external_party':raise EvidenceError('typed payroll dependency requires external-party branch')
  if len(self.transaction_digest)!=64: raise EvidenceError('invalid funding dependency digest')

@dataclass(frozen=True)
class Row:
 observation_id: str
 local_id: str
 ordinal: int
 date: Field
 kind: Field
 amount: Field
 instrument: Field | None
 realized_gain: Field | None
 cash_event_id: str
 cash_body_digest: str
 description: str=''
 printed_reference: Field | None=None
 namespace: Field | None=None
 funding_role: str='unknown'
 funding_reference: Field | None=None
 counterpart_reference: Field | None=None
 funding_witness: FundingWitness | None=None
 funding_role_source: Field | None=None
 funding_status: str="unavailable"
 def __post_init__(self):
  for v in (self.observation_id,self.local_id,self.cash_event_id,self.cash_body_digest): text(v)
  text(self.description,2048,True)
  if type(self.ordinal) is not int or not 0<=self.ordinal<1000: raise EvidenceError('invalid source ordinal')
  if self.funding_status not in ('accepted','unavailable','conflicted'): raise EvidenceError('invalid funding disposition')
  if self.kind.value not in KINDS or self.funding_role not in ROLES: raise EvidenceError('invalid row kind or role')
  day(self.date.value)
  if decimal(self.amount.value)<=0: raise EvidenceError('activity amount must be positive')
  if self.realized_gain is not None and self.realized_gain.status=="accepted": decimal(self.realized_gain.value,True)
  if len(self.cash_body_digest)!=64: raise EvidenceError('invalid cash body digest')
  if (self.printed_reference is None)!=(self.namespace is None): raise EvidenceError('reference namespace missing')

@dataclass(frozen=True)
class Position:
 security_id: str
 identifier: Field
 units: Field
 value: Field
 basis: Field | None
 label: Field | None=None
 position_event_id: str=""
 position_body_digest: str=""
 def __post_init__(self):
  text(self.security_id);text(self.position_event_id,256,True);text(self.position_body_digest,256,True)
  if bool(self.position_event_id)!=bool(self.position_body_digest):raise EvidenceError("incomplete position dependency")
  if self.position_body_digest and len(self.position_body_digest)!=64:raise EvidenceError("invalid position dependency digest")
  if self.units.status=='accepted':decimal(self.units.value,True)
  if self.value.status=='accepted':decimal(self.value.value)
  if self.basis is not None and self.basis.status=='accepted':decimal(self.basis.value)

@dataclass(frozen=True)
class Statement:
 observation_id: str
 account: Field
 currency: Field
 start: Field
 end: Field
 opening_cash: Field
 closing_cash: Field
 rows: tuple[Row,...]
 disposition: str
 explicit_empty: Field | None=None
 printed_reference: Field | None=None
 positions: tuple[Position,...]=()
 snapshot_complete: bool=False
 corroborates: str | None=None
 as_of: Field | None=None
 def __post_init__(self):
  text(self.observation_id);text(self.account.value)
  if self.corroborates is not None:text(self.corroborates)
  if re.fullmatch('[A-Z]{3}',self.currency.value) is None: raise EvidenceError('invalid currency')
  day(self.start.value);day(self.end.value)
  if self.as_of is not None:day(self.as_of.value)
  if self.start.value>self.end.value: raise EvidenceError('inverted source period')
  if self.opening_cash.status=="accepted":decimal(self.opening_cash.value)
  if self.closing_cash.status=="accepted":decimal(self.closing_cash.value)
  if self.disposition not in DISPOSITIONS or type(self.snapshot_complete) is not bool: raise EvidenceError('invalid statement disposition')
  if type(self.rows) is not tuple or type(self.positions) is not tuple: raise EvidenceError('source collections must be immutable')
  if len(self.rows)>1000 or len(self.positions)>20: raise ResourceLimit('source row/position limit')
  if len({r.local_id for r in self.rows})!=len(self.rows) or len({r.observation_id for r in self.rows})!=len(self.rows): raise EvidenceError('duplicate local row identity')
  if len({r.ordinal for r in self.rows})!=len(self.rows): raise EvidenceError('duplicate source ordinal')
  if any(not self.start.value<=r.date.value<=self.end.value for r in self.rows): raise EvidenceError('row outside source period')
  if len({p.security_id for p in self.positions})!=len(self.positions): raise EvidenceError('duplicate security identity')

@dataclass(frozen=True)
class Request:
 view: str
 account: str
 currency: str
 as_of: str | None=None
 start: str | None=None
 end: str | None=None
 grouping: str | None=None
 def __post_init__(self):
  text(self.account)
  if re.fullmatch('[A-Z]{3}',self.currency) is None: raise EvidenceError('invalid request currency')
  if self.view=='positions':
   day(self.as_of)
   if any(x is not None for x in (self.start,self.end,self.grouping)): raise EvidenceError('unexpected point request field')
  elif self.view=='activity_totals':
   day(self.start);day(self.end)
   if self.start>self.end or self.as_of is not None or self.grouping not in ('year','none'): raise EvidenceError('invalid activity interval')
   if (date.fromisoformat(self.end)-date.fromisoformat(self.start)).days>=3660: raise ResourceLimit('interval limit')
   if self.grouping=='year' and int(self.end[:4])-int(self.start[:4])+1>10: raise ResourceLimit('group limit')
  else: raise EvidenceError('unknown investment view')
 @classmethod
 def from_dict(cls,data):
  if type(data) is not dict: raise EvidenceError('object required')
  keys={'view','account','currency','as_of'} if data.get('view')=='positions' else {'view','account','currency','from','to','grouping'}
  if set(data)!=keys: raise EvidenceError('missing or extra investment argument')
  values=dict(data)
  if 'from' in values: values['start']=values.pop('from');values['end']=values.pop('to')
  return cls(**values)


def security_identity(account,source_identifier):
 text(account);text(source_identifier)
 return digest(("investment-security-v1",account,source_identifier))
