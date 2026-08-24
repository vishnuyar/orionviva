"""Shared result contracts and outcome vocabulary for document ingestion."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from vivacore.verify.arithmetic import CheckResult

from .diagnose import ReconciliationFinding
from .statement import StatementFacts

# Ingest actions — the outcome of one ingest, reportable verbatim.
POSTED = "posted"        # reconciled and written to the ledger
PARKED = "parked"        # captured and acknowledged; no projector for it yet
DUPLICATE = "duplicate"  # already ingested (same content hash)
CONFLICT = "conflict"    # recognized, but did not reconcile — not posted
GAP = "gap"              # opening does not continue from the balance held
IDENTITY = "identity"    # reconciles, but whose account is ambiguous — ask
AWAITING = "awaiting"    # a pay stub read + verified, waiting for its net-pay deposit


@dataclass
class ModelPhase:
    """One model interaction in a read — the classify pass or the extract pass —
    captured verbatim for the claims layer. Each is persisted as its own
    ReadRecorded, so a two-phase read yields two."""
    phase: str                       # "classify" | "extract"
    model: str
    prompt_version: str
    raw_text: str
    cost_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    input_mode: str = "text+image"
    parse_ok: bool = True
    error: str | None = None
    resolved_model: str = ""
    # Token counters are meaningful only if the provider response actually
    # carried usage. Adapter defaults of zero are not measurements.
    usage_reported: bool = False


@dataclass
class ReadResult:
    """What a reader returns for one document: its classification, and — if it is
    a statement — the structured facts. A reader for a non-statement returns
    ``facts=None`` with the type it recognized (e.g. 'pay_stub').

    ``phases`` carries the per-call model records (classify, extract) that the
    pipeline persists to the claims layer. The flat ``raw_*``/``model`` fields are
    the single-call view, used by offline stubs; a two-phase read populates
    ``phases`` instead."""
    doc_type: str
    doc_type_confidence: float
    facts: StatementFacts | None = None
    error: str | None = None
    raw_text: str = ""
    model: str = ""
    prompt_version: str = ""
    input_mode: str = "text+image"
    cost_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    phases: list[ModelPhase] = field(default_factory=list)
    resolved_model: str = ""
    usage_reported: bool = False


@dataclass
class IngestResult:
    doc_id: str
    action: str
    doc_type: str
    account: str | None = None
    grade: str | None = None
    reconciliation: CheckResult | None = None
    finding: ReconciliationFinding | None = None   # why it failed / how it was fixed
    auto_corrected: bool = False
    message: str = ""



class DocumentTooLarge(ValueError):
    """A document costs more to read than any real statement should.

    Raised rather than handled by reading part of it: a statement posted over a
    subset of its own pages would reconcile against nothing and be graded like
    any other. The document is captured and parked with this as the reason."""

ReadFn = Callable[[bytes, str], ReadResult]




__all__ = ['POSTED', 'PARKED', 'DUPLICATE', 'CONFLICT', 'GAP', 'IDENTITY', 'AWAITING', 'ModelPhase', 'ReadResult', 'IngestResult', 'DocumentTooLarge', 'ReadFn']
