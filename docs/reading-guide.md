# Reading Guide — where every document sits

**Status:** Living — this is the only place document order exists · **Last updated:** 2026-07-19

## Why this doc

Filenames carry no numbers, by decision (2026-07-19). Numbered filenames make order structural: inserting a document between two others forces renames or, worse, discourages the insertion. Order is editorial, so it lives here and only here. A new document gets written under a plain name and slotted into this guide — nothing else moves.

## The recommended path

Read in this order if arriving fresh. Each entry: what it is, and when you'd return to it.

**1 · Orientation — why this exists and where it's going**

- [discovery-synthesis.md](discovery-synthesis.md) — **start here: the forest on one page.** The thesis, what we measured, what's locked, where every concern sits in the architecture, and the accepted risks. The bridge from discovery into Architecture.
- [v0-scope.md](v0-scope.md) — **the first thing we build**: "one honest answer" (your checking balance, verified, tap-to-source), trust-core-first with no LLM in the answer path. The minimal slice and its build sequence.
- [implementation-roadmap.md](implementation-roadmap.md) — **the whole path after v0**: 14 data-first slices, each seeding a reusable lego block, written as fact statements (open state → implementation → final state → done-tests → why). From consolidating a full financial life, to Viva's voice, to proving a claim to a counterparty (the endgame).
- [`../README.md`](../README.md) (repo root) — what OrionViva is, and the principles everything else reasons from.
- [`../ROADMAP.md`](../ROADMAP.md) — the product phases and what each one has to deliver.

**2 · The process spine — how we're deciding things**

- [discovery-plan.md](discovery-plan.md) — the discovery process and the open-questions register (the heartbeat).
- [discovery-map-and-reversibility.md](discovery-map-and-reversibility.md) — the master map: full discovery inventory, and the one-way/sticky/two-way door classification that governs when each decision gets made.
- [design-invariants.md](design-invariants.md) — the standing checklist (trust, internationalization, experience) every new design doc and ADR must answer to.

**3 · What we learned about the world — landscape research**

- [agent-and-model-landscape.md](agent-and-model-landscape.md) — frameworks, model capabilities, MCP, as of mid-2026.
- [competitive-landscape.md](competitive-landscape.md) — who's building near this (Era, OpenBudget, incumbents, the VC ecosystem) and what it means for positioning.

**4 · Design stances — how the core will work**

Read these together; they are one argument in four parts:

- [extraction-and-confidence.md](extraction-and-confidence.md) — the hard problem: confidence constructed by verification, not reported by models.
- [model-trust-policy.md](model-trust-policy.md) — the layer above: models are never believed; autonomy is earned statistically, guardrails bound the blast radius, feedback loops make it learnable.
- [benchmark-harness-design.md](benchmark-harness-design.md) — the trust policy's instrument: the permanent admission exam (corpus, answer key, proctor rules, grading rubric) every model must pass and keep passing.
- [benchmark-harness-architecture.md](benchmark-harness-architecture.md) — how the exam is built: the `viva-bench` utility in `bench/`, two-adapter model access (OpenAI-compatible + Anthropic), and the two product-embryo modules (verify/, models/).
- [document-preprocessing.md](document-preprocessing.md) — should we parse PDFs before the model reads them? Input modes (image / text / text+image / tool-parsed) as a benchmark dimension; why local OCR strengthens local-first; why verification catches preprocessing data loss.
- [eval-harness-design.md](eval-harness-design.md) — the continuous honesty test: how "never bluff a number" is measured on every change forever; seeded free from frozen keys + user corrections; the confidently-wrong rate as the alarm.
- [verification-findings-and-correction.md](verification-findings-and-correction.md) — what happens when verification *fails*: the cheap-first ladder (deterministic diagnosis → bounded re-read → human asked well), the universal finding contract (forced vs suggested vs unlocalized), correction-as-event as the single spine under all future human teaching, and why the hard cases build the moat.
- [account-identity-and-entity-resolution.md](account-identity-and-entity-resolution.md) — how the same account is recognized across inconsistently-labelled statements: a *learning* building block (signals → graded match → ask only when ambiguous → learn the ruling), reused later for merchants/employers/counterparties. Slice 1.5; seeds the Account/Party primitives.
- [doc-type-registry-and-format-profiles.md](doc-type-registry-and-format-profiles.md) — how a new statement type becomes *data, not code*: classify → select profile → extract; we own the schema, the model perceives; the verification identity is universal code with a per-type formula as data (A1 sign reframe to effect-on-balance); personal knowledge (local moat) vs format knowledge (shareable); versioned profiles + surgical re-reads. Slice 2; seeds the format-profile registry the divergent types (brokerage, tax, insurance) and the [format-commons](format-commons.md) extend.
- [domain-model-vs-orchestration.md](domain-model-vs-orchestration.md) — why checking stays out of model weights, and the specialization flywheel that turns verification into training data.
- [local-first-storage-and-crypto.md](local-first-storage-and-crypto.md) — where truth lives: encrypted storage, key custody, tamper-evidence.
- [threat-model-and-ingestion-security.md](threat-model-and-ingestion-security.md) — adversaries by ruin-vs-bad-day; document prompt injection and why the extraction model is powerless by design (the CaMeL pattern, arrived at independently).
- [own-chain-vs-borrowed-trust.md](own-chain-vs-borrowed-trust.md) — why we anchor to existing fortresses instead of building a chain: the ION and Sovrin precedents, the node-churn physics, and where "every app is a node" honestly fits (verification, not storage).

**4b · The experience — what all the machinery is for**

- [experience-vision.md](experience-vision.md) — a day with Viva: dashboard-first, speak-only-when-spoken-to, four capture surfaces, text + voice; the parts inventory that becomes the v0 component list.
- [agent-toolset.md](agent-toolset.md) — the twelve verbs Viva may ever use, the forbidden list that makes her safe, and the scaling law: tools grow with verbs, never with accounts.
- [data-model-considerations.md](data-model-considerations.md) — three layers (claims/facts/projections), the ten universal primitives, the trust spine (observations, corrections, transfer links, completeness, bitemporality), and what the spike must stress.
- [data-model-spike-findings.md](data-model-spike-findings.md) — experiment 2: the ontology tested against real documents. Double-entry (postings) adopted; transfer-linking splits into own-account netting + Party attribution; tax docs become fact bundles; classification-by-filename disproven.
- [individual-as-enterprise.md](individual-as-enterprise.md) — the individual as a company with zero-effort books (a democratized personal CFO); why the books are permanently incomplete and honest about it; how Opening Balance Equity + reconciliation make any-order ingestion and lifelong onboarding fall out for free.
- [knowledge-and-expectations.md](knowledge-and-expectations.md) — where domain rules live: mechanisms in code, a jurisdiction-tagged knowledge registry as data, model suggestions graded like claims. Documents are evidence that other documents exist.
- [format-commons.md](format-commons.md) — frontier models read a format once, distill its shape into a shareable profile (knowledge, never documents); cheap models answer pointed questions thereafter. Self-healing, privacy-linted, contributed as PRs.

**5 · Deliberately open**

- [adoption-and-distribution.md](adoption-and-distribution.md) — local-first without the friction tax: the onboarding ladder, model access without API keys, and the verified-private-cloud pattern. Shapes the architecture phase.
- [multi-device-and-remote-access.md](multi-device-and-remote-access.md) — the ledger follows you, documents stay put: blind-relay sync, browser access with a passkey, and the one hosted architecture we never build.
- [form-factor-and-stack.md](form-factor-and-stack.md) — CLI vs local web vs desktop; Python vs TypeScript. Options framed, decision deliberately deferred to post-experiment architecture phase.

**6 · What's been decided**

- [decisions/](decisions/README.md) — the ADRs. Note: ADR numbers are serial IDs of decisions (in the order they were made), not a reading order; the index table there is the guide.

## Placement rules

New documents are slotted here at writing time, wherever they belong conceptually — that's the point of unnumbered names. Superseded documents stay in the folder, marked **Superseded** in their status line with a pointer forward, and move to a "Superseded" section here. If this guide and a doc's own cross-references ever disagree about structure, this guide wins.
