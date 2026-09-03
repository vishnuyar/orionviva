"""OpenAI-compatible chat-completions adapter.

One adapter, many providers, differing only in base_url:

    OpenAI            https://api.openai.com/v1
    OpenRouter        https://openrouter.ai/api/v1
    Ollama (local)    http://localhost:11434/v1
    HF router         https://router.huggingface.co/v1
    LM Studio         http://localhost:1234/v1
    vLLM              http://<host>:8000/v1

Plain HTTP via httpx. OpenRouter is detected from the base_url and gets its
attribution headers and per-call reported cost.
"""

from __future__ import annotations

import base64
import time

import httpx

from .spec import ModelSpec
from .base import (AdapterError, CONTINUE_INSTRUCTION, ChatTurn, PageImage,
                   Turn, elide_images, run_to_completion)


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

        def call_once(accumulated: str, attempt: int) -> Turn:
            # First turn: images plus the prompt, which already carries the
            # page's embedded text. Continuation turns re-send the prompt but
            # not the images, so the model still sees every line without the
            # image payload.
            if attempt == 0:
                messages = [{"role": "user",
                             "content": images + [{"type": "text", "text": prompt}]}]
            else:
                messages = [
                    {"role": "user", "content": prompt},
                    {"role": "assistant", "content": accumulated},
                    {"role": "user", "content": CONTINUE_INSTRUCTION},
                ]
            body = {"model": c.model, "max_tokens": c.max_tokens,
                    "temperature": c.temperature, "messages": messages}
            if c.json_mode and attempt == 0:
                # First turn only: a continuation turn emits a raw fragment
                # rather than a whole object, so json_mode is off for those.
                body["response_format"] = {"type": "json_object"}
            if is_openrouter:
                body["usage"] = {"include": True}

            started = time.monotonic()
            try:
                resp = httpx.post(self.url, json=body, headers=headers,
                              timeout=c.timeout_s, trust_env=False)
            except httpx.HTTPError as e:
                # The message carries the elapsed time, the configured timeout,
                # and which attempt failed.
                raise AdapterError(
                    f"[{c.name}] HTTP failure calling {self.url} after "
                    f"{time.monotonic() - started:.1f}s (timeout {c.timeout_s}s, "
                    f"attempt {attempt + 1}): {e}") from e
            latency = time.monotonic() - started
            if resp.status_code != 200:
                raise AdapterError(
                    f"[{c.name}] {self.url} returned {resp.status_code}: {resp.text[:2000]}")
            data = resp.json()

            try:
                choice = data["choices"][0]
                message = choice["message"]
                text = message["content"] or ""
            except (KeyError, IndexError, TypeError) as e:
                raise AdapterError(
                    f"[{c.name}] response shape unexpected (not chat-completions?): "
                    f"{str(data)[:500]}") from e

            # A reasoning model answers on a second channel, named "reasoning"
            # or "reasoning_content" depending on the provider. Carried, never
            # parsed: `text` stays the answer.
            reasoning = str(message.get("reasoning")
                            or message.get("reasoning_content") or "")

            usage = data.get("usage") or {}
            step_in = int(usage.get("prompt_tokens", 0))
            step_out = int(usage.get("completion_tokens", 0))
            details = usage.get("completion_tokens_details") or {}
            try:
                reasoning_tok = int(details.get("reasoning_tokens", 0) or 0)
            except (TypeError, ValueError):
                reasoning_tok = 0
            reported_cost = usage.get("cost")
            if reported_cost is not None:
                try:
                    step_cost = float(reported_cost)
                except (TypeError, ValueError):
                    step_cost = (step_in * c.cost_per_mtok_in
                                 + step_out * c.cost_per_mtok_out) / 1_000_000.0
            else:
                step_cost = (step_in * c.cost_per_mtok_in
                             + step_out * c.cost_per_mtok_out) / 1_000_000.0

            return Turn(
                text=text, finish_reason=choice.get("finish_reason") or "",
                input_tokens=step_in, output_tokens=step_out, cost_usd=step_cost,
                latency_s=latency, resolved_model=str(data.get("model", c.model)),
                request=(elide_images(body, [p.sha256 for p in pages])
                         if attempt == 0 else None),
                response=data,
                reasoning_text=reasoning, reasoning_tokens=reasoning_tok)

        # None means the driver's own default; see ModelSpec.max_continuations.
        if c.max_continuations is None:
            return run_to_completion(call_once)
        return run_to_completion(call_once, max_continuations=c.max_continuations)

    def converse(self, messages: list[dict], tools: list[dict]) -> ChatTurn:
        """One conversational round-trip with native tool-calling.

        ``messages`` is sent verbatim. ``tools`` arrive in the registry's
        neutral shape — name, description, parameters — and are wrapped into
        this protocol's function format here, which is the adapter's half of
        the modality-neutral contract. One round-trip, no continuation, no
        retries; a failure is an AdapterError for the caller to turn into a
        refusal."""
        c = self.candidate
        body: dict = {"model": c.model, "max_tokens": c.max_tokens,
                      "temperature": c.temperature, "messages": messages}
        if tools:
            body["tools"] = [{"type": "function",
                              "function": {"name": t["name"],
                                           "description": t["description"],
                                           "parameters": t["parameters"]}}
                             for t in tools]
            body["tool_choice"] = "required"
            body["parallel_tool_calls"] = False

        is_openrouter = "openrouter.ai" in (c.base_url or "")
        headers = {}
        key = c.api_key()
        if key:
            headers["Authorization"] = f"Bearer {key}"
        if is_openrouter:
            headers["HTTP-Referer"] = "https://orionviva.com"
            headers["X-Title"] = "viva-speak"
            body["usage"] = {"include": True}

        started = time.monotonic()
        try:
            # trust_env=False — see the note in anthropic_adapter: an ambient
            # proxy variable must not decide where a document is sent.
            resp = httpx.post(self.url, json=body, headers=headers,
                              timeout=c.timeout_s, trust_env=False)
        except httpx.HTTPError as e:
            raise AdapterError(
                f"[{c.name}] HTTP failure calling {self.url} after "
                f"{time.monotonic() - started:.1f}s (timeout {c.timeout_s}s): "
                f"{e}") from e
        latency = time.monotonic() - started
        if resp.status_code != 200:
            raise AdapterError(
                f"[{c.name}] {self.url} returned {resp.status_code}: "
                f"{resp.text[:2000]}")
        try:
            data = resp.json()
        except ValueError as e:
            # A misbehaving server can say 200 and hand back an HTML error
            # page; that is an unreachable model, never an exception upward.
            raise AdapterError(
                f"[{c.name}] {self.url} returned 200 with a non-JSON body: "
                f"{resp.text[:500]}") from e

        try:
            choice = data["choices"][0]
            message = choice["message"]
        except (KeyError, IndexError, TypeError) as e:
            raise AdapterError(
                f"[{c.name}] response shape unexpected (not chat-completions?): "
                f"{str(data)[:500]}") from e

        usage = data.get("usage") or {}
        step_in = int(usage.get("prompt_tokens", 0))
        step_out = int(usage.get("completion_tokens", 0))
        reported_cost = usage.get("cost")
        if reported_cost is not None:
            try:
                step_cost = float(reported_cost)
            except (TypeError, ValueError):
                step_cost = (step_in * c.cost_per_mtok_in
                             + step_out * c.cost_per_mtok_out) / 1_000_000.0
        else:
            step_cost = (step_in * c.cost_per_mtok_in
                         + step_out * c.cost_per_mtok_out) / 1_000_000.0

        import copy

        return ChatTurn(
            message=message, tool_calls=list(message.get("tool_calls") or []),
            text=message.get("content") or "",
            finish_reason=choice.get("finish_reason") or "",
            input_tokens=step_in, output_tokens=step_out, cost_usd=step_cost,
            latency_s=latency, resolved_model=str(data.get("model", c.model)),
            # A deep copy, because the caller goes on appending to its message
            # list — the recorded request must stay what was actually sent.
            request=copy.deepcopy(body), response=data)
