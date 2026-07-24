# Pay Stubs & Income — the first divergent document, and decomposing a deposit

**Status:** Implemented (Slice 4, core) · **Last updated:** 2026-07-24 · **Origin:** Slices 2–3 only ever handled the *balance family* — checking, savings, card — which all share one shape, `opening + Σ = closing`. A pay stub is the first genuinely different document: its identity is `gross − deductions = net`, with no opening, closing, or running balance. It is where the doc-type registry's central claim — that a new type with its own shape *and its own verification formula* is **data, not new plumbing** — gets its first real test. It also completes half the picture: Slice 3 made spending honest; income is the other side.

**Invariants touched:** T1 (every posting cites the pay stub and carries a grade), T2 (the `gross − deductions = net` identity is deterministic; the model never certifies), T4 (the decomposition and any correction are append-only events), I1 (pay is `(value, currency)`, never a bare number), I5 (deductions are sorted into **universal buckets** with jurisdiction as data — 401k = EPF = ISA — never a US-shaped table), X2 (a model-proposed deduction category is a *graded* claim, visibly unconfirmed). Principle 2 (a pay stub that doesn't balance is **held**, never guessed) and principle 7 (the safe decomposition is automatic; the uncertain category waits) are load-bearing.

## The architecture (decisions locked with Vishnu, 2026-07-24)

**1. The pay stub is the first *divergent profile*.** It carries its own extraction shape (gross, net, deductions, employer, pay period) and its own identity (`gross − deductions = net`), both selected by its registry profile — exactly the seam Slice 2 built and Slices 2–3 never had to exercise, because the balance family shared one shape. Building this proves the registry generalizes past balances, and turns "add a new document type" from a code change into a profile.

**2. Decompose the deposit — a pay stub *explains* a deposit, it doesn't invent a parallel number.** Your checking statement already posts the net-pay direct deposit (today as uncategorized income). The pay stub says: that deposit was the *net* of a larger gross, and here is where the rest went. So the pay stub books the gross as income and allocates it — the net corroborates and links to the checking deposit (reusing Slice 3's cross-document link, so the same money is **never counted twice**), and the withheld parts become their own legs. It works in either arrival order (Slice 1 spirit): whichever of {pay stub, deposit} lands second triggers the link/heal.

**3. Income is not one shape — a pay stub is not a 1099.** A W-2 pay stub is *per-period*, has a *deduction identity*, and decomposes *one* deposit. A 1099 is an *annual total*, usually has *no deductions* (so no `gross − deductions = net` to check), and its money arrived as *many* deposits — so a 1099's relationship to the ledger is a **completeness check** ("do my deposits from this payer sum to the total they report?"), not a decomposition. Our own data-model spike already flagged 1099/1098 as "a distinct shape — a fact bundle, not transactions." So we deliberately do **not** build a generic "income" abstraction that assumes decomposition; the pay stub is its own profile, and the 1099 becomes a *separate sibling profile* later. Two income types coexist, neither bent to fit the other — which is the whole point of the registry.

**4. Deductions go into universal buckets, never a US-shaped table (I5).** The model extracts each deduction's label as printed *and* proposes a category — **tax / retirement / insurance / other** — as a graded suggestion (its world knowledge, graded like any claim, unconfirmed until a human rules). We post to a bucket by that proposed category; jurisdiction is an attribute, so a US 401k, an Indian EPF, and a UK ISA land in the same *retirement* bucket without a per-country table. Retirement deductions are recognized as *not spending*, but composing them into a retirement **asset** and net worth is deferred (see notes).

**5. Core scope.** In: ingest a pay stub, verify `gross − deductions = net`, recognize income, corroborate/link the net with the checking deposit, and sort deductions into universal buckets. Out (noted as siblings): 1099 and other annual tax docs; recurring-salary detection → an Obligation; 401k-as-retirement-asset; the full employer Party graph.

## The pipeline generalization (this is the engineering of the slice)

Today the ingest path is balance-shaped end to end: one `StatementFacts`, one reconciliation gate, one post path. Slice 4 generalizes it along the seam the registry already defines:

- **Profile selects the shape and the handler.** A `DocProfile` grows to name its *facts shape*, its *identity*, and its *post-projector*. The balance family keeps `identity="balance"`; the pay stub is `identity="paystub"`. `can_project` becomes "is there a projector for this type", and a dispatch on the profile routes to the right parser + verify + post.
- **The reader dispatches after classify.** Classification already picks the profile (Slice 2's two-phase read); now the profile also picks the *extraction prompt* **and** the *facts parser* (`from_model_json` for a statement, `from_paystub_json` for a pay stub). No balance assumptions leak into a pay-stub read.
- **The gate is per-type.** `check_balance_identity` gains a sibling `check_paystub_identity` (`gross − Σ deductions = net`). The finding contract (forced / suggested / unlocalized) is unchanged — a deduction off by the gap localizes the same way a transaction does.

The payoff: every later divergent type — brokerage (`positions × price + cash = total`), 1099 (box sums), insurance (provisions) — is a new profile that plugs its shape and identity into this same dispatch, not a new pipeline.

## The facts shape

`PayStubFacts`: employer (an identity signal, like an institution), employee name(s), pay date, period start/end, currency, `gross`, `net`, and `deductions[]` — each `{label (as printed), amount, category ∈ {tax, retirement, insurance, other}}` where `category` is the model's graded proposal. (Employer contributions such as a 401k match are captured but not posted in Core — they are a separate flow, deferred with the retirement asset.)

## The identity, and posting the decomposition

**Identity (deterministic gate):** `gross − Σ(deductions) = net`. If it doesn't hold to the cent, the pay stub is *held* — the model misread a line, and the same cheap-first diagnosis localizes which one. Never posted on a guess (principle 2).

**Posting (decompose + link):** the pay stub books income and allocates it — gross recognized as income, each deduction posted to its universal bucket (graded by the model's proposed category, `unverified` until confirmed), and the net as the leg that represents money arriving in checking. That net leg **corroborates and links to the checking deposit** via Slice 3's cross-document mechanism, which is where the double-count of the net is resolved: the deposit and the pay stub's net are recognized as the same money. Every leg carries the pay stub as provenance and a grade (the employer-attested figures `verified`; a model-proposed category `unverified` until a human confirms). The exact leg mechanics (a clearing leg linked to the deposit, vs. reclassifying the deposit's uncategorized-income leg) are a build-time choice; the invariants are fixed: **income recognized once, net counted once, order-independent, provenance + grade on every leg.**

If no matching deposit is present yet, income is still recognized from the pay stub itself, and the net stands as an *expected* deposit until its statement arrives (the same one-sided shape as an unmatched transfer) — then it heals.

## Implementation status (as built, 2026-07-24) — audit vs the invariants

Core built and tested (`vivacore.verify.check_paystub_identity`,
`ingest/paystub.py`, `registry` pay-stub profile, `prompt_library` classify-v2 +
paystub prompts, `reader` parser dispatch, `pipeline.post_paystub` /
`heal_paystubs`, `ledger.postings.paystub_decomposition`,
`projection.income_by_currency`):

- ✅ **Divergent profile, as data (the registry claim).** `pay_stub` is a profile
  with `identity="paystub"`; `can_project` generalized to a set of projectable
  identities; the reader dispatches after classify to `from_paystub_json`, and
  the pipeline dispatches on `profile.identity` to `post_paystub`. A synthetic
  different-shaped type is a registry row, proven by test. The balance family is
  untouched (its tests stay green).
- ✅ **T2 — deterministic identity.** `gross − Σ deductions = net`, run by the
  universal gate; the model never certifies. Failure → held with a localized
  finding (a deduction off by the gap → suggested), same contract as a statement.
- ✅ **Decompose the deposit; income counted once.** `paystub_decomposition`
  books gross to `Income:Salary`, cancels the deposit's `Income:Uncategorized`
  placeholder for the net, and posts deductions — legs sum to zero. The checking
  inflow is untouched; income reflects gross. Order-independent: a pay stub with
  no deposit yet is held `awaiting_deposit` and `heal_paystubs` posts it when the
  deposit lands.
- ✅ **I5 — universal buckets.** Deductions post to `Expenses:Tax` /
  `Assets:Retirement` / `Expenses:Insurance` / `Expenses:Other` by the model's
  proposed category (X2 — graded `unverified`), jurisdiction as data; retirement
  is an asset, not spending.
- ✅ **T1/T4** — every leg cites the pay stub and carries a grade; the hold, the
  decomposition, and any correction are append-only events.

Honest edges (noted, not built):

- ⏳ **The net↔deposit link is by amount+date, not yet an explicit provenance
  link.** The decomposition cancels the shared `Income:Uncategorized` bucket by
  the net; it does not yet attach a provenance edge to the *specific* deposit
  (that, and reclassifying an already-categorized deposit once Slice 5 exists,
  are the next increment). Correct for totals today; less precise for tap-through.
- ⏳ **Pay-stub correction actions.** Income and a withheld breakdown now show on
  the dashboard, and held/awaiting pay stubs render in a "pay stubs in progress"
  card (`/api/paystubs`). What's not yet wired is a *correction action* for a
  mis-balanced stub (the pay-stub equivalent of confirming a statement figure) —
  it's shown with its finding but read-only; the HITL correction path for the
  pay-stub shape is a later increment.
- ⏳ **Deferred by scope:** recurring→Obligation (S8), 401k employer match +
  retirement-asset composition into net worth (S6), employer as a first-class
  Party (S5), 1099 as a sibling profile (tax slice).

### Real-data finding (2026-07-24) — the Uncategorized buckets have the wrong sign for liabilities

Running Slice 4 on the author's real vault (32 documents, 5 pay stubs) surfaced a
bug that unit tests missed and that reconciliation cannot catch, because it does
not affect the account legs that verify: **the `Uncategorized` counter-leg is
categorized by the sign of the account leg, which is asset-centric and inverted
for a liability.** A card *purchase* raises what's owed (a positive leg), so its
counter-leg files under `Income:Uncategorized` — a purchase booked as if it were
income; a card *payment* files under `Expenses:Uncategorized`. Every statement
still posts and reconciles (the liability's own balance is correct), but any
income-or-spending **total** built on those buckets is polluted.

Immediate correction (folded into Slice 4): `income_by_currency` now reports only
**recognized** income (`Income:Salary`), never the `Income:Uncategorized`
placeholder, and the spending answer is relabeled as *outflow from deposit
accounts* (own-account transfers excluded) — not "total spending" — because card
purchases aren't attributed yet. We report what we can stand behind (principle 2)
and no more.

Root fix belongs to **Slice 5 (categorization):** its first job is to make the
counter-leg **kind-aware** (a liability's purchase is an expense, its payment a
liability reduction), after which income and spending totals become trustworthy.
A good build-in-public lesson: reconciliation guards the figures a document
states; it does not guard the *interpretation* we layer on top — that needs its
own slice, and real data is what exposed the gap.

## Notes for future slices (read these when you build them)

- **1099 / annual tax docs (later, tax slice):** a *sibling* income profile, not a subtype of the pay stub. Identity is a **completeness check** (`Σ deposits from this payer ≈ reported total`) across many deposits, not a decomposition of one. Reuses the cross-document corroboration and the "documents are evidence other documents exist" idea. Do not force it through the pay-stub shape.
- **Slice 8 (obligations):** recurring-salary detection (a biweekly/monthly cadence from the same employer) seeds an inbound **Obligation** (expected pay). The employer identity and pay dates captured here are the inputs; the Obligation primitive is built there.
- **Slice 6 (positions / assets):** a retirement deduction (401k/EPF) is money that moved into a retirement **asset**. Core buckets it as *retirement* (so it is not miscounted as spending); composing it into a retirement balance and net worth — plus the employer match — lands with the asset primitive.
- **Slice 5 (categorization + Party):** the employer becomes a first-class **Party** (the same entity-resolution block as accounts and merchants), and deduction categories graduate from model-proposed to learned-and-confirmed.

---

## Slice 4 — Pay stub + income

**Block(s) seeded:** the **divergent-profile pattern** (a document type with its own facts shape + identity + post-projector, selected by the registry) and **Income** (gross recognized, decomposed into net + deductions). Reuses cross-document corroboration, `split`-style multi-leg postings, grade + provenance, the finding contract, and the heal pass.

**Open state:** the pipeline can only read balance-shaped statements; a pay stub classifies but parks, and a net-pay deposit sits in checking as undifferentiated income — the tax, retirement, and insurance that never touched the account are invisible, and income is not recognized as such. *Proofs (red tests):* a real pay stub parks (no projector for its shape); a checking deposit that is net pay is categorized only as "uncategorized income", with no gross or deductions anywhere.

**Implementation:**
- Registry profile grows to carry facts-shape + identity + post-projector; `pay_stub` registered with `identity="paystub"`. `can_project` generalizes to "has a projector"; ingest dispatches on the profile.
- Reader dispatches after classify to the pay-stub extraction prompt (new `prompt_library` entries) and a `from_paystub_json` parser → `PayStubFacts`.
- A deterministic `check_paystub_identity` (`gross − Σ deductions = net`); failure → held, with the same forced/suggested/unlocalized diagnosis.
- Post the decomposition: gross → income, deductions → universal buckets (graded by model-proposed category), net → a leg corroborated and linked to the checking deposit (Slice 3 reuse); no double-count; order-independent via the heal pass.
- Answer/surface: income is recognized and answerable; a pay stub's deductions are visible; the net-pay link shows the deposit is explained.

**Final state:** a pay stub posts and reconciles on `gross − deductions = net`; its net links to the matching checking deposit so income is counted once; withheld tax/retirement/insurance are recorded in universal buckets and no longer invisible; a pay stub that doesn't balance is held, not guessed; a new *income* document of a different shape (a 1099) can be added later as its own profile without touching this one.

**Done criteria / tests:**
- A real pay stub reconciles on `gross − deductions = net` and posts; one with a misread deduction is held with a localized finding.
- The net links to the checking deposit (in either ingest order), and total income is counted **once** (no double-count with the bank's deposit).
- Deductions land in universal buckets (tax/retirement/insurance/other) from the model's graded proposal; a retirement deduction is **not** counted as spending.
- Registering a synthetic *different-shaped* type via a profile row alone (no dispatch-code change) routes to its own parser/gate — proving the divergent-profile generalization.
- Existing balance-family tests stay green (the generalization is behavior-preserving for statements).

**Why now + future use:** it proves the registry generalizes beyond the balance family — the first divergent shape and identity as data — which every later type (brokerage, tax, insurance) inherits. It recognizes **income**, the missing half of the financial picture, and it does so by *reusing* Slice 3's cross-document corroboration (net ↔ deposit) rather than inventing new plumbing — another composition proof. And it seeds the Party (employer) and Obligation (recurring pay) threads that Slices 5 and 8 pick up.
