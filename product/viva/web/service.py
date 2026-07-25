"""The surface's service layer — pure functions from a vault to JSON payloads.

Deliberately separate from the HTTP plumbing so it is all testable offline. Each
function reads (or acts on) the vault and returns plain dicts the page renders.
The number, its grade, and its coverage come straight from the answer path; the
*provenance is present in every payload but kept quiet* — the page shows the
picture and the interactions, and only surfaces a source on request.
"""

from __future__ import annotations

from ..answer import answer_spending, answer_total, coverage_summary
from ..ingest import (SEED_CATEGORIES, apply_human_correction,
                      apply_identity_ruling, assign_category,
                      assign_merchant_category, capture_and_ingest,
                      confirm_transfer, held_items, reject_transfer)
from ..ingest.identity import masked
from ..ledger import UnknownAccountError
from ..vault import Vault


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
            row["holdings"] = str(proj.holdings_value(info.account))
            row["unrealized_gain"] = str(ug) if ug is not None else None
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
        "spending_by_subcategory": {c: str(a) for c, a
                                    in proj.spending_by_subcategory().items()},
        "income": {c: str(v) for c, v in income.items()},
        "income_breakdown": _income_breakdown(proj),
        "positions": [p.to_dict() for p in proj.positions()],
        "review_count": len(held_items(proj)),
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
