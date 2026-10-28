"""Immutable local instrument read contracts; none confers model authority."""
from dataclasses import dataclass, asdict
from datetime import date
import json
from ..instrument_claims import CLAIMS, bounded_id
from ..ingest.apr_context_contracts import GroundingReceipt


def iso(value):
    if type(value) is not str or date.fromisoformat(value).isoformat() != value:
        raise ValueError('invalid instrument date')
    return value


def ids(values):
    if type(values) is not tuple or not values or len(values) > 512 or len(set(values)) != len(values):
        raise ValueError('invalid instrument lineage')
    for value in values:
        bounded_id(value,'instrument lineage',limit=256)


@dataclass(frozen=True)
class InstrumentRequest:
    view: str
    account: str
    currency: str
    as_of: str | None = None
    start: str | None = None
    end: str | None = None
    grouping: str | None = None
    component_set: str | None = None
    axis: str | None = None
    target_premise_ref: str | None = None

    def __post_init__(self):
        bounded_id(self.account,'instrument account')
        if type(self.currency) is not str or len(self.currency) != 3 or not self.currency.isascii() or not self.currency.isalpha() or not self.currency.isupper():
            raise ValueError('invalid instrument currency')
        if self.view in {'terms','maturities','allocation'}:
            iso(self.as_of)
            if any(v is not None for v in (self.start,self.end,self.grouping,self.component_set)):
                raise ValueError('unexpected point-in-time request field')
        elif self.view in {'period_components','refinances','tax_payments'}:
            iso(self.start); iso(self.end)
            if self.start > self.end or (date.fromisoformat(self.end)-date.fromisoformat(self.start)).days >= 3660 or self.as_of is not None:
                raise ValueError('invalid instrument period')
        else:
            raise ValueError('unknown instrument view')
        if self.view == 'period_components':
            if self.grouping not in {'none','month','year'} or self.component_set not in {'deposit','loan_principal','payment_escrow','annual_summary'}:
                raise ValueError('unsupported instrument components')
            if self.component_set == 'annual_summary' and self.grouping != 'year':
                raise ValueError('annual summary requires year grouping')
        elif self.component_set is not None:
            raise ValueError('unexpected component set')
        if self.view == 'tax_payments' and self.grouping not in {'none','year'}:
            raise ValueError('unsupported tax grouping')
        if self.view == 'refinances' and self.grouping is not None:
            raise ValueError('unexpected refinance grouping')
        if self.grouping in {'month','year'}:
            first,last=date.fromisoformat(self.start),date.fromisoformat(self.end)
            groups=(last.year-first.year)*12+last.month-first.month+1 if self.grouping=='month' else last.year-first.year+1
            if groups>(12 if self.grouping=='month' else 10):raise ValueError('instrument grouping resource_limit')
        if self.view == 'allocation':
            if self.axis not in {'exposure','vehicle'} or (self.target_premise_ref is not None and self.axis != 'exposure'):
                raise ValueError('unsupported allocation axis')
            if self.target_premise_ref is not None:
                bounded_id(self.target_premise_ref,'target premise')
        elif self.axis is not None or self.target_premise_ref is not None:
            raise ValueError('unexpected allocation field')

    @classmethod
    def from_dict(cls, body):
        if type(body) is not dict:
            raise ValueError('instrument request must be an object')
        base = {'view','account','currency'}
        fields = {'terms':{'as_of'},'maturities':{'as_of'},'allocation':{'as_of','axis'},
            'period_components':{'from','to','grouping','component_set'},'refinances':{'from','to'},
            'tax_payments':{'from','to','grouping'}}
        required = base | fields.get(body.get('view'),set())
        allowed = required | ({'target_premise_ref'} if body.get('view') == 'allocation' else set())
        if not required <= set(body) or set(body) - allowed:
            raise ValueError('instrument request has missing or unknown keys')
        values = {('start' if k == 'from' else 'end' if k == 'to' else k):v for k,v in body.items()}
        return cls(**values)


@dataclass(frozen=True)
class AuthorityAnchor:
    anchor_id: str
    document_id: str
    page: int

    def __post_init__(self):
        bounded_id(self.anchor_id,'anchor')
        bounded_id(self.document_id,'document',limit=256)
        if type(self.page) is not int or self.page < 1:
            raise ValueError('invalid instrument source page')


@dataclass(frozen=True)
class AuthorityNumeric:
    record_id: str
    claim: str
    value: str
    account: str
    currency: str | None
    as_of: str | None
    start: str | None
    end: str | None
    anchor_ids: tuple[str,...]
    observation_ids: tuple[str,...]
    component_ids: tuple[str,...]
    grade: str | None
    exact: bool = True
    direction: str | None = None
    premise_ref: str | None = None
    operand_ids: tuple[str,...] = ()
    record_association: str | None = None
    calculation_context: str | None = None

    def __post_init__(self):
        if self.calculation_context is not None:
            tax=(self.calculation_context=='accepted_empty_tax_event_set_v1' and self.claim=='tax_paid'
                and self.value=='0' and self.start is not None and self.end is not None and self.exact)
            payment=(self.calculation_context=='printed_payment_net_residual_v1' and self.claim=='payment_net_unallocated'
                and self.value=='0' and self.exact and self.as_of is not None and self.record_association is not None
                and len(self.operand_ids)==4 and len(set(self.operand_ids))==4)
            if not (tax or payment):
                raise ValueError('invalid closed instrument calculation context')
        bounded_id(self.record_id,'numeric record')
        if self.record_association is not None:bounded_id(self.record_association,'accepted event association')
        if self.claim not in CLAIMS or CLAIMS[self.claim].value_type != 'number':
            raise ValueError('undeclared numeric instrument claim')
        bounded_id(self.account,'numeric account')
        if type(self.value) is not str or not self.value or len(self.value) > 128 or not self.value.isascii():
            raise ValueError('invalid instrument numeric value')
        ids(self.anchor_ids); ids(self.observation_ids)
        if type(self.component_ids) is not tuple or len(self.component_ids) > 120:
            raise ValueError('invalid instrument components')
        if self.as_of is not None:
            iso(self.as_of)
        if self.start is not None or self.end is not None:
            iso(self.start); iso(self.end)
        if self.claim == 'allocation_percentage_points':
            if self.grade is not None or self.premise_ref is None or not self.operand_ids:
                raise ValueError('point difference requires user premise and actual operands')
        elif self.grade not in {'verified','corroborated','unverified','conflicted'}:
            raise ValueError('instrument figure needs actual evidence grade')
        if self.direction != (CLAIMS[self.claim].direction or None):
            raise ValueError('instrument direction mismatch')

    @property
    def quantity(self):
        return CLAIMS[self.claim].quantity


@dataclass(frozen=True)
class AuthorityAssertion:
    receipt_id: str
    claim: str
    value: str | bool
    account: str
    effective_date: str
    anchor_ids: tuple[str,...]
    observation_ids: tuple[str,...]
    component_ids: tuple[str,...]
    grade: str
    numeric_terms_observation_id: str | None = None
    grounding: GroundingReceipt | None = None
    record_association: str | None = None

    def __post_init__(self):
        bounded_id(self.receipt_id,'assertion')
        if self.record_association is not None:bounded_id(self.record_association,'accepted event association')
        contract = CLAIMS.get(self.claim)
        if contract is None or contract.value_type == 'number':
            raise ValueError('undeclared sourced assertion')
        bounded_id(self.account,'assertion account'); iso(self.effective_date)
        ids(self.anchor_ids); ids(self.observation_ids)
        if contract.value_type == 'boolean':
            if type(self.value) is not bool:
                raise ValueError('boolean assertion type mismatch')
        elif type(self.value) is not str or not self.value:
            raise ValueError('sourced string required')
        elif contract.value_type == 'date':
            iso(self.value)
        elif contract.value_type == 'enum' and self.value not in contract.allowed_values:
            raise ValueError('unknown normalized source value')
        elif contract.value_type == 'literal_text' and len(self.value.encode('utf-8')) > contract.max_bytes:
            raise ValueError('source literal exceeds bound')
        if self.grade not in {'verified','corroborated','unverified','conflicted'}:
            raise ValueError('assertion evidence grade required')
        if self.claim in {'disclosure_apr_status','disclosure_apr_context'} and (self.numeric_terms_observation_id is None or self.grounding is None):
            raise ValueError('APR assertion requires independent grounding')


@dataclass(frozen=True)
class AuthorityDisposition:
    component: str
    disposition: str
    observation_ids: tuple[str,...] = ()
    reason: str = ''

    def __post_init__(self):
        if self.disposition not in {'accepted','held','unavailable','conflicted','resource_limit'}:
            raise ValueError('unknown authority disposition')
        if type(self.reason) is not str or len(self.reason.encode()) > 2048:
            raise ValueError('unbounded authority disposition')


@dataclass(frozen=True)
class AuthorityCoverage:
    start: str
    end: str
    complete: bool
    periods: tuple[tuple[str,str],...] = ()


@dataclass(frozen=True)
class AuthorityFocus:
    account: str
    currency: str
    snapshot_date: str
    axis: str
    exposure: str | None = None


@dataclass(frozen=True)
class AuthorityRelationship:
    role: str
    account: str
    anchor_ids: tuple[str,...]
    observation_ids: tuple[str,...]
    effective_date: str

    def __post_init__(self):
        if self.role not in {'redemption_receiving_account','refinance_old_loan','refinance_new_loan'}:
            raise ValueError('unknown instrument relationship role')
        bounded_id(self.account,'related canonical account')
        ids(self.anchor_ids);ids(self.observation_ids);iso(self.effective_date)


@dataclass(frozen=True)
class InstrumentAuthorityResult:
    request: InstrumentRequest
    revision: str
    figures: tuple[AuthorityNumeric,...] = ()
    assertions: tuple[AuthorityAssertion,...] = ()
    anchors: tuple[AuthorityAnchor,...] = ()
    dispositions: tuple[AuthorityDisposition,...] = ()
    coverage: tuple[AuthorityCoverage,...] = ()
    selection_dependencies: tuple[str,...] = ()
    focus: AuthorityFocus | None = None
    relationships: tuple[AuthorityRelationship,...] = ()

    def __post_init__(self):
        if type(self.request) is not InstrumentRequest or type(self.revision) is not str:
            raise ValueError('invalid instrument result identity')
        for name,kind,limit in (('figures',AuthorityNumeric,80),('assertions',AuthorityAssertion,120),
                ('anchors',AuthorityAnchor,512),('dispositions',AuthorityDisposition,120),('coverage',AuthorityCoverage,120),('relationships',AuthorityRelationship,20)):
            values = getattr(self,name)
            if type(values) is not tuple or len(values) > limit or any(type(v) is not kind for v in values):
                raise ValueError('instrument result resource_limit')
        anchors = {a.anchor_id for a in self.anchors}
        if len(anchors) != len(self.anchors) or any(not set(r.anchor_ids) <= anchors for r in (*self.figures,*self.assertions,*self.relationships)):
            raise ValueError('instrument pooled source mismatch')
        if len(json.dumps(asdict(self),ensure_ascii=False,separators=(',',':')).encode('utf-8')) > 50000:
            raise ValueError('instrument result resource_limit')
