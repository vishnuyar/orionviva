"""The ingest pipeline: capture → classify → verify → post.

The shape the whole product turns on, and the place the model finally meets the
trust core. Every file that arrives is:

  1. **Captured raw and encrypted, first, unconditionally.** Nothing
     is judged before it is safely held. Content-addressed, so a re-upload is a
     no-op, not a duplicate.
  2. **Read by a model** — the one place a model is in this path. The read is a
     *proposal*, never trusted on its own.
  3. **Routed by type — via the registry (data, not code).** The doc-type
     registry maps a classified type to a profile; the balance family (checking,
     savings, credit card) shares one profile and goes to the reconciliation
     gate. Anything with no profile yet is *parked*: held and acknowledged ("I
     have this; I can't read it yet"), never discarded. Adding a type is a
     registry row; as more types are registered, parked documents light up
     retroactively — no re-upload.
  4. **Gated by deterministic reconciliation.** A statement posts to the ledger
     only if opening + its transactions reconcile to the printed closing, to the
     cent. Fail, and it is surfaced as a conflict, not posted. The model reads;
     arithmetic certifies.

Across months of the same account the pipeline *stitches*: a later statement's
opening must equal the balance we already hold, or the gap is surfaced (a likely
missing statement) rather than papered over.

The model read is injected (``read_fn``), so everything here is testable offline
with fixtures. Only the real reader touches the network.
"""

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
from .identity import account_key
from .paystub import PayStubFacts
from .raw_store import RawStore
from .registry import (BALANCE_IDENTITY, BROKERAGE_IDENTITY, INVESTMENT,
                       PAYSTUB_IDENTITY, account_kind_for, can_project,
                       identity_of_facts, profile_for)
from .statement import StatementFacts, TxnFact

log = logging.getLogger(__name__)

# Ingest actions, each an honest outcome the caller can report verbatim.
POSTED = "posted"        # reconciled and written to the ledger
PARKED = "parked"        # captured and acknowledged; no projector for it yet
DUPLICATE = "duplicate"  # already ingested (same content hash)
CONFLICT = "conflict"    # recognized, but did not reconcile — not posted
GAP = "gap"              # opening does not continue from the balance we hold
IDENTITY = "identity"    # reconciles, but whose account is ambiguous — ask
AWAITING = "awaiting"    # a pay stub read + verified, waiting for its net-pay deposit


@dataclass
class ModelPhase:
    """One model interaction in a read — the classify pass or the extract pass —
    captured verbatim for the claims layer. A two-phase real read produces
    two of these; each is persisted as its own ReadRecorded."""
    phase: str                       # "classify" | "extract"
    model: str
    prompt_version: str
    raw_text: str
    cost_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    input_mode: str = "text+image"
    parse_ok: bool = True
    error: str | None = None


@dataclass
class ReadResult:
    """What a reader returns for one document: its classification, and — if it is
    a statement — the structured facts. A reader for a non-statement returns
    ``facts=None`` with the type it recognized (e.g. 'pay_stub').

    ``phases`` carries the per-call model records (classify, extract) that the
    pipeline persists to the claims layer. The flat ``raw_*``/``model`` fields are
    the legacy single-call view, kept so offline stubs stay terse; a real
    two-phase read populates ``phases`` instead."""
    doc_type: str
    doc_type_confidence: float
    facts: StatementFacts | None = None
    error: str | None = None
    raw_text: str = ""
    model: str = ""
    prompt_version: str = ""
    input_mode: str = "text+image"
    cost_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    phases: list[ModelPhase] = field(default_factory=list)


@dataclass
class IngestResult:
    doc_id: str
    action: str
    doc_type: str
    account: str | None = None
    grade: str | None = None
    reconciliation: CheckResult | None = None
    finding: ReconciliationFinding | None = None   # why it failed / how it was fixed
    auto_corrected: bool = False
    message: str = ""


ReadFn = Callable[[bytes, str], ReadResult]


def account_id_for(facts: StatementFacts) -> str:
    """A stable account id anchored to the account number (institution + last-4),
    falling back to the label only when no number was extracted — so every month
    of the same account maps to the same ledger account regardless of how the
    statement labels it."""
    return account_key(facts.institution, facts.account_number, facts.account_ref)


def _resolve(proj, facts: StatementFacts):
    # Resolve identity within the same account kind: a card and a checking
    # account with the same holder are different accounts, not an ambiguity.
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

    Ingestion is order-independent *both ways*: a statement parked as a gap posts
    as soon as it connects — **forward** (its opening = the current balance) or
    **backward** (its closing = the earliest opening, a backfill). One post can
    unblock a neighbour, so this cascades until nothing more connects. Only gap
    holds are retried (they reconcile internally); conflict holds wait for a
    human."""
    posted_total = 0
    attempted: set[str] = set()
    while True:
        proj = ledger.projection()
        candidate = None
        for body in proj.gap_holds():
            doc_id = body["doc_id"]
            # Holds are polymorphic — only the balance family stitches this way.
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
    """Re-attempt conflict-held statements that a newly-arrived counterparty can
    now corroborate. The mirror of ``heal_gaps`` for the cross-document rung: a
    card held because its read dropped a payment posts as soon as the checking
    statement that attests the payment lands (order-independent).
    Only conflict holds with an available decisive partner are retried, so a
    genuine misread with no counterpart keeps waiting for a human."""
    from .transfers import account_tokens_from, find_corroborating_legs
    posted_total = 0
    attempted: set[str] = set()
    while True:
        proj = ledger.projection()
        candidate = None
        for body in proj.open_holds():
            doc_id = body["doc_id"]
            # A pay stub or a brokerage statement can also be held as a conflict,
            # and their facts are a different shape entirely — route, never assume.
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


def sweep(ledger: Ledger) -> dict:
    """Run the full order-independent reconciliation + transfer sweep over an
    existing vault: stitch gaps, close conflict-holds a counterparty now
    corroborates, and detect internal transfers among ALL posted movements. Safe
    to run on startup or on demand — it only appends links/heals and is
    idempotent (already-linked movements and resolved holds are skipped). It
    also links statements ingested before any transfer scan ran."""
    from .transfers import link_transfers
    # Measure net change across the whole sweep: corroboration re-posts run their
    # own transfer scan, so the final link_transfers alone undercounts. Diff the
    # projection instead, for an honest summary.
    p0 = ledger.projection()
    links0, sugg0 = len(p0.transfer_links()), len(p0.transfer_suggestions())
    gaps = heal_gaps(ledger)
    corroborated = heal_corroboration(ledger)
    gaps += heal_paystubs(ledger)         # awaiting pay stubs whose deposit is here
    link_transfers(ledger)
    p1 = ledger.projection()
    auto = len(p1.transfer_links()) - links0
    suggested = len(p1.transfer_suggestions()) - sugg0
    if gaps or corroborated or auto or suggested:
        log.info("sweep: %d gaps healed, %d corroborated, %d transfers auto-linked, "
                 "%d suggested", gaps, corroborated, auto, suggested)
    return {"gaps": gaps, "corroborated": corroborated, "auto": auto,
            "suggested": suggested, "links": len(p1.transfer_links())}


def _apply_forced(facts: StatementFacts,
                  finding: ReconciliationFinding) -> StatementFacts:
    """Return a copy of the facts with a forced correction applied. Only ever
    called on a FORCED finding — a correction an independent identity implies."""
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
    """Reconcile a checking statement and, only if it holds, post it. The gate.

    On failure, diagnose deterministically (no model call). A *forced* correction
    — one an independent identity implies and which closes the reconciliation —
    is auto-applied and posted at `corroborated`, and reported. Anything merely
    *suggested* or unlocalized is *held for review* (persisted, never posted).

    ``confirmed_by='human'`` (used when a person has ruled on a held statement)
    posts the closing at `verified`."""
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

    # Cross-document corroboration rung: before asking a human, see if a
    # decisive counterparty movement on another own account attests the missing
    # line. Cheaper than a re-read (no model call), stronger (two issuers agree).
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
    """The cross-document corroboration rung. If the statement's reconciliation
    gap is exactly a decisive unmatched counterparty movement on another of the
    user's own accounts, supply that missing leg — provenance pointing at the
    counterparty document, graded `corroborated`, and marked as an incomplete
    primary read (so the crutch never hides a model-recall problem) — then post.
    The subsequent transfer scan nets the pair. Returns None (→ hold for a human)
    unless the match is decisive; a gap is never closed on a guess."""
    from .transfers import account_tokens_from, find_corroborating_legs, link_transfers

    proj = ledger.projection()
    account = account_id_for(facts)
    kind = account_kind_for(facts.doc_type)
    delta = _gap_delta(facts)
    # Tokens come from the FACTS (this account may not be opened yet — it's the
    # one failing to reconcile), so a counterparty line naming it can be found.
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

    # One supplied leg per counterparty movement — each cites its OWN counterparty
    # document (a missing section may be attested across several statements). The
    # sign is the missing leg's effect on this account (sign of delta).
    sign = Decimal(-1) if delta < 0 else Decimal(1)
    supplied = [TxnFact(
        date=cp.date, description=f"Payment (corroborated by {_name(cp.account)})",
        amount=sign * abs(cp.amount), source_doc_id=cp.provenance.doc_id,
        grade=CORROBORATED,
        note=("supplied by cross-document corroboration; attested by the "
              "counterparty statement, not read from this document")) for cp in legs]
    corrected = replace(facts, transactions=list(facts.transactions) + supplied)
    if not _reconciles(corrected).passed:         # defensive: only post if it closes
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


def _post_reconciled(ledger: Ledger, facts: StatementFacts, recon: CheckResult,
                     finding: ReconciliationFinding | None,
                     auto_corrected: bool, confirmed_by: str = "") -> IngestResult:
    """Write a statement that reconciles: resolve whose account it is (holding
    for confirmation if that's ambiguous), then seed a new account, stitch onto
    the end (forward), backfill in front (backward), or hold it as a gap."""
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
        # counterparty document) and grade (`corroborated`); an ordinary line
        # defaults to this statement and `verified`.
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


def _paystub_diagnose(facts: PayStubFacts) -> ReconciliationFinding:
    """Localize a pay-stub identity failure with arithmetic alone — the same
    finding contract as a statement, a different formula."""
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

    The divergent gate: `gross − deductions = net`. On failure the pay
    stub is held with a localized finding (never guessed). On
    success, it *decomposes* the checking deposit its net explains — gross booked
    as income, deductions into universal buckets, the net counted once — reusing
    the deposit already on the ledger. If the deposit hasn't been ingested yet,
    the income is read and held until it arrives (order-independent, healed)."""
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
    """Post pay stubs that were held awaiting a deposit which has now arrived —
    the pay-stub mirror of the gap/corroboration heals (order-independent)."""
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


def post_brokerage(ledger: Ledger, facts: BrokerageFacts) -> IngestResult:
    """Verify a brokerage statement's internal tally and, only if it holds, record
    its holdings as measurements.

    The divergent gate: `Σ position market_value + cash = total`, a snapshot
    consistency check (not a flow). On failure the statement is held (never
    guessed). On success the account is opened as `investment`, the cash is
    observed as an attested snapshot balance, and each holding is emitted as a
    `PositionObserved` MEASUREMENT — not posted; cash flow over accrual, only
    realized cash flows post. Unrealized gain is never recorded here — it is a
    derived, as-of-date presentation view over these measurements."""
    # The sweep is cash — but a statement may print the cash line as INCLUDING it
    # (one month) or EXCLUDING it (the next), for the very same account. Rather than
    # guess, try both readings and take the one that reconciles **exactly**; if
    # neither closes (or the sweep is absent and they're identical), fall through
    # to the ordinary gate. Decisive-or-hold, the same contract as every other
    # forced correction. Internally we then normalize to "cash includes the sweep",
    # so the cash figure means the same thing across statements — which is what
    # lets the cash flow stitch month to month.
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

    # The cross-account cash flow. When we know the opening cash AND the period's
    # activity, reconcile the cash as a FLOW (opening + Σ activity = closing) and
    # post each realized event so contributions tie to the funding account,
    # income/fees/gains are recognized, and the cash sub-ledger reconciles.
    # Unrealized change never posts.
    #
    # If the statement doesn't print an opening cash figure, the LEDGER already
    # knows it: it is the cash we hold for this account from the previous
    # statement. That is the forward-stitching rule ("its opening is the balance
    # we hold") applied to brokerage cash, so a statement with no opening line
    # can still post its whole activity.
    proj0 = ledger.projection()
    account0 = account_id_for(facts)
    opening_cash, opening_from = facts.opening_cash, "the statement"
    if opening_cash is None and proj0.seen_account(account0):
        held_dated = proj0.balance(account0).dated
        if held_dated and when and held_dated < when:
            opening_cash = proj0.cash_value(account0)
            opening_from = f"the cash we held as of {held_dated}"
            log.info("post_brokerage: no opening cash printed; carrying %s forward "
                     "from %s", opening_cash, held_dated)
    flow = opening_cash is not None and bool(facts.activity)
    if flow:
        effects = [brokerage_cash_effect(a.kind, a.amount) for a in facts.activity]
        cashflow = check_balance_identity(opening_cash, effects, facts.cash)
        if not cashflow.passed:
            log.info("post_brokerage: cash-flow FAILED (%s); holding %s",
                     cashflow.explain(), facts.doc_id[:12])
            finding = ReconciliationFinding(
                reconciles=False, kind="brokerage_cashflow", status=UNLOCALIZED,
                delta=cashflow.delta, confidence=0.1,
                message=(f"The period's activity doesn't reconcile the cash "
                         f"balance (off by {cashflow.delta}) — an activity line "
                         "may be missing. Held for your review."))
            ledger.append(statement_held(facts.doc_id, facts.to_dict(),
                                         finding.to_dict(), "conflict", when,
                                         Provenance(doc_id=facts.doc_id)))
            return IngestResult(
                doc_id=facts.doc_id, action=CONFLICT, doc_type=facts.doc_type,
                grade="conflicted", reconciliation=cashflow, finding=finding,
                message=f"Not posted; held for your review. {finding.message}")

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
        # Cash as a reconciled flow: opening seed (once) + each activity posting +
        # the attested closing. The activity legs carry contributions to Transfers
        # (tied to the funding account), income to Income:*, fees to Expenses,
        # buys/sells to Assets:Investments, and a sell's realized gain to
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
    # Cash: the attested balance at the statement date (closing of the flow, or a
    # lone snapshot on a holdings-only statement).
    ledger.append(closing_balance_observed(
        account, facts.cash, when, facts.provenance("cash balance")))
    # Holdings: dated measurements, NOT postings.
    for p in facts.positions:
        ledger.append(position_observed(
            account, p.instrument, p.units, p.market_value, facts.currency, when,
            cost_basis=p.cost_basis, grade=CORROBORATED,
            provenance=facts.provenance(f"position {p.instrument}")))
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
    elif facts.activity:
        # Never drop what we read in silence: say the activity is held back and
        # why, so an incomplete picture is visibly incomplete.
        log.info("post_brokerage: %d activity item(s) read but NOT posted — no "
                 "opening cash to reconcile the flow against", len(facts.activity))
        message += (f" I also read {len(facts.activity)} activity item(s), but "
                    "without an opening cash balance I can't reconcile them, so "
                    "they are not posted — the holdings above are complete, the "
                    "period's movements are not.")
    return IngestResult(
        doc_id=facts.doc_id, action=POSTED, doc_type=facts.doc_type,
        account=account, grade="corroborated", reconciliation=recon,
        message=message)


def capture_and_ingest(raw: RawStore, ledger: Ledger, data: bytes,
                       read_fn: ReadFn, filename: str = "",
                       captured_at: str = "") -> IngestResult:
    """Raw-capture a file, read it, and either post it or park it — never lose it."""
    doc_id = raw.put(data)                       # (1) capture first, always
    log.info("ingest start: %s (%d bytes) doc_id=%s",
             filename or "<upload>", len(data), doc_id[:12])
    if ledger.projection().is_resolved(doc_id):
        log.info("ingest: doc_id=%s already posted/held — skipping", doc_id[:12])
        return IngestResult(doc_id=doc_id, action=DUPLICATE, doc_type="",
                            message="Already posted or held (same content); no change.")

    try:
        rr = read_fn(data, doc_id)               # (2) the model read (a proposal)
    except Exception as e:                       # a read that threw is recorded, not orphaned
        log.warning("ingest: read raised for doc_id=%s: %s", doc_id[:12], e)
        rr = ReadResult("unknown", 0.0, None, error=f"read failed: {e}",
                        model="(read error)")
    log.info("ingest: read doc_id=%s -> doc_type=%r conf=%.2f facts=%s error=%s",
             doc_id[:12], rr.doc_type, rr.doc_type_confidence,
             rr.facts is not None, rr.error)

    ledger.append(document_captured(             # record that we hold it
        doc_id, filename, len(data), rr.doc_type, rr.doc_type_confidence,
        captured_at, Provenance(doc_id=doc_id)))

    # The claims layer: persist the verbatim model output for any real read. A
    # two-phase read records one ReadRecorded per phase (classify + extract); a
    # legacy single-call reader (or stub) records one via the flat fields.
    if rr.phases:
        for ph in rr.phases:
            ledger.append(read_recorded(
                doc_id, ph.model, ph.prompt_version, ph.input_mode, ph.raw_text,
                ph.cost_usd, ph.input_tokens, ph.output_tokens, ph.parse_ok,
                ph.error, captured_at, Provenance(doc_id=doc_id), phase=ph.phase))
            log.info("ingest: stored ReadRecorded phase=%s (model=%s cost=$%.4f "
                     "parse_ok=%s resp_chars=%d)", ph.phase, ph.model, ph.cost_usd,
                     ph.parse_ok, len(ph.raw_text))
    elif rr.model:
        ledger.append(read_recorded(
            doc_id, rr.model, rr.prompt_version, rr.input_mode, rr.raw_text,
            rr.cost_usd, rr.input_tokens, rr.output_tokens,
            rr.facts is not None, rr.error, captured_at, Provenance(doc_id=doc_id)))
        log.info("ingest: stored ReadRecorded (model=%s cost=$%.4f parse_ok=%s "
                 "resp_chars=%d)", rr.model, rr.cost_usd, rr.facts is not None,
                 len(rr.raw_text))

    # (3) route by type — the registry decides what has a projector (data, not
    # code): the balance family (checking / savings / card) posts; the rest parks.
    if rr.facts is not None and can_project(rr.doc_type):
        # (4) route by the profile's identity to the right gate + post-projector
        # (the divergent-profile dispatch): a pay stub is not a balance.
        profile = profile_for(rr.doc_type)
        identity = profile.identity if profile is not None else ""
        if identity == PAYSTUB_IDENTITY:
            res = post_paystub(ledger, rr.facts)
        elif identity == BROKERAGE_IDENTITY:
            res = post_brokerage(ledger, rr.facts)
        else:
            res = post_statement(ledger, rr.facts)
        if res.action == POSTED:
            healed = heal_gaps(ledger)           # a new post may unblock waiting statements
            # a newly-arrived counterparty may corroborate a conflict-held statement
            healed += heal_corroboration(ledger)
            # a newly-arrived deposit may let a waiting pay stub decompose it
            healed += heal_paystubs(ledger)
            if healed:
                log.info("ingest: healed %d previously-held statement(s)", healed)
            # (5) a new account's movements may complete an internal transfer with
            # movements already held — detect and net. Deferred import
            # avoids an ingest→ingest cycle at module load.
            from .transfers import link_transfers
            link_transfers(ledger)
        log.info("ingest done: doc_id=%s -> %s (%s)", doc_id[:12], res.action, res.grade)
        return res

    reason = rr.error or f"no projector yet for '{rr.doc_type or 'unknown'}'"
    log.info("ingest done: doc_id=%s -> parked (%s)", doc_id[:12], reason)
    return IngestResult(
        doc_id=doc_id, action=PARKED, doc_type=rr.doc_type,
        message=(f"Captured and held; not yet readable ({reason}). It will be "
                 "understood when a projector for its type arrives."))
