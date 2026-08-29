# OrionViva — Implementation Roadmap

**State:** partial
**Rules:** PROG-1, PROG-2, PROG-3, PROG-4, SPINE-7, SPINE-8, SPINE-9

## Rules

### PROG-1 — What is built is described by capability, not by slice
**State:** untestable
**Code:** none found
**Test:** none

1. The built half of this document names capabilities, so reading it answers *what does this product do today* and nothing else.

### PROG-2 — Slice labels are frozen and never renumbered
**State:** untestable
**Code:** none found
**Test:** none

1. A slice number that has appeared in a commit message or the public build log refers to the historical planning sequence and is never reused or renumbered.
2. A slice number is a planning label, so it does not map onto the built half of this document.
3. Work committed under the label "Slice 9b" is the counterparty-implications work — the three tiers of settled, structural and unknown, described under *Asking, and being told* — not the "Viva speaks" slice.

### PROG-3 — Nothing is built ahead of its slice
**State:** untestable
**Code:** none found
**Test:** none

1. Each slice is designed in detail with the author before any code is written for it.
2. Every slice seeds a reusable block, and the trust signal — grade, provenance, bitemporality — rides all of them.

### PROG-4 — The surface gates run in CI
**State:** by-review
**Code:** .github/workflows/quality.yml:22-27, scripts/check_surface_contract.py, scripts/check_surface_impact.py
**Test:** product/tests/test_surface_contract.py, product/tests/test_surface_capability_coverage.py, product/tests/test_surface_gate_scripts.py, product/tests/test_workflows_are_loadable.py

1. A deliberate contract drift fails the contract gate, and schema and fixture regeneration is deterministic.
2. Every user-facing and command capability has a surface destination or an explicit developer-only, internal or deferred disposition with a reason, and every command entry point is classified exactly once.
3. A backend change that touches the interface must declare its impact.
4. Every package suite — product, core, merchant and bench — runs in the build from the repository root, with no path narrowing, no selection filter and no tolerated failure. The frontend architecture boundary runs there too.
5. Every workflow file parses and declares jobs that run something. A build definition that cannot be parsed is rejected whole, so every gate named inside it stops running with no signal anywhere — the same failure as a gate that cannot report one, a level up.

The import boundaries between product, surface, bridge and desktop are
**VOICE-101** in
[user-interface-architecture-and-delivery.md](user-interface-architecture-and-delivery.md),
where the rule records which gate holds which half and what the Node checker
does not cover. This document's Slice 0 audit recorded those tests as present
*and verified* while two of the six were red, so that line of the audit was
wrong when it was written.

### SPINE-7 — The eval harness ships before the first user who is not the author
**State:** enforced-with-exception
**Code:** product/viva/honesty.py:1 (vault-facing), product/viva/eval_listen.py:1 (one model call against a frozen key)
**Test:** product/tests/test_honesty_harness.py::test_the_refusal_rate_is_measured_over_the_answers_a_person_got, ::test_the_confidently_wrong_rate_is_not_reported_over_a_vault, product/tests/test_eval_listen.py::test_an_unreadable_confidence_or_direction_degrades_to_the_cautious_value

1. No stranger tests the product until a continuous honesty harness exists, with the confidently-wrong rate as its headline.
2. The eval corpus accumulates at zero marginal cost as a by-product of the build, from frozen answer keys and from the corrections a person gives.

**Exception:** the confidently-wrong rate is still measured over one model call against a frozen key and nowhere else. The vault-facing half measures what a vault can answer without a key — the refusal rate, and how often a figure was stated with nothing on record behind it — and reports the confidently-wrong rate as not measured rather than as zero, because a key is what says an answer was wrong and a vault has none. Shapes authored, holes unfilled and clauses dropped are still counted by a debug reader (product/viva/debug/) rather than by the harness.

### SPINE-8 — The trust trial runs alongside breadth, never in front of it
**State:** untestable
**Code:** none found
**Test:** none

1. Daily use with real finances runs concurrently with the breadth work, because breadth is what the trial keeps finding faults in.
2. The trial closes on an event and not on a date: the author believes an answer without re-checking it.

### SPINE-9 — The phases past the product are gated on earned trust, not on a calendar
**State:** untestable
**Code:** none found
**Test:** none

1. The first non-author user waits on the trust trial having closed, per the project's anti-goals.
2. The trust-agent arc waits on the single-user agent having earned trust; a promise made before that is an aspirational promise and ADR-008 forbids one.

## Why

This document has two halves, and the split is the point. Once work exists, the
code and its design document are the record, and a historical slice label only
tells a reader where in a queue it once sat — so the built half is organised by
capability, and reading it answers what the product does today. The remaining
unbuilt half is organised by dependency-ordered cycle family. Each family
receives its own approved brief and may produce one or more vertical slices
without reusing or renumbering the frozen historical labels; for planned work,
the order and dependency path are the content.

The approach remains data-first: each future capability seeds or composes a
reusable block rather than a standalone feature, and the trust signal rides the
whole vertical slice from product through surface contract to interface. This is
the ordered path by which the approved direction can be built.

**What is built, by capability.**

*The ledger and the log.* An encrypted, append-only, hash-chained event log: every fact is an event with a value time and an ingest time, sealed and chained by record hash, so state is always a projection and history is never rewritten. A corrupt ledger refuses to read rather than guessing, and chain verification needs no key. A movement's postings sum to exactly zero, deterministically checked; an amount is the signed change to the named account; account roots are fixed in code and everything below them is data. A movement's counter-leg goes to an uncategorized bucket graded unverified — the amount is attested, the classification is not — and every later categorization is a read-side overlay, so the posted leg is never rewritten. Raw capture precedes judgment: the original bytes are sealed and stored before anything parses them, and every model reply is recorded with its model id and prompt version. Ingestion is any-order with bidirectional heal — a statement older than the one that seeded an account prepends and re-seats the opening balance, a statement dropped into a gap heals both sides and cascades, every ordering of the same documents yields an identical chain, and Opening Balance Equity reflects only genuinely unexplained history. One cached incremental projection is folded forward on each append, so ordinary reads never re-decrypt the log.

*Reading documents.* A document type is a data row naming its account kind, its identity check and the prompt fragments it owns; adding a balance-family type needs no code, and there are no per-institution parsers anywhere in the tree. Reading is two-phase: a cheap classify pass on the first page decides the type, and a type whose profile has no extraction prompt parks before an expensive call is paid for. Every model-facing string lives in a versioned file loaded by id, a released version is never edited, and a build-failing test keeps prompt text out of code. Verification is deterministic: exact-tolerance decimal arithmetic that refuses floats outright, one identity per document family, and a model never certifies a figure. Normalization is locale-aware and versioned, and where a shape is genuinely ambiguous and no locale decides it, the figure is refused rather than guessed. When a document does not reconcile, the gap is diagnosed cheapest-first, and only a forced finding is applied and re-checked — anything else holds the statement for review rather than posting a guess. Divergent profiles — a pay stub, a brokerage statement — each carry their own facts shape, identity and projector, proving that a new document shape is data plus a projector rather than new plumbing.

*Knowing what is the same thing.* The same primitive appears five times: gather signals, grade the match, ask only when genuinely ambiguous, record the ruling, apply it on the read side. Accounts anchor on the number, not on the holder's name. Two movements that are one internal transfer are linked as a graded overlay and excluded from spending, so money never appears to leave twice — and the same mechanism doubles as a reconciliation witness where a counterparty statement's movements uniquely account for another statement's gap, with uniqueness as the gate. A merchant is known by its brand, resolved for a whole vault at once because the boundary between a sender name and the noise around it is a property of the corpus rather than of any line, enriched in one batched call in a package that holds only impersonal knowledge. A category is a resolved identity rather than a bare string, because two spellings of one label silently halve every total that touches either. A category partitions and a tag overlays, and tag reports return the untagged and total figures beside the per-tag ones so a reader can see they do not add up.

*Making the numbers honest.* Asset and liability signs are opposite, and the counter-leg is kind-aware. Spending means money that left your *life*, not money that left an account, derived on the read side by a ladder of evidence, strongest first — and anything the ladder cannot settle is counted but reported provisional rather than silently resolved. A holding is measured at the statement date and never posted; unrealized change is the difference between two measurements rather than a fabricated transaction. Net worth is a curve defined at every date, where an earlier point never moves when a later document lands, an account with no measurement contributes nothing rather than zero and appears in a skipped list, and an asserted-but-unpriced asset is a disclosed gap reported with the question that closes it. Subtotals are per currency with no converted grand total, and every point names its stalest input. The answering path has no model in it: a question is a fixed function over the projection, and the layer's job is the honesty envelope.

*Asking, and being told.* One ranked queue is the front door for everything Viva needs to know, ranked by consequence, scoped to the most general unit that is still honest, with the tail summarized rather than hidden. Question text is a deterministic template, because a model that phrased a question could smuggle a claim into it. Every movement sorts into three tiers — settled, asked nothing; structural, given an informed proposal; unknown, given a real question — so the product forms the belief and the person confirms it. A sentence becomes double-entry through six steps with exactly one model call, and that call parses *intent* only: a ruling's legs structurally cannot carry a figure, and no account comes into being without an explicit yes, whatever the path. The interview is a projection over the answers an account already carries rather than an object, so it is retroactive, correctable and free. What may be asked about a kind of asset is data in a reviewable pack, and which schema an account gets is decided by evidence, strongest first, and only when exactly one kind claims it. An account records its jurisdiction and defaults to *nobody has said* rather than to a country. Every sentence Viva can say lives in a versioned phrasing pack keyed by intent; rendering is strict, and a phrasing may not introduce a fact the intent did not supply. Declines snapshot the stake, so a declined question stays quiet until the stake changes — no timers.

*Being asked, and answering.* A registry of read tools sits on the projection, each returning a graded, cited envelope rather than a bare number, with a planner in front of them that chooses the calls and writes the sentence but never computes a figure. A session carries prior turns as context and re-fetches every figure per turn, so an answer is never composed from what an earlier answer said. Coverage is not the stretch of time a read happened to see movements in — it is the period a reconciled statement declared, recovered from what each document said about itself, joined only where balances continue *and* dates meet, and reported one entry per account. The citation gate is code rather than instruction: a figure with no record id behind it is refused, and the ways a number could ground itself falsely have been closed one at a time. That gate was rebuilt rather than lengthened: a whitelist over prose a model had already written could never be finished, because the set of numeric tokens in a sentence about money that are *not* claims about money is open-ended. What replaced it inverts the order — a model commits a *shape* of literal words with typed holes before any tool is on the table, code binds the holes to references into the run's own ledger, and one renderer writes them. Nothing inspects the finished sentence, because a model writes no digits into one ([projection-decomposition-and-the-tool-registry.md](projection-decomposition-and-the-tool-registry.md)). Every exchange is kept verbatim with the prompt version and model that produced it, which is what makes a later eval possible at all.

*The installed presentation layer.* A React and TypeScript interface runs inside
a Tauri shell over the packaged Python sidecar. Versioned capabilities and
reviewed read models cross one allowlisted JSON-lines boundary; the desktop
renders figures, grades, dates, coverage, caveats and citations without doing
financial arithmetic. Private and persistent sample vaults use the live bridge,
while fixtures cover deterministic presentation states. Canonical Overview
figures declare compact proof `routine` or `required` from structured backend
evidence. A durable device-local preference defaults off and removes only
routine compact assurance; required reviewed qualifications remain visible and
the complete Evidence drawer remains preference-independent. Activity exposes
current category, the complete effective tag set and backend-qualified transfer
state, then offers only the explicit row actions the backend advertises: assign
an existing category, replace the complete movement tag set, confirm or reject
a suggested transfer, or unlink a live one. Each action returns a typed outcome
and the desktop completes a full fresh surface read before replacing its
financial picture; it does not infer transfer candidates or patch a row
optimistically.

*Obligations and quiet findings.* The projection reuses settled stream and
rhythm evidence rather than inventing a second recurrence engine. Three or more
steady observations can support a measured monthly or annual expectation;
calendar advancement preserves the day where possible, exact amounts remain
exact and varying amounts remain ranges, and an expectation is called due only
while evidence coverage is adequate. Stale outgoing and incoming rhythms,
amount changes, exact duplicate candidates, resolved fees and newly grounded
recurrence become typed, backend-ranked findings. Set-aside records the whole
current stake as an append-only event, so the finding stays quiet at that stake
and returns when evidence or the machinery version changes. Overview renders
*Coming up*, at most three findings and relevant account context; all copy,
ordering, visibility and available actions cross the reviewed surface contract,
and no notification or Viva-initiation path exists.

*Current-period control.* One deterministic, per-currency projection starts
from issuer-backed depository balances and applies only confirmed or strongly
measured recurring income and obligations over the next thirty days. Expected
income contributes nothing to the lower bound until it arrives; varying
obligations widen the range, missed income is not rolled forward, and unlike
currencies are never combined. The whole answer carries its horizon, weakest
grade, evidence dates, accounts, records, assumptions, exclusions, missing
inputs and backend-authored balance series and tooltips. Because planned
spending and goal contributions do not exist yet, the product calls the result
*known remainder*, never spend permission or runway. Overview renders the
ready, limited or refused result without arithmetic, and older, undated or
conflicted balances weaken visibly without an invented expiry rule.
Current reachability and remaining gaps live in
[user-interface-implementation-status.md](user-interface-implementation-status.md).

*Instruments and tooling.* Rebuild replays stored claims through today's parsers into a new vault, free and with no model calls, testing the parsers against yesterday's replies. Reingest re-reads the stored originals through today's prompts at real cost and reports regressions. Reset rebuilds the log with categorization dropped and a person's own rulings preserved. An interpretation eval scores sentence-reading against a frozen synthetic key with the confidently-wrong rate as the headline and a hard disqualification on any fabricated split or amount, and a run that could not reach the model is never scored. A model admission exam grades candidates on a frozen corpus across input modes and publishes no composite leaderboard.

**What remains planned, and why in this order.**

These are cycle families, not historical slices, and none receives an old slice
label. Cycle families 1–4 are delivered and are described by capability in the
built half above; the remaining numbers are not renumbered. Families 5–7 are planned
direction rather than built behaviour. Each still needs its own approved brief,
and each capability travels as one vertical slice: product projection or event,
reviewed `viva.surface` contract, capability and operation disposition,
fixtures, installed-interface consumer and tests. A new shell is not a
substitute for any missing layer.

### Cycle family 4 — durable conversation and correction

**State: delivered.**

**Product capability.** Durable turns, typed outcomes and correction proposals
are ledger events and projections. Each turn re-fetches current financial
evidence; earlier conversation can supply context but cannot become evidence.
Question answers and bounded corrections are explicit conversation verbs, and
proposal confirmation re-checks the deterministic question stake before any
write. A moved stake settles as stale.

**Surface contract.** Conversation history, cited replies, proposed corrections
and completed, refused, waiting, stale and set-aside outcomes carry typed
shapes. Text and later voice consume one answer shape.

**Interface consumer.** The desktop renders the durable history and cited
outcomes, shows a proposed correction before confirmation, and never turns a
normal refusal, wait or stale result into an invented error.

**Dependency.** It follows the first picture-side utilities so conversation can
explain the same backend meanings rather than create a parallel product. It
also depends on the built Activity correction reachability, typed outcomes and
refreshed reads.

**Acceptance condition.** An earlier answer may supply context but never
evidence for a later figure; a correction survives a new session and changes
every affected projection; and later voice mirrors the same cited text rather
than creating a second answer path.

No migration or backfill path is included. The product has not been publicly
released, so the durable contract begins with new conversation events and does
not reinterpret older technical read records or support prior vault shapes.

### Cycle family 5 — goals and plans

**Product capability.** A later brief must design explicit goal events and
projections, distinguish a desired target from funds actually reserved for it,
and compute contribution, target-date, progress and deviation deterministically.
A natural-language request may become a typed draft and then a proposal, but it
does not become a write without confirmation. Composing existing financial
reads does not remove this backend work.

**Surface contract.** Goal drafts, proposals, assumptions, alternatives,
progress and modify, confirm, pause and set-aside outcomes must cross as reviewed
types with their evidence and state.

**Interface consumer.** A person may state a goal conversationally or through a
minimal form. A Plans destination is earned only after the registry serves it
and the vault holds a plan or the person has asked to make one.

**Dependency.** Plans depend on family 3's bounded current-period projection and
family 4's durable proposal and correction path. Goal events and projections
must exist before a destination claims to present them.

**Acceptance condition.** An unreserved goal is never rendered as funded; a
draft leaves the ledger unchanged; and confirmation records exactly the
proposal the person saw or refuses it as stale.

### Cycle family 6 — scenarios

**Product capability.** A later brief must implement pure deterministic
amortisation, compounding, payoff, runway and affordability scenarios. Every
assumption is enumerated, the result inherits the weakest evidentiary basis of
its recorded inputs, hypothetical premises stay hypothetical, and no model does
the arithmetic.

**Surface contract.** Scenario requests, comparable results, assumptions,
boundaries and changed premises must cross as typed data. Turning a scenario
into a plan is a separate proposal operation.

**Interface consumer.** The desktop collects premises, renders backend-supplied
comparisons and changed assumptions, and may request that a chosen scenario be
drafted as a plan. It computes none of the comparison.

**Dependency.** Scenarios depend on family 3's bounded financial inputs and
family 5's explicit distinction among hypothetical result, draft and recorded
plan.

**Acceptance condition.** Equal inputs produce equal outputs independently of
model or interface; a hypothetical result never acquires a verification grade
by composition; and no scenario silently becomes a plan or action.

### Cycle family 7 — drafted, explicitly confirmed action

**Product capability.** A later brief must define separately gated action
capabilities outside the read-tool set, produce complete drafts, re-check state
immediately before applying, and record proposal, consent and outcome
separately. A networked or irreversible mechanism must be structurally
unreachable without confirmation.

**Surface contract.** An action contract must carry the exact destination,
consequence, timing, reversibility, basis and typed outcome the person is being
asked to confirm. The operation table remains the readable inventory of every
capability that can touch a vault.

**Interface consumer.** The desktop shows the complete proposed action, requires
an explicit confirmation, treats refusal and staleness as normal outcomes, and
never displays success before the backend reports completion.

**Dependency.** This comes last because it composes the durable confirmation
path from family 4, explicit plans from family 5 and deterministic comparisons
from family 6. No interface gesture may bridge a missing backend policy or
operation.

**Acceptance condition.** An unconfirmed proposal changes nothing; a proposal
whose basis changed cannot be applied unseen; and no executable path exists
outside the declared, gated operation inventory.

**Decision recorded: no agent-memory framework.** Rulings are institutional knowledge, not preferences, and the append-only, graded, deterministically-applied event log already avoids the staleness and trustworthy-retrieval problems those frameworks are benchmarking.

**The stack, end to end.** The first version gave one honest answer, and the
built half consolidates a financial picture on a small set of re-composed
blocks, makes routine proof quieter without weakening required qualification,
adds grounded obligations with quiet findings, and projects a bounded
current-period remainder, and carries durable conversation and correction. The
remaining planned order adds goals and plans, deterministic scenarios, and
finally drafted action behind explicit confirmation. Each remaining feature is the
same vertical path through product, surface and interface, not a new shell.

## Open

- What the interface currently does render is tracked in [user-interface-implementation-status.md](user-interface-implementation-status.md).
- The packages require Python 3.11 or newer while the local default interpreter is older, so integration checks must run under the declared supported runtime or they prove nothing.
- Desktop fixtures remain synthetic interface data and prove rendering, while
  live private/sample-vault tests prove bridge behavior; neither proves signed
  installer behavior on a clean target.
- Recommended integration checks, standing: run the surface contract, capability coverage, import boundary and impact checks under the supported runtime; regenerate schema and fixtures twice and compare byte-for-byte; mutate a field, a closed-vocabulary value, a protocol version and a capability disposition in temporary copies and confirm each fails for the intended reason; inventory every command entry point and assert each is classified exactly once; verify dependency direction in both languages; then run the full product suite and confirm the branch carries no generated frontend output changes.
- The conversation has met the author's real vault, and what the runs found is not settled. A wrong number reached a person, carrying its grade and its citation correctly, from four compounding faults of which none was in the shape mechanism. And *swapping the model changes phrasing rather than answers* is false as written: one local model emitted no tool call in twenty replies and so answered nothing at all, which makes the property per-model rather than a property of the design, with the shipped default on the wrong side of it.
- Two done criteria for the speaking slice still have no test: that a document's own text cannot make Viva act, and that swapping the model changes phrasing rather than answers.
- The wiring between the model and the citation gate is unpinned: the gate is tested hard and its supply line is not.
- The speaking path has no quiet-finding tool to call. Quiet findings are built
  picture state, but do not authorise Viva to initiate or notify.
- Where this sits against the product phases: `ROADMAP.md`'s foundations phase is complete, and the organize-and-consolidate phase is in progress — transfer-linking and the evidence-bounded net-worth curve are built, account aggregation is not.
- Anchoring has never run and nothing schedules it; it is trust hardening's work.
