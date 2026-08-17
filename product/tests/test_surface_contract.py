from decimal import Decimal

import pytest

from viva.surface import CURRENT_PROTOCOL, ActionOutcome, FigureView, PanelState, ProtocolVersion
from viva.surface.models import FigureGrade


def test_protocol_accepts_additive_minor_changes_only():
    assert CURRENT_PROTOCOL.accepts(ProtocolVersion(1, 0))
    assert not CURRENT_PROTOCOL.accepts(ProtocolVersion(1, 1))
    assert not CURRENT_PROTOCOL.accepts(ProtocolVersion(2, 0))


def test_protocol_round_trips_wire_format():
    assert ProtocolVersion.parse("1.4").wire() == "1.4"
    with pytest.raises(ValueError):
        ProtocolVersion.parse("surface-v1")


def test_figure_serializes_exact_decimal_and_evidence():
    figure = FigureView(
        id="net-worth",
        exact_value="48240.18",
        display="$48,240.18",
        currency="USD",
        measure="balance",
        grade=FigureGrade.CORROBORATED,
        grade_label="Corroborated",
        exactness="exact",
        as_of="2026-06-30",
        coverage="checking and savings statements, Jan-Jun 2026",
        record_ids=("statement-1",),
        provenance=("statement-1/page-1",),
        caveats=("one page is held",),
    )
    payload = figure.as_dict()
    assert payload["exact_value"] == "48240.18"
    assert payload["grade"] == "corroborated"
    assert payload["record_ids"] == ["statement-1"]
    assert isinstance(Decimal(payload["exact_value"]), Decimal)


def test_figure_rejects_float_values():
    with pytest.raises(TypeError):
        FigureView("x", 1.2, "$1.20", "USD", "balance", FigureGrade.VERIFIED, "Verified", "exact", "today", "one record")


def test_panel_states_and_action_outcomes_are_closed():
    assert PanelState.NEEDS_INPUT.value == "needs_input"
    assert ActionOutcome("proposal", "Waiting for confirmation").as_dict()["kind"] == "proposal"
    with pytest.raises(ValueError):
        ActionOutcome("ok", "ambiguous")
    with pytest.raises(ValueError):
        ActionOutcome("refused", "No", reason=None)
