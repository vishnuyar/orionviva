"""Source-only investment extraction extension. No model input grants acceptance."""
from dataclasses import dataclass
from .contracts import EvidenceError,text,canonical,ROLES

@dataclass(frozen=True)
class SourceField:
 raw: str
 page: int | None
 def __post_init__(self):
  text(self.raw,2048,True)
  if self.page is not None and (type(self.page) is not int or not 1<=self.page<=200):raise EvidenceError('invalid investment source page')
 def to_dict(self):return {'raw':self.raw,'page':self.page}


@dataclass(frozen=True)
class FundingRoleSourceField(SourceField):
 role: str='unknown'
 def __post_init__(self):
  super().__post_init__()
  if self.role not in ROLES:raise EvidenceError('invalid normalized source funding role')
 def to_dict(self):return {**super().to_dict(),'role':self.role}


def source_field(value):
 if value is None:return None
 if type(value) is not dict or set(value)!={'raw','page'}:raise EvidenceError('source fields accept only raw and page')
 return SourceField(**value)

HEADERS=('account_reference','currency','period_start','period_end','as_of','opening_cash','closing_cash','activity_complete','no_activity')
POSITION=('identifier','label','units','market_value','cost_basis')
ROW=('printed_row_reference','date','kind','amount','security_identifier','reported_realized_gain','printed_reference','counterpart_reference','funding_role')

def source_record(data,names,*,normalized_role=False):
 if type(data) is not dict or set(data)!=set(names):raise EvidenceError('closed investment extraction record required')
 def convert(name,value):
  if normalized_role and name=='funding_role' and value is not None:
   if type(value) is not dict or set(value)!={'raw','page','role'}:raise EvidenceError('closed normalized source funding role required')
   return FundingRoleSourceField(**value)
  return source_field(value)
 return tuple((name,convert(name,data[name])) for name in names)

@dataclass(frozen=True)
class InvestmentSource:
 headers: tuple
 positions: tuple
 rows: tuple
 schema: str='investment-source-v1'
 def to_dict(self):
  def record(values):return {k:v.to_dict() if v is not None else None for k,v in values}
  return {'schema':self.schema,'headers':record(self.headers),'positions':[record(p) for p in self.positions],'rows':[record(r) for r in self.rows]}


def parse(data):
 if data is None:return None
 if type(data) is not dict or set(data)!={'schema','headers','positions','rows'} or data['schema'] not in ('investment-source-v1','investment-source-v2'):raise EvidenceError('unsupported investment extraction schema')
 if type(data['positions']) is not list or len(data['positions'])>20:raise EvidenceError('investment position source bound')
 if type(data['rows']) is not list or len(data['rows'])>1000:raise EvidenceError('investment activity source bound')
 if len(canonical(data))>262144:raise EvidenceError('investment extraction byte bound')
 return InvestmentSource(source_record(data['headers'],HEADERS),tuple(source_record(p,POSITION) for p in data['positions']),tuple(source_record(r,ROW,normalized_role=data['schema']=='investment-source-v2') for r in data['rows']),data['schema'])
