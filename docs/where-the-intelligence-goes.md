# Where the Intelligence Goes

**Status:** ✅ **BUILT 2026-07-25** — all six steps; see *What the build showed* at the end · **Created:** 2026-07-25 · **Origin:** Vishnu, after using Slice 9a on his own vault: *"any merchant we have by enrichment we already get category and subcategory, they should be assigned by default… it is only when we get categories under zelle or checks that we should ask… we are thinking about a financial AI agent, which means it has intelligence… it is ok to be a rule maker, but to the user it should feel like intelligence."*

**Invariants touched:** **T2 / ADR-010** (a model may perceive and infer; deterministic code decides and posts) · T4 (everything new is an event) · **T9** (the impersonal/personal boundary — this doc leans on it hard) · X2 (a proposal states its confidence and what it does not know) · X3 (nothing irreversible without a yes) · **I5** (code universal, specifics are data) · principle 5 (serve, don't overwhelm).

---

## The diagnosis

Slice 9a works and is aimed at the wrong moment.

**It made the *answer* intelligent and left the *question* stupid.** The queue asks *"Is this money spent, or is it something you now own?"* about a counterparty the vault has **already enriched as `loan_payments / mortgage`.* We knew it was a mortgage servicer. We asked anyway. Then a model was spent interpreting a sentence whose content we could have proposed ourselves.

Three costs follow, and they compound:

1. **The person carries load we could have carried.** Being asked what you already told the system — or what any competent reader would infer from the counterparty's name — is the opposite of a butler.
2. **The model call happens at the point of least leverage.** One sentence, one merchant, one person, uncacheable, unshareable, repeated forever. The same reasoning done once per *merchant category* would serve every transaction, every future transaction, and every other user.
3. **It reads as unintelligent even when it is correct.** *"Is that money spent — or is it something you now own?"* about `Harborline-Servi` is a question a person would not ask, because a person would already have a hypothesis.

The correct shape is the inverse: **the product forms the belief; the person confirms or corrects it.**

### And a self-inflicted one

While building 9a I wrote **five separate keyword tables** — `_TRANSFER_HINT_CATEGORIES`, `suggest_answers`'s substring matching, `CORROBORATION`, `_group_for`, `_CONDUIT_MARKERS`. The project's own anti-goals say: *"No per-institution parsers or a keyword classification engine; that whole class of workaround is obsolete."* Each felt local and reasonable. Together they are exactly the engine we said we would not build, and they are why the product feels like a rule-follower rather than a reader. That drift is the thing to correct, not just the question ordering.

---

## The missing idea: a merchant category *implies structure*

Today `merchantcore` answers **"what kind of business is this?"** → `loan_payments / mortgage`. The ledger then uses that only as a *weak hint* for nature (rung 4, provisional) and as a display label.

But `mortgage servicing` is not a weak hint about spending. It is a **near-certain statement about the shape of this person's financial life**: there is a property, there is a loan, the payment is compound, an escrow account probably exists, and a 1098 exists once a year. None of that is uncertain. What *is* uncertain is narrower and much more answerable: *which* property, and whether they want it tracked.

So the missing layer answers a different question:

> **What does having this counterparty in your life imply about your financial structure?**

Most categories imply **nothing**: groceries, utilities, restaurants, streaming. Those should be assigned silently and never asked about — which is most transactions. A minority imply a **relationship**, and that minority is where every question worth asking lives.

| Counterparty category | What it implies | Direction matters |
|---|---|---|
| mortgage servicing | a property, a home loan, escrow, an annual 1098 | out → compound payment |
| brokerage / investment | an investment account | out = contribution (asset); in = withdrawal *or* distribution (income) |
| auto lending | a car loan, probably a vehicle | out → debt paydown + interest |
| consumer lending | a loan | **in = you borrowed; out = you repaid** |
| property management | rent | out = expense (tenant); in = income (landlord) |
| insurance | a policy, and often an asset being insured | out → expense; in → a claim (income) |
| title / escrow company | a property transaction | a one-off, high-stakes, document-implying |
| groceries, utilities, dining, retail | nothing | — |

**Direction is part of the implication, not a separate rule.** Vishnu's example is the clean case: money *in* from a lender asks *"was this a loan?"*; money *out* asks *"do you have a loan outstanding?"* Same counterparty, opposite sign, different question. That must be data on the implication, never an `if` in the queue.

### Where this knowledge belongs — and why the answer is obvious

*"Mortgage servicers imply a property and a loan"* is **impersonal, universal, and true for everyone.** It carries no amount, no date, no account, no name.

So it belongs in **`merchantcore`, produced during enrichment, cached in the catalog, and eventually shared in the commons** — beside category and subcategory, under the same T9 boundary that already governs them. That single placement decision resolves almost everything:

- the model call is **batched** (40 merchants per call, machinery that already exists),
- **impersonal** (T9-safe by construction, nothing about this person crosses),
- **cached forever** (a merchant is enriched once, not once per transaction),
- **versioned** (the enrichment prompt is already in the library),
- **retroactive** (it arrives as `MerchantEnriched`, and the read side re-derives),
- and **shareable** — this is precisely the commons the project has been building toward. *"Mortgage servicers imply a home loan"* is knowledge every user benefits from and no user's privacy is spent on.

Compare with where 9a put it: one personal call, per sentence, uncacheable, unshareable. **Same reasoning, wrong side of the boundary.**

> **Industry note.** Enrichment vendors already infer "financial products held with other institutions" from transaction data — and sell it to banks for cross-sell ([Open Banking Tracker](https://www.openbankingtracker.com/embedded-finance/category/transaction-enrichment), [Personetics](https://personetics.com/products/enrich/)). The capability is proven; the *direction* is what differs. They infer your products to market to you. Here the same inference describes you to yourself, on your machine, with the derived knowledge shared only in its impersonal form. Worth stating plainly in the build log: **we are not inventing the inference, we are inverting who it serves.**

---

## The three tiers

Everything reduces to one rule — **ask only where the counterparty genuinely cannot tell us** — which sorts every movement into three tiers.

### Tier 1 — Known, and implies nothing → **silence**

Enriched merchant, ordinary category. **Assign the category and the major automatically.** Never raise a question. This is the large majority of transactions and today we ask about them, which is the single biggest fix in this document.

*Groceries at a supermarket is an expense. There was never a question here.*

### Tier 2 — Known, and implies structure → **an informed proposal, not a question**

The counterparty tells us what kind of relationship this is. We do **not** ask what it is. We say what we believe, name what we are unsure of, and offer the specific choices:

> *"These 13 payments go to a mortgage servicer. That normally means a home loan — usually split between interest, principal and escrow, which I can't separate without your statement. Shall I set up the loan? (Do you also want me to track the property?)"*

Options composed from the implication; the person taps one, or writes a sentence. **This is where "feels like intelligence" is actually earned** — the product arrives already knowing something, and asks a narrow, expert question instead of a naive open one.

### Tier 3 — Genuinely unknown → **a real question, per transaction**

Conduits (check, ATM, wire, teller, money order) and peers (Zelle, Venmo, a person's name). The descriptor names the *pipe*, not the payee, so no amount of enrichment will ever help. One question per transaction, free text first-class.

**This is the only tier where Slice 9a's machinery was pointed at the right target** — and it is where the earnest-money-vs-account-opening failure lives.

---

## The confidence ladder — reuse, don't invent

How decisively an implication is applied should use the contract the project already has for verification findings ([verification-findings-and-correction.md](verification-findings-and-correction.md)): **forced / suggested / unlocalized.**

| Rung | When | Behaviour |
|---|---|---|
| **forced** | the implication is decisive and unambiguous (a supermarket is an expense; a card payment reduces that card) | **apply, and report that you did.** Never silent, never asked. |
| **suggested** | the implication is strong but the specifics aren't (a mortgage servicer — but which property?) | **propose with options.** One tap, or a sentence. |
| **unlocalized** | nothing implies anything (a check, an ATM withdrawal) | **ask openly.** Free text is the primary channel. |

Three benefits from reuse rather than a new vocabulary: it is already tested, already understood, and it keeps *"never bluff"* structural — a forced application is one we can defend, a suggestion states its own doubt, and an open question admits we don't know.

---

## Where it sits in the flow

```
document → classify → extract → verify → post                    [unchanged]
                                            ↓
                                       movements
                                            ↓
                    normalize descriptor → merchant key           [deterministic]
                                            ↓
  ┌────────────────────────────────────────────────────────────────────┐
  │  merchantcore ENRICH   — batched · impersonal · cached · versioned │
  │  in :  normalized merchant + one linted example                    │
  │  out:  category, subcategory                                       │
  │      + nature_of_counterparty: business | instrument | peer        │
  │      + implies: [ { relationship, major, on_inflow, on_outflow,    │
  │                     account_shape, confidence, documents } ]       │
  └────────────────────────────────────────────────────────────────────┘
                                            ↓
                        MerchantEnriched  (event — exists already)
                                            ↓
  ┌────────────────────────────────────────────────────────────────────┐
  │  DERIVE   — read side · deterministic · retroactive · free         │
  │   • category → every transaction, automatically       (Tier 1)     │
  │   • implication × direction → proposed major + account             │
  │   • existing accounts matched by the Slice-1.5 matcher             │
  │   • confidence → forced | suggested | unlocalized                  │
  └────────────────────────────────────────────────────────────────────┘
                                            ↓
              questions raised ONLY for `suggested` and `unlocalized`
```

**Note what is absent: a second personal model call.** The impersonal step already did the thinking; turning an implication into this person's options is *matching against their account registry*, which is Slice 1.5's matcher pointed at yet another target. Deterministic, free, offline, testable.

That is the answer to *"send it to a model call saying I have this, what could it be"* — **yes, but once per merchant category rather than once per person per transaction.** Same intelligence, ~1000× less of it, and it becomes an asset instead of a cost.

`nature_of_counterparty` also **replaces `_CONDUIT_MARKERS`**: whether "check" names an instrument rather than a business is exactly the kind of universal a model should tell us and a keyword list should not.

---

## Rules vs intelligence — the reconciliation

> *"It is ok to be a rule maker, but to the user it should feel like intelligence."* (Vishnu)

The resolution is a distinction the project already uses elsewhere and lost sight of here:

**A model writes the rules. Deterministic code applies them.**

- Nobody codes `mortgage → house`. A model, reading a merchant category, produces the implication — from world knowledge, generally, for categories nobody anticipated.
- The implication is **stored as data**, versioned, correctable.
- Applying it is **deterministic**: auditable, free, offline, unit-testable, and incapable of inventing a number.

This is the same stance as *"we own the schema, the model assists authoring"* (Slice 2) and *"read documents like a person would — no per-institution parsers"* (a founding anti-goal). A hardcoded table is a rule *we* wrote and will be wrong about; a learned implication is a rule *the world* wrote that we can check, cache and share.

**And a person's correction beats both, permanently** — which is the moat: *"memory of the user is the moat, not the model."*

---

## What survives from 9a, and what changes

**Keep — all of it earned its place:**

- `RulingRecorded` (generic, scoped) — the write-side spine for every tier.
- The **four majors** and the derived chart of accounts.
- **`origin: issued | asserted`** (A3) and the corroboration ladder.
- **`MIXED` / `undecomposed()`** — honest handling of an unknown split.
- **Conduits are per-transaction** — correct, though the *detection* should move to enrichment.
- The **Proposal** type, the eval harness, and the failure taxonomy.

**Change:**

- **The entry point.** 9a assumed the person opens with a sentence. The product should open with a belief; the sentence becomes the correction channel and the Tier-3 primary.
- **The model call moves upstream** — from per-sentence to per-merchant-category, from personal to impersonal, from uncached to cached.
- **The five keyword tables go**, replaced by enrichment output.
- **Tier 1 stops being asked about at all**, which is most of the queue.

Nothing is thrown away. The machinery was built for the hard tier and gets to keep doing that job.

---

## Decisions for Vishnu

**D1 — Where does implication knowledge live?**
 · **(a) merchantcore, at enrichment, commons-shareable** · (b) product-side, per user · (c) a hardcoded table.
**My lean: (a), strongly.** It is impersonal by construction, batched, cached, versioned, retroactive, and it is the commons' entire reason for existing. (c) is the anti-goal restated.

**D2 — Does a second, personal model call exist?**
 · **(a) no — compose options deterministically from the implication + the account registry** · (b) yes, when an implication is ambiguous.
**My lean: (a) first.** Prove the deterministic composition is insufficient before adding a personal call; every personal call is cost, latency, privacy surface and a T9 risk. Revisit with measurement.

**D3 — How much does Viva do without asking?**
 · (a) auto-assign category only · **(b) auto-assign category always, and the major when the implication is *forced*; propose otherwise** · (c) propose everything.
**My lean: (b).** This is the "feels intelligent" lever, and *report what you did* is what keeps it honest rather than presumptuous.

**D4 — Rebuild or extend?**
 · (a) new slice extending 9a in place · **(b) a 6.8-shaped restructure: enrichment gains implications, the queue is rewritten around the three tiers, 9a's machinery is retargeted** · (c) revert 9a.
**My lean: (b).** Not a revert — 9a's write side is right and its read side is retroactive, so this is repointing, not rebuilding. (c) would throw away work that is correct for Tier 3.

---

## What I'd want to measure before committing

Honest gaps, because this doc is an argument and not yet a result:

- **What fraction of the real vault is Tier 1?** If it's 90%, this change removes most of the queue and the case is settled. If it's 40%, the balance of effort shifts. *One projection query over the existing vault answers this today, before any code changes.*
- **Can a model reliably produce implications?** The eval harness already exists and can be pointed at this: given a category/subcategory, does it produce the right relationship, with the right direction, without inventing one for a supermarket? **Inventing structure where none exists is the new ruin case** — the false positive that would create phantom accounts across a whole vault.
- **Does the commons hold?** An implication must be checked to carry no personal residue before it can be shared — the T9 lint that already exists, applied to a new field.

---

# The refactor, concretely

Written against the code as it stands. **Nothing here touches ingest, verification or posting** — the write side is where mistakes are permanent, and none of this needs one. Everything below is enrichment plus read side, which means it is retroactive on the existing vault and reversible.

## Step 0 — Measure before changing anything (no code moves)

`viva.debug_tiers`: for every movement, classify it Tier 1 / 2 / 3 using *today's* catalog, and print the counts and money in each. This is a pure projection query.

It decides whether the rest is worth doing, and it is also the **before** half of the only number that matters: *how many questions did the queue ask, and how many should it have asked?* Run it again after and the difference is the result.

## Step 1 — Enrichment learns to imply (`merchantcore`)

`MerchantRecord` already carries a free `attributes` dict, and `MerchantEnriched` already syncs it into the ledger — so **no new event type and no schema migration.** Two fields go in:

- `counterparty_kind`: `business | instrument | peer`. This **replaces `_CONDUIT_MARKERS`** — whether "check" names an instrument rather than a business is a universal a model should tell us and a keyword list should not.
- `implies`: a list of `{relationship, major, on_inflow, on_outflow, account_shape, confidence, documents}`. Empty for the vast majority — **a supermarket implies nothing**, and saying so must be the easy, default answer.

New prompt `enrich-v3` in the versioned library (append-only; `enrich-v2` retained). The **new ruin case for the eval** is *inventing structure where none exists*: a model that decides a coffee shop implies a loan would create phantom accounts across an entire vault. That failure gets the same treatment as an invented split — disqualifying, never averaged.

Cost: unchanged. Same batched call, ~40 merchants at a time, a few more output tokens each.

## Step 2 — The read side derives (`projection.py`)

- **Delete `_TRANSFER_HINT_CATEGORIES` / `_TRANSFER_HINT_SUBCATEGORIES`.** Nature's rung 4 stops being a keyword guess and becomes *"what does this counterparty's implication say, given the direction of this movement?"* — with the implication's own confidence deciding whether the result is provisional.
- Add `implication_of(movement)` and `tier_of(movement)` as derived reads. Both are projections: **retroactive for free, no re-ingest**, consistent with *abstract the read side early*.
- `derived_category` already fills Tier 1 categories from the catalog. That part needs nothing — which is why the Tier 1 fix is mostly *deletion of a question*, not new machinery.

## Step 3 — The queue asks a tenth as often (`questions.py`)

This is where the felt change happens.

- **Tier 1 raises nothing.** `_nature_questions` currently fires for every enriched merchant decided by hint-or-default. That is the "we already knew and asked anyway" bug, and removing it is the single biggest improvement in this document.
- **Tier 2 becomes a proposal, not a question**: what we believe, what we're unsure of, and options composed from the implication matched against existing accounts (Slice 1.5's matcher, deterministic). Free text stays as the escape.
- **Tier 3 keeps today's per-transaction question** — checks, ATMs, Zelle — which is already correct.

## Step 4 — `listen.py` sheds its rules and keeps its spine

Delete `CORROBORATION`, `_DEFAULT_GROUP`, `_group_for`, and `suggest_answers`'s substring matching. Every one of them is replaced by enrichment output: the document that proves a claim, the account's place in the hierarchy, and the order of the offered answers are all properties of the *implication*, learned once and cached, not of a table we maintain.

`interpret` / `propose` / `apply_proposal` / `Proposal` / `RulingRecorded` / the majors / `origin` / `MIXED` — **all unchanged.** They stop being the front door and become the correction channel and Tier 3's primary path, which is what they were always good at.

## Step 5 — Prove it

- `test_tiers.py`: a supermarket asks nothing; a mortgage servicer proposes; a check asks per transaction.
- Extend `eval_listen` (or a sibling) to score **implication quality**, with *invented structure* as ruin.
- The real-vault run, which the standing practice requires and 9a never got: **Step 0's numbers, before and after.**

## Order, and why

Steps are strictly ordered by reversibility. Step 0 changes nothing. Step 1 adds fields to an existing bag. Steps 2–4 are read-side and deletion. **No event schema changes, no migration, no re-ingest** — and if the implications turn out to be unreliable, reverting is deleting a projection, not unwinding a ledger.

---

## Deferred / out of scope

Multi-party or household implications. Using implications to *predict* future obligations (that is Slice 8). Sharing the implication commons with other users (the mechanism should be built commons-ready and the sharing switched on separately). Any change to the ingest, verification or posting layers — this proposal touches only enrichment and the read side, which is deliberate: **the write side is where mistakes are permanent, and none of this needs one.**

---

## What the build showed (2026-07-25)

**The audit was worse than the diagnosis.** Counting properly found **nine** raw-text classifiers, not five, and **four predate Slice 9a**: `_TRANSFER_WORDS` / `_CARD_WORDS` / `_DEPOSITORY_WORDS` (Slice 3), `_CASH_MARKERS` (Slice 6), `_PEER_MARKERS` (Slice 5.5). So this was never one slice drifting — it is a **reflex**: every time the code met ambiguity in raw text, it reached for a word list. Naming that is more useful than blaming a slice, because the reflex will recur unless the alternative is easier than the list, which is the point of putting implications where enrichment already runs.

*(Not everything that looks like a table is drift. `PRIMARY_CATEGORIES`, `DEDUCTION_ACCOUNTS`, `BROKERAGE_CASH_IN/OUT` are **schema we deliberately own**, mapping our own structured field values. The drift is specifically **classifying raw descriptors by substring**.)*

**Deleted:** `_TRANSFER_HINT_CATEGORIES`, `_TRANSFER_HINT_SUBCATEGORIES`, `_CONDUIT_MARKERS` + `is_conduit`, `CORROBORATION`, `_DEFAULT_GROUP`, `_group_for`, and `suggest_answers`'s substring matching. Each is now a property of the counterparty's implication — `major`, `account_group`, `documents`, `counterparty_kind` — learned once, cached, versioned, shareable.

**Measured, on a synthetic vault of six movements** (four ordinary merchants, one mortgage servicer, one check):

```
before:  6 questions          — one per movement, including the supermarket
after:   2 questions          — 33 per 100 movements
         settled     4  67%   handled without asking
         structural  1  17%   proposed, with its grounds
         unknown     1  17%   asked, one transaction at a time
```

**Two-thirds of the queue disappeared** — and the two questions that remain are the two a person would actually ask.

### What changed in the building

- **`implication_for(merchant, inflow)`** had to exist separately from `implication_of(movement)`. `propose` needs to ask what a counterparty implies *before* it has a movement in hand, and scanning movements to find out was both slow and wrong for a proposal being composed.
- **Confirming a `suggested` implication changes no figure — it removes the doubt about one.** That surfaced when a test asserted spending would drop on confirmation and it didn't: the implication had already excluded it, provisionally. That is the ladder working, and it is a better story than the old one: *"I believed this, and now I'm sure."*
- **Unenriched counterparties raise no nature question at all.** Asking what money *became* before knowing *who received it* is the wrong order, so the flow is strictly ingest → enrich → ask. `debug_tiers` says so out loud when a vault has unenriched merchants, because otherwise the measurement would look artificially question-heavy.
- **Tolerant on transport noise, strict on claims.** `clean_implications` accepts `" Asset "` (whitespace and case are noise) and drops `"assets"` or `"liability payment"` outright. An unrecognised `confidence` degrades to `suggested` and an unrecognised direction to `both` — always toward the rung that **asks** rather than the rung that **acts**.

### Still to do

**The real-vault run.** Everything above is measured on synthetic data. `python -m viva.debug_tiers` gives the honest before; `python -m viva.enrich` under `enrich-v3` fills in the implications; running `debug_tiers` again gives the after. The human rulings already made survive — `reset_categorization` keeps them by default, and they were true regardless of how naively they were asked for.
