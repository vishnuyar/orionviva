"""ModelSpec — how to call one pinned model. Shared by the product and the bench.

A model spec describes a model to call: which adapter, which pinned version,
where, with what limits and (for cost accounting) what prices. Both the product
and the benchmark describe models to call the same way, so this lives in the
core. Keys come from environment variables only — never from a spec object.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from ..errors import ConfigError


@dataclass(frozen=True)
class ModelSpec:
    name: str
    adapter: str                      # "anthropic" | "openai-compatible"
    model: str                        # pinned model identifier
    base_url: str | None = None       # required for openai-compatible
    api_key_env: str | None = None    # env var holding the key (None = keyless, e.g. Ollama)
    temperature: float = 0.2
    max_tokens: int = 8192
    cost_per_mtok_in: float = 0.0     # USD per million input tokens (0 for local)
    cost_per_mtok_out: float = 0.0
    timeout_s: float = 300.0
    notes: str = ""

    def api_key(self) -> str | None:
        if self.api_key_env is None:
            return None
        key = os.environ.get(self.api_key_env, "").strip()
        if not key:
            raise ConfigError(
                f"Model '{self.name}' needs the environment variable "
                f"{self.api_key_env} to be set (keys never live in config files)."
            )
        return key
