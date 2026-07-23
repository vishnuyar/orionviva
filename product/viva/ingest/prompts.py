"""The statement-extraction prompt. Versioned (T8): a prompt change is a new
version, so a stored read can always be traced to the exact instructions that
produced it.

The prompt asks for the structure ``statement.from_model_json`` expects, and —
critically — asks for values *as printed*, with the sign carried by an explicit
``direction`` field. The model reads; the deterministic normalizer and the
reconciliation gate decide. It is told to say so when a document is not a
checking statement rather than forcing one.
"""

PROMPT_VERSION = "stmt-v1"

STATEMENT_EXTRACTION_PROMPT = """\
You are reading one financial statement. Return ONLY a JSON object, no prose.

First decide what this document is. If it is a checking or bank account
statement, set "doc_type" to "checking_statement". If it is something else
(credit card statement, pay stub, tax form, brokerage statement, etc.), set
"doc_type" to your best short label and set "transactions" to an empty list —
do not force non-checking documents into this shape.

For a checking/bank statement, extract:

{
  "doc_type": "checking_statement",
  "doc_type_confidence": 0.0-1.0,
  "account_ref": "how the statement identifies the account (name + masked number)",
  "opening": {"amount_raw": "the opening/beginning balance AS PRINTED", "date_raw": "the period start date AS PRINTED", "page": <page number>},
  "closing": {"amount_raw": "the closing/ending balance AS PRINTED", "date_raw": "the period end date AS PRINTED", "page": <page number>},
  "transactions": [
    {"date_raw": "AS PRINTED", "description": "AS PRINTED", "amount_raw": "the POSITIVE magnitude AS PRINTED", "direction": "credit" or "debit", "running_balance_raw": "the running/ledger balance printed on this line, if any", "page": <page number>}
  ]
}

Rules:
- Copy amounts and dates EXACTLY as printed. Do not reformat, convert, or do math.
- "direction" is "credit" for money INTO the account (deposits, credits) and
  "debit" for money OUT (withdrawals, payments, fees, checks).
- "amount_raw" is always the positive magnitude; the sign comes from "direction".
- "running_balance_raw": if the statement prints a running/ledger balance on each
  line, copy it AS PRINTED. If there is no such column, omit the field. It is a
  cross-check that lets a misread line be pinpointed — worth capturing when present.
- List EVERY transaction in the statement period. Completeness matters more than
  anything: a missing transaction will break reconciliation and be caught.
- If a value is genuinely unreadable, write it exactly as best you can see it —
  never invent a figure to make things add up.
"""
