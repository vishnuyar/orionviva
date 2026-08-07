"""The live model edge — the one place in ingest that reads a document.

Renders the pages, folds in the issuer's own embedded text (the product default
is text+image), calls a shared adapter, and hands the raw output to a
deterministic parser. It proposes; it never certifies.

The read is two-phase: a cheap **classify** pass names the document from the
first page and its embedded text, then, if a profile exists for that type, an
**extract** pass runs the prompt that profile owns. A type with no projector
parks after the classify pass, with no extraction paid for. Each pass is
recorded verbatim in the claims layer.

pypdfium2 is imported lazily, so the rest of ingest never needs it.
"""

from __future__ import annotations

import hashlib
import logging

from vivacore.models import ModelSpec, adapter_for
from vivacore.models.base import PageImage

from .brokerage import from_brokerage_json
from .paystub import from_paystub_json
from .pipeline import ModelPhase, ReadResult
from .prompt_library import classify_prompt
from .registry import (BROKERAGE_IDENTITY, PAYSTUB_IDENTITY,
                       extraction_prompt_for, profile_for)
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
    """Phase 1: name the document.

    Sends only the first page image plus the embedded text, and asks for a type
    rather than figures. Returns (doc_type, confidence, phase-record); the type
    is "unknown" at confidence 0.0 when the reply does not parse."""
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

    These are the calls that leave the machine. The result is a proposal:
    ``capture_and_ingest`` puts it through the reconciliation gate before any
    number is trusted. The classification is authoritative for the document
    type, and is stamped onto the returned facts."""
    pages, embedded_text = _render_and_read_text(pdf_bytes)
    log.info("reader: rendered %d pages, %d chars of embedded text (%s/%s)",
             len(pages), len(embedded_text), locale, currency)
    adapter = adapter_for(spec)

    doc_type, conf, classify_phase = classify(adapter, pages, embedded_text)

    composed = extraction_prompt_for(doc_type)
    if composed is None:
        # No projector for this type: park after the classify pass rather than
        # paying for an extraction nothing can use.
        log.info("reader: no projector for %r — parking after classify", doc_type)
        return ReadResult(doc_type=doc_type, doc_type_confidence=conf, facts=None,
                          error=f"no projector yet for '{doc_type}'",
                          phases=[classify_phase])

    prompt_text, prompt_version = composed
    # The profile's identity selects the facts parser: same two-phase read,
    # different shape.
    profile = profile_for(doc_type)
    identity = profile.identity if profile else ""
    parse_fn = {PAYSTUB_IDENTITY: from_paystub_json,
                BROKERAGE_IDENTITY: from_brokerage_json}.get(identity, from_model_json)
    log.info("reader: extract with profile prompt %s via %s (json_mode=%s) ...",
             prompt_version, spec.model, spec.json_mode)
    rr = read_with_retry(lambda p: adapter.extract(pages, p),
                         _with_embedded(prompt_text, embedded_text),
                         doc_id, locale, currency, prompt_version=prompt_version,
                         parse_fn=parse_fn)
    # The extract prompt does not ask the model to re-decide the type, so the
    # classification is stamped onto the facts and the result.
    rr.doc_type = doc_type
    rr.doc_type_confidence = conf
    if rr.facts is not None:
        rr.facts.doc_type = doc_type
        rr.facts.doc_type_confidence = conf
    rr.phases = [classify_phase] + rr.phases
    return rr


def _parking_reader(data, doc_id):
    """The reader when no model is configured: capture the document, park it,
    read nothing. Nothing leaves the machine."""
    return ReadResult("unknown", 0.0, None, "no model configured for live reading")


def build_reader():
    """The document reader the environment configures, as `(read_fn, is_live)`.

    A live reader is returned only when both VIVA_MODEL_ADAPTER and VIVA_MODEL
    are set; otherwise `(_parking_reader, False)` and every document parks
    unread. Every entry point that ingests documents builds its reader here, so
    one setting means the same thing wherever it is read.

    Env to enable live reading:
      VIVA_MODEL_ADAPTER   'anthropic' or 'openai-compatible'
      VIVA_MODEL           a pinned model id (not a 'latest' alias)
      VIVA_MODEL_KEY_ENV   name of the env var holding the API key
      VIVA_MODEL_BASE_URL  (openai-compatible only, e.g. OpenRouter)
      VIVA_LOCALE          default 'en-US'      VIVA_CURRENCY default 'USD'
    """
    import os

    from ..env import currency_from_env, locale_from_env

    adapter = os.environ.get("VIVA_MODEL_ADAPTER")
    model = os.environ.get("VIVA_MODEL")
    if not (adapter and model):
        return _parking_reader, False

    spec = ModelSpec(
        name="viva-reader", adapter=adapter, model=model,
        base_url=os.environ.get("VIVA_MODEL_BASE_URL"),
        api_key_env=os.environ.get("VIVA_MODEL_KEY_ENV", "ANTHROPIC_API_KEY"),
        json_mode=True)
    locale = locale_from_env()
    currency = currency_from_env()

    def reader(data, doc_id):
        return read_statement(data, doc_id, spec, locale, currency)

    return reader, True


def read_with_retry(extract, prompt: str, doc_id: str, locale: str,
                    currency: str, prompt_version: str = "",
                    max_retries: int = 1, parse_fn=from_model_json) -> ReadResult:
    """The extract phase: call the model and parse, re-asking on a parse failure.

    ``extract(prompt) -> ModelResult`` is injected, so this runs without the
    network; ``parse_fn`` is the type's facts parser. Retries up to
    ``max_retries`` times, and the retry names the offending field for a value
    error and asks for valid JSON for a syntax error. ``cost_usd`` on the result
    is the total across every attempt. Returns a ReadResult carrying one extract
    phase, with ``facts=None`` and ``error`` set when it never parsed."""
    result = extract(prompt)
    facts, err = parse_fn(result.text, doc_id, locale, currency)
    total_cost = result.cost_usd
    tries = 0
    while err is not None and tries < max_retries:
        tries += 1
        log.warning("reader: parse FAILED (%s); re-asking the model (retry %d)",
                    err, tries)
        # Two failures, two asks. A syntax error asks for valid JSON; a value
        # that would not normalize means the JSON was fine and one field is
        # wrong, so the retry names that field.
        if _is_syntax_error(err):
            retry_prompt = (prompt + "\n\nYour previous reply was NOT valid JSON "
                            f"({err}). Return ONLY one valid JSON object: escape "
                            "quotes and newlines inside strings, no trailing commas.")
        else:
            retry_prompt = (
                prompt + "\n\nYour previous reply was valid JSON, but one value "
                f"could not be read: {err}. Return the SAME JSON with ONLY that "
                "field corrected — copy it exactly as printed on the document, or "
                "use \"\" if the document does not show it. Never invent a value.")
        result = extract(retry_prompt)
        total_cost += result.cost_usd
        facts, err = parse_fn(result.text, doc_id, locale, currency)

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
    log.info("reader: parsed %s (%d line(s))", facts.doc_type,
             len(getattr(facts, "transactions", getattr(facts, "deductions", []))))
    return ReadResult(doc_type=facts.doc_type,
                      doc_type_confidence=facts.doc_type_confidence,
                      facts=facts, **common)


def _is_syntax_error(err: str) -> bool:
    """True when the reply was not parseable JSON at all, as opposed to one
    value inside good JSON failing to normalize."""
    low = (err or "").lower()
    return ("json did not parse" in low or "no json object" in low
            or "top-level json" in low)


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
