# ADR-001 · Hybrid Model Strategy (cloud default, local path open)

_This records reasoning, not current behaviour._

**Status:** Accepted · **Date:** 2026-07-19 · **Decides:** which models read the user's documents, and where

**State:** built
**Rules:** ADR-001
**Invariants touched:** T2, T6, T8

## Rules

### ADR-001 — Cloud frontier models by default, under the user's own key, with the local path architecturally open
**State:** enforced-with-exception
**Code:** core/vivacore/models/spec.py:18 · core/vivacore/models/openai_compat.py:76
**Test:** core/tests/test_openai_continuation.py::test_continuation_stitches_and_drops_images

1. Extraction and conversation default to cloud frontier models, called under the user's own API key and zero-data-retention terms.
2. The tradeoff is stated plainly in the product rather than buried in a policy page.
3. The model layer is provider-swappable: nothing in the data model or the verification layer assumes a provider, or assumes that inference is remote.
4. A spec names the environment variable holding a key; a key is never part of the spec and never stored with it.
5. Data at rest stays fully local and encrypted regardless of where inference runs.
6. Verified extractions accumulate on the person's machine as labeled training pairs, exportable as training data.
7. Verification logic is never moved into model weights (ADR-010).

**Exception:** assertion 6 is unbuilt. Nothing in `product/viva` or `core/vivacore` accumulates or exports labeled training pairs; the two `export` functions in the tree are the merchant commons catalog (product/viva/ingest/categorize.py:298, merchant/merchantcore/catalog.py:161), which is a different artifact. The *Why* below says the export must exist from day one precisely because retrofitting it means re-deriving the labels.

## Why

Local-first is non-negotiable, and the best document-reading models are cloud APIs. Sending a bank statement to an API means the data transits and is processed off-device — a real tension with "your data, your keys."

Trust is the product, and the biggest near-term trust risk is *wrong numbers*, not API transit under zero-retention terms. A weaker local model that extracts wrong figures fails the never-bluff-a-number principle today; cloud transit under user-controlled keys is an honest, disclosed compromise of the local-first principle, and being honest about the compromise is itself an application of the principles.

The decision converges toward local rather than entrenching the cloud. The verification layer is model-agnostic, which *lowers* the quality bar a local model must clear, and the specialization flywheel is the mechanism: verified extractions accumulate as labeled pairs, and once sufficient, a personal fine-tune of a local model becomes the extraction default, with frontier fallback for novel documents and the unchanged verification layer grading everything. That is why the ledger must make verified extraction pairs trivially exportable from day one — retrofitting the export would mean re-deriving the labels.

Provider abstraction is a hard requirement on the model layer from the first commit, because a provider assumption that reaches the data model is not a swap afterwards.

## Would reverse this

Local models reaching the verified-accuracy bar, which flips the default; or cloud providers weakening zero-retention or key-custody terms, which accelerates local.

## Open

- The bar a local model must clear to flip the default is undefined; it is to be set when the first benchmark runs.
- The extraction benchmark should re-run each model generation, and nothing schedules it.
- Access modes beyond BYOK and a keyless local endpoint — OAuth-brokered, attested-cloud — have no implementation.
