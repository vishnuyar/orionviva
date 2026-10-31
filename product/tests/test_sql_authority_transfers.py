"""Transfers over genuinely admitted synthetic balance sources."""
from decimal import Decimal as D, localcontext
import pytest
from viva.ingest.pipeline_models import ReadResult
from viva.ingest.statement import StatementFacts, TxnFact
from viva.sql_authority import SQLAuthority

pytestmark=pytest.mark.production_kdf


def admit(store,tag,*,number,institution,label="Account",amount="-10.00",description="synthetic payment",currency="USD",day="2024-02-17",opening="100.00",start="2024-02-01",end="2024-02-29"):
    def reader(_data,doc_id):
        lines=[] if amount is None else [TxnFact(day,description,D(amount),page=1)]
        with localcontext() as arithmetic:
            arithmetic.prec=28
            closing=D(opening)+(D(amount) if amount is not None else D(0))
        facts=StatementFacts(doc_id,"checking_statement",1.0,label,currency,D(opening),start,closing,end,lines,opening_page=1,closing_page=1,account_number=number,institution=institution)
        return ReadResult("checking_statement",1.0,facts=facts)
    result=store.ingest(tag.encode(),reader,contract="synthetic-transfer-v1")
    assert result.status=="accepted"
    return result


@pytest.fixture
def store(tmp_path):
    with SQLAuthority.create(tmp_path.resolve()/"authority","synthetic transfer passphrase") as opened:
        yield opened


def fixed_initial(store):
    # The order admits both rivals before their shared destination.
    a=admit(store,"a",number="100000001111",institution="Alpha",label="A",description="synthetic Alpha payment")
    c=admit(store,"c",number="300000003333",institution="Beta",label="C",description="synthetic Beta payment")
    b=admit(store,"b",number="200000002222",institution="Gamma",label="B",amount="10.00",description="synthetic incoming")
    assert not store.transfer_links()
    assert len(store.transfer_suggestions())==2
    return a,b,c


def test_new_zero_movement_owner_wakes_existing_open_suggestion(store):
    fixed_initial(store)
    before=store.transfer_assertions()
    admit(store,"extra",number="400000004444",institution="Beta",label="Extra",amount=None,currency="EUR",opening="0")
    assert len(store.transfer_links())==1
    assert store.transfer_links()[0]["grade"]=="corroborated"
    assert not store.transfer_suggestions()
    assert len(store.transfer_suggestions(stored=True))==1
    assert len(store.transfer_assertions())==len(before)+1
    assert len(store.movements())==3
    assert store.verify()["verified"]


def test_manual_actions_wait_for_next_genuine_boundary(store):
    fixed_initial(store)
    suggestion=store.transfer_suggestions()[0]; a=suggestion["a"]; b=suggestion["candidates"][0]
    before=len(store.transfer_decisions())
    assert store.confirm_transfer(a,b,today="2024-03-01")
    assert not store.confirm_transfer(a,b,today="2024-03-01")
    assert len(store.transfer_decisions())==before
    assert store.transfer_links()[0]["by"]=="human"
    assert store.unlink_transfer(a,b,today="2024-03-02")
    assert not store.transfer_links()
    assert len(store.transfer_decisions())==before
    assert len(store.transfer_as_of("2024-03-01")["links"])==1
    admit(store,"unrelated",number="900000100000",institution="Background",amount="1000",description="background",opening="10000")
    assert len(store.transfer_suggestions())==2
    assert store.verify()["verified"]


def test_dismissal_is_empty_counterpart_and_later_scan_can_resuggest(store):
    fixed_initial(store)
    a=store.transfer_suggestions()[0]["a"]
    assert store.reject_transfer(a,today="2024-03-01")
    assert store.transfer_assertions()[-1]["body"]["b"]==""
    assert len(store.transfer_suggestions())==1
    assert store.verify()["verified"]
    admit(store,"unrelated",number="900000100000",institution="Background",amount="1000",description="background",opening="10000")
    assert len(store.transfer_suggestions())==2
    assert store.verify()["verified"]


def test_automatic_link_and_source_postings_remain_exact(store):
    src=admit(store,"src",number="100000001111",institution="Alpha",description="synthetic to 2222")
    before=store.postings(src.doc_id)
    admit(store,"dst",number="200000002222",institution="Gamma",amount="10.00",description="incoming")
    assert len(store.transfer_links())==1
    assert store.postings(src.doc_id)==before
    assert store.transfer_assertions()[-1]["provenance"]=={"doc_id":"","page":None,"region":"","note":""}
    assert store.verify()["verified"]


def test_current_settlement_never_exports_or_reconstructs_history(store,monkeypatch):
    from viva.sql_authority import transfers
    def forbidden(*_a,**_kw):
        raise AssertionError("ordinary path reconstructed global history")
    for name in ("movements","transfer_inventory","transfer_bindings","transfer_assertions","transfer_decisions","export_audit","verify"):
        monkeypatch.setattr(store,name,forbidden)
    monkeypatch.setattr(transfers,"fold",forbidden)
    fixed_initial(store)
    admit(store,"extra",number="400000004444",institution="Beta",label="Extra",amount=None,currency="EUR",opening="0")
    assert len(store.transfer_links())==1


def test_manual_incomplete_reference_refuses(store):
    admit(store,"a",number="100000001111",institution="Alpha",description="")
    admit(store,"b",number="200000002222",institution="Gamma",amount="10",description="incoming")
    item=store.transfer_suggestions()[0]
    assert not store.confirm_transfer(item["a"],item["candidates"][0],today="2024-03-01")
    assert not store.reject_transfer(item["a"],today="2024-03-01")
    assert store.verify()["verified"]


@pytest.mark.parametrize("missing",["", "source", "destination"])
def test_pure_reference_adapter_matches_existing_activity_predicates(store,missing):
    from viva.sql_authority.transfers import Context, reference_complete
    from viva.surface.activity import _transfer_reference, _relationship, _current_classification
    admit(store,"a",number="100000001111",institution="Alpha",label="A",description="" if missing=="source" else "synthetic payment")
    admit(store,"b",number="200000002222",institution="Gamma",label="B",amount="10.00",description="" if missing=="destination" else "incoming")
    source=next(m for m in store.movements() if m.amount<0)
    destination=next(m for m in store.movements() if m.amount>0)
    context=Context(store.transfer_inventory())
    expected=_transfer_reference(context,source,destination,"") is not None
    assert reference_complete(store,source,destination)==expected
    assert reference_complete(store,source,destination,relationship=False)==(_transfer_reference(context,source,destination,"",relationship=False) is not None)
    assert reference_complete(store,source,destination)==bool(_relationship(context,source,destination,""))
    assert _current_classification(context,source)["valid"]
    assert _current_classification(context,source)["classification"] is None


def test_pending_closure_snapshots_both_new_rivals_before_matching(store):
    # A first statement is admitted for this account. Its last future statement
    # waits until a connector promotes both it and the connector together.
    admit(store,"a-first",number="100000001111",institution="Alpha",description="unrelated",amount="-1",opening="100",end="2024-01-31",start="2024-01-01",day="2024-01-17")
    from viva.ingest.pipeline_models import ReadResult
    from viva.ingest.statement import StatementFacts, TxnFact
    def future(_data,doc_id):
        return ReadResult("checking_statement",1.0,facts=StatementFacts(doc_id,"checking_statement",1.0,"A","USD",D("89"),"2024-03-01",D("79"),"2024-03-31",[TxnFact("2024-03-02","synthetic Alpha payment",D("-10"),page=1)],opening_page=1,closing_page=1,account_number="100000001111",institution="Alpha"))
    pending=store.ingest(b"future",future,contract="synthetic-transfer-v1")
    assert pending.status=="pending"
    admit(store,"b",number="200000002222",institution="Gamma",label="B",amount="10",description="incoming",start="2024-03-01",end="2024-03-31",day="2024-03-02")
    # Connector has its competing source within the same five-day window.
    admit(store,"connector",number="100000001111",institution="Alpha",label="A",amount="-10",description="synthetic Alpha payment",opening="99",start="2024-01-31",end="2024-03-01",day="2024-02-28")
    assert store.item(pending.doc_id)["state"]=="accepted"
    assert not store.transfer_links()
    assert len(store.transfer_suggestions())==2
    assert len(store.transfer_decisions()[-1]["body"]["admissions"])==2
    assert store.verify()["verified"]


def test_transfer_scoring_does_not_inherit_callers_decimal_precision(store):
    from decimal import localcontext
    with localcontext() as context:
        context.prec=2
        admit(store,"a",number="100000001111",institution="Alpha",label="A",amount="-10.001",description="to 2222",opening="100.123")
        admit(store,"b",number="200000002222",institution="Gamma",label="B",amount="10.001",description="incoming",opening="100.123")
    assert store.transfer_assertions()[-1]["body"]["evidence"]["amount"]=="10.001"
    assert store.verify()["verified"]
