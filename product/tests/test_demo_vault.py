"""Contracts for the persistent fictional sample vault."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from viva.demo import DEMO_PASSPHRASE, build_demo_vault, demo_home, open_demo_vault
from viva.desktop_bridge.__main__ import Sidecar
from viva.desktop_bridge.vault_surface import OpenedVaultSurfaceProvider
from viva.persona import moment
from viva.surface import BRIDGE_OPEN_DEMO_VAULT, CURRENT_PROTOCOL
from viva.vault import Vault, holds_a_vault


def _frame(operation: str, payload: dict | None = None, request_id: str = "r") -> str:
    return json.dumps({"protocol": CURRENT_PROTOCOL.wire(), "request_id": request_id,
                       "operation": operation, "payload": payload or {}})


def _open(sidecar: Sidecar) -> dict:
    return json.loads(sidecar.handle(_frame(BRIDGE_OPEN_DEMO_VAULT))[0])


@pytest.fixture
def home(tmp_path, monkeypatch) -> Path:
    monkeypatch.setenv("VIVA_DEMO_HOME", str(tmp_path / "sample-vault"))
    return tmp_path / "sample-vault"


# ---------------------------------------------------------- vault persistence


def test_the_sample_is_a_vault_the_engine_opens(home: Path):
    vault, made = open_demo_vault()

    assert made is True
    assert holds_a_vault(home)
    assert Vault.open(home, DEMO_PASSPHRASE, create=False) is not None


def test_it_is_minted_once_and_stays(home: Path):
    """The sample is created once and persists between opens."""
    first, made_first = open_demo_vault()
    events = len(list(first.events()))

    second, made_second = open_demo_vault()

    assert made_first is True
    assert made_second is False
    assert len(list(second.events())) == events


def test_sample_open_immediately_serves_converted_current_surfaces(home: Path):
    vault, _ = open_demo_vault()
    provider = OpenedVaultSurfaceProvider(vault)

    assert vault.read_store_lifecycle in {"equal", "caught_up", "rebuilt"}
    assert provider.read_surface("activity", {})["state"] == "ready"
    assert provider.read_surface("spending", {})["state"] in {"ready", "empty"}


def test_fresh_and_existing_sample_each_have_one_readiness_owner(
        home: Path, monkeypatch: pytest.MonkeyPatch):
    calls = []
    real_synchronize = Vault.synchronize_read_store

    def synchronize(vault, *args, **kwargs):
        calls.append(vault.directory)
        return real_synchronize(vault, *args, **kwargs)

    monkeypatch.setattr(Vault, "synchronize_read_store", synchronize)
    fresh, made = open_demo_vault()
    assert made is True
    assert calls == [home]
    fresh.close()

    existing, made = open_demo_vault()
    assert made is False
    assert calls == [home, home]
    existing.close()


def test_every_surface_an_opened_vault_answers_has_something_to_show(home: Path):
    """Every sample destination returns a renderable state."""
    vault, _ = open_demo_vault()
    provider = OpenedVaultSurfaceProvider(vault)

    for surface in sorted(OpenedVaultSurfaceProvider._SURFACES - {"jobs"}):
        parameters = ({"account_id": "acct:everyday-checking"}
                      if surface == "account_ledger" else {})
        read = provider.read_surface(surface, parameters)
        assert read["state"] in ({"ready", "empty"}
                                 if surface == "spending" else {"ready"}), surface
        json.dumps(read, allow_nan=False)


def test_the_states_the_other_screens_can_be_in_are_reachable(home: Path):
    vault, _ = open_demo_vault()
    provider = OpenedVaultSurfaceProvider(vault)

    review = provider.read_surface("conversation", {})
    activity = provider.read_surface("activity", {})
    trust = provider.read_surface("trust", {})

    # The sample queue contains multiple question kinds.
    assert len({question["kind"] for question in review["questions"]}) > 1
    # At least one question uses a closed vocabulary.
    assert any(slot.get("choices") for question in review["questions"]
               for slot in question["slots"])
    # Activity includes a linked transfer and both directions.
    assert any(item["linked"] for item in activity["items"])
    assert {item["direction"] for item in activity["items"]} == {"in", "out"}
    # Trust includes outbound activity and only the remaining absence.
    assert trust["outbound"]["call_count"] > 0
    assert [absence["id"] for absence in trust["absences"]] == ["anchoring"]


def test_every_document_is_named_the_way_a_person_would_recognise_it(home: Path):
    """Every sample document has a distinct display filename."""
    vault, _ = open_demo_vault()

    read = OpenedVaultSurfaceProvider(vault).read_surface("documents", {})
    names = [row["filename"] for row in read["documents"]]

    assert len(set(names)) == len(names)


# ----------------------------------------------------------- sidecar opening


def test_the_sidecar_opens_it_from_a_request_that_names_nothing(home: Path):
    """The sidecar opens the sample without caller-supplied credentials."""
    answered = _open(Sidecar(io.StringIO()))

    assert answered["ok"] is True
    assert answered["result"]["sample"] is True
    assert answered["result"]["message"] == moment("vault_sample_opened")
    assert DEMO_PASSPHRASE not in json.dumps(answered)


def test_a_request_that_names_anything_at_all_is_refused(home: Path):
    answered = json.loads(Sidecar(io.StringIO()).handle(
        _frame(BRIDGE_OPEN_DEMO_VAULT, {"vault_directory": "/somebody/else"}))[0])

    assert answered["ok"] is False
    assert not holds_a_vault(Path("/somebody/else"))


def test_the_frame_words_come_from_the_pack_rather_than_from_a_screen(home: Path):
    """The sample frame uses the shipped copy pack."""
    frame = _open(Sidecar(io.StringIO()))["result"]["frame"]

    assert frame == {"title": moment("sample_frame"),
                     "detail": moment("sample_frame_detail"),
                     "leave": moment("sample_frame_leave")}


def test_a_private_open_carries_no_frame(home: Path, tmp_path: Path):
    """Private vault replies contain no sample frame."""
    answered = json.loads(Sidecar(io.StringIO()).handle(_frame(
        "bridge.open_vault",
        {"vault_directory": str(tmp_path / "mine"), "passphrase": "pw",
         "create": True}))[0])

    assert answered["result"]["sample"] is False
    assert "frame" not in answered["result"]


def test_the_surfaces_it_answers_are_read_through_the_same_dispatch(home: Path):
    sidecar = Sidecar(io.StringIO())
    _open(sidecar)

    read = json.loads(sidecar.handle(_frame(
        "viva.surface.read",
        {"surface": "overview", "job_id": "j", "parameters": {}}))[0])

    assert read["ok"] is True
    assert read["result"]["data"]["state"] == "ready"


# --------------------------------------------------------- fictional content


def test_nothing_in_it_is_anybody_s(home: Path):
    """The sample contains only synthetic institutions and identities."""
    vault, _ = open_demo_vault()
    held = json.dumps(OpenedVaultSurfaceProvider(vault).read_surface("overview", {}))

    assert "Sample" in held
    for real in ("Chase", "Barclays", "HSBC", "Wells Fargo"):
        assert real not in held


def test_a_home_is_this_module_s_to_choose(tmp_path: Path):
    """Only the module API chooses the sample home."""
    assert demo_home(tmp_path).parent == tmp_path
    built = build_demo_vault(tmp_path / "elsewhere")

    assert holds_a_vault(tmp_path / "elsewhere")
    assert list(built.events())
