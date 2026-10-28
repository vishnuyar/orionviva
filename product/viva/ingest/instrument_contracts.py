"""Closed source facts for instrument readers; no ledger mutation or model calls.

These contracts are deliberately inactive until their projectors and read
boundaries exist. Reconciliation accepts printed components independently.
"""
from __future__ import annotations

from dataclasses import dataclass, fields
from datetime import date
from decimal import Decimal
from enum import Enum
import types
from typing import Union, get_args, get_origin, get_type_hints

from vivacore.verify.arithmetic import CheckResult, check_balance_identity


class ContractError(ValueError):
    """A source record cannot be normalized without inventing facts."""


def _matches_type(value, annotation):
    origin, arguments = get_origin(annotation), get_args(annotation)
    if origin in (Union, types.UnionType):
        return any(_matches_type(value, option) for option in arguments)
    if origin is tuple:
        return (type(value) is tuple and len(arguments) == 2 and arguments[1] is Ellipsis
                and all(_matches_type(item, arguments[0]) for item in value))
    return type(value) is annotation


class ClosedFact:
    """Enforce the same immutable field contract at every constructor boundary."""

    def __post_init__(self):
        annotations = get_type_hints(type(self))
        for field in fields(self):
            if not _matches_type(getattr(self, field.name), annotations[field.name]):
                raise ContractError(f"{type(self).__name__}.{field.name} has the wrong closed type: {annotations[field.name]}")


@dataclass(frozen=True)
class Source(ClosedFact):
    doc_id: str
    page: int

    def __post_init__(self):
        super().__post_init__()
        if not isinstance(self.doc_id, str) or not self.doc_id.strip():
            raise ContractError("source document is required")
        if type(self.page) is not int or self.page < 1:
            raise ContractError("source page must be a positive integer")


@dataclass(frozen=True)
class Money(ClosedFact):
    value: Decimal
    currency: str
    source: Source

    def __post_init__(self):
        super().__post_init__()
        if not isinstance(self.value, Decimal) or not self.value.is_finite():
            raise ContractError("money must be a finite Decimal")
        if not isinstance(self.currency, str) or not self.currency.strip():
            raise ContractError("currency is required")
        if not isinstance(self.source, Source):
            raise ContractError("money source is required")


@dataclass(frozen=True)
class SourcedDate(ClosedFact):
    value: str
    source: Source

    def __post_init__(self):
        super().__post_init__()
        try:
            if date.fromisoformat(self.value).isoformat() != self.value:
                raise ValueError
        except (TypeError, ValueError):
            raise ContractError("date must be an ISO calendar date") from None
        if not isinstance(self.source, Source):
            raise ContractError("date source is required")


@dataclass(frozen=True)
class SourcedText(ClosedFact):
    value: str
    source: Source

    def __post_init__(self):
        super().__post_init__()
        if not isinstance(self.value, str) or not self.value.strip():
            raise ContractError("printed text is required")
        if not isinstance(self.source, Source):
            raise ContractError("text source is required")


@dataclass(frozen=True)
class Rate(ClosedFact):
    percent: Decimal
    source: Source

    def __post_init__(self):
        super().__post_init__()
        if (not isinstance(self.percent, Decimal) or not self.percent.is_finite()
                or self.percent < 0 or not isinstance(self.source, Source)):
            raise ContractError("rate must be a sourced nonnegative Decimal percent")


@dataclass(frozen=True)
class AccountIdentity(ClosedFact):
    institution: SourcedText
    account_reference: SourcedText
    holder: SourcedText


class RateBasis(str, Enum):
    SIMPLE_NOMINAL = "simple_nominal"
    NOMINAL_COMPOUNDED = "nominal_compounded"
    EFFECTIVE_APY = "effective_apy"
    UNKNOWN = "unknown"


class DayCount(str, Enum):
    ACT_365 = "actual_365"
    ACT_360 = "actual_360"
    EQUAL_MONTHLY_12 = "equal_monthly_12"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class DepositTerms(ClosedFact):
    principal: Money
    opened: SourcedDate
    maturity: SourcedDate
    rate: Rate | None = None
    rate_basis: RateBasis = RateBasis.UNKNOWN
    day_count: DayCount = DayCount.UNKNOWN
    compounding: SourcedText | None = None
    withdrawal_restriction: SourcedText | None = None
    rate_basis_source: Source | None = None
    day_count_source: Source | None = None

    def calculation_issue(self):
        if self.principal.value < 0:
            return "invalid_principal"
        if self.rate_basis != RateBasis.SIMPLE_NOMINAL:
            return "unsupported_rate_basis"
        if (self.rate is None or self.day_count == DayCount.UNKNOWN
                or self.rate_basis_source is None or self.day_count_source is None):
            return "incomplete_rate_convention"
        if self.maturity.value < self.opened.value:
            return "invalid_term_dates"
        return ""


class DepositKind(str, Enum):
    FUNDING = "funding"
    INTEREST = "interest_credit"
    REDEMPTION = "redemption"
    FEE = "fee"


@dataclass(frozen=True)
class DepositMovement(ClosedFact):
    kind: DepositKind
    amount: Money
    dated: SourcedDate
    reference: SourcedText
    counterparty_reference: SourcedText | None = None

    def __post_init__(self):
        super().__post_init__()
        if self.amount.value <= 0:
            raise ContractError("flow row must have a positive magnitude")


class DepositSubtype(str, Enum):
    OPENING = "opening"
    PERIODIC = "periodic"
    MATURITY = "maturity"


@dataclass(frozen=True)
class DepositFacts(ClosedFact):
    identity: AccountIdentity
    subtype: DepositSubtype
    start: SourcedDate | None = None
    end: SourcedDate | None = None
    opening: Money | None = None
    closing: Money | None = None
    movements: tuple[DepositMovement, ...] | None = None
    terms: DepositTerms | None = None
    uncredited_interest: Money | None = None


@dataclass(frozen=True)
class MortgageTerms(ClosedFact):
    original_principal: Money | None = None
    originated: SourcedDate | None = None
    fixed_rate: bool | None = None
    note_rate: Rate | None = None
    note_rate_basis: RateBasis = RateBasis.UNKNOWN
    disclosure_apr: Rate | None = None
    term_months: int | None = None
    maturity: SourcedDate | None = None
    fixed_rate_source: Source | None = None
    note_rate_basis_source: Source | None = None
    term_months_source: Source | None = None

    def __post_init__(self):
        super().__post_init__()
        if self.term_months is not None and self.term_months <= 0:
            raise ContractError("printed term must be positive")

    def calculation_issue(self):
        if self.original_principal is None:
            return "original_principal_required"
        if self.originated is None:
            return "origination_date_required"
        if self.original_principal.value <= 0:
            return "invalid_principal"
        if self.maturity is not None and self.maturity.value < self.originated.value:
            return "invalid_term_dates"
        if self.fixed_rate is not True or self.fixed_rate_source is None:
            return "fixed_rate_required"
        if (self.note_rate is None or self.note_rate_basis != RateBasis.SIMPLE_NOMINAL
                or self.note_rate_basis_source is None):
            return "nominal_note_rate_required"
        if (type(self.term_months) is not int or self.term_months <= 0
                or self.term_months_source is None):
            return "term_required"
        return ""


class PrincipalKind(str, Enum):
    ADVANCE = "advance"
    REDUCTION = "principal_reduction"
    PAYOFF = "payoff"
    INCREASE_ADJUSTMENT = "increase_adjustment"
    DECREASE_ADJUSTMENT = "decrease_adjustment"


@dataclass(frozen=True)
class PrincipalMovement(ClosedFact):
    kind: PrincipalKind | None = None
    amount: Money | None = None
    dated: SourcedDate | None = None
    reference: SourcedText | None = None

    def __post_init__(self):
        super().__post_init__()
        if self.amount is not None and self.amount.value <= 0:
            raise ContractError("flow row must have a positive magnitude")


@dataclass(frozen=True)
class PaymentComponents(ClosedFact):
    dated: SourcedDate | None = None
    reference: SourcedText | None = None
    principal: Money | None = None
    interest: Money | None = None
    escrow: Money | None = None
    fees: Money | None = None
    total: Money | None = None
    funding_account_reference: SourcedText | None = None


class EscrowKind(str, Enum):
    DEPOSIT = "deposit"
    TAX = "tax_disbursement"
    INSURANCE = "insurance_disbursement"
    INCREASE_ADJUSTMENT = "increase_adjustment"
    DECREASE_ADJUSTMENT = "decrease_adjustment"


@dataclass(frozen=True)
class EscrowMovement(ClosedFact):
    kind: EscrowKind | None = None
    amount: Money | None = None
    dated: SourcedDate | None = None
    reference: SourcedText | None = None
    property_reference: SourcedText | None = None
    tax_year: int | None = None

    def __post_init__(self):
        super().__post_init__()
        if self.amount is not None and self.amount.value <= 0:
            raise ContractError("flow row must have a positive magnitude")
        if self.tax_year is not None and not 1 <= self.tax_year <= 9999:
            raise ContractError("tax year must be a calendar year")


@dataclass(frozen=True)
class EscrowFacts(ClosedFact):
    identity: AccountIdentity | None = None
    opening: Money | None = None
    closing: Money | None = None
    movements: tuple[EscrowMovement, ...] | None = None
    continuity_reference: SourcedText | None = None
    withdrawal_restriction: SourcedText | None = None


@dataclass(frozen=True)
class MortgageFacts(ClosedFact):
    identity: AccountIdentity
    start: SourcedDate
    end: SourcedDate
    opening_principal: Money | None = None
    closing_principal: Money | None = None
    principal_movements: tuple[PrincipalMovement, ...] | None = None
    payments: tuple[PaymentComponents, ...] | None = None
    terms: MortgageTerms | None = None
    escrow: EscrowFacts | None = None


@dataclass(frozen=True)
class ClosingFee(ClosedFact):
    label: SourcedText
    amount: Money


@dataclass(frozen=True)
class RefinanceFacts(ClosedFact):
    dated: SourcedDate
    reference: SourcedText
    old_loan: AccountIdentity
    new_loan: AccountIdentity
    old_payoff_principal: Money
    new_funded_principal: Money
    borrower_contribution: Money
    cash_out: Money
    financed_costs: Money
    fees: tuple[ClosingFee, ...]
    total_fees: Money
    old_closing_principal: Money | None = None
    new_terms: MortgageTerms | None = None
    fee_payment_reference: SourcedText | None = None
    funding_account_reference: SourcedText | None = None
    fee_payment_date: SourcedDate | None = None


class PaidStatus(str, Enum):
    PAID = "paid"
    BILL = "bill"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class TaxReceiptFacts(ClosedFact):
    authority: SourcedText
    property_reference: SourcedText
    tax_year: int
    dated: SourcedDate
    reference: SourcedText
    amount: Money
    status: PaidStatus
    tax_year_source: Source
    status_source: Source
    source_account_reference: SourcedText | None = None

    def __post_init__(self):
        super().__post_init__()
        if self.tax_year is not None and not 1 <= self.tax_year <= 9999:
            raise ContractError("tax year must be a calendar year")

class Exposure(str, Enum):
    BOND = "bond"
    EQUITY = "equity"
    CASH = "cash"
    OTHER = "other"
    UNKNOWN = "unknown"


class Vehicle(str, Enum):
    MUTUAL_FUND = "mutual_fund"
    ETF = "etf"
    INDIVIDUAL = "individual_security"
    OTHER = "other"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class PositionClassification(ClosedFact):
    instrument: SourcedText
    exposure: Exposure = Exposure.UNKNOWN
    vehicle: Vehicle = Vehicle.UNKNOWN
    exposure_source: Source | None = None
    vehicle_source: Source | None = None

    def __post_init__(self):
        super().__post_init__()
        if not isinstance(self.exposure, Exposure) or not isinstance(self.vehicle, Vehicle):
            raise ContractError("classification requires closed enum values")
        if self.exposure != Exposure.UNKNOWN and not isinstance(self.exposure_source, Source):
            raise ContractError("known exposure needs explicit printed source")
        if self.vehicle != Vehicle.UNKNOWN and not isinstance(self.vehicle_source, Source):
            raise ContractError("known vehicle needs explicit printed source")


class Family(str, Enum):
    ORDINARY = "ordinary"
    DEPOSIT = "term_deposit"
    ESCROW = "escrow"


class Restriction(str, Enum):
    TERM = "restricted_term_deposit"
    ESCROW = "restricted_escrow"


@dataclass(frozen=True)
class Availability(ClosedFact):
    family: Family
    restriction: Restriction | None = None
    source: Source | None = None

    def __post_init__(self):
        super().__post_init__()
        if not isinstance(self.family, Family):
            raise ContractError("availability requires a closed family")
        wanted = {Family.DEPOSIT: Restriction.TERM, Family.ESCROW: Restriction.ESCROW}
        if self.family in wanted and (self.restriction != wanted[self.family]
                                      or not isinstance(self.source, Source)):
            raise ContractError("instrument needs an explicit persistent restriction")
        if self.family == Family.ORDINARY and (self.restriction is not None or self.source is not None):
            raise ContractError("ordinary availability delegates to the existing contract")

    def permits_starting_cash(self, ordinary_eligible: bool):
        if type(ordinary_eligible) is not bool:
            raise ContractError("ordinary cash eligibility must be explicit boolean")
        return self.family == Family.ORDINARY and ordinary_eligible


class Disposition(str, Enum):
    ACCEPTED = "accepted"
    HELD = "held"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class ComponentResult(ClosedFact):
    component: str
    disposition: Disposition
    check: CheckResult | None = None
    reason: str = ""


def _money_values(values):
    values = tuple(values)
    if not values or any(not isinstance(v, Money) for v in values):
        raise ContractError("sourced monetary operands required")
    if len({v.currency for v in values}) != 1:
        raise ContractError("mixed currencies cannot reconcile")
    return tuple(v.value for v in values)


def _positive(values):
    if any(v.value < 0 for v in values):
        raise ContractError("printed component magnitudes cannot be negative")


def _period(start, end, movements):
    if start.value > end.value:
        raise ContractError("period starts after its end")
    if any(not start.value <= m.dated.value <= end.value for m in movements):
        raise ContractError("movement falls outside its statement period")


def _result(component, check):
    return ComponentResult(component, Disposition.ACCEPTED if check.passed else Disposition.HELD, check)


def check_deposit(facts: DepositFacts):
    missing = _missing_fields(facts, ("start", "end", "opening", "closing", "movements"))
    if missing:
        return _held_missing("deposit_balance", missing)
    _period(facts.start, facts.end, facts.movements)
    values = [facts.opening, facts.closing, *(m.amount for m in facts.movements)]
    _money_values(values)
    _positive(values)
    effects = [m.amount.value * (1 if m.kind in {DepositKind.FUNDING, DepositKind.INTEREST} else -1)
               for m in facts.movements]
    return _result("deposit_balance", check_balance_identity(facts.opening.value, effects, facts.closing.value))


def _missing_fields(record, names):
    return [name for name in names if getattr(record, name) is None]


def _held_missing(name, missing):
    return ComponentResult(name, Disposition.HELD,
                           reason="missing printed components: " + ", ".join(missing))


def _payment_name(payment, index=None):
    if payment.reference is not None:
        return "payment:" + payment.reference.value
    return "payment:unresolved" if index is None else f"payment:row:{index + 1}"


def check_payment(payment: PaymentComponents, component=None):
    name = component or _payment_name(payment)
    missing = _missing_fields(payment, ("dated", "reference", "principal", "interest", "escrow", "fees", "total"))
    if missing:
        return _held_missing(name, missing)
    parts = [payment.principal, payment.interest, payment.escrow, payment.fees]
    _money_values([*parts, payment.total]); _positive([*parts, payment.total])
    return _result(name, check_balance_identity(Decimal(0), [p.value for p in parts], payment.total.value))


def _escrow_missing(facts):
    missing = _missing_fields(facts, ("identity", "opening", "closing", "movements"))
    if facts.movements is not None:
        for index, row in enumerate(facts.movements):
            missing.extend(f"movements[{index}].{name}" for name in
                           _missing_fields(row, ("kind", "amount", "dated", "reference")))
    return missing


def check_escrow(facts: EscrowFacts):
    missing = _escrow_missing(facts)
    if missing:
        return _held_missing("escrow_balance", missing)
    values = [facts.opening, facts.closing, *(m.amount for m in facts.movements)]
    _money_values(values); _positive(values)
    effects = [m.amount.value * (1 if m.kind in {EscrowKind.DEPOSIT, EscrowKind.INCREASE_ADJUSTMENT} else -1)
               for m in facts.movements]
    return _result("escrow_balance", check_balance_identity(facts.opening.value, effects, facts.closing.value))


def _checked_component(name, operation):
    try:
        return operation()
    except ContractError as error:
        return ComponentResult(name, Disposition.HELD, reason=str(error))


def _mortgage_principal(facts):
    missing = _missing_fields(facts, ("opening_principal", "closing_principal", "principal_movements"))
    if facts.principal_movements is not None:
        for index, row in enumerate(facts.principal_movements):
            missing.extend(f"principal_movements[{index}].{name}" for name in
                           _missing_fields(row, ("kind", "amount", "dated", "reference")))
    if missing:
        return _held_missing("principal_balance", missing)
    _period(facts.start, facts.end, facts.principal_movements)
    values = [facts.opening_principal, facts.closing_principal, *(m.amount for m in facts.principal_movements)]
    _money_values(values); _positive(values)
    effects = [m.amount.value * (1 if m.kind in {PrincipalKind.ADVANCE, PrincipalKind.INCREASE_ADJUSTMENT} else -1)
               for m in facts.principal_movements]
    return _result("principal_balance", check_balance_identity(facts.opening_principal.value, effects, facts.closing_principal.value))


def _principal_currency_source(facts):
    return facts.opening_principal or facts.closing_principal


def _mortgage_payment(facts, payment, component):
    result = check_payment(payment, component)
    if result.check is None:
        return result
    _period(facts.start, facts.end, (payment,))
    principal = _principal_currency_source(facts)
    if principal is not None:
        _money_values([principal, payment.total])
    return result


def _mortgage_escrow(facts):
    result = check_escrow(facts.escrow)
    if result.check is None:
        return result
    _period(facts.start, facts.end, facts.escrow.movements)
    principal = _principal_currency_source(facts)
    if principal is not None:
        _money_values([principal, facts.escrow.opening])
    return result


def check_mortgage(facts: MortgageFacts):
    results = [_checked_component("principal_balance", lambda: _mortgage_principal(facts))]
    if facts.payments is None or not facts.payments:
        results.append(ComponentResult("payments", Disposition.UNAVAILABLE, reason="no printed payment rows"))
    else:
        for index, payment in enumerate(facts.payments):
            name = _payment_name(payment, index)
            results.append(_checked_component(name, lambda: _mortgage_payment(facts, payment, name)))
    if facts.escrow is None:
        results.append(ComponentResult("escrow_balance", Disposition.UNAVAILABLE, reason="no printed escrow section"))
    else:
        results.append(_checked_component("escrow_balance", lambda: _mortgage_escrow(facts)))
    return tuple(results)


def check_refinance(facts: RefinanceFacts):
    amounts = [facts.old_payoff_principal, facts.new_funded_principal, facts.borrower_contribution,
               facts.cash_out, facts.financed_costs, facts.total_fees, *(f.amount for f in facts.fees)]
    _money_values(amounts); _positive(amounts)
    results = [
        _result("settlement_sources_uses", check_balance_identity(
            facts.new_funded_principal.value, [facts.borrower_contribution.value],
            facts.old_payoff_principal.value + facts.cash_out.value + facts.total_fees.value)),
        _result("settlement_fees", check_balance_identity(Decimal(0), [f.amount.value for f in facts.fees], facts.total_fees.value)),
        _result("financed_fees", check_balance_identity(facts.old_payoff_principal.value,
            [facts.financed_costs.value, facts.cash_out.value], facts.new_funded_principal.value)),
    ]
    if facts.old_closing_principal is None:
        results.append(ComponentResult("old_loan_zero", Disposition.UNAVAILABLE, reason="payoff witness required"))
    else:
        _money_values([facts.old_closing_principal, facts.old_payoff_principal])
        results.append(_result("old_loan_zero", check_balance_identity(Decimal(0), [], facts.old_closing_principal.value)))
    return tuple(results)


class MatchKind(str, Enum):
    MORTGAGE_PAYMENT = "mortgage_payment"
    DEPOSIT_TRANSFER = "deposit_transfer"
    TAX_PAYMENT = "tax_payment"
    REFINANCE = "refinance"


MATCH_WINDOWS = {MatchKind.MORTGAGE_PAYMENT: 10, MatchKind.DEPOSIT_TRANSFER: 3,
                 MatchKind.TAX_PAYMENT: 3, MatchKind.REFINANCE: 3}


@dataclass(frozen=True)
class FinancialIdentity(ClosedFact):
    kind: MatchKind
    account_id: str
    counterparty_id: str
    reference: str
    amount: Money
    dated: SourcedDate
    property_id: str = ""
    tax_year: int | None = None

    def __post_init__(self):
        super().__post_init__()
        if self.tax_year is not None and not 1 <= self.tax_year <= 9999:
            raise ContractError("tax year must be a calendar year")

def compatible_counterpart(left: FinancialIdentity, right: FinancialIdentity):
    """Both sides must resolve to the same oriented financial-event identity."""
    if (any(not isinstance(value, str) or not value.strip() for value in
            (left.account_id, left.counterparty_id, left.reference))
            or left.kind != right.kind
            or (left.account_id, left.counterparty_id, left.reference) !=
               (right.account_id, right.counterparty_id, right.reference)):
        return False
    if left.kind == MatchKind.TAX_PAYMENT:
        if (not left.property_id or type(left.tax_year) is not int
                or (left.property_id, left.tax_year) != (right.property_id, right.tax_year)):
            return False
    if (left.amount.value < 0 or right.amount.value < 0
            or left.amount.currency != right.amount.currency or left.amount.value != right.amount.value):
        return False
    return abs((date.fromisoformat(left.dated.value) - date.fromisoformat(right.dated.value)).days) <= MATCH_WINDOWS[left.kind]


def select_counterpart(subject: FinancialIdentity, candidates: tuple[FinancialIdentity, ...]):
    matches = tuple(c for c in candidates if compatible_counterpart(subject, c))
    return ("matched", matches[0]) if len(matches) == 1 else ("ambiguous" if matches else "unmatched", None)


def check_tax_receipt(facts: TaxReceiptFacts):
    _positive([facts.amount])
    if facts.status != PaidStatus.PAID:
        return ComponentResult("tax_paid", Disposition.UNAVAILABLE, reason="source is not a paid receipt")
    if facts.amount.value == 0:
        return ComponentResult("tax_paid", Disposition.HELD, reason="receipt has no positive payment")
    return ComponentResult("tax_paid", Disposition.ACCEPTED)
