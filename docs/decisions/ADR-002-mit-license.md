# ADR-002 · MIT License

_This records reasoning, not current behaviour._

**Status:** Accepted · **Date:** 2026-07-19 · **Decided by:** Vishnu · **Door type:** one-way once external contributions exist

**State:** built
**Rules:** ADR-002

## Rules

### ADR-002 — The project is MIT-licensed
**State:** by-review
**Code:** LICENSE:1
**Test:** none

1. The repository is licensed MIT, and every public statement of the license says MIT.
2. Closed forks are legal and accepted; the license is not the moat.
3. Contributions pair with the DCO (ADR-009) rather than a CLA.

## Why

The repo LICENSE and the project principles said MIT while the site footer said AGPL-3.0. The inconsistency sat on a one-way door: license changes require the consent of every copyright holder, so the choice had to be settled before the first external contribution merged.

**AGPL-3.0** is copyleft with a network clause: anyone offering OrionViva as a hosted service must publish their modifications, which protects against a closed-source SaaS fork monetizing the code without contributing back. Its cost is that it chills adoption and embedding — many companies ban AGPL outright — and it adds licensing complexity to a project whose promise is *read the code, verify the promise*.

**MIT** is maximally permissive: anyone may use, modify, sell or close a fork. The verifiability promise is strongest when nothing impedes reading, running and reusing the code. The AGPL's protection matters most for hosted software, and OrionViva is local-first with no hosted offering, so the scenario AGPL defends against is peripheral. A closed fork cannot take the two things that matter — the person's own data, and the earned trust of the open project.

## Would reverse this

Practically nothing, once external contributions exist. That is the point of deciding now.

## Open

Nothing open.
