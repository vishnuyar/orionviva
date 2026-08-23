"""Balance-statement reconciliation and projection."""

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

def account_id_for(facts: StatementFacts) -> str:
    """A stable account id anchored to the account number (institution + last-4).

    Falls back to the label only when no number was extracted, so every month of
    one account maps to one ledger account however the statement labels it."""
    return account_key(facts.institution, facts.account_number, facts.account_ref)


def _resolve(proj, facts: StatementFacts):
    # Identity resolves within one account kind: a card and a checking account
    # with the same holder are different accounts, not an ambiguity.
    return proj.resolve(facts.institution, facts.account_number,
                        facts.account_ref, facts.account_names,
                        kind=account_kind_for(facts.doc_type))


def _connects(facts: StatementFacts, proj, account: str) -> str:
    """How a reconciled statement attaches to its account's existing chain:
    'forward' (its opening = the current balance), 'backward' (its closing = the
    earliest opening — a backfill), or '' (a gap)."""
    if facts.opening_amount == proj.running_balance(account):
        return "forward"
    if facts.closing_amount == proj.earliest_opening(account):
        return "backward"
    return ""


def heal_gaps(ledger: Ledger) -> int:
    """Re-post gap-held statements that now stitch onto their account's chain.

    Order-independent both ways: a gap-held statement posts as soon as it
    connects forward (its opening = the current balance) or backward (its
    closing = the earliest opening). One post can unblock a neighbour, so this
    cascades until nothing more connects. Only gap holds are retried; conflict
    holds wait for a person. Returns how many posted."""
    posted_total = 0
    attempted: set[str] = set()
    while True:
        proj = ledger.projection()
        candidate = None
        for body in proj.gap_holds():
            doc_id = body["doc_id"]
            # Holds are polymorphic; only the balance family stitches this way.
            if (doc_id in attempted
                    or identity_of_facts(body.get("facts")) != BALANCE_IDENTITY):
                continue
            facts = StatementFacts.from_dict(body["facts"])
            if _connects(facts, proj, _resolve(proj, facts).account_id):
                candidate = facts
                attempted.add(doc_id)
                break
        if candidate is None:
            return posted_total
        log.info("heal: previously-held %s now stitches — re-posting",
                 candidate.doc_id[:12])
        if post_statement(ledger, candidate).action == POSTED:
            posted_total += 1


def _reconciles(facts: StatementFacts) -> CheckResult:
    return check_balance_identity(
        facts.opening_amount, [t.amount for t in facts.transactions],
        facts.closing_amount)


def _gap_delta(facts: StatementFacts) -> Decimal:
    total = sum((t.amount for t in facts.transactions), start=Decimal("0"))
    return facts.closing_amount - (facts.opening_amount + total)


def heal_corroboration(ledger: Ledger) -> int:
    """Re-attempt conflict-held statements a newly-arrived counterparty can now
    corroborate — the cross-document rung's mirror of ``heal_gaps``.

    A card held because its read dropped a payment posts as soon as the checking
    statement attesting that payment lands, in either arrival order. Only
    conflict holds with a decisive partner are retried; a misread with no
    counterpart keeps waiting for a person. Returns how many posted."""
    from .transfers import account_tokens_from, find_corroborating_legs
    posted_total = 0
    attempted: set[str] = set()
    while True:
        proj = ledger.projection()
        candidate = None
        for body in proj.open_holds():
            doc_id = body["doc_id"]
            # A pay stub or brokerage statement can also be held as a conflict,
            # and its facts are a different shape; route on the identity.
            if (body.get("reason") != "conflict" or doc_id in attempted
                    or identity_of_facts(body.get("facts")) != BALANCE_IDENTITY):
                continue
            facts = StatementFacts.from_dict(body["facts"])
            toks = account_tokens_from(facts.institution, facts.account_number,
                                       facts.account_ref)
            if find_corroborating_legs(
                    proj, account_id_for(facts), account_kind_for(facts.doc_type),
                    _gap_delta(facts), facts.currency, facts.opening_date,
                    facts.closing_date, own_tokens=toks):
                candidate = facts
                attempted.add(doc_id)
                break
        if candidate is None:
            return posted_total
        log.info("heal: conflict-held %s now corroborated — re-posting",
                 candidate.doc_id[:12])
        if post_statement(ledger, candidate).action == POSTED:
            posted_total += 1


def _apply_forced(facts: StatementFacts,
                  finding: ReconciliationFinding) -> StatementFacts:
    """Return a copy of the facts with a forced correction applied.

    Only valid for a finding at status FORCED; any other kind is returned
    unchanged."""
    if finding.kind == "amount_misread" and finding.target_index is not None:
        txns = list(facts.transactions)
        i = finding.target_index
        txns[i] = replace(txns[i], amount=Decimal(finding.implied))
        return replace(facts, transactions=txns)
    if finding.kind == "balance_misread":
        return replace(facts, closing_amount=Decimal(finding.implied))
    return facts


def post_statement(ledger: Ledger, facts: StatementFacts,
                   confirmed_by: str = "") -> IngestResult:
    """Reconcile a balance-family statement and, only if it holds, post it.

    The reconciliation ladder, in order, stopping at the first rung that closes
    the gap:

      0. the statement reconciles as read → post at `corroborated`;
      1. ``diagnose`` (arithmetic only, no model call) returns a FORCED
         correction that closes it → apply it and post at `corroborated`,
         reporting the correction on the result;
      2. a decisive counterparty movement on another own account supplies the
         missing leg → post at `corroborated` (see ``_try_corroboration``);
      3. otherwise hold for review, persisted and not posted.

    A SUGGESTED or unlocalized finding never auto-applies. ``confirmed_by=
    'human'`` posts the closing at `verified` instead. Returns an
    ``IngestResult`` whose ``action`` is POSTED, CONFLICT, GAP or IDENTITY."""
    log.info("post_statement: account=%s opening=%s closing=%s txns=%d",
             account_id_for(facts), facts.opening_amount, facts.closing_amount,
             len(facts.transactions))
    recon = _reconciles(facts)
    if recon.passed:
        log.info("post_statement: reconciles on first read")
        return _post_reconciled(ledger, facts, recon, finding=None,
                                auto_corrected=False, confirmed_by=confirmed_by)

    finding = diagnose(facts)
    log.info("post_statement: did NOT reconcile (%s); diagnosis=%s/%s: %s",
             recon.explain(), finding.status, finding.kind, finding.message)
    if finding.status == FORCED:
        corrected = _apply_forced(facts, finding)
        recon2 = _reconciles(corrected)
        if recon2.passed:
            log.info("post_statement: forced correction applied -> reconciles")
            res = _post_reconciled(ledger, corrected, recon2, finding=finding,
                                   auto_corrected=True)
            if res.action == POSTED:
                res.message = f"{finding.message} {res.message}"
            return res

    # Rung 2: before asking a person, see whether a decisive counterparty
    # movement on another own account attests the missing line.
    corroborated = _try_corroboration(ledger, facts)
    if corroborated is not None:
        return corroborated

    log.info("post_statement: holding for review (doc_id=%s)", facts.doc_id[:12])
    ledger.append(statement_held(
        facts.doc_id, facts.to_dict(), finding.to_dict(), "conflict",
        facts.closing_date, Provenance(doc_id=facts.doc_id)))
    return IngestResult(
        doc_id=facts.doc_id, action=CONFLICT, doc_type=facts.doc_type,
        account=account_id_for(facts), grade="conflicted",
        reconciliation=recon, finding=finding,
        message=f"Not posted; held for your review. {finding.message}")


def _try_corroboration(ledger: Ledger, facts: StatementFacts) -> IngestResult | None:
    """Rung 2 of the ladder: close the gap from a counterparty document.

    When the reconciliation gap is exactly explained by decisive unmatched
    movements on other own accounts, each is supplied as a transaction whose
    provenance is the counterparty document, graded `corroborated` and noted as
    not read from this document; the statement is then posted and a transfer
    scan nets the pair.

    Returns None — meaning "carry on to the hold" — unless the match is
    decisive and the supplied legs make the statement reconcile exactly."""
    from .transfers import account_tokens_from, find_corroborating_legs, link_transfers

    proj = ledger.projection()
    account = account_id_for(facts)
    kind = account_kind_for(facts.doc_type)
    delta = _gap_delta(facts)
    # Tokens come from the facts, not the projection: this account may not be
    # open yet, and a counterparty line naming it still has to be findable.
    own_tokens = account_tokens_from(facts.institution, facts.account_number,
                                     facts.account_ref)
    legs = find_corroborating_legs(proj, account, kind, delta, facts.currency,
                                   facts.opening_date, facts.closing_date,
                                   own_tokens=own_tokens)
    if not legs:
        return None

    def _name(acct: str) -> str:
        try:
            return proj.account_info(acct).name or acct
        except Exception:
            return acct

    # One supplied leg per counterparty movement, each citing its own
    # counterparty document — a missing section may be attested across several.
    # The sign is the missing leg's effect on this account (the sign of delta).
    sign = Decimal(-1) if delta < 0 else Decimal(1)
    supplied = [TxnFact(
        date=cp.date, description=f"Payment (corroborated by {_name(cp.account)})",
        amount=sign * abs(cp.amount), source_doc_id=cp.provenance.doc_id,
        grade=CORROBORATED,
        note=("supplied by cross-document corroboration; attested by the "
              "counterparty statement, not read from this document")) for cp in legs]
    corrected = replace(facts, transactions=list(facts.transactions) + supplied)
    if not _reconciles(corrected).passed:         # only post if it closes
        return None
    who = ", ".join(sorted({_name(cp.account) for cp in legs}))
    finding = ReconciliationFinding(
        reconciles=False, kind="cross_document", status=FORCED, delta=str(delta),
        target=f"{len(legs)} missing leg(s) supplied from {who}",
        implied=str(delta), confidence=0.95,
        message=(f"This statement was off by {delta}; {len(legs)} matching "
                 f"movement(s) on your {who} attest the missing line(s). I "
                 "supplied them (corroborated) and linked them as transfers — "
                 "this document's own read was incomplete."))
    log.info("post_statement: cross-document corroboration closes the gap for %s "
             "with %d leg(s) (delta=%s)", facts.doc_id[:12], len(legs), delta)
    res = _post_reconciled(ledger, corrected, _reconciles(corrected),
                           finding=finding, auto_corrected=True)
    if res.action == POSTED:
        res.message = f"{finding.message} {res.message}"
        link_transfers(ledger)                    # net the newly-completed pair(s)
    return res


def _period_already_posted(ledger: Ledger, proj, account: str,
                           facts) -> IngestResult | None:
    """Whether this account's period is already on the ledger, and what to do.

    The byte-hash guard in `capture_and_ingest` only catches a file that is
    byte-identical to one already captured, and banks do not re-serve identical
    PDFs — producer metadata and creation timestamps differ, so a re-downloaded
    statement arrives with a new doc_id and posts its transactions a second
    time. The balance chain catches most of those by accident, because a second
    copy opens where the first one opened and no longer continues from the
    balance held; it does not catch a period whose movements net to zero, and it
    does not exist at all for a brokerage snapshot.

    A document is identified here by whose account it is and the day its period
    ends. On a collision the closing figure decides what happened:

      - **same closing** → the same statement arriving twice. Skipped.
      - **different closing** → the issuer re-issued the period with different
        numbers. Held, because which one is true is not ours to decide.

    The closing figure is a sound discriminator precisely because posting is
    gated on `opening + Σ(effect) = closing`: a re-issue that changes any
    movement's amount must change the closing too, or it would not have
    reconciled. A re-issue that changes only wording leaves every figure this
    ledger holds identical, and skipping it changes nothing.
    """
    seen = proj.posted_period(account, facts.period_end)
    if seen is None:
        return None
    prior_doc, prior_closing = seen
    closing = getattr(facts, "closing_amount", None)
    if closing is None:                       # a snapshot: its total is its figure
        closing = getattr(facts, "total", None)

    if str(closing) == str(prior_closing):
        log.info("post: %s already posted for %s period ending %s — skipping",
                 prior_doc[:12], account, facts.period_end)
        return IngestResult(
            doc_id=facts.doc_id, action=DUPLICATE, doc_type=facts.doc_type,
            account=account,
            message=("Already posted — this is the same statement for "
                     f"{facts.period_end}, which I read on an earlier copy. "
                     "Nothing was counted twice."))

    log.info("post: period %s on %s already posted by %s at %s; this copy closes "
             "at %s — holding as a re-issue", facts.period_end, account,
             prior_doc[:12], prior_closing, closing)
    ledger.append(statement_held(
        facts.doc_id, facts.to_dict(),
        {"kind": "reissue", "prior_doc_id": prior_doc,
         "prior_closing": str(prior_closing), "closing": str(closing),
         "period_end": facts.period_end,
         "message": "another statement already covers this period"},
        "reissue", facts.period_end, Provenance(doc_id=facts.doc_id)))
    return IngestResult(
        doc_id=facts.doc_id, action=CONFLICT, doc_type=facts.doc_type,
        account=account, grade="conflicted",
        message=(f"I already hold a statement for {facts.period_end} on this "
                 f"account closing at {prior_closing}; this one closes at "
                 f"{closing}. One of them supersedes the other and I will not "
                 "guess which — held for your review."))


def _post_reconciled(ledger: Ledger, facts: StatementFacts, recon: CheckResult,
                     finding: ReconciliationFinding | None,
                     auto_corrected: bool, confirmed_by: str = "") -> IngestResult:
    """Write a statement that reconciles.

    Resolves whose account it is — holding for confirmation when that is
    ambiguous — then seeds a new account, stitches onto the end (forward),
    backfills in front (backward), or holds it as a gap."""
    proj = ledger.projection()
    res = _resolve(proj, facts)
    if res.verdict == "ambiguous":
        log.info("_post_reconciled: identity AMBIGUOUS for %s — holding (%s)",
                 res.key, res.reason)
        ledger.append(statement_held(
            facts.doc_id, facts.to_dict(),
            {"kind": "identity", "candidate": res.candidate,
             "candidate_name": res.candidate_name, "key": res.key,
             "message": res.reason}, "identity",
            facts.closing_date, Provenance(doc_id=facts.doc_id)))
        return IngestResult(
            doc_id=facts.doc_id, action=IDENTITY, doc_type=facts.doc_type,
            account=res.candidate, grade="conflicted",
            message=(f"I read this statement, but whose account it is is unclear: "
                     f"{res.reason}. Held for you to confirm."))
    account = res.account_id

    # Whose account and which period are both known only here, which is why the
    # duplicate guard lives at the post gate rather than at capture.
    already = _period_already_posted(ledger, proj, account, facts)
    if already is not None:
        return already

    if not proj.is_seeded(account):
        kind = account_kind_for(facts.doc_type)   # depository | liability, from the registry
        log.info("_post_reconciled: opening new %s account %s (%s %s) seeded at %s",
                 kind, account, facts.account_ref, facts.currency,
                 facts.opening_amount)
        ledger.append(account_opened(
            account, kind, facts.account_ref or account,
            facts.currency, facts.opening_date,
            institution=facts.institution, account_number=facts.account_number,
            account_names=facts.account_names))
        ledger.append(opening_balance_observed(
            account, facts.opening_amount, facts.opening_date,
            facts.opening_provenance()))
    else:
        how = _connects(facts, proj, account)
        if how == "forward":
            log.info("_post_reconciled: forward-stitching onto %s at %s",
                     account, facts.opening_amount)
            # no opening event — the prior closing already is this opening
        elif how == "backward":
            log.info("_post_reconciled: backfilling %s in front (opening %s "
                     "re-seats the OBE)", account, facts.opening_amount)
            ledger.append(opening_balance_observed(
                account, facts.opening_amount, facts.opening_date,
                facts.opening_provenance()))
        else:
            prior = proj.running_balance(account)
            log.info("_post_reconciled: GAP — opening %s / closing %s connect to "
                     "neither (held=%s, earliest=%s); holding", facts.opening_amount,
                     facts.closing_amount, prior, proj.earliest_opening(account))
            ledger.append(statement_held(
                facts.doc_id, facts.to_dict(), None, "gap",
                facts.closing_date, Provenance(doc_id=facts.doc_id)))
            return IngestResult(
                doc_id=facts.doc_id, action=GAP, doc_type=facts.doc_type,
                account=account, grade="conflicted", reconciliation=recon,
                message=(f"This statement ({facts.opening_date} – "
                         f"{facts.closing_date}) opens at {facts.opening_amount}, "
                         f"which doesn't continue from the balance I hold ({prior}). "
                         "A statement between them looks missing — held, so I don't "
                         "invent the gap; it will slot in when the connector arrives."))

    kind = account_kind_for(facts.doc_type)   # picks the kind-aware counter-leg
    for t in facts.transactions:
        # A corroboration-supplied leg carries its own provenance (the
        # counterparty document) and grade; an ordinary line defaults to this
        # statement and `verified`.
        ledger.append(simple_transaction(
            account, t.amount, t.description, t.date,
            provenance=t.provenance(facts.doc_id),
            account_grade=(t.grade or VERIFIED), kind=kind))
    ledger.append(closing_balance_observed(
        account, facts.closing_amount, facts.closing_date,
        facts.closing_provenance(), confirmed_by=confirmed_by))
    log.info("_post_reconciled: posted %d transactions + closing %s to %s%s",
             len(facts.transactions), facts.closing_amount, account,
             " (human-confirmed)" if confirmed_by == "human" else "")

    grade = "verified" if confirmed_by == "human" else "corroborated"
    return IngestResult(
        doc_id=facts.doc_id, action=POSTED, doc_type=facts.doc_type,
        account=account, grade=grade, reconciliation=recon,
        finding=finding, auto_corrected=auto_corrected,
        message=(f"Posted and reconciled: balance {facts.closing_amount} as of "
                 f"{facts.closing_date}."))




__all__ = ['log', 'account_id_for', '_resolve', '_connects', 'heal_gaps', '_reconciles', '_gap_delta', 'heal_corroboration', '_apply_forced', 'post_statement', '_try_corroboration', '_period_already_posted', '_post_reconciled']
