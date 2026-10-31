"""SQLCipher staging, atomic promotion and independently replayable SQL audit."""
from __future__ import annotations

from contextlib import contextmanager
from collections import deque
import copy
import base64
from dataclasses import asdict, dataclass, is_dataclass
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


def _connect(path, key):
    _regular(path)
    db = sql.connect(str(path), timeout=5, isolation_level=None)
    try:
        version = db.execute("PRAGMA cipher_version").fetchone()
        if not version or not version[0]:
            raise AuthorityError("SQLCipher is required; plaintext SQLite is forbidden")
        db.execute(f"PRAGMA key = \"x'{key.hex()}'\"")
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

    def __init__(self, root, key, db):
        self.root, self._key, self._db = root, key, db
        from .reading import implementation_identity
        self._implementation_identity = implementation_identity()
        self._audit_key = _derive(key, b"audit")
        self._raw = RawStore(root / "originals", _derive(key, b"originals"))
        self._lock = threading.RLock()
        self._operations = None
        self._transfer_facts = None
        self.last_queries = ()
        self.last_rows_read = 0
        self._queries = None
        self.last_vm_steps = 0
        self._fault = lambda _point: None
        self._curated_owner = None
        self.last_source_timings = {}
        self.last_source_metrics = self.last_source_timings
        self._progress_callback = None

    @classmethod
    def create(cls, root, passphrase):
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
        db = _connect(database, _derive(key, b"database"))
        try:
            store = cls(root, key, db)
            db.executescript("BEGIN IMMEDIATE;" + DDL)
            db.execute("INSERT INTO format VALUES (?,?)", (FORMAT, SCHEMA_VERSION))
            mac = store._mac(0, ZERO)
            db.execute("INSERT INTO control VALUES(1,0,?,?)", (ZERO, mac))
            db.execute("COMMIT")
            store._check_terminal()
            return store
        except BaseException:
            db.close()
            raise

    @classmethod
    def open(cls, root, passphrase):
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
        db = _connect(root / "authority.db", _derive(key, b"database"))
        try:
            store = cls(root, key, db)
            if db.execute("SELECT * FROM format").fetchall() != [(FORMAT, SCHEMA_VERSION)]:
                raise AuthorityError("unknown authority schema")
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
        self._operations.append({"table": table, "row": dict(row)})

    @contextmanager
    def _transaction(self):
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                revision, previous = self._check_terminal()
                self._revision = revision + 1
                self._operations = []
                self._transfer_facts = {"transfer_inventory": {}, "transfer_bindings": {}}
                yield
                if self._operations:
                    self._fault("before_audit")
                    envelope = canonical(seal(self._audit_key, canonical({"version": 1, "operations": self._operations}).encode(), aad=canonical([self._revision, previous]).encode()))
                    digest = hashlib.sha256(canonical([self._revision, previous, envelope]).encode()).hexdigest()
                    mac = self._mac(self._revision, digest)
                    self._db.execute("INSERT INTO audit VALUES(?,?,?,?)", (self._revision, previous, envelope, digest))
                    self._db.execute("INSERT INTO commits VALUES(?,?,?)", (self._revision, digest, mac))
                    self._db.execute("UPDATE control SET revision=?,head=?,mac=? WHERE singleton=1", (self._revision, digest, mac))
                    self._fault("before_commit")
                self._db.execute("COMMIT")
                self._fault("after_commit")
            except BaseException:
                if self._db.in_transaction:
                    self._db.execute("ROLLBACK")
                raise
            finally:
                self._transfer_facts = None
                self._operations = None

    def _item(self, doc_id, state, reason="", account_id=""):
        self._put("items", dict(doc_id=doc_id, state=state, reason=reason,
                                account_id=account_id, revision=self._revision))

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

    def original(self, doc_id):
        if type(doc_id) is not str or len(doc_id) != 64 or any(char not in "0123456789abcdef" for char in doc_id):
            raise AuthorityError("invalid document address")
        _regular(self.root / "originals" / (doc_id + ".blob"))
        return self._raw.get_bounded(doc_id, max_plaintext=MAX_SOURCE_BYTES,
                                     max_envelope=72 * 1024 * 1024)

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
        path = self.root / "originals" / (doc_id + ".blob")
        if path.exists() or path.is_symlink():
            _regular(path)
            if self.original(doc_id) != original:
                raise IntegrityError("source address mismatch")
        else:
            _durable_json(path, seal(_derive(self._key, b"originals"), original, aad=doc_id.encode("ascii")))

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
                retained = _encode(result)
                body = canonical(retained)
                if len(body.encode()) > MAX_RECEIPT_BYTES:
                    raise AuthorityError("extraction receipt exceeds bound")
                facts = result.facts
                from .reading import capture_types
                facts_type = "curated" if source is not None else "balance" if type(facts) is StatementFacts else "unsupported"
                facts_json = canonical(_encode(facts))
                receipt_started = time.perf_counter()
                with self._transaction():
                    if admission is not None:
                        self._put("source_admissions", dict(doc_id=doc_id, body=canonical({**admission, "read_context_id": context_id})))
                    self._put("receipts", dict(doc_id=doc_id, contract=contract, body=body,
                                               facts_type=facts_type, facts=facts_json,
                                               capture_types=canonical({**capture_types(facts), "read_context_id": context_id})))
                    self._item(doc_id, "staged", "retained extraction awaiting validation")
                if source is not None:
                    self.last_source_timings["receipt_seconds"] = time.perf_counter()-receipt_started
                self._fault("after_raw_receipt")
            if self.item(doc_id)["state"] in {"staged", "pending"}:
                return self.resume(doc_id)
            return self._outcome(doc_id)

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

    def movements(self):
        from .transfers import movements
        with self._transfer_snapshot():
            return movements(self)

    def transfer_inventory(self):
        from .transfers import rows
        with self._transfer_snapshot():
            return rows(self, "transfer_inventory", order="source_order")

    def transfer_bindings(self):
        from .transfers import rows
        with self._transfer_snapshot():
            return rows(self, "transfer_bindings", order="source_order")

    def transfer_links(self):
        from .transfers import live_links
        with self._transfer_snapshot():
            return live_links(self)

    def transfer_suggestions(self, *, stored=False):
        from .transfers import suggestions
        with self._transfer_snapshot():
            return suggestions(self, stored)

    def transfer_assertions(self):
        from .transfers import assertion_rows
        with self._transfer_snapshot():
            return assertion_rows(self)

    def transfer_decisions(self):
        from .transfers import rows
        with self._transfer_snapshot():
            return [{**row, "body": json.loads(row["body"])} for row in rows(self, "transfer_runs", order="(SELECT revision FROM items WHERE doc_id=transfer_runs.boundary),run_id")]

    def transfer_as_of(self, day):
        from .transfers import as_of
        with self._transfer_snapshot():
            return as_of(self, day)

    def confirm_transfer(self, a, b, *, today=None):
        from .transfers import manual
        with localcontext() as arithmetic:
            arithmetic.prec = 28
            arithmetic.traps[Inexact] = True
            return manual(self, "confirm", a, b, today)

    def reject_transfer(self, a, *, today=None):
        from .transfers import manual
        with localcontext() as arithmetic:
            arithmetic.prec = 28
            arithmetic.traps[Inexact] = True
            return manual(self, "reject", a, today=today)

    def unlink_transfer(self, a, b, *, today=None):
        from .transfers import manual
        with localcontext() as arithmetic:
            arithmetic.prec = 28
            arithmetic.traps[Inexact] = True
            return manual(self, "unlink", a, b, today)

    def transfer_dependency_plans(self):
        from .transfers import plans
        return plans(self)

    def account(self, account_id):
        with self._lock:
            self._check_terminal()
            row = self._row("accounts", "account_id=?", (account_id,))
            if row is None:
                raise AuthorityError("unknown accepted account")
            mapping = self._row("account_keys", "account_id=?", (account_id,))
            if mapping is not None:
                row.update(logical_key=mapping["logical_key"], creation_order=mapping["creation_order"])
            row.update(earliest_opening=row["earliest_amount"], running_balance=row["current_amount"])
            return row

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

    def source_admission(self, doc_id):
        with self._lock:
            row = self._row("source_admissions", "doc_id=?", (doc_id,))
            return json.loads(row["body"]) if row else None

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

    def source_occurrences(self, doc_id):
        with self._lock:
            columns = TABLES["source_occurrences"]
            values = self._read("SELECT doc_id,line_index,event_id,date,page,raw FROM source_occurrences WHERE doc_id=? ORDER BY line_index", (doc_id,))
            return [{**dict(zip(columns, value)), "ordinal": value[1]} for value in values]

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

    def identity_decision(self, doc_id):
        with self._lock:
            rows = self._read("SELECT body FROM identity_decisions WHERE doc_id=? ORDER BY created_revision DESC,decision_id DESC LIMIT 1", (doc_id,))
            return json.loads(rows[0][0]) if rows else None

    def resolve_source_identity(self, facts):
        from .identity import resolve_source
        with self._lock:
            return resolve_source(self, facts)

    def dependency_plans(self):
        with self._lock:
            return {"account": self._db.execute("EXPLAIN QUERY PLAN SELECT * FROM accounts WHERE identity=?", ("identity",)).fetchall(),
                    "period": self._db.execute("EXPLAIN QUERY PLAN SELECT * FROM periods WHERE account_id=? AND period_end=?", ("account", "2000-01-01")).fetchall(),
                    "pending": self._db.execute("EXPLAIN QUERY PLAN SELECT doc_id FROM dependencies WHERE identity=? AND boundary_amount=? AND direction=? AND active=1", ("identity", "0", "forward")).fetchall()}

    def export_audit(self):
        with self._lock:
            self._db.execute("BEGIN")
            try:
                revision, head = self._check_terminal()
                rows = self._db.execute("SELECT sequence,previous_hash,envelope,record_hash FROM audit ORDER BY sequence").fetchall()
                commits = self._db.execute("SELECT revision,head,mac FROM commits ORDER BY revision").fetchall()
                sources = [{"doc_id": doc_id, "sha256": doc_id, "byte_count": size} for doc_id, size in self._db.execute("SELECT doc_id,byte_count FROM documents ORDER BY doc_id").fetchall()]
                result = {"format": FORMAT, "revision": revision, "head": head,
                          "sources": sources,
                          "mac": self._mac(revision, head), "records": [list(row) for row in rows],
                          "commits": [list(row) for row in commits]}
                self._db.execute("COMMIT")
                return result
            except BaseException:
                self._db.execute("ROLLBACK")
                raise

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

    def _reconstruct(self, export, expected_head):
        self.check_export_structure(export, expected_head=expected_head)
        if not hmac.compare_digest(export["mac"], self._mac(export["revision"], export["head"])):
            raise IntegrityError("audit head MAC mismatch")
        state = {table: {} for table in TABLES}
        for record, commit in zip(export["records"], export["commits"]):
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
        expected_sources = [{"doc_id": row["doc_id"], "sha256": row["doc_id"], "byte_count": row["byte_count"]}
                            for _key, row in sorted(state["documents"].items())]
        if expected_sources != export["sources"]:
            raise IntegrityError("exported sources disagree with authenticated audit")
        return state

    def verify(self, *, expected_head=None):
        with self._lock:
            export = self.export_audit()
            state = self._reconstruct(export, expected_head)
            self._db.execute("BEGIN")
            try:
                if self.head != {"revision": export["revision"], "head": export["head"]}:
                    raise IntegrityError("authority changed during verification")
                counts = {}
                for table, columns in TABLES.items():
                    actual = {tuple(row[columns.index(key)] for key in KEYS[table]): dict(zip(columns, row)) for row in self._db.execute(f"SELECT {','.join(chr(34) + column + chr(34) for column in columns)} FROM {table}").fetchall()}
                    if actual != state[table]:
                        raise IntegrityError(f"audited state mismatch: {table}")
                    counts[table] = len(actual)
                from .identity import verify_semantics
                verify_semantics(self, state)
                from .transfer_verify import verify as verify_transfers
                with localcontext() as arithmetic:
                    arithmetic.prec = 28
                    arithmetic.traps[Inexact] = True
                    verify_transfers(self, state, export)
                for key, document in state["documents"].items():
                    if len(self.original(key[0])) != document["byte_count"]:
                        raise IntegrityError("source size mismatch")
                self._db.execute("COMMIT")
                return {"verified": True, "revision": export["revision"], "head": export["head"], "counts": counts}
            except BaseException:
                self._db.execute("ROLLBACK")
                raise
