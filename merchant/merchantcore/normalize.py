"""Merchant normalization — a raw transaction descriptor to a canonical key.

Deterministic and versioned: the key is what the merchant catalog is keyed by,
and two users derive the same key from the same descriptor, so the rules are
fixed and carried by ``NORMALIZER_VERSION``.

Not fuzzy matching — it never merges two different spellings. It strips the
tail that varies transaction to transaction (store numbers, order ids, phone
numbers, payment-processor prefixes, posting dates) and leaves the merchant
words as read.

``is_shareable`` is the fallback privacy lint, used where no induced grammar
exists to name a slot. A peer-payment or person-name descriptor must not enter
the unencrypted catalog or the commons.
"""

from __future__ import annotations

import re

NORMALIZER_VERSION = "merch-v2"

# Payment-processor / POS prefixes that wrap the real merchant name.
_PREFIXES = (
    "tst* ", "tst*", "sq *", "sq*", "sp *", "sp*", "pos ", "pp*", "paypal *",
    "paypal*", "ppd id:", "ppd", "ach pmt", "web pymt", "pos debit ",
    "pos purchase ", "purchase ", "debit card purchase ", "checkcard ",
)

# Substrings that mark a personal peer-payment (never shareable).
_PEER_MARKERS = (
    "venmo", "zelle", "cash app", "cashapp", "cash.app", "paypal *",
    "quickpay", "popmoney", " to ", " from ",
)

# A posting date printed inside the descriptor. Stripped before the non-word
# pass, which would otherwise remove the separators and leave "02 14 store" —
# a distinct key per month for one merchant. Only a fragment carrying a
# separator is a date: a bare number can be part of a name.
_DATE_FRAGMENT = re.compile(r"\b\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?\b")
_ORDER_ID = re.compile(r"\*[a-z0-9]{3,}")          # *RA30Z3BP0, *RH4DD6YM1
_STORE_NUM = re.compile(r"#\s*\d+")                 # #0664
_PHONE = re.compile(r"\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b")
_LONGNUM = re.compile(r"\b\d{3,}\b")                # order/ref numbers, ids
_NONWORD = re.compile(r"[^a-z0-9 ]+")
_WS = re.compile(r"\s+")


def normalize_merchant(descriptor: str) -> str:
    """Canonical merchant key for a raw descriptor.

    Deterministic and versioned. Returns "" if nothing remains after stripping."""
    s = (descriptor or "").lower().strip()
    for p in _PREFIXES:
        if s.startswith(p):
            s = s[len(p):]
            break
    s = _DATE_FRAGMENT.sub(" ", s)
    s = _PHONE.sub(" ", s)
    s = _ORDER_ID.sub(" ", s)
    s = _STORE_NUM.sub(" ", s)
    s = _LONGNUM.sub(" ", s)
    s = _NONWORD.sub(" ", s)
    s = _WS.sub(" ", s).strip()
    return s


def is_shareable(descriptor: str) -> bool:
    """True when a descriptor may enter the unencrypted catalog or the commons.

    Three ways to be refused: a peer-payment marker anywhere in the line, any
    alphabetic character outside ASCII, or nothing left after normalization.
    Fails closed — a refusal costs enrichment coverage, never a name."""
    low = (descriptor or "").lower()
    if any(mark in low for mark in _PEER_MARKERS):
        return False
    # Constraint: silence from this English, ASCII marker list is not a
    # clearance. A descriptor carrying non-ASCII letters is withheld until a
    # grammar exists for that institution and a slot name answers instead.
    if any(c.isalpha() and ord(c) > 127 for c in (descriptor or "")):
        return False
    return bool(normalize_merchant(descriptor))
