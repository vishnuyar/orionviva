"""What this application says about being updated, and about being recovered.

There is no update channel. The whole of this item is saying that in a way a
person can act on, rather than leaving a screen to imply a channel by having a
section about one — and making the packaging step fail on the day either half of
a channel appears, so the sentence stops being shown before it stops being true.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import prepare_native_release as release  # noqa: E402
import viva.revision as revision  # noqa: E402

from viva.desktop_bridge.handlers import default_handlers
from viva.desktop_bridge.rpc import dispatch_frame
from viva.persona import moment
from viva.revision import UNKNOWN
from viva.surface import LIFECYCLE_READ
from viva.surface.lifecycle import PACKAGED, SOURCE, UNESTABLISHED, lifecycle, origin_of


def _read(payload: dict | None = None) -> dict:
    frame = json.dumps({"protocol": "2.0", "request_id": "r",
                        "operation": LIFECYCLE_READ, "payload": payload or {}})
    return json.loads(dispatch_frame(frame, default_handlers().handlers))


# ------------------------------------------------------ there is no channel


def test_the_read_says_there_is_no_channel_rather_than_reporting_a_state():
    """A screen with an update section implies a channel. This is `absent`
    because there is nothing to be ready about: nothing here asks whether a
    newer version exists, and nothing here could install one."""
    read = lifecycle("abcdef123456", written=True)

    assert read["state"] == "absent"
    assert read["sentence"] == moment("update_no_channel")


def test_it_says_what_an_update_does_to_a_vault_before_what_it_does_to_the_app():
    """The one thing a person actually needs is that their records are not
    inside the thing being replaced."""
    read = lifecycle("abcdef123456", written=True)
    ids = [note["id"] for note in read["notes"]]

    assert ids == ["vault_untouched", "recovery"]
    assert read["notes"][0]["sentence"] == moment("update_vault_untouched")


def test_recovery_is_an_instruction_rather_than_a_status():
    """"Recovery available" is a claim about machinery. What to do when a
    version will not start is something a person can act on."""
    read = lifecycle("abcdef123456", written=True)

    assert read["notes"][1]["sentence"] == moment("update_recovery")


# ------------------------------------------------- how this copy got here


def test_a_build_that_wrote_its_revision_down_was_packaged():
    """Writing a revision beside the package is the one thing only a packaging
    step does."""
    assert origin_of("abcdef123456", written=True) == PACKAGED
    assert lifecycle("abcdef123456", True)["origin_sentence"] == moment("update_installed_build")


def test_a_packaged_dirty_tree_keeps_its_honest_revision_mark(tmp_path, monkeypatch):
    monkeypatch.setattr(revision, "_package_root", lambda: tmp_path)
    (tmp_path / revision.REVISION_FILE).write_text(
        "abcdef123456+changes\n", encoding="utf-8")

    assert revision.source_revision() == "abcdef123456+changes"


def test_a_build_answering_out_of_a_tree_was_not_packaged():
    assert origin_of("abcdef123456", written=False) == SOURCE
    assert lifecycle("abcdef123456", False)["origin_sentence"] == moment("update_source_build")


def test_a_build_that_can_establish_neither_says_so_rather_than_guessing():
    """It is not a missing field: a field that vanishes reads like one nobody
    thought to send."""
    assert origin_of(UNKNOWN, written=False) == UNESTABLISHED
    assert origin_of(UNKNOWN, written=True) == UNESTABLISHED
    assert lifecycle(UNKNOWN, False)["origin_sentence"] == moment("update_unknown_build")


def test_every_origin_has_a_sentence_and_no_origin_has_two():
    from viva.surface.lifecycle import ORIGINS

    assert set(ORIGINS) == {PACKAGED, SOURCE, UNESTABLISHED}
    assert len(set(ORIGINS.values())) == len(ORIGINS)


# ----------------------------------------------------- asked without a vault


def test_it_is_answered_before_any_vault_is_open():
    """A person meets this question before they have opened anything, and the
    answer does not depend on what they open."""
    answered = _read()

    assert answered["ok"] is True
    assert answered["result"]["sentence"] == moment("update_no_channel")


def test_it_accepts_no_fields():
    """What it reports is a fact about this process, so there is nothing a
    caller could name."""
    answered = _read({"channel": "beta"})

    assert answered["ok"] is False
    assert answered["error"]["code"] == "invalid_request"


def test_the_whole_read_is_json_safe():
    json.dumps(lifecycle("abcdef123456", True), allow_nan=False)


# ------------------------------------ the packaging step holds the sentence


def test_shipping_half_a_channel_fails_the_release(monkeypatch, tmp_path: Path):
    """A signed update manifest beside installers no copy can read advertises a
    channel that does not exist; an updater compiled in with nothing published
    asks a channel nobody publishes. Neither is shippable."""
    monkeypatch.setattr(release, "_updater_declarations",
                        lambda: (["tauri-plugin-updater"], []))
    with pytest.raises(SystemExit, match="nothing publishes a channel"):
        release.validate_update_channel()

    monkeypatch.setattr(release, "_updater_declarations",
                        lambda: ([], ["createUpdaterArtifacts"]))
    with pytest.raises(SystemExit, match="no installed copy can read"):
        release.validate_update_channel()


def test_shipping_a_whole_channel_fails_too_while_the_sentence_says_there_is_none():
    """The sentence a person reads and the release configuration are one fact.
    A build that acquired a channel would show them a sentence saying it had
    not, so the release fails until both are changed."""
    import unittest.mock as mock

    with mock.patch.object(release, "_updater_declarations",
                           lambda: (["tauri-plugin-updater"], ["pubkey"])):
        with pytest.raises(SystemExit, match="change both or neither"):
            release.validate_update_channel()


def test_this_build_declares_no_channel_on_either_side():
    """Read off the real configuration, so the day somebody adds either half
    this says so."""
    readable, published = release._updater_declarations()

    assert readable == []
    assert published == []
    release.validate_update_channel()
