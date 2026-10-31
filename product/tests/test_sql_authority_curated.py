"""Bounded pinned-source admissions and independent semantic integrity."""
import copy
import hashlib
import json
import secrets

import pytest

from viva.sql_authority import SQLAuthority, CuratedSource, AuthorityError, IntegrityError
from viva.sql_authority.store import canonical
from viva.sql_authority import curated

pytestmark = pytest.mark.production_kdf


@pytest.fixture(scope="module")
def source():
    return CuratedSource.open()


@pytest.fixture
def store(tmp_path):
    credential = secrets.token_urlsafe(32)
    with SQLAuthority.create(tmp_path.resolve()/"authority", credential) as opened:
        opened._test_credentials = lambda: credential
        yield opened


def member(source, doc_type="checking_statement", index=0):
    return [d for d in source.documents if d["doc_type"] == doc_type][index]


def accept(store, source, index=0):
    document = member(source, index=index)
    return store.ingest_curated(source.original(document["sha256"]), source)


def test_owner_detached_and_not_caller_constructible(source, store):
    docs = source.documents
    docs[0]["id"] = "forged"
    identity = source.identity
    identity["document_count"] = 1
    assert source.documents[0]["id"] != "forged"
    assert source.identity["document_count"] == 794
    with pytest.raises(AuthorityError):
        CuratedSource()
    with pytest.raises(AuthorityError):
        store.attach_curated(object.__new__(CuratedSource))
    with pytest.raises(AuthorityError):
        store.ingest_curated(b"not a pinned original", source)


def test_source_real_postings_receipt_occurrences_and_reopen(source, store):
    result = accept(store, source)
    assert result.status == "accepted"
    assert store.source_admission(result.doc_id)["pack"] == source.identity
    assert store.receipt(result.doc_id)["reading"]["facts"] is None
    assert len(store.source_transactions(result.doc_id)) == len(store.source_occurrences(result.doc_id)) > 0
    observations = store.source_observations(result.doc_id)
    assert all(type(row["event_asserted"]) is bool and row["event_asserted"] for row in observations)
    assert store.identity_decision(result.doc_id)["metrics"]["vm_instructions"] > 0
    assert all(store.last_source_timings[key] >= 0 for key in (
        "capture_seconds", "receipt_seconds", "source_validation_seconds", "parse_seconds",
        "interpretation_seconds", "settlement_seconds"))
    assert store.verify()["verified"]
    with SQLAuthority.open(store.root, store._test_credentials()) as reopened:
        with pytest.raises(IntegrityError, match="authenticated"):
            reopened.verify()
        reopened.attach_curated(CuratedSource.open())
        assert reopened.verify()["verified"]


def test_raw_receipt_precedes_parse_and_owner_required_for_resume(source, store, monkeypatch):
    def crash(point):
        if point == "after_raw_receipt":
            raise RuntimeError("interruption")
    store._fault = crash
    document = member(source)
    original = source.original(document["sha256"])
    monkeypatch.setattr(curated, "from_model_json", lambda *args: pytest.fail("parse before receipt"))
    with pytest.raises(RuntimeError, match="interruption"):
        store.ingest_curated(original, source)
    receipt = store.receipt(document["sha256"])
    assert receipt["reading"]["raw_text"] and receipt["reading"]["facts"] is None
    assert store.original(document["sha256"]) == original
    assert store._row("interpretations", "doc_id=?", (document["sha256"],)) is None
    monkeypatch.undo()
    with SQLAuthority.open(store.root, store._test_credentials()) as reopened:
        assert reopened.resume(document["sha256"]).status == "pending"
        assert reopened.receipt(document["sha256"]) == receipt
        reopened.attach_curated(CuratedSource.open())
        assert reopened.resume(document["sha256"]).status == "accepted"
        assert reopened.verify()["verified"]


def test_nonbalance_members_are_retained_and_refused(source, store):
    document = member(source, "pay_stub")
    outcome = store.ingest_curated(source.original(document["sha256"]), source)
    assert outcome.status == "unsupported" and outcome.reason == "unsupported_family"
    assert store.receipt(outcome.doc_id)["reading"]["raw_text"]
    assert store.postings(outcome.doc_id) == []
    assert store.verify()["verified"]


@pytest.mark.parametrize("exception", [ValueError, KeyError, TypeError, IndexError])
def test_bounded_source_parse_errors_hold_after_receipt(source, store, monkeypatch, exception):
    def malformed(*args):
        raise exception("malformed source envelope")
    monkeypatch.setattr(curated.curation, "decode_retained_input", malformed)
    outcome = accept(store, source)
    assert outcome.status == "pending" and outcome.reason == "source_admission_requires_review"
    assert store.receipt(outcome.doc_id)["reading"]["raw_text"]
    assert store.postings(outcome.doc_id) == []


def test_forward_source_opening_is_printed_only(source, store):
    first = accept(store, source, 0)
    second = accept(store, source, 1)
    assert first.status == second.status == "accepted"
    assert first.account_id == second.account_id
    values = {row["kind"]: row for row in store.source_observations(second.doc_id)}
    assert not values["opening"]["event_asserted"]
    assert values["closing"]["event_asserted"]
    assert store.verify()["verified"]


def reseal(store, replacements):
    from viva.crypto import open_sealed, seal
    exported = store.export_audit()
    previous = "0" * 64
    for sequence, old_previous, envelope, old_digest in exported["records"]:
        payload = json.loads(open_sealed(store._audit_key, json.loads(envelope),
            aad=canonical([sequence, old_previous]).encode()))
        for operation in payload["operations"]:
            table, row = operation["table"], operation["row"]
            for change_table, predicate, changed in replacements:
                if table == change_table and predicate(row):
                    operation["row"] = changed
        sealed = canonical(seal(store._audit_key, canonical(payload).encode(),
            aad=canonical([sequence, previous]).encode()))
        digest = hashlib.sha256(canonical([sequence, previous, sealed]).encode()).hexdigest()
        store._db.execute("UPDATE audit SET previous_hash=?,envelope=?,record_hash=? WHERE sequence=?",
            (previous, sealed, digest, sequence))
        store._db.execute("UPDATE commits SET head=?,mac=? WHERE revision=?", (digest, store._mac(sequence, digest), sequence))
        previous = digest
    store._db.execute("UPDATE control SET head=?,mac=?", (previous, store._mac(exported["revision"], previous)))
    # Explicitly prove the independent structural/keyed reconstruction passes.
    store._reconstruct(store.export_audit(), store.head)


@pytest.mark.parametrize("target", ["input", "physical", "order", "mapping", "claim", "view_and_decision"])
def test_keyed_wrong_semantics_still_rejected(source, store, target):
    first, second = accept(store, source, 0), accept(store, source, 1)
    assert second.status == "accepted"
    replacements = []
    if target == "claim":
        old = store._row("reference_claims", "claim_id=?", (first.doc_id + ":account",))
        changed = {**old, "page": 2}
        store._db.execute("UPDATE reference_claims SET page=2 WHERE claim_id=?", (old["claim_id"],))
        replacements.append(("reference_claims", lambda row: row["claim_id"] == old["claim_id"], changed))
    else:
        raw = store._read("SELECT decision_id,doc_id,body,created_revision FROM identity_decisions WHERE doc_id=?", (second.doc_id,))[0]
        decision_id, doc_id, body, revision = raw
        decision = json.loads(body)
        if target == "input":
            decision["input"]["source_account_ref"] = "INVENTED"
        elif target == "physical":
            decision["physical_account"] = "acct:sql:invented"
        elif target == "order":
            decision["account_order"] = []
        elif target == "mapping":
            decision["logical_to_physical"] = {}
        else:
            view = store._row("reference_views", "account_id=? AND reference=?", (first.account_id, store.receipt(first.doc_id)["facts"]["source_account_ref"]))
            changed_view = {**view, "positive_claim_id": ""}
            store._db.execute("UPDATE reference_views SET positive_claim_id='' WHERE account_id=?", (first.account_id,))
            replacements.append(("reference_views", lambda row: row["account_id"] == first.account_id, changed_view))
            decision["resolution"]["verdict"] = "new"
        changed = dict(decision_id=decision_id, doc_id=doc_id, body=canonical(decision), created_revision=revision)
        store._db.execute("UPDATE identity_decisions SET body=? WHERE decision_id=?", (changed["body"], decision_id))
        replacements.append(("identity_decisions", lambda row: row["decision_id"] == decision_id, changed))
    reseal(store, replacements)
    with pytest.raises(IntegrityError):
        store.verify()


def test_real_source_out_of_order_gap_uses_affected_boundary(source, store):
    newest = accept(store,source,2)
    gap = accept(store,source,0)
    assert newest.status == "accepted" and gap.status == "pending"
    assert store.identity_decision(gap.doc_id)["promoted"] is False
    assert store.postings(gap.doc_id) == []
    connector = accept(store,source,1)
    assert connector.status == "accepted"
    assert store.item(gap.doc_id)["state"] == "accepted"
    assert store.identity_decision(gap.doc_id)["promoted"] is True
    assert all("WHERE" in query for query in store.last_queries)
    assert any("boundary_amount=?" in query for query in store.last_queries)
    assert store.verify()["verified"]


@pytest.mark.parametrize("mutation", ["other_envelope", "cell", "page", "locale", "pin", "context", "metadata_rehashed", "parser_field", "occurrence", "direction", "currency", "malformed"])
def test_pinned_admission_rejects_rehashed_source_tampering(source, store, mutation):
    document = member(source)
    def crash(point):
        if point == "after_raw_receipt":
            raise RuntimeError("retained")
    store._fault = crash
    with pytest.raises(RuntimeError):
        store.ingest_curated(source.original(document["sha256"]),source)
    store._fault = lambda point: None
    receipt = store._row("receipts","doc_id=?",(document["sha256"],))
    admission = store._row("source_admissions","doc_id=?",(document["sha256"],))
    reading, admitted = json.loads(receipt["body"]),json.loads(admission["body"])
    envelope = json.loads(reading["raw_text"])
    if mutation == "other_envelope":
        other, _ = curated.issue(source,source.original(member(source,index=1)["sha256"]),member(source,index=1)["sha256"])
        reading["raw_text"] = other.raw_text
    elif mutation == "cell":
        envelope["source_cells"][0]["raw"] = "+999.00"
        reading["raw_text"] = canonical(envelope)
    elif mutation == "page":
        envelope["source_cells"][0]["page"] = 2
        reading["raw_text"] = canonical(envelope)
    elif mutation == "parser_field":
        envelope["parser_input"]["transactions"][0]["description"]="altered source description"
        reading["raw_text"]=canonical(envelope)
    elif mutation == "occurrence":
        envelope["source_event_ids"][0]="E999999"
        reading["raw_text"]=canonical(envelope)
    elif mutation == "direction":
        cell=envelope["source_cells"][0]
        cell["normalization"]="magnitude" if cell["normalization"]=="identity" else "identity"
        reading["raw_text"]=canonical(envelope)
    elif mutation == "currency":
        admitted["currency"]="EUR"
    elif mutation == "malformed":
        reading["raw_text"]="{malformed retained response"
    elif mutation == "locale":
        reading["source_locale"] = admitted["locale"] = "de-DE"
    elif mutation == "pin":
        admitted["pack"]["readings_sha256"] = "0"*64
    elif mutation == "context":
        admitted["read_context_id"] = "0"*64
    else:
        admitted["document"]["id"] = "foreign"
        admitted["reading_sha256"] = hashlib.sha256(canonical(admitted).encode()).hexdigest()
    admitted["envelope_sha256"] = hashlib.sha256(reading["raw_text"].encode()).hexdigest()
    changed_receipt = {**receipt,"body":canonical(reading)}
    changed_admission = {**admission,"body":canonical(admitted)}
    store._db.execute("UPDATE receipts SET body=? WHERE doc_id=?",(changed_receipt["body"],document["sha256"]))
    store._db.execute("UPDATE source_admissions SET body=? WHERE doc_id=?",(changed_admission["body"],document["sha256"]))
    reseal(store,[("receipts",lambda row:row["doc_id"]==document["sha256"],changed_receipt),
        ("source_admissions",lambda row:row["doc_id"]==document["sha256"],changed_admission)])
    outcome=store.resume(document["sha256"])
    assert outcome.status == "pending" and outcome.reason == "source_admission_requires_review"
    assert store.postings(outcome.doc_id) == []


def test_generic_acquisition_cannot_grant_source_authority(source,store):
    from viva.ingest.pipeline_models import ReadResult
    from viva.ingest.statement import StatementFacts
    accepted=accept(store,source)
    facts=StatementFacts.from_dict(store.receipt(accepted.doc_id)["facts"])
    def reader(original,doc_id):
        proposed=copy.deepcopy(facts)
        proposed.doc_id=doc_id
        proposed.acquisition["document_sha256"]=doc_id
        return ReadResult(proposed.doc_type,None,facts=proposed,acquisition=proposed.acquisition)
    outcome=store.ingest(b"synthetic unrelated original",reader,contract="synthetic-unit")
    assert outcome.status == "pending" and outcome.reason == "identity_requires_review"
    assert store.source_admission(outcome.doc_id) is None
    assert store.postings(outcome.doc_id) == []


def test_source_read_context_change_holds_without_history_or_parse(source,store,monkeypatch):
    document=member(source)
    def crash(point):
        if point=="after_raw_receipt":
            raise RuntimeError("retained")
    store._fault=crash
    with pytest.raises(RuntimeError):
        store.ingest_curated(source.original(document["sha256"]),source)
    store._fault=lambda point:None
    monkeypatch.setattr(store,"_implementation_identity",{**store._implementation_identity,"sha256":"0"*64})
    monkeypatch.setattr(curated,"derive",lambda *args:pytest.fail("changed context parsed"))
    import viva.sql_authority.identity as identity
    monkeypatch.setattr(identity,"verify_semantics",lambda *args:pytest.fail("normal write folded history"))
    outcome=store.resume(document["sha256"])
    assert outcome.status == "pending" and outcome.reason == "extraction_contract_changed"
    assert all("WHERE" in query for query in store.last_queries)


@pytest.mark.parametrize("mutation",["omitted_contradiction","invented_witness","ineligible_positive"])
def test_compact_stage_with_captured_unmarked_history(source,store,mutation):
    from viva.sql_authority.identity import maintain_claim,verify_compact_views,record_decision
    from viva.ingest.statement import StatementFacts
    accepted=accept(store,source)
    original=b"synthetic captured historical reference"
    doc_id=hashlib.sha256(original).hexdigest()
    store._capture_original(doc_id,original)
    with store._transaction():
        store._put("documents",dict(doc_id=doc_id,byte_count=len(original),contract="synthetic-history-unit"))
        maintain_claim(store,dict(claim_id=doc_id+":account",account_id=accepted.account_id,
            reference="OTHER-REFERENCE",doc_id=doc_id,scope="account",page=1,
            identity_page_count=None,claim_order=store._revision))
    state=store._reconstruct(store.export_audit(),store.head)
    assert verify_compact_views(state) is None
    # Baseline compact proof passes; this synthetic history is deliberately not
    # source-authorized and the later independent admission barrier refuses it.
    with pytest.raises(IntegrityError,match="independently admitted accepted source"):
        store.verify()
    view=store._row("reference_views","account_id=? AND reference=?",(accepted.account_id,"OTHER-REFERENCE"))
    if mutation=="omitted_contradiction":
        changed={**view,"history_claim_id":""}
    elif mutation=="invented_witness":
        changed={**view,"history_claim_id":"0"*64+":account"}
    else:
        changed={**view,"positive_claim_id":view["history_claim_id"]}
    with store._transaction():
        store._put("reference_views",changed)
        facts=StatementFacts.from_dict(store.receipt(accepted.doc_id)["facts"])
        wrong=store.identity_decision(accepted.doc_id)
        wrong["resolution"]["verdict"]="same"
        wrong["resolution"]["account_id"]=store.account(accepted.account_id)["logical_key"]
        record_decision(store,facts,{key:wrong[key] for key in ("resolution","logical_to_physical","account_order","metrics")},accepted.account_id)
    store._reconstruct(store.export_audit(),store.head)
    with pytest.raises(IntegrityError,match="compact references disagree with immutable claim semantics"):
        store.verify()


@pytest.mark.parametrize("table,mutation",[
    ("source_admissions","non_json"),("source_admissions","extra"),
    ("source_admissions","page_bool"),("source_admissions","count_bool"),
    ("source_admissions","missing"),("source_admissions","nested_type"),
    ("identity_decisions","non_json"),("identity_decisions","extra"),
    ("identity_decisions","metric_bool"),("identity_decisions","candidate_container"),
    ("identity_decisions","missing"),("identity_decisions","plan_bool"),
    ("identity_decisions","input_container"),("identity_decisions","promoted_int"),
])
def test_closed_nested_audit_protocol(source,store,table,mutation):
    from viva.sql_authority.schema import valid_row
    accepted=accept(store,source)
    if table=="source_admissions":
        row=store._row(table,"doc_id=?",(accepted.doc_id,))
    else:
        values=store._read("SELECT decision_id,doc_id,body,created_revision FROM identity_decisions WHERE doc_id=?",(accepted.doc_id,))[0]
        row=dict(zip(("decision_id","doc_id","body","created_revision"),values))
    assert valid_row(table,row)
    body=json.loads(row["body"])
    if mutation=="non_json":
        row["body"]="broken"
    elif mutation=="extra":
        body["unknown"]=True
    elif mutation=="missing":
        del body[next(iter(body))]
    elif mutation=="page_bool":
        body["document"]["page_count"]=True
    elif mutation=="count_bool":
        body["pack"]["document_count"]=True
    elif mutation=="nested_type":
        body["document"]={"bad":[]}
    elif mutation=="metric_bool":
        body["metrics"]["rows_read"]=True
    elif mutation=="candidate_container":
        body["resolution"]["candidates"]={}
    elif mutation=="plan_bool":
        body["metrics"]["plans"]["reference"][0][0]=True
    elif mutation=="input_container":
        body["input"]["transactions"]={}
    else:
        body["promoted"]=1
    if mutation!="non_json":
        row["body"]=canonical(body)
    assert not valid_row(table,row), (table,mutation)
    with pytest.raises(IntegrityError,match="unknown audited row"):
        reseal(store,[(table,lambda old:old["doc_id"]==accepted.doc_id,row)])


@pytest.mark.parametrize("body",['{"bad":NaN}','{"bad":Infinity}', '['*1500+']'*1500, '"\\ud800"'])
def test_malformed_nested_protocol_fails_as_integrity_error(source,store,body):
    from viva.sql_authority.schema import valid_row
    accepted=accept(store,source)
    row=store._row("source_admissions","doc_id=?",(accepted.doc_id,))
    changed={**row,"body":body}
    assert valid_row("source_admissions",changed) is False
    with pytest.raises(IntegrityError,match="unknown audited row"):
        reseal(store,[("source_admissions",lambda row:True,changed)])


@pytest.mark.parametrize("table,column,value",[
    ("source_admissions","body","{}"),("source_occurrences","page",True),
    ("account_keys","creation_order",True),("holder_index","normalized_name",[]),
    ("reference_claims","scope","foreign"),("reference_views","history_claim_id","invented"),
    ("identity_decisions","created_revision",True),
])
def test_each_new_row_family_has_independent_typed_reconstruction(source,store,table,column,value):
    from viva.sql_authority.schema import TABLES
    accept(store,source)
    raw=store._db.execute('SELECT '+','.join('"'+key+'"' for key in TABLES[table])+' FROM '+table+' LIMIT 1').fetchone()
    row=dict(zip(TABLES[table],raw))
    changed={**row,column:value}
    with pytest.raises(IntegrityError,match="unknown audited row"):
        reseal(store,[(table,lambda old:old==row,changed)])


@pytest.mark.parametrize("point",["after_financial_rows","before_audit","before_commit"])
def test_curated_promotion_fault_rolls_back_all_new_rows(source,store,point):
    document=member(source)
    def fail(at):
        if at==point and any(op["table"]=="reference_claims" for op in store._operations):
            raise RuntimeError("promotion interrupted")
    store._fault=fail
    with pytest.raises(RuntimeError,match="promotion interrupted"):
        store.ingest_curated(source.original(document["sha256"]),source)
    assert store.item(document["sha256"])["state"]=="staged"
    counts=store.verify()["counts"]
    assert counts["source_admissions"]==counts["receipts"]==1
    for table in ("interpretations","source_occurrences","account_keys","holder_index","reference_claims","reference_views","identity_decisions","postings"):
        assert counts[table]==0
    with SQLAuthority.open(store.root,store._test_credentials()) as reopened:
        reopened.attach_curated(CuratedSource.open())
        assert reopened.resume(document["sha256"]).status=="accepted"
        assert reopened.verify()["counts"]["reference_claims"]==1


@pytest.mark.parametrize("state",["staged","accepted"])
def test_curated_commit_lost_ack_is_idempotent(source,store,state):
    document=member(source)
    original=source.original(document["sha256"])
    def fail(point):
        if point=="after_commit" and store.item(document["sha256"])["state"]==state:
            raise RuntimeError("lost acknowledgment")
    store._fault=fail
    with pytest.raises(RuntimeError,match="lost acknowledgment"):
        store.ingest_curated(original,source)
    with SQLAuthority.open(store.root,store._test_credentials()) as reopened:
        reopened.attach_curated(CuratedSource.open())
        accepted=reopened.ingest_curated(original,source)
        head=reopened.head
        assert reopened.ingest_curated(original,source).status==accepted.status=="accepted"
        assert reopened.head==head
        assert reopened.verify()["counts"]["reference_claims"]==1


def test_curated_two_writers_and_stable_reader(source,store):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    document=member(source)
    original=source.original(document["sha256"])
    barrier=threading.Barrier(2)
    credential=store._test_credentials()
    root=store.root
    def writer(index):
        with SQLAuthority.open(root,credential) as opened:
            barrier.wait(timeout=5)
            return opened.ingest_curated(original,source)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(writer,range(2)))
    assert all(result.status=="accepted" for result in results)
    assert results[0].account_id==results[1].account_id
    store.attach_curated(source)
    assert store.verify()["counts"]["reference_claims"]==1
    first=results[0]
    with SQLAuthority.open(root,credential) as reader:
        reader.attach_curated(source)
        old=reader.account(first.account_id)["running_balance"]
        def observe(point):
            if point=="after_financial_rows":
                assert reader.account(first.account_id)["running_balance"]==old
                assert len(reader._read("SELECT claim_id FROM reference_claims WHERE account_id=?",(first.account_id,)))==1
                assert reader.source_transactions(member(source,index=1)["sha256"])==[]
        store._fault=observe
        second=accept(store,source,1)
        assert second.status=="accepted"
        assert reader.account(first.account_id)["running_balance"]!=old
        assert reader.verify()["counts"]["reference_claims"]==2


def test_source_connector_ignores_many_unrelated_pending_boundaries(source,store,monkeypatch):
    from test_sql_authority_bank import reading
    newest,gap=accept(store,source,2),accept(store,source,0)
    assert newest.status=="accepted" and gap.status=="pending"
    unrelated=[]
    for index in range(100):
        number=str(800000000+index)
        first=store.ingest(f"synthetic unrelated base {index}".encode(),
            lambda data,doc_id,number=number:reading(doc_id,number=number),contract="synthetic-unit")
        pending=store.ingest(f"synthetic unrelated gap {index}".encode(),
            lambda data,doc_id,number=number:reading(doc_id,number=number,opening="80",closing="70",start="2026-02-28",end="2026-03-31"),contract="synthetic-unit")
        assert first.status=="accepted" and pending.status=="pending"
        unrelated.append(pending.doc_id)
    observed=[]
    original_read=store._read
    def read(query,parameters=()):
        rows=original_read(query,parameters)
        if query.startswith("SELECT d.doc_id FROM dependencies"):
            observed.extend(row[0] for row in rows)
        return rows
    monkeypatch.setattr(store,"_read",read)
    connector=accept(store,source,1)
    assert connector.status=="accepted" and store.item(gap.doc_id)["state"]=="accepted"
    rows,vm=store.last_rows_read,store.last_vm_steps
    assert gap.doc_id in observed and not set(observed).intersection(unrelated)
    assert all(store.item(doc_id)["state"]=="pending" for doc_id in unrelated)
    plans=store.dependency_plans()
    assert "dependencies_boundary" in str(plans["pending"])
    assert 0<rows<250 and 0<vm<50000
    print({"unrelated_pending_documents":len(unrelated),"affected_rows_read":rows,
        "affected_vm_instructions":vm,"pending_plan":plans["pending"],"returned_affected_documents":len(observed)})
    assert store.verify()["verified"]


def test_lock_creation_uses_exclusive_then_existing_open(source,store,monkeypatch):
    import errno
    import os
    import viva.sql_authority.store as authority_store
    original_open=os.open
    seen=[]
    def no_racy_combined_open(path,flags,mode=0o777,*,dir_fd=None):
        if str(path).endswith(".lock") and dir_fd is not None:
            seen.append(flags)
            if flags & os.O_CREAT and not flags & os.O_EXCL:
                raise FileNotFoundError(errno.ENOENT,"deterministic combined-create negative control",path)
        return original_open(path,flags,mode,dir_fd=dir_fd)
    monkeypatch.setattr(authority_store.os,"open",no_racy_combined_open)
    accepted=accept(store,source)
    assert accepted.status=="accepted"
    assert accept(store,source).status=="accepted"
    assert any(flags & os.O_EXCL for flags in seen)
    assert any(not flags & os.O_CREAT for flags in seen)


@pytest.mark.parametrize("unsafe",["symlink","public_mode","hardlink","directory"])
def test_curated_existing_lock_path_checks_remain_fail_closed(source,store,unsafe,tmp_path):
    document=member(source)
    path=store.root/"originals"/(document["sha256"]+".lock")
    outside=tmp_path.resolve()/"sentinel"
    outside.write_bytes(b"synthetic untouched sentinel")
    outside.chmod(0o600)
    if unsafe=="symlink":
        path.symlink_to(outside)
    elif unsafe=="hardlink":
        path.hardlink_to(outside)
    elif unsafe=="directory":
        path.mkdir(mode=0o700)
    else:
        path.touch(mode=0o644)
    with pytest.raises((AuthorityError,OSError)):
        store.ingest_curated(source.original(document["sha256"]),source)
    assert outside.read_bytes()==b"synthetic untouched sentinel"


def test_owned_original_replacement_and_detached_admission_cannot_change_authority(source,store,tmp_path):
    import shutil
    copy_root=tmp_path.resolve()/"source-copy"
    shutil.copytree(curated._owned(source).root,copy_root)
    owned=CuratedSource.open(copy_root)
    document=member(owned)
    original=owned.original(document["sha256"])
    (copy_root/document["file"]).write_bytes(original+b"changed")
    with pytest.raises(AuthorityError,match="original changed"):
        owned.original(document["sha256"])
    with pytest.raises(AuthorityError,match="not a pinned source member"):
        store.ingest_curated(original+b"changed",owned)
    with pytest.raises(ValueError):
        CuratedSource.open(copy_root)
    with pytest.raises(AuthorityError):
        CuratedSource.open({"readings":{document["sha256"]:{}}})
    accepted=accept(store,source)
    admission=store.source_admission(accepted.doc_id)
    admission["document"]["id"]="changed caller copy"
    admission["pack"]["manifest_sha256"]="0"*64
    assert store.source_admission(accepted.doc_id)["document"]["id"]!=admission["document"]["id"]
    assert store.verify()["verified"]


def test_source_helper_identity_change_after_reopen_refuses_resume(source,store,monkeypatch):
    import viva.sql_authority.reading as interpretation
    document=member(source)
    def crash(point):
        if point=="after_raw_receipt":
            raise RuntimeError("retained")
    store._fault=crash
    with pytest.raises(RuntimeError):
        store.ingest_curated(source.original(document["sha256"]),source)
    monkeypatch.setattr(interpretation,"_IMPLEMENTATION_MODULES",interpretation._IMPLEMENTATION_MODULES+("viva.sample.activation",))
    with SQLAuthority.open(store.root,store._test_credentials()) as reopened:
        reopened.attach_curated(CuratedSource.open())
        monkeypatch.setattr(curated,"derive",lambda *args:pytest.fail("changed helper closure parsed"))
        outcome=reopened.resume(document["sha256"])
        assert outcome.status=="pending" and outcome.reason=="extraction_contract_changed"
        assert reopened.postings(document["sha256"])==[]
        assert all("WHERE" in query for query in reopened.last_queries)
