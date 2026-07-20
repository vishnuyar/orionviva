# ADR-002 · MIT License

**Status:** Accepted · **Date:** 2026-07-19 · **Decided by:** Vishnu · **Door type:** one-way once external contributions exist

## Context

The repo LICENSE and the project principles said MIT; the site homepage footer said AGPL-3.0. The inconsistency sat on a one-way door: license changes require consent of every copyright holder, so the choice must be settled before the first external contribution merges.

## Alternatives considered

**AGPL-3.0** — copyleft with a network clause: anyone offering OrionViva as a hosted service must publish their modifications. Protects against a closed-source SaaS fork monetizing the code without contributing back. Cost: chills adoption and embedding (many companies ban AGPL outright), and adds licensing complexity to a project whose promise is "read the code, verify the promise."

**MIT (chosen)** — maximally permissive: anyone may use, modify, sell, or close a fork. The verifiability promise ("you never have to take it on faith") is strongest when nothing impedes reading, running, and reusing the code. The AGPL's protection matters most for hosted software; OrionViva is local-first with no hosted offering, so the scenario AGPL defends against is peripheral. A closed fork cannot take the two things that matter — the user's own data and the earned trust of the open project.

## Decision

MIT, as the repo already states.

## Consequences

Site footers fixed (`orionviva-web` commit `079dd4c`, all pages now read "Open source (MIT)"); repo README carries a MIT License section again. Pair with DCO for contributions (ADR-009). Accept that closed forks are legal; the moat was never the license.

## Would reverse this

Practically nothing after external contributions exist — that is the point of deciding now.
