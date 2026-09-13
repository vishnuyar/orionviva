"""Stable domain identity for a posted movement.

This ledger-domain primitive is shared by canonical and SQL projections
implementation.  Both the canonical event projection and disposable SQL read
model use it, so neither runtime layer depends on the other.
"""
from __future__ import annotations

from decimal import Decimal


def movement_key(doc_id: str, account: str, date: str, amount: Decimal | str,
                 description: str, occurrence: int = 0) -> str:
    """Return the content-derived identity shared by all ledger projections."""
    return f"{doc_id}|{account}|{date}|{amount}|{description}|{occurrence}"
