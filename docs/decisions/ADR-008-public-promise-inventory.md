# ADR-008 · Public Promise Inventory

_This records reasoning, not current behaviour._

**Status:** Accepted · **Date:** 2026-07-19 · **Door type:** one-way per entry (a public promise can be added, never withdrawn)

**State:** partial
**Rules:** ADR-008
**Invariants touched:** T1, T5, T6, X3

## Rules

### ADR-008 — The public promises are an explicit inventory, and nothing may promise more than it holds
**State:** untestable
**Code:** none found
**Test:** none

1. The promises are maintained as an explicit, versioned inventory, and this record is its founding entry.
2. Adding a promise is a deliberate act requiring an amendment here, and each addition states what evidence justifies making it.
3. No public statement — site, README, build log, release notes — may commit to more than the inventory holds.
4. The inventory holds only what the product can honor today; an aspirational promise is refused.
5. The inventory grows and never shrinks.

**The inventory, v1:**

1. **Never bluff a number.** Confidence language in answers maps only to verification grades; "I'm sure" requires `verified`. (T1, X2)
2. **Every figure cites its source.** No answer without provenance the person can follow to the record. (T1)
3. **Your data and keys stay with you.** Local-first; no hosted storage of decryptable personal financial data, ever. (T5)
4. **Nothing leaves your machine silently.** Only user-initiated model calls (ADR-001) and anonymous 32-byte anchor hashes (ADR-004); the complete outbound record is always visible in the product (ADR-006). (T6)
5. **You're the customer, not the product.** Paid directly; ad-free; data never sold, rented or mined.
6. **The code is open (MIT), so promises 1–5 are verifiable rather than asserted.** (ADR-002)
7. **Built in the open, mistakes included.** The build log reports what went wrong, not only what worked.
8. **Nothing irreversible happens without your explicit yes.** (X3)

## Why

Every public commitment is a trust ratchet: withdrawing one refutes the product thesis more efficiently than any bug could. The site and README already contained several promises, made at different times in different words. Unenumerated promises are the dangerous kind — they get made accidentally, in marketing copy or a build-log aside, and are discovered only when broken.

**No formal inventory** — on the ground that the principles docs cover it — was rejected: principles guide builders, promises bind to users, and the gap between them is where accidental commitments breed.

**Aspirational promises**, such as committing to selective disclosure before the single-user agent has earned trust, were rejected as the exact failure the project's anti-goals name.

The rule itself is a documentation discipline and has no code to enforce it; what enforcement exists lives under the invariants each promise maps to. The inventory belongs in the repo and eventually in the product itself.

## Would reverse this

Entries: nothing. The inventory only grows, deliberately.

## Open

- Nothing checks a public statement against the inventory, so promise 3 of this record holds by review alone.
- Promise 4's outbound record is unbuilt (ADR-006), so what the product can display falls short of what the promise says it always can.
- Site copy and README have not been audited against v1 for accidental over-promising.
