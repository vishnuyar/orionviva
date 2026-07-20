# ADR-009 · Contributions Under DCO

**Status:** Accepted · **Date:** 2026-07-19 · **Decided by:** Vishnu · **Door type:** one-way at first external merge

## Context

The day the first outside contribution merges, the copyright-holder set stops being one person, and the legal basis for inclusion must already be settled. Deciding after is somewhere between expensive and impossible.

## Decision

Developer Certificate of Origin: contributors add `Signed-off-by` to commits, certifying they have the right to submit the work under MIT. Their copyright remains theirs; the project is a patchwork of MIT-licensed contributions. Enforced by a standard DCO check on pull requests; documented in CONTRIBUTING.md before the repo invites contributions.

## Alternatives considered

**CLA** — grants the project broad rights including unilateral relicensing; preserves dual-licensing/open-core options. Rejected: signing friction deters the security-minded reviewers this project most wants; a "we reserve the right to relicense" instrument is a dissonant signal from a project whose pitch is verifiable trust; and MIT's permissiveness already covers every commercial path that matters (anyone, including the author, may build on or sell the code).

**Nothing** (implicit inbound=outbound) — common in small repos, ambiguous when it matters. Rejected: ambiguity in provenance of *code* is a poor look for a product about provenance of *data*.

## Consequences

Contributed portions are MIT forever; whole-project relicensing is foreclosed for practical purposes — accepted knowingly alongside ADR-002. Author-written code remains relicensable by the author alone (rarely needed under MIT). CONTRIBUTING.md must also carry the trust-critical review policy (the discovery map, E5): changes touching verification, crypto, or the event log get adversarial review.

## Would reverse this

Moving DCO→CLA later would require every past contributor's consent — treat as unavailable. This is the door closing, on purpose, in the community's favor.
