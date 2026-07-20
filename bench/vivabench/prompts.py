"""The shared exam question. One template for every candidate (proctor rule).

Version the prompt like everything else on the trust path: results are only
comparable within a prompt version, and the run records carry it.
"""

PROMPT_VERSION = "p1"

EXTRACTION_PROMPT = """\
You are reading a financial document, provided as page images.

Extract EVERY factual claim on the document into JSON. A claim is any of:
- an "amount": any monetary value (transaction, balance, total, fee, rate, minimum due...)
- a "date": any date (statement period bounds, transaction dates, due dates...)
- a "text": a counterparty, payee, or line-item description tied to an amount or date
- an "account_id": any account identifier exactly as printed (including masked forms)
- a "meta": document-level facts (institution name, account type, statement period, currency)

Return ONLY a JSON object, no prose, in exactly this shape:

{
  "claims": [
    {
      "type": "amount" | "date" | "text" | "account_id" | "meta",
      "label": "<what this is, e.g. 'closing balance', 'transaction date', 'payee'>",
      "value_raw": "<the value EXACTLY as printed, character for character>",
      "page": <1-based page number the value appears on>,
      "region": {"x0": 0.0-1.0, "y0": 0.0-1.0, "x1": 0.0-1.0, "y1": 0.0-1.0},
      "confidence": 0.0-1.0,
      "group": "<optional: an id linking claims of one line item, e.g. 'txn-14'>"
    }
  ]
}

Rules:
- "value_raw" must reproduce the printed text exactly — do not normalize numbers,
  currencies, or dates. "1.234,56" stays "1.234,56".
- "region" is the approximate bounding box of the printed value on its page,
  as fractions of page width/height from the top-left corner.
- "confidence" is YOUR honest estimate that value_raw is exactly correct.
  Use the full range; 1.0 means you would stake everything on it.
- Do not skip transactions. Every line item on every page must appear.
- Do not invent claims. If a region is illegible, emit the claim with your best
  reading and a LOW confidence rather than omitting it silently.
"""
