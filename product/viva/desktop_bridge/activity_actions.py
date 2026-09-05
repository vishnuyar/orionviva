"""Explicit movement-scoped category, tag and transfer correction actions."""

from __future__ import annotations

import time
from typing import Any

from merchantcore import seed_subcategories_by_category, subcategory_identity
from viva.ingest.categorize import (assign_category as write_category,
                                    assign_movement_meaning,
                                    normalize_category,
                                    open_loan_receivables_at, tag_movement)
from viva.ledger.events import (SCOPE_MOVEMENT, VERIFIED, category_assigned,
                                movement_tagged)
from viva.ledger.projection.categories import subcategory_group_key
from viva.ingest.transfers import (confirm_transfer as write_transfer_link,
                                   reject_transfer as write_transfer_unlink)
from viva.persona import moment
from viva.ledger.streams import money_effect
from viva.surface.activity import (MAX_BATCH_MOVEMENTS, MAX_SELECTED_TAGS,
                                   MAX_TAG_LABEL_LENGTH, activity)
from viva.surface.models import ActionOutcome

from .handlers import BridgeRequestError


class ActivityActions:
    """Validate one remembered movement against a new live projection."""

    def __init__(self, vault: Any) -> None:
        self._vault = vault

    def assign_category(self, payload: dict[str, Any]) -> dict[str, Any]:
        movement_key, category_id = _category_request(payload)
        projection, movement, row, vocabularies = self._live(movement_key)
        if movement is None:
            return _stale()
        if "assign_category" not in row["actions"]:
            return _refused("category_vocabulary_unavailable")
        advertised = {item["id"] for item in vocabularies["categories"]["items"]}
        if category_id not in advertised:
            return _refused("category_not_advertised")
        label = next(item["label"] for item in vocabularies["categories"]["items"]
                     if item["id"] == category_id)
        if row["category"]["id"] == category_id:
            return ActionOutcome(
                "completed", moment("activity_category_unchanged",
                                    category=label)
            ).as_dict()
        # This operation has authority over the category partition only.
        write_category(self._vault.ledger, movement_key, category_id,
                       by="human", nature="")
        return ActionOutcome(
            "completed", moment("activity_category_recorded",
                                category=label)
        ).as_dict()

    def assign_classification(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Assign one coherent category/subcategory pair to an exact batch.

        Selection and hierarchy are checked again inside the ledger's locked
        decision.  Events are prepared for the entire selection before the
        store sees any of them, so a stale member or an invalid pair cannot
        leave a prefix of the batch behind.
        """
        movement_keys, requested_category, requested_subcategory = \
            _classification_request(payload)
        outcome = {"reason": "", "changed": 0,
                   "subcategory": requested_subcategory}

        def decide(projection):
            movements = {movement.key: movement for movement in projection.movements()}
            selected = [movements.get(key) for key in movement_keys]
            if any(movement is None for movement in selected):
                outcome["reason"] = "movement_selection_stale"
                return ()
            canonical = _canonical_classification_pair(
                projection, requested_category, requested_subcategory)
            if canonical is None:
                outcome["reason"] = "classification_alias_ambiguous"
                return ()
            category_id, subcategory_id = canonical
            if not _valid_subcategory_pair(projection, category_id, subcategory_id):
                outcome["reason"] = "invalid_category_subcategory_pair"
                return ()
            outcome["subcategory"] = subcategory_id
            events = []
            for movement in selected:
                assert movement is not None
                current = projection.category_of(movement.key) or {}
                current_category, current_subcategory = _record_pair(
                    projection, current)
                if (current_category == category_id
                        and current_subcategory == subcategory_id
                        and current.get("grade") == VERIFIED
                        and current.get("by") == "human"):
                    continue
                events.append(category_assigned(
                    movement.key, movement.description, category_id, VERIFIED,
                    movement.date, by="human", nature="",
                    subcategory=subcategory_id))
            outcome["changed"] = len(events)
            return tuple(events)

        self._vault.ledger.append_atomically(decide)
        if outcome["reason"] == "movement_selection_stale":
            return _selection_stale()
        if outcome["reason"]:
            return _refused(outcome["reason"])
        if not outcome["changed"]:
            return ActionOutcome(
                "completed", moment("activity_category_unchanged",
                                    category=outcome["subcategory"])
            ).as_dict()
        return ActionOutcome(
            "completed", moment("activity_category_recorded",
                                category=outcome["subcategory"])
        ).as_dict()

    def assign_meaning(self, payload: dict[str, Any]) -> dict[str, Any]:
        movement_key, meaning, counterparty = _meaning_request(payload)
        projection, movement, row, _vocabularies = self._live(movement_key)
        if movement is None:
            return _stale()
        if "assign_meaning" not in row["actions"]:
            if meaning == "loan_repayment":
                effect = money_effect(movement.kind, movement.amount)
                open_loans = open_loan_receivables_at(projection, movement)
                if not open_loans:
                    return _refused("no_matching_open_loan")
                if effect > 0 and all(outstanding < effect
                                      for _account, outstanding in open_loans):
                    return _refused("repayment_exceeds_open_principal")
            return _refused("movement_meaning_unavailable")
        try:
            recorded = assign_movement_meaning(
                self._vault.ledger, movement_key, meaning, counterparty)
        except ValueError as exc:
            detail = str(exc).lower()
            reason = ("no_matching_open_loan" if "no matching loan" in detail
                      else "repayment_exceeds_open_principal"
                      if "exceed" in detail
                      else "wrong_movement_direction"
                      if "direction" in detail or "outgoing" in detail
                      else "movement_meaning_invalid")
            return _refused(reason)
        if not recorded:
            return _stale()
        treatment = {
            "spending": "spending",
            "loan": "a loan receivable",
            "loan_repayment": "a loan repayment",
        }.get(meaning, "the corrected treatment")
        return ActionOutcome(
            "completed", moment("activity_category_recorded",
                                category=treatment)
        ).as_dict()

    def replace_tags(self, payload: dict[str, Any]) -> dict[str, Any]:
        movement_key, tag_ids = _tag_request(payload)
        projection, movement, row, vocabularies = self._live(movement_key)
        if movement is None:
            return _stale()
        tag_ids = [tag.strip().lower() for tag in tag_ids]
        if len(tag_ids) > MAX_SELECTED_TAGS:
            return _refused("too_many_tags")
        if any(not tag or len(tag) > MAX_TAG_LABEL_LENGTH for tag in tag_ids):
            return _refused("tag_label_out_of_bounds")
        if len(tag_ids) != len(set(tag_ids)):
            return _refused("duplicate_tag_ids")
        if "replace_tags" not in row["actions"]:
            reason = ("inherited_tags_not_movement_scoped"
                      if projection.inherited_tags_of(movement)
                      else "tag_vocabulary_unavailable")
            return _refused(reason)
        # The complete vocabulary lists every known tag; a bounded replacement
        # may also introduce a tag.
        if projection.movement_tags_of(movement) == sorted(tag_ids):
            return ActionOutcome(
                "completed", moment("activity_tags_unchanged")
            ).as_dict()
        tag_movement(self._vault.ledger, movement_key, sorted(tag_ids), by="human")
        return ActionOutcome(
            "completed", moment("activity_tags_recorded", count=len(tag_ids))
        ).as_dict()

    def add_tags(self, payload: dict[str, Any]) -> dict[str, Any]:
        movement_keys, tag_ids = _tag_batch_request(payload)
        return self._change_tags(movement_keys, tag_ids, remove=False)

    def remove_tags(self, payload: dict[str, Any]) -> dict[str, Any]:
        movement_keys, tag_ids = _tag_batch_request(payload)
        return self._change_tags(movement_keys, tag_ids, remove=True)

    def _change_tags(self, movement_keys: list[str], tag_ids: list[str], *,
                     remove: bool) -> dict[str, Any]:
        outcome = {"reason": "", "changed": 0}

        def decide(projection):
            movements = {movement.key: movement for movement in projection.movements()}
            selected = [movements.get(key) for key in movement_keys]
            if any(movement is None for movement in selected):
                outcome["reason"] = "movement_selection_stale"
                return ()
            if any(projection.tag_alias_is_ambiguous(tag) for tag in tag_ids):
                outcome["reason"] = "tag_alias_ambiguous"
                return ()
            canonical = [projection.canonical_tag(tag) for tag in tag_ids]
            if any(not tag or len(tag) > MAX_TAG_LABEL_LENGTH
                   for tag in canonical):
                outcome["reason"] = "tag_label_out_of_bounds"
                return ()
            if len(canonical) != len(set(canonical)):
                outcome["reason"] = "duplicate_tag_ids"
                return ()
            requested = set(canonical)
            if remove and any(
                    requested & set(projection.inherited_tags_of(movement))
                    for movement in selected if movement is not None):
                outcome["reason"] = "inherited_tags_not_movement_scoped"
                return ()
            changes: list[tuple[str, list[str]]] = []
            for movement in selected:
                assert movement is not None
                current = set(projection.movement_tags_of(movement))
                if any(projection.tag_alias_is_ambiguous(tag)
                       for tag in current):
                    outcome["reason"] = "tag_alias_ambiguous"
                    return ()
                desired = current - requested if remove else current | requested
                ordered = sorted(desired)
                if (len(ordered) > MAX_SELECTED_TAGS
                        or any(not tag or len(tag) > MAX_TAG_LABEL_LENGTH
                               for tag in ordered)):
                    outcome["reason"] = (
                        "too_many_tags" if len(ordered) > MAX_SELECTED_TAGS
                        else "tag_label_out_of_bounds")
                    return ()
                if ordered != sorted(current):
                    changes.append((movement.key, ordered))
            events = tuple(movement_tagged(
                movement_key, tags, _now(), scope=SCOPE_MOVEMENT, by="human")
                for movement_key, tags in changes)
            outcome["changed"] = len(events)
            return events

        self._vault.ledger.append_atomically(decide)
        if outcome["reason"] == "movement_selection_stale":
            return _selection_stale()
        if outcome["reason"]:
            return _refused(outcome["reason"])
        if not outcome["changed"]:
            return ActionOutcome(
                "completed", moment("activity_tags_unchanged")
            ).as_dict()
        return ActionOutcome(
            "completed", moment("activity_tags_recorded", count=len(tag_ids))
        ).as_dict()

    def confirm_transfer(self, payload: dict[str, Any]) -> dict[str, Any]:
        movement_key, counterpart_key = _transfer_pair_request(payload)
        _projection, movement, row, _vocabularies = self._live(movement_key)
        if movement is None:
            return _stale()
        transfer = row["transfer"]
        if (transfer.get("state") != "suggested"
                or "confirm_transfer" not in row["actions"]
                or counterpart_key not in {
                    candidate["id"] for candidate in transfer.get("candidates", [])
                }):
            return _transfer_stale()
        if not write_transfer_link(
                self._vault.ledger, movement_key, counterpart_key):
            return _transfer_stale()
        return ActionOutcome(
            "completed", moment("activity_transfer_confirmed")
        ).as_dict()

    def reject_transfer(self, payload: dict[str, Any]) -> dict[str, Any]:
        movement_key = _transfer_movement_request(payload)
        _projection, movement, row, _vocabularies = self._live(movement_key)
        if movement is None:
            return _stale()
        transfer = row["transfer"]
        if (transfer.get("state") != "suggested"
                or "reject_transfer" not in row["actions"]):
            return _transfer_stale()
        # Rejection settles the whole current suggestion. The existing writer
        # records that ruling as an unlink/rejection event with no counterpart.
        write_transfer_unlink(self._vault.ledger, movement_key)
        return ActionOutcome(
            "completed", moment("activity_transfer_rejected")
        ).as_dict()

    def unlink_transfer(self, payload: dict[str, Any]) -> dict[str, Any]:
        movement_key, counterpart_key = _transfer_pair_request(payload)
        _projection, movement, row, _vocabularies = self._live(movement_key)
        if movement is None:
            return _stale()
        transfer = row["transfer"]
        if (transfer.get("state") != "linked"
                or "unlink_transfer" not in row["actions"]
                or transfer.get("counterpart", {}).get("id") != counterpart_key):
            return _transfer_stale()
        write_transfer_unlink(
            self._vault.ledger, movement_key, counterpart_key)
        return ActionOutcome(
            "completed", moment("activity_transfer_unlinked")
        ).as_dict()

    def _live(self, movement_key: str):
        projection = self._vault.ledger.projection()
        movements = list(projection.movements())
        movement = next((item for item in movements if item.key == movement_key), None)
        if movement is None:
            return projection, None, None, None
        read = activity(projection, limit=max(1, len(movements)))
        row = next(item for item in read["items"] if item["id"] == movement_key)
        return projection, movement, row, read["vocabularies"]


def _category_request(payload: dict[str, Any]) -> tuple[str, str]:
    allowed = {"movement_key", "category_id"}
    _closed(payload, allowed)
    movement_key = payload.get("movement_key")
    if not isinstance(movement_key, str) or not movement_key.strip():
        raise BridgeRequestError("movement_key must be a non-empty string")
    category_id = payload.get("category_id")
    if not isinstance(category_id, str) or not category_id.strip():
        raise BridgeRequestError("category_id must be a non-empty string")
    return movement_key, category_id


def _classification_request(payload: dict[str, Any]) -> tuple[list[str], str, str]:
    allowed = {"movement_ids", "category_id", "subcategory_id"}
    _closed(payload, allowed)
    movement_ids = _movement_selection(payload.get("movement_ids"))
    category = payload.get("category_id")
    subcategory = payload.get("subcategory_id")
    if not isinstance(category, str) or not category.strip():
        raise BridgeRequestError("category_id must be a non-empty string")
    if not isinstance(subcategory, str) or not subcategory.strip():
        raise BridgeRequestError("subcategory_id must be a non-empty string")
    category_id = normalize_category(category)
    subcategory_id = subcategory_identity(subcategory)
    if not subcategory_id:
        raise BridgeRequestError("subcategory_id must name a subcategory")
    return movement_ids, category_id, subcategory_id


def _meaning_request(payload: dict[str, Any]) -> tuple[str, str, str]:
    allowed = {"movement_key", "meaning", "counterparty"}
    _closed(payload, allowed)
    movement_key = payload.get("movement_key")
    meaning = payload.get("meaning")
    counterparty = payload.get("counterparty")
    if not isinstance(movement_key, str) or not movement_key.strip():
        raise BridgeRequestError("movement_key must be a non-empty string")
    if not isinstance(meaning, str) or not meaning.strip():
        raise BridgeRequestError("meaning must be a non-empty string")
    if not isinstance(counterparty, str):
        raise BridgeRequestError("counterparty must be a string")
    return movement_key, meaning, counterparty


def _tag_request(payload: dict[str, Any]) -> tuple[str, list[str]]:
    allowed = {"movement_key", "tag_ids"}
    _closed(payload, allowed)
    movement_key = payload.get("movement_key")
    tag_ids = payload.get("tag_ids")
    if not isinstance(movement_key, str) or not movement_key.strip():
        raise BridgeRequestError("movement_key must be a non-empty string")
    if not isinstance(tag_ids, list) or any(not isinstance(tag, str) for tag in tag_ids):
        raise BridgeRequestError("tag_ids must be a list of strings")
    return movement_key, tag_ids


def _tag_batch_request(payload: dict[str, Any]) -> tuple[list[str], list[str]]:
    allowed = {"movement_ids", "tag_ids"}
    _closed(payload, allowed)
    movement_ids = _movement_selection(payload.get("movement_ids"))
    supplied = payload.get("tag_ids")
    if not isinstance(supplied, list) or any(
            not isinstance(tag, str) for tag in supplied):
        raise BridgeRequestError("tag_ids must be a list of strings")
    if not supplied:
        raise BridgeRequestError("tag_ids must not be empty")
    tag_ids = [tag.strip().lower() for tag in supplied]
    if len(tag_ids) > MAX_SELECTED_TAGS:
        raise BridgeRequestError(
            f"tag_ids may contain at most {MAX_SELECTED_TAGS} tags")
    if any(not tag or len(tag) > MAX_TAG_LABEL_LENGTH for tag in tag_ids):
        raise BridgeRequestError(
            f"tag ids must be 1 to {MAX_TAG_LABEL_LENGTH} characters")
    if len(tag_ids) != len(set(tag_ids)):
        raise BridgeRequestError("tag_ids must be unique after normalization")
    return movement_ids, tag_ids


def _movement_selection(raw: Any) -> list[str]:
    if not isinstance(raw, list) or any(not isinstance(key, str) for key in raw):
        raise BridgeRequestError("movement_ids must be a list of strings")
    if not raw:
        raise BridgeRequestError("movement_ids must not be empty")
    if len(raw) > MAX_BATCH_MOVEMENTS:
        raise BridgeRequestError(
            f"movement_ids may contain at most {MAX_BATCH_MOVEMENTS} identities")
    if any(not key or not key.strip() or key != key.strip() for key in raw):
        raise BridgeRequestError(
            "movement_ids must contain exact non-empty movement identities")
    if len(raw) != len(set(raw)):
        raise BridgeRequestError("movement_ids must not contain duplicates")
    return list(raw)


def _valid_subcategory_pair(projection: Any, category: str,
                            subcategory: str) -> bool:
    requested = subcategory_group_key(category, subcategory)
    # Historical catalog events may predate normalized category writers.  Pair
    # identity remains case-normalized even when an unaliased read preserves
    # the historical display spelling.
    known = {pair.lower() for pair in projection.known_subcategory_pairs()}
    shipped = {
        subcategory_group_key(
            projection.canonical_category(normalize_category(parent)),
            projection.canonical_subcategory(subcategory_identity(label)))
        for parent, labels in seed_subcategories_by_category().items()
        for label in labels
    }
    return requested.lower() in known or requested in shipped


def _canonical_classification_pair(
        projection: Any, category: str,
        subcategory: str) -> tuple[str, str] | None:
    category = normalize_category(category)
    subcategory = subcategory_identity(subcategory)
    if (projection.category_alias_is_ambiguous(category)
            or projection.subcategory_alias_is_ambiguous(subcategory)):
        return None
    return (projection.canonical_category(category),
            projection.canonical_subcategory(subcategory))


def _record_pair(projection: Any,
                 record: dict[str, Any]) -> tuple[str, str]:
    raw_category = str(record.get("category", "") or "").strip()
    raw_subcategory = str(record.get("subcategory", "") or "").strip()
    category = (projection.canonical_category(normalize_category(raw_category))
                if raw_category else "")
    subcategory = (projection.canonical_subcategory(
        subcategory_identity(raw_subcategory)) if raw_subcategory else "")
    return category, subcategory


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _transfer_pair_request(payload: dict[str, Any]) -> tuple[str, str]:
    allowed = {"movement_key", "counterpart_key"}
    _closed(payload, allowed)
    movement_key = payload.get("movement_key")
    counterpart_key = payload.get("counterpart_key")
    if not isinstance(movement_key, str) or not movement_key.strip():
        raise BridgeRequestError("movement_key must be a non-empty string")
    if not isinstance(counterpart_key, str) or not counterpart_key.strip():
        raise BridgeRequestError("counterpart_key must be a non-empty string")
    if movement_key == counterpart_key:
        raise BridgeRequestError("a transfer counterpart must be another movement")
    return movement_key, counterpart_key


def _transfer_movement_request(payload: dict[str, Any]) -> str:
    allowed = {"movement_key"}
    _closed(payload, allowed)
    movement_key = payload.get("movement_key")
    if not isinstance(movement_key, str) or not movement_key.strip():
        raise BridgeRequestError("movement_key must be a non-empty string")
    return movement_key


def _closed(payload: dict[str, Any], expected: set[str]) -> None:
    if not isinstance(payload, dict):
        raise BridgeRequestError("activity action payload must be an object")
    unexpected = set(payload) - expected
    missing = expected - set(payload)
    if unexpected or missing:
        detail = []
        if missing:
            detail.append("missing: " + ", ".join(sorted(missing)))
        if unexpected:
            detail.append("unexpected: " + ", ".join(sorted(unexpected)))
        raise BridgeRequestError("invalid activity action fields (" + "; ".join(detail) + ")")


def _stale() -> dict[str, Any]:
    return ActionOutcome("stale", moment("activity_movement_stale"),
                         reason="movement_not_current").as_dict()


def _selection_stale() -> dict[str, Any]:
    return ActionOutcome(
        "stale", moment("activity_movement_stale"),
        reason="movement_selection_stale"
    ).as_dict()


def _refused(reason: str) -> dict[str, Any]:
    key = ("activity_tags_scope_refused"
           if reason == "inherited_tags_not_movement_scoped"
           else "activity_correction_refused")
    return ActionOutcome("refused", moment(key), reason=reason).as_dict()


def _transfer_stale() -> dict[str, Any]:
    return ActionOutcome(
        "stale", moment("activity_transfer_state_stale"),
        reason="transfer_state_changed"
    ).as_dict()
