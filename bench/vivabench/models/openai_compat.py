"""OpenAI-compatible chat-completions adapter — the universal socket.

One adapter, many providers, differing only in base_url:

    OpenAI            https://api.openai.com/v1
    OpenRouter        https://openrouter.ai/api/v1
    Ollama (local)    http://localhost:11434/v1
    HF router         https://router.huggingface.co/v1
    LM Studio         http://localhost:1234/v1
    vLLM              http://<host>:8000/v1

Plain HTTP via httpx; same rationale as the Anthropic adapter.
"""

from __future__ import annotations

import base64
import time

import httpx

from ..config import Candidate
from .base import AdapterError, ModelResult, PageImage, elide_images


class OpenAICompatAdapter:
    def __init__(self, candidate: Candidate):
        self.candidate = candidate
        assert candidate.base_url, "openai-compatible candidates carry a base_url"
        self.url = candidate.base_url.rstrip("/") + "/chat/completions"

    def extract(self, pages: list[PageImage], prompt: str) -> ModelResult:
        c = self.candidate
        content: list[dict] = []
        for page in pages:
            b64 = base64.b64encode(page.png_bytes).decode("ascii")
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{b64}"},
                }
            )
        content.append({"type": "text", "text": prompt})

        body = {
            "model": c.model,
            "max_tokens": c.max_tokens,
            "temperature": c.temperature,
            "messages": [{"role": "user", "content": content}],
        }

        is_openrouter = "openrouter.ai" in (c.base_url or "")
        if is_openrouter:
            # Ask OpenRouter to return the exact charged cost, so the budget guard
            # runs on actuals rather than configured estimates.
            body["usage"] = {"include": True}

        headers = {}
        key = c.api_key()
        if key:
            headers["Authorization"] = f"Bearer {key}"
        if is_openrouter:
            # OpenRouter courtesy headers (identify the app; harmless).
            headers["HTTP-Referer"] = "https://orionviva.com"
            headers["X-Title"] = "viva-bench"

        started = time.monotonic()
        try:
            resp = httpx.post(self.url, json=body, headers=headers, timeout=c.timeout_s)
        except httpx.HTTPError as e:
            raise AdapterError(f"[{c.name}] HTTP failure calling {self.url}: {e}") from e
        latency = time.monotonic() - started

        if resp.status_code != 200:
            raise AdapterError(
                f"[{c.name}] {self.url} returned {resp.status_code}: {resp.text[:2000]}"
            )
        data = resp.json()

        try:
            text = data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as e:
            raise AdapterError(
                f"[{c.name}] response shape unexpected (not chat-completions?): "
                f"{str(data)[:500]}"
            ) from e

        usage = data.get("usage") or {}
        in_tok = int(usage.get("prompt_tokens", 0))
        out_tok = int(usage.get("completion_tokens", 0))
        # Prefer a provider-reported exact cost (OpenRouter returns usage.cost in
        # USD when asked); fall back to configured per-Mtoken rates otherwise.
        reported_cost = usage.get("cost")
        if reported_cost is not None:
            try:
                cost = float(reported_cost)
            except (TypeError, ValueError):
                cost = (in_tok * c.cost_per_mtok_in + out_tok * c.cost_per_mtok_out) / 1_000_000.0
        else:
            cost = (in_tok * c.cost_per_mtok_in + out_tok * c.cost_per_mtok_out) / 1_000_000.0

        return ModelResult(
            text=text,
            resolved_model=str(data.get("model", c.model)),
            input_tokens=in_tok,
            output_tokens=out_tok,
            cost_usd=cost,
            latency_s=latency,
            request=elide_images(body, [p.sha256 for p in pages]),
            response=data,
        )
