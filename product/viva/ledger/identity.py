"""Account identity — stable keys and name matching for entity resolution.

Identity is anchored to the account *number*, not a free-text label the model
renders inconsistently. Because statements show the number in different forms —
full ("000000000001234") on one, masked ("...1234") on another — the key uses
the **last four digits** (the lowest common denominator that survives masking),
scoped by institution.

This lives in the ledger layer because the projection resolves identity while
replaying events. The *learning* layer (matching an ambiguous statement to a
known account and remembering the person's ruling) is built on these helpers.
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


def masked(account_number: str) -> str:
    """A display-safe form of an account number: ••••last4 (or '' if none)."""
    key = number_key(account_number)
    return f"••••{key}" if key else ""


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


# Words that are not distinctive account tokens — shared across institutions or
# products, so they can't identify WHICH account a description names.
# A token is generic when SOMEBODY ELSE'S ACCOUNT ALSO HAS IT — not when it
# appears on a list somebody wrote in English.
#
# There used to be a stopword list here: "chase", "bank", "card", "checking",
# "the", "and", "for". It was guessing at what `distinctive_tokens` can simply
# look up. "chase" is generic in a vault where every account is Chase and
# perfectly distinctive in one holding a single Chase account beside a Citi
# card — a fixed list cannot know which vault it is in, and the vault can.
#
# What remains here is the shape rule only: a token must be long enough to be a
# word rather than an initial, and the holder's own name is excluded because it
# is shared by every account they own and so distinguishes none of them.
MIN_TOKEN = 4


def account_tokens(institution: str, number: str, ref: str) -> set[str]:
    """Distinctive tokens that identify one account inside a transaction
    description: its institution, its last-4, and product words from its label —
    minus generic stopwords. These are what a line like 'PAYMENT TO <product>
    ENDING IN 1234' carries to name the account it paid.

    Lives here (the ledger's identity layer) because BOTH the transfer matcher and
    the projection's nature derivation need it — one implementation,
    no import cycle. The account HOLDER's name is deliberately excluded: it is
    shared across all of a person's own accounts, so it distinguishes nothing."""
    toks: set[str] = set()
    if institution and len(institution) >= 3:
        toks.add(institution.lower())
    digits = normalize_number(number)
    if len(digits) >= 4:
        toks.add(digits[-4:])
    for w in re.split(r"[^a-z0-9]+", (ref or "").lower()):
        if len(w) >= MIN_TOKEN:
            toks.add(w)
    return {t for t in toks if t}


def distinctive_tokens(per_account: dict, institution_of: dict | None = None) -> dict:
    """Per account, the tokens that actually NAME it. Two rules, both structural.

    **Unique among your accounts.** A token two of your accounts both carry
    names neither of them. This is the job a stopword list was doing, done from
    the accounts in front of us: "chase" is generic in a vault where every
    account is Chase and distinctive in one holding a single Chase account, and
    a fixed list cannot know which vault it is in.

    **Identifier-shaped, or the institution.** Uniqueness alone is not enough,
    and a real test caught why: an account LABELLED "Card 2222" contributes the
    token "card", which is unique among two accounts and is still the most
    generic word on a card statement. So a label word must carry a digit to
    count — `2222`, `401k`, `plus2` — because a digit is what makes a token an
    identifier rather than a description. The institution is exempt: it is a
    name, not a description, and uniqueness is the whole test for it.

    What this deliberately gives up: "TRANSFER TO SAVINGS" between two accounts
    at one bank no longer links itself, because "savings" describes a kind and
    names no account. It becomes a question, which is the honest answer — that
    is exactly the guess the old `_DEPOSITORY_WORDS` list was making."""
    inst = {a: (i or "").strip().lower() for a, i in (institution_of or {}).items()}
    seen: dict = {}
    for toks in per_account.values():
        for tok in toks:
            seen[tok] = seen.get(tok, 0) + 1

    def keeps(acct: str, tok: str) -> bool:
        if seen.get(tok, 0) != 1:
            return False
        return any(c.isdigit() for c in tok) or tok == inst.get(acct)

    return {acct: {t for t in toks if keeps(acct, t)}
            for acct, toks in per_account.items()}


def normalize_name(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").strip().lower())


def names_overlap(a: list[str], b: list[str]) -> bool:
    """True if any holder name is shared (normalized). The seed matcher's name
    signal; fuzzier matching can grow here later without touching callers."""
    A = {normalize_name(x) for x in (a or []) if str(x).strip()}
    B = {normalize_name(x) for x in (b or []) if str(x).strip()}
    return bool(A & B)
