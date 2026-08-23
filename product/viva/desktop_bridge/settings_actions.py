"""Injected settings actions: a proposal, and the yes that applies it.

This module knows neither the vault implementation nor the desktop transport.
It is the bridge half of `viva.configuration`, and it keeps that module's one
structural distinction rather than restating it as a rule: there are two propose
handlers and two apply paths, and the presentation one has nowhere to put a
model, an adapter or a key.

**Nothing is applied by proposing.** A proposal describes what would change,
says whether saying yes to it makes bytes able to leave, and carries the digest
a yes has to name. A yes naming a different digest applies nothing, because a
person who was shown one thing and confirmed while another was in flight has not
agreed to what would happen.

**A key exists in one request and nowhere else.** It is not on a proposal, not
in a reply, not in a digest and not in a log line. What travels back is whether
one is set.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from viva.surface import ActionOutcome

from .handlers import BridgeRequestError

# Each way a proposal can be refused, against the sentence that says what
# stopped. Every one of them states that nothing changed and nothing was sent,
# because a person reading a refusal about sending needs both facts.
_SENTENCES: dict[str, str] = {
    "locale_unknown": "settings_locale_unknown",
    "currency_unknown": "settings_currency_unknown",
    "adapter_unknown": "settings_adapter_unknown",
    "model_unnamed": "settings_model_unnamed",
    "key_missing": "settings_key_missing",
    "settings_unwritable": "settings_unwritable",
    "proposal_moved": "settings_declined",
}


class SettingsActions:
    """The allowlisted settings handlers for one sidecar."""

    def propose(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Describe what would change, and change nothing.

        The reply is a `proposal` outcome in every branch that built one. That
        word is the vocabulary's own for a reply held for a confirmation, which
        is exactly what this is."""
        from viva.configuration import (ConfigurationError, propose_model,
                                        propose_presentation)
        from viva.persona import moment

        kind, fields = _propose_request(payload)
        try:
            proposal = (propose_presentation(**fields) if kind == "presentation"
                        else propose_model(**fields))
        except ConfigurationError as exc:
            return _refused(exc.reason)
        said = ("settings_model_proposed" if proposal.sends
                else "settings_presentation_proposed")
        return ActionOutcome("proposal", moment(said),
                             state=proposal.as_dict()).as_dict()

    def confirm(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Apply exactly the proposal that was shown, or nothing.

        The proposal is rebuilt here from the same fields rather than taken
        from the caller. A caller that could hand back a proposal object could
        hand back one nobody was shown, and the digest would then be a name for
        a thing the caller chose."""
        from viva.configuration import (ConfigurationError, apply,
                                        propose_model, propose_presentation)
        from viva.persona import moment

        kind, fields, digest, key = _confirm_request(payload)
        try:
            proposal = (propose_presentation(**fields) if kind == "presentation"
                        else propose_model(**fields, key=key))
            settings = apply(proposal, digest, key)
        except ConfigurationError as exc:
            return _refused(exc.reason)
        if kind == "presentation":
            said = "settings_presentation_confirmed"
        elif not settings.can_send:
            said = "settings_model_cleared"
        elif proposal.changes.get("key") == "not needed":
            said = "settings_model_keyless_confirmed"
        else:
            said = "settings_model_confirmed"
        return ActionOutcome("completed", moment(said),
                             state=settings.as_dict()).as_dict()

    def read(self, payload: dict[str, Any]) -> dict[str, Any]:
        """What is in force, as a screen may read it. No key is in the reply."""
        from viva.configuration import current

        _fenced(payload, set(), "viva.settings.read")
        return {"state": "ready", **current().as_dict()}


def _refused(reason: str) -> dict[str, Any]:
    from viva.persona import moment

    return ActionOutcome("refused", moment(_SENTENCES[reason]),
                         reason=reason).as_dict()


# The fields each kind of proposal accepts. Two sets rather than one with a
# filter: the presentation path has nowhere to put a model, so nothing on it
# can reach the reader's model edge — which is a property of the shape rather
# than of a check a later edit could relax.
_PRESENTATION_FIELDS = {"locale", "currency"}
_MODEL_FIELDS = {"adapter", "model", "base_url", "key_action"}


def _propose_request(payload: Mapping[str, Any]) -> tuple[str, dict[str, str]]:
    allowed = {"kind"} | _PRESENTATION_FIELDS | _MODEL_FIELDS
    _fenced(payload, allowed, "viva.settings.propose")
    kind = _kind(payload)
    if kind == "model":
        _key_action(payload)
    fields = _PRESENTATION_FIELDS if kind == "presentation" else _MODEL_FIELDS
    return kind, {name: _text(payload, name) for name in sorted(fields)
                  if name in payload}


def _confirm_request(payload: Mapping[str, Any]) -> tuple[str, dict[str, str], str, str]:
    allowed = {"kind", "digest", "key"} | _PRESENTATION_FIELDS | _MODEL_FIELDS
    _fenced(payload, allowed, "viva.settings.confirm")
    kind = _kind(payload)
    if kind == "model":
        _key_action(payload)
    if kind == "presentation" and "key" in payload:
        # The one place the two paths could be joined by a caller, closed here
        # rather than ignored: a request that sends a key under the kind that
        # sends nothing is refused as the request it is.
        raise BridgeRequestError(
            "viva.settings.confirm does not accept a key for presentation")
    digest = payload.get("digest")
    if not isinstance(digest, str) or not digest.strip():
        raise BridgeRequestError("digest must be a non-empty string")
    fields = _PRESENTATION_FIELDS if kind == "presentation" else _MODEL_FIELDS
    return (kind,
            {name: _text(payload, name) for name in sorted(fields) if name in payload},
            digest, _text(payload, "key"))


def _kind(payload: Mapping[str, Any]) -> str:
    kind = payload.get("kind")
    if kind not in ("presentation", "model"):
        raise BridgeRequestError("kind must be presentation or model")
    return kind


def _key_action(payload: Mapping[str, Any]) -> None:
    action = _text(payload, "key_action")
    if action not in ("", "set", "none"):
        raise BridgeRequestError("key_action must be set, none, or empty")


def _text(payload: Mapping[str, Any], name: str) -> str:
    value = payload.get(name, "")
    if not isinstance(value, str):
        raise BridgeRequestError(f"{name} must be a string")
    return value


def _fenced(payload: Mapping[str, Any], allowed: set[str], operation: str) -> None:
    unexpected = set(payload) - allowed
    if unexpected:
        raise BridgeRequestError(
            f"{operation} does not accept fields: {', '.join(sorted(unexpected))}")
