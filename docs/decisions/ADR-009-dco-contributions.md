# ADR-009 · Contributions Under DCO

_This records reasoning, not current behaviour._

**Status:** Accepted · **Date:** 2026-07-19 · **Decided by:** Vishnu · **Door type:** one-way at first external merge

**State:** built
**Rules:** ADR-009

## Rules

### ADR-009 — Contributions come in under the Developer Certificate of Origin
**State:** by-review
**Code:** .github/workflows/dco.yml:1 · CONTRIBUTING.md:11
**Test:** none

1. A contributor adds `Signed-off-by` to their commits, certifying they have the right to submit the work under MIT.
2. Copyright remains the contributor's; the project is a patchwork of MIT-licensed contributions.
3. The rule is enforced by a DCO check on pull requests and documented in CONTRIBUTING.md before the repo invites contributions.
4. CONTRIBUTING.md also carries the trust-critical review policy: changes touching verification, crypto or the event log get adversarial review.

## Why

The day the first outside contribution merges, the copyright-holder set stops being one person, and the legal basis for inclusion must already be settled. Deciding afterwards is somewhere between expensive and impossible.

**A CLA** grants the project broad rights including unilateral relicensing, and preserves dual-licensing and open-core options. It was rejected on three grounds: signing friction deters exactly the security-minded reviewers this project most wants; a "we reserve the right to relicense" instrument is a dissonant signal from a project whose pitch is verifiable trust; and MIT's permissiveness already covers every commercial path that matters, since anyone including the author may build on or sell the code.

**Nothing at all** — implicit inbound-equals-outbound — is common in small repos and ambiguous when it matters. Ambiguity in the provenance of *code* is a poor look for a product about the provenance of *data*.

The consequence is accepted knowingly: contributed portions are MIT forever, and whole-project relicensing is foreclosed for practical purposes. Author-written code remains relicensable by the author alone, which under MIT is rarely needed.

## Would reverse this

Moving from DCO to a CLA later would require every past contributor's consent — treat as unavailable. This is the door closing, on purpose, in the community's favour.

## Open

Nothing open.
