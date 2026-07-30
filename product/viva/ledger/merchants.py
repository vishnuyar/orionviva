"""Merchant normalization — re-exported from the ``merchantcore`` package.

The normalizer, the privacy lint and the merchant record live in
``merchantcore``, a peer to vivacore. The projection derives a transaction's
category through ``normalize_merchant``; this re-export gives the ledger layer a
stable import path for it without importing ingest.
"""

from merchantcore import NORMALIZER_VERSION, is_shareable, normalize_merchant

__all__ = ["normalize_merchant", "is_shareable",
           "NORMALIZER_VERSION"]
