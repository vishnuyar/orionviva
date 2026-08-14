# Benchmark Harness Architecture — viva-bench, the utility

**Status:** Draft, amended as-built · **Last updated:** 2026-08-14 · **Companion to:** [benchmark-harness-design.md](benchmark-harness-design.md) (the *what and why*; this is the *how*)
**Invariants touched:** T2 (scoring is deterministic code), T3 (raw capture of every run), T6 (outbound = model calls only, budget-guarded), T8 (pinned versions, provider-swappable), I2 (locale-aware versioned normalization), I4 (key schema carries locale), I6 (pack format), X1 (a stranger runs it with a config file and a README, no code edits)

## 1 · What gets built

A command-line utility, **`viva-bench`**, that administers the admission exam end to end: describe a corpus, build and audit an answer key, run candidates against it, score deterministically, and emit per-(model × document type × locale) scorecards. Reusable by design: anyone points it at *their* corpus and *their* models via config, and no document ever leaves their machine except through model calls they configured themselves.

## 2 · Where it lives, and how it's tracked

**Code:** same repo, `bench/` at the root — a monorepo choice, deliberate: the two product-embryo modules (below) will be *extracted upward* into the product later, which is trivial inside one repo and archaeology across two. Public and MIT like everything else.

**Private data:** corpus, answer keys, and run outputs default to `bench-data/` (gitignored — the existing financial-data fence covers it) with the path configurable. The repo carries only the *hash* of a frozen answer key, never the key.

**Docs tracking:** this doc sits beside the design doc in the reading guide (§4, design stances); the TODO tracks build progress; findings will become a new doc when experiment 1 runs. Layout:

```
orionviva/
├── docs/                          ← thinking (this file, design doc, findings later)
├── bench/                         ← viva-bench utility (public, MIT)
│   ├── README.md                  ← how a stranger runs it
│   ├── pyproject.toml
│   ├── vivabench/
│   │   ├── corpus.py  keybuild/  runner/  score/  report/
│   │   │        ↑ imports vivacore.models, vivacore.verify, vivacore.claims
│   │   ├── models/                ⛔ GONE — extracted upward into core/vivacore
│   │   ├── verify/                ⛔ GONE — extracted upward into core/vivacore
│   ├── packs/                     ⛔ NOT BUILT — pack format spec + example pack (I6), §7 step 5
│   ├── synthetic/                 ← corpus generator: a coherent invented financial
│   │                                life; PDFs built locally, answer key committed
│   └── tests/                     ← ★ verify/ gets the ferocious ones
└── bench-data/                    ← gitignored: corpus, keys, raw runs
```

★ = written to product-grade standard (typed, specified, ferociously tested — ADR-010's future crown jewel starts here). Everything else is honest utility-grade.

**The extraction upward has happened.** The two starred modules were the reason
this section chose one repo, and neither lives under `vivabench/` any more:
imports throughout the package read `vivacore.models`, `vivacore.verify.match`
and `vivacore.claims`. §4 below still describes `verify/` as the verification
layer's first draft — read that as a description of `core/vivacore/verify/`,
which is now product code held to product standards rather than bench code
aspiring to them.

**Amended 2026-08-14, and the reason is worth keeping.** The pass above marked
`models/` and `verify/` and stopped, leaving `packs/`, the adapter line, the
budget guard and the stack section reading as verified-current when all four
were wrong. A half-amended document is worse than an unamended one: the
amendments that *are* there certify the lines that are not. Every line in this
file has now been checked against the tree, and the corrections are inline
rather than appended.

## 3 · The model access layer (configurable backends)

**The 2026 reality that simplifies everything:** the OpenAI-compatible protocol has become the universal socket — formalized in the vendor-neutral *Open Responses* spec (Jan 2026) with Ollama, OpenRouter, Hugging Face, LM Studio, and vLLM as launch partners. Ollama serves it at a local URL; OpenRouter fronts 300+ models with it; HF's inference router speaks it. So **two adapters cover the entire universe**:

1. **`openai-compatible`** — one adapter, any base URL: OpenAI itself, OpenRouter, Ollama (localhost), Hugging Face router, LM Studio, vLLM, a future attested endpoint.
2. **`anthropic`** — the Messages API over plain HTTP, because it is the one first-class candidate that does not speak the OpenAI-compatible socket. _(Amended 2026-08-14: this line said "native SDK". It never was one. `anthropic_adapter.py:1` is `httpx` and says so in its own docstring, `core/pyproject.toml` declares `httpx` as its single runtime dependency, and the repo imports no provider SDK anywhere — which is a stated stance, not an accident: see [threat-model-and-ingestion-security.md](threat-model-and-ingestion-security.md), "No SDK on the wire". This line was the repo's only dissent from it.)_

Candidates are pure configuration — `models.yaml`, no code changes ever:

```yaml
candidates:
  claude:      {adapter: anthropic,          model: claude-fable-5-2026xxxx}
  gpt:         {adapter: openai-compatible,  base_url: https://api.openai.com/v1,      model: gpt-5.x-pinned}
  qwen-local:  {adapter: openai-compatible,  base_url: http://localhost:11434/v1,       model: qwen3-vl:32b-q4  # Ollama}
  tiny:        {adapter: openai-compatible,  base_url: http://localhost:11434/v1,       model: <phone-class>}
  # keys via env vars; per-candidate: temperature, max_tokens, cost/Mtoken, notes
```

Every run records the *resolved* model identity reported by the endpoint, not just the config string (T8 — "latest" aliases are refused on principle; the runner errors on unpinned names).

**Alternative considered — LiteLLM** (unified library/proxy over 100+ providers): genuinely good, and the conventional choice. Rejected for the same reason the DCO check is fifteen lines of shell: this layer is a product embryo on the trust path, and importing a large fast-moving dependency to do what two thin adapters (~200 lines each) do is exactly the supply-chain trade this project keeps refusing. If a future exotic provider appears, it will almost certainly speak OpenAI-compatible anyway — that's the point of the socket.

## 4 · The other components, briefly

- **Corpus manifest** (`corpus.yaml`): per document — file path, document type, locale, currency, quality tag (clean/scan/weird), notes. The pack format (I6) is exactly this manifest + a key, zipped. **Not built.** What exists instead is `bench/synthetic/`, a generator for a coherent invented financial life: `make_corpus.py` writes the PDFs locally and a committed `answer-key.json`. It is an end-to-end corpus for the *product*, in its own nested key format, and `vivacore.claims.load_key` cannot read it — so a stranger smoke-tests by running a generator, not by unzipping a pack.
- **Key builder** (`viva-bench draft-key`, `freeze-key`): two-candidate independent drafting → merge → a JSON audit worksheet → `freeze-key` (fold the resolved rows, canonicalize, hash). *As built, three things in the original plan are absent, and are fenced in [benchmark-harness-design.md](benchmark-harness-design.md) §4: there is no deterministic arithmetic refereeing between drafting and audit (`vivacore.verify.arithmetic` is called by no bench code); there is no `audit` command and no terminal UI — `draft-key` writes `<doc_id>.audit.json` and a person fills each row's `resolved` field in a text editor; and the worksheet cannot put the document page beside a claim, because neither `DraftEntry` nor the key entries it produces carry a page. The command is `freeze-key`, not `freeze`.*
- **Runner** (`viva-bench run`): N runs × candidates × documents; every request/response captured raw to content-addressed JSONL before any parsing touches it (T3); resumable (re-running skips completed cells); **budget guard** — accumulated *actual* spend is checked before each cell and the run raises `BudgetExceeded` at the ceiling ($100, per approved design). *Two consequences the design's projected-spend rule does not have: a run can overshoot by up to one cell's cost, because the check is between cells and never inside one; and nothing is refused up front, so a plan that will obviously breach the ceiling is discovered only after the ceiling is spent. The projected-spend-computed-up-front rule (design doc §7, D-b) is not implemented.*
- **Scorer** (`viva-bench score`): pure function from (raw runs + frozen key) → grades; strict/normalized matching, recall of missed claims, self-consistency, calibration curves, system-level grades including the confidently-wrong rate. Normalization rules live in `verify/`, locale-aware and versioned (I2) — **this module is the verification layer's first draft, and its test suite is a permanent project asset regardless of the product's eventual language.** *(It has since moved: it is `core/vivacore/verify/`, per §2.)* *(Amended 2026-08-14: **source-region validity is not among the metrics.** The scorer computes accuracy, recall, strict rate, self-consistency, calibration/ECE, mean spurious, and the two system metrics. The runner captures each claim's model-reported region into the raw log and nothing reads it back; the frozen key has no region to check it against. Neither cost nor latency is reported either, though the runner captures both.)*
- **Reporter** (`viva-bench report`): scorecards as markdown + JSON per (model, doc type, locale); no composite leaderboard, per the design doc. *(Tracked as a defect, not fenced as prose: `report` is registered as an alias of `score` at `cli.py:287` and never given the `--mode` flag `cmd_score` reads, so every invocation raises `AttributeError` before a record is read. `bench/tests/` has no CLI coverage at all. Use `score` until the alias is fixed.)*

**Choosing per-document page concurrency.** The cap is deliberately modest, and
the reason is a scoring hazard rather than politeness. `extract_by_page` lets an
`AdapterError` from any single page fail the whole cell, and `run_exam` writes
that as a `status: "error"` record indistinguishable from a genuine model
failure — so a provider's rate limiter, tripped by a high fan-out, is recorded
*against the candidate*. An aggressive concurrency setting can therefore be read
as a model failing the exam. The argument is structural rather than measured; no
number here has been tuned against a provider's actual limits.

## 5 · Storage of results

Plain files, no database: JSONL for runs (append-only, hash-chained per run file in the ADR-004 spirit — cheap here and rehearses the product's log), YAML for configs, markdown+JSON for reports. Rationale: durable, diffable, inspectable by a stranger with a text editor — formats are the durable asset; a database earns its place in the product, not the utility.

## 6 · Stack

Python 3.11+, minimal dependencies (one HTTP client — `httpx`, with no provider SDKs on the wire — YAML, a PDF-to-image library for multimodal calls, pytest). This is the experiments-phase stack decision only — the product stack remains deliberately open (form-factor doc). What survives any future rewrite: the file formats, the verification test suite, and the measured findings.

## 7 · Build order

1. `models/` adapters + `corpus.py` + runner skeleton with raw capture and budget guard — enough to make one real call end to end.
2. `verify/` normalization + arithmetic checks with its test suite (product-grade from the first line).
3. Key builder + audit flow (the author's first hands-on session).
4. Scorer + reporter.
5. Synthetic example pack + README for strangers. **Not done** — `bench/synthetic/` is a generator, not a pack.

Steps 1–2 are the risk-bearing ones; 3–5 are assembly. Estimate: a few working sessions.

## Open questions

- PDF handling detail: send documents as page images (uniform across candidates, guarantees the *vision* pathway is what's tested) vs. native PDF ingestion where a provider supports it — leaning page-images for comparability; revisit if a candidate underperforms suspiciously.
- Audit UI: terminal-based first; a tiny local web page for side-by-side document viewing only if the terminal proves painful in practice.
