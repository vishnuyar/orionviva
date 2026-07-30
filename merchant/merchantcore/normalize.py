"""Merchant normalization — a raw transaction descriptor to a canonical merchant.

Deterministic and **versioned**: the normalized key is what the merchant catalog
is keyed by, and — for a shareable commons — two users must derive the *same* key
from the same descriptor, so the rules are fixed and carried by a version. This
is NOT fuzzy matching (which would merge "Costco" and "Costa Coffee"); it only
strips the noisy tail that varies transaction-to-transaction — store numbers,
order ids, phone numbers, payment-processor prefixes — leaving the merchant words
as read. The model does the actual grouping/categorization on the deduped list.

``is_shareable`` is the privacy lint: a peer-payment or person-name
descriptor ("VENMO TO JOHN SMITH", "ZELLE FROM …") is personal and must never
enter the unencrypted catalog or the commons — only clearly *commercial*
merchants are shareable.
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

# A posting date printed inside the descriptor. It has to go before the
# non-word pass removes its separators, because "02/14 STORE" survives that
# pass as "02 14 store" and then heads a merchant key of its own — so one
# merchant seen in two months becomes two merchants, and every total that
# touches either is split. Only a fragment with a separator is stripped: a
# bare number can be part of a name ("7 eleven", "76").
_DATE_FRAGMENT = re.compile(r"\b\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?\b")
_ORDER_ID = re.compile(r"\*[a-z0-9]{3,}")          # US*RA30Z3BP0, *RH4DD6YM1
_STORE_NUM = re.compile(r"#\s*\d+")                 # #0664
_PHONE = re.compile(r"\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b")
_LONGNUM = re.compile(r"\b\d{3,}\b")                # order/ref numbers, ids
_NONWORD = re.compile(r"[^a-z0-9 ]+")
_WS = re.compile(r"\s+")


def normalize_merchant(descriptor: str) -> str:
    """Canonical merchant key for a raw descriptor (deterministic, versioned).
    Empty string if nothing meaningful remains."""
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
    """True when a descriptor names a *commercial* merchant safe to put in the
    unencrypted catalog / commons — i.e. NOT a peer payment or a person's name.
    Conservative: anything with a peer-payment marker is filtered out."""
    low = (descriptor or "").lower()
    if any(mark in low for mark in _PEER_MARKERS):
        return False
    # THE MARKER LIST IS ENGLISH AND ASCII, so on a line it cannot read its
    # SILENCE IS NOT EVIDENCE — and silence here means "safe to send to a model
    # provider". A Hindi or Japanese peer payment contains none of these words,
    # so the list cleared it by never having had a chance to look.
    #
    # Failing closed instead. A descriptor carrying letters outside ASCII is
    # withheld until a grammar exists for that institution, at which point a
    # slot name answers the question properly and this function is not consulted
    # at all. Costs enrichment coverage on a new non-English vault; the
    # alternative is a person's name crossing because a word list was mute.
    if any(c.isalpha() and ord(c) > 127 for c in (descriptor or "")):
        return False
    return bool(normalize_merchant(descriptor))
