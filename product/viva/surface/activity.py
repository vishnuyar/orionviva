"""What moved, composed from one projection.

Every row here came off a document somebody added. Two things are decided by
this module and by nothing downstream of it.

**Which way the money went is read from the account's kind.** A posted amount is
signed by its effect on the balance the document prints, so on a card a purchase
posts positive; the one function that knows the kind decides, and it raises
rather than guessing when it is handed none. This is what the direction site
closing bought, and it is why this read can speak direction at all.

**A movement that is not plain spending says what it is.** Money moved between
a person's own pockets is not spending; a movement held out of spending on weak
evidence is neither counted nor quietly kept; a movement whose components are
known and whose proportions are not gets its own line. Each is a reviewed
sentence rather than a missing row, because a row that disappears is a figure
that changed with nothing said about why.

Nothing here is a total. Money in different currencies is not added, and this
read hands back rows rather than a sum — the picture is where a figure lives,
and a second place computing one would be a second answer.

A pure function of a projection. It opens nothing, reads no clock and knows
nothing about how the payload travels.
"""

from __future__ import annotations

from typing import Any

from .. import render
from ..ingest.categorize import (UNCATEGORIZED, normalize_category,
                                 open_loan_receivables_at)
from ..ingest.transfers import is_transfer_candidate
from ..listen import category_vocabulary
from ..ledger.projection.movements import (BY_CATEGORY, MIXED, SETTLEMENT,
                                           SPENDING, TRANSFER, is_expense)
from ..ledger.streams import money_effect
from ..persona import moment
from .models import PanelState

# How many rows one read hands back. A person meets what moved most recently;
# everything else is behind a question this read does not take yet, and the
# count of what was left out travels so nothing is hidden — only not pushed.
DEFAULT_LIMIT = 50
VOCABULARY_LIMIT = 40
MAX_SELECTED_TAGS = 40
MAX_TAG_LABEL_LENGTH = 80
TRANSFER_CANDIDATE_LIMIT = 20
TRANSFER_EVIDENCE_RULES = frozenset({
    "account_ref_slot",
    "account_ref_slot+printed_date",
    "named_account",
    "named_account+printed_date",
})

# What a row is, beyond spending, against the sentence that says so. A nature
# outside this table is plain spending and carries no sentence: the row is what
# it looks like, and a line saying so would be noise on every ordinary row.
NATURES: dict[str, str] = {
    TRANSFER: "activity_transfer",
    SETTLEMENT: "activity_transfer",
    MIXED: "activity_unsettled",
}


def activity(projection, locale: str = "", limit: int = DEFAULT_LIMIT,
             focus: str = "") -> dict[str, Any]:
    """Everything that moved, newest first, ready to render.

    ``limit`` bounds what is handed over. What was left out is reported with
    its count rather than dropped: a list that silently stops is a list a
    person reads as the whole of what happened."""
    movements = list(projection.movements())
    vocabularies = _vocabularies(projection)
    if not movements:
        return {
            "state": PanelState.ABSENT.value,
            # Not the same as nothing having moved, and said so.
            "sentence": moment("activity_empty"),
            "items": [],
            "beyond": {"count": 0},
            "vocabularies": vocabularies,
        }
    pending = {item.get("a") for item in
               getattr(projection, "transfer_suggestions", lambda: [])()}
    # Order unresolved reviews first, then ordinary history newest-first.
    ordered = sorted(movements,
                     key=lambda m: (m.key in pending, str(m.date), m.key),
                     reverse=True)
    shown = ordered[:limit]
    if focus and all(movement.key != focus for movement in shown):
        focused = next((movement for movement in ordered
                        if movement.key == focus), None)
        if focused is not None:
            shown = ([*shown[:-1], focused] if shown else [focused])
    shown_keys = {movement.key for movement in shown}
    rest = [movement for movement in ordered if movement.key not in shown_keys]
    return {
        "state": PanelState.READY.value,
        "sentence": moment("activity_scope"),
        "items": [_row(projection, movement, locale, vocabularies)
                  for movement in shown],
        # What ranking pushed below the fold, reported with its size. No amount
        # travels with it: the rows beyond are in whatever currencies they are
        # in, and one number over them would be a total of unlike things.
        "beyond": {"count": len(rest)},
        "vocabularies": vocabularies,
    }


def _row(projection, movement, locale: str,
         vocabularies: dict[str, Any]) -> dict[str, Any]:
    """One movement, as a person meets it.

    The direction is derived here from the account's kind, through the one
    function that decides it — never from the posted sign, which reads a card
    purchase as money arriving."""
    effect = money_effect(movement.kind, movement.amount)
    current = _current_category(projection, movement)
    tags = list(getattr(projection, "tags_of", lambda _m: [])(movement))
    inherited = list(getattr(projection, "inherited_tags_of", lambda _m: [])(movement))
    actions: list[str] = []
    if (vocabularies["categories"]["complete"]
            and vocabularies["categories"]["items"]):
        actions.append("assign_category")
    repayment_choices = _loan_repayment_choices(projection, movement, effect)
    # Linked own-account transfers do not offer an economic-treatment action.
    # Offer inbound repayment only for receivables that can accept the amount.
    if not movement.linked and (effect < 0 or repayment_choices):
        actions.append("assign_meaning")
    if vocabularies["tags"]["complete"] and not inherited:
        actions.append("replace_tags")
    transfer, transfer_actions = _transfer_state(projection, movement, locale)
    actions.extend(transfer_actions)
    return {
        "id": movement.key,
        "date": movement.date,
        "description": movement.description,
        "account": movement.account,
        # `direction` is what the money did, and it is the kind's answer. The
        # amount travels unsigned beside it, because a sign and a word saying
        # the same thing are two chances to disagree.
        "direction": "in" if effect > 0 else "out",
        "exact_value": str(abs(effect)),
        "currency": movement.currency,
        "display": str(render.money(abs(effect), movement.currency,
                                    locale=locale)),
        "nature": movement.nature,
        # Surface the recorded treatment and loan name directly.
        "treatment": _treatment(movement, effect),
        "loan_repayment_choices": repayment_choices,
        # What this is, where it is not plain spending. Empty on an ordinary
        # row, because a line saying "this is spending" on every spending row
        # is a line that stops being read.
        "sentence": _sentence(movement),
        # Whether this movement is one a link, a ruling or a document settled,
        # or one resting on weaker evidence. It is the reason the projection
        # recorded, carried rather than re-derived.
        "decided_by": movement.nature_reason,
        "provisional": bool(movement.provisional),
        "linked": bool(movement.linked),
        "category": current,
        "tags": [_choice(tag) for tag in tags],
        # The closed relationship state is the only authority for transfer
        # controls. `linked` above remains descriptive compatibility data; a
        # caller must never turn that boolean into a write affordance.
        "transfer": transfer,
        "actions": actions,
    }


def _loan_repayment_choices(projection, movement, effect) -> list[str]:
    """Loan receivables this inbound amount could repay on its own date."""
    if effect <= 0:
        return []
    choices = [
        str(render.account({"path": account}))
        for account, outstanding in open_loan_receivables_at(projection, movement)
        if outstanding >= effect
    ]
    return sorted(set(choices))


def _treatment(movement, effect) -> dict[str, str]:
    account = movement.ruling_account or ""
    if account.startswith("Assets:Loans:"):
        return {
            "kind": "loan_repayment" if effect > 0 else "loan",
            "name": str(render.account({"path": account})),
        }
    if movement.nature == SPENDING and is_expense(movement):
        return {"kind": "spending", "name": ""}
    if movement.nature == SETTLEMENT:
        return {"kind": "settlement", "name": ""}
    if movement.nature == MIXED:
        return {"kind": "mixed", "name": ""}
    return {"kind": "not_spending", "name": ""}


def _transfer_state(projection, movement, locale: str
                    ) -> tuple[dict[str, Any], list[str]]:
    """The live transfer relationship and only the actions it can support.

    Suggestions are bounded without being silently truncated.  An incomplete
    set may still explain what the vault knows, but neither confirming one
    candidate nor rejecting the whole suggestion is safe until every current
    candidate is present and coherent.
    """
    by_key = {item.key: item for item in projection.movements()}
    linked_keys = set(getattr(projection, "linked_keys", lambda: set())())
    suggestions = list(getattr(
        projection, "transfer_suggestions", lambda: [])())
    suggestion = next((item for item in suggestions
                       if item.get("a") == movement.key), None)
    if suggestion is not None:
        raw = suggestion.get("candidates")
        raw_candidates = raw if isinstance(raw, list) else []
        references: list[dict[str, Any]] = []
        seen: set[str] = set()
        coherent = (isinstance(raw, list) and bool(raw_candidates)
                    and len(raw_candidates) <= TRANSFER_CANDIDATE_LIMIT)
        for candidate_id in raw_candidates[:TRANSFER_CANDIDATE_LIMIT]:
            if (not isinstance(candidate_id, str) or not candidate_id.strip()
                    or candidate_id == movement.key or candidate_id in seen
                    or candidate_id in linked_keys):
                coherent = False
                continue
            seen.add(candidate_id)
            candidate = by_key.get(candidate_id)
            if candidate is not None and not is_transfer_candidate(
                    movement, candidate):
                coherent = False
                continue
            reference = (_transfer_reference(
                projection, movement, candidate, locale)
                if candidate is not None else None)
            if reference is None:
                coherent = False
                continue
            references.append(reference)
        complete = (coherent and len(references) == len(raw_candidates))
        explanation_key = ("activity_transfer_suggested"
                           if complete
                           else "activity_transfer_suggestion_incomplete")
        state = {
            "state": "suggested",
            "explanation": moment(explanation_key, count=len(references)),
            "candidates": references,
            "complete": complete,
            "limit": TRANSFER_CANDIDATE_LIMIT,
        }
        return (state, ["confirm_transfer", "reject_transfer"]
                if complete else [])

    links = list(getattr(projection, "transfer_links", lambda: [])())
    matching_links = [item for item in links
                      if movement.key in {item.get("a"), item.get("b")}]
    link = matching_links[0] if len(matching_links) == 1 else None
    if link is not None:
        counterpart_id = (link.get("b") if link.get("a") == movement.key
                          else link.get("a"))
        counterpart = (by_key.get(counterpart_id)
                       if isinstance(counterpart_id, str) else None)
        counterpart_links = [item for item in links
                             if counterpart_id in {item.get("a"), item.get("b")}]
        explanation_key = _link_explanation(link)
        coherent_pair = (isinstance(counterpart_id, str)
                         and bool(counterpart_id.strip())
                         and counterpart_id != movement.key
                         and counterpart is not None
                         and len(counterpart_links) == 1
                         and bool(explanation_key)
                         and (is_transfer_candidate(movement, counterpart)
                              or is_transfer_candidate(counterpart, movement)))
        reference = (_transfer_reference(
            projection, movement, counterpart, locale, relationship=False)
            if coherent_pair else None)
        relationship = (_relationship(projection, movement, counterpart, locale)
                        if coherent_pair else "")
        if reference is not None and relationship:
            return ({
                "state": "linked",
                "explanation": moment(explanation_key),
                "counterpart": reference,
                "relationship": relationship,
            }, ["unlink_transfer"])

    return {"state": "none"}, []


def _link_explanation(link: dict[str, Any]) -> str:
    """Reviewed copy only for provenance combinations a real writer emits."""
    by = link.get("by")
    grade = link.get("grade")
    decided_by = str(link.get("decided_by") or "").strip()
    if by == "human" and grade == "verified" and not decided_by:
        return "activity_transfer_linked_human"
    if (by == "auto" and grade == "corroborated"
            and decided_by in TRANSFER_EVIDENCE_RULES):
        return "activity_transfer_linked_evidence"
    return ""


def _transfer_reference(projection, source, counterpart, locale: str,
                        *, relationship: bool = True) -> dict[str, Any] | None:
    """One fully reviewed counterpart reference, or no unsafe partial one."""
    effect = money_effect(counterpart.kind, counterpart.amount)
    values: dict[str, Any] = {
        "id": str(counterpart.key or "").strip(),
        "date": str(counterpart.date or "").strip(),
        "description": str(counterpart.description or "").strip(),
        "account": _account_display(projection, counterpart.account),
        "direction": "in" if effect > 0 else "out",
        "exact_value": str(abs(effect)),
        "currency": str(counterpart.currency or "").strip(),
        "display": str(render.money(abs(effect), counterpart.currency,
                                    locale=locale)),
    }
    if relationship:
        values["relationship"] = _relationship(
            projection, source, counterpart, locale)
    if any(not str(value).strip() for value in values.values()):
        return None
    return values


def _account_display(projection, account: str) -> str:
    try:
        info = projection.account_info(account)
    except Exception:  # the relationship is withheld if its account is unreadable
        return ""
    entity = {"account": info.account, "name": info.name,
              "number_masked": info.number}
    return str(render.account(entity))


def _relationship(projection, source, counterpart, locale: str) -> str:
    source_effect = money_effect(source.kind, source.amount)
    counterpart_effect = money_effect(counterpart.kind, counterpart.amount)
    values = {
        "source_date": str(render.date(source.date)),
        "source_description": str(source.description or "").strip(),
        "source_account": _account_display(projection, source.account),
        "source_amount": str(render.money(abs(source_effect), source.currency,
                                          locale=locale)),
        "counterpart_date": str(render.date(counterpart.date)),
        "counterpart_description": str(counterpart.description or "").strip(),
        "counterpart_account": _account_display(projection, counterpart.account),
        "counterpart_amount": str(render.money(abs(counterpart_effect),
                                               counterpart.currency,
                                               locale=locale)),
    }
    if any(not value for value in values.values()):
        return ""
    return moment("activity_transfer_relationship", **values)


def _current_category(projection, movement) -> dict[str, Any]:
    found = getattr(projection, "derived_category", lambda _m: None)(movement)
    raw = str(found.get("category", "") or "").strip() if found else ""
    identity = normalize_category(raw) if raw else ""
    return {"id": identity or None,
            "label": str(render.category(identity or UNCATEGORIZED))}


def _category_choice(identity: str) -> dict[str, str]:
    held = str(identity or "").strip()
    return {"id": held, "label": str(render.category(held))}


def _choice(identity: str) -> dict[str, str]:
    held = str(identity or "").strip()
    return {"id": held, "label": str(render.label(held))}


def _vocabularies(projection) -> dict[str, Any]:
    category_sources = (list(category_vocabulary(projection))
                        if hasattr(projection, "merchant_categories") else [])
    category_sources.extend(
        getattr(projection, "known_categories", lambda: [])())
    categories = sorted({normalize_category(value)
                         for value in category_sources
                         if str(value or "").strip()})
    tags = sorted({str(value or "").strip().lower()
                   for value in getattr(projection, "known_tags", lambda: [])()
                   if str(value or "").strip()})
    tags_within_bounds = all(len(value) <= MAX_TAG_LABEL_LENGTH for value in tags)
    return {
        "categories": {
            "items": [_category_choice(value)
                      for value in categories[:VOCABULARY_LIMIT]],
            "complete": len(categories) <= VOCABULARY_LIMIT,
            "limit": VOCABULARY_LIMIT,
        },
        "tags": {
            "items": [_choice(value) for value in tags[:VOCABULARY_LIMIT]],
            "complete": (len(tags) <= VOCABULARY_LIMIT
                         and tags_within_bounds),
            "limit": VOCABULARY_LIMIT,
            "max_selected": MAX_SELECTED_TAGS,
            "max_label_length": MAX_TAG_LABEL_LENGTH,
        },
    }


def _sentence(movement) -> str:
    """The reviewed line for what this row is, or nothing.

    A movement held out of spending on weak evidence is said before what its
    nature nominally is: that it rests on a hint is the more important fact,
    and it is the one that explains why a total moved."""
    if movement.provisional or movement.nature_reason == BY_CATEGORY:
        if movement.nature != SPENDING:
            return moment("activity_provisional")
    key = NATURES.get(movement.nature, "")
    return moment(key) if key else ""
