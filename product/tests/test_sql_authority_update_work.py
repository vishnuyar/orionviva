"""Real authority updates retain constraints and bounded internal database work."""
from decimal import Decimal
import hashlib
import json
import secrets
import statistics

import pytest
from sqlcipher3 import dbapi2 as sql

from scripts.validate_sql_authority import CONTRACT, fixture, reader_for
from viva.crypto import open_sealed
from viva.sql_authority import SQLAuthority, IntegrityError
from viva.sql_authority.schema import TABLES, KEYS, MUTABLE
from viva.sql_authority.store import canonical

pytestmark = pytest.mark.production_kdf


class Population:
    def __init__(self):
        self.stores = {}
        self.credentials = {}
        self.accounts = {}

    def __repr__(self):
        return "<synthetic encrypted authority histories>"


@pytest.fixture(scope="module")
def populated(tmp_path_factory):
    result = Population()
    base = tmp_path_factory.mktemp("sql-update-work").resolve()
    try:
        for count in (100, 1000):
            phrase = secrets.token_urlsafe(32)
            store = SQLAuthority.create(base / str(count), phrase)
            result.stores[count] = store
            result.credentials[count] = phrase
            for index in range(count):
                case = fixture("checking_statement", index, namespace="update-regression")
                calls = []
                outcome = store.ingest(case["original"], reader_for(case, calls), contract=CONTRACT)
                assert outcome.status == "accepted" and len(calls) == 1
                result.accounts[count] = outcome.account_id
            assert store._db.execute("PRAGMA foreign_keys").fetchone() == (1,)
        yield result
    finally:
        for store in result.stores.values():
            store.close()
        result.credentials.clear()


def rows(store, table):
    columns = TABLES[table]
    selected = ",".join('"' + name + '"' for name in columns)
    return sorted(store._db.execute(f"SELECT {selected} FROM {table}").fetchall(), key=repr)


def children(store):
    return {name: rows(store, name) for name in
            ("periods", "transactions", "postings", "balance_observations")}


def measured_put(store, table, proposed):
    instructions = []
    statements = []
    counter = [0]
    def progress():
        counter[0] += 1
        return 0
    store._db.set_trace_callback(statements.append)
    store._db.set_progress_handler(progress, 1)
    try:
        store._put(table, proposed)
    finally:
        store._db.set_progress_handler(None, 0)
        store._db.set_trace_callback(None)
    instructions.append(counter[0])
    updates = [statement for statement in statements if statement.startswith("UPDATE " + table + " SET ")]
    assert len(updates) == 1
    return instructions[0], updates[0]


def test_actual_put_vm_work_stays_bounded_with_populated_child_history(populated, tmp_path):
    observations = []
    for count, store in populated.stores.items():
        account = store._row("accounts", "account_id=?", (populated.accounts[count],))
        before = children(store)
        assert len(before["periods"]) == count
        assert len(before["transactions"]) == 2 * count
        assert len(before["balance_observations"]) == 2 * count
        requested = {**account, "current_amount": str(Decimal(account["current_amount"]) + 1)}
        work, updates, plans = [], [], []
        for _ in range(5):
            with store._transaction():
                instructions, statement = measured_put(store, "accounts", requested)
                work.append(instructions)
                updates.append(statement)
                assert store._operations[-1] == {"table": "accounts", "row": requested}
                assert store._row("accounts", "account_id=?", (account["account_id"],)) == requested
                plans.append(store._db.execute("EXPLAIN " + statement).fetchall())
                store._put("accounts", account)
        assert children(store) == before
        assert store._row("accounts", "account_id=?", (account["account_id"],)) == account
        assert store._db.execute("PRAGMA foreign_key_check").fetchall() == []
        assert store.verify()["verified"]
        observations.append({"statements": count, "matching_child_rows": 5 * count,
            "sqlite": store._db.execute("SELECT sqlite_version()").fetchone()[0],
            "sqlcipher": store._db.execute("PRAGMA cipher_version").fetchone()[0],
            "vm_instructions": work, "median_vm_instructions": statistics.median(work),
            "actual_updates": updates, "update_plans": plans,
            "parent_and_children_preserved": True})
    ratio = observations[1]["median_vm_instructions"] / observations[0]["median_vm_instructions"]
    evidence = {"observations": observations, "larger_to_smaller_vm_ratio": ratio,
                "source_sha256": hashlib.sha256(__import__("pathlib").Path(__import__("viva.sql_authority.store", fromlist=["__file__"]).__file__).read_bytes()).hexdigest()}
    (tmp_path / "update-work-evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")
    assert all(observation["median_vm_instructions"] > 0 for observation in observations)
    assert ratio <= 2.0, evidence
    for observation in observations:
        for statement in observation["actual_updates"]:
            assignment, predicate = statement.split(" SET ", 1)[1].split(" WHERE ", 1)
            assert "account_id=" not in assignment
            assert predicate.startswith("account_id=")


def test_composite_mutable_keys_isolation_full_row_audit_and_reopen(populated):
    store = populated.stores[100]
    for index in (103, 106):
        case = fixture("checking_statement", index, namespace="update-composite")
        outcome = store.ingest(case["original"], reader_for(case, []), contract=CONTRACT)
        assert outcome.status == "pending" and outcome.reason == "chain_gap_or_overlap"
    dependencies = rows(store, "dependencies")
    target = dict(zip(TABLES["dependencies"], dependencies[0]))
    proposed = {**target, "active": 0}
    with store._transaction():
        _instructions, statement = measured_put(store, "dependencies", proposed)
        assert store._operations[-1] == {"table": "dependencies", "row": proposed}
    assignment, predicate = statement.split(" SET ", 1)[1].split(" WHERE ", 1)
    assert "doc_id=" not in assignment and "direction=" not in assignment
    assert "doc_id=" in predicate and " AND direction=" in predicate
    expected = [tuple(proposed[column] for column in TABLES["dependencies"]) if row == dependencies[0] else row for row in dependencies]
    assert rows(store, "dependencies") == sorted(expected, key=repr)
    exported = store.export_audit()
    sequence, previous, envelope, _digest = exported["records"][-1]
    payload = json.loads(open_sealed(store._audit_key, json.loads(envelope), aad=canonical([sequence, previous]).encode()))
    assert payload == {"version": 1, "operations": [{"table": "dependencies", "row": proposed}]}
    assert set(payload["operations"][0]["row"]) == set(TABLES["dependencies"])
    assert store.verify()["verified"]
    with SQLAuthority.open(store.root, populated.credentials[100]) as reopened:
        assert reopened.verify(expected_head=store.head)["verified"]
        assert rows(reopened, "dependencies") == sorted(expected, key=repr)


def test_noop_immutable_refusal_and_other_account_isolation(populated):
    store = populated.stores[1000]
    account = store._row("accounts", "account_id=?", (populated.accounts[1000],))
    before = store.head
    with store._transaction():
        store._put("accounts", dict(account))
        assert store._operations == []
    assert store.head == before
    document = dict(zip(TABLES["documents"], rows(store, "documents")[0]))
    with pytest.raises(IntegrityError, match="immutable"):
        with store._transaction():
            store._put("documents", {**document, "byte_count": document["byte_count"] + 1})
    assert store.head == before
    case = fixture("savings_statement", 0, namespace="update-isolation")
    other = store.ingest(case["original"], reader_for(case, []), contract=CONTRACT)
    assert other.status == "accepted" and other.account_id != account["account_id"]
    other_before = store._row("accounts", "account_id=?", (other.account_id,))
    children_before = children(store)
    with store._transaction():
        store._put("accounts", {**account, "current_amount": str(Decimal(account["current_amount"]) + 1)})
        store._put("accounts", account)
    assert store._row("accounts", "account_id=?", (other.account_id,)) == other_before
    assert children(store) == children_before
    assert store.verify()["verified"]


def test_real_foreign_keys_and_existing_mutable_nonkey_contract_remain_enforced(populated):
    store = populated.stores[100]
    assert all(set(TABLES[table]) - set(KEYS[table]) for table in MUTABLE)
    before = children(store)
    account = populated.accounts[100]
    with pytest.raises(sql.IntegrityError, match="FOREIGN KEY"):
        store._db.execute("UPDATE accounts SET account_id=? WHERE account_id=?", ("acct:synthetic-renamed", account))
    observation = dict(zip(TABLES["balance_observations"], rows(store, "balance_observations")[0]))
    orphan = {**observation, "observation_id": "synthetic-orphan", "account_id": "acct:synthetic-missing"}
    with pytest.raises(sql.IntegrityError, match="FOREIGN KEY"):
        store._db.execute("INSERT INTO balance_observations VALUES(?,?,?,?,?,?,?,?,?,?)", tuple(orphan[column] for column in TABLES["balance_observations"]))
    assert store._db.execute("PRAGMA foreign_keys").fetchone() == (1,)
    assert store._db.execute("PRAGMA foreign_key_check").fetchall() == []
    assert children(store) == before
    assert store.verify()["verified"]
