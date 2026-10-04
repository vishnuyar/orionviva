"""Effective lifecycle of accounts created solely by reversible corrections."""
from __future__ import annotations


def inactive_accounting_accounts(corrections, rulings, account_infos):
    """Return orphan correction-created paths, preserving independent evidence.

    ``corrections`` maps ids to folded bodies with ``undone`` and optional
    ``created_accounts``. Account metadata carries ``origin`` and explicit
    ``independently_observed``/``reopened`` flags supplied by each read model.
    """
    bodies = list(corrections.values()) if isinstance(corrections, dict) else list(corrections)
    candidates = {account for body in bodies if body.get("undone")
                  for account in body.get("created_accounts", [])}
    protected = {leg.get("account", "") for body in bodies if not body.get("undone")
                 for leg in body.get("legs", [])}
    for ruling in rulings:
        protected.update(leg.get("account", "") for leg in ruling.get("legs", []))
        scope, subject = ruling.get("scope", ""), ruling.get("subject", "")
        if scope == "attribute":
            protected.add(subject.rpartition(":")[0])
        elif scope == "account":
            protected.add(subject)
        value = ruling.get("value", "")
        if isinstance(value, str) and value in candidates:
            protected.add(value)
    for account, info in account_infos.items():
        if (info.get("origin", "issued") != "asserted"
                or info.get("independently_observed") or info.get("reopened")):
            protected.add(account)
    return candidates - protected
