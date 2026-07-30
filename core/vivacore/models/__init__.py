"""Model access layer.

Two adapters cover every provider in use:

- ``anthropic``           — Anthropic's Messages API, spoken directly over HTTP.
- ``openai-compatible``   — the OpenAI chat-completions protocol: OpenAI,
  OpenRouter, Ollama, Hugging Face router, LM Studio, vLLM — same protocol,
  different base_url.

Both speak plain HTTP via httpx; no provider SDKs.

Contract every adapter honors:
- request and response are returned verbatim, for raw capture;
- the endpoint-reported model identity is surfaced as ``resolved_model``;
- adapters never parse, never retry silently, never editorialize.

``adapter_for`` raises AdapterError for an unknown adapter name.
"""

from .base import AdapterError, ModelAdapter, ModelResult, PageImage
from .anthropic_adapter import AnthropicAdapter
from .openai_compat import OpenAICompatAdapter

from .spec import ModelSpec


def adapter_for(candidate: ModelSpec) -> ModelAdapter:
    if candidate.adapter == "anthropic":
        return AnthropicAdapter(candidate)
    if candidate.adapter == "openai-compatible":
        return OpenAICompatAdapter(candidate)
    raise AdapterError(f"Unknown adapter '{candidate.adapter}'.")


__all__ = [
    "AdapterError",
    "ModelAdapter",
    "ModelResult",
    "PageImage",
    "AnthropicAdapter",
    "OpenAICompatAdapter",
    "adapter_for",
]
