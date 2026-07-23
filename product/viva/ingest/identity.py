"""Back-compat re-export. Account identity now lives in the ledger layer
(``viva.ledger.identity``) because the projection resolves identity while
replaying events. Import from there in new code."""

from ..ledger.identity import (account_key, masked, names_overlap,
                               normalize_name, normalize_number, number_key, slug)

__all__ = ["account_key", "masked", "names_overlap", "normalize_name",
           "normalize_number", "number_key", "slug"]
