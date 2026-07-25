"""Adapter contract. Product embryo — keep boring, typed, and honest."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Protocol


class AdapterError(Exception):
    """A model call failed in a way the runner should record and surface."""


# --------------------------------------------------------- continuation driver

# A long answer (a statement with hundreds of transactions, a big merchant batch)
# can exceed the model's output budget, so the provider truncates mid-text and
# reports finish_reason "length". Re-asking from scratch just truncates again, so
# we ask the model to *continue* from the partial and stitch the pieces — bounded
# so a runaway can't loop forever. This lived inside one adapter; it belongs to
# every adapter, so it lives here and both drive through it (T-modular: one place
# to reason about truncation safety, not per-provider copies that drift).
MAX_CONTINUATIONS = 6
CONTINUE_INSTRUCTION = (
    "Continue the output from exactly where it stopped. Output ONLY the remaining "
    "characters — do not repeat anything already produced, no code fence, no prose.")


@dataclass
class Turn:
    """One model round-trip: the text it returned plus this call's accounting.
    Adapters produce these; :func:`run_to_completion` stitches a sequence into a
    single :class:`ModelResult`."""

    text: str
    finish_reason: str = ""          # normalized: "length" means truncated
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    latency_s: float = 0.0
    resolved_model: str = ""
    request: dict[str, Any] | None = None   # elided; captured from the FIRST turn
    response: dict[str, Any] = field(default_factory=dict)


def run_to_completion(call_once: Callable[[str, int], Turn],
                      max_continuations: int = MAX_CONTINUATIONS) -> ModelResult:
    """Drive a completion to a natural stop, continuing across truncation.

    ``call_once(accumulated, attempt)`` performs exactly one round-trip and returns
    a :class:`Turn`: attempt 0 is the full first request (images + prompt); each
    later attempt continues from ``accumulated`` (no images) when the previous turn
    came back ``finish_reason == "length"``. The adapter owns request-shaping (its
    message format, json_mode, provider quirks); this owns the loop, the bound, and
    the accounting — so every adapter gets identical truncation safety for free."""
    accumulated = ""
    in_tok = out_tok = 0
    cost = latency = 0.0
    finish = resolved = ""
    first_request: dict[str, Any] | None = None
    last_response: dict[str, Any] = {}
    for attempt in range(max_continuations + 1):
        turn = call_once(accumulated, attempt)
        accumulated += turn.text
        in_tok += turn.input_tokens
        out_tok += turn.output_tokens
        cost += turn.cost_usd
        latency += turn.latency_s
        finish = turn.finish_reason
        resolved = turn.resolved_model or resolved
        if turn.response:
            last_response = turn.response
        if first_request is None and turn.request is not None:
            first_request = turn.request
        if finish != "length":
            break
    return ModelResult(
        text=accumulated, resolved_model=resolved, input_tokens=in_tok,
        output_tokens=out_tok, cost_usd=cost, latency_s=latency,
        request=first_request or {}, response=last_response, finish_reason=finish)


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
    finish_reason: str = ""      # "stop" | "length" (truncated) | ...


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
