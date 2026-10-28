"""Bounded delivered-answer selection receipts; prose never establishes focus."""
from collections import OrderedDict
from dataclasses import dataclass,asdict
from datetime import date
import hashlib
import json
import secrets
from .instrument_claims import bounded_id

VERSION="allocation-continuation-v1"

@dataclass(frozen=True)
class RecoveryAnchor:
    version: str
    turn_id: str
    answer_id: str

    def __post_init__(self):
        if self.version != VERSION:
            raise ValueError('unknown continuation recovery version')
        bounded_id(self.turn_id,'recovery turn');bounded_id(self.answer_id,'recovery answer')

    @classmethod
    def from_dict(cls,value):
        if type(value) is not dict or set(value)!={'version','turn_id','answer_id'}:
            raise ValueError('invalid closed continuation recovery anchor')
        return cls(**value)

@dataclass(frozen=True)
class SelectionManifest:
    version: str
    turn_id: str
    answer_id: str
    account: str
    currency: str
    snapshot_date: str
    axis: str
    exposure: str | None
    revision: str
    dependencies: tuple[str,...]
    source_commitment: str
    binding_identity: str

    def __post_init__(self):
        if self.version != VERSION:
            raise ValueError('unsupported selection manifest')
        for name in ('turn_id','answer_id','account','revision'):
            bounded_id(getattr(self,name),name)
        if type(self.currency) is not str or len(self.currency)!=3 or not self.currency.isascii() or not self.currency.isalpha() or not self.currency.isupper():
            raise ValueError('invalid selection currency')
        if type(self.snapshot_date) is not str or date.fromisoformat(self.snapshot_date).isoformat()!=self.snapshot_date:
            raise ValueError('invalid selected snapshot date')
        if self.axis not in ('exposure','vehicle') or self.exposure not in (None,'bond','equity','cash','other','unknown'):
            raise ValueError('invalid selected allocation focus')
        if type(self.dependencies) is not tuple or not self.dependencies or len(self.dependencies)>120 or len(set(self.dependencies))!=len(self.dependencies):
            raise ValueError('invalid selection dependencies')
        for value in self.dependencies:bounded_id(value,'selection dependency',limit=256)
        for value in (self.source_commitment,self.binding_identity):
            if type(value) is not str or len(value)!=64 or any(c not in '0123456789abcdef' for c in value):
                raise ValueError('invalid allocation selection commitment')
        if len(json.dumps(self.to_dict(),sort_keys=True,separators=(',',':'),ensure_ascii=False).encode('utf-8'))>4096:
            raise ValueError('allocation selection receipt exceeds bound')

    def to_dict(self):
        return {**asdict(self),'dependencies':list(self.dependencies)}

    @classmethod
    def from_dict(cls,value):
        names=set(cls.__dataclass_fields__)
        if type(value) is not dict or set(value)!=names or type(value.get('dependencies')) is not list:
            raise ValueError('invalid closed selection manifest')
        return cls(**{**value,'dependencies':tuple(value['dependencies'])})

@dataclass(frozen=True)
class DeliveredSelection:
    receipt_id: str
    vault_id: str
    session_id: str
    manifest: SelectionManifest


class DeliveredAllocationRegistry:
    def __init__(self,vault_id,session_id=None):
        self.vault_id=bounded_id(vault_id,'active vault')
        self.session_id=bounded_id(session_id or secrets.token_hex(16),'active session')
        self._answers=OrderedDict()
        self._receipts={}

    def reset(self):
        self._answers.clear();self._receipts.clear()
        self.session_id=secrets.token_hex(16)

    def issue_delivered(self,manifests,*,turn_id,answer_id,delivered,validate):
        if delivered is not True or type(manifests) is not tuple or not 1<=len(manifests)<=4:
            raise ValueError('selection requires one successfully delivered bounded answer')
        bounded_id(turn_id,'delivered turn');bounded_id(answer_id,'delivered answer')
        if any(type(m) is not SelectionManifest or m.turn_id!=turn_id or m.answer_id!=answer_id for m in manifests):
            raise ValueError('selection answer/turn mismatch')
        key=(turn_id,answer_id)
        if key in self._answers:
            existing=tuple(self._receipts[r].manifest for r in self._answers[key])
            if existing!=manifests:
                raise ValueError('duplicate answer identity with conflicting selection')
            if any(not validate(m) for m in manifests):
                self._evict(key);raise ValueError('selection evidence no longer available')
            return self._answers[key]
        if any(not validate(m) for m in manifests):
            raise ValueError('selection dependencies no longer available')
        ids=[]
        for manifest in manifests:
            rid=secrets.token_urlsafe(24)
            if rid in self._receipts or rid in ids:
                raise ValueError('duplicate continuation receipt identity')
            record=DeliveredSelection(rid,self.vault_id,self.session_id,manifest)
            # Bounds cover the complete runtime receipt, not just its saved body.
            if len(json.dumps(asdict(record),sort_keys=True,separators=(',',':')).encode())>4096:
                raise ValueError('complete allocation receipt exceeds bound')
            ids.append(rid)
        # All validation/size checks precede atomic registry insertion.
        for rid,manifest in zip(ids,manifests):self._receipts[rid]=DeliveredSelection(rid,self.vault_id,self.session_id,manifest)
        self._answers[key]=tuple(ids)
        while len(self._answers)>8:self._evict(next(iter(self._answers)))
        return tuple(ids)

    def _evict(self,key):
        for rid in self._answers.pop(key,()):self._receipts.pop(rid,None)

    def resolve(self,receipt_id,*,vault_id,session_id,validate):
        bounded_id(receipt_id,'continuation receipt')
        record=self._receipts.get(receipt_id)
        if record is None or vault_id!=self.vault_id or session_id!=self.session_id or record.vault_id!=vault_id or record.session_id!=session_id:
            raise ValueError('allocation continuation is unavailable in this context')
        if not validate(record.manifest):
            self._evict((record.manifest.turn_id,record.manifest.answer_id))
            raise ValueError('allocation continuation dependencies changed')
        return record

    def eligible_ids(self):
        return tuple(rid for records in self._answers.values() for rid in records)

    def recover(self,anchor,*,load,validate):
        if type(anchor) is not RecoveryAnchor:
            raise ValueError('recovery requires an explicit validated anchor')
        # The authenticated bounded eligible-answer index supplies exactly this answer.
        record=load(anchor.turn_id,anchor.answer_id)
        if type(record) is not tuple or not record or any(type(m) is not SelectionManifest for m in record):
            raise ValueError('saved allocation selection is unavailable')
        return self.issue_delivered(record,turn_id=anchor.turn_id,answer_id=anchor.answer_id,delivered=True,validate=validate)


def source_commitment(result):
    focus=asdict(result.focus) if result.focus is not None else None
    if focus is not None:focus["exposure"]=None
    value={"focus":focus,
        "figures":[asdict(f) for f in result.figures if f.claim!='allocation_percentage_points'],
        "anchors":[asdict(a) for a in result.anchors],"dependencies":list(result.selection_dependencies)}
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()


def validate_selection(manifest,revision,*,deadline):
    from .read_store.instrument_authority_contracts import InstrumentRequest
    from .read_store.instrument_authority import read_instrument_authority
    if type(manifest) is not SelectionManifest:return False
    try:
        revision._store.authenticated_source_identity(revision)
        request=InstrumentRequest('allocation',manifest.account,manifest.currency,as_of=manifest.snapshot_date,axis=manifest.axis)
        current=read_instrument_authority(revision,request,deadline=deadline)
        return (current.focus is not None and current.focus.account==manifest.account
            and current.focus.snapshot_date==manifest.snapshot_date
            and current.focus.currency==manifest.currency and current.focus.axis==manifest.axis
            and tuple(current.selection_dependencies)==manifest.dependencies
            and source_commitment(current)==manifest.source_commitment)
    except (ValueError,TypeError,KeyError):return False
