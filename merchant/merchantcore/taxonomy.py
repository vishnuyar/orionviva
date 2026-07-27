"""The category taxonomy — impersonal, shareable, versioned.

Two levels, mirroring the enrichment industry (Plaid's Personal Finance
Categories, Ntropy): a small **primary** set of stable, portable buckets that the
commons compares across users, and a richer **subcategory** the model fills with
value ("warehouse club", "coffee shop", "streaming") for finer slicing. Primary
is controlled (16 + a fallback); subcategory is an open value, lightly
normalized, so the commons converges on it over time without a rigid 100-item
list. This lives in merchantcore because the taxonomy is merchant/format
knowledge — shareable, not personal.
"""

from __future__ import annotations

TAXONOMY_VERSION = "cat-v2"      # the controlled primary set below

# 16 primary categories (a friendly cousin of Plaid's PFC primaries).
PRIMARY_CATEGORIES = (
    "income",                 # salary, interest, dividends, refunds-as-income
    "transfers",              # moving your own money, credit-card payments
    "loan_payments",          # mortgage, auto, student, personal loan payments
    "fees",                   # bank, card, finance, ATM fees
    "groceries",              # supermarkets, warehouse clubs, food shops
    "dining",                 # restaurants, cafes, bars, food delivery
    "shopping",               # general merchandise, retail, online marketplaces
    "transport",              # fuel, rideshare, transit, parking, auto service
    "travel",                 # flights, hotels, car rental, lodging
    "utilities",              # electric, water, gas, internet, phone
    "housing",                # rent, home improvement, furnishings, maintenance
    "health",                 # medical, pharmacy, dental, health insurance
    "personal_care",          # salons, gyms, grooming, wellness
    "entertainment",          # streaming, events, hobbies, gaming
    "services",               # professional & general services (legal, repair…)
    "government_nonprofit",   # taxes, government fees, charitable giving
)

FALLBACK_CATEGORY = "other"    # used only when genuinely unclear


def is_primary(category: str) -> bool:
    return (category or "").strip().lower() in PRIMARY_CATEGORIES


def canonical_primary(category: str) -> str:
    """Normalize a proposed primary category into the controlled set, or the
    fallback if it isn't one of the 16."""
    c = (category or "").strip().lower()
    return c if c in PRIMARY_CATEGORIES else FALLBACK_CATEGORY


def normalize_subcategory(subcategory: str) -> str:
    """Lightly normalize the model's free subcategory value (trim + lowercase).
    Open by design; the commons converges on common values over time."""
    return " ".join((subcategory or "").strip().lower().split())
