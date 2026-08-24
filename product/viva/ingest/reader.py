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
from .pipeline import DocumentTooLarge, ModelPhase, ReadResult
from . import prompt_library
from .prompt_library import classify_prompt
from .registry import (BROKERAGE_IDENTITY, PAYSTUB_IDENTITY,
                       extraction_prompt_for, profile_for)
from .statement import from_model_json

log = logging.getLogger(__name__)


# What a document may cost before it is refused. A page count and a byte count
# bound the work; the edge cap bounds a single page, because page *size* is not
# bounded by file size at all — a 263-byte PDF may declare the largest MediaBox
# PDF allows, which at scale 2.0 is a 28,800px square and 3.3 GB of bitmap. The
# process that runs out of memory is the one holding the vault key.
MAX_PAGES = 200
MAX_BYTES = 50 * 1024 * 1024
MAX_EDGE_PX = 2000          # matches bench/vivabench/corpus.py


def _render_and_read_text(pdf_bytes: bytes, scale: float = 2.0):
    """Return (pages, embedded_text). Lazy pypdfium2 import (rendering is heavy).

    Bounded three ways, and every handle closed — the bytes are attacker-shaped
    and reach PDFium's parser in this process."""
    import pypdfium2 as pdfium

    if len(pdf_bytes) > MAX_BYTES:
        raise DocumentTooLarge(
            f"the file is {len(pdf_bytes) / 1e6:.1f} MB and the limit is "
            f"{MAX_BYTES / 1e6:.0f} MB")

    pdf = pdfium.PdfDocument(pdf_bytes)
    try:
        if len(pdf) > MAX_PAGES:
            raise DocumentTooLarge(
                f"the document has {len(pdf)} pages and the limit is {MAX_PAGES}")

        pages: list[PageImage] = []
        texts: list[str] = []
        for i in range(len(pdf)):
            page = pdf[i]
            try:
                # Clamped before the bitmap is allocated, not after it exists.
                width, height = page.get_size()
                longest = max(width, height) or 1
                page_scale = min(scale, MAX_EDGE_PX / longest)
                bitmap = page.render(scale=page_scale)
                png = bitmap.to_pil()
                import io
                buf = io.BytesIO()
                png.save(buf, format="PNG")
                data = buf.getvalue()
                pages.append(PageImage(page_number=i + 1, png_bytes=data,
                                       sha256=hashlib.sha256(data).hexdigest()))
                textpage = page.get_textpage()
                texts.append(f"--- page {i + 1} ---\n{textpage.get_text_range()}")
            finally:
                page.close()
        return pages, "\n\n".join(texts)
    finally:
        pdf.close()


# The frame that holds the document's own text apart from the instructions. Its
# text is a prompt file like any other, so it is versioned, immutable once
# released, and recoverable from a recorded `prompt_version`.
EMBEDDED_FRAME = "untrusted-frame-v1"
# Two failures, two asks: a syntax error asks for valid JSON; a value that would
# not normalize means the JSON was fine and one field is wrong, so the re-ask
# names that field.
RETRY_SYNTAX = "retry-syntax-v1"
RETRY_VALUE = "retry-value-v1"
_SLOT = "{{DOCUMENT_TEXT}}"


def _with_embedded(prompt: str, embedded_text: str) -> tuple[str, str]:
    """Compose the trusted prompt with the document's own text, framed.

    Returns ``(text, frame_version)``. The frame closes the untrusted document
    block and restates the trusted task afterwards. Embedded closing tags are
    defanged so document text cannot terminate its own frame."""
    frame = prompt_library.fragment(EMBEDDED_FRAME)
    before, after = frame.split(_SLOT, 1)
    safe = embedded_text.replace("</untrusted_document_text>",
                                 "<\u200b/untrusted_document_text>")
    return prompt + "\n\n" + before + safe + after, EMBEDDED_FRAME


def _usage_reported(response: object) -> bool:
    """Whether a provider response contains token usage, not adapter zeros."""
    if not isinstance(response, dict):
        return False
    usage = response.get("usage")
    if not isinstance(usage, dict):
        return False
    return any(key in usage for key in (
        "prompt_tokens", "completion_tokens", "input_tokens", "output_tokens"))


def classify(adapter, pages: list[PageImage], embedded_text: str,
             configured_model: str = ""
             ) -> tuple[str, float, ModelPhase]:
    """Phase 1: name the document.

    Sends only the first page image plus the embedded text, and asks for a type
    rather than figures. Returns (doc_type, confidence, phase-record); the type
    is "unknown" at confidence 0.0 when the reply does not parse."""
    prompt, version = classify_prompt()
    first_page = pages[:1]                    # cheap: one image, not the whole doc
    log.info("reader: classify (first page + %d chars text, prompt=%s) ...",
             len(embedded_text), version)
    framed, frame_version = _with_embedded(prompt, embedded_text)
    version = f"{version}+{frame_version}"
    result = adapter.extract(first_page, framed)
    doc_type, conf = _peek_classification(result.text)
    log.info("reader: classified %r (conf=%.2f, cost $%.4f)",
             doc_type, conf, result.cost_usd)
    phase = ModelPhase(
        phase="classify", model=configured_model or result.resolved_model,
        resolved_model=result.resolved_model, prompt_version=version,
        raw_text=result.text, cost_usd=result.cost_usd,
        input_tokens=result.input_tokens, output_tokens=result.output_tokens,
        input_mode="text+image", parse_ok=doc_type != "unknown",
        usage_reported=_usage_reported(result.response))
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

    doc_type, conf, classify_phase = classify(
        adapter, pages, embedded_text, configured_model=spec.model)

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
    framed, frame_version = _with_embedded(prompt_text, embedded_text)
    prompt_version = f"{prompt_version}+{frame_version}"
    rr = read_with_retry(lambda p: adapter.extract(pages, p), framed,
                         doc_id, locale, currency, prompt_version=prompt_version,
                         parse_fn=parse_fn, configured_model=spec.model)
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


def parking_reader():
    """The read function for a path that captures and does not read.

    A caller that must not read asks for this rather than building a reader and
    discarding the live half: discarding is one line away from not discarding,
    and a function with no branch that could return a live reader is not. What
    comes back opens no connection and names no model, whatever the environment
    holds.
    """
    return _parking_reader


def live_reading_configured() -> bool:
    """Whether this environment names both halves of a live reader.

    A caller that parks by construction still has two true things it might say
    about why nothing was read, and this is the one that tells them apart. It
    asks the same question :func:`build_reader` asks and builds nothing, so
    knowing the answer costs no adapter, no key and no call.
    """
    import os

    return bool(os.environ.get("VIVA_MODEL_ADAPTER")
                and os.environ.get("VIVA_MODEL"))


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

    if not live_reading_configured():
        return parking_reader(), False
    adapter = os.environ.get("VIVA_MODEL_ADAPTER")
    model = os.environ.get("VIVA_MODEL")

    key_env = os.environ.get("VIVA_MODEL_KEY_ENV", "ANTHROPIC_API_KEY")
    spec = ModelSpec(
        name="viva-reader", adapter=adapter, model=model,
        base_url=os.environ.get("VIVA_MODEL_BASE_URL"),
        api_key_env=None if (key_env or "").lower() in ("", "none") else key_env,
        json_mode=True)
    locale = locale_from_env()
    currency = currency_from_env()

    def reader(data, doc_id):
        return read_statement(data, doc_id, spec, locale, currency)

    return reader, True


def read_with_retry(extract, prompt: str, doc_id: str, locale: str,
                    currency: str, prompt_version: str = "",
                    max_retries: int = 1, parse_fn=from_model_json,
                    configured_model: str = "") -> ReadResult:
    """The extract phase: call the model and parse, re-asking on a parse failure.

    ``extract(prompt) -> ModelResult`` is injected, so this runs without the
    network; ``parse_fn`` is the type's facts parser. Retries up to
    ``max_retries`` times, and the retry names the offending field for a value
    error and asks for valid JSON for a syntax error. ``cost_usd`` on the result
    is the total across every attempt. Every outbound request is retained as a
    distinct extract phase; ``facts=None`` and ``error`` are set when none
    parsed."""
    result = extract(prompt)
    facts, err = parse_fn(result.text, doc_id, locale, currency)
    total_cost = result.cost_usd
    tries = 0
    used_versions: set[str] = set()
    attempts = [(result, prompt_version, err)]
    while err is not None and tries < max_retries:
        tries += 1
        log.warning("reader: parse FAILED (%s); re-asking the model (retry %d)",
                    err, tries)
        # Two failures, two asks. A syntax error asks for valid JSON; a value
        # that would not normalize means the JSON was fine and one field is
        # wrong, so the retry names that field.
        retry_id = (RETRY_SYNTAX if _is_syntax_error(err) else RETRY_VALUE)
        retry_prompt = (prompt + "\n\n"
                        + prompt_library.fragment(retry_id).replace("{err}", str(err)))
        # The re-ask is what produced whatever comes back, so it is named on the
        # reading. Without this the recorded version resolves to the first ask
        # only, and a retry-produced figure cites text that did not produce it.
        used_versions.add(retry_id)
        result = extract(retry_prompt)
        total_cost += result.cost_usd
        facts, err = parse_fn(result.text, doc_id, locale, currency)
        attempt_version = prompt_version
        for extra in sorted(used_versions):
            attempt_version = f"{attempt_version}+{extra}"
        attempts.append((result, attempt_version, err))

    log.info("reader: model %s replied %d chars, cost $%.4f (parse_ok=%s%s)",
             result.resolved_model, len(result.text), total_cost, err is None,
             f", {tries} retr{'y' if tries == 1 else 'ies'}" if tries else "")
    log.debug("reader: RAW model output:\n%s", result.text)

    for extra in sorted(used_versions):
        prompt_version = f"{prompt_version}+{extra}"

    phases = [ModelPhase(
        phase="extract",
        model=configured_model or attempt.resolved_model,
        resolved_model=attempt.resolved_model,
        prompt_version=attempt_version, raw_text=attempt.text,
        cost_usd=attempt.cost_usd,
        input_tokens=attempt.input_tokens, output_tokens=attempt.output_tokens,
        input_mode="text+image", parse_ok=attempt_error is None,
        error=attempt_error,
        usage_reported=_usage_reported(attempt.response))
        for attempt, attempt_version, attempt_error in attempts]
    input_tokens = sum(attempt.input_tokens for attempt, _, _ in attempts)
    output_tokens = sum(attempt.output_tokens for attempt, _, _ in attempts)
    common = dict(raw_text=result.text,
                  model=configured_model or result.resolved_model,
                  resolved_model=result.resolved_model,
                  prompt_version=prompt_version, input_mode="text+image",
                  cost_usd=total_cost, input_tokens=input_tokens,
                  output_tokens=output_tokens, phases=phases,
                  usage_reported=any(_usage_reported(attempt.response)
                                     for attempt, _, _ in attempts))
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
