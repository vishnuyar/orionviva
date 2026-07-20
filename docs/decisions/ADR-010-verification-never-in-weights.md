# ADR-010 · Verification Is Never Moved into Model Weights

**Status:** Accepted · **Date:** 2026-07-19 · **Door type:** one-way in reverse (the thesis becomes unfalsifiable the day this is violated)

## Context

The domain-model doc examined the tempting alternative — training a model to internalize the checking (tally balances, notice gaps, reconcile) so fewer explicit rules exist. The temptation will recur every time a model generation gets better, so the stance is recorded as a standing principle rather than a one-time analysis.

## Decision

The verification layer — arithmetic identities, cross-sample and cross-model agreement, completeness checks, confidence grading — is deterministic, inspectable code, permanently. Models *extract* and *converse*; they never *certify*. No confidence grade, reconciliation result, or arithmetic answer is ever produced inside a model's forward pass. This holds regardless of which model extracts (cloud frontier, personal LoRA from the domain-model doc flywheel, anything after).

## Alternatives considered

**Train the checking into a domain model** — fewer moving parts, and models will keep getting better at it. Rejected on principle, not capability: a model that tallied internally cannot show its work; a check that can't be audited isn't a check; and a fine-tuned model is still uncalibrated about its own errors — 98% accuracy means 1-in-50 confidently wrong, and the verification layer exists to catch exactly those. "Arithmetic in the model's head" is already a standing anti-goal; this ADR extends it to all certification.

**Model-as-verifier** (a second model checks the first) — useful as an *input signal* (cross-model agreement, the extraction doc) but never as the authority; two models agreeing is evidence, not proof. Deterministic identities that pass are proof.

## Consequences

The verification module is the product's crown jewel: small, boring, ferociously tested, and the natural candidate for the strictest engineering standard in the codebase (the form-factor doc's open question on whether it earns Rust or merciless testing). Every future "the model can just do this now" proposal is answered by pointing here.

## Would reverse this

Nothing. Models becoming perfect wouldn't reverse it — provable and correct are different properties, and the product sells the first.
