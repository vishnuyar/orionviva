"""Anthropic Messages API adapter — plain HTTP, no SDK.

The Messages API is stable, documented, and small enough that ~100 lines of
inspectable code beat an SDK dependency on the trust path. If Anthropic ships
a breaking change, the exam fails loudly and we update one file.
"""

from __future__ import annotations

import base64
import time

import httpx

from .spec import ModelSpec
from .base import (AdapterError, PageImage, Turn, elide_images,
                   run_to_completion)

_API_URL = "https://api.anthropic.com/v1/messages"
_API_VERSION = "2023-06-01"


class AnthropicAdapter:
    def __init__(self, candidate: ModelSpec):
        self.candidate = candidate

    def extract(self, pages: list[PageImage], prompt: str) -> ModelResult:
        c = self.candidate
        first_content: list[dict] = []
        for page in pages:
            first_content.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": base64.b64encode(page.png_bytes).decode("ascii"),
                    },
                }
            )
        first_content.append({"type": "text", "text": prompt})

        def call_once(accumulated: str, attempt: int) -> Turn:
            # Continuation on Anthropic is an assistant *prefill*: re-send the
            # prompt (text only, no images) and hand back the partial as an
            # assistant turn; the model continues it. The API forbids trailing
            # whitespace on a prefill, so it is stripped for the request only —
            # the stitched text keeps the model's own spacing.
            if attempt == 0:
                messages = [{"role": "user", "content": first_content}]
            else:
                messages = [
                    {"role": "user", "content": [{"type": "text", "text": prompt}]},
                    {"role": "assistant", "content": accumulated.rstrip()},
                ]
            body = {
                "model": c.model,
                "max_tokens": c.max_tokens,
                "temperature": c.temperature,
                "messages": messages,
            }

            started = time.monotonic()
            try:
                resp = httpx.post(
                    _API_URL,
                    json=body,
                    headers={
                        "x-api-key": c.api_key() or "",
                        "anthropic-version": _API_VERSION,
                    },
                    timeout=c.timeout_s,
                )
            except httpx.HTTPError as e:
                raise AdapterError(
                    f"[{c.name}] HTTP failure calling Anthropic after "
                    f"{time.monotonic() - started:.1f}s (timeout {c.timeout_s}s, "
                    f"attempt {attempt + 1}): {e}") from e
            latency = time.monotonic() - started

            if resp.status_code != 200:
                raise AdapterError(
                    f"[{c.name}] Anthropic returned {resp.status_code}: {resp.text[:2000]}"
                )
            data = resp.json()

            text = "".join(
                block.get("text", "")
                for block in data.get("content", [])
                if block.get("type") == "text"
            )
            # Anthropic's own name for truncation is stop_reason "max_tokens";
            # normalize it to "length" so the shared driver continues.
            stop = data.get("stop_reason") or ""
            finish = "length" if stop == "max_tokens" else stop
            usage = data.get("usage", {})
            in_tok = int(usage.get("input_tokens", 0))
            out_tok = int(usage.get("output_tokens", 0))
            step_cost = (
                in_tok * c.cost_per_mtok_in + out_tok * c.cost_per_mtok_out
            ) / 1_000_000.0

            return Turn(
                text=text, finish_reason=finish, input_tokens=in_tok,
                output_tokens=out_tok, cost_usd=step_cost, latency_s=latency,
                resolved_model=str(data.get("model", c.model)),
                request=(elide_images(body, [p.sha256 for p in pages])
                         if attempt == 0 else None),
                response=data)

        # A spec may say "one shot, no stitching" — see ModelSpec.max_continuations.
        if c.max_continuations is None:
            return run_to_completion(call_once)
        return run_to_completion(call_once, max_continuations=c.max_continuations)
