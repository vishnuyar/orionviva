"""Adapter contract. Product embryo — keep boring, typed, and honest."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


class AdapterError(Exception):
    """A model call failed in a way the runner should record and surface."""


@dataclass(frozen=True)
class PageImage:
    """One rendered document page, ready for a multimodal request."""

    page_number: int          # 1-based
    png_bytes: bytes
    sha256: str


@dataclass(frozen=True)
class ModelResult:
    """Everything the runner needs, with nothing thrown away (T3).

    ``request`` and ``response`` are the verbatim JSON payloads sent and
    received — raw capture happens on these, not on any parsed view.
    """

    text: str                     # the model's text output (unparsed)
    resolved_model: str           # model identity AS REPORTED by the endpoint (T8)
    input_tokens: int
    output_tokens: int
    cost_usd: float               # computed from candidate cost config
    latency_s: float
    request: dict[str, Any]      # verbatim request body (images elided by hash)
    response: dict[str, Any]     # verbatim response body


class ModelAdapter(Protocol):
    """One extraction call: pages + prompt in, ModelResult out. Nothing else.

    Adapters have no tools, no write access, no retries-with-mutation —
    structurally bounded per the model trust policy's guardrails.
    """

    def extract(self, pages: list[PageImage], prompt: str) -> ModelResult: ...


def elide_images(body: dict[str, Any], hashes: list[str]) -> dict[str, Any]:
    """Return a copy of a request body with image payloads replaced by their
    hashes. Raw page bytes are already stored once, content-addressed, in the
    page cache — duplicating megabytes of base64 into every run record would
    bloat the log without adding evidence. The hash preserves the audit chain:
    record -> page hash -> exact bytes."""
    import copy
    import json

    # Cheap deep copy via JSON round-trip is fine: bodies are JSON by construction.
    out = copy.deepcopy(body)
    replaced = iter(hashes)

    def _walk(node: Any) -> None:
        if isinstance(node, dict):
            # Anthropic style: {"type":"image","source":{"type":"base64","data":...}}
            if node.get("type") == "image" and isinstance(node.get("source"), dict):
                node["source"] = {"elided_png_sha256": next(replaced, "?")}
                return
            # OpenAI style: {"type":"image_url","image_url":{"url":"data:image/png;base64,..."}}
            if node.get("type") == "image_url" and isinstance(node.get("image_url"), dict):
                node["image_url"] = {"elided_png_sha256": next(replaced, "?")}
                return
            for v in node.values():
                _walk(v)
        elif isinstance(node, list):
            for v in node:
                _walk(v)

    _walk(out)
    # Guard: the elided body must remain valid JSON (it is, by construction).
    json.dumps(out)
    return out
