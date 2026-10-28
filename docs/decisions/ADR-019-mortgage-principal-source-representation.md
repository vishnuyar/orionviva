# ADR-019 — Mortgage principal source representation

Date: 2026-10-26
Status: Accepted design; implementation and acceptance evidence are separate.

## Context

A mortgage can print a negative effect on principal while canonical principal
movements require positive magnitudes whose explicit kind supplies direction.
Copying the printed negative scalar faithfully into a magnitude field fails
that invariant; taking every absolute value would hide contradictory proposals.

## Decision

The mortgage-principal-source-v2 profile selects immutable mortgage-base-v2
and the reviewed mortgage-v3 guidance fragment, with a backend-owned
normalization context schema2. Historical mortgage-base-v2 plus mortgage-v2
reads remain compatible under the same source contract. Numeric normalization remains
nv1. A closed signed source row preserves signed_effect raw text and page,
effect_basis=principal_balance_effect-v1, explicit kind and kind_source page.
Only a nonzero finite effect agreeing with that explicit kind lowers to the
unchanged positive canonical magnitude. The magnitude variant remains valid.
Negative payment or escrow fields do not acquire this interpretation.

Verbatim extraction responses, linked transport receipts and the typed context
retain the original representation through replay and export. Page pointers
identify proposed evidence; they do not certify that a model read it correctly.
Ordinary financial reconciliation and grade rules continue after parsing.

Schema1, absent legacy context and v1 prompts retain their prior interpretation.
A historical failed signed magnitude remains failed; rebuilding does not opt it
into the new contract. New context/prompt mismatches reject. A fresh model
reading must retain its own prompt, context, failure history and cost.

## Alternatives and reversibility

Prompt-only positive magnitudes cannot faithfully represent a signed-only source.
Unconditional absolute value and signed canonical flows risk double reversal.
Both were rejected. The active mortgage profile can select a later reviewed
contract, but recorded contexts and released prompts remain immutable.

The v3 fragment clarifies printed escrow identity scope without changing this
financial decision or the source schema. The escrow reference must be its own
explicitly printed identifier. A common institution or holder header supplies
a field only when it unambiguously governs escrow; missing, unreadable,
competing or ambiguous fields keep escrow.identity null. Loan, payment, property
and continuity references cannot replace its reference. Existing reconciliation,
source-page, identity and once-only household cash protections still apply.
Actual-model source comparison remains an outstanding Witness obligation;
offline structured replies do not establish model compliance.
