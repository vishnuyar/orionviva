"""Small JSON-lines RPC protocol used by the desktop bridge."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from typing import Any

from viva.surface import CURRENT_PROTOCOL, ProtocolVersion, ProtocolVersionError


class BridgeProtocolError(ValueError):
    """Raised when a frame cannot be safely accepted or serialized."""


def _protocol(value: Any) -> ProtocolVersion:
    if not isinstance(value, str):
        raise BridgeProtocolError("protocol must be a string")
    try:
        return ProtocolVersion.parse(value)
    except ProtocolVersionError as exc:
        raise BridgeProtocolError(str(exc)) from exc


def _request_id(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise BridgeProtocolError("request_id must be a non-empty string")
    return value


def decode_frame(frame: str | bytes) -> dict[str, Any]:
    """Decode one newline-delimited JSON frame into a validated request."""

    try:
        payload = json.loads(frame)
    except (TypeError, json.JSONDecodeError) as exc:
        raise BridgeProtocolError("frame must contain valid JSON") from exc
    if not isinstance(payload, dict):
        raise BridgeProtocolError("frame must be a JSON object")
    protocol = _protocol(payload.get("protocol"))
    if protocol.major != CURRENT_PROTOCOL.major:
        raise BridgeProtocolError("unsupported protocol major version")
    _request_id(payload.get("request_id"))
    operation = payload.get("operation")
    if not isinstance(operation, str) or not operation.strip():
        raise BridgeProtocolError("operation must be a non-empty string")
    request_payload = payload.get("payload", {})
    if not isinstance(request_payload, dict):
        raise BridgeProtocolError("payload must be a JSON object")
    return payload


def encode_frame(payload: Mapping[str, Any]) -> str:
    """Serialize one response as a compact JSON-lines frame."""

    try:
        return json.dumps(dict(payload), separators=(",", ":"), sort_keys=True) + "\n"
    except (TypeError, ValueError) as exc:
        raise BridgeProtocolError("response is not JSON serializable") from exc


def _error_frame(request_id: str, code: str, message: str) -> str:
    return encode_frame({
        "protocol": CURRENT_PROTOCOL.wire(),
        "request_id": request_id,
        "ok": False,
        "error": {"code": code, "message": message},
    })


def dispatch_frame(
    frame: str | bytes,
    handlers: Mapping[str, Callable[[dict[str, Any]], Any]],
) -> str:
    """Validate and dispatch a frame through an explicit handler allowlist."""

    try:
        request = decode_frame(frame)
    except BridgeProtocolError as exc:
        request_id = "unknown"
        try:
            decoded = json.loads(frame)
            if isinstance(decoded, dict) and isinstance(decoded.get("request_id"), str):
                request_id = decoded["request_id"]
        except (TypeError, json.JSONDecodeError):
            pass
        return _error_frame(request_id, "invalid_request", str(exc))
    request_protocol = _protocol(request["protocol"])
    request_id = request["request_id"]
    operation = request["operation"]
    handler = handlers.get(operation)
    if handler is None:
        return _error_frame(request_id, "operation_not_allowed", operation)
    if not CURRENT_PROTOCOL.accepts(request_protocol):
        return _error_frame(request_id, "protocol_not_supported", request["protocol"])
    payload=request["payload"]
    parameters=payload.get("parameters") if isinstance(payload,dict) else None
    documents_page=(operation=="viva.surface.read" and payload.get("surface")=="documents"
        and isinstance(parameters,dict) and parameters.get("contract_version")=="documents-page-v1")
    def bounded_response(encoded):
        if not documents_page or len(encoded.encode("utf-8"))<=100000:return encoded
        limited=_error_frame(request_id,"resource_limit","Documents response exceeds its byte bound")
        return limited if len(limited.encode("utf-8"))<=100000 else _error_frame("unknown","resource_limit","Documents response exceeds its byte bound")
    try:
        result = handler(request["payload"])
    except ValueError as exc:
        if documents_page and str(exc)=="resource_limit":
            return bounded_response(_error_frame(request_id,"resource_limit","Documents response exceeds its resource bound"))
        return bounded_response(_error_frame(request_id, "invalid_request", str(exc)))
    except Exception as exc:  # noqa: BLE001 - the bridge must not die on handler failure.
        return bounded_response(_error_frame(request_id, "handler_failed", str(exc)))
    return bounded_response(encode_frame({
        "protocol": CURRENT_PROTOCOL.wire(),
        "request_id": request_id,
        "ok": True,
        "result": result,
    }))
