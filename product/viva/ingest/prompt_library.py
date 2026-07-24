"""Prompts as versioned, addressable DATA — not a single overwritten string.

The read happens in two phases (the Slice 2 design, decision 1): a cheap
**classify** pass names the document, then an **extract** pass runs the prompt
that belongs to that type's profile. This module holds the retained, versioned
text for both, so a stored read's ``prompt_version`` always resolves to the exact
instructions that produced it (T8) — reproducibility without git archaeology, and
the self-contained unit a format-commons could one day share.

Retention discipline (enforced by ``test_prompt_library``): every dict here is
**append-only**. To change a prompt you add a NEW version id; you never edit an
existing one. A read recorded under ``card-v1`` must resolve to card-v1's text
forever, even after ``card-v2`` exists.

The extraction prompt is *composed*: a shared ``EXTRACT_BASE`` (the parse shape +
universal rules, identical for every balance type) plus a per-type
``TYPE_FRAGMENTS`` entry (what the balance means, and that type's completeness
traps). The base carries no type-specific guidance; the fragment carries no
shape. Composition yields a self-describing version id like
``extract:base-v1+card-v1``.
"""

from __future__ import annotations

# --------------------------------------------------------------- classify phase

CLASSIFY_PROMPTS: dict[str, str] = {
    "classify-v1": """\
You are classifying ONE financial document — deciding only WHAT it is, not
reading any figures. Return ONLY a JSON object, no prose:

{"doc_type": "<type>", "doc_type_confidence": 0.0-1.0}

Set "doc_type" to exactly one of:
  - "checking_statement"     — a checking / current / bank account statement
  - "savings_statement"      — a savings / money-market account statement
  - "credit_card_statement"  — a credit-card account statement
If it is none of these (pay stub, tax form, brokerage statement, loan statement,
invoice, etc.), set "doc_type" to your best short snake_case label for it.

Judge from the whole document (the first page and its embedded text usually
suffice). Do NOT extract balances or transactions — that is a separate step.
""",
}

# ----------------------------------------------------------------- extract phase

EXTRACT_BASE: dict[str, str] = {
    "base-v1": """\
You are reading one financial statement. Return ONLY a JSON object, no prose.

Extract exactly this shape:

{
  "doc_type_confidence": 0.0-1.0,
  "account_number": "the account (or card) number AS PRINTED (full or masked, e.g. ...1234); '' if none visible",
  "institution": "the bank/issuer name, e.g. 'Chase', 'Amex', 'SBI'",
  "account_names": ["each account-holder name printed on the statement — usually one, two for a joint account"],
  "account_ref": "a short human label for the account (e.g. 'Chase Sapphire ...1234')",
  "opening": {"amount_raw": "the opening/previous balance AS PRINTED", "date_raw": "the period start date AS PRINTED", "page": <page number>},
  "closing": {"amount_raw": "the closing/new balance AS PRINTED", "date_raw": "the period end date AS PRINTED", "page": <page number>},
  "transactions": [
    {"date_raw": "AS PRINTED", "description": "AS PRINTED", "amount_raw": "the POSITIVE magnitude AS PRINTED", "balance_effect": "increase" or "decrease", "running_balance_raw": "the running/ledger balance printed on this line, if any", "page": <page number>}
  ]
}

Universal rules:
- "account_number", "institution", "account_names" identify WHOSE account this is
  — extract them as printed; they let the same account be recognized across
  statements even when labelled differently. Include every holder name.
- Copy amounts and dates EXACTLY as printed. Do not reformat, convert, or do math.
- "amount_raw" is always the POSITIVE magnitude; the sign comes from "balance_effect".
- "balance_effect" is "increase" if the line RAISES the printed balance and
  "decrease" if it LOWERS it. The account-type guidance below says which is which.
- "running_balance_raw": if the statement prints a running/ledger balance on each
  line, copy it AS PRINTED; otherwise omit the field. It is a cross-check that
  lets a misread line be pinpointed — capture it when present.
- If a value is genuinely unreadable, write it exactly as best you can see it —
  never invent a figure to make things add up.

Account-type guidance (what the balance means, and how to sign each line):
""",
}

# Per-type fragments. Each names what the printed balance means and the
# completeness traps specific to that type. "balance-generic-v1" is the default
# for a newly-registered balance type that hasn't authored its own fragment yet —
# so adding a type stays a data-only registry row.
TYPE_FRAGMENTS: dict[str, str] = {
    "balance-generic-v1": """\
This is a balance-style account statement. The printed balance moves up and down
as money flows through the account. For each line, set "balance_effect" to
"increase" if it raises the printed balance and "decrease" if it lowers it.
List EVERY balance-changing line in the period, from ALL sections of the
statement — completeness matters more than anything, and a missing line will
break reconciliation and be caught.
""",
    "checking-v1": """\
This is a checking / current / bank account statement. The printed balance is the
money HELD in the account. A deposit, credit, or interest payment INCREASES it
(balance_effect "increase"); a withdrawal, payment, card purchase, fee, or check
DECREASES it (balance_effect "decrease").
List EVERY transaction in the period, from ALL sections (deposits, withdrawals,
fees, and any separate lists) — completeness matters more than anything.
""",
    "savings-v1": """\
This is a savings / money-market account statement. The printed balance is the
money HELD. A deposit or interest credit INCREASES it (balance_effect
"increase"); a withdrawal, transfer out, or fee DECREASES it (balance_effect
"decrease"). Interest paid into the account is an increase — include it.
List EVERY line in the period from ALL sections — completeness matters most.
""",
    "card-v1": """\
This is a credit-card statement. The printed balance is the money OWED: the
"opening" is the previous balance and the "closing" is the new balance. A
purchase, charge, cash advance, fee, or interest INCREASES what's owed
(balance_effect "increase"); a payment, autopay, statement credit, or refund
DECREASES it (balance_effect "decrease").

COMPLETENESS — READ CAREFULLY: card statements often list payments and credits in
a SEPARATE section from purchases (sometimes on another page, above or below the
purchases). You MUST include EVERY payment, autopay, statement credit, and refund
as a "decrease" line — do not stop at the purchases list. If opening + the signed
effects does not land exactly on the closing balance, you have almost certainly
missed a line (most often a payment) — look again before answering.
""",
}


# ---------------------------------------------------------------- resolvers

_ALL: dict[str, str] = {**CLASSIFY_PROMPTS, **EXTRACT_BASE, **TYPE_FRAGMENTS}


def classify_prompt(version: str = "classify-v1") -> tuple[str, str]:
    """The classification prompt text and its version id."""
    return CLASSIFY_PROMPTS[version], version


def compose_extraction(base_version: str, fragment_version: str) -> tuple[str, str]:
    """Compose the shared base with a per-type fragment. Returns (text, version),
    where the version is the self-describing composite ``extract:<base>+<frag>``
    that gets stamped on the read and round-trips through ``resolve``."""
    text = EXTRACT_BASE[base_version] + "\n" + TYPE_FRAGMENTS[fragment_version]
    return text, f"extract:{base_version}+{fragment_version}"


def resolve(version: str) -> str:
    """Reconstruct the exact prompt text for any recorded ``prompt_version`` — a
    classify id, a base/fragment id, or a composite ``extract:base+frag``. This is
    what makes a stored read reproducible without leaving the app (T8)."""
    if version.startswith("extract:"):
        base_v, frag_v = version[len("extract:"):].split("+", 1)
        return EXTRACT_BASE[base_v] + "\n" + TYPE_FRAGMENTS[frag_v]
    return _ALL[version]
