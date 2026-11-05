"""Software-owned ordinary CD capture profile, without financial authority."""
MAX_CAPTURE_BYTES = 8 * 1024 * 1024
PROFILE = "ordinary_cd_capture_v1"
RECEIPT_KIND = "cd_capture_v1"
INTERPRETATION_KIND = "cd_retained_v1"
RESULT_FIELDS = (
    "doc_type", "doc_type_confidence", "facts", "error", "raw_text", "model",
    "prompt_version", "input_mode", "cost_usd", "input_tokens", "output_tokens",
    "phases", "resolved_model", "usage_reported", "source_locale", "acquisition",
    "normalization_context",
)
PHASE_FIELDS = (
    "phase", "model", "prompt_version", "raw_text", "cost_usd", "input_tokens",
    "output_tokens", "input_mode", "parse_ok", "error", "resolved_model",
    "usage_reported", "transport_receipt_ids", "transport_complete", "extraction_id",
    "phase_attempt", "normalization_context",
)
TAG_FIELDS = (
    "version", "mode", "facts_runtime_type", "payload_runtime_type", "facts_wire_profile",
    "normalization_context_runtime_type", "context_wire_profile",
    "phase_context_runtime_types", "read_context_id",
)


def descriptor():
    """Return a detached, closed description of the installed capture contract."""
    return {
        "version": 1, "profile": PROFILE, "receipt_kind": RECEIPT_KIND,
        "interpretation_kind": INTERPRETATION_KIND,
        "facts_wire_profile": "instrument_wrapper_emitted_capture_v1",
        "context_wire_profile": "extraction_context_capture_encode_v1",
        "normalization_context_schema": 1,
        "result_fields": list(RESULT_FIELDS), "phase_fields": list(PHASE_FIELDS),
        "capture_tag_fields": list(TAG_FIELDS), "maximum_utf8_bytes": MAX_CAPTURE_BYTES,
        "financial_settlement": False,
    }
