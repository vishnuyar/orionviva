"""The live model edge — the ONE place a model reads a document (the network edge).

Everything else in ingest is deterministic and unit-tested offline. This module
is deliberately thin and quarantined: render the pages, fold in the issuer's own
embedded text (the measured product default is text+image — see
docs/document-preprocessing.md), call a shared adapter, and hand the raw output
to the deterministic ``from_model_json`` parser. It proposes; it never certifies.

Heavy dependencies (pypdfium2 for rendering) are imported lazily so the tested
core never needs them. This edge is intentionally left unrun until a real
statement and the author's own keys are in hand — the reconciliation gate, not
this reader, is what makes any of it trustworthy.
"""

from __future__ import annotations

import hashlib
import logging

from vivacore.models import ModelSpec, adapter_for
from vivacore.models.base import PageImage

from .pipeline import ReadResult
from .prompts import PROMPT_VERSION, STATEMENT_EXTRACTION_PROMPT
from .statement import from_model_json

log = logging.getLogger(__name__)


def _render_and_read_text(pdf_bytes: bytes, scale: float = 2.0):
    """Return (pages, embedded_text). Lazy pypdfium2 import (rendering is heavy)."""
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(pdf_bytes)
    pages: list[PageImage] = []
    texts: list[str] = []
    for i in range(len(pdf)):
        page = pdf[i]
        bitmap = page.render(scale=scale)
        png = bitmap.to_pil()
        import io
        buf = io.BytesIO()
        png.save(buf, format="PNG")
        data = buf.getvalue()
        pages.append(PageImage(page_number=i + 1, png_bytes=data,
                               sha256=hashlib.sha256(data).hexdigest()))
        textpage = page.get_textpage()
        texts.append(f"--- page {i + 1} ---\n{textpage.get_text_range()}")
    return pages, "\n\n".join(texts)


def read_statement(pdf_bytes: bytes, doc_id: str, spec: ModelSpec,
                   locale: str, currency: str) -> ReadResult:
    """Read one statement with a model (text+image) into a ReadResult.

    The live edge: this is the call that costs money and leaves the machine. The
    output is only a proposal — ``capture_and_ingest`` runs it through the
    reconciliation gate before a single number is trusted."""
    pages, embedded_text = _render_and_read_text(pdf_bytes)
    log.info("reader: rendered %d pages, %d chars of embedded text (%s/%s)",
             len(pages), len(embedded_text), locale, currency)
    prompt = (STATEMENT_EXTRACTION_PROMPT
              + "\n\n[The issuer's own embedded text for these pages follows; "
                "use it together with the images.]\n" + embedded_text)
    adapter = adapter_for(spec)
    log.info("reader: calling model %s (%s, json_mode=%s) ...",
             spec.model, spec.adapter, spec.json_mode)
    return read_with_retry(lambda p: adapter.extract(pages, p), prompt,
                           doc_id, locale, currency)


def read_with_retry(extract, prompt: str, doc_id: str, locale: str,
                    currency: str, max_retries: int = 1) -> ReadResult:
    """Call the model and parse; if the JSON doesn't parse, re-ask once with the
    error (belt-and-suspenders alongside JSON mode). ``extract(prompt) ->
    ModelResult`` is injected so this is testable without the network."""
    result = extract(prompt)
    facts, err = from_model_json(result.text, doc_id, locale, currency)
    total_cost = result.cost_usd
    tries = 0
    while err is not None and tries < max_retries:
        tries += 1
        log.warning("reader: parse FAILED (%s); re-asking the model (retry %d)",
                    err, tries)
        retry_prompt = (prompt + "\n\nYour previous reply was NOT valid JSON "
                        f"({err}). Return ONLY one valid JSON object: escape "
                        "quotes and newlines inside strings, no trailing commas.")
        result = extract(retry_prompt)
        total_cost += result.cost_usd
        facts, err = from_model_json(result.text, doc_id, locale, currency)

    log.info("reader: model %s replied %d chars, cost $%.4f (parse_ok=%s%s)",
             result.resolved_model, len(result.text), total_cost, err is None,
             f", {tries} retr{'y' if tries == 1 else 'ies'}" if tries else "")
    log.debug("reader: RAW model output:\n%s", result.text)

    common = dict(raw_text=result.text, model=result.resolved_model,
                  prompt_version=PROMPT_VERSION, input_mode="text+image",
                  cost_usd=total_cost, input_tokens=result.input_tokens,
                  output_tokens=result.output_tokens)
    if err is not None:
        doc_type, conf = _peek_classification(result.text)
        log.warning("reader: parse still FAILED after retry (%s); classified %r",
                    err, doc_type)
        return ReadResult(doc_type=doc_type, doc_type_confidence=conf,
                          facts=None, error=err, **common)
    log.info("reader: parsed %s (%s) with %d transactions",
             facts.doc_type, facts.account_ref, len(facts.transactions))
    return ReadResult(doc_type=facts.doc_type,
                      doc_type_confidence=facts.doc_type_confidence,
                      facts=facts, **common)


def _peek_classification(text: str) -> tuple[str, float]:
    import json
    import re
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        try:
            d = json.loads(m.group(0))
            return (str(d.get("doc_type", "unknown")).lower(),
                    float(d.get("doc_type_confidence", 0.0) or 0.0))
        except (json.JSONDecodeError, TypeError, ValueError):
            pass
    return "unknown", 0.0
