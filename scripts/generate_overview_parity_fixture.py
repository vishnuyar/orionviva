#!/usr/bin/env python3
"""Generate the artifact the backend and the interface are both held to.

The bytes this writes are what the real provider returns for a real vault,
carried through the real bridge dispatch. Nothing in it is authored by hand.

The vault it reads is built here, in code, from the event constructors the
ingest path posts through, and holds eight shapes of account: one that
reconciles, one owed on, one owed on and in credit, one nothing attested and so
carried by no net-worth point, one holding instruments, one whose records
disagree, one in a second currency, and one whose newest record is old. Beside
them it holds a debt a ruling brought into being that no total can carry and no
card shows, a document nothing has read, and a document read and not posted.
Every name and number in it is invented.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import shutil
import sys
import tempfile
from decimal import Decimal
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ARTIFACT = (ROOT / "product" / "viva" / "surface" / "fixtures"
                    / "overview-parity-v1.json")

# The day the fixture is written as of, and the conventions its amounts are
# written under. Both are stated rather than taken from the machine that runs
# this, so the bytes do not depend on where or when it ran.
TODAY = "2026-09-30"
LOCALE = "en-US"

# Every setting the product reads that would otherwise move these bytes, stated
# here and applied for the length of the run. The locale decides how amounts
# are written; the two reader settings decide which sentence the documents read
# says about reading, so a machine with them exported would generate a
# different artifact from the same product. A generator whose output depends on
# whose machine ran it is not a single writer of anything. `None` means the
# setting is removed rather than given a value.
STATED_ENVIRONMENT: dict[str, str | None] = {
    "VIVA_LOCALE": LOCALE,
    "VIVA_MODEL_ADAPTER": None,
    "VIVA_MODEL": None,
}

# The surfaces the artifact holds: every one an opened vault answers. It began
# as the overview and the documents read beside it, because a citation is only
# a route where the document it names is a row a person can open. It is all of
# them now, because this is the sample vault a person opens — so the interface
# suite renders these same bytes rather than a set of rows composed in the
# shell, and a screen that drifts from what the backend sends fails here.
SURFACES = ("overview", "documents", "conversation", "trust", "activity", "plans")

# What each surface is read with. The day the picture is read on is stated here
# rather than left to the machine's clock: a total is good as of the day it was
# asked for, so a read that asked on no stated day would write the day it ran
# into these bytes and disagree with itself tomorrow.
PARAMETERS: dict[str, dict] = {"overview": {"read_on": TODAY},
                               "activity": {"as_of": TODAY},
                               "plans": {"read_on": TODAY}}


def _import_path() -> None:
    for package in ("product", "core", "merchant"):
        path = str(ROOT / package)
        if path not in sys.path:
            sys.path.insert(0, path)


@contextlib.contextmanager
def _stated_environment(settings: dict = STATED_ENVIRONMENT):
    """Run under the settings the fixture declares, whatever the machine's own
    are, and restore the caller's on the way out."""
    before = {name: os.environ.get(name) for name in settings}
    try:
        for name, value in settings.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        yield
    finally:
        for name, value in before.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def build_vault(directory: Path):
    """The fictional vault, built by the module that owns it.

    It is the same vault a person opens when they enter the sample. One
    fictional vault with two readers, rather than a demo and a fixture that
    drift until the artifact stops describing what anybody sees."""
    _import_path()
    from viva.demo import build_demo_vault

    return build_demo_vault(directory)


def read_surfaces(vault) -> dict[str, Any]:
    """Every surface the artifact holds, read the way the desktop reads it.

    The real provider, the real dispatcher and the real frame: what this
    records is what a shell would receive, not what a caller of the composer
    would."""
    _import_path()
    from viva.desktop_bridge import dispatch_frame, handlers_with_surface_provider
    from viva.desktop_bridge.vault_provider import create_vault_surface_provider
    from viva.surface import CURRENT_PROTOCOL

    if not SURFACES:
        raise SystemExit("the artifact declares no surface to read; a byte "
                         "comparison over nothing passes without checking "
                         "anything")
    dispatcher = handlers_with_surface_provider(
        create_vault_surface_provider(vault))
    reads = {}
    for surface in SURFACES:
        frame = json.dumps({
            "protocol": CURRENT_PROTOCOL.wire(),
            "request_id": f"parity-{surface}",
            "operation": "viva.surface.read",
            "payload": {"surface": surface, "job_id": f"parity-{surface}",
                        "parameters": PARAMETERS.get(surface, {})},
        })
        reads[surface] = json.loads(dispatch_frame(frame, dispatcher.handlers))
    return reads


def build_artifact() -> dict[str, Any]:
    """The artifact both languages read, built by running the product.

    Refuses to produce an artifact that holds nothing. A gate whose subject is
    a byte comparison passes over an empty set as readily as over a correct
    one, so the set it walks is checked to be non-empty rather than assumed."""
    _import_path()
    from viva.surface import CURRENT_PROTOCOL

    directory = Path(tempfile.mkdtemp(prefix="orionviva-parity-"))
    try:
        with _stated_environment():
            vault = build_vault(directory / "vault")
            reads = read_surfaces(vault)
    finally:
        shutil.rmtree(directory, ignore_errors=True)
    if not reads or any(not frame.get("ok") for frame in reads.values()):
        raise SystemExit("a surface did not answer; the artifact is not "
                         "written from a failed read")
    return {
        "artifact": "orionviva.overview-parity-v1",
        "protocol": CURRENT_PROTOCOL.wire(),
        "locale": LOCALE,
        "today": TODAY,
        "reads": reads,
    }


def encoded_artifact() -> bytes:
    return (json.dumps(build_artifact(), indent=2, sort_keys=True)
            + "\n").encode("utf-8")


def check_artifact(path: Path = DEFAULT_ARTIFACT) -> None:
    expected = encoded_artifact()
    if not path.exists():
        raise SystemExit(f"overview parity fixture is missing: {path}")
    if path.read_bytes() != expected:
        raise SystemExit(
            "overview parity drift detected; run "
            f"{Path(__file__).name} --write to review the generated update")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true",
                      help="fail when the artifact is stale")
    mode.add_argument("--write", action="store_true",
                      help="write the artifact the product produces")
    parser.add_argument("--artifact", type=Path, default=DEFAULT_ARTIFACT)
    args = parser.parse_args(argv)
    if args.write:
        args.artifact.parent.mkdir(parents=True, exist_ok=True)
        args.artifact.write_bytes(encoded_artifact())
        print(f"wrote {args.artifact}")
    else:
        check_artifact(args.artifact)
        print(f"overview parity fixture is current: {args.artifact}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
