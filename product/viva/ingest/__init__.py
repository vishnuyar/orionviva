"""Ingest: capture every file raw, read it, verify it, post or park it.

The deterministic core — raw capture, statement parsing, the reconciliation
gate, posting — runs offline. The live model read lives in ``reader`` and is
imported lazily by the callers that need it, so the core carries no heavy or
network dependencies.
"""

from .diagnose import (DIAGNOSIS_VERSION, FORCED, SUGGESTED, UNLOCALIZED,
                       ReconciliationFinding, diagnose)
from .brokerage import (BrokerageActivity, BrokerageFacts, PositionFact,
                        from_brokerage_json)
from .pipeline import (AWAITING, CONFLICT, DUPLICATE, GAP, IDENTITY, PARKED,
                       POSTED, IngestResult, ReadResult, account_id_for,
                       capture_and_ingest, heal_corroboration, heal_gaps,
                       heal_paystubs, post_brokerage, post_paystub,
                       post_statement, sweep)
from .categorize import (SEED_CATEGORIES, assign_category,
                         assign_merchant_category, categorize_merchants_batch,
                         rule_category_same_as,
                         rule_tag_same_as, tag_merchant, tag_movement,
                         rule_merchant_nature,
                         enrich_merchants, export_catalog, normalize_category,
                         suggest_categories)
from .merchants import NORMALIZER_VERSION, is_shareable, normalize_merchant
from .paystub import Deduction, PayStubFacts, from_paystub_json
from .raw_store import RawStore
from .registry import (BALANCE_IDENTITY, BROKERAGE_IDENTITY, DEPOSITORY,
                       INVESTMENT, LIABILITY, PAYSTUB_IDENTITY, DocProfile,
                       account_kind_for, can_project, identity_of_facts,
                       profile_for, register)
from .review import (HeldItem, apply_human_correction, apply_identity_ruling,
                     held_items, other_holds)
from .statement import StatementFacts, TxnFact, from_model_json
from .transfers import (confirm_transfer, link_transfers, reject_transfer)

__all__ = [
    "RawStore",
    "StatementFacts", "TxnFact", "from_model_json",
    "ReadResult", "IngestResult", "capture_and_ingest", "post_statement",
    "post_paystub", "account_id_for", "heal_gaps", "heal_corroboration",
    "heal_paystubs", "sweep", "AWAITING",
    "PayStubFacts", "Deduction", "from_paystub_json",
    "BrokerageFacts", "BrokerageActivity", "PositionFact", "from_brokerage_json",
    "post_brokerage",
    "assign_category", "suggest_categories", "normalize_category",
    "SEED_CATEGORIES", "assign_merchant_category", "categorize_merchants_batch",
    "rule_category_same_as", "rule_tag_same_as",
    "tag_movement", "tag_merchant",
    "rule_merchant_nature",
    "enrich_merchants", "export_catalog", "normalize_merchant", "is_shareable",
    "NORMALIZER_VERSION",
    "HeldItem", "held_items", "other_holds", "apply_human_correction",
    "apply_identity_ruling",
    "diagnose", "ReconciliationFinding", "DIAGNOSIS_VERSION",
    "FORCED", "SUGGESTED", "UNLOCALIZED",
    "DocProfile", "profile_for", "register", "can_project", "account_kind_for",
    "identity_of_facts",
    "BALANCE_IDENTITY", "PAYSTUB_IDENTITY", "BROKERAGE_IDENTITY",
    "DEPOSITORY", "LIABILITY", "INVESTMENT",
    "POSTED", "PARKED", "DUPLICATE", "CONFLICT", "GAP", "IDENTITY",
]
