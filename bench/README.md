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

The rest of the chain is built too:

```bash
viva-bench draft-key --from-log   # draft an answer key from extractions already
                                  # in the run log (omit --from-log to call two
                                  # drafter models directly)
viva-bench freeze-key             # fold your resolved audits in, freeze, hash
viva-bench score                  # grade the runs against the frozen keys;
                                  # writes findings.md + scorecards.json
```

`report` is registered as an alias of `score` and **currently crashes** — it was
never given the `--mode` flag `score` reads, so every invocation raises
`AttributeError` before a record is read. Use `score`. Tracked as a defect.

Two more things worth knowing before you trust a number this produces:
`freeze-key` is not idempotent — running it twice folds the same resolved rows
in again, growing the key and changing its hash — and the answer key is joined
on model-written labels rather than on (value, page, region), which collapses
repeated line items. See the architecture and design docs before reading a
recall figure as a measurement.

## Layout

- `vivabench/` — the harness: config, corpus and page rendering, the raw-capture
  log, the runner, the key builder, the scorer, the reporter.
- The two **product embryos** it depends on were extracted upward and now live in
  [`core/vivacore`](../core/README.md), shared with the product:
  `vivacore/verify/` (locale-aware normalization, arithmetic identities, claim
  matching — deterministic, Decimal-only, tested hardest; ambiguity like "1.234"
  without a locale or "03/04/2025" without a country is a first-class result,
  never a guess) and `vivacore/models/` (the pinned, provider-agnostic model
  access layer — plain HTTP, two adapters, zero SDK dependencies).
- `synthetic/` — a generator for a coherent invented financial life, used for
  end-to-end product runs. Nothing in it is real; see its own README.
- everything else — honest utility code.

Private data (real documents, real keys, raw runs) lives in `bench-data/` at the
repo root, which is gitignored. The repo never carries a real statement or a
real answer key — of a real key, at most the *hash* of a frozen one. The one
committed answer key, `synthetic/answer-key.json`, is the ground truth for the
wholly invented corpus in `synthetic/` and is committed by design: its documents
are generated locally, so the key is the only durable half.
