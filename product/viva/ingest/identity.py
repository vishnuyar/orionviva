"""Account identity — deterministic keys from stable signals (Slice 1.5).

Identity is anchored to the account *number*, not a free-text label the model
renders inconsistently. Because statements show the number in different forms —
full ("000000000001234") on one, masked ("...1234") on another — the key uses
the **last four digits** (the lowest common denominator that survives masking),
scoped by institution. The full number and the names are kept as *aliases* on the
account for the matcher and for display.

This is the deterministic core. The *learning* layer (matching an ambiguous
statement to a known account and remembering the person's ruling) builds on top
of these keys — see docs/account-identity-and-entity-resolution.md.
"""

from __future__ import annotations

import re


def normalize_number(account_number: str) -> str:
    """Just the digits of an account number (drops masking chars, spaces, dashes)."""
    return re.sub(r"\D", "", account_number or "")


def number_key(account_number: str) -> str:
    """The stable identity fragment: the last four digits (or all, if fewer).
    Survives the full-vs-masked difference between two statements of one account."""
    digits = normalize_number(account_number)
    return digits[-4:] if len(digits) >= 4 else digits


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").strip().lower()).strip("-")


def account_key(institution: str, account_number: str, account_ref: str) -> str:
    """A stable account id. Prefer institution + last-4 of the number; fall back
    to a slug of the free-text label only when no number was extracted."""
    key = number_key(account_number)
    if key:
        inst = slug(institution)
        return f"acct:{inst + ':' if inst else ''}{key}"
    return f"acct:{slug(account_ref) or 'unknown'}"
