# Benchmark Harness Design — the admission exam for models

**State:** partial
**Rules:** PROG-6, PROG-7, PROG-8, PROG-9, PROG-10, PROG-11, PROG-12, PROG-13, PROG-14, PROG-15, PROG-16, PROG-17, PROG-18

## Rules

### PROG-6 — Grading is deterministic code, never a model
**State:** enforced
**Code:** bench/vivabench/score.py:78 (`grade_run`), bench/vivabench/score.py:204 (`build_scorecards`)
**Test:** bench/tests/test_claims_and_score.py::test_grade_perfect_run, bench/tests/test_claims_and_score.py::test_grade_catches_silent_omission

1. Scoring is a pure function from raw runs plus a frozen key to grades.
2. No model judges a candidate's answer.
3. Normalisation rules are locale-aware and versioned, and matching is graded both strictly and normalised.

### PROG-7 — No composite score
**State:** enforced
**Code:** bench/vivabench/report.py:3, bench/vivabench/report.py:42
**Test:** bench/tests/test_claims_and_score.py::test_scorecards_group_and_calibrate

1. The output is a scorecard per (model, document type, locale).
2. No leaderboard number is computed, published or implied.

### PROG-8 — The answer key never enters the repo; only its hash does
**State:** enforced
**Code:** bench/vivabench/config.py:121 (data dir defaults to the gitignored `bench-data/`), .gitignore:40
**Test:** bench/tests/test_claims_and_score.py::test_hash_is_order_independent, bench/tests/test_claims_and_score.py::test_hash_changes_with_content

1. The corpus, the answer keys and the raw run outputs live outside the tracked tree.
2. The repository carries the canonical hash of a frozen key and never the key.
3. The harness code itself is ordinary open-source; the corpus and key never are.

### PROG-9 — A claim's identity is its value, page and region
**State:** contradicted-by-code
**Code:** bench/vivabench/keybuild.py:113, core/vivacore/claims.py:30 (`Claim.key`)
**Test:** none

1. A claim is identified by (value, page, region).
2. A label is an annotation, never a join key.

**Contradiction:** the identity rule this project adopted (see [extraction-and-confidence.md](extraction-and-confidence.md)) is (value, page, region). `Claim.key()` (core/vivacore/claims.py:30) returns `(type, normalized label)`, and `merge_drafts` (bench/vivabench/keybuild.py:113) indexes on that tuple and merges with `setdefault`, so within a label bucket the first claim wins and every later one is discarded with no count, no warning and no audit row. The extraction prompt manufactures the collision by instructing the model to label every line item identically *and* to emit all of them. Every ingredient of the real identity exists and is thrown away: the runner writes page, region and a page-namespaced group onto every claim, and nothing reads them back.

### PROG-10 — Five runs per document per candidate
**State:** by-review-with-exception
**Code:** bench/vivabench/config.py:37, bench/vivabench/config.py:128
**Test:** none

1. Each candidate reads each document five times, so self-consistency is measurable.

**Exception:** five is a dataclass default and a `models.yaml` fallback, not a refusal. `runs_per_document: 3` loads without complaint (contrast config.py:70, where an unpinned alias raises), and `viva-bench run --runs N` overrides it per run (bench/vivabench/cli.py:255). Nothing in the tree asserts five.

### PROG-11 — Unpinned model aliases are refused
**State:** by-review
**Code:** bench/vivabench/config.py:52, bench/vivabench/config.py:70
**Test:** none

1. A candidate configured with a "latest"-style alias is refused before any call is made.
2. Every run records the resolved model identity the endpoint reported, not just the configured string.

### PROG-12 — The circularity break is four steps
**State:** by-review-with-exception
**Code:** bench/vivabench/keybuild.py:58 (`draft_key` refuses fewer than two model families), :39 (`_agree`, the referee that exists), :158 (`freeze`); bench/vivabench/cli.py:170 (the audit worksheet), :196 (the author's rulings folded back), :203 (the hash)
**Test:** none

1. Two different model families independently draft the key.
2. Deterministic arithmetic referees both drafts, and what passes an identity is ground truth by proof rather than by model opinion.
3. Every disagreement, every arithmetic failure and a random 20% sample of the agreements go to the author, whose rulings are recorded with reasons.
4. The key is then frozen and hashed.

**Exception:** steps 1 and 4 are built. Step 2 is built in a weakened form: `_agree` (bench/vivabench/keybuild.py:39) is a deterministic referee over both drafts, but it compares the two readings to each other rather than running an arithmetic identity — `vivacore.verify.arithmetic` is written, tested and used by the product, and no bench module calls it, so `verified_by="arithmetic"` is never stamped though the schema enumerates it. Step 3 is partial: `draft-key` writes only the disagreements to the worksheet, so agreements are never spot-checked — the one check that would catch two models making the same mistake — and the worksheet has no reason field, `KeyEntry.notes` never being written. A frozen key's present authority is *two models agreed*.

### PROG-13 — The budget ceiling is hard, and breaching it is refused before it is spent
**State:** by-review-with-exception
**Code:** bench/vivabench/runner.py:271-276 (`BudgetExceeded`), bench/vivabench/runner.py:37
**Test:** none

1. Accumulated spend is checked against a configured ceiling and the run stops rather than continuing past it.
2. A plan whose projected spend breaches the ceiling is refused up front, with a stop-and-report.

**Exception:** assertion 2 is unmet, and assertion 1 holds only between cells. bench/vivabench/runner.py:272 compares *actual* accumulated spend against the ceiling before each cell and never inside one, so a run can overshoot by up to one cell's cost, and nothing is refused up front — a plan that will obviously breach the ceiling is discovered only after the ceiling is spent.

### PROG-14 — Source-region validity is graded
**State:** unmet
**Code:** bench/vivabench/score.py:167 (`Scorecard` carries no region metric)
**Test:** none

1. The exam checks whether the place a model says a figure came from actually contains it.
2. The provenance click-through threshold is drawn from that measurement.

**Note:** model-reported regions are captured raw by the runner and never read back, and the frozen key carries no region to check them against, so the number the trust policy would draw a threshold from does not exist. Note also that [document-preprocessing.md](document-preprocessing.md) F4/Q22 has since ruled the product's region anchor is the text layer's measured character boxes rather than the model's self-reported box, which narrows the honest v1 check to *the claimed page contains the value*, with the box comparison waiting on character-box extraction reaching `bench/`.

### PROG-15 — Cost and latency are reported per document per candidate
**State:** unmet
**Code:** bench/vivabench/score.py:167 (`Scorecard` has no cost or latency field)
**Test:** none

1. Each scorecard reports cost and latency per document, at each redundancy level, so the trust policy's autonomy ladder can be priced.

**Note:** the runner captures both faithfully (bench/vivabench/runner.py:210-216) and the reporter emits neither.

### PROG-16 — Model time and wall-clock time keep distinct names
**State:** by-review
**Code:** bench/vivabench/runner.py:211-216
**Test:** none

1. `latency_s` is the sum of the per-page model calls and does not move when page concurrency changes; it is the figure that compares candidates.
2. `wall_clock_s` is what the harness machine waited, and is a property of the harness configuration.
3. A concurrency setting is never reported as a speed result.

### PROG-17 — A frozen key's hash is stable
**State:** contradicted-by-code
**Code:** bench/vivabench/cli.py:183 (`cmd_freeze_key`), bench/vivabench/keybuild.py:158 (`freeze`)
**Test:** none

1. Only the key's hash is committed, so a future re-run can prove it used the identical key.

**Contradiction:** the doc says the key is frozen and hashed so future re-runs can prove they used the identical key. `cmd_freeze_key` re-reads the audit worksheet and appends every resolved row to `key.entries` on every invocation, and `freeze` (bench/vivabench/keybuild.py:158) only sets the flag and hashes what it is given, so entries grow with each pass and each pass commits a different hash.

### PROG-18 — Truncation during key building is warned about loudly
**State:** by-review
**Code:** bench/vivabench/keybuild.py:75-80
**Test:** none

1. A drafting run that was cut off mid-document raises an explicit warning rather than merely recording the fact.
2. A short key and a complete key are indistinguishable in the key's own terms, so only the run log can tell them apart.

## Why

A permanent, repeatable exam is what stands between a model and real financial documents, and what keeps it there. It has four parts: an exam paper of real documents, an answer key of every figure on them verified by a human, a proctor that administers the exam identically to every candidate forever, and a rubric that says what counts as right and — more importantly — how badly a candidate is punished for being *confidently* wrong.

**The corpus is real, not synthetic, and small.** Twelve to eighteen real documents across roughly seven types, weighted toward the author's actual financial life, plus two deliberately hard cases: a poor-quality scan and an unusual layout. Common types only would flatter every candidate, and the product's promise lives in the tail. Synthetic statements lack the true messiness — kerning artifacts, scan noise, inconsistent layouts — that causes real errors, so synthetic is the wrong tool for v1 ground truth and the right one for regional packs later. A fifty-document corpus buys better statistics at a ground-truthing cost that scales linearly in the author's hours, and twelve to eighteen documents already yield several hundred claims, enough to separate candidates decisively.

Synthetic documents have a second, compatible use that the rejection above does not touch. The synthetic corpus is generated as one coherent three-month life — a card payment that leaves checking and lands on the card, a pay stub whose net equals the payroll deposit, a brokerage contribution with two witnesses — because those cross-document facts are the only arithmetic an end-to-end run can be graded on that is known true by construction. A unit test with a stubbed reader cannot produce them: the stub supplies the very facts the matcher is meant to derive.

**The answer unit is a claim, not a total.** Every monetary amount, every date, every counterparty, masked account identifiers and document-level facts — roughly 30 to 80 per statement. Balances and totals alone would be cheap and would let a model that silently drops one transaction score perfectly while committing exactly the failure this project fears, so completeness has to be examined and line items are in. Boilerplate is out: legal text and marketing copy feed no verification, and scoring them would spend ground-truth hours on things the product never uses.

**The key must not be written by the thing it grades.** Using one model to write the key and grading models against it measures agreement with the scribe. The break is arithmetic: identities that pass are ground truth by proof rather than by opinion, with the author as the court of appeal wherever arithmetic cannot reach — payee names, dates nothing cross-validates. Fully manual keying is the purist option and was rejected because hand transcription introduces its own errors at hundreds of claims, and the arithmetic identities catch machine errors more reliably than tired eyes catch their own.

**Two levels are graded separately because they answer different questions.** The raw model level asks how good the candidate is alone: per-claim accuracy, recall (the silent-omission failure), self-consistency across repeats, source-region validity, and stated-confidence calibration — when a model says 90%, is it right nine times in ten? The system level asks how good the *pipeline* around the candidate is: verified-coverage, and the ruin metric, the confidently-wrong rate. The product promise rides on that number being near zero; everything else is economics. A single leaderboard score invites choosing the model that is best on average while hiding that it is occasionally, confidently, catastrophically wrong — the exact confusion this project exists to end.

**The roster spans the adoption ladder**: two pinned frontier models from different providers, because cross-model agreement needs independent families and two providers hedge one provider's quirks; one strong local vision model at a pinned quantisation; and one on-device-class small model for the zero-setup floor. Cloud-only would leave the local questions unanswered and the hybrid trajectory ungrounded; eight to ten candidates would multiply runs, reconciliation and findings complexity, and the exam is permanent, so latecomers can sit it later.

**The proctor rules are the fairness guarantee.** One prompt template for all candidates, asking for structured claims with source regions and self-stated confidence — the self-statement is measured, never trusted. Versions pinned and recorded; every request and response captured raw. No candidate ever sees the answer key or another candidate's output. Ambiguities in documents are ruled on by the author, and the rulings are logged.

**The system-level metric is currently agreement-only**, and that gap is stated rather than papered over. The definition is N samples plus cross-model agreement plus arithmetic verification; the implementation accepts a label when a majority of runs produced it and consults no balance reconciliation or line-item sum, so the reported figures approximate the designed metric and understate what the real pipeline would verify.

**What comes out** is a findings document held to the same honesty standard as everything else, scorecards per (model, document type), the frozen hash-anchored answer key, and the runnable harness. What it seeds is the continuous eval suite, the trust policy's first measured thresholds in place of placeholders, the flywheel baseline, and the pack format for future regional corpora.

**The community mode.** Alongside [format-commons.md](format-commons.md), the harness gains a lightweight sibling for users, distinct from the full exam: a single-document diagnostic — frontier blind read, verification, format-profile distillation — producing a shareable bundle of exactly two artifacts, the format profile (layout knowledge, zero personal values) and a scorecard for that format. Minutes rather than hours, one document rather than a corpus. It is the answer to "this document reads badly" in an open-source support loop: every complaint becomes a potential contribution. The contribution boundary holds for both modes: what may flow to the shared registry is profiles and scorecards only — never documents, never answer keys, never extracted values — and contribution is always an explicit, user-reviewed act, gated by the privacy lint and review. The full exam is the instrument for model admission; the diagnostic is the instrument for format knowledge. They share the adapters, the verification layer and the claim schema.

**The decided points**, settled by the author: seven corpus types with a one-to-two-document non-US stretch the author can personally verify; a $100 hard budget ceiling with a stop-and-report rule; four candidates spanning frontier, local and phone class; and five repeats.

## Open

- The key builder and the scorer join on labels rather than on identity (PROG-9). Until they join on (value, page, region), no accuracy, recall or coverage figure this harness produces is a measurement of the candidate — measured on the repo's own synthetic statement, two drafters reading perfectly and identically produced 35 claims and a 5-entry key, against which a candidate that omitted ten of eleven transactions graded accuracy 1.0, recall 1.0, and the reporter prints that false guarantee into every generated findings document.
- The built key schema is narrower than the design's list. `KeyEntry` stores raw text, locale, currency, type, label and the verified-by flag; it has no region, and its `page` field is declared and never populated at any construction site, although the runner records the authoritative page on every claim. The absence of a normalised-value field is deliberate and better — normalisation is derived at compare time and the key records its rules version, so storing it would duplicate a versioned derivation and could go stale against its own ruleset. The other two are what block the identity rule, source-region validity as a metric, and an audit queue that can put the page in front of the auditor.
- The single-document diagnostic command is specified and no such subcommand exists.
- Whether the on-device-class candidate is testable outside the platform vendor's own frameworks at v1, or approximated by the smallest available open vision model.
- Prompt-template sensitivity: v1 uses one shared template, and a small annex may test whether reasonable variations move accuracy. If they do, that is itself a finding about fragility.
