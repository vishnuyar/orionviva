"""Application-owned sealed history around the indexed SQL authority."""
from contextlib import contextmanager
import base64
import os
from pathlib import Path
import secrets
import threading
import time

from ..crypto import (new_vault_header, open_vault_header, seal, open_sealed,
                      SCRYPT_N, SCRYPT_R, SCRYPT_P, SALT_LEN, VERSION)
from .store import SQLAuthority, AuthorityError, IntegrityError, _connect, _derive, ZERO
from .schema import DDL, FORMAT as SQL_FORMAT, SCHEMA_VERSION
from . import application_io as io
from . import application_history as history
from . import application_schema as schema


Busy = io.Busy
RecoveryRequired = io.RecoveryRequired
_ISSUED = {}
_CONSTRUCTION = object()


class _Binding:
    def __init__(self, owner):
        self.owner, self.engine = owner, None
        self.root_identity = io.identity(owner.root)
        self.pid = os.getpid()


def _owned_binding(binding, engine=None):
    record = _ISSUED.get(id(binding))
    if (type(binding) is not _Binding or record is None or record[0] is not binding
            or record[1] is not binding.owner or record[2] != binding.root_identity
            or record[3] != binding.pid or record[4] is not binding.engine
            or binding.pid != os.getpid() or binding.owner._closed
            or io.identity(binding.owner.root) != binding.root_identity
            or (engine is not None and binding.engine is not engine)):
        raise AuthorityError("unissued or expired application engine binding")
    if binding.owner._root_lock.depth and binding.owner._root_lock.owner != threading.get_ident():
        raise AuthorityError("application binding held by another thread")
    return binding.owner


def _install_engine(binding, engine):
    owner = _owned_binding(binding)
    if binding.engine is not None or owner._root_lock.owner != threading.get_ident():
        raise AuthorityError("application construction ownership required")
    if engine.root != owner.root / "sql" or engine.verification != "complete":
        raise AuthorityError("application engine context differs")
    binding.engine = engine
    owner._engine = engine
    _ISSUED[id(binding)] = (binding, owner, binding.root_identity, binding.pid, engine)


def _crypto_header(header):
    history.fields(header, {"v", "kdf", "check"})
    if header["v"] != VERSION:
        raise IntegrityError("unknown application crypto version")
    kdf = history.fields(header["kdf"], {"salt", "n", "r", "p"})
    if any(type(kdf[name]) is not int for name in ("n", "r", "p")) or type(kdf["salt"]) is not str:
        raise IntegrityError("invalid application KDF")
    try:
        salt = base64.b64decode(kdf["salt"], validate=True)
    except ValueError as error:
        raise IntegrityError("invalid application salt") from error
    if (base64.b64encode(salt).decode("ascii") != kdf["salt"]
            or (kdf["n"], kdf["r"], kdf["p"], len(salt)) != (SCRYPT_N, SCRYPT_R, SCRYPT_P, SALT_LEN)):
        raise IntegrityError("unsupported application KDF policy")
    history.envelope(header["check"])
    return header


def _crypto_key(header, passphrase):
    _crypto_header(header)
    return open_vault_header(header, passphrase)


def _metadata(root, passphrase=None, *, timings=None):
    data = io.read(root / "application.json")
    metadata = history.fields(history.decode(data), {"format", "version", "root_id", "crypto", "check"})
    if metadata["format"] != history.FORMAT or type(metadata["version"]) is not int or metadata["version"] != 1:
        raise IntegrityError("unknown application format")
    history.hexadecimal(metadata["root_id"])
    history.envelope(metadata["check"])
    _crypto_header(metadata["crypto"])
    if passphrase is None:
        return metadata, None
    kdf_started = time.perf_counter()
    key = _crypto_key(metadata["crypto"], passphrase)
    if timings is not None:
        timings["outer_kdf_seconds"] = time.perf_counter() - kdf_started
    if open_sealed(history.keys(key)["metadata"], metadata["check"], aad=b"sql-application-format") != history.encoded([history.FORMAT, 1, metadata["root_id"]]):
        raise IntegrityError("application metadata authentication differs")
    return metadata, key


class ApplicationSQLAuthority:
    """A complete-verification SQL facade with independent live sealed history."""

    _METHODS = frozenset({
        "item", "original", "receipt", "movements", "transfer_inventory", "transfer_bindings",
        "transfer_links", "transfer_suggestions", "transfer_assertions", "transfer_decisions",
        "transfer_as_of", "account", "transactions", "postings", "balance_observations",
        "source_admission", "source_transactions", "source_occurrences", "source_observations",
        "identity_decision", "resolve_source_identity", "export_audit", "ingest", "ingest_curated",
        "attach_curated", "resume", "confirm_transfer", "reject_transfer", "unlink_transfer",
        "dependency_plans", "transfer_dependency_plans",
    })
    _METRICS = frozenset({"last_queries", "last_rows_read", "last_vm_steps", "last_source_timings", "last_source_metrics"})

    def __init__(self, root, lock, metadata, key, token):
        if token is not _CONSTRUCTION:
            raise AuthorityError("application owner must be created or opened")
        self.root, self._root_lock, self._metadata, self._key = root, lock, metadata, key
        self._history = history.History(root, metadata["root_id"], key)
        self._engine = None
        self._closed = False
        self._depth = 0
        self._thread = None
        self._observed = None
        self._pending = None
        self._extension = None
        self._committed = False
        self._bootstrapping = False
        self._recovering = False
        self._fault = lambda _point: None
        self.lifecycle_timings = {}
        self._binding = _Binding(self)
        _ISSUED[id(self._binding)] = (self._binding, self, self._binding.root_identity, self._binding.pid, None)

    def __getattr__(self, name):
        if name in self._METHODS:
            def invoke(*args, **kwargs):
                self._check_open()
                if name in {"dependency_plans", "transfer_dependency_plans"}:
                    with self.operation("decision"):
                        with self._engine._decision():
                            return getattr(self._engine, name)(*args, **kwargs)
                return getattr(self._engine, name)(*args, **kwargs)
            return invoke
        if name in self._METRICS:
            self._check_open()
            import copy
            return copy.deepcopy(getattr(self._engine, name))
        raise AttributeError(name)

    @property
    def verification(self):
        return "complete"

    @property
    def head(self):
        self._check_open()
        return self._engine.head

    @property
    def terminal(self):
        with self.operation("decision"):
            with self._engine._decision():
                return dict(self._observed)

    def _check_open(self):
        if _owned_binding(self._binding, self._engine) is not self:
            raise AuthorityError("foreign application owner binding")
        if self._closed:
            raise AuthorityError("application owner is closed")

    @classmethod
    def create(cls, root, passphrase):
        started = time.perf_counter()
        root = Path(root).absolute()
        io.directory(root.parent, private=False)
        io.mkdir(root)
        io.sync_directory(root.parent)
        lock = io.FileLock(root / "application.lock", create=True)
        owner = None
        try:
            with lock.hold():
                io.sync_directory(root)
                kdf_started = time.perf_counter()
                crypto, key = new_vault_header(passphrase)
                outer_kdf_seconds = time.perf_counter() - kdf_started
                root_id = secrets.token_hex(32)
                metadata = dict(format=history.FORMAT, version=1, root_id=root_id, crypto=crypto,
                                check=seal(history.keys(key)["metadata"], history.encoded([history.FORMAT, 1, root_id]), aad=b"sql-application-format"))
                io.replace_head(root / "application.json", history.encoded(metadata), temporary="application.next", allow_absent=True)
                for name in ("history", "pending"):
                    io.mkdir(root / name)
                io.sync_directory(root)
                owner = cls(root, lock, metadata, key, _CONSTRUCTION)
                owner.lifecycle_timings["outer_kdf_seconds"] = outer_kdf_seconds
                owner._bootstrapping = True
                issued = owner._issue("creation")
                owner._begin(issued)
                owner._open_engine(passphrase, create=True)
                owner._fault("after_engine_creation")
                with owner._engine._snapshot():
                    owner._engine._verify_current()
                body = dict(metadata_sha256=history.digest(io.read(root / "application.json")),
                            sql_metadata_sha256=history.digest(io.read(root / "sql" / "authority.json")),
                            sql_format=SQL_FORMAT, sql_schema_version=SCHEMA_VERSION,
                            schema_contract=history.digest(schema.expected().encode("utf-8")))
                owner._prepare(issued, "genesis", body, {"revision": 0, "head": ZERO})
                owner._publish()
                owner._bootstrapping = False
                owner._check_ready()
                owner.verify()
                owner.lifecycle_timings["create_seconds"] = time.perf_counter() - started
            return owner
        except BaseException:
            if owner is not None:
                owner._dispose()
            else:
                lock.close()
            raise

    @classmethod
    def open(cls, root, passphrase, *, curated_source=None):
        started = time.perf_counter()
        if curated_source is not None:
            from .curated import _owned
            _owned(curated_source)
        root = io.directory(root)
        lock = io.FileLock(root / "application.lock")
        owner = None
        try:
            with lock.hold():
                timings = {}
                metadata, key = _metadata(root, passphrase, timings=timings)
                owner = cls(root, lock, metadata, key, _CONSTRUCTION)
                owner.lifecycle_timings.update(timings)
                owner._check_ready()
                owner._open_engine(passphrase, curated_source=curated_source)
                owner.verify()
                owner.lifecycle_timings["open_seconds"] = time.perf_counter() - started
            return owner
        except BaseException:
            if owner is not None:
                owner._dispose()
            else:
                lock.close()
            raise

    def _open_engine(self, passphrase, *, create=False, curated_source=None):
        if _owned_binding(self._binding) is not self:
            raise AuthorityError("application construction binding differs")
        if self._root_lock.owner != threading.get_ident():
            raise AuthorityError("root ownership required before SQL connection")
        root = self.root / "sql"
        if create:
            io.mkdir(root)
            io.mkdir(root / "originals")
            kdf_started = time.perf_counter()
            header, key = new_vault_header(passphrase)
            self.lifecycle_timings["inner_kdf_seconds"] = time.perf_counter() - kdf_started
            metadata = dict(format=history.ENGINE_FORMAT, application_root=self._metadata["root_id"], crypto=header,
                            check=seal(key, history.encoded([history.ENGINE_FORMAT, self._metadata["root_id"]]), aad=b"sql-application-engine-format"))
            io.replace_head(root / "authority.json", history.encoded(metadata), temporary="authority.next", allow_absent=True)
            io.exclusive_write(root / "authority.db", b"")
            io.sync_directory(self.root)
        else:
            metadata = history.fields(history.decode(io.read(root / "authority.json")), {"format", "application_root", "crypto", "check"})
            if metadata["format"] != history.ENGINE_FORMAT or metadata["application_root"] != self._metadata["root_id"]:
                raise IntegrityError("application child identity differs")
            kdf_started = time.perf_counter()
            key = _crypto_key(metadata["crypto"], passphrase)
            self.lifecycle_timings["inner_kdf_seconds"] = time.perf_counter() - kdf_started
            if open_sealed(key, history.envelope(metadata["check"]), aad=b"sql-application-engine-format") != history.encoded([history.ENGINE_FORMAT, self._metadata["root_id"]]):
                raise IntegrityError("application engine metadata differs")
        db = _connect(root / "authority.db", _derive(key, b"database"), verification="complete")
        try:
            engine = SQLAuthority(root, key, db, verification="complete", _application_binding=self._binding)
            if create:
                db.executescript("BEGIN IMMEDIATE;" + DDL)
                db.execute("INSERT INTO format VALUES (?,?)", (SQL_FORMAT, SCHEMA_VERSION))
                db.execute("INSERT INTO control VALUES(1,0,?,?)", (ZERO, engine._mac(0, ZERO)))
                db.execute("COMMIT")
            schema.verify(db)
            if curated_source is not None:
                from .curated import _owned
                _owned(curated_source)
                engine._curated_owner = curated_source
        except BaseException:
            db.close()
            raise

    def _layout(self, *, pending=False):
        io.directory(self.root)
        allowed = {"application.json", "application.lock", "history", "terminal.json", "pending", "sql"}
        actual = {path.name for path in self.root.iterdir()}
        if pending:
            allowed |= {"terminal.next"}
        if actual - allowed or (not pending and actual != allowed):
            raise IntegrityError("unknown or incomplete application layout")
        for name in ("history", "pending", "sql", "sql/originals"):
            if (self.root / name).exists():
                io.directory(self.root / name)
            elif not self._bootstrapping:
                raise RecoveryRequired("application directory incomplete")
        for name in ("application.json", "application.lock", "terminal.json", "terminal.next"):
            if (self.root / name).exists():
                io.regular(self.root / name)
        if (self.root / "sql").exists():
            permitted = {"authority.json", "authority.db", "originals"}
            if pending:
                permitted |= {"authority.db-journal", "authority.next"}
            if {path.name for path in (self.root / "sql").iterdir()} - permitted:
                raise IntegrityError("unknown application SQL member")
            for path in (self.root / "sql").iterdir():
                if path.name != "originals":
                    io.regular(path)
        for path in (self.root / "pending").iterdir():
            history.hexadecimal(path.name)
            io.directory(path)

    def _check_ready(self):
        self._layout(pending=True)
        if list((self.root / "pending").iterdir()) or (self.root / "terminal.next").exists() or (self.root / "sql" / "authority.db-journal").exists():
            raise RecoveryRequired("application has unfinished publication")
        self._layout()
        terminal, _records, _bodies = self._history.scan(prefix=self._observed)
        self._observed = terminal
        return terminal

    @contextmanager
    def operation(self, kind):
        self._check_open()
        with self._root_lock.hold():
            if self._depth and self._thread != threading.get_ident():
                raise AuthorityError("foreign application operation")
            if not self._depth and not self._bootstrapping:
                self._check_ready()
            if kind == "transaction":
                if self._pending is not None:
                    raise AuthorityError("nested application writer refused")
                if self._engine._db.in_transaction or self._engine._verified_operation:
                    raise AuthorityError("writer requires independent committed application operation")
                self._begin(self._issue("transaction"))
            self._depth += 1
            self._thread = threading.get_ident()
            try:
                yield
            except BaseException:
                if kind == "transaction" and self._pending is not None and not self._committed:
                    if not self._engine._db.in_transaction:
                        try:
                            self._abort()
                        except BaseException:
                            # An unsuccessful abort retains its exact pending evidence.
                            pass
                raise
            finally:
                self._depth -= 1
                if not self._depth:
                    self._thread = None

    def _issue(self, kind, capture=None):
        prior = self._observed
        if kind != "creation" and prior is None:
            raise IntegrityError("issued operation needs accepted boundary")
        if prior is not None and (prior["sequence"] >= history.MAX_SEQUENCE
                or (kind == "transaction" and prior["sql_revision"] >= history.MAX_SEQUENCE)):
            raise IntegrityError("application sequence overflow before mutation")
        return dict(version=1, root_id=self._metadata["root_id"], operation_id=secrets.token_hex(32),
                    kind=kind, prior_terminal=None if prior is None else dict(prior),
                    prior_sql={"revision": 0 if prior is None else prior["sql_revision"],
                               "head": ZERO if prior is None else prior["sql_head"]}, capture=capture)

    def _begin(self, issued):
        if list((self.root / "pending").iterdir()):
            raise RecoveryRequired("another pending application operation")
        path = self.root / "pending" / issued["operation_id"]
        io.mkdir(path)
        io.sync_directory(path.parent)
        self._pending = (path, issued)
        self._extension = None
        self._committed = False
        self._set_intent("initial")

    def _set_intent(self, stage, prepared=None, superseded=None):
        path, issued = self._pending
        data = self._history.intent(issued, stage, prepared, superseded)
        io.replace_head(path / "intent.json", data, temporary="intent.next", allow_absent=stage == "initial")
        self._fault("after_" + stage + "_intent")

    def _prepare(self, issued, kind, body, sql_head, *, abort=False, superseded=None):
        path, actual = self._pending
        if issued != actual:
            raise IntegrityError("preparation issued context differs")
        data = self._history.make(issued, kind, body, sql_head)
        name = "prepared-abort.json" if abort else "prepared-publication.json"
        io.exclusive_write(path / name, data)
        self._fault("after_prepared_file")
        self._set_intent("abort_prepared" if abort else "prepared", (name, history.digest(data)), superseded)
        self._extension = data
        return data

    def prepare_transaction(self):
        path, issued = self._pending
        export = self._engine._export_current()
        if export["revision"] == issued["prior_sql"]["revision"]:
            kind, body = "noop", {"intent_sha256": history.digest(history.encoded(issued))}
        elif export["revision"] == issued["prior_sql"]["revision"] + 1:
            kind, body = "sql_commit", {"record": export["records"][-1], "commit": export["commits"][-1]}
        else:
            raise IntegrityError("writer generated unexpected SQL extension")
        self._prepare(issued, kind, body, {"revision": export["revision"], "head": export["head"]})

    def complete_transaction(self):
        self._committed = True
        self._fault("after_sql_commit")
        with self._engine._snapshot():
            self._engine._verify_current()
        self._publish()

    def verify_schema(self):
        if self._root_lock.owner != threading.get_ident():
            raise AuthorityError("schema verification requires root ownership")
        schema.verify(self._engine._db)

    def verify_representation(self, export):
        if self._bootstrapping and not list((self.root / "history").iterdir()):
            if export["revision"] != 0 or export["records"] or export["sources"]:
                raise IntegrityError("creation child is not empty")
            self._layout(pending=True)
            if list((self.root / "sql" / "originals").iterdir()):
                raise IntegrityError("creation child has unexpected original membership")
            return
        terminal, records, payloads = self._history.scan(prefix=self._observed, allow_terminal_lag=self._recovering)
        if self._extension is not None:
            prepared = self._history.record(self._extension, previous=terminal)
            payloads.append(self._history.payload(prepared, previous=terminal))
            records.append(prepared)
        expected_records, expected_commits, custody = [], [], {}
        for record, payload in zip(records, payloads):
            if record["kind"] == "genesis":
                body = payload["body"]
                if (body["metadata_sha256"] != history.digest(io.read(self.root / "application.json"))
                        or body["sql_metadata_sha256"] != history.digest(io.read(self.root / "sql" / "authority.json"))
                        or body["schema_contract"] != history.digest(schema.expected().encode("utf-8"))):
                    raise IntegrityError("genesis metadata or software schema differs")
            elif record["kind"] == "sql_commit":
                expected_records.append(payload["body"]["record"])
                expected_commits.append(payload["body"]["commit"])
            elif record["kind"] == "custody":
                body = payload["body"]
                if body["doc_id"] in custody:
                    raise IntegrityError("duplicate custody publication")
                custody[body["doc_id"]] = body
        if export["records"] != expected_records or export["commits"] != expected_commits:
            raise IntegrityError("SQL differs from authoritative sealed operations")
        originals = self.root / "sql" / "originals"
        actual = set()
        for member in originals.iterdir():
            io.regular(member)
            if member.suffix == ".lock":
                history.hexadecimal(member.stem)
                continue
            if member.suffix != ".blob" or member.stem not in custody:
                raise IntegrityError("unknown original lacks authenticated custody")
            body = custody[member.stem]
            if member.stat().st_size > 72 * 1024 * 1024:
                raise IntegrityError("captured original exceeds existing envelope bound")
            if history.digest(io.read(member)) != body["blob_sha256"]:
                raise IntegrityError("captured ciphertext differs from custody")
            plain = self._engine._original(member.stem)
            if len(plain) != body["byte_count"]:
                raise IntegrityError("captured plaintext length differs")
            actual.add(member.stem)
        if actual != set(custody) or any(source["doc_id"] not in custody or source["byte_count"] != custody[source["doc_id"]]["byte_count"] for source in export["sources"]):
            raise IntegrityError("SQL sources or custody members differ")
        if self._extension is None:
            self._observed = terminal

    def _publish(self):
        path, issued = self._pending
        intent, inner = self._history.read_intent(io.read(path / "intent.json"))
        name = inner["prepared_name"]
        if name is None:
            raise IntegrityError("publication lacks durable prepared intent")
        draft = path / name
        target = self.root / "history" / f"{1 if issued['prior_terminal'] is None else issued['prior_terminal']['sequence'] + 1:020d}.json"
        data = io.read(draft) if draft.exists() else io.read(target)
        if history.digest(data) != inner["prepared_sha256"]:
            raise IntegrityError("publication preparation digest differs")
        record = self._history.record(data, previous=issued["prior_terminal"])
        if self._history.payload(record, previous=issued["prior_terminal"])["issued"] != issued:
            raise IntegrityError("publication prepared owner differs")
        if target.exists():
            if io.read(target) != data:
                raise IntegrityError("existing immutable publication differs")
        else:
            io.no_replace(draft, target)
        if io.read(target) != data:
            raise IntegrityError("published history bytes differ from preparation")
        self._fault("after_history_publication")
        terminal_bytes = self._history.terminal_bytes(record)
        if (self.root / "terminal.next").exists():
            if io.read(self.root / "terminal.next") != terminal_bytes:
                raise IntegrityError("terminal draft differs")
            io.finish_head(self.root / "terminal.json", temporary="terminal.next", expected=terminal_bytes, allow_absent=issued["kind"] == "creation")
            io.sync_directory(self.root)
        else:
            io.replace_head(self.root / "terminal.json", terminal_bytes, temporary="terminal.next", allow_absent=issued["kind"] == "creation")
        self._fault("after_terminal_publication")
        superseded = None if inner["superseded_name"] is None else (inner["superseded_name"], inner["superseded_sha256"])
        if intent["stage"] != "published":
            self._set_intent("published", (name, inner["prepared_sha256"]), superseded)
        self._cleanup(inner, data)
        self._observed = history.terminal_of(record)
        self._pending, self._extension = None, None

    def _cleanup(self, inner, published):
        path, issued = self._pending
        permitted = {"intent.json", inner["prepared_name"]}
        if inner["superseded_name"] is not None:
            permitted.add(inner["superseded_name"])
        if issued["kind"] == "capture":
            permitted.add("prepared-original.blob")
        if {item.name for item in path.iterdir()} - permitted:
            raise IntegrityError("unexpected pending member during cleanup")
        for name, expected in ((inner["prepared_name"], inner["prepared_sha256"]),
                               (inner["superseded_name"], inner["superseded_sha256"]),
                               ("prepared-original.blob", None if issued["capture"] is None else issued["capture"]["blob_sha256"])):
            if name is not None and (path / name).exists():
                if expected is None or history.digest(io.read(path / name)) != expected:
                    raise IntegrityError("cleanup member differs from authenticated intent")
                io.unlink(path / name)
                self._fault("after_prepared_cleanup")
        io.sync_directory(path)
        io.unlink(path / "intent.json")
        io.sync_directory(path)
        self._fault("after_intent_cleanup")
        io.rmdir(path)
        io.sync_directory(path.parent)
        self._fault("after_pending_cleanup")

    def _abort(self):
        path, issued = self._pending
        old = issued["prior_sql"]
        self._extension = None
        if {"revision": self._engine._check_terminal()[0], "head": self._engine._check_terminal()[1]} != old:
            raise RecoveryRequired("SQL commit outcome needs explicit recovery")
        with self._engine._snapshot():
            self._engine._verify_current()
        original = io.read(path / "prepared-publication.json") if (path / "prepared-publication.json").exists() else None
        if original is not None:
            proposed = self._history.record(original, previous=issued["prior_terminal"])
            if self._history.payload(proposed, previous=issued["prior_terminal"])["issued"] != issued:
                raise IntegrityError("abort proposed publication differs")
        body = dict(intent_sha256=history.digest(history.encoded(issued)), interrupted_kind=issued["kind"],
                    prepared_sha256=None if original is None else history.digest(original),
                    superseded_publication=None if original is None else original.decode("utf-8"))
        superseded = None if original is None else ("prepared-publication.json", history.digest(original))
        self._prepare(issued, "interrupted_abort", body, old, abort=True, superseded=superseded)
        self._publish()

    @contextmanager
    def document_lock(self, doc_id):
        history.hexadecimal(doc_id)
        # The document lock is acquired without root and survives the reader.
        lock = None
        with self._root_lock.hold():
            self._check_ready()
            path = self.root / "sql" / "originals" / (doc_id + ".lock")
            try:
                lock = io.FileLock(path, create=True)
                io.sync_directory(path.parent)
            except FileExistsError:
                lock = io.FileLock(path)
        try:
            with lock.hold():
                yield
        finally:
            lock.close()

    def capture(self, doc_id, original):
        self._check_open()
        with self._root_lock.hold():
            self._check_ready()
            with self._engine._snapshot():
                self._engine._verify_current()
            final = self.root / "sql" / "originals" / (doc_id + ".blob")
            if final.exists():
                if self._engine._original(doc_id) != original:
                    raise IntegrityError("duplicate source address differs")
                return
            data = history.encoded(seal(_derive(self._engine._key, b"originals"), original, aad=doc_id.encode("ascii")))
            issued = self._issue("capture", dict(doc_id=doc_id, byte_count=len(original), blob_name="prepared-original.blob", blob_sha256=history.digest(data)))
            self._begin(issued)
            path = self._pending[0]
            io.exclusive_write(path / "prepared-original.blob", data)
            self._fault("after_original_preparation")
            io.no_replace(path / "prepared-original.blob", final)
            if io.read(final) != data:
                raise IntegrityError("published original differs from prepared ciphertext")
            self._fault("after_original_publication")
            self._prepare(issued, "custody", {name: issued["capture"][name] for name in ("doc_id", "byte_count", "blob_sha256")}, issued["prior_sql"])
            self._publish()

    def verify(self, *, expected_head=None, expected_terminal=None):
        with self.operation("decision"):
            if expected_terminal is not None and self._observed != history.boundary(expected_terminal):
                raise IntegrityError("trusted application terminal differs")
            return self._engine.verify(expected_head=expected_head)

    @staticmethod
    def verify_live_chain(root, *, expected_terminal=None):
        root = io.directory(root)
        lock = io.FileLock(root / "application.lock")
        try:
            with lock.hold():
                metadata, _key = _metadata(root)
                expected_names = {"application.json", "application.lock", "history", "terminal.json", "pending", "sql"}
                if {path.name for path in root.iterdir()} - (expected_names | {"terminal.next"}):
                    raise IntegrityError("unknown application layout")
                io.directory(root / "pending")
                if list((root / "pending").iterdir()) or (root / "terminal.next").exists() or (root / "sql" / "authority.db-journal").exists():
                    raise RecoveryRequired("application publication incomplete")
                if {path.name for path in root.iterdir()} != expected_names:
                    raise RecoveryRequired("application layout incomplete")
                io.directory(root / "sql")
                io.directory(root / "sql" / "originals")
                if {path.name for path in (root / "sql").iterdir()} != {"authority.json", "authority.db", "originals"}:
                    raise IntegrityError("unknown or incomplete application SQL layout")
                for name in ("authority.json", "authority.db"):
                    io.regular(root / "sql" / name)
                for member in (root / "sql" / "originals").iterdir():
                    io.regular(member)
                    if member.suffix not in {".blob", ".lock"}:
                        raise IntegrityError("unknown keyless source-layout member")
                    history.hexadecimal(member.stem)
                terminal, _records, _payloads = history.History(root, metadata["root_id"]).scan(expected=expected_terminal)
                return dict(structural=True, authenticated=False, root_id=metadata["root_id"], terminal=terminal)
        finally:
            lock.close()

    def backup(self, destination, *, passphrase, expected_terminal=None):
        from .application_backup import backup
        return backup(self, destination, passphrase=passphrase, expected_terminal=expected_terminal)

    @classmethod
    def restore(cls, backup_directory, destination, passphrase, *, curated_source=None, expected_terminal=None):
        from .application_backup import restore
        return restore(backup_directory, destination, passphrase, curated_source=curated_source, expected_terminal=expected_terminal)

    def _recover_intent_head(self, path):
        current = path / "intent.json"
        temporary = path / "intent.next"
        if temporary.exists():
            next_bytes = io.read(temporary)
            next_outer, next_inner = self._history.read_intent(next_bytes)
            if current.exists():
                outer, inner = self._history.read_intent(io.read(current))
                transitions = {"initial": {"prepared", "abort_prepared"},
                               "prepared": {"abort_prepared", "published"},
                               "abort_prepared": {"published"}, "published": set()}
                if next_inner["issued"] != inner["issued"] or next_outer["stage"] not in transitions[outer["stage"]]:
                    raise IntegrityError("intent temporary is not exact stage successor")
            elif next_outer["stage"] != "initial":
                raise IntegrityError("intent temporary cannot create later-stage ownership")
            if next_outer["operation_id"] != path.name:
                raise IntegrityError("intent temporary directory differs")
            self._validate_issued_frontier(next_inner["issued"])
            self._validate_prepared_members(path, next_outer, next_inner)
            io.finish_head(current, temporary="intent.next", expected=next_bytes, allow_absent=not current.exists())
            io.sync_directory(path)
        if not current.exists():
            raise RecoveryRequired("pending operation lacks authenticated intent")
        outer, inner = self._history.read_intent(io.read(current))
        if outer["operation_id"] != path.name:
            raise IntegrityError("intent directory differs")
        self._validate_issued_frontier(inner["issued"])
        self._validate_prepared_members(path, outer, inner)
        return outer, inner

    def _validate_issued_frontier(self, issued):
        prior = issued["prior_terminal"]
        names = list((self.root / "history").iterdir())
        if not names:
            if issued["kind"] != "creation" or (self.root / "terminal.json").exists():
                raise IntegrityError("issued operation lost preceding history")
            return
        latest, records, payloads = self._history.scan(allow_terminal_lag=True)
        if latest != prior:
            if (latest["sequence"] != (1 if prior is None else prior["sequence"] + 1)
                    or payloads[-1]["issued"] != issued):
                raise IntegrityError("issued frontier differs from exact pending publication")
        if prior is not None and (prior["sequence"] > len(records) or history.terminal_of(records[prior["sequence"] - 1]) != prior):
            raise IntegrityError("issued prior prefix differs")
        if (self.root / "terminal.json").exists():
            terminal = self._history.terminal()
            if terminal != prior and terminal != latest:
                raise IntegrityError("terminal is not pending prior or final boundary")

    def _validate_prepared_members(self, path, outer, inner):
        allowed = {"intent.json", "intent.next", "prepared-publication.json", "prepared-abort.json"}
        if inner["issued"]["kind"] == "capture":
            allowed.add("prepared-original.blob")
        if {member.name for member in path.iterdir()} - allowed:
            raise IntegrityError("unexpected pending recovery member")
        for member in path.iterdir():
            io.regular(member)
        prior = inner["issued"]["prior_terminal"]
        for name in ("prepared-publication.json", "prepared-abort.json"):
            if (path / name).exists():
                data = io.read(path / name)
                record = self._history.record(data, previous=prior)
                payload = self._history.payload(record, previous=prior)
                if payload["issued"] != inner["issued"] or ((name == "prepared-abort.json") != (record["kind"] == "interrupted_abort")):
                    raise IntegrityError("recovery preparation context differs")
        if inner["prepared_name"] is not None and (path / inner["prepared_name"]).exists():
            if history.digest(io.read(path / inner["prepared_name"])) != inner["prepared_sha256"]:
                raise IntegrityError("prepared intent file differs")
        if inner["superseded_name"] is not None and (path / inner["superseded_name"]).exists():
            if history.digest(io.read(path / inner["superseded_name"])) != inner["superseded_sha256"]:
                raise IntegrityError("superseded intent file differs")
        if outer["stage"] == "published":
            sequence = 1 if prior is None else prior["sequence"] + 1
            final = self.root / "history" / f"{sequence:020d}.json"
            if not final.exists() or history.digest(io.read(final)) != inner["prepared_sha256"]:
                raise IntegrityError("published intent lacks exact accepted record")

    @classmethod
    def recover(cls, root, passphrase, *, curated_source=None, expected_prefix=None):
        if curated_source is not None:
            from .curated import _owned
            _owned(curated_source)
        if expected_prefix is not None:
            history.boundary(expected_prefix)
        root = io.directory(root)
        lock = io.FileLock(root / "application.lock")
        owner = None
        try:
            with lock.hold():
                metadata, key = _metadata(root, passphrase)
                owner = cls(root, lock, metadata, key, _CONSTRUCTION)
                owner._recovering = True
                owner._layout(pending=True)
                if expected_prefix is not None:
                    owner._history.scan(prefix=expected_prefix, allow_terminal_lag=True)
                pending = list((root / "pending").iterdir())
                if len(pending) > 1:
                    raise IntegrityError("multiple unfinished application operations")
                if not pending:
                    owner._observed = expected_prefix
                    owner._check_ready()
                    owner._open_engine(passphrase, curated_source=curated_source)
                    owner.verify()
                    result = dict(status="ready", root_id=metadata["root_id"], terminal=owner._observed,
                                  operation_id=None, outcome="already_ready")
                else:
                    path = pending[0]
                    if not list(path.iterdir()):
                        terminal, records, _payloads = owner._history.scan(prefix=expected_prefix)
                        if records[-1]["operation_id"] != path.name or (root / "sql" / "authority.db-journal").exists() or (root / "terminal.next").exists():
                            raise IntegrityError("empty pending directory lacks exact completed operation")
                        owner._observed = terminal
                        owner._open_engine(passphrase, curated_source=curated_source)
                        with owner._engine._snapshot():
                            owner._engine._verify_current()
                        io.rmdir(path)
                        io.sync_directory(path.parent)
                        result = dict(status="ready", root_id=metadata["root_id"], terminal=terminal,
                                      operation_id=path.name, outcome="cleanup_only")
                    else:
                        result = owner._recover_operation(path, passphrase, curated_source, expected_prefix)
                owner._recovering = False
                owner._check_ready()
                with owner._engine._snapshot():
                    owner._engine._verify_current()
            owner.close()
            return result
        except BaseException:
            if owner is not None:
                owner._dispose()
            else:
                lock.close()
            raise

    def _recover_operation(self, path, passphrase, curated_source, expected_prefix):
        outer, inner = self._recover_intent_head(path)
        issued = inner["issued"]
        self._pending = path, issued
        prior = issued["prior_terminal"]
        records = []
        if list((self.root / "history").iterdir()):
            terminal, records, _payloads = self._history.scan(prefix=expected_prefix, allow_terminal_lag=True)
            expected_sequence = 1 if prior is None else prior["sequence"] + 1
            if terminal != prior and terminal["sequence"] != expected_sequence:
                raise IntegrityError("pending operation publication frontier differs")
            if prior is not None and (prior["sequence"] > len(records) or history.terminal_of(records[prior["sequence"] - 1]) != prior):
                raise IntegrityError("pending prior prefix differs")
        elif issued["kind"] != "creation" or expected_prefix is not None:
            raise IntegrityError("pending operation lost accepted history")
        self._observed = prior
        self._bootstrapping = issued["kind"] == "creation" and not records
        if (self.root / "sql" / "authority.next").exists():
            raise RecoveryRequired("incomplete child metadata cannot be adopted")
        initial_genesis = issued["kind"] == "creation" and outer["stage"] == "initial"
        if issued["kind"] == "creation" and inner["prepared_name"] != "prepared-publication.json":
            if not initial_genesis or not (path / "prepared-publication.json").exists():
                raise RecoveryRequired("creation lacks prepared genesis; no ready adoption")
        self._open_engine(passphrase, curated_source=curated_source)
        sql_revision, sql_head = self._engine._check_terminal()
        actual_sql = {"revision": sql_revision, "head": sql_head}
        if (path / "prepared-abort.json").exists() and actual_sql != issued["prior_sql"]:
            raise IntegrityError("abort preparation conflicts with committed SQL extension")
        target_sequence = 1 if prior is None else prior["sequence"] + 1
        final = self.root / "history" / f"{target_sequence:020d}.json"
        prepared = None
        if initial_genesis:
            prepared = io.read(path / "prepared-publication.json")
            genesis = self._history.record(prepared, previous=None)
            genesis_payload = self._history.payload(genesis, previous=None)
            body = genesis_payload["body"]
            if (genesis["kind"] != "genesis" or genesis_payload["issued"] != issued
                    or actual_sql != {"revision": 0, "head": ZERO}
                    or body["metadata_sha256"] != history.digest(io.read(self.root / "application.json"))
                    or body["sql_metadata_sha256"] != history.digest(io.read(self.root / "sql" / "authority.json"))
                    or body["schema_contract"] != history.digest(schema.expected().encode())):
                raise IntegrityError("initial prepared genesis differs")
            with self._engine._snapshot():
                self._engine._verify_current()
            self._set_intent("prepared", ("prepared-publication.json", history.digest(prepared)))
            outer, inner = self._history.read_intent(io.read(path / "intent.json"))
        if inner["prepared_name"] is not None:
            draft = path / inner["prepared_name"]
            if draft.exists():
                prepared = io.read(draft)
            elif final.exists():
                prepared = io.read(final)
            else:
                raise IntegrityError("durable prepared intent lacks exact bytes")
            if history.digest(prepared) != inner["prepared_sha256"]:
                raise IntegrityError("recovery preparation digest differs")
        if final.exists():
            if prepared is None or io.read(final) != prepared:
                raise IntegrityError("accepted publication not bound by pending intent")
            record = self._history.record(prepared, previous=prior)
            if self._history.payload(record, previous=prior)["issued"] != issued:
                raise IntegrityError("accepted operation differs")
            expected_sql = {"revision": record["sql_revision"], "head": record["sql_head"]}
            if actual_sql != expected_sql:
                raise IntegrityError("published SQL state differs")
            self._extension = None
            self._observed = history.terminal_of(record)
            self._bootstrapping = False
            with self._engine._snapshot():
                self._engine._verify_current()
            self._publish()
            outcome = "cleanup_only"
        elif issued["kind"] == "capture":
            if actual_sql != issued["prior_sql"]:
                raise IntegrityError("capture changed SQL")
            self._recover_capture(outer, inner)
            final_record = self._history.record(io.read(self.root / "history" / f"{self._observed['sequence']:020d}.json"), previous=prior)
            outcome = "custody" if final_record["kind"] == "custody" else "aborted"
        elif prepared is not None:
            record = self._history.record(prepared, previous=prior)
            payload = self._history.payload(record, previous=prior)
            if payload["issued"] != issued:
                raise IntegrityError("prepared recovery issued context differs")
            intended_sql = {"revision": record["sql_revision"], "head": record["sql_head"]}
            if actual_sql == intended_sql and outer["stage"] != "initial":
                self._extension = prepared
                with self._engine._snapshot():
                    self._engine._verify_current()
                if record["kind"] == "genesis":
                    body = payload["body"]
                    if (body["metadata_sha256"] != history.digest(io.read(self.root / "application.json"))
                            or body["sql_metadata_sha256"] != history.digest(io.read(self.root / "sql" / "authority.json"))
                            or body["schema_contract"] != history.digest(schema.expected().encode())):
                        raise IntegrityError("prepared genesis metadata differs")
                self._publish()
                outcome = {"sql_commit": "committed", "noop": "noop", "interrupted_abort": "aborted", "genesis": "genesis"}[record["kind"]]
            elif actual_sql == issued["prior_sql"] and issued["kind"] != "creation":
                self._recover_abort(inner)
                outcome = "aborted"
            else:
                raise IntegrityError("SQL beyond or inconsistent with prepared extension")
        elif actual_sql == issued["prior_sql"] and issued["kind"] != "creation":
            self._recover_abort(inner)
            outcome = "aborted"
        else:
            raise IntegrityError("SQL outcome lacks durable intended extension")
        self._bootstrapping = False
        return dict(status="ready", root_id=self._metadata["root_id"], terminal=self._observed,
                    operation_id=issued["operation_id"], outcome=outcome)

    def _old_journal_context(self):
        """Authenticate the unique unpublished OLD transaction from durable bytes."""
        self._check_open()
        if (_owned_binding(self._binding, self._engine) is not self
                or self._recovering is not True
                or self._root_lock.owner != threading.get_ident()
                or not self._root_lock.depth or self._root_lock.pid != os.getpid()
                or self._engine.root != self.root / "sql"
                or self._engine._application_binding is not self._binding
                or self._extension is not None or self._pending is None
                or (self.root / "terminal.next").exists()):
            raise AuthorityError("native journal finalization requires owned explicit OLD recovery")
        self._root_lock._check()
        path, issued = self._pending
        if (path != self.root / "pending" / issued["operation_id"]
                or list((self.root / "pending").iterdir()) != [path]):
            raise IntegrityError("native journal pending ownership differs")
        io.directory(path)
        data = io.read(path / "intent.json")
        outer, inner = self._history.read_intent(data)
        if (inner["issued"] != issued or issued["kind"] != "transaction"
                or outer["operation_id"] != path.name
                or inner["superseded_name"] is not None
                or inner["superseded_sha256"] is not None):
            raise IntegrityError("native journal issued transaction differs")
        members = {member.name for member in path.iterdir()}
        preserved = {"intent.json": data}
        prior = issued["prior_terminal"]
        terminal, _records, _payloads = self._history.scan(prefix=prior)
        revision, head = self._engine._check_terminal()
        if (terminal != prior or self._observed != prior
                or {"revision": revision, "head": head} != issued["prior_sql"]):
            raise IntegrityError("native journal requires exact published and SQL OLD boundary")
        if outer["stage"] == "initial":
            if (members != {"intent.json"} or inner["prepared_name"] is not None
                    or inner["prepared_sha256"] is not None):
                raise IntegrityError("native journal initial preparation differs")
        elif outer["stage"] == "prepared":
            if (members != {"intent.json", "prepared-publication.json"}
                    or inner["prepared_name"] != "prepared-publication.json"
                    or type(inner["prepared_sha256"]) is not str):
                raise IntegrityError("native journal prepared membership differs")
            prepared = io.read(path / "prepared-publication.json")
            if history.digest(prepared) != inner["prepared_sha256"]:
                raise IntegrityError("native journal preparation digest differs")
            record = self._history.record(prepared, previous=prior)
            payload = self._history.payload(record, previous=prior)
            if (payload["issued"] != issued or record["root_id"] != self._metadata["root_id"]
                    or record["operation_id"] != issued["operation_id"]
                    or record["sequence"] != prior["sequence"] + 1
                    or record["previous_hash"] != prior["head"]
                    or record["kind"] != "sql_commit"
                    or record["sql_revision"] != issued["prior_sql"]["revision"] + 1):
                raise IntegrityError("native journal proposed SQL publication differs")
            proposed, commit = payload["body"]["record"], payload["body"]["commit"]
            if (proposed[1] != issued["prior_sql"]["head"]
                    or proposed[0] != record["sql_revision"] or proposed[3] != record["sql_head"]
                    or commit[:2] != [proposed[0], proposed[3]]):
                raise IntegrityError("native journal proposed SQL binding differs")
            preserved["prepared-publication.json"] = prepared
        else:
            raise RecoveryRequired("native journal recovery stage is not initial or prepared OLD")
        return preserved, terminal

    def _journal_user_version(self):
        rows = self._engine._db.execute("PRAGMA main.user_version").fetchall()
        if (type(rows) is not list or len(rows) != 1 or len(rows[0]) != 1
                or type(rows[0][0]) is not int or not -2147483648 <= rows[0][0] <= 2147483647):
            raise IntegrityError("native journal header integer is unsupported")
        return rows[0][0]

    def _finalize_old_journal(self):
        """Finalize native DELETE journaling without advancing logical SQL history."""
        journal = self.root / "sql" / "authority.db-journal"
        if not journal.exists():
            return
        preserved, terminal = self._old_journal_context()
        engine = self._engine
        with engine._lock:
            if engine._db.in_transaction or engine._verified_operation or engine._verifying:
                raise AuthorityError("native journal finalization requires an independent writer")
            settings = (("journal_mode", "delete"), ("synchronous", 2),
                        ("cipher_use_hmac", 1), ("locking_mode", "normal"))
            for name, expected in settings:
                rows = engine._db.execute("PRAGMA " + name).fetchall()
                if len(rows) != 1 or len(rows[0]) != 1 or str(rows[0][0]).lower() != str(expected):
                    raise AuthorityError("native journal durability profile is unsupported")
            owned_transaction = False
            try:
                engine._db.execute("BEGIN IMMEDIATE")
                owned_transaction = True
                engine._verify_current()
                exported = engine._export_current()
                control = engine._db.execute("SELECT singleton,revision,head,mac FROM control").fetchall()
                if (len(control) != 1 or control[0][0] != 1
                        or {"revision": exported["revision"], "head": exported["head"]} != self._pending[1]["prior_sql"]
                        or self._old_journal_context() != (preserved, terminal)):
                    raise IntegrityError("native journal writer preimage differs")
                captured = self._journal_user_version()
                engine._db.execute("PRAGMA main.user_version=" + str(captured))
                if self._journal_user_version() != captured:
                    raise IntegrityError("native journal header changed")
                engine._verify_current()
                if (engine._export_current() != exported
                        or engine._db.execute("SELECT singleton,revision,head,mac FROM control").fetchall() != control
                        or self._old_journal_context() != (preserved, terminal)
                        or self._journal_user_version() != captured):
                    raise IntegrityError("native journal writer state changed")
                engine._db.execute("COMMIT")
                owned_transaction = False
                if journal.exists():
                    raise RecoveryRequired("native journal remains after finalization")
                with engine._snapshot():
                    engine._verify_current()
                    if (engine._export_current() != exported
                            or engine._db.execute("SELECT singleton,revision,head,mac FROM control").fetchall() != control
                            or self._old_journal_context() != (preserved, terminal)
                            or self._journal_user_version() != captured):
                        raise IntegrityError("native journal committed state changed")
            except BaseException:
                if owned_transaction and engine._db.in_transaction:
                    engine._db.execute("ROLLBACK")
                raise

    def _recover_abort(self, inner):
        self._finalize_old_journal()
        path, issued = self._pending
        self._extension = None
        with self._engine._snapshot():
            self._engine._verify_current()
        abort = path / "prepared-abort.json"
        if abort.exists():
            data = io.read(abort)
            record = self._history.record(data, previous=issued["prior_terminal"])
            payload = self._history.payload(record, previous=issued["prior_terminal"])
            if record["kind"] != "interrupted_abort" or payload["issued"] != issued:
                raise IntegrityError("existing abort draft differs")
            original = path / "prepared-publication.json"
            superseded = None
            if original.exists():
                if payload["body"]["superseded_publication"] != io.read(original).decode("utf-8"):
                    raise IntegrityError("existing abort lost original proposed bytes")
                superseded = (original.name, history.digest(io.read(original)))
            elif payload["body"]["superseded_publication"] is not None:
                raise IntegrityError("existing abort original preparation missing")
            current_outer, current_inner = self._history.read_intent(io.read(path / "intent.json"))
            if current_outer["stage"] != "abort_prepared":
                self._set_intent("abort_prepared", (abort.name, history.digest(data)), superseded)
            elif current_inner["prepared_sha256"] != history.digest(data):
                raise IntegrityError("retained abort intent digest differs")
            self._extension = data
            self._publish()
        else:
            self._abort()

    def _recover_capture(self, outer, inner):
        path, issued = self._pending
        capture = issued["capture"]
        final = self.root / "sql" / "originals" / (capture["doc_id"] + ".blob")
        draft = path / "prepared-original.blob"
        if outer["stage"] == "abort_prepared":
            if final.exists() or draft.exists():
                raise RecoveryRequired("aborted capture retains conflicting original evidence")
            self._recover_abort(inner)
            return
        if final.exists():
            if history.digest(io.read(final)) != capture["blob_sha256"]:
                raise IntegrityError("interrupted final original differs")
        elif draft.exists():
            if history.digest(io.read(draft)) != capture["blob_sha256"]:
                raise RecoveryRequired("incomplete original preparation retained")
            io.no_replace(draft, final)
        else:
            self._recover_abort(inner)
            return
        plain = self._engine._original(capture["doc_id"])
        if len(plain) != capture["byte_count"]:
            raise IntegrityError("interrupted original plaintext differs")
        prepared = path / "prepared-publication.json"
        if prepared.exists():
            data = io.read(prepared)
            record = self._history.record(data, previous=issued["prior_terminal"])
            payload = self._history.payload(record, previous=issued["prior_terminal"])
            if record["kind"] != "custody" or payload["issued"] != issued:
                raise IntegrityError("interrupted custody preparation differs")
            if outer["stage"] != "prepared":
                self._set_intent("prepared", (prepared.name, history.digest(data)))
            self._extension = data
        else:
            self._prepare(issued, "custody", {name: capture[name] for name in ("doc_id", "byte_count", "blob_sha256")}, issued["prior_sql"])
        with self._engine._snapshot():
            self._engine._verify_current()
        self._publish()

    def close(self):
        if self._closed:
            return
        if self._depth or (self._engine is not None and self._engine._db.in_transaction):
            raise AuthorityError("cannot close an active application operation")
        with self._root_lock.hold():
            self._dispose(close_lock=False)
        self._root_lock.close()

    def _dispose(self, *, close_lock=True):
        if self._engine is not None:
            self._engine.close()
        self._closed = True
        _ISSUED.pop(id(self._binding), None)
        if close_lock and not self._root_lock.depth:
            self._root_lock.close()

    def __enter__(self):
        self._check_open()
        return self

    def __exit__(self, *_args):
        self.close()
