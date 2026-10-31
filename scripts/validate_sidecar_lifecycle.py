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
import re
import stat
import time
import shutil
import subprocess
import tempfile
import threading

PROTOCOL = "2.1"
SAMPLE_VERSION = "five-year-life-v1"
MAX_FRAME_BYTES = 4_000_000
SAMPLE_PASSPHRASE = "a-sample-vault-anybody-may-open"


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def snapshot(root: Path, *, canonical: bool = False) -> dict[str, str]:
    _ordinary(root, directory=True)
    if canonical: _ordinary(root/"raw", directory=True)
    paths = ([root / "events.jsonl", root / "events.jsonl.head",
              *sorted((root / "raw").rglob("*"))] if canonical
             else sorted(root.rglob("*")))
    if any(path.is_symlink() or (path.exists() and not path.is_file() and not path.is_dir())
           for path in paths):
        raise RuntimeError("synthetic vault contains a linked canonical member")
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
    def __init__(self, executable: Path, home: Path, timeout: float = 90, *, environment=None):
        self.timeout = timeout
        self.frames: queue.Queue = queue.Queue(maxsize=32)
        self.reader_error = None
        self.number = 0
        self.process = subprocess.Popen(
            [str(executable)], cwd=home, env=isolated_environment(home) if environment is None else environment,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, encoding="utf-8")
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()

    def _read(self):
        try:
            while True:
                line = self.process.stdout.readline(MAX_FRAME_BYTES+1)
                if not line:
                    break
                if len(line) > MAX_FRAME_BYTES or len(line.encode("utf-8")) > MAX_FRAME_BYTES or not line.endswith("\n"):
                    raise RuntimeError("sidecar supplied an oversized or incomplete frame")
                try:
                    self.frames.put(line, timeout=0.1)
                except queue.Full:
                    raise RuntimeError("sidecar supplied too many queued frames") from None
        except (OSError, UnicodeError, RuntimeError) as error:
            self.reader_error = error
        finally:
            try: self.frames.put_nowait(None)
            except queue.Full: pass

    def request(self, operation: str, payload: dict | None = None, *, deadline=None) -> dict:
        expires = time.monotonic()+self.timeout
        if deadline is not None:
            expires = min(expires, deadline)
        if time.monotonic() >= expires:
            raise RuntimeError(f"timed out during {operation}")
        self.number += 1
        request_id = f"lifecycle-{self.number}"
        encoded = json.dumps(dict(protocol=PROTOCOL, request_id=request_id,
                                  operation=operation, payload=payload or {})) + "\n"
        if len(encoded.encode('utf-8')) > MAX_FRAME_BYTES:
            raise RuntimeError('sidecar request exceeds its frame bound')
        sent = threading.Event()
        errors = []
        def send():
            try:
                self.process.stdin.write(encoded)
                self.process.stdin.flush()
            except (OSError, ValueError) as error:
                errors.append(error)
            finally: sent.set()
        writer = threading.Thread(target=send, daemon=True)
        writer.start()
        if not sent.wait(timeout=max(0, expires-time.monotonic())):
            try: self.process.kill()
            except OSError: pass
            writer.join(timeout=1)
            raise RuntimeError(f"timed out writing {operation}")
        writer.join(timeout=1)
        if errors: raise RuntimeError(f'sidecar stopped accepting {operation}') from errors[0]
        while True:
            remaining = expires-time.monotonic()
            if remaining <= 0:
                raise RuntimeError(f"timed out during {operation}")
            if getattr(self, 'reader_error', None) is not None:
                raise RuntimeError("sidecar reader rejected its output") from self.reader_error
            try:
                line = self.frames.get(timeout=remaining)
            except queue.Empty:
                raise RuntimeError(f"timed out during {operation}") from None
            if line is None:
                raise RuntimeError(f"sidecar stopped answering during {operation}")
            def closed(pairs):
                value = {}
                for key, item in pairs:
                    if key in value: raise RuntimeError('duplicate sidecar frame field')
                    value[key] = item
                return value
            try:
                frame = json.loads(line, object_pairs_hook=closed)
            except (ValueError, TypeError):
                raise RuntimeError("sidecar wrote a line that is not a frame") from None
            if time.monotonic() >= expires:
                raise RuntimeError(f"timed out during {operation}")
            if (not isinstance(frame, dict) or frame.get("protocol") != PROTOCOL
                    or frame.get("request_id") != request_id):
                raise RuntimeError(f"sidecar supplied a malformed or mismatched frame during {operation}")
            if "event" in frame:
                progress = frame.get("result")
                if (set(frame) != {"protocol", "request_id", "event", "result"}
                        or frame["event"] != "job.progress" or not isinstance(progress, dict)
                        or not isinstance(progress.get("job_id"), str) or not progress['job_id']
                        or progress.get("status") not in {"started", "progress", "completed", "failed", "cancelled"}
                        or type(progress.get("completed")) is not int
                        or type(progress.get("total")) is not int
                        or not 0 <= progress['completed'] <= progress['total']):
                    raise RuntimeError("sidecar supplied malformed progress")
                continue
            if type(frame.get("ok")) is not bool:
                raise RuntimeError("sidecar supplied a malformed reply")
            if frame['ok'] is True and not isinstance(frame.get('result'), dict):
                raise RuntimeError(f"invalid result during {operation}")
            if frame['ok'] is False and not isinstance(frame.get('error'), dict):
                raise RuntimeError(f"invalid refusal during {operation}")
            return frame

    def ask(self, operation: str, payload: dict | None = None, *, deadline=None) -> dict:
        frame = self.request(operation, payload, deadline=deadline)
        if frame['ok'] is not True:
            raise RuntimeError(f"sidecar refused {operation}: "
                               f"{frame['error'].get('code', 'no-code')}")
        return frame['result']

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


def _sample_status(value):
    fields = {'state','sample_version','completed_documents','total_documents',
              'posted_documents','held_documents','phase','message'}
    if (not isinstance(value, dict) or set(value) != fields
            or value['sample_version'] != SAMPLE_VERSION
            or value['state'] not in {'preparing','ready','failed'}
            or value['phase'] not in {'validating','capturing','checking','ready','failed'}
            or not isinstance(value['message'], str) or not value['message']
            or any(type(value[name]) is not int or not 0 <= value[name] <= 794
                   for name in ('completed_documents','total_documents','posted_documents','held_documents'))
            or value['total_documents'] != 794
            or value['posted_documents']+value['held_documents'] != value['completed_documents']
            or (value['state'] == 'ready' and (value['phase'] != 'ready' or value['completed_documents'] != 794))
            or (value['state'] == 'failed' and value['phase'] != 'failed')
            or (value['state'] == 'preparing' and value['phase'] in {'ready','failed'})):
        raise RuntimeError('sample supplied malformed preparation status')
    return value


def prepare_sample(ask, *, deadline):
    """Prepare once and poll under a single unchanged readiness budget."""
    status = _sample_status(ask('bridge.sample.prepare', deadline=deadline))
    first = True
    while True:
        if time.monotonic() >= deadline:
            raise RuntimeError('sample preparation timed out')
        if status['state'] == 'failed': raise RuntimeError('sample preparation failed')
        if not first and status['state'] == 'ready': return status
        first = False
        if status['state'] == 'preparing':
            time.sleep(min(0.05, max(0, deadline-time.monotonic())))
        status = _sample_status(ask('bridge.sample.status', deadline=deadline))


def _ordinary(path, *, directory):
    info = path.lstat()
    if (path.is_symlink() or (directory and not stat.S_ISDIR(info.st_mode))
            or (not directory and not stat.S_ISREG(info.st_mode))
            or (hasattr(os, 'getuid') and info.st_uid != os.getuid())):
        raise RuntimeError('sample pointer path is not ordinary and owned')
    if path.resolve(strict=True) != path:
        raise RuntimeError('sample pointer path is not canonical')


def resolve_sample_root(home):
    """Bind the initial closed pointer once; never select a replacement vault."""
    root = home/'vault'/'versioned'
    _ordinary(home, directory=True); _ordinary(home/'vault', directory=True)
    _ordinary(root, directory=True)
    pointer = root/'five-year-sample-active.json'
    _ordinary(pointer, directory=False)
    def closed(pairs):
        value = {}
        for key, item in pairs:
            if key in value: raise RuntimeError('duplicate sample pointer field')
            value[key] = item
        return value
    with pointer.open('rb') as source: data = source.read(513)
    if len(data) > 512: raise RuntimeError('sample pointer exceeds its bound')
    value = json.loads(data, object_pairs_hook=closed)
    if (not isinstance(value, dict) or set(value) != {'version','instance_id'}
            or value['version'] != SAMPLE_VERSION or not isinstance(value['instance_id'], str)
            or re.fullmatch('[0-9a-f]{32}', value['instance_id']) is None):
        raise RuntimeError('sample pointer is malformed')
    selected = root/'sample-vaults'/value['version']/value['instance_id']/'vault'
    for directory in (root/'sample-vaults', root/'sample-vaults'/value['version'], selected.parent, selected):
        _ordinary(directory, directory=True)
    if not selected.is_relative_to(root): raise RuntimeError('sample pointer escaped its root')
    return selected


def probe(executable: Path, home: Path, *, create: bool, vault_root: Path | None = None) -> str:
    session = Session(executable, home)
    try:
        handshake = session.ask("bridge.handshake")
        revision = handshake.get("revision")
        if handshake.get("protocol") != PROTOCOL or not revision or revision == "unknown":
            raise RuntimeError("unidentified or incompatible packaged sidecar")
        if session.ask("viva.lifecycle.read").get("origin") != "packaged":
            raise RuntimeError("sidecar does not report packaged origin")
        deadline = time.monotonic()+90
        if create:
            prepare_sample(session.ask, deadline=deadline)
            if session.ask("bridge.open_demo_vault", deadline=deadline).get("sample") is not True:
                raise RuntimeError("sidecar did not create the fictional sample")
        else:
            if vault_root is None: raise RuntimeError("reopen has no bound canonical vault")
            _ordinary(vault_root, directory=True)
            session.ask("bridge.open_vault", dict(vault_directory=str(vault_root),
                        passphrase=SAMPLE_PASSPHRASE, create=False), deadline=deadline)
        # Ordinary reopen starts a background read-store catch-up. Its status
        # surface is the public readiness boundary; do not retry refused writes.
        while True:
            readiness = session.ask("viva.surface.read", dict(surface="overview_accounts",
                                    job_id="lifecycle-ready", parameters={}), deadline=deadline)
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
        root = Path(directory).resolve(strict=True)
        home, install = root / "profile", root / "installation"
        home.mkdir()
        vault = None
        canonical = None
        for index, artifact in enumerate((baseline, candidate, baseline)):
            install.mkdir()
            executable = install / artifact.name
            shutil.copy2(artifact, executable)
            expected_hash = hashes[1] if index == 1 else hashes[0]
            if digest(executable) != expected_hash:
                raise RuntimeError("artifact changed before launch")
            revisions.append(probe(executable, home, create=index == 0, vault_root=vault))
            if index == 0:
                vault = resolve_sample_root(home)
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
        revisions.append(probe(executable, home, create=False, vault_root=vault))
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
