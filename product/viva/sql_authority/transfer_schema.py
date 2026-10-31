"""Closed encrypted transfer storage protocols."""
from datetime import date
from decimal import Decimal, InvalidOperation
import json

TABLES = {
    "transfer_inventory": ("account", "kind", "currency", "institution", "number", "name", "source_doc", "source_order"),
    "transfer_bindings": ("movement", "account", "physical_account", "txn_id", "doc_id", "page", "date", "amount", "description", "occurrence", "source_order"),
    "transfer_tokens": ("token", "account"),
    "transfer_endpoints": ("movement", "account", "currency", "magnitude", "flow", "date", "active"),
    "transfer_edges": ("a", "b"),
    "transfer_dirty": ("movement", "active"),
    "transfer_runs": ("run_id", "boundary", "body"),
    "transfer_assertions": ("ordinal", "event_type", "occurred_at", "body", "provenance", "boundary", "run_id"),
    "transfer_pairs": ("a", "b", "status", "grade", "by", "decided_by", "resident"),
    "transfer_members": ("movement", "a", "b", "active"),
    "transfer_suggestions": ("a", "body", "active", "resident"),
}
KEYS = {name: columns[:1] for name, columns in TABLES.items()}
KEYS.update(transfer_tokens=("token", "account"), transfer_edges=("a", "b"), transfer_pairs=("a", "b"))
MUTABLE = frozenset({"transfer_endpoints", "transfer_dirty", "transfer_pairs", "transfer_members", "transfer_suggestions"})
DDL = """
CREATE TABLE transfer_inventory(account TEXT PRIMARY KEY, kind TEXT NOT NULL, currency TEXT NOT NULL, institution TEXT NOT NULL, number TEXT NOT NULL, name TEXT NOT NULL, source_doc TEXT NOT NULL REFERENCES documents, source_order INTEGER UNIQUE NOT NULL CHECK(source_order>0));
CREATE TABLE transfer_bindings(movement TEXT PRIMARY KEY, account TEXT NOT NULL REFERENCES transfer_inventory, physical_account TEXT NOT NULL REFERENCES accounts, txn_id TEXT UNIQUE NOT NULL REFERENCES transactions, doc_id TEXT NOT NULL REFERENCES documents, page INTEGER, date TEXT NOT NULL, amount TEXT NOT NULL, description TEXT NOT NULL, occurrence INTEGER NOT NULL CHECK(occurrence>=0), source_order INTEGER UNIQUE NOT NULL CHECK(source_order>0));
CREATE INDEX transfer_binding_order ON transfer_bindings(account,date,description,amount,source_order);
CREATE INDEX transfer_binding_document ON transfer_bindings(doc_id,source_order);
CREATE TABLE transfer_tokens(token TEXT NOT NULL, account TEXT NOT NULL REFERENCES transfer_inventory, PRIMARY KEY(token,account));
CREATE INDEX transfer_token_account ON transfer_tokens(account,token);
CREATE TABLE transfer_endpoints(movement TEXT PRIMARY KEY REFERENCES transfer_bindings, account TEXT NOT NULL REFERENCES transfer_inventory, currency TEXT NOT NULL, magnitude TEXT NOT NULL, flow TEXT NOT NULL CHECK(flow IN('source','destination','neither')), date TEXT NOT NULL, active INTEGER NOT NULL CHECK(active IN(0,1)));
CREATE INDEX transfer_endpoint_match ON transfer_endpoints(currency,magnitude,flow,date,movement);
CREATE INDEX transfer_endpoint_account ON transfer_endpoints(account,active,movement);
CREATE TABLE transfer_edges(a TEXT NOT NULL REFERENCES transfer_endpoints, b TEXT NOT NULL REFERENCES transfer_endpoints, PRIMARY KEY(a,b), CHECK(a!=b));
CREATE INDEX transfer_edge_reverse ON transfer_edges(b,a);
CREATE TABLE transfer_dirty(movement TEXT PRIMARY KEY REFERENCES transfer_endpoints, active INTEGER NOT NULL CHECK(active IN(0,1)));
CREATE INDEX transfer_dirty_active ON transfer_dirty(active,movement);
CREATE TABLE transfer_runs(run_id TEXT PRIMARY KEY, boundary TEXT NOT NULL REFERENCES documents, body TEXT NOT NULL);
CREATE TABLE transfer_assertions(ordinal INTEGER PRIMARY KEY CHECK(ordinal>0), event_type TEXT NOT NULL CHECK(event_type IN('TransferLinked','TransferSuggested','TransferUnlinked')), occurred_at TEXT NOT NULL, body TEXT NOT NULL, provenance TEXT NOT NULL, boundary TEXT NOT NULL REFERENCES documents, run_id TEXT NOT NULL);
CREATE TABLE transfer_pairs(a TEXT NOT NULL, b TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN('linked','unlinked')), grade TEXT NOT NULL, by TEXT NOT NULL, decided_by TEXT NOT NULL, resident INTEGER UNIQUE NOT NULL CHECK(resident>0), PRIMARY KEY(a,b), CHECK(a<b));
CREATE TABLE transfer_members(movement TEXT PRIMARY KEY REFERENCES transfer_endpoints, a TEXT NOT NULL, b TEXT NOT NULL, active INTEGER NOT NULL CHECK(active IN(0,1)), FOREIGN KEY(a,b) REFERENCES transfer_pairs(a,b));
CREATE INDEX transfer_member_pair ON transfer_members(a,b,active,movement);
CREATE TABLE transfer_suggestions(a TEXT PRIMARY KEY REFERENCES transfer_endpoints, body TEXT NOT NULL, active INTEGER NOT NULL CHECK(active IN(0,1)), resident INTEGER NOT NULL CHECK(resident>0));
CREATE INDEX transfer_suggestion_resident ON transfer_suggestions(active,resident,a);
"""


def _text(value, limit=16384):
    return type(value) is str and len(value.encode("utf-8")) <= limit


def _integer(value, minimum=0):
    return type(value) is int and minimum <= value <= 2**63-1


def _date(value):
    try:
        return type(value) is str and date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


def _json(value):
    parsed = json.loads(value)
    if json.dumps(parsed,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False) != value:
        raise ValueError("noncanonical JSON")
    return parsed


def _keys(value, fields):
    return type(value) is dict and set(value) == set(fields)


def _digest(value):
    return type(value) is str and len(value)==64 and all(c in "0123456789abcdef" for c in value)


def _movement(value):
    if not _text(value) or not value:
        return False
    parts=value.split("|")
    if len(parts)<6 or not _digest(parts[0]) or not parts[1] or not _date(parts[2]):
        return False
    try:
        from .schema import supported_amount
        return supported_amount(Decimal(parts[3])) and parts[-1].isascii() and parts[-1].isdigit() and len(parts[-1])<20
    except InvalidOperation:
        return False


def valid_context(value):
    if not _keys(value,{"files","python","sha256"}) or not _digest(value["sha256"]):
        return False
    files=value["files"]
    if type(files) is not dict or not files or len(files)>10000 or not all(_text(k,1024) and bool(k) and not k.startswith("/") and _digest(v) for k,v in files.items()):
        return False
    py=value["python"]
    if not _keys(py,{"implementation","cache_tag","version","build"}) or not all(_text(py[k]) and bool(py[k]) for k in ("implementation","cache_tag","build")):
        return False
    version=py["version"]
    return (type(version) is list and len(version)==5 and all(_integer(version[i]) for i in (0,1,2,4)) and version[3] in {"alpha","beta","candidate","final"})


def valid_evidence(value):
    if not _keys(value, {"verdict", "amount", "currency", "days_apart", "source", "destination", "decided_by", "source_desc", "destination_desc"}):
        return False
    if not all(_text(item) for key,item in value.items() if key!="days_apart") or not _integer(value["days_apart"]) or value["days_apart"]>5:
        return False
    try:
        from .schema import supported_amount
        return (value["verdict"] in {"decisive","suggested"} and supported_amount(Decimal(value["amount"]))
            and Decimal(value["amount"])>0 and len(value["currency"])==3 and value["currency"].isascii() and value["currency"].isalpha()
            and value["decided_by"] in {"","printed_date","account_ref_slot","account_ref_slot+printed_date","named_account","named_account+printed_date"})
    except InvalidOperation:
        return False


def valid_body(kind, value):
    if kind == "TransferSuggested":
        return (_keys(value,{"a","candidates","evidence","status"}) and _movement(value["a"])
            and type(value["candidates"]) is list and len(value["candidates"])<=1000000
            and all(_movement(key) for key in value["candidates"])
            and value["status"]=="suggested" and valid_evidence(value["evidence"]))
    if kind == "TransferLinked":
        evidence=value.get("evidence") if type(value) is dict else None
        return (_keys(value,{"a","b","grade","evidence","by","status"})
            and all(_movement(value[key]) for key in ("a","b")) and value["a"]!=value["b"]
            and value["grade"] in {"verified","corroborated"} and value["by"] in {"human","auto"}
            and value["status"]=="linked" and (evidence=={"kind":"confirmed"} or valid_evidence(evidence)))
    return (_keys(value,{"a","b","by","status"}) and _movement(value["a"])
        and (value["b"]=="" or _movement(value["b"])) and value["a"]!=value["b"] and value["by"]=="human" and value["status"]=="unlinked")


def valid_transport(value):
    return (_keys(value,{"event_type","occurred_at","body","provenance"})
        and value["event_type"] in {"TransferLinked","TransferSuggested","TransferUnlinked"}
        and _date(value["occurred_at"]) and valid_body(value["event_type"],value["body"])
        and value["provenance"]=={"doc_id":"","page":None,"region":"","note":""})


def valid_run(value):
    if not _keys(value,{"context","endpoints","owners","graph","strength","why","verdicts","initial_open","assertions","admissions"}):
        return False
    if not valid_context(value["context"]):
        return False
    for name in ("endpoints","initial_open","admissions"):
        if type(value[name]) is not list or len(value[name])>1000000 or not all((_digest(key) if name=="admissions" else _movement(key)) for key in value[name]):
            return False
    if type(value["owners"]) is not list or len(value["owners"])>1000000:
        return False
    if not all(valid_row("transfer_inventory",row) for row in value["owners"]):
        return False
    if type(value["graph"]) is not dict or any(not _movement(key) or type(cands) is not list or len(cands)>1000000 or not all(_movement(c) for c in cands) for key,cands in value["graph"].items()):
        return False
    if type(value["verdicts"]) is not dict or not all(_movement(k) and _movement(v) for k,v in value["verdicts"].items()):
        return False
    for name,field in (("strength","score"),("why","rule")):
        if type(value[name]) is not list or len(value[name])>1000000:
            return False
        for row in value[name]:
            if not _keys(row,{"a","b",field}) or not _movement(row["a"]) or not _movement(row["b"]):
                return False
            if not (_integer(row[field]) and row[field]<=3 if field=="score" else _text(row[field])):
                return False
    return type(value["assertions"]) is list and len(value["assertions"])<=1000000 and all(valid_transport(row) for row in value["assertions"])


def valid_row(table,row):
    try:
        if table not in TABLES or not _keys(row,TABLES[table]):
            return False
        ints={"source_order","occurrence","active","resident","ordinal"}
        for key,value in row.items():
            if key=="page":
                if value is not None and (not _integer(value,1) or value>200):
                    return False
            elif key in ints:
                if not _integer(value,0 if key in {"occurrence","active"} else 1) or (key=="active" and value>1):
                    return False
            elif not _text(value,16*1024*1024 if key in {"body","provenance"} else 16384):
                return False
            elif key in {"date","occurred_at"} and not _date(value):
                return False
            elif key in {"amount","magnitude"}:
                from .schema import supported_amount
                if not supported_amount(Decimal(value)) or (key=="magnitude" and Decimal(value)<0):
                    return False
        for key in {"movement","a","b"}&set(row):
            if key in {"a","b"} and table=="transfer_pairs" and row[key]=="":
                continue
            if not _movement(row[key]):
                return False
        for key in {"doc_id","source_doc","txn_id","boundary"}&set(row):
            if not _digest(row[key]):
                return False
        if "run_id" in row and (row["run_id"]!="" or table=="transfer_runs"):
            if len(row["run_id"])!=32 or any(c not in "0123456789abcdef" for c in row["run_id"]):
                return False
        if table=="transfer_inventory":
            return row["kind"] in {"depository","liability",""} and bool(row["account"]) and (row["currency"]=="" if row["kind"]=="" else len(row["currency"])==3 and row["currency"].isascii() and row["currency"].isalpha())
        if table=="transfer_endpoints":
            return row["flow"] in {"source","destination","neither"} and len(row["currency"])==3 and row["currency"].isascii() and row["currency"].isalpha()
        if table=="transfer_bindings":
            return bool(row["account"]) and bool(row["physical_account"]) and Decimal(row["amount"])!=0
        if table=="transfer_tokens":
            return bool(row["token"]) and bool(row["account"])
        if table=="transfer_edges":
            return row["a"]!=row["b"]
        if table=="transfer_runs":
            return valid_run(_json(row["body"]))
        if table=="transfer_assertions":
            return valid_transport({key:_json(row[key]) if key in {"body","provenance"} else row[key] for key in ("event_type","occurred_at","body","provenance")})
        if table=="transfer_suggestions":
            return valid_body("TransferSuggested",_json(row["body"]))
        if table=="transfer_pairs":
            return row["a"]<row["b"] and row["status"] in {"linked","unlinked"} and row["grade"] in {"","verified","corroborated"} and row["by"] in {"","human","auto"}
        return True
    except (ValueError,TypeError,KeyError,RecursionError,UnicodeError,InvalidOperation):
        return False
