"""The proctor: administers the exam identically to every candidate.

Responsibilities (and nothing more):
- iterate the (document x candidate x run) matrix, skipping completed cells;
- render pages once, call the adapter, capture everything raw;
- enforce the budget ceiling — hard stop, loud report (approved design D-b).

Failures are recorded as records too: a crashed call is evidence, not noise.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

from .capture import RunStore
from .config import BenchConfig, Corpus
from .corpus import file_sha256, render_pages
from .models import AdapterError, adapter_for
from .prompts import EXTRACTION_PROMPT, PROMPT_VERSION


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
        if not store.is_done(doc.id, cand.name, i)
    )
    return RunPlan(
        total_cells=total,
        remaining_cells=remaining,
        spent_usd=store.spent_usd,
        budget_usd=config.budget_usd,
    )


def run_exam(
    config: BenchConfig,
    corpus: Corpus,
    store: RunStore,
    page_cache: Path,
    log=print,
) -> None:
    """Run all remaining cells. Raises BudgetExceeded at the ceiling."""
    adapters = {c.name: adapter_for(c) for c in config.candidates}

    for doc in corpus.documents:
        pages = None  # rendered lazily, once per document
        doc_hash = None
        for cand in config.candidates:
            for run_index in range(1, config.runs_per_document + 1):
                if store.is_done(doc.id, cand.name, run_index):
                    continue

                # ---- budget guard: check BEFORE spending, on actuals (T6/D-b)
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
                    "prompt_version": PROMPT_VERSION,
                    "page_hashes": [p.sha256 for p in pages],
                }
                try:
                    result = adapters[cand.name].extract(pages, EXTRACTION_PROMPT)
                except AdapterError as e:
                    store.append(
                        {**base_record, "status": "error", "error": str(e), "cost_usd": 0.0}
                    )
                    log(f"    ERROR (recorded): {e}", file=sys.stderr) if log is print else log(
                        f"    ERROR (recorded): {e}"
                    )
                    continue

                store.append(
                    {
                        **base_record,
                        "status": "ok",
                        "resolved_model": result.resolved_model,
                        "text": result.text,
                        "input_tokens": result.input_tokens,
                        "output_tokens": result.output_tokens,
                        "cost_usd": result.cost_usd,
                        "latency_s": round(result.latency_s, 3),
                        "request": result.request,
                        "response": result.response,
                    }
                )
                log(
                    f"    ok: {result.input_tokens}+{result.output_tokens} tok, "
                    f"${result.cost_usd:.4f}, {result.latency_s:.1f}s "
                    f"(total spent ${store.spent_usd:.2f})"
                )
        # free page bytes between documents
        pages = None
