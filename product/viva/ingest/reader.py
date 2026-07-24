"""The live model edge — the ONE place a model reads a document (the network edge).

Everything else in ingest is deterministic and unit-tested offline. This module
is deliberately thin and quarantined: render the pages, fold in the issuer's own
embedded text (the measured product default is text+image — see
docs/document-preprocessing.md), call a shared adapter, and hand the raw output
to the deterministic ``from_model_json`` parser. It proposes; it never certifies.

The read is **two-phase** (the Slice 2 design): a cheap **classify** pass names
the document (first page + its embedded text — no full extraction), then, if a
profile exists for that type, an **extract** pass runs the prompt that type's
profile owns (a shared base + a per-type fragment). A type with no projector yet
is parked after the cheap classify — we don't pay for a full extraction we can't
use. Each pass is recorded verbatim in the claims layer.

Heavy dependencies (pypdfium2 for rendering) are imported lazily so the tested
core never needs them.
"""

from __future__ import annotations

import hashlib
import logging

from vivacore.models import ModelSpec, adapter_for
from vivacore.models.base import PageImage

from .pipeline import ModelPhase, ReadResult
from .prompt_library import classify_prompt
from .registry import extraction_prompt_for
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


def _with_embedded(prompt: str, embedded_text: str) -> str:
    return (prompt + "\n\n[The issuer's own embedded text for these pages follows; "
            "use it together with the image(s).]\n" + embedded_text)


def classify(adapter, pages: list[PageImage], embedded_text: str
             ) -> tuple[str, float, ModelPhase]:
    """Phase 1: name the document cheaply. Sends only the first page image plus
    the embedded text (classification is easy and does not need every page), and
    asks for a type, not figures. Returns (doc_type, confidence, phase-record)."""
    prompt, version = classify_prompt()
    first_page = pages[:1]                    # cheap: one image, not the whole doc
    log.info("reader: classify (first page + %d chars text, prompt=%s) ...",
             len(embedded_text), version)
    result = adapter.extract(first_page, _with_embedded(prompt, embedded_text))
    doc_type, conf = _peek_classification(result.text)
    log.info("reader: classified %r (conf=%.2f, cost $%.4f)",
             doc_type, conf, result.cost_usd)
    phase = ModelPhase(
        phase="classify", model=result.resolved_model, prompt_version=version,
        raw_text=result.text, cost_usd=result.cost_usd,
        input_tokens=result.input_tokens, output_tokens=result.output_tokens,
        input_mode="text+image", parse_ok=doc_type != "unknown")
    return doc_type, conf, phase


def read_statement(pdf_bytes: bytes, doc_id: str, spec: ModelSpec,
                   locale: str, currency: str) -> ReadResult:
    """Read one document two-phase (classify → extract) into a ReadResult.

    The live edge: these are the calls that cost money and leave the machine. The
    output is only a proposal — ``capture_and_ingest`` runs it through the
    reconciliation gate before a single number is trusted."""
    pages, embedded_text = _render_and_read_text(pdf_bytes)
    log.info("reader: rendered %d pages, %d chars of embedded text (%s/%s)",
             len(pages), len(embedded_text), locale, currency)
    adapter = adapter_for(spec)

    doc_type, conf, classify_phase = classify(adapter, pages, embedded_text)

    composed = extraction_prompt_for(doc_type)
    if composed is None:
        # No projector for this type yet — park after the cheap classify, without
        # paying for a full extraction we couldn't use.
        log.info("reader: no projector for %r — parking after classify", doc_type)
        return ReadResult(doc_type=doc_type, doc_type_confidence=conf, facts=None,
                          error=f"no projector yet for '{doc_type}'",
                          phases=[classify_phase])

    prompt_text, prompt_version = composed
    log.info("reader: extract with profile prompt %s via %s (json_mode=%s) ...",
             prompt_version, spec.model, spec.json_mode)
    rr = read_with_retry(lambda p: adapter.extract(pages, p),
                         _with_embedded(prompt_text, embedded_text),
                         doc_id, locale, currency, prompt_version=prompt_version)
    # Classification is authoritative for the type (the extract prompt no longer
    # asks the model to re-decide it); stamp it onto the facts and the result.
    rr.doc_type = doc_type
    rr.doc_type_confidence = conf
    if rr.facts is not None:
        rr.facts.doc_type = doc_type
        rr.facts.doc_type_confidence = conf
    rr.phases = [classify_phase] + rr.phases
    return rr


def read_with_retry(extract, prompt: str, doc_id: str, locale: str,
                    currency: str, prompt_version: str = "",
                    max_retries: int = 1) -> ReadResult:
    """The extract phase: call the model and parse; if the JSON doesn't parse,
    re-ask once with the error (belt-and-suspenders alongside JSON mode).
    ``extract(prompt) -> ModelResult`` is injected so this is testable without the
    network. Populates ``phases`` with the single extract record."""
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

    phase = ModelPhase(
        phase="extract", model=result.resolved_model,
        prompt_version=prompt_version, raw_text=result.text, cost_usd=total_cost,
        input_tokens=result.input_tokens, output_tokens=result.output_tokens,
        input_mode="text+image", parse_ok=err is None, error=err)
    common = dict(raw_text=result.text, model=result.resolved_model,
                  prompt_version=prompt_version, input_mode="text+image",
                  cost_usd=total_cost, input_tokens=result.input_tokens,
                  output_tokens=result.output_tokens, phases=[phase])
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
