"""The surface's service layer — pure functions from a vault to JSON payloads.

Deliberately separate from the HTTP plumbing so it is all testable offline. Each
function reads (or acts on) the vault and returns plain dicts the page renders.
The number, its grade, and its coverage come straight from the answer path; the
*provenance is present in every payload but kept quiet* — the page shows the
picture and the interactions, and only surfaces a source on request.
"""

from __future__ import annotations

from ..answer import answer_total, coverage_summary
from ..ingest import (apply_human_correction, apply_identity_ruling,
                      capture_and_ingest, held_items)
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
        if info.kind not in ("depository", "liability"):
            continue
        ba = proj.balance(info.account)
        liability = info.kind == "liability"
        accounts.append({
            "account": info.account, "name": info.name or info.account,
            "currency": info.currency,
            # A liability's balance is money owed; show a positive owed figure and
            # let the page label it, so the sign convention never confuses a person.
            "amount": str(abs(ba.amount) if liability else ba.amount),
            "kind": info.kind, "liability": liability,
            "grade": ba.grade, "as_of": ba.dated,
            "institution": info.institution, "number": masked(info.number),
            "holders": info.names})
    return {
        "total": total.to_dict(),
        "accounts": accounts,
        "coverage": coverage_summary(proj).text,
        "review_count": len(held_items(proj)),
    }


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
