"""The statement-extraction prompt. Versioned (T8): a prompt change is a new
version, so a stored read can always be traced to the exact instructions that
produced it.

stmt-v3 (Slice 2) reads the whole **balance family** — checking, savings, and
credit-card statements — with one shared shape, because their structure is the
same: an opening balance, a list of movements, a closing balance. What differs
is only *what the printed balance means* (money held vs money owed), which we
interpret from the classified type (the registry), not from the model.

The sign of each movement is asked as its **effect on the printed balance**
(A1): does this line *increase* or *decrease* the balance shown on the
statement? That framing is account-kind-agnostic — a deposit raises a checking
balance and a purchase raises a card's owed balance, both "increase" — so the
one identity ``opening + Σ(effect) = closing`` reconciles every type. The model
reads and reports the effect; the deterministic normalizer and the
reconciliation gate decide (ADR-010).
"""

PROMPT_VERSION = "stmt-v3"

STATEMENT_EXTRACTION_PROMPT = """\
You are reading one financial statement. Return ONLY a JSON object, no prose.

First decide what this document is and set "doc_type" to exactly one of:
  - "checking_statement"     — a checking / current / bank account statement
  - "savings_statement"      — a savings / money-market account statement
  - "credit_card_statement"  — a credit-card account statement
If it is none of these (pay stub, tax form, brokerage statement, loan statement,
etc.), set "doc_type" to your best short label AND set "transactions" to an empty
list — do not force other documents into this shape.

For a checking, savings, OR credit-card statement, extract this shape:

{
  "doc_type": "checking_statement" | "savings_statement" | "credit_card_statement",
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

What the printed balance means, by type:
- checking / savings: the balance is the money HELD in the account. A deposit,
  credit, or interest payment INCREASES it; a withdrawal, payment, fee, or check
  DECREASES it.
- credit card: the balance is the money OWED. A purchase, charge, fee, or
  interest INCREASES it; a payment or refund/credit DECREASES it. The "opening"
  is the previous balance; the "closing" is the new balance.

Rules:
- "account_number", "institution", "account_names" identify WHOSE account this is
  — extract them as printed; they let the same account be recognized across
  statements even when labelled differently. Include every holder name.
- Copy amounts and dates EXACTLY as printed. Do not reformat, convert, or do math.
- "amount_raw" is always the POSITIVE magnitude; the sign comes from "balance_effect".
- "balance_effect" is "increase" if the line RAISES the printed balance and
  "decrease" if it LOWERS it (see the by-type meaning above). When in doubt, ask:
  after this line, is the statement's running balance higher or lower?
- "running_balance_raw": if the statement prints a running/ledger balance on each
  line, copy it AS PRINTED. If there is no such column, omit the field. It is a
  cross-check that lets a misread line be pinpointed — worth capturing when present.
- List EVERY transaction in the statement period. Completeness matters more than
  anything: a missing transaction will break reconciliation and be caught.
- If a value is genuinely unreadable, write it exactly as best you can see it —
  never invent a figure to make things add up.
"""
