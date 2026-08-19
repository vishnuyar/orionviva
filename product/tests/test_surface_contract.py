import re
from decimal import Decimal
from pathlib import Path

import pytest

from viva.surface import CURRENT_PROTOCOL, ActionOutcome, FigureView, PanelState, ProtocolVersion
from viva.surface.models import FigureGrade


def test_protocol_accepts_additive_minor_changes_only():
    assert CURRENT_PROTOCOL.accepts(ProtocolVersion(2, 0))
    assert not CURRENT_PROTOCOL.accepts(ProtocolVersion(2, 1))
    assert not CURRENT_PROTOCOL.accepts(ProtocolVersion(1, 0))


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
        provenance="Read from statement-1, page 1.",
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
    assert payload["provenance"] == ""
    assert payload["citations"] == []
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


def test_figure_declares_a_measure_the_vocabulary_holds():
    """A figure says what its number is OF, out of the closed vocabulary a
    figure declares from — one name wider than the one a hole asks from,
    because a figure may say nothing measured it and no hole may ask for that.

    A real number correctly graded is still a false sentence when it is put
    where something else belongs, so an unvocabularied word fails where the
    figure is built rather than where it is read."""
    from viva.quantity import KINDS, MEASURES, UNMEASURED

    def figure(measure: str) -> FigureView:
        return FigureView(
            id="account-figure",
            exact_value="48240.18",
            display="$48,240.18",
            currency="USD",
            measure=measure,
            grade=FigureGrade.VERIFIED,
            grade_label="verified",
            exactness="exact",
            as_of="2026-06-30",
            coverage="one account, as of one day",
        )

    for measure in MEASURES:
        assert figure(measure).as_dict()["measure"] == measure
    # The asymmetry, both ways round: what a figure may declare and a hole may
    # not ask for, and a word neither of them holds.
    assert UNMEASURED in MEASURES and UNMEASURED not in KINDS
    for measure in ("balance sheet", "BALANCE", "moneys"):
        with pytest.raises(ValueError):
            figure(measure)


def test_citation_routes_to_a_document_under_a_reviewed_relation():
    """A citation with no document routes nowhere, and a relation nobody
    reviewed is a claim about evidence this product does not make."""
    from viva.surface.models import Citation, CitationRelation

    cited = Citation(document_id="doc-1", page="7", label="closing balance")
    assert cited.as_dict() == {"document_id": "doc-1", "page": "7",
                               "label": "closing balance",
                               "relation": CitationRelation.ATTESTS.value}
    with pytest.raises(ValueError):
        Citation(document_id="")
    with pytest.raises(ValueError):
        Citation(document_id="doc-1", relation="proves")
    with pytest.raises(TypeError):
        Citation(document_id="doc-1", page=7)


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


# Where the shell and its native host declare the version they stamp on a
# frame, and the pattern each declares it with. The value is read out rather
# than written here, so this compares two declarations instead of restating
# one.
_HOSTS = {
    "desktop/src-tauri/src/main.rs":
        re.compile(r'const BRIDGE_PROTOCOL: &str = "([^"]+)"'),
    "desktop/src/bridge/contracts.ts":
        re.compile(r'export const BRIDGE_PROTOCOL = "([^"]+)"'),
}


def test_every_host_stamps_frames_with_the_protocol_the_sidecar_speaks():
    """The sidecar refuses a frame whose major version is not its own, so a
    host left behind at the old version is a shell that can send nothing and a
    green suite that says so nowhere."""
    root = Path(__file__).resolve().parents[2]
    declared = {}
    for name, pattern in _HOSTS.items():
        source = (root / name).read_text(encoding="utf-8")
        found = pattern.search(source)
        assert found, f"{name} declares no protocol version to stamp frames with"
        declared[name] = found.group(1)

    behind = {name: value for name, value in declared.items()
              if value != CURRENT_PROTOCOL.wire()}
    assert not behind, (
        f"the sidecar speaks {CURRENT_PROTOCOL.wire()} and these hosts stamp "
        f"something else: {behind}")


def test_no_host_writes_a_frame_protocol_beside_the_one_it_declares():
    """One declaration per host. A second literal is the half of a bump that
    gets forgotten."""
    root = Path(__file__).resolve().parents[2]
    stray = []
    for name in ("desktop/src/tauri-host.ts", "desktop/src-tauri/src/main.rs"):
        for line in (root / name).read_text(encoding="utf-8").splitlines():
            if "BRIDGE_PROTOCOL" in line:
                continue
            if re.search(r'protocol"?\s*[:=]\s*(json!\()?"\d+\.\d+"', line):
                stray.append(f"{name}: {line.strip()}")
    assert not stray, "a frame protocol is written as a literal:\n  " + "\n  ".join(stray)
