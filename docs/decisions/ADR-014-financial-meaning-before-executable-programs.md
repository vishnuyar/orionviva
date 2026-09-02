# ADR-014 · Financial meaning precedes executable programs

_This records reasoning, not current behaviour._

**Status:** Accepted · **Date:** 2026-09-02 · **Decided by:** Vishnu · **Binds:** the runtime answer compiler and its admission gate · **Door type:** two-way mechanism under the one-way trust ordering of ADR-013

**State:** built-with-exception
**Rules:** ADR-014
**Invariants touched:** T1, T2, T3, T8, I1, X2

## Rules

### ADR-014 — The model names financial meaning and typed parameters; deterministic code authors the executable AnswerProgram
**State:** enforced-with-exception
**Code:** product/viva/answer_program/compiler.py, product/viva/answer_program/intents.py, product/viva/answer_program/release.py
**Test:** product/tests/test_semantic_answering.py::test_model_contract_cannot_author_executable_program_fields, product/tests/test_semantic_answering.py::test_every_reviewed_family_lowers_and_validates_before_a_read

1. A runtime model may select only reviewed financial meaning, typed parameters,
   requested claims, or a structured non-answer outcome.
2. Deterministic code owns answer clauses, reads, financial queries, bindings,
   selectors, required-clause policy, and resource bounds.
3. The complete lowered program exists and passes the retained validator before
   any current-turn financial read. A bounded catalog of account, category, and
   counterparty identity metadata may be supplied for canonical selection; it
   carries no balances, amounts, movement rows, documents, or evidence.
4. Direct model-authored executable programs are not a runtime capability and
   no previous planner is a fallback.
5. Runtime availability requires exact-model admission of the compact contract
   and deterministic-builder digest.

**Exception:** the mechanism and publication gate are built, but no profile has
yet passed and been published for the new contract. Runtime answering therefore
remains unavailable outside explicit admission and Witness purposes.

## Context

The first one-shot AnswerProgram implementation preserved the right trust
ordering but assigned the model the wrong responsibility. It asked ordinary
language understanding and complete private-language program authorship to
succeed together. In the fresh Witness, the retained validator safely refused
malformed programs, but none of the seven ordinary questions produced a usable
answer. The lower deterministic runtime was not the common failure point.

ADR-013 says a sentence's shape and selection precede current-turn data and
deliberately leaves the mechanism reversible. This decision changes that
mechanism without changing the ordering.

## Alternatives considered

Restoring the iterative planner was rejected because it would restore a second
answer authority and the failure modes the one-shot runtime replaced.

Keeping direct executable authorship and improving prompts was rejected because
each new tool, query operator, selector, or policy field would expand a private
language every candidate model had to reproduce. Better instructions would not
remove that coupling.

A composable semantic claim language was deferred. It may ultimately support
more combinations, but it is another language and lowering engine. The product
does not yet have evidence that six reviewed primitive families create
combinatorial pressure.

The selected approach makes the model answer one question: what financial
meaning did the person request? Code answers the second: what exact bounded
program establishes it? This retains deterministic arithmetic, evidence,
binding, rendering, and fail-closed resource enforcement.

## Consequences

The initial runtime surface is narrower and honest about unsupported meaning.
Adding breadth requires a reviewed family and admission evidence. In exchange,
provider-swappability improves because a candidate model no longer learns the
executable grammar, and routine questions cannot fail because it misspelled an
internal graph.

Captures now keep both sides of the boundary: the semantic request and the
lowered program, each with a digest. The exact admission profile binds the
semantic prompt, schema, catalog, deterministic builders, retained runtime
contracts, canonical synthetic admission fixture, fully derived oracle set,
and resolved model identity. Every oracle is derived before the compiler or
provider is constructed, so an invalid case contract spends no live calls.

## Would reverse this

The mechanism is reversible. Evidence that a constrained semantic vocabulary
needs many near-duplicate families would justify designing the deferred
composable language. Repeated exact-profile results showing direct executable
authorship is reliable across multiple supported models could reopen that
option, but would not remove ADR-013's before-data ordering or ADR-010's ban on
model certification.
