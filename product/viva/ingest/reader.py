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
import math
from dataclasses import replace

from vivacore.models import ModelSpec, adapter_for
from vivacore.models.base import PageImage

from .brokerage import from_brokerage_json
from .paystub import from_paystub_json
from .pipeline import DocumentTooLarge, ModelPhase, ReadResult
from . import prompt_library
from .prompt_library import classify_prompt
from .registry import (BALANCE_IDENTITY, BROKERAGE_IDENTITY, PAYSTUB_IDENTITY, INSTRUMENT_IDENTITY,
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


def _render_and_read_text(pdf_bytes: bytes, scale: float = 2.0, *, checkpoint=None):
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
            if checkpoint is not None:checkpoint()
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
RETRY_VALUE = "retry-value-v2"
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
    classification_error=None
    try:doc_type, conf = _peek_classification(result.text)
    except Exception as exc:
        doc_type,conf='unknown',0.0
        classification_error=f'classification parser raised {type(exc).__name__}'
    log.info("reader: classified %r (conf=%.2f, cost $%.4f)",
             doc_type, conf, result.cost_usd)
    phase = ModelPhase(
        phase="classify", model=configured_model or result.resolved_model,
        resolved_model=result.resolved_model, prompt_version=version,
        raw_text=result.text, cost_usd=result.cost_usd,
        input_tokens=result.input_tokens, output_tokens=result.output_tokens,
        input_mode="text+image", parse_ok=doc_type != "unknown",error=classification_error,
        usage_reported=_usage_reported(result.response))
    return doc_type, conf, phase


def read_statement(pdf_bytes: bytes, doc_id: str, spec: ModelSpec,
                   locale: str, currency: str) -> ReadResult:
    """Read one document two-phase (classify → extract) into a ReadResult.

    These are the calls that leave the machine. The result is a proposal:
    ``capture_and_ingest`` puts it through the reconciliation gate before any
    number is trusted. The classification is authoritative for the document
    type, and is stamped onto the returned facts."""
    from ..normalization_context import ExtractionNormalizationContext
    from vivacore.verify.normalize import RULES_VERSION
    ExtractionNormalizationContext(1, RULES_VERSION, locale, currency)
    pages, embedded_text = _render_and_read_text(pdf_bytes)
    log.info("reader: rendered %d pages, %d chars of embedded text (%s/%s)",
             len(pages), len(embedded_text), locale, currency)
    return read_prepared_statement(tuple(pages), embedded_text, doc_id, spec, locale, currency)


class ReadStopped(Exception):
    """A coordinator denied a new model request after retaining prior phases."""


def prepare_statement(pdf_bytes, *, checkpoint=None):
    return _render_and_read_text(pdf_bytes,checkpoint=checkpoint)


def read_prepared_statement(pages, embedded_text, doc_id, spec, locale, currency,
                            *, phase_sink=None, permit=None, response_sink=None):
    """Read immutable prepared images; this path never enters PDFium."""
    from ..normalization_context import ExtractionNormalizationContext
    from vivacore.verify.normalize import RULES_VERSION
    ExtractionNormalizationContext(1, RULES_VERSION, locale, currency)
    if type(pages) is not tuple or not pages or len(pages)>MAX_PAGES:
        raise ValueError('bounded prepared pages required')
    adapter = adapter_for(spec)
    from uuid import uuid4
    from vivacore.models.base import extraction_transport_scope
    extraction_id = uuid4().hex
    scoped = phase_sink is not None or response_sink is not None
    class ControlledAdapter:
        phase = 'classify'
        context = None
        version = '+'.join((classify_prompt()[1], EMBEDDED_FRAME))
        attempt = 0
        links = None
        failures = None
        received = 0
        def extract(self,images,prompt):
            if not scoped:
                if permit is not None and not permit():raise ReadStopped()
                return adapter.extract(images,prompt)
            self.links = []
            self.received = 0
            self.reported_usage = []
            def admit(kind,model,ordinal):
                if permit is not None and not permit():raise ReadStopped()
            def receive(kind,model,ordinal,status,raw):
                self.received += 1
                from ..extraction_responses import response_body
                body = response_body(doc_id, extraction_id, self.phase, self.attempt,
                    ordinal, kind, model, self.version, 'text+image', status, raw)
                if response_sink is not None:
                    identity = response_sink(body)
                    if type(identity) is not str or not identity:
                        raise ValueError('durable response acknowledgement unavailable')
                    self.links.append(identity)
                from types import SimpleNamespace
                from ..extraction_responses import summary
                metadata=summary(SimpleNamespace(body=body,event_id=''))
                self.reported_usage.append((metadata['input_tokens'],metadata['output_tokens']))
            with extraction_transport_scope(admit,receive) as scope:
                try:
                    # Non-HTTP test adapters retain the existing logical admission.
                    if not hasattr(adapter, 'candidate'):
                        admit('', spec.model, 0)
                    result = adapter.extract(images,prompt)
                except Exception:
                    if scope.turns:
                        turns = scope.turns
                        measured,inputs,outputs=self.usage_totals()
                        failed = ModelPhase(self.phase, spec.model, self.version,
                            ''.join(turn.text for turn in turns), parse_ok=False,
                            error='incomplete extraction transport',
                            cost_usd=sum(turn.cost_usd for turn in turns),
                            input_tokens=inputs,output_tokens=outputs,
                            usage_reported=measured,
                            transport_receipt_ids=list(self.links), transport_complete=False,
                            extraction_id=extraction_id, phase_attempt=self.attempt,
                            normalization_context=self.context if self.phase == 'extract' else None)
                        self.failures = failed
                        if phase_sink is not None:phase_sink(failed,'unknown',0.0)
                    raise
            self.attempt += 1
            return result
        def usage_totals(self):
            if not self.reported_usage or any(
                    value is None for row in self.reported_usage for value in row):
                return False,0,0
            return (True,sum(row[0] for row in self.reported_usage),
                    sum(row[1] for row in self.reported_usage))
        def decorate(self, phase):
            if scoped and self.received:
                phase.usage_reported,phase.input_tokens,phase.output_tokens=self.usage_totals()
                phase.transport_receipt_ids=list(self.links or [])
                phase.transport_complete=True
                phase.extraction_id=extraction_id
                phase.phase_attempt=self.attempt-1
            return phase
    controlled=ControlledAdapter()
    try:
        doc_type, conf, classify_phase = classify(
            controlled, pages, embedded_text, configured_model=spec.model)
        classify_phase=controlled.decorate(classify_phase)
    except Exception as exc:
        if not scoped:raise
        return ReadResult('unknown',0.0,None,error='read stopped' if isinstance(exc,ReadStopped)
                          else 'read request failed',
                          phases=([controlled.failures] if controlled.failures is not None else []))

    from ..ledger.projection.coverage import canonical_classification
    capture_type, capture_conf, classification_error = canonical_classification(doc_type, conf)
    if classification_error:
        classify_phase.parse_ok = False
        classify_phase.error = classification_error
    if phase_sink is not None:phase_sink(classify_phase,capture_type,capture_conf)
    try:
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
        extraction_context = ExtractionNormalizationContext(
            2 if profile and profile.instrument_source_contract else 1,
            RULES_VERSION, locale, currency,
            profile.instrument_source_contract if profile else None)
        parse_fn = {PAYSTUB_IDENTITY: from_paystub_json,
                    BROKERAGE_IDENTITY: from_brokerage_json}.get(identity, from_model_json)
        if identity == INSTRUMENT_IDENTITY:
            from .instrument_read import parser_for, validate_sources
            if not math.isfinite(conf) or not 0 <= conf <= 1:
                classify_phase.parse_ok = False
                classify_phase.error = "invalid instrument classification confidence"
                return ReadResult(doc_type, 0.0, None, classify_phase.error, phases=[classify_phase])
            parse_fn = parser_for(profile.doc_type,
                source_contract=profile.instrument_source_contract, page_count=len(pages))
        if identity in (INSTRUMENT_IDENTITY, BROKERAGE_IDENTITY, BALANCE_IDENTITY, PAYSTUB_IDENTITY):
            from .instrument_read import validate_sources
            source_parser = parse_fn
            def parse_fn(text, captured_id, source_locale, source_currency):
                facts, error = source_parser(text, captured_id, source_locale, source_currency)
                if facts is not None:
                    try:
                        if identity == INSTRUMENT_IDENTITY:
                            validate_sources(facts.payload, captured_id, len(pages))
                        elif identity == PAYSTUB_IDENTITY:
                            from ..investment.payroll_extraction import validate_pages
                            from ..retirement_funding.payroll_v2 import invalidate_period_pages
                            facts=invalidate_period_pages(facts,len(pages))
                            validate_pages(facts.payroll_source, len(pages))
                        elif identity == BROKERAGE_IDENTITY:
                            from ..investment.payroll_extraction import validate_pages
                            validate_pages(facts.investment_source, len(pages))
                            validate_sources([getattr(p, "classification", None)
                                              for p in facts.positions], captured_id, len(pages))
                        else:
                            reference_pages = [getattr(facts, "source_account_ref_page", None)]
                            reference_pages += [row.page for row in facts.transactions
                                if getattr(row, "source_reference", "") or getattr(row, "counterparty_reference", "")]
                            if any(page is not None and (type(page) is not int or not 1 <= page <= len(pages))
                                   for page in reference_pages):
                                raise ValueError("reference evidence is outside the captured document")
                        if identity in (BALANCE_IDENTITY, BROKERAGE_IDENTITY):
                            facts.validated_source_page_count = len(pages)
                    except ValueError as exc:
                        return None, str(exc)
                return facts, error
        log.info("reader: extract with profile prompt %s via %s (json_mode=%s) ...",
                 prompt_version, spec.model, spec.json_mode)
        framed, frame_version = _with_embedded(prompt_text, embedded_text)
        prompt_version = f"{prompt_version}+{frame_version}"
        if phase_sink is not None:
            selected_parser=parse_fn
            def parse_fn(*args):
                facts,error=selected_parser(*args)
                if facts is not None:
                    facts=replace(facts,doc_type=capture_type,doc_type_confidence=conf)
                return facts,error
        controlled.phase='extract'
        controlled.context=extraction_context
        controlled.version=prompt_version
        controlled.attempt=0
        captured_extract=[]
        def capture_extract(phase):
            controlled.decorate(phase)
            phase_sink(phase,doc_type,conf)
            captured_extract.append(phase)
        rr = read_with_retry(lambda p: controlled.extract(pages, p), framed,
                             doc_id, locale, currency, prompt_version=prompt_version,
                             parse_fn=parse_fn, configured_model=spec.model,
                             phase_sink=(None if phase_sink is None else capture_extract),
                             before_extract=lambda version:setattr(controlled,"version",version),
                             extraction_context=extraction_context, source_doc_type=profile.doc_type)
        # The extract prompt does not ask the model to re-decide the type, so the
        # classification is stamped onto the facts and the result.
        rr.doc_type = doc_type
        rr.doc_type_confidence = conf
        if rr.facts is not None and phase_sink is None:
            if identity == INSTRUMENT_IDENTITY:
                rr.doc_type = profile.doc_type
                rr.facts = replace(rr.facts, doc_type=profile.doc_type, doc_type_confidence=conf)
            else:
                rr.facts.doc_type = doc_type
                rr.facts.doc_type_confidence = conf
        rr.phases = [classify_phase] + (captured_extract if phase_sink is not None else rr.phases)
        if controlled.failures is not None:
            rr.phases.append(controlled.failures)
            rr.facts=None
            rr.error='incomplete extraction transport'
        return rr
    except Exception as exc:
        return ReadResult(doc_type,conf,None,error='read stopped' if isinstance(exc,ReadStopped) else 'read request failed',
                          phases=[classify_phase]+([controlled.failures] if controlled.failures is not None else []),source_locale=locale)


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

    reader.prepare=prepare_statement
    reader.read_prepared=lambda pages,text,doc_id,**kwargs:read_prepared_statement(
        tuple(pages),text,doc_id,spec,locale,currency,**kwargs)
    return reader, True


def read_with_retry(extract, prompt: str, doc_id: str, locale: str,
                    currency: str, prompt_version: str = "",
                    max_retries: int = 1, parse_fn=from_model_json,
                    configured_model: str = "", phase_sink=None, before_extract=None,
                    extraction_context=None, source_doc_type="") -> ReadResult:
    """The extract phase: call the model and parse, re-asking on a parse failure.

    ``extract(prompt) -> ModelResult`` is injected, so this runs without the
    network; ``parse_fn`` is the type's facts parser. Retries up to
    ``max_retries`` times, and the retry names the offending field for a value
    error and asks for valid JSON for a syntax error. ``cost_usd`` on the result
    is the total across every attempt. Every outbound request is retained as a
    distinct extract phase; ``facts=None`` and ``error`` are set when none
    parsed."""
    from ..normalization_context import ExtractionNormalizationContext
    from vivacore.verify.normalize import RULES_VERSION
    # Validate before any new paid attempt; provider JSON never supplies this.
    from ..normalization_context import encode_context, source_contract_for_claim
    selected_context = (ExtractionNormalizationContext(1, RULES_VERSION, locale, currency)
                        if extraction_context is None else extraction_context)
    encode_context(selected_context)
    if (selected_context.parser_locale, selected_context.parser_currency) != (locale, currency):
        raise ValueError('extraction context does not match parser inputs')
    source_contract_for_claim(selected_context, source_doc_type, prompt_version)
    attempts = []
    used_versions: set[str] = set()
    tries = 0
    next_prompt = prompt
    facts = None
    while True:
        context = selected_context
        attempt_version = prompt_version
        for extra in sorted(used_versions):
            attempt_version = f"{attempt_version}+{extra}"
        if before_extract is not None:before_extract(attempt_version)
        try:
            result = extract(next_prompt)
        except Exception as exc:
            if not attempts:raise
            facts=None
            err='read stopped' if isinstance(exc,ReadStopped) else 'later read request failed'
            break
        exceptional = False
        try:
            facts, err = parse_fn(result.text, doc_id, locale, currency)
        except Exception as exc:
            facts, err = None, f"parser raised {type(exc).__name__}: {exc}"
            exceptional = True
        if err is not None and type(err) is not str:
            facts, err = None, 'parser returned unsupported error metadata'
            exceptional = True
        attempts.append((result, attempt_version, err, context))
        # Validate actual aggregation before acknowledging this immutable phase.
        try:
            measured_cost=attempts[0][0].cost_usd
            for prior,_,_,_ in attempts[1:]:measured_cost+=prior.cost_usd
            sum(prior.input_tokens for prior,_,_,_ in attempts)
            sum(prior.output_tokens for prior,_,_,_ in attempts)
        except Exception as exc:
            facts=None;err=f'completed response metadata raised {type(exc).__name__}: {exc}'
            attempts[-1]=(result,attempt_version,err,context);exceptional=True
        if phase_sink is not None:
            phase_sink(ModelPhase(phase='extract',model=configured_model or result.resolved_model,
                prompt_version=attempt_version,raw_text=result.text,cost_usd=result.cost_usd,
                input_tokens=result.input_tokens,output_tokens=result.output_tokens,
                input_mode='text+image',parse_ok=err is None,error=err,
                resolved_model=result.resolved_model,usage_reported=_usage_reported(result.response),
                normalization_context=context))
        if err is None or exceptional or tries >= max_retries:
            break
        tries += 1
        try:
            retry_id = RETRY_SYNTAX if _is_syntax_error(err) else RETRY_VALUE
            next_prompt = (prompt + "\n\n" + prompt_library.fragment(retry_id).replace("{err}", str(err)))
            used_versions.add(retry_id)
        except Exception as exc:
            facts, err = None, f"retry preparation raised {type(exc).__name__}: {exc}"
            break  # completed attempt stays retained with its original parse error

    # Aggregate compatibility fields never replace per-attempt measured values.
    # If completed-response metadata cannot aggregate, retain every actual phase
    # and terminate failed rather than manufacture a charge or trigger a retry.
    try:
        total_cost = attempts[0][0].cost_usd
        for attempt, _, _, _ in attempts[1:]:total_cost += attempt.cost_usd
        input_tokens = sum(attempt.input_tokens for attempt, _, _, _ in attempts)
        output_tokens = sum(attempt.output_tokens for attempt, _, _, _ in attempts)
        doc_type = facts.doc_type if facts is not None else "unknown"
        confidence = facts.doc_type_confidence if facts is not None else 0.0
    except Exception as exc:
        facts, err = None, f"completed response metadata raised {type(exc).__name__}: {exc}"
        last, version, _prior_error, context = attempts[-1]
        attempts[-1] = (last, version, err, context)
        total_cost = input_tokens = output_tokens = None
        doc_type, confidence = "unknown", 0.0
    phases = [ModelPhase(
        phase="extract", model=configured_model or attempt.resolved_model,
        resolved_model=attempt.resolved_model, prompt_version=version,
        raw_text=attempt.text, cost_usd=attempt.cost_usd,
        input_tokens=attempt.input_tokens, output_tokens=attempt.output_tokens,
        input_mode="text+image", parse_ok=error is None, error=error,
        usage_reported=_usage_reported(attempt.response), normalization_context=context)
        for attempt, version, error, context in attempts]
    common = dict(raw_text=result.text, source_locale=locale,
                  model=configured_model or result.resolved_model,
                  resolved_model=result.resolved_model,
                  prompt_version=attempts[-1][1], input_mode="text+image",
                  cost_usd=total_cost, input_tokens=input_tokens,
                  output_tokens=output_tokens, phases=phases,
                  usage_reported=any(_usage_reported(attempt.response) for attempt, _, _, _ in attempts),
                  normalization_context=attempts[-1][3])
    if err is not None:
        try:doc_type, confidence = _peek_classification(result.text)
        except Exception:doc_type, confidence = "unknown", 0.0
        return ReadResult(doc_type=doc_type, doc_type_confidence=confidence,
                          facts=None, error=err, **common)
    return ReadResult(doc_type=doc_type, doc_type_confidence=confidence, facts=facts, **common)


def _is_syntax_error(err: str) -> bool:
    """True when the reply was not parseable JSON at all, as opposed to one
    value inside good JSON failing to normalize."""
    low = (err or "").lower()
    return ("json did not parse" in low or "no json object" in low
            or "top-level json" in low)


def _peek_classification(text: str) -> tuple[str, float]:
    from ..ledger.projection.coverage import parse_classification
    return parse_classification(text)
