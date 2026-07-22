# v0 Scope — "one honest answer"

**Status:** Draft — the first architecture-phase artifact · **Last updated:** 2026-07-21 · **Decisions in:** first answer = *balance* (attested, cleanest trust proof); build order = *trust-core first, conversational AI second*.
**Invariants touched:** all of T1–T8 are exercised for the first time end-to-end; X2 (honest uncertainty in the answer); this doc is where "the whole has never been assembled" (synthesis risk #1) gets retired.

## The one sentence

v0 ingests one real checking-account statement, extracts and *verifies* it, posts it to an encrypted double-entry ledger, and answers **"what's my balance?"** with the figure, its confidence grade, and a tap-through to the exact spot on the source page — with **no LLM anywhere in the answer path.**

## Why this slice (the discipline of subtraction)

v0's job is not to impress; it is to **assemble the trust loop once, end to end, using the parts already proven** (`verify/`, `models/` from viva-bench). Balance is chosen because every link is `verified` — attested by the statement, confirmed by reconciliation — so if the answer is wrong we know exactly which link broke. Everything that adds a *second* trust level or a new subsystem is explicitly deferred.

## In scope (the whole chain, thinnest viable)

1. **Ingest** one checking statement (PDF), `text+image` mode (the measured-best ingestion), page-at-a-time.
2. **Extract** claims via the existing model layer (`models/`), captured raw (T3), no tools/writes to the model (the powerless reader, B2).
3. **Verify** with `verify/`: normalize (locale-aware), and run the **balance identity** (opening + transactions = closing). Grade each figure (`verified`/`corroborated`/`unverified`/`conflicted`).
4. **Post** to a **double-entry ledger** stored as **encrypted, append-only events** (T4, T5): opening-balance posting + one posting per transaction, balancing against an Opening Balance Equity account (individual-as-enterprise).
5. **Project** a running balance for the account from the event log.
6. **Answer** "what's my balance?" via a *fixed* code path (no LLM): return the figure + grade + provenance pointer, and — if reconciliation failed or a statement is missing — say so honestly (X2).
7. **Show it**: a minimal local viewer where the answer's number is tappable → opens the source page to the exact region (the provenance round-trip, experiment 3, finally demonstrated).

## Explicitly deferred (named so they don't creep in)

The conversational NL agent + twelve tools · categorization / spending (the inferred leg) · multi-account & multi-currency consolidation · the knowledge/expectations engine · format commons · memory/corrections · persona/voice (v0 uses plain, neutral phrasing) · sync/multi-device · anchoring (the log is append-only + hash-chained now; external anchoring can be stubbed) · dashboard richness. Each is a clean later increment; none is on the critical path to one honest answer.

## Build sequence (efficient order, reusing what's proven)

1. **Lift the embryos up.** Move `verify/` and `models/` from `bench/vivabench/` into a shared product package so bench and product share one copy (they are the same crown-jewel code). *Small, mechanical, high-leverage.*
2. **The encrypted event ledger** (the new heart): event store (append-only, hash-chained, encrypted-at-rest), postings, the double-entry rule, and the running-balance projection. This is where most new code lives.
3. **The ingest→verify→post pipeline**, wired **headless** first: a script that takes a statement and lands verified postings in the ledger, reconciled. *This is the moment the chain first exists.*
4. **The fixed answer path**: `balance(account, as_of)` → figure + grade + provenance, with a headless test proving "one honest answer" (and proving it says so when it *can't* answer confidently).
5. **The minimal provenance viewer**: the smallest local UI that renders the answer and does tap-to-source. *The first thing a human looks at.*
6. **Stop. Assess against the invariants.** Only then plan increment 2 (the NL agent).

Steps 1–4 are headless and testable — trust proven before any pixel. Step 5 is the first UI, kept deliberately minimal.

## Two decisions still yours (background + alternatives)

**A · Stack / language.** *Recommendation: Python.* Background: `verify/` and `models/` are already Python and tested; reusing them directly means zero rewrite of the crown jewel, and Python's the fastest path to a working ledger + pipeline. The trade a purist might weigh: a stricter language (Rust) for the verification/ledger core buys compile-time guarantees on the most correctness-critical code — but at a large solo-maintainer cost and a rewrite of proven code, and merciless tests give us most of the assurance already. *Alternative if you prefer:* keep everything Python for v0, and revisit whether the *ledger+verify core* graduates to Rust only if v0 exposes a real correctness pain. My call: Python now; don't rewrite what's proven.

**B · v0 surface / form factor.** *Recommendation: a minimal local web page served by the Python app (localhost).* Background: the provenance round-trip *needs* a visual surface (tap a number, see the source region) — a CLI can't show that, and it's the single most important thing v0 demonstrates. A local web page is the lowest-effort way to get tap-to-source, is cross-platform, and later graduates into the real dashboard (and eventually a Tauri desktop shell) without a rewrite. *Alternatives:* (i) CLI-only — cheaper, but can't show provenance click-through, so it fails v0's headline demo; (ii) jump straight to a native desktop app (Tauri) — nicer feel, but more build surface than a trust proof needs. My call: minimal local web page for v0; defer the desktop shell.

## Definition of done (v0 is "done" when…)

You drop your own checking statement onto a local page, and it shows *your balance, marked verified, and tapping it opens the statement to the exact line* — and when you feed a statement whose math doesn't reconcile, or with a month missing, it **says so** instead of bluffing. That is the thesis, working, for the first time, on real money.

## What this retires and what it opens

Retires synthesis risk #1 ("never assembled"). Opens increment 2 (the conversational agent + persona — where Viva's *soul* finally gets built, on top of a trust core already proven). The ADRs this phase still owes: the ledger/event-store decision (storage engine), the confidence-grade vocabulary as a formal ADR, and — recorded here — stack=Python and surface=local-web for v0.

## Open questions (register)

- Q37: Event store engine — encrypted SQLite (SQLCipher) vs append-only encrypted JSONL vs an embedded event-store lib; decide at step 2 with the simplest-that-works rule.
- Q38: The exact double-entry posting shape for a checking statement (deposits, withdrawals, fees) and how Opening Balance Equity is seeded from the statement's opening balance.
- Q39: Minimal viewer tech — plain HTML+JS served locally vs a small framework; keep it boring and dependency-light.
