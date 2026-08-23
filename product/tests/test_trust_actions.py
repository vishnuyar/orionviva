"""Trust's remainder: the maintenance run, anchoring, and a file to send.

Two of the three are about saying plainly what this machine cannot establish.
The third is about a file somebody can hand over without handing over their
money.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from viva.desktop_bridge.handlers import BridgeRequestError, handlers_for_opened_vault
from viva.desktop_bridge.trust_actions import TrustActions, _run_request
from viva.desktop_bridge.vault_surface import OpenedVaultSurfaceProvider
from viva.ledger.events import document_captured, read_recorded
from viva.persona import moment
from viva.surface.diagnostics import FIELDS, diagnostics, written
from viva.vault import Vault

PASSPHRASE = "a-real-passphrase"


def _vault(tmp_path: Path) -> Vault:
    vault = Vault.open(tmp_path / "vault", PASSPHRASE)
    vault.ledger.append(document_captured("d" * 64, "everyday-checking.pdf", 11,
                                          "statement", 0.9, "2026-07-01"))
    vault.ledger.append(read_recorded("d" * 64, "a-pinned-1", "p", "text", "{}",
                                      0.25, 1, 2, True, None, "2026-07-01"))
    return vault


# ------------------------------------------------------- unattended work


def test_a_request_that_does_not_say_to_spend_plans_and_stops(tmp_path: Path):
    """The agent reaches a model. A request that did not say to spend has not
    asked for that."""
    answered = TrustActions(_vault(tmp_path)).run({})

    assert answered["kind"] == "completed"
    assert answered["message"] == moment("maintenance_planned")
    assert answered["state"]["dry_run"] is True
    assert answered["state"]["calls_spent"] == 0


def test_a_run_with_work_to_do_and_no_model_named_says_so_and_sends_nothing(
        tmp_path: Path, monkeypatch):
    import viva.agent.run as agent

    monkeypatch.setattr(agent, "model_configured", lambda: False)

    answered = TrustActions(_vault(tmp_path)).run({"spend": True})

    assert answered["state"]["calls_spent"] == 0
    # A vault with nothing to do reports a plain run; one with work waiting
    # reports that it could not spend. Either way nothing was sent.
    assert answered["message"] in {moment("maintenance_ran"),
                                   moment("maintenance_unconfigured")}


def test_the_reply_carries_the_whole_run_rather_than_a_summary(tmp_path: Path):
    """A report of unattended work that summarised itself would be the one
    place in this product where somebody has to take a summary on trust."""
    answered = TrustActions(_vault(tmp_path)).run({})

    for named in ("observation", "considered", "cooled", "deferred",
                  "performed", "calls_spent", "calls_budget"):
        assert named in answered["state"]


def test_spending_is_a_word_and_a_budget_is_a_number():
    assert _run_request({}) == (False, None)
    assert _run_request({"spend": True, "budget": 3}) == (True, 3)
    with pytest.raises(BridgeRequestError):
        _run_request({"spend": "yes"})
    with pytest.raises(BridgeRequestError):
        _run_request({"budget": -1})
    with pytest.raises(BridgeRequestError):
        _run_request({"spend": True, "rules": {}})


# ----------------------------------------------------------- what is absent


def test_the_trust_read_says_plainly_that_nothing_is_anchored(tmp_path: Path):
    """An absent capability described in soft words reads as a capability."""
    read = OpenedVaultSurfaceProvider(_vault(tmp_path)).read_surface("trust", {})

    anchoring = [item for item in read["absences"] if item["id"] == "anchoring"]
    assert anchoring
    assert anchoring[0]["sentence"] == moment("trust_no_anchoring")


def test_a_vault_nothing_has_run_over_says_that_too(tmp_path: Path):
    read = OpenedVaultSurfaceProvider(_vault(tmp_path)).read_surface("trust", {})

    assert [item["id"] for item in read["absences"]] == [
        "anchoring", "conversation_history", "maintenance"]


# --------------------------------------------------- a file somebody can send


def test_the_diagnostic_carries_only_the_fields_it_names():
    """Built from a list of what may be said rather than by removing what must
    not travel: a list of what to take out is wrong the first time somebody
    adds a field."""
    assert set(diagnostics()) == set(FIELDS)


def test_nothing_from_a_vault_reaches_the_diagnostic(tmp_path: Path):
    vault = _vault(tmp_path)
    written_to = tmp_path / "diagnostic.json"

    answered = TrustActions(vault).diagnose({"file": str(written_to)})
    held = written_to.read_text()

    assert answered["kind"] == "completed"
    assert answered["message"] == moment("diagnostic_written")
    for private in ("everyday-checking.pdf", "d" * 64, "0.25", "2026-07-01"):
        assert private not in held


def test_the_diagnostic_counts_what_a_vault_holds_without_naming_any_of_it(
        tmp_path: Path):
    vault = _vault(tmp_path)
    written_to = tmp_path / "diagnostic.json"

    TrustActions(vault).diagnose({"file": str(written_to)})
    held = json.loads(written_to.read_text())

    assert held["documents"] == 1
    assert held["model_calls"] == 1
    assert held["events"] >= 2


def test_the_model_is_reported_as_named_or_not_and_never_by_name(monkeypatch):
    """A pinned id names a provider and a spend."""
    monkeypatch.setenv("VIVA_MODEL_ADAPTER", "anthropic")
    monkeypatch.setenv("VIVA_MODEL", "a-very-particular-model-1")

    held = diagnostics()

    assert held["model_named"] is True
    assert held["model_adapter"] == "anthropic"
    assert "a-very-particular-model-1" not in json.dumps(held)


def test_a_count_that_is_not_a_count_writes_a_zero_rather_than_itself():
    """A caller that handed a name or an amount by mistake writes a zero rather
    than writing it out."""
    held = diagnostics({"documents": "Everyday Checking", "events": -4,
                        "model_calls": True})

    assert held["documents"] == 0
    assert held["events"] == 0
    assert held["model_calls"] == 0


def test_the_file_is_readable_before_it_is_sent():
    """The only check that matters is a person reading it."""
    text = written({"documents": 2})

    assert json.loads(text)["documents"] == 2
    assert text.endswith("\n")


def test_a_file_that_will_not_be_written_changes_nothing(tmp_path: Path):
    answered = TrustActions(_vault(tmp_path)).diagnose(
        {"file": str(tmp_path / "vault" / "events.jsonl" / "nope.json")})

    assert answered["kind"] == "refused"
    assert answered["reason"] == "file_unwritable"


def test_both_actions_are_served_by_an_opened_vault():
    handlers = handlers_for_opened_vault(object()).handlers

    assert "viva.maintenance.run" in handlers
    assert "viva.maintenance.diagnose" in handlers
