"""Run-local instrument authority seals; serialized figures are never authority."""
from __future__ import annotations
import hashlib
import hmac
import json
import secrets
from .instrument_claims import CLAIMS

_KEY = secrets.token_bytes(32)
_MINT = object()


def _digest(figure):
    # Run IDs are assigned after emission. All semantic/source fields are sealed.
    data={key:value for key,value in figure.items() if key != "id"}
    return hmac.digest(_KEY,json.dumps(data,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False).encode("utf-8"),"sha256")


class _InstrumentFigure(dict):
    def __init__(self, value, mint, run_token):
        if mint is not _MINT:
            raise ValueError("instrument seals are issued only by the local authority")
        super().__init__(value)
        self._proof = _digest(self)
        self._run_token = run_token


def _attest_figure(figure, claim, *, run_token):
    """Internal adapter seam, called only after a typed accepted authority read."""
    contract=CLAIMS.get(claim)
    if contract is None or contract.value_type != "number" or figure.get("quantity") != contract.quantity:
        raise ValueError("instrument figure claim/quantity mismatch")
    if not figure.get("record_ids") or not figure.get("subject") or not figure.get("boundary"):
        raise ValueError("instrument figures require source, subject and scope")
    if contract.quantity == "allocation_percentage_points":
        if figure.get("kind") != "hypothetical" or figure.get("grade"):
            raise ValueError("allocation target comparison is hypothetical without a grade")
    elif figure.get("kind") != "financial" or figure.get("grade") not in {"verified","corroborated","unverified","conflicted"}:
        raise ValueError("instrument source figure requires actual evidence grade")
    return _InstrumentFigure({**figure,"claim":claim}, _MINT, run_token)


def authenticated_figure(figure):
    if type(figure) is not _InstrumentFigure:
        return False
    try:
        contract=CLAIMS.get(figure.get("claim"))
        return (contract is not None and figure.get("quantity")==contract.quantity
                and hmac.compare_digest(figure._proof,_digest(figure)))
    except (ValueError,TypeError,AttributeError):
        return False


class _InstrumentAssertion(dict):
    def __init__(self,value,mint,run_token):
        if mint is not _MINT:raise ValueError('untrusted instrument assertion')
        super().__init__(value);self._proof=_digest(self);self._run_token=run_token


def _attest_assertion(value, *, run_token):
    from datetime import date
    claim=value.get('claim');contract=CLAIMS.get(claim)
    if contract is None or contract.value_type=='number' or value.get('value_type')!=contract.value_type:
        raise ValueError('unknown assertion claim or incompatible type')
    actual=value.get('value')
    if contract.value_type=='boolean':
        if type(actual) is not bool:raise ValueError('normalized boolean must remain boolean')
    elif type(actual) is not str:raise ValueError('source assertion requires its typed value')
    elif contract.value_type=='enum' and actual not in contract.allowed_values:raise ValueError('unknown normalized assertion')
    elif contract.value_type=='date' and date.fromisoformat(actual).isoformat()!=actual:raise ValueError('invalid source date')
    elif contract.value_type=='literal_text' and (not actual or len(actual.encode('utf-8'))>contract.max_bytes):raise ValueError('source literal exceeds bound')
    if not value.get('account') or not value.get('anchors') or not value.get('observation_ids') or value.get('grade') not in {'verified','corroborated','unverified','conflicted'}:
        raise ValueError('assertion lacks actual source evidence')
    if value.get('disposition')!='accepted':raise ValueError('unaccepted source assertion')
    return _InstrumentAssertion(value,_MINT,run_token)


def authenticated_assertion(value):
    try:return type(value) is _InstrumentAssertion and hmac.compare_digest(value._proof,_digest(value))
    except (ValueError,TypeError,AttributeError):return False


class _InstrumentPremise(dict):
    def __init__(self,value,mint,run_token):
        if mint is not _MINT:raise ValueError('untrusted allocation premise')
        super().__init__(value);self._proof=_digest(self);self._run_token=run_token


def _attest_premise(premise,question,*,run_token):
    from dataclasses import asdict
    from .instrument_claims import ResolvedTargetPremise
    if type(premise) is not ResolvedTargetPremise:raise ValueError('target role proof is unavailable')
    a,b=premise.target_role_span;c,d=premise.exposure_span
    if question[a:b]!=premise.target_role_text or question[c:d]!=premise.exposure_text:
        raise ValueError('target premise belongs to another question')
    return _InstrumentPremise({**asdict(premise),'id':'','claim':'allocation_target',
        'kind':'user_stated','question_digest':hashlib.sha256(question.encode()).hexdigest()},_MINT,run_token)


def authenticated_premise(value,question):
    try:return (type(value) is _InstrumentPremise and hmac.compare_digest(value._proof,_digest(value))
        and value['question_digest']==hashlib.sha256(question.encode()).hexdigest())
    except (ValueError,TypeError,AttributeError,KeyError):return False


from dataclasses import dataclass
@dataclass(frozen=True)
class SourceAssertionGroup:
    assertion_ids: tuple[str,...]
    claim: str
    account: str
    reference_kind: str
    run_token: object

    def __post_init__(self):
        if type(self.assertion_ids) is not tuple or not 1<=len(self.assertion_ids)<=80 or len(set(self.assertion_ids))!=len(self.assertion_ids):raise ValueError("source assertion group resource_limit")
        c=CLAIMS.get(self.claim)
        if c is None or c.value_type=="number" or c.reference_kind!=self.reference_kind or not self.account:raise ValueError("invalid source assertion group")
