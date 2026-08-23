"""Pay-stub reconciliation and projection."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, replace
from decimal import Decimal
from typing import Callable

from vivacore.verify.arithmetic import (CheckResult, check_balance_identity,
                                        check_brokerage_identity,
                                        check_paystub_identity)

from ..ledger.events import (CORROBORATED, VERIFIED, Provenance, account_opened,
                             closing_balance_observed, document_captured,
                             opening_balance_observed, position_observed,
                             read_recorded, statement_held)
from ..ledger.ledger import Ledger
from ..ledger.postings import (brokerage_activity_transaction,
                               brokerage_cash_effect, paystub_decomposition,
                               simple_transaction)
from .brokerage import BrokerageFacts
from .diagnose import FORCED, SUGGESTED, UNLOCALIZED, ReconciliationFinding, diagnose
from ..ledger.identity import account_key
from .paystub import PayStubFacts
from .raw_store import RawStore
from .registry import (BALANCE_IDENTITY, BROKERAGE_IDENTITY, INVESTMENT,
                       PAYSTUB_IDENTITY, account_kind_for, can_project,
                       identity_of_facts, profile_for)
from .statement import StatementFacts, TxnFact

log = logging.getLogger(__name__)


from .pipeline_models import *

def _paystub_diagnose(facts: PayStubFacts) -> ReconciliationFinding:
    """Localize a pay-stub identity failure with arithmetic alone.

    Same ``ReconciliationFinding`` contract as a statement, over
    `gross − Σ deductions = net`."""
    recon = check_paystub_identity(
        facts.gross, [d.amount for d in facts.deductions], facts.net)
    if recon.passed:
        return ReconciliationFinding(reconciles=True, kind="ok", status="none",
                                     delta="0", message="Pay stub reconciles.",
                                     confidence=1.0)
    delta = Decimal(recon.delta)
    for i, d in enumerate(facts.deductions):
        if abs(d.amount) == abs(delta):
            return ReconciliationFinding(
                reconciles=False, kind="deduction_missing_or_extra",
                status=SUGGESTED, delta=str(delta),
                target=f"deduction {i} ({d.label})", target_index=i,
                observed=str(d.amount), confidence=0.5,
                message=(f"gross − deductions is off by {delta}, which equals "
                         f"'{d.label}' ({d.amount}) — a deduction may be missing "
                         "or duplicated. Please check the stub."))
    return ReconciliationFinding(
        reconciles=False, kind="unknown", status=UNLOCALIZED, delta=str(delta),
        confidence=0.1,
        message=(f"gross {facts.gross} − deductions ≠ net {facts.net} (off by "
                 f"{delta}), with no clean explanation. Held for review."))


def _net_pay_deposit(proj, net: Decimal, currency: str, pay_date: str):
    """The checking deposit a pay stub's net explains: a depository inflow equal
    to the net, within a couple of weeks of the pay date."""
    from .transfers import _days_apart
    for m in proj.movements():
        if (m.kind == "depository" and m.currency == currency
                and m.amount == net and not m.linked
                and (not pay_date or _days_apart(m.date, pay_date) <= 10)):
            return m
    return None


def post_paystub(ledger: Ledger, facts: PayStubFacts) -> IngestResult:
    """Verify a pay stub and, only if it holds, decompose the matching deposit.

    The gate is `gross − Σ deductions = net`. On failure the stub is held with a
    localized finding. On success it decomposes the checking deposit its net
    explains — gross booked as income, deductions into universal buckets, the
    net counted once — reusing the deposit already on the ledger. With no such
    deposit yet, the stub is held as AWAITING and ``heal_paystubs`` posts it
    when the deposit arrives."""
    finding = _paystub_diagnose(facts)
    when = facts.pay_date or facts.period_end or facts.period_start
    if not finding.reconciles:
        log.info("post_paystub: identity FAILED (%s); holding %s",
                 finding.message, facts.doc_id[:12])
        ledger.append(statement_held(facts.doc_id, facts.to_dict(),
                                     finding.to_dict(), "conflict", when,
                                     Provenance(doc_id=facts.doc_id)))
        return IngestResult(
            doc_id=facts.doc_id, action=CONFLICT, doc_type=facts.doc_type,
            grade="conflicted", finding=finding,
            message=f"Not posted; held for your review. {finding.message}")

    proj = ledger.projection()

    # A stub decomposes a deposit; it does not stitch onto a balance chain, so
    # neither the chain nor the period register can see a second copy of one.
    # Two copies posted two decompositions and doubled the income — the deposit
    # is not marked in any way that the second copy would notice. What it is
    # recognised by is the decomposition it would write.
    description = f"Pay from {facts.employer or 'employer'}"
    if proj.is_pay_decomposed(description, when, str(facts.gross)):
        log.info("post_paystub: pay from %s on %s already decomposed — "
                 "this stub is a duplicate", facts.employer, when)
        return IngestResult(
            doc_id=facts.doc_id, action=DUPLICATE, doc_type=facts.doc_type,
            message=(f"Already broken down — I hold this pay from "
                     f"{facts.employer or 'your employer'} "
                     f"({facts.currency} {facts.net} net) and its deposit. "
                     "Nothing was counted twice."))

    deposit = _net_pay_deposit(proj, facts.net, facts.currency, facts.pay_date)
    if deposit is None:
        log.info("post_paystub: no matching net-pay deposit for %s — awaiting",
                 facts.doc_id[:12])
        ledger.append(statement_held(facts.doc_id, facts.to_dict(), None,
                                     "awaiting_deposit", when,
                                     Provenance(doc_id=facts.doc_id)))
        return IngestResult(
            doc_id=facts.doc_id, action=AWAITING, doc_type=facts.doc_type,
            grade="unverified",
            message=(f"Read your pay from {facts.employer or 'your employer'} "
                     f"(net {facts.currency} {facts.net}); holding until the "
                     "matching deposit is ingested, then I'll break it down."))

    ledger.append(paystub_decomposition(
        facts.gross, facts.net, facts.deductions,
        f"Pay from {facts.employer or 'employer'}", when,
        provenance=facts.provenance("net-pay decomposition")))
    log.info("post_paystub: decomposed pay from %r gross=%s net=%s deductions=%d "
             "against deposit on %s", facts.employer, facts.gross, facts.net,
             len(facts.deductions), deposit.account)
    return IngestResult(
        doc_id=facts.doc_id, action=POSTED, doc_type=facts.doc_type,
        account="Income:Salary", grade="corroborated",
        message=(f"Income posted: gross {facts.currency} {facts.gross}, net "
                 f"{facts.net} matches your deposit — tax, retirement, and "
                 "insurance are now itemized."))


def heal_paystubs(ledger: Ledger) -> int:
    """Post pay stubs held awaiting a deposit that has now arrived — the
    pay-stub mirror of ``heal_gaps``. Returns how many posted."""
    posted = 0
    attempted: set[str] = set()
    while True:
        proj = ledger.projection()
        candidate = None
        for body in proj.open_holds():
            if (body.get("reason") != "awaiting_deposit"
                    or body["doc_id"] in attempted):
                continue
            facts = PayStubFacts.from_dict(body["facts"])
            if _net_pay_deposit(proj, facts.net, facts.currency,
                                facts.pay_date) is not None:
                candidate = facts
                attempted.add(body["doc_id"])
                break
        if candidate is None:
            return posted
        log.info("heal: awaiting pay stub %s now has its deposit — posting",
                 candidate.doc_id[:12])
        if post_paystub(ledger, candidate).action == POSTED:
            posted += 1




__all__ = ['log', '_paystub_diagnose', '_net_pay_deposit', 'post_paystub', 'heal_paystubs']
