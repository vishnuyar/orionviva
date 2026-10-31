"""Pure prerequisites for admitting a manual transfer relationship."""

TRANSFER_CANDIDATE_LIMIT = 20
TRANSFER_EVIDENCE_RULES = frozenset({
    "account_ref_slot",
    "account_ref_slot+printed_date",
    "named_account",
    "named_account+printed_date",
})


def recognized_link_origin(link):
    """Recognize only provenance combinations emitted by transfer writers."""
    decided_by = str(link.get("decided_by") or "").strip()
    if link.get("by") == "human" and link.get("grade") == "verified" and not decided_by:
        return "human"
    if (link.get("by") == "auto" and link.get("grade") == "corroborated"
            and decided_by in TRANSFER_EVIDENCE_RULES):
        return "auto"
    return ""


def account_reference_available(account, name, number):
    """Whether the existing account label fallbacks supply a reference."""
    return bool(str(name or "").strip()
                or str(account or "").rpartition(":")[2].strip()
                or str(number or "").strip())


def counterpart_reference_complete(counterpart, account_available):
    """Required counterpart identity facts, before presentation checks."""
    return bool(account_available and all(
        str(value or "").strip() for value in (
            counterpart.key, counterpart.date, counterpart.description,
            counterpart.account, counterpart.currency)))


def relationship_complete(source, counterpart, source_account_available,
                          counterpart_account_available):
    """Required relationship facts without imposing counterpart-only fields."""
    return bool(source_account_available and counterpart_account_available
                and str(source.date) and str(counterpart.date)
                and str(source.description or "").strip()
                and str(counterpart.description or "").strip())
