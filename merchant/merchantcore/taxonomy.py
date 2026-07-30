"""The category taxonomy — impersonal, shareable, versioned.

Two levels. The *primary* set is a small controlled list (16 buckets plus a
fallback) that the commons compares across users. The *subcategory* is an open
value the model fills in ("warehouse club", "coffee shop", "streaming"),
lightly normalized, for finer slicing.

Lives in merchantcore because a taxonomy is merchant knowledge: shareable, not
personal. It is the single source of truth the product's category picker reads.
"""

from __future__ import annotations

TAXONOMY_VERSION = "cat-v2"      # the controlled primary set below

# The 16 controlled primary categories.
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

FALLBACK_CATEGORY = "other"    # for a category that is not one of the 16


def is_primary(category: str) -> bool:
    return (category or "").strip().lower() in PRIMARY_CATEGORIES


def canonical_primary(category: str) -> str:
    """Normalize a proposed primary category into the controlled set.

    Returns FALLBACK_CATEGORY when it is not one of the 16."""
    c = (category or "").strip().lower()
    return c if c in PRIMARY_CATEGORIES else FALLBACK_CATEGORY


def normalize_subcategory(subcategory: str) -> str:
    """Trim, lowercase and collapse whitespace in a free subcategory value.

    The value set is open: anything is accepted, nothing is mapped away."""
    return " ".join((subcategory or "").strip().lower().split())
