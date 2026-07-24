"""Merchant normalization — re-exported from the ledger layer.

The normalizer lives in ``viva.ledger.merchants`` because the projection derives
a transaction's category through it (ledger must not import ingest). This module
keeps the ingest-side import path stable.
"""

from ..ledger.merchants import (NORMALIZER_VERSION, is_shareable,
                                normalize_merchant)

__all__ = ["normalize_merchant", "is_shareable", "NORMALIZER_VERSION"]
