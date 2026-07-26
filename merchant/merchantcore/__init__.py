"""merchantcore — the merchant knowledge base (a peer to vivacore).

Impersonal, reusable merchant knowledge: deterministic normalization, the
multi-attribute MerchantRecord, a batched model enrichment engine, and the
merchant->category commons. It holds and shares ONLY impersonal data (T9) — the
personal ledger never crosses this boundary.
"""

from .catalog import Catalog
from .enrich import ENRICHMENT_VERSION, Enricher, build_enrichment_prompt
from .normalize import NORMALIZER_VERSION, is_shareable, is_conduit, normalize_merchant
from .record import MerchantRecord
from .taxonomy import (FALLBACK_CATEGORY, PRIMARY_CATEGORIES, TAXONOMY_VERSION,
                       canonical_primary, is_primary, normalize_subcategory)

__all__ = [
    "normalize_merchant", "is_shareable", "is_conduit", "NORMALIZER_VERSION",
    "MerchantRecord",
    "Enricher", "build_enrichment_prompt", "ENRICHMENT_VERSION",
    "Catalog",
    "PRIMARY_CATEGORIES", "FALLBACK_CATEGORY", "TAXONOMY_VERSION",
    "is_primary", "canonical_primary", "normalize_subcategory",
]
