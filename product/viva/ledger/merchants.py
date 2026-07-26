"""Merchant normalization — re-exported from the ``merchantcore`` package.

The normalizer, the privacy lint, and the merchant record now live in
``merchantcore`` (a peer to vivacore; see docs/merchantcore-package.md), because
merchant knowledge is impersonal and reusable. The projection derives a
transaction's category through ``normalize_merchant``, so this thin re-export
keeps the ledger-layer import path stable (and ledger must not import ingest).
"""

from merchantcore import NORMALIZER_VERSION, is_shareable, normalize_merchant

__all__ = ["normalize_merchant", "is_shareable",
           "NORMALIZER_VERSION"]
