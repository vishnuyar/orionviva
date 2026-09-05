"""The category taxonomy — impersonal, shareable, versioned.

Two levels. The *primary* set is a small controlled list (16 buckets plus a
fallback) that the commons compares across users. The *subcategory* is an open
value the model fills in ("warehouse club", "coffee shop", "streaming"),
lightly normalized, for finer slicing.

A subcategory vocabulary ships with the package, in a file named for the
taxonomy version it is, so a record's stamped version resolves to the exact
list that produced it. The list is offered and not enforced: a model is shown
it and asked to reuse a label where one fits, and nothing rejects a label
outside it.

Lives in merchantcore because a taxonomy is merchant knowledge: shareable, not
personal. It is the single source of truth the product's category picker reads.
"""

from __future__ import annotations

import json
import pathlib
from functools import lru_cache

from vivacore import versions

PACKAGE = pathlib.Path(__file__).resolve().parent

# The version stamped on every record, as `merchantcore/versions.json` declares
# it. It names both the controlled primary set below and the seed vocabulary
# file that carries the same id.
TAXONOMY_VERSION = versions.active(PACKAGE, "taxonomy")

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


def subcategory_identity(subcategory: str) -> str:
    """The one label two spellings that differ only in punctuation share.

    Separators are folded — underscore, hyphen and any run of whitespace
    become one space, and an ampersand becomes the word it stands for — so
    `credit_card_payment`, `credit card payment` and `gym & fitness` /
    `gym and fitness` each resolve to a single identity, which is also how the
    merged label is spelled.

    Characters only, and no vocabulary: `restaurant` and `restaurants` stay two
    labels, and so do `internet cable` and `internet and cable`."""
    s = (subcategory or "").strip().lower()
    s = s.replace("_", " ").replace("-", " ").replace("&", " and ")
    return " ".join(s.split())


def read_subcategory_seed(path) -> tuple[str, ...]:
    """The shipped vocabulary held in one versioned file, as flat labels.

    The file groups labels under the primary they belong to, each with a gloss
    for whoever reviews it; only the labels are read here, in file order.

    Nothing is dropped quietly — every fault raises ValueError: where the file
    is not an object; where it names no vocabulary at all; where the file's own
    version is not the name it is filed under; where labels are grouped under a
    name that is not a primary; where a primary carries no labels, or carries
    something that is not a group of them; where a label is empty, carries no
    gloss, or holds an ampersand; where a label is also a primary's name; and
    where two labels are one label under the separator fold."""
    path = pathlib.Path(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(
            f"{path}: a vocabulary is an object carrying a version and the "
            f"labels grouped under their primaries")
    declared = str(data.get("version") or "")
    if declared != path.stem:
        raise ValueError(
            f"{path}: the file says version {declared!r} and is filed under "
            f"{path.stem!r}; a stamped version resolves to one file's bytes")
    grouped = data.get("subcategories")
    if not isinstance(grouped, dict) or not grouped:
        raise ValueError(
            f"{path}: names no subcategories; a file that anchors nothing is "
            f"indistinguishable from a package shipping no vocabulary at all")
    allowed = set(PRIMARY_CATEGORIES) | {FALLBACK_CATEGORY}
    reserved = {subcategory_identity(p) for p in allowed}
    seen: dict[str, str] = {}
    out: list[str] = []
    for primary, labels in grouped.items():
        if primary not in allowed:
            raise ValueError(
                f"{path}: {primary!r} is not a primary category")
        if not isinstance(labels, dict) or not labels:
            raise ValueError(
                f"{path}: {primary!r} carries no labels; a primary named here "
                f"holds a group of label-to-gloss pairs")
        for label, gloss in labels.items():
            identity = subcategory_identity(label)
            if not identity:
                raise ValueError(f"{path}: {primary!r} holds an empty label")
            if not isinstance(gloss, str) or not gloss.strip():
                raise ValueError(
                    f"{path}: {label!r} carries no gloss; a label nobody can "
                    f"read the meaning of cannot be reviewed")
            if "&" in label:
                raise ValueError(
                    f"{path}: {label!r} holds an ampersand; the convention "
                    f"this file states spells the word out")
            if identity in reserved:
                raise ValueError(
                    f"{path}: {label!r} is also a primary category name; one "
                    f"alias namespace serves both levels")
            if identity in seen:
                raise ValueError(
                    f"{path}: {label!r} is the label {seen[identity]!r} again; "
                    f"a vocabulary names a thing once")
            seen[identity] = label
            out.append(label.strip())
    return tuple(out)


@lru_cache(maxsize=1)
def seed_subcategories() -> tuple[str, ...]:
    """The vocabulary this package ships, or an empty tuple where it ships none.

    With no seed file, the vocabulary offered downstream is whatever the vault
    already uses. Cached; the file is read once."""
    try:
        path = versions.path_of(PACKAGE, TAXONOMY_VERSION)
    except versions.ManifestError:
        return ()
    return read_subcategory_seed(path)


@lru_cache(maxsize=1)
def seed_subcategories_by_category() -> dict[str, tuple[str, ...]]:
    """The shipped finer labels, under the primary each one may slice.

    The flat vocabulary remains useful when only label reuse matters.  A
    compound human assignment needs the hierarchy as well: accepting a known
    label under a different primary would create a state the taxonomy itself
    contradicts.  Reuse :func:`read_subcategory_seed` as the validator before
    retaining the file's grouping, so the two views cannot accept different
    source bytes.
    """
    try:
        path = versions.path_of(PACKAGE, TAXONOMY_VERSION)
    except versions.ManifestError:
        return {}
    read_subcategory_seed(path)
    grouped = json.loads(path.read_text(encoding="utf-8"))["subcategories"]
    return {
        category: tuple(str(label).strip() for label in labels)
        for category, labels in grouped.items()
    }


def subcategory_vocabulary(known=None, seed=None) -> tuple[str, ...]:
    """The labels to offer, seed first and then the ones already in use.

    Compared under `subcategory_identity`, first spelling wins, which puts a
    seed label ahead of a later variant of itself.

    A seed label never removes a label already in use: only a label the seed
    already spells another way gives up its spelling, and where two differ at
    all both are offered. ``known`` defaults to nothing, ``seed`` to the
    package's own."""
    source = tuple(seed_subcategories() if seed is None else tuple(seed))
    seen: set[str] = set()
    out: list[str] = []
    for label in source + tuple(known or []):
        identity = subcategory_identity(label)
        if identity and identity not in seen:
            seen.add(identity)
            out.append(str(label).strip())
    return tuple(out)
