#!/usr/bin/env python3
"""Verify release signatures with host-native tools, without launching the app."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess


def artifact_digest(path: Path) -> str:
    """Bind app bundles to paths, symlink targets and every regular file byte."""
    digest = hashlib.sha256()
    paths = sorted(path.rglob("*")) if path.is_dir() else [path]
    if not paths:
        raise RuntimeError("empty artifact")
    for item in paths:
        relative = str(item.relative_to(path)) if path.is_dir() else item.name
        if item.is_symlink():
            kind, value = "link", os.readlink(item)
        elif item.is_file():
            with item.open("rb") as stream:
                kind, value = "file", hashlib.file_digest(stream, "sha256").hexdigest()
        elif item.is_dir():
            continue
        else:
            raise RuntimeError("unsupported artifact entry")
        digest.update(json.dumps([relative, kind, value], ensure_ascii=True).encode() + b"\n")
    return digest.hexdigest()


def run(command, *, environment=None):
    result = subprocess.run(command, env=environment, capture_output=True, text=True,
                            encoding="utf-8", timeout=120, check=False)
    if result.returncode:
        raise RuntimeError(f"native verification failed: {Path(command[0]).name}")
    return result.stdout + result.stderr


def verify(artifact: Path, expected_identity: str) -> dict:
    artifact = artifact.resolve(strict=True)
    if not expected_identity.strip():
        raise RuntimeError("expected publisher identity is required")
    before = artifact_digest(artifact)
    host = platform.system()
    if host == "Darwin":
        if artifact.suffix.lower() not in {".app", ".dmg"}:
            raise RuntimeError("macOS requires an app bundle or DMG")
        run(["/usr/bin/codesign", "--verify", "--deep", "--strict", "--verbose=2", str(artifact)])
        details = run(["/usr/bin/codesign", "--display", "--verbose=4", str(artifact)])
        teams = [line.split("=", 1)[1].strip() for line in details.splitlines()
                 if line.startswith("TeamIdentifier=")]
        if teams != [expected_identity]:
            raise RuntimeError("macOS signing team did not match expected publisher")
        assessment = (["--type", "open", "--context", "context:primary-signature"]
                      if artifact.suffix.lower() == ".dmg" else ["--type", "execute"])
        run(["/usr/sbin/spctl", "--assess", "--verbose=2", *assessment, str(artifact)])
        run(["/usr/bin/xcrun", "stapler", "validate", str(artifact)])
        checks = ["codesign-strict", "expected-team", "gatekeeper-assessment", "stapled-notarization"]
    elif host == "Windows":
        if artifact.suffix.lower() not in {".exe", ".msi"}:
            raise RuntimeError("Windows requires an EXE or MSI")
        # Paths travel as environment data, never interpolated PowerShell source.
        environment = dict(os.environ, ORIONVIVA_SIGNATURE_ARTIFACT=str(artifact))
        output = run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
                      "$ErrorActionPreference='Stop'; $s=Get-AuthenticodeSignature -LiteralPath $env:ORIONVIVA_SIGNATURE_ARTIFACT; "
                      "@{status=$s.Status.ToString(); thumbprint=$s.SignerCertificate.Thumbprint} | ConvertTo-Json -Compress"],
                     environment=environment)
        result = json.loads(output)
        expected = "".join(expected_identity.split()).upper()
        if result.get("status") != "Valid" or result.get("thumbprint", "").upper() != expected:
            raise RuntimeError("Windows signature or expected publisher did not validate")
        checks = ["authenticode-valid", "expected-certificate-thumbprint"]
    else:
        raise RuntimeError("no native publisher signature policy is configured for this host")
    if artifact_digest(artifact) != before:
        raise RuntimeError("artifact changed during native verification")
    return dict(schema="native-signature-v1", status="passed", host=host,
                artifact_digest=before, digest_scheme="path-kind-content-sha256-v1",
                artifact_name=artifact.name, expected_identity=expected_identity,
                checks=checks, scope="signature verification; no installation or UI launch")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--expected-identity", required=True,
                        help="Apple Team ID or Windows signing certificate thumbprint")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    artifact, output = args.artifact.resolve(), args.output.resolve()
    if output == artifact or output.is_relative_to(artifact):
        parser.error("output must not overwrite or be inside the input artifact")
    args.output.unlink(missing_ok=True)
    report = verify(args.artifact, args.expected_identity)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print("native signature: passed; installation and native interaction remain separate checks")


if __name__ == "__main__":
    main()
