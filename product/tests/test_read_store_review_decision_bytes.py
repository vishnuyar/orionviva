"""Review decision selectors refuse oversized JSON before Python fetch."""

import json

import pytest

from viva.ledger import EventStore
from viva.ledger.events import finding_set_aside, question_declined
from viva.read_store import ReadStore
from viva.read_store import composition, questions
from viva.read_store.rhythm import RhythmReadError
from viva.read_store.store import ReadStoreError


@pytest.mark.parametrize("glyph", ["X", "雪"])
@pytest.mark.parametrize("kind,event,subject", [
    ("question", question_declined(
        "question-1", "merchant", "2026-08-29", amount="0.00", count=0),
     "question-1"),
    ("finding", finding_set_aside(
        "finding-1", "fee_observed", {"amount": "0.00"}, "2026-08-29"),
     "finding-1"),
])
def test_review_decision_json_exact_utf8_bound_and_prefetch_refusal(
        tmp_path, glyph, kind, event, subject):
    canonical = EventStore.open(tmp_path / "events.jsonl", "pw")
    canonical.append(event)
    with ReadStore.create(tmp_path / "read-model", "pw") as reads:
        reads.synchronize(canonical)
        with reads.open_reader() as revision:
            original = revision.connection.execute(
                "SELECT body_json FROM review_decisions LIMIT 1").fetchone()[0]
        base = json.loads(original)
        bound = (questions.MAX_REVIEW_DECISION_BYTES if kind == "question"
                 else composition.MAX_FINDING_DECISION_BYTES)
        shell = json.dumps({**base, "padding": ""}, ensure_ascii=False)
        room = bound - len(shell.encode("utf-8"))
        width = len(glyph.encode("utf-8"))
        padding = glyph * (room // width) + "X" * (room % width)
        for extra in ("", "X"):
            encoded = json.dumps({**base, "padding": padding + extra},
                                 ensure_ascii=False)
            assert len(encoded.encode("utf-8")) == bound + len(extra)
            reads.publish(lambda connection: connection.execute(
                "UPDATE review_decisions SET body_json=?", (encoded,)),
                copy_current=True)
            with reads.open_reader() as revision:
                old_select = revision.connection.execute(
                    "SELECT body_json FROM review_decisions LIMIT 1").fetchone()[0]
                assert json.loads(old_select) == json.loads(encoded)
                traced = []
                revision.connection.set_trace_callback(traced.append)
                def selected():
                    if kind == "question":
                        return questions._latest_decisions(
                            revision.connection, "QuestionDeclined", [subject])
                    return composition._latest_finding_decisions(
                        revision.connection, [subject])
                if extra:
                    with pytest.raises(RhythmReadError, match="byte bound"):
                        selected()
                else:
                    assert selected()[subject]["padding"] == padding
                if kind == "question":
                    direct = lambda: revision.question_decline_matches(
                        subject, amount_text="0.00", count=0,
                        as_of="2026-08-29")
                    history = lambda: revision.question_decision_history(
                        as_of="2026-08-29")
                else:
                    direct = lambda: revision.finding_set_aside_matches(
                        subject, stake={"amount": "0.00"},
                        as_of="2026-08-29")
                    history = lambda: revision.finding_decision_history(
                        as_of="2026-08-29")
                if extra:
                    with pytest.raises(ReadStoreError, match="byte bound"):
                        direct()
                    with pytest.raises(ReadStoreError, match="byte bound"):
                        history()
                else:
                    assert direct()
                    assert history()[0]["body_json"] == encoded
                revision.connection.set_trace_callback(None)
                bounded = [sql for sql in traced if "FROM review_decisions" in sql
                           and "CASE WHEN length(CAST(body_json AS BLOB))" in sql]
                assert len(bounded) == 3
                plans = [" ".join(str(row[-1]) for row in revision.connection.execute(
                    "EXPLAIN QUERY PLAN " + sql).fetchall()) for sql in bounded]
                assert all("TEMP B-TREE" not in plan.upper() for plan in plans)
