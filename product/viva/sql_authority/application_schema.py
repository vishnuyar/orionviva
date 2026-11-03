"""Software-owned exact SQL schema contract, independent of stored rows."""
import functools

from sqlcipher3 import dbapi2 as sql

from .schema import DDL
from .store import IntegrityError, canonical


def descriptor(db):
    objects = db.execute(
        "SELECT type,name,tbl_name,sql FROM sqlite_schema ORDER BY type,name"
    ).fetchall()
    details = []
    for kind, name, table, statement in objects:
        if kind not in {"table", "index"} or (statement and "VIRTUAL TABLE" in statement.upper()):
            raise IntegrityError("unexpected application schema object")
        quoted = '"' + name.replace('"', '""') + '"'
        entry = [kind, name, table, statement]
        if kind == "table":
            entry.extend([
                db.execute(f"PRAGMA table_xinfo({quoted})").fetchall(),
                db.execute(f"PRAGMA foreign_key_list({quoted})").fetchall(),
                db.execute(f"PRAGMA index_list({quoted})").fetchall(),
            ])
        else:
            entry.append(db.execute(f"PRAGMA index_xinfo({quoted})").fetchall())
        details.append(entry)
    return canonical(details)


@functools.lru_cache(maxsize=1)
def expected():
    db = sql.connect(":memory:", isolation_level=None)
    try:
        db.executescript(DDL)
        return descriptor(db)
    finally:
        db.close()


def verify(db):
    contract = expected()
    if descriptor(db) != contract:
        raise IntegrityError("application SQL schema differs from software contract")
    return contract
