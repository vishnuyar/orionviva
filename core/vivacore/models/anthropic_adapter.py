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
from .base import AdapterError, ModelResult, PageImage, elide_images

_API_URL = "https://api.anthropic.com/v1/messages"
_API_VERSION = "2023-06-01"


class AnthropicAdapter:
    def __init__(self, candidate: ModelSpec):
        self.candidate = candidate

    def extract(self, pages: list[PageImage], prompt: str) -> ModelResult:
        c = self.candidate
        content: list[dict] = []
        for page in pages:
            content.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": base64.b64encode(page.png_bytes).decode("ascii"),
                    },
                }
            )
        content.append({"type": "text", "text": prompt})

        body = {
            "model": c.model,
            "max_tokens": c.max_tokens,
            "temperature": c.temperature,
            "messages": [{"role": "user", "content": content}],
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
            raise AdapterError(f"[{c.name}] HTTP failure calling Anthropic: {e}") from e
        latency = time.monotonic() - started

        if resp.status_code != 200:
            raise AdapterError(
                f"[{c.name}] Anthropic returned {resp.status_code}: {resp.text[:2000]}"
            )
        data = resp.json()

        text_parts = [
            block.get("text", "")
            for block in data.get("content", [])
            if block.get("type") == "text"
        ]
        usage = data.get("usage", {})
        in_tok = int(usage.get("input_tokens", 0))
        out_tok = int(usage.get("output_tokens", 0))
        cost = (
            in_tok * c.cost_per_mtok_in + out_tok * c.cost_per_mtok_out
        ) / 1_000_000.0

        return ModelResult(
            text="".join(text_parts),
            resolved_model=str(data.get("model", c.model)),
            input_tokens=in_tok,
            output_tokens=out_tok,
            cost_usd=cost,
            latency_s=latency,
            request=elide_images(body, [p.sha256 for p in pages]),
            response=data,
        )
