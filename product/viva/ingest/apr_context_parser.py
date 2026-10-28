"""Closed local candidates contain measured references, never model authority."""
from dataclasses import dataclass
from .apr_context_contracts import FIELDS,text
from .instrument_contracts import ContractError


@dataclass(frozen=True)
class LocalAprCandidate:
    field: str
    value: str
    page: int
    label_span: int
    value_spans: tuple[int,...]

    def __post_init__(self):
        if self.field not in FIELDS or type(self.page) is not int or not 1<=self.page<=200:
            raise ContractError('invalid APR candidate field/page')
        text(self.value,256 if self.field=='status' else 2048)
        if (type(self.label_span) is not int or not 0<=self.label_span<512
                or type(self.value_spans) is not tuple or not 1<=len(self.value_spans)<=9
                or len(set(self.value_spans))!=len(self.value_spans)
                or any(type(v) is not int or not 0<=v<512 for v in self.value_spans)):
            raise ContractError('invalid local measured spans')
