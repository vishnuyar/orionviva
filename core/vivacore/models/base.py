"""The adapter contract, the shared continuation driver, and their types."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Protocol


class AdapterError(Exception):
    """A model call failed in a way the runner should record and surface."""


# --------------------------------------------------------- continuation driver

# An answer that exceeds the model's output budget comes back truncated
# mid-text with finish_reason "length". The driver below asks the model to
# continue from the partial and stitches the pieces, bounded by
# MAX_CONTINUATIONS so a runaway cannot loop forever. Every adapter shares it.
MAX_CONTINUATIONS = 6
CONTINUE_INSTRUCTION = (
    "Continue the output from exactly where it stopped. Output ONLY the remaining "
    "characters — do not repeat anything already produced, no code fence, no prose.")


@dataclass
class Turn:
    """One model round-trip: the text returned plus that call's accounting.

    Adapters produce these; :func:`run_to_completion` stitches a sequence of
    them into a single :class:`ModelResult`."""

    text: str
    finish_reason: str = ""          # normalized: "length" means truncated
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    latency_s: float = 0.0
    resolved_model: str = ""
    request: dict[str, Any] | None = None   # elided; set on the first turn only
    response: dict[str, Any] = field(default_factory=dict)


def run_to_completion(call_once: Callable[[str, int], Turn],
                      max_continuations: int = MAX_CONTINUATIONS) -> ModelResult:
    """Drive a completion to a natural stop, continuing across truncation.

    ``call_once(accumulated, attempt)`` performs exactly one round-trip and
    returns a :class:`Turn`: attempt 0 is the full first request (images +
    prompt); each later attempt continues from ``accumulated`` (no images) and
    is made only when the previous turn came back ``finish_reason == "length"``.
    At most ``max_continuations`` continuations are made, after which the
    stitched text is returned with ``finish_reason`` still "length".

    The adapter owns request-shaping; this owns the loop, the bound, and the
    accounting. Tokens, cost and latency are summed across turns; ``request`` is
    the first turn's and ``response`` the last turn's."""
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
    """The result of one extraction call, stitched across any continuations.

    ``request`` and ``response`` are the verbatim JSON payloads sent and
    received — raw capture happens on these, not on any parsed view.
    """

    text: str                     # the model's text output (unparsed)
    resolved_model: str           # model identity as reported by the endpoint
    input_tokens: int
    output_tokens: int
    cost_usd: float               # computed from candidate cost config
    latency_s: float
    request: dict[str, Any]      # verbatim request body (images elided by hash)
    response: dict[str, Any]     # verbatim response body
    finish_reason: str = ""      # "stop" | "length" (truncated) | ...


class ModelAdapter(Protocol):
    """One extraction call: pages + prompt in, ModelResult out.

    Adapters have no tools, no write access, and no retries-with-mutation.
    """

    def extract(self, pages: list[PageImage], prompt: str) -> ModelResult: ...


@dataclass(frozen=True)
class ChatTurn:
    """One conversational round-trip: the assistant message verbatim, the
    tool calls it carries (empty when the model answered in text), and the
    call's accounting.

    ``request`` and ``response`` are the verbatim JSON payloads sent and
    received — raw capture happens on these, exactly as it does for
    :class:`ModelResult`. Adapters that support conversation return one of
    these per round-trip; no continuation is attempted, because a tool call
    truncated mid-JSON is a malformed step for the caller to handle, not a
    fragment to stitch.
    """

    message: dict[str, Any]       # the assistant message, verbatim
    tool_calls: list              # the message's tool calls, [] when none
    text: str                     # the message's text content, "" when none
    finish_reason: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    latency_s: float
    resolved_model: str
    request: dict[str, Any]      # verbatim request body
    response: dict[str, Any]     # verbatim response body


def elide_images(body: dict[str, Any], hashes: list[str]) -> dict[str, Any]:
    """Return a copy of a request body with image payloads replaced by their
    page hashes.

    ``hashes`` is consumed in order, one per image node found, in either the
    Anthropic or the OpenAI image shape. The original body is not modified. The
    recorded hash is what keeps the audit chain intact: run record -> page hash
    -> the exact bytes in the content-addressed page cache."""
    import copy
    import json

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
    # Raises if the elided body is no longer JSON-serialisable.
    json.dumps(out)
    return out
