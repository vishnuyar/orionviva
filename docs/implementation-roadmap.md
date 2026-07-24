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

## Slice 3 — Transfer links
**Block seeded:** Transfer link (two postings = one economic non-event), graded.

**Open state:** a checking→card payment counts as spending on checking *and* a payment on the card — money seems to leave twice; spending double-counts. *Proof:* summed cross-account outflow overstates real spending by the transfer amount (red test).

**Implementation:** detect candidate transfers (amount/date proximity + description hints across accounts); create a Transfer-link entity with its own grade + evidence; net the two legs so aggregates don't double-count. Ambiguous links surface as **Findings**; confirmation is **correction-as-event** → verified.

**Final state:** internal transfers are recognized and netted; "how much did I spend" excludes moving your own money; wrong links are surfaced, not silently applied.

**Done criteria / tests:** a checking→card payment is linked and excluded from spending; total spending = real external outflow; an ambiguous link surfaces for confirmation; a confirmed link is verified and persists.

**Why now + future use:** without it, spending (S5) and cash flow are simply wrong — load-bearing for job-1 accuracy; it's the first cross-account fact, seeding the operational graph; reuses Finding + correction (composition proof).

---

## Slice 4 — Pay stub + income
**Block seeded:** pay-stub projector (registry) + Obligation *inbound* (recurring income) + cross-document corroboration seed.

**Open state:** income isn't modeled; a pay stub parks; salary isn't recognized; cash flow has no inflow side. *Proof:* pay stub parks; no income in any view (red test).

**Implementation:** pay-stub identity *gross − deductions = net*; each deduction a fact (tax, 401k, insurance) — some *also* other facts (401k → a retirement observation); recurring detection → an inbound **Obligation** (expected salary cadence); the net deposit corroborates the checking deposit (transfer-link / cross-doc reuse).

**Final state:** income modeled; salary a recognized recurring inflow; deductions itemized; net-pay deposit corroborates checking.

**Done criteria / tests:** a pay stub reconciles (gross−deductions=net); the net deposit matches a checking transaction (cross-doc → higher grade); recurring salary detected as an Obligation; a deduction (401k) stored ready to corroborate a retirement statement.

**Why now + future use:** income is half of cash flow (needed for budgets/goals S10); the deduction facts seed the first **two-doc-corroborates-one-fact** test; recurring-income reuses the bills primitive inbound.

---

## Slice 5 — Categorization & spending
**Block seeded:** Tag/Category (many-to-many overlay) + amount-split (double-entry) + spending projection + correction-as-event.

**Open state:** every non-checking leg is "Uncategorized"; "where did my money go?" is unanswerable. *Proof:* spending-by-category returns all-Uncategorized (red test).

**Implementation:** the two mechanisms — `split_transaction` (amount across categories) + a `tags` overlay; a spending projection (by category/tag/merchant/time); categorization via **correction-as-event** (user or model assigns; grade rises on confirmation); a minimal, aggressively-overridable seed taxonomy. Model *suggestions* are graded like claims; user corrections are the moat.

**Final state:** transactions carry categories/tags; "spending on groceries in March" answers with grade + provenance; corrections teach the system.

**Done criteria / tests:** a split across two categories still balances; a tag query aggregates across merchants; a user correction posts as an event and lifts grade to verified; spending excludes transfers (S3); re-upload preserves categorizations.

**Why now + future use:** first real advice (job 2); the correction stream **is** the moat + the eval/training signal; reuses correction + projection verbatim; feeds budgets (S10) and Viva's most-asked questions.

---

## Slice 6 — Positions & investments
**Block seeded:** Asset (valuation class) / Position (subtype + cost basis/lots).

> _Note (from doc-type-registry design): brokerage is the first **divergent profile** — its own extraction schema + identity `positions×price + cash = total`. Because Slice 2 builds classify→profile→extract, this is a new profile + the Position primitive, not new plumbing._

**Open state:** brokerage/retirement holdings aren't modeled; a brokerage statement parks or only its cash reconciles; net worth can't include investments. *Proof:* positions query empty (red test).

**Implementation:** a Position primitive (units + instrument + value at statement date = a **measurement**, dated) with a **cost-basis/lots** attribute; a brokerage projector (positions + transactions + dividends + fees — the dense cross-check); a **valuation class** (measured / valued / estimated) so a statement value is never dressed as live. Asset generalization slot for property/vehicles seeded here with securities.

**Final state:** holdings modeled and valued as-of-statement; portfolio queryable; cost basis tracked; net worth can include investments, honestly dated.

**Done criteria / tests:** positions + cash reconcile to the statement total; a position carries units + value + date + class=measured; cost basis stored; dividends corroborate income (S4); a stale value is labeled "as of {date}," never "current."

**Why now + future use:** the biggest missing net-worth component; the valuation-class discipline is set here and **every future asset inherits it** (a trust-critical invariant against dressing guesses as facts); cost basis seeds Tax (S11); dividends reuse cross-doc corroboration.

---

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

## Slice 9 — Viva, the conversational agent
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
