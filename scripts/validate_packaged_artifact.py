#!/usr/bin/env python3
"""Run a built sidecar the way the application runs it, and say what it did.

Everything else in this repository checks the source tree. This runs the
artifact: it starts the packaged executable as a subprocess, speaks the real
protocol to it over standard input and output, opens a vault through it and
reads every surface an opened vault answers. A build that imports cleanly and
cannot answer a frame is exactly the build a person downloads.

**The vault it opens is the sample one.** It is a real vault the engine mints
in a temporary home, so this exercises the path a person takes rather than a
fixture: no passphrase is passed in, none is printed, and nothing this touches
is anybody's own records. The home is removed on the way out.

**It asserts the build names itself.** A build that cannot say which revision it
is is the one somebody filing a report most needs named, so a handshake that
answers with the word for not knowing fails here rather than reaching a person.

**Nothing here is a substitute for the build having been signed.** This says the
executable runs and answers; whether it was notarised, and by whom, is the
release workflow's own question and is checked there.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, NoReturn

ROOT = Path(__file__).resolve().parents[1]
SIDECAR_NAME = "viva-desktop-bridge"

# The protocol this speaks. Written here rather than imported, because the
# subject is a packaged artifact and importing the product to test the package
# would be asking the source tree what the package does.
PROTOCOL = "2.0"

# The word a build uses for a revision it could not establish. Same reason.
UNKNOWN_REVISION = "unknown"

# What an opened vault must answer. A build that serves four of them is not a
# build a person can use, and a list this walks is the whole of what is
# checked, so a surface added later joins it here.
SURFACES = ("overview", "documents", "conversation", "jobs", "trust", "activity")


def fail(message: str) -> NoReturn:
    raise SystemExit(f"packaged artifact: {message}")


class Sidecar:
    """One packaged executable, spoken to the way the host speaks to it."""

    def __init__(self, executable: Path, home: Path) -> None:
        environment = dict(os.environ)
        # The sample vault goes somewhere this run owns and deletes. Without
        # this it would be minted in the home directory of whoever ran the
        # check, which is a real folder on a real machine.
        environment["VIVA_DEMO_HOME"] = str(home)
        self._process = subprocess.Popen(
            [str(executable)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, env=environment, cwd=str(home))
        self._request = 0

    def ask(self, operation: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """One request, one reply, in the order the transport guarantees.

        A reply that is not a whole JSON line, or that answers a different
        request, is a protocol failure rather than a value to interpret: the
        host would have nothing to render either."""
        self._request += 1
        request_id = f"validate-{self._request}"
        frame = json.dumps({"protocol": PROTOCOL, "request_id": request_id,
                            "operation": operation, "payload": payload or {}})
        assert self._process.stdin is not None and self._process.stdout is not None
        self._process.stdin.write(frame + "\n")
        self._process.stdin.flush()
        while True:
            line = self._process.stdout.readline()
            if not line:
                fail(f"the sidecar stopped answering during {operation}")
            try:
                answered = json.loads(line)
            except json.JSONDecodeError:
                fail(f"the sidecar wrote a line that is not a frame during {operation}")
            # Progress frames carry no request outcome and are not replies.
            if answered.get("event"):
                continue
            if answered.get("request_id") != request_id:
                fail(f"the sidecar answered {answered.get('request_id')!r} to "
                     f"{request_id!r}")
            return answered

    def close(self) -> None:
        if self._process.stdin is not None:
            self._process.stdin.close()
        try:
            self._process.wait(timeout=20)
        except subprocess.TimeoutExpired:
            self._process.kill()


def _result(answered: dict[str, Any], operation: str) -> dict[str, Any]:
    if not answered.get("ok"):
        error = answered.get("error") or {}
        fail(f"{operation} was refused: {error.get('code', 'no code')}")
    result = answered.get("result")
    if not isinstance(result, dict):
        fail(f"{operation} answered with nothing a host could read")
    return result


def validate(executable: Path) -> list[str]:
    """Everything this run establishes about the artifact, in words.

    Returns what it checked rather than printing as it goes, so a run that
    fails half way through has said nothing that reads like a pass."""
    if not executable.is_file():
        fail(f"no such executable: {executable}")
    if not os.access(executable, os.X_OK):
        fail(f"not executable: {executable}")

    home = Path(tempfile.mkdtemp(prefix="orionviva-artifact-"))
    checked: list[str] = []
    sidecar = Sidecar(executable, home)
    try:
        handshake = _result(sidecar.ask("bridge.handshake"), "bridge.handshake")
        if handshake.get("protocol") != PROTOCOL:
            fail(f"the artifact speaks protocol {handshake.get('protocol')!r}")
        revision = str(handshake.get("revision", ""))
        if not revision or revision == UNKNOWN_REVISION:
            fail("the artifact cannot say which revision it is, which is the "
                 "one thing a person filing a report about it needs")
        checked.append(f"answers the handshake, and names itself {revision}")

        lifecycle = _result(sidecar.ask("viva.lifecycle.read"), "viva.lifecycle.read")
        if lifecycle.get("origin") != "packaged":
            fail(f"the artifact reports itself as {lifecycle.get('origin')!r} "
                 "rather than as a packaged build")
        checked.append("reports itself as a packaged build")

        opened = _result(sidecar.ask("bridge.open_demo_vault"), "bridge.open_demo_vault")
        if opened.get("sample") is not True:
            fail("the artifact did not open the sample vault as the sample vault")
        if not (opened.get("frame") or {}).get("title"):
            fail("the artifact opened the sample vault with no frame to draw "
                 "around it, so nothing would say the money in it is invented")
        checked.append("mints and opens the sample vault, with its frame")

        for surface in SURFACES:
            read = _result(sidecar.ask("viva.surface.read", {
                "surface": surface, "job_id": f"validate-{surface}",
                "parameters": {}}), f"viva.surface.read({surface})")
            data = read.get("data")
            if not isinstance(data, dict) or not data.get("state"):
                fail(f"the {surface} read answered with nothing a screen could show")
        checked.append(f"answers every surface an opened vault serves ({len(SURFACES)})")

        refused = sidecar.ask("viva.surface.snapshot")
        if refused.get("ok") is not False:
            fail("the artifact answered an operation nobody declared")
        checked.append("refuses an operation the registry does not declare")
    finally:
        sidecar.close()
        shutil.rmtree(home, ignore_errors=True)
    return checked


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executable", type=Path,
                        help="the packaged sidecar to run; defaults to the "
                             "staged one for this host")
    parser.add_argument("--target", help="Rust target triple, for the default path")
    args = parser.parse_args(argv)

    executable = args.executable
    if executable is None:
        if not args.target:
            fail("name an executable with --executable, or a target triple "
                 "with --target")
        suffix = ".exe" if "windows" in args.target else ""
        executable = (ROOT / "desktop" / "src-tauri" / "binaries"
                      / f"{SIDECAR_NAME}-{args.target}{suffix}")

    for said in validate(executable):
        print(f"packaged artifact: {said}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
