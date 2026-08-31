"""Brokerage snapshot reconciliation and projection."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, replace
from decimal import Decimal
from typing import Callable

from vivacore.verify.arithmetic import (CheckResult, check_balance_identity,
                                        check_brokerage_identity,
                                        check_paystub_identity)

from ..ledger.events import (CORROBORATED, VERIFIED, Provenance, account_opened,
                             brokerage_activity_held,
                             brokerage_activity_resolved,
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

from .statement_projector import account_id_for, _period_already_posted

def post_brokerage(ledger: Ledger, facts: BrokerageFacts) -> IngestResult:
    """Verify a brokerage statement's internal tally and, only if it holds,
    record its holdings as measurements.

    The gate is the snapshot identity `Σ position market_value + cash = total`.
    On failure the statement is held. On success the account is opened as
    `investment`, the cash is observed as an attested balance, and each holding
    is emitted as a `PositionObserved` measurement rather than a posting — only
    realized cash flows post, and unrealized gain is a derived view over these
    measurements, never a ledger fact.

    When the period's activity is present and an opening cash figure is known
    (printed, or carried forward from the ledger), the cash is additionally
    reconciled as a flow and each activity line posts."""
    # A statement may print the cash line as including the money-market sweep or
    # excluding it, and the same account can do either month to month.
    # `resolve_sweep_cash` picks whichever reading reconciles exactly and
    # normalizes to "cash includes the sweep", so the figure means one thing
    # across statements and the cash flow can stitch month to month.
    from .brokerage import is_cash_row, resolve_sweep_cash
    when = facts.as_of
    sweep_total = sum((p.market_value for p in facts.positions
                       if is_cash_row(p.instrument)), start=Decimal("0"))
    facts, sweep_note = resolve_sweep_cash(facts)
    if sweep_note:
        log.info("post_brokerage: sweep holding(s) worth %s treated as cash (%s)",
                 sweep_total, sweep_note)

    recon = check_brokerage_identity(
        [p.market_value for p in facts.positions], facts.cash, facts.total)
    if not recon.passed:
        log.info("post_brokerage: internal tally FAILED (%s); holding %s",
                 recon.explain(), facts.doc_id[:12])
        finding = ReconciliationFinding(
            reconciles=False, kind="brokerage_tally", status=UNLOCALIZED,
            delta=recon.delta, confidence=0.1,
            message=(f"The holdings and cash don't add up to the stated total "
                     f"(off by {recon.delta}) — a position may be misread. Held "
                     "for your review."))
        ledger.append(statement_held(facts.doc_id, facts.to_dict(),
                                     finding.to_dict(), "conflict", when,
                                     Provenance(doc_id=facts.doc_id)))
        return IngestResult(
            doc_id=facts.doc_id, action=CONFLICT, doc_type=facts.doc_type,
            grade="conflicted", reconciliation=recon, finding=finding,
            message=f"Not posted; held for your review. {finding.message}")

    # The cash flow. With an opening cash figure and the period's activity, the
    # cash reconciles as a flow (opening + Σ activity = closing) and each
    # realized event posts. When the statement prints no opening figure, the
    # cash held for this account from the previous statement is carried forward
    # — the forward-stitching rule applied to brokerage cash.
    proj0 = ledger.projection()
    account0 = account_id_for(facts)

    # A snapshot has no balance chain to fall foul of, so a second copy of one
    # posts its whole activity again with nothing to stop it. This is that stop.
    already = _period_already_posted(ledger, proj0, account0, facts)
    if already is not None:
        return already

    opening_cash, opening_from = facts.opening_cash, "the statement"
    if opening_cash is None and proj0.seen_account(account0):
        held_dated = proj0.balance(account0).dated
        if held_dated and when and held_dated < when:
            opening_cash = proj0.cash_value(account0)
            opening_from = f"the cash we held as of {held_dated}"
            log.info("post_brokerage: no opening cash printed; carrying %s forward "
                     "from %s", opening_cash, held_dated)
    flow = opening_cash is not None and bool(facts.activity)
    activity_issue = ""
    activity_finding = None
    if flow:
        effects = [brokerage_cash_effect(a.kind, a.amount) for a in facts.activity]
        cashflow = check_balance_identity(opening_cash, effects, facts.cash)
        if not cashflow.passed:
            log.info("post_brokerage: cash-flow FAILED (%s); holding %s",
                     cashflow.explain(), facts.doc_id[:12])
            activity_finding = ReconciliationFinding(
                reconciles=False, kind="brokerage_cashflow", status=UNLOCALIZED,
                delta=cashflow.delta, confidence=0.1,
                message=(f"The period's activity doesn't reconcile the cash "
                         f"balance (off by {cashflow.delta}) — an activity line "
                         "may be missing. Held for your review."))
            activity_issue = activity_finding.message
            flow = False
    elif facts.activity:
        activity_finding = ReconciliationFinding(
            reconciles=False, kind="brokerage_cashflow", status=UNLOCALIZED,
            delta="0", confidence=0.1,
            message=("The period's activity has no opening cash balance to "
                     "reconcile against. Held for your review."))
        activity_issue = activity_finding.message

    proj = ledger.projection()
    account = account_id_for(facts)
    seeding = not proj.seen_account(account)
    if seeding:
        log.info("post_brokerage: opening investment account %s (%s) at %s",
                 account, facts.account_ref, when)
        ledger.append(account_opened(
            account, INVESTMENT, facts.account_ref or account, facts.currency,
            when, institution=facts.institution,
            account_number=facts.account_number,
            account_names=facts.account_names))

    if flow:
        # Cash as a reconciled flow: the opening seed (once), each activity
        # posting, then the attested closing. The activity legs carry
        # contributions to Transfers, income to Income:*, fees to Expenses,
        # buys and sells to Assets:Investments, and a sell's realized gain to
        # Income:CapitalGains.
        if seeding:
            ledger.append(opening_balance_observed(
                account, opening_cash, when,
                facts.provenance(f"opening cash (from {opening_from})")))
        for a in facts.activity:
            ledger.append(brokerage_activity_transaction(
                account, a.kind, a.amount, a.description, a.date or when,
                instrument=a.instrument, realized_gain=a.realized_gain,
                provenance=facts.provenance(f"{a.kind} {a.instrument}".strip())))
    # Cash: the attested balance at the statement date — the closing of the
    # flow, or a lone snapshot on a holdings-only statement.
    ledger.append(closing_balance_observed(
        account, facts.cash, when, facts.provenance("cash balance")))
    # Holdings: dated measurements, not postings.
    for p in facts.positions:
        ledger.append(position_observed(
            account, p.instrument, p.units, p.market_value, facts.currency, when,
            cost_basis=p.cost_basis, grade=CORROBORATED,
            provenance=facts.provenance(f"position {p.instrument}")))
    if activity_finding is not None:
        # Snapshot posting and activity quarantine remain independently visible.
        ledger.append(brokerage_activity_held(
            facts.doc_id, facts.to_dict(), activity_finding.to_dict(), when,
            Provenance(doc_id=facts.doc_id)))
    log.info("post_brokerage: %s recorded cash %s + %d position(s)%s, total %s "
             "as of %s", account, facts.cash, len(facts.positions),
             f" + {len(facts.activity)} activity" if flow else "", facts.total, when)
    message = (f"Holdings recorded: {len(facts.positions)} position(s) plus cash "
               f"{facts.currency} {facts.cash}, total {facts.total} as of {when}.")
    if sweep_note:
        message += (f" Its money-market sweep ({facts.currency} {sweep_total}) is "
                    f"counted as cash — {sweep_note}.")
    if flow:
        message += f" {len(facts.activity)} activity item(s) posted."
    elif activity_issue:
        message += (f" I also read {len(facts.activity)} activity item(s), but "
                    f"they are not posted: {activity_issue} The holdings snapshot "
                    "above remains recorded because it reconciles independently.")
    elif facts.activity:
        log.info("post_brokerage: %d activity item(s) read but NOT posted — no "
                 "opening cash to reconcile the flow against", len(facts.activity))
        message += (f" I also read {len(facts.activity)} activity item(s), but "
                    "without an opening cash balance I can't reconcile them, so "
                    "they are not posted — the holdings above are complete, the "
                    "period's movements are not.")
    return IngestResult(
        doc_id=facts.doc_id, action=POSTED, doc_type=facts.doc_type,
        account=account, grade="corroborated", reconciliation=recon,
        finding=activity_finding, message=message)


def apply_brokerage_activity_correction(
        ledger: Ledger, doc_id: str, activity: list,
        opening_cash: Decimal | str | None = None) -> IngestResult:
    """Reconcile and atomically replay a held brokerage activity stream.

    The holdings snapshot is unchanged. A successful replay appends the
    corrected movements and closes the durable activity hold.
    """
    outcome: list[IngestResult] = []

    def decide(projection):
        body = next((item for item in projection.open_activity_holds()
                     if item.get("doc_id") == doc_id), None)
        if body is None:
            raise ValueError(f"no brokerage activity held for {doc_id}")
        facts = BrokerageFacts.from_dict(body["facts"])
        corrected = replace(
            facts, activity=list(activity),
            opening_cash=(Decimal(opening_cash) if opening_cash is not None
                          else facts.opening_cash))
        if corrected.opening_cash is None:
            raise ValueError("brokerage activity correction needs opening_cash")
        effects = [brokerage_cash_effect(item.kind, item.amount)
                   for item in corrected.activity]
        recon = check_balance_identity(corrected.opening_cash, effects,
                                       corrected.cash)
        if not recon.passed:
            finding = ReconciliationFinding(
                reconciles=False, kind="brokerage_cashflow", status=UNLOCALIZED,
                delta=str(recon.delta), confidence=0.1,
                message=(f"The corrected activity still does not reconcile the "
                         f"cash balance (off by {recon.delta}). Held for review."))
            outcome.append(IngestResult(
                doc_id=doc_id, action=CONFLICT, doc_type=corrected.doc_type,
                grade="conflicted", reconciliation=recon, finding=finding,
                message=finding.message))
            return (brokerage_activity_held(
                doc_id, corrected.to_dict(), finding.to_dict(), corrected.as_of,
                Provenance(doc_id=doc_id)),)

        account = account_id_for(corrected)
        events = [brokerage_activity_transaction(
            account, item.kind, item.amount, item.description,
            item.date or corrected.as_of, instrument=item.instrument,
            realized_gain=item.realized_gain,
            provenance=corrected.provenance(
                f"{item.kind} {item.instrument}".strip()))
            for item in corrected.activity]
        events.append(brokerage_activity_resolved(
            doc_id, corrected.as_of, Provenance(doc_id=doc_id)))
        outcome.append(IngestResult(
            doc_id=doc_id, action=POSTED, doc_type=corrected.doc_type,
            account=account, grade="verified", reconciliation=recon,
            message=(f"{len(corrected.activity)} corrected activity item(s) "
                     "posted.")))
        return tuple(events)

    # Movements and their resolution event append under one writer lock.
    ledger.append_atomically(decide)
    return outcome[0]




__all__ = ['log', 'post_brokerage', 'apply_brokerage_activity_correction']
