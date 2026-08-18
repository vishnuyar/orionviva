# ADR-003 · Raw Capture Doctrine

_This records reasoning, not current behaviour._

**Status:** Accepted · **Date:** 2026-07-19 · **Door type:** one-way (uncaptured data is gone forever)

**State:** partial
**Rules:** ADR-003
**Invariants touched:** T3, T5

## Rules

### ADR-003 — Originals, model I/O and verification trails are captured before parsing and kept forever
**State:** enforced-with-exception
**Code:** product/viva/ingest/raw_store.py:51 · product/viva/ledger/events.py:271 · core/vivacore/models/base.py:169
**Test:** product/tests/test_raw_store.py::test_put_is_content_addressed

1. Every original document is stored exactly as received, encrypted and immutable, before any parsing touches it.
2. Every model interaction during extraction is stored: full request, full response, model identity and version, and every source-region claim.
3. Every verification trail is stored: which checks ran and what they found.
4. Nothing on that list is ever pruned, summarized in place, or cleaned up.
5. Extraction interfaces are built capture-first: the raw exchange is written before parsing.
6. A recorded request may elide an image payload, replacing it with the page hash, and only while the page cache is retained — which puts the page cache on the never-pruned list.

**Exception:** assertion 2 is unmet on the ingest path. `read_recorded` (product/viva/ledger/events.py:271) carries the model, the prompt version, the input mode, the raw response text, whether it parsed, and the cost and token counts — and no request field of any kind. The image-elision carve-out (core/vivacore/models/base.py:169) describes the paths that *do* record a request; it is not the only gap, because one path records none. The answering path stores the request verbatim (product/viva/speak.py:600), so the difference is a choice rather than a limit.

## Why

Irreversibility in this project lives mostly in what is not captured: a source region not recorded at extraction time can never be attached later, and a model response discarded cannot be re-audited. Storage is cheap and the past is unrecoverable.

**Keeping originals and discarding model I/O** is smaller and tidier, and it loses the ability to audit *how* a figure was derived, to re-grade history when verification improves, and to harvest verified training pairs for the specialization flywheel. The discarded bytes are precisely the audit trail a trust product runs on.

**A retention window** is conventional in finance and rejected here: the trust arc's value grows with unbroken history, volumes are personal-scale, and the person can always delete their own data — the product just never does it silently.

**Capturing lazily and adding provenance later** is the classic mistake this record exists to forbid. Provenance cannot be retrofitted.

The doctrine is also what demotes most other decisions from one-way to revisable: schemas, grades and models can all be re-derived from retained truth.

The position the ingest code takes is that an extraction request is *reconstructable* rather than stored — the source document is content-addressed, the prompt is an immutable versioned file, and the recorded prompt version resolves to the exact text that produced the reading. That is a real argument, and it has never been ratified here. Where it falls short is specific: reconstruction is faithful in **content** and not in **bytes**, so anything the caller assembled around the prompt and the document is inference rather than evidence, and it holds only as long as every prompt version stays resolvable forever.

## Would reverse this

Nothing foreseeable. Volume would have to grow roughly six orders of magnitude before cost is a conversation.

## Open

- Whether the right close on the ingest request is to build the capture or to ratify reconstruction. Nothing here settles it, and nothing here licenses dropping a capture.
