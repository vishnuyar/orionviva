from dataclasses import replace
import pytest
from viva.allocation_continuation import DeliveredAllocationRegistry,SelectionManifest,RecoveryAnchor,VERSION

def manifest(turn="turn",answer="answer",account="account"):
    return SelectionManifest(VERSION,turn,answer,account,"USD","2025-12-31","exposure",None,"revision",("position:1","balance:2"),"a"*64,"b"*64)

def issue(reg,m=None,**kw):
    m=m or manifest()
    return reg.issue_delivered((m,),turn_id=m.turn_id,answer_id=m.answer_id,delivered=True,validate=lambda _:True,**kw)

def test_only_delivered_validated_answers_issue_and_forged_ids_never_resolve():
    r=DeliveredAllocationRegistry("vault","session");m=manifest()
    for delivered in (False,None,"true"):
        with pytest.raises(ValueError):r.issue_delivered((m,),turn_id="turn",answer_id="answer",delivered=delivered,validate=lambda _:True)
    with pytest.raises(ValueError):r.issue_delivered((m,),turn_id="turn",answer_id="answer",delivered=True,validate=lambda _:False)
    assert not r.eligible_ids()
    with pytest.raises(ValueError):r.resolve("forged",vault_id="vault",session_id="session",validate=lambda _:True)

def test_current_vault_session_reset_and_changed_dependencies_fail_closed():
    r=DeliveredAllocationRegistry("vault","session");rid=issue(r)[0]
    for v,s in [("other","session"),("vault","other")]:
        with pytest.raises(ValueError):r.resolve(rid,vault_id=v,session_id=s,validate=lambda _:True)
    assert r.resolve(rid,vault_id="vault",session_id="session",validate=lambda _:True).manifest.account=="account"
    with pytest.raises(ValueError):r.resolve(rid,vault_id="vault",session_id="session",validate=lambda _:False)
    assert not r.eligible_ids()
    rid=issue(r)[0];r.reset()
    with pytest.raises(ValueError):r.resolve(rid,vault_id="vault",session_id=r.session_id,validate=lambda _:True)

def test_eight_answer_window_evicts_receipts_and_exact_anchor_recovery_is_idempotent():
    r=DeliveredAllocationRegistry("vault","session");records=[]
    for i in range(9):
        m=manifest("turn"+str(i),"answer"+str(i));records.append((m,issue(r,m)[0]))
    assert len(r.eligible_ids())==8
    with pytest.raises(ValueError):r.resolve(records[0][1],vault_id="vault",session_id="session",validate=lambda _:True)
    m,rid=records[-1];anchor=RecoveryAnchor(VERSION,m.turn_id,m.answer_id)
    assert r.recover(anchor,load=lambda t,a:(m,),validate=lambda _:True)==(rid,)
    with pytest.raises(ValueError):r.recover(anchor,load=lambda t,a:(manifest(),),validate=lambda _:True)
    with pytest.raises(ValueError):r.recover(anchor,load=lambda t,a:None,validate=lambda _:True)

def test_duplicate_answer_conflicts_and_four_receipt_limit_are_atomic():
    r=DeliveredAllocationRegistry("vault","session");m=manifest();ids=issue(r,m)
    with pytest.raises(ValueError):issue(r,replace(m,account="other"))
    assert r.eligible_ids()==ids
    with pytest.raises(ValueError):r.issue_delivered(tuple(replace(m,account="a"+str(i)) for i in range(5)),turn_id="turn",answer_id="answer",delivered=True,validate=lambda _:True)
    assert r.eligible_ids()==ids

def test_issued_id_collision_within_same_batch_refuses_before_insertion(monkeypatch):
    import viva.allocation_continuation as module
    r=DeliveredAllocationRegistry("vault","session");m=manifest()
    monkeypatch.setattr(module.secrets,"token_urlsafe",lambda n:"same-id")
    with pytest.raises(ValueError,match="duplicate"):r.issue_delivered((m,replace(m,account="other")),turn_id="turn",answer_id="answer",delivered=True,validate=lambda _:True)
    assert not r.eligible_ids()

def test_receipt_full_serialized_size_and_nested_types_are_bounded():
    m=manifest()
    with pytest.raises(ValueError):replace(m,dependencies=["position:1"])
    with pytest.raises(ValueError):replace(m,dependencies=tuple("position:"+str(i)+"x"*200 for i in range(30)))
    with pytest.raises(ValueError):RecoveryAnchor.from_dict({"version":VERSION,"turn_id":"turn","answer_id":"answer","manifest":m.to_dict()})
