"""ModelSpec — how to call one pinned model. Shared by the product and the bench.

A spec names the adapter, the pinned model version, where to reach it, its
limits, and (for cost accounting) its prices. API keys are not part of it: a
spec carries the name of an environment variable, and the key is read from the
environment at call time.
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
    api_key_env: str | None = None    # env var holding the key (None = keyless, e.g. a local server)
    temperature: float = 0.2
    max_tokens: int = 8192
    cost_per_mtok_in: float = 0.0     # USD per million input tokens (0 for local)
    cost_per_mtok_out: float = 0.0
    timeout_s: float = 300.0
    json_mode: bool = False           # ask the provider for guaranteed-valid JSON
    # How many times to continue across provider truncation. The shared default
    # suits document extraction, where a long transaction list genuinely gets
    # cut off and stitching the tail back on is the repair. A call whose output
    # is short and bounded sets this to 0, so truncation is reported rather than
    # repaired. docs/from-your-words-to-the-ledger.md
    max_continuations: int | None = None   # None = the shared default
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
