# Reading Guide — where every document sits

**State:** built
**Rules:** SPINE-5, SPINE-6

## Rules

### SPINE-5 — Document order lives here and nowhere else
**State:** unmet
**Code:** none found
**Test:** none

1. No filename carries an ordering number; order is editorial and lives only in this guide. (A decision's serial id in `decisions/`, and a closed phase's date in `archived/`, are identity rather than order.)
2. A new document is written under a plain name and slotted into this guide; nothing else moves.
3. Where this guide and a document's own cross-references disagree about structure, this guide wins.

### SPINE-6 — Superseded stays, historical is fenced, neither is deleted
**State:** unmet
**Code:** none found
**Test:** none

1. A document whose content was replaced stays in this folder, marked superseded, with a pointer forward.
2. A document that was true of a closed phase moves to [archived/](archived/README.md) under a historical-record banner and is recorded in section 6 below.
3. Nothing under `archived/` describes how OrionViva works today, and nothing in it is used for development.
4. Neither kind is ever deleted.

## The recommended path

Read in this order if arriving fresh. Each entry: what it is, and when you would return to it.

**1 · Orientation — why this exists and where it is going**

- [rules.md](rules.md) — **the index of what is true today.** Every rule this folder defines, in one table, with its state and the test that pins it, followed by every rule no test pins and every rule the code contradicts. It carries no argument and no date: the *why* for any rule is in the document named beside it, and history is in git and in the ADRs. Read it first if the question is what the product does; read the rest of this guide if the question is why.
- [architecture-overview.md](architecture-overview.md) — the map of the machine: the package trees, the layers of the desktop application, the trust boundaries, and where the open seams are. A map that points at the authorities rather than restating them — the page to open first when arriving at the code.
- [data-flow.md](data-flow.md) — the machine in motion: how a document becomes numbers, how an answer becomes a ruling, how a question becomes a cited answer, and what crosses the bridge. Reads beside the architecture overview.
- [implementation-roadmap.md](implementation-roadmap.md) — the checked record of what is built by capability, including quiet proof, bounded Activity correction, obligations and quiet findings, followed by the five remaining dependency-ordered cycle families from current-period control through explicitly confirmed action. Each future family still requires its own approved brief and crosses product, surface contract and installed interface as one vertical slice.
- [`../README.md`](../README.md) (repo root) — what OrionViva is, and the principles everything else reasons from.
- [`../ROADMAP.md`](../ROADMAP.md) — the product phases and what each one has to deliver.

**2 · The process spine — how things are decided**

- [design-invariants.md](design-invariants.md) — the standing checklist (trust, internationalization, accounting model, experience) every design doc and ADR answers to.
- [`../WORKFLOW.md`](../WORKFLOW.md) (repo root) — the lanes a change travels down, the roles that carry it, the checkpoints that are the product owner's, and the warrant under which a stand-in may hold them in a delegated run.
- [`../STYLE-COMMENT-PASS.md`](../STYLE-COMMENT-PASS.md) (repo root) — what a comment may say: behaviour, never provenance, argument or incident. A rule that must not be undone is a named test, not a paragraph.
- [`../SECURITY.md`](../SECURITY.md) (repo root) — the private vulnerability-reporting route, supported-code policy, and the security boundaries a reporter must not overclaim.
- [`../RELEASING.md`](../RELEASING.md) (repo root) — the desktop tag, signing environment, draft-release checks, clean-target smoke pass, and manual rollback procedure.

**3 · Design stances — how the core works**

Read these together; they are one argument, running extraction → merchants → categories → the balance sheet → the voice.

- [extraction-and-confidence.md](extraction-and-confidence.md) — the hard problem: confidence constructed by verification, never reported by models.
- [model-trust-policy.md](model-trust-policy.md) — models are never believed; autonomy is earned statistically, guardrails bound the blast radius, feedback loops make it learnable.
- [benchmark-harness-design.md](benchmark-harness-design.md) — the trust policy's instrument: the permanent admission exam (corpus, answer key, proctor rules, grading rubric) every model must pass and keep passing.
- [benchmark-harness-architecture.md](benchmark-harness-architecture.md) — how the exam is built: the `viva-bench` utility in `bench/`, two-adapter model access, and the two product-embryo modules since extracted upward into `core/vivacore`.
- [document-preprocessing.md](document-preprocessing.md) — whether to parse PDFs before the model reads them: input modes as a benchmark dimension, why local OCR strengthens local-first, why verification catches preprocessing data loss.
- [eval-harness-design.md](eval-harness-design.md) — the continuous honesty test: how "never bluff a number" is measured on every change forever, seeded from frozen keys and user corrections, with the confidently-wrong rate as the alarm.
- [verification-findings-and-correction.md](verification-findings-and-correction.md) — what happens when verification fails: the cheap-first ladder (deterministic diagnosis → bounded re-read → human asked well), the universal finding contract, and correction-as-event as the spine under all human teaching.
- [account-identity-and-entity-resolution.md](account-identity-and-entity-resolution.md) — how one account is recognized across inconsistently-labelled statements: signals → graded match → ask only when ambiguous → learn the ruling. The learning block reused later for merchants, employers and counterparties.
- [doc-type-registry-and-format-profiles.md](doc-type-registry-and-format-profiles.md) — how a new statement type becomes data rather than code: classify → select profile → extract. The verification identity is universal code with a per-type formula as data; personal knowledge is the local moat, format knowledge is shareable.
- [transfer-links-and-cross-document-corroboration.md](transfer-links-and-cross-document-corroboration.md) — one movement, two witnesses: own-account transfers recognized and excluded from spending, and a transfer link doubling as a cross-document reconciliation witness. A graded, reversible overlay, never a re-posting. Read *The evidence a link stands on* before touching the matcher.
- [pay-stubs-and-income.md](pay-stubs-and-income.md) — the first divergent document, whose identity is `gross − deductions = net`. A pay stub decomposes a deposit, income is recognized once, and deductions sort into universal buckets.
- [merchantcore-package.md](merchantcore-package.md) — the merchant enrichment package, a peer to vivacore that the product consumes: normalize, MerchantRecord, Enricher, Catalog, commons. The product submits only impersonal hints, merchantcore makes its own batched model calls, and the product syncs results back as events.
- [the-conduit-and-the-counterparty.md](the-conduit-and-the-counterparty.md) — where the descriptor ends and the grammar begins. A rail is a conduit and the party at the other end is the counterparty, so what a normalizer may keep is decided structurally rather than by a word list. Read *What a slot name may be believed about* for the crossing gate and its limit.
- [merchant-catalog-and-commons.md](merchant-catalog-and-commons.md) — categorize the merchant, not the transaction: a normalized merchant → category catalog fed by a batched call over new merchants only, applied retrospectively. The raw descriptor stays encrypted; only a linted, impersonal commercial catalog is ever shared.
- [categories-and-tags.md](categories-and-tags.md) — one partitions, one overlays. A category is exactly one per movement so the parts sum to the whole; a tag is many, overlapping, and tag totals deliberately do not sum. MON-82–MON-84 hold the three classes of duplicate label and who may merge each.
- [categorization-and-spending.md](categorization-and-spending.md) — what makes "where did my money go?" answerable: the kind-aware counter-leg, category as a graded overlay via correction-as-event, a jurisdiction-neutral seed taxonomy, and a spending-by-category projection composing with transfer exclusion.
- [honest-aggregates-and-the-learning-loop.md](honest-aggregates-and-the-learning-loop.md) — spending means money that left your *life*, not money that left an account. Establishes the derived movement nature, names the four ask-and-learn loops as one primitive, and sets the standing rule: abstract the read side early, the write side late.
- [the-question-queue.md](the-question-queue.md) — the learning loop's front door: a read-side `Question` projection ranked by consequence, scoped to the most general unit that is still honest. Question text is a deterministic template, never a model call.
- [the-surface-cards.md](the-surface-cards.md) — the presentation semantics: one card per instrument kind, each carrying the figure, its as-of date and grade, and what it does not include. A liability speaks *owed*; an investment shows the statement's own cross-check.
- [the-presentation-layer.md](the-presentation-layer.md) — the page rebuilt around the question queue as its spine, with one-tap answers inline and a focused detail view. Records the four rulings, including categories staying implicit.
- [prompts-as-files.md](prompts-as-files.md) — why every prompt is a `.txt` file and none is a Python literal, where a version is declared, and why a manifest family need not be a prompt. Read it before adding a prompt, a pack or a registry file.
- [where-the-intelligence-goes.md](where-the-intelligence-goes.md) — read before the transaction-intelligence spec. The product forms the belief and the person confirms it: a merchant category implies structure, and that knowledge belongs in merchantcore at enrichment time where it is impersonal, batched and shareable. Sorts every movement into three tiers.
- [from-your-words-to-the-ledger.md](from-your-words-to-the-ledger.md) — how a sentence becomes double-entry. Settles the ontology — four majors, equity deliberately absent — with a fixed top and a free hierarchy below, and exactly one model call in the six-step toolset.
- [viva-listens-and-speaks.md](viva-listens-and-speaks.md) — one engine, two directions: saying what something is (write) versus asking what is true (read). Listening comes first. Centrepiece is **Proposal**, the write-side twin of Finding, which makes X3 a property of the type rather than a rule to remember. Do not adopt a memory framework.
- [viva-persona.md](viva-persona.md) — who Viva is: identity, traits, guiding principles, the conversational arc, the question library, the "I don't know" handling, and the first-session script.
- [viva-persona-and-interview.md](viva-persona-and-interview.md) — Viva decides *how* to ask, never *what*: the persona as a rendering-and-interviewing layer over the queue, with voice phrasings, attribute schemas and expectation entries all as data packs.
- [the-interview-and-the-schema-pack.md](the-interview-and-the-schema-pack.md) — the schema owns what may be asked, the model owns what to ask next, the person owns whether anything is created. The schema pack is shape as data, jurisdiction-tagged from the first entry. Governed by [ADR-012](decisions/ADR-012-the-interview-model-boundary.md).
- [document-coverage.md](document-coverage.md) — every instrument a financial life produces, and which ones the product has eaten. Doubles as the corpus plan and the profile backlog, ordered by what each gap blocks, with the India column included by design.
- [learning-mode.md](learning-mode.md) — superseded by [from-your-words-to-the-ledger.md](from-your-words-to-the-ledger.md); read it for the diagnosis. A mortgage payment is three things at once, so the honest move is to ask for the document that states the split rather than make the person guess.
- [local-categorization-and-custom-categories.md](local-categorization-and-custom-categories.md) — the categorization thread's private half: peer descriptors have no stable merchant category, so they need a per-transaction, local path the commons cannot touch. Custom categories are first-class and strictly local.
- [net-worth.md](net-worth.md) — net worth is a curve, not a number with a date attached. `net_worth(D)` is defined at every date between the earliest and latest document, each point built from every account's last-known measurement at or before D. Per-currency subtotals, never conversion.
- [positions-and-investments.md](positions-and-investments.md) — the first asset that is not cash. A holding is a dated measurement, not a posting, so the money ledger stays pure cash flow and unrealized gain is the difference between measurements. Introduces the snapshot reconciliation identity and the valuation-class invariant.
- [local-first-storage-and-crypto.md](local-first-storage-and-crypto.md) — where truth lives: encrypted storage, key custody, tamper-evidence.
- [threat-model-and-ingestion-security.md](threat-model-and-ingestion-security.md) — adversaries by ruin-versus-bad-day; document prompt injection and why the extraction model is powerless by design. Also the supply-chain argument for hand-written HTTP model adapters.
- [own-chain-vs-borrowed-trust.md](own-chain-vs-borrowed-trust.md) — why the project anchors to existing fortresses instead of building a chain: the ION and Sovrin precedents, the node-churn physics, and where "every app is a node" honestly fits.

**3b · The experience — what all the machinery is for**

- [experience-vision.md](experience-vision.md) — a day with Viva: dashboard-first, speak-only-when-spoken-to, four capture surfaces, text and voice.
- [user-interface-architecture-and-delivery.md](user-interface-architecture-and-delivery.md) — the durable starting point for the real presentation layer: an installed desktop app over a packaged Python sidecar, a transport-independent `viva.surface` module, and a sliced path beginning with contracts rather than chrome. Its second half is the anti-staleness design.
- [user-interface-implementation-status.md](user-interface-implementation-status.md) — the architecture document's status counterpart: what is actually true of the interface on this branch, written so it fails rather than rots. Every gap opens with a direction and an address at which the measurement can be re-taken; a gap no machine here can hold says so and is counted on the document's face.
- [the-words-the-interface-uses.md](the-words-the-interface-uses.md) — the language authority beside the architecture one: which word names which layer — the desktop application, the shell, the interface, the surface, the bridge — and why a person is shown a *receipt* while the contract keeps `Citation`. Read it before naming a component or writing screen copy.
- [surface-charter.md](surface-charter.md) — the interface rules and decisions taken from an
  outside review of this product's surface, written down because that review is not
  tracked here and nothing in the build could check a claim made from it. Six rules with
  their arguments beneath them, the deferrals and what would bring each back, the
  sequencing it declines to ratify, and a register of what the review got wrong. Read it
  before proposing an interface rule: it is also the ceiling of what a stand-in may decide.
- [backend-capability-gaps.md](backend-capability-gaps.md) — the current complement to the live status record: capabilities still absent or intentionally incomplete, with executable registries left as the source of truth for what exists.
- [the-work-order.md](the-work-order.md) — a superseded pointer: the desktop run is complete, its numbered plan is archived, and current work starts from the status and gap records rather than extending the old sequence.
- [the-maintenance-agent.md](the-maintenance-agent.md) — what Viva does when nobody asked: the observe → plan → perform → record loop, the `AgentActed` event, the stake that keeps a refusal quiet until evidence or machinery moves, and a budget denominated in calls.
- [agent-toolset.md](agent-toolset.md) — the verbs Viva may ever use, the forbidden list that makes her safe, and the scaling law: tools grow with verbs, never with accounts.
- [projection-decomposition-and-the-tool-registry.md](projection-decomposition-and-the-tool-registry.md) — the projection split into a core fold plus per-family view modules behind an unchanged facade, and the registry on top: honest tools, the `ToolResult` envelope with refusal first-class, vault-validated filters, evidence-bounded period reads, and the modality-neutral runner. Also the record of how a sentence is composed from shapes with typed holes.
- [data-model-considerations.md](data-model-considerations.md) — three layers (claims, facts, projections), the ten universal primitives, the trust spine, and what a spike must stress.
- [data-model-spike-findings.md](data-model-spike-findings.md) — the ontology tested against real documents. Double-entry adopted; transfer-linking splits into own-account netting plus Party attribution; classification-by-filename disproven.
- [individual-as-enterprise.md](individual-as-enterprise.md) — the individual as a company with zero-effort books; why the books are permanently incomplete and honest about it; how Opening Balance Equity plus reconciliation make any-order ingestion fall out for free.
- [knowledge-and-expectations.md](knowledge-and-expectations.md) — where domain rules live: mechanisms in code, a jurisdiction-tagged knowledge registry as data, model suggestions graded like claims.
- [format-commons.md](format-commons.md) — frontier models read a format once and distil its shape into a shareable profile; cheap models answer pointed questions thereafter. Self-healing, privacy-linted, contributed as PRs.

**4 · Deliberately open**

- [adoption-and-distribution.md](adoption-and-distribution.md) — local-first without the friction tax: the onboarding ladder, model access without API keys, and the verified-private-cloud pattern.
- [account-connection-research.md](account-connection-research.md) — the research record for aggregation as a future acquisition path alongside encrypted manual upload; it is not a current capability.
- [multi-device-and-remote-access.md](multi-device-and-remote-access.md) — the ledger follows you, documents stay put: blind-relay sync, browser access with a passkey, and the one hosted architecture never to build.
- [the-suggestions-channel.md](the-suggestions-channel.md) — what Viva offers when she cannot answer. The refusal stays clean and what is useful moves to a separate, labelled channel, because a chosen thing arriving in an answer's authority is the risk. The channel exists on both sides and the risks differ: while Viva speaks the risk is misreading, while she asks it is leading.
- [jobs-and-the-progress-channel.md](jobs-and-the-progress-channel.md) — the shape a long piece of work reports itself in, fixed before anything produces one. Five constraints bind whoever builds the first producer: who mints a job's identity, why an event goes to a subscriber rather than through a filter, when a state may join the vocabulary, that a fraction ships only from a producer that knows its denominator, and that nothing on this channel is ever appended to the event log.
- [orionviva-transaction-intelligence-spec.md](orionviva-transaction-intelligence-spec.md) — an approved direction, not current state. The K1/K2/K3 knowledge vocabulary and the behavioural-classification design that sits on top of the merchant layer.

**5b · What has been decided**

- [decisions/](decisions/README.md) — the ADRs. An ADR records the *reasoning* that settled a one-way door — context, alternatives, the ruling, and what would reverse it. It is deliberately not a report on current behaviour: a decision standing in an ADR is not a claim that the code has met it. For whether it has, read the state column in [rules.md](rules.md). ADR numbers are serial ids of decisions in the order they were made, never a reading order; the index table there is the guide.

**6 · Historical record — read for reasoning, never for what is true now**

Documents from a closed phase live in [archived/](archived/README.md), each carrying a banner saying so.

- [archived/discovery-plan.md](archived/discovery-plan.md) — the research phase's own plan and its open-questions register.
- [archived/discovery-map-and-reversibility.md](archived/discovery-map-and-reversibility.md) — the doors framework (one-way, sticky, two-way) and the decision inventory it sequenced. Its output is the first eleven ADRs.
- [archived/agent-and-model-landscape.md](archived/agent-and-model-landscape.md) — agent frameworks and model capabilities, expired by design. The conclusion that survived is *models are commodities, memory of the user is the moat*.
- [archived/competitive-landscape.md](archived/competitive-landscape.md) — competing and adjacent products from public material, never audited.
- [archived/form-factor-and-stack.md](archived/form-factor-and-stack.md) — CLI versus local web versus desktop, Python versus TypeScript, with the choice deferred. It is no longer deferred: see [the-presentation-layer.md](the-presentation-layer.md).
- [archived/domain-model-vs-orchestration.md](archived/domain-model-vs-orchestration.md) — should the checking live in model weights? Settled permanently by [ADR-010](decisions/ADR-010-verification-never-in-weights.md).
- [archived/v0-scope.md](archived/v0-scope.md) — the thinnest first slice: one statement, one verified balance, no model in the answer path.
- [archived/stocktake-2026-07.md](archived/stocktake-2026-07.md) — the holistic audit, and the honest record of six occasions when a measuring instrument reported something untrue. Its rules live on as standing practices: graceful degradation belongs in the product and never in the instrument that measures it; report the final state, never the sum of moments; never grade one axis against another.
- [archived/the-repair-list-2026-07.md](archived/the-repair-list-2026-07.md) — the decision list drafted from that audit and the first real-money run, ruled item by item.
- [archived/discovery-synthesis.md](archived/discovery-synthesis.md) — the discovery phase's closing map of the whole forest, written before anything was built. Read for the thesis, not for the state.
- [archived/cold-read-audit-2026-07.md](archived/cold-read-audit-2026-07.md) — the line-level correctness read of all four packages by a reader arriving with no priors.
- [archived/backend-capability-gaps-before-live-desktop.md](archived/backend-capability-gaps-before-live-desktop.md) — the backend handoff before the live bridge closed most of its exposure list.
- [archived/the-work-order-before-live-desktop.md](archived/the-work-order-before-live-desktop.md) — the completed numbered desktop build plan.
- [archived/user-interface-implementation-status-before-live-desktop.md](archived/user-interface-implementation-status-before-live-desktop.md) — the detailed pre-bridge gap measurement.
- [archived/todo-before-live-desktop.md](archived/todo-before-live-desktop.md) — the long working handoff with old branch, suite, and work-order state preserved as context.

## Why

Numbered filenames make order structural: inserting a document between two others forces renames or, worse, discourages the insertion. Order is editorial, so it lives in one place and only one place, and a new document costs a plain name plus a line here.

Superseded and historical are different facts and are fenced differently on purpose. *Superseded* means the project changed its mind; *historical* means this was true then. Neither is ever deleted — a project arguing that trust must be provable does not quietly erase its own reasoning; it fences it off where no reader can mistake it for the present.

This guide describes what each document *is* and when to return to it. It does not track what each document claims, because a summary of a claim is a second copy of that claim, and two copies drift. The document itself is the record, and [rules.md](rules.md) is the one derived index — it copies a rule's id, name, state and test, which are the four things a reader needs before they know which document to open, and no part of the argument.

## Open

- `README.md`, `TODO.md`, and `phases.md` are folder-level navigation and working
  registers rather than reading-path documents. Every other live top-level
  document must be slotted here, and every relative Markdown link must resolve;
  the documentation gate enforces both.
