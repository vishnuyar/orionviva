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

- `openai-compatible` — one adapter, many base_urls: OpenRouter
  (`https://openrouter.ai/api/v1`), OpenAI (`https://api.openai.com/v1`),
  Ollama on your machine (`http://localhost:11434/v1`), Hugging Face's router,
  LM Studio, vLLM.
- `anthropic` — Anthropic's Messages API directly (only needed if you skip
  OpenRouter and want Claude via a native key).

**Recommended: OpenRouter.** One key (`OPENROUTER_API_KEY`), one base_url, many
models — pick vision-capable slugs from https://openrouter.ai/models and pin
them (the `models.example.yaml` shows the pattern). When the provider is
OpenRouter, viva-bench asks it for the exact charged cost per call, so the
budget guard runs on actuals — you don't have to hand-enter prices. A single
key covers the two frontier drafters, an open model as the local-capability
proxy, and a small model as the phone-class proxy.

To measure the *true* on-device floor (not just capability), add an Ollama
candidate (`http://localhost:11434/v1`, no key) later — that run never leaves
your machine.

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
