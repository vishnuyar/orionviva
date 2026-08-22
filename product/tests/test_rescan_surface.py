"""A pass back over what a vault already holds, and what it says it did.

Counts are not a read model. Every test here is about the difference: whether
a screen is handed sentences somebody reviewed, or numbers it would have to
invent words for.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from viva import render
from viva.desktop_bridge.handlers import handlers_for_opened_vault
from viva.desktop_bridge.rpc import dispatch_frame
from viva.persona import moment
from viva.surface import CURRENT_PROTOCOL
from viva.surface.rescan import rescan
from viva.vault import Vault

RESCAN = "viva.documents.rescan"
PASSPHRASE = "a-real-passphrase"

NOTHING = {"gaps": 0, "corroborated": 0, "auto": 0, "suggested": 0,
           "resolved": 0, "open_before": 0, "links": 0}


def test_a_pass_that_changed_nothing_says_so_in_its_own_sentence():
    """An empty list of changes and a sweep that found nothing look identical
    on a screen and mean different things — the first reads as a panel that
    failed to render."""
    view = rescan(NOTHING)

    assert view["state"] == "ready"
    assert view["changes"] == []
    assert view["sentence"] == moment("rescan_nothing")


def test_a_count_of_zero_is_not_a_row():
    """A line saying nothing was linked is a line a person reads and learns
    nothing from, and six of them are a screen that has stopped meaning
    anything."""
    view = rescan({**NOTHING, "gaps": 2})

    assert [change["id"] for change in view["changes"]] == ["gaps"]


def test_every_change_carries_the_reviewed_sentence_for_what_it_is():
    view = rescan({**NOTHING, "gaps": 2, "corroborated": 1, "auto": 3, "resolved": 4})

    assert [change["id"] for change in view["changes"]] == [
        "gaps", "corroborated", "auto", "resolved"]
    assert view["changes"][0]["sentence"] == moment("rescan_gaps", count=render.count(2))
    assert view["changes"][2]["sentence"] == moment("rescan_linked", count=render.count(3))


def test_what_is_still_open_is_carried_apart_from_what_this_pass_did():
    """The sweep reports how many possible transfers are waiting. That is a
    standing fact about the vault, not something this pass did, and a screen
    must not be able to present it as an outcome."""
    view = rescan({**NOTHING, "suggested": 5})

    assert view["changes"] == []
    assert [item["id"] for item in view["standing"]] == ["suggested"]
    assert view["standing"][0]["sentence"] == moment("rescan_open", count=render.count(5))


def test_a_pass_that_changed_something_says_what_it_did_not_do():
    """The obvious next thought after "it went back over everything" is that it
    read the documents. It did not."""
    view = rescan({**NOTHING, "gaps": 1})

    assert view["sentence"] == moment("rescan_unread")


def test_a_count_that_is_not_a_count_is_read_as_none_rather_than_coerced():
    view = rescan({**NOTHING, "gaps": "two", "auto": -1, "corroborated": True})

    assert view["changes"] == []


def test_the_whole_view_is_json_safe():
    json.dumps(rescan({**NOTHING, "gaps": 1, "suggested": 2}), allow_nan=False)


# ------------------------------------------------------------- over the bridge


def _frame(operation: str, payload: dict) -> str:
    return json.dumps({"protocol": CURRENT_PROTOCOL.wire(), "request_id": "r1",
                       "operation": operation, "payload": payload})


def _send(vault: Vault, payload: dict) -> dict:
    handlers = handlers_for_opened_vault(vault).handlers
    return json.loads(dispatch_frame(_frame(RESCAN, payload), handlers))


def test_a_pass_over_an_empty_vault_answers_completed_and_says_nothing_changed(tmp_path: Path):
    """A pass that changed nothing did happen. Reporting it as anything but
    completed would have a person press it again expecting a different
    answer."""
    vault = Vault.open(tmp_path / "vault", PASSPHRASE)

    answered = _send(vault, {})

    assert answered["ok"] is True
    result = answered["result"]
    assert result["kind"] == "completed"
    assert result["message"] == moment("rescan_nothing")
    assert result["state"]["changes"] == []
    assert result["state"]["job_id"].startswith("viva.documents.rescan-")


def test_the_request_carries_nothing_at_all(tmp_path: Path):
    """A pass goes over the whole vault. A field naming part of it would be a
    caller asserting a scope the sweep does not have."""
    vault = Vault.open(tmp_path / "vault", PASSPHRASE)

    answered = _send(vault, {"since": "2026-01-01"})

    assert answered["ok"] is False
    assert answered["error"]["code"] == "invalid_request"


def test_running_it_twice_over_an_unchanged_vault_changes_nothing_twice(tmp_path: Path):
    vault = Vault.open(tmp_path / "vault", PASSPHRASE)

    first = _send(vault, {})["result"]
    second = _send(vault, {})["result"]

    assert first["state"]["changes"] == second["state"]["changes"] == []
    assert first["message"] == second["message"]


def test_no_model_runs_on_this_route_whatever_the_environment_holds(tmp_path: Path, monkeypatch):
    """Going back over what is already held reads nothing new, which is what
    makes this an action a person can press without agreeing to anything."""
    import viva.ingest.reader as reader

    def refuse(*_args, **_kwargs):
        raise AssertionError("a rescan reached the model edge")

    monkeypatch.setattr(reader, "build_reader", refuse, raising=False)
    vault = Vault.open(tmp_path / "vault", PASSPHRASE)

    assert _send(vault, {})["ok"] is True


def test_the_action_is_served_by_an_opened_vault():
    assert RESCAN in handlers_for_opened_vault(object()).handlers
