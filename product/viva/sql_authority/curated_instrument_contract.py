"""Closed retained derivation contract for authenticated curated instruments."""
PROFILE = "curated_instrument_derivation_v1"
INTERPRETATION_KIND = "curated_instrument_retained_v1"
FAMILIES = ("term_deposit_statement", "mortgage_statement", "refinance_settlement", "property_tax_receipt")
LEXICAL_SCOPE = "declared_validated_cells_only"
CONTEXT_FIELDS = ("version", "profile", "doc_type", "parser_locale", "parser_currency",
                  "instrument_source_contract", "page_count", "validated_cell_count", "lexical_scope",
                  "disposition", "reason", "financial_admission")


def descriptor():
    return {"version": 1, "profile": PROFILE, "interpretation_kind": INTERPRETATION_KIND,
            "families": list(FAMILIES), "facts_wire_profile": "instrument_read_wrapper_v1",
            "returned_facts": None, "parser_inputs": "authenticated_curated_admission",
            "page_bounds": "actual_original_pdf", "lexical_scope": LEXICAL_SCOPE,
            "context_fields": list(CONTEXT_FIELDS), "financial_admission": False}
