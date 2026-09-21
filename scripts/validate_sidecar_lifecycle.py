#!/usr/bin/env python3
"""Check packaged-sidecar replacement and removal against a synthetic vault.

This is not an OS installer, signature, native UI, or uninstall verification.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import tempfile
import threading

PROTOCOL = "2.1"
SAMPLE_PASSPHRASE = "a-sample-vault-anybody-may-open"


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def snapshot(root: Path, *, canonical: bool = False) -> dict[str, str]:
    paths = ([root / "events.jsonl", root / "events.jsonl.head",
              *sorted((root / "raw").rglob("*"))] if canonical
             else sorted(root.rglob("*")))
    result = {path.relative_to(root).as_posix(): digest(path)
              for path in paths if path.is_file()}
    if not result or (canonical and ("events.jsonl" not in result or "events.jsonl.head" not in result or
                                    not any(name.startswith("raw/") for name in result))):
        raise RuntimeError("synthetic vault is missing canonical evidence")
    return result


def isolated_environment(home: Path) -> dict[str, str]:
    """Supply OS loader essentials; omit model keys, proxies and user config."""
    allowed = {"SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT"}
    env = {key: value for key, value in os.environ.items() if key.upper() in allowed}
    for name in ("config", "cache", "data", "temp"):
        (home / name).mkdir(parents=True, exist_ok=True)
    dotenv = home / "empty.env"
    dotenv.write_text("", encoding="utf-8")
    env.update(HOME=str(home), USERPROFILE=str(home),
               APPDATA=str(home / "config"), LOCALAPPDATA=str(home / "data"),
               XDG_CONFIG_HOME=str(home / "config"), XDG_CACHE_HOME=str(home / "cache"),
               XDG_DATA_HOME=str(home / "data"), TMP=str(home / "temp"),
               TEMP=str(home / "temp"), TMPDIR=str(home / "temp"),
               VIVA_ENV_FILE=str(dotenv), VIVA_DEMO_HOME=str(home / "vault"),
               LANG="en_US.UTF-8")
    return env


class Session:
    """Bound each reply and shut down only the subprocess this session owns."""
    def __init__(self, executable: Path, home: Path, timeout: float = 90):
        self.timeout = timeout
        self.frames: queue.Queue = queue.Queue()
        self.number = 0
        self.process = subprocess.Popen(
            [str(executable)], cwd=home, env=isolated_environment(home),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, encoding="utf-8")
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()

    def _read(self):
        try:
            for line in self.process.stdout:
                self.frames.put(line)
        finally:
            self.frames.put(None)

    def ask(self, operation: str, payload: dict | None = None) -> dict:
        import time
        self.number += 1
        request_id = f"lifecycle-{self.number}"
        self.process.stdin.write(json.dumps(dict(protocol=PROTOCOL, request_id=request_id,
                                                 operation=operation, payload=payload or {})) + "\n")
        self.process.stdin.flush()
        deadline = time.monotonic() + self.timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RuntimeError(f"timed out during {operation}")
            try:
                line = self.frames.get(timeout=remaining)
            except queue.Empty:
                raise RuntimeError(f"timed out during {operation}") from None
            if line is None:
                raise RuntimeError(f"sidecar exited during {operation}")
            frame = json.loads(line)
            if time.monotonic() >= deadline:
                raise RuntimeError(f"timed out during {operation}")
            if frame.get("event"):
                continue
            if frame.get("request_id") != request_id or frame.get("ok") is not True:
                raise RuntimeError(f"sidecar refused or mismatched {operation}: "
                                   f"{(frame.get('error') or {}).get('code', 'no-code')}")
            if not isinstance(frame.get("result"), dict):
                raise RuntimeError(f"invalid result during {operation}")
            return frame["result"]

    def close(self):
        try:
            self.process.stdin.close()
            self.process.wait(timeout=20)
        except (BrokenPipeError, subprocess.TimeoutExpired):
            self.process.kill()
            self.process.wait(timeout=20)
        finally:
            self.process.stdout.close()
            self.reader.join(timeout=1)
        if self.process.returncode != 0:
            raise RuntimeError("sidecar did not exit cleanly")


def probe(executable: Path, home: Path, *, create: bool) -> str:
    session = Session(executable, home)
    try:
        handshake = session.ask("bridge.handshake")
        revision = handshake.get("revision")
        if handshake.get("protocol") != PROTOCOL or not revision or revision == "unknown":
            raise RuntimeError("unidentified or incompatible packaged sidecar")
        if session.ask("viva.lifecycle.read").get("origin") != "packaged":
            raise RuntimeError("sidecar does not report packaged origin")
        if create:
            if session.ask("bridge.open_demo_vault").get("sample") is not True:
                raise RuntimeError("sidecar did not create the fictional sample")
        else:
            session.ask("bridge.open_vault", dict(vault_directory=str(home / "vault"),
                        passphrase=SAMPLE_PASSPHRASE, create=False))
        # Ordinary reopen starts a background read-store catch-up. Its status
        # surface is the public readiness boundary; do not retry refused writes.
        import time
        deadline = time.monotonic() + 90
        while True:
            readiness = session.ask("viva.surface.read", dict(surface="overview_accounts",
                                    job_id="lifecycle-ready", parameters={}))
            if (readiness.get("data") or {}).get("freshness") == "current":
                break
            if time.monotonic() >= deadline:
                raise RuntimeError("reopened read store did not become current")
            time.sleep(0.1)
        for surface in ("documents", "activity"):
            result = session.ask("viva.surface.read", dict(surface=surface,
                                job_id=f"lifecycle-{surface}", parameters={}))
            data = result.get("data")
            rows = "documents" if surface == "documents" else "items"
            if (not isinstance(data, dict) or data.get("state") != "ready"
                    or not isinstance(data.get(rows), list) or not data[rows]):
                raise RuntimeError("reopened vault did not answer its read surfaces")
        return revision
    finally:
        session.close()


def validate(baseline: Path, candidate: Path, *, require_distinct: bool = False) -> dict:
    baseline, candidate = baseline.resolve(strict=True), candidate.resolve(strict=True)
    hashes = [digest(path) for path in (baseline, candidate)]
    distinct = hashes[0] != hashes[1]
    if require_distinct and not distinct:
        raise RuntimeError("two-version evidence requires distinct artifact bytes")
    revisions = []
    with tempfile.TemporaryDirectory(prefix="orionviva-sidecar-lifecycle-") as directory:
        root = Path(directory)
        home, install = root / "profile", root / "installation"
        home.mkdir()
        vault = home / "vault"
        canonical = None
        for index, artifact in enumerate((baseline, candidate, baseline)):
            install.mkdir()
            executable = install / artifact.name
            shutil.copy2(artifact, executable)
            expected_hash = hashes[1] if index == 1 else hashes[0]
            if digest(executable) != expected_hash:
                raise RuntimeError("artifact changed before launch")
            revisions.append(probe(executable, home, create=index == 0))
            if digest(executable) != expected_hash:
                raise RuntimeError("artifact changed during launch")
            observed = snapshot(vault, canonical=True)
            if canonical is not None and observed != canonical:
                raise RuntimeError("replacement changed canonical vault bytes")
            canonical = observed
            before_removal = snapshot(vault)
            shutil.rmtree(install)
            if snapshot(vault) != before_removal:
                raise RuntimeError("removing application bytes changed the vault")
        # Reinstall once more to prove the surviving files remain readable.
        install.mkdir()
        executable = install / baseline.name
        shutil.copy2(baseline, executable)
        if digest(executable) != hashes[0]:
            raise RuntimeError("baseline changed before reinstall")
        revisions.append(probe(executable, home, create=False))
        if digest(executable) != hashes[0] or not revisions[0] == revisions[2] == revisions[3]:
            raise RuntimeError("baseline identity changed across launches")
        if snapshot(vault, canonical=True) != canonical:
            raise RuntimeError("reinstallation changed canonical vault bytes")
    return dict(schema="sidecar-lifecycle-v1", status="passed",
                scope="packaged-sidecar replacement; not OS installation or signing",
                mode="distinct-artifact" if distinct else "same-artifact-smoke",
                baseline_sha256=hashes[0], candidate_sha256=hashes[1],
                revisions=revisions, checks=["sample-created", "candidate-reopen",
                "baseline-rollback-reopen", "application-removal-preserves-vault",
                "baseline-reinstall-reopen", "canonical-bytes-unchanged"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--candidate", type=Path)
    parser.add_argument("--target", help="same-artifact smoke for a staged Rust target")
    parser.add_argument("--require-distinct", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.target:
        if args.baseline or args.candidate or args.require_distinct:
            parser.error("--target is only for same-artifact smoke")
        suffix = ".exe" if "windows" in args.target else ""
        args.baseline = args.candidate = (Path(__file__).resolve().parents[1]
            / "desktop/src-tauri/binaries" / f"viva-desktop-bridge-{args.target}{suffix}")
    elif not args.baseline or not args.candidate:
        parser.error("supply both --baseline and --candidate, or --target")
    output = args.output.resolve()
    if output in {args.baseline.resolve(), args.candidate.resolve()}:
        parser.error("output must not overwrite an input artifact")
    # A failed run must not leave an earlier passing report at this path.
    args.output.unlink(missing_ok=True)
    report = validate(args.baseline, args.candidate, require_distinct=args.require_distinct)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"sidecar lifecycle: {report['mode']} passed; not OS installer evidence")


if __name__ == "__main__":
    main()
