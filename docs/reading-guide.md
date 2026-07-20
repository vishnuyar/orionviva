# Reading Guide — where every document sits

**Status:** Living — this is the only place document order exists · **Last updated:** 2026-07-19

## Why this doc

Filenames carry no numbers, by decision (2026-07-19). Numbered filenames make order structural: inserting a document between two others forces renames or, worse, discourages the insertion. Order is editorial, so it lives here and only here. A new document gets written under a plain name and slotted into this guide — nothing else moves.

## The recommended path

Read in this order if arriving fresh. Each entry: what it is, and when you'd return to it.

**1 · Orientation — why this exists and where it's going**

- [`../README.md`](../README.md) (repo root) — what OrionViva is, and the principles everything else reasons from.
- [`../ROADMAP.md`](../ROADMAP.md) — the product phases and what each one has to deliver.

**2 · The process spine — how we're deciding things**

- [discovery-plan.md](discovery-plan.md) — the discovery process and the open-questions register (the heartbeat).
- [discovery-map-and-reversibility.md](discovery-map-and-reversibility.md) — the master map: full discovery inventory, and the one-way/sticky/two-way door classification that governs when each decision gets made.

**3 · What we learned about the world — landscape research**

- [agent-and-model-landscape.md](agent-and-model-landscape.md) — frameworks, model capabilities, MCP, as of mid-2026.
- [competitive-landscape.md](competitive-landscape.md) — who's building near this (Era, OpenBudget, incumbents, the VC ecosystem) and what it means for positioning.

**4 · Design stances — how the core will work**

Read these together; they are one argument in four parts:

- [extraction-and-confidence.md](extraction-and-confidence.md) — the hard problem: confidence constructed by verification, not reported by models.
- [model-trust-policy.md](model-trust-policy.md) — the layer above: models are never believed; autonomy is earned statistically, guardrails bound the blast radius, feedback loops make it learnable.
- [domain-model-vs-orchestration.md](domain-model-vs-orchestration.md) — why checking stays out of model weights, and the specialization flywheel that turns verification into training data.
- [local-first-storage-and-crypto.md](local-first-storage-and-crypto.md) — where truth lives: encrypted storage, key custody, tamper-evidence.

**5 · Deliberately open**

- [form-factor-and-stack.md](form-factor-and-stack.md) — CLI vs local web vs desktop; Python vs TypeScript. Options framed, decision deliberately deferred to post-experiment architecture phase.

**6 · What's been decided**

- [decisions/](decisions/README.md) — the ADRs. Note: ADR numbers are serial IDs of decisions (in the order they were made), not a reading order; the index table there is the guide.

## Placement rules

New documents are slotted here at writing time, wherever they belong conceptually — that's the point of unnumbered names. Superseded documents stay in the folder, marked **Superseded** in their status line with a pointer forward, and move to a "Superseded" section here. If this guide and a doc's own cross-references ever disagree about structure, this guide wins.
