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
    with pytest.raises(ValueError):
        ProtocolVersion.parse("1.4.2")
    with pytest.raises(ValueError):
        ProtocolVersion.parse("1.-1")
    with pytest.raises(ValueError):
        ProtocolVersion(-1, 0)


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


@pytest.mark.parametrize("field", ["id", "measure", "as_of", "coverage"])
def test_figure_rejects_missing_identity_fields(field):
    kwargs = dict(
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
    )
    kwargs[field] = ""
    with pytest.raises(ValueError):
        FigureView(**kwargs)


def test_figure_rejects_float_values():
    with pytest.raises(TypeError):
        FigureView("x", 1.2, "$1.20", "USD", "balance", FigureGrade.VERIFIED, "Verified", "exact", "today", "one record")


def test_figure_rejects_blank_currency_and_keeps_json_safe_lists():
    figure = FigureView(
        id="net-worth",
        exact_value="48240.18",
        display="$48,240.18",
        currency=None,
        measure="balance",
        grade=FigureGrade.VERIFIED,
        grade_label="Verified",
        exactness="exact",
        as_of="2026-06-30",
        coverage="checking statements, Jan-Jun 2026",
    )
    payload = figure.as_dict()
    assert payload["currency"] is None
    assert payload["record_ids"] == []
    assert payload["provenance"] == []
    assert payload["caveats"] == []

    with pytest.raises(ValueError):
        FigureView(
            id="net-worth",
            exact_value="48240.18",
            display="$48,240.18",
            currency="",
            measure="balance",
            grade=FigureGrade.VERIFIED,
            grade_label="Verified",
            exactness="exact",
            as_of="2026-06-30",
            coverage="checking statements, Jan-Jun 2026",
        )


def test_panel_states_and_action_outcomes_are_closed():
    assert {state.value for state in PanelState} == {"absent", "ready", "partial", "needs_input", "unavailable", "failed"}
    assert {grade.value for grade in FigureGrade} == {"verified", "corroborated", "unverified", "conflicted"}
    assert ActionOutcome("proposal", "Waiting for confirmation").as_dict()["kind"] == "proposal"
    assert ActionOutcome("completed", "Done").as_dict()["kind"] == "completed"
    assert ActionOutcome("waiting", "Pending review").as_dict()["kind"] == "waiting"
    assert ActionOutcome("stale", "Out of date").as_dict()["kind"] == "stale"
    with pytest.raises(ValueError):
        ActionOutcome("ok", "ambiguous")
    with pytest.raises(ValueError):
        ActionOutcome("refused", "No", reason=None)
