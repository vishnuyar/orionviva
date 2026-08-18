# Benchmark Harness Architecture — viva-bench, the utility

**State:** partial
**Rules:** PROG-19, PROG-20, PROG-21, PROG-22, PROG-23, PROG-54

## Rules

### PROG-19 — Two adapters, no provider SDK on the wire
**State:** enforced
**Code:** core/vivacore/models/openai_compat.py, core/vivacore/models/anthropic_adapter.py:1
**Test:** core/tests/test_openai_continuation.py::test_continuation_stitches_and_drops_images, core/tests/test_anthropic_continuation.py::test_continuation_stitches_via_assistant_prefill

1. One `openai-compatible` adapter serves any base URL — a hosted API, a router, a local server.
2. One `anthropic` adapter speaks the Messages API over plain HTTP.
3. No provider SDK is imported anywhere; the only HTTP dependency is `httpx`.

### PROG-20 — Candidates are configuration, never code
**State:** by-review
**Code:** bench/vivabench/config.py:121-128 (`models.yaml` loading), core/vivacore/models/spec.py:38
**Test:** none

1. Adding, removing or repointing a candidate is a config edit and never a code change.
2. API keys reach the code from environment variables and never from a config file.

### PROG-21 — Every model interaction is captured raw before anything parses it
**State:** enforced
**Code:** bench/vivabench/capture.py:1, bench/vivabench/capture.py:96 (`append`)
**Test:** bench/tests/test_match_and_capture.py::test_chain_appends_and_verifies, bench/tests/test_match_and_capture.py::test_tampering_breaks_the_chain

1. Each model interaction becomes one JSONL record written before any parsing touches it.
2. Records are hash-chained, so a later edit breaks the chain and verification reports it.
3. A re-run skips completed cells rather than re-spending on them.

### PROG-22 — Results are plain files a stranger can read
**State:** by-review
**Code:** bench/vivabench/capture.py:1 (JSONL runs), bench/vivabench/config.py:121 (YAML config), bench/vivabench/report.py:18 (markdown + JSON)
**Test:** none

1. Runs are JSONL, configs are YAML, reports are markdown and JSON.
2. No database sits anywhere in the utility.

### PROG-23 — `viva-bench report` emits the scorecards
**State:** contradicted-by-code
**Code:** bench/vivabench/cli.py:287
**Test:** none

1. `report` writes scorecards as markdown and JSON per (model, document type, locale).

**Contradiction:** the doc describes `viva-bench report` as the reporter command. bench/vivabench/cli.py:287 registers `report` as a bare alias of `cmd_score` and never gives it the `--mode` flag `cmd_score` reads (bench/vivabench/cli.py:233), so every invocation raises `AttributeError` before a record is read. `bench/tests/` has no CLI coverage at all. `score` works.

### PROG-54 — The pack format is a corpus manifest plus a key, zipped
**State:** by-review-with-exception
**Code:** bench/vivabench/config.py:141 (`Document` — path, doc_type, locale, currency, quality, notes), :162 (`load_corpus`, which requires file, doc_type, locale and currency and rejects a duplicate id)
**Test:** none

1. A corpus manifest names, per document, its path, document type, locale, currency, quality tag and notes.
2. A pack is that manifest plus a key, zipped, so a stranger smoke-tests by unzipping one.

**Exception:** assertion 1 is built; assertion 2 is not. What exists instead is `bench/synthetic/`, a generator for a coherent invented financial life whose `make_corpus.py` writes PDFs locally and a committed answer key in its own nested format that `vivacore.claims.load_key` cannot read. A stranger smoke-tests by running a generator, not by unzipping a pack.

## Why

`viva-bench` administers the admission exam end to end: describe a corpus, build and audit an answer key, run candidates against it, score deterministically, and emit per-(model × document type × locale) scorecards. It is reusable by design — anyone points it at their own corpus and their own models through config, and no document leaves their machine except through model calls they configured themselves.

**One repo, deliberately.** The two product-embryo modules — the model access layer and the verification layer — were always going to be extracted upward into the product, which is trivial inside one repo and archaeology across two. That extraction has happened: both now live in `core/vivacore/`, held to product standards rather than aspiring to them, and the package imports them. Private data — corpus, answer keys, run outputs — defaults to a gitignored directory with the path configurable, and the repo carries only a frozen key's hash.

**Why two adapters cover the universe.** The OpenAI-compatible protocol became the universal socket, formalised in a vendor-neutral spec with the major local and hosted runtimes as launch partners. So one adapter reaches any base URL, and a second exists only for the one first-class candidate that does not speak that socket. The conventional alternative is a unified multi-provider library; it is genuinely good and it was rejected for the same reason the contribution check is fifteen lines of shell. This layer sits on the trust path, and importing a large fast-moving dependency to do what two thin adapters do is exactly the supply-chain trade this project keeps refusing. A future exotic provider will almost certainly speak the socket anyway — that is the point of a socket.

**Why page concurrency is capped modestly**, and the reason is a scoring hazard rather than politeness. A failure from any single page fails the whole cell, and the run writes that as an error record indistinguishable from a genuine model failure — so a provider's rate limiter, tripped by high fan-out, is recorded *against the candidate*, and an aggressive concurrency setting reads as a model failing the exam. The argument is structural rather than measured; no number here has been tuned against a provider's actual limits.

**Why plain files.** JSONL for runs, hash-chained per run file in the spirit of the product's own log; YAML for configs; markdown and JSON for reports. Durable, diffable, inspectable by a stranger with a text editor. The formats are the durable asset — a database earns its place in the product, not in the utility. What survives any future rewrite of the stack is exactly this: the file formats, the verification test suite, and the measured findings.

**A note on how this document is maintained.** An earlier pass amended two sections and stopped, leaving four others reading as verified-current when they were wrong. A half-amended document is worse than an unamended one, because the corrections that *are* present certify the lines that are not. Every line here is checked against the tree, and corrections are made in place rather than appended.

**The build order** is adapters and runner skeleton with raw capture and budget guard first, enough to make one real call end to end; then the verification layer with its test suite, product-grade from the first line; then the key builder and audit flow; then scorer and reporter; then a synthetic example pack and a README for strangers. The first two are the risk-bearing steps and the rest are assembly.

Companion to [benchmark-harness-design.md](benchmark-harness-design.md), which carries the what and the why of the exam itself; this carries the how. The no-SDK stance is [threat-model-and-ingestion-security.md](threat-model-and-ingestion-security.md)'s, and this document was for a while its only dissent.

## Open

- The `report` command is broken (PROG-23) and `bench/tests/` has no CLI coverage of any command.
- The key builder has no arithmetic refereeing step, no `audit` command and no terminal interface: `draft-key` writes a JSON worksheet and a person fills each row's resolved field in a text editor, and the worksheet cannot put the document page beside a claim because neither the draft entries nor the key entries carry a page.
- The pack format and its example pack are unbuilt (PROG-54), and the README-for-strangers step behind them is therefore incomplete.
- Source-region validity is not among the scorer's metrics, and neither cost nor latency is reported, though the runner captures all three.
- PDF handling: send documents as page images, uniform across candidates and guaranteeing the vision pathway is what is tested, or use native PDF ingestion where a provider supports it. The leaning is page images for comparability; revisit if a candidate underperforms suspiciously.
- Audit interface: terminal first, with a small local page for side-by-side document viewing only if the terminal proves painful in practice.
- The findings document becomes a new doc when the first experiment runs.
