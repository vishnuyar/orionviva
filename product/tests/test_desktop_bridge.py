import json

import pytest

from viva.desktop_bridge import (
    BridgeProtocolError,
    decode_frame,
    default_handlers,
    dispatch_frame,
    encode_frame,
    JobProgressEvent,
    handlers_for_opened_vault,
    handlers_with_surface_provider,
    OpenedVaultSurfaceProvider,
)
from viva.desktop_bridge.review_actions import UnreadableOutcome, outcome_of
from viva.desktop_bridge import vault_surface
from viva.persona import moment
from viva.vault import Vault
from viva.surface import CURRENT_PROTOCOL, serialize_registry
from viva.surface import FigureView
from viva.surface.models import FigureGrade


def frame(**overrides):
    payload = {
        "protocol": "2.0",
        "request_id": "req-1",
        "operation": "bridge.handshake",
        "payload": {},
    }
    payload.update(overrides)
    return json.dumps(payload)


def test_handshake_is_versioned_and_framed():
    response = json.loads(dispatch_frame(frame(), default_handlers().handlers))

    assert response == {
        "protocol": "2.0",
        "request_id": "req-1",
        "ok": True,
        "result": {"protocol": "2.0", "transport": "json-lines"},
    }


def test_unknown_operations_are_refused_by_the_allowlist():
    response = json.loads(
        dispatch_frame(frame(operation="viva.surface.snapshot"), default_handlers().handlers)
    )

    assert response["ok"] is False
    assert response["error"]["code"] == "operation_not_allowed"


def test_default_surface_read_returns_live_reviewed_registry():
    response = json.loads(
        dispatch_frame(
            frame(operation="viva.surface.capabilities"),
            default_handlers().handlers,
        )
    )

    assert response["ok"] is True
    assert response["result"] == {
        "protocol": CURRENT_PROTOCOL.wire(),
        "capabilities": json.loads(serialize_registry()),
    }
    assert any(item["id"] == "review.questions" for item in response["result"]["capabilities"])


def test_surface_read_rejects_payload_fields():
    response = json.loads(
        dispatch_frame(
            frame(operation="viva.surface.capabilities", payload={"destination": "review"}),
            default_handlers().handlers,
        )
    )

    assert response["ok"] is False
    assert response["error"]["code"] == "invalid_request"
    assert "does not accept payload fields" in response["error"]["message"]


def test_surface_provider_is_injected_without_importing_vault_or_ui_code():
    calls = []

    def provider(payload):
        calls.append(payload)
        return {"panel": "overview", "state": "ready"}

    handlers = {"viva.surface.snapshot": provider}
    response = json.loads(
        dispatch_frame(
            frame(operation="viva.surface.snapshot", payload={}),
            handlers,
        )
    )

    assert response["ok"] is True
    assert response["result"] == {"panel": "overview", "state": "ready"}
    assert calls == [{}]


def test_injected_surface_handler_can_return_typed_json_data():
    handlers = default_handlers().handlers | {
        "viva.surface.snapshot": lambda payload: {"panel": payload["panel"], "state": "ready"}
    }

    response = json.loads(
        dispatch_frame(
            frame(operation="viva.surface.snapshot", payload={"panel": "overview"}),
            handlers,
        )
    )

    assert response["result"] == {"panel": "overview", "state": "ready"}


def test_surface_handler_can_return_a_json_safe_contract_model():
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
        coverage="checking and savings statements",
    )
    handlers = {"viva.surface.snapshot": lambda _payload: {"figure": figure.as_dict()}}

    response = json.loads(
        dispatch_frame(
            frame(operation="viva.surface.snapshot"),
            handlers,
        )
    )

    assert response["ok"] is True
    assert response["result"]["figure"]["exact_value"] == "48240.18"


def test_newer_minor_protocol_is_rejected_without_calling_handler():
    called = False

    def handler(_payload):
        nonlocal called
        called = True
        return {"state": "ready"}

    response = json.loads(
        dispatch_frame(
            frame(protocol="2.1", operation="viva.surface.snapshot"),
            {"viva.surface.snapshot": handler},
        )
    )

    assert response["ok"] is False
    assert response["error"]["code"] == "protocol_not_supported"
    assert called is False


def test_allowlist_snapshot_cannot_be_mutated_after_dispatcher_creation():
    dispatcher = default_handlers()

    with pytest.raises(TypeError):
        dispatcher.handlers["viva.surface.snapshot"] = lambda _payload: {}

    assert "viva.surface.snapshot" not in dispatcher.handlers


@pytest.mark.parametrize(
    "payload, message",
    [
        ({"protocol": "2.0", "operation": "bridge.handshake"}, "request_id"),
        ({"protocol": "2.0", "request_id": "x", "operation": ""}, "operation"),
        ({"protocol": "3.0", "request_id": "x", "operation": "bridge.handshake"}, "major"),
    ],
)
def test_malformed_or_incompatible_frames_fail_closed(payload, message):
    with pytest.raises(BridgeProtocolError, match=message):
        decode_frame(json.dumps(payload))


def test_encode_frame_is_json_lines_and_rejects_non_json_values():
    assert encode_frame({"ok": True}) == '{"ok":true}\n'
    with pytest.raises(BridgeProtocolError):
        encode_frame({"value": object()})


def test_progress_event_frames_are_json_safe_and_preserve_order():
    events = [
        {"event": "job.progress", "sequence": 1, "state": "started"},
        {"event": "job.progress", "sequence": 2, "state": "reading"},
        {"event": "job.progress", "sequence": 3, "state": "completed"},
    ]

    stream = "".join(encode_frame(event) for event in events)
    decoded = [json.loads(line) for line in stream.splitlines()]

    assert decoded == events
    assert [event["sequence"] for event in decoded] == [1, 2, 3]


def test_json_lines_dispatch_round_trip_handles_success_and_error_frames():
    """Exercise the line-oriented contract a stdio sidecar would expose."""

    stream = "".join(
        [
            encode_frame(json.loads(frame())),
            "not-json\n",
            encode_frame(json.loads(frame(operation="missing.operation"))),
        ]
    )

    responses = [
        json.loads(dispatch_frame(line, default_handlers().handlers))
        for line in stream.splitlines()
    ]

    assert responses[0]["ok"] is True
    assert responses[0]["request_id"] == "req-1"
    assert responses[1]["ok"] is False
    assert responses[1]["error"]["code"] == "invalid_request"
    assert responses[2]["ok"] is False
    assert responses[2]["error"]["code"] == "operation_not_allowed"


def test_json_lines_error_frame_preserves_request_id_for_bad_payload():
    bad_frame = json.dumps(
        {
            "protocol": CURRENT_PROTOCOL.wire(),
            "request_id": "stdio-7",
            "operation": "bridge.handshake",
            "payload": [],
        }
    )

    response = json.loads(dispatch_frame(bad_frame, default_handlers().handlers))

    assert response["request_id"] == "stdio-7"
    assert response["ok"] is False
    assert response["error"]["code"] == "invalid_request"


def test_malformed_dispatch_requests_return_error_frames_without_raising():
    response = json.loads(dispatch_frame("not-json", default_handlers().handlers))

    assert response == {
        "protocol": CURRENT_PROTOCOL.wire(),
        "request_id": "unknown",
        "ok": False,
        "error": {
            "code": "invalid_request",
            "message": "frame must contain valid JSON",
        },
    }


def test_handler_failures_are_returned_as_safe_error_frames():
    def broken_handler(_payload):
        raise RuntimeError("vault unavailable")

    response = json.loads(
        dispatch_frame(
            frame(operation="viva.surface.snapshot"),
            {"viva.surface.snapshot": broken_handler},
        )
    )

    assert response["ok"] is False
    assert response["error"]["code"] == "handler_failed"
    assert response["error"]["message"] == "vault unavailable"


def test_invalid_handshake_payload_is_returned_as_a_safe_error_frame():
    response = json.loads(
        dispatch_frame(
            frame(payload={"unexpected": True}),
            default_handlers().handlers,
        )
    )

    assert response["ok"] is False
    assert response["error"]["code"] == "invalid_request"


class StubVaultSurface:
    def read_surface(self, surface, parameters):
        return {"name": surface, "parameters": dict(parameters), "state": "ready"}


def test_injected_vault_surface_read_emits_progress_and_preserves_default_handlers():
    events = []
    dispatcher = handlers_with_surface_provider(StubVaultSurface(), events.append)

    response = json.loads(
        dispatch_frame(
            frame(
                operation="viva.surface.read",
                payload={"surface": "overview", "parameters": {"month": "2026-06"}, "job_id": "job-7"},
            ),
            dispatcher.handlers,
        )
    )

    assert response["result"] == {
        "surface": "overview",
        "job_id": "job-7",
        "data": {"name": "overview", "parameters": {"month": "2026-06"}, "state": "ready"},
    }
    assert [event.status for event in events] == ["started", "completed"]
    assert events[-1].as_dict()["completed"] == 1
    assert "viva.surface.capabilities" in dispatcher.handlers


def test_vault_surface_failure_emits_failed_progress_and_safe_error_frame():
    events = []

    class BrokenVault:
        def read_surface(self, _surface, _parameters):
            raise RuntimeError("vault unavailable")

    response = json.loads(
        dispatch_frame(
            frame(operation="viva.surface.read", payload={"surface": "overview"}),
            handlers_with_surface_provider(BrokenVault(), events.append).handlers,
        )
    )

    assert response["error"]["code"] == "handler_failed"
    assert events[-1].status == "failed"


def test_job_progress_event_rejects_invalid_ranges():
    with pytest.raises(ValueError, match="between zero and total"):
        JobProgressEvent("job-1", "started", 2, 1)


def test_opened_vault_provider_exposes_real_empty_vault_surfaces(tmp_path):
    vault = Vault.open(tmp_path / "vault", "pw")
    provider = OpenedVaultSurfaceProvider(vault)

    overview = provider.read_surface("overview", {"read_on": "2026-09-30"})
    documents = provider.read_surface("documents", {})
    review = provider.read_surface("review", {"limit": 5})

    assert overview == {
        "state": "ready",
        "issues": [],
        "caveats": [],
        "as_of": None,
        "accounts": [],
        "account_count": 0,
        "spending_by_currency": {},
        # A vault with nothing in it has no total, and says so. Silence is not
        # a refusal: a blank where a figure was yesterday reads as the product
        # being broken, which is worse and less true than what happened.
        "picture": {
            "coverage": moment("picture_no_figure"),
            "read_on": "2026-09-30",
            "figures": [],
            "withheld": [],
            "unplaced": [],
        },
    }
    # A panel earns its existence from data: an empty vault has no paperwork,
    # and says so rather than reporting a successful read of nothing.
    assert documents["state"] == "absent"
    assert documents["documents"] == []
    assert documents["holds"] == []
    assert documents["raw_document_count"] == 0
    assert documents["reading_sentence"] == ""
    assert review["state"] == "ready"
    assert review["questions"] == []
    assert review["total"] == 0


def test_opened_vault_provider_rejects_unknown_surface_and_parameters(tmp_path):
    provider = OpenedVaultSurfaceProvider(Vault.open(tmp_path / "vault", "pw"))

    with pytest.raises(ValueError, match="unsupported surface"):
        provider.read_surface("settings", {})
    with pytest.raises(ValueError, match="do not accept fields"):
        provider.read_surface("overview", {"account": "secret"})
    with pytest.raises(ValueError, match="positive integer"):
        provider.read_surface("review", {"limit": 0})
    with pytest.raises(ValueError, match="read_on must be a string"):
        provider.read_surface("overview", {"read_on": 20260930})


def test_the_day_a_picture_is_read_on_is_stated_or_is_the_day_it_is_asked_on(tmp_path, monkeypatch):
    """The read parameter and the payload field are one name end to end, and
    it is not the projection horizon a letter away from it. A caller may state
    the day, which is how a generated artifact stays the same bytes whenever it
    runs; with none stated the surface holds no clock and this side does."""
    provider = OpenedVaultSurfaceProvider(Vault.open(tmp_path / "vault", "pw"))
    monkeypatch.setattr(vault_surface, "_now", lambda: "2027-03-01")

    stated = provider.read_surface("overview", {"read_on": "2026-09-30"})
    unstated = provider.read_surface("overview", {})

    assert stated["picture"]["read_on"] == "2026-09-30"
    assert unstated["picture"]["read_on"] == "2027-03-01"
    # The horizon keeps its own name and its own meaning.
    assert stated["as_of"] is None


def test_opened_vault_allowlist_dispatches_real_surface_reads(tmp_path):
    vault = Vault.open(tmp_path / "vault", "pw")
    response = json.loads(
        dispatch_frame(
            frame(
                operation="viva.surface.read",
                payload={"surface": "overview", "job_id": "vault-job"},
            ),
            handlers_for_opened_vault(vault).handlers,
        )
    )

    assert response["ok"] is True
    assert response["result"]["surface"] == "overview"
    assert response["result"]["job_id"] == "vault-job"
    assert response["result"]["data"]["account_count"] == 0


def _review_frame(operation, payload):
    return frame(operation=operation, payload=payload)


def test_the_decline_verb_is_reachable_only_once_a_vault_is_open(tmp_path):
    """The verb an opened vault serves is served there and nowhere else. Before
    a vault is open the allowlist refuses it, which is the same refusal any
    unserved operation gets."""
    cold = json.loads(
        dispatch_frame(
            _review_frame("viva.review.decline",
                          {"question_id": "q-1", "reason": "not_now"}),
            default_handlers().handlers,
        )
    )

    assert cold["ok"] is False
    assert cold["error"]["code"] == "operation_not_allowed"

    vault = Vault.open(tmp_path / "vault", "pw")
    handlers = handlers_for_opened_vault(vault).handlers

    assert "viva.review.decline" in handlers
    assert "viva.documents.upload" in handlers


def test_an_action_the_registry_declares_without_a_handler_is_refused(tmp_path):
    """Every declared action is an operation; only the ones this build serves
    have a handler. The rest are refused by the allowlist rather than by
    silence — including the review capability's own `answer`, which this build
    declares and does not serve."""
    vault = Vault.open(tmp_path / "vault", "pw")
    handlers = handlers_for_opened_vault(vault).handlers

    for operation in ("viva.review.answer",):
        response = json.loads(
            dispatch_frame(_review_frame(operation, {}), handlers))

        assert response["ok"] is False, operation
        assert response["error"]["code"] == "operation_not_allowed"


def test_declining_a_question_that_is_not_open_refuses_with_a_reason(tmp_path):
    """A refusal is an ordinary reply, not an error frame: the reply carries a
    sentence for the person and a machine reason beside it. Setting aside
    something no longer being asked records nothing and says so."""
    vault = Vault.open(tmp_path / "vault", "pw")
    response = json.loads(
        dispatch_frame(
            _review_frame("viva.review.decline",
                          {"question_id": "no-such-question", "reason": "not_now"}),
            handlers_for_opened_vault(vault).handlers,
        )
    )

    assert response["ok"] is True
    assert response["result"]["kind"] == "refused"
    assert response["result"]["reason"] == "not_open"
    assert response["result"]["message"]


def test_review_action_payloads_are_fenced(tmp_path):
    """A decline names a question and carries a reason out of the reviewed set
    and nothing else. Anything further is refused before the engine is
    called."""
    vault = Vault.open(tmp_path / "vault", "pw")
    handlers = handlers_for_opened_vault(vault).handlers

    for operation, payload, message in (
        ("viva.review.decline", {"question_id": "", "reason": "not_now"}, "question_id"),
        ("viva.review.decline", {"question_id": "q", "reason": "bored"}, "reason must be one of"),
        ("viva.review.decline", {"question_id": "q", "said": "no"}, "does not accept"),
    ):
        response = json.loads(dispatch_frame(_review_frame(operation, payload), handlers))
        assert response["ok"] is False, (operation, payload)
        assert response["error"]["code"] == "invalid_request"
        assert message in response["error"]["message"]


def test_an_outcome_says_what_happened_rather_than_carrying_a_bare_ok():
    """Every branch reads a declaration the engine made, and never the shape of
    the reply: whether it was accepted, whether accepting it recorded anything,
    and the name it gave a refusal."""
    assert outcome_of({"ok": True, "recorded": True}).kind == "completed"
    assert outcome_of({"ok": True}).kind == "completed"
    refused = outcome_of({"ok": False, "why": "not_open", "message": "That one closed."})
    assert (refused.kind, refused.reason, refused.message) == (
        "refused", "not_open", "That one closed.")
    assert outcome_of({"ok": True, "recorded": False}).message, (
        "an outcome always carries a sentence for the person")


def test_an_answer_the_document_settles_is_not_reported_as_recorded():
    """A reply the engine declares recorded nothing reads as `waiting`, not as
    `completed`, and keeps the engine's own sentence."""
    outcome = outcome_of({"ok": True, "recorded": False,
                          "message": "The document itself settles this one."})

    assert outcome.kind == "waiting"
    assert outcome.message == "The document itself settles this one."


def test_a_reply_this_vocabulary_has_no_word_for_raises_rather_than_guessing():
    """Three shapes raise rather than mapping to the nearest word: a reply held
    for a confirmation, a reply that does not say whether it was accepted, and
    a refusal that names no reason."""
    for unreadable in (
        {"ok": True, "confirm": True, "proposal": {"scope": "attribute"}},
        {"action": "posted", "message": "Posted."},
        {"ok": False, "message": "No."},
    ):
        with pytest.raises(UnreadableOutcome):
            outcome_of(unreadable)
