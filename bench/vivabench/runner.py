"""The proctor: administers the exam identically to every candidate.

What it does:
- iterate the (document x candidate x run) matrix, skipping completed cells;
- render pages once, call the adapter page by page, capture everything raw;
- stop at the budget ceiling by raising BudgetExceeded.

One cell is one (document, candidate, run), but N calls: one per page. Pages are
extracted independently and merged here, so a candidate with a 32k output cap and
one with a 128k cap answer the same question under the same conditions.

A crashed call and a truncated page are both recorded as records rather than
dropped.

Design rationale for page-at-a-time extraction and input modes:
docs/document-preprocessing.md
"""

from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .capture import RunStore
from vivacore.claims import parse_claims
from .config import BenchConfig, Corpus
from .corpus import file_sha256, page_texts, render_pages, text_gaps
from vivacore.models import AdapterError, adapter_for
from vivacore.models.base import ModelResult, PageImage
from vivacore.prompts import PROMPT_VERSIONS, page_prompt


class BudgetExceeded(Exception):
    pass


@dataclass
class RunPlan:
    total_cells: int
    remaining_cells: int
    spent_usd: float
    budget_usd: float


def plan(config: BenchConfig, corpus: Corpus, store: RunStore) -> RunPlan:
    total = len(corpus.documents) * len(config.candidates) * config.runs_per_document
    remaining = sum(
        1
        for doc in corpus.documents
        for cand in config.candidates
        for i in range(1, config.runs_per_document + 1)
        if not store.is_done(doc.id, cand.name, i, config.input_mode)
    )
    return RunPlan(
        total_cells=total,
        remaining_cells=remaining,
        spent_usd=store.spent_usd,
        budget_usd=config.budget_usd,
    )


def _finish_reason(response: dict[str, Any]) -> str | None:
    """The endpoint's own stop signal, across both adapters, or None.

    Reads `choices[0].finish_reason` (or `native_finish_reason`) for
    OpenAI-compatible responses and `stop_reason` for Anthropic's. Truncation is
    never inferred from the shape of the output, only from this value.
    """
    if not isinstance(response, dict):
        return None
    choices = response.get("choices")
    if isinstance(choices, list) and choices and isinstance(choices[0], dict):
        return choices[0].get("finish_reason") or choices[0].get("native_finish_reason")
    return response.get("stop_reason")  # Anthropic Messages API


_TRUNCATED = ("length", "max_tokens", "MAX_TOKENS")


@dataclass
class PageOutcome:
    """One page's call and everything recorded about it."""

    page_number: int
    result: ModelResult
    finish_reason: str | None
    parse_error: str | None
    claim_count: int

    @property
    def truncated(self) -> bool:
        return self.finish_reason in _TRUNCATED


def _extract_one_page(
    adapter, page: PageImage, page_count: int, mode: str, page_text: str
) -> PageOutcome:
    """One page, one call. Touches no shared state, so it is thread-safe."""
    prompt = page_prompt(page.page_number, page_count, mode, page_text)
    # "text" means characters only; sending the image too would make it
    # text+image under another name.
    images = [] if mode == "text" else [page]
    result = adapter.extract(images, prompt)
    claims, parse_error = parse_claims(result.text)
    return PageOutcome(
        page_number=page.page_number,
        result=result,
        finish_reason=_finish_reason(result.response),
        parse_error=parse_error,
        claim_count=len(claims),
    )


def extract_by_page(
    adapter,
    pages: list[PageImage],
    log,
    concurrency: int = 1,
    mode: str = "image",
    texts: list[str] | None = None,
) -> tuple[list[PageOutcome], dict]:
    """Call the adapter once per page and merge the claims into one answer.

    Returns `(outcomes, fields)`: one PageOutcome per page in page order, and the
    merged record fields for the store. ``fields["text"]`` is a single
    ``{"claims": [...]}`` object, so the scorer sees one answer per cell.

    `texts` is indexed by absolute page number and must cover every page in
    `pages` when `mode` is "text" or "text+image"; otherwise ValueError. An
    AdapterError from any page propagates and no answer is returned.

    With `concurrency` > 1 the per-page calls run in a thread pool, but outcomes
    are assembled in page order, so nothing here depends on completion order.
    """
    n = len(pages)
    started = time.monotonic()
    by_page: dict[int, PageOutcome] = {}
    texts = texts or []
    if mode in ("text", "text+image"):
        highest = max((p.page_number for p in pages), default=0)
        if highest > len(texts):
            raise ValueError(
                f"input mode {mode!r} needs text for page {highest}, but only "
                f"{len(texts)} page texts were supplied."
            )

    def _text_for(page: PageImage) -> str:
        return texts[page.page_number - 1] if texts else ""

    def _record(outcome: PageOutcome) -> None:
        by_page[outcome.page_number] = outcome
        flags = []
        if outcome.truncated:
            flags.append("TRUNCATED")
        if outcome.parse_error:
            flags.append(f"PARSE: {outcome.parse_error}")
        log(
            f"      page {outcome.page_number}/{n}: {outcome.claim_count} claims, "
            f"{outcome.result.output_tokens} out tok, ${outcome.result.cost_usd:.4f}"
            + (("  [" + "; ".join(flags) + "]") if flags else "")
        )

    if concurrency > 1 and n > 1:
        # AdapterError from any page propagates and fails the whole cell, as in
        # the sequential path.
        with ThreadPoolExecutor(max_workers=min(concurrency, n)) as pool:
            futures = [
                pool.submit(_extract_one_page, adapter, p, n, mode, _text_for(p))
                for p in pages
            ]
            for future in as_completed(futures):
                _record(future.result())
    else:
        for page in pages:
            _record(_extract_one_page(adapter, page, n, mode, _text_for(page)))

    outcomes = [by_page[p.page_number] for p in pages]

    merged: list[dict] = []
    for outcome in outcomes:
        claims, _ = parse_claims(outcome.result.text)
        # A claim's own page field is the model's assertion; the merged row uses
        # the page that was actually sent.
        for claim in claims:
            row = {
                "type": claim.type,
                "label": claim.label,
                "value_raw": claim.value_raw,
                "page": outcome.page_number,
            }
            if claim.region is not None:
                row["region"] = claim.region
            if claim.confidence is not None:
                row["confidence"] = claim.confidence
            if claim.group is not None:
                # Namespaced per page: "txn-1" on page 2 and on page 7 are
                # different items.
                row["group"] = f"p{outcome.page_number}-{claim.group}"
            merged.append(row)

    fields = {
        "text": json.dumps({"claims": merged}, ensure_ascii=False),
        "resolved_model": outcomes[0].result.resolved_model if outcomes else "",
        "input_tokens": sum(o.result.input_tokens for o in outcomes),
        "output_tokens": sum(o.result.output_tokens for o in outcomes),
        "cost_usd": sum(o.result.cost_usd for o in outcomes),
        # latency_s is model time: the sum of the per-page calls, unaffected by
        # page_concurrency, and the figure that compares candidates.
        # wall_clock_s is what this machine waited, so it is a property of the
        # harness configuration rather than of the candidate.
        "latency_s": round(sum(o.result.latency_s for o in outcomes), 3),
        "wall_clock_s": round(time.monotonic() - started, 3),
        "page_concurrency": min(concurrency, n) if concurrency > 1 else 1,
        "input_mode": mode,
        "prompt_version": PROMPT_VERSIONS[mode],
        "claim_count": len(merged),
        "pages_called": len(outcomes),
        "pages_truncated": [o.page_number for o in outcomes if o.truncated],
        "pages_unparsed": [o.page_number for o in outcomes if o.parse_error],
        # Every page's verbatim request and response, kept whole.
        "page_calls": [
            {
                "page": o.page_number,
                "text": o.result.text,
                "finish_reason": o.finish_reason,
                "parse_error": o.parse_error,
                "claim_count": o.claim_count,
                "input_tokens": o.result.input_tokens,
                "output_tokens": o.result.output_tokens,
                "cost_usd": o.result.cost_usd,
                "latency_s": round(o.result.latency_s, 3),
                "request": o.result.request,
                "response": o.result.response,
            }
            for o in outcomes
        ],
    }
    return outcomes, fields


def run_exam(
    config: BenchConfig,
    corpus: Corpus,
    store: RunStore,
    page_cache: Path,
    log=print,
) -> None:
    """Run every cell not already completed in `store`.

    Appends one record per cell, ``status`` "ok" or "error". Raises
    BudgetExceeded before spending anything once actual spend reaches
    `config.budget_usd`, and ValueError if the configured input mode would miss
    printed content on a document with no text layer."""
    adapters = {c.name: adapter_for(c) for c in config.candidates}

    mode = config.input_mode

    for doc in corpus.documents:
        pages = None  # rendered lazily, once per document
        texts: list[str] | None = None
        doc_hash = None
        for cand in config.candidates:
            for run_index in range(1, config.runs_per_document + 1):
                if store.is_done(doc.id, cand.name, run_index, mode):
                    continue

                # ---- budget guard: checked before spending, against actuals
                if store.spent_usd >= config.budget_usd:
                    raise BudgetExceeded(
                        f"Budget ceiling reached: spent ${store.spent_usd:.2f} of "
                        f"${config.budget_usd:.2f}. Stopping as designed. "
                        "Raise budget_usd deliberately if you choose to continue."
                    )

                if pages is None:
                    log(f"  rendering {doc.id} ({doc.file.name}) ...")
                    pages = render_pages(doc, page_cache)
                    doc_hash = file_sha256(doc.file)
                    if mode in ("text", "text+image"):
                        texts = page_texts(doc, page_cache)
                        gaps = text_gaps(doc, page_cache)
                        if gaps:
                            # Printed content with no text layer: a scan. Refuse
                            # rather than send blank pages and grade the silence.
                            raise ValueError(
                                f"Document '{doc.id}' has printed content but no "
                                f"text layer on page(s) {gaps}, so input mode "
                                f"{mode!r} would silently miss it. Run this "
                                "document in 'image' mode."
                            )
                        log(f"    text layer: {sum(len(t) for t in texts)} chars "
                            f"across {len(texts)} pages")

                label = f"{doc.id} x {cand.name} run {run_index}/{config.runs_per_document}"
                log(f"  {label} ...")
                base_record = {
                    "doc_id": doc.id,
                    "doc_sha256": doc_hash,
                    "doc_type": doc.doc_type,
                    "locale": doc.locale,
                    "currency": doc.currency,
                    "candidate": cand.name,
                    "configured_model": cand.model,
                    "run_index": run_index,
                    # extract_by_page supplies these on success; an error record,
                    # which has no fields to merge, falls back to them here.
                    "prompt_version": PROMPT_VERSIONS[mode],
                    "input_mode": mode,
                    "page_hashes": [p.sha256 for p in pages],
                }
                try:
                    outcomes, fields = extract_by_page(
                        adapters[cand.name], pages, log, config.page_concurrency,
                        mode, texts,
                    )
                except AdapterError as e:
                    store.append(
                        {**base_record, "status": "error", "error": str(e), "cost_usd": 0.0}
                    )
                    log(f"    ERROR (recorded): {e}")
                    continue

                store.append({**base_record, "status": "ok", **fields})
                warn = ""
                if fields["pages_truncated"]:
                    warn += f"  TRUNCATED pages {fields['pages_truncated']}"
                if fields["pages_unparsed"]:
                    warn += f"  UNPARSED pages {fields['pages_unparsed']}"
                log(
                    f"    ok: {fields['claim_count']} claims over "
                    f"{fields['pages_called']} pages, "
                    f"{fields['input_tokens']}+{fields['output_tokens']} tok, "
                    f"${fields['cost_usd']:.4f}, {fields['latency_s']:.0f}s "
                    f"(total spent ${store.spent_usd:.2f}){warn}"
                )
        # free page bytes between documents
        pages = None
