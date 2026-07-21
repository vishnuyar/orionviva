"""The shared exam question. One template for every candidate (proctor rule).

Version the prompt like everything else on the trust path: results are only
comparable within a prompt version, and the run records carry it.

p2: one page per call. A whole dense document needs ~62k output tokens, which
exceeds the output ceiling of every small candidate (32k for the Qwen class) —
scoring them on a truncated answer would measure the ceiling, not the reading.
Pages are therefore extracted one at a time and merged; the model is told which
page it is looking at so claim page numbers stay absolute.

Input modes: the same question, asked over different inputs, so the benchmark
can measure whether preprocessing helps rather than assume it. Versions are
per-mode so that adding a mode never invalidates results already collected
under another one — "p2" image records stay comparable forever.
"""

PROMPT_VERSION = "p2"        # the image-mode prompt; unchanged since p2

INPUT_MODES = ("image", "text", "text+image")

PROMPT_VERSIONS = {
    "image": "p2",
    "text": "t1",
    "text+image": "ti1",
}

EXTRACTION_PROMPT = """\
You are reading ONE page of a financial document, provided as a page image.

This image is page {page_number} of {page_count} of the document. Every claim
you emit must carry "page": {page_number}. Extract only what is printed on THIS
page; other pages are handled separately.

Extract EVERY factual claim on the page into JSON. A claim is any of:
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
      "page": {page_number},
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
- Do not skip transactions. Every line item on this page must appear.
- Do not invent claims. If a region is illegible, emit the claim with your best
  reading and a LOW confidence rather than omitting it silently.
- If this page carries no extractable claims, return {"claims": []}.
"""


# Each mode owns its opening: what the input IS, and how the page is identified.
# The task itself (everything from "Extract EVERY factual claim") is shared
# verbatim, so a mode comparison measures the input, not a reworded question.
# The image header is byte-identical to p2 — image results stay comparable.
_HEADERS = {
    "image": """\
You are reading ONE page of a financial document, provided as a page image.

This image is page {page_number} of {page_count} of the document. Every claim
you emit must carry "page": {page_number}. Extract only what is printed on THIS
page; other pages are handled separately.
""",
    "text": """\
You are reading ONE page of a financial document, provided as the exact text
the issuing institution embedded in the PDF. This is not OCR — these are the
characters the institution itself rendered. It is, however, a flat character
stream: column and row alignment may be lost, so read the structure carefully.

This is page {page_number} of {page_count} of the document. Every claim you
emit must carry "page": {page_number}. Extract only what is printed on THIS
page; other pages are handled separately.
""",
    "text+image": """\
You are reading ONE page of a financial document, provided TWICE: as a page
image, and as the exact text the issuing institution embedded in the PDF. The
text is not OCR — these are the characters the institution itself rendered —
but it is a flat character stream, so column and row alignment can be lost in
it. The image shows the true layout.

Use both. Take each value's exact characters from the text, and take its
position, its column, and which row or section it belongs to from the image.
Where they disagree, trust the TEXT for what the characters are and the IMAGE
for what they mean.

This is page {page_number} of {page_count} of the document. Every claim you
emit must carry "page": {page_number}. Extract only what is printed on THIS
page; other pages are handled separately.
""",
}

_PAGE_TEXT_BLOCK = """

--- BEGIN EMBEDDED TEXT, PAGE {page_number} ---
{page_text}
--- END EMBEDDED TEXT, PAGE {page_number} ---
"""


def page_prompt(
    page_number: int, page_count: int, mode: str = "image", page_text: str = ""
) -> str:
    """The exam question for one page, in one input mode.

    Identical for every candidate within a mode (the proctor rule): only the
    input changes, never the question. Plain substitution, not str.format: the
    template contains literal JSON braces, and an accidental format-spec error
    in the exam question would be a silent change to what every candidate is
    asked.
    """
    if mode not in INPUT_MODES:
        raise ValueError(f"unknown input mode {mode!r}; expected one of {INPUT_MODES}")

    marker = "Extract EVERY factual claim"
    body = EXTRACTION_PROMPT[EXTRACTION_PROMPT.index(marker):]   # the shared task
    prompt = _HEADERS[mode] + "\n" + body
    if mode in ("text", "text+image"):
        # An empty block is honest: this page carries no embedded text. The
        # caller has already established it is blank rather than a scan.
        body_text = page_text if page_text.strip() else "(this page has no embedded text)"
        prompt += _PAGE_TEXT_BLOCK.replace("{page_text}", body_text)
    return prompt.replace("{page_number}", str(page_number)).replace(
        "{page_count}", str(page_count)
    )
