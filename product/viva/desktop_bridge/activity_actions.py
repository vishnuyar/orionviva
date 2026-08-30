"""Explicit movement-scoped category, tag and transfer correction actions."""

from __future__ import annotations

from typing import Any

from viva.ingest.categorize import (assign_category as write_category,
                                    assign_movement_meaning, tag_movement)
from viva.ingest.transfers import (confirm_transfer as write_transfer_link,
                                   reject_transfer as write_transfer_unlink)
from viva.persona import moment
from viva.surface.activity import (MAX_SELECTED_TAGS, MAX_TAG_LABEL_LENGTH,
                                   activity)
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

    def assign_meaning(self, payload: dict[str, Any]) -> dict[str, Any]:
        movement_key, meaning, counterparty = _meaning_request(payload)
        _projection, movement, row, _vocabularies = self._live(movement_key)
        if movement is None:
            return _stale()
        if "assign_meaning" not in row["actions"]:
            return _refused("movement_meaning_unavailable")
        try:
            recorded = assign_movement_meaning(
                self._vault.ledger, movement_key, meaning, counterparty)
        except ValueError:
            return _refused("movement_meaning_invalid")
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
        advertised = {item["id"] for item in vocabularies["tags"]["items"]}
        if any(tag not in advertised for tag in tag_ids):
            return _refused("tag_not_advertised")
        if projection.movement_tags_of(movement) == sorted(tag_ids):
            return ActionOutcome(
                "completed", moment("activity_tags_unchanged")
            ).as_dict()
        tag_movement(self._vault.ledger, movement_key, sorted(tag_ids), by="human")
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
