#!/usr/bin/env python3
"""Validate native release inputs and generate the Tauri release override."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, NoReturn
from urllib.parse import urlparse

try:
    import tomllib
except ModuleNotFoundError:
    raise SystemExit("native release: Python 3.11 or newer is required") from None


ROOT = Path(__file__).resolve().parents[1]
DESKTOP = ROOT / "desktop"
TAURI_ROOT = DESKTOP / "src-tauri"
TAURI_CONFIG = TAURI_ROOT / "tauri.conf.json"
PACKAGE_CONFIG = DESKTOP / "package.json"
CARGO_CONFIG = TAURI_ROOT / "Cargo.toml"
TARGETS_CONFIG = TAURI_ROOT / "release-targets.json"
DEFAULT_OUTPUT = TAURI_ROOT / "tauri.release.generated.json"
SIDECAR_NAME = "viva-desktop-bridge"
VERSION_PATTERN = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?$")


def fail(message: str) -> NoReturn:
    raise SystemExit(f"native release: {message}")


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        fail(f"cannot read {path.relative_to(ROOT)}: {error}")
    if not isinstance(value, dict):
        fail(f"{path.relative_to(ROOT)} must contain a JSON object")
    return value


def read_cargo_version() -> str:
    try:
        value = tomllib.loads(CARGO_CONFIG.read_text(encoding="utf-8"))
        version = value["package"]["version"]
    except (OSError, tomllib.TOMLDecodeError, KeyError, TypeError) as error:
        fail(f"cannot read desktop/src-tauri/Cargo.toml package version: {error}")
    if not isinstance(version, str):
        fail("desktop/src-tauri/Cargo.toml package version must be a string")
    return version


def validate_versions() -> str:
    versions = {
        "desktop/package.json": read_json(PACKAGE_CONFIG).get("version"),
        "desktop/src-tauri/tauri.conf.json": read_json(TAURI_CONFIG).get("version"),
        "desktop/src-tauri/Cargo.toml": read_cargo_version(),
    }
    if any(not isinstance(version, str) for version in versions.values()):
        fail("all desktop package metadata files must declare a string version")
    distinct = set(versions.values())
    if len(distinct) != 1:
        detail = ", ".join(f"{path}={version}" for path, version in versions.items())
        fail(f"desktop versions are not synchronized: {detail}")
    version = next(iter(distinct))
    if not VERSION_PATTERN.fullmatch(version):
        fail(f"desktop version is not release-compatible: {version}")
    return version


def load_targets() -> dict[str, dict[str, str]]:
    entries = read_json(TARGETS_CONFIG).get("include")
    if not isinstance(entries, list) or not entries:
        fail("desktop/src-tauri/release-targets.json must contain a non-empty include list")

    targets: dict[str, dict[str, str]] = {}
    required = {"name", "runner", "platform", "target", "bundles"}
    supported_platforms = {"linux", "windows", "macos"}
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict) or not required.issubset(entry):
            fail(f"release target entry {index} is missing required string fields")
        if any(not isinstance(entry[key], str) or not entry[key] for key in required):
            fail(f"release target entry {index} contains an empty or non-string field")
        target = entry["target"]
        if target in targets:
            fail(f"duplicate release target: {target}")
        if entry["platform"] not in supported_platforms:
            fail(f"unsupported release platform: {entry['platform']}")
        targets[target] = {key: entry[key] for key in required}
    return targets


def required_environment(names: list[str]) -> dict[str, str]:
    values = {name: os.environ.get(name, "").strip() for name in names}
    missing = [name for name, value in values.items() if not value]
    if missing:
        fail(f"missing required release environment: {', '.join(missing)}")
    return values


def validate_https_url(name: str, endpoint: str) -> None:
    parsed = urlparse(endpoint)
    if parsed.scheme != "https" or not parsed.netloc:
        fail(f"{name} must be an absolute HTTPS URL")
    if parsed.username or parsed.password or parsed.fragment:
        fail(f"{name} cannot contain credentials or a fragment")


def normalize_windows_thumbprint(value: str) -> str:
    thumbprint = re.sub(r"\s+", "", value).upper()
    if not re.fullmatch(r"[0-9A-F]{40}", thumbprint):
        fail("ORIONVIVA_WINDOWS_CERTIFICATE_THUMBPRINT must be a 40-digit SHA-1 thumbprint")
    return thumbprint


def validate_tag(version: str) -> None:
    tag = os.environ.get("ORIONVIVA_RELEASE_TAG", "").strip()
    if tag and tag != f"desktop-v{version}":
        fail(f"release tag {tag!r} does not match desktop-v{version}")


def sidecar_path(target: str) -> Path:
    suffix = ".exe" if "windows" in target else ""
    return TAURI_ROOT / "binaries" / f"{SIDECAR_NAME}-{target}{suffix}"


# What names an update channel, on each side of the application. The left half
# is what would let an installed copy read one; the right half is what would
# publish one. This is a list rather than a search for the word "update",
# because the word appears in prose and these are the declarations that decide.
UPDATER_CRATES = ("tauri-plugin-updater",)
UPDATER_CONFIG_KEYS = ("updater", "createUpdaterArtifacts", "pubkey")


def _updater_declarations() -> tuple[list[str], list[str]]:
    """What this build declares about an update channel, on each side.

    Returns what would let an installed copy read one, and what would publish
    one. Read rather than assumed: the day somebody adds either, this says so
    instead of the release quietly acquiring half a channel."""
    cargo = CARGO_CONFIG.read_text(encoding="utf-8")
    readable = [crate for crate in UPDATER_CRATES if crate in cargo]
    configured = json.dumps(read_json(TAURI_CONFIG))
    published = [key for key in UPDATER_CONFIG_KEYS if f'"{key}"' in configured]
    return readable, published


def validate_update_channel() -> None:
    """Ship installers, or ship an updater; never the signature of one without
    the other.

    A signed update manifest beside installers no copy can read would advertise
    a channel that does not exist — a promise on the release page the binary
    cannot keep. And an updater compiled in with nothing published would have
    an installed copy asking a channel nobody publishes.

    This is also the pair that keeps the sentence a person reads true: the
    lifecycle read tells them this copy does not check for updates and cannot
    install one, and that sentence stops being true the moment either half of
    this appears. So it fails here rather than there."""
    readable, published = _updater_declarations()
    if readable and not published:
        fail("an updater plugin is compiled in but nothing publishes a channel: "
             + ", ".join(readable))
    if published and not readable:
        fail("an update channel would be published that no installed copy can "
             "read: " + ", ".join(published))
    if readable and published:
        fail("this build declares an update channel, and the sentence the "
             "product shows a person says there is none; change both or "
             "neither: " + ", ".join(readable + published))


def release_override(platform: str, values: dict[str, str]) -> dict[str, Any]:
    # No updater artifacts, and `validate_update_channel` is what holds it:
    # the application has no updater plugin compiled into it, so a signed
    # `latest.json` beside the installers would advertise a channel that no
    # installed copy can read.
    bundle: dict[str, Any] = {}
    if platform == "windows":
        bundle["windows"] = {
            "certificateThumbprint": values["ORIONVIVA_WINDOWS_CERTIFICATE_THUMBPRINT"],
            "digestAlgorithm": "sha256",
            "timestampUrl": values["ORIONVIVA_WINDOWS_TIMESTAMP_URL"],
        }
    return {"bundle": bundle}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", help="Rust target triple from release-targets.json")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--metadata-only", action="store_true")
    parser.add_argument("--check-sidecar", action="store_true")
    args = parser.parse_args()

    version = validate_versions()
    targets = load_targets()
    validate_tag(version)
    validate_update_channel()

    if args.metadata_only:
        print(f"native release: metadata valid for {version} ({len(targets)} targets), "
              "and no update channel is declared on either side")
        return 0
    if not args.target:
        fail("--target is required unless --metadata-only is used")
    if args.target not in targets:
        fail(f"unsupported target {args.target!r}; expected one of {', '.join(sorted(targets))}")

    target = targets[args.target]
    common = required_environment(
        [
            "TAURI_SIGNING_PRIVATE_KEY",
        ]
    )

    platform_values: dict[str, str] = {}
    if target["platform"] == "macos":
        platform_values = required_environment(
            [
                "APPLE_CERTIFICATE",
                "APPLE_CERTIFICATE_PASSWORD",
                "APPLE_KEYCHAIN_PASSWORD",
                "APPLE_ID",
                "APPLE_PASSWORD",
                "APPLE_TEAM_ID",
            ]
        )
    elif target["platform"] == "windows":
        platform_values = required_environment(
            [
                "WINDOWS_CERTIFICATE",
                "WINDOWS_CERTIFICATE_PASSWORD",
                "ORIONVIVA_WINDOWS_CERTIFICATE_THUMBPRINT",
                "ORIONVIVA_WINDOWS_TIMESTAMP_URL",
            ]
        )
        validate_https_url(
            "ORIONVIVA_WINDOWS_TIMESTAMP_URL",
            platform_values["ORIONVIVA_WINDOWS_TIMESTAMP_URL"],
        )
        platform_values["ORIONVIVA_WINDOWS_CERTIFICATE_THUMBPRINT"] = (
            normalize_windows_thumbprint(
                platform_values["ORIONVIVA_WINDOWS_CERTIFICATE_THUMBPRINT"]
            )
        )

    if args.check_sidecar and not sidecar_path(args.target).is_file():
        fail(f"staged sidecar is missing: {sidecar_path(args.target).relative_to(ROOT)}")

    output = args.output.resolve()
    if output != DEFAULT_OUTPUT.resolve() and ROOT not in output.parents:
        fail("release override output must stay inside the repository")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(release_override(target["platform"], common | platform_values), indent=2)
        + "\n",
        encoding="utf-8",
    )
    print(
        f"native release: prepared {target['name']} for {version} at "
        f"{output.relative_to(ROOT)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
