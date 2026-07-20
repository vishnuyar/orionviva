# viva-bench

The admission exam for models that want to read your financial documents.
Part of [OrionViva](https://orionviva.com) — see
[`docs/benchmark-harness-design.md`](../docs/benchmark-harness-design.md) for
what the exam measures and why, and
[`docs/benchmark-harness-architecture.md`](../docs/benchmark-harness-architecture.md)
for how this utility is put together.

**Your documents never leave your machine** except as the model calls *you*
configure, under *your* keys. Nothing here phones home; every model
interaction is captured raw into an append-only, hash-chained log you can
audit (`viva-bench verify-log`).

## Setup

```bash
cd bench
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest                      # the verification core must be green before anything runs
```

## Configure

Copy the examples and edit:

```bash
cp models.example.yaml models.yaml     # your candidates, budget ceiling
cp corpus.example.yaml corpus.yaml     # your documents (paths into bench-data/)
```

Candidates are pure config. Two adapters cover effectively every provider:

- `anthropic` — Anthropic's Messages API.
- `openai-compatible` — one adapter, many base_urls: OpenAI
  (`https://api.openai.com/v1`), OpenRouter (`https://openrouter.ai/api/v1`),
  Ollama on your machine (`http://localhost:11434/v1`), Hugging Face's router,
  LM Studio, vLLM.

API keys come from environment variables only. Unpinned model aliases
("latest") are refused — pin exact versions; the exam grades a model that
exists, not a moving target.

## Run

```bash
viva-bench validate      # checks configs, files, and the run plan; no network
viva-bench run           # administers the exam; resumable; hard budget stop
viva-bench verify-log    # recheck the raw log's hash chain
```

`draft-key`, `score`, and `report` are later build steps (architecture §7).

## Layout

- `vivabench/verify/` — **product embryo**: locale-aware normalization,
  arithmetic identities, claim matching. Deterministic, Decimal-only, tested
  hardest. Ambiguity ("1.234" without a locale; "03/04/2025" without a
  country) is a first-class result, never a guess.
- `vivabench/models/` — **product embryo**: the pinned, provider-agnostic
  model access layer. Plain HTTP, two adapters, zero SDK dependencies.
- everything else — honest utility code.

Private data (documents, keys, raw runs) lives in `bench-data/` at the repo
root, which is gitignored. The repo never carries a statement or an answer
key — at most the *hash* of a frozen key.
