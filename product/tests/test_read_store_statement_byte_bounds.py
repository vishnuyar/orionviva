"""Statement evidence is refused before an oversized model response is parsed."""

import json
from pathlib import Path

import pytest

from viva.ledger import EventStore, Provenance
from viva.ledger import events
from viva.read_store import ReadStore, ReadStoreError


PASSPHRASE = "correct horse battery staple"
STATEMENT_BYTE_BOUND = 1_000_000


@pytest.mark.parametrize("glyph", ["X", "雪"])
def test_statement_register_refuses_oversized_response_before_parser(
        tmp_path: Path, glyph: str):
    source = Provenance("doc-α", 0, "balance", "statement")
    canonical = EventStore.open(tmp_path / "events.jsonl", PASSPHRASE)
    for event in (
        events.document_captured("doc-α", "statement.pdf", 1,
                                 "checking_statement", 1.0, "2026-01-01", source),
        events.read_recorded("doc-α", "route", "v1", "text", "{}", 0.0,
                             0, 0, True, None, "2026-01-02", source,
                             usage_reported=False),
        events.account_opened("account-α", "depository", "Checking", "USD",
                              "2026-01-01", provenance=source),
        events.closing_balance_observed("account-α", "0.0000", "2026-01-31",
                                        source),
    ):
        canonical.append(event)
    with ReadStore.create(tmp_path / "read-model", PASSPHRASE) as reads:
        assert reads.synchronize(canonical).state == "rebuilt"
        shell = json.dumps({"padding": ""})
        room = STATEMENT_BYTE_BOUND - len(shell)
        width = len(glyph.encode("utf-8"))
        padding = glyph * (room // width) + "X" * (room % width)
        at_limit = json.dumps({"padding": padding}, ensure_ascii=False)
        assert len(at_limit.encode("utf-8")) == STATEMENT_BYTE_BOUND
        reads.publish(lambda connection: connection.execute(
            "UPDATE document_reads SET response_text=?", (at_limit,)),
            copy_current=True)
        with reads.open_reader() as revision:
            revision.review_projection()
        oversized = json.dumps({"padding": padding + "X"}, ensure_ascii=False)
        assert len(oversized.encode("utf-8")) == STATEMENT_BYTE_BOUND + 1
        reads.publish(lambda connection: connection.execute(
            "UPDATE document_reads SET response_text=?", (oversized,)),
            copy_current=True)
        with reads.open_reader() as revision:
            with pytest.raises(ReadStoreError, match="statement.*byte bound"):
                revision.review_projection()
