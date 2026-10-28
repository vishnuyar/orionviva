"""Source-bound instrument ingestion and deterministic, provider-free healing.

Source arithmetic and counterpart corroboration are independent gates. Financial
rows are keyed by their source financial identity; document observations remain
independent witnesses and corrections retire only their own derived effects.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal
from hashlib import sha256
import json

from . import instrument_contracts as c
from .mortgage_known_allocation import residual, create_allocation, known_allocation_event
from .instrument_effects import (PaymentAllocation, allocation_event,
    InstrumentComponentState, component_state_event)
from .instrument_observations import ObservationChange, ObservationKind as K, Operation
from .instrument_read import InstrumentReadFacts, validate_sources
from .pipeline_models import IngestResult, POSTED, CONFLICT, AWAITING, DUPLICATE, IDENTITY
from ..ledger.events import (Event, Posting, Provenance, CORROBORATED, VERIFIED,
    account_opened, opening_balance_observed, closing_balance_observed,
    transaction_recorded, transfer_linked, statement_held)
from ..ledger.instruments import (encode, _sources, observation_event, fold_change,
    current_observations, family_event, reference_event, reference_accounts, append_effects, planned_effects)
from ..ledger.projection.movements import _enumerated

KINDS = {c.DepositFacts: K.DEPOSIT_COMPONENTS, c.MortgageFacts: K.MORTGAGE_COMPONENTS,
         c.RefinanceFacts: K.REFINANCE, c.TaxReceiptFacts: K.TAX_RECEIPT}


def _key(*parts):
    return sha256(json.dumps(parts, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def _provenance(source):
    return Provenance(source.doc_id, source.page)


def _held(name, reason):
    return c.ComponentResult(name, c.Disposition.HELD, reason=reason)


def _accepted(name):
    return c.ComponentResult(name, c.Disposition.ACCEPTED)


def _identity_accounts(proj, identity, kind, *, currency=None):
    candidates = reference_accounts(proj, identity.account_reference.value)
    return tuple(account for account in candidates if (
        proj.account_info(account).kind == kind
        and (currency is None or proj.account_info(account).currency == currency)
        and proj.account_info(account).institution.casefold().strip() == identity.institution.value.casefold().strip()
        and identity.holder.value.casefold().strip() in {n.casefold().strip() for n in proj.account_info(account).names}))


def _account_id(identity, kind):
    return "instrument:" + _key(kind, identity.institution.value.casefold().strip(),
        identity.account_reference.value, identity.holder.value.casefold().strip())[:32]


def _subject(proj, payload):
    if isinstance(payload, c.TaxReceiptFacts):
        return "property:" + _key(payload.authority.value, payload.property_reference.value, payload.tax_year)
    identity = payload.new_loan if isinstance(payload, c.RefinanceFacts) else payload.identity
    kind = "liability" if isinstance(payload, (c.MortgageFacts, c.RefinanceFacts)) else "depository"
    candidates = _identity_accounts(proj, identity, kind, currency=_currency(payload))
    if not candidates:
        candidates = _identity_accounts(proj, identity, kind)
    if len(candidates) > 1:
        raise c.ContractError("ambiguous source financial account")
    return candidates[0] if candidates else _account_id(identity, kind)


def _ensure_account(proj, identity, kind, currency, dated, *, family=None, continuity=None, restriction_source=None, bound_account=None):
    declared = _identity_accounts(proj, identity, kind)
    candidates = _identity_accounts(proj, identity, kind, currency=currency)
    if declared and not candidates:
        raise c.ContractError("no exact currency binding for known instrument account")
    if continuity is not None:
        continuous = reference_accounts(proj, continuity.value, "continuous_escrow")
        continuous = tuple(a for a in continuous if proj.account_info(a).kind == kind
            and identity.holder.value.casefold().strip() in {n.casefold().strip() for n in proj.account_info(a).names})
        compatible = tuple(a for a in continuous if proj.account_info(a).currency == currency)
        if continuous and not compatible:
            raise c.ContractError("no exact currency binding for continuing escrow account")
        continuous = compatible
        if len(continuous) > 1 or (continuous and candidates and set(candidates) != set(continuous)):
            raise c.ContractError("ambiguous continuous escrow identity")
        candidates = continuous or candidates
    if bound_account is not None and proj.seen_account(bound_account):
        if bound_account not in candidates:
            raise c.ContractError("source observation's closed account binding is not currency compatible")
        candidates = (bound_account,)
    if len(candidates) > 1:
        raise c.ContractError("ambiguous source financial account")
    account = candidates[0] if candidates else _account_id(identity, kind)
    source = identity.account_reference.source
    if not proj.seen_account(account):
        yield _key("account", account), account_opened(account, kind,
            identity.account_reference.value, currency, dated,
            institution=identity.institution.value, account_names=[identity.holder.value], provenance=_provenance(source))
    if account not in reference_accounts(proj, identity.account_reference.value):
        yield _key("reference", account, identity.account_reference.value), reference_event(
            account, identity.account_reference.value, dated, source)
    if continuity is not None and account not in reference_accounts(proj, continuity.value, "continuous_escrow"):
        yield _key("continuous_escrow", account, continuity.value), reference_event(
            account, continuity.value, dated, continuity.source, scope="continuous_escrow")
    if family is not None:
        if account not in proj.account_restrictions():
            yield _key("family", account, family), family_event(account, family, dated, source)
        # This is an explicit restriction carried by the instrument's source
        # document class. A missing or withdrawn statement never releases it.
        availability_id = _key("restriction", account, family)
        if restriction_source is not None and availability_id not in proj.core._instrument_observations:
            availability = c.Availability(c.Family(family),
                c.Restriction.TERM if family == "term_deposit" else c.Restriction.ESCROW, restriction_source)
            yield availability_id, observation_event(ObservationChange(availability_id, account, K.AVAILABILITY,
                c.SourcedDate(dated, restriction_source), Operation.CREATE, restriction_source, availability))
    return account


def _chain(proj, account, start, end, opening, closing):
    state = proj.core._acct.get(account)
    if state is None or state.opening is None:
        return "initial"
    if end < state.opening_date and closing == state.opening:
        return "backward"
    if start >= state.closing_date and opening == proj.running_balance(account):
        return "forward"
    return ""


def _flow(account, amount, description, dated, source, role, *, kind="depository"):
    # Principal and restricted-asset changes have explicit non-income
    # counterparts. No ordinary cash account receives a fabricated movement.
    target = ("Income:Interest" if role == "term_interest" else
              "Expenses:Fees" if role in {"term_fee", "refinance_fee"} else
              "Expenses:PropertyTax" if role == "escrow_tax" else
              "Expenses:Insurance" if role == "escrow_insurance" else "Transfers:Instrument")
    event = transaction_recorded([Posting(account, amount, CORROBORATED),
        Posting(target, -amount, CORROBORATED)], description, dated, provenance=_provenance(source))
    event.body["instrument_role"] = role
    return event


def _financial_identity(role, account, dated, reference):
    return _key("financial", role, account, dated, reference)


def _bank_matches(proj, owner, own_reference, funding, reference, amount, dated, window, sign=-1):
    if funding is None:
        return ()
    funding_accounts = tuple(a for a in reference_accounts(proj, funding.value)
        if proj.account_info(a).currency == amount.currency)
    if len(funding_accounts) != 1:
        return ()
    account = funding_accounts[0]
    matches = []
    for key, bank, state, line in _enumerated(proj.core):
        printed = proj.core._instrument_bank_references.get(line.transaction_id, ("", ""))
        if (bank == account and state.kind == "depository" and state.currency == amount.currency
            and line.amount == amount.value * sign
            and printed[0] == reference.value
            and printed[1] == own_reference
            and abs((date.fromisoformat(line.date) - date.fromisoformat(dated.value)).days) <= window
            and line.provenance.page is not None):
            matches.append((key, line))
    return tuple(matches)


def _balance_section(proj, account, start, end, opening, closing, rows, role_for, sign_for, prefix):
    closing_key = _key("closing", prefix, account, end.value)
    keys = [_financial_identity(role_for(row), account, row.dated.value, row.reference.value) for row in rows]
    if len(keys) != len(set(keys)):
        return False
    existing = proj.core._instrument_effect_records.get(closing_key)
    if existing is not None:
        # Repeated independent witnesses may corroborate, never overwrite a
        # conflicting closing or a changed same-reference movement magnitude.
        if Decimal(existing.body["amount"]) != closing.value:
            return False
        origin = existing.body.get("instrument_observation_id")
        prior = proj.core._instrument_observations.get(origin)
        if prior is not None:
            previous = prior["change"].payload
            old_opening = (previous.opening if prefix == "deposit" else previous.opening_principal
                           if prefix == "principal" else previous.escrow.opening)
            old_start = previous.start
            if old_opening.value != opening.value or old_start.value != start.value:
                return False
        for row in rows:
            key = _financial_identity(role_for(row), account, row.dated.value, row.reference.value)
            prior = proj.core._instrument_effect_records.get(key)
            if prior is None or Decimal(prior.body["postings"][0]["amount"]) != row.amount.value * sign_for(row):
                return False
        return True
    state = proj.core._acct.get(account)
    # A settlement and a paid-off loan statement can witness the same
    # principal transfer. All explicit flow identities and amounts must match;
    # the new witness adds no second principal movement.
    if rows and state is not None and state.closing_date == end.value and proj.running_balance(account) == closing.value:
        matched = all(key in proj.core._instrument_effect_records and
            Decimal(proj.core._instrument_effect_records[key].body["postings"][0]["amount"]) == row.amount.value * sign_for(row)
            for key, row in zip(keys, rows))
        if matched:
            yield closing_key, closing_balance_observed(account, closing.value, end.value, _provenance(closing.source))
            return True
    direction = _chain(proj, account, start.value, end.value, opening.value, closing.value)
    if not direction:
        return False
    dependencies = []
    if direction == "forward":
        state = proj.core._acct[account]
        previous = [event for event in proj.core._instrument_effect_records.values()
            if event.event_type == "ClosingBalanceObserved" and event.body.get("account_id") == account
            and event.occurred_at == state.closing_date]
        for event in previous:
            dependencies.extend(event.body.get("instrument_dependencies", []))
            origin = event.body.get("instrument_observation_id")
            if origin:
                dependencies.append(origin)
        dependencies = sorted(set(dependencies))
    def dependent(event):
        if dependencies:
            event.body["instrument_dependencies"] = dependencies
        return event
    if direction in {"initial", "backward"}:
        yield _key("opening", prefix, account, start.value), opening_balance_observed(
            account, opening.value, start.value, _provenance(opening.source))
    for row in rows:
        role, sign = role_for(row), sign_for(row)
        key = _financial_identity(role, account, row.dated.value, row.reference.value)
        yield key, dependent(_flow(account, row.amount.value * sign, row.reference.value,
            row.dated.value, row.amount.source, role))
    yield closing_key, dependent(closing_balance_observed(
        account, closing.value, end.value, _provenance(closing.source)))
    return True


def _term_fields(value, path=""):
    """Known assertion values, excluding provenance and unknown conventions."""
    if value is None or isinstance(value, c.Source):
        return {}
    if isinstance(value, (c.SourcedText, c.SourcedDate)):
        return {path: value.value}
    if isinstance(value, c.Money):
        return {path: (value.value, value.currency)}
    if isinstance(value, c.Rate):
        return {path: value.percent}
    if hasattr(value, "__dataclass_fields__"):
        result = {}
        for name in value.__dataclass_fields__:
            result.update(_term_fields(getattr(value, name), path + "." + name))
        return result
    if getattr(value, "value", value) == "unknown":
        return {}
    return {path: getattr(value, "value", value)}


def _terms_result(proj, change, terms, name):
    asserted = _term_fields(terms)
    for row in current_observations(proj.core._instrument_observations).values():
        other = row["change"]
        previous = getattr(other.payload, "terms", None)
        if (other.observation_id == change.observation_id or other.subject_id != change.subject_id
                or other.kind != change.kind or previous is None):
            continue
        # An explicitly renewed CD starts another contract. Fixed mortgage
        # terms refer to their same sourced origination; variable terms are
        # retained but never calculated by this vertical.
        if isinstance(terms, c.DepositTerms) and previous.opened.value != terms.opened.value:
            continue
        if isinstance(terms, c.MortgageTerms) and not (terms.fixed_rate is previous.fixed_rate is True):
            continue
        prior = _term_fields(previous)
        if any(asserted[key] != prior[key] for key in asserted.keys() & prior.keys()):
            return _held(name, "conflicting explicit terms require a reviewed source correction")
    return _accepted(name)


def _deposit(proj, change, results):
    f, account = change.payload, change.subject_id
    if proj.seen_account(account) and proj.account_info(account).currency != _currency(f):
        results.append(_held("deposit_balance", "no exact currency binding for known instrument account"))
        if f.terms is not None:
            results.append(_held("deposit_terms", "source currency is not bound to this financial account"))
        return
    dated = f.start.value if f.start is not None else change.effective.value
    yield from _ensure_account(proj, f.identity, "depository", _currency(f), dated, family="term_deposit", bound_account=account,
        restriction_source=(f.terms.withdrawal_restriction.source if f.terms and f.terms.withdrawal_restriction else None))
    if f.terms is not None:
        results.append(_terms_result(proj, change, f.terms, "deposit_terms"))
    try:
        result = c.check_deposit(f)
    except c.ContractError as exc:
        result = _held("deposit_balance", str(exc))
    if result.disposition == c.Disposition.ACCEPTED:
        roles = {c.DepositKind.FUNDING: "term_funding", c.DepositKind.INTEREST: "term_interest",
                 c.DepositKind.REDEMPTION: "term_redemption", c.DepositKind.FEE: "term_fee"}
        connected = yield from _balance_section(proj, account, f.start, f.end, f.opening, f.closing, f.movements,
            lambda row: roles[row.kind], lambda row: 1 if row.kind in {c.DepositKind.FUNDING, c.DepositKind.INTEREST} else -1, "deposit")
        if not connected:
            result = _held("deposit_balance", "opening does not connect to retained instrument balance")
        else:
            for row in f.movements:
                if row.kind not in {c.DepositKind.FUNDING, c.DepositKind.REDEMPTION}:
                    continue
                sign = -1 if row.kind == c.DepositKind.FUNDING else 1
                matches = _bank_matches(proj, account, f.identity.account_reference.value,
                    row.counterparty_reference, row.reference, row.amount, row.dated, 3, sign)
                own = [key for key, a, state, line in _enumerated(proj.core) if a == account
                    and line.date == row.dated.value and line.description == row.reference.value
                    and line.amount == -sign * row.amount.value]
                if len(matches) == len(own) == 1:
                    yield _key("link", own[0], matches[0][0]), transfer_linked(own[0], matches[0][0],
                        CORROBORATED, {"reference": row.reference.value, "identity": "source_accounts_reference_currency_amount_window"},
                        row.dated.value, by="document", provenance=_provenance(row.reference.source))
                    results.append(_accepted("counterpart:" + row.reference.value))
                else:
                    results.append(_held("counterpart:" + row.reference.value, "unique bounded source-reference counterpart required"))
    results.append(result)


def _mortgage(proj, change, results):
    f, account = change.payload, change.subject_id
    if proj.seen_account(account) and proj.account_info(account).currency != _currency(f):
        results.extend(_held(row.component, "no exact currency binding for known instrument account")
                       for row in c.check_mortgage(f))
        return
    yield from _ensure_account(proj, f.identity, "liability", _currency(f), f.start.value, bound_account=account)
    checks = list(c.check_mortgage(f))
    if f.terms is not None:
        results.append(_terms_result(proj, change, f.terms, "mortgage_terms"))
    if checks[0].disposition == c.Disposition.ACCEPTED:
        connected = yield from _balance_section(proj, account, f.start, f.end,
            f.opening_principal, f.closing_principal, f.principal_movements, lambda row: "principal",
            lambda row: 1 if row.kind in {c.PrincipalKind.ADVANCE, c.PrincipalKind.INCREASE_ADJUSTMENT} else -1, "principal")
        if not connected:
            checks[0] = _held("principal_balance", "opening does not connect to retained loan principal")
    escrow_account = ""
    if f.escrow is not None and f.escrow.identity is not None:
        e = f.escrow
        continuous = reference_accounts(proj, e.continuity_reference.value, "continuous_escrow") if e.continuity_reference else ()
        escrow_account = continuous[0] if len(continuous) == 1 else _account_id(e.identity, "depository")
        try:
            yield from _ensure_account(proj, e.identity, "depository", _currency(f), f.start.value,
                family="escrow", continuity=e.continuity_reference,
                restriction_source=e.withdrawal_restriction.source if e.withdrawal_restriction else None)
        except c.ContractError as exc:
            checks[-1] = _held("escrow_balance", str(exc))
            escrow_account = ""
        # Resolve only a currency-compatible identity after declarations fold.
        resolved = _identity_accounts(proj, e.identity, "depository", currency=_currency(f))
        if resolved and escrow_account:
            escrow_account = resolved[0]
        if escrow_account and checks[-1].disposition == c.Disposition.ACCEPTED:
            roles = {c.EscrowKind.DEPOSIT: "escrow_deposit", c.EscrowKind.TAX: "escrow_tax",
                c.EscrowKind.INSURANCE: "escrow_insurance", c.EscrowKind.INCREASE_ADJUSTMENT: "escrow_adjustment",
                c.EscrowKind.DECREASE_ADJUSTMENT: "escrow_adjustment"}
            connected = yield from _balance_section(proj, escrow_account, f.start, f.end, e.opening, e.closing, e.movements,
                lambda row: roles[row.kind], lambda row: 1 if row.kind in {c.EscrowKind.DEPOSIT, c.EscrowKind.INCREASE_ADJUSTMENT} else -1, "escrow")
            if not connected:
                checks[-1] = _held("escrow_balance", "opening does not connect to retained escrow balance")
    for i, payment in enumerate(f.payments or ()):
        check = checks[i + 1]
        known = False
        if check.disposition != c.Disposition.ACCEPTED:
            try:
                residual(payment)
                known = True
            except (ValueError, TypeError):
                continue
        matches = _bank_matches(proj, account, f.identity.account_reference.value,
            payment.funding_account_reference, payment.reference, payment.total, payment.dated, 10)
        if len(matches) != 1 or (payment.escrow.value and not escrow_account):
            checks[i + 1] = _held(check.component, "unique bounded source-reference cash counterpart and escrow identity required")
            continue
        key, line = matches[0]
        if known:
            try:
                allocation = create_allocation(proj, change, payment, str(i), account, escrow_account, key, line)
            except (ValueError, TypeError):
                continue
        else:
            allocation = PaymentAllocation(key, account, escrow_account, payment,
                c.Source(line.provenance.doc_id, line.provenance.page))
        existing = proj.core._instrument_allocations.get(key)
        if existing is not None and existing != allocation:
            # Different documents may repeat the same amounts. Their source
            # identity stays independent; conflicting magnitudes stay held.
            if tuple(None if getattr(existing.payment,n) is None else getattr(existing.payment,n).value for n in ("principal", "interest", "escrow", "fees", "total")) != tuple(
                None if getattr(payment,n) is None else getattr(payment,n).value for n in ("principal", "interest", "escrow", "fees", "total")):
                checks[i + 1] = _held(check.component, "conflicting source payment allocation")
                continue
        yield _key("allocation", key), known_allocation_event(allocation) if known else allocation_event(allocation)
        if known:
            results.append(_accepted("known_allocation:" + payment.reference.value))
    results.extend(checks)


def _refinance(proj, change, results):
    f = change.payload
    checks = list(c.check_refinance(f))
    results.extend(checks)
    if not all(row.disposition == c.Disposition.ACCEPTED for row in checks[:3]):
        return
    old = _identity_accounts(proj, f.old_loan, "liability", currency=_currency(f))
    new = _identity_accounts(proj, f.new_loan, "liability", currency=_currency(f))
    if ((_identity_accounts(proj, f.old_loan, "liability") and not old)
            or (_identity_accounts(proj, f.new_loan, "liability") and not new)):
        results.append(_held("settlement_relationship", "no exact currency binding for source loan endpoints"))
        return
    if len(old) > 1 or len(new) > 1:
        results.append(_held("settlement_relationship", "ambiguous source loan endpoints"))
        return
    yield from _ensure_account(proj, f.new_loan, "liability", _currency(f), f.dated.value)
    new_account = new[0] if len(new) == 1 else _account_id(f.new_loan, "liability")
    # A settlement reports a newly funded principal balance. It is an opening
    # source measurement, never a bank deposit or income. A later mortgage
    # statement corroborates it without posting the advance twice.
    if not proj.is_seeded(new_account):
        yield _key("refinance_opening", new_account, f.reference.value), opening_balance_observed(
            new_account, f.new_funded_principal.value, f.dated.value, _provenance(f.new_funded_principal.source))
        yield _key("refinance_closing", new_account, f.reference.value), closing_balance_observed(
            new_account, f.new_funded_principal.value, f.dated.value, _provenance(f.new_funded_principal.source))
    # Old payoff is recognized only against a retained, reconciled old loan
    # balance and an explicit old-zero witness. No invented cash bridge.
    if (len(old) == 1 and f.old_closing_principal is not None and f.old_closing_principal.value == 0
            and proj.running_balance(old[0]) == f.old_payoff_principal.value):
        yield _financial_identity("principal", old[0], f.dated.value, f.reference.value), _flow(
            old[0], -f.old_payoff_principal.value, f.reference.value, f.dated.value, f.old_payoff_principal.source, "principal")
        yield _key("refinance_old_zero", old[0], f.reference.value), closing_balance_observed(
            old[0], 0, f.dated.value, _provenance(f.old_closing_principal.source))
    elif len(old) != 1 or proj.running_balance(old[0]) != 0:
        results.append(_held("old_loan_payoff_link", "retained old-loan principal and explicit zero witness required"))
    cash_fees = f.total_fees.value - f.financed_costs.value
    if cash_fees > 0:
        if f.fee_payment_reference is None or f.fee_payment_date is None:
            results.append(_held("settlement_cash_fee", "printed fee-payment reference and date required"))
            return
        amount = c.Money(cash_fees, f.total_fees.currency, f.total_fees.source)
        matches = _bank_matches(proj, new_account, f.new_loan.account_reference.value, f.funding_account_reference,
            f.fee_payment_reference, amount, f.fee_payment_date, 3)
        if len(matches) != 1:
            results.append(_held("settlement_cash_fee", "unique bounded source-reference fee counterpart required"))
        else:
            key, line = matches[0]
            zero = c.Money(Decimal(0), amount.currency, amount.source)
            payment = c.PaymentComponents(f.fee_payment_date, f.fee_payment_reference, zero, zero, zero, amount, amount,
                f.funding_account_reference)
            yield _key("allocation", key), allocation_event(PaymentAllocation(key, new_account, "", payment,
                c.Source(line.provenance.doc_id, line.provenance.page)))
            results.append(_accepted("settlement_cash_fee"))


def _tax(proj, change, results):
    f = change.payload
    result = c.check_tax_receipt(f)
    results.append(result)
    if result.disposition != c.Disposition.ACCEPTED:
        return
    matches = []
    source_accounts = set(reference_accounts(proj, f.source_account_reference.value)) if f.source_account_reference else set()
    if f.source_account_reference:
        source_accounts.update(reference_accounts(proj, f.source_account_reference.value, "continuous_escrow"))
    source_accounts = {a for a in source_accounts if proj.account_info(a).currency == f.amount.currency}
    if len(source_accounts) != 1:
        results.append(_held("tax_payment_link", "unique currency-compatible source account identity required"))
        return
    for row in current_observations(proj.core._instrument_observations).values():
        other = row["change"]
        if other.kind != K.MORTGAGE_COMPONENTS or other.payload.escrow is None:
            continue
        e = other.payload.escrow
        if e.identity is None or not any(result.component == "escrow_balance"
                and result.disposition == c.Disposition.ACCEPTED for result in c.check_mortgage(other.payload)):
            continue
        escrow_accounts = set(_identity_accounts(proj, e.identity, "depository", currency=f.amount.currency))
        if e.continuity_reference is not None:
            escrow_accounts.update(a for a in reference_accounts(proj, e.continuity_reference.value, "continuous_escrow")
                if proj.account_info(a).currency == f.amount.currency
                and e.identity.holder.value.casefold().strip() in {n.casefold().strip() for n in proj.account_info(a).names})
        if len(escrow_accounts) != 1 or not escrow_accounts.intersection(source_accounts):
            continue
        for payment in e.movements or ():
            if (payment.kind == c.EscrowKind.TAX and payment.reference.value == f.reference.value
                and payment.property_reference is not None and payment.property_reference.value == f.property_reference.value
                and payment.tax_year == f.tax_year and payment.amount.currency == f.amount.currency
                and payment.amount.value == f.amount.value
                and abs((date.fromisoformat(payment.dated.value) - date.fromisoformat(f.dated.value)).days) <= 3):
                for account in escrow_accounts:
                    key = _financial_identity("escrow_tax", account, payment.dated.value, payment.reference.value)
                    if key in proj.core._instrument_effect_keys:
                        matches.append(key)
    results.append(_accepted("tax_payment_link") if len(set(matches)) == 1 else
        _held("tax_payment_link", "unique property/year/reference/currency/account disbursement witness required"))
    # A receipt corroborates an existing debit; it never creates another one.
    yield from ()


def _currency(value):
    if isinstance(value, c.Money):
        return value.currency
    if hasattr(value, "__dataclass_fields__"):
        for name in value.__dataclass_fields__:
            result = _currency(getattr(value, name))
            if result:
                return result
    if type(value) is tuple:
        for item in value:
            result = _currency(item)
            if result:
                return result
    return ""


def _plan(proj, change):
    results = []
    handler = {K.DEPOSIT_COMPONENTS: _deposit, K.MORTGAGE_COMPONENTS: _mortgage,
        K.REFINANCE: _refinance, K.TAX_RECEIPT: _tax}.get(change.kind)
    if handler is None:
        return
    yield from handler(proj, change, results)
    state = InstrumentComponentState(change.observation_id, change.source.doc_id, tuple(results),
        change.source, change.effective)
    prior = proj.core._instrument_component_states.get(change.observation_id)
    if state != prior:
        components=state.components + (prior.components if prior is not None else ())
        if any(part.component.startswith("known_allocation:") for part in components):
            predecessors=[event for event in proj.core._instrument_effect_records.values()
                if event.event_type=="InstrumentComponentStateRecorded"
                and event.body.get("instrument_observation_id")==change.observation_id]
            predecessor=predecessors[-1] if predecessors else None
            if prior is not None and (predecessor is None or predecessor.body.get("state")!=encode(prior)):
                raise c.ContractError("known allocation state transition has no current retained predecessor")
            key=_key("known_allocation_component_transition_v1",change.observation_id,
                predecessor.event_id if predecessor is not None else None,encode(state))
        else:
            key=_key("state",change.observation_id,encode(state))
        yield key, component_state_event(state)


def post_instrument(ledger, facts, *, prior_id=None):
    if type(facts) is not InstrumentReadFacts:
        raise c.ContractError("instrument dispatcher requires its typed reader wrapper")
    validate_sources(facts.payload, facts.doc_id)
    if not facts.period_end:
        return IngestResult(facts.doc_id, CONFLICT, facts.doc_type, message="No printed effective date; facts retained without financial projection.")
    result = {}
    def choose(proj):
        if facts.doc_id not in proj.captured_docs():
            raise c.ContractError("instrument source must be captured before projection")
        try:
            subject = _subject(proj, facts.payload)
        except c.ContractError as exc:
            result.update(identifier=None, subject=None, identity_hold=str(exc))
            return (statement_held(facts.doc_id, facts.to_dict(), None, "identity", facts.period_end,
                Provenance(facts.doc_id, note=str(exc))),)
        source = (facts.payload.dated.source if hasattr(facts.payload, "dated") else facts.payload.identity.account_reference.source)
        identifier = _key("document_observation", facts.doc_id, facts.doc_type, encode(facts.payload), prior_id)
        if identifier in proj.core._instrument_observations:
            result.update(identifier=identifier, subject=subject, duplicate=True)
            return ()
        change = ObservationChange(identifier, subject, KINDS[type(facts.payload)],
            c.SourcedDate(facts.period_end, source), Operation.CORRECT if prior_id else Operation.CREATE,
            source, facts.payload, prior_id)
        if not _sources(change) <= set(proj.captured_docs()):
            raise c.ContractError("all observation sources must be retained")
        event = observation_event(change)
        # Validation and append share one authenticated writer frontier.
        history = {key: dict(row) for key, row in proj.core._instrument_observations.items()}
        fold_change(history, event)
        result.update(identifier=identifier, subject=subject, duplicate=False)
        proj.apply(event)
        return (event, *planned_effects(proj, identifier, _plan))
    try:
        ledger.append_atomically(choose)
    except c.ContractError as exc:
        return IngestResult(facts.doc_id, IDENTITY, facts.doc_type, message=str(exc))
    if result.get("identity_hold"):
        return IngestResult(facts.doc_id, IDENTITY, facts.doc_type, message=result["identity_hold"])
    if result["duplicate"]:
        return IngestResult(facts.doc_id, DUPLICATE, facts.doc_type, account=result["subject"])
    state = ledger.projection().core._instrument_component_states[result["identifier"]]
    held = [row.component for row in state.components if row.disposition == c.Disposition.HELD]
    return IngestResult(facts.doc_id, AWAITING if held else POSTED, facts.doc_type,
        account=result["subject"], grade=CORROBORATED if not held else None,
        message=("Instrument source components retained; waiting: " + ", ".join(held) if held else
                 "Instrument source components reconciled and projected."))


def heal_instruments(ledger):
    count = 0
    # No model calls and no mutable cached proposal: each append replans at its
    # own locked canonical frontier. A successful neighbour may connect a gap.
    for _ in range(1000):
        changed = 0
        observations = tuple(current_observations(ledger.projection().core._instrument_observations))
        for identifier in observations:
            row = ledger.projection().core._instrument_observations.get(identifier)
            if row is not None and row["change"].kind in KINDS.values() and not row["superseded"]:
                projection = ledger.projection()
                # A preview is advisory only: unchanged durable holds do not
                # need an authenticated writer transaction. Any possible new
                # effect is replanned under the actual locked frontier.
                if any(key not in projection.core._instrument_effect_keys
                       for key, effect in _plan(projection, row["change"])):
                    changed += append_effects(ledger, identifier, _plan)
        count += changed
        if not changed:
            return count
    raise c.ContractError("instrument healing exceeded its bounded convergence limit")
