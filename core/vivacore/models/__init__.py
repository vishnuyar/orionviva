"""Model access layer — product embryo (ADR-001, trust policy T8).

Two adapters cover the known universe:

- ``anthropic``           — Anthropic's Messages API, spoken directly over HTTP.
- ``openai-compatible``   — the universal socket ("Open Responses" era): OpenAI,
  OpenRouter, Ollama, Hugging Face router, LM Studio, vLLM — same protocol,
  different base_url.

Both are deliberately plain-HTTP via httpx (one dependency, fully inspectable)
rather than provider SDKs or a multi-provider wrapper library — the
supply-chain-minimalism argument is in docs/benchmark-harness-architecture.md §3.

Contract every adapter honors:
- request/response are returned VERBATIM for raw capture (T3);
- the endpoint-reported model identity is surfaced as ``resolved_model`` (T8);
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
