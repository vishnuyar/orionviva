# OrionViva — Implementation Roadmap

**Status:** Approved plan · **Last updated:** 2026-07-23 · **Approach:** data-first; every slice seeds a reusable **lego block**, and the trust signal (grade + provenance + bitemporality) rides all of them from v0 to the endgame.
**Invariants touched:** the whole set — this is the ordered path by which T1–T8, I1–I6, X1–X3 get built. Each slice states its own.

Each slice is named by the lego block it seeds and written as a fact statement:
**Open state** (before, with a proof the capability is absent) → **Implementation** → **Final state**
(after) → **Done criteria / tests** → **Why now + future-use advantages**. Per-slice detail is
expanded into a design doc when that slice is built; ordering here is fixed. Nothing is built
ahead of its slice, and each slice is designed in detail with the author before code.

The lego blocks (v0 primitives) and the full block inventory live in the architecture notes;
this doc is the *sequence*.

---

## Slice 1 — Backfill / any-order ingestion  ✅ DONE (commit f8393fd)
**Block seeded:** completes the *stitch/identity* block (bidirectional).

_Delivered: backward-prepend + bidirectional cascading heal (any upload order → identical chain); Option A projection (OBE = earliest opening); and the `Ledger` facade (cached incremental projection — first perf optimization)._

**Open state:** a statement *older* than the one that seeded an account can't slot in *before* it — it strands as a "gap," even when its closing connects to the seed's opening. *Proof:* upload May (seeds), then April (April closing = May opening) → April held as a gap (a red test asserting this).

**Implementation:** when a reconciled statement's *closing* equals the account's current *earliest* opening, **prepend** it — append a superseding earlier opening (re-seat Opening Balance Equity at the older date), connect the chain, cascade for a run. Events stay append-only; the projection recomputes "earliest opening."

**Final state:** statements ingest in **any order**; the chain assembles regardless of sequence. Three-year-old data fits as seamlessly as a mid-month statement.

**Done criteria / tests:** every ordering of a 3-month run yields the identical posted chain, zero gaps; a statement dropped into a middle gap heals both sides; account opening = earliest statement's opening; OBE reflects only genuinely-unexplained history; the once-red open-state test passes.

**Why now + future use:** unblocks currently-stranded statements; turns order-independence into an **invariant every future doc type inherits for free**; precondition for trustworthy net worth (S7), which can't have order-dependent holes.

---

## Slice 1.5 — Account identity & entity resolution (learning)  ✅ DONE
**Blocks seeded:** Account (identity set) · Party (names/joint) · the universal entity-resolution matcher · identity-map projection · per-format registry (seed).

Added after the first real run: the same account arrived under different labels (product name vs holder name), so a free-text account id didn't stitch. Fix is a *learning* identity block — signals → graded match → ask only when ambiguous → learn the ruling, for **all** account types. Full spec: [account-identity-and-entity-resolution.md](account-identity-and-entity-resolution.md).

_Delivered: identity signals (number/institution/names) extracted + persisted + shown (masked); number-anchored account id (last-4); a matcher raising an identity Finding on ambiguity; ask-once-and-learn confirmation (AccountAliasConfirmed → merge or new); transactions sorted by date. Shipped alongside: multi-file upload (one model call per file), and JSON-mode + a bounded parse-retry so the model returns valid JSON on long statements. A `reingest-from-raw` tool re-reads stored PDFs into a fresh vault when the prompt improves._

## Slice 2 — Doc-type registry + credit card & savings  ✅ DONE
**Block seeded:** the format-profile registry (doc_type → {kind, extraction profile, identity}) + account kind (asset/liability) + the classify→profile→extract structure.

**Full spec + locked architecture:** [doc-type-registry-and-format-profiles.md](doc-type-registry-and-format-profiles.md). Decisions: **A1** sign reframe (effect-on-balance, prompt→v3, value-preserving for checking); **we own the schema, the model assists authoring**; versioned, personal-data-free profiles; **two kinds of learned data** (personal=local, format=shareable); re-read via reingest when a profile gains fields. That doc also carries forward-notes for S3/S6/S7/S8 and the format-commons slice.

_Delivered: `ingest/registry.py` — a `DocProfile` registry (checking/savings = depository, credit card = liability, all sharing the one `balance` identity); the pipeline routes by `profile_for`/`can_project` instead of a hardcoded checking set, and opens accounts with the profile's kind. Prompt bumped to `stmt-v3`: the balance family reads through one shape with per-line `balance_effect` (A1); the parser prefers it and falls back to the legacy `direction`, so stored reads reparse unchanged (value-preserving for checking). Identity ambiguity is scoped to same-kind. Display is kind-aware: a card reads as "owed" in the answer path, the web overview, and debug_vault. Net-worth netting deferred to S7. Tests: card reconciles as a liability shown owed; savings interest reconciles; same-holder card+checking stay two accounts; a brand-new balance type posts via a registry row alone (no gate change)._

**Open state:** only checking posts; a card/savings statement classifies but parks. *Proof:* ingest a card statement → parked, no balance (red test).

**Implementation:** a registry mapping each doc_type to its identity check and posting shape — card: *prev balance + charges − payments − credits = new balance* (a **liability** account; you owe it); savings: opening + txns + interest = closing. Add account **kind** (depository vs liability) driving sign and display. The reconciliation gate code is unchanged; the identity is *looked up* from the registry.

**Final state:** card and savings statements post and reconcile; the surface shows held vs owed; new types are added as registry **data**, not code.

**Done criteria / tests:** a real card statement reconciles on the charges−payments identity; a savings statement with interest reconciles; registering a *synthetic* type via data (no gate-code change) posts it; liability balances display as owed.

**Why now + future use:** proves "code universal, specifics are data" — the claim the whole architecture rests on; unlocks multi-account (net worth, transfers); the liability kind seeds loans (S11); every later doc type becomes a registry row.

---

## Slice 3 — Transfer links + cross-document corroboration  ✅ DONE (core)
**Block seeded:** Transfer link (two postings = one economic non-event, graded) + the cross-document reconciliation witness (a decisive counterparty leg closes another statement's gap).

**Full spec + locked architecture:** [transfer-links-and-cross-document-corroboration.md](transfer-links-and-cross-document-corroboration.md). Decisions: **internal own-account transfers only** (external Party → S5); **minimal netting** — `Transfers` is an exclusion category, self-netting economic sign → S7; **auto-link on decisive evidence, ask otherwise** (learn the ruling); **the transfer link doubles as a cross-document reconciliation witness** — a cheap, model-free, dual-issuer rung that supplies a leg a statement's read dropped (gated by decisiveness, provenance marked to the corroborating issuer, incomplete-read recorded so the crutch can't hide a model recall problem); v1 auto-links only when both legs are ingested own accounts; links reference a stable movement key, not an event id.

**Open state:** a checking→card payment counts as spending on checking *and* a payment on the card — money seems to leave twice; and a statement whose gap is attested by a counterparty stays held though the evidence to close it is already in the ledger. *Proofs (red tests):* summed cross-account outflow overstates real spending by the transfer amount; a card missing a payment the checking statement attests stays unreconciled.

**Implementation:** a stable movement key; a candidate matcher (amount/date/direction/description/own-account) over an amount·date index; a `TransferLinked` overlay event (grade + evidence) + recategorization of both legs into `Transfers` (excluded from aggregates); a decisiveness gate → auto-link (`corroborated`) or **Finding** (`suggested` → `verified`), learned thereafter; a **cross-document corroboration rung** in diagnosis that supplies a missing leg from a decisive counterparty (provenance → counterparty doc, incomplete-read marker, heals both orders); own-account membership learning; correction-as-event for confirm/reject/unlink.

**Final state:** internal transfers are recognized and excluded from spending; a statement whose gap is attested by a counterparty is rescued and posts `corroborated` with dual-issuer provenance; wrong/ambiguous links surface, never silently applied; confirmed patterns auto-link.

**Done criteria / tests:** a checking→card payment is linked and excluded from spending; total spending = real external outflow; a card missing a payment reconciles when the checking statement is present and its posting cites the checking doc; the same in either ingest order (heal); an ambiguous match surfaces a Finding (not auto-linked) and a non-decisive gap is not auto-closed; a confirmed link is verified and persists across reingest; a transfer naming an unseen destination asks the own-account question and learns it.

**Why now + future use:** without it, spending (S5) and cash flow are simply wrong — load-bearing for job-1 accuracy; it's the first cross-account fact, seeding the operational graph; the cross-document witness materially strengthens the verification layer and is an early instance of the endgame's cross-issuer corroboration; almost entirely reuse (Finding + correction + entity-resolution + grade + provenance + heal) — a composition proof.

---

## Slice 4 — Pay stub + income  ✅ DONE (core)
**Block seeded:** the **divergent-profile pattern** (a document type with its own facts shape + identity + post-projector, selected by the registry) + **Income** (gross decomposed into net + deductions).

**Full spec + locked architecture:** [pay-stubs-and-income.md](pay-stubs-and-income.md). Decisions: pay stub is the **first divergent profile** (identity `gross − deductions = net`, its own shape — proves the registry generalizes past the balance family); **decompose the deposit** (the net corroborates + links to the checking deposit — Slice 3 reuse, no double-count, order-independent; deductions become their own legs); **income is not one shape** (a 1099 is a *sibling profile*, not a subtype — annual total, no deduction identity, corroborates the SUM of many deposits; do NOT build a generic income abstraction); deductions into **universal buckets** (tax/retirement/insurance/other) as model-proposed graded attributes, jurisdiction as data (I5); **Core scope** — recurring→Obligation (S8), 401k-as-retirement-asset (S6), employer Party graph (S5), and 1099 all deferred.

**Open state:** the pipeline only reads balance-shaped statements; a pay stub parks, and a net-pay deposit sits in checking as undifferentiated income (the withheld tax/retirement/insurance invisible). *Proofs (red tests):* a pay stub parks (no projector for its shape); a net-pay deposit is only "uncategorized income", with no gross or deductions anywhere.

**Implementation:** generalize the ingest path along the registry seam — a `DocProfile` names its facts-shape + identity + post-projector; the reader dispatches after classify to the pay-stub prompt + a `from_paystub_json` parser (`PayStubFacts`); a deterministic `check_paystub_identity` (`gross − Σ deductions = net`) with the same forced/suggested/unlocalized finding contract; post the decomposition (gross → income, deductions → universal buckets graded by model-proposed category, net → a leg corroborated + linked to the checking deposit); income recognized once, order-independent via the heal pass.

**Final state:** a pay stub posts and reconciles on `gross − deductions = net`; its net links to the checking deposit so income is counted once; withheld tax/retirement/insurance are recorded (retirement not miscounted as spending); a pay stub that doesn't balance is held, not guessed; a different-shaped income doc (1099) can be added later as its own profile without touching this one.

**Done criteria / tests:** a real pay stub reconciles and posts; a misread deduction is held with a localized finding; the net links to the checking deposit in either ingest order and income is counted **once**; deductions land in universal buckets from the model's graded proposal and a retirement deduction is not counted as spending; registering a synthetic different-shaped type via a profile row alone routes to its own parser/gate (the divergent-profile proof); existing balance-family tests stay green.

**Why now + future use:** proves the registry generalizes beyond the balance family (first divergent shape + identity as data — inherited by brokerage/tax/insurance); recognizes **income**, the missing half; reuses Slice 3's corroboration (net ↔ deposit) rather than new plumbing; seeds the employer-Party (S5) and recurring-Obligation (S8) threads.

---

## Slice 5.6 — Extract `merchantcore` + the live enrichment engine  ✅ DONE (core)
**Block seeded:** the standalone `merchantcore` package (peer to vivacore): normalize · MerchantRecord (multi-attribute) · Enricher (batched model calls + versioned enrichment prompt) · Catalog (unencrypted store + pending queue + content-addressed commons export/import).

**Full spec:** [merchantcore-package.md](merchantcore-package.md). The three flows: product **submits only impersonal** merchant hints (normalized key + linted example — T5 at a package boundary, no amounts/dates/accounts cross); merchantcore makes its **own batched model calls** to enrich merchants into graded multi-attribute records; the product **syncs results back as `MerchantEnriched` events** so its ledger stays self-contained (T4) and categorizes retrospectively. Generalizes the Slice-5.5 `MerchantCategorized` → `MerchantEnriched`. Second shared crown-jewel package; the home for the enrichment prompt, multi-attribute merchants (website/socials/reviews later), and the commons registry. Deferred: web/API enrichers, the git commons registry, merchant-as-Party.

## Slice 5.5 — Merchant catalog & the categorization commons  ✅ DONE (core)
**Block seeded:** merchant catalog (normalized merchant → category, the prior) + deterministic versioned normalizer + batched merchant-categorization edge + unencrypted content-addressed commons export.

**Full spec + locked architecture:** [merchant-catalog-and-commons.md](merchant-catalog-and-commons.md). Origin: Slice 5's per-transaction categorization asked for the same merchant repeatedly on a real vault. Decisions (Vishnu's batched-catalog idea + refinements, 2026-07-24): **categorize the merchant not the transaction** (O(new-merchants) model cost, retrospective); **catalog is a prior, the Slice-5 per-transaction overlay is the override** (grade ladder verified→corroborated→unverified→Uncategorized); **privacy split** — raw descriptor stays ENCRYPTED (PII: order-ids, peer names), only a linted commercial merchant→category catalog is ever unencrypted/shared (T5); **deterministic + versioned normalization + model grouping, never fuzzy-matching** (Costco/Costa danger; location is an attribute, not a category); **batched threshold-triggered** model call (known merchant → free lookup, unknown → plain-vanilla + caveat); **the commons falls out** — content-addressed opt-in export, corroborated-by-count, local override wins. Deferred: full commons registry, merchant-as-Party, self-healing.

## Slice 5 — Categorization & spending  ✅ DONE (core)
**Block seeded:** Tag/Category (many-to-many overlay) + amount-split (double-entry) + spending projection + correction-as-event.

**Full spec + locked architecture:** [categorization-and-spending.md](categorization-and-spending.md). Core scope (Vishnu, 2026-07-24): **first job** = kind-aware counter-leg (card purchase→expense, card payment→transfers — fixes the Slice-4 sign-inverted buckets); **category = a graded overlay** via correction-as-event (`CategoryAssigned(movement_key, descriptor, category, grade, by)`, model `unverified` → human `verified`, movement-keyed so it survives reingest); **single-category, suggest-and-confirm** (no auto-apply); minimal jurisdiction-neutral **seed taxonomy** (I5); real **spending-by-category/time** excluding transfers (S3 reuse). **The forward seam:** every categorization captures the merchant descriptor → merchant normalization + a lazy, locale-sharded, override-able **merchant→category commons** (format-commons-style *prior*) + learned auto-apply are all a *later projection over the recorded correction events* — nothing wasted, no re-ingest. Deferred: merchant learning/commons, amount-splits, tags overlay, external Party.

**Open state:** every non-checking leg is "Uncategorized"; "where did my money go?" is unanswerable. *Proof:* spending-by-category returns all-Uncategorized (red test).

**Implementation:** _First job (a Slice-4 real-data finding): make the Uncategorized counter-leg **kind-aware** — a liability's purchase is an expense, its payment a liability reduction — so the Income/Expenses buckets stop being sign-inverted for cards and income/spending totals become trustworthy._ Then the two mechanisms — `split_transaction` (amount across categories) + a `tags` overlay; a spending projection (by category/tag/merchant/time); categorization via **correction-as-event** (user or model assigns; grade rises on confirmation); a minimal, aggressively-overridable seed taxonomy. Model *suggestions* are graded like claims; user corrections are the moat.

**Final state:** transactions carry categories/tags; "spending on groceries in March" answers with grade + provenance; corrections teach the system.

**Done criteria / tests:** a split across two categories still balances; a tag query aggregates across merchants; a user correction posts as an event and lifts grade to verified; spending excludes transfers (S3); re-upload preserves categorizations.

**Why now + future use:** first real advice (job 2); the correction stream **is** the moat + the eval/training signal; reuses correction + projection verbatim; feeds budgets (S10) and Viva's most-asked questions.

> _Forward note (from the first enrichment run, 2026-07-24): merchant-level categorization structurally can't reach **peer descriptors** (Zelle/Venmo) — one is a gift, another a loan repayment — and `is_shareable` rightly keeps them out of the commons. Their **local, per-transaction** categorization + **user-defined categories** (strictly local, never exported — T9) + a movement's **spending-vs-transfer nature** land with the **presentation-layer slice**, not here. The substrate already supports it (`CategoryAssigned` is movement-keyed and overrides the merchant prior); decisions captured in [local-categorization-and-custom-categories.md](local-categorization-and-custom-categories.md)._

---

## Slice 6 — Positions & investments  ✅ DONE (both stages)
**Block seeded:** Asset (valuation class) / Position (subtype + cost basis/lots).

_Delivered. **Stage 1 (holdings snapshot):** the `brokerage_statement` divergent profile (kind `INVESTMENT`, identity `Σ market_value + cash = total`); a `PositionObserved` measurement event (holdings recorded, never posted — Option A/M1); `post_brokerage` internal-tally gate; projection `positions()` / `account_value()` / `holdings_value()` / `unrealized_gain()` (the last a derived as-of view, never a ledger fact); surface + debug show total value and dated holdings. **Stage 2 (cross-account cash flow):** the statement's `activity` (contributions, withdrawals, dividends, interest, fees, buys, sells) posts as real cash movements reconciled by a cash-flow gate (`opening + Σ activity = closing`); contributions/withdrawals tie to the funding account via Slice-3 links (counted once, `_flow` now treats investment cash like a depository); dividends/interest → income, fees → expense, a sell's reported realized gain → `Income:CapitalGains`, buys/sells → `Assets:Investments`; **unrealized gain never posts — a presentation-only as-of derivation (M1)**. Prompt bumped to `brokerage-base-v2` (opening cash + activity). Tests (8) + arithmetic (3); full suite 269 green. As-built notes + known limitations in [positions-and-investments.md](positions-and-investments.md)._

**Full spec + locked architecture:** [positions-and-investments.md](positions-and-investments.md). Decision (Vishnu, 2026-07-24): **holdings are dated measurements, not postings** (Option A) — a `PositionObserved` event measures a holding at the statement date (like `ClosingBalanceObserved` measures a balance); only real cash flows post; **unrealized gain is the difference between measurements, never a fabricated transaction** (the thesis: measurements, not generations). New `INVESTMENT` account kind. The brokerage account is a **reconciliation hub, checked two ways**: an *internal tally* `Σ(market_value) + cash = total` (a hard, model-free gate) and a *cross-account flow* `opening + contributions + dividends + interest − fees ± realized ± unrealized = closing`, where contributions **tie to checking/savings via Slice-3 links** (counted once) and the gap is dividends/interest/fees/booked-gain/paper-change — a hard gate when the statement reports its components, a soft attribution otherwise (unrealized change is the only piece that never posts). The **valuation-class invariant** (`measured` only in S6, always shown with its as-of date, never "current"); cost basis a single graded figure now (per-lot deferred). Built in two stages (snapshot, then flow); net-worth composition stays in S7.

> _Note (from doc-type-registry design): brokerage is the first **divergent profile** — its own extraction schema + identity `positions×price + cash = total`. Because Slice 2 builds classify→profile→extract, this is a new profile + the Position primitive, not new plumbing._

**Open state:** brokerage/retirement holdings aren't modeled; a brokerage statement parks or only its cash reconciles; net worth can't include investments. *Proof:* positions query empty (red test).

**Implementation:** a Position primitive (units + instrument + value at statement date = a **measurement**, dated) with a **cost-basis/lots** attribute; a brokerage projector (positions + transactions + dividends + fees — the dense cross-check); a **valuation class** (measured / valued / estimated) so a statement value is never dressed as live. Asset generalization slot for property/vehicles seeded here with securities.

**Final state:** holdings modeled and valued as-of-statement; portfolio queryable; cost basis tracked; net worth can include investments, honestly dated.

**Done criteria / tests:** positions + cash reconcile to the statement total; a position carries units + value + date + class=measured; cost basis stored; dividends corroborate income (S4); a stale value is labeled "as of {date}," never "current."

**Why now + future use:** the biggest missing net-worth component; the valuation-class discipline is set here and **every future asset inherits it** (a trust-critical invariant against dressing guesses as facts); cost basis seeds Tax (S11); dividends reuse cross-doc corroboration.

---

## Slice 6.5 — Honest aggregates & the learning loop  ✅ DONE (Moves 1 & 2)
**Blocks seeded:** movement **nature** (derived) · the **question queue** (the learning loop's front door).

**Full spec + locked architecture:** [honest-aggregates-and-the-learning-loop.md](honest-aggregates-and-the-learning-loop.md). Added after the first full real-vault run: spending was computed as *money that left an account*, not *money that left your life* (M1). Transfer **links** excluded a movement; a *category* saying `transfers` did not — two descriptions of one fact, one aggregate listening to half of them. And a single category (`loan_payments`) covered two opposite natures (mortgage vs own-card payment), proving **category cannot decide nature**. Decisions: nature is **derived** (linked → counterparty is an own account → human ruling → category/subcategory as a *suggestion* → default `spending`); undecided evidence leaves a movement counted but **provisional**, with the aggregate reporting its own uncertainty (X2/principle 6) rather than guessing either way; the transfer auto-link bar is deliberately **not** loosened (a wrong link is a wrong number). Read-side only — no new event type, retroactive with no re-ingest. Also names the vision shape (Vishnu, 2026-07-25): the four ask-and-learn loops already built **are one primitive**, the questions Viva asks *are* the product, and the rulings are the moat — with the sequencing rule **abstract the read side early, the write side late** (question queue = Move 2; a generic `Ruling` event = Move 3, gated on a fifth question type).

---

## Slice 6.7 — The presentation layer  ✅ DONE
**Block seeded:** the surface as a first-class layer — the question queue as the page's spine.

**Full spec + rulings:** [the-presentation-layer.md](the-presentation-layer.md). Inserted because the engine had outrun the surface *measurably*: four endpoints the page never called (`/api/questions`, `/api/rule-nature`, and `/api/categorize` + `/api/assign-category` — dead since Slice 5) and seven overview fields ignored, including every position from Slice 6, Move 1's provisional/excluded honesty signals, and `other_holds`. Rulings (Vishnu, 2026-07-25): **hybrid answering** (one-tap inline, focused detail view when context is needed); **categories stay implicit** — the 16 primaries as suggestions, plus any you've used, plus add-your-own, with no `CategoryDefined` event (the named-but-unused wrinkle accepted as the signal for Move 3); **peer descriptors get per-transaction categorization** at last; **React + Vite** over a zero-dependency file split, for legibility to readers of a public repo and reliability of AI-written code — bounded by static build output served by the existing stdlib server, no runtime CDN, lockfile committed, and **zero new dependencies in `core/` or `product/`**.

---

---

## Slice 6.8 — Counterparty implications & the three tiers  ✅ DONE
**Blocks seeded:** an **implication** carried on a merchant record · the **tier** projection that decides who gets asked.

**Full spec + build record:** [where-the-intelligence-goes.md](where-the-intelligence-goes.md). Written after running 9a on a real vault and finding the machinery correct but *aimed at the wrong moment*: the answer was intelligent and the question was naive — asking "is this spent, or something you now own?" about a counterparty already enriched as `loan_payments / mortgage`. The inversion: **the product forms the belief, the person confirms it.** A merchant category *implies structure* (a mortgage servicer implies a property, a loan, escrow, a 1098), and that knowledge belongs in `merchantcore` at enrichment time — impersonal, batched, cached, commons-shareable — not in a per-sentence personal model call. Every movement sorts into **settled** (silence) · **structural** (an informed proposal) · **unknown** (a real question, one transaction at a time), reusing the forced/suggested ladder from verification findings. Also owns the drift that prompted it: **nine** raw-text keyword classifiers had accumulated against a stated anti-goal, four of them predating 9a — a reflex, not a slice.

**Naming note (2026-07-26):** this work was committed under the label *"Slice 9b"*, which collides with **9b — Viva speaks** below, reserved for the read direction. It is renamed **6.8**, where it belongs: it is the 6.x queue-and-aggregates family getting smarter, not Viva gaining a voice. Commit messages before 2026-07-26 still say 9b.

**Measured on real money (2026-07-26):** 15 counterparties carrying over half the vault's money moved from a naive question to a named proposal; the scoring of it is in [stocktake-2026-07.md](stocktake-2026-07.md), including three false "contradictions" the scorer invented and what that cost.

## Slice 7 — Net worth
**Block seeded:** Net-worth projection (compose assets − liabilities, bitemporal).

> _Note (from doc-type-registry design): liability netting (assets − liabilities) is a **projection over posted data — zero data impact**. Slice 2 shows cards as "owed"; net worth composes them here with no migration._

**Open state:** no single "what am I worth" figure; balances and positions live apart. *Proof:* net-worth query unsupported (red test).

**Implementation:** a projection summing depository + investment assets − liabilities (cards, loans), **per currency** (no FX faking), each figure carrying grade + as-of date; coverage-aware (states included/missing); bitemporal so "net worth as of date X" and "as I knew it on date Y" both work.

**Final state:** one honest net-worth figure per currency, with coverage and grade; a trend over time.

**Done criteria / tests:** net worth = Σ assets − Σ liabilities, only trustworthy grades summed, excluded accounts named; multi-currency reports per-currency (no conversion); a past-date recompute is correct; coverage states completeness.

**Why now + future use:** the headline peace-of-mind number (job 4); **pure projection composition, no new primitive** — the clearest lego payoff; bitemporal net worth is the direct precursor to the proof bundle (S13).

---

## Slice 8 — Obligations & proactive alerts
**Block seeded:** Obligation (bills/recurring) + Proactive trigger + Finding *reused*.

> _Note (from doc-type-registry design): card-specific fields (credit limit, minimum payment, due date) feed Obligations here. When needed, **bump the card profile version and targeted-re-read** only the affected statements (the claims layer records which profile version read each doc) via reingest — not a redesign._

**Open state:** bills/recurring aren't tracked; fees, duplicate subscriptions, anomalies pass silently; the system never volunteers. *Proof:* no obligations list; a fee posts unremarked (red test).

**Implementation:** an Obligation primitive (cadence + due rules from recurring detection); anomaly/fee/subscription detection as **Findings** (reuse); a proactive trigger deciding *when* to surface (persona: speak when it matters); completeness (expected-vs-seen) becomes a nudge.

**Final state:** bills and recurring charges tracked; fees, anomalies, unused/duplicate subscriptions surfaced; the first "volunteer insight."

**Done criteria / tests:** a recurring charge becomes an Obligation with cadence; a surprise fee / duplicate subscription raises a Finding; a missing expected statement is flagged; triggers respect a "speak when it matters" threshold (no noise).

**Why now + future use:** turns passive records into active help (job 2→3); reuses Finding + Obligation + completeness; the proactive-trigger block is exactly what Viva (S9) uses to volunteer — built just before her.

---

## Slice 9 — Viva, the conversational agent  ✂️ SPLIT (2026-07-25) into 9a ✅ / 9b

**Full research + design:** [viva-listens-and-speaks.md](viva-listens-and-speaks.md). The agent and the learning loop are **one engine, two directions**, and they carry different risk: a mis-parsed *ruling* persists and generalizes; a wrong *answer* misleads once. So this slice splits.

**Slice 9a — Viva listens.  ✅ BUILT 2026-07-25.** Answer a question in your own words: a model parses **intent** into a structured **Proposal** — never a figure, never arithmetic — you confirm, and deterministic code applies it through the writers that already exist. Needs no new tools; it is what the author feels the absence of today (a closed-option question cannot express a compound truth like a mortgage payment). Seeds the **Proposal** block, which turns `TransferSuggested`, model category suggestions, forced corrections, drafted budgets (S10) and eventual actions into instances of one thing — making X3 structural rather than remembered. Also forces the unwritten persona work (C1 uncertainty language, C3 when-to-speak).

**9a's concrete design:** [from-your-words-to-the-ledger.md](from-your-words-to-the-ledger.md). The ontology is settled — **four majors** (expense/asset/liability/income), equity derived not asserted, fixed top with a free hierarchy below — and the six-step toolset has exactly one model call, with account resolution reusing the Slice-1.5 matcher. Needs a `Liabilities:` root (absent today, which is why debt paydown is unsayable), general Asset accounts with valuation class, and `split_transaction` (built in v0, still unused — this is its first customer). Writing to the ledger is **9a's job**: the split is by direction of information, not by who writes.

**Slice 9b — Viva speaks (stays here).** The read direction: a tool registry (data, not code — the doc-type registry pattern again) plus a planner that composes answers from tool *results only*. Waits for a toolset worth asking (net worth, obligations).

**Decision recorded:** no agent-memory framework. Rulings are institutional knowledge, not preferences; the append-only, graded, deterministically-applied event log already avoids the staleness and trustworthy-retrieval problems those frameworks are benchmarking.

## Slice 9 (original entry) — Viva, the conversational agent
**Block seeded:** Agent/orchestrator (seed: 1 tool → grows) + Persona config + user-memory context.

**Open state:** interaction is fixed function calls / UI; no free-form questions; no voice. *Proof:* no NL entrypoint (red test).

**Implementation:** an orchestration loop — NL question → LLM plans tool calls over the deterministic tools from S1–S8 → LLM composes the answer in Viva's voice, surfacing grade + provenance, **never computing a figure** (ADR-010 / CaMeL); a persona config (voice, when-to-speak, uncertainty language); user operational memory as context; pluggable model (ModelSpec — user-keyed frontier now, local swap later); a quarantined powerless reader for prompt-injection safety.

**Final state:** you talk to Viva; she answers anything the tools cover — honestly, with sources, in her voice — and volunteers (via S8 triggers).

**Done criteria / tests:** NL questions map to the right tools and return grade+source; Viva hedges/refuses honestly on missing/conflicted data (measured by the eval harness's confidently-wrong rate); the model never emits an unverified number (tool-boundary test); a document prompt-injection can't make her act (CaMeL test); swapping the model changes phrasing, not answers.

**Why now + future use:** the soul; data-first pays off — she wires to a rich toolset with no new truth-logic; the tools-first invariant means **every later slice auto-extends her** for free.

---

## Slice 10 — Goals & budgets
**Block seeded:** Goal/Budget (target + progress projection).

**Open state:** can't set a budget or savings/payoff goal; no progress; no "take action." *Proof:* goals unsupported (red test).

**Implementation:** a Goal/Budget primitive (spend ≤ X on category; save Y by date; pay off Z) + a progress projection over spending (S5) / income (S4) / balances; Viva can draft budgets and payoff plans (job 3) — autonomous draft, asks before anything irreversible.

**Final state:** budgets and goals exist with live progress; Viva advises and drafts plans.

**Done criteria / tests:** a category budget tracks actual vs target from spending; a payoff/savings goal projects a date from cash flow; progress updates as statements post; Viva drafts on request but never acts irreversibly without a yes.

**Why now + future use:** job 3 (take action); composes spending + income + balances (no new engine); establishes the **graduated-autonomy pattern** (draft vs act) that all future actions inherit.

---

> _Coverage: the full instrument list — what's covered, what's missing, and what each gap blocks — is [document-coverage.md](document-coverage.md). Most of this slice is that list becoming registry rows._

> _Forward note (from the question queue's first real run, 2026-07-25): a mortgage payment is **compound** — interest, principal and escrow in one movement — so it cannot be answered by a single nature ruling and must be **split** (`split_transaction`, built in v0 and still unused). The ratios come from the loan statement or the 1098, which is why this lands here. Until then the queue must name such payments as compound and ask for the document rather than force a guess: [learning-mode.md](learning-mode.md)._

## Slice 11 — Loans, insurance, tax, FX (heavier domains — each its own smallest-seed sub-slice)
**Blocks seeded:** Loan/amortization · Provision (insurance/loan terms) · Tax (attribute + liability projection + cost basis + jurisdiction) · FX/currency.

**Open state:** a mortgage is a raw transaction stream (no principal/interest/payoff); insurance coverage isn't searchable; tax-relevance and estimated liability absent; multi-currency can't total or convert. *Proof:* mortgage doesn't amortize; "am I covered for X" unanswerable; tax view empty; INR+USD can't combine (red tests).

**Implementation:** Loan (amortization from terms-as-Provision; escrow split; payoff projection); Provision (attested non-numeric coverage/terms, searchable, graded); Tax (tax-relevant Tag + cost-basis cap-gains + estimated-liability projection with cited jurisdiction rules); FX (answer-time conversion, cited + dated rate, converted totals labeled "estimate"). Each ships via its smallest seed — one loan, one policy, one tax doc, one currency pair.

**Final state:** loans amortize and project payoff; insurance/loan terms searchable; tax liability estimable with cited rules; cross-currency reported honestly.

**Done criteria / tests:** a mortgage payment splits principal/interest/escrow and projects a payoff date; "what's my deductible for X" answers from a Provision with source; estimated tax uses cited jurisdiction rules; an FX-converted total is labeled an estimate with rate + date.

**Why now + future use:** completes consolidation of a full financial life; each reuses existing blocks + one new primitive (the smallest-seed discipline); Provision proves the model isn't secretly transaction-shaped; Tax + cost basis + jurisdiction are prerequisites for real advice and for the US+India reality.

---

## Slice 12 — Trust hardening
**Blocks seeded:** Anchoring (chain head → trusted timestamp/transparency log) + Issuer signatures / verifiable credentials.

**Open state:** the hash chain proves internal tamper-evidence but anchors to no external time; authenticity relies on the model reading, not the issuer attesting. *Proof:* no external anchor; a signed statement's signature isn't verified (red test).

**Implementation:** periodically anchor the chain head to a trusted timestamp / transparency log — **signatures + timestamp, no blockchain** (our honest stance); where issuers provide signed docs (verifiable credentials), verify the signature → authenticity **without inference** (grade jumps to issuer-attested). No token, no chain.

**Final state:** the ledger is tamper-evident *to third parties* and time-anchored; issuer-signed facts are authenticated at source.

**Done criteria / tests:** the chain head anchors and the anchor verifies independently; a signed statement's signature validates and lifts its grade; an outside party can detect tampering given only the anchor.

**Why now + future use:** makes facts **provable to others** — the precondition for the endgame (S13); reuses event + provenance + grade; holds the "signatures not blockchain" line from discovery.

---

## Slice 13 — Creditworthiness + selective disclosure (endgame seed)
**Blocks seeded:** Creditworthiness projection + Selective-disclosure proof bundle.

**Open state:** your data can't vouch for you; a counterparty can't verify a claim without seeing everything; no proof export. *Proof:* no proof bundle; can't answer a counterparty without full disclosure (red test).

**Implementation:** a creditworthiness projection (grade + provenance + payment history + net worth, bitemporal); a proof bundle disclosing a single graded claim — "balance ≥ X as of date," "on-time payments ≥ N" — with its provenance + anchor, revealing nothing more (selective disclosure; ZK later). Smallest seed: export one signed, verifiable claim.

**Final state:** you can prove a specific financial claim to a counterparty, holding your own keys, revealing only what's needed — the user-owned credit-bureau alternative, in miniature.

**Done criteria / tests:** a proof bundle for "balance ≥ X as of date" verifies against the anchor + issuer signatures without exposing other data; the claim carries its grade; a third party validates it offline; nothing beyond the claim leaks.

**Why now + future use:** **the vision realized in seed form** (agent-to-agent trust); composes literally every block; everything prior built toward this — and it starts as one exportable claim, then grows to agent-to-agent negotiation with ZK.

---

## Slice 14 — Household/scope + Sync (later modes)
**Blocks seeded:** Scope/Household lens (Party + whose-money view) + Sync (blind-relay encrypted).

**Open state:** single-user, single-device; no shared view; no multi-device. *Proof:* can't scope to a household member's account or sync to a phone (red test).

**Implementation:** a Scope lens (Party-based filtering: individual / joint / household; multi-party data, user still holds keys); Sync (encrypted vault export/import → blind relay; documents stay put, the ledger follows). Smallest seeds: one household member's account visible; one manual encrypted export/import.

**Final state:** optional household view; the vault follows you across devices without decryptable data leaving your control.

**Done criteria / tests:** a joint account attributes to the right parties; a household total scopes correctly; an encrypted vault round-trips across devices with no plaintext exposure; keys never leave the user.

**Why now + future use:** last because it's a *mode*, not a foundation; Party existed from day one so this doesn't reshape the schema (design paid off); sync respects the zero-exfiltration invariant (blind relay only).

---

## The stack, end to end

v0 gave one honest answer. S1–S8 consolidate a whole financial life on the reused blocks
(plus a few smallest-seed primitives). S9 gives it a voice. S10–S11 let it advise and act across
every domain. S12–S13 make its facts provable to others — the credit-bureau alternative. S14
opens it to household and multi-device. Every slice is the same small set of lego blocks,
re-composed — and the trust signal (grade + provenance + bitemporality) rides all of them from
v0 to the endgame.
