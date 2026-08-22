"""The check that runs the artifact, checked against artifacts that misbehave.

Everything else in this repository checks the source tree. `validate_packaged_
artifact` runs the built executable and speaks the real protocol to it, which is
the one thing a source-tree check cannot do — and which means the check itself
has to be checked, because a validator that passes over a broken build is worse
than no validator.

So each test here builds a stand-in executable that speaks the protocol badly in
exactly one way, and asserts the validator says so. The stand-ins are Python
scripts rather than packaged binaries: what is under test is the validator's
reading of a conversation, and a conversation is the same over either.
"""

from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import validate_packaged_artifact as checker  # noqa: E402

GOOD_FRAME = {"title": "a frame", "detail": "a detail", "leave": "a way out"}


def _stand_in(tmp_path: Path, replies: dict, name: str = "sidecar") -> Path:
    """One executable that answers each operation with what it is given.

    A whole executable rather than a mock, because what is under test is a
    validator that starts a process and reads its output: a mock would test the
    validator against an object it will never meet."""
    script = tmp_path / name
    script.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys\n"
        f"replies = json.loads({json.dumps(json.dumps(replies))})\n"
        "for line in sys.stdin:\n"
        "    if not line.strip():\n"
        "        continue\n"
        "    asked = json.loads(line)\n"
        "    said = replies.get(asked['operation'], replies.get('*'))\n"
        "    if said is None:\n"
        "        said = {'ok': False, 'error': {'code': 'operation_not_allowed'}}\n"
        "    said = dict(said)\n"
        "    said.setdefault('protocol', '2.0')\n"
        "    said['request_id'] = asked['request_id']\n"
        "    sys.stdout.write(json.dumps(said) + '\\n')\n"
        "    sys.stdout.flush()\n",
        encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return script


def _working(**overrides) -> dict:
    replies = {
        "bridge.handshake": {"ok": True, "result": {
            "protocol": "2.0", "transport": "json-lines", "revision": "abcdef123456"}},
        "viva.lifecycle.read": {"ok": True, "result": {
            "state": "absent", "origin": "packaged", "revision": "abcdef123456"}},
        "bridge.open_demo_vault": {"ok": True, "result": {
            "state": "opened", "sample": True, "frame": GOOD_FRAME}},
        "viva.surface.read": {"ok": True, "result": {
            "surface": "overview", "job_id": "j", "data": {"state": "ready"}}},
    }
    replies.update(overrides)
    return replies


def _run(tmp_path: Path, replies: dict) -> list[str]:
    return checker.validate(_stand_in(tmp_path, replies))


# --------------------------------------------------- an artifact that answers


def test_a_build_that_answers_everything_is_reported_in_words(tmp_path: Path):
    said = _run(tmp_path, _working())

    assert any("names itself abcdef123456" in line for line in said)
    assert any("packaged build" in line for line in said)
    assert any("sample vault" in line for line in said)
    assert any("every surface" in line for line in said)


def test_the_sample_vault_is_minted_where_this_run_owns_it(tmp_path: Path, monkeypatch):
    """A validator that minted the sample vault in the home directory of
    whoever ran it would leave a real folder on a real machine."""
    seen: list[str] = []
    real = checker.subprocess.Popen

    def watched(*args, **kwargs):
        seen.append(kwargs["env"]["VIVA_DEMO_HOME"])
        return real(*args, **kwargs)

    monkeypatch.setattr(checker.subprocess, "Popen", watched)
    _run(tmp_path, _working())

    assert seen and not Path(seen[0]).exists()
    assert str(Path.home()) not in seen[0]


# ----------------------------------------------- each way a build can be wrong


def test_a_build_that_cannot_name_itself_fails(tmp_path: Path):
    """The build somebody is filing a report about is the one that most needs
    naming."""
    replies = _working(**{"bridge.handshake": {"ok": True, "result": {
        "protocol": "2.0", "transport": "json-lines", "revision": "unknown"}}})

    with pytest.raises(SystemExit, match="which revision it is"):
        _run(tmp_path, replies)


def test_a_build_that_says_it_is_a_source_tree_fails(tmp_path: Path):
    """A packaged artifact reporting itself as a checkout means the packaging
    step did not write its revision, so the installed copy would say the wrong
    thing about itself for the rest of its life."""
    replies = _working(**{"viva.lifecycle.read": {"ok": True, "result": {
        "state": "absent", "origin": "source"}}})

    with pytest.raises(SystemExit, match="rather than as a packaged build"):
        _run(tmp_path, replies)


def test_a_build_that_speaks_another_protocol_fails(tmp_path: Path):
    replies = _working(**{"bridge.handshake": {"ok": True, "result": {
        "protocol": "3.0", "revision": "abcdef123456"}}})

    with pytest.raises(SystemExit, match="speaks protocol"):
        _run(tmp_path, replies)


def test_a_sample_vault_that_opens_without_its_frame_fails(tmp_path: Path):
    """Nothing would say the money in it is invented."""
    replies = _working(**{"bridge.open_demo_vault": {"ok": True, "result": {
        "state": "opened", "sample": True}}})

    with pytest.raises(SystemExit, match="no frame"):
        _run(tmp_path, replies)


def test_a_build_that_opens_a_private_vault_instead_fails(tmp_path: Path):
    replies = _working(**{"bridge.open_demo_vault": {"ok": True, "result": {
        "state": "opened", "sample": False, "frame": GOOD_FRAME}}})

    with pytest.raises(SystemExit, match="as the sample vault"):
        _run(tmp_path, replies)


def test_a_surface_that_answers_with_nothing_fails(tmp_path: Path):
    replies = _working(**{"viva.surface.read": {"ok": True, "result": {
        "surface": "overview", "job_id": "j", "data": {}}}})

    with pytest.raises(SystemExit, match="nothing a screen could show"):
        _run(tmp_path, replies)


def test_a_build_that_answers_an_undeclared_operation_fails(tmp_path: Path):
    """An allowlist that answers everything is not an allowlist."""
    replies = _working(**{"*": {"ok": True, "result": {"anything": True}}})

    with pytest.raises(SystemExit, match="nobody declared"):
        _run(tmp_path, replies)


def test_a_build_that_stops_answering_fails_rather_than_hanging(tmp_path: Path):
    script = tmp_path / "silent"
    script.write_text("#!/usr/bin/env python3\nimport sys\nsys.exit(0)\n", encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IXUSR)

    with pytest.raises(SystemExit, match="stopped answering"):
        checker.validate(script)


def test_a_build_that_writes_something_that_is_not_a_frame_fails(tmp_path: Path):
    script = tmp_path / "chatty"
    script.write_text("#!/usr/bin/env python3\n"
                      "import sys\n"
                      "for line in sys.stdin:\n"
                      "    sys.stdout.write('not a frame\\n')\n"
                      "    sys.stdout.flush()\n", encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IXUSR)

    with pytest.raises(SystemExit, match="not a frame"):
        checker.validate(script)


def test_a_file_that_is_not_executable_fails_before_anything_runs(tmp_path: Path):
    plain = tmp_path / "plain"
    plain.write_text("", encoding="utf-8")
    plain.chmod(plain.stat().st_mode & ~stat.S_IXUSR & ~stat.S_IXGRP & ~stat.S_IXOTH)

    with pytest.raises(SystemExit, match="not executable"):
        checker.validate(plain)

    with pytest.raises(SystemExit, match="no such executable"):
        checker.validate(tmp_path / "absent")


# --------------------------------------- what it walks is what it is checking


def test_every_surface_an_opened_vault_serves_is_walked():
    """A surface added to the provider and not here would be a screen this
    check reports as working without ever having asked it anything."""
    from viva.desktop_bridge.vault_surface import OpenedVaultSurfaceProvider

    assert set(checker.SURFACES) == OpenedVaultSurfaceProvider._SURFACES
