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

This document has two halves, and the split is the point. A slice is a unit of *planning*. Once the work exists, the code and its design document are the record, and a label only tells a reader where in a queue it once sat — so the built half is organised by capability, and reading it answers what the product does today. Only the unbuilt half is organised by slice, in the fact-statement form the plan has used throughout, because for unbuilt work the order *is* the content.

The approach is data-first: every slice seeds a reusable block rather than a feature, and the trust signal rides all of them from the first version to the endgame. This is the ordered path by which the whole invariant set gets built.

**What is built, by capability.**

*The ledger and the log.* An encrypted, append-only, hash-chained event log: every fact is an event with a value time and an ingest time, sealed and chained by record hash, so state is always a projection and history is never rewritten. A corrupt ledger refuses to read rather than guessing, and chain verification needs no key. A movement's postings sum to exactly zero, deterministically checked; an amount is the signed change to the named account; account roots are fixed in code and everything below them is data. A movement's counter-leg goes to an uncategorized bucket graded unverified — the amount is attested, the classification is not — and every later categorization is a read-side overlay, so the posted leg is never rewritten. Raw capture precedes judgment: the original bytes are sealed and stored before anything parses them, and every model reply is recorded with its model id and prompt version. Ingestion is any-order with bidirectional heal — a statement older than the one that seeded an account prepends and re-seats the opening balance, a statement dropped into a gap heals both sides and cascades, every ordering of the same documents yields an identical chain, and Opening Balance Equity reflects only genuinely unexplained history. One cached incremental projection is folded forward on each append, so ordinary reads never re-decrypt the log.

*Reading documents.* A document type is a data row naming its account kind, its identity check and the prompt fragments it owns; adding a balance-family type needs no code, and there are no per-institution parsers anywhere in the tree. Reading is two-phase: a cheap classify pass on the first page decides the type, and a type whose profile has no extraction prompt parks before an expensive call is paid for. Every model-facing string lives in a versioned file loaded by id, a released version is never edited, and a build-failing test keeps prompt text out of code. Verification is deterministic: exact-tolerance decimal arithmetic that refuses floats outright, one identity per document family, and a model never certifies a figure. Normalization is locale-aware and versioned, and where a shape is genuinely ambiguous and no locale decides it, the figure is refused rather than guessed. When a document does not reconcile, the gap is diagnosed cheapest-first, and only a forced finding is applied and re-checked — anything else holds the statement for review rather than posting a guess. Divergent profiles — a pay stub, a brokerage statement — each carry their own facts shape, identity and projector, proving that a new document shape is data plus a projector rather than new plumbing.

*Knowing what is the same thing.* The same primitive appears five times: gather signals, grade the match, ask only when genuinely ambiguous, record the ruling, apply it on the read side. Accounts anchor on the number, not on the holder's name. Two movements that are one internal transfer are linked as a graded overlay and excluded from spending, so money never appears to leave twice — and the same mechanism doubles as a reconciliation witness where a counterparty statement's movements uniquely account for another statement's gap, with uniqueness as the gate. A merchant is known by its brand, resolved for a whole vault at once because the boundary between a sender name and the noise around it is a property of the corpus rather than of any line, enriched in one batched call in a package that holds only impersonal knowledge. A category is a resolved identity rather than a bare string, because two spellings of one label silently halve every total that touches either. A category partitions and a tag overlays, and tag reports return the untagged and total figures beside the per-tag ones so a reader can see they do not add up.

*Making the numbers honest.* Asset and liability signs are opposite, and the counter-leg is kind-aware. Spending means money that left your *life*, not money that left an account, derived on the read side by a ladder of evidence, strongest first — and anything the ladder cannot settle is counted but reported provisional rather than silently resolved. A holding is measured at the statement date and never posted; unrealized change is the difference between two measurements rather than a fabricated transaction. Net worth is a curve defined at every date, where an earlier point never moves when a later document lands, an account with no measurement contributes nothing rather than zero and appears in a skipped list, and an asserted-but-unpriced asset is a disclosed gap reported with the question that closes it. Subtotals are per currency with no converted grand total, and every point names its stalest input. The answering path has no model in it: a question is a fixed function over the projection, and the layer's job is the honesty envelope.

*Asking, and being told.* One ranked queue is the front door for everything Viva needs to know, ranked by consequence, scoped to the most general unit that is still honest, with the tail summarized rather than hidden. Question text is a deterministic template, because a model that phrased a question could smuggle a claim into it. Every movement sorts into three tiers — settled, asked nothing; structural, given an informed proposal; unknown, given a real question — so the product forms the belief and the person confirms it. A sentence becomes double-entry through six steps with exactly one model call, and that call parses *intent* only: a ruling's legs structurally cannot carry a figure, and no account comes into being without an explicit yes, whatever the path. The interview is a projection over the answers an account already carries rather than an object, so it is retroactive, correctable and free. What may be asked about a kind of asset is data in a reviewable pack, and which schema an account gets is decided by evidence, strongest first, and only when exactly one kind claims it. An account records its jurisdiction and defaults to *nobody has said* rather than to a country. Every sentence Viva can say lives in a versioned phrasing pack keyed by intent; rendering is strict, and a phrasing may not introduce a fact the intent did not supply. Declines snapshot the stake, so a declined question stays quiet until the stake changes — no timers.

*Being asked, and answering.* A registry of read tools sits on the projection, each returning a graded, cited envelope rather than a bare number, with a planner in front of them that chooses the calls and writes the sentence but never computes a figure. A session carries prior turns as context and re-fetches every figure per turn, so an answer is never composed from what an earlier answer said. Coverage is not the stretch of time a read happened to see movements in — it is the period a reconciled statement declared, recovered from what each document said about itself, joined only where balances continue *and* dates meet, and reported one entry per account. The citation gate is code rather than instruction: a figure with no record id behind it is refused, and the ways a number could ground itself falsely have been closed one at a time. That gate was rebuilt rather than lengthened: a whitelist over prose a model had already written could never be finished, because the set of numeric tokens in a sentence about money that are *not* claims about money is open-ended. What replaced it inverts the order — a model commits a *shape* of literal words with typed holes before any tool is on the table, code binds the holes to references into the run's own ledger, and one renderer writes them. Nothing inspects the finished sentence, because a model writes no digits into one ([projection-decomposition-and-the-tool-registry.md](projection-decomposition-and-the-tool-registry.md)). Every exchange is kept verbatim with the prompt version and model that produced it, which is what makes a later eval possible at all.

*Presentation semantics, as a decision rather than as code.* One card per instrument kind, each carrying the same three things — the figure, its as-of date and grade, and what it does not include — with a liability speaking *owed* rather than showing a signed figure. Both the compiled-bundle surface and the plain-HTML one were built and removed: a stale artifact can serve last hour's product with no error and no way to tell by looking, and the debug page that replaced it had begun costing verification findings of its own. What survives is the semantics, carried in [the-surface-cards.md](the-surface-cards.md); the real presentation layer is still an unheld design conversation, and designing a third surface before that conversation would be a fourth thing to throw away.

*Instruments and tooling.* Rebuild replays stored claims through today's parsers into a new vault, free and with no model calls, testing the parsers against yesterday's replies. Reingest re-reads the stored originals through today's prompts at real cost and reports regressions. Reset rebuilds the log with categorization dropped and a person's own rulings preserved. An interpretation eval scores sentence-reading against a frozen synthetic key with the confidently-wrong rate as the headline and a hard disqualification on any fabricated split or amount, and a run that could not reach the model is never scored. A model admission exam grades candidates on a frozen corpus across input modes and publishes no composite leaderboard.

**What is planned, and why in this order.**

*Obligations and proactive alerts* turn passive records into active help: an obligation primitive with cadence and due rules from recurrence detection, anomaly and fee and subscription detection reusing the existing finding block, and a proactive trigger deciding *when* to surface. Its real dependency is nature and category semantics settling, not time — recurrence detection stays noisy until then. The proactive-trigger block is exactly what the conversational agent later uses to volunteer. Card-specific fields feed obligations; when needed, the card profile version bumps and only affected statements are re-read, because the claims layer records which profile version read each document.

*Viva speaks* is mostly built, and what remains is the honesty measurement rather than the machinery.

*Goals and budgets* compose spending, income and balances with no new engine, and establish the graduated-autonomy pattern — draft against act — that every future action inherits: Viva drafts on request and never acts irreversibly without a yes.

*Loans, insurance, tax and FX* each ship as their own smallest seed: one loan, one policy, one tax document, one currency pair. Most of this is [document-coverage.md](document-coverage.md) becoming registry rows. A mortgage payment is compound — interest, principal and escrow in one movement — so it cannot be answered by a single ruling and must be split, and the ratios come from the loan statement, which is why it lands here; until then the queue names such payments as compound and asks for the document rather than forcing a guess ([learning-mode.md](learning-mode.md)). This slice completes consolidation of a full financial life; the provision primitive proves the model is not secretly transaction-shaped, and tax, cost basis and jurisdiction are prerequisites for real advice and for a two-country reality.

*Trust hardening* periodically anchors the chain head to a trusted timestamp or transparency log — signatures and a timestamp, no blockchain, no token — and verifies issuer signatures where issuers provide them, so authenticity needs no inference. It makes facts provable to others, which is the precondition for the endgame.

*Creditworthiness and selective disclosure* is the vision in seed form: a bitemporal creditworthiness projection, and a proof bundle disclosing a single graded claim with its provenance and anchor, revealing nothing more. It composes every block, and the net-worth curve's provable subtotal is already its first primitive, derived for free.

*Household scope and sync* comes last because it is a *mode*, not a foundation: a scope lens filtering by party, and sync as encrypted vault export and import through a blind relay where documents stay put and the ledger follows. Party existed from day one, so this does not reshape the schema.

**Decision recorded: no agent-memory framework.** Rulings are institutional knowledge, not preferences, and the append-only, graded, deterministically-applied event log already avoids the staleness and trustworthy-retrieval problems those frameworks are benchmarking.

**The stack, end to end.** The first version gave one honest answer. The built half consolidates a whole financial life on a small set of re-composed blocks. Obligations make it volunteer, the speaking slice gives it a voice, goals and instruments let it advise and act across every domain, trust hardening and selective disclosure make its facts provable to others — the credit-bureau alternative — and household scope opens it to multiple people and devices. Every slice is the same blocks, re-composed.

## Open

- What the interface currently does render is tracked in [user-interface-implementation-status.md](user-interface-implementation-status.md).
- The desktop bridge gates and the live desktop transport are deferred by design until a bridge consumer exists; adding empty machinery ahead of one would be worse than the gap.
- The packages require Python 3.11 or newer while the local default interpreter is older, so integration checks must run under the declared supported runtime or they prove nothing.
- Existing desktop fixtures are synthetic interface data rather than generated surface fixtures; treating them as parity evidence bypasses the contract gate.
- Recommended integration checks, standing: run the surface contract, capability coverage, import boundary and impact checks under the supported runtime; regenerate schema and fixtures twice and compare byte-for-byte; mutate a field, a closed-vocabulary value, a protocol version and a capability disposition in temporary copies and confirm each fails for the intended reason; inventory every command entry point and assert each is classified exactly once; verify dependency direction in both languages; then run the full product suite and confirm the branch carries no generated frontend output changes.
- The conversation has met the author's real vault, and what the runs found is not settled. A wrong number reached a person, carrying its grade and its citation correctly, from four compounding faults of which none was in the shape mechanism. And *swapping the model changes phrasing rather than answers* is false as written: one local model emitted no tool call in twenty replies and so answered nothing at all, which makes the property per-model rather than a property of the design, with the shipped default on the wrong side of it.
- Two done criteria for the speaking slice still have no test: that a document's own text cannot make Viva act, and that swapping the model changes phrasing rather than answers.
- The wiring between the model and the citation gate is unpinned: the gate is tested hard and its supply line is not.
- Volunteering through the proactive triggers is a done criterion of the speaking slice and the triggers do not exist yet.
- Where this sits against the product phases: `ROADMAP.md`'s foundations phase is complete, and the organize-and-consolidate phase is in progress — transfer-linking and always-current net worth are built, account aggregation is not.
- Anchoring has never run and nothing schedules it; it is trust hardening's work.
- Done criteria, obligations and proactive alerts: a recurring charge becomes an obligation with cadence; a surprise fee or duplicate subscription raises a finding; completeness (expected-versus-seen) becomes a nudge, so a missing expected statement is flagged; triggers respect a speak-when-it-matters threshold.
- Done criteria, goals and budgets: a category budget tracks actual against target from spending; a payoff or savings goal projects a date from cash flow; progress updates as statements post; Viva drafts on request but never acts irreversibly without a yes.
- Done criteria, loans, insurance, tax and FX: a mortgage payment splits principal, interest and escrow and projects a payoff date; a deductible question answers from a provision with its source; estimated tax cites its jurisdiction rules; an FX-converted total is labelled an estimate with its rate and date.
- Done criteria, trust hardening: the chain head anchors and the anchor verifies independently; a signed statement's signature validates and the grade rises to issuer-attested; an outside party detects tampering given only the anchor.
- Done criteria, creditworthiness and selective disclosure: a proof bundle verifies against the anchor and issuer signatures without exposing other data; the claim carries its grade; a third party validates it offline; nothing beyond the claim leaks.
- Done criteria, household scope and sync: a joint account attributes to the right parties; a household total scopes correctly; an encrypted vault round-trips across devices with no plaintext exposure; keys never leave the user.
