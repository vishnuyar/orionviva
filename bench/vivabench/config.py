"""Configuration loading for viva-bench.

Two files drive everything:

- ``models.yaml``  — the candidate roster, budget ceiling, data directory.
- ``corpus.yaml``  — the exam paper: documents, types, locales (invariant I4).

Design rules enforced here rather than politely suggested:
- Unpinned model aliases ("latest") are refused outright (invariant T8).
- Every document must declare a locale and currency (invariant I4).
- API keys come from environment variables only — never from config files.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml


class ConfigError(Exception):
    """A configuration problem the user must fix. Message is the fix."""


# --------------------------------------------------------------------------- models.yaml


@dataclass(frozen=True)
class Candidate:
    name: str
    adapter: str                      # "anthropic" | "openai-compatible"
    model: str                        # pinned model identifier
    base_url: str | None = None       # required for openai-compatible
    api_key_env: str | None = None    # env var name holding the key (None = keyless, e.g. Ollama)
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
                f"Candidate '{self.name}' needs the environment variable "
                f"{self.api_key_env} to be set (keys never live in config files)."
            )
        return key


@dataclass(frozen=True)
class BenchConfig:
    candidates: list[Candidate]
    budget_usd: float
    data_dir: Path
    runs_per_document: int = 5
    # Pages of one document extracted in parallel. Pages are independent calls,
    # so this changes only wall-clock, never what is measured. Kept modest so a
    # provider's rate limiter is not mistaken for a candidate's failure.
    page_concurrency: int = 6
    # What the model is shown: "image" (page pixels), "text" (the issuer's own
    # embedded PDF text), or "text+image" (both). A benchmark dimension, not a
    # setting to guess at — see docs/document-preprocessing.md.
    input_mode: str = "image"

    def candidate(self, name: str) -> Candidate:
        for c in self.candidates:
            if c.name == name:
                return c
        raise ConfigError(f"No candidate named '{name}' in models.yaml.")


_FORBIDDEN_ALIAS_FRAGMENTS = ("latest",)
_VALID_ADAPTERS = ("anthropic", "openai-compatible")
_VALID_INPUT_MODES = ("image", "text", "text+image")


def _validate_candidate(raw: dict) -> Candidate:
    name = raw.get("name")
    if not name:
        raise ConfigError("Every candidate needs a 'name'.")
    adapter = raw.get("adapter")
    if adapter not in _VALID_ADAPTERS:
        raise ConfigError(
            f"Candidate '{name}': adapter must be one of {_VALID_ADAPTERS}, got {adapter!r}."
        )
    model = raw.get("model", "")
    if not model:
        raise ConfigError(f"Candidate '{name}' needs a 'model'.")
    lowered = model.lower()
    for fragment in _FORBIDDEN_ALIAS_FRAGMENTS:
        if fragment in lowered:
            raise ConfigError(
                f"Candidate '{name}' uses the unpinned alias {model!r}. "
                "The trust policy (T8) refuses 'latest' on principle: pin an exact "
                "version so the exam grades a model that exists, not a moving target."
            )
    if adapter == "openai-compatible" and not raw.get("base_url"):
        raise ConfigError(
            f"Candidate '{name}': openai-compatible adapter needs a 'base_url' "
            "(e.g. https://api.openai.com/v1, http://localhost:11434/v1, "
            "https://openrouter.ai/api/v1)."
        )
    return Candidate(
        name=name,
        adapter=adapter,
        model=model,
        base_url=raw.get("base_url"),
        api_key_env=raw.get("api_key_env"),
        temperature=float(raw.get("temperature", 0.2)),
        max_tokens=int(raw.get("max_tokens", 8192)),
        cost_per_mtok_in=float(raw.get("cost_per_mtok_in", 0.0)),
        cost_per_mtok_out=float(raw.get("cost_per_mtok_out", 0.0)),
        timeout_s=float(raw.get("timeout_s", 300.0)),
        notes=str(raw.get("notes", "")),
    )


def load_bench_config(path: Path) -> BenchConfig:
    if not path.exists():
        raise ConfigError(f"models config not found: {path}")
    raw = yaml.safe_load(path.read_text()) or {}
    candidates_raw = raw.get("candidates") or []
    if not candidates_raw:
        raise ConfigError("models.yaml has no candidates.")
    candidates = [_validate_candidate(c) for c in candidates_raw]
    names = [c.name for c in candidates]
    if len(names) != len(set(names)):
        raise ConfigError("Candidate names must be unique.")
    budget = float(raw.get("budget_usd", 0))
    if budget <= 0:
        raise ConfigError(
            "models.yaml needs a positive 'budget_usd' — the hard spending ceiling "
            "is a design requirement, not an option."
        )
    input_mode = str(raw.get("input_mode", "image"))
    if input_mode not in _VALID_INPUT_MODES:
        raise ConfigError(
            f"models.yaml has input_mode {input_mode!r}; expected one of "
            f"{_VALID_INPUT_MODES}."
        )
    data_dir = Path(raw.get("data_dir", "../bench-data")).expanduser()
    if not data_dir.is_absolute():
        data_dir = (path.parent / data_dir).resolve()
    return BenchConfig(
        candidates=candidates,
        budget_usd=budget,
        data_dir=data_dir,
        runs_per_document=int(raw.get("runs_per_document", 5)),
        page_concurrency=max(1, int(raw.get("page_concurrency", 6))),
        input_mode=input_mode,
    )


# --------------------------------------------------------------------------- corpus.yaml


_VALID_QUALITY = ("clean", "scan", "weird")


@dataclass(frozen=True)
class Document:
    id: str
    file: Path                # resolved absolute path
    doc_type: str             # e.g. checking_statement, credit_card_statement, ...
    locale: str               # BCP-47-ish, e.g. en-US, de-DE  (invariant I4)
    currency: str             # ISO 4217, e.g. USD             (invariant I1)
    quality: str = "clean"
    notes: str = ""


@dataclass(frozen=True)
class Corpus:
    documents: list[Document] = field(default_factory=list)

    def document(self, doc_id: str) -> Document:
        for d in self.documents:
            if d.id == doc_id:
                return d
        raise ConfigError(f"No document with id '{doc_id}' in corpus.")


def load_corpus(path: Path) -> Corpus:
    if not path.exists():
        raise ConfigError(f"corpus manifest not found: {path}")
    raw = yaml.safe_load(path.read_text()) or {}
    docs_raw = raw.get("documents") or []
    if not docs_raw:
        raise ConfigError("corpus.yaml lists no documents.")
    documents: list[Document] = []
    seen_ids: set[str] = set()
    for d in docs_raw:
        doc_id = d.get("id")
        if not doc_id:
            raise ConfigError("Every corpus document needs an 'id'.")
        if doc_id in seen_ids:
            raise ConfigError(f"Duplicate document id '{doc_id}'.")
        seen_ids.add(doc_id)
        for required in ("file", "doc_type", "locale", "currency"):
            if not d.get(required):
                raise ConfigError(
                    f"Document '{doc_id}' is missing '{required}'. Locale and currency "
                    "are required from day one (invariants I1/I4) — they cannot be "
                    "retrofitted into ground truth later."
                )
        quality = d.get("quality", "clean")
        if quality not in _VALID_QUALITY:
            raise ConfigError(
                f"Document '{doc_id}': quality must be one of {_VALID_QUALITY}."
            )
        file_path = Path(d["file"]).expanduser()
        if not file_path.is_absolute():
            file_path = (path.parent / file_path).resolve()
        documents.append(
            Document(
                id=doc_id,
                file=file_path,
                doc_type=str(d["doc_type"]),
                locale=str(d["locale"]),
                currency=str(d["currency"]).upper(),
                quality=quality,
                notes=str(d.get("notes", "")),
            )
        )
    return Corpus(documents=documents)
