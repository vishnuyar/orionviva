"""Model access layer — product embryo.

Two adapters cover the known universe:

- ``anthropic``           — Anthropic's Messages API, spoken directly over HTTP.
- ``openai-compatible``   — the universal socket ("Open Responses" era): OpenAI,
  OpenRouter, Ollama, Hugging Face router, LM Studio, vLLM — same protocol,
  different base_url.

Both are deliberately plain-HTTP via httpx (one dependency, fully inspectable)
rather than provider SDKs or a multi-provider wrapper library: less
third-party code sits on the trust path, and every byte sent is visible here.

Contract every adapter honors:
- request/response are returned VERBATIM for raw capture;
- the endpoint-reported model identity is surfaced as ``resolved_model``;
- adapters never parse, never retry silently, never editorialize.
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
