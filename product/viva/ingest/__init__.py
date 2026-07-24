"""Ingest: capture every file raw, read it, verify it, post or park it.

The deterministic core (raw capture, statement parsing, the reconciliation gate,
posting) is fully testable offline. The live model read lives in ``reader`` and
is imported lazily by callers that need it, so the tested core carries no heavy
or network dependencies.
"""

from .diagnose import (DIAGNOSIS_VERSION, FORCED, SUGGESTED, UNLOCALIZED,
                       ReconciliationFinding, diagnose)
from .pipeline import (CONFLICT, DUPLICATE, GAP, IDENTITY, PARKED, POSTED,
                       IngestResult, ReadResult, account_id_for,
                       capture_and_ingest, heal_gaps, post_statement)
from .raw_store import RawStore
from .registry import (BALANCE_IDENTITY, DEPOSITORY, LIABILITY, DocProfile,
                       account_kind_for, can_project, profile_for, register)
from .review import (HeldItem, apply_human_correction, apply_identity_ruling,
                     held_items)
from .statement import StatementFacts, TxnFact, from_model_json

__all__ = [
    "RawStore",
    "StatementFacts", "TxnFact", "from_model_json",
    "ReadResult", "IngestResult", "capture_and_ingest", "post_statement",
    "account_id_for", "heal_gaps",
    "HeldItem", "held_items", "apply_human_correction", "apply_identity_ruling",
    "diagnose", "ReconciliationFinding", "DIAGNOSIS_VERSION",
    "FORCED", "SUGGESTED", "UNLOCALIZED",
    "DocProfile", "profile_for", "register", "can_project", "account_kind_for",
    "BALANCE_IDENTITY", "DEPOSITORY", "LIABILITY",
    "POSTED", "PARKED", "DUPLICATE", "CONFLICT", "GAP", "IDENTITY",
]
