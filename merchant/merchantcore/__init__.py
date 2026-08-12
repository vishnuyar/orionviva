"""merchantcore — the merchant knowledge base (a peer to vivacore).

Impersonal, reusable merchant knowledge: deterministic normalization, the
multi-attribute MerchantRecord, a batched model enrichment engine, descriptor
parsing and grammar induction, and the merchant->category commons. Holds only
impersonal data; the personal ledger does not cross this boundary.
"""

from . import home
from .catalog import Catalog
from .enrich import ENRICHMENT_VERSION, Enricher, build_enrichment_prompt
from .descriptor import (PARSER_VERSION, DescriptorParse, brand_candidate,
                         is_never_templatable, linted_example,
                         parse_descriptor, split_ach_heads)
from .normalize import NORMALIZER_VERSION, is_shareable, normalize_merchant
from .induce import (INDUCTION_VERSION, Inducer, build_induction_prompt,
                     machinery_version)
from .profile import (INDUCIBLE_KINDS, PACK_RULES, PARTY_SLOTS, PERSONAL_SLOTS,
                      PROFILE_FORMAT, SLOTS, Profile, ProfileError,
                      validate, validate_evidence,
                      ProfileStore, Template, is_inducible, party_slot)
from .resolve import (RESOLVER_VERSION, Resolution, channel_of,
                      corroborates_a_business, resolve_descriptor)
from .record import MerchantRecord
from .taxonomy import (FALLBACK_CATEGORY, PRIMARY_CATEGORIES, TAXONOMY_VERSION,
                       canonical_primary, is_primary, normalize_subcategory)

__all__ = [
    "normalize_merchant", "is_shareable", "NORMALIZER_VERSION",
    "parse_descriptor", "brand_candidate", "DescriptorParse", "PARSER_VERSION",
    "linted_example", "split_ach_heads", "is_never_templatable",
    "resolve_descriptor", "Resolution", "channel_of", "RESOLVER_VERSION",
    "corroborates_a_business",
    "MerchantRecord",
    "Profile", "ProfileStore", "ProfileError", "Template", "SLOTS",
    "PERSONAL_SLOTS", "PROFILE_FORMAT", "INDUCIBLE_KINDS", "is_inducible",
    "PARTY_SLOTS", "party_slot", "validate", "validate_evidence",
    "Inducer", "build_induction_prompt", "INDUCTION_VERSION",
    "machinery_version", "PACK_RULES",
    "Enricher", "build_enrichment_prompt", "ENRICHMENT_VERSION",
    "Catalog", "home",
    "PRIMARY_CATEGORIES", "FALLBACK_CATEGORY", "TAXONOMY_VERSION",
    "is_primary", "canonical_primary", "normalize_subcategory",
]
