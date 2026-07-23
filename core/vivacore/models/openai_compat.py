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

from .spec import ModelSpec
from .base import AdapterError, ModelResult, PageImage, elide_images

# A statement with many transactions can produce JSON longer than max_tokens, so
# the provider truncates (finish_reason="length") mid-JSON. Rather than re-ask
# from scratch (which truncates again), we ask the model to *continue* from where
# it stopped and stitch the parts — bounded so a runaway can't loop forever.
_MAX_CONTINUATIONS = 6
_CONTINUE = ("Continue the JSON output from exactly where it stopped. Output "
             "ONLY the remaining characters — do not repeat anything already "
             "produced, no code fence, no prose.")


class OpenAICompatAdapter:
    def __init__(self, candidate: ModelSpec):
        self.candidate = candidate
        assert candidate.base_url, "openai-compatible candidates carry a base_url"
        self.url = candidate.base_url.rstrip("/") + "/chat/completions"

    def extract(self, pages: list[PageImage], prompt: str) -> ModelResult:
        c = self.candidate
        images: list[dict] = []
        for page in pages:
            b64 = base64.b64encode(page.png_bytes).decode("ascii")
            images.append({"type": "image_url",
                           "image_url": {"url": f"data:image/png;base64,{b64}"}})

        is_openrouter = "openrouter.ai" in (c.base_url or "")
        headers = {}
        key = c.api_key()
        if key:
            headers["Authorization"] = f"Bearer {key}"
        if is_openrouter:
            headers["HTTP-Referer"] = "https://orionviva.com"
            headers["X-Title"] = "viva-bench"

        # First turn: images + the prompt (which already carries the statement's
        # embedded text). Continuation turns drop the heavy images — the embedded
        # text is re-sent in the prompt, so the model can still see every line
        # without the multi-megabyte image payload.
        messages = [{"role": "user", "content": images + [{"type": "text", "text": prompt}]}]

        accumulated = ""
        in_tok = out_tok = 0
        cost = 0.0
        latency = 0.0
        finish = ""
        first_request = None
        last_response: dict = {}

        for attempt in range(_MAX_CONTINUATIONS + 1):
            body = {
                "model": c.model,
                "max_tokens": c.max_tokens,
                "temperature": c.temperature,
                "messages": messages,
            }
            if c.json_mode and attempt == 0:
                # Guaranteed-valid JSON on the first turn; continuation turns emit
                # a raw fragment, so json_mode is off for those.
                body["response_format"] = {"type": "json_object"}
            if is_openrouter:
                body["usage"] = {"include": True}

            started = time.monotonic()
            try:
                resp = httpx.post(self.url, json=body, headers=headers, timeout=c.timeout_s)
            except httpx.HTTPError as e:
                raise AdapterError(f"[{c.name}] HTTP failure calling {self.url}: {e}") from e
            latency += time.monotonic() - started
            if resp.status_code != 200:
                raise AdapterError(
                    f"[{c.name}] {self.url} returned {resp.status_code}: {resp.text[:2000]}")
            data = resp.json()
            last_response = data
            if first_request is None:
                first_request = elide_images(body, [p.sha256 for p in pages])

            try:
                choice = data["choices"][0]
                text = choice["message"]["content"] or ""
            except (KeyError, IndexError, TypeError) as e:
                raise AdapterError(
                    f"[{c.name}] response shape unexpected (not chat-completions?): "
                    f"{str(data)[:500]}") from e
            finish = choice.get("finish_reason") or ""

            usage = data.get("usage") or {}
            step_in = int(usage.get("prompt_tokens", 0))
            step_out = int(usage.get("completion_tokens", 0))
            in_tok += step_in
            out_tok += step_out
            reported_cost = usage.get("cost")
            if reported_cost is not None:
                try:
                    cost += float(reported_cost)
                except (TypeError, ValueError):
                    cost += (step_in * c.cost_per_mtok_in + step_out * c.cost_per_mtok_out) / 1_000_000.0
            else:
                cost += (step_in * c.cost_per_mtok_in + step_out * c.cost_per_mtok_out) / 1_000_000.0

            accumulated += text
            if finish != "length":
                break
            # Truncated — continue from the partial, without resending images.
            messages = [
                {"role": "user", "content": prompt},
                {"role": "assistant", "content": accumulated},
                {"role": "user", "content": _CONTINUE},
            ]

        return ModelResult(
            text=accumulated,
            resolved_model=str(last_response.get("model", c.model)),
            input_tokens=in_tok,
            output_tokens=out_tok,
            cost_usd=cost,
            latency_s=latency,
            request=first_request or {},
            response=last_response,
            finish_reason=finish,
        )
