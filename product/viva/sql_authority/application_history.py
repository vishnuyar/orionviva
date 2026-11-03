"""Closed sealed publication grammar and authenticated intent envelopes."""
import base64
import hashlib
import hmac
import json

from ..crypto import seal, open_sealed, VERSION
from .store import AuthorityError, IntegrityError, canonical, ZERO
from . import application_io as io


FORMAT = "viva-sql-application-v1"
ENGINE_FORMAT = "viva-sql-application-engine-v3"
MAX_SEQUENCE = 2 ** 63 - 1
BOUNDARY = {"root_id", "sequence", "head", "sql_revision", "sql_head"}
RECORD = {"version", "root_id", "sequence", "previous_hash", "kind", "operation_id",
          "sql_revision", "sql_head", "payload", "record_hash", "mac"}
ISSUED = {"version", "root_id", "operation_id", "kind", "prior_terminal", "prior_sql", "capture"}


def encoded(value):
    return canonical(value).encode("utf-8")


def digest(value):
    return hashlib.sha256(value).hexdigest()


def decode(data):
    def unique(pairs):
        result = {}
        for name, value in pairs:
            if name in result:
                raise IntegrityError("duplicate application protocol field")
            result[name] = value
        return result
    def nonfinite(_value):
        raise IntegrityError("nonfinite application protocol value")
    try:
        value = json.loads(data, object_pairs_hook=unique, parse_constant=nonfinite)
        raw = data.encode("utf-8") if type(data) is str else data
        if encoded(value) != raw:
            raise IntegrityError("noncanonical application protocol")
        return value
    except (ValueError, TypeError, UnicodeError) as error:
        raise IntegrityError("invalid application protocol") from error


def fields(value, names):
    if type(value) is not dict or set(value) != set(names):
        raise IntegrityError("unknown application protocol fields")
    return value


def hexadecimal(value):
    if type(value) is not str or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise IntegrityError("invalid application hexadecimal value")
    return value


def integer(value, minimum=0):
    if type(value) is not int or not minimum <= value <= MAX_SEQUENCE:
        raise IntegrityError("invalid application sequence")
    return value


def envelope(value):
    fields(value, {"v", "nonce", "ct"})
    if type(value["v"]) is not str or value["v"] != VERSION:
        raise IntegrityError("invalid sealed envelope version")
    for name, length in (("nonce", 12), ("ct", None)):
        if type(value[name]) is not str:
            raise IntegrityError("invalid sealed envelope encoding")
        try:
            raw = base64.b64decode(value[name], validate=True)
        except ValueError as error:
            raise IntegrityError("invalid sealed envelope encoding") from error
        if base64.b64encode(raw).decode("ascii") != value[name] or (length and len(raw) != length) or (name == "ct" and len(raw) < 16):
            raise IntegrityError("invalid sealed envelope length")
    return value


def boundary(value):
    fields(value, BOUNDARY)
    hexadecimal(value["root_id"])
    integer(value["sequence"], 1)
    hexadecimal(value["head"])
    integer(value["sql_revision"])
    hexadecimal(value["sql_head"])
    return value


def sql_boundary(value):
    fields(value, {"revision", "head"})
    integer(value["revision"])
    hexadecimal(value["head"])
    return value


def terminal_of(record):
    return {"root_id": record["root_id"], "sequence": record["sequence"],
            "head": record["record_hash"], "sql_revision": record["sql_revision"],
            "sql_head": record["sql_head"]}


def keys(key):
    return {name: hmac.digest(key, FORMAT.encode("ascii") + b"\0" + name.encode("ascii"), "sha256")
            for name in ("metadata", "history", "terminal", "intent", "payload")}


def mac(key, value):
    return hmac.digest(key, encoded(value), "sha256").hex()


def aad(record):
    return encoded([FORMAT, record["root_id"], record["sequence"], record["previous_hash"],
                    record["kind"], record["operation_id"], record["sql_revision"], record["sql_head"]])


def validate_issued(value, root_id):
    fields(value, ISSUED)
    if type(value["version"]) is not int or value["version"] != 1 or value["root_id"] != root_id:
        raise IntegrityError("invalid issued application identity")
    hexadecimal(value["operation_id"])
    sql_boundary(value["prior_sql"])
    if value["kind"] not in {"creation", "capture", "transaction"}:
        raise IntegrityError("invalid issued operation")
    if value["kind"] == "creation":
        if value["prior_terminal"] is not None or value["prior_sql"] != {"revision": 0, "head": ZERO}:
            raise IntegrityError("invalid creation boundary")
    else:
        prior = boundary(value["prior_terminal"])
        if prior["root_id"] != root_id or value["prior_sql"] != {
                "revision": prior["sql_revision"], "head": prior["sql_head"]}:
            raise IntegrityError("issued prior SQL differs")
    if value["kind"] == "capture":
        capture = fields(value["capture"], {"doc_id", "byte_count", "blob_name", "blob_sha256"})
        hexadecimal(capture["doc_id"])
        hexadecimal(capture["blob_sha256"])
        integer(capture["byte_count"])
        if capture["byte_count"] > 50 * 1024 * 1024 or capture["blob_name"] != "prepared-original.blob":
            raise IntegrityError("invalid capture binding")
    elif value["capture"] is not None:
        raise IntegrityError("unexpected issued capture")
    return value


class History:
    def __init__(self, root, root_id, key=None):
        self.root, self.root_id = root, hexadecimal(root_id)
        self.keys = keys(key) if key is not None else None

    def record(self, data, *, previous=None):
        record = fields(decode(data), RECORD)
        if type(record["version"]) is not int or record["version"] != 1 or record["root_id"] != self.root_id:
            raise IntegrityError("unknown application record identity")
        integer(record["sequence"], 1)
        integer(record["sql_revision"])
        for name in ("previous_hash", "operation_id", "sql_head", "record_hash", "mac"):
            hexadecimal(record[name])
        if record["kind"] not in {"genesis", "sql_commit", "custody", "noop", "interrupted_abort"}:
            raise IntegrityError("unknown application record kind")
        if type(record["payload"]) is not str:
            raise IntegrityError("invalid application payload")
        envelope(decode(record["payload"]))
        content = {name: item for name, item in record.items() if name not in {"record_hash", "mac"}}
        if digest(encoded(content)) != record["record_hash"]:
            raise IntegrityError("application history hash mismatch")
        if previous is None:
            if (record["sequence"], record["previous_hash"], record["kind"], record["sql_revision"], record["sql_head"]) != (1, ZERO, "genesis", 0, ZERO):
                raise IntegrityError("invalid application genesis")
        else:
            increment = 1 if record["kind"] == "sql_commit" else 0
            if (record["sequence"] != previous["sequence"] + 1 or record["previous_hash"] != previous["head"]
                    or record["kind"] == "genesis" or record["sql_revision"] != previous["sql_revision"] + increment
                    or (not increment and record["sql_head"] != previous["sql_head"])):
                raise IntegrityError("application publication continuity mismatch")
        if self.keys is not None:
            if not hmac.compare_digest(record["mac"], mac(self.keys["history"], [self.root_id, record["sequence"], record["record_hash"]])):
                raise IntegrityError("application record MAC differs")
            self.payload(record, previous=previous)
        return record

    def payload(self, record, *, previous):
        payload = fields(decode(open_sealed(self.keys["payload"], decode(record["payload"]), aad=aad(record))), {"issued", "body"})
        issued = validate_issued(payload["issued"], self.root_id)
        if issued["operation_id"] != record["operation_id"] or issued["prior_terminal"] != previous:
            raise IntegrityError("publication issued boundary differs")
        body, kind = payload["body"], record["kind"]
        if kind == "genesis":
            fields(body, {"metadata_sha256", "sql_metadata_sha256", "sql_format", "sql_schema_version", "schema_contract"})
            for name in ("metadata_sha256", "sql_metadata_sha256", "schema_contract"):
                hexadecimal(body[name])
            if issued["kind"] != "creation" or type(body["sql_format"]) is not str or type(body["sql_schema_version"]) is not int or (body["sql_format"], body["sql_schema_version"]) not in {("viva-sql-authority-prototype-v3", 3), ("viva-sql-authority-prototype-v4", 4), ("viva-sql-authority-prototype-v5", 5)}:
                raise IntegrityError("invalid genesis representation")
        elif kind == "sql_commit":
            fields(body, {"record", "commit"})
            row, commit = body["record"], body["commit"]
            if (issued["kind"] != "transaction" or type(row) is not list or len(row) != 4
                    or type(commit) is not list or len(commit) != 3
                    or type(row[0]) is not int or row[0] != record["sql_revision"]
                    or row[1] != issued["prior_sql"]["head"] or type(row[2]) is not str
                    or row[3] != digest(encoded(row[:3])) or row[3] != record["sql_head"]
                    or commit[:2] != [row[0], row[3]]):
                raise IntegrityError("sealed SQL operation boundary differs")
            hexadecimal(commit[2])
            envelope(decode(row[2]))
        elif kind == "custody":
            fields(body, {"doc_id", "byte_count", "blob_sha256"})
            if issued["kind"] != "capture" or body != {name: issued["capture"][name] for name in body}:
                raise IntegrityError("custody projection differs")
        elif kind == "noop":
            fields(body, {"intent_sha256"})
            if issued["kind"] != "transaction" or body["intent_sha256"] != digest(encoded(issued)):
                raise IntegrityError("noop issued binding differs")
        else:
            fields(body, {"intent_sha256", "interrupted_kind", "prepared_sha256", "superseded_publication"})
            if issued["kind"] == "creation" or body["interrupted_kind"] != issued["kind"] or body["intent_sha256"] != digest(encoded(issued)):
                raise IntegrityError("abort issued binding differs")
            original = body["superseded_publication"]
            if original is None:
                if body["prepared_sha256"] is not None:
                    raise IntegrityError("abort preparation missing")
            else:
                if type(original) is not str or digest(original.encode("utf-8")) != body["prepared_sha256"]:
                    raise IntegrityError("abort preparation differs")
                if fields(decode(original), RECORD)["kind"] == "interrupted_abort":
                    raise IntegrityError("recursive abort preparation")
                proposed = self.record(original, previous=previous)
                proposed_payload = self.payload(proposed, previous=previous)
                if proposed["kind"] == "interrupted_abort" or proposed_payload["issued"] != issued:
                    raise IntegrityError("recursive or foreign abort")
        return payload

    def make(self, issued, kind, body, sql_head):
        validate_issued(issued, self.root_id)
        prior = issued["prior_terminal"]
        sequence = 1 if prior is None else prior["sequence"] + 1
        integer(sequence, 1)
        record = dict(version=1, root_id=self.root_id, sequence=sequence,
                      previous_hash=ZERO if prior is None else prior["head"], kind=kind,
                      operation_id=issued["operation_id"], sql_revision=sql_head["revision"], sql_head=sql_head["head"])
        record["payload"] = canonical(seal(self.keys["payload"], encoded({"issued": issued, "body": body}), aad=aad(record)))
        record["record_hash"] = digest(encoded(record))
        record["mac"] = mac(self.keys["history"], [self.root_id, sequence, record["record_hash"]])
        data = encoded(record)
        self.record(data, previous=prior)
        return data

    def terminal_bytes(self, record):
        value = {"version": 1, **terminal_of(record)}
        value["mac"] = mac(self.keys["terminal"], value)
        return encoded(value)

    def terminal(self):
        value = fields(decode(io.read(self.root / "terminal.json")), BOUNDARY | {"version", "mac"})
        if type(value["version"]) is not int or value["version"] != 1:
            raise IntegrityError("invalid terminal version")
        public = boundary({name: value[name] for name in BOUNDARY})
        if public["root_id"] != self.root_id:
            raise IntegrityError("foreign terminal")
        hexadecimal(value["mac"])
        if self.keys is not None and not hmac.compare_digest(value["mac"], mac(self.keys["terminal"], {name: item for name, item in value.items() if name != "mac"})):
            raise IntegrityError("terminal MAC differs")
        return public

    def scan(self, *, expected=None, prefix=None, allow_terminal_lag=False):
        if expected is not None:
            boundary(expected)
        if prefix is not None:
            boundary(prefix)
        io.directory(self.root / "history")
        names = sorted(path.name for path in (self.root / "history").iterdir())
        previous, records, bodies = None, [], []
        for index, name in enumerate(names, 1):
            if name != f"{index:020d}.json":
                raise IntegrityError("history member missing, reordered or unknown")
            record = self.record(io.read(self.root / "history" / name), previous=previous)
            if self.keys is not None:
                bodies.append(self.payload(record, previous=previous))
            previous = terminal_of(record)
            records.append(record)
        if not records:
            raise io.RecoveryRequired("application genesis incomplete")
        terminal = self.terminal() if (self.root / "terminal.json").exists() else None
        if terminal is None and not allow_terminal_lag:
            raise io.RecoveryRequired("application terminal incomplete")
        if terminal != previous and not allow_terminal_lag:
            raise IntegrityError("application terminal differs from history")
        if expected is not None and previous != expected:
            raise IntegrityError("trusted final application boundary differs")
        if prefix is not None and (prefix["sequence"] > len(records) or terminal_of(records[prefix["sequence"] - 1]) != prefix):
            raise IntegrityError("observed application prefix lost")
        return previous, records, bodies

    def intent(self, issued, stage, prepared=None, superseded=None):
        validate_issued(issued, self.root_id)
        value = dict(version=1, root_id=self.root_id, operation_id=issued["operation_id"], stage=stage)
        inner = dict(issued=issued, prepared_name=None if prepared is None else prepared[0],
                     prepared_sha256=None if prepared is None else prepared[1],
                     superseded_name=None if superseded is None else superseded[0],
                     superseded_sha256=None if superseded is None else superseded[1])
        value["payload"] = canonical(seal(self.keys["payload"], encoded(inner), aad=encoded([FORMAT, 1, self.root_id, issued["operation_id"], stage])))
        value["mac"] = mac(self.keys["intent"], value)
        return encoded(value)

    def read_intent(self, data):
        value = fields(decode(data), {"version", "root_id", "operation_id", "stage", "payload", "mac"})
        if type(value["version"]) is not int or value["version"] != 1 or value["root_id"] != self.root_id or value["stage"] not in {"initial", "prepared", "abort_prepared", "published"}:
            raise IntegrityError("invalid intent identity or stage")
        hexadecimal(value["operation_id"])
        hexadecimal(value["mac"])
        if not hmac.compare_digest(value["mac"], mac(self.keys["intent"], {name: item for name, item in value.items() if name != "mac"})):
            raise IntegrityError("intent MAC differs")
        if type(value["payload"]) is not str:
            raise IntegrityError("invalid intent payload")
        inner = fields(decode(open_sealed(self.keys["payload"], envelope(decode(value["payload"])), aad=encoded([FORMAT, 1, self.root_id, value["operation_id"], value["stage"]]))), {"issued", "prepared_name", "prepared_sha256", "superseded_name", "superseded_sha256"})
        issued = validate_issued(inner["issued"], self.root_id)
        if issued["operation_id"] != value["operation_id"]:
            raise IntegrityError("intent operation differs")
        prepared = inner["prepared_name"]
        if value["stage"] == "initial":
            if any(inner[name] is not None for name in inner if name != "issued"):
                raise IntegrityError("unexpected initial preparation")
        else:
            if prepared not in {"prepared-publication.json", "prepared-abort.json"}:
                raise IntegrityError("unknown preparation name")
            hexadecimal(inner["prepared_sha256"])
            if value["stage"] == "prepared" and prepared != "prepared-publication.json":
                raise IntegrityError("prepared intent is not normal publication")
            if value["stage"] == "abort_prepared" and prepared != "prepared-abort.json":
                raise IntegrityError("abort intent is not abort preparation")
        if inner["superseded_name"] is not None:
            if prepared != "prepared-abort.json" or inner["superseded_name"] != "prepared-publication.json":
                raise IntegrityError("invalid superseded preparation")
            hexadecimal(inner["superseded_sha256"])
        elif inner["superseded_sha256"] is not None:
            raise IntegrityError("unexpected superseded digest")
        return value, inner
