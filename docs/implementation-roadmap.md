# OrionViva — Implementation Roadmap

**Status:** Living · **Last updated:** 2026-08-01 · **Approach:** data-first; every slice seeds a reusable **lego block**, and the trust signal (grade + provenance + bitemporality) rides all of them from v0 to the endgame.
**Invariants touched:** the whole set — this is the ordered path by which T1–T9, I1–I6, M1, X1–X3 get built.

This doc has two halves, and the split is the point.

**What is built** is described by **capability**, not by the slice that produced it. A slice is a unit of *planning*; once the work exists, the code and its design doc are the record, and a label like "5.6" only tells a reader where in a queue it once sat. Reading the built half should answer *what does this product do today*, and nothing else.

**What is not built** is described by **slice**, in order, in the fact-statement form the plan has used throughout: **open state** (with a proof the capability is absent) → **implementation** → **final state** → **done criteria / tests** → **why now + future use**. Nothing is built ahead of its slice, and each is designed in detail with the author before code.

**About the labels.** Slice numbers appear in commit messages and in the public build log. Those are the frozen record and are not renumbered; they refer to the historical planning sequence, which no longer maps onto this document's built half. Work committed before 2026-07-26 under the label "Slice 9b" is the counterparty-implications work described below under *Deciding who to ask*, not the unbuilt "Viva speaks" slice.

**Where this sits against the product phases.** `ROADMAP.md`'s Phase 0 (foundations) is complete. Phase 1 (organize & consolidate) is in progress: transfer-linking and always-current net worth are built; account aggregation is not.

---

# Built

## The ledger and the log

**An encrypted, append-only, hash-chained event log.** Every fact is an `Event` with a value time and an ingest time, sealed with AES-GCM and chained by record hash, so state is always a projection and history is never rewritten. A corrupt ledger refuses to read rather than guessing. Chain verification needs no key.

**Double-entry postings.** A movement's postings sum to exactly zero, checked deterministically. An `amount` is the signed change to the named account. Account roots are fixed in code; everything below them is data. A movement's counter-leg goes to an Uncategorized bucket graded `unverified` — the amount is attested, the classification is not — and every later categorization is an overlay on the read side, so the posted leg is never rewritten.

**Raw capture before judgment.** The original bytes are sealed and stored before anything parses them, and every model request and reply is recorded verbatim with its model id and prompt version. Nothing trust-relevant is discarded.

**Any-order ingestion with bidirectional heal.** A statement older than the one that seeded an account prepends and re-seats the opening balance; a statement dropped into a gap heals both sides and cascades. Every ordering of the same documents yields an identical chain. Opening Balance Equity reflects only genuinely unexplained history.

**A cached incremental projection.** The `Ledger` facade holds one live projection folded forward on each append, so ordinary reads never re-decrypt the log. A point-in-time projection is available as an escape hatch.

## Reading documents

**A doc-type registry.** A document type is a data row naming its account kind, its identity check, and the prompt fragments it owns. Adding a balance-family type needs no code. The pipeline classifies, selects the profile, then extracts. There are no per-institution parsers anywhere in the tree.

**Two-phase reading.** A cheap classify pass on the first page decides the type; a type whose profile has no extraction prompt parks before an expensive extract call is paid for. Extraction sends every page image together with the issuer's own embedded text. A bounded retry distinguishes a JSON syntax failure from an unreadable field, and a shared continuation driver survives truncation.

**Prompts as versioned files.** Every model-facing string lives in `<package>/prompts/<version>.txt` and is loaded by id; a released version is never edited, so a recorded `prompt_version` resolves to the exact text that produced a reading, forever. A composed extraction prompt records a self-describing composite id that reverses back to its parts. A build-failing test keeps prompt text out of code.

**Deterministic verification.** Arithmetic runs on `Decimal` with exact tolerance and refuses floats outright. Each document family has one identity: `opening + Σ = closing` for the balance family, `gross − deductions = net` for a pay stub, `Σ market_value + cash = total` for a brokerage snapshot, and `opening cash + Σ activity = closing cash` for brokerage flow. A model never certifies a figure.

**Locale-aware normalization.** An amount is always a value and a currency. Grouping and decimal conventions, negative conventions (parentheses, DR/CR, trailing sign) and date orders are resolved by explicit versioned rules; where the shape is genuinely ambiguous and no locale decides it, the figure is refused rather than guessed. One accessor supplies the configured locale to every entry point.

**Findings when a document does not reconcile.** A gap is diagnosed cheapest-first: a printed running balance can localize the misread line *forced*; a gap equal to one line's amount or divisible by nine is *suggested*; otherwise it is *unlocalized*. A forced finding is applied and re-checked; anything else holds the statement for review rather than posting a guess.

**Divergent profiles.** A pay stub carries its own facts shape, its own identity, and its own projector, and decomposes the checking deposit its net explains — gross recognized as income once, withheld tax, retirement and insurance recorded as their own legs in universal buckets with jurisdiction as an attribute. A brokerage statement does the same for holdings and activity. Both prove that a new document shape is data plus a projector, not new plumbing.

## Knowing what is the same thing

The same primitive appears five times: gather signals, grade the match, ask only when genuinely ambiguous, record the ruling, apply it on the read side.

**Account identity.** Accounts anchor on the last four digits of the number, with institution and holder names as supporting signals and the holder's own name deliberately excluded as non-distinctive. An ambiguous match raises a question scoped to the same account kind; the confirmation is recorded and applied thereafter.

**Transfer links and cross-document corroboration.** Two movements that are one internal transfer are linked as a graded overlay — neither leg is re-posted — and excluded from spending, so money never appears to leave twice. The same mechanism doubles as a reconciliation witness: when a counterparty statement's movements uniquely account for another statement's gap, that gap closes with two issuers vouching and no model call. Uniqueness is the gate; a gap is never closed on a guess.

**Merchant knowledge.** A merchant is known by its **brand**, so two locations of one retailer are one record: the key is the normalized brand a resolution layer named, and the normalized descriptor only where no layer could name one. It is resolved for a whole vault at once, because the boundary between a sender name and the noise around it is a property of the corpus rather than of any single line, and a lookup considers both candidates so an answer recorded under the older name still answers. Merchants are normalized deterministically by a versioned normalizer and enriched in one batched model call over new merchants only, into records carrying a category, a subcategory, a canonical name and structural attributes. Enrichment lives in `merchantcore`, a package peer to `vivacore` that holds only impersonal merchant knowledge; personal figures never cross into it. Results sync back as events so the ledger stays self-contained, and categorization applies retrospectively. The catalog is shared across vaults and is the seed of a content-addressed commons.

**Category identity.** A category is a resolved identity, not a bare string, because two spellings of one label silently halve every total that touches either. Three layers, no string comparison: every minting path is shown the existing vocabulary first; a genuinely new label resolves once through a scoped ruling; and the projection folds aliases on the read side, retroactively, reversed by appending.

**Tags.** A category partitions — exactly one per movement, so the parts sum to the whole — and a tag overlays, many per movement, with totals that deliberately do not sum. Tag reports return `untagged` and `total` beside the per-tag figures so a reader can see they do not add up. Tags are their own event type, because a tag is personal meaning that no commons can know.

## Making the numbers honest

**A kind-aware counter-leg.** Asset and liability signs are opposite: money out of an asset and a charge on a liability are both expenses; money into an asset is income; a payment on a liability is a debt reduction, not income.

**Movement nature.** Spending means money that left your *life*, not money that left an account. Nature is derived on the read side by a ladder, strongest evidence first: an explicit transfer link, then a person's ruling on the movement or its merchant, then an own-account name in the description, then what the counterparty's category implies, then a default of spending. Anything the ladder cannot settle is counted but reported **provisional** rather than silently resolved, and a compound movement is reported as undecomposed rather than forced into one bucket.

**Spending, by category and by subcategory**, composed with transfer exclusion, with the amount resting on weak evidence reported separately from the amount that does not.

**Positions as dated measurements.** A holding is measured at the statement date, never posted. Unrealized change is the difference between two measurements — a presentation view carrying its date and valuation class — never a fabricated transaction. Realized cash events post: contributions tie to the funding account and are counted once, dividends and interest are income, fees are expense, and a reported realized gain books to capital gains.

**Net worth as a curve.** `net_worth(D)` is defined at every date between the earliest and latest observation, each point built from every account's last measurement at or before D. An earlier point never moves when a later document lands. An account with no measurement contributes nothing — never zero, never a guess — and appears in a `skipped` list naming the document that would fix it. An asset the person asserted but has never priced is a **disclosed gap**: reported in `missing` with the question that closes it, so the point reads incomplete rather than quietly complete — and a stated cost then replaces the cash-derived line for that account rather than adding to it. Which answer lets the curve carry a thing, and which answer dates it, are pack fields; the curve infers neither. Sign comes from account kind, so an overpaid card reads as an asset. Subtotals are per currency with no converted grand total, and every point names its stalest input.

**An answering path with no model in it.** A question is a fixed function over the projection; the layer's job is the honesty envelope. A total sums only trustworthy balances and names by grade every account it excluded. A conflicted balance returns the reconciliation explanation instead of a number. Multiple currencies return subtotals and a statement that they are not converted.

## Asking, and being told

**A question queue.** One ranked front door for everything Viva needs to know — identity, reconciliation, transfers, merchants, nature, corroboration, expected documents, and what an account still needs known about itself. Questions are ranked by consequence, so answering the top of the list moves the most money; each is scoped to the most general unit that is still honest; and the tail is summarized rather than hidden. Question text is a deterministic template. A model that phrased a question could smuggle a claim into it. A question set aside is deferred into a **pending list the person opens**, not into silence: it is still built, so it can be looked for, and it returns of its own accord when the money behind it moves.

**Deciding who to ask.** A merchant's category implies structure — a mortgage servicer implies a property, a loan, escrow, a tax document — and that knowledge is attached at enrichment time, where it is impersonal, batched, cached and shareable. Every movement then sorts into three tiers: **settled**, which is asked nothing; **structural**, which gets an informed proposal naming what the product already believes; and **unknown**, which gets a real question, one transaction at a time. The product forms the belief and the person confirms it.

**Rulings in your own words.** A sentence becomes double-entry through six steps with exactly one model call, and that call parses *intent* only. The four majors are expense, asset, liability and income; equity is absent because for a person it is net worth and is derived. A ruling's legs structurally cannot carry a figure — the event constructor refuses a leg with an amount — so the money always comes from the movement. The one exception is a figure the *person* stated about a thing they hold, and it is fenced: attribute scope only, refused unless the number appears among the numbers they actually wrote, refused if it is negative or not finite. Account resolution reuses the account matcher, so ask-only-when-ambiguous comes for free. **No account comes into being without an explicit yes**, whatever the path: an answer that would open one comes back as a proposal saying so in plain words, an account taken to be an existing one is named in that sentence rather than silently bound, and an answer that names nothing at all is met with the question rather than a placeholder path. A missing document never blocks a ruling: the account is created, the cash posted, the decomposition marked provisional, and the corroborating document asked for.

**The interview — a question with a next step.** For an account whose kind is resolved, the next thing still owed about it is asked, one question at a time, and answering it produces the next. There is no interview object and no interview event: the state is a projection over the answers and declines the account already carries, so it is retroactive, correctable and free. An answer is a scoped ruling like every other. An interview is ranked with everything else by the cash a ruling has put against its account, so it never outranks a larger finding for being new, and an account whose money its own statements already explain carries a stake of zero rather than borrowing its balance. A yes that implies a second instrument — a loan against a property — offers to start that one's interview, and offers rather than creates.

**The schema pack — the fourth pack.** What may be asked about a kind of asset or liability is data: kinds, question keys, jurisdiction tags, the words each question asks, what answering it unlocks, which answers are essential, which one gates net worth and which one dates it. A lint refuses a pack that could ask something unreviewable — an answer type outside the closed vocabulary, a choice that enumerates nothing, a question that cannot say what it unlocks, a document type the ingestion pipeline does not classify. The pack holds no vault data, so it is reviewable in one sitting and shareable like the merchant catalog. **Which schema an account gets is decided by evidence, strongest first:** the shape of a path this interview created, then the document types an issuer produced for it, then the ledger's own account kind — and only when exactly one kind claims it, because a loan and a card are both liabilities and that word alone settles nothing. An account nothing resolves is recorded as a coverage gap rather than asked a question built on a guess. A classified statement also answers the question its own type settles, so nobody is asked whether a checking account is a checking account.

**Where an instrument lives.** An account records its jurisdiction, and it defaults to *nobody has said* rather than to a country. Which schema applies and which documents would attest a fact both follow from it, so a default naming one country would have put a fact in the ledger that no document and no person ever stated.

**Viva's voice as data.** Every sentence Viva can say lives in a versioned phrasing pack keyed by intent, with a declared set of slots; rendering is strict, so a question with a hole where a fact should be fails loudly rather than shipping. A phrasing may not introduce a fact the intent did not supply. "Not now" and "I don't know" are recorded as decline events that snapshot the stake, so a declined question stays quiet until the stake changes — no timers.

**Expectations — documents that pursue documents.** A jurisdiction-tagged registry of read-side mechanisms: a retirement flow implies a retirement statement, an investment account implies a tax document, and an account whose newest statement has gone stale implies a fresher one. Satisfaction is deterministic — the document arrived or it did not.

## The surface

**A local web surface built from cards, in plain HTML with no build step.** One card per instrument kind: a depository leads with its balance and its as-of date; a liability speaks *owed* and calls out a credit balance; an investment shows the statement's own `cash + Σ holdings = total` cross-check and names activity it could not post; an asserted asset says *cost*, badged as your word, with the document that would corroborate it. Every card carries the same three things — the figure, its as-of date and grade, and what it does not include. A card that throws cannot take the page down or blame the ledger. A compiled-bundle surface was built and removed: a stale artifact can serve last hour's product with no error and no way to tell by looking.

This surface is explicitly a debug tool. The real presentation layer is an unheld design conversation.

## Instruments and tooling

**Rebuild** replays stored claims through today's parsers into a new vault, free, with no model calls — testing the parsers against yesterday's replies. **Reingest** re-reads the stored original documents through today's prompts, at real cost, and reports regressions against the source vault. Both leave the source untouched.

**Reset** rebuilds the log with categorization events dropped and a person's own rulings preserved, printing a per-type before-and-after count. **Export and diff of rulings** answer whether the product now proposes what a person previously had to type.

**An interpretation eval** scores sentence-reading against a frozen synthetic key, with the confidently-wrong rate as the headline and a hard disqualification on any fabricated split or amount. A run that could not reach the model is never scored and never averaged.

**A model admission exam** (`viva-bench`) grades candidate models on a frozen corpus across input modes, measuring per-claim accuracy, recall, self-consistency, calibration, spurious claims, truncation, cost and latency — and publishes no composite leaderboard.

---

# Planned

Slice numbers below continue the historical sequence and are not reused.

## Slice 8 — Obligations & proactive alerts
**Block seeded:** Obligation (bills/recurring) + Proactive trigger + Finding *reused*.

> _Card-specific fields (credit limit, minimum payment, due date) feed Obligations. When needed, bump the card profile version and targeted-re-read only the affected statements — the claims layer records which profile version read each document — rather than a redesign._

**Open state:** bills/recurring aren't tracked; fees, duplicate subscriptions, anomalies pass silently; the system never volunteers. *Proof:* no obligations list; a fee posts unremarked (red test).

**Implementation:** an Obligation primitive (cadence + due rules from recurring detection); anomaly/fee/subscription detection as **Findings** (reuse); a proactive trigger deciding *when* to surface; completeness (expected-vs-seen) becomes a nudge.

**Final state:** bills and recurring charges tracked; fees, anomalies, unused/duplicate subscriptions surfaced; the first volunteered insight.

**Done criteria / tests:** a recurring charge becomes an Obligation with cadence; a surprise fee or duplicate subscription raises a Finding; a missing expected statement is flagged; triggers respect a speak-when-it-matters threshold.

**Why now + future use:** turns passive records into active help; reuses Finding + Obligation + completeness; the proactive-trigger block is exactly what the conversational agent uses to volunteer.

**Real dependency:** nature and category semantics settling, not time — recurrence detection will be noisy until then.

---

## Slice 9 — Viva speaks
**Block seeded:** a tool registry (data, not code — the doc-type registry pattern again) + a planner that composes answers from tool results only.

The write direction is built: a person says what something is, and deterministic code applies it. This is the read direction — a person asks what is true. The two carry different risk, which is why they were separated: a mis-parsed ruling persists and generalizes, while a wrong answer misleads once.

**Open state:** interaction is fixed function calls and buttons; no free-form questions; no voice. *Proof:* no natural-language entrypoint (red test).

**Implementation:** a question in plain language plans tool calls over the deterministic tools already built, and the model composes the answer from tool *results only*, surfacing grade and provenance and **never computing a figure**. The persona pack supplies the voice; user operational memory supplies the context; the model is pluggable and pinned. The document reader stays quarantined and powerless.

**Final state:** you talk to Viva; she answers anything the tools cover — honestly, with sources, in her voice — and volunteers through the Slice 8 triggers.

**Done criteria / tests:** questions map to the right tools and return grade and source; Viva hedges or refuses honestly on missing or conflicted data, measured by the confidently-wrong rate; the model never emits an unverified number (a tool-boundary test); a document prompt-injection cannot make her act; swapping the model changes phrasing, not answers.

**Why now + future use:** the soul, and the payoff of building data-first — she wires to a rich toolset with no new truth logic, and every later slice extends her for free. Waits for a toolset worth asking.

**Decision recorded:** no agent-memory framework. Rulings are institutional knowledge, not preferences; the append-only, graded, deterministically-applied event log already avoids the staleness and trustworthy-retrieval problems those frameworks are benchmarking.

---

## Slice 10 — Goals & budgets
**Block seeded:** Goal/Budget (target + progress projection).

**Open state:** can't set a budget or a savings/payoff goal; no progress; no take-action. *Proof:* goals unsupported (red test).

**Implementation:** a Goal/Budget primitive (spend ≤ X on a category; save Y by a date; pay off Z) and a progress projection over spending, income and balances. Viva drafts budgets and payoff plans — autonomous on the draft, asking before anything irreversible.

**Final state:** budgets and goals exist with live progress; Viva advises and drafts plans.

**Done criteria / tests:** a category budget tracks actual against target from spending; a payoff or savings goal projects a date from cash flow; progress updates as statements post; Viva drafts on request but never acts irreversibly without a yes.

**Why now + future use:** composes spending, income and balances with no new engine; establishes the graduated-autonomy pattern (draft vs act) that every future action inherits.

---

## Slice 11 — Loans, insurance, tax, FX
**Blocks seeded:** Loan/amortization · Provision (insurance and loan terms) · Tax (attribute + liability projection + cost basis + jurisdiction) · FX/currency.

Each domain ships as its own smallest seed — one loan, one policy, one tax document, one currency pair.

> _The full instrument list — what is covered, what is missing, and what each gap blocks — is [document-coverage.md](document-coverage.md). Most of this slice is that list becoming registry rows._

> _A mortgage payment is compound — interest, principal and escrow in one movement — so it cannot be answered by a single ruling and must be split. The ratios come from the loan statement or the annual interest statement, which is why this lands here. Until then the queue names such payments as compound and asks for the document rather than forcing a guess: [learning-mode.md](learning-mode.md)._

**Open state:** a mortgage is a raw transaction stream with no principal/interest/payoff; insurance coverage isn't searchable; tax-relevance and estimated liability are absent; multi-currency can't total or convert. *Proof:* a mortgage doesn't amortize; "am I covered for X" is unanswerable; the tax view is empty; two currencies can't combine (red tests).

**Implementation:** Loan (amortization from terms held as a Provision; escrow split; payoff projection); Provision (attested non-numeric coverage and terms, searchable, graded); Tax (a tax-relevant tag, cost-basis capital gains, an estimated-liability projection citing jurisdiction rules); FX (answer-time conversion with a cited, dated rate, and converted totals labelled an estimate).

**Final state:** loans amortize and project payoff; insurance and loan terms are searchable; tax liability is estimable with cited rules; cross-currency is reported honestly.

**Done criteria / tests:** a mortgage payment splits principal/interest/escrow and projects a payoff date; a deductible question answers from a Provision with its source; estimated tax cites its jurisdiction rules; an FX-converted total is labelled an estimate with rate and date.

**Why now + future use:** completes consolidation of a full financial life; each domain reuses existing blocks plus one new primitive; Provision proves the model isn't secretly transaction-shaped; tax, cost basis and jurisdiction are prerequisites for real advice and for a two-country reality.

---

## Slice 12 — Trust hardening
**Blocks seeded:** Anchoring (chain head → trusted timestamp / transparency log) + issuer signatures / verifiable credentials.

**Open state:** the hash chain proves internal tamper-evidence but anchors to no external time; authenticity rests on a model reading a document rather than an issuer attesting it. *Proof:* no external anchor; a signed statement's signature isn't verified (red test).

**Implementation:** periodically anchor the chain head to a trusted timestamp or transparency log — signatures and a timestamp, no blockchain. Where issuers provide signed documents, verify the signature so authenticity needs no inference and the grade rises to issuer-attested. No token, no chain.

**Final state:** the ledger is tamper-evident to third parties and time-anchored; issuer-signed facts are authenticated at source.

**Done criteria / tests:** the chain head anchors and the anchor verifies independently; a signed statement's signature validates and lifts its grade; an outside party detects tampering given only the anchor.

**Why now + future use:** makes facts provable to others, the precondition for the endgame; reuses event, provenance and grade; holds the signatures-not-blockchain line.

---

## Slice 13 — Creditworthiness + selective disclosure
**Blocks seeded:** a creditworthiness projection + a selective-disclosure proof bundle.

**Open state:** your data can't vouch for you; a counterparty can't verify a claim without seeing everything; there is no proof export. *Proof:* no proof bundle; a counterparty question can't be answered without full disclosure (red test).

**Implementation:** a creditworthiness projection over grade, provenance, payment history and net worth, bitemporal; and a proof bundle disclosing a single graded claim — "balance ≥ X as of a date", "on-time payments ≥ N" — with its provenance and anchor, revealing nothing more. Smallest seed: export one signed, verifiable claim.

**Final state:** you can prove a specific financial claim to a counterparty, holding your own keys, revealing only what is needed — the user-owned credit-bureau alternative, in miniature.

**Done criteria / tests:** a proof bundle verifies against the anchor and issuer signatures without exposing other data; the claim carries its grade; a third party validates it offline; nothing beyond the claim leaks.

**Why now + future use:** the vision in seed form. It composes every block, and the net-worth curve's provable subtotal is already its first primitive, derived for free.

---

## Slice 14 — Household scope + sync
**Blocks seeded:** a Scope/Household lens (Party + whose-money view) + Sync (blind-relay, encrypted).

**Open state:** single-user, single-device; no shared view; no multi-device. *Proof:* can't scope to a household member's account or sync to a phone (red test).

**Implementation:** a Scope lens filtering by Party — individual, joint, household — with the user still holding the keys; and Sync as encrypted vault export and import through a blind relay, where documents stay put and the ledger follows. Smallest seeds: one household member's account visible; one manual encrypted round-trip.

**Final state:** an optional household view, and a vault that follows you across devices without decryptable data leaving your control.

**Done criteria / tests:** a joint account attributes to the right parties; a household total scopes correctly; an encrypted vault round-trips across devices with no plaintext exposure; keys never leave the user.

**Why now + future use:** last because it is a *mode*, not a foundation. Party existed from day one, so this doesn't reshape the schema.

---

## The stack, end to end

v0 gave one honest answer. The built half consolidates a whole financial life on a small set of re-composed blocks. Slice 8 makes it volunteer, Slice 9 gives it a voice, Slices 10 and 11 let it advise and act across every domain, Slices 12 and 13 make its facts provable to others — the credit-bureau alternative — and Slice 14 opens it to household and multi-device. Every slice is the same lego blocks, re-composed, and the trust signal rides all of them from v0 to the endgame.
