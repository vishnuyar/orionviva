# The Discovery Map & Decision Reversibility

**Status:** Draft (this is the master map — other docs are its details) · **Last updated:** 2026-07-19

## The framing: doors, not decisions

Not all decisions are equal, and treating them equally is itself a failure mode — either paralysis (treating every choice as fatal) or recklessness (treating every choice as revisable). Three classes:

**One-way doors.** Genuinely irreversible — not because code can't be rewritten, but because *time, data, or trust* can't be recovered. These must be decided now, before product code exists.

**Sticky doors.** Technically reversible but the cost compounds with every day of real data, real users, or public exposure. These deserve deliberate decisions with an explicit migration story, but not paralysis.

**Two-way doors.** Cheap to reverse. These should be decided *late* and *fast*, with the best information available — deciding them early is pure downside.

The deep principle underneath, and the answer to "how do we avoid irreversible mistakes": **irreversibility lives almost entirely in what you fail to capture and what you promise publicly — almost never in what you build.** Code is clay. But a statement ingested without its source region can never get one retroactively; a hash chain started in month six proves nothing about months one through five; a privacy promise broken once is broken forever. So the strategy is: hardwire the *invariants* (what must always be true), keep the *mechanisms* (how it's achieved) swappable, and over-capture raw truth because storage is cheap and the past is unrecoverable.

---

## The one-way doors — hardwire before the first line of product code

These are the decisions that cannot be reinstated later. Each is small to implement; all of them together are the project's real foundation.

**D1 · Raw capture doctrine.** Every original document is kept forever, encrypted, immutable. Every model interaction during extraction (full request/response, model version, source regions claimed) is kept. Rationale: this is the master key to reversibility everywhere else — with raw truth retained, *any* future pipeline, model, schema, or confidence system can re-derive everything. Without it, nothing can. Costs megabytes; buys the ability to change our minds about almost everything downstream.

**D2 · Append-only, hash-chained event log from commit one.** Every ingestion, extraction, verification result, correction, and answer is an event; nothing is ever destructively updated; the chain makes history tamper-evident. Tamper-evidence only proves history *from when it starts* — it cannot be backdated, which is precisely why it can't wait. This is also the substrate of the Phase 4 trust arc: an agent that will one day vouch for you needs a provable history of how it came to know what it knows. Current state is a *projection* of the log, and projections are rebuildable — this single pattern converts most sticky schema decisions into two-way doors.

**D3 · Encryption-at-rest from commit one, with a versioned crypto envelope.** Never a plaintext phase, even "temporarily during development" — the author's real statements are the test data from day one. Versioned envelope = crypto agility: algorithms can be upgraded by re-encryption, so the *format* stays reversible while the *posture* never lapses. Note the asymmetry: encryption choices are reversible while keys are held; a leak is not.

**D4 · Zero exfiltration by default.** Nothing leaves the machine except the user-initiated model calls under ADR-001, and the product can always show exactly what left, when, to whom. No telemetry, no crash reporting, no analytics by default, ever. One-way because the first silent byte that leaves breaks the promise permanently — and because "we added telemetry" is a door that swings one direction in users' minds.

**D5 · Stable identity scheme for records.** How a transaction, account, document, and figure get their permanent IDs (content-derived where possible), decided before real data accumulates. Sticky-verging-on-one-way: every provenance pointer, correction, and memory entry will reference these IDs forever; an identity migration after a year of data is where projects go to die.

**D6 · Public promise inventory.** Every public commitment — never bluff a number, data never leaves without consent, ad-free, open source — is a trust ratchet: it can be added to but never withdrawn. Maintain the inventory explicitly; adding to it is a deliberate act, not a marketing slip. The README and site already contain several; they should be enumerated and treated as constraints on all future decisions.

**D7 · Contribution policy before the first external PR.** DCO or CLA, decided now. License changes (even fixing the MIT/AGPL inconsistency currently on the site vs. repo — see below) require agreement of all copyright holders; the day the first outside contribution merges, that set stops being "just Vishnu." Cheap today, near-impossible later.

**D8 · Verification never moves into model weights.** Elevated to principle in the domain-model doc. Listed here because it's a one-way door in reverse: the day answers depend on unauditable internal model arithmetic, the provable-trust thesis is unfalsifiable and the product is ordinary.

**Found while mapping:** the site homepage footer said AGPL-3.0; the repo LICENSE and the project principles said MIT. Resolved: **MIT confirmed** (ADR-002). Site footers corrected across all pages (`orionviva-web` commit `079dd4c`); repo README's License section restored to MIT. No AGPL reference remains in either repo.

> **Update 2026-07-19:** All eight doors are now closed — see [decisions/](decisions/) ADR-002 through ADR-010. Decisions taken: DCO for contributions, hybrid record identity, day-one anchoring to both OpenTimestamps and RFC 3161, diagnostics by manual export only.

---

## Sticky doors — decide deliberately, with a named migration path

| Decision | Why it's sticky | Migration escape hatch |
|---|---|---|
| Unified data model semantics (what an account, transaction, holding, snapshot *is*) | Every feature builds on it; real data accumulates in it | D2: model is a projection of the event log — rebuildable, if the *events* captured enough truth (D1) |
| Confidence grade vocabulary (verified/corroborated/unverified/conflicted) | Users learn it; answers embed it; it becomes the product's dialect | Grades stored as re-derivable annotations, raw verification trail kept (D1) → can re-grade history |
| Memory architecture (how corrections/preferences/goals are stored) | The moat itself; entangles with everything | Memory entries as events in the log with provenance → re-projectable |
| Agent persona (Viva's voice, when she speaks, what she volunteers) | Public-facing identity; user habituation | Prompt/config layer, never scattered through code |
| Key custody & recovery UX | Users set up recovery once and forget; changing it requires re-enrollment | Versioned envelope (D3); design re-enrollment flow from the start |
| Aggregation stance (Q7) | Vendor integration + user expectation of live data | Aggregated data enters as *lower-trust-grade events* — same log, honest label, removable |
| Answer/citation UX (how provenance is shown) | Shapes what users trust; hard to walk back richness | UI layer only — data (D1/D2) supports any presentation |

## Two-way doors — decide late, decide fast

Language/stack and form factor (the form-factor doc — the experiments settle them); model provider and agent harness (abstraction layer is a hard requirement, so swappable by design); local vs cloud extraction default (ADR-001 is a trajectory, not a position); storage engine internals (SQLite/SQLCipher vs alternatives — behind the projection layer); MCP consumption and exposure; categorization taxonomy (annotations, revisable); UI framework; packaging; pricing mechanics. None of these deserve discovery *depth* now beyond what the research docs already hold. The discipline is refusing to decide them early.

---

## The full discovery map

Six domains. Status: ✅ doc exists · 🔶 partially covered · ⬜ not started. Ordering within domains ≈ dependency order.

### A · Data & intelligence (the core)

| # | Discovery item | Status | Feeds decisions |
|---|---|---|---|
| A1 | Unified data model deep-dive: account taxonomy across bank/card/brokerage/retirement/loan/property/insurance/tax; transactions vs positions vs snapshots; multi-currency; corrections-as-first-class | ⬜ (experiment 2 planned) | Sticky: data model; D5 |
| A2 | Extraction & calibrated confidence | ✅ the extraction doc | Sticky: grades; D8 |
| A3 | Ingestion pipeline: formats (PDF/image/CSV/email?), dedup on re-upload, multi-page/multi-account statements, quality floor for scans | ⬜ | D5, D1 details |
| A4 | Transfer linking & internal-flow detection (card payment ≠ spending) | ⬜ | Data model |
| A5 | Categorization & personal taxonomy: seed taxonomy vs learned-from-corrections | ⬜ | Memory architecture |
| A6 | Memory architecture: what Viva remembers (corrections, preferences, goals, context), with provenance; explicit-memory stance vs parametric (the domain-model doc) | 🔶 the domain-model doc | Sticky: memory |
| A7 | Query/answer architecture: NL → deterministic compute over verified data → answer with citations + inherited confidence; where the boundary sits | ⬜ | D8 |
| A8 | Evaluation harness: how honesty is *continuously measured* — regression suite of question/answer/provenance triples over known data; an untested trust property doesn't exist | ⬜ | All of A |
| A9 | Specialization flywheel mechanics (corpus format, when to tune) | ✅ the domain-model doc | D1 details |

### B · Security & trust engineering

| # | Discovery item | Status | Feeds decisions |
|---|---|---|---|
| B1 | Threat model: adversaries (device thief, malware, cloud model provider, subpoena, malicious document, user error), what each can/can't get; ruin-classification per Taleb constraint | ⬜ — should be next after experiments | D3, D4, key custody |
| B2 | **Prompt injection via documents**: a statement PDF containing adversarial instructions to the extracting model. Unique exposure: we ingest untrusted documents into a privileged agent *by design*. Newly identified; nobody in the landscape docs addresses it | ⬜ — high priority | Ingestion architecture; agent tool permissions |
| B3 | Key custody & recovery deep-dive (the storage doc sketch → full design) | 🔶 the storage doc | Sticky: custody UX |
| B4 | Tamper-evident log design: event schema, hash chain, optional public anchoring | 🔶 the storage doc | D2 details |
| B5 | Backup & multi-device: encrypted-blob sync patterns, conflict handling | 🔶 the storage doc (deferred) | Two-way if D1–D3 hold |
| B6 | Agent action sandboxing for Phase 3: capability model for "autonomous where safe" — what Viva can *ever* do without asking, enforced in code not prompt | ⬜ | Phase 3 gate |

### C · Product & experience

| # | Discovery item | Status | Feeds decisions |
|---|---|---|---|
| C1 | Uncertainty UX: how doubt *feels* in an answer — language, visual grammar, when Viva refuses. The load-bearing wall, experienced | ⬜ | Sticky: grades vocabulary |
| C2 | Provenance UX: click-through from figure to source region; what "proving what it stood on" looks like | ⬜ (experiment 3 tests plumbing) | Sticky: citation UX |
| C3 | Persona design: Viva's voice, discretion, when she volunteers vs stays quiet ("serve, don't overwhelm" operationalized) | ⬜ | Sticky: persona |
| C4 | Onboarding & progressive disclosure: the first session with one statement; UI revealing itself as data arrives | ⬜ | Form factor |
| C5 | Correction & feedback loops: how the user fixes Viva, and how fixes become memory (the moat's front door) | ⬜ | A5, A6 |
| C6 | Form factor | ✅ the form-factor doc | Two-way |

### D · Platform & architecture

| # | Discovery item | Status | Feeds decisions |
|---|---|---|---|
| D-1 | Agent harness & model abstraction layer | ✅ the agent-landscape doc | Two-way (by design) |
| D-2 | Stack selection | ✅ the form-factor doc | Two-way (post-experiments) |
| D-3 | Storage & crypto implementation | ✅ the storage doc | D3 details |
| D-4 | MCP surface: consuming (aggregators/institutions) and exposing (local server = the trust boundary where "your agent answers other agents" starts) | 🔶 the agent-landscape and competitive-landscape docs | Two-way, but *permissioning design* previews Phase 4 |
| D-5 | Packaging, updates, code signing (for eventual non-author users) | ⬜ (noted, deferred) | Two-way |

### E · Ecosystem & the longer arc

| # | Discovery item | Status | Feeds decisions |
|---|---|---|---|
| E1 | Competitive landscape | ✅ the competitive-landscape doc (quarterly refresh) | Positioning |
| E2 | Aggregation stance (Q7): documents-only vs aggregation-as-lower-trust-feed | 🔶 the competitive-landscape doc | Sticky |
| E3 | Verifiable credentials arc: track eIDAS rollout, reusable KYC, US mDL; what Phase 4 inherits for free from regulation | 🔶 the competitive-landscape doc | Timing only — build nothing yet |
| E4 | Regulatory & liability: where "explain & advise" crosses into regulated financial advice (jurisdiction-dependent); what disclaimers/design keep Viva honest *and* lawful; data protection posture | ⬜ — needed before any user who isn't the author | Phase 2 language design |
| E5 | Open-source community strategy: DCO/CLA (D7), security review process for contributions touching trust-critical code, threat of malicious PRs | ⬜ — D7 part is *now* | D7 |

### F · Sustainability

| # | Discovery item | Status | Feeds decisions |
|---|---|---|---|
| F1 | Business model: what is actually paid for when software is open and data is local (support? sync relay? managed model access? packaged convenience?) — "paid directly" needs a mechanism eventually | ⬜ (post-trust-earned) | Two-way |
| F2 | Build-in-public cadence: what gets logged, honesty standard for the build log (mistakes included), cadence | 🔶 (site exists) | D6 adjacent |

---

## Sequencing (what this map implies)

1. **Now:** close the one-way doors — D1–D8 written as short ADRs (mostly a day's work; they're stances, not systems). ~~Fix the license inconsistency.~~ Done — MIT everywhere.
2. **Next:** the three de-risking experiments (the discovery plan) — they feed A1, A2, C2, and the stack choice, and the experiment corpus doubles as the seed of the A8 evaluation harness.
3. **Then:** B1 threat model + B2 prompt-injection design — before the first end-to-end pipeline exists, because ingestion architecture must be born suspicious of its inputs.
4. **Then:** architecture phase — sticky doors decided with experiment evidence (data model, grades, memory), two-way doors decided cheaply (stack, form factor).
5. **Ongoing:** E1/E3 refresh triggers; the open-questions register in the discovery plan remains the heartbeat.

The map is large; the path through it is narrow. Almost everything waits on the same three experiments — which is the signature of a well-ordered project rather than an overwhelming one.
