# ADR-003 · Raw Capture Doctrine

**Status:** Accepted · **Date:** 2026-07-19 · **Door type:** one-way (uncaptured data is gone forever)

## Context

Irreversibility in this project lives mostly in what we fail to capture: a source region not recorded at extraction time can never be attached later; a model response discarded cannot be re-audited. Storage is cheap; the past is unrecoverable.

## Decision

From the first ingestion, keep forever, encrypted and immutable: (1) every original document exactly as received; (2) every model interaction during extraction — full request, full response, model identity/version, and every source-region claim; (3) every verification trail (which checks ran, what they found). Nothing on this list is ever pruned, summarized-in-place, or "cleaned up."

## Alternatives considered

**Keep originals only, discard model I/O** — smaller and tidier; loses the ability to audit *how* a figure was derived, to re-grade history when verification improves, and to harvest verified training pairs (the domain-model doc flywheel). Rejected: the discarded bytes are precisely the audit trail a trust product runs on.

**Retention window (e.g., 7 years)** — conventional in finance. Rejected: the trust arc's value grows with unbroken history, volumes are personal-scale (megabytes), and the user can always delete their own data — the *product* just never does it silently.

**Capture lazily, "add provenance later when needed"** — the classic mistake this ADR exists to forbid. Provenance cannot be retrofitted.

## Consequences

Extraction interfaces must be built capture-first: the raw exchange is written before any parsing touches it. Storage layout needs an immutable blob store beside the database (the storage doc). This doctrine is what demotes most other decisions from one-way to revisable — schemas, grades, and models can all be re-derived from retained truth.

**Amendment (2026-07-31) — one carve-out, and it is in the code.** Recorded
after the fact, because the decision above did not anticipate it. The recorded
request elides image payloads, replacing each with its page hash. The page bytes
are already stored once, content-addressed, in the page cache, so copying
megabytes of base64 into every run record would bloat the log without adding
evidence — the hash keeps the audit chain whole (run record → page hash → the
exact bytes) at a fraction of the size. This is the only exception to "the
request is stored verbatim", and it is conditional: what it drops is recoverable
**only while the page cache is retained**, which puts the page cache on this
ADR's never-pruned list rather than beside it.

**Amendment (2026-08-15) — on the extraction path the request is not stored at
all.** The decision's item (2) promises full request *and* full response for
every model interaction during extraction, and the amendment above calls the
elided image payload the **only** exception to storing a request verbatim. Both
overstate what the ingest path does. The event it writes carries the model, the
prompt version, the input mode, the raw response text, whether the response
parsed, and the cost and token counts — one per phase, `classify` and `extract`
— and no request field of any kind. The earlier carve-out still describes the
paths that *do* record a request; it is not the only gap, because one path
records none.

The position the code takes is that an extraction request is **reconstructable**
rather than stored: the source document is kept content-addressed, the prompt is
an immutable versioned file, and the recorded prompt version resolves to the
exact text that produced the reading, so the request can be rebuilt from what
the vault holds. That is a real argument, and this ADR has never been asked to
ratify it. Where it falls short of the decision is specific and worth naming:
reconstruction is faithful in **content** and not in **bytes**, so anything the
caller assembled around the prompt and the document is inference rather than
evidence, and it holds only as long as every prompt version stays resolvable
forever. The answering path shows the difference is a choice rather than a
limit — a `speak` capture stores the verbatim request beside the verbatim
response.

The decision above is not withdrawn and nothing here licenses dropping a
capture. This records that item (2) is unmet on the ingest path, so no reader
infers that an extraction request can be produced on demand. Whether the right
close is to build the capture or to ratify reconstruction is open, and this note
does not settle it.

## Would reverse this

Nothing foreseeable. Volume would have to grow ~six orders of magnitude before cost is a conversation.
