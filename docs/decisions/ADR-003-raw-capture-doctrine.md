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

## Would reverse this

Nothing foreseeable. Volume would have to grow ~six orders of magnitude before cost is a conversation.
