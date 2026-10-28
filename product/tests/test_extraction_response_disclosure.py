"""Nonfinancial response provenance, bounded Trust, and unique charge disclosure."""
import json
from types import SimpleNamespace
import pytest
from viva.extraction_responses import response_body, RESPONSE_EVENT
from viva.ledger.events import read_recorded
from viva.surface.outbound import outbound
from viva.read_store.trust import outbound_events
from viva.read_store.store import ReadStoreError
from viva.vault import Vault


def response(identifier="response-1", usage=None, raw=None):
    if raw is None:
        raw=json.dumps({"usage": usage if usage is not None else {}}).encode()
    return SimpleNamespace(event_type=RESPONSE_EVENT,event_id=identifier,
        occurred_at="2026-08-01",body=response_body("doc-1","operation-1","extract",0,0,
        "openai_compatible","route","prompt","text",200,raw))


def call(links=None):
    e=read_recorded("doc-1","route","prompt","text","reply",9.0,10,20,
        True,None,"2026-08-01",phase="extract")
    if links is not None:
        e.body.update(transport_receipt_ids=links,transport_complete=True,
                      extraction_id="operation-1",phase_attempt=0)
    return e


def rows(record):
    return {r["id"]:r["sentence"] for r in record["absences"]}


def test_response_cost_replaces_linked_aggregate_once_and_keeps_phase_tokens():
    e=response(usage={"cost":"0.100000000000000001","prompt_tokens":3,"completion_tokens":4})
    record=outbound([e,call([e.event_id]),call()])
    assert record["cost"]["exact_value"]=="9.100000000000000001"
    assert record["call_count"]==2
    assert record["tokens"]=={"input":20,"output":40,"total":60,"measured_calls":2}
    assert rows(record)["outbound_extraction_response_count"].endswith("1.")
    assert rows(record)["outbound_extraction_orphan_count"].endswith("0.")


def test_orphan_only_is_visible_and_missing_usage_and_price_stay_unavailable():
    record=outbound([response()])
    assert record["call_count"]==0
    assert record["sentence"]!=outbound([])["sentence"]
    assert record["cost"] is None
    assert rows(record)["outbound_extraction_orphan_count"].endswith("1.")
    assert rows(record)["outbound_extraction_unknown_usage_count"].endswith("1.")
    assert rows(record)["outbound_extraction_unknown_cost_count"].endswith("1.")


def test_measured_zero_and_partial_usage_have_distinct_disclosures():
    record=outbound([response(usage={"cost":0,"prompt_tokens":0,"completion_tokens":0})])
    assert record["cost"]["exact_value"]=="0"
    assert rows(record)["outbound_extraction_unknown_usage_count"].endswith("0.")
    partial=outbound([response(usage={"prompt_tokens":7})])
    assert rows(partial)["outbound_extraction_response_input"].endswith("7.")
    assert rows(partial)["outbound_extraction_unknown_usage_count"].endswith("1.")


def test_trust_projection_excludes_raw_bytes_and_retains_orphan_identity(tmp_path):
    from viva.ledger.events import Event, Provenance
    e=response(raw=b'{"usage":{"cost":0.25},"secret":"PRIVATE_PROVIDER_TEXT"}')
    vault=Vault.open(tmp_path/"vault","synthetic-passphrase")
    vault.synchronize_read_store()
    vault.ledger.append(Event(event_type=e.event_type,body=e.body,
        occurred_at=e.occurred_at,provenance=Provenance(doc_id="doc-1"),event_id=e.event_id))
    vault.synchronize_read_store()
    with vault.read_store.open_reader() as revision:
        events=outbound_events(revision)
        assert len(events)==1
        assert events[0].event_id==e.event_id
        assert "PRIVATE_PROVIDER_TEXT" not in repr(events)
        assert "response_bytes_base64" not in repr(events)
        assert outbound(events)["cost"]["exact_value"]=="0.25"
        columns=[row[1] for row in revision.connection.execute("PRAGMA table_info(extraction_responses)")]
        assert "response_bytes_base64" not in columns


def test_trust_response_and_aggregate_share_total_row_bound(tmp_path,monkeypatch):
    from viva.ledger.events import Event, Provenance
    from viva.read_store import trust
    vault=Vault.open(tmp_path/"vault","synthetic-passphrase")
    vault.synchronize_read_store()
    e=response()
    vault.ledger.append(Event(event_type=e.event_type,body=e.body,
        occurred_at=e.occurred_at,provenance=Provenance(doc_id="doc-1"),event_id=e.event_id))
    vault.ledger.append(call())
    monkeypatch.setattr(trust,"MAX_TRUST_EXCHANGES",1)
    vault.synchronize_read_store()
    with vault.read_store.open_reader() as revision:
        with pytest.raises(ReadStoreError,match="exchange history exceeds"):
            outbound_events(revision)


@pytest.mark.parametrize("field", ["doc_id","extraction_id","phase","response_id","cost_usd"])
def test_response_summary_scalar_bound_is_checked_in_sql(tmp_path,field):
    from viva.ledger.events import Event, Provenance
    from viva.read_store.scalar_bounds import MAX_SCALAR_BYTES
    vault=Vault.open(tmp_path/"vault","synthetic-passphrase")
    e=response()
    vault.ledger.append(Event(event_type=e.event_type,body=e.body,
        occurred_at=e.occurred_at,provenance=Provenance(doc_id="doc-1"),event_id=e.event_id))
    vault.synchronize_read_store()
    vault.read_store.publish(lambda db:db.execute(
        "UPDATE extraction_responses SET summary_json=json_set(summary_json,?,?)",
        ("$."+field,"x"*(MAX_SCALAR_BYTES+1))),copy_current=True)
    with vault.read_store.open_reader() as revision:
        with pytest.raises(ReadStoreError,match="byte bound"):
            outbound_events(revision)


def test_response_summary_body_bound_and_ordered_indexed_union(tmp_path):
    from viva.ledger.events import Event, Provenance
    from viva.read_store.trust import MAX_TRUST_BODY_BYTES
    vault=Vault.open(tmp_path/"vault","synthetic-passphrase")
    e=response()
    vault.ledger.append(call())
    vault.ledger.append(Event(event_type=e.event_type,body=e.body,
        occurred_at=e.occurred_at,provenance=Provenance(doc_id="doc-1"),event_id=e.event_id))
    vault.synchronize_read_store()
    with vault.read_store.open_reader() as revision:
        traces=[]
        revision.connection.set_trace_callback(traces.append)
        events=outbound_events(revision)
        revision.connection.set_trace_callback(None)
        assert [e.event_type for e in events]==["ReadRecorded",RESPONSE_EVENT]
        query=next(sql for sql in traces if "UNION ALL" in sql)
        plan=revision.connection.execute("EXPLAIN QUERY PLAN "+query).fetchall()
        assert not any("TEMP B-TREE" in str(row) for row in plan)
    vault.read_store.publish(lambda db:db.execute(
        "UPDATE extraction_responses SET summary_json=json_set(summary_json,'$.padding',?)",
        ("x"*(MAX_TRUST_BODY_BYTES+1),)),copy_current=True)
    with vault.read_store.open_reader() as revision:
        with pytest.raises(ReadStoreError,match="byte bound"):
            outbound_events(revision)


def test_duplicate_event_identity_never_doubles_response_charge():
    e=response(usage={"cost":"0.25"})
    record=outbound([e,e])
    assert record["cost"]["exact_value"]=="0.25"
    assert rows(record)["outbound_extraction_response_count"].endswith("1.")


def test_diagnostics_distinguish_phase_and_http_counts_and_export_no_contents(monkeypatch):
    from viva.surface.diagnostics import diagnostics
    result=diagnostics({"model_calls":2,"extraction_http_responses":3,
        "response_bytes_base64":"PRIVATE_PROVIDER_TEXT","doc_id":"private-doc"})
    assert result["model_calls"]==2
    assert result["extraction_http_responses"]==3
    assert "phase" in result["count_definitions"]["model_calls"]
    assert "HTTP" in result["count_definitions"]["extraction_http_responses"]
    assert "PRIVATE_PROVIDER_TEXT" not in json.dumps(result)
    assert "private-doc" not in json.dumps(result)



def test_debug_claim_can_inspect_orphan_raw_bytes_without_financial_reparse(tmp_path,monkeypatch,capsys):
    from viva.debug import claim
    import viva.vault
    e=response(raw=b'not-json\x00exact-bytes')
    monkeypatch.setenv("VIVA_PASSPHRASE","synthetic-only")
    monkeypatch.setenv("VIVA_VAULT_DIR",str(tmp_path))
    monkeypatch.setattr(claim,"load_dotenv",lambda:None)
    monkeypatch.setattr(claim,"configure_logging",lambda:None)
    monkeypatch.setattr(claim.sys,"argv",["claim","doc-1","--raw"])
    monkeypatch.setattr(viva.vault.Vault,"open",lambda *a,**kw:SimpleNamespace(events=lambda:[e]))
    claim.main()
    result=capsys.readouterr().out
    assert "HTTP response response-1" in result
    assert repr(b'not-json\x00exact-bytes') in result
    assert "reported_cost_usd=None" in result


def test_local_debug_cost_label_keeps_unknown_distinct_from_zero():
    from viva.debug import claim,vault
    for module in (claim,vault):
        assert module._cost_label({"cost_usd":None})=="unavailable"
        assert module._cost_label({"cost_usd":0})=="$0.0000"
