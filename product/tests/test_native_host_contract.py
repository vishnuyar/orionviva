"""Acceptance checks for the sidecar's declared operation contract.

The subject is the Python sidecar and the Rust host that speaks to it, plus one
literal on the far side of the boundary: the refusal code the interface reads a
reply by. Whether the interface sends the operation names and payload fields
the sidecar serves is still the Node checker's half.
"""

from __future__ import annotations

import ast
import io
import json
import re
from pathlib import Path

import pytest

from viva.desktop_bridge.__main__ import Sidecar, _open_vault
from viva.desktop_bridge.handlers import (CONVERSATION_OPERATIONS,
                                           DOCUMENTS_OPERATIONS,
                                           RESCAN_OPERATIONS,
                                           REVIEW_OPERATIONS,
                                           SETTINGS_OPERATIONS,
                                           TRANSFER_OPERATIONS,
                                           default_handlers,
                                           handlers_for_opened_vault)
from viva.desktop_bridge.rpc import dispatch_frame
from viva.desktop_bridge.surface_read import _read_request
from viva.surface import (
    BRIDGE_HANDSHAKE,
    BRIDGE_OPEN_VAULT,
    SETTINGS_READ,
    CURRENT_PROTOCOL,
    SURFACE_CAPABILITIES,
    SURFACE_READ,
    operation_names,
)


ROOT = Path(__file__).parents[2]
TAURI_DIR = ROOT / "desktop" / "src-tauri"
TAURI_CONFIG = TAURI_DIR / "tauri.conf.json"
HOST_SOURCE = TAURI_DIR / "src" / "main.rs"
BRIDGE_PACKAGE = ROOT / "product" / "viva" / "desktop_bridge"
INTERFACE_CONTRACTS = ROOT / "desktop" / "src" / "bridge" / "contracts.ts"
SIDECAR_NAME = "viva-desktop-bridge"

# Where the interface declares the one refusal code it reads as the sidecar
# having taken a request and said no. The value is read out rather than written
# here, so this compares two declarations instead of restating one.
REFUSAL_DECLARATION = re.compile(r'export const REQUEST_REFUSED = "([^"]+)"')

# The reviewed payload contract: what each operation accepts from a caller.
PAYLOAD_FIELDS: dict[str, set[str]] = {
    BRIDGE_HANDSHAKE: set(),
    # `create` is the person's own word for making a vault where they said to.
    # It defaults to false, so a path typed with a letter wrong is refused
    # rather than answered with a brand-new empty vault.
    BRIDGE_OPEN_VAULT: {"vault_directory", "passphrase", "create"},
    SURFACE_CAPABILITIES: set(),
    SURFACE_READ: {"surface", "parameters", "job_id"},
    REVIEW_OPERATIONS["answer"]: {"question_id", "said"},
    REVIEW_OPERATIONS["decline"]: {"question_id", "reason"},
    # One field, and that is the whole fence: a caller with nowhere to put an
    # identity cannot assert one, so the constraint is kept by the shape of the
    # request rather than by a check that could be relaxed.
    DOCUMENTS_OPERATIONS["upload"]: {"path"},
    # A stop names the work and nothing else. A cancel carrying a path would be
    # a caller asserting which work an identity stands for, which is the same
    # fence the upload's single field keeps from the other side.
    DOCUMENTS_OPERATIONS["cancel"]: {"job_id"},
    # A copy out names where to write it. A copy back names what to read, where
    # to put it, and the passphrase that proves it can be read — the third is
    # there because a restore is verified by being opened, and nothing but the
    # engine can open it.
    TRANSFER_OPERATIONS["export"]: {"archive"},
    TRANSFER_OPERATIONS["restore"]: {"archive", "directory", "passphrase"},
    # A pass goes over the whole vault, so the request carries nothing. A field
    # naming part of it would be a caller asserting a scope the sweep does not
    # have, and the fence is the shape of the request.
    RESCAN_OPERATIONS["rescan"]: set(),
    # Settings are asked before a vault exists, so they are in the baseline
    # allowlist and declare their fields here like everything else. The key is
    # among the confirm fields and among no others: it travels in one request
    # and is never on a proposal, in a reply or in a digest.
    # A question, and whether its text will be in front of the person. The
    # second is a fact about the caller's own screen and the input to the rule
    # that a figure is never spoken with nowhere to check it — not a switch for
    # speech, which is why there is no field here that could be one.
    CONVERSATION_OPERATIONS["ask"]: {"question", "mirrored"},
    SETTINGS_READ: set(),
    SETTINGS_OPERATIONS["propose"]: {"kind", "locale", "currency", "adapter",
                                     "model", "base_url"},
    SETTINGS_OPERATIONS["confirm"]: {"kind", "digest", "key", "locale",
                                     "currency", "adapter", "model", "base_url"},
}

# Where the sidecar declares the fields it will accept, per operation.
PAYLOAD_VALIDATORS: dict[str, tuple[Path, str]] = {
    BRIDGE_OPEN_VAULT: (BRIDGE_PACKAGE / "__main__.py", "_open_vault"),
    SURFACE_READ: (BRIDGE_PACKAGE / "surface_read.py", "_read_request"),
    REVIEW_OPERATIONS["answer"]: (BRIDGE_PACKAGE / "review_actions.py", "_answer_request"),
    REVIEW_OPERATIONS["decline"]: (BRIDGE_PACKAGE / "review_actions.py", "_decline_request"),
    DOCUMENTS_OPERATIONS["upload"]: (BRIDGE_PACKAGE / "document_actions.py", "_upload_request"),
    DOCUMENTS_OPERATIONS["cancel"]: (BRIDGE_PACKAGE / "document_actions.py", "_cancel_request"),
    TRANSFER_OPERATIONS["restore"]: (BRIDGE_PACKAGE / "vault_actions.py", "_restore_request"),
    RESCAN_OPERATIONS["rescan"]: (BRIDGE_PACKAGE / "rescan_actions.py", "_no_fields"),
    CONVERSATION_OPERATIONS["ask"]: (BRIDGE_PACKAGE / "conversation_actions.py",
                                     "_ask_request"),
}

# The reviewed request contract: what the protocol decoder reads off a frame.
REQUEST_FRAME_FIELDS = {"protocol", "request_id", "operation", "payload"}
REQUIRED_REQUEST_FIELDS = ("protocol", "request_id", "operation")

# A complete, valid payload for each operation. A probe adds one undeclared
# field to these, so nothing but the allowlist can refuse it.
UNDECLARED_FIELD = "unexpected_field"
COMPLETE_PAYLOADS: dict[str, dict[str, object]] = {
    BRIDGE_HANDSHAKE: {},
    SURFACE_CAPABILITIES: {},
    SURFACE_READ: {"surface": "overview", "parameters": {}, "job_id": "job-id"},
}

# The host declares which operations survive a sidecar restart here.
RETRY_DECLARATION = "let may_recover = matches!("
RETRY_PATTERN = "Some("


def _served_operations() -> set[str]:
    """Return every operation a fully opened sidecar answers.

    The vault is never touched: the handlers hold it and only reach for it when
    a frame arrives, so an opened-vault allowlist can be built without one."""
    dispatcher = handlers_for_opened_vault(object())
    return set(dispatcher.handlers) | {BRIDGE_OPEN_VAULT}


def _declared_payload_fields(module: Path, function: str) -> set[str]:
    """Return the payload field names one sidecar validator accepts."""
    tree = ast.parse(module.read_text(encoding="utf-8"), filename=str(module))
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or node.name != function:
            continue
        for statement in ast.walk(node):
            if (
                isinstance(statement, ast.Assign)
                and len(statement.targets) == 1
                and isinstance(statement.targets[0], ast.Name)
                and statement.targets[0].id == "allowed"
            ):
                return {ast.literal_eval(element) for element in statement.value.elts}
    raise AssertionError(
        f"{module.name}:{function} no longer declares an accepted payload field set"
    )


def _frame(operation: str, **payload) -> str:
    return json.dumps({
        "protocol": CURRENT_PROTOCOL.wire(),
        "request_id": "request-id",
        "operation": operation,
        "payload": payload,
    })


def _response_frame_fields() -> set[str]:
    """Return every field name the protocol puts on a frame it sends back."""
    handlers = default_handlers().handlers
    answered = json.loads(dispatch_frame(_frame(BRIDGE_HANDSHAKE), handlers))
    refused = json.loads(dispatch_frame("{}", handlers))
    buffer = io.StringIO()
    Sidecar(buffer)._write_event("request-id", {"status": "started"})
    progress = json.loads(buffer.getvalue())
    return set(answered) | set(refused) | set(progress)


def _host_source() -> str:
    assert HOST_SOURCE.is_file(), f"the native host source is missing: {HOST_SOURCE}"
    return HOST_SOURCE.read_text(encoding="utf-8")


def _host_retry_operations() -> set[str]:
    """Return the operations the host declares safe to replay after a restart."""
    source = _host_source()
    start = source.find(RETRY_DECLARATION)
    assert start != -1, (
        f"{HOST_SOURCE.name} no longer declares which operations may be replayed "
        "after the sidecar dies, so retry safety cannot be checked"
    )
    block = source[start : source.index(");", start)]
    arm = block.find(RETRY_PATTERN)
    assert arm != -1, (
        f"{HOST_SOURCE.name} declares replayable operations in a shape this gate "
        "cannot read, so retry safety cannot be checked"
    )
    opening = arm + len(RETRY_PATTERN)
    return set(re.findall(r'"([^"]+)"', block[opening : block.index(")", opening)]))


def _host_frame_fields() -> set[str]:
    """Return every frame field name the host reads or writes.

    The pattern accepts any identifier spelling, so a field renamed to the
    casing used on the other side of this boundary is still seen.
    """
    return set(
        re.findall(r'\.(?:get|entry)\("([A-Za-z_][A-Za-z0-9_]*)"\)', _host_source())
    )


def test_native_host_declares_tauri_configuration_and_named_sidecar():
    assert TAURI_CONFIG.is_file(), (
        "native host is missing desktop/src-tauri/tauri.conf.json"
    )
    config = json.loads(TAURI_CONFIG.read_text())

    external_bins = config.get("bundle", {}).get("externalBin", [])
    assert f"binaries/{SIDECAR_NAME}" in external_bins


def test_named_sidecar_maps_to_the_python_module_entrypoint():
    entrypoint = BRIDGE_PACKAGE / "__main__.py"
    assert entrypoint.is_file()
    source = entrypoint.read_text()
    assert 'if __name__ == "__main__":' in source
    assert "sys.stdin" in source
    assert "sys.stdout" in source


def test_the_operation_table_the_allowlist_and_the_payload_fields_agree():
    served = _served_operations()

    assert served, "the sidecar serves no operations; this gate has lost its grip"
    # The table declares one operation per action the registry names, which is
    # more than any allowlist admits: an action with no handler is a declared
    # operation the sidecar refuses. What must never happen is the other
    # direction — a handler answering something the table never declared.
    assert not served - operation_names(), (
        "the sidecar answers operations the declared table does not hold: "
        f"{sorted(served - operation_names())}"
    )
    assert set(PAYLOAD_FIELDS) == served, (
        "every operation the sidecar serves declares a payload field set: "
        f"{sorted(set(PAYLOAD_FIELDS) ^ served)}"
    )

    for operation, (module, function) in PAYLOAD_VALIDATORS.items():
        assert module.is_file(), f"sidecar validator is missing: {module}"
        assert _declared_payload_fields(module, function) == PAYLOAD_FIELDS[operation], (
            f"{operation} enforces a different payload field set than the "
            "contract declares"
        )


def test_the_sidecar_refuses_a_payload_field_no_operation_declares(tmp_path):
    """Each probe is a payload that is valid but for one undeclared field.

    A payload that is otherwise incomplete would be refused by the required
    field checks, which would satisfy this test while the allowlist did
    nothing.
    """
    handlers = default_handlers().handlers
    for operation in (BRIDGE_HANDSHAKE, SURFACE_CAPABILITIES):
        with pytest.raises(ValueError):
            handlers[operation]({**COMPLETE_PAYLOADS[operation], UNDECLARED_FIELD: "v"})

    with pytest.raises(ValueError) as refusal:
        _read_request({**COMPLETE_PAYLOADS[SURFACE_READ], UNDECLARED_FIELD: "v"})
    assert UNDECLARED_FIELD in str(refusal.value), (
        "the refusal must name the field it rejected"
    )

    with pytest.raises(ValueError) as refusal:
        _open_vault({
            "vault_directory": str(tmp_path),
            "passphrase": "synthetic-passphrase",
            UNDECLARED_FIELD: "v",
        })
    assert UNDECLARED_FIELD in str(refusal.value), (
        "the refusal must name the field it rejected"
    )


def test_the_host_only_retries_operations_the_sidecar_serves():
    """The replay set is a claim about crash recovery, not about contract parity.

    A renamed operation would leave the host's arm matching nothing, and
    recovery would stop working with no other signal.
    """
    retried = _host_retry_operations()

    assert retried, (
        "the host declares no replayable operations; either recovery was "
        "removed or this gate stopped finding the declaration"
    )
    unserved = retried - _served_operations()
    assert not unserved, (
        "the host would replay operations the sidecar does not serve: "
        f"{sorted(unserved)}"
    )


def _refusing_handler(payload: dict[str, object]) -> object:
    raise ValueError("synthetic refusal")


def test_the_interface_reads_a_refusal_by_the_code_the_sidecar_emits():
    """The code the sidecar emits for a request it will not take is the code
    the interface declares it reads.

    The interface tells a person their vault refused the request only for this
    code, and shows a reply it could not read for every other, so the two
    declarations are compared rather than restated.
    """
    source = INTERFACE_CONTRACTS.read_text(encoding="utf-8")
    declared = REFUSAL_DECLARATION.search(source)
    assert declared, (
        f"{INTERFACE_CONTRACTS.name} declares no refusal code, so the interface "
        "can no longer tell a request the sidecar refused from one it never served"
    )

    undecodable = json.loads(dispatch_frame("{}", {}))
    raised = json.loads(dispatch_frame(
        _frame("probe.refuses"), {"probe.refuses": _refusing_handler}))
    emitted = {undecodable["error"]["code"], raised["error"]["code"]}

    assert emitted == {declared.group(1)}, (
        f"the sidecar refuses a request with {sorted(emitted)} and the "
        f"interface reads {declared.group(1)!r}"
    )


def test_every_frame_field_the_host_names_is_one_the_protocol_defines():
    handlers = default_handlers().handlers
    for field in REQUIRED_REQUEST_FIELDS:
        frame = json.loads(_frame(BRIDGE_HANDSHAKE))
        del frame[field]
        response = json.loads(dispatch_frame(json.dumps(frame), handlers))
        assert not response["ok"], f"the decoder accepted a frame with no {field}"

    named = _host_frame_fields()
    assert named, "the host names no frame fields; this gate has lost its grip"

    defined = REQUEST_FRAME_FIELDS | _response_frame_fields()
    unknown = named - defined
    assert not unknown, (
        f"the host names frame fields the protocol does not define: {sorted(unknown)}"
    )
