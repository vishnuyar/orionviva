"""Semantic rejection survives coordinated disposable-key audit changes."""
import json
import pytest
from viva.sql_authority import SQLAuthority, IntegrityError
from viva.sql_authority.store import canonical
from viva.sql_authority.schema import valid_row
from test_sql_authority_transfers import admit, fixed_initial
from test_sql_authority_integrity import _resealed_export

pytestmark=pytest.mark.production_kdf


def install_coherent_mutation(store,mutate):
    original=store.export_audit()
    altered=_resealed_export(store,original,mutate)
    state=store._reconstruct(altered,{"revision":altered["revision"],"head":altered["head"]})
    store._db.execute("BEGIN IMMEDIATE")
    try:
        for record in altered["records"]:
            store._db.execute("UPDATE audit SET previous_hash=?,envelope=?,record_hash=? WHERE sequence=?",(record[1],record[2],record[3],record[0]))
        for revision,head,mac in altered["commits"]:
            store._db.execute("UPDATE commits SET head=?,mac=? WHERE revision=?",(head,mac,revision))
        store._db.execute("UPDATE control SET head=?,mac=? WHERE singleton=1",(altered["head"],altered["mac"]))
        for row in state["transfer_runs"].values():
            store._db.execute("UPDATE transfer_runs SET body=?,boundary=? WHERE run_id=?",(row["body"],row["boundary"],row["run_id"]))
        for row in state["transfer_assertions"].values():
            store._db.execute("UPDATE transfer_assertions SET boundary=?,body=?,provenance=? WHERE ordinal=?",(row["boundary"],row["body"],row["provenance"],row["ordinal"]))
        store._db.execute("COMMIT")
    except BaseException:
        store._db.execute("ROLLBACK")
        raise
    # Prove audit reconstruction accepts the coordinated rows before semantics.
    assert store._reconstruct(store.export_audit(),store.head)["transfer_runs"]==state["transfer_runs"]


@pytest.mark.parametrize("control",["rival","owner","score","verdict","candidate_order","witness_order","context"])
def test_coordinated_wrong_decision_witness_rejected(tmp_path,control):
    with SQLAuthority.create(tmp_path.resolve()/"authority","synthetic transfer passphrase") as store:
        fixed_initial(store)
        # Two destinations ensure the ordering control changes a real array.
        admit(store,"d",number="500000005555",institution="Delta",label="D",amount="10.00",description="another incoming")
        assert store.verify()["verified"]
        assert store.verify()["verified"]
        last=store.transfer_decisions()[-1]["run_id"]
        def mutate(payload):
            for operation in payload["operations"]:
                if operation["table"]!="transfer_runs" or operation["row"]["run_id"]!=last:
                    continue
                body=json.loads(operation["row"]["body"])
                if control=="rival":
                    body["graph"].pop(next(iter(body["graph"])))
                elif control=="owner":
                    body["owners"].pop()
                elif control=="score":
                    body["strength"][0]["score"]=(body["strength"][0]["score"]+1)%4
                elif control=="verdict":
                    key=next(iter(body["graph"])); body["verdicts"][key]=body["graph"][key][0]
                elif control=="candidate_order":
                    body["graph"][next(iter(body["graph"]))].reverse()
                elif control=="witness_order":
                    body["owners"].reverse()
                else:
                    body["context"]["sha256"]="0"*64
                operation["row"]["body"]=canonical(body)
        install_coherent_mutation(store,mutate)
        with pytest.raises(IntegrityError,match="transfer semantic"):
            store.verify()


@pytest.mark.parametrize("table,row",[
    ("transfer_dirty",{"movement":"x","active":True}),
    ("transfer_endpoints",{"movement":"x","account":"a","currency":"USD","magnitude":"NaN","flow":"source","date":"2024-01-01","active":1}),
    ("transfer_inventory",{"account":"a","kind":"depository","currency":"USD","institution":"A","number":"1","name":"A","source_doc":"x","source_order":True}),
    ("transfer_assertions",{"ordinal":1,"event_type":"Unknown","occurred_at":"2024-01-01","body":"{}","provenance":"{}","boundary":"x","run_id":""}),
])
def test_closed_transfer_rows_reject_malformed_protocol(table,row):
    assert not valid_row(table,row)
    assert not valid_row(table,{**row,"unknown":1})


def test_previous_format_header_rejected_without_migration(tmp_path):
    root=tmp_path.resolve()/"authority"
    with SQLAuthority.create(root,"synthetic transfer passphrase"):
        pass
    path=root/"authority.json"; body=json.loads(path.read_text()); body["format"]="viva-sql-authority-prototype-v2"; path.write_text(json.dumps(body))
    from viva.sql_authority import AuthorityError
    with pytest.raises(AuthorityError,match="format"):
        SQLAuthority.open(root,"synthetic transfer passphrase")


@pytest.mark.parametrize("amount",[None,"-10.00"])
def test_complete_transfer_admission_omission_is_not_hidden_by_matching_audit(tmp_path,monkeypatch,amount):
    from viva.sql_authority import transfers
    with SQLAuthority.create(tmp_path.resolve()/"authority","synthetic transfer passphrase") as store:
        assert store.verify()["verified"]
        # All ordinary source/current/audit records are genuinely committed. The
        # deliberately faulty admission omits the entire transfer-side family.
        monkeypatch.setattr(transfers,"admit",lambda *_args:None)
        admit(store,"omitted",number="400000004444",institution="Beta",label="Extra",amount=amount,currency="EUR",opening="0")
        exported=store.export_audit()
        assert store._reconstruct(exported,store.head)["items"]
        with pytest.raises(IntegrityError,match="inventory omitted"):
            store.verify()


def test_every_source_transaction_requires_a_movement_even_if_all_other_transfer_rows_agree(tmp_path,monkeypatch):
    from viva.sql_authority import transfers
    real_admit=transfers.admit
    with SQLAuthority.create(tmp_path.resolve()/"authority","synthetic transfer passphrase") as store:
        assert store.verify()["verified"]
        def incomplete(store,account,mapped,facts):
            transfers.inventory_admit(store,mapped["logical_key"],account["kind"],account["currency"],account["institution"],account["number"],account["label"],facts.doc_id)
        monkeypatch.setattr(transfers,"admit",incomplete)
        admit(store,"omitted",number="400000004444",institution="Beta",amount="-10",opening="100")
        assert store._reconstruct(store.export_audit(),store.head)["transactions"]
        with pytest.raises(IntegrityError,match="movement omitted"):
            store.verify()


def test_orphan_authenticated_decision_run_is_rejected(tmp_path):
    with SQLAuthority.create(tmp_path.resolve()/"authority","synthetic transfer passphrase") as store:
        fixed_initial(store)
        assert store.verify()["verified"]
        copied=store.transfer_decisions()[-1]
        with store._transaction():
            store._put("transfer_runs",{**copied,"run_id":"f"*32,"body":canonical(copied["body"])})
        assert store._reconstruct(store.export_audit(),store.head)["transfer_runs"]
        with pytest.raises(IntegrityError,match="orphan decision"):
            store.verify()


def test_source_boundary_cannot_be_coherently_rebound(tmp_path):
    with SQLAuthority.create(tmp_path.resolve()/"authority","synthetic transfer passphrase") as store:
        first,_,_=fixed_initial(store)
        assert store.verify()["verified"]
        last=store.transfer_decisions()[-1]["run_id"]
        def mutate(payload):
            for op in payload["operations"]:
                if op["table"]=="transfer_runs" and op["row"]["run_id"]==last:
                    op["row"]["boundary"]=first.doc_id
                if op["table"]=="transfer_assertions" and op["row"]["run_id"]==last:
                    op["row"]["boundary"]=first.doc_id
        install_coherent_mutation(store,mutate)
        with pytest.raises(IntegrityError,match="outer source boundary"):
            store.verify()


def test_zero_transaction_owner_without_dependency_wakeup_is_rejected(tmp_path,monkeypatch):
    from viva.sql_authority import transfers
    with SQLAuthority.create(tmp_path.resolve()/"authority","synthetic transfer passphrase") as store:
        fixed_initial(store)
        assert store.verify()["verified"]
        monkeypatch.setattr(transfers,"dirty",lambda *_args:None)
        admit(store,"extra",number="400000004444",institution="Beta",label="Extra",amount=None,currency="EUR",opening="0")
        assert not store.transfer_links()
        assert store._reconstruct(store.export_audit(),store.head)["transfer_inventory"]
        with pytest.raises(IntegrityError,match="automatic assertions/wakeup"):
            store.verify()


@pytest.mark.parametrize("duplicates",[False,True])
def test_binding_order_and_duplicate_occurrence_follow_financial_source_order(tmp_path,duplicates):
    from decimal import Decimal as D
    from viva.ingest.pipeline_models import ReadResult
    from viva.ingest.statement import StatementFacts,TxnFact
    with SQLAuthority.create(tmp_path.resolve()/"authority","synthetic transfer passphrase") as store:
        def reader(_source,doc):
            lines=[TxnFact("2024-02-17","synthetic repeated" if duplicates else label,D("-10.00"),page=1) for label in ("synthetic first","synthetic second")]
            facts=StatementFacts(doc,"checking_statement",1.0,"A","USD",D("100"),"2024-02-01",D("80.00"),"2024-02-29",lines,opening_page=1,closing_page=1,account_number="100000001111",institution="Alpha")
            return ReadResult("checking_statement",1.0,facts=facts)
        store.ingest(b"source ordering",reader,contract="synthetic-transfer-v1")
        assert store.verify()["verified"]
        original=store.transfer_bindings()
        def mutate(payload):
            selected=[op for op in payload["operations"] if op["table"]=="transfer_bindings"]
            if not selected:
                return
            assert len(selected)==2
            if duplicates:
                selected[0]["row"]["txn_id"],selected[1]["row"]["txn_id"]=selected[1]["row"]["txn_id"],selected[0]["row"]["txn_id"]
            else:
                selected[0]["row"]["source_order"],selected[1]["row"]["source_order"]=selected[1]["row"]["source_order"],selected[0]["row"]["source_order"]
                positions=[i for i,op in enumerate(payload["operations"]) if op["table"]=="transfer_bindings"]
                payload["operations"][positions[0]],payload["operations"][positions[1]]=payload["operations"][positions[1]],payload["operations"][positions[0]]
        altered=_resealed_export(store,store.export_audit(),mutate)
        state=store._reconstruct(altered,{"revision":altered["revision"],"head":altered["head"]})
        store._db.execute("PRAGMA defer_foreign_keys=ON")
        store._db.execute("BEGIN IMMEDIATE")
        try:
            for row in original:
                store._db.execute("UPDATE transfer_bindings SET source_order=source_order+1000000,txn_id=? WHERE movement=?",("f"*62+str(row["source_order"]).zfill(2),row["movement"]))
            for row in state["transfer_bindings"].values():
                store._db.execute("UPDATE transfer_bindings SET source_order=?,txn_id=? WHERE movement=?",(row["source_order"],row["txn_id"],row["movement"]))
            for record in altered["records"]:
                store._db.execute("UPDATE audit SET previous_hash=?,envelope=?,record_hash=? WHERE sequence=?",(record[1],record[2],record[3],record[0]))
            for revision,head,mac in altered["commits"]:
                store._db.execute("UPDATE commits SET head=?,mac=? WHERE revision=?",(head,mac,revision))
            store._db.execute("UPDATE control SET head=?,mac=? WHERE singleton=1",(altered["head"],altered["mac"]))
            store._db.execute("COMMIT")
        except BaseException:
            store._db.execute("ROLLBACK")
            raise
        assert store._reconstruct(store.export_audit(),store.head)["transfer_bindings"]==state["transfer_bindings"]
        assert store._db.execute("PRAGMA foreign_key_check").fetchall()==[]
        with pytest.raises(IntegrityError,match="source movement identity/order"):
            store.verify()


def test_authenticated_manual_reversal_requires_complete_activity_relationship(tmp_path):
    from viva.sql_authority.transfers import append,Context
    from viva.ledger.events import transfer_unlinked
    from viva.surface.activity import _transfer_state
    with SQLAuthority.create(tmp_path.resolve()/"authority","synthetic transfer passphrase") as store:
        # Counterpart ownership printed on the destination can establish a real
        # automatic link even when its source description is blank.
        admit(store,"blank-source",number="100000001111",institution="Alpha",label="A",description="")
        admit(store,"destination",number="200000002222",institution="Gamma",label="B",amount="10.00",description="synthetic incoming Alpha")
        assert store.verify()["verified"]
        pair=store.transfer_links()[0]
        source=next(m for m in store.movements() if m.amount<0)
        counterpart=next(m for m in store.movements() if m.amount>0)
        context=Context(store.transfer_inventory())
        context.movements=store.movements
        context.linked_keys=lambda:{pair["a"],pair["b"]}
        context.transfer_suggestions=store.transfer_suggestions
        context.transfer_links=store.transfer_links
        assert "unlink_transfer" not in _transfer_state(context,source,"")[1]
        assert not store.unlink_transfer(source.key,counterpart.key,today="2024-03-01")
        assert store.verify()["verified"]
        # Known disposable-key authority writes matching assertions/current views
        # and audit while bypassing the actual action admission predicate.
        with store._transaction():
            append(store,transfer_unlinked(source.key,counterpart.key,"2024-03-01"),source.provenance.doc_id)
        assert store._reconstruct(store.export_audit(),store.head)["transfer_assertions"]
        with pytest.raises(IntegrityError,match="manual reversal"):
            store.verify()
