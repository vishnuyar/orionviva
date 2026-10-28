"""The ingest read-model: what is captured, what posted, what held."""

from __future__ import annotations

from .core import ProjectionCore


def is_resolved(core: ProjectionCore, doc_id: str) -> bool:
    """A document has reached a terminal state — posted, or held for review."""
    return (doc_id in core._posted or doc_id in core._held
            or any(state.doc_id == doc_id for state in core._instrument_component_states.values()))


def posted_period(core: ProjectionCore, account: str,
                  period_end: str) -> tuple | None:
    """The document already posted for this account and period end, as
    ``(doc_id, closing_amount)`` — or None if the period is unclaimed."""
    return core._periods.get((account, period_end))


def is_pay_decomposed(core: ProjectionCore, description: str, pay_date: str,
                      gross: str) -> bool:
    """Whether this pay has already been broken out of its deposit."""
    return (description, pay_date, gross) in core._decomposed


def posted_doc_ids(core: ProjectionCore) -> set[str]:
    return set(core._posted)


def captured_docs(core: ProjectionCore) -> dict[str, str]:
    return {doc: effective_type(kind, core._classified_types.get(doc, {}).values())
            for doc, kind in core._captured.items()}


def captured_filenames(core: ProjectionCore) -> dict[str, str]:
    """What each captured document was called where it came from.

    Empty for a document captured without a name — the capture records what it
    was given, and a name nobody supplied is not invented here."""
    return dict(core._captured_names)


def read_attempted_docs(core: ProjectionCore) -> set[str]:
    """Every document some model was asked about, whatever it answered.

    Membership says a read happened, not that it worked: a reply that never
    parsed is still a reading, and it is what separates a document that was
    read and yielded nothing from one nothing has ever looked at."""
    return set(core._read_attempted)


def read_parsed_docs(core: ProjectionCore) -> set[str]:
    """Every document whose reading declared itself usable.

    Read off the reading's own ``parse_ok`` on the pass that produces facts,
    which is what the vault recorded about that reading. Whether the ledger
    then posted it, held it or had nowhere to put it is a separate fact and is
    asked for separately: a document can reach a terminal state without any
    reading behind it, and one can be read perfectly and reach none."""
    return set(core._read_parsed)


def open_holds(core: ProjectionCore) -> list[dict]:
    """StatementHeld bodies for documents not since posted."""
    return [b for did, b in core._held.items() if did not in core._posted]


def open_activity_holds(core: ProjectionCore) -> list[dict]:
    """Brokerage activity streams still quarantined after snapshot posting."""
    return list(core._activity_held.values())


def gap_holds(core: ProjectionCore) -> list[dict]:
    return [b for b in open_holds(core) if b.get("reason") == "gap"]


def document_contributions(core: ProjectionCore) -> dict[str, dict]:
    """What each posted document actually put on the books.

    One entry per document that attested a closing balance: the account it
    spoke about, the figure that was accepted for it, the day that figure is
    good for, and the currency the account is held in. It is what the ledger
    recorded and nothing else — no wording, no grade, no derived total.

    The accepted figure is the corrected one where a person ruled on a misread,
    which is the figure that is actually on the books rather than the one the
    document printed. A document that posted movements and attested no closing
    has no entry: this says what a document was worth to the picture, and a
    document with nothing here contributed nothing a figure rests on.
    """
    accounts = {}
    for account, state in core._acct.items():
        for doc_id in state.doc_ids:
            accounts.setdefault(doc_id, (account, state.currency))
    found: dict[str, dict] = {}
    for doc_id, (amount, as_of) in core._doc_closing.items():
        account, currency = accounts.get(doc_id, ("", ""))
        found[doc_id] = {"account": account, "currency": currency,
                         "amount": str(amount), "as_of": as_of}
    return found


def parse_classification(text):
    """Parse the reader's type and confidence claim without interpreting figures."""
    import json
    import re
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            value = json.loads(match.group(0))
            return (str(value.get("doc_type", "unknown")).lower(),
                    float(value.get("doc_type_confidence", 0.0) or 0.0))
        except (json.JSONDecodeError, TypeError, ValueError):
            pass
    return "unknown", 0.0


def canonical_classification(kind, confidence):
    """Apply the live reader's instrument aliases and confidence rejection."""
    import math
    from ...ingest.registry import profile_for, INSTRUMENT_IDENTITY
    profile = profile_for(kind)
    if profile is not None and profile.identity == INSTRUMENT_IDENTITY:
        if not math.isfinite(confidence) or not 0 <= confidence <= 1:
            return profile.doc_type, 0.0, 'invalid instrument classification confidence'
        return profile.doc_type, confidence, None
    return kind, confidence, None


def classified_claim(event, responses):
    """An ordinary saved classify claim, validated against its preceding receipts."""
    from ...extraction_responses import validate_links, _SCOPED_FIELDS
    body = event.body
    if (event.event_type != 'ReadRecorded' or body.get('phase') != 'classify'
            or body.get('parse_ok') is not True or body.get('parse_error') is not None
            or 'acquisition' in body or not body.get('doc_id')):
        return None
    scoped = _SCOPED_FIELDS.intersection(body)
    if scoped and body.get('transport_complete') is not True:
        return None
    try:
        validate_links(body, responses)
        kind, confidence = parse_classification(body.get('response_text', ''))
        kind, confidence, error = canonical_classification(kind, confidence)
    except (ValueError, TypeError, AttributeError, OverflowError):
        return None
    if error or not kind or kind == 'unknown':
        return None
    return (kind, confidence, tuple(body.get('transport_receipt_ids', ())))


def effective_type(raw_type, claims):
    """Known captures keep their claim; contradictory derived claims stay unknown."""
    if raw_type and raw_type != 'unknown':
        return raw_type
    kinds = {claim[0] for claim in claims}
    return next(iter(kinds)) if len(kinds) == 1 else raw_type
