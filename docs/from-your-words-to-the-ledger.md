# From Your Words to the Ledger (Slice 9a — Viva listens)

**Status:** ✅ **BUILT 2026-07-25** (A1–A3 settled during the build; see *What changed in the building* at the bottom) · **Created:** 2026-07-25 · **Design by:** Vishnu (the flow and the four-category framing); mechanism and reuse mapping by Claude. **Block seeded:** the **Proposal** (see [viva-listens-and-speaks.md](viva-listens-and-speaks.md)) and **account resolution** — the Slice-1.5 matcher pointed at a new target.

**Invariants touched:** **T2 / ADR-010 (the model parses meaning; it never supplies a figure, picks an account, or posts)** · T3 (your sentence and the parse are captured verbatim) · T4 (a confirmed ruling is an append-only event; postings use the builders we already have) · **X2 (a proposal states what it changes, how much money it moves, and what it does *not* know)** · X3 (nothing applied without an explicit yes — a property of Proposal, not a rule to remember) · I5 (the four majors are universal; everything beneath is data) · **M1 (cash-flow over accrual — a created asset records what you *paid*, not what it's *worth*)**.

---

## The problem this closes

The question queue offers three answers — `spending / transfer / settlement` — and a real vault immediately produced two questions none of them fit: a mortgage payment (three things at once) and a car purchase (something you now own, which the ledger cannot represent). Answering more questions in that vocabulary produces more wrong answers, and any net worth built on top inherits them.

The diagnosis: **`nature` was an impoverished stand-in for what the counter-leg *is*.** The ledger already posts to `Assets:`, `Income:`, `Expenses:`, `Equity:` and `Transfers:` internally — double-entry's own vocabulary, complete and centuries old — but the surface collapsed it to three words. There is not even a `Liabilities:` root: paying down a card lands in `Transfers:Uncategorized`, which is why *"I paid off debt"* is currently unsayable.

That vocabulary has many members and compound cases, so **it cannot go behind buttons — but it fits in a sentence.** Free text is not a convenience here; it is the only practical interface to a complete ontology.

## The vocabulary

Every movement's counter-leg is one of **four majors**, closed and universal:

| Major | Means | Example |
|---|---|---|
| **Expense** | money spent, gone | groceries, interest, a fee |
| **Asset** | you still have it, in another form | a car, cash withdrawn, escrow, money lent to a friend, another of your accounts |
| **Liability** | what you owe changed | a card paid down, mortgage principal |
| **Income** | money that arrived | salary, a dividend, rent from a tenant |

**Equity is deliberately absent.** For a person, equity *is* net worth — assets minus liabilities — so it is derived, never asserted. (`Equity:OpeningBalance` stays system-generated for unexplained history.)

**Fixed top, free hierarchy below** — the same shape as the 16 primary categories with a free subcategory: `Assets:Vehicles:<name>`, `Liabilities:Mortgage:<lender>`. The four are code; everything under them is data (I5).

## The toolset — six steps, one model call

```
1  frame_question      deterministic   (exists — the question queue)
2  suggest_answers     deterministic   from merchant category/subcategory: the common case is a button
3  interpret           ← THE MODEL     your sentence → a structured proposal
4  resolve_account     deterministic   exact match / candidate to confirm / new
5  propose_posting     deterministic   the legs, the accounts, what changes, how much moves
6  confirm → apply     deterministic   simple_transaction | split_transaction + the ruling event
```

The model touches **step 3 only**. It never sees the ledger, never picks an account, never emits an amount — any number in its output is discarded, because amounts come from the movement.

### Step 3 — what `interpret` may return

```
Interpretation(
  legs: [ {major, account_hint, share?} ],   # 1 leg normally; N for a compound payment
  relates_to: "loan" | "asset" | none,        # what the counterparty *is*
  corroborates: "mortgage_statement" | none,   # a document that would PROVE this — a suggestion, never a gate
  confidence, verbatim)                       # the sentence, kept
```

`share` is present only when the person states proportions. **If the split is unknown, that is a valid and expected outcome** — see below.

### Step 4 — account resolution *is* Slice 1.5's matcher

This is the reuse that makes the slice cheap. Resolving *"which account does this belong to?"* is the same problem as *"is this the same account as one I've seen?"*, which Slice 1.5 already solves: **signals → graded match → ask only when ambiguous → learn the ruling → never ask again.**

- **Exact match** → post, no question. (The default should be silence.)
- **Candidate** → *"Does this belong to your Chase mortgage, or is it a different loan?"*
- **No match** → propose creating one, with a name suggested from the merchant's canonical name and subcategory.

**Creation always requires confirmation — and that is the only confirmation this slice needs (D2).** **Account sprawl is the failure mode** — `Assets:Car`, `Assets:Tesla`, `Assets:My Car` — so the same disciplines that tamed merchant descriptors apply: normalize the name, suggest existing accounts before offering new, and let the matcher offer merges later.

## The three cases that shaped this

**"I bought a car."** → one leg, `Asset`, new account `Assets:Vehicles:<name>`. It records **cost**, not value: what you paid is a measured fact, what it's worth now is unknown. So the account carries cost basis plus a valuation class of `estimated` — exactly what Slice 6's valuation discipline was built for. Without this, net worth silently claims the car is still worth what you paid.

**"This is my mortgage."** → **three legs**: `Expense` (interest), `Liability` (principal), `Asset` (escrow — money you still own). The proportions are unknown *to you as well*, because they are printed on a statement neither of us has.

**A missing document must not block the account** (Vishnu, 2026-07-25). Create `Liabilities:Mortgage:<lender>` now, post the cash to it — cash leaving is a measured fact (M1) — and mark **the decomposition** provisional, not the movement. What we know is recorded; only the split waits. Concretely: the account exists and generalizes immediately, spending stops being overstated, and the **liability balance derived from these payments is flagged unreliable** so net worth cannot quietly treat interest as debt reduction. The 1098 then arrives as a *suggestion for corroboration*, not a precondition: *"Your 1098 would let me split these into interest, principal and escrow exactly — and prove it."*

**"This paid my car loan."** → one leg, `Liability`, account created. Its **balance is unknown** until a loan statement arrives, and that is an honest state: payments known, outstanding unknown, coverage says so. It also makes the loan statement a natural thing to ask you for.

### The corroboration prompt (generalized)

> **Big purchases have paperwork. Ask for it — never to unblock, always to prove.** (Vishnu, 2026-07-25)

Provenance is the product, so every account this slice creates should invite the document that vouches for it: a **car → invoice or bill of sale**; a **home → closing disclosure**; a **mortgage → statement or 1098**; a **loan → the loan statement**. These are corroboration in exactly the Slice 3 sense — a second, independent issuer confirming what a bank line only implies. A purchase inferred from one bank line is `unverified`; the same purchase with its invoice is `verified`, with an amount, a date, a counterparty and often an itemization the bank line never carried.

Two rules keep this from turning into nagging: **the ask is never a gate** (the account is already created, the posting already made), and **the ask is ranked with everything else** in the question queue by consequence, so a $40k invoice surfaces and a $200 one does not. These asks route into [document-coverage.md](document-coverage.md)'s list rather than a separate mechanism.

## What the substrate needs — after reading the code (2026-07-25)

A pass over `postings.py` / `projection.py` before building corrected two claims this spec made:

**The chart of accounts is already *derived*, not posted.** A category is an **overlay keyed on `movement_key`** (Slice 5); the posted counter-leg stays `Expenses:Uncategorized` forever and every aggregate reads the overlay — which is why the `Income:Uncategorized` / `Expenses:Uncategorized` balances are recorded as cosmetically stale with no answer path reading them. So a **`Liabilities:` root is a read-side change**: cheap, retroactive, reversible, exactly as [principle: read side early, write side late](honest-aggregates-and-the-learning-loop.md) predicts. `Assets:Vehicles:<name>` and `Liabilities:Mortgage:<lender>` are *materialized by the projection* from the ruling, not written into postings. The overlay carries everything a real posting would need, so re-posting later remains possible without losing anything.

**`split_transaction` is not this slice's first customer.** It requires split magnitudes summing to the movement total, so it cannot express *"three legs, proportions unknown."* The unknown-ratio mortgage posts **one leg with the decomposition pending**. `split_transaction` waits for Slice 11, when the 1098 supplies real ratios — which is the honest reading of "post nothing you cannot justify."

Still genuinely needed:

- **Asset accounts** for things that are not securities — the general Asset primitive, with valuation class. `Position` (Slice 6) becomes a subtype rather than the only kind.
- A pointer from the **merchant catalog to an account**, so the ruling generalizes: once *"Harborline is my mortgage"* is settled, every future payment posts without asking.

## Architectural decisions (A1–A3) — the write-side, one-way doors

The read side is reversible and can be built freely. These three are not.

**A1 — the ruling event: build Move 3's generic `Ruling` now.** The alternatives were extending `CategoryAssigned` a fourth time, or adding narrow per-question event types. `Ruling` was deferred until *a fifth question type earned it* — this is that type, and it needs exactly what `Ruling` was designed to carry: **its own scope** (movement / merchant / account). Deferring costs a fourth narrow event that `Ruling` would then have to subsume anyway.

**A2 — accounts born from a sentence live in the *same* registry.** Every account today is born from a document with identity signals (number, institution, holder names); `Assets:Vehicles:<name>` has none. One registry is what makes step 4 cheap — the Slice 1.5 matcher, sprawl control and merge-later all work unchanged. The cost is a registry containing accounts nobody issued, which is handled by A3 rather than by a second namespace.

**A3 — every account records its `origin`: `issued` or `asserted`.** *(The expensive-to-miss one.)* Everything in the ledger traces to a document from an issuer. A car account's existence rests on **the person saying so** — fine for a butler, and *not* fine at the endgame, where a claim is proven to a counterparty and an asserted account is not evidence in the way a statement is. **The distinction is only capturable at write time**; miss it and the ledger quietly becomes un-vouchable, with no way to reconstruct which accounts a third party could ever rely on. It is near-free today and unrecoverable later, so it goes in now.

This also makes the corroboration ask **structural rather than a nicety**: the invoice / 1098 / closing disclosure is literally the path from `asserted` to `issued`, and a document arriving *upgrades the account's origin*. What began as "ask for the invoice, we're provenance-based" turns out to be the mechanism by which a personal ledger becomes something another party can trust — the endgame, reachable from this slice.

## Decisions (both settled 2026-07-25, by Vishnu)

**D1 — Plain English on the surface, always. The four majors live only in the data.** The person is never asked "is this an asset?"; they are asked whether they still have it, in another form. Nobody types an accounting term to use this product.

> **Forward note — question phrasing is a job for a small local model.** Today the templates are fixed strings. Later, a **small in-house model can phrase the question in the person's own language and preferred tone** — a Swedish user gets a Swedish question, not a translated one, and someone who wants terse gets terse. This is the right shape for three reasons: phrasing touches **no figure and no account**, so it sits entirely outside the T2 boundary and cannot corrupt anything; it is small enough to run **locally**, so the warmest surface in the product needs no cloud; and it turns I5 from "we avoided US-shaped assumptions" into something actually felt. Because the majors are stored, never spoken, this is a **surface-only change** — no event, projection or prompt moves. Record it as a candidate for the local-model thread (ADR-001's flip-to-local bar).

**D2 — Confirmation is scoped to the account, not to every parse: the first time an account is involved, always confirm; after that, the learned ruling applies silently.** This is Slice 1.5's ask-once-and-learn contract, and it is a sharper rule than a blanket "never auto-apply" — the expensive, sprawl-creating, hard-to-reverse act is **binding money to an account for the first time**, and that is exactly what gets the explicit yes. Once *"Harborline is my mortgage"* is confirmed, the next twelve payments post without a question. The default, after the first answer, is silence.

## Done criteria / tests

- A sentence produces the **same events** the buttons would, with the same grade and reversibility — free text is an alternative channel, never a second mechanism.
- **The interpreter never supplies a figure**: fed a sentence containing an amount, the amount is ignored and the posting uses the movement's own value (a test asserts this).
- A compound answer with unknown proportions **still creates the account and posts the cash**; only the *decomposition* is provisional, and the liability balance derived from it is flagged unreliable. A missing document never blocks a ruling.
- Every created asset or liability **raises a corroboration ask** (invoice / closing disclosure / 1098 / loan statement), ranked by consequence — and answering it is never required to proceed.
- **Confirmation is per account, not per parse**: the first binding asks; the thirteenth payment to the same lender posts in silence.
- A created asset carries cost basis and an `estimated` valuation class; a created liability carries an unknown balance, stated honestly in coverage.
- Account resolution asks **only when ambiguous**; an exact match posts silently; a ruling generalizes so the same counterparty is never asked about twice.
- With **no model configured**, the queue still works with buttons — free text is an addition, never a dependency.
- Every sentence and parse is captured verbatim in the claims layer (`phase="interpret"`), so a better model can re-derive later without asking again.

## Deferred

Open-world free text with no question attached (Stage A's harder sibling). Proposal unification across sources (Stage B). The tool registry and planner — **Slice 9b, Viva speaking**. Splitting a mortgage by real amortization ratios (Slice 11, once the statement is ingested). Asset *valuation* over time as opposed to cost at acquisition. **Locally-phrased questions** (the small in-house model in D1's forward note) — the templates stay fixed strings for now.

---

## What changed in the building (2026-07-25)

Reading the code before writing it corrected two claims, and the tests found two bugs the design had not anticipated. Both are recorded here rather than quietly fixed, because a build log that only reports its wins would refute this project's own thesis.

**A fifth nature: `mixed`.** The spec said a compound payment with unknown proportions "posts nothing it cannot justify." Building it forced the sharper question — *is it spending or isn't it?* Counting the whole mortgage payment as spending restates the exact overstatement Slice 6.5 fixed; dropping it understates. Neither is true, so it is neither: `MIXED` is its own nature with its own line, `undecomposed()`, reporting the total, the count, the accounts and **the document that would resolve it**. The headline now reads *"X spent, plus Y I can't split yet — your 1098 would settle it."* That sentence is the thing the three-button question could never say.

**The ruling rung was promoted above the own-account rung.** Nature was decided: link → own-account → ruling → category → default. A ruling is *a person telling us what something is*; the own-account rung is a **heuristic over description text**. When they disagree the person is right, so rungs 2 and 3 swapped. The product quietly overriding what it was told would be the worst class of bug this codebase could have.

**A ruling's new account matched its own movements as an internal transfer.** `Liabilities:Mortgage:Acme`, created from *"this is my mortgage"*, entered the own-account token index — and every payment to `ACME MORTGAGE SERVICING` then looked like a transfer to itself, silently overriding the ruling that created it. Fixed by indexing **issued accounts only**: an asserted account is named after the counterparty whose payments created it, so it can never be evidence of an internal transfer. *Found by a test, not by a real run* — which is the argument for testing the rungs individually rather than only the aggregate.

**A model's reply is untrusted input, not a contract.** `{"legs": "nope"}` crashed the interpreter. Now anything that is not a list of objects, and any leg outside the closed vocabulary, is dropped with a warning and the caller falls back to the buttons.

**Two things the spec got wrong about the substrate**, both corrected above: the `Liabilities:` root is a read-side change (a category is an overlay, so the chart of accounts is materialized by the projection), and `split_transaction` is **not** this slice's first customer — it requires shares summing to the total, which is precisely what an unknown split does not have.

**An old bug found on the way past:** the queue's third option, *"Something I now own,"* was wired to `nature="settlement"` — debt repayment. Answering it honestly recorded the wrong thing. The four majors replace it.

### What shipped

`RulingRecorded` (generic, scoped: movement / merchant / account) · `origin: issued | asserted` on every account · the four majors + `account_path` · `MIXED` + `undecomposed()` + `ruled_accounts()` · `viva/listen.py` (the six steps, one model call) · the `corroboration` question kind · `/api/rule-major`, `/api/listen`, `/api/apply-ruling` · the sentence box and proposal card on the debug surface. **26 new tests, 249 green.**

### Measuring the model (added the same day)

`python -m viva.eval_listen` scores any model on the one job this slice gives it, against a **frozen synthetic key** of 22 sentences (`viva/evals/listen_cases.json` — invented counterparties, no amounts, safe in a public repo). Free, offline-capable, and reproducible.

**The headline is not accuracy — it is the confidently-wrong rate.** This is [eval-harness-design.md](eval-harness-design.md)'s thesis meeting its first real subject, and the failure modes are deliberately not on one scale:

| verdict | meaning | cost |
|---|---|---|
| `unreadable` | no JSON, or no legs | **safe** — one tap on a button that already existed |
| `missed_compound` | read a mortgage as one thing | weak — collapses a nature, doesn't fabricate |
| `wrong_majors` | a confident misreading | wrong — and it *generalizes* to every future payment |
| **`invented_split`** | a ratio nobody stated | **ruin** |
| **`leaked_amount`** | a figure from the model's head | **ruin** |

A model that declines costs a person a tap. A model that invents a 60/40 mortgage split writes a wrong number into someone's finances, grades it `verified` because the person did confirm the sentence, and applies it forever. **Any non-zero ruin count disqualifies a model outright** — averaging it against successes is exactly the mistake this project exists not to make.

Several cases accept *more than one* reading: an ATM withdrawal is defensibly cash-you-still-have or money-spent. A key insisting on one answer would measure obedience rather than understanding. `--repeat N` surfaces instability, because a model that is right two times in three is a different product from one that always is.

The harness has its own tests (`test_eval_listen.py`) — a scorer that mis-grades a fabrication as "ok" would silence the one alarm the thesis rests on.

**The harness failed its own test on the first real run (2026-07-25).** Pointed at a local Ollama, all 66 calls errored before reaching the model — and the report said *"0% ruin, clean, safe but weak."* Every failure had been swallowed by `interpret`'s deliberate degrade-never-raise behaviour and scored as `unreadable`, the safe bucket. The tell was in the output and unread: **p50 latency of 0.01s**, two orders of magnitude too fast for local inference.

This is the confidently-wrong failure committed *by the instrument built to detect it*, which makes it the most useful bug in the slice. An eval that cannot distinguish "the model declined" from "we never reached the model" is worse than no eval, because it is **reassuring**. Fixed by making the distinction structural rather than inferred:

- `Interpretation` now carries **why** there are no legs — `unreachable` / `unparseable` / `empty` — plus the underlying error and the raw reply. Two identical-looking outcomes that mean opposite things are no longer collapsed.
- `BROKEN` is its own verdict, **excluded from the denominator**, so a broken run cannot launder non-events into a good score.
- The confidently-wrong rate becomes **`None`, not `0`**, when nothing was measured. An unknown rate is not a good rate — the same discipline the ledger applies to an unknown balance.
- A wholly-broken run prints *"NOTHING WAS MEASURED"*, the actual error, and what to check. It says nothing whatsoever about the model, because nothing was learned about the model.
- `--probe` runs one call with nothing swallowed, and `--no-json-mode` covers local servers that reject `response_format`.

The general lesson, worth more than the fix: **a component that degrades gracefully must still report the difference between "I handled it" and "it broke."** Silent resilience in the product is correct; silent resilience in the instrument measuring the product is a lie.

### The second live run: a good mechanism in the wrong place

With the connection working, one sentence produced **seven HTTP calls over 23 seconds**, then *"reply still truncated after continuation"*, then a JSON parse error. The count is the diagnosis: `MAX_CONTINUATIONS = 6`, plus the first call, is exactly seven.

The **continuation driver** — lifted into `vivacore.models.base` a few days earlier precisely because a truncated document read was silently losing transactions — was doing its job in a place where its job is wrong. Reading a statement, truncation means *the list was genuinely too long* and stitching the tail back is the correct repair. Reading a sentence, the answer is ~60 tokens **by construction**: hitting the limit means the model is rambling, and stitching six more chunks onto a runaway reply turns one cheap, recoverable failure into unparseable garbage at seven times the cost and seven times the latency. Worse, continuation turns `json_mode` off for the follow-up turns, so it was concatenating free prose onto a JSON prefix and then asking `json.loads` to make sense of it.

The fix, and the principle behind it:

- `ModelSpec.max_continuations` — a call whose output is **short and bounded** sets it to 0. Truncation there is a condition to **report, not repair**.
- `one_shot_extractor` is the interpreter's own edge; both the product and the eval use it, since an eval on a different edge measures the wrong thing.
- `_first_json_object` finds the first *balanced* object anywhere in the reply, so fences, reasoning traces and trailing pleasantries stop costing us a good reading. The balance check matters more than the leniency: **a truncated reply is refused rather than half-read**, because a cut-off reading is not partial, it is unknown, and guessing the rest is how a wrong ruling gets written and then generalized.
- `max_tokens` raised to 1024 — headroom for models that think out loud, which now costs tokens but never costs the reading.

### The prompt: bank-shaped, and outside the library

Two problems, both spotted by Vishnu on reading the rendered prompt (2026-07-25).

**It assumed a bank.** *"one payment from their bank account"*, *"the counterparty on the statement"* — but the vault already holds cards, brokerages and retirement accounts, and will hold loan accounts and wallets. That framing quietly mis-describes every one of them, and it is the same I5 failure the project has caught before in other places: an assumption baked into universal code instead of arriving as data. `interpret-v1` now says *"ONE movement of their money"*, names the actual instrument through a `{source}` placeholder the service fills from the account's own kind, and states explicitly that the movement may come from any instrument in any country.

**It was a module constant, not a versioned prompt.** Slice 2 established prompts as **retained, addressable, append-only data**, with a frozen-hash test enforcing that a released version's text can never change. `INTERPRET_PROMPT` lived in `listen.py` as a plain string — rewritable in place. Tuning it would have silently reinterpreted every ruling recorded before the change, with no way to recover what the model had actually been told, and would have made eval runs incomparable across time. It now lives in `prompt_library.py` as `interpret-v1` with named placeholders, and **every ruling stamps its `prompt_version`** so a stored ruling resolves to the exact instructions that read it (T8).

The general shape, again: a discipline the project already had, not applied to new code because the new code arrived from a different direction. Worth a habit — *when a slice makes a model call, its prompt goes in the library and its version goes on the event.*

Three live failures, all of the same shape: **an existing discipline not carried across to new code that arrived from a different direction.** The first swallowed errors, the second stitched a bounded answer, the third hardcoded a prompt that assumed a bank. Reading a 40-page statement and reading a six-word sentence are not the same problem — but they are the same *project*, and its rules apply to both.

### Not done yet

**No real-document run.** Every slice is supposed to meet real statements before being called done, and this one has met only fixtures. The standing practice says that is when concept errors surface — Slice 6 was declared done without one and had two defects. Until a real mortgage or car purchase goes through the sentence path, treat this as built but unproven.
