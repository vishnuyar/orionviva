# ADR-007 · Hybrid Record Identity (Permanent Random ID + Content Fingerprint)

**Status:** Accepted · **Date:** 2026-07-19 · **Decided by:** Vishnu · **Door type:** sticky-verging-on-one-way (every pointer references these forever)

## Context

Every provenance citation, correction, memory entry, and cross-reference will point at records — transactions, documents, figures, accounts — by ID, forever. An identity migration after a year of accumulated pointers is close to a rewrite. The scheme must survive the product's two defining behaviors: corrections are first-class, and the same reality arrives repeatedly (re-uploaded statements, overlapping exports).

## Decision

Two fields, two jobs. **Identity:** a random, permanent ID (UUIDv7-class, time-ordered) stamped at creation and never changed by anything — not corrections, not re-categorization, not schema migrations. **Recognition:** a content fingerprint (deterministic hash of normalized source fields) stored alongside, used at ingestion to detect duplicates and link re-observations of the same underlying fact. Corrections append events (ADR-004) referencing the unchanged ID; the fingerprint of the *original* extraction is retained for verification against source.

## Alternatives considered

**Content-derived IDs only** — elegant and self-verifying; the same record always names itself identically, so dedup is free. Fatal flaw here: correct a misread $1,200 to $1,300 and the record's identity changes, orphaning every pointer — in a product where corrections are core, this demands permanent migration machinery. (Patching it by hashing only the immutable original converges on the hybrid anyway.)

**Random IDs only** — simplest possible; but duplicate detection must then be solved separately and later, under pressure, and probably by adding the very fingerprint field this ADR adds calmly now.

## Consequences

Fingerprint normalization rules (which fields, how normalized, per record type) become part of the data-model deep-dive (the discovery map, A1) and must be versioned — fingerprints may be recomputed under new rules; IDs never. "Same fingerprint, different documents" (two identical $5.00 coffees on one day) is a known case: fingerprints *flag* candidate duplicates for the verification layer; they never silently merge.

## Would reverse this

Nothing reverses issued IDs. Fingerprint algorithms evolve freely behind versioning.
