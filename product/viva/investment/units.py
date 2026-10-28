"""Faithful bounded nonnegative security quantities without Decimal rounding."""
from decimal import Decimal
from .contracts import EvidenceError,decimal

class UnsupportedUnits(EvidenceError): pass
class UnitsFormatLimit(EvidenceError): pass

def units(value,group_separator=',',decimal_separator='.'):
 try: number=decimal(value)
 except EvidenceError as e: raise UnsupportedUnits(str(e)) from e
 if number.is_zero(): return '0'
 sign,digits,exponent=number.as_tuple();digits=list(digits)
 while digits and digits[-1]==0: digits.pop();exponent+=1
 integer_count=max(1,len(digits)+exponent);fraction_count=max(0,-exponent)
 if integer_count>18 or fraction_count>12: raise UnsupportedUnits('security quantity digit bound')
 raw=''.join(map(str,digits))
 if exponent>=0: raw+='0'*exponent
 elif len(raw)+exponent>0: raw=raw[:exponent]+'.'+raw[exponent:]
 else: raw='0.'+'0'*(-exponent-len(raw))+raw
 if len(raw)>31: raise UnitsFormatLimit('canonical units length')
 if (group_separator,decimal_separator) not in ((',','.'),('.',','),(' ',','),('', '.')): raise UnitsFormatLimit('unsupported units locale')
 integer,sep,fraction=raw.partition('.')
 if group_separator:
  chunks=[]
  while integer: chunks.append(integer[-3:]);integer=integer[:-3]
  integer=group_separator.join(reversed(chunks))
 result=integer+(decimal_separator+fraction if sep else '')
 if len(result)>40 or len(result.encode('utf-8'))>40: raise UnitsFormatLimit('localized units length')
 return result
