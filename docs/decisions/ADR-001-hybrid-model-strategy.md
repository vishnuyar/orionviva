# ADR-001 · Hybrid Model Strategy (cloud default, local path open)

**Status:** Accepted · **Date:** 2026-07-19 · **Decides:** which models read the user's documents, and where

## Context

Local-first is a non-negotiable principle, but the best document-reading models are cloud APIs. Sending a bank statement to an API means the data transits and is processed off-device — a real tension with "your data, your keys." Local VLMs (Qwen3-VL class) are credible but not yet trustworthy enough, unverified, for financial extraction (see the agent-landscape and extraction docs).

## Decision

Default to cloud frontier models for extraction and conversation, under the user's own API key and zero-data-retention terms, with the tradeoff stated plainly in the product — never buried. Keep the local-model path architecturally open: the model layer is provider-swappable, and nothing in the data model or verification layer may assume a specific provider or that inference is remote.

## Rationale

Trust is the product, and the biggest near-term trust risk is *wrong numbers*, not API transit under ZDR terms. A weaker local model that extracts wrong figures fails principle 2 (never bluff a number) today; cloud transit under user-controlled keys is an honest, disclosed compromise of principle 3. Honesty about the compromise is itself an application of the principles. Meanwhile, the verification layer (the extraction doc) is model-agnostic and *lowers* the quality bar a local model must clear — so this decision converges toward local-by-default over time rather than entrenching the cloud.

## Consequences

- The product must show, in plain language, what leaves the machine and under what terms; this belongs in the UI, not a policy page.
- Data at rest remains fully local and encrypted regardless of inference location.
- The extraction benchmark (discovery experiment 1) re-runs each model generation; a local model that matches cloud accuracy *with verification* flips the default. Define that bar when the first benchmark runs.
- Provider abstraction is a hard requirement on the model layer from commit one.

## Would reverse this

Local models reaching the verified-accuracy bar (→ local default), or cloud providers weakening ZDR/key-custody terms (→ accelerate local).

## Amendment (2026-07-19)

The domain-model doc reframes the local path from "kept open" to a mechanism — the **specialization flywheel**: verified extractions accumulate as labeled training pairs on the user's machine; once sufficient, a personal LoRA of a local VLM becomes the extraction default, with frontier fallback for novel documents and the (unchanged) verification layer grading everything. Consequence added: the ledger must make verified extraction pairs trivially exportable as training data from day one. Also elevated to principle: verification logic is never moved into model weights.
