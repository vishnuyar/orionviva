"""Event-derived document read, hold, resolution, and correction rows."""

import json
from pathlib import Path

import pytest

from viva.ledger import EventStore, Provenance
from viva.ledger import events
from viva.read_store import ReadStore


PASSPHRASE = "correct horse battery staple"
TABLES = ("document_reads", "document_holds", "document_hold_resolutions",
          "document_corrections")
FAMILY_TABLE = {
    "ReadRecorded": "document_reads",
    "StatementHeld": "document_holds",
    "BrokerageActivityHeld": "document_holds",
    "BrokerageActivityResolved": "document_hold_resolutions",
    "CorrectionApplied": "document_corrections",
}


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _corpus():
    cited = Provenance("文書-α", 0, "表:一", "note ☕")
    uncited = Provenance()
    return [
        events.document_captured("doc-α", "résumé.pdf", 0, "", 0.0,
                                 "2026-01-01", cited),
        events.read_recorded(
            "doc-α", "route-α", "v1", "text", "雪", 0.125,
            0, 0, False, None, "2026-01-02", uncited,
            usage_reported=False, resolved_model=""),
        events.read_recorded(
            "doc-α", "route-α", "v2", "image", "{}", 0.0,
            0, 7, True, "", "2026-01-03", cited,
            usage_reported=True, resolved_model="provider-β"),
        events.statement_held(
            "doc-α", {"null": None, "empty": [], "zero": 0,
                       "ordered": ["旅", "旅"], "amount": "1.2300"},
            None, "", "2026-01-04", uncited),
        events.brokerage_activity_held(
            "doc-α", {"amount": "999999999999.000000001"},
            {"kind": "gap", "rows": ["雪", "雪"]}, "2026-01-05", cited),
        events.brokerage_activity_resolved("doc-α", "2026-01-06", uncited),
        events.correction_applied("doc-α", "closing", "0.0000", "1.2300",
                                  "2026-01-07", by="human", provenance=cited),
    ]


def _expected(event, sequence):
    body = event.body
    provenance = (event.provenance.doc_id, event.provenance.page,
                  event.provenance.region, event.provenance.note)
    prefix = (sequence, event.event_type, body["doc_id"], event.occurred_at)
    if event.event_type == "ReadRecorded":
        fields = (body["model"], body["model_role"], body.get("resolved_model"),
                  body["prompt_version"], body["input_mode"], body["response_text"],
                  _json(body["cost_usd"]), body.get("input_tokens"),
                  body.get("output_tokens"),
                  None if "usage_reported" not in body else int(body["usage_reported"]),
                  int(body["parse_ok"]), body["parse_error"], body["phase"],
                  _json(body))
    elif event.event_type in ("StatementHeld", "BrokerageActivityHeld"):
        fields = (body["reason"], _json(body["facts"]),
                  None if body["finding"] is None else _json(body["finding"]))
    elif event.event_type == "CorrectionApplied":
        fields = (body["target"], body["from"], body["to"], body["by"])
    else:
        fields = ()
    return prefix + fields + provenance


def _snapshot(revision):
    return {table: revision.connection.execute(
        f"SELECT * FROM {table} ORDER BY source_sequence").fetchall()
        for table in TABLES}


@pytest.mark.parametrize("cut", [1, 3, 5])
def test_document_details_match_events_across_suffix_full_restart_and_held(
        tmp_path: Path, cut: int):
    corpus = _corpus()
    canonical = EventStore.open(tmp_path / "events.jsonl", PASSPHRASE)
    for event in corpus[:cut]:
        canonical.append(event)
    path = tmp_path / "split"
    with ReadStore.create(path, PASSPHRASE) as split:
        assert split.synchronize(canonical).state == "rebuilt"
        held = split.open_reader()
        before = _snapshot(held)
        for event in corpus[cut:]:
            canonical.append(event)
        assert split.synchronize(canonical).state == "caught_up"
        assert _snapshot(held) == before
        held.close()
        with split.open_reader() as revision:
            complete = _snapshot(revision)
            for sequence, event in enumerate(corpus):
                table = FAMILY_TABLE.get(event.event_type)
                if table:
                    assert revision.connection.execute(
                        f"SELECT * FROM {table} WHERE source_sequence=?",
                        (sequence,)).fetchone() == _expected(event, sequence)
    with ReadStore.open(path, PASSPHRASE) as restarted:
        with restarted.open_reader() as revision:
            assert _snapshot(revision) == complete
    with ReadStore.create(tmp_path / "full", PASSPHRASE) as full:
        assert full.synchronize(canonical).state == "rebuilt"
        with full.open_reader() as revision:
            assert _snapshot(revision) == complete
