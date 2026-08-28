#!/usr/bin/env python3
"""Generate and check the reviewed ``viva.surface`` contract artifact."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import fields
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ARTIFACT = ROOT / "product" / "viva" / "surface" / "fixtures" / "surface-v1.json"


def _surface_import_path(root: Path) -> None:
    product = root / "product"
    if str(product) not in sys.path:
        sys.path.insert(0, str(product))


def build_artifact(root: Path = ROOT) -> dict[str, Any]:
    """Build a JSON-safe, stable projection of the Python surface contract."""
    _surface_import_path(root)
    from viva.surface import CURRENT_PROTOCOL, capabilities
    from viva.surface.models import (ActionOutcome, FindingView, FigureView,
                                     ObligationView, PanelState, ProofEmphasis,
                                     ProofPresentation, ProofReason)

    registry = []
    fixtures = []
    for capability in sorted(capabilities(), key=lambda item: item.id):
        registry.append({
            "id": capability.id,
            "owner": capability.owner,
            "maturity": capability.maturity.value,
            "disposition": capability.disposition.value,
            "destination": capability.destination.value,
            "availability": capability.availability,
            "contract": capability.contract,
            "actions": list(capability.actions),
            "trust_effect": [effect.value for effect in capability.trust_effect],
            "reason": capability.reason,
            "entrypoint": capability.entrypoint,
            "fixture_ids": list(capability.fixture_ids),
        })
        for fixture_id in capability.fixture_ids:
            fixtures.append({
                "id": fixture_id,
                "capability_id": capability.id,
                "contract": capability.contract,
                "state": "ready",
                "payload": {"capability_id": capability.id, "contract": capability.contract},
            })

    def dataclass_fields(model: type[Any]) -> list[str]:
        return [field.name for field in fields(model)]

    return {
        "artifact": "orionviva.surface-v1",
        "protocol": CURRENT_PROTOCOL.wire(),
        "registry": registry,
        "fixtures": fixtures,
        "models": {
            "FigureView": dataclass_fields(FigureView),
            "ObligationView": dataclass_fields(ObligationView),
            "FindingView": dataclass_fields(FindingView),
            "ProofPresentation": dataclass_fields(ProofPresentation),
            "ProofEmphasis": [emphasis.value for emphasis in ProofEmphasis],
            "ProofReason": [reason.value for reason in ProofReason],
            "PanelState": [state.value for state in PanelState],
            "ActionOutcome": dataclass_fields(ActionOutcome),
        },
    }


def encoded_artifact(root: Path = ROOT) -> bytes:
    return (json.dumps(build_artifact(root), indent=2, sort_keys=True) + "\n").encode("utf-8")


def check_artifact(path: Path = DEFAULT_ARTIFACT, root: Path = ROOT) -> None:
    expected = encoded_artifact(root)
    if not path.exists():
        raise SystemExit(f"surface contract fixture is missing: {path}")
    actual = path.read_bytes()
    if actual != expected:
        raise SystemExit(
            "surface contract drift detected; run "
            f"{Path(__file__).name} --write to review the generated update"
        )
    parsed = json.loads(actual)
    if parsed != build_artifact(root):
        raise SystemExit("surface contract fixture is not valid JSON for the current registry")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="fail when the artifact is stale")
    mode.add_argument("--write", action="store_true", help="write the deterministic artifact")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--artifact", type=Path, default=None)
    args = parser.parse_args(argv)
    root = args.root.resolve()
    artifact = (args.artifact or (root / "product/viva/surface/fixtures/surface-v1.json")).resolve()
    if args.write:
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_bytes(encoded_artifact(root))
        print(f"wrote {artifact}")
    else:
        check_artifact(artifact, root)
        print(f"surface contract is current: {artifact}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
