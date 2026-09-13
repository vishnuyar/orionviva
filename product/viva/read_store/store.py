"""Encrypted immutable generations for the disposable read projection."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import shutil
import stat
import threading
import time
import uuid
from datetime import date
from decimal import Decimal, ROUND_CEILING
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from ..crypto import (KdfParams, CryptoError, SALT_LEN, SCRYPT_N, SCRYPT_P,
                      SCRYPT_R, derive_key)

try:
    from sqlcipher3 import dbapi2 as sqlcipher
except ImportError as exc:
    raise RuntimeError("SQLCipher runtime is required for the encrypted read store") from exc

METADATA_VERSION = "viva-read-store-scrypt-v1"
MANIFEST_VERSION = "viva-read-store-current-v4"
CHECK_TOKEN = b"viva-read-store-ok"
METADATA_NAME, CURRENT_NAME, DATABASE_NAME = "key.json", "current.json", "projection.db"
GENERATIONS_NAME, QUARANTINE_NAME, LOCK_NAME = "generations", "quarantine", "writer.lock"
BUSY_TIMEOUT_MS = 5_000
WRITER_LOCK_TIMEOUT_SECONDS = 5.0
MANIFEST_REPLACE_TIMEOUT_SECONDS = 2.0
RETAIN_SUPERSEDED_GENERATIONS = 2
RETAIN_QUARANTINED_GENERATIONS = 2
_MANIFEST_DOMAIN = b"viva-read-store-manifest-key-v1"
_DATABASE_DOMAIN = b"viva-read-store-database-key-v1"
CONTROL_SCHEMA_VERSION = 30
PROJECTOR_VERSION = "materialized-v19"
RESOLVER_VERSION = "resolver-v1"
AS_OF_VERSION = "as-of-v1"
_APPLIED_EVENTS_GENESIS_DOMAIN = b"viva-read-store-applied-events-genesis-v1\0"
_APPLIED_EVENTS_ENTRY_DOMAIN = b"viva-read-store-applied-events-entry-v1\0"
_RESOLVER_SNAPSHOT_DOMAIN = b"viva-read-store-resolver-snapshot-v1\0"
GOAL_HISTORY_PER_GOAL_LIMIT = 2_000
MAX_GOAL_HISTORY_ROWS = 10_000
MAX_GOAL_HISTORY_BODY_BYTES = 1_000_000
GOAL_POSTINGS_PER_ACCOUNT_LIMIT = 10_000
GOAL_RESERVATION_EVENT_LIMIT = 10_000
MAX_REVIEW_DECISION_BODY_BYTES = 1_000_000
MAX_DOCUMENT_RESPONSE_BYTES = 1_000_000
MAX_MODEL_EXCHANGE_BODY_BYTES = 1_000_000
MAX_TRANSFER_SUGGESTION_BYTES = 1_000_000


def _decimal_step(current: str | None, amount: str, event_type: str) -> str:
    """Apply one reservation event without routing money through SQLite REAL."""
    before = Decimal(current or "0")
    value = Decimal(amount)
    if event_type == "GoalFundsReleased":
        return str(max(before - min(value, max(before, Decimal("0"))), Decimal("0")))
    return str(before + value)


class _DecimalSum:
    """Exact aggregate used by SQL read models; SQLite numeric affinity is forbidden."""
    def __init__(self):
        self.total = Decimal("0")

    def step(self, value):
        if value is not None:
            self.total += Decimal(value)

    def finalize(self):
        return str(self.total)


class ReadStoreError(CryptoError):
    """The read store is unavailable, unauthenticated, or not encrypted."""


class ReadStoreBusy(ReadStoreError):
    """The single writer did not become available within its bound."""


class ReadStoreDegraded(ReadStoreError):
    """Canonical events committed, but the disposable projection did not."""


@dataclass(frozen=True)
class SynchronizeResult:
    state: str
    generation: str
    source_count: int
    applied_count: int


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _aad(version: str, kdf: dict[str, Any]) -> bytes:
    return b"viva-read-store-metadata:" + _canonical({"v": version, "kdf": kdf})


def _new_metadata(passphrase: str) -> tuple[dict[str, Any], bytes]:
    params = KdfParams(salt=os.urandom(SALT_LEN), n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P)
    key, kdf, nonce = derive_key(passphrase, params), params.to_dict(), os.urandom(12)
    check = AESGCM(key).encrypt(nonce, CHECK_TOKEN, _aad(METADATA_VERSION, kdf))
    return {"v": METADATA_VERSION, "kdf": kdf, "check": {
        "nonce": base64.b64encode(nonce).decode(), "ct": base64.b64encode(check).decode()}}, key


def _open_metadata(metadata: dict[str, Any], passphrase: str) -> bytes:
    try:
        version, kdf = metadata["v"], metadata["kdf"]
        if version != METADATA_VERSION:
            raise ReadStoreError(f"unsupported read-store metadata version {version!r}")
        params = KdfParams.from_dict(kdf)
        if ((params.n, params.r, params.p) != (SCRYPT_N, SCRYPT_R, SCRYPT_P)
                or len(params.salt) != SALT_LEN):
            raise ReadStoreError("unsupported read-store KDF parameters")
        key = derive_key(passphrase, params)
        opened = AESGCM(key).decrypt(
            base64.b64decode(metadata["check"]["nonce"], validate=True),
            base64.b64decode(metadata["check"]["ct"], validate=True), _aad(version, kdf))
    except ReadStoreError:
        raise
    except Exception as exc:
        raise ReadStoreError(
            "read-store metadata authentication failed: wrong passphrase or tampering") from exc
    if opened != CHECK_TOKEN:
        raise ReadStoreError("read-store metadata authentication failed")
    return key


def _restrict(path: Path, mode: int) -> None:
    if os.name != "nt":
        path.chmod(mode)


def _write_private(path: Path, data: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"): flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data); stream.flush(); os.fsync(stream.fileno())
    except Exception:
        path.unlink(missing_ok=True)
        raise
    _restrict(path, 0o600)


def _write_json(path: Path, value: dict[str, Any]) -> None:
    _write_private(path, _canonical(value) + b"\n")


def _create_private_file(path: Path) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"): flags |= os.O_NOFOLLOW
    os.close(os.open(path, flags, 0o600))


def _lstat_kind(path: Path, *, directory: bool) -> None:
    """Reject links and unexpected filesystem objects at trust boundaries."""
    try: mode = path.lstat().st_mode
    except OSError as exc: raise ReadStoreError(f"unsafe read-store path: {path.name}") from exc
    wanted = stat.S_ISDIR(mode) if directory else stat.S_ISREG(mode)
    if stat.S_ISLNK(mode) or not wanted:
        raise ReadStoreError(f"unsafe read-store path: {path.name}")


def _contained(root: Path, path: Path) -> None:
    try: path.absolute().relative_to(root.absolute())
    except ValueError as exc: raise ReadStoreError("read-store path escapes its root") from exc


def _read_json_file(root: Path, path: Path) -> dict[str, Any]:
    _contained(root, path); _lstat_kind(path, directory=False)
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"): flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags)
    try:
        with os.fdopen(descriptor, "r", encoding="utf-8") as stream:
            return json.load(stream)
    except Exception as exc:
        raise ReadStoreError(f"invalid read-store file: {path.name}") from exc


def _fsync_dir(path: Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _wipe(value: bytearray) -> None:
    for index in range(len(value)):
        value[index] = 0


def _close_after_failure(connection: Any) -> None:
    try:
        connection.close()
    except Exception:
        pass


def assert_sqlcipher_runtime() -> str:
    connection = sqlcipher.connect(":memory:")
    try:
        row = connection.execute("PRAGMA cipher_version").fetchone()
    finally:
        connection.close()
    if not row or not isinstance(row[0], str) or not row[0].strip():
        raise ReadStoreError("SQLCipher runtime is absent; plaintext SQLite is forbidden")
    return row[0].strip()


def _connect(path: Path, key: bytes | bytearray, *, readonly: bool = False):
    assert_sqlcipher_runtime()
    target = f"file:{path.as_posix()}?mode=ro" if readonly else str(path)
    connection = sqlcipher.connect(target, uri=readonly)
    try:
        connection.create_function("viva_decimal_step", 3, _decimal_step,
                                   deterministic=True)
        connection.create_aggregate("viva_decimal_sum", 1, _DecimalSum)
        connection.execute(f"PRAGMA key = \"x'{key.hex()}'\"")
        connection.execute("PRAGMA cipher_plaintext_header_size = 0")
        connection.execute("PRAGMA temp_store = MEMORY")
        if not readonly:
            connection.execute("PRAGMA journal_mode = DELETE")
            connection.execute("PRAGMA synchronous = FULL")
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA trusted_schema = OFF")
        connection.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
        if readonly:
            connection.execute("PRAGMA query_only = ON")
        connection.execute("SELECT count(*) FROM sqlite_master").fetchone()
        expected = {"cipher_plaintext_header_size": 0, "temp_store": 2,
                    "journal_mode": "delete", "synchronous": 2,
                    "foreign_keys": 1, "trusted_schema": 0,
                    "busy_timeout": BUSY_TIMEOUT_MS}
        if readonly:
            expected["query_only"] = 1
        for pragma, wanted in expected.items():
            row = connection.execute(f"PRAGMA {pragma}").fetchone()
            got = row[0] if row else None
            if isinstance(wanted, str): got = str(got).lower()
            elif isinstance(got, str) and got.isdecimal(): got = int(got)
            if got != wanted:
                raise ReadStoreError(f"SQLCipher setting {pragma} was {got!r}, expected {wanted!r}")
        return connection
    except Exception:
        _close_after_failure(connection)
        raise


def _generation_id() -> str:
    return "g-" + uuid.uuid4().hex


def _valid_generation(value: Any) -> bool:
    return (isinstance(value, str) and value.startswith("g-") and len(value) == 34
            and all(c in "0123456789abcdef" for c in value[2:]))


def _mac_key(root_key: bytes) -> bytes:
    return hmac.new(root_key, _MANIFEST_DOMAIN, hashlib.sha256).digest()


def _database_key(root_key: bytes) -> bytes:
    return hmac.new(root_key, _DATABASE_DOMAIN, hashlib.sha256).digest()


def _applied_events_genesis(schema_version: int, projector_version: str) -> str:
    """Commit an empty mapping chain to its schema and projector semantics."""
    payload = _canonical({"schema_version": schema_version,
                          "projector_version": projector_version})
    return hashlib.sha256(_APPLIED_EVENTS_GENESIS_DOMAIN + payload).hexdigest()


def _extend_applied_events_digest(previous: str, sequence: int, event_id: str,
                                  record_hash: str, event_type: str) -> str:
    """Extend the ordered applied-event identity commitment by one row."""
    payload = _canonical({"sequence": sequence, "event_id": event_id,
                          "record_hash": record_hash, "event_type": event_type})
    return hashlib.sha256(
        _APPLIED_EVENTS_ENTRY_DOMAIN + bytes.fromhex(previous) + payload
    ).hexdigest()


def _manifest(generation: str, epoch: int, source: dict[str, Any],
              key: bytes | bytearray) -> dict[str, Any]:
    body = {"v": MANIFEST_VERSION, "generation": generation,
            "epoch": epoch, "source": source}
    tag = hmac.new(bytes(key), _canonical(body), hashlib.sha256).digest()
    return {**body, "tag": base64.b64encode(tag).decode()}


def _verify_manifest(value: Any, key: bytes | bytearray) -> dict[str, Any]:
    try:
        if set(value) != {"v", "generation", "epoch", "source", "tag"} \
                or value["v"] != MANIFEST_VERSION:
            raise ValueError("shape")
        generation = value["generation"]
        if not _valid_generation(generation): raise ValueError("generation")
        epoch, source = value["epoch"], value["source"]
        if not isinstance(epoch, int) or isinstance(epoch, bool) or epoch < 1:
            raise ValueError("epoch")
        if set(source) != {"count", "head", "last_sequence", "last_hash",
                           "applied_events_digest", "resolver_content_hash"}:
            raise ValueError("source shape")
        if (not isinstance(source["count"], int) or source["count"] < 0
                or not isinstance(source["last_sequence"], int)
                or source["last_sequence"] < -1
                or not isinstance(source["head"], str)
                or not isinstance(source["last_hash"], str)
                or not isinstance(source["applied_events_digest"], str)
                or re.fullmatch(r"[0-9a-f]{64}", source["applied_events_digest"]) is None
                or not isinstance(source["resolver_content_hash"], str)
                or re.fullmatch(r"[0-9a-f]{64}", source["resolver_content_hash"]) is None):
            raise ValueError("source")
        supplied = base64.b64decode(value["tag"], validate=True)
        body = {name: value[name] for name in ("v", "generation", "epoch", "source")}
        expected = hmac.new(bytes(key), _canonical(body), hashlib.sha256).digest()
        if not hmac.compare_digest(supplied, expected): raise ValueError("tag")
        return body
    except Exception as exc:
        raise ReadStoreError("current read-store manifest authentication failed") from exc


def _replace_manifest(source: Path, target: Path) -> None:
    deadline = time.monotonic() + MANIFEST_REPLACE_TIMEOUT_SECONDS
    while True:
        try:
            os.replace(source, target)
            return
        except PermissionError as exc:
            retry = os.name == "nt" and getattr(exc, "winerror", None) in (32, 33)
            if not retry or time.monotonic() >= deadline: raise
            time.sleep(.01)


_locks_guard = threading.Lock()
_locks: dict[str, threading.Lock] = {}


class _WriterLock:
    def __init__(self, path: Path, timeout: float):
        self.path, self.timeout, self.stream = path, timeout, None
        with _locks_guard:
            self.local = _locks.setdefault(str(path.resolve()), threading.Lock())

    def __enter__(self):
        if not self.local.acquire(timeout=self.timeout):
            raise ReadStoreBusy("read-store writer lock timed out")
        try:
            _lstat_kind(self.path, directory=False)
            flags = os.O_RDWR
            if hasattr(os, "O_NOFOLLOW"): flags |= os.O_NOFOLLOW
            self.stream = os.fdopen(os.open(self.path, flags), "a+b")
            _restrict(self.path, 0o600)
            deadline = time.monotonic() + self.timeout
            while True:
                try:
                    if os.name == "nt":
                        import msvcrt
                        self.stream.seek(0); msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(self.stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    return self
                except (BlockingIOError, OSError):
                    if time.monotonic() >= deadline:
                        raise ReadStoreBusy("read-store writer lock timed out")
                    time.sleep(.01)
        except Exception:
            if self.stream: self.stream.close()
            self.local.release(); raise

    def __exit__(self, *_exc):
        try:
            if self.stream:
                if os.name == "nt":
                    import msvcrt
                    self.stream.seek(0); msvcrt.locking(self.stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self.stream.fileno(), fcntl.LOCK_UN)
                self.stream.close()
        finally:
            self.local.release()


class ReadRevision:
    def __init__(self, store: "ReadStore", generation: str, connection: Any):
        self._store, self.generation, self.connection = store, generation, connection
        self._closed = False

    def close(self):
        if self._closed: return
        # A failed native close may still own an OS handle.  Keep the reference
        # pinned and make the failure visible; a later close may safely retry.
        self.connection.close()
        self._closed = True
        self._store._release(self.generation)

    def __enter__(self): return self
    def __exit__(self, *_exc): self.close()

    @property
    def resolver_version(self) -> str:
        return self.connection.execute(
            "SELECT resolver_version FROM projection_meta WHERE singleton=1"
        ).fetchone()[0]

    def resolver(self, *, expected_version: str | None = None):
        """Return the resolver whose identity is bound to this revision."""
        version = self.resolver_version
        if expected_version is not None and expected_version != version:
            raise ReadStoreError(
                f"read revision resolver is {version!r}, not {expected_version!r}")
        if version != RESOLVER_VERSION:
            raise ReadStoreError(f"read revision resolver {version!r} is not registered")
        from merchantcore.profile import Profile, is_inducible
        from merchantcore.taxonomy import subcategory_identity
        from ..ledger.merchant_keys import resolve_keys
        from .scalar_bounds import selected as scalar_selected, refuse as refuse_scalars
        from .rhythm import MAX_RESOLVER_PROFILES, MAX_RHYTHM_JSON_BYTES
        columns = ("institution", "account_kind")
        selected, bounds = scalar_selected(columns)
        rows = self.connection.execute(
            f"SELECT {selected},CASE WHEN length(CAST(profile_json AS BLOB))<=? "
            "THEN profile_json END FROM resolver_profiles "
            "ORDER BY institution, account_kind LIMIT ?",
            (*bounds, MAX_RHYTHM_JSON_BYTES, MAX_RESOLVER_PROFILES + 1)).fetchall()
        if len(rows) > MAX_RESOLVER_PROFILES:
            raise ReadStoreError("resolver profiles exceed their read bound")
        refuse_scalars([row[:2] for row in rows], columns,
                       label="resolver profile labels")
        if any(profile_json is None for _institution, _kind, profile_json in rows):
            raise ReadStoreError("resolver profile exceeds its byte bound")
        profiles = {(institution, kind): Profile.from_dict(json.loads(profile_json))
                    for institution, kind, profile_json in rows}

        def profile_for(institution, kind):
            return profiles.get((institution, kind)) if is_inducible(kind) else None
        return lambda inputs: resolve_keys(inputs, profile_for=profile_for)

    def rhythm_hypotheses(self, *, as_of: str, limit: int = 200):
        """Compose merchant cadence hypotheses from this SQL revision only."""
        from .rhythm import rhythms
        result, _movement_map = rhythms(
            self.connection, as_of=as_of, limit=limit)
        return result

    def obligations(self, *, today: str, limit: int = 200):
        """Compose qualified outgoing obligations from this SQL revision only."""
        from .rhythm import obligations
        return obligations(self.connection, today=today, limit=limit)

    def findings(self, *, today: str, include_set_aside: bool = False,
                 limit: int = 200):
        """Compose current deterministic findings from this revision only."""
        from .composition import findings
        return findings(self.connection, today=today,
                        include_set_aside=include_set_aside, limit=limit)

    def current_period(self, *, today: str, horizon_days: int = 30,
                       evidence_as_of: str | None = None):
        """Compose the complete current-period contract from this revision."""
        from .composition import current_period
        return current_period(self, today=today, horizon_days=horizon_days,
                              evidence_as_of=evidence_as_of)

    def overview_projection(self, *, today: str):
        """Return bounded SQL inputs for the reviewed Overview composer."""
        from .overview import projection
        return projection(self, today=today)

    def historical_overview_projection(self, *, as_of: str, today: str):
        """Return value-time Overview inputs from this held revision."""
        from .overview import SQLHistoricalOverviewProjection
        return SQLHistoricalOverviewProjection(self, as_of=as_of, today=today)

    def activity_projection(self):
        """Return bounded SQL inputs for current Activity composition."""
        from .overview import SQLOverviewProjection
        return SQLOverviewProjection(self, "", activity_evidence=True)

    def historical_activity_projection(self, *, as_of: str):
        """Return value-time filtered SQL inputs for historical Activity."""
        from .temporal_activity import SQLHistoricalActivityProjection
        return SQLHistoricalActivityProjection(self, as_of)

    def account_ledger_components(self, account_id: str, *, locale: str = "en-US"):
        """Return bounded statement and deduplication facts for one account."""
        from .account_ledger import components
        return components(self, account_id, locale=locale)

    def account_ledger_page(self, account_id: str, *, locale: str = "en-US",
                            cursor_secret: bytes, limit: int = 50,
                            cursor: str = ""):
        """Read one indexed keyset page from this held generation."""
        from .account_ledger_page import read_page
        return read_page(self, account_id, locale, cursor_secret=cursor_secret,
                         limit=limit, cursor=cursor)

    def spending_projection(self, *, today: str, locale: str = "en-US"):
        """Return bounded SQL inputs for current Spending composition."""
        from .overview import SQLOverviewProjection
        return SQLOverviewProjection(
            self, today, statement_evidence=True, locale=locale)

    def documents_projection(self):
        """Return bounded SQL inputs for current Documents composition."""
        from .documents import SQLDocumentsProjection
        return SQLDocumentsProjection(self)

    def review_projection(self, *, locale: str = "en-US"):
        """Return bounded SQL inputs for current Review composition."""
        from .overview import SQLOverviewProjection
        return SQLOverviewProjection(
            self, "", activity_evidence=True, statement_evidence=True,
            locale=locale)

    def plans_projection(self):
        """Return bounded SQL inputs for current Plans composition."""
        from .plans import SQLPlansProjection
        return SQLPlansProjection(self)

    def conversation_projection(self, *, locale: str = "en-US"):
        """Return durable timeline and Review inputs from this revision."""
        from .conversation import SQLConversationProjection
        return SQLConversationProjection(self, locale=locale)

    def open_questions(self, *, as_of: str, jurisdiction: str = "",
                       locale: str = "", limit: int | None = 10,
                       held_as_of: str | None = None):
        """Return the bounded actionable question queue from this revision."""
        from .questions import open_questions
        return open_questions(self.connection, as_of=as_of,
                              jurisdiction=jurisdiction,
                              locale=locale, limit=limit,
                              held_as_of=held_as_of)

    def find_question(self, question_id: str, *, as_of: str,
                      jurisdiction: str = "", locale: str = ""):
        """Return one live question from this immutable revision."""
        from .questions import find_question
        return find_question(self.connection, question_id, as_of=as_of,
                             jurisdiction=jurisdiction, locale=locale)

    def pending_questions(self, *, as_of: str, jurisdiction: str = "",
                          locale: str = ""):
        """Return current set-aside questions from this revision."""
        from .questions import pending_questions
        return pending_questions(self.connection, as_of=as_of,
                                 jurisdiction=jurisdiction, locale=locale)

    def held_items(self, *, as_of: str):
        """Return current balance-family holds from this immutable revision."""
        from .held import held_items
        rows = held_items(self.connection, as_of=as_of)
        return [{key: value for key, value in row.items()
                 if key not in ("facts", "resolution", "occurred_at")}
                for row in rows]

    def document_history(self, *, as_of: str, limit: int = 200,
                         before: tuple[str, int] | None = None) -> list[dict[str, Any]]:
        """Return one bounded, stable page of captured-document history.

        Every statement runs on the immutable generation authenticated by
        :meth:`ReadStore.open_reader`. The cursor is a value-time/source-order
        key, so later generations cannot move a row within this revision.
        """
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 200:
            raise ValueError("document history limit must be between 1 and 200")
        parameters: list[Any] = [as_of]
        boundary = ""
        if before is not None:
            occurred_at, source_sequence = before
            boundary = " AND (occurred_at < ? OR (occurred_at = ? AND source_sequence < ?))"
            parameters.extend((occurred_at, occurred_at, source_sequence))
        parameters.append(limit)
        rows = self.connection.execute(
            "SELECT source_sequence,doc_id,occurred_at,filename,byte_len,doc_type,"
            "doc_type_confidence_text,state,provenance_doc_id,provenance_page,"
            "provenance_region,provenance_note FROM documents "
            "WHERE occurred_at<=?" + boundary
            + " ORDER BY occurred_at DESC,source_sequence DESC LIMIT ?", parameters).fetchall()
        names = ("source_sequence", "doc_id", "occurred_at", "filename", "byte_len",
                 "doc_type", "doc_type_confidence_text", "state", "provenance_doc_id",
                 "provenance_page", "provenance_region", "provenance_note")
        return [dict(zip(names, row)) for row in rows]

    def document_read_history(self, doc_id: str, *, as_of: str,
                              limit: int = 50) -> list[dict[str, Any]]:
        """Return bounded model-reading history for one document, newest first."""
        if not doc_id:
            raise ValueError("document id is required")
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 50:
            raise ValueError("document read history limit must be between 1 and 50")
        rows = self.connection.execute(
            "SELECT source_sequence,occurred_at,phase,model,model_role,resolved_model,"
            "prompt_version,input_mode,"
            "CASE WHEN length(CAST(response_text AS BLOB))<=? THEN response_text END,"
            "cost_usd_text,input_tokens,"
            "output_tokens,usage_reported,parse_ok,parse_error FROM document_reads "
            "WHERE doc_id=? AND occurred_at<=? "
            "ORDER BY occurred_at DESC,source_sequence DESC LIMIT ?",
            (MAX_DOCUMENT_RESPONSE_BYTES, doc_id, as_of, limit)).fetchall()
        if any(row[8] is None for row in rows):
            raise ReadStoreError("document response exceeds its byte bound")
        names = ("source_sequence", "occurred_at", "phase", "model", "model_role",
                 "resolved_model", "prompt_version", "input_mode", "response_text",
                 "cost_usd_text", "input_tokens", "output_tokens", "usage_reported",
                 "parse_ok", "parse_error")
        return [dict(zip(names, row)) for row in rows]

    def model_exchange_history(
        self, *, as_of: str, limit: int = 200,
        before: tuple[str, int] | None = None, phase: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return the bounded Trust input recording every model exchange.

        This is intentionally a history read, not a rendered Trust answer.  It
        preserves the event body and provenance so the later surface-conversion
        slice can reproduce ``surface.outbound`` without reopening the log.
        """
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 200:
            raise ValueError("model exchange limit must be between 1 and 200")
        clauses, parameters = ["occurred_at<=?"], [as_of]
        if phase is not None:
            clauses.append("phase=?"); parameters.append(phase)
        if before is not None:
            if (not isinstance(before, tuple) or len(before) != 2
                    or not isinstance(before[0], str)
                    or not isinstance(before[1], int) or isinstance(before[1], bool)):
                raise ValueError("model exchange cursor must be (occurred_at, source_sequence)")
            clauses.append("(occurred_at<? OR (occurred_at=? AND source_sequence<?))")
            parameters.extend((before[0], before[0], before[1]))
        parameters.append(limit)
        columns = ("source_sequence", "event_type", "doc_id", "occurred_at",
                   "phase", "model", "model_role", "resolved_model",
                   "cost_usd_text", "input_tokens", "output_tokens",
                   "usage_reported", "body_json", "provenance_doc_id",
                   "provenance_page", "provenance_region", "provenance_note")
        selected = tuple(
            "CASE WHEN length(CAST(body_json AS BLOB))<=? THEN body_json END"
            if column == "body_json" else column for column in columns)
        rows = self.connection.execute(
            f"SELECT {','.join(selected)} FROM document_reads "
            f"WHERE {' AND '.join(clauses)} "
            "ORDER BY occurred_at DESC,source_sequence DESC LIMIT ?",
            (MAX_MODEL_EXCHANGE_BODY_BYTES, *parameters)).fetchall()
        if any(row[12] is None for row in rows):
            raise ReadStoreError("model exchange body exceeds its byte bound")
        return [dict(zip(columns, row)) for row in rows]

    def agent_action_history(
        self, *, as_of: str, limit: int = 200,
        before: tuple[str, int] | None = None, outcome: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return bounded unattended-work history used by Trust and cooldowns."""
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 200:
            raise ValueError("agent action limit must be between 1 and 200")
        if outcome not in (None, "done", "refused", "failed"):
            raise ValueError("unknown agent action outcome")
        clauses, parameters = ["occurred_at<=?"], [as_of]
        if outcome is not None:
            clauses.append("outcome=?"); parameters.append(outcome)
        if before is not None:
            if (not isinstance(before, tuple) or len(before) != 2
                    or not isinstance(before[0], str)
                    or not isinstance(before[1], int) or isinstance(before[1], bool)):
                raise ValueError("agent action cursor must be (occurred_at, source_sequence)")
            clauses.append("(occurred_at<? OR (occurred_at=? AND source_sequence<?))")
            parameters.extend((before[0], before[0], before[1]))
        parameters.append(limit)
        columns = ("source_sequence", "event_type", "occurred_at", "rule_id",
                   "action_kind", "target", "outcome", "calls", "stake_json",
                   "produced", "replaced", "detail", "by_actor", "body_json",
                   "provenance_doc_id", "provenance_page", "provenance_region",
                   "provenance_note")
        rows = self.connection.execute(
            f"SELECT {','.join(columns)} FROM agent_action_history "
            f"WHERE {' AND '.join(clauses)} "
            "ORDER BY occurred_at DESC,source_sequence DESC LIMIT ?", parameters).fetchall()
        return [dict(zip(columns, row)) for row in rows]

    def document_hold_history(self, doc_id: str, *, as_of: str,
                              limit: int = 50) -> list[dict[str, Any]]:
        """Return bounded statement/activity hold history without parsing raw data."""
        if not doc_id:
            raise ValueError("document id is required")
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 50:
            raise ValueError("document hold history limit must be between 1 and 50")
        rows = self.connection.execute(
            "SELECT source_sequence,event_type,occurred_at,reason,facts_json,finding_json "
            "FROM document_holds WHERE doc_id=? AND occurred_at<=? "
            "ORDER BY occurred_at DESC,source_sequence DESC LIMIT ?",
            (doc_id, as_of, limit)).fetchall()
        names = ("source_sequence", "event_type", "occurred_at", "reason",
                 "facts_json", "finding_json")
        return [dict(zip(names, row)) for row in rows]

    def statement_period_history(
        self, *, as_of: str, limit: int = 200,
        before: tuple[str, int] | None = None,
        account_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return posted statement periods in stable value/source order."""
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 200:
            raise ValueError("statement period limit must be between 1 and 200")
        clauses, parameters = ["period_end<=?"], [as_of]
        if account_id is not None:
            clauses.append("account_id=?"); parameters.append(account_id)
        if before is not None:
            if (not isinstance(before, tuple) or len(before) != 2
                    or not isinstance(before[0], str)
                    or not isinstance(before[1], int)
                    or isinstance(before[1], bool)):
                raise ValueError("statement period cursor must be (period_end, source_sequence)")
            clauses.append("(period_end<? OR (period_end=? AND source_sequence<?))")
            parameters.extend((before[0], before[0], before[1]))
        parameters.append(limit)
        columns = ("source_sequence", "account_id", "doc_id", "period_end",
                   "closing_amount_text", "confirmed_by", "provenance_doc_id",
                   "provenance_page", "provenance_region", "provenance_note")
        rows = self.connection.execute(
            f"SELECT {','.join(columns)} FROM statement_periods "
            f"WHERE {' AND '.join(clauses)} "
            "ORDER BY period_end DESC,source_sequence DESC LIMIT ?", parameters).fetchall()
        return [dict(zip(columns, row)) for row in rows]

    def statement_coverage(
        self, *, as_of: str, limit: int = 200,
        before: tuple[str, str, int] | None = None,
    ) -> list[dict[str, Any]]:
        """Return the first accepted document for each account/period.

        ``ProjectionCore._periods`` uses ``setdefault`` in canonical sequence
        order. The grouped minimum below is the relational form of that exact
        duplicate rule; later corrections remain in history without silently
        taking ownership of an already-claimed period.
        """
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 200:
            raise ValueError("statement coverage limit must be between 1 and 200")
        parameters: list[Any] = [as_of]
        boundary = ""
        if before is not None:
            if (not isinstance(before, tuple) or len(before) != 3
                    or not all(isinstance(value, str) for value in before[:2])
                    or not isinstance(before[2], int) or isinstance(before[2], bool)):
                raise ValueError(
                    "statement coverage cursor must be (period_end, account_id, source_sequence)")
            boundary = (" WHERE (p.period_end<? OR (p.period_end=? AND p.account_id>?) "
                        "OR (p.period_end=? AND p.account_id=? AND p.source_sequence<?))")
            parameters.extend((before[0], before[0], before[1],
                               before[0], before[1], before[2]))
        parameters.append(limit)
        columns = ("source_sequence", "account_id", "doc_id", "period_end",
                   "closing_amount_text", "confirmed_by", "provenance_doc_id",
                   "provenance_page", "provenance_region", "provenance_note")
        rows = self.connection.execute(
            "WITH first_period AS (SELECT account_id,period_end,MIN(source_sequence) source_sequence "
            "FROM statement_periods WHERE period_end<=? GROUP BY account_id,period_end) "
            f"SELECT {','.join('p.' + column for column in columns)} FROM statement_periods p "
            "JOIN first_period f USING(account_id,period_end,source_sequence)" + boundary
            + " ORDER BY p.period_end DESC,p.account_id ASC,p.source_sequence DESC LIMIT ?",
            parameters).fetchall()
        return [dict(zip(columns, row)) for row in rows]

    def document_state_history(
        self, *, as_of: str, limit: int = 200,
        before: tuple[str, int] | None = None,
    ) -> list[dict[str, Any]]:
        """Return bounded document lifecycle state without touching raw blobs."""
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 200:
            raise ValueError("document state limit must be between 1 and 200")
        parameters: list[Any] = [as_of, as_of, as_of, as_of, as_of, as_of]
        boundary = ""
        if before is not None:
            if (not isinstance(before, tuple) or len(before) != 2
                    or not isinstance(before[0], str)
                    or not isinstance(before[1], int)
                    or isinstance(before[1], bool)):
                raise ValueError("document state cursor must be (occurred_at, source_sequence)")
            boundary = " AND (d.occurred_at<? OR (d.occurred_at=? AND d.source_sequence<?))"
            parameters.extend((before[0], before[0], before[1]))
        parameters.append(limit)
        rows = self.connection.execute(
            "SELECT d.source_sequence,d.doc_id,d.occurred_at,d.filename,d.doc_type,"
            "CASE WHEN EXISTS(SELECT 1 FROM statement_periods p WHERE p.doc_id=d.doc_id AND p.period_end<=?) "
            "OR EXISTS(SELECT 1 FROM posted_document_events p WHERE p.doc_id=d.doc_id AND p.occurred_at<=?) THEN 'posted' "
            "WHEN EXISTS(SELECT 1 FROM document_holds h WHERE h.doc_id=d.doc_id AND h.event_type='StatementHeld' AND h.occurred_at<=?) THEN 'held' "
            "WHEN EXISTS(SELECT 1 FROM document_reads r WHERE r.doc_id=d.doc_id AND r.occurred_at<=?) THEN 'read' ELSE 'captured' END state,"
            "EXISTS(SELECT 1 FROM document_reads r WHERE r.doc_id=d.doc_id AND r.occurred_at<=?) read_attempted,"
            "EXISTS(SELECT 1 FROM document_reads r WHERE r.doc_id=d.doc_id AND r.occurred_at<=? AND r.phase='extract' AND r.parse_ok=1) read_parsed "
            "FROM documents d WHERE d.occurred_at<=?" + boundary
            + " ORDER BY d.occurred_at DESC,d.source_sequence DESC LIMIT ?",
            [*parameters[:6], as_of, *parameters[6:]]).fetchall()
        names = ("source_sequence", "doc_id", "occurred_at", "filename", "doc_type",
                 "state", "read_attempted", "read_parsed")
        return [dict(zip(names, row)) for row in rows]

    def review_decision_history(
        self, *, as_of: str, limit: int = 200,
        before: tuple[str, int] | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return review decisions in deterministic newest-first order."""
        return self._review_decision_history(
            as_of=as_of, limit=limit, before=before, status=status)

    def _review_decision_history(
        self, *, as_of: str, limit: int,
        before: tuple[str, int] | None,
        status: str | None,
        event_type: str | None = None,
    ) -> list[dict[str, Any]]:
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 200:
            raise ValueError("review history limit must be between 1 and 200")
        if status not in (None, "declined", "set_aside", "ruled", "corrected"):
            raise ValueError("unknown review status")
        clauses, parameters = ["occurred_at<=?"], [as_of]
        if status is not None:
            clauses.append("status=?"); parameters.append(status)
        if event_type is not None:
            clauses.append("event_type=?"); parameters.append(event_type)
        if before is not None:
            if (not isinstance(before, tuple) or len(before) != 2
                    or not isinstance(before[0], str)
                    or not isinstance(before[1], int)
                    or isinstance(before[1], bool)):
                raise ValueError("review cursor must be (occurred_at, source_sequence)")
            clauses.append("(occurred_at<? OR (occurred_at=? AND source_sequence<?))")
            parameters.extend((before[0], before[0], before[1]))
        parameters.append(limit)
        columns = ("source_sequence", "event_type", "occurred_at", "status",
                   "subject_id", "kind", "body_json", "provenance_doc_id",
                   "provenance_page", "provenance_region", "provenance_note")
        selected = tuple(
            "CASE WHEN length(CAST(body_json AS BLOB))<=? THEN body_json END"
            if column == "body_json" else column for column in columns)
        rows = self.connection.execute(
            f"SELECT {','.join(selected)} FROM review_decisions "
            f"WHERE {' AND '.join(clauses)} "
            "ORDER BY occurred_at DESC,source_sequence DESC LIMIT ?",
            (MAX_REVIEW_DECISION_BODY_BYTES, *parameters)).fetchall()
        if any(row[6] is None for row in rows):
            raise ReadStoreError("review decision body exceeds its byte bound")
        return [dict(zip(columns, row)) for row in rows]

    def question_decision_history(self, *, as_of: str, limit: int = 200,
                                  before: tuple[str, int] | None = None) \
            -> list[dict[str, Any]]:
        """Return durable question declines without mixing in other review work."""
        return self._review_decision_history(
            as_of=as_of, limit=limit, before=before, status="declined",
            event_type="QuestionDeclined")

    def finding_decision_history(self, *, as_of: str, limit: int = 200,
                                 before: tuple[str, int] | None = None) \
            -> list[dict[str, Any]]:
        """Return durable finding set-asides without deriving current findings."""
        return self._review_decision_history(
            as_of=as_of, limit=limit, before=before, status="set_aside",
            event_type="FindingSetAside")

    def question_decline_matches(
        self, question_id: str, *, amount_text: str, count: int, as_of: str,
    ) -> bool:
        """Return whether the latest decline matches the exact current stake."""
        if not question_id:
            raise ValueError("question id is required")
        if not isinstance(amount_text, str):
            raise ValueError("question amount must be exact text")
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            raise ValueError("question count must be a non-negative integer")
        row = self.connection.execute(
            "SELECT CASE WHEN length(CAST(body_json AS BLOB))<=? "
            "THEN body_json END FROM review_decisions "
            "WHERE event_type='QuestionDeclined' AND subject_id=? AND occurred_at<=? "
            "ORDER BY source_sequence DESC LIMIT 1",
            (MAX_REVIEW_DECISION_BODY_BYTES, question_id, as_of)).fetchone()
        if row is None:
            return False
        if row[0] is None:
            raise ReadStoreError("review decision body exceeds its byte bound")
        body = json.loads(row[0])
        return (body.get("amount") == amount_text
                and int(body.get("count", 0)) == count)

    def finding_set_aside_matches(
        self, finding_id: str, *, stake: dict[str, Any], as_of: str,
    ) -> bool:
        """Whether the latest set-aside is for this exact current finding.

        Canonical JSON equality keeps nested evidence, record ordering and
        Decimal text significant, matching ``LedgerProjection.findings``.
        """
        if not finding_id:
            raise ValueError("finding id is required")
        if not isinstance(stake, dict):
            raise ValueError("finding stake must be an object")
        row = self.connection.execute(
            "SELECT CASE WHEN length(CAST(body_json AS BLOB))<=? "
            "THEN body_json END FROM review_decisions "
            "WHERE event_type='FindingSetAside' AND subject_id=? AND occurred_at<=? "
            "ORDER BY source_sequence DESC LIMIT 1",
            (MAX_REVIEW_DECISION_BODY_BYTES, finding_id, as_of)).fetchone()
        if row is None:
            return False
        if row[0] is None:
            raise ReadStoreError("review decision body exceeds its byte bound")
        body = json.loads(row[0])
        return body.get("stake") == stake

    def current_goal_states(self, *, as_of: str, limit: int = 200) \
            -> list[dict[str, Any]]:
        """Fold current goal terms and reservations from this SQL revision.

        This reproduces the canonical goal state machine without constructing
        a ``LedgerProjection`` or reading canonical events.  Event eligibility
        is date-bound, while precedence remains source-sequence order.  The
        result intentionally stops at current state; calendar-dependent plan
        presentation remains a later named derivation.
        """
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 200:
            raise ValueError("current goal limit must be between 1 and 200")
        oversized = self.connection.execute(
            "WITH eligible_goals AS ("
            " SELECT goal_id FROM goal_event_history"
            " WHERE event_type='GoalCreated' AND occurred_at<=? AND goal_id<>''"
            " GROUP BY goal_id ORDER BY goal_id LIMIT ?"
            ") SELECT 1 FROM eligible_goals g"
            " JOIN goal_event_history h ON h.goal_id=g.goal_id"
            " WHERE h.occurred_at<=? GROUP BY h.goal_id HAVING COUNT(*)>? LIMIT 1",
            (as_of, limit, as_of, GOAL_HISTORY_PER_GOAL_LIMIT)).fetchone()
        if oversized is not None:
            raise ReadStoreError(
                f"goal exceeds its {GOAL_HISTORY_PER_GOAL_LIMIT}-event current-view bound")
        # Bound identities before folding their histories.  Goal ids are the
        # canonical current-view order, so only histories eligible for the
        # bounded current snapshot are read.
        from .scalar_bounds import (MAX_SCALAR_BYTES, selected as scalar_selected,
                                    refuse as refuse_scalars)
        columns = ("h.source_sequence", "h.event_type", "h.occurred_at",
                   "h.goal_id", "a.event_id")
        selected, bounds = scalar_selected(columns, ("h.source_sequence",))
        expressions = selected.split(",")
        goal_scalar_lengths = ",".join(
            f"coalesce(length(CAST(json_extract(h.body_json,'$.{name}') AS BLOB)),0)"
            for name in ("goal_id", "kind", "title", "currency", "target_amount",
                         "target_date", "monthly_contribution", "proposal_id",
                         "account_id", "amount", "reason", "state"))
        rows = self.connection.execute(
            f"SELECT {','.join(expressions[:4])},"
            "CASE WHEN length(CAST(h.body_json AS BLOB))<=? AND max(" +
            goal_scalar_lengths + ")<=? "
            f"THEN h.body_json END,{expressions[4]} "
            "FROM goal_event_history h INDEXED BY goal_events_by_source "
            "JOIN applied_events a ON a.sequence=h.source_sequence "
            "WHERE h.occurred_at<=? AND h.goal_id IN ("
            " SELECT goal_id FROM goal_event_history INDEXED BY goal_creates_by_current_id"
            " WHERE event_type='GoalCreated' AND occurred_at<=? AND goal_id<>''"
            " GROUP BY goal_id ORDER BY goal_id LIMIT ?) "
            "ORDER BY h.source_sequence LIMIT ?",
            (*bounds[:3], MAX_GOAL_HISTORY_BODY_BYTES, MAX_SCALAR_BYTES,
             bounds[3], as_of, as_of, limit,
             MAX_GOAL_HISTORY_ROWS + 1)).fetchall()
        if len(rows) > MAX_GOAL_HISTORY_ROWS:
            raise ReadStoreError("goal history exceeds its read row bound")
        refuse_scalars([row[:4] + row[5:] for row in rows], columns,
                       ("h.source_sequence",), label="goal history labels")
        goals: dict[str, dict[str, Any]] = {}
        for _sequence, event_type, occurred_at, goal_id, body_json, event_id in rows:
            if body_json is None:
                raise ReadStoreError("goal history body exceeds its byte bound")
            try:
                body = json.loads(body_json)
            except (TypeError, ValueError, RecursionError) as exc:
                raise ReadStoreError("goal history body is invalid") from exc
            if not isinstance(body, dict):
                raise ReadStoreError("goal history body has the wrong shape")
            if event_type == "GoalCreated":
                if goal_id and goal_id not in goals:
                    goals[goal_id] = {
                        **body, "state": "active", "created_at": occurred_at,
                        "updated_at": occurred_at, "event_ids": [event_id],
                        "reservations": {}, "reservation_history": [], "issues": [],
                    }
                continue
            goal = goals.get(goal_id)
            if goal is None:
                continue
            if event_type == "GoalTermsChanged":
                for key in ("kind", "title", "currency", "target_amount",
                            "target_date", "monthly_contribution",
                            "contribution_day", "proposal_id"):
                    goal[key] = body.get(key, "")
            elif event_type in ("GoalFundsReserved", "GoalFundsReleased"):
                from decimal import Decimal
                account_id = body.get("account_id", "")
                amount = Decimal(body.get("amount", "0"))
                before = Decimal(goal["reservations"].get(account_id, "0"))
                applied = min(amount, max(before, Decimal("0"))) \
                    if event_type == "GoalFundsReleased" else amount
                after = (before - applied if event_type == "GoalFundsReleased"
                         else before + applied)
                goal["reservations"][account_id] = str(max(after, Decimal("0")))
                valid = applied == amount
                if not valid:
                    goal["issues"].append(
                        f"release_exceeds_reserved:{account_id}:{event_id}")
                goal["reservation_history"].append({
                    **body,
                    "kind": ("released" if event_type == "GoalFundsReleased"
                             else "reserved"),
                    "applied_amount": str(applied), "valid": valid,
                    "occurred_at": occurred_at, "event_id": event_id,
                })
            elif event_type == "GoalStateChanged":
                goal["state"] = body.get("state", goal["state"])
                goal["proposal_id"] = body.get("proposal_id", "")
            goal["updated_at"] = occurred_at
            goal["event_ids"].append(event_id)
        return [goals[key] for key in sorted(goals)[:limit]]

    def _goal_reservations_by_account(self, *, as_of: str) -> dict[str, Decimal]:
        """Aggregate every current goal before output pagination is applied.

        The recursive SQL fold emits one final row per goal/account and only
        those final rows cross into Python.  Work is O(R log R), where R is
        eligible reservation/release events, using the goal/order index. Exact
        Decimal callbacks ensure SQLite never coerces money through REAL.
        """
        from .scalar_bounds import MAX_SCALAR_BYTES, refuse as refuse_scalars
        reservation_count, oversized_scalar = self.connection.execute(
            "WITH created AS (SELECT goal_id,MIN(source_sequence) first_create "
            "FROM goal_event_history WHERE event_type='GoalCreated' "
            "AND occurred_at<=? AND goal_id<>'' GROUP BY goal_id) "
            "SELECT COUNT(*),COALESCE(MAX(CASE WHEN "
            "length(CAST(goal_id AS BLOB))>? OR "
            "length(CAST(account_id AS BLOB))>? OR "
            "length(CAST(amount_text AS BLOB))>? THEN 1 ELSE 0 END),0) "
            "FROM (SELECT h.goal_id,h.account_id,h.amount_text "
            "FROM goal_event_history h "
            "JOIN created c ON c.goal_id=h.goal_id "
            "WHERE h.event_type IN ('GoalFundsReserved','GoalFundsReleased') "
            "AND h.occurred_at<=? AND h.source_sequence>c.first_create "
            "AND h.account_id IS NOT NULL LIMIT ?)",
            (as_of, MAX_SCALAR_BYTES, MAX_SCALAR_BYTES, MAX_SCALAR_BYTES,
             as_of, GOAL_RESERVATION_EVENT_LIMIT + 1)).fetchone()
        if reservation_count > GOAL_RESERVATION_EVENT_LIMIT:
            raise ReadStoreError(
                "goal reservations exceed their "
                f"{GOAL_RESERVATION_EVENT_LIMIT}-event fold bound")
        if oversized_scalar:
            raise ReadStoreError("goal reservation field exceeds its scalar byte bound")
        rows = self.connection.execute(
            "WITH RECURSIVE created AS ("
            " SELECT goal_id,MIN(source_sequence) first_create"
            " FROM goal_event_history WHERE event_type='GoalCreated'"
            " AND occurred_at<=? AND goal_id<>'' GROUP BY goal_id"
            "), ordered AS ("
            " SELECT h.goal_id,h.account_id,h.event_type,h.amount_text,"
            " ROW_NUMBER() OVER (PARTITION BY h.goal_id,h.account_id"
            " ORDER BY h.source_sequence) rn"
            " FROM goal_event_history h JOIN created c ON c.goal_id=h.goal_id"
            " WHERE h.event_type IN ('GoalFundsReserved','GoalFundsReleased')"
            " AND h.occurred_at<=? AND h.source_sequence>c.first_create"
            " AND h.account_id IS NOT NULL"
            "), folded(goal_id,account_id,rn,amount_text) AS ("
            " SELECT goal_id,account_id,rn,"
            " viva_decimal_step(NULL,amount_text,event_type) FROM ordered WHERE rn=1"
            " UNION ALL SELECT n.goal_id,n.account_id,n.rn,"
            " viva_decimal_step(f.amount_text,n.amount_text,n.event_type)"
            " FROM folded f JOIN ordered n ON n.goal_id=f.goal_id"
            " AND n.account_id=f.account_id AND n.rn=f.rn+1"
            "), final AS ("
            " SELECT f.account_id,f.amount_text FROM folded f WHERE NOT EXISTS("
            " SELECT 1 FROM folded n WHERE n.goal_id=f.goal_id"
            " AND n.account_id=f.account_id AND n.rn=f.rn+1))"
            " SELECT CASE WHEN length(CAST(account_id AS BLOB))<=? "
            "THEN account_id ELSE 1 END,viva_decimal_sum(amount_text) FROM final"
            " GROUP BY account_id ORDER BY account_id",
            (as_of, as_of, MAX_SCALAR_BYTES)).fetchall()
        refuse_scalars([(row[0],) for row in rows], ("account_id",),
                       label="goal reservation account")
        return {account_id: Decimal(amount) for account_id, amount in rows}

    def current_goal_views(self, *, today: str, limit: int = 200,
                           evidence_as_of: str | None = None) \
            -> list[dict[str, Any]]:
        """Compose the calendar-dependent goal contract from this revision.

        The fold and every account input are read from this immutable SQL
        generation.  Monetary values remain ``Decimal`` objects in the typed
        result; callers choose their own wire encoding at the surface boundary.
        """
        try:
            read_on = date.fromisoformat(str(today)[:10])
        except (TypeError, ValueError):
            raise ValueError("goals require an ISO read date") from None
        evidence = evidence_as_of or today
        states = self.current_goal_states(as_of=evidence, limit=limit)
        balances = self._goal_account_balances(as_of=evidence, limit=200)
        # Availability is account-wide canonical state, not a property of the
        # requested goal page. Aggregate all eligible goals before `limit` can
        # affect which goal views are returned.
        reserved = self._goal_reservations_by_account(as_of=evidence)

        views = []
        for goal in states:
            target = Decimal(goal["target_amount"])
            held = sum((Decimal(value) for value in
                        goal.get("reservations", {}).values()), Decimal("0"))
            remaining = max(target - held, Decimal("0"))
            monthly_text = goal.get("monthly_contribution", "")
            monthly = Decimal(monthly_text) if monthly_text else None
            contribution_day = goal.get("contribution_day")
            target_on = self._goal_date(goal.get("target_date", ""))
            occurrences = self._contribution_dates(
                read_on, contribution_day, through=target_on) \
                if contribution_day is not None and target_on is not None else ()
            required = ((remaining / len(occurrences)).quantize(
                Decimal("0.01"), rounding=ROUND_CEILING)
                if target_on is not None and occurrences and remaining else
                Decimal("0") if target_on is not None and not remaining else None)
            projected = ""
            if monthly is not None and contribution_day is not None and remaining:
                count = int((remaining / monthly).to_integral_value(
                    rounding=ROUND_CEILING))
                projected = self._nth_contribution(
                    read_on, contribution_day, count)
            elif not remaining:
                projected = read_on.isoformat()
            if not remaining:
                status = "complete"
            elif goal.get("state") == "paused":
                status = "paused"
            elif target_on is not None and target_on < read_on:
                status = "at_risk"
            elif monthly is None:
                status = "unscheduled"
            elif target_on is None:
                status = "on_track"
            elif not projected or projected > target_on.isoformat():
                status = "at_risk"
            else:
                status = ("ahead" if any(item > projected for item in occurrences)
                          else "on_track")

            available, exclusions = [], []
            currency = goal.get("currency", "")
            for account_id in sorted(balances):
                account = balances[account_id]
                if account["kind"] not in ("depository", "liability", "investment"):
                    continue
                reason = ("account_not_depository"
                          if account["kind"] != "depository" else
                          "account_not_issuer" if account["origin"] != "issued" else
                          "account_currency_unstated" if not account["currency"] else
                          "account_currency_differs"
                          if account["currency"] != currency else
                          "account_balance_conflicted"
                          if account["grade"] == "conflicted" else "")
                if reason:
                    exclusions.append({
                        "account_id": account_id, "name": account["name"],
                        "currency": account["currency"], "reason": reason})
                    continue
                account_reserved = reserved.get(account_id, Decimal("0"))
                available.append({
                    "account_id": account_id, "name": account["name"],
                    "currency": account["currency"], "balance": account["amount"],
                    "reserved": account_reserved,
                    "available": max(account["amount"] - account_reserved,
                                     Decimal("0")),
                    "grade": account["grade"], "dated": account["dated"],
                    "as_of": today, "provenance": account["provenance"],
                    "explanation": account["explanation"],
                })
            views.append({
                **goal, "status": status, "target_amount": target,
                "monthly_contribution": monthly, "reserved": held,
                "remaining": remaining,
                "reservations": tuple(sorted(
                    (key, Decimal(value)) for key, value in
                    goal.get("reservations", {}).items())),
                "required_monthly": required,
                "projected_completion_date": projected,
                "deviation": (monthly - required
                              if monthly is not None and required is not None else None),
                "next_contribution_date": (self._contribution_dates(
                    read_on, contribution_day, limit=1)[0]
                    if monthly is not None and contribution_day is not None else ""),
                "available_accounts": tuple(available),
                "exclusions": tuple(exclusions),
                "history": tuple({
                    "kind": item.get("kind", ""),
                    "account_id": item.get("account_id", ""),
                    "amount": Decimal(item.get("amount", "0")),
                    "applied_amount": Decimal(item.get(
                        "applied_amount", item.get("amount", "0"))),
                    "reason": item.get("reason", ""),
                    "occurred_at": item.get("occurred_at", ""),
                    "event_id": item.get("event_id", ""),
                    "proposal_id": item.get("proposal_id", ""),
                    "valid": bool(item.get("valid", True)),
                } for item in goal.get("reservation_history", [])),
            })
        return views

    @staticmethod
    def _goal_date(value: str) -> date | None:
        if not value:
            return None
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            raise ValueError("goal target date is not an ISO calendar date") from None

    @staticmethod
    def _contribution_dates(start: date, contribution_day: int, *,
                            through: date | None = None,
                            limit: int | None = None) -> tuple[str, ...]:
        if (not isinstance(contribution_day, int)
                or isinstance(contribution_day, bool)
                or not 1 <= contribution_day <= 28):
            raise ValueError("contribution day must be from 1 to 28")
        if through is None and (not isinstance(limit, int) or limit < 1):
            raise ValueError("an open contribution schedule requires a positive limit")
        year, month = start.year, start.month
        out = []
        while year <= 9999:
            candidate = date(year, month, contribution_day)
            if candidate >= start:
                if through is not None and candidate > through:
                    break
                out.append(candidate.isoformat())
                if limit is not None and len(out) >= limit:
                    break
            year, month = ((year + 1, 1) if month == 12 else (year, month + 1))
        return tuple(out)

    @classmethod
    def _nth_contribution(cls, start: date, contribution_day: int,
                          occurrence: int) -> str:
        first = date.fromisoformat(cls._contribution_dates(
            start, contribution_day, limit=1)[0])
        absolute = first.year * 12 + first.month - 1 + occurrence - 1
        year, month = divmod(absolute, 12)
        return "" if year > 9999 else date(year, month + 1, contribution_day).isoformat()

    def _goal_account_balances(self, *, as_of: str, limit: int) \
            -> dict[str, dict[str, Any]]:
        """Return bounded account/balance inputs with a fixed query count.

        The former implementation issued four statements per account.  This
        fold probes the per-account posting bound first, then loads each input
        family once; its statement count is constant as account cardinality
        grows.
        """
        from .scalar_bounds import selected as scalar_selected, refuse as refuse_scalars

        def bounded_scalars(columns, numeric, tail, parameters):
            selected, bounds = scalar_selected(columns, numeric)
            rows = self.connection.execute(
                f"SELECT {selected} " + tail, (*bounds, *parameters)).fetchall()
            refuse_scalars(rows, columns, numeric,
                           label="goal account observation input")
            return rows

        account_ids = [row[0] for row in bounded_scalars(
            ("account_id",), (), "FROM account_entities e WHERE EXISTS("
            " SELECT 1 FROM accounts a WHERE a.account_id=e.account_id AND a.occurred_at<=?"
            " UNION ALL SELECT 1 FROM balance_observations b"
            " WHERE b.account_id=e.account_id AND b.occurred_at<=?"
            " UNION ALL SELECT 1 FROM postings p JOIN transactions t"
            " ON t.source_sequence=p.source_sequence"
            " WHERE p.account_id=e.account_id AND t.occurred_at<=?)"
            " ORDER BY account_id LIMIT ?", (as_of, as_of, as_of, limit + 1))]
        if len(account_ids) > limit:
            raise ReadStoreError(
                f"goal availability exceeds its {limit}-account bound")
        if not account_ids:
            return {}
        placeholders = ",".join("?" for _ in account_ids)
        parameters = (*account_ids, as_of)
        oversized = self.connection.execute(
            "SELECT p.account_id,COUNT(*) FROM postings p JOIN transactions t"
            " ON t.source_sequence=p.source_sequence"
            f" WHERE p.account_id IN ({placeholders}) AND t.occurred_at<=?"
            " GROUP BY p.account_id HAVING COUNT(*)>? LIMIT 1",
            (*parameters, GOAL_POSTINGS_PER_ACCOUNT_LIMIT)).fetchone()
        if oversized is not None:
            raise ReadStoreError(
                f"account {oversized[0]!r} exceeds its "
                f"{GOAL_POSTINGS_PER_ACCOUNT_LIMIT}-posting goal-view bound")
        opened_rows = bounded_scalars(
            ("a.account_id", "a.kind", "a.name", "a.currency", "a.origin"),
            (), "FROM accounts a"
            f" WHERE a.event_type='AccountOpened' AND a.account_id IN ({placeholders})"
            " AND a.occurred_at<=? AND NOT EXISTS (SELECT 1 FROM accounts newer"
            " WHERE newer.account_id=a.account_id AND newer.event_type='AccountOpened'"
            " AND newer.occurred_at<=? AND newer.source_sequence>a.source_sequence)",
            (*parameters, as_of))
        opening_rows = bounded_scalars(
            ("b.account_id", "b.amount_text", "b.occurred_at",
             "b.provenance_doc_id", "b.provenance_page",
             "b.provenance_region", "b.provenance_note"),
            ("b.provenance_page",),
            "FROM balance_observations b WHERE b.event_type='OpeningBalanceObserved'"
            f" AND b.account_id IN ({placeholders}) AND b.occurred_at<=?"
            " AND NOT EXISTS (SELECT 1 FROM balance_observations earlier"
            " WHERE earlier.account_id=b.account_id"
            " AND earlier.event_type='OpeningBalanceObserved'"
            " AND (earlier.occurred_at<b.occurred_at OR (earlier.occurred_at=b.occurred_at"
            " AND earlier.source_sequence<b.source_sequence)))", parameters)
        closing_rows = bounded_scalars(
            ("b.account_id", "b.amount_text", "b.occurred_at", "b.confirmed_by",
             "b.provenance_doc_id", "b.provenance_page", "b.provenance_region",
             "b.provenance_note"), ("b.provenance_page",),
            "FROM balance_observations b WHERE b.event_type='ClosingBalanceObserved'"
            f" AND b.account_id IN ({placeholders}) AND b.occurred_at<=?"
            " AND NOT EXISTS (SELECT 1 FROM balance_observations later"
            " WHERE later.account_id=b.account_id"
            " AND later.event_type='ClosingBalanceObserved'"
            " AND later.occurred_at<=? AND (later.occurred_at>b.occurred_at OR"
            " (later.occurred_at=b.occurred_at AND later.source_sequence>b.source_sequence)))",
            (*parameters, as_of))
        posting_rows = bounded_scalars(
            ("p.account_id", "p.amount_text"), (),
            "FROM postings p JOIN transactions t"
            " ON t.source_sequence=p.source_sequence"
            f" WHERE p.account_id IN ({placeholders}) AND t.occurred_at<=?"
            " ORDER BY p.account_id,p.source_sequence,p.posting_index", parameters)
        opened_by = {row[0]: row[1:] for row in opened_rows}
        opening_by = {row[0]: row[1:] for row in opening_rows}
        closing_by = {row[0]: row[1:] for row in closing_rows}
        deltas_by: dict[str, list[Decimal]] = {}
        for account_id, amount in posting_rows:
            deltas_by.setdefault(account_id, []).append(Decimal(amount))
        out = {}
        for account_id in account_ids:
            kind, name, currency, origin = opened_by.get(
                account_id, ("", "", "", "issued"))
            opening = opening_by.get(account_id)
            closing = closing_by.get(account_id)
            deltas = deltas_by.get(account_id, ())
            replayed = (Decimal(opening[0]) if opening else Decimal("0")) + sum(
                deltas, Decimal("0"))
            if closing is None:
                amount, grade = replayed, "unverified"
                provenance = opening[2:] if opening else ("", None, "", "")
                explanation = ("Computed by replaying opening balance and transactions; "
                               "no closing figure was attested to check it against.")
                dated = opening[1] if opening else ""
            elif opening is None:
                amount, grade, provenance, dated = Decimal(closing[0]), "verified", closing[3:], closing[1]
                explanation = ("Attested closing balance; no opening figure or "
                               "transactions to corroborate it against.")
            else:
                from vivacore.verify.arithmetic import check_balance_identity
                check = check_balance_identity(Decimal(opening[0]), deltas,
                                               Decimal(closing[0]))
                amount, provenance, dated = Decimal(closing[0]), closing[3:], closing[1]
                grade = ("verified" if closing[2] == "human" else "corroborated") \
                    if check.passed else "conflicted"
                explanation = ("Attested closing balance, confirmed by you and reconciled."
                               if check.passed and closing[2] == "human" else
                               "Attested closing balance, opening plus the period's transactions "
                               "reconcile to it to the cent." if check.passed else
                               "The attested closing balance and the transactions disagree: "
                               f"{check.explain()}. Surfaced, not averaged.")
            out[account_id] = {
                "kind": kind, "name": name, "currency": currency,
                "origin": origin, "amount": amount, "grade": grade,
                "dated": dated,
                "provenance": {"doc_id": provenance[0], "page": provenance[1],
                               "region": provenance[2], "note": provenance[3]},
                "explanation": explanation,
            }
        return out

    def obligation_control_history(
        self, *, as_of: str, limit: int = 200,
        before: tuple[str, int] | None = None,
    ) -> list[dict[str, Any]]:
        """Return rhythm rulings that control obligation/current-period reads."""
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 200:
            raise ValueError("obligation control limit must be between 1 and 200")
        clauses, parameters = ["scope='rhythm'", "occurred_at<=?"], [as_of]
        if before is not None:
            if (not isinstance(before, tuple) or len(before) != 2
                    or not isinstance(before[0], str)
                    or not isinstance(before[1], int)
                    or isinstance(before[1], bool)):
                raise ValueError("obligation control cursor must be (occurred_at, source_sequence)")
            clauses.append("(occurred_at<? OR (occurred_at=? AND source_sequence<?))")
            parameters.extend((before[0], before[0], before[1]))
        parameters.append(limit)
        columns = ("source_sequence", "occurred_at", "subject", "legs_json", "by_actor",
                   "grade", "said", "value_text", "currency", "provenance_doc_id",
                   "provenance_page", "provenance_region", "provenance_note")
        rows = self.connection.execute(
            f"SELECT {','.join(columns)} FROM ruling_history WHERE {' AND '.join(clauses)} "
            "ORDER BY occurred_at DESC,source_sequence DESC LIMIT ?", parameters).fetchall()
        return [dict(zip(columns, row)) for row in rows]

    def goal_event_history(
        self, *, as_of: str, limit: int = 200,
        before: tuple[str, int] | None = None, goal_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return bounded canonical goal/reservation history, newest first."""
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 200:
            raise ValueError("goal history limit must be between 1 and 200")
        clauses, parameters = ["occurred_at<=?"], [as_of]
        if goal_id is not None:
            clauses.append("goal_id=?"); parameters.append(goal_id)
        if before is not None:
            if (not isinstance(before, tuple) or len(before) != 2
                    or not isinstance(before[0], str)
                    or not isinstance(before[1], int) or isinstance(before[1], bool)):
                raise ValueError("goal cursor must be (occurred_at, source_sequence)")
            clauses.append("(occurred_at<? OR (occurred_at=? AND source_sequence<?))")
            parameters.extend((before[0], before[0], before[1]))
        parameters.append(limit)
        columns = ("source_sequence", "event_type", "occurred_at", "goal_id",
                   "account_id", "amount_text", "proposal_id", "body_json",
                   "provenance_doc_id", "provenance_page", "provenance_region",
                   "provenance_note")
        rows = self.connection.execute(
            f"SELECT {','.join(columns)} FROM goal_event_history "
            f"WHERE {' AND '.join(clauses)} "
            "ORDER BY occurred_at DESC,source_sequence DESC LIMIT ?", parameters).fetchall()
        return [dict(zip(columns, row)) for row in rows]

    def goal_proposal_history(
        self, *, as_of: str, limit: int = 200,
        before: tuple[str, int] | None = None, proposal_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return bounded goal-proposal record and resolution history."""
        return self._semantic_history("goal_proposal_history", as_of, limit, before,
                                      "proposal_id", proposal_id)

    def conversation_turn_history(
        self, *, as_of: str, limit: int = 200,
        before: tuple[str, int] | None = None, turn_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return bounded conversation turn open/settle history."""
        return self._semantic_history("conversation_turn_history", as_of, limit, before,
                                      "turn_id", turn_id)

    def conversation_proposal_history(
        self, *, as_of: str, limit: int = 200,
        before: tuple[str, int] | None = None, proposal_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return bounded conversation-proposal record/resolution history."""
        return self._semantic_history("conversation_proposal_history", as_of, limit, before,
                                      "proposal_id", proposal_id)

    def _semantic_history(self, table: str, as_of: str, limit: int,
                          before: tuple[str, int] | None, identity_column: str,
                          identity: str | None) -> list[dict[str, Any]]:
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 200:
            raise ValueError("semantic history limit must be between 1 and 200")
        clauses, parameters = ["occurred_at<=?"], [as_of]
        if identity is not None:
            clauses.append(f"{identity_column}=?"); parameters.append(identity)
        if before is not None:
            if (not isinstance(before, tuple) or len(before) != 2
                    or not isinstance(before[0], str)
                    or not isinstance(before[1], int) or isinstance(before[1], bool)):
                raise ValueError("semantic cursor must be (occurred_at, source_sequence)")
            clauses.append("(occurred_at<? OR (occurred_at=? AND source_sequence<?))")
            parameters.extend((before[0], before[0], before[1]))
        parameters.append(limit)
        columns = ("source_sequence", "event_type", "occurred_at", identity_column,
                   "body_json", "provenance_doc_id", "provenance_page",
                   "provenance_region", "provenance_note")
        rows = self.connection.execute(
            f"SELECT {','.join(columns)} FROM {table} WHERE {' AND '.join(clauses)} "
            "ORDER BY occurred_at DESC,source_sequence DESC LIMIT ?", parameters).fetchall()
        return [dict(zip(columns, row)) for row in rows]

    def movement_history(
        self, *, as_of: str, limit: int = 200,
        before: tuple[str, str] | None = None, account: str | None = None,
        currency: str | None = None, nature: str | None = None,
        category: str | None = None, document: str | None = None,
        merchant: str | None = None, stable_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return a bounded page, filtering current-revision rows by value date.

        ``as_of`` is the page's inclusive movement-date boundary. It is not a
        historical projection horizon; versioned overlay/as-of semantics remain
        the separately gated 4G read contract.
        """
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 200:
            raise ValueError("movement history limit must be between 1 and 200")
        if (before is not None
                and (not isinstance(before, tuple) or len(before) != 2
                     or any(not isinstance(value, str) or not value
                            for value in before))):
            raise ValueError(
                "movement history cursor must be a non-empty (occurred_at, movement_key) tuple")
        clauses, parameters = ["occurred_at<=?"], [as_of]
        for column, value in (("account_id", account), ("currency", currency),
                              ("nature", nature), ("category", category),
                              ("provenance_doc_id", document),
                              ("merchant_key", merchant), ("movement_key", stable_id)):
            if value is not None:
                clauses.append(f"{column}=?"); parameters.append(value)
        if before is not None:
            occurred_at, movement_key = before
            clauses.append("(occurred_at<? OR (occurred_at=? AND movement_key>?))")
            parameters.extend((occurred_at, occurred_at, movement_key))
        parameters.append(limit)
        columns = ("movement_key", "source_sequence", "posting_index", "account_id",
                   "account_kind", "occurred_at", "amount_text", "grade", "currency",
                   "description", "provenance_doc_id", "provenance_page",
                   "provenance_region", "provenance_note", "linked", "nature",
                   "nature_reason", "provisional", "ruling_account", "merchant_key",
                   "category", "subcategory", "category_grade", "subcategory_grade",
                   "category_by", "subcategory_by")
        rows = self.connection.execute(
            f"SELECT {','.join(columns)} FROM movements WHERE {' AND '.join(clauses)} "
            "ORDER BY occurred_at DESC,movement_key ASC LIMIT ?", parameters).fetchall()
        return [dict(zip(columns, row)) for row in rows]

    def transfer_links(self, *, limit: int = 200) -> list[dict[str, Any]]:
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 200:
            raise ValueError("transfer link limit must be between 1 and 200")
        columns = ("movement_a", "movement_b", "grade", "by_actor", "decided_by")
        rows = self.connection.execute(
            f"SELECT {','.join(columns)} FROM transfer_links "
            "ORDER BY movement_a,movement_b LIMIT ?", (limit,)).fetchall()
        return [dict(zip(columns, row)) for row in rows]

    def transfer_suggestions(self, *, limit: int = 200) -> list[dict[str, Any]]:
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 200:
            raise ValueError("transfer suggestion limit must be between 1 and 200")
        rows = self.connection.execute(
            "SELECT movement_a,"
            "CASE WHEN length(CAST(candidates_json AS BLOB))<=? THEN candidates_json END,"
            "CASE WHEN length(CAST(evidence_json AS BLOB))<=? THEN evidence_json END "
            "FROM transfer_suggestions ORDER BY movement_a LIMIT ?",
            (MAX_TRANSFER_SUGGESTION_BYTES, MAX_TRANSFER_SUGGESTION_BYTES,
             limit)).fetchall()
        from .transfer_payload import candidate_keys, decode as decode_transfer
        output = []
        for a, candidates, evidence in rows:
            try:
                output.append({"a": a,
                               "candidates": candidate_keys(decode_transfer(
                                   candidates, list,
                                   maximum_bytes=MAX_TRANSFER_SUGGESTION_BYTES)),
                               "evidence": decode_transfer(
                                   evidence, (list, dict),
                                   maximum_bytes=MAX_TRANSFER_SUGGESTION_BYTES),
                               "status": "suggested"})
            except ValueError as exc:
                raise ReadStoreError("transfer suggestion payload is refused") from exc
        return output


def _resolver_snapshot_hash(
        rows: tuple[tuple[str, str, str], ...],
        *,
        schema_version: int = CONTROL_SCHEMA_VERSION,
        projector_version: str = PROJECTOR_VERSION,
        resolver_version: str = RESOLVER_VERSION,
        domain: bytes = _RESOLVER_SNAPSHOT_DOMAIN) -> str:
    """Bind frozen resolver content to its versioned projection semantics."""
    payload = _canonical({
        "schema_version": schema_version,
        "projector_version": projector_version,
        "resolver_version": resolver_version,
        "profiles": rows,
    })
    return hashlib.sha256(domain + payload).hexdigest()


def _resolver_snapshot(
        *, schema_version: int = CONTROL_SCHEMA_VERSION,
        projector_version: str = PROJECTOR_VERSION,
        resolver_version: str = RESOLVER_VERSION,
) -> tuple[str, tuple[tuple[str, str, str], ...]]:
    """Freeze the complete installed latest-profile mapping canonically."""
    from ..induce_profile import profile_store
    store = profile_store()
    latest: dict[tuple[str, str], Any] = {}
    for profile_id in store.ids():
        profile = store.load(profile_id)
        pair = (profile.institution, profile.kind)
        prior = latest.get(pair)
        if prior is None or profile.id > prior.id:
            latest[pair] = profile
    rows = tuple((institution, kind, _canonical(profile.to_dict()).decode())
                 for (institution, kind), profile in sorted(latest.items()))
    return _resolver_snapshot_hash(
        rows, schema_version=schema_version,
        projector_version=projector_version,
        resolver_version=resolver_version), rows


def _stored_resolver_snapshot(connection) -> tuple[str, tuple[tuple[str, str, str], ...]]:
    """Authenticate canonical frozen profile rows against their declared identity."""
    from merchantcore.profile import Profile
    rows = tuple(connection.execute(
        "SELECT institution, account_kind, profile_json FROM resolver_profiles "
        "ORDER BY institution, account_kind").fetchall())
    for institution, kind, profile_json in rows:
        profile = Profile.from_dict(json.loads(profile_json))
        if ((profile.institution, profile.kind) != (institution, kind)
                or profile_json != _canonical(profile.to_dict()).decode()):
            raise ReadStoreError("read revision resolver snapshot is not canonical")
    semantics = connection.execute(
        "SELECT schema_version, projector_version, resolver_version "
        "FROM projection_meta WHERE singleton=1"
    ).fetchone()
    if semantics is None:
        raise ReadStoreError("read revision resolver semantics are missing")
    schema, projector, resolver = semantics
    return _resolver_snapshot_hash(
        rows, schema_version=schema, projector_version=projector,
        resolver_version=resolver), rows


class ReadStore:
    """One writer coordinator and any number of revision-bound readers."""
    def __init__(self, directory: Path, root_key: bytes):
        self.directory = directory
        # The passphrase-derived root authenticates key.json and is discarded.
        # The coordinator retains only domain-separated operational subkeys.
        self._database_key = bytearray(_database_key(root_key))
        self._manifest_key = bytearray(_mac_key(root_key))
        self._references: dict[str, int] = {}
        self._lifecycle_lock = threading.RLock()
        self._references_lock, self._closed = threading.Lock(), False
        self._highest_epoch = 0
        self._cleanup_error: str | None = None
        self._publication_warning: str | None = None
        self._recovery_manifest: dict[str, Any] | None = None

    @classmethod
    def create(cls, directory: Path, passphrase: str) -> "ReadStore":
        directory = Path(directory)
        if directory.exists() or directory.is_symlink():
            raise ReadStoreError("read-store root already exists")
        directory.mkdir(parents=True, exist_ok=False); _lstat_kind(directory, directory=True)
        _restrict(directory, 0o700)
        metadata, key = _new_metadata(passphrase)
        try:
            _write_json(directory / METADATA_NAME, metadata)
            for name in (GENERATIONS_NAME, QUARANTINE_NAME):
                (directory / name).mkdir(mode=0o700); _restrict(directory / name, 0o700)
            _create_private_file(directory / LOCK_NAME)
            store = cls(directory, key); store.publish(); return store
        except Exception:
            shutil.rmtree(directory, ignore_errors=True); raise
        finally:
            owned = bytearray(key); _wipe(owned)

    @classmethod
    def open(cls, directory: Path, passphrase: str) -> "ReadStore":
        return cls._open(directory, passphrase, allow_invalid_current=False)

    @classmethod
    def open_for_recovery(cls, directory: Path, passphrase: str) -> "ReadStore":
        """Open authenticated metadata while deferring an invalid generation.

        The returned coordinator cannot serve that generation. Its only useful
        next operation is ``synchronize``, which publishes a rebuilt revision.
        """
        return cls._open(directory, passphrase, allow_invalid_current=True)

    @classmethod
    def _open(cls, directory: Path, passphrase: str, *, allow_invalid_current: bool) -> "ReadStore":
        directory, key = Path(directory), None
        try:
            _lstat_kind(directory, directory=True)
            for name, is_directory in ((METADATA_NAME, False), (LOCK_NAME, False),
                                       (GENERATIONS_NAME, True), (QUARANTINE_NAME, True)):
                _lstat_kind(directory / name, directory=is_directory)
            for entry in directory.iterdir():
                if entry.is_symlink():
                    raise ReadStoreError(f"unsafe read-store path: {entry.name}")
            for entry in (directory / QUARANTINE_NAME).iterdir():
                if entry.is_symlink():
                    raise ReadStoreError(f"unsafe read-store path: {entry.name}")
            _restrict(directory, 0o700); _restrict(directory / METADATA_NAME, 0o600)
            key = _open_metadata(_read_json_file(directory, directory / METADATA_NAME), passphrase)
            store = cls(directory, key)
            try:
                manifest = store._current_manifest(recover=True)
            except Exception:
                if not allow_invalid_current:
                    raise
                value = _read_json_file(directory, directory / CURRENT_NAME)
                manifest = _verify_manifest(value, store._manifest_key)
                store._recovery_manifest = manifest
            store._highest_epoch = manifest["epoch"]
            if store._recovery_manifest is None:
                store._cleanup_best_effort()
            return store
        except ReadStoreError: raise
        except Exception as exc: raise ReadStoreError("encrypted read store could not be opened") from exc
        finally:
            if key is not None: owned = bytearray(key); _wipe(owned)

    @property
    def current_generation(self) -> str:
        self._ensure_open(); return self._current_manifest()["generation"]

    @property
    def cleanup_error(self) -> str | None:
        """Most recent best-effort cleanup error after a successful commit."""
        return self._cleanup_error

    @property
    def publication_warning(self) -> str | None:
        """Durability warning recorded after an already-committed pointer replace."""
        return self._publication_warning

    @property
    def connection(self):
        raise ReadStoreError("read-store generations are immutable; use open_reader")

    def open_reader(self) -> ReadRevision:
        with self._lifecycle_lock:
            self._ensure_open(); manifest = self._current_manifest()
            generation = manifest["generation"]
            self._validate_generation_path(generation)
            with self._references_lock:
                self._references[generation] = self._references.get(generation, 0) + 1
            try:
                connection = _connect(self._path(generation) / DATABASE_NAME,
                                      self._database_key, readonly=True)
                self._assert_manifest_matches(connection, manifest)
                return ReadRevision(self, generation, connection)
            except Exception:
                self._release(generation); raise

    def authenticated_source_identity(self, revision: ReadRevision) -> dict[str, Any]:
        """Return source identity only after manifest and generation authentication."""
        if revision._store is not self or revision._closed:
            raise ReadStoreError("read revision does not belong to this store")
        manifest = self._current_manifest()
        if manifest["generation"] != revision.generation:
            raise ReadStoreError("read revision is no longer current")
        self._assert_manifest_matches(revision.connection, manifest)
        return dict(manifest["source"])

    def synchronize(self, event_store, apply_event: Callable[[Any, Any], None] | None = None,
                    *, schema_version: int = CONTROL_SCHEMA_VERSION,
                    projector_version: str = PROJECTOR_VERSION,
                    resolver_version: str = RESOLVER_VERSION,
                    as_of_version: str = AS_OF_VERSION,
                    fail_at: str | None = None) -> SynchronizeResult:
        """Publish an equal, incrementally caught-up, or rebuilt revision.

        EventStore alone authenticates canonical prefixes and supplies events.
        A projection failure leaves its previous immutable generation current;
        callers must report the raised degraded state and must never replay the
        already-committed event write.
        """
        from ..ledger.store import CommittedIdentity, CommittedPrefixMismatch

        if resolver_version != RESOLVER_VERSION:
            raise ReadStoreError(
                f"resolver {resolver_version!r} is not registered for materialization")

        versions = (schema_version, projector_version, resolver_version,
                    as_of_version, METADATA_VERSION)
        resolver_content_hash, resolver_profiles = _resolver_snapshot(
            schema_version=schema_version,
            projector_version=projector_version,
            resolver_version=resolver_version)
        try:
            with self.open_reader() as reader:
                control = self._control_state(reader.connection)
        except Exception:
            control = None

        try:
            if (control is not None and control["versions"] == versions
                    and control["resolver_content_hash"] == resolver_content_hash):
                prefix = CommittedIdentity(
                    control["count"], control["head"],
                    control["end_offset"], control["cursor_mac"])
                try:
                    suffix = event_store.committed_suffix_after(prefix)
                except CommittedPrefixMismatch:
                    suffix = None
                if suffix is not None:
                    if not suffix.events:
                        return SynchronizeResult(
                            "equal", self.current_generation,
                            suffix.identity.count, 0)
                    generation = self.publish(
                        lambda connection: self._apply_committed_events(
                            connection, suffix.events, suffix.identity, versions,
                            apply_event, fail_at, resolver_content_hash,
                            resolver_profiles),
                        copy_current=True,
                        fail_at=("after_build" if fail_at == "after_database_commit"
                                 else None))
                    return SynchronizeResult(
                        "caught_up", generation, suffix.identity.count,
                        len(suffix.events))

            snapshot = event_store.committed_snapshot()
            generation = self.publish(
                lambda connection: self._apply_committed_events(
                    connection, snapshot.events, snapshot.identity, versions,
                    apply_event, fail_at, resolver_content_hash,
                    resolver_profiles),
                fail_at=("after_build" if fail_at == "after_database_commit"
                         else None))
            return SynchronizeResult(
                "rebuilt", generation, snapshot.identity.count,
                len(snapshot.events))
        except Exception as exc:
            if isinstance(exc, ReadStoreDegraded):
                raise
            raise ReadStoreDegraded(
                "canonical events are committed but the read store is degraded; "
                "catch up or rebuild before serving current reads") from exc

    @staticmethod
    def _control_state(connection) -> dict[str, Any]:
        row = connection.execute(
            "SELECT schema_version, projector_version, resolver_version, "
            "as_of_version, key_derivation_version, source_count, source_head, "
            "source_end_offset, source_cursor_mac, last_sequence, last_hash, "
            "applied_events_digest, resolver_content_hash "
            "FROM projection_meta WHERE singleton=1"
        ).fetchone()
        if row is None:
            raise ReadStoreError("read-store projection metadata is missing")
        count, head, end_offset, cursor_mac, last_sequence, last_hash, stored_digest, resolver_hash = row[5:]
        rows = connection.execute(
            "SELECT sequence, event_id, record_hash, event_type FROM applied_events "
            "ORDER BY sequence"
        ).fetchall()
        terminal_hash = rows[-1][2] if rows else "0" * 64
        identities_are_canonical = all(
            sequence == expected
            and isinstance(event_id, str) and bool(event_id)
            and event_id == event_id.strip()
            and isinstance(record_hash, str)
            and re.fullmatch(r"[0-9a-f]{64}", record_hash) is not None
            and isinstance(event_type, str) and bool(event_type)
            and event_type == event_type.strip()
            for expected, (sequence, event_id, record_hash, event_type) in enumerate(rows)
        )
        schema, projector = row[:2]
        computed_digest = _applied_events_genesis(schema, projector)
        if identities_are_canonical:
            for sequence, event_id, record_hash, event_type in rows:
                computed_digest = _extend_applied_events_digest(
                    computed_digest, sequence, event_id, record_hash, event_type)
        if (isinstance(count, bool) or not isinstance(count, int) or count < 0
                or len(rows) != count or not identities_are_canonical
                or last_sequence != count - 1
                or not isinstance(head, str)
                or re.fullmatch(r"[0-9a-f]{64}", head) is None
                or not isinstance(last_hash, str)
                or re.fullmatch(r"[0-9a-f]{64}", last_hash) is None
                or head != last_hash or terminal_hash != head
                or not isinstance(stored_digest, str)
                or not hmac.compare_digest(stored_digest, computed_digest)
                or not isinstance(resolver_hash, str)
                or re.fullmatch(r"[0-9a-f]{64}", resolver_hash) is None):
            raise ReadStoreError("read-store applied-event identity is corrupt")
        if (not isinstance(end_offset, int) or end_offset < 0
                or not isinstance(cursor_mac, str)
                or re.fullmatch(r"[0-9a-f]{64}", cursor_mac) is None):
            raise ReadStoreError("read-store event cursor is corrupt")
        return {"versions": tuple(row[:5]), "count": count, "head": head,
                "end_offset": end_offset, "cursor_mac": cursor_mac,
                "resolver_content_hash": resolver_hash}

    @staticmethod
    def _apply_committed_events(connection, entries, identity, versions,
                                apply_event, fail_at, resolver_content_hash,
                                resolver_profiles):
        schema, projector, resolver, as_of, key_version = versions
        existing, applied_events_digest = connection.execute(
            "SELECT source_count, applied_events_digest FROM projection_meta WHERE singleton=1"
        ).fetchone()
        if existing == 0:
            applied_events_digest = _applied_events_genesis(schema, projector)
        if fail_at == "before_event_rows":
            raise RuntimeError("injected read-store projection failure: before_event_rows")
        for offset, entry in enumerate(entries):
            expected = existing + offset
            if entry.sequence != expected:
                raise ReadStoreError("committed suffix is not contiguous")
            ReadStore._materialize_event(connection, entry)
            if apply_event is not None:
                apply_event(connection, entry)
            connection.execute(
                "INSERT INTO applied_events(sequence, event_id, record_hash, event_type) "
                "VALUES(?, ?, ?, ?)",
                (entry.sequence, entry.event_id, entry.record_hash,
                 entry.event.event_type))
            applied_events_digest = _extend_applied_events_digest(
                applied_events_digest, entry.sequence, entry.event_id, entry.record_hash,
                entry.event.event_type)
            if fail_at == "during_event_rows" and offset == 0:
                raise RuntimeError(
                    "injected read-store projection failure: during_event_rows")
        ReadStore._refresh_movements(connection)
        if fail_at == "before_metadata_advance":
            raise RuntimeError(
                "injected read-store projection failure: before_metadata_advance")
        last_sequence = identity.count - 1
        connection.execute("""UPDATE projection_meta SET
            schema_version=?, projector_version=?, resolver_version=?,
            as_of_version=?, key_derivation_version=?, source_count=?,
            source_head=?, source_end_offset=?, source_cursor_mac=?,
            last_sequence=?, last_hash=?, applied_events_digest=?,
            resolver_content_hash=? WHERE singleton=1""",
            (schema, projector, resolver, as_of, key_version, identity.count,
             identity.head_hash, identity.end_offset, identity.cursor_mac,
             last_sequence, identity.head_hash, applied_events_digest,
             resolver_content_hash))
        connection.execute("DELETE FROM resolver_profiles")
        connection.executemany(
            "INSERT INTO resolver_profiles(institution, account_kind, profile_json) "
            "VALUES(?, ?, ?)", resolver_profiles)
        from .account_ledger import materialize_component_index
        materialize_component_index(connection)
        if fail_at == "after_mapping_digest_advance":
            raise RuntimeError(
                "injected read-store projection failure: after_mapping_digest_advance")
        if fail_at == "after_metadata_advance":
            raise RuntimeError(
                "injected read-store projection failure: after_metadata_advance")

    @staticmethod
    def _refresh_movements(connection):
        """Rebuild revision-derived movement rows from normalized SQL history.

        Backfills can change canonical occurrence indexes, account metadata,
        and overlays retroactively. Rebuilding this disposable table inside the
        generation transaction is deterministic while reads remain bounded.
        """
        from ..ledger.movement_identity import movement_key
        from decimal import Decimal
        from merchantcore.profile import Profile, is_inducible
        from merchantcore.taxonomy import subcategory_identity
        from ..ledger.identity import (account_tokens, distinctive_tokens,
                                       text_has_token, usable_full_number)
        from ..ledger.merchant_keys import resolve_keys
        from ..ledger.merchants import normalize_merchant

        connection.execute("DELETE FROM account_ledger_component_index")
        connection.execute("DELETE FROM movement_tags")
        connection.execute("DELETE FROM movements")
        connection.execute("DELETE FROM transfer_links")
        connection.execute("DELETE FROM transfer_suggestions")
        accounts = {}
        for sequence, event_type, account, kind, currency, institution, number, name, origin in connection.execute(
                "SELECT source_sequence,event_type,account_id,kind,currency,institution,"
                "account_number,name,origin FROM accounts ORDER BY source_sequence"):
            if event_type == "AccountOpened":
                accounts[account] = {"kind": kind or "", "currency": currency or "",
                                     "institution": institution or "", "number": number or "",
                                     "name": name or "", "origin": origin or "issued"}
            else:
                state = accounts.setdefault(account, {"kind": "", "currency": "",
                    "institution": "", "number": "", "name": "", "origin": "issued"})
                if usable_full_number(number or "") and not usable_full_number(state["number"]):
                    state["number"] = number
                state["institution"] = state["institution"] or institution or ""

        live_links, suggestions = {}, {}
        for _seq, event_type, a, b, candidates_json, grade, decided_by, by_actor, evidence_json in connection.execute(
                "SELECT source_sequence,event_type,movement_a,movement_b,candidates_json,"
                "grade,decided_by,by_actor,evidence_json FROM transfer_history "
                "ORDER BY source_sequence"):
            if event_type == "TransferSuggested":
                suggestions[a] = (json.loads(candidates_json), evidence_json)
                continue
            pair = frozenset((a, b))
            live_links[pair] = ((grade, by_actor, decided_by)
                                if event_type == "TransferLinked" else None)
            suggestions.pop(a, None); suggestions.pop(b, None)
        linked = {key for pair, info in live_links.items() if info is not None for key in pair}
        for pair, info in live_links.items():
            if info is None: continue
            ordered = sorted(pair); a, b = ordered[0], ordered[-1]
            connection.execute("INSERT INTO transfer_links VALUES(?,?,?,?,?)",
                               (a, b, *info))
        for a, (candidates, evidence_json) in suggestions.items():
            if a in linked or (candidates and all(candidate in linked for candidate in candidates)):
                continue
            connection.execute("INSERT INTO transfer_suggestions VALUES(?,?,?)",
                               (a, _canonical(candidates).decode(), evidence_json))

        rank = {"verified": 3, "corroborated": 2, "unverified": 1, "": 0}
        categories = {}
        for row in connection.execute(
                "SELECT movement_key,descriptor,category,subcategory,nature,grade,by_actor,"
                "category_grade,subcategory_grade,category_by,subcategory_by "
                "FROM category_history ORDER BY source_sequence"):
            key, descriptor, category, subcategory, nature, grade, by_actor, cg, sg, cb, sb = row
            incoming = {"descriptor": descriptor, "category": category,
                        "subcategory": subcategory, "nature": nature, "grade": grade,
                        "by": by_actor, "category_grade": cg, "subcategory_grade": sg,
                        "category_by": cb, "subcategory_by": sb}
            prior = categories.get(key)
            if prior is None:
                categories[key] = incoming; continue
            cat = incoming if rank.get(cg, 0) >= rank.get(prior["category_grade"], 0) else prior
            sub = incoming if rank.get(sg if subcategory else "", 0) >= rank.get(
                prior["subcategory_grade"] if prior["subcategory"] else "", 0) else prior
            categories[key] = {**cat, "subcategory": sub["subcategory"],
                               "subcategory_grade": sub["subcategory_grade"],
                               "subcategory_by": sub["subcategory_by"],
                               "grade": min((cat["category_grade"], sub["subcategory_grade"]),
                                            key=lambda value: rank.get(value, 0)),
                               "by": (cat["category_by"] if cat["category_by"] == sub["subcategory_by"]
                                      else "mixed")}

        merchants = {}
        alias_owner, conflicted = {}, set()
        for row in connection.execute(
                "SELECT merchant_key,category,subcategory,canonical_name,attributes_json,"
                "aliases_json,grade,by_actor,category_grade,subcategory_grade,category_by,"
                "subcategory_by FROM merchant_history ORDER BY source_sequence"):
            key, category, subcategory, canonical_name, attrs, aliases, grade, by_actor, cg, sg, cb, sb = row
            incoming = {"merchant": key, "category": category, "subcategory": subcategory,
                        "canonical_name": canonical_name, "attributes": json.loads(attrs),
                        "aliases": json.loads(aliases), "grade": grade, "by": by_actor,
                        "category_grade": cg, "subcategory_grade": sg,
                        "category_by": cb, "subcategory_by": sb}
            prior = merchants.get(key)
            if prior is None or rank.get(grade, 0) >= rank.get(prior["grade"], 0):
                incoming["aliases"] = sorted(set(incoming["aliases"]) |
                                             set((prior or {}).get("aliases", ())))
                merchants[key] = incoming
            elif incoming["aliases"]:
                prior["aliases"] = sorted(set(prior.get("aliases", ())) |
                                           set(incoming["aliases"]))
        for key, record in merchants.items():
            for alias in record.get("aliases", ()):
                if alias in alias_owner and alias_owner[alias] != key: conflicted.add(alias)
                else: alias_owner[alias] = key

        rulings = {}
        category_aliases, tag_aliases = {}, {}
        for scope, subject, legs, grade, same_as in connection.execute(
                "SELECT scope,subject,legs_json,grade,same_as FROM ruling_history "
                "ORDER BY source_sequence"):
            incoming = {"scope": scope, "subject": subject, "legs": json.loads(legs),
                        "grade": grade, "same_as": same_as}
            prior = rulings.get((scope, subject))
            if prior is None or grade == "verified" or prior["grade"] != "verified":
                rulings[(scope, subject)] = incoming
            if same_as and scope in ("category", "tag"):
                (category_aliases if scope == "category" else tag_aliases)[subject] = same_as

        def canonical(aliases, label, identity=lambda value: (value or "").strip().lower()):
            start = identity(label); current = start; seen = set()
            normalized, collisions = {}, set()
            for raw, target in sorted(aliases.items()):
                key, value = identity(raw), identity(target)
                if key == value: continue
                if key in normalized and normalized[key] != value: collisions.add(key)
                else: normalized[key] = value
            if current not in normalized:
                return (label or "").strip()
            while current in normalized:
                if current in seen or current in collisions: return start
                seen.add(current); current = normalized[current]
            return start if current in collisions else current

        profiles = {(institution, kind): Profile.from_dict(json.loads(profile_json))
                    for institution, kind, profile_json in connection.execute(
                        "SELECT institution,account_kind,profile_json FROM resolver_profiles")}
        def profile_for(institution, kind):
            return profiles.get((institution, kind)) if is_inducible(kind) else None
        resolver_inputs = [(account, state["institution"], state["kind"], description)
                           for account, description in connection.execute(
                               "SELECT p.account_id,t.description FROM postings p "
                               "JOIN transactions t USING(source_sequence) "
                               "GROUP BY p.account_id,t.description "
                               "ORDER BY MIN(t.source_sequence),MIN(p.posting_index)")
                           for state in [accounts.get(account, {})]
                           if state.get("kind") in ("depository", "liability", "investment")]
        resolved = resolve_keys(resolver_inputs, profile_for=profile_for)
        own_raw = {account: account_tokens(state["institution"], state["number"], state["name"])
                   for account, state in accounts.items()
                   if state["kind"] in ("depository", "liability", "investment")
                   and state["origin"] == "issued"}
        own_tokens = distinctive_tokens(
            own_raw, {account: accounts[account]["institution"] for account in own_raw})
        account_aliases = {alias: account for alias, account in connection.execute(
            "SELECT alias_key,account_id FROM account_alias_history WHERE learn_signal=1 "
            "ORDER BY source_sequence")}

        latest_tags = {}
        for scope, subject, tags_json in connection.execute(
                "SELECT scope,subject,tags_json FROM tag_history ORDER BY source_sequence"):
            latest_tags[(scope, subject)] = json.loads(tags_json)

        counts = {}
        rows = connection.execute(
            "SELECT t.source_sequence,p.posting_index,p.account_id,t.occurred_at,p.amount_text,"
            "p.grade,t.description,t.provenance_doc_id,t.provenance_page,"
            "t.provenance_region,t.provenance_note FROM transactions t JOIN postings p "
            "ON p.source_sequence=t.source_sequence ORDER BY p.account_id,t.occurred_at,"
            "t.description,p.amount_text,t.source_sequence,p.posting_index").fetchall()
        for seq, pindex, account, occurred, amount, grade, description, doc, page, region, note in rows:
            state = accounts.get(account, {})
            kind, currency = state.get("kind", ""), state.get("currency", "")
            if kind not in ("depository", "liability", "investment"):
                continue
            signature = (doc, account, occurred, amount, description)
            occurrence = counts.get(signature, 0); counts[signature] = occurrence + 1
            key = movement_key(doc, account, occurred, amount, description, occurrence)
            overlay = categories.get(key, {})
            is_linked = key in linked
            descriptor_key = normalize_merchant(description)
            brand_key = resolved.get((account, description), descriptor_key)
            structural = resolved.candidates.get((account, description), ())
            canonical_id = next((alias_owner[candidate] for candidate in structural
                                 if candidate in alias_owner and candidate not in conflicted), "")
            merchant_keys = tuple(dict.fromkeys(value for value in
                                  (canonical_id, brand_key, *structural, descriptor_key) if value)) or ("",)
            merchant = merchant_keys[0]
            merchant_record = None
            for candidate in merchant_keys:
                found = merchants.get(candidate)
                if found is not None and (merchant_record is None or
                        rank.get(found["grade"], 0) > rank.get(merchant_record["grade"], 0)):
                    merchant_record = found
            effective = overlay
            if overlay.get("by") == "default" and merchant_record:
                effective = dict(merchant_record)
                if not effective.get("subcategory"):
                    effective.update({"subcategory": overlay.get("subcategory", ""),
                                      "subcategory_grade": overlay.get("subcategory_grade", ""),
                                      "subcategory_by": overlay.get("subcategory_by", ""),
                                      "by": "mixed", "grade": overlay.get("grade", "")})
            elif not overlay: effective = merchant_record or {}
            effective = dict(effective)
            if effective.get("category"):
                effective["category"] = canonical(category_aliases, effective["category"])
            if effective.get("subcategory"):
                folded = subcategory_identity(effective["subcategory"])
                effective["subcategory"] = canonical(
                    category_aliases, folded, subcategory_identity)
            movement_ruling = rulings.get(("movement", key))
            merchant_ruling = None
            for candidate in merchant_keys:
                found = rulings.get(("merchant", candidate))
                if found is not None and (merchant_ruling is None or
                        rank.get(found["grade"], 0) > rank.get(merchant_ruling["grade"], 0)):
                    merchant_ruling = found
            ruling = movement_ruling or merchant_ruling
            nature, reason, provisional, ruling_account = "spending", "default", 0, ""
            if is_linked:
                nature, reason = "transfer", "linked"
            elif ruling and ruling["legs"]:
                natures = {"expense": "spending", "income": "spending",
                           "asset": "transfer", "liability": "settlement"}
                found = {natures.get(leg.get("major"), "spending") for leg in ruling["legs"]}
                nature = next(iter(found)) if len(found) == 1 else "mixed"
                reason, provisional = "ruling", int(nature == "mixed")
                for major in ("liability", "asset"):
                    path = next((leg.get("account", "") for leg in ruling["legs"]
                                 if leg.get("major") == major and leg.get("account")), "")
                    if path:
                        ruling_account = account_aliases.get(path, path); break
            elif overlay.get("nature") in ("transfer", "settlement", "spending"):
                nature, reason = overlay["nature"], "ruling"
            elif ((merchant_record or {}).get("attributes") or {}).get("nature") in (
                    "transfer", "settlement", "spending"):
                nature, reason = merchant_record["attributes"]["nature"], "ruling"
            elif any(other != account and any(text_has_token(description.lower(), token)
                                              for token in tokens)
                     for other, tokens in own_tokens.items()):
                nature, reason = "transfer", "own_account"
            else:
                effect = Decimal(amount) * (Decimal("-1") if kind == "liability" else Decimal("1"))
                want = "inflow" if effect > 0 else "outflow"
                implications = ((merchant_record or {}).get("attributes") or {}).get("implies") or []
                implied = next((item for item in implications if item.get("on") in (want, "both")), None)
                if implied and implied.get("major") in ("asset", "liability"):
                    nature = "transfer" if implied["major"] == "asset" else "settlement"
                    reason, provisional = "category_hint", int(implied.get("confidence") != "forced")
            values = (key, seq, pindex, account, kind, occurred, amount, grade, currency,
                      description, doc, page, region, note, int(is_linked), nature, reason,
                      provisional,
                      ruling_account, merchant, effective.get("category", ""),
                      effective.get("subcategory", ""), effective.get("category_grade", ""),
                      effective.get("subcategory_grade", ""), effective.get("category_by", ""),
                      effective.get("subcategory_by", ""))
            connection.execute("INSERT INTO movements VALUES(" + ",".join("?" * len(values)) + ")", values)
            own = latest_tags.get(("movement", key), ())
            shared = next((latest_tags[("merchant", candidate)] for candidate in merchant_keys
                           if latest_tags.get(("merchant", candidate))), ())
            for source, tags in (("movement", own), ("merchant", shared)):
                for tag in sorted({canonical(tag_aliases, (value or "").strip().lower())
                                   for value in tags if value}):
                    connection.execute("INSERT OR IGNORE INTO movement_tags VALUES(?,?,?)",
                                       (key, tag, source))

    def publish(self, build: Callable[[Any], None] | None = None, *, fail_at: str | None = None,
                lock_timeout: float = WRITER_LOCK_TIMEOUT_SECONDS,
                copy_current: bool = False) -> str:
        self._ensure_open()
        with _WriterLock(self.directory / LOCK_NAME, lock_timeout):
            with self._lifecycle_lock:
                target = self.directory / CURRENT_NAME
                if target.exists() or target.is_symlink() or self._highest_epoch:
                    previous = self._recovery_manifest or self._current_manifest()
                else:
                    previous = None
                epoch = 1 if previous is None else previous["epoch"] + 1
            generation, connection, published, temporary = _generation_id(), None, False, None
            path = self._path(generation); path.mkdir(mode=0o700); _restrict(path, 0o700)
            database = path / DATABASE_NAME; _create_private_file(database)
            try:
                if copy_current:
                    if previous is None:
                        raise ReadStoreError("cannot copy a missing read-store revision")
                    source_database = self._path(previous["generation"]) / DATABASE_NAME
                    shutil.copyfile(source_database, database)
                    _restrict(database, 0o600)
                connection = _connect(database, self._database_key)
                if copy_current:
                    connection.execute("UPDATE projection_meta SET state='building' "
                                       "WHERE singleton=1")
                else:
                    self._create_schema(connection, "building")
                if build: build(connection)
                connection.commit(); self._inject(fail_at, "after_build")
                connection.execute("UPDATE projection_meta SET state='ready', publication_epoch=? "
                                   "WHERE singleton=1", (epoch,))
                connection.commit(); self._inject(fail_at, "after_ready")
                connection.close(); connection = None; _restrict(database, 0o600)
                descriptor = os.open(database, os.O_RDONLY)
                try: os.fsync(descriptor)
                finally: os.close(descriptor)
                _fsync_dir(path); self._inject(fail_at, "after_database_fsync")
                verified = _connect(database, self._database_key, readonly=True)
                try:
                    self._assert_ready(verified)
                    source = self._source_identity(verified)
                finally: verified.close()
                temporary = self.directory / f"current.{generation}.tmp"
                _write_json(temporary, _manifest(generation, epoch, source, self._manifest_key))
                self._inject(fail_at, "before_manifest_replace")
                with self._lifecycle_lock:
                    intended = _manifest(generation, epoch, source, self._manifest_key)
                    try:
                        _replace_manifest(temporary, self.directory / CURRENT_NAME)
                    except Exception:
                        # A platform may report an error after the rename has
                        # taken effect.  Resolve that uncertainty from the
                        # authenticated pointer before deciding that the new
                        # generation is disposable.
                        try:
                            observed = self._current_manifest()
                        except Exception:
                            observed = None
                        if observed != {name: intended[name] for name in
                                       ("v", "generation", "epoch", "source")}:
                            raise
                    # os.replace is the commit point.  From here onward the
                    # generation is live and must never be quarantined, even
                    # if syncing the containing directory reports a failure.
                    published = True
                    self._recovery_manifest = None
                    self._highest_epoch = epoch
                    try:
                        _fsync_dir(self.directory)
                        self._publication_warning = None
                    except Exception as exc:
                        self._publication_warning = f"{type(exc).__name__}: {exc}"
                self._inject(fail_at, "after_manifest_replace")
            except Exception:
                if connection: _close_after_failure(connection)
                if not published:
                    if temporary is not None: temporary.unlink(missing_ok=True)
                    self._quarantine(path)
                raise
            # Publication is the commit point. Cleanup cannot turn success into
            # failure and is retried by later open/publish/release operations.
            self._cleanup_best_effort()
            return generation

    def cleanup(self):
        with self._lifecycle_lock:
            self._cleanup_locked()

    def _cleanup_locked(self):
        self._ensure_open(); current = self._current_manifest(recover=True)["generation"]
        ready = []
        # With a valid current pointer, any remaining candidate was never the
        # publication boundary and cannot supersede it on a later restart.
        for temporary in self.directory.glob("current.g-*.tmp"):
            _lstat_kind(temporary, directory=False)
            temporary.unlink(missing_ok=True)
        for path in list((self.directory / GENERATIONS_NAME).iterdir()):
            if path.is_symlink():
                raise ReadStoreError(f"unsafe read-store path: {path.name}")
            if path.name == current or self._referenced(path.name): continue
            if not path.is_dir() or not _valid_generation(path.name):
                self._quarantine(path); continue
            try:
                self._validate_generation_path(path.name)
                connection = _connect(path / DATABASE_NAME, self._database_key, readonly=True)
                try:
                    self._assert_ready(connection)
                    epoch = self._publication_epoch(connection)
                finally: connection.close()
                ready.append((epoch, path.name, path))
            except Exception: self._quarantine(path)
        ready.sort(reverse=True)
        for _, _, path in ready[RETAIN_SUPERSEDED_GENERATIONS:]: self._quarantine(path)
        quarantine = self.directory / QUARANTINE_NAME
        for path in quarantine.iterdir():
            if path.is_symlink():
                raise ReadStoreError(f"unsafe read-store path: {path.name}")
        old = sorted(quarantine.iterdir(),
                     key=lambda p: p.stat().st_mtime_ns, reverse=True)
        for path in old[RETAIN_QUARANTINED_GENERATIONS:]:
            if path.is_dir(): shutil.rmtree(path)
            else: path.unlink()
        _fsync_dir(quarantine); _fsync_dir(self.directory / GENERATIONS_NAME)

    def _cleanup_best_effort(self):
        try:
            self.cleanup()
            self._cleanup_error = None
        except Exception as exc:
            self._cleanup_error = f"{type(exc).__name__}: {exc}"

    def close(self):
        if self._closed: return
        with self._references_lock:
            if self._references: raise ReadStoreError("cannot close read store while revisions are open")
        self._closed = True; _wipe(self._database_key); _wipe(self._manifest_key)

    def __enter__(self): return self
    def __exit__(self, *_exc): self.close()

    def _path(self, generation):
        if not _valid_generation(generation): raise ReadStoreError("invalid generation identity")
        path = self.directory / GENERATIONS_NAME / generation
        _contained(self.directory / GENERATIONS_NAME, path)
        return path

    def _current_manifest(self, recover=False):
        target = self.directory / CURRENT_NAME
        if target.is_symlink(): raise ReadStoreError("unsafe read-store path: current.json")
        if not target.exists() and recover:
            candidates = []
            for temporary in self.directory.iterdir():
                if not (temporary.name.startswith("current.g-") and temporary.name.endswith(".tmp")):
                    continue
                try:
                    manifest = _verify_manifest(_read_json_file(self.directory, temporary),
                                                self._manifest_key)
                    self._validate_manifest_generation(manifest)
                    candidates.append((manifest, temporary))
                except Exception:
                    # Do not mutate suspicious paths during resolution.
                    continue
            if len(candidates) != 1:
                reason = "ambiguous" if candidates else "missing"
                raise ReadStoreError(f"current read-store manifest recovery is {reason}")
            manifest, temporary = candidates[0]
            if manifest["epoch"] < self._highest_epoch:
                raise ReadStoreError("read-store manifest rollback detected")
            _replace_manifest(temporary, target); _fsync_dir(self.directory)
        value = _read_json_file(self.directory, target)
        manifest = _verify_manifest(value, self._manifest_key)
        if manifest["epoch"] < self._highest_epoch:
            raise ReadStoreError("read-store manifest rollback detected")
        self._validate_manifest_generation(manifest)
        self._highest_epoch = max(self._highest_epoch, manifest["epoch"])
        return manifest

    def _validate_ready(self, generation):
        self._validate_generation_path(generation)
        connection = _connect(self._path(generation) / DATABASE_NAME,
                              self._database_key, readonly=True)
        try: self._assert_ready(connection)
        finally: connection.close()

    def _validate_generation_path(self, generation):
        path = self._path(generation)
        _lstat_kind(path, directory=True)
        database = path / DATABASE_NAME
        _contained(path, database); _lstat_kind(database, directory=False)
        for suffix in ("-wal", "-shm"):
            sidecar = path / f"{DATABASE_NAME}{suffix}"
            if sidecar.exists() or sidecar.is_symlink():
                # Rollback-journal mode must never leave a WAL state to interpret.
                raise ReadStoreError(f"unexpected read-store sidecar: {sidecar.name}")

    def _validate_manifest_generation(self, manifest):
        self._validate_generation_path(manifest["generation"])
        connection = _connect(self._path(manifest["generation"]) / DATABASE_NAME,
                              self._database_key, readonly=True)
        try: self._assert_manifest_matches(connection, manifest)
        finally: connection.close()

    @staticmethod
    def _create_schema(connection, state):
        connection.execute("CREATE TABLE read_store_identity (format_version TEXT NOT NULL)")
        connection.execute("INSERT INTO read_store_identity VALUES (?)", (METADATA_VERSION,))
        connection.execute("""CREATE TABLE projection_meta (
            singleton INTEGER PRIMARY KEY CHECK(singleton=1), schema_version INTEGER NOT NULL,
            projector_version TEXT NOT NULL, resolver_version TEXT NOT NULL,
            as_of_version TEXT NOT NULL, key_derivation_version TEXT NOT NULL,
            source_count INTEGER NOT NULL, source_head TEXT NOT NULL,
            source_end_offset INTEGER NOT NULL CHECK(source_end_offset >= 0),
            source_cursor_mac TEXT NOT NULL CHECK(length(source_cursor_mac)=64),
            last_sequence INTEGER NOT NULL, last_hash TEXT NOT NULL,
            applied_events_digest TEXT NOT NULL CHECK(length(applied_events_digest)=64),
            resolver_content_hash TEXT NOT NULL CHECK(length(resolver_content_hash)=64),
            publication_epoch INTEGER NOT NULL DEFAULT 0,
            state TEXT NOT NULL CHECK(state IN ('building','ready')))""")
        connection.execute("""CREATE TABLE applied_events (
            sequence INTEGER PRIMARY KEY CHECK(sequence >= 0),
            event_id TEXT NOT NULL UNIQUE,
            record_hash TEXT NOT NULL UNIQUE CHECK(length(record_hash)=64),
            event_type TEXT NOT NULL CHECK(length(event_type)>0),
            UNIQUE(sequence, event_type))""")
        connection.execute("""CREATE TABLE event_provenance (
            source_sequence INTEGER PRIMARY KEY REFERENCES applied_events(sequence)
                DEFERRABLE INITIALLY DEFERRED,
            doc_id TEXT NOT NULL, page INTEGER, region TEXT NOT NULL, note TEXT NOT NULL,
            CHECK(page IS NULL OR page >= 0))""")
        connection.execute("""CREATE TABLE resolver_profiles (
            institution TEXT NOT NULL, account_kind TEXT NOT NULL,
            profile_json TEXT NOT NULL,
            PRIMARY KEY(institution, account_kind))""")
        # applied_events is an identity ledger, not a second event-body mirror.
        connection.execute("""CREATE TABLE account_entities (
            account_id TEXT PRIMARY KEY CHECK(length(account_id) > 0))""")
        connection.execute("""CREATE TABLE accounts (
            source_sequence INTEGER PRIMARY KEY REFERENCES applied_events(sequence)
                DEFERRABLE INITIALLY DEFERRED,
            event_type TEXT NOT NULL CHECK(event_type IN ('AccountOpened','AccountIdentityObserved')),
            account_id TEXT NOT NULL, occurred_at TEXT NOT NULL,
            kind TEXT, name TEXT, currency TEXT, jurisdiction TEXT,
            institution TEXT NOT NULL, account_number TEXT NOT NULL, origin TEXT,
            provenance_doc_id TEXT NOT NULL, provenance_page INTEGER,
            provenance_region TEXT NOT NULL, provenance_note TEXT NOT NULL,
            FOREIGN KEY(account_id) REFERENCES account_entities(account_id),
            FOREIGN KEY(source_sequence, event_type)
                REFERENCES applied_events(sequence, event_type)
                DEFERRABLE INITIALLY DEFERRED,
            CHECK((event_type='AccountOpened' AND kind IS NOT NULL AND name IS NOT NULL
                   AND currency IS NOT NULL AND jurisdiction IS NOT NULL AND origin IS NOT NULL)
               OR (event_type='AccountIdentityObserved' AND kind IS NULL AND name IS NULL
                   AND currency IS NULL AND jurisdiction IS NULL AND origin IS NULL)),
            CHECK(provenance_page IS NULL OR provenance_page >= 0))""")
        connection.execute("""CREATE TABLE account_names (
            source_sequence INTEGER NOT NULL REFERENCES accounts(source_sequence) ON DELETE CASCADE,
            name_index INTEGER NOT NULL CHECK(name_index >= 0), name TEXT NOT NULL,
            PRIMARY KEY(source_sequence, name_index))""")
        connection.execute("""CREATE TABLE balance_observations (
            source_sequence INTEGER PRIMARY KEY REFERENCES applied_events(sequence)
                DEFERRABLE INITIALLY DEFERRED,
            event_type TEXT NOT NULL CHECK(event_type IN ('OpeningBalanceObserved','ClosingBalanceObserved')),
            account_id TEXT NOT NULL, occurred_at TEXT NOT NULL,
            amount_text TEXT NOT NULL, confirmed_by TEXT,
            provenance_doc_id TEXT NOT NULL, provenance_page INTEGER,
            provenance_region TEXT NOT NULL, provenance_note TEXT NOT NULL,
            FOREIGN KEY(account_id) REFERENCES account_entities(account_id),
            FOREIGN KEY(source_sequence, event_type)
                REFERENCES applied_events(sequence, event_type)
                DEFERRABLE INITIALLY DEFERRED,
            CHECK((event_type='OpeningBalanceObserved' AND confirmed_by IS NULL)
               OR event_type='ClosingBalanceObserved'),
            CHECK(typeof(amount_text)='text'),
            CHECK(provenance_page IS NULL OR provenance_page >= 0))""")
        connection.execute("""CREATE TABLE transactions (
            source_sequence INTEGER PRIMARY KEY REFERENCES applied_events(sequence)
                DEFERRABLE INITIALLY DEFERRED,
            event_type TEXT NOT NULL CHECK(event_type='TransactionRecorded'),
            occurred_at TEXT NOT NULL, description TEXT NOT NULL,
            provenance_doc_id TEXT NOT NULL, provenance_page INTEGER,
            provenance_region TEXT NOT NULL, provenance_note TEXT NOT NULL,
            FOREIGN KEY(source_sequence, event_type)
                REFERENCES applied_events(sequence, event_type)
                DEFERRABLE INITIALLY DEFERRED,
            CHECK(provenance_page IS NULL OR provenance_page >= 0))""")
        connection.execute("""CREATE TABLE transaction_tags (
            source_sequence INTEGER NOT NULL REFERENCES transactions(source_sequence) ON DELETE CASCADE,
            tag_index INTEGER NOT NULL CHECK(tag_index >= 0), tag TEXT NOT NULL,
            PRIMARY KEY(source_sequence, tag_index))""")
        connection.execute("""CREATE TABLE postings (
            source_sequence INTEGER NOT NULL REFERENCES transactions(source_sequence) ON DELETE CASCADE,
            posting_index INTEGER NOT NULL CHECK(posting_index >= 0),
            account_id TEXT NOT NULL REFERENCES account_entities(account_id),
            amount_text TEXT NOT NULL, grade TEXT NOT NULL,
            PRIMARY KEY(source_sequence, posting_index),
            CHECK(typeof(amount_text)='text'))""")
        connection.execute("""CREATE TABLE positions (
            source_sequence INTEGER PRIMARY KEY REFERENCES applied_events(sequence)
                DEFERRABLE INITIALLY DEFERRED,
            event_type TEXT NOT NULL CHECK(event_type='PositionObserved'),
            account_id TEXT NOT NULL REFERENCES account_entities(account_id),
            occurred_at TEXT NOT NULL, instrument_id TEXT NOT NULL,
            quantity_text TEXT NOT NULL, value_text TEXT NOT NULL,
            currency TEXT NOT NULL, cost_basis_text TEXT NOT NULL,
            valuation_class TEXT NOT NULL, grade TEXT NOT NULL,
            provenance_doc_id TEXT NOT NULL, provenance_page INTEGER,
            provenance_region TEXT NOT NULL, provenance_note TEXT NOT NULL,
            FOREIGN KEY(source_sequence, event_type)
                REFERENCES applied_events(sequence, event_type)
                DEFERRABLE INITIALLY DEFERRED,
            CHECK(typeof(quantity_text)='text' AND typeof(value_text)='text'
                  AND typeof(cost_basis_text)='text'),
            CHECK(provenance_page IS NULL OR provenance_page >= 0))""")
        connection.execute("""CREATE TABLE documents (
            source_sequence INTEGER PRIMARY KEY REFERENCES applied_events(sequence)
                DEFERRABLE INITIALLY DEFERRED,
            event_type TEXT NOT NULL CHECK(event_type='DocumentCaptured'),
            doc_id TEXT NOT NULL, occurred_at TEXT NOT NULL, filename TEXT NOT NULL,
            byte_len INTEGER NOT NULL CHECK(byte_len >= 0), doc_type TEXT NOT NULL,
            doc_type_confidence_text TEXT NOT NULL, state TEXT NOT NULL CHECK(state='captured'),
            provenance_doc_id TEXT NOT NULL, provenance_page INTEGER,
            provenance_region TEXT NOT NULL, provenance_note TEXT NOT NULL,
            FOREIGN KEY(source_sequence, event_type)
                REFERENCES applied_events(sequence, event_type)
                DEFERRABLE INITIALLY DEFERRED,
            CHECK(typeof(doc_type_confidence_text)='text'),
            CHECK(provenance_page IS NULL OR provenance_page >= 0))""")
        connection.execute("""CREATE TABLE document_account_history (
            source_sequence INTEGER NOT NULL REFERENCES applied_events(sequence)
                DEFERRABLE INITIALLY DEFERRED,
            account_index INTEGER NOT NULL CHECK(account_index >= 0),
            event_type TEXT NOT NULL CHECK(event_type IN
                ('AccountOpened','AccountIdentityObserved','OpeningBalanceObserved',
                 'ClosingBalanceObserved','TransactionRecorded','PositionObserved')),
            occurred_at TEXT NOT NULL,
            doc_id TEXT NOT NULL CHECK(length(doc_id)>0),
            account_id TEXT NOT NULL REFERENCES account_entities(account_id),
            role TEXT NOT NULL CHECK(role IN
                ('account','opening','closing','transaction','position')),
            provenance_doc_id TEXT NOT NULL, provenance_page INTEGER,
            provenance_region TEXT NOT NULL, provenance_note TEXT NOT NULL,
            PRIMARY KEY(source_sequence,account_index),
            FOREIGN KEY(source_sequence,event_type)
                REFERENCES applied_events(sequence,event_type)
                DEFERRABLE INITIALLY DEFERRED,
            CHECK((role='account' AND event_type IN
                       ('AccountOpened','AccountIdentityObserved')) OR
                  (role='opening' AND event_type='OpeningBalanceObserved') OR
                  (role='closing' AND event_type='ClosingBalanceObserved') OR
                  (role='transaction' AND event_type='TransactionRecorded') OR
                  (role='position' AND event_type='PositionObserved')),
            CHECK(provenance_page IS NULL OR provenance_page>=0))""")
        connection.execute("""CREATE TABLE document_reads (
            source_sequence INTEGER PRIMARY KEY REFERENCES applied_events(sequence)
                DEFERRABLE INITIALLY DEFERRED,
            event_type TEXT NOT NULL CHECK(event_type='ReadRecorded'),
            doc_id TEXT NOT NULL, occurred_at TEXT NOT NULL,
            model TEXT NOT NULL, model_role TEXT NOT NULL,
            resolved_model TEXT, prompt_version TEXT NOT NULL,
            input_mode TEXT NOT NULL, response_text TEXT NOT NULL,
            cost_usd_text TEXT NOT NULL, input_tokens INTEGER,
            output_tokens INTEGER, usage_reported INTEGER,
            parse_ok INTEGER NOT NULL CHECK(parse_ok IN (0,1)), parse_error TEXT,
            phase TEXT NOT NULL, body_json TEXT NOT NULL,
            provenance_doc_id TEXT NOT NULL, provenance_page INTEGER,
            provenance_region TEXT NOT NULL, provenance_note TEXT NOT NULL,
            FOREIGN KEY(source_sequence, event_type)
                REFERENCES applied_events(sequence, event_type)
                DEFERRABLE INITIALLY DEFERRED,
            CHECK(typeof(cost_usd_text)='text' AND json_valid(body_json)),
            CHECK(usage_reported IS NULL OR usage_reported IN (0,1)),
            CHECK(provenance_page IS NULL OR provenance_page >= 0))""")
        connection.execute("""CREATE TABLE document_holds (
            source_sequence INTEGER PRIMARY KEY REFERENCES applied_events(sequence)
                DEFERRABLE INITIALLY DEFERRED,
            event_type TEXT NOT NULL CHECK(event_type IN ('StatementHeld','BrokerageActivityHeld')),
            doc_id TEXT NOT NULL, occurred_at TEXT NOT NULL, reason TEXT NOT NULL,
            facts_json TEXT NOT NULL, finding_json TEXT,
            provenance_doc_id TEXT NOT NULL, provenance_page INTEGER,
            provenance_region TEXT NOT NULL, provenance_note TEXT NOT NULL,
            FOREIGN KEY(source_sequence, event_type)
                REFERENCES applied_events(sequence, event_type)
                DEFERRABLE INITIALLY DEFERRED,
            CHECK(json_valid(facts_json)),
            CHECK(finding_json IS NULL OR json_valid(finding_json)),
            CHECK(provenance_page IS NULL OR provenance_page >= 0))""")
        connection.execute("""CREATE TABLE document_hold_resolutions (
            source_sequence INTEGER PRIMARY KEY REFERENCES applied_events(sequence)
                DEFERRABLE INITIALLY DEFERRED,
            event_type TEXT NOT NULL CHECK(event_type='BrokerageActivityResolved'),
            doc_id TEXT NOT NULL, occurred_at TEXT NOT NULL,
            provenance_doc_id TEXT NOT NULL, provenance_page INTEGER,
            provenance_region TEXT NOT NULL, provenance_note TEXT NOT NULL,
            FOREIGN KEY(source_sequence, event_type)
                REFERENCES applied_events(sequence, event_type)
                DEFERRABLE INITIALLY DEFERRED,
            CHECK(provenance_page IS NULL OR provenance_page >= 0))""")
        connection.execute("""CREATE TABLE document_corrections (
            source_sequence INTEGER PRIMARY KEY REFERENCES applied_events(sequence)
                DEFERRABLE INITIALLY DEFERRED,
            event_type TEXT NOT NULL CHECK(event_type='CorrectionApplied'),
            doc_id TEXT NOT NULL, occurred_at TEXT NOT NULL, target TEXT NOT NULL,
            from_value TEXT NOT NULL, to_value TEXT NOT NULL, decided_by TEXT NOT NULL,
            provenance_doc_id TEXT NOT NULL, provenance_page INTEGER,
            provenance_region TEXT NOT NULL, provenance_note TEXT NOT NULL,
            FOREIGN KEY(source_sequence, event_type)
                REFERENCES applied_events(sequence, event_type)
                DEFERRABLE INITIALLY DEFERRED,
            CHECK(provenance_page IS NULL OR provenance_page >= 0))""")
        connection.execute("""CREATE TABLE statement_periods (
            source_sequence INTEGER PRIMARY KEY REFERENCES applied_events(sequence)
                DEFERRABLE INITIALLY DEFERRED,
            event_type TEXT NOT NULL CHECK(event_type='ClosingBalanceObserved'),
            account_id TEXT NOT NULL REFERENCES account_entities(account_id),
            doc_id TEXT NOT NULL CHECK(length(doc_id)>0), period_end TEXT NOT NULL,
            closing_amount_text TEXT NOT NULL, confirmed_by TEXT NOT NULL,
            provenance_doc_id TEXT NOT NULL, provenance_page INTEGER,
            provenance_region TEXT NOT NULL, provenance_note TEXT NOT NULL,
            FOREIGN KEY(source_sequence, event_type)
                REFERENCES applied_events(sequence, event_type)
                DEFERRABLE INITIALLY DEFERRED,
            CHECK(typeof(closing_amount_text)='text'),
            CHECK(provenance_page IS NULL OR provenance_page >= 0))""")
        connection.execute("""CREATE TABLE posted_document_events (
            source_sequence INTEGER PRIMARY KEY REFERENCES applied_events(sequence)
                DEFERRABLE INITIALLY DEFERRED,
            event_type TEXT NOT NULL CHECK(event_type IN
                ('OpeningBalanceObserved','ClosingBalanceObserved',
                 'TransactionRecorded','PositionObserved')),
            doc_id TEXT NOT NULL CHECK(length(doc_id)>0), occurred_at TEXT NOT NULL,
            provenance_doc_id TEXT NOT NULL, provenance_page INTEGER,
            provenance_region TEXT NOT NULL, provenance_note TEXT NOT NULL,
            FOREIGN KEY(source_sequence, event_type)
                REFERENCES applied_events(sequence, event_type)
                DEFERRABLE INITIALLY DEFERRED,
            CHECK(provenance_page IS NULL OR provenance_page >= 0))""")
        connection.execute("""CREATE TABLE review_decisions (
            source_sequence INTEGER PRIMARY KEY REFERENCES applied_events(sequence)
                DEFERRABLE INITIALLY DEFERRED,
            event_type TEXT NOT NULL CHECK(event_type IN
                ('QuestionDeclined','FindingSetAside','RulingRecorded','CorrectionApplied')),
            occurred_at TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('declined','set_aside','ruled','corrected')),
            subject_id TEXT NOT NULL, kind TEXT NOT NULL, body_json TEXT NOT NULL,
            provenance_doc_id TEXT NOT NULL, provenance_page INTEGER,
            provenance_region TEXT NOT NULL, provenance_note TEXT NOT NULL,
            FOREIGN KEY(source_sequence, event_type)
                REFERENCES applied_events(sequence, event_type)
                DEFERRABLE INITIALLY DEFERRED,
            CHECK((event_type='QuestionDeclined' AND status='declined') OR
                  (event_type='FindingSetAside' AND status='set_aside') OR
                  (event_type='RulingRecorded' AND status='ruled') OR
                  (event_type='CorrectionApplied' AND status='corrected')),
            CHECK(json_valid(body_json)),
            CHECK(provenance_page IS NULL OR provenance_page >= 0))""")
        connection.execute("""CREATE TABLE transfer_history (
            source_sequence INTEGER PRIMARY KEY REFERENCES applied_events(sequence)
                DEFERRABLE INITIALLY DEFERRED,
            event_type TEXT NOT NULL CHECK(event_type IN
                ('TransferLinked','TransferUnlinked','TransferSuggested')),
            occurred_at TEXT NOT NULL, movement_a TEXT NOT NULL,
            movement_b TEXT, candidates_json TEXT NOT NULL, status TEXT NOT NULL,
            grade TEXT NOT NULL, decided_by TEXT NOT NULL, by_actor TEXT NOT NULL,
            evidence_json TEXT NOT NULL,
            provenance_doc_id TEXT NOT NULL, provenance_page INTEGER,
            provenance_region TEXT NOT NULL, provenance_note TEXT NOT NULL,
            FOREIGN KEY(source_sequence, event_type)
                REFERENCES applied_events(sequence, event_type)
                DEFERRABLE INITIALLY DEFERRED,
            CHECK(provenance_page IS NULL OR provenance_page >= 0),
            CHECK(json_valid(candidates_json) AND json_valid(evidence_json)))""")
        connection.execute("""CREATE TABLE category_history (
            source_sequence INTEGER PRIMARY KEY REFERENCES applied_events(sequence)
                DEFERRABLE INITIALLY DEFERRED,
            event_type TEXT NOT NULL CHECK(event_type='CategoryAssigned'),
            occurred_at TEXT NOT NULL, movement_key TEXT NOT NULL,
            descriptor TEXT NOT NULL, category TEXT NOT NULL, subcategory TEXT NOT NULL,
            nature TEXT NOT NULL, grade TEXT NOT NULL, by_actor TEXT NOT NULL,
            category_grade TEXT NOT NULL, subcategory_grade TEXT NOT NULL,
            category_by TEXT NOT NULL, subcategory_by TEXT NOT NULL,
            provenance_doc_id TEXT NOT NULL, provenance_page INTEGER,
            provenance_region TEXT NOT NULL, provenance_note TEXT NOT NULL,
            FOREIGN KEY(source_sequence, event_type)
                REFERENCES applied_events(sequence, event_type)
                DEFERRABLE INITIALLY DEFERRED,
            CHECK(provenance_page IS NULL OR provenance_page >= 0))""")
        connection.execute("""CREATE TABLE merchant_history (
            source_sequence INTEGER PRIMARY KEY REFERENCES applied_events(sequence)
                DEFERRABLE INITIALLY DEFERRED,
            event_type TEXT NOT NULL CHECK(event_type IN
                ('MerchantCategorized','MerchantEnriched')),
            occurred_at TEXT NOT NULL, merchant_key TEXT NOT NULL,
            category TEXT NOT NULL, subcategory TEXT NOT NULL,
            canonical_name TEXT NOT NULL, attributes_json TEXT NOT NULL,
            aliases_json TEXT NOT NULL, grade TEXT NOT NULL, by_actor TEXT NOT NULL,
            category_grade TEXT NOT NULL, subcategory_grade TEXT NOT NULL,
            category_by TEXT NOT NULL, subcategory_by TEXT NOT NULL,
            provenance_doc_id TEXT NOT NULL, provenance_page INTEGER,
            provenance_region TEXT NOT NULL, provenance_note TEXT NOT NULL,
            FOREIGN KEY(source_sequence, event_type)
                REFERENCES applied_events(sequence, event_type)
                DEFERRABLE INITIALLY DEFERRED,
            CHECK(provenance_page IS NULL OR provenance_page >= 0),
            CHECK(json_valid(attributes_json) AND json_valid(aliases_json)))""")
        connection.execute("""CREATE TABLE tag_history (
            source_sequence INTEGER PRIMARY KEY REFERENCES applied_events(sequence)
                DEFERRABLE INITIALLY DEFERRED,
            event_type TEXT NOT NULL CHECK(event_type='MovementTagged'),
            occurred_at TEXT NOT NULL, scope TEXT NOT NULL,
            subject TEXT NOT NULL, tags_json TEXT NOT NULL, by_actor TEXT NOT NULL,
            provenance_doc_id TEXT NOT NULL, provenance_page INTEGER,
            provenance_region TEXT NOT NULL, provenance_note TEXT NOT NULL,
            FOREIGN KEY(source_sequence, event_type)
                REFERENCES applied_events(sequence, event_type)
                DEFERRABLE INITIALLY DEFERRED,
            CHECK(provenance_page IS NULL OR provenance_page >= 0),
            CHECK(scope IN ('movement','merchant') AND json_valid(tags_json)))""")
        connection.execute("""CREATE TABLE ruling_history (
            source_sequence INTEGER PRIMARY KEY REFERENCES applied_events(sequence)
                DEFERRABLE INITIALLY DEFERRED,
            event_type TEXT NOT NULL CHECK(event_type='RulingRecorded'),
            occurred_at TEXT NOT NULL, scope TEXT NOT NULL, subject TEXT NOT NULL,
            legs_json TEXT NOT NULL, by_actor TEXT NOT NULL, grade TEXT NOT NULL,
            said TEXT NOT NULL, corroborates TEXT NOT NULL, same_as TEXT NOT NULL,
            value_text TEXT NOT NULL, currency TEXT NOT NULL, prompt_version TEXT NOT NULL,
            provenance_doc_id TEXT NOT NULL, provenance_page INTEGER,
            provenance_region TEXT NOT NULL, provenance_note TEXT NOT NULL,
            FOREIGN KEY(source_sequence, event_type)
                REFERENCES applied_events(sequence, event_type)
                DEFERRABLE INITIALLY DEFERRED,
            CHECK(provenance_page IS NULL OR provenance_page >= 0),
            CHECK(json_valid(legs_json) AND typeof(value_text)='text'))""")
        connection.execute("""CREATE TABLE attribute_history (
            source_sequence INTEGER PRIMARY KEY REFERENCES applied_events(sequence)
                DEFERRABLE INITIALLY DEFERRED,
            event_type TEXT NOT NULL CHECK(event_type='RulingRecorded'),
            occurred_at TEXT NOT NULL, account_id TEXT NOT NULL,
            attribute_key TEXT NOT NULL, value_text TEXT NOT NULL,
            currency TEXT NOT NULL, grade TEXT NOT NULL, said TEXT NOT NULL,
            by_actor TEXT NOT NULL,
            provenance_doc_id TEXT NOT NULL, provenance_page INTEGER,
            provenance_region TEXT NOT NULL, provenance_note TEXT NOT NULL,
            FOREIGN KEY(source_sequence,event_type)
                REFERENCES applied_events(sequence,event_type)
                DEFERRABLE INITIALLY DEFERRED,
            CHECK(typeof(value_text)='text'),
            CHECK(provenance_page IS NULL OR provenance_page>=0))""")
        connection.execute("""CREATE TABLE account_alias_history (
            source_sequence INTEGER PRIMARY KEY REFERENCES applied_events(sequence)
                DEFERRABLE INITIALLY DEFERRED,
            event_type TEXT NOT NULL CHECK(event_type='AccountAliasConfirmed'),
            occurred_at TEXT NOT NULL, alias_key TEXT NOT NULL,
            account_id TEXT NOT NULL, doc_id TEXT NOT NULL, by_actor TEXT NOT NULL,
            learn_signal INTEGER NOT NULL CHECK(learn_signal IN (0,1)),
            match_names_json TEXT NOT NULL, match_label TEXT NOT NULL,
            account_kind TEXT NOT NULL,
            evidence_scoped INTEGER NOT NULL CHECK(evidence_scoped IN (0,1)),
            provenance_doc_id TEXT NOT NULL, provenance_page INTEGER,
            provenance_region TEXT NOT NULL, provenance_note TEXT NOT NULL,
            FOREIGN KEY(source_sequence, event_type)
                REFERENCES applied_events(sequence, event_type)
                DEFERRABLE INITIALLY DEFERRED,
            CHECK(provenance_page IS NULL OR provenance_page >= 0),
            CHECK(json_valid(match_names_json)))""")
        connection.execute("""CREATE TABLE goal_event_history (
            source_sequence INTEGER PRIMARY KEY REFERENCES applied_events(sequence)
                DEFERRABLE INITIALLY DEFERRED,
            event_type TEXT NOT NULL CHECK(event_type IN
                ('GoalCreated','GoalTermsChanged','GoalFundsReserved',
                 'GoalFundsReleased','GoalStateChanged')),
            occurred_at TEXT NOT NULL, goal_id TEXT NOT NULL,
            account_id TEXT, amount_text TEXT, proposal_id TEXT NOT NULL,
            body_json TEXT NOT NULL,
            provenance_doc_id TEXT NOT NULL, provenance_page INTEGER,
            provenance_region TEXT NOT NULL, provenance_note TEXT NOT NULL,
            FOREIGN KEY(source_sequence,event_type)
                REFERENCES applied_events(sequence,event_type)
                DEFERRABLE INITIALLY DEFERRED,
            CHECK(amount_text IS NULL OR typeof(amount_text)='text'),
            CHECK(json_valid(body_json)),
            CHECK(provenance_page IS NULL OR provenance_page>=0))""")
        connection.execute("""CREATE TABLE goal_proposal_history (
            source_sequence INTEGER PRIMARY KEY REFERENCES applied_events(sequence)
                DEFERRABLE INITIALLY DEFERRED,
            event_type TEXT NOT NULL CHECK(event_type IN
                ('GoalProposalRecorded','GoalProposalResolved')),
            occurred_at TEXT NOT NULL, proposal_id TEXT NOT NULL,
            body_json TEXT NOT NULL,
            provenance_doc_id TEXT NOT NULL, provenance_page INTEGER,
            provenance_region TEXT NOT NULL, provenance_note TEXT NOT NULL,
            FOREIGN KEY(source_sequence,event_type)
                REFERENCES applied_events(sequence,event_type)
                DEFERRABLE INITIALLY DEFERRED,
            CHECK(json_valid(body_json)),
            CHECK(provenance_page IS NULL OR provenance_page>=0))""")
        connection.execute("""CREATE TABLE conversation_turn_history (
            source_sequence INTEGER PRIMARY KEY REFERENCES applied_events(sequence)
                DEFERRABLE INITIALLY DEFERRED,
            event_type TEXT NOT NULL CHECK(event_type IN
                ('ConversationTurnOpened','ConversationTurnSettled')),
            occurred_at TEXT NOT NULL, turn_id TEXT NOT NULL,
            body_json TEXT NOT NULL,
            provenance_doc_id TEXT NOT NULL, provenance_page INTEGER,
            provenance_region TEXT NOT NULL, provenance_note TEXT NOT NULL,
            FOREIGN KEY(source_sequence,event_type)
                REFERENCES applied_events(sequence,event_type)
                DEFERRABLE INITIALLY DEFERRED,
            CHECK(json_valid(body_json)),
            CHECK(provenance_page IS NULL OR provenance_page>=0))""")
        connection.execute("""CREATE TABLE conversation_proposal_history (
            source_sequence INTEGER PRIMARY KEY REFERENCES applied_events(sequence)
                DEFERRABLE INITIALLY DEFERRED,
            event_type TEXT NOT NULL CHECK(event_type IN
                ('ConversationProposalRecorded','ConversationProposalResolved')),
            occurred_at TEXT NOT NULL, proposal_id TEXT NOT NULL,
            body_json TEXT NOT NULL,
            provenance_doc_id TEXT NOT NULL, provenance_page INTEGER,
            provenance_region TEXT NOT NULL, provenance_note TEXT NOT NULL,
            FOREIGN KEY(source_sequence,event_type)
                REFERENCES applied_events(sequence,event_type)
                DEFERRABLE INITIALLY DEFERRED,
            CHECK(json_valid(body_json)),
            CHECK(provenance_page IS NULL OR provenance_page>=0))""")
        connection.execute("""CREATE TABLE agent_action_history (
            source_sequence INTEGER PRIMARY KEY REFERENCES applied_events(sequence)
                DEFERRABLE INITIALLY DEFERRED,
            event_type TEXT NOT NULL CHECK(event_type='AgentActed'),
            occurred_at TEXT NOT NULL, rule_id TEXT NOT NULL,
            action_kind TEXT NOT NULL, target TEXT NOT NULL,
            outcome TEXT NOT NULL CHECK(outcome IN ('','done','refused','failed')),
            calls INTEGER NOT NULL CHECK(calls>=0), stake_json TEXT NOT NULL,
            produced TEXT NOT NULL, replaced TEXT NOT NULL, detail TEXT NOT NULL,
            by_actor TEXT NOT NULL, body_json TEXT NOT NULL,
            provenance_doc_id TEXT NOT NULL, provenance_page INTEGER,
            provenance_region TEXT NOT NULL, provenance_note TEXT NOT NULL,
            FOREIGN KEY(source_sequence,event_type)
                REFERENCES applied_events(sequence,event_type)
                DEFERRABLE INITIALLY DEFERRED,
            CHECK(json_valid(stake_json) AND json_valid(body_json)),
            CHECK(provenance_page IS NULL OR provenance_page>=0))""")
        connection.execute("""CREATE TABLE movements (
            movement_key TEXT PRIMARY KEY, source_sequence INTEGER NOT NULL,
            posting_index INTEGER NOT NULL, account_id TEXT NOT NULL,
            account_kind TEXT NOT NULL, occurred_at TEXT NOT NULL,
            amount_text TEXT NOT NULL, grade TEXT NOT NULL, currency TEXT NOT NULL,
            description TEXT NOT NULL, provenance_doc_id TEXT NOT NULL,
            provenance_page INTEGER, provenance_region TEXT NOT NULL,
            provenance_note TEXT NOT NULL, linked INTEGER NOT NULL CHECK(linked IN (0,1)),
            nature TEXT NOT NULL, nature_reason TEXT NOT NULL,
            provisional INTEGER NOT NULL CHECK(provisional IN (0,1)),
            ruling_account TEXT NOT NULL, merchant_key TEXT NOT NULL,
            category TEXT NOT NULL, subcategory TEXT NOT NULL,
            category_grade TEXT NOT NULL, subcategory_grade TEXT NOT NULL,
            category_by TEXT NOT NULL, subcategory_by TEXT NOT NULL,
            CHECK(typeof(amount_text)='text'),
            FOREIGN KEY(source_sequence,posting_index)
                REFERENCES postings(source_sequence,posting_index),
            UNIQUE(source_sequence, posting_index))""")
        connection.execute("""CREATE TABLE transfer_links (
            movement_a TEXT NOT NULL, movement_b TEXT NOT NULL,
            grade TEXT NOT NULL, by_actor TEXT NOT NULL, decided_by TEXT NOT NULL,
            PRIMARY KEY(movement_a,movement_b), CHECK(movement_a <= movement_b))""")
        connection.execute("""CREATE TABLE transfer_suggestions (
            movement_a TEXT PRIMARY KEY, candidates_json TEXT NOT NULL,
            evidence_json TEXT NOT NULL,
            CHECK(json_valid(candidates_json) AND json_valid(evidence_json)))""")
        connection.execute("""CREATE TABLE movement_tags (
            movement_key TEXT NOT NULL REFERENCES movements(movement_key) ON DELETE CASCADE,
            tag TEXT NOT NULL, source TEXT NOT NULL CHECK(source IN ('movement','merchant')),
            PRIMARY KEY(movement_key,tag,source))""")
        connection.execute("""CREATE TABLE account_ledger_component_index (
            account_id TEXT NOT NULL, occurred_at TEXT NOT NULL,
            canonical_movement_key TEXT NOT NULL REFERENCES movements(movement_key),
            members_json TEXT NOT NULL CHECK(json_valid(members_json)),
            PRIMARY KEY(account_id,canonical_movement_key))""")
        connection.execute("""CREATE TABLE account_ledger_component_state (
            account_id TEXT PRIMARY KEY, locale TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('ready','refused','identity_error')),
            component_count INTEGER NOT NULL CHECK(component_count>=0),
            coverage_json TEXT NOT NULL CHECK(json_valid(coverage_json)),
            overlap_json TEXT NOT NULL CHECK(json_valid(overlap_json)),
            records_json TEXT NOT NULL CHECK(json_valid(records_json)),
            account_json TEXT NOT NULL CHECK(json_valid(account_json)),
            balance_json TEXT NOT NULL CHECK(json_valid(balance_json)))""")
        connection.execute("CREATE INDEX accounts_by_identity ON accounts(account_id, occurred_at, source_sequence)")
        connection.execute("CREATE INDEX accounts_by_identity_source ON accounts(account_id, source_sequence DESC)")
        connection.execute("CREATE INDEX accounts_by_date_source ON accounts(occurred_at,source_sequence)")
        connection.execute("CREATE INDEX accounts_by_source_date ON accounts(source_sequence,occurred_at)")
        connection.execute("CREATE INDEX observations_by_account_date ON balance_observations(account_id, occurred_at, source_sequence)")
        connection.execute("CREATE INDEX observations_by_source ON balance_observations(source_sequence,event_type)")
        connection.execute("CREATE INDEX opening_observations_by_account_date ON balance_observations(account_id,occurred_at,source_sequence) WHERE event_type='OpeningBalanceObserved'")
        connection.execute("CREATE INDEX closing_observations_by_account_date ON balance_observations(account_id,occurred_at DESC,source_sequence DESC) WHERE event_type='ClosingBalanceObserved'")
        connection.execute("CREATE INDEX postings_by_account ON postings(account_id, source_sequence, posting_index)")
        connection.execute("CREATE INDEX positions_by_account_date ON positions(account_id,occurred_at DESC,source_sequence DESC)")
        connection.execute("CREATE INDEX documents_by_state_date ON documents(state, occurred_at, source_sequence)")
        connection.execute("CREATE INDEX documents_by_source ON documents(source_sequence,doc_type)")
        connection.execute("CREATE INDEX documents_by_date_keyset ON documents(occurred_at DESC, source_sequence DESC)")
        connection.execute("CREATE INDEX documents_by_doc ON documents(doc_id)")
        connection.execute("CREATE INDEX document_accounts_by_account ON document_account_history(account_id,occurred_at,source_sequence,account_index)")
        connection.execute("CREATE INDEX document_accounts_by_doc ON document_account_history(doc_id,account_id,source_sequence,account_index)")
        connection.execute("CREATE INDEX document_reads_by_doc_date ON document_reads(doc_id, occurred_at DESC, source_sequence DESC)")
        connection.execute("CREATE INDEX model_exchanges_by_order ON document_reads(occurred_at DESC,source_sequence DESC)")
        connection.execute("CREATE INDEX model_exchanges_by_phase_order ON document_reads(phase,occurred_at DESC,source_sequence DESC)")
        connection.execute("CREATE INDEX document_reads_by_doc_phase_source ON document_reads(doc_id,phase,parse_ok,source_sequence DESC)")
        connection.execute("CREATE INDEX document_reads_by_source ON document_reads(source_sequence,doc_id,phase,parse_ok)")
        connection.execute("CREATE INDEX document_holds_by_doc_date ON document_holds(doc_id, occurred_at DESC, source_sequence DESC)")
        connection.execute("CREATE INDEX document_hold_resolutions_by_doc_date ON document_hold_resolutions(doc_id, occurred_at DESC, source_sequence DESC)")
        connection.execute("CREATE INDEX document_corrections_by_doc_date ON document_corrections(doc_id, occurred_at DESC, source_sequence DESC)")
        connection.execute("CREATE INDEX statement_periods_by_account_date ON statement_periods(account_id,period_end DESC,source_sequence DESC)")
        connection.execute("CREATE INDEX statement_periods_by_period_order ON statement_periods(period_end DESC,source_sequence DESC)")
        connection.execute("CREATE INDEX statement_periods_by_document_date ON statement_periods(doc_id,period_end DESC,source_sequence DESC)")
        connection.execute("CREATE INDEX statement_periods_by_document_source ON statement_periods(doc_id,source_sequence)")
        connection.execute("CREATE INDEX posted_document_events_by_doc_date ON posted_document_events(doc_id,occurred_at DESC,source_sequence DESC)")
        connection.execute("CREATE INDEX review_decisions_by_status_order ON review_decisions(status,occurred_at DESC,source_sequence DESC)")
        connection.execute("CREATE INDEX review_decisions_by_current_subject ON review_decisions(event_type,subject_id,source_sequence DESC)")
        connection.execute("CREATE INDEX review_decisions_by_order ON review_decisions(occurred_at DESC,source_sequence DESC)")
        connection.execute("CREATE INDEX movements_by_date ON movements(occurred_at DESC,movement_key)")
        connection.execute("CREATE INDEX movements_by_activity_order ON movements(occurred_at DESC,movement_key DESC)")
        connection.execute("CREATE INDEX movements_by_question_order ON movements(occurred_at,movement_key)")
        connection.execute("CREATE INDEX movements_by_account_date ON movements(account_id,occurred_at DESC,movement_key)")
        connection.execute("CREATE INDEX movements_by_account_ledger_order ON movements(account_id,occurred_at DESC,movement_key DESC)")
        connection.execute("CREATE INDEX account_ledger_components_by_page ON account_ledger_component_index(account_id,occurred_at DESC,canonical_movement_key DESC)")
        connection.execute("CREATE INDEX movements_by_currency_date ON movements(currency,occurred_at DESC,movement_key)")
        connection.execute("CREATE INDEX movements_by_nature_date ON movements(nature,occurred_at DESC,movement_key)")
        connection.execute("CREATE INDEX movements_by_category_date ON movements(category,occurred_at DESC,movement_key)")
        connection.execute("CREATE INDEX movements_by_document_date ON movements(provenance_doc_id,occurred_at DESC,movement_key)")
        connection.execute("CREATE INDEX movements_by_merchant_date ON movements(merchant_key,occurred_at DESC,movement_key)")
        connection.execute("CREATE INDEX movements_by_loan_ruling ON movements(ruling_account,occurred_at,movement_key)")
        connection.execute("CREATE INDEX transfer_links_by_b ON transfer_links(movement_b,movement_a)")
        connection.execute("CREATE INDEX transactions_by_date_source ON transactions(occurred_at,source_sequence)")
        connection.execute("CREATE INDEX transfer_history_by_pair ON transfer_history(movement_a,movement_b,source_sequence)")
        connection.execute("CREATE INDEX transfer_history_by_date_source ON transfer_history(occurred_at,source_sequence)")
        connection.execute("CREATE INDEX category_history_by_movement ON category_history(movement_key,source_sequence)")
        connection.execute("CREATE INDEX merchant_history_by_key ON merchant_history(merchant_key,source_sequence)")
        connection.execute("CREATE INDEX merchant_history_by_date_source ON merchant_history(occurred_at,source_sequence)")
        connection.execute("CREATE INDEX tag_history_by_subject ON tag_history(scope,subject,source_sequence)")
        connection.execute("CREATE INDEX ruling_history_by_subject ON ruling_history(scope,subject,source_sequence)")
        connection.execute("CREATE INDEX ruling_history_by_scope_order ON ruling_history(scope,occurred_at DESC,source_sequence DESC)")
        connection.execute("CREATE INDEX attributes_by_account_key_value_time ON attribute_history(account_id,attribute_key,occurred_at DESC,source_sequence DESC)")
        connection.execute("CREATE INDEX attributes_by_eligible_time ON attribute_history(occurred_at,source_sequence)")
        connection.execute("CREATE INDEX attributes_by_account_eligible_time ON attribute_history(account_id,occurred_at,source_sequence)")
        connection.execute("CREATE INDEX account_alias_history_by_key ON account_alias_history(alias_key,source_sequence)")
        connection.execute("CREATE INDEX goal_events_by_goal_order ON goal_event_history(goal_id,occurred_at DESC,source_sequence DESC)")
        connection.execute("CREATE INDEX goal_events_by_order ON goal_event_history(occurred_at DESC,source_sequence DESC)")
        connection.execute("CREATE INDEX goal_events_by_source ON goal_event_history(source_sequence)")
        connection.execute("CREATE INDEX goal_creates_by_current_id ON goal_event_history(goal_id,occurred_at,source_sequence) WHERE event_type='GoalCreated' AND goal_id<>''")
        connection.execute("CREATE INDEX goal_proposals_by_id_order ON goal_proposal_history(proposal_id,occurred_at DESC,source_sequence DESC)")
        connection.execute("CREATE INDEX goal_proposals_by_order ON goal_proposal_history(occurred_at DESC,source_sequence DESC)")
        connection.execute("CREATE INDEX conversation_turns_by_id_order ON conversation_turn_history(turn_id,occurred_at DESC,source_sequence DESC)")
        connection.execute("CREATE INDEX conversation_turns_by_order ON conversation_turn_history(occurred_at DESC,source_sequence DESC)")
        connection.execute("CREATE INDEX conversation_proposals_by_id_order ON conversation_proposal_history(proposal_id,occurred_at DESC,source_sequence DESC)")
        connection.execute("CREATE INDEX conversation_proposals_by_order ON conversation_proposal_history(occurred_at DESC,source_sequence DESC)")
        connection.execute("CREATE INDEX agent_actions_by_order ON agent_action_history(occurred_at DESC,source_sequence DESC)")
        connection.execute("CREATE INDEX agent_actions_by_outcome_order ON agent_action_history(outcome,occurred_at DESC,source_sequence DESC)")
        resolver_hash, resolver_profiles = _resolver_snapshot()
        connection.executemany("INSERT INTO resolver_profiles VALUES(?,?,?)", resolver_profiles)
        connection.execute("INSERT INTO projection_meta VALUES(1,?,?,?,?,?,0,?,?,?,-1,?,?,?,0,?)",
                           (CONTROL_SCHEMA_VERSION, PROJECTOR_VERSION,
                            RESOLVER_VERSION, AS_OF_VERSION, METADATA_VERSION,
                            "0" * 64, 0, "0" * 64, "0" * 64,
                            _applied_events_genesis(CONTROL_SCHEMA_VERSION,
                            PROJECTOR_VERSION), resolver_hash, state))

    @staticmethod
    def _materialize_event(connection, entry):
        """Losslessly store one authenticated event and its first query models.

        Domain numbers remain in canonical JSON or TEXT columns. In particular,
        monetary values never pass through Python float or SQLite REAL.
        """
        event = entry.event
        payload = event.to_dict(); body = payload["body"]
        provenance = payload["provenance"]
        prov = (provenance.get("doc_id", ""), provenance.get("page"),
                provenance.get("region", ""), provenance.get("note", ""))
        kind = event.event_type
        connection.execute("INSERT INTO event_provenance VALUES(?,?,?,?,?)",
                           (entry.sequence, *prov))
        account_id = body.get("account_id")
        if account_id:
            connection.execute("INSERT OR IGNORE INTO account_entities VALUES(?)", (account_id,))
        if kind in ("AccountOpened", "AccountIdentityObserved") and account_id:
            connection.execute(
                "INSERT INTO accounts VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (entry.sequence, kind, account_id, event.occurred_at,
                 body.get("kind"), body.get("name"), body.get("currency"),
                 body.get("jurisdiction"), body.get("institution", ""),
                 body.get("account_number", ""), body.get("origin"), *prov))
            for index, name in enumerate(body.get("account_names", ())):
                connection.execute("INSERT INTO account_names VALUES(?,?,?)",
                                   (entry.sequence, index, name))
            if prov[0]:
                connection.execute(
                    "INSERT INTO document_account_history VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (entry.sequence, 0, kind, event.occurred_at, prov[0],
                     account_id, "account", *prov))
        if kind in ("OpeningBalanceObserved", "ClosingBalanceObserved") and account_id:
            connection.execute(
                "INSERT INTO balance_observations VALUES(?,?,?,?,?,?,?,?,?,?)",
                (entry.sequence, kind, account_id, event.occurred_at,
                 body["amount"], (body.get("confirmed_by") if kind == "ClosingBalanceObserved"
                                  else None), *prov))
            if kind == "ClosingBalanceObserved" and prov[0]:
                connection.execute(
                    "INSERT INTO statement_periods VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (entry.sequence, kind, account_id, prov[0], event.occurred_at,
                     body["amount"], body.get("confirmed_by", ""), *prov))
            if prov[0]:
                connection.execute(
                    "INSERT INTO document_account_history VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (entry.sequence, 0, kind, event.occurred_at, prov[0],
                     account_id, "opening" if kind == "OpeningBalanceObserved"
                     else "closing", *prov))
        if kind == "TransactionRecorded":
            connection.execute(
                "INSERT INTO transactions VALUES(?,?,?,?,?,?,?,?)",
                (entry.sequence, kind, event.occurred_at, body.get("description", ""), *prov))
            for index, tag in enumerate(body.get("tags", ())):
                connection.execute("INSERT INTO transaction_tags VALUES(?,?,?)",
                                   (entry.sequence, index, tag))
            for index, posting in enumerate(body.get("postings", ())):
                connection.execute("INSERT OR IGNORE INTO account_entities VALUES(?)",
                                   (posting["account"],))
                connection.execute(
                    "INSERT INTO postings VALUES(?,?,?,?,?)",
                    (entry.sequence, index, posting["account"],
                     posting["amount"], posting.get("grade", "unverified")))
                if prov[0]:
                    connection.execute(
                        "INSERT INTO document_account_history VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                        (entry.sequence, index, kind, event.occurred_at, prov[0],
                         posting["account"], "transaction", *prov))
        if kind == "PositionObserved" and account_id:
            connection.execute(
                "INSERT INTO positions VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (entry.sequence, kind, account_id, event.occurred_at,
                 body.get("instrument", ""), body.get("units", ""),
                 body.get("market_value", ""), body.get("currency", ""),
                 body.get("cost_basis", ""), body.get("valuation_class", "measured"),
                 body.get("grade", ""), *prov))
            if prov[0]:
                connection.execute(
                    "INSERT INTO document_account_history VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (entry.sequence, 0, kind, event.occurred_at, prov[0],
                     account_id, "position", *prov))
        if kind == "DocumentCaptured" and body.get("doc_id"):
            connection.execute(
                "INSERT INTO documents VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (entry.sequence, kind, body["doc_id"], event.occurred_at,
                 body.get("filename", ""), body.get("byte_len", 0),
                 body.get("doc_type", ""),
                 _canonical(body.get("doc_type_confidence")).decode(), "captured", *prov))
        if kind == "ReadRecorded" and body.get("doc_id"):
            connection.execute(
                "INSERT INTO document_reads VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (entry.sequence, kind, body["doc_id"], event.occurred_at,
                 body.get("model", ""), body.get("model_role", ""),
                 body.get("resolved_model"), body.get("prompt_version", ""),
                 body.get("input_mode", ""), body.get("response_text", ""),
                 _canonical(body.get("cost_usd", 0)).decode(),
                 body.get("input_tokens"), body.get("output_tokens"),
                 (None if "usage_reported" not in body
                  else int(bool(body.get("usage_reported")))),
                 int(bool(body.get("parse_ok"))), body.get("parse_error"),
                 body.get("phase", "extract"), _canonical(body).decode(), *prov))
        if kind in ("StatementHeld", "BrokerageActivityHeld") and body.get("doc_id"):
            connection.execute(
                "INSERT INTO document_holds VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (entry.sequence, kind, body["doc_id"], event.occurred_at,
                 body.get("reason", "activity" if kind == "BrokerageActivityHeld" else ""),
                 _canonical(body.get("facts", {})).decode(),
                 (None if body.get("finding") is None
                  else _canonical(body["finding"]).decode()), *prov))
        if kind == "BrokerageActivityResolved" and body.get("doc_id"):
            connection.execute(
                "INSERT INTO document_hold_resolutions VALUES(?,?,?,?,?,?,?,?)",
                (entry.sequence, kind, body["doc_id"], event.occurred_at, *prov))
        if kind == "CorrectionApplied" and body.get("doc_id"):
            connection.execute(
                "INSERT INTO document_corrections VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (entry.sequence, kind, body["doc_id"], event.occurred_at,
                 body.get("target", ""), body.get("from", ""), body.get("to", ""),
                 body.get("by", ""), *prov))
        if kind in ("TransferLinked", "TransferUnlinked", "TransferSuggested"):
            evidence = body.get("evidence") or {}
            connection.execute(
                "INSERT INTO transfer_history VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (entry.sequence, kind, event.occurred_at, body.get("a", ""),
                 body.get("b"), _canonical(body.get("candidates") or []).decode(),
                 body.get("status", ""), body.get("grade", ""),
                 evidence.get("decided_by", ""), body.get("by", ""),
                 _canonical(evidence).decode(), *prov))
        if kind == "CategoryAssigned":
            connection.execute(
                "INSERT INTO category_history VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (entry.sequence, kind, event.occurred_at, body.get("movement_key", ""),
                 body.get("descriptor", ""), body.get("category", ""),
                 body.get("subcategory", ""), body.get("nature", ""),
                 body.get("grade", ""), body.get("by", ""),
                 body.get("category_grade", body.get("grade", "")),
                 body.get("subcategory_grade", body.get("grade", "")),
                 body.get("category_by", body.get("by", "")),
                 body.get("subcategory_by", body.get("by", "")), *prov))
        if kind in ("MerchantCategorized", "MerchantEnriched"):
            connection.execute(
                "INSERT INTO merchant_history VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (entry.sequence, kind, event.occurred_at, body.get("merchant", ""),
                 body.get("category", ""), body.get("subcategory", ""),
                 body.get("canonical_name", ""),
                 _canonical(body.get("attributes") or {}).decode(),
                 _canonical(body.get("aliases") or []).decode(), body.get("grade", ""),
                 body.get("by", ""), body.get("category_grade", body.get("grade", "")),
                 body.get("subcategory_grade", body.get("grade", "")),
                 body.get("category_by", body.get("by", "")),
                 body.get("subcategory_by", body.get("by", "")), *prov))
        if kind == "MovementTagged":
            connection.execute(
                "INSERT INTO tag_history VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (entry.sequence, kind, event.occurred_at, body.get("scope", "movement"),
                 body.get("subject", ""), _canonical(body.get("tags") or []).decode(),
                 body.get("by", ""), *prov))
        if kind == "RulingRecorded":
            connection.execute(
                "INSERT INTO ruling_history VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (entry.sequence, kind, event.occurred_at, body.get("scope", ""),
                 body.get("subject", ""), _canonical(body.get("legs") or []).decode(),
                 body.get("by", ""), body.get("grade", ""), body.get("said", ""),
                 body.get("corroborates", ""), body.get("same_as", ""),
                 str(body.get("value", "")), body.get("currency", ""),
                 body.get("prompt_version", ""), *prov))
            if body.get("scope") == "attribute":
                attribute_account, separator, attribute_key = body.get(
                    "subject", "").rpartition(":")
                if separator and attribute_account and attribute_key:
                    connection.execute(
                        "INSERT INTO attribute_history VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (entry.sequence, kind, event.occurred_at,
                         attribute_account, attribute_key,
                         str(body.get("value", "")), body.get("currency", ""),
                         body.get("grade", ""), body.get("said", ""),
                         body.get("by", ""), *prov))
        if kind == "AccountAliasConfirmed":
            connection.execute(
                "INSERT INTO account_alias_history VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (entry.sequence, kind, event.occurred_at, body.get("alias_key", ""),
                 body.get("account_id", ""), body.get("doc_id", ""),
                 body.get("by", ""), int(body.get("learn_signal", True)),
                 _canonical(body.get("match_names") or []).decode(),
                 body.get("match_label", ""), body.get("kind", ""),
                 int(any(key in body for key in
                         ("match_names", "match_label", "kind"))), *prov))
        if kind in ("GoalCreated", "GoalTermsChanged", "GoalFundsReserved",
                    "GoalFundsReleased", "GoalStateChanged"):
            connection.execute(
                "INSERT INTO goal_event_history VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (entry.sequence, kind, event.occurred_at,
                 body.get("goal_id", ""), body.get("account_id"),
                 body.get("amount"), body.get("proposal_id", ""),
                 _canonical(body).decode(), *prov))
        if kind in ("GoalProposalRecorded", "GoalProposalResolved"):
            connection.execute(
                "INSERT INTO goal_proposal_history VALUES(?,?,?,?,?,?,?,?,?)",
                (entry.sequence, kind, event.occurred_at,
                 body.get("proposal_id", ""), _canonical(body).decode(), *prov))
        if kind in ("ConversationTurnOpened", "ConversationTurnSettled"):
            connection.execute(
                "INSERT INTO conversation_turn_history VALUES(?,?,?,?,?,?,?,?,?)",
                (entry.sequence, kind, event.occurred_at,
                 body.get("turn_id", ""), _canonical(body).decode(), *prov))
        if kind in ("ConversationProposalRecorded", "ConversationProposalResolved"):
            connection.execute(
                "INSERT INTO conversation_proposal_history VALUES(?,?,?,?,?,?,?,?,?)",
                (entry.sequence, kind, event.occurred_at,
                 body.get("proposal_id", ""), _canonical(body).decode(), *prov))
        if kind == "AgentActed":
            connection.execute(
                "INSERT INTO agent_action_history VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (entry.sequence, kind, event.occurred_at, body.get("rule", ""),
                 body.get("kind", ""), body.get("target", ""),
                 body.get("outcome", ""), body.get("calls", 0),
                 _canonical(body.get("stake") or {}).decode(),
                 body.get("produced", ""), body.get("replaced", ""),
                 body.get("detail", ""), body.get("by", ""),
                 _canonical(body).decode(), *prov))

        if (kind in ("OpeningBalanceObserved", "ClosingBalanceObserved",
                     "TransactionRecorded", "PositionObserved")
                and prov[0]):
            connection.execute(
                "INSERT INTO posted_document_events VALUES(?,?,?,?,?,?,?,?)",
                (entry.sequence, kind, prov[0], event.occurred_at, *prov))

        review = {
            "QuestionDeclined": ("declined", body.get("question_id", ""),
                                 body.get("kind", "")),
            "FindingSetAside": ("set_aside", body.get("finding_id", ""),
                                body.get("kind", "")),
            "RulingRecorded": ("ruled", body.get("subject", ""),
                              body.get("scope", "")),
            "CorrectionApplied": ("corrected", body.get("doc_id", ""),
                                  body.get("target", "")),
        }.get(kind)
        if review is not None:
            connection.execute(
                "INSERT INTO review_decisions VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (entry.sequence, kind, event.occurred_at, *review,
                 _canonical(body).decode(), *prov))

    @staticmethod
    def _assert_ready(connection):
        identity = connection.execute("SELECT format_version FROM read_store_identity").fetchone()
        state = connection.execute("SELECT state FROM projection_meta WHERE singleton=1").fetchone()
        if identity != (METADATA_VERSION,) or state != ("ready",):
            raise ReadStoreError("read-store generation is incomplete or incompatible")

    @staticmethod
    def _source_identity(connection):
        row = connection.execute("SELECT source_count, source_head, last_sequence, last_hash, "
                                 "applied_events_digest, resolver_content_hash "
                                 "FROM projection_meta WHERE singleton=1").fetchone()
        source = dict(zip(("count", "head", "last_sequence", "last_hash",
                           "applied_events_digest", "resolver_content_hash"), row))
        actual, _rows = _stored_resolver_snapshot(connection)
        if not hmac.compare_digest(actual, source["resolver_content_hash"]):
            raise ReadStoreError("read revision resolver snapshot is corrupt")
        return source

    @staticmethod
    def _publication_epoch(connection):
        return int(connection.execute("SELECT publication_epoch FROM projection_meta "
                                      "WHERE singleton=1").fetchone()[0])

    def _assert_manifest_matches(self, connection, manifest):
        self._assert_ready(connection)
        if (self._publication_epoch(connection) != manifest["epoch"]
                or self._source_identity(connection) != manifest["source"]):
            raise ReadStoreError("read-store manifest does not match its source revision")

    @staticmethod
    def _inject(selected, boundary):
        if selected == boundary: raise RuntimeError(f"injected read-store publication failure: {boundary}")

    def _referenced(self, generation):
        with self._references_lock: return self._references.get(generation, 0) > 0

    def _release(self, generation):
        with self._references_lock:
            count = self._references.get(generation, 0)
            if count <= 1: self._references.pop(generation, None)
            else: self._references[generation] = count - 1
        if not self._closed: self._cleanup_best_effort()

    def _quarantine(self, path):
        _contained(self.directory / GENERATIONS_NAME, path)
        if path.is_symlink(): raise ReadStoreError(f"unsafe read-store path: {path.name}")
        if not path.exists() or self._referenced(path.name): return
        target = self.directory / QUARANTINE_NAME / f"{path.name}-{uuid.uuid4().hex}"
        try: os.replace(path, target)
        except OSError: return

    def _ensure_open(self):
        if self._closed: raise ReadStoreError("read store is closed")
