"""JSON fast frontier encoding preserves every old byte/type/error boundary."""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import Enum
from pathlib import Path
import json,hashlib
import pytest
from viva.ledger.events import Event
from viva.investment.events import prefix,_json_primitives
from viva.investment.contracts import canonical

class TextEnum(str,Enum):VALUE='source'
class IntEnum(int,Enum):VALUE=1
class DictSubclass(dict):pass
class TextSubclass(str):pass
@dataclass
class Typed:
 amount:Decimal
 label:str

@pytest.mark.parametrize('value',[None,True,False,0,10,-2,0.0,-0.0,1e20,'é😀\n\\"',[],(),[1,{'nested':[None,True,'']},('a','b')],{'currency':'USD','amount':'0.00'},Decimal('1.20'),date(2025,1,1),Typed(Decimal('1.20'),'typed'),TextEnum.VALUE,IntEnum.VALUE,DictSubclass(amount='1'),TextSubclass('raw'),{1:'integer-key'},{None:'null-key'},{('tuple',):'bad-key'},{'set':{1,2}},set(),frozenset(),float('nan'),float('inf'),float('-inf'),b'bytes'])
def test_prefix_bytes_and_exact_failure_class_match_original_canonical(value):
 events=(Event('SourceProbe','2025-01-01',{'value':value},event_id='source-probe'),)
 try:expected=canonical(tuple(e.to_dict() for e in events))
 except Exception as error:
  with pytest.raises(type(error)):prefix(events)
 else:
  assert prefix(events).prefix_digest==hashlib.sha256(expected).hexdigest()
  if _json_primitives(tuple(e.to_dict() for e in events)):
   assert json.dumps(tuple(e.to_dict() for e in events),sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()==expected


def test_true_pre_payroll_committed_event_prefixes_keep_historical_digests():
 data=json.loads((Path(__file__).parent/'fixtures/investment/pre-payroll-investment-v1-events.json').read_text());events=tuple(Event.from_dict(item) for item in data)
 for count in range(len(events)+1):
  selected=events[:count];assert prefix(selected).prefix_digest==hashlib.sha256(canonical(tuple(event.to_dict() for event in selected))).hexdigest()
