"""Stable account keys, number signals, and entity-resolution tokens."""

from __future__ import annotations

import re


def normalize_number(account_number: str) -> str:
    """Just the digits of an account number (drops masking chars, spaces, dashes)."""
    return re.sub(r"\D", "", account_number or "")


def number_key(account_number: str) -> str:
    """Return the last four digits, or empty for a shorter number signal."""
    digits = normalize_number(account_number)
    return digits[-4:] if len(digits) >= 4 else ""


_REFERENCE_LAST4 = re.compile(
    r"(?:ending(?:\s+in)?|ends?(?:\s+in)?|last\s*4|x{2,}|\*{2,}|•{2,})"
    r"\D{0,12}(\d{4})\b",
    re.IGNORECASE,
)


def reference_number_key(account_ref: str) -> str:
    """A last-four explicitly printed in an account/product reference."""
    match = _REFERENCE_LAST4.search(account_ref or "")
    return match.group(1) if match else ""


def identity_number_key(account_number: str, account_ref: str = "") -> str:
    """Best usable number signal, preferring a valid number field then ref."""
    return number_key(account_number) or reference_number_key(account_ref)


def conflicting_number_signals(account_number: str, account_ref: str) -> bool:
    """Whether two independently usable number signals disagree."""
    direct = number_key(account_number)
    printed = reference_number_key(account_ref)
    return bool(direct and printed and direct != printed)


def masked(account_number: str) -> str:
    """A display-safe form of an account number: ••••last4 (or '' if none)."""
    key = number_key(account_number)
    return f"••••{key}" if key else ""


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").strip().lower()).strip("-")


def canonical_institution(institution: str) -> str:
    """Stable issuer key without institution-specific knowledge."""
    return slug(institution)


_INSTITUTION_LEGAL_WORDS = frozenset({
    "the", "bank", "national", "association", "na", "n", "a", "inc",
    "incorporated", "corp", "corporation", "company", "co", "llc"})


def institution_names_overlap(a: str, b: str) -> bool:
    """Whether two issuer names share the same distinctive legal-name core."""
    def tokens(value: str) -> set[str]:
        return {token for token in re.split(r"[^a-z0-9]+", value.lower())
                if token and token not in _INSTITUTION_LEGAL_WORDS}
    left, right = tokens(a or ""), tokens(b or "")
    return bool(left and right and (left <= right or right <= left))


def account_labels_overlap(a: str, b: str) -> bool:
    """Whether two account labels share a non-generic product token."""
    generic = {"account", "statement", "of", "the"}
    def tokens(value: str) -> set[str]:
        return {token for token in re.split(r"[^a-z0-9]+", value.lower())
                if token and token not in generic}
    left, right = tokens(a or ""), tokens(b or "")
    return bool(left and right and left & right)


def account_key(institution: str, account_number: str, account_ref: str) -> str:
    """Return an issuer-and-number key, or a label key without a number."""
    key = identity_number_key(account_number, account_ref)
    if key:
        inst = canonical_institution(institution)
        return f"acct:{inst + ':' if inst else ''}{key}"
    return f"acct:{slug(account_ref) or 'unknown'}"


# Words that are not distinctive account tokens — shared across institutions or
# products, so they can't identify WHICH account a description names.
# A token is generic when another account also carries it.
#
# Minimum length for a token to count as a word rather than an initial.
MIN_TOKEN = 4


def account_tokens(institution: str, number: str, ref: str) -> set[str]:
    """Return issuer, number, and product tokens that may identify an account."""
    toks: set[str] = set()
    if institution and len(institution) >= 3:
        toks.add(institution.lower())
    key = identity_number_key(number, ref)
    if key:
        toks.add(key)
    for w in re.split(r"[^a-z0-9]+", (ref or "").lower()):
        if len(w) >= MIN_TOKEN:
            toks.add(w)
    return {t for t in toks if t}


def distinctive_tokens(per_account: dict, institution_of: dict | None = None) -> dict:
    """Map accounts to unique number or issuer tokens from ``per_account``."""
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


def text_has_token(text: str, token: str) -> bool:
    """Match an identity token at alphanumeric boundaries, not as a fragment."""
    return bool(re.search(rf"(?<![a-z0-9]){re.escape(token.lower())}(?![a-z0-9])",
                          (text or "").lower()))


def normalize_name(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").strip().lower())


def names_overlap(a: list[str], b: list[str]) -> bool:
    """True if any holder name is shared (normalized). The seed matcher's name
    signal; fuzzier matching can grow here later without touching callers."""
    A = {normalize_name(x) for x in (a or []) if str(x).strip()}
    B = {normalize_name(x) for x in (b or []) if str(x).strip()}
    return bool(A & B)
