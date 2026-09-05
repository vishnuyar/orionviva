"""Backend-authored attention queue for the Review destination.

Review is deliberately narrower than Activity.  It contains only work another
backend read explicitly says is waiting for the person; editability, an empty
category, or any other shape of a movement is never promoted into attention
here.  Question order is the order supplied by ``open_questions``.
"""

from __future__ import annotations

from typing import Any

from ..questions import ACTIONABLE_QUESTION_WINDOW, open_questions
from .account_ledger import AccountLedgerIdentityError, _deduplicate
from .activity import _row


DEFAULT_LIMIT = ACTIONABLE_QUESTION_WINDOW
MAX_LIMIT = 500
_BINDING_SCALAR_REFS = ("movement", "document", "doc_id", "account")
_BINDING_LIST_REFS = ("movements", "candidates")


def review(projection: Any, locale: str, *, limit: int = DEFAULT_LIMIT,
           as_of: str = "", jurisdiction: str = "") -> dict[str, Any]:
    """Return the ordered, bounded set of authored attention items.

    A transaction destination is included only when every referenced movement
    resolves uniquely, belongs to one account, and collapses to one canonical
    account-ledger row.  Otherwise the item remains actionable through its
    exact question identity and says why transaction context was withheld.
    """
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_LIMIT:
        raise ValueError(f"review limit must be between 1 and {MAX_LIMIT}")
    queue = open_questions(
        projection, limit=limit, as_of=as_of,
        jurisdiction=jurisdiction, locale=locale)
    questions = list(queue.get("questions") or [])
    items = [_item(projection, question, locale) for question in questions]
    if any(not item["id"] for item in items) or len({item["id"] for item in items}) != len(items):
        raise ValueError("review item identity is missing or ambiguous")
    total = int(queue.get("total", len(items)))
    if total < len(items):
        raise ValueError("review total is smaller than its supplied items")
    group = {
        "id": "questions",
        "label": "Questions",
        "count": len(items),
        "items": items,
    }
    return {
        "state": "ready",
        "contract": "ReviewSummary.v1",
        "title": "Review",
        "summary": ("Nothing is waiting for your answer."
                    if total == 0 else
                    f"{total} item{' is' if total == 1 else 's are'} waiting for your answer."),
        "actionable_count": total,
        "shown_count": len(items),
        "remaining_count": total - len(items),
        # Questions are the only attention kind this read currently authors.
        # Other kinds join this list only when their own backend projection can
        # supply stable identities, reasons, targets, and actions.
        "types": ([{"id": "questions", "label": "Questions",
                    "count": len(items)}] if items else []),
        "groups": [group] if items else [],
    }


def _item(projection: Any, question: dict[str, Any], locale: str) -> dict[str, Any]:
    question_id = str(question.get("id") or "")
    target, context = _transaction_target(projection, question, locale)
    if target is None:
        target = {
            "kind": "conversation",
            "question_id": question_id,
            "disclosure": "No exact account-ledger transaction could be proven from this question’s references. The question will open in its conversation instead.",
        }
        context = {"date": "", "amount": "", "account": "", "merchant": ""}
        primary_action = "open_question"
        action_label = "Answer question"
    else:
        primary_action = "open_transaction"
        action_label = "Review transaction"
    item = {
        "id": f"question:{question_id}",
        "type": "question",
        "type_label": "Question",
        "marker": "?",
        "marker_label": "Viva needs an answer",
        "label": str(question.get("text") or ""),
        "reason": str(question.get("why") or ""),
        "status": "open",
        "context": context,
        "target": target,
        "primary_action": primary_action,
        "action_label": action_label,
        "allowed_actions": [primary_action],
    }
    item["binding"] = _binding(question, item)
    return item


def question_review_binding(projection: Any, question: dict[str, Any],
                            locale: str) -> dict[str, Any]:
    """Return the exact Review semantics paired with one conversation row."""
    return dict(_item(projection, question, locale)["binding"])


def _binding(question: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
    refs = question.get("refs") if isinstance(question.get("refs"), dict) else {}
    normalized_refs: dict[str, Any] = {}
    for key in _BINDING_SCALAR_REFS:
        value = refs.get(key)
        normalized_refs[key] = value if isinstance(value, str) else ""
    for key in _BINDING_LIST_REFS:
        value = refs.get(key)
        normalized_refs[key] = (list(value) if isinstance(value, list)
                                and all(isinstance(entry, str) for entry in value)
                                else [])
    return {
        "item_id": item["id"],
        "question_id": item["target"]["question_id"],
        "question_kind": str(question.get("kind") or ""),
        "label": item["label"],
        "reason": item["reason"],
        "refs": normalized_refs,
        "target": dict(item["target"]),
        "status": item["status"],
        "primary_action": item["primary_action"],
        "allowed_actions": list(item["allowed_actions"]),
    }


def _transaction_target(projection: Any, question: dict[str, Any],
                        locale: str) -> tuple[dict[str, Any] | None, dict[str, str]]:
    refs = question.get("refs")
    if not isinstance(refs, dict):
        return None, {}
    source = refs.get("movement")
    if source not in (None, "") and (not isinstance(source, str) or not source):
        return None, {}
    related = refs.get("movements", [])
    if related is None:
        related = []
    if (not isinstance(related, list)
            or any(not isinstance(value, str) or not value for value in related)
            or len(set(related)) != len(related)):
        return None, {}
    # ``movement`` and ``movements`` are two authored views of the same
    # relationship, so the singular identity may legitimately also occur in
    # the plural list. Repetition *inside* either list is malformed and is
    # refused above rather than silently normalised.
    identities = list(related)
    if isinstance(source, str) and source and source not in identities:
        identities.insert(0, source)
    if not identities:
        return None, {}

    all_movements = list(projection.movements())
    by_id: dict[str, list[Any]] = {}
    for movement in all_movements:
        by_id.setdefault(str(movement.key), []).append(movement)
    if any(len(by_id.get(identity, [])) != 1 for identity in identities):
        return None, {}
    selected = [by_id[identity][0] for identity in identities]
    accounts = {str(movement.account) for movement in selected}
    if len(accounts) != 1:
        return None, {}
    account_id = next(iter(accounts))
    declared_account = refs.get("account")
    if declared_account not in (None, "", account_id):
        return None, {}

    # Candidate references are not destinations, but they are part of the
    # question's claimed relationship.  A malformed or ambiguous candidate
    # makes that relationship unsafe to present as exact transaction context.
    candidates = refs.get("candidates", [])
    if candidates is None:
        candidates = []
    if (not isinstance(candidates, list)
            or any(not isinstance(identity, str) or not identity for identity in candidates)
            or len(set(candidates)) != len(candidates)):
        return None, {}
    if any(len(by_id.get(identity, [])) != 1 for identity in candidates):
        return None, {}

    infos = [info for info in projection.account_infos()
             if str(info.account) == account_id]
    if len(infos) != 1:
        return None, {}
    statements = projection.statements(account_id)
    records = list(statements.records) if statements else []
    try:
        entries, _ = _deduplicate(
            [movement for movement in all_movements
             if str(movement.account) == account_id], records)
    except AccountLedgerIdentityError:
        return None, {}
    containing = [entry for entry in entries if identities and all(
        identity in {str(member.key) for member in entry["members"]}
        for identity in identities)]
    if len(containing) != 1:
        return None, {}
    entry = containing[0]
    member_ids = sorted(str(member.key) for member in entry["members"])
    canonical = str(entry["movement"].key)
    requested = str(source or identities[0])
    if requested not in member_ids or canonical not in member_ids:
        return None, {}

    # Candidates are a claim about this question's movement relationship, not
    # free-floating context. A candidate outside the one proven canonical row
    # would make opening that row imply a relationship the projection did not
    # establish.
    if any(identity not in member_ids for identity in candidates):
        return None, {}

    document_alias = refs.get("document")
    document_id_alias = refs.get("doc_id")
    if (document_alias not in (None, "")
            and (not isinstance(document_alias, str) or not document_alias)):
        return None, {}
    if (document_id_alias not in (None, "")
            and (not isinstance(document_id_alias, str) or not document_id_alias)):
        return None, {}
    if (document_alias and document_id_alias and document_alias != document_id_alias):
        return None, {}
    document = document_alias or document_id_alias
    if document:
        member_documents = {
            str(getattr(member.provenance, "doc_id", "") or "")
            for member in entry["members"]}
        if document not in member_documents:
            return None, {}

    row = _row(projection, entry["movement"], locale, {
        "categories": {"items": [], "complete": False, "limit": 0},
        "subcategories": {"items": [], "complete": False, "limit": 0},
        "tags": {"items": [], "complete": False, "limit": 0,
                 "max_selected": 0, "max_label_length": 0},
    })
    return ({
        "kind": "transaction",
        "question_id": str(question.get("id") or ""),
        "account_id": account_id,
        "movement_id": requested,
        "canonical_movement_id": canonical,
        "member_movement_ids": member_ids,
    }, {
        "date": str(row.get("date") or ""),
        "amount": str(row.get("display") or ""),
        "account": str(row.get("account_name") or ""),
        "merchant": str(row.get("description") or ""),
    })
