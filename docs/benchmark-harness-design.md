# Benchmark Harness Design — the admission exam for models

**Status:** Approved — all four decision points settled 2026-07-20 (§8) · **Last updated:** 2026-07-20
**Invariants touched:** T1 (provenance+confidence is what we're measuring), T2 (deterministic scoring), T3 (raw capture of every exam run), T8 (pinned versions), I1–I2 (currency + locale-aware normalization in scoring), I4 (answer key carries locale from day one), I6 (pack-extensible), X2 (calibration is the headline metric)

## 1 · What this is, in one paragraph

A permanent, repeatable exam that any model must pass before it touches real financial documents, and must keep passing to keep its standing (model trust policy). It has four parts: an **exam paper** (real documents), an **answer key** (every figure on them, verified by a human), a **proctor** (a small program that administers the exam identically to every candidate, forever), and a **grading rubric** (what counts as right, and — more importantly — how badly a candidate is punished for being *confidently* wrong). Version one settles Q1 (is model confidence meaningful?), Q8 (how far behind are local models?), Q9 (the flywheel's baseline), and Q13 (the zero-setup on-device floor).

## 2 · The exam paper (corpus)

**Recommendation:** 12–18 real documents from the author's own institutions, spanning roughly seven types — checking/savings statement, credit card statement, brokerage statement, retirement account statement, an insurance document, a pay stub, a loan or mortgage statement — weighted toward what the author's actual financial life contains, **plus two deliberately hard cases**: one poor-quality scan (photographed page, skew, shadow) and one unusual layout. Optionally 1–2 non-US documents *if* the author can personally verify them (I6 stretch test).

**Alternatives considered:** *Common types only* — cheaper to ground-truth, but the exam would flatter every candidate; the product's promise ("no unsupported institution") lives in the tail. *Synthetic documents* — infinitely available, privacy-clean, but synthetic statements lack the true messiness (kerning artifacts, scan noise, inconsistent layouts) that causes real errors; synthetic is the right tool for *regional packs* later (I6), not for v1 ground truth. *Massive corpus (50+)* — better statistics, but ground-truthing cost scales linearly with the author's hours, and 12–18 documents already yield several hundred figures, enough to separate candidates decisively.

## 3 · The questions (what counts as an answer unit)

Each document decomposes into **claims** — the atomic facts the verification layer would need: every monetary amount (transactions, balances, totals, fees, rates), every date, every counterparty/description, account identifiers (masked forms), and document-level facts (institution, account type, statement period, currency). Expected volume: roughly 30–80 claims per statement.

**Alternatives:** *Balances and totals only* — cheap, but a model that silently drops one transaction would score perfectly while being exactly the failure we fear; completeness (recall) must be examined, so line items are in. *Everything including boilerplate* — legal text and marketing copy don't feed verification; scoring them wastes ground-truth hours on things the product never uses.

## 4 · The answer key (ground truth), and how we avoid grading models with a model

Every claim in the key stores: raw text **as printed** (e.g., "1.234,56"), normalized value, currency (I1), locale (I4), claim type, page and approximate region, and a verified-by flag. The key never enters the repo — it stays on the author's machine, encrypted; only its hash is committed, so future re-runs can prove they used the identical key (raw-capture spirit).

**The circularity trap:** using one model to write the key and then grading models against it would just measure agreement with the scribe. **The break, four steps:** (1) two *different* model families independently draft the key; (2) the deterministic arithmetic checks run over both drafts — balances must reconcile, line items must sum, dates must order; arithmetic that passes is ground truth by *proof*, not by model opinion; (3) every disagreement between the two drafts, every arithmetic failure, and a random 20% audit sample go to the author's eyes — the ground-truth authority and court of appeal, with rulings recorded with reasons; (4) the key is then frozen and hashed. Estimated human effort: a few focused hours, concentrated exactly where math can't reach (payee names, dates the checks can't cross-validate).

**Alternative:** *fully manual keying* — the purist option; rejected because transcription by hand introduces its own errors at hundreds of claims, and the arithmetic identities catch machine errors more reliably than tired human eyes catch their own.

## 5 · The grading rubric (metrics)

Two levels are graded separately, because they answer different questions:

- **Raw model level** — how good is the candidate alone? Per-claim accuracy (strict and normalized match), **recall** (did it miss claims entirely? the silent-omission failure), self-consistency across repeat runs, source-region validity (does the place it *says* the figure came from actually contain it — this gates provenance click-through), and stated-confidence calibration: when the model says 90%, is it right nine times in ten? (Research says no — Q1 makes this measurable.)
- **System level** — how good is the *pipeline* (N samples + cross-model agreement + arithmetic verification) built around the candidate? Headline metrics: **verified-coverage** (what share of claims the system can grade `verified` or `corroborated`) and the ruin metric, **confidently-wrong rate** — how often something graded `verified`/`corroborated` is actually false. The product promise rides on this number being ~zero; everything else is economics.
- **Economics** — cost and latency per document, per candidate, at each redundancy level (this prices the trust policy's autonomy ladder).

**Alternative rejected:** a single leaderboard score (F1). One number invites choosing the model that's "best on average" while hiding that it's occasionally, confidently, catastrophically wrong — the exact confusion this project exists to end. The output is a **scorecard per (model, document type, locale)**, no composite.

## 6 · The candidates (v1 roster)

**Recommendation — four, spanning the adoption ladder's rungs:** two pinned frontier cloud models from *different* providers (cross-model agreement needs independent families; two also hedges the finding against one provider's quirks), one strong local VLM (Qwen3-VL-class at a pinned quantization, run on the author's machine), and one on-device-class small model (AFM-tier, for Q13's zero-setup floor).

**Alternatives:** *cloud-only* — cheaper, but leaves Q8/Q13 unanswered and the hybrid trajectory (ADR-001) ungrounded; *kitchen sink (8–10 models)* — each candidate multiplies runs, ground-truth reconciliation, and findings complexity; the exam is permanent, so latecomers can simply sit it later.

## 7 · Proctor rules (protocol)

Identical prompt template for all candidates (asking for structured claims with source regions and self-stated confidence — we measure the self-statement, we never *trust* it). **N = 5** runs per document per model — enough to measure self-consistency with usable statistics; 3 is too noisy to distinguish flakiness from bad luck, 10 doubles cost for diminishing precision. Versions pinned and recorded (T8); every request and response captured raw (T3); no candidate ever sees the answer key or another candidate's output; ambiguities in documents ruled on by the author, rulings logged. The harness code itself is ordinary open-source (MIT, in the repo); the corpus and key never are. Scoring is deterministic code (T2) — normalization rules locale-aware and versioned (I2).

**Budget estimate:** ~15 documents × 4 candidates × 5 runs = ~300 runs, of which ~150 hit paid APIs. At mid-2026 frontier pricing with multi-page documents, plausibly **$20–60 total**; ceiling proposed at $100 with a stop-and-report rule if the projection breaches it. Local candidates cost only compute time.

## 8 · Decision points — settled (author decision, 2026-07-20)

- **D-a Corpus mix:** seven types, US + non-US stretch (1–2 non-US documents the author can personally verify, if held).
- **D-b Budget ceiling:** $100 hard stop, stop-and-report rule if projections breach it.
- **D-c Roster:** four candidates — Claude (pinned) + GPT (pinned) + Qwen3-VL-class local + phone-class tiny model.
- **D-d Repeat count:** N=5.

## 9 · What comes out, and what it seeds

Outputs: a findings doc (same honesty standard as everything — published to the build log even if embarrassing); scorecards v1 per (model, doc type); the frozen, hash-anchored answer key; the runnable harness. Seeds: the A8 continuous-eval suite (same key, re-run on schedule), the trust policy's first real thresholds (replacing placeholders with measured numbers), the flywheel's baseline (Q9), and the I6 pack format for future regional corpora.

## Amendment (2026-07-20): the community mode — `probe`

Added alongside [format-commons.md](format-commons.md): the harness gains a lightweight sibling command for users, distinct from the full exam.

**`viva-bench probe <document>`** — the single-document diagnostic: frontier blind read → verification → format-profile distillation → a **shareable diagnostic bundle** containing exactly two artifacts: the format profile (layout knowledge, zero personal values) and a scorecard (accuracy statistics for that format). Minutes, not hours; one document, not a corpus. This is the answer to "this document reads badly" in the open-source support loop: every complaint becomes a potential contribution.

**The contribution boundary, stated once for both modes:** what may flow to the shared registry is *profiles and scorecards only* — never documents, never answer keys, never extracted values. Contribution is always an explicit, user-reviewed act (ADR-006), gated by the privacy lint and PR review (format-commons lifecycle step 5). The full exam remains the instrument for *model admission*; `probe` is the instrument for *format knowledge*. They share the adapters, verify/, and the claim schema — the same embryos, two purposes.

**Future harness mode** (noted in format-commons): profile-guided vs blind extraction on the same corpus, measuring what a profile buys in accuracy and cost.

## Open questions

- Whether the on-device-class candidate is testable outside Apple's frameworks at v1, or approximated by the smallest available open VLM (a Q13 measurement detail).
- Prompt-template sensitivity: v1 uses one shared template; a small annex may test whether reasonable template variations move accuracy (if they do, that's itself a finding about fragility).
