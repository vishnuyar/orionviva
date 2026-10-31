#!/usr/bin/env python3
"""Exercise the experimental SQL authority against fixed synthetic/public inputs.

This standalone engineering harness never opens an existing vault. Parity uses
the legacy implementation only in a separate oracle phase. Scale measures the
supported balance-statement slice, not the mixed product sample or packaging.
Source mode is the separately authorized complete 420-input experiment; it is
never a correctness warm-up and never runs automatically with another mode.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from contextlib import contextmanager
from datetime import date, timedelta
from dataclasses import asdict
from decimal import Decimal
import hashlib
import importlib
import inspect
import json
import math
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys
import time
import traceback


CONTRACT = "synthetic-balance-extraction-v1/en-US/USD"
KINDS = ("checking_statement", "savings_statement", "credit_card_statement")
SOURCE_DIRS = ("product/viva", "core/vivacore", "merchant/merchantcore")


class HarnessFailure(RuntimeError):
    """A required observation did not hold."""


def require(condition, label):
    if not condition:
        raise HarnessFailure(label)


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("ascii")


def digest(value):
    return hashlib.sha256(value).hexdigest()


def write_new(path, value):
    with path.open("xb") as stream:
        stream.write(encode(value) + b"\n")
        stream.flush()
        os.fsync(stream.fileno())


def source_identity(root):
    paths = [root / "scripts/validate_sql_authority.py"]
    for directory in SOURCE_DIRS:
        paths.extend(path for path in (root / directory).rglob("*")
                     if path.is_file() and path.suffix in {".py", ".json", ".txt", ".yaml", ".yml", ".csv"}
                     and "__pycache__" not in path.parts)
    files = {str(path.relative_to(root)): digest(path.read_bytes()) for path in sorted(paths)}
    return {"sha256": digest(encode(files)), "files": files}


def runtime_identity(dependencies, *, include_pdf=False):
    packages = {}
    names = ("sqlcipher3", "cryptography") + (("pypdfium2", "pypdfium2_raw", "pypdfium2_cfg") if include_pdf else ())
    for name in names:
        directory = dependencies / name
        require(directory.is_dir(), "required encrypted runtime dependency absent")
        packages[name] = {str(path.relative_to(directory)): digest(path.read_bytes())
                          for path in sorted(directory.rglob("*"))
                          if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"}
    for prefix in names:
        for directory in sorted(dependencies.glob(prefix+"-*.dist-info")):
            packages[directory.name] = {str(path.relative_to(directory)):digest(path.read_bytes())
                                       for path in sorted(directory.rglob("*")) if path.is_file()}
    for path in sorted(dependencies.glob("_cffi_backend*.so")):
        packages[path.name] = {"sha256":digest(path.read_bytes())}
    return {"python": sys.version, "executable_sha256": digest(Path(sys.executable).resolve().read_bytes()),
            "packages": packages, "sha256": digest(encode(packages))}


def fixture(kind, index, *, constant=False, namespace="parity"):
    """Two nonzero rows and one fixed-size dependency closure per statement."""
    family = KINDS.index(kind)
    start = date(2001, 1, 1) + timedelta(days=index * 2)
    opening = Decimal("100.00") if constant else Decimal("100.00") + Decimal(4 * index)
    amounts = (Decimal("7.00"), Decimal("-7.00") if constant else Decimal("-3.00"))
    payload = {"doc_type": kind, "doc_type_confidence": 1.0,
               "account_ref": "Synthetic " + kind.replace("_statement", ""),
               "account_number": str(830000000001 + family),
               "institution": "Synthetic Fixture Institution", "account_names": [],
               "opening": {"amount_raw": str(opening), "date_raw": start.isoformat(), "page": 1},
               "closing": {"amount_raw": str(opening + sum(amounts)),
                           "date_raw": (start + timedelta(days=1)).isoformat(), "page": 2},
               "transactions": []}
    for ordinal, amount in enumerate(amounts):
        payload["transactions"].append({
            "date_raw": (start + timedelta(days=ordinal)).isoformat(),
            "description": "Synthetic fixture movement " + str(ordinal),
            "amount_raw": str(abs(amount)),
            "balance_effect": "increase" if amount > 0 else "decrease", "page": ordinal + 1,
            "source_reference": f"fixture:{namespace}:{family}:{index}:{ordinal}",
            "counterparty_reference": ""})
    original = b"%PDF-1.4\n% synthetic offline fixture\n" + encode(
        {"namespace": namespace, "family": family, "period": index, "extraction": payload}) + b"\n%%EOF\n"
    return {"id": f"{namespace}:{kind}:{index}", "original": original, "payload": payload}


def fixture_identity(cases):
    return {"count": len(cases), "sha256": digest(encode([
        {"id": case["id"], "original_sha256": digest(case["original"]),
         "payload_sha256": digest(encode(case["payload"]))} for case in cases]))}


def reader_for(case, calls):
    from viva.ingest.pipeline_models import ReadResult
    from viva.ingest.statement import from_model_json
    raw = encode(case["payload"]).decode("ascii")

    def read(original, doc_id):
        require(original == case["original"] and digest(original) == doc_id, "reader original binding")
        calls.append(doc_id)
        facts, error = from_model_json(raw, doc_id, "en-US", "USD")
        require(error is None and facts is not None, "fixed extraction parses")
        return ReadResult(case["payload"]["doc_type"], 1.0, facts,
                          raw_text=raw, model="synthetic-offline-reader",
                          resolved_model="synthetic-offline-reader", prompt_version="synthetic-balance-v1",
                          source_locale="en-US", input_mode="text")
    return read


def block_network():
    def refuse(*_args, **_kwargs):
        raise HarnessFailure("network connection forbidden")
    socket.socket.connect = refuse
    socket.socket.connect_ex = refuse
    socket.create_connection = refuse
    socket.getaddrinfo = refuse


def restrict_files(root, output, dependencies):
    """Permit candidate/dependency reads and disposable-output writes only."""
    readable = (root, output, dependencies, Path(sys.base_prefix).resolve(),
                Path("/usr"), Path("/System"), Path("/Library/Apple"))

    def beneath(path, parent):
        return path == parent or parent in path.parents

    def audit(event, arguments):
        if event != "open":
            return
        path = arguments[0]
        if isinstance(path, int):
            return
        if not isinstance(path, (str, bytes, os.PathLike)):
            return
        path = Path(os.fsdecode(path)).absolute().resolve()
        mode, flags = arguments[1:3]
        writing = (isinstance(mode, str) and any(char in mode for char in "wax+")) or (
            isinstance(flags, int) and bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC)))
        if writing:
            require(beneath(path, output), "write outside disposable output forbidden")
        else:
            require(path == Path("/dev/urandom") or any(beneath(path, base) for base in readable),
                    "read outside candidate and dependencies forbidden")
            if path.name == ".env":
                require(path == output / "isolation/cwd/.env", "private dotenv access forbidden")
    sys.addaudithook(audit)


def isolation_controls(root):
    controls = (
        lambda: socket.create_connection(("127.0.0.1", 1)),
        lambda: (root / ".env").read_bytes(),
        lambda: (root / "__forbidden_harness_write__").write_bytes(b""),
    )
    for control in controls:
        try:
            control()
        except HarnessFailure:
            continue
        raise HarnessFailure("isolation negative control escaped")
    return len(controls)


@contextmanager
def legacy_traps():
    """Patch actual entry points and all already-imported function aliases."""
    from viva.ledger import EventStore, Ledger, LedgerProjection
    from viva.ledger.projection.core import ProjectionCore
    modules = {
        "viva.ingest.pipeline": ("capture_and_ingest", "_capture_and_ingest", "_settle_read", "sweep"),
        "viva.ingest.statement_projector": ("post_statement", "heal_gaps", "heal_corroboration"),
        "viva.ingest.paystub_projector": ("heal_paystubs",),
        "viva.ingest.instrument_projector": ("heal_instruments",),
        "viva.investment.healing": ("heal_after_source", "heal_root", "heal_copy_root"),
        "viva.ingest.transfers": ("link_transfers",),
    }
    targets = []
    for name, attributes in modules.items():
        module = importlib.import_module(name)
        for attribute in attributes:
            targets.append((f"{name}.{attribute}", getattr(module, attribute), module, attribute))
    changes = []
    controls = []

    def trap(label):
        def refuse(*_args, **_kwargs):
            raise HarnessFailure("forbidden legacy execution: " + label)
        return refuse

    for cls, arguments in ((EventStore, (None, None, None)), (Ledger, (None,)),
                           (LedgerProjection, ((),)), (ProjectionCore, ((),))):
        previous = cls.__init__
        inspect.signature(previous).bind(None, *arguments)
        changes.append((cls, "__init__", previous))
        setattr(cls, "__init__", trap(cls.__name__))
        controls.append((cls.__name__, lambda cls=cls, arguments=arguments: cls(*arguments)))
    for label, original, target_module, target_attribute in targets:
        replacement = trap(label)
        for module in tuple(sys.modules.values()):
            namespace = getattr(module, "__dict__", None)
            if namespace is None:
                continue
            for name, value in tuple(namespace.items()):
                if value is original:
                    changes.append((module, name, value))
                    setattr(module, name, replacement)
        positional, keywords = [], {}
        for parameter in inspect.signature(original).parameters.values():
            if parameter.default is not inspect.Parameter.empty:
                continue
            if parameter.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD):
                positional.append(None)
            elif parameter.kind is inspect.Parameter.KEYWORD_ONLY:
                keywords[parameter.name] = None
        inspect.signature(original).bind(*positional, **keywords)
        controls.append((label, lambda module=target_module, name=target_attribute,
                        positional=positional, keywords=keywords: getattr(module, name)(*positional, **keywords)))
    try:
        proved = []
        for label, call in controls:
            try:
                call()
            except HarnessFailure as exc:
                require(str(exc).startswith("forbidden legacy execution:"), "legacy trap instrumentation")
                proved.append(label)
            else:
                raise HarnessFailure("legacy negative control escaped")
        yield proved
    finally:
        for owner, name, original in reversed(changes):
            setattr(owner, name, original)


class SQLGuard:
    """Deny history reconstruction while allowing exact terminal authentication."""
    def __init__(self, connection):
        from viva.sql_authority.schema import TABLES, KEYS
        self.connection = connection
        self.statements = 0
        self.reads = {
            self.normalize("SELECT " + ",".join(columns) + " FROM " + table + " WHERE " +
                           " AND ".join(key + "=?" for key in KEYS[table]))
            for table, columns in TABLES.items()}
        self.reads.update(self.normalize(statement) for statement in (
            "SELECT revision,head,mac FROM control WHERE singleton=1",
            "SELECT head,mac FROM commits WHERE revision=?",
            "SELECT record_hash FROM audit WHERE sequence=?",
            "SELECT account_id,identity FROM accounts WHERE kind=? AND normalized_number=?",
            "SELECT " + ",".join(TABLES["accounts"]) + " FROM accounts WHERE identity=?",
            "SELECT " + ",".join(TABLES["account_keys"]) + " FROM account_keys WHERE logical_key=?",
            "SELECT txn_id,doc_id,line_index,account_id,date,description,page,amount,source_reference,counterparty_reference FROM transactions WHERE account_id=? ORDER BY date,doc_id,line_index",
            "SELECT p.txn_id,p.leg,p.account_id,p.amount,p.grade,p.currency,p.doc_id,p.page,t.line_index FROM postings p JOIN transactions t ON t.txn_id=p.txn_id WHERE p.doc_id=? ORDER BY t.line_index,p.leg",
            "SELECT observation_id,doc_id,account_id,kind,date,amount,page,currency,grade,event_asserted FROM balance_observations WHERE account_id=? ORDER BY date,kind,doc_id",
            "SELECT d.doc_id FROM dependencies d JOIN items i ON i.doc_id=d.doc_id WHERE d.identity=? AND d.boundary_amount=? AND d.direction=? AND d.active=1 AND i.state='pending' ORDER BY d.doc_id",
            "SELECT txn_id,doc_id,line_index,account_id,date,description,page,amount,source_reference,counterparty_reference FROM transactions WHERE doc_id=? ORDER BY line_index",
            "SELECT doc_id,line_index,event_id,date,page,raw FROM source_occurrences WHERE doc_id=? ORDER BY line_index",
            "SELECT observation_id,doc_id,account_id,kind,date,amount,page,currency,grade,event_asserted FROM balance_observations WHERE doc_id=? ORDER BY kind",
            "SELECT body FROM identity_decisions WHERE doc_id=? ORDER BY created_revision DESC,decision_id DESC LIMIT 1",
            "SELECT v.account_id FROM reference_views v JOIN accounts a ON a.account_id=v.account_id WHERE v.reference=? AND v.positive_claim_id<>'' AND a.kind=?",
            "SELECT h.account_id FROM holder_index h JOIN accounts a ON a.account_id=h.account_id WHERE h.normalized_name=? AND a.kind=?",
            "SELECT account_id,reference,positive_claim_id,history_claim_id FROM reference_views WHERE account_id=?",
        ))
        # These are complete indexed dependency shapes, never full exports.
        transfer_shapes = [
            "SELECT e.movement FROM transfer_tokens t JOIN transfer_endpoints e ON e.account=t.account WHERE t.token=? AND e.active=1 ORDER BY e.movement",
            "SELECT movement FROM transfer_dirty WHERE active=1 ORDER BY movement",
            "SELECT x.b FROM transfer_edges x JOIN transfer_endpoints e ON e.movement=x.b WHERE x.a=? AND e.active=1 UNION SELECT x.a FROM transfer_edges x JOIN transfer_endpoints e ON e.movement=x.a WHERE x.b=? AND e.active=1",
            "SELECT b FROM transfer_edges WHERE a=?",
            "SELECT b FROM transfer_edges WHERE a=? UNION SELECT a FROM transfer_edges WHERE b=?",
            "SELECT DISTINCT inventory.account,inventory.kind,inventory.currency,inventory.institution,inventory.number,inventory.name,inventory.source_doc,inventory.source_order FROM transfer_tokens endpoint JOIN transfer_tokens owners ON owners.token=endpoint.token JOIN transfer_inventory inventory ON inventory.account=owners.account WHERE endpoint.account=? ORDER BY inventory.account",
        ]
        for table, field in (("transfer_inventory","source_order"),("transfer_bindings","source_order"),("transfer_assertions","ordinal")):
            transfer_shapes.append("SELECT COALESCE(MAX("+field+"),0)+1 FROM "+table+" WHERE 1")
        transfer_shapes.append("SELECT "+",".join(TABLES["transfer_endpoints"])+" FROM transfer_endpoints WHERE currency=? AND magnitude=? AND flow=? AND date>=? AND date<=?")
        self.reads.update(self.normalize(statement) for statement in transfer_shapes)
        self.plans = {self.normalize(statement) for statement in (
            "EXPLAIN QUERY PLAN SELECT * FROM accounts WHERE identity=?",
            "EXPLAIN QUERY PLAN SELECT * FROM periods WHERE account_id=? AND period_end=?",
            "EXPLAIN QUERY PLAN SELECT doc_id FROM dependencies WHERE identity=? AND boundary_amount=? AND direction=? AND active=1",
            "EXPLAIN QUERY PLAN SELECT account_id FROM reference_views WHERE reference=?",
            "EXPLAIN QUERY PLAN SELECT account_id FROM holder_index WHERE normalized_name=?",
            "EXPLAIN QUERY PLAN SELECT account_id FROM account_keys WHERE logical_key=?",
        )}

    @staticmethod
    def normalize(statement):
        return " ".join(statement.lower().replace('"', '').split())

    def __getattr__(self, name):
        require(name not in {"cursor", "executescript", "executemany"}, "unguarded SQL execution forbidden")
        return getattr(self.connection, name)

    def execute(self, statement, parameters=()):
        lowered = self.normalize(statement)
        if lowered.startswith(("select", "with")):
            require(lowered in self.reads, "SQL read outside fixed indexed shapes forbidden")
        elif lowered.startswith("explain"):
            require(lowered in self.plans, "SQL plan outside fixed indexed shapes forbidden")
        self.statements += 1
        return self.connection.execute(statement, parameters)


@contextmanager
def normal_history_traps(store):
    from viva.sql_authority import SQLAuthority
    from viva.sql_authority import identity, transfer_verify
    targets = [(transfer_verify,"verify"), (SQLAuthority, "verify"), (SQLAuthority, "export_audit"),
               (SQLAuthority, "_reconstruct"), (identity, "verify_semantics")]
    saved = []
    def refuse(*_args, **_kwargs):
        raise HarnessFailure("explicit history reconstruction on normal path forbidden")
    for owner, name in targets:
        saved.append((owner, name, getattr(owner, name)))
        setattr(owner, name, refuse)
    try:
        for call in (lambda: store.verify(), lambda: store.export_audit(),
                     lambda: store._reconstruct({}, None), lambda: identity.verify_semantics(store, {}),
                     lambda: transfer_verify.verify(store, {}, {})):
            try:
                call()
            except HarnessFailure as exc:
                require(str(exc) == "explicit history reconstruction on normal path forbidden", "history trap instrumentation")
            else:
                raise HarnessFailure("normal-path history negative control escaped")
        yield
    finally:
        for owner, name, original in reversed(saved):
            setattr(owner, name, original)


@contextmanager
def guarded_sql(store):
    connection = store._db
    guard = SQLGuard(connection)
    store._db = guard
    try:
        for statement, parameters in (
                ("SELECT * FROM audit", ()), ("SELECT * FROM transactions", ()),
                ("SELECT * FROM audit WHERE sequence>0", ()),
                ("SELECT * FROM transactions WHERE 1=1", ()),
                ("WITH history AS (SELECT * FROM transactions) SELECT * FROM history", ()),
                ("SELECT txn_id FROM transactions WHERE account_id=? OR 1=1", ("synthetic",))):
            try:
                store._db.execute(statement, parameters).fetchall()
            except HarnessFailure:
                pass
            else:
                raise HarnessFailure("unbounded SQL negative control escaped")
        with normal_history_traps(store):
            yield guard
    finally:
        store._db = connection


def money(value):
    return str(Decimal(str(value)).normalize())


def sorted_records(records):
    return sorted(records, key=encode)


def normalized_provenance(value):
    require(set(value) == {"doc_id", "page", "region", "note"}, "closed provenance fields")
    return value


def oracle_snapshot(ledger, cases):
    from viva.ingest.registry import account_kind_for
    from viva.ledger.postings import counter_account
    projection = ledger.projection()
    events = list(ledger.store.events())
    metadata = {}
    account_map = {}
    balances = {}
    transactions = []
    postings = []
    observations = []
    expected_identities = {
        (account_kind_for(case["payload"]["doc_type"]), "USD",
         case["payload"]["account_number"], case["payload"]["institution"])
        for case in cases}
    expected_counters = {
        counter_account(account_kind_for(case["payload"]["doc_type"]),
                        Decimal(line["amount_raw"]) * (1 if line["balance_effect"] == "increase" else -1))
        for case in cases for line in case["payload"]["transactions"]}
    for account in projection.accounts():
        info = projection.account_info(account)
        if info.kind not in {"depository", "liability"}:
            require(info.kind == "" and account in expected_counters,
                    "oracle unexpected non-statement account")
            continue
        key = (info.kind, info.currency, info.number, info.institution)
        require(key in expected_identities, "oracle statement account source identity")
        require(key not in metadata, "oracle unique metadata mapping")
        account_map[account] = key
        metadata[key] = {"kind": info.kind, "currency": info.currency, "number": info.number,
                         "institution": info.institution, "label": info.name, "names": info.names}
        answer = projection.balance(account)
        balances[key] = {"running": money(projection.running_balance(account)),
                         "earliest": money(projection.earliest_opening(account)),
                         "amount": money(answer.amount), "grade": answer.grade,
                         "date": answer.dated, "currency": answer.currency,
                         "provenance": normalized_provenance(answer.provenance.to_dict())}
    require(set(metadata) == expected_identities and len(account_map) == len(expected_identities),
            "oracle all fixture statement accounts represented")
    # Counter accounts have no printed opening. Their movements remain part
    # of the parity surface even though balances above concern real accounts.
    for account in projection.accounts():
        for line in projection.transactions(account):
            record = line.to_dict()
            require(set(record) == {"date", "description", "amount", "grade", "currency", "provenance"},
                    "closed legacy transaction fields")
            record["amount"] = money(record["amount"])
            record["account"] = account_map.get(account, account)
            transactions.append(record)
    ordinal_by_doc = {}
    references = {}
    for event in events:
        if event.event_type == "TransactionRecorded":
            doc_id = event.provenance.doc_id
            ordinal = ordinal_by_doc.get(doc_id, 0)
            ordinal_by_doc[doc_id] = ordinal + 1
            references[(doc_id, ordinal)] = {
                "source_reference": event.body.get("source_reference", ""),
                "counterparty_reference": event.body.get("counterparty_reference", "")}
            for leg, posting in enumerate(event.body["postings"]):
                postings.append({"doc_id": doc_id, "ordinal": ordinal, "leg": leg,
                                 "account": account_map.get(posting["account"], posting["account"]),
                                 "amount": money(posting["amount"]), "grade": posting["grade"],
                                 "provenance": normalized_provenance(event.provenance.to_dict())})
        elif event.event_type == "ClosingBalanceObserved":
            observations.append({"doc_id": event.provenance.doc_id,
                                 "account": account_map[event.body["account_id"]],
                                 "kind": "closing",
                                 "date": event.occurred_at, "amount": money(event.body["amount"]),
                                 "provenance": normalized_provenance(event.provenance.to_dict())})
        elif event.event_type == "ReadRecorded" and event.body.get("phase") == "extract":
            # Legacy retains every printed opening in its immutable extraction
            # receipt; only seed/backfill openings also become ledger events.
            from viva.ingest.statement import from_model_json
            facts, error = from_model_json(event.body["response_text"], event.provenance.doc_id, "en-US", "USD")
            require(error is None, "legacy receipt parse")
            account = next(key for key in metadata if key[2] == facts.account_number)
            observations.append({"doc_id": facts.doc_id, "account": account, "kind": "opening",
                                 "date": facts.opening_date, "amount": money(facts.opening_amount),
                                 "provenance": normalized_provenance(facts.opening_provenance().to_dict())})
    return metadata, balances, sorted_records(transactions), sorted_records(postings), references, sorted_records(observations)


def sql_snapshot(store, outcomes):
    metadata = {}
    balances = {}
    account_map = {}
    for account_id in set(outcome.account_id for outcome in outcomes):
        row = store.account(account_id)
        key = (row["kind"], row["currency"], row["number"], row["institution"])
        require(key not in metadata, "SQL unique metadata mapping")
        account_map[account_id] = key
        metadata[key] = {name: row[name] for name in ("kind", "currency", "number", "institution", "label")}
        metadata[key]["names"] = json.loads(row["names"])
        observations = store.balance_observations(account_id)
        latest = max((row for row in observations if row["kind"] == "closing"), key=lambda row: row["date"])
        balances[key] = {"running": money(row["running_balance"]), "earliest": money(row["earliest_opening"]),
                         "amount": money(latest["amount"]), "grade": latest["grade"], "date": latest["date"], "currency": latest["currency"],
                         "provenance": normalized_provenance(latest["provenance"])}
    transactions = []
    postings = []
    references = {}
    observations = []
    transaction_metadata = {}
    for account_id, key in account_map.items():
        for row in store.transactions(account_id):
            transaction_metadata[row["txn_id"]] = row
            transactions.append({"account": key, "date": row["date"], "description": row["description"],
                                 "amount": money(row["amount"]), "grade": row["grade"], "currency": metadata[key]["currency"],
                                 "provenance": normalized_provenance(row["provenance"])})
            references[(row["doc_id"], row["ordinal"])] = {
                name: row[name] for name in ("source_reference", "counterparty_reference")}
        for row in store.balance_observations(account_id):
            observations.append({"doc_id": row["doc_id"], "account": key, "kind": row["kind"], "date": row["date"], "amount": money(row["amount"]),
                                 "provenance": normalized_provenance(row["provenance"])})
    for outcome in outcomes:
        rows = store.postings(outcome.doc_id)
        for row in rows:
            require(row["currency"] == metadata[account_map[outcome.account_id]]["currency"], "posting currency")
            postings.append({"doc_id": row["doc_id"], "ordinal": row["ordinal"], "leg": row["leg"],
                             "account": account_map.get(row["account"], row["account"]),
                             "amount": money(row["amount"]), "grade": row["grade"],
                             "provenance": normalized_provenance(row["provenance"])})
            if row["account"] not in account_map:
                transaction = transaction_metadata[row["txn_id"]]
                transactions.append({"account": row["account"], "date": transaction["date"],
                                     "description": transaction["description"], "amount": money(row["amount"]),
                                     "grade": row["grade"], "currency": row["currency"],
                                     "provenance": normalized_provenance(row["provenance"])})
        for ordinal in set(row["ordinal"] for row in rows):
            require(sum(Decimal(row["amount"]) for row in rows if row["ordinal"] == ordinal) == 0,
                    "exact double entry")
    return metadata, balances, sorted_records(transactions), sorted_records(postings), references, sorted_records(observations)


def compare_snapshots(expected, actual):
    for label, old, new in zip(("account metadata", "balances", "transactions", "postings", "source references", "balance observations"), expected, actual):
        require(old == new, "legacy parity: " + label)


def counter_comparison_controls(expected):
    proved = []
    for field, replacement in (("account", "Synthetic:ChangedCounter"), ("grade", "verified"), ("amount", "999")):
        changed = deepcopy(expected)
        posting = next(row for row in changed[3] if type(row["account"]) is str)
        require(posting[field] != replacement, "counter mutation must change semantic field")
        posting[field] = replacement
        try:
            compare_snapshots(expected, changed)
        except HarnessFailure as exc:
            require(str(exc) == "legacy parity: postings", "counter comparison failure classification")
            proved.append(field)
        else:
            raise HarnessFailure("counter posting mutation escaped parity")
    return proved


def compare_source_document(expected, actual):
    """Compare ordered raw assertions without financial projection overlays."""
    fields = {"transactions", "asserted_observations", "printed_openings"}
    require(type(expected) is dict and type(actual) is dict and set(expected) == set(actual) == fields,
            "closed raw source comparison")
    for field in sorted(fields):
        require(expected[field] == actual[field], "raw source parity: " + field)


def source_comparison_controls(expected):
    """A repeated occurrence remains independently identifiable and checked."""
    require(bool(expected["transactions"]), "source comparison control needs a genuine transaction")
    changes = (
        ("counterpart amount", lambda value: value["transactions"][0]["postings"][1].update(amount="999")),
        ("counterpart grade", lambda value: value["transactions"][0]["postings"][1].update(grade="changed-grade")),
        ("counterpart account", lambda value: value["transactions"][0]["postings"][1].update(account="changed-counterpart")),
        ("date", lambda value: value["transactions"][0].update(date="1900-01-01")),
        ("provenance", lambda value: value["transactions"][0]["provenance"].update(page=199)),
        ("occurrence pairing", lambda value: value["transactions"][0]["occurrence"].update(event_id="E999999")),
        ("occurrence multiplicity", lambda value: value["transactions"].append(deepcopy(value["transactions"][0]))),
    )
    proved = []
    for label, alter in changes:
        changed = deepcopy(expected)
        alter(changed)
        require(changed != expected, "source mutation must alter an assertion")
        try:
            compare_source_document(expected, changed)
        except HarnessFailure as exc:
            require(str(exc) == "raw source parity: transactions", "source mutation failure classification")
            proved.append(label)
        else:
            raise HarnessFailure("raw source mutation escaped comparison")
    return proved


def final_source_disposition(*, admission_error=False, state, matched):
    """Return exactly one terminal accounting label for every source input."""
    if admission_error:
        return "admission error"
    if state == "unsupported":
        return "declared unsupported"
    if state != "accepted":
        return "pending"
    return "promoted-and-matched" if matched else "mismatched"


def source_occurrences(envelope):
    """Retain exact ordinal-to-occurrence/source-cell binding, including repeats."""
    identifiers = envelope["source_event_ids"]
    records = []
    for ordinal, identifier in enumerate(identifiers):
        cells = [cell for cell in envelope["source_cells"]
                 if cell["association"].get("kind") == "event"
                 and cell["association"].get("row_reference") == identifier]
        require(bool(cells), "source occurrence has an actual directional cell")
        witnesses = {(cell["association"]["date"], cell["page"], cell["raw"]) for cell in cells}
        require(len(witnesses) == 1, "source occurrence exact cell agreement")
        dated, page, raw = next(iter(witnesses))
        records.append({"line_index": ordinal, "event_id": identifier, "date": dated, "page": page, "raw": raw})
    require(len({row["event_id"] for row in records}) == len(records), "source occurrence identities unique")
    return records


def legacy_source_assertions(events, doc_id, envelope, account_mapping):
    """Actual log assertions and receipt evidence occupy separate fields."""
    from viva.sample.curation import canonical as source_canonical
    from viva.ingest.statement import from_model_json
    occurrences = source_occurrences(envelope)
    source_events = [event for event in events if event.provenance.doc_id == doc_id]
    transactions = []
    observations = []
    printed = []
    for event in source_events:
        if event.event_type == "TransactionRecorded":
            ordinal = len(transactions)
            require(ordinal < len(occurrences), "legacy transaction has a source occurrence")
            require(event.body.get("tags", []) == [], "nonempty legacy transaction tags outside source slice")
            postings = [{"account": account_mapping.get(row["account"], row["account"]),
                         "amount": money(row["amount"]), "grade": row["grade"]}
                        for row in event.body["postings"]]
            transactions.append({"ordinal": ordinal, "occurrence": occurrences[ordinal],
                                 "date": event.occurred_at, "description": event.body["description"],
                                 "source_reference": event.body.get("source_reference", ""),
                                 "counterparty_reference": event.body.get("counterparty_reference", ""),
                                 "provenance": normalized_provenance(event.provenance.to_dict()),
                                 "postings": postings})
        elif event.event_type in {"OpeningBalanceObserved", "ClosingBalanceObserved"}:
            require(event.body.get("confirmed_by", "") == "", "human closing ruling outside source slice")
            observations.append({"kind": "opening" if event.event_type == "OpeningBalanceObserved" else "closing",
                                 "account": account_mapping[event.body["account_id"]], "date": event.occurred_at,
                                 "amount": money(event.body["amount"]),
                                 "provenance": normalized_provenance(event.provenance.to_dict())})
        elif event.event_type == "ReadRecorded" and event.body.get("phase") == "extract":
            require(event.body["response_text"] == source_canonical(envelope).decode(), "legacy complete source envelope retained")
            facts, error = from_model_json(source_canonical(envelope["parser_input"]).decode(), doc_id,
                                          event.body["normalization_locale"], event.body["source_currency"])
            require(error is None and facts is not None, "legacy source receipt normalizes")
            printed.append({"date": facts.opening_date, "amount": money(facts.opening_amount),
                            "provenance": normalized_provenance(facts.opening_provenance().to_dict())})
    return {"transactions": transactions, "asserted_observations": sorted_records(observations),
            "printed_openings": printed}


def sql_source_assertions(store, doc_id, account_mapping):
    rows = store.source_transactions(doc_id)
    occurrence_rows = store.source_occurrences(doc_id)
    for occurrence in occurrence_rows:
        require(occurrence["doc_id"] == doc_id and occurrence["line_index"] == occurrence["ordinal"],
                "SQL source occurrence document and ordinal binding")
    occurrences = [{"line_index": row["ordinal"], **{name: row[name] for name in ("event_id", "date", "page", "raw")}}
                   for row in occurrence_rows]
    require([row["line_index"] for row in occurrences] == list(range(len(occurrences))),
            "SQL occurrence ordinal coverage")
    postings = store.postings(doc_id)
    transactions = []
    for row in rows:
        ordinal = row["ordinal"]
        require(ordinal == len(transactions) and ordinal < len(occurrences), "SQL transaction occurrence order")
        legs = [leg for leg in postings if leg["ordinal"] == ordinal]
        require([leg["leg"] for leg in legs] == [0, 1], "SQL exact ordered double-entry legs")
        require(sum(Decimal(leg["amount"]) for leg in legs) == 0, "SQL source exact double entry")
        require(row["tags"] == [] and row["grade"] == legs[0]["grade"], "SQL raw transaction fields agree with accepted postings")
        transactions.append({"ordinal": ordinal, "occurrence": occurrences[ordinal], "date": row["date"],
                             "description": row["description"], "source_reference": row["source_reference"],
                             "counterparty_reference": row["counterparty_reference"],
                             "provenance": normalized_provenance(row["provenance"]),
                             "postings": [{"account": account_mapping.get(leg["account"], leg["account"]),
                                           "amount": money(leg["amount"]), "grade": leg["grade"]} for leg in legs]})
    require(len(postings) == 2 * len(transactions), "SQL source postings multiplicity")
    observations, observed_openings, observed_closings = [], [], []
    item = store.item(doc_id)
    for row in store.source_observations(doc_id):
        require(row["doc_id"] == doc_id, "document-indexed source observation binding")
        value = {"kind": row["kind"], "account": account_mapping[row["account_id"]],
                 "date": row["date"], "amount": money(row["amount"]),
                 "provenance": normalized_provenance(row["provenance"])}
        require(type(row["event_asserted"]) is bool, "source event assertion flag is explicit")
        if row["event_asserted"]:
            observations.append(value)
        (observed_openings if row["kind"] == "opening" else observed_closings).append(
            {name: value[name] for name in ("date", "amount", "provenance")})
    # Printed observations come independently from immutable interpreted
    # receipt facts, never from an invented legacy opening assertion.
    receipt = store.receipt(doc_id)
    printed = []
    if receipt["facts_type"] == "balance":
        from viva.ingest.statement import StatementFacts
        facts = StatementFacts.from_dict(receipt["facts"])
        printed.append({"date": facts.opening_date, "amount": money(facts.opening_amount),
                        "provenance": normalized_provenance(facts.opening_provenance().to_dict())})
        if item["state"] == "accepted":
            closing = {"date": facts.closing_date, "amount": money(facts.closing_amount),
                       "provenance": normalized_provenance(facts.closing_provenance().to_dict())}
            require(observed_openings == printed and observed_closings == [closing],
                    "accepted SQL observations bind immutable receipt")
            require(len(transactions) == len(occurrences), "accepted SQL complete source occurrence multiplicity")
    return {"transactions": transactions, "asserted_observations": sorted_records(observations),
            "printed_openings": printed}


@contextmanager
def trace_legacy_resolution(records):
    """Observe the unchanged resolver while the separate oracle ingests."""
    from viva.ledger.projection import accounts
    original = accounts.resolve
    def observe(core, *arguments, **keywords):
        result = original(core, *arguments, **keywords)
        source = keywords.get("source_identity")
        if source is not None and source.eligible():
            records.setdefault(source.doc_id, {
                "resolution": asdict(result),
                "account_order": [key for key, state in core._acct.items()
                                  if state.seen and state.kind in {"depository", "liability"}]})
        return result
    accounts.resolve = observe
    try:
        yield
    finally:
        accounts.resolve = original


def source_account_metadata(value, *, legacy):
    """Account identifiers carry no number, holder or institution evidence."""
    if legacy:
        return {"kind": value["kind"], "currency": value["currency"], "label": value["name"],
                "institution": value["institution"], "number": value["account_number"],
                "names": value["account_names"]}
    return {name: value[name] for name in ("kind", "currency", "label", "institution", "number")} | {
        "names": json.loads(value["names"])}


def map_source_accounts(events, store, document_ids):
    opened = [event for event in events if event.event_type == "AccountOpened"]
    legacy_mapping = {event.body["account_id"]: f"account-{index + 1}" for index, event in enumerate(opened)}
    sql_mapping, logical_mapping, sql_accounts = {}, {}, {}
    for doc_id in document_ids:
        item = store.item(doc_id)
        if item["state"] != "accepted" or item["account_id"] in sql_accounts:
            continue
        sql_accounts[item["account_id"]] = store.account(item["account_id"])
    require(len(sql_accounts) == len(opened), "all SQL and legacy source accounts represented")
    orders = [account["creation_order"] for account in sql_accounts.values()]
    require(all(type(order) is int and order > 0 for order in orders) and len(set(orders)) == len(orders),
            "SQL account creation-order keys are distinct and positive")
    for index, (account_id, account) in enumerate(sorted(sql_accounts.items(), key=lambda entry: entry[1]["creation_order"])):
        # The persisted key may be a revision rather than a contiguous ordinal.
        # Its order, not its arithmetic distance, binds actual opening events.
        legacy_event = opened[index]
        require(source_account_metadata(account, legacy=False) == source_account_metadata(legacy_event.body, legacy=True),
                "explicit SQL-to-legacy account metadata mapping")
        alias = legacy_mapping[legacy_event.body["account_id"]]
        require(alias not in sql_mapping.values(), "source account mapping is one to one")
        sql_mapping[account_id] = alias
        logical_mapping[account["logical_key"]] = alias
    require(len(logical_mapping) == len(sql_accounts), "logical source account mapping is one to one")
    return legacy_mapping, sql_mapping, logical_mapping


def mapped_resolution(value, mapping):
    required = {"account_id", "key", "verdict", "candidate", "candidate_name", "candidates", "reason"}
    require(type(value) is dict and set(value) == required, "closed existing Resolution fields")
    result = deepcopy(value)
    for field in ("account_id", "candidate"):
        result[field] = mapping.get(result[field], result[field])
    result["candidates"] = [mapping.get(candidate, candidate) for candidate in result["candidates"]]
    return result


def compare_source_resolution(expected, actual, legacy_mapping, logical_mapping, physical_mapping):
    require(mapped_resolution(expected["resolution"], legacy_mapping) ==
            mapped_resolution(actual["resolution"], logical_mapping), "exact source resolver outcome")
    expected_order = [legacy_mapping.get(key, key) for key in expected["account_order"]]
    actual_order = [logical_mapping.get(key, key) for key in actual["account_order"]]
    require(actual_order == [key for key in expected_order if key in actual_order],
            "source resolver preserves candidate creation order")
    mapping = actual["logical_to_physical"]
    require(type(mapping) is dict and set(mapping) == set(actual["account_order"]),
            "complete explicit resolver logical-to-physical closure mapping")
    require(all(logical in logical_mapping and physical in physical_mapping and
                logical_mapping[logical] == physical_mapping[physical] for logical, physical in mapping.items()),
            "resolver logical-to-physical account identity binding")


def public_pack_identity(root):
    files = {path.name: digest(path.read_bytes()) for path in sorted(root.iterdir()) if path.is_file()}
    require(len(files) == 797, "complete pinned public input closure")
    return {"sha256": digest(encode(files)), "files": files}


def frozen_public_selection(root):
    """Select pinned metadata without PDF parsing or issuing source authority."""
    from viva.sample import resources, curation
    from viva.ingest.registry import BALANCE_IDENTITY, profile_for
    manifest_bytes = (root / "manifest.json").read_bytes()
    reading_bytes = (root / "readings.json").read_bytes()
    require(digest(manifest_bytes) == resources.MANIFEST_SHA256 and
            digest(reading_bytes) == resources.READINGS_SHA256, "fixed source metadata pins")
    manifest, readings = json.loads(manifest_bytes), json.loads(reading_bytes)
    rows = {row["document_sha256"]: row for row in readings["readings"]}
    require(len(rows) == len(manifest["documents"]) == 794, "complete public metadata membership")
    selected = []
    for document in manifest["documents"]:
        reading = rows[document["sha256"]]
        profile = profile_for(reading["doc_type"])
        if profile is not None and profile.identity == BALANCE_IDENTITY:
            selected.append({**document, "doc_type": reading["doc_type"]})
    identity = {"sample_version": resources.VERSION, "manifest_sha256": resources.MANIFEST_SHA256,
                "readings_sha256": resources.READINGS_SHA256, "reading_contract": curation.CONTRACT,
                "document_count": 794, "source_event_count": readings["source_event_count"]}
    return selected, identity


def source_identity_growth(samples):
    require(len(samples) == 420, "identity growth keeps all 420 inputs")
    values = [sample["vm_instructions"] for sample in samples]
    require(all(type(value) is int and value > 0 for value in values), "positive identity VM work on every source input")
    initial, final = median(values[:20]), median(values[-20:])
    return {"count": len(values), "first20_median_vm": initial, "final20_median_vm": final,
            "ratio": final / initial, "threshold": 2.0, "passed": final <= 2 * initial}


def run_source_correctness(output):
    """Three actual originals exercise comparison without a qualifying run."""
    from viva.ingest import RawStore, capture_and_ingest
    from viva.ledger import EventStore, Ledger
    from viva.sample import resources
    from viva.sample.curation import CuratedReader
    from viva.sql_authority import SQLAuthority, CuratedSource
    source = CuratedSource.open()
    checking = [document for document in source.documents if document["doc_type"] == KINDS[0]][:2]
    card = [document for document in source.documents if document["doc_type"] == KINDS[2]][:1]
    documents = [document for document in source.documents if document in checking + card]
    require(len(documents) == 3, "bounded source correctness uses exactly three originals")
    write_new(output / "source-correctness-inputs.json", {"documents": documents, "pack": source.identity,
                                                        "scope": "two checking and one card; no performance qualification"})
    pack = resources.load_pack()
    reader = CuratedReader(pack)
    secret = secrets.token_urlsafe(48)
    oracle_root = output / "correctness-legacy"
    oracle_root.mkdir(mode=0o700)
    ledger = Ledger(EventStore.open(oracle_root / "events.jsonl", secret))
    raw = RawStore.open(oracle_root / "originals", secret)
    resolutions = {}
    with trace_legacy_resolution(resolutions):
        for document in documents:
            original = source.original(document["sha256"])
            result = capture_and_ingest(raw, ledger, original, reader, filename=document["file"], captured_at="2006-01-01")
            require(result.action == "posted", "bounded genuine legacy source posts")
            require(raw.get(result.doc_id) == original, "bounded genuine legacy original retrieval")
    events = list(ledger.store.events())
    records, decisions = [], {}
    with legacy_traps() as controls:
        with SQLAuthority.create(output / "correctness-sql", secret) as store:
            with guarded_sql(store):
                for document in documents:
                    doc_id = document["sha256"]
                    original = source.original(doc_id)
                    outcome = store.ingest_curated(original, source)
                    require(outcome.status == "accepted", "bounded genuine SQL source promotes")
                    require(store.original(doc_id) == original, "bounded genuine SQL original retrieval")
                    receipt = store.receipt(doc_id)
                    require(receipt["raw_reading"]["raw_text"] == resources.canonical(pack.readings[doc_id]["envelope"]).decode(),
                            "bounded complete raw source receipt")
                    admission = store.source_admission(doc_id)
                    require(admission is not None and admission["pack"] == source.identity, "bounded issued source admission")
                    decisions[doc_id] = store.identity_decision(doc_id)
                legacy_mapping, physical_mapping, logical_mapping = map_source_accounts(events, store,
                                                                                        [row["sha256"] for row in documents])
                for document in documents:
                    doc_id = document["sha256"]
                    expected = legacy_source_assertions(events, doc_id, pack.readings[doc_id]["envelope"], legacy_mapping)
                    actual = sql_source_assertions(store, doc_id, physical_mapping)
                    compare_source_document(expected, actual)
                    require(decisions[doc_id] is not None, "bounded source identity attempt retained")
                    compare_source_resolution(resolutions[doc_id], decisions[doc_id], legacy_mapping, logical_mapping, physical_mapping)
                    records.append({"doc_id": doc_id, "matched": True, "transactions": len(actual["transactions"]),
                                    "genuine_asserted_openings": sum(row["kind"] == "opening" for row in actual["asserted_observations"]),
                                    "printed_receipt_openings": len(actual["printed_openings"])})
                mutation_controls = source_comparison_controls(legacy_source_assertions(
                    events, documents[0]["sha256"], pack.readings[documents[0]["sha256"]]["envelope"], legacy_mapping))
                head = store.head
            store.verify(expected_head=head)
        reissued = CuratedSource.open()
        with SQLAuthority.open(output / "correctness-sql", secret) as reopened:
            reopened.attach_curated(reissued)
            with guarded_sql(reopened):
                for document in documents:
                    doc_id = document["sha256"]
                    require(reopened.resume(doc_id).status == "accepted", "reissued owner resumes completed source without rereading")
                    require(reopened.receipt(doc_id)["raw_reading"]["raw_text"] ==
                            resources.canonical(pack.readings[doc_id]["envelope"]).decode(), "reissued owner preserves raw receipt")
                require(reopened.head == head, "completed source resume creates no duplicate financial or audit rows")
            reopened.verify(expected_head=head)
    return {"scope": "three actual public originals, correctness only; no 420 or timing qualification",
            "gates_passed": True, "matched": records, "source_owner_reissue_and_reopen": True,
            "legacy_negative_controls": controls, "sql_negative_controls_per_scope": 6,
            "normal_history_negative_controls_per_scope": 4, "comparison_negative_controls": mutation_controls}


def run_curated_source(output):
    checkpoint = {}
    try:
        return _run_curated_source(output, checkpoint)
    finally:
        records = checkpoint.get("records")
        if records is not None:
            for record in records.values():
                record["disposition"] = final_source_disposition(
                    admission_error=record["admission_error"], state=record["state"], matched=record["matched"])
            counts = {label: sum(row["disposition"] == label for row in records.values())
                      for label in ("admission error", "declared unsupported", "pending", "promoted-and-matched", "mismatched")}
            require(len(records) == sum(counts.values()) == 420, "failed packet retains exclusive 420 dispositions")
            write_new(output / "source-dispositions.json", {"count": 420, "final_counts": counts,
                                                           "documents": list(records.values())})


def _run_curated_source(output, checkpoint):
    """Run the complete packet only after its separate measurement ruling."""
    experiment_started = time.perf_counter()
    from viva.ingest import RawStore, capture_and_ingest
    from viva.ingest.registry import BALANCE_IDENTITY, profile_for
    from viva.ledger import EventStore, Ledger
    from viva.sample import resources
    from viva.sample.curation import CuratedReader
    from viva.sql_authority import SQLAuthority, CuratedSource
    source_started = time.perf_counter()
    module_setup_seconds = source_started - experiment_started
    pack_root = Path(__file__).resolve().parents[1] / "product/viva/sample_data" / resources.VERSION
    documents, source_identity_before = frozen_public_selection(pack_root)
    require(len(documents) == 420 and {document["doc_type"] for document in documents} == set(KINDS),
            "fixed complete 420 balance inputs in manifest order")
    require(len({document["sha256"] for document in documents}) == 420, "source inputs unique")
    records = {document["sha256"]: {"doc_id": document["sha256"], "manifest_index": index,
                                   "doc_type": document["doc_type"], "legacy_initial_state": "not_attempted",
                                   "state": "not_attempted", "admission_error": False, "matched": False,
                                   "captured": False, "receipt_retained": False, "source_admitted": False,
                                   "interpreted": False, "source_bound": False}
               for index, document in enumerate(documents)}
    checkpoint["records"] = records
    manifest = {"pack": source_identity_before, "documents": documents,
                "sha256": digest(encode(documents)), "count": 420}
    write_new(output / "source-inputs.json", manifest)
    try:
        source = CuratedSource.open()
    except BaseException as exc:
        for record in records.values():
            record.update(admission_error=True, error_type=type(exc).__name__)
        raise
    source_setup = time.perf_counter() - source_started
    authenticated_documents = [document for document in source.documents
                               if (profile_for(document["doc_type"]) is not None and
                                   profile_for(document["doc_type"]).identity == BALANCE_IDENTITY)]
    require(authenticated_documents == documents and source.identity == source_identity_before,
            "issued source owner exactly matches independently frozen pinned inputs")
    pack_hash_started = time.perf_counter()
    pack_before = public_pack_identity(pack_root)
    pack_hash_seconds = time.perf_counter() - pack_hash_started
    write_new(output / "pack-before.json", pack_before)
    secret = secrets.token_urlsafe(48)
    oracle_root = output / "source-legacy-oracle"
    oracle_root.mkdir(mode=0o700)
    legacy_started = time.perf_counter()
    pack = resources.load_pack()
    reader = CuratedReader(pack)
    ledger = Ledger(EventStore.open(oracle_root / "events.jsonl", secret))
    raw = RawStore.open(oracle_root / "originals", secret)
    legacy_setup = time.perf_counter() - legacy_started
    resolutions, legacy_statuses = {}, {}
    legacy_started = time.perf_counter()
    with trace_legacy_resolution(resolutions):
        for document in documents:
            doc_id = document["sha256"]
            try:
                original = source.original(doc_id)
            except BaseException as exc:
                records[doc_id].update(admission_error=True, error_type=type(exc).__name__)
                raise
            result = capture_and_ingest(raw, ledger, original, reader,
                                        filename=document["file"], captured_at="2006-01-01")
            require(raw.get(doc_id) == original, "actual legacy source original retrieval")
            legacy_statuses[doc_id] = result.action
            records[doc_id]["legacy_initial_state"] = result.action
    legacy_capture = time.perf_counter() - legacy_started
    events = list(ledger.store.events())
    source_timings, identity_metrics, decisions = [], [], {}
    original_seconds = 0.0
    verification_seconds = comparison_seconds = reopen_seconds = 0.0
    source_controls = []
    capture_started = time.perf_counter()
    with legacy_traps() as forbidden_controls:
        initialization_started = time.perf_counter()
        store = SQLAuthority.create(output / "source-sql-authority", secret)
        initialization_seconds = time.perf_counter() - initialization_started
        with store:
            with guarded_sql(store):
                for document in documents:
                    doc_id = document["sha256"]
                    original_started = time.perf_counter()
                    try:
                        original = source.original(doc_id)
                    except BaseException as exc:
                        records[doc_id].update(admission_error=True, error_type=type(exc).__name__)
                        raise
                    original_seconds += time.perf_counter() - original_started
                    step = time.perf_counter()
                    try:
                        outcome = store.ingest_curated(original, source)
                    except BaseException as exc:
                        records[doc_id]["error_type"] = type(exc).__name__
                        try:
                            records[doc_id]["state"] = store.item(doc_id)["state"]
                            store.receipt(doc_id)
                        except Exception:
                            records[doc_id]["admission_error"] = True
                        raise
                    records[doc_id].update(state=outcome.status, reason=outcome.reason,
                                          import_seconds=time.perf_counter() - step)
                    required_timings = {"capture_seconds", "receipt_seconds", "source_validation_seconds",
                                        "parse_seconds", "interpretation_seconds", "settlement_seconds"}
                    timings = dict(store.last_source_timings)
                    require(set(timings) >= required_timings and all(
                        type(timings[name]) in {float, int} and timings[name] >= 0 for name in required_timings),
                        "complete actual-source stage timing evidence")
                    source_timings.append({"doc_id": doc_id, **timings})
                    decision = store.identity_decision(doc_id)
                    decisions[doc_id] = decision
                    if decision is None:
                        identity_metrics.append({"doc_id": doc_id, "measured": False, "vm_instructions": None,
                                                 "reason": "no retained identity attempt"})
                    else:
                        metrics = decision["metrics"]
                        require(set(metrics) >= {"vm_instructions", "rows_read", "queries", "plans", "closure_accounts",
                                                 "distinct_references", "witness_claims"}, "complete source identity boundary evidence")
                        identity_metrics.append({"doc_id": doc_id, "measured": True, **metrics})
                    require(store.original(doc_id) == original, "actual SQL source original retrieval")
                    receipt = store.receipt(doc_id)
                    admission = store.source_admission(doc_id)
                    require(admission is not None and admission["pack"] == source_identity_before and
                            admission["document"]["sha256"] == doc_id, "actual audited source admission matches pinned owner")
                    records[doc_id].update(captured=True, receipt_retained=True, source_admitted=True,
                                          interpreted=receipt["facts_type"] != "curated",
                                          source_bound=receipt["facts_type"] == "balance")
                    require(receipt["raw_reading"]["raw_text"] ==
                            resources.canonical(pack.readings[doc_id]["envelope"]).decode(),
                            "complete pinned envelope receipt unchanged")
                legacy_mapping, sql_mapping, logical_mapping = map_source_accounts(events, store, records)
                comparison_started = time.perf_counter()
                for document in documents:
                    doc_id = document["sha256"]
                    item = store.item(doc_id)
                    records[doc_id].update(state=item["state"], reason=item["reason"])
                    expected = legacy_source_assertions(events, doc_id, pack.readings[doc_id]["envelope"], legacy_mapping)
                    actual = sql_source_assertions(store, doc_id, sql_mapping)
                    records[doc_id].update(legacy_transactions=len(expected["transactions"]),
                                          sql_transactions=len(actual["transactions"]),
                                          legacy_asserted_observations=len(expected["asserted_observations"]),
                                          sql_asserted_observations=len(actual["asserted_observations"]))
                    if item["state"] == "accepted":
                        try:
                            compare_source_document(expected, actual)
                            require(doc_id in resolutions, "actual legacy resolver source witness")
                            require(decisions[doc_id] is not None, "accepted source has a retained identity decision")
                            require(decisions[doc_id]["physical_account"] == item["account_id"],
                                    "accepted financial account binds actual identity decision")
                            compare_source_resolution(resolutions[doc_id], decisions[doc_id], legacy_mapping, logical_mapping, sql_mapping)
                            records[doc_id]["matched"] = True
                            if not source_controls and expected["transactions"]:
                                source_controls = source_comparison_controls(expected)
                        except HarnessFailure as exc:
                            records[doc_id]["comparison_failure"] = str(exc)
                    records[doc_id]["disposition"] = final_source_disposition(
                        admission_error=records[doc_id]["admission_error"], state=item["state"], matched=records[doc_id]["matched"])
                comparison_seconds = time.perf_counter() - comparison_started
                head = store.head
            verification_started = time.perf_counter()
            store.verify(expected_head=head)
            verification_seconds = time.perf_counter() - verification_started
        reopen_started = time.perf_counter()
        with SQLAuthority.open(output / "source-sql-authority", secret) as reopened:
            reopened.attach_curated(source)
            with guarded_sql(reopened):
                for document in documents:
                    doc_id = document["sha256"]
                    require(reopened.item(doc_id)["state"] == records[doc_id]["state"], "source state survives reopen")
                    require(reopened.receipt(doc_id)["raw_reading"]["raw_text"] ==
                            resources.canonical(pack.readings[doc_id]["envelope"]).decode(), "source receipt survives reopen")
            reopened.verify(expected_head=head)
        reopen_seconds = time.perf_counter() - reopen_started
    capture_and_check_seconds = time.perf_counter() - capture_started
    after_hash_started = time.perf_counter()
    pack_after = public_pack_identity(pack_root)
    after_hash_seconds = time.perf_counter() - after_hash_started
    write_new(output / "pack-after.json", pack_after)
    require(pack_before == pack_after and source.identity == source_identity_before, "pinned complete inputs remain unchanged")
    dispositions = list(records.values())
    require(len(dispositions) == 420 and all("disposition" in row for row in dispositions), "complete exclusive source disposition table")
    counts = {label: sum(row["disposition"] == label for row in dispositions)
              for label in ("admission error", "declared unsupported", "pending", "promoted-and-matched", "mismatched")}
    require(sum(counts.values()) == 420, "exclusive final dispositions sum to 420")
    try:
        growth = source_identity_growth(identity_metrics)
    except HarnessFailure as exc:
        growth = {"count": len(identity_metrics), "threshold": 2.0, "passed": False,
                  "failure": str(exc), "unmeasured_doc_ids": [row["doc_id"] for row in identity_metrics if not row["measured"]]}
    promoted_types = {row["doc_type"] for row in dispositions if row["disposition"] == "promoted-and-matched"}
    passed = counts["admission error"] == counts["mismatched"] == 0 and counts["promoted-and-matched"] > 0 and promoted_types == set(KINDS) and growth["passed"]
    report = {"scope": "actual pinned 420 balance sources; overlays and other 374 inputs remain outside this slice",
              "gates_passed": passed, "complete_420_financial_parity": counts["promoted-and-matched"] == 420,
              "input_identity": manifest["sha256"], "exclusive_final_counts": counts, "dispositions": dispositions,
              "overlapping_stage_counts": {name: sum(bool(row[name]) for row in dispositions)
                                            for name in ("captured", "receipt_retained", "source_admitted", "interpreted", "source_bound")},
              "source_stage_timings": source_timings, "identity_metrics": identity_metrics, "identity_growth": growth,
              "comparison_negative_controls": source_controls, "legacy_negative_controls": forbidden_controls,
              "sql_negative_controls_per_scope": 6,
              "account_mapping_sha256": digest(encode({"legacy": legacy_mapping, "physical_sql": sql_mapping, "logical_sql": logical_mapping})),
              "timings": {"cold_source_setup_seconds": source_setup, "source_owner_setup_seconds": source.setup_seconds,
                          "module_setup_seconds": module_setup_seconds,
                          "initial_input_identity_seconds": pack_hash_seconds, "final_input_identity_seconds": after_hash_seconds,
                          "legacy_setup_seconds": legacy_setup, "legacy_capture_seconds": legacy_capture,
                          "sql_initialization_seconds": initialization_seconds, "original_retrieval_seconds": original_seconds,
                          "sql_capture_and_checks_seconds": capture_and_check_seconds,
                          "comparison_seconds": comparison_seconds, "verification_seconds": verification_seconds,
                          "reopen_and_verification_seconds": reopen_seconds,
                          "sql_composed_seconds": module_setup_seconds + source_setup + pack_hash_seconds + capture_and_check_seconds + after_hash_seconds,
                          "whole_experiment_seconds_including_legacy": time.perf_counter() - experiment_started},
              "timing_note": "Stage counters are nested within capture/settlement and are not added twice; no full-pack setup or explicit verification excluded from SQL composed total."}
    write_new(output / "source-comparison.json", report)
    return report


def run_parity(output):
    from viva.ingest import RawStore, capture_and_ingest
    from viva.ledger import EventStore, Ledger
    from viva.sql_authority import SQLAuthority
    cases = [fixture(kind, index) for kind in KINDS for index in (1, 2, 0, 3)]
    manifest = fixture_identity(cases)
    write_new(output / "inputs.json", manifest)
    passphrase = secrets.token_urlsafe(48)
    oracle_root = output / "legacy-oracle"
    oracle_root.mkdir(mode=0o700)
    ledger = Ledger(EventStore.open(oracle_root / "events.jsonl", passphrase))
    raw = RawStore.open(oracle_root / "originals", passphrase)
    legacy_calls = []
    for case in cases:
        outcome = capture_and_ingest(raw, ledger, case["original"], reader_for(case, legacy_calls),
                                     filename="synthetic.pdf", captured_at="2001-02-01")
        require(outcome.action == "posted", "supported oracle fixture must post")
        require(raw.get(outcome.doc_id) == case["original"], "oracle original retrieval")
    expected = oracle_snapshot(ledger, cases)
    counter_controls = counter_comparison_controls(expected)
    calls = []
    outcomes = []
    with legacy_traps() as proved:
        with SQLAuthority.create(output / "sql-authority", passphrase) as store:
            with guarded_sql(store) as guard:
                for case in cases:
                    outcome = store.ingest(case["original"], reader_for(case, calls), contract=CONTRACT)
                    require(outcome.status == "accepted", "supported SQL fixture must accept")
                    outcomes.append(outcome)
                    require(store.original(outcome.doc_id) == case["original"], "SQL original retrieval")
                    receipt = store.receipt(outcome.doc_id)
                    require(receipt["contract"] == CONTRACT, "receipt contract")
                    require(receipt["reading"]["raw_text"] == encode(case["payload"]).decode("ascii"), "raw response retained")
                actual = sql_snapshot(store, outcomes)
                compare_snapshots(expected, actual)
                head = store.head
                duplicate = store.ingest(cases[0]["original"], reader_for(cases[0], calls), contract=CONTRACT)
                require(duplicate.status == "accepted" and store.head == head, "byte duplicate idempotency")
                held = held_cases(store, calls)
                sql_evidence = {"statements": guard.statements,
                                "dependency_plans": store.dependency_plans()}
                final_head = store.head
            store.verify(expected_head=final_head)
            structure = store.export_audit()
            SQLAuthority.check_export_structure(structure, expected_head=final_head)
        with SQLAuthority.open(output / "sql-authority", passphrase) as reopened:
            with guarded_sql(reopened):
                require(sql_snapshot(reopened, outcomes) == expected, "reopened legacy parity")
                for case, outcome in zip(cases, outcomes):
                    require(reopened.original(outcome.doc_id) == case["original"], "reopened original retrieval")
                    require(reopened.receipt(outcome.doc_id)["contract"] == CONTRACT, "reopened receipt retrieval")
            reopened.verify(expected_head=final_head)
    require(len(calls) == len(cases) + held["reader_calls"], "no duplicate extraction")
    require(fixture_identity(cases) == manifest, "fixed parity inputs unchanged")
    return {"scope": "first balance-statement slice; not full 794 parity", "supported": len(outcomes),
            "legacy_calls": len(legacy_calls), "prototype_calls": len(calls), "inputs": manifest,
            "parity_fields": ["account metadata", "balances", "transaction fields", "postings", "provenance", "grades", "source references", "balance observations"],
            "legacy_negative_controls": proved, "sql_negative_controls": 6, "held": held,
            "counter_comparison_negative_controls": counter_controls,
            "sql": sql_evidence, "reopen_verified": True, "inputs_unchanged": True}


def held_cases(store, calls):
    from viva.ingest.pipeline_models import ReadResult
    held = []
    cases = []
    masked = fixture(KINDS[0], 7, namespace="masked")
    masked["payload"]["account_number"] = "****0001"
    masked["original"] = b"%PDF-1.4\n% synthetic masked fixture\n" + encode(masked["payload"]) + b"\n%%EOF\n"
    cases.append(masked)
    overlap = fixture(KINDS[0], 1, namespace="economic-duplicate")
    cases.append(overlap)
    for case in cases:
        outcome = store.ingest(case["original"], reader_for(case, calls), contract=CONTRACT)
        require(outcome.status == "pending" and not store.postings(outcome.doc_id), "unsupported identity/overlap held")
        held.append({"case": case["id"], "state": outcome.status, "reason": outcome.reason})
    mismatch = fixture(KINDS[0], 8, namespace="raw-typed-mismatch")
    base_reader = reader_for(mismatch, calls)
    def mismatched_reader(original, doc_id):
        result = base_reader(original, doc_id)
        result.facts.closing_amount += Decimal("1.00")
        return result
    outcome = store.ingest(mismatch["original"], mismatched_reader, contract=CONTRACT)
    require(outcome.status == "pending" and not store.postings(outcome.doc_id), "raw and typed extraction mismatch held")
    held.append({"case": mismatch["id"], "state": outcome.status, "reason": outcome.reason})
    original = b"synthetic unsupported financial family"
    def unsupported_reader(_data, doc_id):
        calls.append(doc_id)
        return ReadResult("unknown", 1.0, None, raw_text='{"doc_type":"unknown"}', model="synthetic-offline-reader")
    outcome = store.ingest(original, unsupported_reader, contract=CONTRACT)
    require(outcome.status == "unsupported" and not store.postings(outcome.doc_id), "unsupported family held")
    held.append({"case": "unsupported family", "state": outcome.status, "reason": outcome.reason})
    return {"cases": held, "accepted": 0, "reader_calls": len(cases) + 2,
            "limitation": "identity ambiguity and overlap are conservatively held, not complete legacy parity"}


def distribution(samples):
    ordered = sorted(samples)
    def percentile(fraction):
        return ordered[max(0, math.ceil(len(ordered) * fraction) - 1)]
    return {"count": len(samples), "min_ms": ordered[0], "p50_ms": percentile(.5),
            "p95_ms": percentile(.95), "p99_ms": percentile(.99), "max_ms": ordered[-1]}


def median(samples):
    ordered = sorted(samples)
    middle = len(ordered) // 2
    return (ordered[middle - 1] + ordered[middle]) / 2 if len(ordered) % 2 == 0 else ordered[middle]


def run_scale(output):
    from viva.sql_authority import SQLAuthority
    passphrase = secrets.token_urlsafe(48)
    reports = []
    all_pass = True
    with legacy_traps() as proved:
        for count in (100, 1000, 5000):
            # Generate before timing. Each statement is two rows, unchanged
            # opening/closing, and exactly one accepted account dependency.
            cases = [fixture(KINDS[0], index, constant=True, namespace=f"scale-{count}") for index in range(count)]
            manifest = fixture_identity(cases)
            write_new(output / f"inputs-{count}.json", manifest)
            started = time.perf_counter()
            store = SQLAuthority.create(output / f"sql-{count}", passphrase)
            initialization = time.perf_counter() - started
            settlements = []
            elapsed = []
            queried_rows = []
            instruction_counts = []
            calls = []
            query_shapes = set()
            accepted = 0
            with store:
                with guarded_sql(store) as guard:
                    started = time.perf_counter()
                    for case in cases:
                        step = time.perf_counter()
                        outcome = store.ingest(case["original"], reader_for(case, calls), contract=CONTRACT)
                        elapsed.append((time.perf_counter() - step) * 1000)
                        instruction_counts.append(store.last_vm_steps)
                        settlements.append(outcome.settlement_ms)
                        queried_rows.append(store.last_rows_read)
                        query_shapes.update(store.last_queries)
                        accepted += outcome.status == "accepted"
                        require(outcome.status == "accepted", "scale must accept every fixture")
                    capture = time.perf_counter() - started
                    plans = store.dependency_plans()
                    head = store.head
                verification_started = time.perf_counter()
                store.verify(expected_head=head)
                verification_seconds = time.perf_counter() - verification_started
            stats = distribution(settlements)
            require(fixture_identity(cases) == manifest, "fixed scale inputs unchanged")
            initial, final = median(settlements[:20]), median(settlements[-20:])
            gate = accepted == count and final <= 2 * initial and stats["p95_ms"] < 100 and stats["p99_ms"] < 250
            if count == 100:
                gate = gate and capture < 30
            all_pass = all_pass and gate
            report = {"count": count, "accepted": accepted, "initialization_seconds": initialization,
                      "capture_seconds_excluding_initialization": capture,
                      "settlement": stats, "initial20_median_ms": initial, "final20_median_ms": final,
                      "last_to_first_ratio": final / initial, "capture_per_document": distribution(elapsed),
                      "settlement_ms": settlements, "capture_ms": elapsed, "queried_rows": queried_rows,
                      "approx_vm_instructions_per_document": instruction_counts,
                      "query_shapes": sorted(query_shapes), "dependency_plans": plans,
                      "verification_seconds_excluded_from_capture": verification_seconds,
                      "inputs": manifest, "inputs_unchanged": True, "gates_passed": gate}
            write_new(output / f"scale-{count}.json", report)
            reports.append(report)
    return {"scope": "constant two-row supported balance statements; not mixed corpus or packaged readiness",
            "gates_passed": all_pass, "legacy_negative_controls": proved,
            "sql_negative_controls_per_vault": 6, "runs": reports,
            "instrumentation": "SQL execute guard; product progress callback every 100 VM instructions and last_rows_read cover settlement only"}


# Isolated transfer instrumentation. These helpers never define SQL admission.
TRANSFER_FIXTURE_SHA256 = "32f50d518dae75a44b24fc8ed518b3f11d3f9e85635519294944e950ab8b5077"
TRANSFER_FROZEN_FUNCTIONS = ("fixture", "fixture_identity", "reader_for", "distribution", "median", "run_scale", "run_parity")


def transfer_case(identifier, institution, name, number, amounts, *, currency="USD", descriptions=None, dates=None):
    """A genuine generic synthetic reading with an original byte identity."""
    amounts = [Decimal(value) for value in amounts]
    opening = Decimal("0") if not amounts else Decimal("10000")
    payload = {"doc_type": "checking_statement", "doc_type_confidence": 1.0,
               "account_ref": name, "account_number": number, "institution": institution,
               "account_names": [],
               "opening": {"amount_raw": str(opening), "date_raw": "2024-02-01", "page": 1},
               "closing": {"amount_raw": str(opening + sum(amounts)), "date_raw": "2024-02-29", "page": 1},
               "transactions": [{"amount_raw": str(abs(amount)),
                    "balance_effect": "increase" if amount > 0 else "decrease",
                    "date_raw": dates[i] if dates else "2024-02-17",
                    "description": descriptions[i] if descriptions else "unrelated incoming",
                    "page": 1, "source_reference": f"synthetic:{identifier}:{i}",
                    "counterparty_reference": ""} for i, amount in enumerate(amounts)]}
    original = b"%PDF-1.4\n% synthetic transfer original\n" + encode({"id": identifier, "currency": currency, "reading": payload}) + b"\n%%EOF\n"
    return {"id": identifier, "original": original, "payload": payload, "currency": currency}


def transfer_fixed_cases(population=0):
    require(type(population) is int and 0 <= population <= 1000, "fixed fixture population")
    cases = [transfer_case("s1", "Alpha", "A", "100000001111", ["-10.00"], descriptions=["synthetic Alpha payment"]),
             transfer_case("s2", "Beta", "C", "300000003333", ["-10.00"], descriptions=["synthetic Beta payment"]),
             transfer_case("d", "Gamma", "B", "200000002222", ["10.00"], descriptions=["synthetic incoming"])]
    cases.extend(transfer_case(f"unrelated-{i:04d}", "Background", "Background", str(900000100000+i), [str(1000+i)])
                 for i in range(population))
    return cases, transfer_case("new-owner", "Beta", "Extra", "400000004444", [], currency="EUR")


def transfer_reader(case, calls):
    from viva.ingest.pipeline_models import ReadResult
    from viva.ingest.statement import from_model_json
    raw = encode(case["payload"]).decode("ascii")
    def read(original, doc_id):
        require(original == case["original"] and digest(original) == doc_id, "transfer reader original binding")
        calls.append(doc_id)
        facts, error = from_model_json(raw, doc_id, "en-US", case["currency"])
        require(error is None and facts is not None, "transfer extraction parses")
        return ReadResult("checking_statement", 1.0, facts, raw_text=raw,
                          model="synthetic-offline-reader", resolved_model="synthetic-offline-reader",
                          prompt_version="synthetic-balance-v1", source_locale="en-US", input_mode="text")
    return read


def transfer_full_context(projection, previous=None):
    """Independent full-inventory legacy expectation; no candidate exports."""
    from viva.ingest import transfers as t
    from viva.ledger.identity import account_tokens
    graph, sources = t._candidates(projection)
    distinctive = t._distinctive(projection)
    strength, why = t.weigh(projection, graph, sources, distinctive, lambda _movement: None)
    movements = list(projection.movements())
    if previous is None:
        endpoint_keys = {m.key for m in movements}
    else:
        before_movements, before_accounts = previous
        current_accounts = set(projection.accounts())
        new_tokens = set()
        for account in current_accounts - set(before_accounts):
            info = projection.account_info(account)
            new_tokens.update(account_tokens(info.institution, info.number, info.name))
        endpoint_keys = {m.key for m in movements if m.key not in before_movements
                         or m.linked != before_movements[m.key]}
        for m in movements:
            info = projection.account_info(m.account)
            if not m.linked and account_tokens(info.institution, info.number, info.name) & new_tokens:
                endpoint_keys.add(m.key)
        changed = True
        while changed:
            changed = False
            for key, values in graph.items():
                component = {key} | {m.key for m in values}
                if component & endpoint_keys and not component <= endpoint_keys:
                    endpoint_keys.update(component); changed = True
    graph = {key: values for key, values in graph.items() if key in endpoint_keys}
    strength = {pair: value for pair, value in strength.items() if pair[0] in graph}
    why = {pair: value for pair, value in why.items() if pair[0] in graph}
    endpoint_accounts = {m.account for m in movements if m.key in endpoint_keys and not m.linked}
    infos = {account: projection.account_info(account) for account in projection.accounts()}
    tokens = {account: account_tokens(info.institution, info.number, info.name) for account, info in infos.items()}
    raw = set().union(*(tokens[account] for account in endpoint_accounts)) if endpoint_accounts else set()
    owners = endpoint_accounts | {account for account, values in tokens.items() if values & raw}
    return {"endpoints": sorted(endpoint_keys),
            "owners": [{"account": account, "kind": info.kind, "currency": info.currency,
                        "institution": info.institution, "number": info.number, "name": info.name}
                       for account, info in infos.items() if account in owners],
            "graph": {key: [m.key for m in values] for key, values in graph.items()},
            "strength": [{"a": a, "b": b, "score": score} for (a,b), score in strength.items()],
            "why": [{"a": a, "b": b, "rule": rule} for (a,b), rule in why.items()],
            "verdicts": t.decide(graph, strength),
            "initial_open": sorted(row["a"] for row in projection.transfer_suggestions() if row["a"] in graph)}


@contextmanager
def transfer_oracle_scans(scans, *, retain_last=None):
    """Retain actual scan boundaries, supplying only the explicit empty profile."""
    from viva.ingest import transfers as t
    from viva import induce_profile
    original = t.link_transfers
    changes = []
    previous = None
    def scan(ledger, profile_for=None):
        nonlocal previous
        projection = ledger.projection()
        expected = transfer_full_context(projection, previous)
        previous = ({m.key: m.linked for m in projection.movements()}, projection.accounts())
        assertions = []
        class ObservedLedger:
            def projection(self):
                return ledger.projection()
            def append(self, event):
                ledger.append(event)
                assertions.append(transfer_transport(event))
        result = original(ObservedLedger(), profile_for=lambda _movement: None)
        expected["assertions"] = assertions
        scans.append(expected)
        if retain_last is not None and len(scans) > retain_last:
            del scans[:-retain_last]
        previous = ({m.key: m.linked for m in ledger.projection().movements()}, ledger.projection().accounts())
        return result
    def forbidden(*_args, **_kwargs):
        raise HarnessFailure("host profile access forbidden")
    for module in tuple(sys.modules.values()):
        namespace = getattr(module, "__dict__", {})
        for name, value in tuple(namespace.items()):
            if value is original:
                changes.append((module, name, value)); setattr(module, name, scan)
    for owner, name in ((t, "default_profile_for"), (induce_profile, "profile_store")):
        changes.append((owner, name, getattr(owner, name))); setattr(owner, name, forbidden)
    try:
        yield
    finally:
        for owner, name, value in reversed(changes):
            setattr(owner, name, value)


def transfer_transport(event):
    return {"event_type": event.event_type, "occurred_at": event.occurred_at,
            "body": deepcopy(event.body), "provenance": event.provenance.to_dict()}


def transfer_movement_rows(movements):
    return [{"key": m.key, "account": m.account, "kind": m.kind, "date": m.date,
             "amount": str(m.amount), "description": m.description, "currency": m.currency,
             "provenance": m.provenance.to_dict(), "linked": m.linked} for m in movements]


def transfer_legacy_financial(ledger):
    projection = ledger.projection()
    transactions, observations, readings, inventory = [], [], {}, []
    seen = set()
    source_docs = {}
    for event in ledger.store.events():
        if event.event_type in {"OpeningBalanceObserved", "ClosingBalanceObserved"}:
            source_docs.setdefault(event.body["account_id"], event.provenance.doc_id)
    def admit(account, doc_id):
        if account in seen:
            return
        seen.add(account)
        info = projection.account_info(account)
        inventory.append({"account": account, "kind": info.kind, "currency": info.currency,
                          "institution": info.institution, "number": info.number, "name": info.name,
                          "source_doc": doc_id, "source_order": len(inventory)+1})
    for event in ledger.store.events():
        body, prov = event.body, event.provenance
        if event.event_type == "AccountOpened":
            admit(body["account_id"], source_docs[body["account_id"]])
        elif event.event_type == "TransactionRecorded":
            for posting in body["postings"]:
                admit(posting["account"], prov.doc_id)
            transactions.append({"doc_id": prov.doc_id, "date": event.occurred_at,
                "description": body["description"], "postings": body["postings"],
                "provenance": prov.to_dict(), "source_reference": body.get("source_reference", ""),
                "counterparty_reference": body.get("counterparty_reference", "")})
        elif event.event_type in {"OpeningBalanceObserved", "ClosingBalanceObserved"}:
            observations.append({"account": body["account_id"], "date": event.occurred_at,
                "amount": body["amount"], "kind": "opening" if event.event_type.startswith("Opening") else "closing",
                "provenance": prov.to_dict()})
        elif event.event_type == "ReadRecorded" and body.get("phase") == "extract":
            readings[prov.doc_id] = body["response_text"]
    return {"transactions": transactions, "observations": sorted_records(observations),
            "readings": readings, "inventory": inventory}


def transfer_sql_financial(store):
    inventory = store.transfer_inventory()
    physical = {}
    for row in inventory:
        if row["kind"] in {"depository", "liability"}:
            account = store.account(store.item(row["source_doc"])["account_id"])
            require(account["logical_key"] == row["account"], "per-boundary physical logical mapping")
            require(account["account_id"] not in physical, "per-boundary account bijection")
            physical[account["account_id"]] = row["account"]
    bindings = store.transfer_bindings()
    docs = list(dict.fromkeys(row["source_doc"] for row in inventory))
    # Documents on existing accounts are represented by new source bindings.
    docs = list(dict.fromkeys(docs + [row["doc_id"] for row in bindings]))
    rows_by_id = {row["txn_id"]: row for doc in docs for row in store.source_transactions(doc)}
    posts = {doc: store.postings(doc) for doc in docs}
    transactions = []
    for binding in bindings:
        row = rows_by_id[binding["txn_id"]]
        transactions.append({"doc_id": row["doc_id"], "date": row["date"], "description": row["description"],
            "postings": [{"account": physical.get(p["account_id"], p["account_id"]), "amount": p["amount"], "grade": p["grade"]}
                         for p in posts[row["doc_id"]] if p["txn_id"] == row["txn_id"]],
            "provenance": row["provenance"], "source_reference": row["source_reference"],
            "counterparty_reference": row["counterparty_reference"]})
    observations = []
    for account_id, logical in physical.items():
        for row in store.balance_observations(account_id):
            if row["event_asserted"]:
                observations.append({"account": logical, "date": row["date"], "amount": row["amount"],
                                     "kind": row["kind"], "provenance": row["provenance"]})
    return {"transactions": transactions, "observations": sorted_records(observations),
            "readings": {doc: store.receipt(doc)["reading"]["raw_text"] for doc in docs}, "inventory": inventory}


def transfer_oracle_snapshot(ledger, dates=("2024-02-16", "2024-02-17", "2024-03-01")):
    projection = ledger.projection()
    return {"financial": transfer_legacy_financial(ledger), "movements": transfer_movement_rows(projection.movements()),
            "assertions": [transfer_transport(event) for event in ledger.store.events() if event.event_type.startswith("Transfer")],
            "links": projection.transfer_links(),
            "suggestions": projection.transfer_suggestions(),
            "stored": list(projection._core._transfer_suggestions.values()),
            "as_of": {day: {"links": ledger.projection_as_of(day).transfer_links(),
                            "suggestions": ledger.projection_as_of(day).transfer_suggestions()} for day in dates}}


def transfer_sql_snapshot(store, dates=("2024-02-16", "2024-02-17", "2024-03-01")):
    return {"financial": transfer_sql_financial(store), "movements": transfer_movement_rows(store.movements()),
            "assertions": [{key: row[key] for key in ("event_type", "occurred_at", "body", "provenance")}
                           for row in store.transfer_assertions()],
            "links": store.transfer_links(), "suggestions": store.transfer_suggestions(),
            "stored": store.transfer_suggestions(stored=True),
            "as_of": {day: store.transfer_as_of(day) for day in dates}}


def compare_transfer_snapshot(expected, actual):
    require(set(expected) == set(actual), "transfer comparison closed dimensions")
    for key in expected:
        if key == "financial":
            require(set(expected[key]) == set(actual[key]), "transfer financial closed dimensions")
            for field in expected[key]:
                require(expected[key][field] == actual[key][field], "transfer financial parity: " + field)
        else:
            require(expected[key] == actual[key], "transfer parity: " + key)


def compare_transfer_decision(expected, actual):
    """Compare full-context oracle semantic fields without trusting witnesses."""
    for key in ("endpoints", "graph", "verdicts", "initial_open", "assertions"):
        require(expected[key] == actual[key], "transfer decision parity: " + key)
    for key in ("strength", "why"):
        require(sorted(expected[key], key=lambda row: (row["a"], row["b"])) ==
                sorted(actual[key], key=lambda row: (row["a"], row["b"])), "transfer decision parity: " + key)
    owners = [{key: row[key] for key in ("account", "kind", "currency", "institution", "number", "name")}
              for row in actual["owners"]]
    require(expected["owners"] == owners, "transfer decision parity: raw token owners")


class TransferVM:
    """Count the entire outer operation despite nested product handler resets."""
    def __init__(self, connection):
        self.connection, self.steps, self.statements = connection, 0, []
        self.callback, self.interval, self.ticks = None, 0, 0
    def count(self):
        self.steps += 1
        if self.callback is not None:
            self.ticks += 1
            if self.ticks >= self.interval:
                self.ticks = 0
                return self.callback()
        return 0
    def set_progress_handler(self, callback, interval):
        self.callback, self.interval, self.ticks = callback, interval, 0
        self.connection.set_progress_handler(self.count, 1)
    def execute(self, statement, parameters=()):
        self.statements.append(statement)
        return self.connection.execute(statement, parameters)
    def __getattr__(self, name):
        return getattr(self.connection, name)


@contextmanager
def transfer_vm(store):
    connection = store._db
    meter = TransferVM(connection)
    store._db = meter
    connection.set_progress_handler(meter.count, 1)
    try:
        yield meter
    finally:
        connection.set_progress_handler(None, 0)
        store._db = connection


def transfer_growth_gate(samples):
    require(set(samples) == {100, 1000}, "fixed transfer populations")
    require(all(len(values) == 20 and all(type(n) is int and n > 0 for n in values) for values in samples.values()),
            "twenty positive independent transfer samples")
    ratio = median(samples[1000]) / median(samples[100])
    return {"medians": {str(n): median(values) for n, values in samples.items()},
            "growth": ratio, "gates_passed": ratio <= 2.0}


def transfer_consume_history(store):
    """Declared counterfactual: consume every source and overlay history row once."""
    counts = {}
    for table in ("transactions", "postings", "audit", "receipts", "interpretations",
                  "source_occurrences", "transfer_bindings", "transfer_assertions"):
        counts[table] = len(store._db.execute("SELECT * FROM " + table).fetchall())
    require(counts["transactions"] > 0 and counts["audit"] > 0, "history counterfactual nonempty")
    return counts


def transfer_source_mapping(ledger, store):
    """Prove the bijections and exact immutable source occurrence bindings."""
    from viva.ledger.movement_identity import movement_key
    events = list(ledger.store.events())
    projection = ledger.projection()
    actual_inventory = store.transfer_inventory()
    actual_by_account = {row["account"]: row for row in actual_inventory}
    require(len(actual_by_account) == len(actual_inventory), "transfer inventory bijection")
    require(set(actual_by_account) == set(projection.accounts()), "transfer complete seen inventory")
    for account in projection.accounts():
        info = projection.account_info(account)
        expected = {"account": account, "kind": info.kind, "currency": info.currency,
                    "institution": info.institution, "number": info.number, "name": info.name}
        require(expected == {key: actual_by_account[account][key] for key in expected}, "transfer immutable account metadata")
    bindings = store.transfer_bindings()
    physical = {}
    expected = []
    counts = {}
    for event in events:
        if event.event_type != "TransactionRecorded":
            continue
        for posting in event.body["postings"]:
            account = posting["account"]
            if projection.account_info(account).kind not in {"depository", "liability"}:
                continue
            body, prov = event.body, event.provenance
            amount = posting["amount"]
            signature = (prov.doc_id, account, event.occurred_at, amount, body["description"])
            occurrence = counts.get(signature, 0); counts[signature] = occurrence+1
            expected.append({"movement": movement_key(prov.doc_id, account, event.occurred_at, Decimal(amount), body["description"], occurrence),
                             "account": account, "doc_id": prov.doc_id, "page": prov.page,
                             "date": event.occurred_at, "amount": amount, "description": body["description"],
                             "occurrence": occurrence, "source_order": len(expected)+1})
    require(len(bindings) == len(expected), "transfer source multiplicity")
    for wanted, actual in zip(expected, bindings):
        require(wanted == {key: actual[key] for key in wanted}, "transfer source identity/order/occurrence")
        account = store.account(actual["physical_account"])
        require(account["logical_key"] == wanted["account"], "transfer logical physical account mapping")
        physical.setdefault(wanted["account"], actual["physical_account"])
        require(physical[wanted["account"]] == actual["physical_account"], "transfer stable physical mapping")
        source = store.transactions(actual["physical_account"])
        transaction = [row for row in source if row["txn_id"] == actual["txn_id"]]
        require(len(transaction) == 1 and transaction[0]["doc_id"] == wanted["doc_id"], "transfer transaction binding")
    require(len(set(physical.values())) == len(physical), "transfer account mapping bijection")
    return {"inventory": actual_inventory, "bindings": bindings}


def transfer_activity_action(ledger, operation, a, b="", *, today="2024-03-01"):
    """Use actual Activity admission then unchanged writer with a fixed clock."""
    from viva.ingest import transfers as t
    from viva.surface.activity import _current_classification, _transfer_state
    projection = ledger.projection()
    require(not projection._core._categories and not projection._core._merchant_categories,
            "manual baseline genuinely absent classification")
    movement = next((m for m in projection.movements() if m.key == a), None)
    if movement is None or not _current_classification(projection, movement)["valid"]:
        return False
    state, actions = _transfer_state(projection, movement, "en-US")
    if operation not in actions:
        return False
    if operation == "confirm_transfer" and b not in [row["id"] for row in state["candidates"]]:
        return False
    if operation == "unlink_transfer" and b != state["counterpart"]["id"]:
        return False
    original = t._today
    t._today = lambda: today
    try:
        if operation == "confirm_transfer":
            return t.confirm_transfer(ledger, a, b)
        t.reject_transfer(ledger, a, b if operation == "unlink_transfer" else "")
        return True
    finally:
        t._today = original


def transfer_legacy_case(root, cases, *, retain_boundaries=True):
    from viva.ingest import RawStore, capture_and_ingest
    from viva.ledger import EventStore, Ledger
    root.mkdir(mode=0o700)
    passphrase = secrets.token_urlsafe(48)
    ledger = Ledger(EventStore.open(root / "events.jsonl", passphrase))
    raw = RawStore.open(root / "originals", passphrase)
    scans, snapshots, calls = [], [], []
    with transfer_oracle_scans(scans, retain_last=None if retain_boundaries else 2):
        for index, case in enumerate(cases):
            outcome = capture_and_ingest(raw, ledger, case["original"], transfer_reader(case, calls),
                                         filename="synthetic.pdf", captured_at="2024-03-01")
            require(outcome.action == "posted", "transfer legacy source must post")
            require(raw.get(outcome.doc_id) == case["original"], "transfer legacy original custody")
            if retain_boundaries or index >= len(cases)-2:
                snapshots.append(transfer_oracle_snapshot(ledger))
    return ledger, scans, snapshots


def transfer_control_cases(control):
    if control == "metadata-wakeup":
        cases, extra = transfer_fixed_cases()
        return cases+[extra]
    source = transfer_case("source", "Alpha", "A", "100000001111", ["-10.00"], descriptions=["synthetic payment to 2222"])
    destination = transfer_case("destination", "Gamma", "B", "200000002222", ["10.00"], descriptions=["synthetic incoming"])
    if control == "omit-rival":
        rival = transfer_case("rival", "Beta", "C", "300000003333", ["-10.00"], descriptions=["synthetic payment to 2222"])
        return [source, rival, destination]
    if control == "omit-global-owner":
        owner = transfer_case("outside-owner", "Delta", "Extra", "400000002222", [], currency="EUR")
        return [source, owner, destination]
    if control == "candidate-order":
        other = transfer_case("other-destination", "Delta", "D", "500000005555", ["10.00"], descriptions=["synthetic incoming later"], dates=["2024-02-18"])
        ambiguous = transfer_case("ambiguous-source", "Alpha", "A", "100000001111", ["-10.00"], descriptions=["synthetic outgoing"])
        return [destination, other, ambiguous]
    raise HarnessFailure("unknown transfer mutation control")


@contextmanager
def transfer_selector_mutation(store, control, cases):
    """Mutate an actual SQL settlement selector or assertion constructor."""
    from viva.sql_authority import transfers
    original_read = store._read
    original_constructor = transfers.transfer_suggested
    hits = []
    ignored = None
    if control == "omit-rival":
        rival_doc = digest(cases[1]["original"])
        ignored = next(row["movement"] for row in store.transfer_bindings() if row["doc_id"] == rival_doc)
    if control == "omit-global-owner":
        owner_doc = digest(cases[1]["original"])
        ignored = next(row["account"] for row in store.transfer_inventory() if row["source_doc"] == owner_doc and row["number"])
    def read(statement, parameters=()):
        rows = original_read(statement, parameters)
        if control == "metadata-wakeup" and statement.startswith("SELECT movement FROM transfer_dirty WHERE active=1"):
            hits.append("dirty-source-selection")
            return []
        if control == "omit-rival" and (statement.startswith("SELECT movement FROM transfer_dirty WHERE active=1")
                                        or statement.startswith("SELECT x.b FROM transfer_edges")):
            if any(row[0] == ignored for row in rows):
                hits.append("rival-component-selection")
            return [row for row in rows if row[0] != ignored]
        if control == "omit-global-owner" and statement.startswith("SELECT DISTINCT inventory.account,inventory.kind,inventory.currency,inventory.institution,inventory.number,inventory.name,inventory.source_doc,inventory.source_order FROM transfer_tokens endpoint JOIN transfer_tokens owners ON owners.token=endpoint.token JOIN transfer_inventory inventory ON inventory.account=owners.account WHERE endpoint.account=? ORDER BY inventory.account"):
            if any(row[0] == ignored for row in rows):
                hits.append("global-token-owner-selection")
            return [row for row in rows if row[0] != ignored]
        return rows
    def suggested(a, candidates, evidence, occurred_at):
        if len(candidates) > 1:
            hits.append("ordered-suggestion-constructor")
            return original_constructor(a, list(reversed(candidates)), evidence, occurred_at)
        return original_constructor(a, candidates, evidence, occurred_at)
    store._read = read
    if control == "candidate-order":
        transfers.transfer_suggested = suggested
    try:
        yield hits
    finally:
        store._read = original_read
        transfers.transfer_suggested = original_constructor


def run_transfer_selection_controls(output):
    from viva.sql_authority import SQLAuthority
    evidence = []
    for control in ("omit-rival", "omit-global-owner", "candidate-order", "metadata-wakeup"):
        cases = transfer_control_cases(control)
        ledger, scans, snapshots = transfer_legacy_case(output / (control+"-oracle"), cases)
        with SQLAuthority.create(output / (control+"-sql"), secrets.token_urlsafe(48)) as store:
            with legacy_traps(), guarded_sql(store):
                for case in cases[:-1]:
                    result = store.ingest(case["original"], transfer_reader(case, []), contract=CONTRACT)
                    require(result.status == "accepted", "mutation setup source admission")
            compare_transfer_snapshot(snapshots[-2], transfer_sql_snapshot(store))
            with transfer_selector_mutation(store, control, cases) as hits, legacy_traps(), guarded_sql(store):
                result = store.ingest(cases[-1]["original"], transfer_reader(cases[-1], []), contract=CONTRACT)
            require(result.status == "accepted" and hits, "actual SQL selector mutation must execute: "+control)
            actual = transfer_sql_snapshot(store)
            if control in {"omit-rival", "omit-global-owner"}:
                require(len(actual["links"]) == len(snapshots[-1]["links"])+1, "omission must manufacture false uniqueness")
            elif control == "metadata-wakeup":
                require(not actual["links"] and len(snapshots[-1]["links"]) == 1, "missing wakeup must lose actual automatic link")
            else:
                require(actual["suggestions"][0]["candidates"] == list(reversed(snapshots[-1]["suggestions"][0]["candidates"])),
                        "candidate order mutation must change actual raw suggestion")
            try:
                compare_transfer_snapshot(snapshots[-1], actual)
            except HarnessFailure as exc:
                failure = str(exc)
            else:
                raise HarnessFailure("actual SQL semantic mutation escaped comparator: "+control)
            row = {"control": control, "hits": hits, "rejected": True, "assertion": failure,
                   "source_count": len(cases), "oracle": snapshots[-1], "mutated_sql": actual}
            write_new(output / (control+"-control.json"), row)
            evidence.append({key: row[key] for key in ("control", "hits", "rejected", "assertion", "source_count")})
    return evidence


def transfer_graph_scenarios():
    scenarios = {}
    def leg(identifier, index, amount, day):
        return transfer_case(identifier, "Graph", "Leg", str(700000100000+index), [amount],
                             descriptions=["synthetic graph leg"], dates=["2024-02-"+day])
    scenarios["transitive-bridge-chain"] = [leg("chain-d"+str(i), i, "10.00", day)
        for i,day in enumerate(("01", "05", "09"))] + [leg("chain-s"+str(i), i+3, "-10.00", day)
        for i,day in enumerate(("01", "05", "09"))]
    scenarios["disconnected-global-source-order"] = [leg("component-d1", 11, "10.00", "17"),
        leg("component-d2", 12, "20.00", "17"),
        transfer_case("component-sources", "Graph", "Leg", "700000100013", ["-20.00", "-10.00"],
                      descriptions=["synthetic graph twenty", "synthetic graph ten"])]
    scenarios["duplicate-occurrence-source-order"] = [
        transfer_case("duplicate-sources", "Alpha", "A", "100000001111", ["-10.00", "-10.00"],
                      descriptions=["synthetic repeated payment", "synthetic repeated payment"]),
        transfer_case("duplicate-destination", "Gamma", "B", "200000002222", ["10.00"], descriptions=["synthetic incoming"])]
    for size in (4, 8):
        scenarios["genuine-component-growth-"+str(size)] = [leg("grown-s"+str(i), 20+i, "-10.00", "17") for i in range(size)] + [leg("grown-d", 40, "10.00", "17")]
    for size in (1, 3):
        owners = [transfer_case("token-owner-"+str(i), "Owner"+str(i), "Other", str(800000002222+10000*i), [], currency="EUR") for i in range(size)]
        scenarios["genuine-token-growth-"+str(size)] = owners + [transfer_case("owner-source", "Alpha", "A", "100000001111", ["-10.00"], descriptions=["synthetic payment to 2222"]),
            transfer_case("owner-destination", "Gamma", "B", "200000002222", ["10.00"], descriptions=["synthetic incoming"])]
    return scenarios


def run_transfer_graph_correctness(output):
    from viva.sql_authority import SQLAuthority
    evidence = []
    for name, cases in transfer_graph_scenarios().items():
        ledger, scans, snapshots = transfer_legacy_case(output / (name+"-oracle"), cases)
        with SQLAuthority.create(output / (name+"-sql"), secrets.token_urlsafe(48)) as store:
            for index, case in enumerate(cases):
                with legacy_traps(), guarded_sql(store):
                    result = store.ingest(case["original"], transfer_reader(case, []), contract=CONTRACT)
                require(result.status == "accepted", "graph fixture genuine admission: "+name)
                actual_snapshot = transfer_sql_snapshot(store)
                try:
                    compare_transfer_snapshot(snapshots[index], actual_snapshot)
                except HarnessFailure:
                    write_new(output / (name+"-failure.json"), {"scenario": name, "boundary": index, "expected": snapshots[index], "actual": actual_snapshot})
                    raise
            decisions = store.transfer_decisions()
            relevant_scans = [scan for scan in scans if scan["endpoints"]]
            for scan in scans:
                if not scan["endpoints"]:
                    require(not scan["assertions"] and not scan["graph"] and not scan["owners"], "empty full scan is inert")
            require(len(relevant_scans) == len(decisions), "graph fixture nonempty outer boundary count: "+name)
            for expected, actual in zip(relevant_scans, decisions):
                compare_transfer_decision(expected, actual["body"])
            last = scans[-1]
            transfer_source_mapping(ledger, store)
            if name == "transitive-bridge-chain":
                require(len(last["endpoints"]) == 6 and len(last["graph"]) == 3, "transitive closure includes remote rival")
            if name == "disconnected-global-source-order":
                keys = [row["body"]["a"] for row in last["assertions"]]
                require(len(keys) == 2 and keys == sorted(keys), "global source order spans disconnected components")
            store.verify(expected_head=store.head)
            evidence.append({"scenario": name, "sources": len(cases), "endpoints": len(last["endpoints"]),
                             "owners": len(last["owners"]), "edges": sum(len(values) for values in last["graph"].values()),
                             "boundaries": len(scans), "matched": True})
    write_new(output / "graph-correctness.json", evidence)
    return evidence


def transfer_empty_baseline_legacy(root, cases):
    """Lower-level accepted-source oracle: categories are never generated here."""
    from viva.ingest import RawStore
    from viva.ingest.statement_projector import post_statement
    from viva.ingest.transfers import link_transfers
    from viva.ledger import EventStore, Ledger
    from viva.ledger.events import document_captured, read_recorded, Provenance
    root.mkdir(mode=0o700)
    passphrase = secrets.token_urlsafe(48)
    ledger = Ledger(EventStore.open(root / "events.jsonl", passphrase))
    raw = RawStore.open(root / "originals", passphrase)
    snapshots = []
    for case in cases:
        doc = raw.put(case["original"])
        rr = transfer_reader(case, [])(raw.get(doc), doc)
        ledger.append(document_captured(doc, "synthetic.pdf", len(case["original"]), rr.doc_type, 1.0,
                                       "2024-03-01", Provenance(doc_id=doc)))
        ledger.append(read_recorded(doc, rr.model, rr.prompt_version, rr.input_mode, rr.raw_text,
                                    0.0, 0, 0, True, None, "2024-03-01", Provenance(doc_id=doc),
                                    resolved_model=rr.resolved_model, normalization_context=rr.normalization_context))
        result = post_statement(ledger, rr.facts)
        require(result.action == "posted", "empty-baseline actual source reconciliation")
        link_transfers(ledger, profile_for=lambda _movement: None)
        projection = ledger.projection()
        require(not projection._core._categories and not projection._core._merchant_categories,
                "lower-level source route must genuinely have no categories")
        snapshots.append(transfer_oracle_snapshot(ledger))
    return ledger, raw, snapshots


def run_transfer_manual_correctness(output):
    """Faithful Activity baseline and separate untouched-finalized predicate check."""
    from viva.sql_authority import SQLAuthority
    from viva.surface.activity import _current_classification, _transfer_state
    from viva.ledger.events import category_assigned
    from viva.sql_authority.schema import TABLES
    cases, new_owner = transfer_fixed_cases()
    ledger, raw, snapshots = transfer_empty_baseline_legacy(output / "manual-empty-oracle", cases)
    projection = ledger.projection()
    suggestions = projection.transfer_suggestions()
    require(len(suggestions) == 2 and all(len(row["candidates"]) == 1 for row in suggestions), "nonempty actionable manual fixture")
    a, other = [row["a"] for row in suggestions]
    b = suggestions[0]["candidates"][0]
    actions = [("confirm_transfer",a,b), ("confirm_transfer",a,b),
               ("unlink_transfer",a,b), ("unlink_transfer",a,b),
               ("reject_transfer",other,""), ("reject_transfer",other,"")]
    expected_actions = []
    for operation, left, right in actions:
        outcome = transfer_activity_action(ledger, operation, left, right)
        expected_actions.append((outcome, transfer_oracle_snapshot(ledger)))
    require([row[0] for row in expected_actions] == [True,False,True,False,True,False], "three positive Activity actions plus stale refusals")
    passphrase = secrets.token_urlsafe(48)
    with SQLAuthority.create(output / "manual-empty-sql", passphrase) as store:
        require(not any("categor" in name for name in TABLES), "SQL format has no admitted classification overlay family")
        for index, case in enumerate(cases):
            with legacy_traps(), guarded_sql(store):
                result = store.ingest(case["original"], transfer_reader(case, []), contract=CONTRACT)
            require(result.status == "accepted", "manual SQL accepted source baseline")
            compare_transfer_snapshot(snapshots[index], transfer_sql_snapshot(store))
        outcomes = []
        for (operation,left,right), (wanted, snapshot) in zip(actions, expected_actions):
            before_runs = len(store.transfer_decisions())
            with legacy_traps(), guarded_sql(store):
                kwargs = {"today": "2024-03-01"}
                result = (getattr(store,operation)(left, **kwargs) if operation == "reject_transfer"
                          else getattr(store,operation)(left,right,**kwargs))
            require(result == wanted, "actual Activity versus SQL manual outcome: "+operation)
            require(len(store.transfer_decisions()) == before_runs, "manual action must not invent automatic scan")
            compare_transfer_snapshot(snapshot, transfer_sql_snapshot(store))
            outcomes.append({"operation":operation,"completed":result})
        # A later genuine matcher boundary can relink. Its earlier effective
        # date must still fold after the manual assertions in source order.
        from viva.ingest.statement_projector import post_statement
        from viva.ingest.transfers import link_transfers
        from viva.ledger.events import document_captured, read_recorded, Provenance
        doc = raw.put(new_owner["original"])
        rr = transfer_reader(new_owner,[])(raw.get(doc),doc)
        ledger.append(document_captured(doc,"synthetic.pdf",len(new_owner["original"]),rr.doc_type,1.0,"2024-03-01",Provenance(doc_id=doc)))
        ledger.append(read_recorded(doc,rr.model,rr.prompt_version,rr.input_mode,rr.raw_text,0.0,0,0,True,None,"2024-03-01",Provenance(doc_id=doc),resolved_model=rr.resolved_model,normalization_context=rr.normalization_context))
        require(post_statement(ledger,rr.facts).action == "posted", "manual later source accepted")
        link_transfers(ledger,profile_for=lambda _movement:None)
        with legacy_traps(), guarded_sql(store):
            result = store.ingest(new_owner["original"],transfer_reader(new_owner,[]),contract=CONTRACT)
        require(result.status == "accepted", "manual next genuine SQL boundary")
        compare_transfer_snapshot(transfer_oracle_snapshot(ledger), transfer_sql_snapshot(store))
        require(len(store.transfer_links()) == 1 and store.transfer_links()[0]["grade"] == "corroborated", "source-order relink replaces verified grade")
        final, head = transfer_sql_snapshot(store), store.head
        store.verify(expected_head=head)
    with SQLAuthority.open(output / "manual-empty-sql", passphrase) as reopened:
        compare_transfer_snapshot(final, transfer_sql_snapshot(reopened))
        reopened.verify(expected_head=head)
    # Actual malformed classification is a separate negative Activity state.
    # No SQL eligibility bit, category row, or candidate expectation is injected.
    ledger2, _raw2, _snapshots2 = transfer_empty_baseline_legacy(output / "manual-invalid-classification", cases)
    movement = next(m for m in ledger2.projection().movements() if m.key == a)
    ledger2.append(category_assigned(a,movement.description,"", "verified", "2024-03-01",subcategory="orphan"))
    require(not _current_classification(ledger2.projection(),movement)["valid"], "actual invalid classification must be invalid")
    before = len(list(ledger2.store.events()))
    # The empty-baseline helper deliberately refuses to pretend this is empty.
    require(bool(ledger2.projection()._core._categories), "invalid classification is retained")
    require(not _current_classification(ledger2.projection(),movement)["valid"], "invalid category denies manual admission")
    require(len(list(ledger2.store.events())) == before, "invalid-classification predicate does not append")
    finalized, _scans, _snapshots = transfer_legacy_case(output / "manual-finalized-predicate", cases)
    require(bool(finalized.projection()._core._categories), "untouched full pipeline retains default categories")
    coherent = all(_current_classification(finalized.projection(),m)["valid"] for m in finalized.projection().movements())
    require(coherent, "actual finalized categories remain coherent")
    finalized_outcomes = []
    for operation,left,right in actions:
        p = finalized.projection(); m = next(item for item in p.movements() if item.key == left)
        state, allowed = _transfer_state(p,m,"en-US")
        admitted = _current_classification(p,m)["valid"] and operation in allowed
        if operation == "confirm_transfer":
            admitted = admitted and right in [item["id"] for item in state.get("candidates",[])]
        if operation == "unlink_transfer":
            admitted = admitted and right == state.get("counterpart",{}).get("id")
        if admitted:
            from viva.ingest import transfers as t
            original_today = t._today; t._today = lambda:"2024-03-01"
            try:
                if operation == "confirm_transfer":
                    admitted = t.confirm_transfer(finalized,left,right)
                else:
                    t.reject_transfer(finalized,left,right if operation == "unlink_transfer" else "")
            finally:
                t._today = original_today
        finalized_outcomes.append(bool(admitted))
    report = {"scope":"lower-level accepted-source/manual oracle; no full-pipeline classification parity claim",
              "actions":outcomes,"genuine_empty_legacy_classification":True,"sql_classification_family_absent":True,
              "invalid_classification_rejected":True,"finalized_pipeline_categories_retained":True,
              "separate_finalized_outcomes":finalized_outcomes,"historical_source_order_relink":True,"reopen":True}
    write_new(output / "manual-comparison.json",report)
    return report


def transfer_transport_controls(expected):
    """Exercise exact-field gates against a real independently matched snapshot."""
    controls = {}
    for name, field in (("movement identity", "key"), ("amount text", "amount"), ("currency", "currency"), ("date", "date")):
        actual = deepcopy(expected)
        actual["movements"][0][field] += "-altered"
        controls[name] = actual
    for name, field in (("grade", "grade"), ("rule", "decided_by")):
        actual = deepcopy(expected); actual["links"][0][field] = "altered"
        controls[name] = actual
    for name, operation in (("effective date", lambda row: row.update(occurred_at="2024-02-18")),
                            ("raw evidence", lambda row: row["body"]["evidence"].update(source_desc="altered")),
                            ("event provenance", lambda row: row["provenance"].update(note="altered"))):
        actual = deepcopy(expected); operation(actual["assertions"][-1]); controls[name] = actual
    actual = deepcopy(expected); actual["assertions"][0],actual["assertions"][1] = actual["assertions"][1],actual["assertions"][0]
    controls["assertion source order"] = actual
    actual = deepcopy(expected); actual["links"].append(deepcopy(actual["links"][0])); controls["consumed unique membership"] = actual
    actual = deepcopy(expected); actual["financial"]["inventory"][0]["source_order"] += 1; controls["account mapping source order"] = actual
    actual = deepcopy(expected); actual["financial"]["transactions"][0]["postings"][0]["grade"] = "unverified"; controls["source posting grade"] = actual
    proved = []
    for name, actual in controls.items():
        try:
            compare_transfer_snapshot(expected, actual)
        except HarnessFailure:
            proved.append(name)
        else:
            raise HarnessFailure("actual transport mutation escaped: "+name)
    return proved


class TransferOpaqueEntropy:
    """Public, predeclared identifier entropy; never used for cryptography."""
    def __init__(self, values):
        self.values, self.calls = tuple(values), []
    def token_hex(self, size):
        require(type(size) is int and size == 16, "opaque helper entropy size")
        require(len(self.calls) < len(self.values), "unexpected opaque helper entropy consumption")
        value = self.values[len(self.calls)]
        require(len(value) == 32 and all(char in "0123456789abcdef" for char in value), "predeclared opaque identifier entropy")
        self.calls.append({"ordinal":len(self.calls),"bytes":size,"value":value})
        return value


@contextmanager
def transfer_opaque_entropy(values, expected_calls):
    """Reuse the exact helper code with a private entropy-only globals view."""
    import marshal
    from types import FunctionType
    from viva.ledger import identity
    original = identity.opaque_account_key
    from viva import crypto
    actual_secrets, actual_token_hex = identity.secrets, secrets.token_hex
    actual_crypto = (crypto.os.urandom,crypto.seal,crypto.new_vault_header,secrets.token_bytes)
    entropy = TransferOpaqueEntropy(values)
    namespace = dict(original.__globals__)
    namespace["secrets"] = entropy
    controlled = FunctionType(original.__code__,namespace,original.__name__,original.__defaults__,original.__closure__)
    controlled.__module__, controlled.__qualname__ = original.__module__, original.__qualname__
    require(controlled.__code__ is original.__code__, "opaque helper exact code object")
    changes = []
    try:
        for module in tuple(sys.modules.values()):
            for name,value in tuple(getattr(module,"__dict__",{}).items()):
                if value is original:
                    changes.append((module,name)); setattr(module,name,controlled)
        require(changes, "opaque helper seam must be installed")
        evidence = {"helper_source_sha256":digest(Path(inspect.getfile(original)).read_bytes()),
                    "helper_code_sha256":digest(marshal.dumps(original.__code__)),
                    "predeclared_values":list(values),"calls":entropy.calls,
                    "aliases":[module.__name__+"."+name for module,name in changes]}
        require(identity.secrets is actual_secrets and secrets.token_hex is actual_token_hex and
                actual_crypto == (crypto.os.urandom,crypto.seal,crypto.new_vault_header,secrets.token_bytes),
                "opaque helper seam leaves cryptography unchanged throughout")
        yield evidence
        require(len(entropy.calls) == expected_calls, "opaque helper exact expected consumption")
    finally:
        # Restore aliases imported during the narrow fixture scope too.
        for module in tuple(sys.modules.values()):
            for name,value in tuple(getattr(module,"__dict__",{}).items()):
                if value is controlled:
                    setattr(module,name,original)
        require(identity.opaque_account_key is original and identity.secrets is actual_secrets
                and secrets.token_hex is actual_token_hex and
                actual_crypto == (crypto.os.urandom,crypto.seal,crypto.new_vault_header,secrets.token_bytes),
                "opaque seam restores helper and never changes real entropy")


def run_transfer_collision_correctness(output, *, reverse_sql_entropy=False):
    from viva.sql_authority import SQLAuthority
    # The stream is defined before either root exists, independently of outcomes.
    values = [digest(("synthetic-public-opaque-context:"+str(i)).encode())[:32] for i in range(2)]
    cases = [transfer_case("colliding-owner-"+str(i),"Owner","Other",str(800000002222+10000*i),[],currency="EUR") for i in range(3)]
    cases += [transfer_case("collision-source","Alpha","A","100000001111",["-10.00"],descriptions=["synthetic payment to 2222"]),
              transfer_case("collision-destination","Gamma","B","200000002222",["10.00"],descriptions=["synthetic incoming"])]
    with transfer_opaque_entropy(values,2) as legacy_entropy:
        ledger,scans,snapshots = transfer_legacy_case(output / "opaque-collision-oracle",cases)
    with SQLAuthority.create(output / "opaque-collision-sql",secrets.token_urlsafe(48)) as store:
        with transfer_opaque_entropy(list(reversed(values)) if reverse_sql_entropy else values,2) as sql_entropy:
            for index,case in enumerate(cases):
                with legacy_traps(),guarded_sql(store):
                    result = store.ingest(case["original"],transfer_reader(case,[]),contract=CONTRACT)
                require(result.status == "accepted", "controlled collision genuine source admission")
                compare_transfer_snapshot(snapshots[index],transfer_sql_snapshot(store))
        require(legacy_entropy["calls"] == sql_entropy["calls"], "identical controlled helper calls/order")
        transfer_source_mapping(ledger,store)
        decisions=store.transfer_decisions()
        relevant_scans=[scan for scan in scans if scan["endpoints"]]
        require(len(decisions)==len(relevant_scans), "collision actual nonempty boundary count")
        for expected,actual in zip(relevant_scans,decisions):
            compare_transfer_decision(expected,actual["body"])
        store.verify(expected_head=store.head)
        physical = store.transfer_inventory()
    report={"scope":"controlled nonsecret helper entropy collision correctness only; no qualifying randomness change",
            "sources":len(cases),"legacy_entropy":legacy_entropy,"sql_entropy":sql_entropy,
            "independent_source_bijections":True,"exact_assertion_candidate_order":True,"inventory":physical}
    write_new(output / "opaque-collision-correctness.json",report)
    return report


def transfer_financial_identity_bijection(expected, actual):
    """Match first admissions independently, retaining every source row order."""
    require(len(expected["inventory"]) == len(actual["inventory"]), "cross-root inventory multiplicity")
    left, right = {}, {}
    for index,(wanted,got) in enumerate(zip(expected["inventory"],actual["inventory"])):
        require({key:value for key,value in wanted.items() if key != "account"} ==
                {key:value for key,value in got.items() if key != "account"}, "cross-root immutable admission identity/order")
        require(wanted["account"] not in left and got["account"] not in right, "cross-root admission bijections")
        left[wanted["account"]],right[got["account"]] = "account-"+str(index),"account-"+str(index)
    def normalized(value,mapping):
        result=deepcopy(value)
        for row in result["inventory"]:
            row["account"]=mapping[row["account"]]
        for row in result["observations"]:
            row["account"]=mapping[row["account"]]
        result["observations"]=sorted_records(result["observations"])
        for transaction in result["transactions"]:
            for posting in transaction["postings"]:
                posting["account"]=mapping[posting["account"]]
        return result
    require(normalized(expected,left)==normalized(actual,right), "cross-root source financial parity under proved bijection")
    return {"legacy":left,"sql":right}


def retain_uncontrolled_collision_reproduction(output):
    """Retain the observed uncontrolled-identity mismatch without altering it."""
    from viva.sql_authority import SQLAuthority
    cases=[transfer_case("token-owner-"+str(i),"Owner","Other",str(800000002222+10000*i),[],currency="EUR") for i in range(3)]
    ledger,_scans,snapshots=transfer_legacy_case(output / "uncontrolled-collision-oracle",cases)
    failures=[]
    with SQLAuthority.create(output / "uncontrolled-collision-sql",secrets.token_urlsafe(48)) as store:
        for index,case in enumerate(cases):
            with legacy_traps(),guarded_sql(store):
                result=store.ingest(case["original"],transfer_reader(case,[]),contract=CONTRACT)
            require(result.status=="accepted", "uncontrolled collision source admission")
            actual=transfer_sql_snapshot(store)
            bijections=transfer_financial_identity_bijection(snapshots[index]["financial"],actual["financial"])
            try:
                compare_transfer_snapshot(snapshots[index],actual)
            except HarnessFailure as exc:
                failures.append({"boundary":index,"assertion":str(exc),"expected":snapshots[index],"actual":actual,"bijections":bijections})
    require(len(failures)==2, "uncontrolled preferred-key collisions produce distinct root-local IDs")
    report={"scope":"uncontrolled construction-failure reproduction, not a passing raw-identity comparison",
            "original_outcome":"pytest-1260 genuine-token-growth-3 failed financial observations at boundary1; original tool output retained, pytest temp snapshot subsequently expired",
            "cause":"unchanged opaque_account_key uses independent secrets.token_hex(16) after preferred-key collision",
            "source_financial_bijections_match":True,"raw_identity_comparator_rejects":True,"failures":failures}
    write_new(output / "uncontrolled-opaque-id-financial-comparison-failure.json",report)
    return {key:value for key,value in report.items() if key!="failures"}


def transfer_contract_identity():
    import ast
    root=Path(__file__).resolve().parents[1]
    frozen=root / "runs/sqlite-authority/frozen-accepted-v2-source/scripts/validate_sql_authority.py"
    require(digest(frozen.read_bytes()) == "972235b4f32c085d2b5e18ef541afba2a61edbad57477290cfe9fc9c56e4b54e", "accepted source driver identity")
    def functions(path):
        return {node.name:ast.dump(node,include_attributes=False) for node in ast.parse(path.read_text()).body if isinstance(node,ast.FunctionDef)}
    old,new=functions(frozen),functions(Path(__file__))
    require(all(old[name] == new[name] for name in TRANSFER_FROZEN_FUNCTIONS), "original seven fixture and gate ASTs unchanged")
    definition=root / "runs/sqlite-authority/transfer-factcheck/regression-fixture.json"
    require(digest(definition.read_bytes()) == TRANSFER_FIXTURE_SHA256, "exact approved transfer fixture definition")
    names=("docs/sql-authority-transfers.md", "runs/sqlite-authority/frozen-accepted-v2-source/manifest.json",
           "runs/sqlite-authority/transfer-factcheck/director-checkpoint1.md",
           "runs/sqlite-authority/transfer-factcheck/manual-baseline-construction-ruling.md",
           "runs/sqlite-authority/transfer-factcheck/opaque-id-comparison-ruling.md",
           "product/tests/test_sql_authority_transfer_comparison.py", "product/tests/test_sql_authority_transfer_mechanism.py")
    return {"files":{name:digest((root/name).read_bytes()) for name in names},
            "approved_owning_brief_sha256":"6365f04c5004845317c7ea598da21c3c379c67d91fac7acad9ca685872db37ec",
            "fixture_sha256":TRANSFER_FIXTURE_SHA256,"preserved_function_asts":list(TRANSFER_FROZEN_FUNCTIONS)}


def run_transfer_correctness(output):
    """Bounded synthetic correctness; never a composed or real-source packet."""
    from viva.sql_authority import SQLAuthority
    contract_identity=transfer_contract_identity()
    write_new(output / "transfer-contract-identity.json",contract_identity)
    cases, new_owner = transfer_fixed_cases()
    cases = cases + [new_owner]
    ledger, scans, snapshots = transfer_legacy_case(output / "transfer-legacy", cases)
    write_new(output / "transfer-inputs.json", fixture_identity(cases))
    calls, observations = [], []
    passphrase = secrets.token_urlsafe(48)
    with legacy_traps() as traps:
        with SQLAuthority.create(output / "transfer-sql", passphrase) as store:
            for index, case in enumerate(cases):
                # The normal path may not inspect/export a full history.
                with guarded_sql(store):
                    result = store.ingest(case["original"], transfer_reader(case, calls), contract=CONTRACT)
                require(result.status == "accepted", "transfer SQL source must accept")
                compare_transfer_snapshot(snapshots[index], transfer_sql_snapshot(store))
                require(store.original(result.doc_id) == case["original"], "transfer SQL original custody")
                if index == len(cases)-1:
                    observations.append(transfer_source_mapping(ledger, store))
            decisions = store.transfer_decisions()
            require(len(scans) == len(decisions), "transfer actual outer scan count")
            for expected, actual in zip(scans, decisions):
                compare_transfer_decision(expected, actual["body"])
            require(len(store.transfer_links()) == 1, "new zero-movement owner wakes decisive match")
            require(len(store.transfer_suggestions(stored=True)) == 1 and not store.transfer_suggestions(),
                    "linked sole candidate hides retained suggestion")
            mapping = observations[-1]
            final = transfer_sql_snapshot(store)
            head = store.head
            store.verify(expected_head=head)
        with SQLAuthority.open(output / "transfer-sql", passphrase) as reopened:
            compare_transfer_snapshot(final, transfer_sql_snapshot(reopened))
            require(mapping == transfer_source_mapping(ledger, reopened), "transfer reopened stable physical mapping")
            reopened.verify(expected_head=head)
    transport_controls = transfer_transport_controls(snapshots[-1])
    selection_controls = run_transfer_selection_controls(output)
    graph_scenarios = run_transfer_graph_correctness(output)
    manual = run_transfer_manual_correctness(output)
    collision = run_transfer_collision_correctness(output)
    uncontrolled_collision = retain_uncontrolled_collision_reproduction(output)
    require(contract_identity==transfer_contract_identity(), "transfer authority/fixture/test identities unchanged")
    return {"gates_passed": True, "contract_identity":contract_identity, "selection_controls": selection_controls, "transport_controls": transport_controls, "graph_scenarios": graph_scenarios, "manual": manual, "collision": collision, "uncontrolled_collision": uncontrolled_collision, "scope": "bounded synthetic transfer correctness only",
            "fixture": "transfer-fixed-closure-v3", "definition_sha256": TRANSFER_FIXTURE_SHA256,
            "source_count": len(cases), "boundary_count": len(scans), "legacy_traps": traps,
            "reopen": True, "automatic_link_count": 1}


def transfer_checkpoint_identity(root):
    require(root.is_dir() and not root.is_symlink(), "checkpoint canonical real directory")
    paths=list(sorted(root.rglob("*")))
    require(all(not path.is_symlink() and not path.stat().st_mode & 0o077 for path in [root]+paths), "checkpoint private modes and no links")
    require(not any(path.name.endswith(("-wal","-shm","-journal")) for path in paths), "closed checkpoint cannot omit pending SQL side files")
    files={str(path.relative_to(root)):digest(path.read_bytes()) for path in paths if path.is_file()}
    require("authority.db" in files and "authority.json" in files, "complete closed encrypted checkpoint")
    return files


def run_transfer_instrument(output):
    """Prequalification instrument admission with every failed control retained."""
    from viva.sql_authority import SQLAuthority
    contract_identity=transfer_contract_identity()
    write_new(output / "transfer-contract-identity.json",contract_identity)
    samples = {control: {100: [], 1000: []} for control in ("indexed", "old-global-selection")}
    details, checkpoints = [], []
    for population in (100, 1000):
        cases, new_owner = transfer_fixed_cases(population)
        ledger, scans, snapshots = transfer_legacy_case(output / f"oracle-{population}", cases+[new_owner], retain_boundaries=False)
        expected, expected_decision = snapshots[-1], scans[-1]
        checkpoint_root = output / f"checkpoint-{population}"
        passphrase = secrets.token_urlsafe(48)
        setup_started = time.perf_counter()
        with SQLAuthority.create(checkpoint_root, passphrase) as store:
            with legacy_traps(), normal_history_traps(store):
                for case in cases:
                    result = store.ingest(case["original"], transfer_reader(case, []), contract=CONTRACT)
                    require(result.status == "accepted", "instrument genuine setup admission")
            compare_transfer_snapshot(snapshots[-2], transfer_sql_snapshot(store))
            checkpoint_head = store.head
            store.verify(expected_head=checkpoint_head)
        identity = transfer_checkpoint_identity(checkpoint_root)
        setup_seconds = time.perf_counter()-setup_started
        checkpoints.append({"population":population,"head":checkpoint_head,"files":identity,
                            "setup_seconds":setup_seconds,"sources":len(cases)})
        write_new(output / f"checkpoint-{population}.json",checkpoints[-1])
        for control in samples:
            for repetition in range(20):
                root = output / f"{control}-{population}-{repetition:02d}"
                copy_started = time.perf_counter()
                shutil.copytree(checkpoint_root,root,copy_function=shutil.copy2)
                require(transfer_checkpoint_identity(root) == identity, "trusted closed encrypted checkpoint byte identity")
                with SQLAuthority.open(root,passphrase) as store:
                    require(store.head == checkpoint_head, "authenticated checkpoint head")
                    store.verify(expected_head=checkpoint_head)
                    copy_open_seconds = time.perf_counter()-copy_started
                    with legacy_traps(), normal_history_traps(store), transfer_vm(store) as meter:
                        history = transfer_consume_history(store) if control == "old-global-selection" else {}
                        result = store.ingest(new_owner["original"], transfer_reader(new_owner, []), contract=CONTRACT)
                    require(result.status == "accepted", "instrument genuine zero-movement admission")
                    require(meter.steps > 0, "positive whole-operation SQL steps")
                    compare_transfer_snapshot(expected, transfer_sql_snapshot(store))
                    compare_transfer_decision(expected_decision, store.transfer_decisions()[-1]["body"])
                    samples[control][population].append(meter.steps)
                    details.append({"population": population, "sample": repetition, "control": control,
                                    "vm_steps": meter.steps, "setup_seconds": setup_seconds,
                                    "checkpoint_copy_open_seconds":copy_open_seconds,
                                    "consumed_history": history, "plans": store.transfer_dependency_plans()})
                    write_new(output / f"sample-{control}-{population}-{repetition:02d}.json", details[-1])
    require(contract_identity==transfer_contract_identity(), "transfer instrument authority/fixture/test identities unchanged")
    indexed = transfer_growth_gate(samples["indexed"])
    bad = transfer_growth_gate(samples["old-global-selection"])
    admitted = indexed["gates_passed"] and not bad["gates_passed"]
    report = {"gates_passed": admitted, "scope": "instrument admission only; no qualifying composed result",
              "fixture": "transfer-fixed-closure-v3", "definition_sha256": TRANSFER_FIXTURE_SHA256,
              "samples": samples, "indexed": indexed, "old_global_selection": bad,
              "negative_control_rejected": not bad["gates_passed"], "details": details,
              "authenticated_checkpoints":checkpoints}
    write_new(output / "instrument-admission.json", report)
    return report


def worker(args):
    root = Path(__file__).resolve().parents[1]
    output = Path(args.output)
    dependencies = Path(args.dependencies)
    sys.path[:0] = [str(root / name) for name in ("product", "core", "merchant", "bench")] + [str(dependencies)]
    before = source_identity(root)
    write_new(output / "source-before.json", before)
    started = time.perf_counter()
    result = {"mode": args.mode, "status": "failed", "isolation_passed": False,
              "full_794_parity": False, "packaged_readiness": False}
    exit_code = 1
    runtime_before, runtime_after_saved = None, False
    try:
        require(Path.cwd() == output / "isolation" / "cwd", "isolated working directory")
        require(Path.home() == output / "isolation" / "home", "disposable HOME")
        require(Path(os.environ["TMPDIR"]) == output / "isolation" / "tmp", "sibling TMPDIR")
        require((Path.cwd() / ".env").read_bytes() == b"", "blank dotenv")
        require(set(os.environ) <= {"HOME", "TMPDIR", "PATH", "LANG", "LC_ALL", "LC_CTYPE",
                "PYTHONDONTWRITEBYTECODE", "PYTHONNOUSERSITE", "__CF_USER_TEXT_ENCODING"}, "blank environment")
        write_new(output / "isolation.json", {"blank_environment": True, "dotenv_bytes": 0,
                  "sibling_home_and_tmp": True, "network_forbidden": True,
                  "isolated_python": bool(sys.flags.isolated and sys.flags.no_site),
                  "dependency_directory_sha256": digest(str(dependencies).encode()), "mode": args.mode,
                  "driver_sha256": before["files"]["scripts/validate_sql_authority.py"]})
        block_network()
        restrict_files(root, output, dependencies)
        result["isolation_negative_controls"] = isolation_controls(root)
        result["isolation_passed"] = True
        runtime_before = runtime_identity(dependencies, include_pdf=args.mode.startswith(("source", "transfer-")))
        write_new(output / "runtime-before.json", runtime_before)
        if args.mode == "parity":
            result["evidence"] = run_parity(output)
        elif args.mode == "source":
            result["evidence"] = run_curated_source(output)
        elif args.mode == "transfer-correctness":
            result["evidence"] = run_transfer_correctness(output)
        elif args.mode == "transfer-instrument":
            result["evidence"] = run_transfer_instrument(output)
        elif args.mode == "source-correctness":
            result["evidence"] = run_source_correctness(output)
        else:
            result["evidence"] = run_scale(output)
        runtime_after = runtime_identity(dependencies, include_pdf=args.mode.startswith(("source", "transfer-")))
        write_new(output / "runtime-after.json", runtime_after)
        runtime_after_saved = True
        require(runtime_before == runtime_after, "runtime dependencies unchanged")
        result["runtime_stable"] = True
        result["status"] = "passed" if args.mode == "parity" or result["evidence"]["gates_passed"] else "failed"
        exit_code = int(result["status"] != "passed")
    except BaseException as exc:
        # Exceptions from a crypto/backend edge must never print arguments,
        # which might include a disposable credential or decoded evidence.
        result["error_type"] = type(exc).__name__
        if type(exc) is HarnessFailure:
            result["assertion"] = str(exc)
        result["trace"] = [{"file": Path(frame.filename).name, "line": frame.lineno, "function": frame.name}
                           for frame in traceback.extract_tb(exc.__traceback__)]
    finally:
        if runtime_before is not None and not runtime_after_saved:
            try:
                runtime_after = runtime_identity(dependencies, include_pdf=args.mode.startswith(("source", "transfer-")))
                write_new(output / "runtime-after.json", runtime_after)
                result["runtime_stable"] = runtime_before == runtime_after
            except BaseException as exc:
                result["runtime_after_error_type"] = type(exc).__name__
        after = source_identity(root)
        write_new(output / "source-after.json", after)
        result["source_stable"] = before == after
        if before != after or result.get("runtime_stable") is False:
            result["status"] = "invalid_source_changed"
            exit_code = 1
        result["elapsed_seconds"] = time.perf_counter() - started
        write_new(output / "result.json", result)
    print(json.dumps({"status": result["status"], "mode": args.mode, "source_stable": result["source_stable"]}))
    return exit_code


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("parity", "scale", "source", "source-correctness", "transfer-correctness", "transfer-instrument"), required=True)
    parser.add_argument("--output", required=True, help="new canonical absolute directory; must not exist")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--dependencies", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        return worker(args)
    root = Path(__file__).resolve().parents[1]
    output = Path(args.output)
    require(output.is_absolute() and output == output.resolve(), "output must be canonical absolute path")
    require(not output.exists() and not output.is_symlink(), "output must be new")
    require(output.parent.is_dir(), "output parent must exist")
    output.mkdir(mode=0o700)
    for relative in ("isolation", "isolation/home", "isolation/tmp", "isolation/cwd"):
        (output / relative).mkdir(mode=0o700)
    (output / "isolation/cwd/.env").touch(mode=0o600, exist_ok=False)
    interpreter = Path("/private/tmp/orionviva-source-verifier-runtime-v2/bin/python") if args.mode.startswith("transfer-") else root / ".venv/bin/python"
    dependencies = (Path("/Users/vishnu/orionviva/.venv/lib/python3.13/site-packages") if args.mode.startswith("transfer-") else root / ".venv/lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages").resolve()
    require(interpreter.is_file() and dependencies.is_dir(), "candidate virtualenv required")
    environment = {"HOME": str(output / "isolation/home"), "TMPDIR": str(output / "isolation/tmp"),
                   "PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8",
                   "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1"}
    command = [str(interpreter), "-I", "-S", "-B", str(Path(__file__).resolve()),
               "--worker", "--mode", args.mode, "--output", str(output), "--dependencies", str(dependencies)]
    with (output / "worker.log").open("xb") as log:
        completed = subprocess.run(command, cwd=output / "isolation/cwd", env=environment,
                                   stdout=log, stderr=subprocess.STDOUT, check=False)
    print(json.dumps({"mode": args.mode, "exit_code": completed.returncode,
                      "result": str(output / "result.json")}))
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
