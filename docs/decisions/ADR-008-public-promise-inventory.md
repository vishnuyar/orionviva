# ADR-008 · Public Promise Inventory

**Status:** Accepted · **Date:** 2026-07-19 · **Door type:** one-way per entry (a public promise can be added, never withdrawn)

## Context

Every public commitment is a trust ratchet: withdrawing one refutes the product thesis more efficiently than any bug could. The site and README already contain several promises, made at different times in different words. Unenumerated promises are the dangerous kind — they get made accidentally, in marketing copy or a build-log aside, and discovered only when broken.

## Decision

The promises are maintained as an explicit, versioned inventory — this ADR is its founding record. Adding a promise is a deliberate act requiring an ADR amendment; no public statement (site, README, build log, release notes) may commit to more than the inventory holds.

**The inventory, v1:**

1. **Never bluff a number.** Confidence language in answers maps only to verification grades; "I'm sure" requires `verified`.
2. **Every figure cites its source.** No answer without provenance the user can follow to the record.
3. **Your data and keys stay with you.** Local-first; no hosted storage of decryptable personal financial data, ever.
4. **Nothing leaves your machine silently.** Only user-initiated model calls (ADR-001) and anonymous 32-byte anchor hashes (ADR-004); the complete outbound record is always visible in the product (ADR-006).
5. **You're the customer, not the product.** Paid directly; ad-free; data never sold, rented, or mined.
6. **The code is open (MIT), so promises 1–5 are verifiable, not asserted.**
7. **Built in the open, mistakes included.** The build log reports what went wrong, not only what worked.
8. **Nothing irreversible happens without your explicit yes.**

## Alternatives considered

**No formal inventory** ("the principles docs cover it") — rejected: principles guide builders; promises bind to users. The gap between them is where accidental commitments breed.

**Aspirational promises** (e.g., committing Phase 4 selective disclosure now) — rejected: promising the arc before the single-user agent has earned trust is the exact failure the project's anti-goals name. The inventory holds only what the product can honor *today or at v0*.

## Consequences

Site copy and README should be audited against v1 for accidental over-promising (e.g., marketing language implying advice or guarantees). Each future promise addition states what evidence justifies making it. The inventory belongs in the repo and eventually in the product itself.

## Would reverse this

Entries: nothing. The inventory only grows, deliberately.
