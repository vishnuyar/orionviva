"""Finite meanings shared by instrument authority, capability and answer binding.

This module supplies vocabulary and immutable contracts, never evidence authority.
Only the instrument read and the run-owned evidence graph may attest its claims.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import date
from types import MappingProxyType

@dataclass(frozen=True)
class ClaimContract:
    quantity: str = ""
    render_type: str = ""
    reference_kind: str = "figure"
    value_type: str = "number"
    allowed_values: tuple[str, ...] = ()
    max_bytes: int = 0
    direction: str = ""

_CLAIMS = {}
def _number(names, quantity, render_type="money", *, direction=""):
    for name in names.split():
        _CLAIMS[name] = ClaimContract(quantity, render_type, direction=direction)
_number("deposit_contract_principal", "deposit_contract_principal")
_number("loan_original_principal", "loan_original_principal")
_number("deposit_nominal_rate loan_note_rate loan_disclosure_apr", "instrument_rate", "rate")
_number("deposit_opening_balance deposit_closing_balance escrow_opening_balance escrow_closing_balance allocation_total_value allocation_unclassified_value", "balance")
_number("loan_opening_principal loan_closing_principal refinance_old_zero", "owed")
_number("principal_repayment principal_payoff payment_principal", "repayment")
INTERNAL_ONLY_CLAIMS = frozenset(("payment_principal",))
_number("payment_interest payment_fees tax_paid refinance_fees", "spending")
_number("payment_net_unallocated", "net_movement")
_number("deposit_credited_interest", "income")
_number("payment_total escrow_funding deposit_redemption refinance_old_payoff refinance_borrower_contribution", "gross_flow", direction="outflow")
_number("deposit_funding refinance_new_advance refinance_cash_out", "gross_flow", direction="inflow")
_number("refinance_financed_costs", "gross_flow", direction="financed")
_number("loan_term_months", "count", "count")
for _axis, _values in (("exposure", ("bond", "equity", "cash", "other", "unknown")),
                       ("vehicle", ("mutual_fund", "etf", "individual_security", "other", "unknown"))):
    for _value in _values:
        _number(f"allocation_{_axis}_{_value}_value", "balance")
        _number(f"allocation_{_axis}_{_value}_weight", "ratio_of_balance", "rate")
_number("allocation_percentage_points", "allocation_percentage_points", "percentage_points")
for _name in ("deposit_opened", "deposit_maturity", "loan_originated", "loan_maturity", "settlement_date", "payment_date", "tax_payment_date", "redemption_date"):
    _CLAIMS[_name] = ClaimContract(render_type="date", reference_kind="instrument_date", value_type="date")
for _name in ("deposit_compounding", "deposit_withdrawal_restriction", "escrow_withdrawal_restriction", "property_identity"):
    _CLAIMS[_name] = ClaimContract(render_type="instrument_text", reference_kind="instrument_text", value_type="literal_text", max_bytes=256)
for _name in ("payment_reference", "tax_payment_reference", "settlement_reference", "redemption_reference", "refinance_old_account_reference", "refinance_new_account_reference"):
    _CLAIMS[_name] = ClaimContract(render_type="instrument_text", reference_kind="instrument_text", value_type="literal_text", max_bytes=128)
for _name, _values in (("deposit_rate_basis", ("simple_nominal", "nominal_compounded", "effective_apy", "unknown")),
                       ("loan_note_rate_basis", ("simple_nominal", "nominal_compounded", "effective_apy", "unknown")),
                       ("deposit_day_count", ("actual_365", "actual_360", "equal_monthly_12", "unknown")),
                       ("availability_restriction", ("restricted_term_deposit", "restricted_escrow"))):
    _CLAIMS[_name] = ClaimContract(render_type="instrument_normalized", reference_kind="instrument_normalized", value_type="enum", allowed_values=_values)
_CLAIMS["loan_fixed_rate"] = ClaimContract(render_type="instrument_normalized", reference_kind="instrument_normalized", value_type="boolean")
# The separately approved APR amendment supplies structural grounding, never enums.
for _name, _bound in (("disclosure_apr_status", 256), ("disclosure_apr_context", 2048)):
    _CLAIMS[_name] = ClaimContract(render_type="instrument_text", reference_kind="instrument_text", value_type="literal_text", max_bytes=_bound)
INVESTMENT_CLAIMS = frozenset(("security_units", "holding_cost_basis", "investment_contribution", "investment_dividend", "sale_proceeds", "disposed_cost_basis", "realized_gain", "investment_market_value", "investment_holdings_count"))
for _q in INVESTMENT_CLAIMS:
    _number(_q, "balance" if _q=="investment_market_value" else "count" if _q=="investment_holdings_count" else _q, "security_units" if _q=="security_units" else "count" if _q=="investment_holdings_count" else "money")
MORTGAGE_DERIVED_CLAIMS=frozenset(('payment_net_unallocated',))
RETIREMENT_CLAIMS=frozenset(('employee_retirement_contributions','direct_rollover_amount','rollover_source_outflow','rollover_destination_inflow','rollover_checking_receipts','rollover_attributed_income','rollover_date','rollover_reference','rollover_source_account','rollover_destination_account'))
_number('employee_retirement_contributions direct_rollover_amount','investment_contribution')
_number('rollover_source_outflow','gross_flow',direction='outflow')
_number('rollover_destination_inflow rollover_checking_receipts','gross_flow',direction='inflow')
_number('rollover_attributed_income','income')
_CLAIMS['rollover_date']=ClaimContract(render_type='date',reference_kind='instrument_date',value_type='date')
for _name in ('rollover_reference','rollover_source_account','rollover_destination_account'):
    _CLAIMS[_name]=ClaimContract(render_type='instrument_text',reference_kind='instrument_text',value_type='literal_text',max_bytes=256)
CLAIMS = MappingProxyType(_CLAIMS)
from .quantity import DEDICATED
DEDICATED_QUANTITIES = frozenset(DEDICATED)


def bounded_id(value, label, *, ascii_only=True, limit=128):
    if (type(value) is not str or not value or len(value.encode("utf-8")) > limit
            or (ascii_only and any(ord(c) < 32 or ord(c) > 126 for c in value))):
        raise ValueError(f"invalid {label}")
    return value


@dataclass(frozen=True)
class ResolvedTargetPremise:
    receipt_id: str
    question_id: str
    account: str
    currency: str
    exposure: str
    as_of: str
    target_numerator: int
    target_denominator: int
    target_role_span: tuple[int, int]
    exposure_span: tuple[int, int]
    target_role_text: str
    exposure_text: str
    percent_unit: str
    continuation_receipt_id: str = ""
    dependencies: tuple[str, ...] = ()

    def __post_init__(self):
        for name in ("receipt_id", "question_id", "account"):
            bounded_id(getattr(self, name), name)
        if type(self.currency) is not str or len(self.currency) != 3 or not self.currency.isascii() or not self.currency.isupper() or not self.currency.isalpha():
            raise ValueError("invalid premise currency")
        if self.exposure not in ("bond", "equity", "cash", "other"):
            raise ValueError("invalid premise exposure")
        if type(self.as_of) is not str or date.fromisoformat(self.as_of).isoformat() != self.as_of:
            raise ValueError("invalid premise date")
        n, d = self.target_numerator, self.target_denominator
        if type(n) is not int or type(d) is not int or d <= 0 or not 0 <= n <= d or max(n.bit_length(), d.bit_length()) > 512:
            raise ValueError("invalid bounded premise rational")
        for span in (self.target_role_span, self.exposure_span):
            if type(span) is not tuple or len(span) != 2 or any(type(i) is not int for i in span) or not 0 <= span[0] < span[1] <= 2048:
                raise ValueError("invalid premise source span")
        if type(self.target_role_text) is not str or not self.target_role_text or len(self.target_role_text.encode("utf-8")) > 64:
            raise ValueError("invalid premise target-role text")
        if type(self.exposure_text) is not str or not self.exposure_text or len(self.exposure_text.encode("utf-8")) > 32:
            raise ValueError("invalid premise exposure text")
        if self.percent_unit not in ("%", "percent"):
            raise ValueError("invalid premise percent unit")
        if self.continuation_receipt_id:
            bounded_id(self.continuation_receipt_id, "continuation receipt")
        if type(self.dependencies) is not tuple or len(self.dependencies) > 120:
            raise ValueError("invalid premise dependencies")
        for dependency in self.dependencies:
            bounded_id(dependency, "premise dependency")


_NORMALIZED_WORDS = MappingProxyType({
    "simple_nominal":"Simple nominal rate", "nominal_compounded":"Nominal compounded rate",
    "effective_apy":"Effective annual percentage yield", "unknown":"Unknown convention",
    "actual_365":"Actual days over 365", "actual_360":"Actual days over 360",
    "equal_monthly_12":"Twelve equal contractual months",
    "restricted_term_deposit":"Restricted term deposit", "restricted_escrow":"Restricted escrow",
})

def normalized_words(claim,value):
    contract=CLAIMS.get(claim)
    if contract is None or contract.reference_kind!='instrument_normalized':
        raise ValueError('unknown normalized instrument claim')
    if contract.value_type=='boolean':
        if type(value) is not bool:raise ValueError('normalized boolean type mismatch')
        return 'Fixed rate' if value else 'Not fixed rate'
    if type(value) is not str or value not in contract.allowed_values:
        raise ValueError('normalized enum type mismatch')
    return _NORMALIZED_WORDS[value]


CLAIM_RELATIONSHIPS = MappingProxyType({
    'refinance_old_payoff':'refinance_old_loan',
    'refinance_old_zero':'refinance_old_loan',
    'refinance_old_account_reference':'refinance_old_loan',
})

def selected_subject(figure,entity_ref):
    if set(entity_ref)=={'account_set_id','set_type','member_ids'}:
        return {key:(figure.get('subject') or {}).get(key) for key in entity_ref}==entity_ref and entity_ref.get('set_type')=='retirement_plans'
    if set(entity_ref)=={'id','security_id'}:
        return (figure.get('subject') or {}).get('account_id')==entity_ref['id'] and (figure.get('subject') or {}).get('security_id')==entity_ref['security_id']
    if set(entity_ref)=={'id'}:
        return (figure.get('subject') or {}).get('account_id')==entity_ref['id']
    if set(entity_ref)=={'role'}:
        return (CLAIM_RELATIONSHIPS.get(figure.get('claim'))==entity_ref['role']
            and figure.get('instrument_relationship')==entity_ref['role'])
    return False
