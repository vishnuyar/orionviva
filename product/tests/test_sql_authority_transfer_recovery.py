"""Transfer settlement shares atomic source completion and serialized admission."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import threading
import pytest
from viva.sql_authority import SQLAuthority
from test_sql_authority_transfers import admit, fixed_initial

pytestmark=pytest.mark.production_kdf


@pytest.mark.parametrize("point",["after_transfer_inventory","after_transfer_bindings","after_transfer_snapshot","after_transfer_assertion","after_transfer_settlement","before_audit","before_commit"])
def test_transfer_fault_retains_receipt_and_rolls_back_complete_boundary(tmp_path,point):
    root=tmp_path.resolve()/"authority"
    with SQLAuthority.create(root,"synthetic transfer passphrase") as store:
        fixed_initial(store)
        head=store.head; count=len(store.transfer_assertions()); inventory=store.transfer_inventory()
        def fault(at):
            if at==point and any(op["table"]=="periods" for op in (store._operations or [])):
                raise RuntimeError("synthetic fault")
        store._fault=fault
        with pytest.raises(RuntimeError,match="synthetic fault"):
            admit(store,"extra",number="400000004444",institution="Beta",label="Extra",amount=None,currency="EUR",opening="0")
        doc=hashlib.sha256(b"extra").hexdigest()
        assert store.item(doc)["state"]=="staged"
        assert store.original(doc)==b"extra"
        assert store.receipt(doc)
        assert not store.transfer_links()
        assert store.transfer_inventory()==inventory
        assert len(store.transfer_assertions())==count
        assert store.verify()["verified"]
    with SQLAuthority.open(root,"synthetic transfer passphrase") as store:
        assert store.resume(doc).status=="accepted"
        assert len(store.transfer_links())==1
        head=store.head
        assert store.resume(doc).status=="accepted"
        assert store.head==head
        assert store.verify()["verified"]


def test_manual_writers_compete_for_single_live_movement(tmp_path):
    root=tmp_path.resolve()/"authority"
    with SQLAuthority.create(root,"synthetic transfer passphrase") as store:
        fixed_initial(store)
        choices=[(s["a"],s["candidates"][0]) for s in store.transfer_suggestions()]
    barrier=threading.Barrier(2)
    def act(pair):
        with SQLAuthority.open(root,"synthetic transfer passphrase") as store:
            barrier.wait(timeout=5)
            return store.confirm_transfer(*pair,today="2024-03-01")
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(act,choices))==[False,True]
    with SQLAuthority.open(root,"synthetic transfer passphrase") as store:
        assert len(store.transfer_links())==1
        assert store.verify()["verified"]


def test_readers_observe_prior_overlay_until_commit(tmp_path):
    root=tmp_path.resolve()/"authority"
    with SQLAuthority.create(root,"synthetic transfer passphrase") as writer:
        fixed_initial(writer)
        with SQLAuthority.open(root,"synthetic transfer passphrase") as reader:
            seen=[]
            def fault(at):
                if at=="after_transfer_assertion":
                    seen.append(True)
                    assert not reader.transfer_links()
                    assert len(reader.transfer_suggestions())==2
            writer._fault=fault
            admit(writer,"extra",number="400000004444",institution="Beta",label="Extra",amount=None,currency="EUR",opening="0")
            assert seen
            assert len(reader.transfer_links())==1
            assert reader.verify()["verified"]


def test_failed_writer_retries_on_same_connection_without_cached_admission(tmp_path):
    root=tmp_path.resolve()/"authority"
    with SQLAuthority.create(root,"synthetic transfer passphrase") as store:
        fixed_initial(store)
        before=store.transfer_inventory()
        seen=[]
        def fault(at):
            if at=="after_transfer_bindings" and any(op["table"]=="periods" for op in (store._operations or [])):
                seen.append(True)
                assert store._transfer_facts is not None
                assert any(row and row["number"]=="400000004444" for row in store._transfer_facts["transfer_inventory"].values())
                assert any(row and row["doc_id"]==hashlib.sha256(b"retry").hexdigest() for row in store._transfer_facts["transfer_bindings"].values())
                raise RuntimeError("synthetic admission rollback")
        store._fault=fault
        with pytest.raises(RuntimeError,match="synthetic admission rollback"):
            admit(store,"retry",number="400000004444",institution="Other",label="Extra",amount="-3",currency="EUR")
        assert seen
        assert store._transfer_facts is None
        assert store.transfer_inventory()==before
        store._fault=lambda _point:None
        assert store.resume(hashlib.sha256(b"retry").hexdigest()).status=="accepted"
        assert store._transfer_facts is None
        assert len(store.transfer_inventory())==len(before)+1
        assert store.verify()["verified"]
