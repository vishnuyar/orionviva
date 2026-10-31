"""Closed rows and indexes for the isolated experimental authority."""

FORMAT = "viva-sql-authority-prototype-v3"
SCHEMA_VERSION = 3
TABLES = {
    "documents": ("doc_id", "byte_count", "contract"),
    "source_admissions": ("doc_id", "body"),
    "source_occurrences": ("doc_id", "line_index", "event_id", "date", "page", "raw"),
    "account_keys": ("account_id", "logical_key", "creation_order"),
    "holder_index": ("account_id", "normalized_name"),
    "reference_claims": ("claim_id", "account_id", "reference", "doc_id", "scope", "page", "identity_page_count", "claim_order"),
    "reference_views": ("account_id", "reference", "positive_claim_id", "history_claim_id"),
    "identity_decisions": ("decision_id", "doc_id", "body", "created_revision"),
    "read_contexts": ("context_id", "body"),
    "receipts": ("doc_id", "contract", "body", "facts_type", "facts", "capture_types"),
    "interpretations": ("doc_id", "facts_type", "facts", "context"),
    "staged_statements": ("doc_id", "identity", "kind", "currency", "opening_amount", "opening_date", "closing_amount", "closing_date"),
    "staged_lines": ("doc_id", "line_index", "date", "amount", "description", "page", "running_balance"),
    "items": ("doc_id", "state", "reason", "account_id", "revision"),
    "accounts": ("account_id", "identity", "kind", "currency", "number", "normalized_number", "institution", "label", "names", "earliest_amount", "earliest_date", "current_amount", "current_date"),
    "periods": ("account_id", "period_end", "doc_id", "opening_date", "opening_amount", "closing_amount"),
    "transactions": ("txn_id", "doc_id", "line_index", "account_id", "date", "description", "page", "amount", "source_reference", "counterparty_reference"),
    "postings": ("txn_id", "leg", "account_id", "amount", "grade", "currency", "doc_id", "page"),
    "balance_observations": ("observation_id", "doc_id", "account_id", "kind", "date", "amount", "page", "currency", "grade", "event_asserted"),
    "findings": ("doc_id", "code", "detail"),
    "dependencies": ("doc_id", "identity", "boundary_amount", "direction", "active"),
    "validation_runs": ("run_id", "doc_id", "state", "revision", "detail"),
}
KEYS = {table: columns[:1] for table, columns in TABLES.items()}
KEYS.update(source_occurrences=("doc_id", "line_index"), holder_index=("account_id", "normalized_name"),
            reference_views=("account_id", "reference"), staged_lines=("doc_id", "line_index"), periods=("account_id", "period_end"),
            postings=("txn_id", "leg"), findings=("doc_id", "code"),
            dependencies=("doc_id", "direction"))
MUTABLE = frozenset({"items", "accounts", "dependencies", "reference_views"})

DDL = """
CREATE TABLE format(version TEXT NOT NULL, schema_version INTEGER NOT NULL);
CREATE TABLE control(singleton INTEGER PRIMARY KEY CHECK(singleton=1), revision INTEGER NOT NULL, head TEXT NOT NULL, mac TEXT NOT NULL);
CREATE TABLE audit(sequence INTEGER PRIMARY KEY, previous_hash TEXT NOT NULL, envelope TEXT NOT NULL, record_hash TEXT UNIQUE NOT NULL);
CREATE TABLE commits(revision INTEGER PRIMARY KEY, head TEXT NOT NULL, mac TEXT NOT NULL);
CREATE TABLE documents(doc_id TEXT PRIMARY KEY, byte_count INTEGER NOT NULL, contract TEXT NOT NULL);
CREATE TABLE source_admissions(doc_id TEXT PRIMARY KEY REFERENCES documents, body TEXT NOT NULL);
CREATE TABLE source_occurrences(doc_id TEXT NOT NULL REFERENCES source_admissions, line_index INTEGER NOT NULL, event_id TEXT NOT NULL, date TEXT NOT NULL, page INTEGER NOT NULL, raw TEXT NOT NULL, PRIMARY KEY(doc_id,line_index));
CREATE TABLE account_keys(account_id TEXT PRIMARY KEY REFERENCES accounts, logical_key TEXT UNIQUE NOT NULL, creation_order INTEGER UNIQUE NOT NULL);
CREATE TABLE holder_index(account_id TEXT NOT NULL REFERENCES accounts, normalized_name TEXT NOT NULL, PRIMARY KEY(account_id,normalized_name));
CREATE TABLE reference_claims(claim_id TEXT PRIMARY KEY, account_id TEXT NOT NULL REFERENCES accounts, reference TEXT NOT NULL, doc_id TEXT NOT NULL REFERENCES documents, scope TEXT NOT NULL, page INTEGER, identity_page_count INTEGER, claim_order INTEGER NOT NULL);
CREATE TABLE reference_views(account_id TEXT NOT NULL REFERENCES accounts, reference TEXT NOT NULL, positive_claim_id TEXT NOT NULL, history_claim_id TEXT NOT NULL, PRIMARY KEY(account_id,reference));
CREATE TABLE identity_decisions(decision_id TEXT PRIMARY KEY, doc_id TEXT NOT NULL REFERENCES documents, body TEXT NOT NULL, created_revision INTEGER NOT NULL);
CREATE INDEX holder_name ON holder_index(normalized_name,account_id);
CREATE INDEX reference_value ON reference_views(reference,account_id);
CREATE INDEX identity_document ON identity_decisions(doc_id,created_revision DESC,decision_id DESC);
CREATE INDEX claims_account ON reference_claims(account_id,claim_order,claim_id);
CREATE TABLE read_contexts(context_id TEXT PRIMARY KEY, body TEXT NOT NULL);
CREATE TABLE receipts(doc_id TEXT PRIMARY KEY REFERENCES documents, contract TEXT NOT NULL, body TEXT NOT NULL, facts_type TEXT NOT NULL, facts TEXT NOT NULL, capture_types TEXT NOT NULL);
CREATE TABLE interpretations(doc_id TEXT PRIMARY KEY REFERENCES receipts, facts_type TEXT NOT NULL, facts TEXT NOT NULL, context TEXT NOT NULL);
CREATE TABLE staged_statements(doc_id TEXT PRIMARY KEY REFERENCES receipts, identity TEXT NOT NULL, kind TEXT NOT NULL, currency TEXT NOT NULL, opening_amount TEXT NOT NULL, opening_date TEXT NOT NULL, closing_amount TEXT NOT NULL, closing_date TEXT NOT NULL);
CREATE TABLE staged_lines(doc_id TEXT NOT NULL REFERENCES staged_statements, line_index INTEGER NOT NULL, date TEXT NOT NULL, amount TEXT NOT NULL, description TEXT NOT NULL, page INTEGER, running_balance TEXT, PRIMARY KEY(doc_id,line_index));
CREATE TABLE items(doc_id TEXT PRIMARY KEY REFERENCES documents, state TEXT NOT NULL, reason TEXT NOT NULL, account_id TEXT NOT NULL, revision INTEGER NOT NULL);
CREATE TABLE accounts(account_id TEXT PRIMARY KEY, identity TEXT UNIQUE NOT NULL, kind TEXT NOT NULL, currency TEXT NOT NULL, number TEXT NOT NULL, normalized_number TEXT NOT NULL, institution TEXT NOT NULL, label TEXT NOT NULL, names TEXT NOT NULL, earliest_amount TEXT NOT NULL, earliest_date TEXT NOT NULL, current_amount TEXT NOT NULL, current_date TEXT NOT NULL);
CREATE TABLE periods(account_id TEXT NOT NULL REFERENCES accounts, period_end TEXT NOT NULL, doc_id TEXT UNIQUE NOT NULL REFERENCES staged_statements, opening_date TEXT NOT NULL, opening_amount TEXT NOT NULL, closing_amount TEXT NOT NULL, PRIMARY KEY(account_id,period_end));
CREATE TABLE transactions(txn_id TEXT PRIMARY KEY, doc_id TEXT NOT NULL REFERENCES periods(doc_id), line_index INTEGER NOT NULL, account_id TEXT NOT NULL REFERENCES accounts, date TEXT NOT NULL, description TEXT NOT NULL, page INTEGER, amount TEXT NOT NULL, source_reference TEXT NOT NULL, counterparty_reference TEXT NOT NULL, UNIQUE(doc_id,line_index));
CREATE TABLE postings(txn_id TEXT NOT NULL REFERENCES transactions, leg INTEGER NOT NULL, account_id TEXT NOT NULL, amount TEXT NOT NULL, grade TEXT NOT NULL, currency TEXT NOT NULL, doc_id TEXT NOT NULL REFERENCES documents, page INTEGER, PRIMARY KEY(txn_id,leg));
CREATE TABLE balance_observations(observation_id TEXT PRIMARY KEY, doc_id TEXT NOT NULL REFERENCES documents, account_id TEXT NOT NULL REFERENCES accounts, kind TEXT NOT NULL, date TEXT NOT NULL, amount TEXT NOT NULL, page INTEGER, currency TEXT NOT NULL, grade TEXT NOT NULL, event_asserted INTEGER NOT NULL CHECK(event_asserted IN(0,1)));
CREATE TABLE findings(doc_id TEXT NOT NULL REFERENCES documents, code TEXT NOT NULL, detail TEXT NOT NULL, PRIMARY KEY(doc_id,code));
CREATE TABLE dependencies(doc_id TEXT NOT NULL REFERENCES documents, identity TEXT NOT NULL, boundary_amount TEXT NOT NULL, direction TEXT NOT NULL, active INTEGER NOT NULL CHECK(active IN (0,1)), PRIMARY KEY(doc_id,direction));
CREATE TABLE validation_runs(run_id TEXT PRIMARY KEY, doc_id TEXT NOT NULL REFERENCES documents, state TEXT NOT NULL, revision INTEGER NOT NULL, detail TEXT NOT NULL);
CREATE INDEX accounts_number ON accounts(kind,normalized_number);
CREATE INDEX transactions_account_date ON transactions(account_id,date,txn_id);
CREATE INDEX postings_document ON postings(doc_id,txn_id,leg);
CREATE INDEX dependencies_boundary ON dependencies(identity,boundary_amount,direction,active,doc_id);
CREATE INDEX items_state ON items(state,doc_id);
CREATE INDEX observations_document ON balance_observations(doc_id,kind);
CREATE INDEX observations_account_date ON balance_observations(account_id,date);
"""


from . import transfer_schema
TABLES.update(transfer_schema.TABLES)
KEYS.update(transfer_schema.KEYS)
MUTABLE = MUTABLE | transfer_schema.MUTABLE
DDL += transfer_schema.DDL


def supported_amount(value):
    """Bound exact arithmetic operands before exponent expansion or summation."""
    from decimal import Decimal
    return (type(value) is Decimal and value.is_finite()
            and len(value.as_tuple().digits) <= 24
            and value.as_tuple().exponent >= -8 and value.adjusted() <= 14)


def valid_row(table, row):
    """Validate the closed scalar protocol independently of SQLite coercion."""
    from datetime import date
    from decimal import Decimal, InvalidOperation
    import json

    if type(table) is not str or table not in TABLES or type(row) is not dict or set(row) != set(TABLES[table]):
        return False
    if table in transfer_schema.TABLES:
        return transfer_schema.valid_row(table, row)
    nullable = {"page", "running_balance", "identity_page_count"}
    integer_bounds = {"byte_count": (0, 50 * 1024 * 1024), "line_index": (0, 9999),
                      "creation_order": (1, 2 ** 63 - 1), "claim_order": (1, 2 ** 63 - 1), "created_revision": (1, 2 ** 63 - 1),
                      "event_asserted": (0, 1), "leg": (0, 1), "revision": (1, 2 ** 63 - 1), "active": (0, 1)}
    dates = {"date", "opening_date", "closing_date", "period_end", "earliest_date", "current_date"}
    amounts = {"amount", "opening_amount", "closing_amount", "running_balance", "earliest_amount", "current_amount", "boundary_amount"}
    enums = {
        ("items", "state"): {"captured", "read_uncertain", "staged", "pending", "unsupported", "accepted"},
        ("validation_runs", "state"): {"pending", "unsupported", "accepted"},
        ("staged_statements", "kind"): {"depository", "liability"},
        ("accounts", "kind"): {"depository", "liability"},
        ("balance_observations", "kind"): {"opening", "closing"},
        ("reference_claims", "scope"): {"account"},
        ("dependencies", "direction"): {"forward", "backward"},
        ("postings", "grade"): {"verified", "unverified"},
        ("balance_observations", "grade"): {"corroborated"},
        ("receipts", "facts_type"): {"balance", "curated", "unsupported"},
        ("interpretations", "facts_type"): {"balance", "invalid_balance", "invalid_reading", "contract_changed", "source_rejected", "unsupported"},
    }
    for column, value in row.items():
        if value is None:
            if column not in nullable:
                return False
            continue
        if column in {"page", "identity_page_count"}:
            if type(value) is not int or not 1 <= value <= 200:
                return False
            continue
        if column in integer_bounds:
            low, high = integer_bounds[column]
            if type(value) is not int or not low <= value <= high:
                return False
            continue
        limit = 8 * 1024 * 1024 if column in {"body", "facts", "names", "context"} else 4096
        if column in {"logical_key", "normalized_name"}:
            limit = 16384
        if column == "contract":
            limit = 256
        if not _text(value,limit):
            return False
        if column in {"claim_id", "positive_claim_id", "history_claim_id"}:
            if column != "claim_id" and value == "":
                continue
            if len(value) != 72 or not value.endswith(":account") or any(c not in "0123456789abcdef" for c in value[:64]):
                return False
        if column == "event_id" and (len(value) != 7 or value[0] != "E" or not value[1:].isascii() or not value[1:].isdigit()):
            return False
        if column == "contract" and not value:
            return False
        if column == "account_id" and table != "items" and not value:
            return False
        if column == "normalized_number" and value and (len(value) <= 4 or not value.isascii() or not value.isdigit()):
            return False
        if (table, column) in enums and value not in enums[table, column]:
            return False
        if column in {"doc_id", "txn_id", "identity", "run_id", "context_id", "decision_id"}:
            if column == "identity" and table == "staged_statements" and value == "":
                continue
            expected = 32 if column in {"run_id", "decision_id"} else 64
            if len(value) != expected or any(char not in "0123456789abcdef" for char in value):
                return False
        if column == "currency" and (len(value) != 3 or not value.isascii() or not value.isalpha()):
            return False
        if column in dates:
            try:
                if date.fromisoformat(value).isoformat() != value:
                    return False
            except ValueError:
                return False
        if column in amounts:
            try:
                if not value.isascii() or value != value.strip() or len(value) > 128 or not supported_amount(Decimal(value)):
                    return False
            except InvalidOperation:
                return False
        if column == "names":
            try:
                names = json.loads(value)
            except (ValueError, TypeError):
                return False
            if type(names) is not list or len(names) > 100 or any(type(name) is not str or len(name.encode()) > 4096 for name in names):
                return False
    if table in {"source_admissions","identity_decisions"}:
        try:
            body=json.loads(row["body"])
        except (ValueError,RecursionError):
            return False
        try:
            canonical_body=json.dumps(body,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False)
        except (ValueError,RecursionError,UnicodeError):
            return False
        if row["body"] != canonical_body:
            return False
        validator=valid_source_admission if table=="source_admissions" else valid_identity_decision
        if not validator(body):
            return False
    return True


def _text(value, limit=4096):
    if type(value) is not str:
        return False
    try:
        return len(value.encode()) <= limit
    except UnicodeError:
        return False


def _digest(value):
    return _text(value,64) and len(value)==64 and all(c in "0123456789abcdef" for c in value)


def _integer(value, low=0, high=2**63-1):
    return type(value) is int and low <= value <= high


def valid_source_admission(body):
    """Closed nested admission transport; ownership remains separately verified."""
    if type(body) is not dict or set(body) != {"document","reading_sha256","envelope_sha256","locale","currency","pack","acquisition","read_context_id"}:
        return False
    document, pack = body["document"],body["pack"]
    document_fields={"account_ref","doc_type","family","file","id","page_count","period_end","period_start","sha256"}
    if (type(document) is not dict or set(document)!=document_fields
            or not all(_text(document[key]) for key in document_fields-{"page_count"})
            or not _integer(document["page_count"],1,200) or not _digest(document["sha256"])):
        return False
    pack_fields={"document_count","manifest_sha256","reading_contract","readings_sha256","sample_version","source_event_count"}
    if (type(pack) is not dict or set(pack)!=pack_fields
            or not _integer(pack["document_count"],1,10000) or not _integer(pack["source_event_count"],0,1000000)
            or not all(_text(pack[key],256) for key in ("reading_contract","sample_version"))
            or not all(_digest(pack[key]) for key in ("manifest_sha256","readings_sha256"))):
        return False
    if not all(_digest(body[key]) for key in ("reading_sha256","envelope_sha256","read_context_id")):
        return False
    if not _text(body["locale"],80) or not _text(body["currency"],3):
        return False
    from ..acquisition import validate
    try:
        validate(body["acquisition"])
    except ValueError:
        return False
    return True


def valid_identity_decision(body):
    """Closed typed resolver result and instrumentation, without choosing policy."""
    if type(body) is not dict or set(body)!={"resolution","logical_to_physical","account_order","metrics","policy","input","physical_account","promoted"}:
        return False
    if body["policy"]!="source_reference" or type(body["promoted"]) is not bool or not _text(body["physical_account"]):
        return False
    resolution=body["resolution"]
    resolution_fields={"account_id","key","verdict","candidate","candidate_name","candidates","reason"}
    if (type(resolution) is not dict or set(resolution)!=resolution_fields
            or not all(_text(resolution[key],16384) for key in resolution_fields-{"candidates"})
            or resolution["verdict"] not in {"same","new","ambiguous"}
            or type(resolution["candidates"]) is not list or len(resolution["candidates"])>10000
            or not all(_text(value,16384) for value in resolution["candidates"])):
        return False
    mapping, order=body["logical_to_physical"],body["account_order"]
    if (type(mapping) is not dict or len(mapping)>10000
            or not all(_text(key,16384) and _text(value) for key,value in mapping.items())
            or type(order) is not list or len(order)>10000 or not all(_text(value,16384) for value in order)):
        return False
    metrics=body["metrics"]
    counts={"vm_instructions","rows_read","closure_accounts","distinct_references","witness_claims"}
    if (type(metrics) is not dict or set(metrics)!=counts|{"queries","plans"}
            or not all(_integer(metrics[key]) for key in counts)
            or type(metrics["queries"]) is not list or len(metrics["queries"])>100000
            or not all(_text(query,16384) for query in metrics["queries"])):
        return False
    plans=metrics["plans"]
    if type(plans) is not dict or set(plans)!={"reference","holder","preferred"}:
        return False
    for rows in plans.values():
        if type(rows) is not list or len(rows)>100 or any(type(row) is not list or len(row)!=4
            or not all(_integer(value) for value in row[:3]) or not _text(row[3],16384) for row in rows):
            return False
    from .reading import _facts_shape
    value=body["input"]
    if not _facts_shape(value,{"transactions":True,"decimals":True,"read_context_id":"0"*64}):
        return False
    from ..acquisition import validate
    try:
        validate(value["acquisition"])
    except ValueError:
        return False
    from ..ingest.statement import StatementFacts
    from .bank import valid_observations
    from decimal import InvalidOperation
    try:
        facts=StatementFacts.from_dict(value)
    except (ValueError,InvalidOperation):
        return False
    return value["doc_type_confidence"] is None and valid_observations(facts)
