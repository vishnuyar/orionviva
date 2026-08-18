# ADR-010 · Verification Is Never Moved into Model Weights

_This records reasoning, not current behaviour._

**Status:** Accepted · **Date:** 2026-07-19 · **Door type:** one-way in reverse (the thesis becomes unfalsifiable the day this is violated)

**State:** built
**Rules:** ADR-010
**Invariants touched:** T2, T8

## Rules

### ADR-010 — Models extract and converse; they never certify
**State:** enforced
**Code:** core/vivacore/verify/arithmetic.py:1 · core/vivacore/verify/match.py:1
**Test:** core/tests/test_arithmetic.py::test_float_poison_rejected

1. The verification layer — arithmetic identities, cross-sample and cross-model agreement, completeness checks, confidence grading — is deterministic, inspectable code, permanently.
2. No confidence grade, reconciliation result or arithmetic answer is produced inside a model's forward pass.
3. This holds regardless of which model extracts: cloud frontier, a personal fine-tune, or anything after.
4. Cross-model agreement is an input signal and never the authority.
5. No model is asked to check another model's work; a check compares declarations the code itself put there.

## Why

The tempting alternative is to train a model to internalize the checking — tally balances, notice gaps, reconcile — so that fewer explicit rules exist. The temptation recurs every time a model generation gets better, which is why the stance is recorded as a standing principle rather than a one-time analysis.

**Training the checking into a domain model** means fewer moving parts, and models will keep getting better at it. It is rejected on principle rather than on capability: a model that tallied internally cannot show its work, a check that cannot be audited is not a check, and a fine-tuned model is still uncalibrated about its own errors — 98% accuracy means one in fifty confidently wrong, and the verification layer exists to catch exactly those.

**Model-as-verifier**, a second model checking the first, is useful as an input signal and never as the authority. Two models agreeing is evidence; a deterministic identity that passes is proof.

The verification module is therefore the product's crown jewel: small, boring, ferociously tested, and the natural candidate for the strictest engineering standard in the codebase. Every future "the model can just do this now" proposal is answered by pointing here.

A later reader who finds a model on both sides of a check — one proposing structure at each end — should not conclude that this decision conflicts with the shape mechanism (ADR-013). It does not: the model proposes structure at both ends and certifies nothing at either, and the checks compare declarations the code itself put there.

## Would reverse this

Nothing. Models becoming perfect would not reverse it — provable and correct are different properties, and the product sells the first.

## Open

- Whether the verification module earns a stricter language or merely merciless testing is unruled.
