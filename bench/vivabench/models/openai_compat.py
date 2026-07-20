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

        headers = {}
        key = c.api_key()
        if key:
            headers["Authorization"] = f"Bearer {key}"

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
        cost = (
            in_tok * c.cost_per_mtok_in + out_tok * c.cost_per_mtok_out
        ) / 1_000_000.0

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
