"""Independent versioned source literals with explicit numeric-term dependencies."""
from dataclasses import dataclass,asdict
from datetime import date
import json

from .instrument_contracts import Source, ContractError

FIELDS = frozenset({'status', 'context'})
APR_FIELD_LABELS={'status':'Disclosure apr status','context':'Disclosure apr basis'}
REASONS = frozenset({'historical_absence','not_printed','invalid_context','source_unavailable',
    'source_limit','unsupported_representation','ambiguous_association','literal_mismatch','numeric_terms_unavailable'})


def text(value, maximum, *, ascii_only=False):
    if type(value) is not str or not value or len(value.encode('utf-8')) > maximum:
        raise ContractError('invalid bounded APR text')
    if ascii_only and (not value.isascii() or not value.isprintable()):
        raise ContractError('invalid APR identity')
    return value


def iso(value):
    if type(value) is not str or date.fromisoformat(value).isoformat() != value:
        raise ContractError('invalid APR effective date')
    return value


@dataclass(frozen=True)
class GroundedSpan:
    span_id: int
    start: int
    end: int
    box: tuple[str, ...]
    text: str

    def __post_init__(self):
        import math
        if (type(self.span_id) is not int or not 0<=self.span_id<512 or type(self.start) is not int or type(self.end) is not int
                or not 0<=self.start<self.end<=32768 or type(self.box) is not tuple or len(self.box)!=4
                or any(type(v) is not str or len(v)>32 or not math.isfinite(float(v)) for v in self.box)
                or float(self.box[0])>=float(self.box[2]) or float(self.box[1])>=float(self.box[3])):
            raise ContractError('invalid grounded APR geometry')
        text(self.text,4096)
        if len(self.text)!=self.end-self.start:raise ContractError('APR measured range/text mismatch')


@dataclass(frozen=True)
class GroundingReceipt:
    grammar_version: str
    page_digest: str
    identity_span: int
    numeric_apr_span: int | None
    field_label_span: int
    value_spans: tuple[int, ...]
    block_spans: tuple[int, ...]
    grounder_version: str = 'apr-local-v1'
    document_id: str = ''
    page: int = 1
    numeric_terms_observation_id: str = ''
    measured_spans: tuple[GroundedSpan, ...] = ()

    def __post_init__(self):
        if self.grounder_version != 'apr-local-v1' or self.grammar_version != 'apr-labelled-record-v1':
            raise ContractError('unknown APR grounding version')
        if type(self.page_digest) is not str or len(self.page_digest) != 64 or any(c not in '0123456789abcdef' for c in self.page_digest):
            raise ContractError('invalid APR page digest')
        scalar = (self.identity_span, self.field_label_span)
        if self.numeric_apr_span is not None:
            scalar += (self.numeric_apr_span,)
        if any(type(v) is not int or not 0 <= v < 512 for v in scalar):
            raise ContractError('invalid APR span identity')
        for values in (self.value_spans, self.block_spans):
            if (type(values) is not tuple or not values or len(values) > 256 or len(set(values)) != len(values)
                    or any(type(v) is not int or not 0 <= v < 512 for v in values)):
                raise ContractError('invalid APR measured spans')
        if not set((*scalar, *self.value_spans)) <= set(self.block_spans):
            raise ContractError('APR spans cross their record block')
        if type(self.page) is not int or not 1<=self.page<=200 or type(self.document_id) is not str or type(self.numeric_terms_observation_id) is not str:
            raise ContractError('invalid grounded APR source identity')
        if type(self.measured_spans) is not tuple or len(self.measured_spans)>256 or any(type(v) is not GroundedSpan for v in self.measured_spans):
            raise ContractError('invalid grounded APR measurements')
        previous_end=-1
        for span in self.measured_spans:
            if span.start<previous_end:raise ContractError('APR measured receipt order mismatch')
            previous_end=span.end
        if self.measured_spans and {s.span_id for s in self.measured_spans}!=set(self.block_spans):
            raise ContractError('APR receipt measured block mismatch')
        if len(json.dumps(self.to_dict(), ensure_ascii=False).encode()) > 8192:
            raise ContractError('APR grounding resource limit')

    def to_dict(self):
        return json.loads(json.dumps(asdict(self),ensure_ascii=False))


@dataclass(frozen=True)
class AprContextResult:
    disposition: str
    value: str | None = None
    source: Source | None = None
    grounding: GroundingReceipt | None = None
    reason: str | None = None
    conflicts: tuple[str, ...] = ()

    def __post_init__(self):
        if self.disposition == 'accepted':
            text(self.value, 2048)
            if type(self.source) is not Source or type(self.grounding) is not GroundingReceipt or self.reason is not None or self.conflicts:
                raise ContractError('accepted APR context requires source grounding')
        elif self.disposition == 'unavailable':
            if self.reason not in REASONS or any(v is not None for v in (self.value,self.source,self.grounding)) or self.conflicts:
                raise ContractError('invalid unavailable APR context')
        elif self.disposition == 'conflicted':
            if (any(v is not None for v in (self.value,self.source,self.grounding,self.reason))
                    or type(self.conflicts) is not tuple or not 2 <= len(self.conflicts) <= 8
                    or len(set(self.conflicts)) != len(self.conflicts)):
                raise ContractError('invalid APR conflicts')
            for v in self.conflicts:
                text(v,128,ascii_only=True)
        else:
            raise ContractError('unknown APR disposition')


@dataclass(frozen=True)
class AprContextPayload:
    """Payload for the ordinary authenticated instrument observation frontier."""
    schema_version: int
    loan_id: str
    numeric_terms_observation_id: str
    effective_date: str
    field: str
    result: AprContextResult
    capture_id: str
    document_id: str

    def __post_init__(self):
        for value in (self.loan_id,self.numeric_terms_observation_id,self.capture_id,self.document_id):
            text(value,256)
        iso(self.effective_date)
        if type(self.schema_version) is not int or self.schema_version!=1 or self.field not in FIELDS or type(self.result) is not AprContextResult:
            raise ContractError('invalid apr_context_v1 payload')
        if self.result.disposition=='conflicted':
            raise ContractError('conflict is projected, never stored as source interpretation')
        if self.result.disposition=='accepted':
            text(self.result.value,256 if self.field=='status' else 2048)
            receipt=self.result.grounding
            if (self.result.source.doc_id!=self.document_id or receipt.document_id!=self.document_id
                    or receipt.page!=self.result.source.page or receipt.numeric_terms_observation_id!=self.numeric_terms_observation_id
                    or not receipt.measured_spans):
                raise ContractError('APR grounding dependency mismatch')
            measured={span.span_id:span for span in receipt.measured_spans}
            first=measured[receipt.field_label_span]
            label,delimiter,value=first.text.partition(':')
            if delimiter!=':' or label!=APR_FIELD_LABELS[self.field] or receipt.value_spans[0]!=receipt.field_label_span:
                raise ContractError('APR measured field mismatch')
            retained=value.lstrip(' \t')+''.join('\n'+measured[index].text for index in receipt.value_spans[1:])
            if retained!=self.result.value:raise ContractError('APR retained literal mismatch')
