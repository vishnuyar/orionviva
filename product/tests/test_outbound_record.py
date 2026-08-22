"""The complete outbound record, and the absences it carries.

The public promise is that nothing leaves silently and the complete outbound
record is always visible. Until now the invariant behind it was kept by there
being nothing to show. Every test here is about the difference between that and
showing it.
"""

from __future__ import annotations

import json
from pathlib import Path

from viva import render
from viva.desktop_bridge.vault_surface import OpenedVaultSurfaceProvider
from viva.ledger.events import document_captured, read_recorded
from viva.persona import moment
from viva.surface.outbound import outbound
from viva.vault import Vault

PASSPHRASE = "a-real-passphrase"


def _call(phase: str = "extract", model: str = "a-model", cost: float = 0.0,
          day: str = "2026-07-01"):
    return read_recorded("doc-1", model, "p-v1", "text+image", "{}", cost,
                         10, 20, True, None, day, phase=phase)


def test_a_vault_that_has_sent_nothing_says_so_rather_than_rendering_empty():
    """An empty list and a panel that failed to load are the same picture, so
    the emptiness is stated. It is `ready`, because the panel has something
    true to say and saying it is the whole point."""
    record = outbound([])

    assert record["state"] == "ready"
    assert record["call_count"] == 0
    assert record["sentence"] == moment("outbound_none")


def test_the_absences_are_in_the_read_for_a_vault_that_has_sent_nothing_too():
    """A screen that composes its own caveats writes them out of date the day
    the capability lands, and nothing goes red when it does."""
    for record in (outbound([]), outbound([_call()])):
        assert [item["id"] for item in record["absences"]] == ["scope", "anchoring"]
        assert record["absences"][1]["sentence"] == moment("outbound_no_anchor")


def test_each_pass_is_counted_and_says_what_was_actually_sent_on_it():
    record = outbound([_call("classify"), _call("extract"), _call("extract"),
                       _call("speak")])

    assert [(row["id"], row["count"]) for row in record["phases"]] == [
        ("classify", 1), ("extract", 2), ("speak", 1)]
    assert record["phases"][1]["sentence"] == moment(
        "outbound_phase_extract", count=render.count(2))


def test_a_pass_this_build_has_no_sentence_for_is_reported_rather_than_folded():
    """A call recorded under a name added later says that it exists and that
    what it sent is not described here, which is the honest rendering of a word
    this build does not know."""
    record = outbound([_call("extract"), _call("dream"), _call("dream")])

    unnamed = [row for row in record["phases"] if row["id"] == "unnamed"]
    assert unnamed and unnamed[0]["count"] == 2
    assert unnamed[0]["sentence"] == moment("outbound_phase_unnamed",
                                            count=render.count(2))


def test_the_distinct_models_and_the_span_are_the_charters_own_case():
    record = outbound([_call(model="one", day="2026-07-01"),
                       _call(model="two", day="2026-08-05"),
                       _call(model="one", day="2026-07-20")])

    assert record["models"] == [{"name": "one", "count": 2}, {"name": "two", "count": 1}]
    assert record["span"]["first"] == "2026-07-01"
    assert record["span"]["last"] == "2026-08-05"
    assert record["model_sentence"] == moment("outbound_models",
                                              count=render.count(2))


def test_a_cost_is_summed_over_the_digits_recorded_rather_than_over_floats():
    """A person may be reading this against a bill. The sum is of the digits
    the log wrote, not of the binary approximations of them."""
    record = outbound([_call(cost=0.1), _call(cost=0.2)])

    assert record["cost"]["exact_value"] == "0.3"


def test_a_vault_whose_calls_recorded_no_price_gets_no_total_rather_than_zero():
    """Nothing was measured, and a zero is a measurement."""
    calls = [_call()]
    calls[0].body.pop("cost_usd")

    assert outbound(calls)["cost"] is None


def test_only_the_day_a_call_was_recorded_on_travels():
    """A time of day says what a person was doing at four in the morning, which
    is not a fact this record exists to publish."""
    record = outbound([_call(day="2026-07-01T04:12:33Z")])

    assert record["span"]["first"] == "2026-07-01"
    assert "04:12" not in json.dumps(record)


def test_nothing_but_a_model_call_is_read_out_of_the_stream():
    record = outbound([document_captured("d", "f.pdf", 1, "statement", 0.0,
                                         "2026-07-01"),
                       _call()])

    assert record["call_count"] == 1


def test_the_whole_record_is_json_safe():
    json.dumps(outbound([_call(cost=0.5)]), allow_nan=False)


def test_the_trust_surface_reads_the_record_from_a_real_vault(tmp_path: Path):
    vault = Vault.open(tmp_path / "vault", PASSPHRASE)
    vault.ledger.append(_call("classify", "a-model", 0.25, "2026-07-01"))

    read = OpenedVaultSurfaceProvider(vault).read_surface("trust", {})

    assert read["state"] == "ready"
    assert read["outbound"]["call_count"] == 1
    assert read["outbound"]["cost"]["exact_value"] == "0.25"
    json.dumps(read, allow_nan=False)


def test_the_trust_surface_of_a_silent_vault_still_carries_the_record(tmp_path: Path):
    vault = Vault.open(tmp_path / "vault", PASSPHRASE)

    read = OpenedVaultSurfaceProvider(vault).read_surface("trust", {})

    assert read["outbound"]["sentence"] == moment("outbound_none")
    assert read["notes"] == []
