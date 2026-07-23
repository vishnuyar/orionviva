"""Ingest: capture every file raw, read it, verify it, post or park it.

The deterministic core (raw capture, statement parsing, the reconciliation gate,
posting) is fully testable offline. The live model read lives in ``reader`` and
is imported lazily by callers that need it, so the tested core carries no heavy
or network dependencies.
"""

from .diagnose import (DIAGNOSIS_VERSION, FORCED, SUGGESTED, UNLOCALIZED,
                       ReconciliationFinding, diagnose)
from .pipeline import (CHECKING_DOC_TYPES, CONFLICT, DUPLICATE, GAP, PARKED,
                       POSTED, IngestResult, ReadResult, account_id_for,
                       capture_and_ingest, heal_gaps, post_statement)
from .raw_store import RawStore
from .review import HeldItem, apply_human_correction, held_items
from .statement import StatementFacts, TxnFact, from_model_json

__all__ = [
    "RawStore",
    "StatementFacts", "TxnFact", "from_model_json",
    "ReadResult", "IngestResult", "capture_and_ingest", "post_statement",
    "account_id_for", "heal_gaps",
    "HeldItem", "held_items", "apply_human_correction",
    "diagnose", "ReconciliationFinding", "DIAGNOSIS_VERSION",
    "FORCED", "SUGGESTED", "UNLOCALIZED",
    "CHECKING_DOC_TYPES",
    "POSTED", "PARKED", "DUPLICATE", "CONFLICT", "GAP",
]
