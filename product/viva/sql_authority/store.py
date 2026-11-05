"""SQLCipher staging, atomic promotion and independently replayable SQL audit."""
from __future__ import annotations

from contextlib import contextmanager, nullcontext
from functools import wraps
from collections import deque
import copy
import base64
from dataclasses import asdict, dataclass, fields, is_dataclass
from decimal import Decimal, localcontext, Inexact
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import stat
import threading
import time

from sqlcipher3 import dbapi2 as sql

from ..crypto import (new_vault_header, open_vault_header, seal, open_sealed,
                      SCRYPT_N, SCRYPT_R, SCRYPT_P, SALT_LEN, KdfParams)
from ..ingest.raw_store import RawStore, _durable_json
from ..ledger.platform_io import lock_writer, unlock_writer
from ..ingest.pipeline_models import ReadResult
from ..ingest.statement import StatementFacts
from .schema import DDL, FORMAT, SCHEMA_VERSION, TABLES, KEYS, MUTABLE, valid_row

ZERO = "0" * 64
MAX_SOURCE_BYTES = 50 * 1024 * 1024
MAX_RECEIPT_BYTES = 8 * 1024 * 1024


class AuthorityError(ValueError):
    """The experimental authority refused an unsafe or unsupported operation."""


class IntegrityError(AuthorityError):
    """Stored evidence or its authenticated boundary disagrees."""


@dataclass(frozen=True)
class ImportOutcome:
    doc_id: str
    status: str
    reason: str
    account_id: str
    revision: int
    settlement_ms: float = 0.0


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False)


def _encode(value):
    from ..ingest.paystub import PayStubFacts
    from ..ingest.brokerage import BrokerageFacts
    if type(value) in {PayStubFacts,BrokerageFacts}:
        return _encode(value.to_dict())
    if type(value) is ReadResult and type(value.facts) in {PayStubFacts,BrokerageFacts}:
        return {field.name: _encode(getattr(value, field.name)) for field in fields(ReadResult)}
    if isinstance(value, Decimal):
        return str(value)
    if is_dataclass(value):
        return {key: _encode(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {key: _encode(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_encode(item) for item in value]
    return value


def _derive(key, domain):
    return hmac.digest(key, b"sql-authority-prototype-v1\0" + domain, "sha256")


def _safe_root(root, *, create=False):
    root = Path(root).absolute()
    if ".." in root.parts:
        raise AuthorityError("authority path must be canonical")
    for path in (root, *root.parents):
        if path.exists() or path.is_symlink():
            if path.is_symlink() or not path.is_dir():
                raise AuthorityError("unsafe authority directory")
    if create:
        root.mkdir(mode=0o700, parents=True, exist_ok=False)
    if not root.is_dir() or stat.S_IMODE(root.stat().st_mode) & 0o077:
        raise AuthorityError("authority root must be private")
    return root


def _regular(path):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise AuthorityError("authority file must be a regular private file")
    if stat.S_IMODE(info.st_mode) & 0o077:
        raise AuthorityError("authority file must be private")


def _verification_policy(value):
    if type(value) is not str or value not in {"indexed", "complete"}:
        raise AuthorityError("unknown authority verification policy")
    return value


def _cipher_capability(db):
    version = db.execute("PRAGMA cipher_version").fetchone()
    words = version[0].split() if version and type(version[0]) is str else []
    parts = words[0].split(".") if words else []
    if len(parts) < 2 or not all(part.isascii() and part.isdigit() for part in parts[:2]):
        raise AuthorityError("unsupported encrypted integrity capability")
    if tuple(map(int, parts[:2])) < (4, 2):
        raise AuthorityError("unsupported encrypted integrity capability")
    enabled = db.execute("PRAGMA cipher_use_hmac").fetchall()
    if (len(enabled) != 1 or len(enabled[0]) != 1
            or type(enabled[0][0]) not in (int, str) or enabled[0][0] not in (1, "1")):
        raise AuthorityError("encrypted page authentication is required")


def _canonical_read(method):
    @wraps(method)
    def guarded(self, *args, **kwargs):
        with self._decision():
            return method(self, *args, **kwargs)
    return guarded


def _application_phase(method):
    @wraps(method)
    def guarded(self, *args, **kwargs):
        with self._application_context("phase"):
            return method(self, *args, **kwargs)
    return guarded


def _connect(path, key, *, verification="indexed"):
    _regular(path)
    db = sql.connect(str(path), timeout=5, isolation_level=None)
    try:
        version = db.execute("PRAGMA cipher_version").fetchone()
        if not version or not version[0]:
            raise AuthorityError("SQLCipher is required; plaintext SQLite is forbidden")
        db.execute(f"PRAGMA key = \"x'{key.hex()}'\"")
        if verification == "complete":
            db.execute("PRAGMA cipher_use_hmac=ON")
            _cipher_capability(db)
        expected = {"cipher_plaintext_header_size": 0, "temp_store": 2,
                    "journal_mode": "delete", "synchronous": 2,
                    "foreign_keys": 1, "trusted_schema": 0, "busy_timeout": 5000}
        for name, value in expected.items():
            db.execute(f"PRAGMA {name}={value}")
        db.execute("SELECT count(*) FROM sqlite_master").fetchone()
        for name, wanted in expected.items():
            got = db.execute(f"PRAGMA {name}").fetchone()[0]
            if isinstance(wanted, int):
                got = int(got)
            if got != wanted:
                raise AuthorityError("unsafe encrypted database settings")
        return db
    except BaseException:
        db.close()
        raise


class SQLAuthority:
    """An explicitly created experimental format, with no legacy migration."""

    def __init__(self, root, key, db, *, verification="indexed", _application_binding=None):
        self._verification = _verification_policy(verification)
        self.root, self._key, self._db = root, key, db
        self._application_binding = _application_binding
        self._application_required = _application_binding is not None
        if _application_binding is None:
            _regular(root / "authority.json")
            if json.loads((root / "authority.json").read_text()).get("format") != FORMAT:
                raise AuthorityError("nonprototype construction requires issued application ownership")
        if _application_binding is not None:
            from .application import _install_engine
            _install_engine(_application_binding, self)
        from .reading import implementation_identity
        self._implementation_identity = implementation_identity()
        self._audit_key = _derive(key, b"audit")
        self._raw = RawStore(root / "originals", _derive(key, b"originals"))
        self._lock = threading.RLock()
        self._operations = None
        self._verified_operation = False
        self._verifying = False
        self._transfer_facts = None
        self.last_queries = ()
        self.last_rows_read = 0
        self._queries = None
        self.last_vm_steps = 0
        self._fault = lambda _point: None
        self._curated_owner = None
        self._verification_originals = None
        self._semantic_collection = None
        self.last_source_timings = {}
        self.last_source_metrics = self.last_source_timings
        self._progress_callback = None

    @classmethod
    def create(cls, root, passphrase, *, verification="indexed", application=False):
        if type(application) is not bool:
            raise AuthorityError("closed application selection required")
        verification = _verification_policy(verification)
        if application:
            if verification != "complete":
                raise AuthorityError("application authority requires complete verification")
            from .application import ApplicationSQLAuthority
            return ApplicationSQLAuthority.create(root, passphrase)
        root = _safe_root(root, create=True)
        header, key = new_vault_header(passphrase)
        metadata = {"format": FORMAT, "crypto": header,
                    "check": seal(key, FORMAT.encode(), aad=b"sql-authority-format")}
        _durable_json(root / "authority.json", metadata)
        os.chmod(root / "authority.json", 0o600)
        (root / "originals").mkdir(mode=0o700)
        database = root / "authority.db"
        fd = os.open(database, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
        db = _connect(database, _derive(key, b"database"), verification=verification)
        try:
            store = cls(root, key, db, verification=verification)
            db.executescript("BEGIN IMMEDIATE;" + DDL)
            db.execute("INSERT INTO format VALUES (?,?)", (FORMAT, SCHEMA_VERSION))
            mac = store._mac(0, ZERO)
            db.execute("INSERT INTO control VALUES(1,0,?,?)", (ZERO, mac))
            db.execute("COMMIT")
            if verification == "complete":
                store.verify()
            else:
                store._check_terminal()
            return store
        except BaseException:
            db.close()
            raise

    @classmethod
    def open(cls, root, passphrase, *, verification="indexed", curated_source=None, application=False):
        if type(application) is not bool:
            raise AuthorityError("closed application selection required")
        verification = _verification_policy(verification)
        if application:
            if verification != "complete":
                raise AuthorityError("application authority requires complete verification")
            from .application import ApplicationSQLAuthority
            return ApplicationSQLAuthority.open(root, passphrase, curated_source=curated_source)
        if curated_source is not None:
            from .curated import _owned
            _owned(curated_source)
        root = _safe_root(root)
        allowed = {"authority.json", "authority.db", "authority.db-journal", "originals"}
        if set(path.name for path in root.iterdir()) - allowed:
            raise AuthorityError("unknown or legacy authority layout")
        _regular(root / "authority.json")
        if (root / "authority.json").stat().st_size > 8192:
            raise AuthorityError("authority header exceeds bound")
        def closed_object(pairs):
            value = {}
            for name, item in pairs:
                if name in value:
                    raise AuthorityError("duplicate authority header field")
                value[name] = item
            return value
        metadata = json.loads((root / "authority.json").read_text(), object_pairs_hook=closed_object)
        if set(metadata) != {"format", "crypto", "check"} or metadata["format"] != FORMAT:
            raise AuthorityError("unknown authority format")
        if (type(metadata["crypto"]) is not dict or set(metadata["crypto"]) != {"v", "kdf", "check"}
                or type(metadata["crypto"]["kdf"]) is not dict
                or set(metadata["crypto"]["kdf"]) != {"salt", "n", "r", "p"}):
            raise AuthorityError("unknown authority crypto header")
        kdf = metadata["crypto"]["kdf"]
        if any(type(kdf[name]) is not int for name in ("n", "r", "p")) or type(kdf["salt"]) is not str:
            raise AuthorityError("invalid authority KDF parameters")
        salt = base64.b64decode(kdf["salt"], validate=True)
        if base64.b64encode(salt).decode("ascii") != kdf["salt"]:
            raise AuthorityError("noncanonical authority KDF salt")
        params = KdfParams.from_dict(kdf)
        if (params.n, params.r, params.p, len(params.salt)) != (SCRYPT_N, SCRYPT_R, SCRYPT_P, SALT_LEN):
            raise AuthorityError("unsupported authority KDF policy")
        key = open_vault_header(metadata["crypto"], passphrase)
        if open_sealed(key, metadata["check"], aad=b"sql-authority-format") != FORMAT.encode():
            raise IntegrityError("authority format authentication failed")
        originals = root / "originals"
        if originals.is_symlink() or not originals.is_dir() or stat.S_IMODE(originals.stat().st_mode) & 0o077:
            raise AuthorityError("unsafe originals directory")
        for side in root.glob("authority.db*"):
            _regular(side)
        db = _connect(root / "authority.db", _derive(key, b"database"), verification=verification)
        try:
            store = cls(root, key, db, verification=verification)
            if curated_source is not None:
                store.attach_curated(curated_source)
            if db.execute("SELECT * FROM format").fetchall() != [(FORMAT, SCHEMA_VERSION)]:
                raise AuthorityError("unknown authority schema")
            if verification == "complete":
                store.verify()
            else:
                store._check_terminal()
            return store
        except BaseException:
            db.close()
            raise

    def close(self):
        with self._lock:
            self._db.close()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()

    @property
    def verification(self):
        return self._verification

    def _application_context(self, kind):
        if self._application_binding is None:
            if self._application_required:
                raise AuthorityError("application engine binding is missing")
            return nullcontext()
        from .application import _owned_binding
        return _owned_binding(self._application_binding, self).operation(kind)

    def _application_event(self, name, *args):
        if self._application_required and self._application_binding is None:
            raise AuthorityError("application engine binding is missing")
        if self._application_binding is not None:
            from .application import _owned_binding
            return getattr(_owned_binding(self._application_binding, self), name)(*args)

    @contextmanager
    def _snapshot(self):
        with self._lock:
            if self._db.in_transaction or self._verified_operation or self._verifying:
                raise AuthorityError("verification requires an independent committed operation")
            self._db.execute("BEGIN")
            try:
                # BEGIN is deferred: establish the actual reader snapshot before
                # the physical-page scan and retain it through the answer.
                self._application_event("verify_schema")
                self._check_terminal()
                yield
                self._db.execute("COMMIT")
            except BaseException:
                if self._db.in_transaction:
                    self._db.execute("ROLLBACK")
                raise

    @contextmanager
    def _decision(self):
        with self._application_context("decision"):
            with self._decision_inside():
                yield

    @contextmanager
    def _decision_inside(self):
        if self._verification == "indexed":
            yield
            return
        with self._lock:
            if self._verified_operation:
                yield
                return
            with self._snapshot():
                self._verified_operation = True
                try:
                    if not self._application_event("_bind_certified_read"):
                        self._verify_current()
                    yield
                finally:
                    self._verified_operation = False

    def _mac(self, revision, head):
        return hmac.new(self._audit_key, canonical([FORMAT, revision, head]).encode(), hashlib.sha256).hexdigest()

    def _check_terminal(self):
        rows = self._read("SELECT revision,head,mac FROM control WHERE singleton=1")
        row = rows[0] if rows else None
        if row is None or not hmac.compare_digest(row[2], self._mac(row[0], row[1])):
            raise IntegrityError("invalid authenticated authority head")
        revision, head, mac = row
        if revision:
            commits = self._read("SELECT head,mac FROM commits WHERE revision=?", (revision,))
            commit = commits[0] if commits else None
            terminals = self._read("SELECT record_hash FROM audit WHERE sequence=?", (revision,))
            terminal = terminals[0] if terminals else None
            if commit != (head, mac) or terminal != (head,):
                raise IntegrityError("missing terminal audit or commit")
        return revision, head

    @property
    @_canonical_read
    def head(self):
        with self._lock:
            revision, head = self._check_terminal()
            return {"revision": revision, "head": head}

    def _read(self, statement, parameters=()):
        if self._queries is not None:
            self._queries.append(statement)
        rows = self._db.execute(statement, parameters).fetchall()
        if self._queries is not None:
            self.last_rows_read += len(rows)
        return rows

    def _row(self, table, where, parameters):
        columns = TABLES[table]
        rows = self._read(f"SELECT {','.join(chr(34) + column + chr(34) for column in columns)} FROM {table} WHERE {where}", parameters)
        return dict(zip(columns, rows[0])) if rows else None

    def _put(self, table, row):
        columns = TABLES[table]
        if self._operations is None or not valid_row(table, row):
            raise AuthorityError("closed audited row required")
        keys = KEYS[table]
        where = " AND ".join(f"{key}=?" for key in keys)
        prior = self._row(table, where, tuple(row[key] for key in keys))
        if prior == row:
            return
        if prior is not None and table not in MUTABLE:
            raise IntegrityError("immutable evidence cannot change")
        if prior is None:
            self._db.execute(f"INSERT INTO {table}({','.join(chr(34) + column + chr(34) for column in columns)}) VALUES({','.join('?' for _ in columns)})", tuple(row[key] for key in columns))
        else:
            assignments = tuple(column for column in columns if column not in keys)
            self._db.execute(f"UPDATE {table} SET {','.join(f'{key}=?' for key in assignments)} WHERE {where}", tuple(row[key] for key in assignments) + tuple(row[key] for key in keys))
        if table == "accounts":
            self._investment_prior_accounts.setdefault(row["account_id"],prior)
        self._operations.append({"table": table, "row": dict(row)})

    @contextmanager
    def _transaction(self):
        with self._application_context("transaction"), self._lock:
            if self._verified_operation or self._db.in_transaction:
                raise AuthorityError("writer requires an independent committed operation")
            self._db.execute("BEGIN IMMEDIATE")
            try:
                if self._verification == "complete":
                    if not self._application_event("_bind_certified_preimage"):
                        self._verify_current()
                    self._verified_operation = True
                revision, previous = self._check_terminal()
                self._revision = revision + 1
                self._operations = []
                self._investment_prior_accounts = {}
                self._transfer_facts = {"transfer_inventory": {}, "transfer_bindings": {}}
                yield
                from .investment import close_writer as close_investment
                close_investment(self)
                from .payroll import close_writer
                with localcontext() as arithmetic:
                    arithmetic.prec = 28
                    arithmetic.traps[Inexact] = True
                    close_writer(self)
                if self._operations:
                    self._fault("before_audit")
                    envelope = canonical(seal(self._audit_key, canonical({"version": 1, "operations": self._operations}).encode(), aad=canonical([self._revision, previous]).encode()))
                    digest = hashlib.sha256(canonical([self._revision, previous, envelope]).encode()).hexdigest()
                    mac = self._mac(self._revision, digest)
                    self._db.execute("INSERT INTO audit VALUES(?,?,?,?)", (self._revision, previous, envelope, digest))
                    self._db.execute("INSERT INTO commits VALUES(?,?,?)", (self._revision, digest, mac))
                    self._db.execute("UPDATE control SET revision=?,head=?,mac=? WHERE singleton=1", (self._revision, digest, mac))
                    self._fault("before_commit")
                self._application_event("prepare_transaction")
                from .cd_receipt_verify import verify_new_record
                verify_new_record(self, revision, previous)
                from .curated_instrument_verify import verify_new_record as verify_curated_instrument
                verify_curated_instrument(self, revision, previous)
                self._db.execute("COMMIT")
                self._verified_operation = False
                self._application_event("complete_transaction")
                self._fault("after_commit")
            except BaseException:
                if self._db.in_transaction:
                    self._db.execute("ROLLBACK")
                raise
            finally:
                self._verified_operation = False
                self._transfer_facts = None
                self._operations = None
                self._investment_prior_accounts = None

    def _item(self, doc_id, state, reason="", account_id=""):
        self._put("items", dict(doc_id=doc_id, state=state, reason=reason,
                                account_id=account_id, revision=self._revision))

    @_canonical_read
    def item(self, doc_id):
        with self._lock:
            self._check_terminal()
            result = self._row("items", "doc_id=?", (doc_id,))
            if result is None:
                raise AuthorityError("unknown document")
            return result

    def _outcome(self, doc_id, elapsed=0.0):
        item = self.item(doc_id)
        return ImportOutcome(doc_id, item["state"], item["reason"], item["account_id"], item["revision"], elapsed)

    @_canonical_read
    def original(self, doc_id):
        return self._original(doc_id)

    def _original(self, doc_id):
        data, _commitment = self._original_with_commitment(doc_id)
        return data

    def _original_with_commitment(self, doc_id):
        if type(doc_id) is not str or len(doc_id) != 64 or any(char not in "0123456789abcdef" for char in doc_id):
            raise AuthorityError("invalid document address")
        _regular(self.root / "originals" / (doc_id + ".blob"))
        data, commitment = self._raw._get_bounded_with_commitment(doc_id, max_plaintext=MAX_SOURCE_BYTES,
                                                                 max_envelope=72 * 1024 * 1024)
        if self._verification_originals is not None:
            observed = (commitment,len(data))
            if doc_id in self._verification_originals and self._verification_originals[doc_id] != observed:
                raise IntegrityError("original changed between authenticated verification reads")
            self._verification_originals[doc_id] = observed
        self._application_event("_checked_original",doc_id,commitment,len(data))
        return data, commitment

    @_canonical_read
    def receipt(self, doc_id):
        with self._lock:
            self._check_terminal()
            row = self._row("receipts", "doc_id=?", (doc_id,))
            if row is None:
                raise AuthorityError("no completed extraction receipt")
            raw_reading = json.loads(row["body"])
            interpretation = self._row("interpretations", "doc_id=?", (doc_id,))
            reading = dict(raw_reading)
            if interpretation is not None:
                reading["authority_context"] = json.loads(interpretation["context"])
            evidence = interpretation or row
            return {"contract": row["contract"], "reading": reading,
                    "raw_reading": raw_reading, "facts_type": evidence["facts_type"],
                    "facts": json.loads(evidence["facts"])}

    @contextmanager
    def _document_lock(self, doc_id):
        if self._application_required:
            from .application import _owned_binding
            with _owned_binding(self._application_binding, self).document_lock(doc_id):
                yield
            return
        directory = os.open(self.root / "originals", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            try:
                descriptor = os.open(doc_id + ".lock", os.O_CREAT | os.O_EXCL | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600, dir_fd=directory)
            except FileExistsError:
                descriptor = os.open(doc_id + ".lock", os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        finally:
            os.close(directory)
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) & 0o077:
                raise AuthorityError("unsafe document lock")
            lock_writer(descriptor)
            try:
                yield
            finally:
                unlock_writer(descriptor)
        finally:
            os.close(descriptor)

    def _capture_original(self, doc_id, original):
        if self._application_required:
            return self._application_event("capture", doc_id, original)
        path = self.root / "originals" / (doc_id + ".blob")
        if path.exists() or path.is_symlink():
            _regular(path)
            if self.original(doc_id) != original:
                raise IntegrityError("source address mismatch")
        else:
            _durable_json(path, seal(_derive(self._key, b"originals"), original, aad=doc_id.encode("ascii")))

    @_application_phase
    def attach_curated(self, source):
        from .curated import _owned
        _owned(source)
        self._curated_owner = source

    def ingest_curated(self, original, source):
        from .curated import _owned
        from ..sample.curation import CONTRACT
        _owned(source)
        self.attach_curated(source)
        self.last_source_timings = {}
        self.last_source_metrics = self.last_source_timings
        from .incremental import _automatic
        with _automatic(self,original,source):
            return self._ingest(original, None, contract=CONTRACT, source=source)

    def ingest(self, original, reader, *, contract):
        return self._ingest(original, reader, contract=contract)

    def _ingest(self, original, reader, *, contract, source=None):
        if type(original) is not bytes or len(original) > MAX_SOURCE_BYTES:
            raise AuthorityError("source bytes exceed bound")
        if type(contract) is not str or not contract or len(contract.encode()) > 256:
            raise AuthorityError("explicit bounded extraction contract required")
        doc_id = self._raw.fingerprint(original)
        with self._document_lock(doc_id):
            capture_started = time.perf_counter()
            self._capture_original(doc_id, original)
            if source is not None:
                self.last_source_timings["capture_seconds"] = time.perf_counter()-capture_started
            with self._transaction():
                existing = self._row("documents", "doc_id=?", (doc_id,))
                if existing is not None and existing["contract"] != contract:
                    raise AuthorityError("retained extraction contract differs")
                if existing is None:
                    self._put("documents", dict(doc_id=doc_id, byte_count=len(original), contract=contract))
                    self._item(doc_id, "captured")
            current = self.item(doc_id)
            if current["state"] == "captured":
                from .reading import current_read_context
                context_body = canonical(current_read_context(self._implementation_identity))
                context_id = hashlib.sha256(context_body.encode()).hexdigest()
                with self._transaction():
                    self._put("read_contexts", dict(context_id=context_id, body=context_body))
                    self._item(doc_id, "read_uncertain", "reading admitted; completion not retained")
                admission = None
                if source is not None:
                    from .curated import issue
                    result, admission = issue(source, original, doc_id)
                else:
                    result = copy.deepcopy(reader(original, doc_id))
                if type(result) is not ReadResult:
                    raise AuthorityError("reader must return ReadResult")
                facts = result.facts
                from .reading import capture_types
                from ..ingest.paystub import PayStubFacts
                from ..ingest.brokerage import BrokerageFacts
                from ..ingest.instrument_read import InstrumentReadFacts
                from ..ingest.instrument_contracts import DepositFacts
                ordinary_cd = (source is None and type(facts) is InstrumentReadFacts
                               and type(facts.payload) is DepositFacts)
                if ordinary_cd:
                    from .cd_receipts import encode_ordinary_cd_receipt
                    captured_cd = encode_ordinary_cd_receipt(result, read_context_id=context_id)
                    body, facts_json = captured_cd["body"], captured_cd["facts"]
                    tags_json = captured_cd["capture_types"]
                    facts_type = "cd_capture_v1"
                else:
                    retained = _encode(result)
                    body = canonical(retained)
                    if len(body.encode()) > MAX_RECEIPT_BYTES:
                        raise AuthorityError("extraction receipt exceeds bound")
                    facts_type = "curated" if source is not None else "balance" if type(facts) is StatementFacts else "payroll" if type(facts) is PayStubFacts else "investment" if type(facts) is BrokerageFacts else "unsupported"
                    facts_json = canonical(_encode(facts))
                    tags_json = canonical({**capture_types(facts), "read_context_id": context_id})
                receipt_started = time.perf_counter()
                with self._transaction():
                    if admission is not None:
                        self._put("source_admissions", dict(doc_id=doc_id, body=canonical({**admission, "read_context_id": context_id})))
                    self._put("receipts", dict(doc_id=doc_id, contract=contract, body=body,
                                               facts_type=facts_type, facts=facts_json,
                                               capture_types=tags_json))
                    self._item(doc_id, "staged", "retained extraction awaiting validation")
                if source is not None:
                    self.last_source_timings["receipt_seconds"] = time.perf_counter()-receipt_started
                self._fault("after_raw_receipt")
            if self.item(doc_id)["state"] in {"staged", "pending"}:
                return self.resume(doc_id)
            return self._outcome(doc_id)

    @_application_phase
    def resume(self, doc_id):
        from .bank import settle
        started = time.perf_counter()
        queries = []
        with self._lock:
            self._queries, self.last_rows_read = queries, 0
            self.last_vm_steps = 0
            def count_vm():
                self.last_vm_steps += 100
                return 0
            self._progress_callback = count_vm
            self._db.set_progress_handler(count_vm, 100)
            try:
                with self._transaction():
                    item = self._row("items", "doc_id=?", (doc_id,))
                    if item is None:
                        raise AuthorityError("unknown document")
                    if item["state"] in {"staged", "pending"}:
                        queue, attempted = deque([doc_id]), set()
                        admitted = []
                        while queue:
                            current = queue.popleft()
                            if current not in attempted:
                                attempted.add(current)
                                with localcontext() as arithmetic:
                                    arithmetic.prec = 28
                                    arithmetic.traps[Inexact] = True
                                    queue.extend(settle(self, current) or ())
                                if self._row("items", "doc_id=?", (current,))["state"] == "accepted":
                                    admitted.append(current)
                        if admitted:
                            from .transfers import settle_dirty
                            with localcontext() as arithmetic:
                                arithmetic.prec = 28
                                arithmetic.traps[Inexact] = True
                                settle_dirty(self, doc_id, admitted)
                return self._outcome(doc_id, (time.perf_counter() - started) * 1000)
            finally:
                self._db.set_progress_handler(None, 0)
                self._progress_callback = None
                self.last_source_timings["settlement_seconds"] = time.perf_counter()-started
                self._queries = None
                self.last_queries = tuple(queries)

    @contextmanager
    def _transfer_snapshot(self):
        with self._lock:
            owned = not self._db.in_transaction
            if owned:
                self._db.execute("BEGIN")
            try:
                self._check_terminal()
                yield
                if owned:
                    self._db.execute("COMMIT")
            except BaseException:
                if owned and self._db.in_transaction:
                    self._db.execute("ROLLBACK")
                raise

    @_canonical_read
    def movements(self):
        from .transfers import movements
        with self._transfer_snapshot():
            return movements(self)

    @_canonical_read
    def transfer_inventory(self):
        from .transfers import rows
        with self._transfer_snapshot():
            return rows(self, "transfer_inventory", order="source_order")

    @_canonical_read
    def transfer_bindings(self):
        from .transfers import rows
        with self._transfer_snapshot():
            return rows(self, "transfer_bindings", order="source_order")

    @_canonical_read
    def transfer_links(self):
        from .transfers import live_links
        with self._transfer_snapshot():
            return live_links(self)

    @_canonical_read
    def transfer_suggestions(self, *, stored=False):
        from .transfers import suggestions
        with self._transfer_snapshot():
            return suggestions(self, stored)

    @_canonical_read
    def transfer_assertions(self):
        from .transfers import assertion_rows
        with self._transfer_snapshot():
            return assertion_rows(self)

    @_canonical_read
    def transfer_decisions(self):
        from .transfers import rows
        with self._transfer_snapshot():
            return [{**row, "body": json.loads(row["body"])} for row in rows(self, "transfer_runs", order="(SELECT revision FROM items WHERE doc_id=transfer_runs.boundary),run_id")]

    @_canonical_read
    def transfer_as_of(self, day):
        from .transfers import as_of
        with self._transfer_snapshot():
            return as_of(self, day)

    @_application_phase
    def confirm_transfer(self, a, b, *, today=None):
        from .transfers import manual
        with localcontext() as arithmetic:
            arithmetic.prec = 28
            arithmetic.traps[Inexact] = True
            return manual(self, "confirm", a, b, today)

    @_application_phase
    def reject_transfer(self, a, *, today=None):
        from .transfers import manual
        with localcontext() as arithmetic:
            arithmetic.prec = 28
            arithmetic.traps[Inexact] = True
            return manual(self, "reject", a, today=today)

    @_application_phase
    def unlink_transfer(self, a, b, *, today=None):
        from .transfers import manual
        with localcontext() as arithmetic:
            arithmetic.prec = 28
            arithmetic.traps[Inexact] = True
            return manual(self, "unlink", a, b, today)

    def transfer_dependency_plans(self):
        from .transfers import plans
        return plans(self)

    @_canonical_read
    def account(self, account_id):
        with self._lock:
            self._check_terminal()
            row = self._row("accounts", "account_id=?", (account_id,))
            if row is None:
                raise AuthorityError("unknown accepted account")
            if row["kind"] == "investment":
                from .investment import cash_account_guard
                cash_account_guard(self,row)
            mapping = self._row("account_keys", "account_id=?", (account_id,))
            if mapping is not None:
                row.update(logical_key=mapping["logical_key"], creation_order=mapping["creation_order"])
            row.update(earliest_opening=row["earliest_amount"], running_balance=row["current_amount"])
            return row

    @_canonical_read
    def transactions(self, account_id):
        with self._lock:
            self._check_terminal()
            rows = self._read("SELECT txn_id,doc_id,line_index,account_id,date,description,page,amount,source_reference,counterparty_reference FROM transactions WHERE account_id=? ORDER BY date,doc_id,line_index", (account_id,))
            results = []
            for values in rows:
                row = dict(zip(TABLES["transactions"], values))
                row.update(ordinal=row["line_index"], grade="verified", provenance={"doc_id": row["doc_id"], "page": row["page"], "region": "", "note": ""})
                results.append(row)
            return results

    @_canonical_read
    def postings(self, doc_id):
        with self._lock:
            self._check_terminal()
            rows = self._read("SELECT p.txn_id,p.leg,p.account_id,p.amount,p.grade,p.currency,p.doc_id,p.page,t.line_index FROM postings p JOIN transactions t ON t.txn_id=p.txn_id WHERE p.doc_id=? ORDER BY t.line_index,p.leg", (doc_id,))
            results = []
            for values in rows:
                row = dict(zip(TABLES["postings"], values[:8]))
                row.update(ordinal=values[8], account=row["account_id"], provenance={"doc_id": row["doc_id"], "page": row["page"], "region": "", "note": ""})
                results.append(row)
            return results

    @_canonical_read
    def balance_observations(self, account_id):
        with self._lock:
            self._check_terminal()
            columns = TABLES["balance_observations"]
            rows = self._read("SELECT observation_id,doc_id,account_id,kind,date,amount,page,currency,grade,event_asserted FROM balance_observations WHERE account_id=? ORDER BY date,kind,doc_id", (account_id,))
            result = []
            for values in rows:
                row = dict(zip(columns, values))
                row["event_asserted"] = bool(row["event_asserted"])
                row["provenance"] = {"doc_id": row["doc_id"], "page": row["page"], "region": "", "note": row["kind"] + " balance"}
                result.append(row)
            return result

    @_canonical_read
    def investment_component(self, doc_id):
        from .investment import component_view
        with self._lock:
            self._check_terminal()
            return component_view(self,doc_id)

    @_canonical_read
    def income_expense(self, *, start='', end=''):
        from .accounting import read
        from .accounting_verify import verify
        with self._lock:
            if self._verification!='complete':
                raise AuthorityError('income/expense requires complete verification')
            result=read(self,start=start,end=end)
            verify(self,result,start=start,end=end)
            return result

    @_canonical_read
    def investment_snapshot(self, account_id, *, as_of):
        from .investment import snapshot_view
        with self._lock:
            self._check_terminal()
            return snapshot_view(self,account_id,as_of)

    @_canonical_read
    def investment_cash_period(self, doc_id):
        from .investment import cash_period_view
        with self._lock:
            self._check_terminal()
            return cash_period_view(self,doc_id)

    @_canonical_read
    def investment_activity(self, doc_id):
        from .investment import activity_view
        with self._lock:
            self._check_terminal()
            return activity_view(self,doc_id)

    @_canonical_read
    def investment_postings(self, doc_id):
        from .investment import postings_view
        with self._lock:
            self._check_terminal()
            return postings_view(self,doc_id)

    @_canonical_read
    def investment_history(self, doc_id):
        from .investment import history_view
        with self._lock:
            self._check_terminal()
            return history_view(self,doc_id)

    @_canonical_read
    def payroll_facts(self, doc_id):
        from .payroll import fact_view
        with self._lock:
            self._check_terminal()
            return fact_view(self, doc_id)

    @_canonical_read
    def payroll_component(self, doc_id):
        from .payroll import component_view
        with self._lock:
            self._check_terminal()
            return component_view(self, doc_id)

    @_canonical_read
    def payroll_decisions(self, doc_id):
        from .payroll import decisions_view
        with self._lock:
            self._check_terminal()
            return decisions_view(self, doc_id)

    @_canonical_read
    def payroll_postings(self, doc_id=None):
        from .payroll import posting_view
        with self._lock:
            self._check_terminal()
            return posting_view(self, doc_id)

    @_canonical_read
    def source_admission(self, doc_id):
        with self._lock:
            row = self._row("source_admissions", "doc_id=?", (doc_id,))
            return json.loads(row["body"]) if row else None

    @_canonical_read
    def source_transactions(self, doc_id):
        with self._lock:
            columns = TABLES["transactions"]
            values = self._read("SELECT txn_id,doc_id,line_index,account_id,date,description,page,amount,source_reference,counterparty_reference FROM transactions WHERE doc_id=? ORDER BY line_index", (doc_id,))
            result = []
            for raw in values:
                row = dict(zip(columns, raw))
                account = self._row("accounts", "account_id=?", (row["account_id"],))
                row.update(ordinal=row["line_index"], grade="verified", currency=account["currency"], tags=[],
                    provenance={"doc_id": doc_id, "page": row["page"], "region": "", "note": ""})
                result.append(row)
            return result

    @_canonical_read
    def source_occurrences(self, doc_id):
        with self._lock:
            columns = TABLES["source_occurrences"]
            values = self._read("SELECT doc_id,line_index,event_id,date,page,raw FROM source_occurrences WHERE doc_id=? ORDER BY line_index", (doc_id,))
            return [{**dict(zip(columns, value)), "ordinal": value[1]} for value in values]

    @_canonical_read
    def source_observations(self, doc_id):
        with self._lock:
            columns = TABLES["balance_observations"]
            values = self._read("SELECT observation_id,doc_id,account_id,kind,date,amount,page,currency,grade,event_asserted FROM balance_observations WHERE doc_id=? ORDER BY kind", (doc_id,))
            result = []
            for value in values:
                row = dict(zip(columns, value))
                row["event_asserted"] = bool(row["event_asserted"])
                row["provenance"] = {"doc_id": doc_id, "page": row["page"], "region": "", "note": row["kind"]+" balance"}
                result.append(row)
            return result

    @_canonical_read
    def identity_decision(self, doc_id):
        with self._lock:
            rows = self._read("SELECT body FROM identity_decisions WHERE doc_id=? ORDER BY created_revision DESC,decision_id DESC LIMIT 1", (doc_id,))
            return json.loads(rows[0][0]) if rows else None

    @_canonical_read
    def resolve_source_identity(self, facts):
        from .identity import resolve_source
        with self._lock:
            return resolve_source(self, facts)

    def dependency_plans(self):
        with self._lock:
            return {"account": self._db.execute("EXPLAIN QUERY PLAN SELECT * FROM accounts WHERE identity=?", ("identity",)).fetchall(),
                    "period": self._db.execute("EXPLAIN QUERY PLAN SELECT * FROM periods WHERE account_id=? AND period_end=?", ("account", "2000-01-01")).fetchall(),
                    "pending": self._db.execute("EXPLAIN QUERY PLAN SELECT doc_id FROM dependencies WHERE identity=? AND boundary_amount=? AND direction=? AND active=1", ("identity", "0", "forward")).fetchall()}

    def _export_current(self):
        revision, head = self._check_terminal()
        rows = self._db.execute("SELECT sequence,previous_hash,envelope,record_hash FROM audit ORDER BY sequence").fetchall()
        commits = self._db.execute("SELECT revision,head,mac FROM commits ORDER BY revision").fetchall()
        sources = [{"doc_id": doc_id, "sha256": doc_id, "byte_count": size} for doc_id, size in self._db.execute("SELECT doc_id,byte_count FROM documents ORDER BY doc_id").fetchall()]
        return {"format": FORMAT, "revision": revision, "head": head,
                "sources": sources, "mac": self._mac(revision, head),
                "records": [list(row) for row in rows],
                "commits": [list(row) for row in commits]}

    def export_audit(self):
        with self._application_context("decision"), self._lock:
            if self._verifying or (self._db.in_transaction and self._operations is not None):
                raise AuthorityError("export requires a committed authority snapshot")
            if self._verification == "complete":
                with self._decision():
                    return self._export_current()
            with self._snapshot():
                return self._export_current()

    @staticmethod
    def check_export_structure(export, *, expected_head=None):
        if type(export) is not dict or set(export) != {"format", "revision", "head", "mac", "records", "commits", "sources"} or type(export["format"]) is not str or export["format"] != FORMAT:
            raise IntegrityError("unknown audit export")
        if (type(export["revision"]) is not int or not 0 <= export["revision"] <= 2 ** 63 - 1
                or type(export["records"]) is not list or type(export["commits"]) is not list
                or len(export["records"]) != export["revision"] or len(export["commits"]) != export["revision"]):
            raise IntegrityError("audit export boundary mismatch")
        for field in ("head", "mac"):
            if type(export[field]) is not str or len(export[field]) != 64 or any(char not in "0123456789abcdef" for char in export[field]):
                raise IntegrityError("invalid audit boundary encoding")
        if expected_head is not None and (type(expected_head) is not dict or set(expected_head) != {"revision", "head"}
                or type(expected_head["revision"]) is not int or type(expected_head["head"]) is not str):
            raise IntegrityError("invalid trusted audit boundary")
        sources = export["sources"]
        if type(sources) is not list:
            raise IntegrityError("invalid exported source catalog")
        seen = set()
        for source in sources:
            if (type(source) is not dict or set(source) != {"doc_id", "sha256", "byte_count"}
                    or type(source["doc_id"]) is not str or len(source["doc_id"]) != 64
                    or any(char not in "0123456789abcdef" for char in source["doc_id"])
                    or type(source["sha256"]) is not str or source["sha256"] != source["doc_id"] or source["doc_id"] in seen
                    or type(source["byte_count"]) is not int or not 0 <= source["byte_count"] <= MAX_SOURCE_BYTES):
                raise IntegrityError("invalid exported source binding")
            seen.add(source["doc_id"])
        previous = ZERO
        for index, record in enumerate(export["records"], 1):
            if type(record) is not list or len(record) != 4:
                raise IntegrityError("invalid audit record")
            sequence, prior, envelope, digest = record
            if (type(sequence) is not int or sequence != index or type(prior) is not str
                    or prior != previous or type(envelope) is not str or type(digest) is not str
                    or digest != hashlib.sha256(canonical([sequence, prior, envelope]).encode()).hexdigest()):
                raise IntegrityError("audit chain mismatch")
            commit = export["commits"][index - 1]
            if (type(commit) is not list or len(commit) != 3 or type(commit[0]) is not int
                    or type(commit[1]) is not str or type(commit[2]) is not str
                    or len(commit[2]) != 64 or any(char not in "0123456789abcdef" for char in commit[2])
                    or commit[:2] != [index, digest]):
                raise IntegrityError("audit commit mismatch")
            previous = digest
        if previous != export["head"] or (expected_head is not None and expected_head != {"revision": export["revision"], "head": previous}):
            raise IntegrityError("trusted audit boundary mismatch")
        return {"structural": True, "authenticated": False, "revision": export["revision"]}

    def _advance_reconstruction(self, state, record, commit):
        sequence, previous, envelope, _digest = record
        if not hmac.compare_digest(commit[2], self._mac(commit[0], commit[1])):
            raise IntegrityError("audit commit MAC mismatch")
        payload = json.loads(open_sealed(self._audit_key, json.loads(envelope), aad=canonical([sequence, previous]).encode()))
        if type(payload) is not dict or set(payload) != {"version", "operations"} or type(payload["version"]) is not int or payload["version"] != 1 or type(payload["operations"]) is not list or not payload["operations"]:
            raise IntegrityError("unknown audit payload")
        for operation in payload["operations"]:
            if type(operation) is not dict or set(operation) != {"table", "row"}:
                raise IntegrityError("unknown audit operation")
            table, row = operation["table"], operation["row"]
            if not valid_row(table, row):
                raise IntegrityError("unknown audited row")
            key = tuple(row[column] for column in KEYS[table])
            if key in state[table] and table not in MUTABLE:
                raise IntegrityError("immutable audited row rewritten")
            state[table][key] = row
        from .cd_receipt_verify import verify_operations
        verify_operations(self, state, payload["operations"], revision=sequence)
        from .curated_instrument_verify import verify_operations as verify_curated_instruments
        verify_curated_instruments(self, state, payload["operations"], revision=sequence)
        return payload['operations']

    def _finish_reconstruction(self,state,export):
        expected_sources = [{"doc_id": row["doc_id"], "sha256": row["doc_id"], "byte_count": row["byte_count"]}
                            for _key, row in sorted(state["documents"].items())]
        if expected_sources != export["sources"]:
            raise IntegrityError("exported sources disagree with authenticated audit")

    def _reconstruct(self, export, expected_head):
        self.check_export_structure(export, expected_head=expected_head)
        if not hmac.compare_digest(export["mac"], self._mac(export["revision"], export["head"])):
            raise IntegrityError("audit head MAC mismatch")
        state = {table: {} for table in TABLES}
        for record, commit in zip(export['records'],export['commits']):
            self._advance_reconstruction(state,record,commit)
        self._finish_reconstruction(state,export)
        return state

    def _fresh_physical_checks(self):
        self._application_event("verify_schema")
        if self._verification == "complete":
            if self._db.execute("SELECT * FROM format").fetchall() != [(FORMAT, SCHEMA_VERSION)]:
                raise IntegrityError("unknown authority schema")
            _cipher_capability(self._db)
            if self._db.execute("PRAGMA cipher_integrity_check").fetchall():
                raise IntegrityError("encrypted page integrity failure")
            if self._db.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                raise IntegrityError("database structural integrity failure")
            if self._db.execute("PRAGMA foreign_key_check").fetchall():
                raise IntegrityError("database reference integrity failure")

    def _verify_current(self, *, expected_head=None):
        if not self._db.in_transaction or self._verifying:
            raise AuthorityError("verification requires an owned snapshot")
        self._verifying = True
        prior_operation = self._verified_operation
        self._verified_operation = True
        previous_originals = self._verification_originals
        self._verification_originals = {}
        previous_collection=self._semantic_collection
        self._semantic_collection={}
        try:
            self._fresh_physical_checks()
            export = self._export_current()
            representation = self._application_event("verify_representation", export)
            state = self._reconstruct(export, expected_head)
            from . import certified_state as certified
            checked_export_digest = self._certified_sql_digest(export) if representation is not None else None
            checked_tables = []
            counts = {}
            for table, columns in TABLES.items():
                actual = {tuple(row[columns.index(key)] for key in KEYS[table]): dict(zip(columns, row)) for row in self._db.execute(f"SELECT {','.join(chr(34) + column + chr(34) for column in columns)} FROM {table}").fetchall()}
                if actual != state[table]:
                    raise IntegrityError(f"audited state mismatch: {table}")
                counts[table] = len(actual)
                if representation is not None:
                    checked_tables.append((table,certified._table_digest(table,columns,actual.values())))
            from .investment_verify import verify as verify_investment
            verify_investment(self,state,export)
            from .identity import verify_semantics
            verify_semantics(self,state)
            from .payroll_verify import verify as verify_payroll
            from .transfer_verify import verify as verify_transfers
            with localcontext() as arithmetic:
                arithmetic.prec=28;arithmetic.traps[Inexact]=True
                verify_payroll(self,state,export)
                verify_transfers(self,state,export)
            for key, document in state["documents"].items():
                if len(self._original(key[0])) != document["byte_count"]:
                    raise IntegrityError("source size mismatch")
            if representation is not None:
                observed = tuple(sorted((doc,digest,size) for doc,(digest,size) in self._verification_originals.items()))
                if observed != representation.originals:
                    raise IntegrityError("complete source reads differ from checked custody proof")
                self._application_event("_accept_full_verification",representation,checked_export_digest,tuple(checked_tables))
                self._application_event("_accept_full_semantics",state,export,self._semantic_collection['investment'],self._semantic_collection['payroll'],self._semantic_collection['transfer'],self._semantic_collection['decisions'])
            return {"verified": True, "revision": export["revision"], "head": export["head"], "counts": counts}
        finally:
            self._semantic_collection=previous_collection
            self._verification_originals = previous_originals
            self._verified_operation = prior_operation
            self._verifying = False

    def _certified_sql_digest(self, export):
        from . import certified_state as certified
        control = self._db.execute("SELECT singleton,revision,head,mac FROM control ORDER BY singleton").fetchall()
        formats = self._db.execute("SELECT version,schema_version FROM format").fetchall()
        if control != [(1,export['revision'],export['head'],export['mac'])] or formats != [(FORMAT,SCHEMA_VERSION)]:
            raise IntegrityError("complete control or format membership differs")
        return certified._digest({'export':export,'control':control,'format':formats})

    def _bind_verified_state(self, proof, *, initial=False):
        if self._application_binding is None or self._verification != "complete" or not self._db.in_transaction:
            raise AuthorityError("certified binding requires an owned complete application snapshot")
        from .application import _owned_binding
        from . import certified_state as certified
        owner = _owned_binding(self._application_binding,self)
        certified._owner(proof,owner)
        self._fresh_physical_checks()
        if self._certified_sql_digest(self._export_current()) != proof.sql_digest:
            raise IntegrityError("SQL differs from authoritative sealed operations")
        checked = []
        actual_tables = {}
        for table, columns in TABLES.items():
            rows = [dict(zip(columns,row)) for row in self._db.execute(
                f"SELECT {','.join(chr(34)+column+chr(34) for column in columns)} FROM {table}").fetchall()]
            checked.append((table,certified._table_digest(table,columns,rows)))
            actual_tables[table] = {tuple(row[key] for key in KEYS[table]):row for row in rows}
        if tuple(checked) != proof.tables:
            raise IntegrityError("materialized state differs from fully checked state")
        previous_binding = owner._binding_certificate
        previous_operation = self._verified_operation
        owner._binding_certificate = proof
        self._verified_operation = True
        try:
            owner._bind_representation(proof.representation,initial=initial)
            if actual_tables['source_admissions']:
                from .curated import authenticate
                for (doc,),_admission in actual_tables['source_admissions'].items():
                    receipt=actual_tables['receipts'].get((doc,))
                    if receipt is None:
                        raise IntegrityError("checked source admission has no raw receipt")
                    authenticate(self,receipt,json.loads(receipt['body']))
            owner._bind_history(proof.representation)
        finally:
            self._verified_operation = previous_operation
            owner._binding_certificate = previous_binding

    def verify(self, *, expected_head=None):
        with self._application_context("decision"), self._snapshot():
            return self._verify_current(expected_head=expected_head)
