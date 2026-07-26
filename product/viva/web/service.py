"""The surface's service layer — pure functions from a vault to JSON payloads.

Deliberately separate from the HTTP plumbing so it is all testable offline. Each
function reads (or acts on) the vault and returns plain dicts the page renders.
The number, its grade, and its coverage come straight from the answer path; the
*provenance is present in every payload but kept quiet* — the page shows the
picture and the interactions, and only surfaces a source on request.
"""

from __future__ import annotations

import logging
from decimal import Decimal

from ..answer import answer_spending, answer_total, coverage_summary
from ..ingest import (SEED_CATEGORIES, apply_human_correction,
                      apply_identity_ruling, assign_category,
                      assign_merchant_category, capture_and_ingest,
                      confirm_transfer, held_items, other_holds,
                      reject_transfer)
from ..ingest.identity import masked
from ..ledger.merchants import normalize_merchant as normalize
from ..ledger import UnknownAccountError
from ..vault import Vault

log = logging.getLogger("viva.web.service")


def overview(vault: Vault) -> dict:
    """The dashboard payload: total, each account with a quiet grade, coverage,
    and the count of items awaiting the person's review."""
    proj = vault.ledger.projection()             # the cached live projection
    total = answer_total(proj)
    accounts = []
    for info in proj.account_infos():
        if info.kind not in ("depository", "liability", "investment"):
            continue
        ba = proj.balance(info.account)
        liability = info.kind == "liability"
        investment = info.kind == "investment"
        # An investment account's headline is its TOTAL value — cash + the latest
        # measured holdings (Slice 6) — not the bare cash balance.
        amount = proj.account_value(info.account) if investment else (
            abs(ba.amount) if liability else ba.amount)
        row = {
            "account": info.account, "name": info.name or info.account,
            "currency": info.currency,
            # A liability's balance is money owed; show a positive owed figure and
            # let the page label it, so the sign convention never confuses a person.
            "amount": str(amount),
            "kind": info.kind, "liability": liability, "investment": investment,
            "grade": ba.grade, "as_of": ba.dated,
            "institution": info.institution, "number": masked(info.number),
            "holders": info.names}
        if investment:
            ug = proj.unrealized_gain(info.account)
            as_of, mixed = proj.holdings_as_of(info.account)
            row["holdings"] = str(proj.holdings_value(info.account))
            row["cash"] = str(proj.cash_value(info.account))
            row["unrealized_gain"] = str(ug) if ug is not None else None
            # The composed total is only good as of its OLDEST part; say so.
            row["as_of"] = as_of or row["as_of"]
            row["mixed_as_of"] = mixed
        accounts.append(row)
    income = proj.income_by_currency()
    pending_paystubs = [b for b in proj.open_holds()
                        if "gross" in b.get("facts", {})]
    return {
        "total": total.to_dict(),
        "accounts": accounts,
        "coverage": coverage_summary(proj).text,
        "spending": answer_spending(proj).to_dict(),
        "spending_by_category": {c: str(a) for c, a
                                 in proj.spending_by_category().items()},
        # How much of the spending figure rests on weak evidence, and what was
        # kept out of it and why (Slice 6.5) — the number states its own doubt.
        "provisional_spending": str(proj.provisional_spending()),
        # Money whose components are known but whose PROPORTIONS are not
        # (Slice 9a). Its own line, deliberately: folding it into spending
        # would overstate and dropping it would understate, so the headline
        # says "X spent, plus Y I can't split yet" and names the document.
        "undecomposed": {k: (str(v) if not isinstance(v, list) else v)
                         for k, v in proj.undecomposed().items()},
        # The chart of accounts your own rulings built — asserted, not issued.
        "ruled_accounts": [
            {**row, "paid": str(row["paid"])}
            for row in sorted(proj.ruled_accounts().values(),
                              key=lambda r: -r["paid"])],
        "excluded_from_spending": [
            {"description": m.description, "amount": str(abs(m.amount)),
             "account": m.account, "date": m.date, "reason": m.nature_reason,
             "nature": m.nature, "provisional": m.provisional}
            for m in proj.excluded_from_spending()],
        "spending_by_subcategory": {c: str(a) for c, a
                                    in proj.spending_by_subcategory().items()},
        "income": {c: str(v) for c, v in income.items()},
        "income_breakdown": _income_breakdown(proj),
        "positions": [p.to_dict() for p in proj.positions()],
        "review_count": len(held_items(proj)),
        # Held documents with no fix-it affordance yet (pay stub, brokerage) —
        # listed so nothing the system is sitting on is invisible.
        "other_holds": other_holds(proj),
        "transfer_review_count": len(proj.transfer_suggestions()),
        "paystub_review_count": len(pending_paystubs),
        "uncategorized_count": len(proj.uncategorized_expenses()),
        "unknown_merchant_count": len(proj.uncategorized_merchants()),
    }


def _income_breakdown(proj) -> list[dict]:
    """Where recognized pay went — the universal deduction buckets that carry a
    balance, so the dashboard can show gross → net decomposition (Slice 4)."""
    from ..ledger.postings import DEDUCTION_ACCOUNTS
    rows = []
    for label, account in [("Retirement", DEDUCTION_ACCOUNTS["retirement"]),
                           ("Tax", DEDUCTION_ACCOUNTS["tax"]),
                           ("Insurance", DEDUCTION_ACCOUNTS["insurance"]),
                           ("Other withheld", DEDUCTION_ACCOUNTS["other"])]:
        try:
            amt = proj.balance(account).amount
        except UnknownAccountError:
            continue
        if amt:
            rows.append({"label": label, "amount": str(amt)})
    return rows


def questions(vault: Vault, limit: int = 10) -> dict:
    """The one ranked list of what Viva needs (Slice 6.5 Move 2) — highest stake
    first, with the tail summarized rather than hidden. The existing review cards
    still answer these; this is the front door that says which to do first."""
    from ..questions import open_questions
    return open_questions(vault.ledger, limit=limit)


def rule_nature(vault: Vault, merchant: str, nature: str) -> dict:
    """Answer a nature question at merchant scope — settles every transaction
    from that counterparty, past and future."""
    from ..ingest import rule_merchant_nature
    rule_merchant_nature(vault.ledger, merchant, nature, by="human")
    return {"ok": True}


def rule_major(vault: Vault, merchant: str, major: str, descriptor: str = "",
               kind: str = "") -> dict:
    """Answer with one of the four majors (Slice 9a) — the button path.

    Deterministic end to end: no model is involved when a person taps an answer,
    so this works with nothing configured. It goes through the same `propose` /
    `apply_proposal` pair the sentence path uses, so a tapped answer and a typed
    one produce byte-identical events — free text is an alternative channel,
    never a second mechanism."""
    from ..listen import Interpretation, apply_proposal, propose
    proj = vault.ledger.projection()
    interp = Interpretation(
        legs=[{"major": major, "account_hint": descriptor or merchant, "share": ""}],
        kind=kind, said="")
    proposal = propose(proj, interp, descriptor or merchant)
    applied = apply_proposal(vault.ledger, proposal, _today())
    return {"ok": True, **applied}


def listen_to(vault: Vault, said: str, descriptor: str, movement_key: str = "",
              category: str = "", subcategory: str = "",
              amount: str = "", currency: str = "") -> dict:
    """Read a sentence and return a **Proposal** — nothing is written (X3).

    The person sees what would change and how much money it moves before any of
    it happens. With no model configured this returns `understood: False` and
    the surface falls back to the buttons, which is the honest failure: we could
    not read it, so we do not guess."""
    from ..listen import interpret, propose
    proj = vault.ledger.projection()
    # Name the instrument the movement actually sat in — a card, a brokerage, a
    # loan account — instead of letting the prompt assume a bank (I5).
    source = ""
    for m in proj.movements():
        if movement_key and m.key == movement_key:
            source = _describe_source(proj, m.account)
            break
        if not movement_key and normalize(m.description) == normalize(descriptor):
            source = _describe_source(proj, m.account)
            break
    interp = interpret(said, descriptor, category, subcategory, _interpreter(),
                       source=source)
    if not interp.legs:
        # Four different failures used to share one unhelpful sentence, so
        # neither the person nor the log could tell a model that was DOWN from
        # one that was rambling from one that genuinely didn't understand.
        # Saying which is the difference between a product that admits a limit
        # and one that just seems broken.
        message = {
            "unreachable": "I can't reach my reader right now — the buttons "
                           "still work, and nothing was lost.",
            "unparseable": "I got an answer back but couldn't make sense of it. "
                           "Try fewer words, or use a button.",
            "empty": "I read that, but couldn't tell what the money became. "
                     "Could you say what happened to it?",
        }.get(interp.failure, "I couldn't read that one — the buttons still work.")
        log.warning("listen: %s (%s) said=%r raw=%r", interp.failure,
                    interp.detail, said, (interp.raw or "")[:400])
        return {"understood": False, "why": interp.failure, "message": message}
    proposal = propose(proj, interp, descriptor, amount, currency, movement_key)
    return {"understood": True, "proposal": proposal.to_dict()}


def _describe_source(proj, account: str) -> str:
    """A plain-language name for the instrument a movement sat in. Never a bank
    by assumption: the vault holds cards, brokerages and (soon) loan accounts,
    and a prompt that says "your bank account" mis-frames all of them."""
    try:
        info = proj.account_info(account)
    except Exception:                              # noqa: BLE001
        return ""
    kind = {"depository": "a bank or cash account", "liability": "a credit account",
            "investment": "an investment account"}.get(info.kind, "an account they hold")
    return f"{info.name or account} — {kind}" if info.name else kind


def apply_ruling(vault: Vault, proposal: dict) -> dict:
    """Confirm a proposal. The only path from a sentence to the ledger."""
    from ..listen import Proposal, apply_proposal
    fields = {k: v for k, v in proposal.items() if k != "summary"}
    return {"ok": True, **apply_proposal(vault.ledger, Proposal(**fields), _today())}


def _today() -> str:
    from datetime import date
    return date.today().isoformat()


def _interpreter():
    """The live model edge for step 3, or None when nothing is configured.
    Absent a model the whole queue keeps working — free text is an addition.

    **Configured separately from the document reader, on purpose.** Reading a
    statement is a hard vision task that wants the strongest model available;
    reading *"this is my mortgage"* is a ~390-token text task a 4B model does
    well. Forcing one setting for both would either overpay on every sentence or
    under-read every statement. So `VIVA_INTERPRET_*` overrides `VIVA_MODEL_*`
    per-field, and falls back to it when unset.

    This is also the seam the local model goes through (D1's forward note):
    point `VIVA_INTERPRET_BASE_URL` at Ollama or LM Studio and set
    `VIVA_INTERPRET_KEY_ENV=none`, and no sentence a person types ever leaves
    the machine — which is the whole promise, applied to the warmest surface in
    the product."""
    import os

    def cfg(field, default=None):
        return (os.environ.get(f"VIVA_INTERPRET_{field}")
                or os.environ.get(f"VIVA_MODEL_{field}" if field != "MODEL" else "VIVA_MODEL")
                or default)

    model = os.environ.get("VIVA_INTERPRET_MODEL") or os.environ.get("VIVA_MODEL")
    if not model:
        return None
    from vivacore.models import ModelSpec

    from ..listen import one_shot_extractor
    # A local server is keyless. `none` says so explicitly rather than leaving a
    # missing key to fail three layers down with a confusing message.
    key_env = cfg("KEY_ENV", "OPENROUTER_API_KEY")
    return one_shot_extractor(ModelSpec(
        name="viva-listen", adapter=cfg("ADAPTER", "openai-compatible"),
        model=model, base_url=cfg("BASE_URL"),
        api_key_env=None if (key_env or "").lower() in ("", "none") else key_env,
        # The answer is ~60 tokens. The headroom is for models that think out
        # loud before answering — `_first_json_object` finds the object inside
        # the prose, so reasoning costs tokens but never costs the reading.
        max_tokens=1024, json_mode=True))


def categorize_review(vault: Vault, limit: int = 50) -> dict:
    """The categorization queue: uncategorized expense movements, with the seed
    categories to choose from. Provenance rides along quietly."""
    proj = vault.ledger.projection()
    items = []
    for m in proj.uncategorized_expenses()[:limit]:
        items.append({"key": m.key, "descriptor": m.description,
                      "amount": str(abs(m.amount)), "currency": m.currency,
                      "date": m.date, "account": m.account})
    return {"items": items, "categories": list(SEED_CATEGORIES)}


def merchant_transactions(vault: Vault, merchant: str, limit: int = 200) -> dict:
    """Every movement with one merchant — the context behind a question.

    Keyed on the NORMALIZED merchant, the same unit a ruling generalizes over, so
    what you're shown is exactly what your answer will settle. (The first cut
    reused the categorization queue and filtered by substring, which returned
    nothing for a nature question: that queue only holds *uncategorized*
    movements, and a nature question is asked about a merchant that already has a
    category.)"""
    from ..ledger.merchants import normalize_merchant
    proj = vault.ledger.projection()
    key = normalize_merchant(merchant)
    items = []
    for m in proj.movements():
        if normalize_merchant(m.description) != key:
            continue
        ruling = proj.derived_category(m) or {}
        items.append({
            "key": m.key, "date": m.date, "description": m.description,
            "amount": str(abs(m.amount)), "currency": m.currency,
            "account": m.account,
            "category": ruling.get("category", ""),
            "subcategory": ruling.get("subcategory", ""),
            "nature": m.nature, "counts_as_spending": proj._counts_as_spending(m)})
    items.sort(key=lambda i: i["date"])
    total = sum(abs(Decimal(i["amount"])) for i in items) if items else Decimal("0")
    return {"merchant": key, "items": items[:limit], "count": len(items),
            "total": str(total),
            "currency": items[0]["currency"] if items else "",
            "categories": list(SEED_CATEGORIES)}


def assign_category_to(vault: Vault, movement_key: str, category: str) -> dict:
    """A person assigns a category to a movement (`verified` — the moat)."""
    ok = assign_category(vault.ledger, movement_key, category, by="human")
    return {"ok": ok}


def merchant_review(vault: Vault, limit: int = 50) -> dict:
    """The categorization queue, by MERCHANT (Slice 5.5): deduped unknown
    merchants with how many transactions each covers, so one ruling clears many."""
    proj = vault.ledger.projection()
    rows = sorted(proj.uncategorized_merchants().items(),
                  key=lambda kv: kv[1]["count"], reverse=True)
    items = [{"merchant": k, "example": r["example"], "count": r["count"],
              "shareable": r["shareable"]} for k, r in rows[:limit]]
    return {"items": items, "categories": list(SEED_CATEGORIES)}


def assign_merchant(vault: Vault, merchant: str, category: str) -> dict:
    """Categorize a whole merchant (`verified`) — fills all its transactions."""
    assign_merchant_category(vault.ledger, merchant, category, by="human")
    return {"ok": True}


def paystub_review(vault: Vault) -> dict:
    """Pay stubs read but not fully posted — awaiting their deposit, or held
    because gross − deductions did not equal net (Slice 4)."""
    from ..ingest import PayStubFacts
    proj = vault.ledger.projection()
    items = []
    for b in proj.open_holds():
        f = b.get("facts", {})
        if "gross" not in f:
            continue
        facts = PayStubFacts.from_dict(f)
        items.append({
            "doc_id": b["doc_id"], "reason": b.get("reason", ""),
            "employer": facts.employer, "currency": facts.currency,
            "pay_date": facts.pay_date,
            "gross": str(facts.gross), "net": str(facts.net),
            "deductions": [d.to_dict() for d in facts.deductions],
            "finding": b.get("finding")})
    return {"items": items}


def transfer_review(vault: Vault) -> dict:
    """Suggested internal transfers awaiting a ruling, in human-readable form.
    Candidates already linked (confirmed under another suggestion) are dropped, so
    a movement never appears as an option twice, and a suggestion with no
    remaining candidates disappears."""
    proj = vault.ledger.projection()
    by_key = {m.key: m for m in proj.movements()}
    linked = proj.linked_keys()

    def _describe(key: str) -> dict:
        m = by_key.get(key)
        if m is None:
            return {"key": key, "label": key}
        return {"key": key, "account": m.account, "date": m.date,
                "amount": str(m.amount), "description": m.description}

    items = []
    for s in proj.transfer_suggestions():
        cands = [k for k in s.get("candidates", []) if k not in linked]
        if not cands:
            continue                     # nothing left to match → not a question
        items.append({
            "source": _describe(s["a"]),
            "candidates": [_describe(k) for k in cands],
            "evidence": s.get("evidence", {})})
    return {"items": items}


def confirm_transfer_link(vault: Vault, movement_a: str, movement_b: str) -> dict:
    """A person confirms two movements are one transfer (netted, `verified`).
    A no-op if either was already linked — a movement joins at most one transfer."""
    made = confirm_transfer(vault.ledger, movement_a, movement_b)
    return {"ok": made}


def reject_transfer_link(vault: Vault, movement_a: str, movement_b: str = "") -> dict:
    """A person dismisses a suggested transfer (not the same money)."""
    reject_transfer(vault.ledger, movement_a, movement_b)
    return {"ok": True}


def account_view(vault: Vault, account: str) -> dict:
    """One account: its balance and its transactions (provenance rides along,
    for the quiet 'source' affordance)."""
    proj = vault.ledger.projection()
    try:
        info = proj.account_info(account)
        ba = proj.balance(account)
        lines = proj.transactions(account)
    except UnknownAccountError:
        return {"error": "unknown_account", "account": account}
    return {
        "account": account, "name": info.name or account,
        "currency": info.currency,
        "institution": info.institution, "number": masked(info.number),
        "holders": info.names,
        "balance": ba.to_dict(),
        "transactions": [ln.to_dict() for ln in lines],
    }


def review_list(vault: Vault) -> dict:
    """Everything held awaiting a human ruling."""
    return {"items": [h.to_dict() for h in held_items(vault.ledger.projection())]}


def confirm_correction(vault: Vault, doc_id: str, field: str, value: str,
                       target_index: int | None = None) -> dict:
    """Apply a person's ruling on a held statement and re-post it."""
    res = apply_human_correction(vault.ledger, doc_id, field, value, target_index)
    return {
        "action": res.action, "grade": res.grade, "account": res.account,
        "message": res.message,
    }


def confirm_identity(vault: Vault, doc_id: str, decision: str) -> dict:
    """Apply a person's ruling on an ambiguous account identity ('same' / 'new')."""
    res = apply_identity_ruling(vault.ledger, doc_id, decision)
    return {"action": res.action, "grade": res.grade, "account": res.account,
            "message": res.message}


def upload(vault: Vault, filename: str, data: bytes, read_fn) -> dict:
    """Ingest an uploaded file (capture → read → post/park/hold)."""
    res = capture_and_ingest(vault.raw, vault.ledger, data, read_fn,
                             filename=filename, captured_at=_today())
    return {
        "action": res.action, "grade": res.grade, "doc_type": res.doc_type,
        "account": res.account, "auto_corrected": res.auto_corrected,
        "message": res.message,
        "finding": res.finding.to_dict() if res.finding else None,
    }


def _today() -> str:
    import time
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
