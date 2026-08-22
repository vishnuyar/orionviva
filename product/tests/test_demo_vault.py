"""The sample vault a person opens, and where it lives.

The demo used to be told sentence by sentence: a qualifier beside each figure,
in an interface that had a second dialect for rendering them. What is here is a
vault — minted by the engine, opened through the sidecar, read by the same
provider — which is what lets one frame around the whole place be true by
construction and the per-sentence qualifiers retire.
"""

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


# ------------------------------------------------------- a vault, not a fixture


def test_the_sample_is_a_vault_the_engine_opens(home: Path):
    vault, made = open_demo_vault()

    assert made is True
    assert holds_a_vault(home)
    assert Vault.open(home, DEMO_PASSPHRASE, create=False) is not None


def test_it_is_minted_once_and_stays(home: Path):
    """A vault made fresh each launch loses whatever a person did inside it, and
    a demo somebody cannot change is a screenshot."""
    first, made_first = open_demo_vault()
    events = len(list(first.events()))

    second, made_second = open_demo_vault()

    assert made_first is True
    assert made_second is False
    assert len(list(second.events())) == events


def test_every_surface_an_opened_vault_answers_has_something_to_show(home: Path):
    """A demo is every screen. One that answered on two of them would send a
    person to a screen that says nothing and let them read that as the
    product."""
    vault, _ = open_demo_vault()
    provider = OpenedVaultSurfaceProvider(vault)

    for surface in sorted(OpenedVaultSurfaceProvider._SURFACES - {"jobs"}):
        read = provider.read_surface(surface, {})
        assert read["state"] == "ready", surface
        json.dumps(read, allow_nan=False)


def test_the_states_the_other_screens_can_be_in_are_reachable(home: Path):
    vault, _ = open_demo_vault()
    provider = OpenedVaultSurfaceProvider(vault)

    review = provider.read_surface("review", {})
    activity = provider.read_surface("activity", {})
    trust = provider.read_surface("trust", {})

    # Questions of more than one kind, so the queue is not one shape repeated.
    assert len({question["kind"] for question in review["questions"]}) > 1
    # A question that wants an answer out of a closed vocabulary.
    assert any(slot.get("choices") for question in review["questions"]
               for slot in question["slots"])
    # Money between a person's own pockets, which is the one row on the
    # activity screen that is not what its sign says it is.
    assert any(item["linked"] for item in activity["items"])
    assert {item["direction"] for item in activity["items"]} == {"in", "out"}
    # Something has been sent, so the outbound record is a record rather than
    # an absence, and something has run, so Trust is not only absences.
    assert trust["outbound"]["call_count"] > 0
    assert [absence["id"] for absence in trust["absences"]] == ["anchoring"]


def test_every_document_is_named_the_way_a_person_would_recognise_it(home: Path):
    """Eight rows called `bank_statement.txt` is a list nobody can tell apart,
    and a demo that shows the documents screen working worse than it does."""
    vault, _ = open_demo_vault()

    read = OpenedVaultSurfaceProvider(vault).read_surface("documents", {})
    names = [row["filename"] for row in read["documents"]]

    assert len(set(names)) == len(names)


# ---------------------------------------------- opened through the real sidecar


def test_the_sidecar_opens_it_from_a_request_that_names_nothing(home: Path):
    """Where the sample vault lives and what opens it are the engine's. A caller
    has nowhere to point this at a folder they keep their own records in, and
    nowhere to learn what would open it."""
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
    """The one sentence in this product that says nothing here is real is a
    shipped sentence. A shell composing its own would put it out of the pack's
    reach."""
    frame = _open(Sidecar(io.StringIO()))["result"]["frame"]

    assert frame == {"title": moment("sample_frame"),
                     "detail": moment("sample_frame_detail"),
                     "leave": moment("sample_frame_leave")}


def test_a_private_open_carries_no_frame(home: Path, tmp_path: Path):
    """A frame drawn around a person's own records would tell them their money
    was invented."""
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


# --------------------------------------------------------- nothing here is real


def test_nothing_in_it_is_anybody_s(home: Path):
    """Every institution, holder and amount is invented, and the names are
    self-evidently so."""
    vault, _ = open_demo_vault()
    held = json.dumps(OpenedVaultSurfaceProvider(vault).read_surface("overview", {}))

    assert "Sample" in held
    for real in ("Chase", "Barclays", "HSBC", "Wells Fargo"):
        assert real not in held


def test_a_home_is_this_module_s_to_choose(tmp_path: Path):
    """A caller choosing where the demo goes is a caller who can point it at a
    real vault."""
    assert demo_home(tmp_path).parent == tmp_path
    built = build_demo_vault(tmp_path / "elsewhere")

    assert holds_a_vault(tmp_path / "elsewhere")
    assert list(built.events())
