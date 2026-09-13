"""Bounded decoding of transfer suggestion evidence from one SQL revision."""

import json


MAX_TRANSFER_JSON_DEPTH = 32
MAX_TRANSFER_JSON_NODES = 10_000
MAX_TRANSFER_CONTAINER_ITEMS = 200
MAX_TRANSFER_CANDIDATE_KEY_BYTES = 512


def decode(encoded, expected, *, maximum_bytes: int):
    if not isinstance(encoded, str) or len(encoded.encode("utf-8")) > maximum_bytes:
        raise ValueError("transfer JSON exceeds its byte bound")
    try:
        value = json.loads(encoded)
    except (TypeError, ValueError, RecursionError) as exc:
        raise ValueError("transfer JSON is invalid") from exc
    if not isinstance(value, expected):
        raise ValueError("transfer JSON has the wrong shape")
    stack = [(value, 1)]
    visited = 0
    while stack:
        item, depth = stack.pop()
        visited += 1
        if visited > MAX_TRANSFER_JSON_NODES or depth > MAX_TRANSFER_JSON_DEPTH:
            raise ValueError("transfer JSON exceeds its nested work bound")
        if isinstance(item, dict):
            if len(item) > MAX_TRANSFER_CONTAINER_ITEMS:
                raise ValueError("transfer JSON exceeds its container bound")
            stack.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            if len(item) > MAX_TRANSFER_CONTAINER_ITEMS:
                raise ValueError("transfer JSON exceeds its container bound")
            stack.extend((child, depth + 1) for child in item)
    return value


def candidate_keys(value, *, maximum_count: int = 200):
    if (not isinstance(value, list) or len(value) > maximum_count
            or any(not isinstance(key, str) or not key
                   or len(key.encode("utf-8")) > MAX_TRANSFER_CANDIDATE_KEY_BYTES
                   for key in value)):
        raise ValueError("transfer candidates exceed their key or count bound")
    return value
