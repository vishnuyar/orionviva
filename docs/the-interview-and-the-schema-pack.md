# The Interview & the Schema Pack — a question that continues

**Status:** Design spec — **approved 2026-08-01. Cycle 1 built 2026-08-01** (as-built note below); cycles 2 and 3 unbuilt. · **Created:** 2026-08-01 · **Origin:** Vishnu: *"the current question framing in this product is already stale: it just feels like a list of buttons for the user, with no intelligence on the site… we should probably create a schema for all types of assets and liabilities which might be there in a person's financial journey… some are probably a must, some are good to have."* · **Governed by:** [ADR-012](decisions/ADR-012-the-interview-model-boundary.md) · **Blocks seeded:** the **interview primitive** (a question with a next step) · the **schema pack** (the fourth pack) · the **closed-vocabulary selector** · **account-scope tags** · the **disclosed gap** in net worth.

**Invariants touched:** **T1** (every attribute carries a source and a grade) · **T2** (the model selects a key and writes a sentence; it never supplies a value, picks an account, or posts) · **T3** (envelope and reply captured verbatim) · **T4** (every answer and decline is an event — and this spec adds *no new event type*) · **T6** (two enumerated outbound flows, whitelisted — ADR-012) · **T8** (prompt version and model stamped on every interview call) · **T9** (a schema is impersonal world knowledge and shareable; every answer and every tag is personal and vault-only) · **M1** (a created asset records what was *paid*, never what it is *worth*) · **I5/I6** (schemas are jurisdiction-tagged pack entries, never US-shaped code) · **X2** (an asset whose essentials are unfilled is a disclosed gap, never a zero) · **X3** (no account exists without an explicit yes) · principles **5** (serve, don't overwhelm), **6** (you direct the pace).

---

## The one sentence

**The schema owns what may be asked; the model owns what to ask next; the person owns whether anything is created.**

## The diagnosis this comes from

Tier 2 is built and it opens well. For a mortgage servicer the queue composes the count, the total, the relationship, and an ask sentence that a model wrote at enrichment. Then it offers two options — *yes, that relationship* / *no, money spent* — and a yes applies in the same request.

That is the entire interaction. **There is no second question anywhere in the product**, because a question is a one-shot record: text, options, a free-text box, refs. Nothing has a next step.

So "a list of buttons with no intelligence" is not a phrasing complaint and not a ranking complaint. It is an accurate description of a structural fact. Better wording cannot fix it; a new primitive can.

The same fact explains an open audit finding. A tier-3 option carries only a movement key and a major, so with nowhere to ask *"which one, and what is it called?"*, applying immediately was the only move the shape allowed — and an unnamed asset reached the net-worth curve. **The interview is that finding's structural fix**, which is why the guard and the capability are one piece of work rather than two.

## What this is the sequel to

Five settled positions this builds on and must not undo.

1. **Viva decides how to ask, never what to ask** ([viva-persona-and-interview.md](viva-persona-and-interview.md)). Extended rather than broken: the *schema* decides what may be asked — reviewed, versioned, impersonal — and a model may only order and word what the schema already permits.
2. **Intelligence at the question, not the answer** ([where-the-intelligence-goes.md](where-the-intelligence-goes.md)). The three tiers are unchanged; the interview is what happens *after* a tier-2 proposal is accepted, and it raises nothing for tier 1.
3. **Model as interpreter, person as ratifier, code as applier** ([from-your-words-to-the-ledger.md](from-your-words-to-the-ledger.md)). Unchanged in every particular. Answers still become Proposals and Proposals are still the only path to a change.
4. **A question that cannot be honestly asked is not asked** ([learning-mode.md](learning-mode.md)). A kind with no schema raises nothing and records the gap; it never asks a question it cannot use.
5. **Never a nag** ([experience-vision.md](experience-vision.md)). The interview interleaves and defers; it never chases.

## The decisions (Vishnu, 2026-08-01)

| | Decision | Why |
|---|---|---|
| **D1** | **The interview is a primitive: a question with a next step — and it is *read-side*.** It has no state of its own and no new event type. An interview is a projection over the attribute rulings and declines already recorded for a subject. | The read-side-early rule, paying out again. Cycle 1 lands with no schema migration, heals an existing vault on replay, and is reversed by deleting a projection rather than by living with an event shape forever. |
| **D2** | **The schema is a closed vocabulary. A model may select within it; a key outside it is dropped.** | The mechanism this project already uses to let a model be smart without being dangerous — `interpret` drops any leg outside its vocabulary, grammar induction slots into a closed set. A model choosing among reviewed questions cannot steer the interview toward what *it* wants to know. |
| **D3** | **Seed small, generate on first encounter, promote on review.** A previously-unseen kind triggers one impersonal model call that drafts its schema; the draft is written to the pack, flagged unreviewed, asked from immediately, and promoted when read. | Enumerating forty kinds from here produces a US-shaped list whose omissions are invisible. The precedent is the expectations registry, seeded with ~6 of the vault's own instrument types and grown. |
| **D4** | **No amounts and no currency in the interview envelope.** The count and cadence make a question feel informed; the money adds nothing to selection and is the most sensitive field. The jurisdiction tag carries what currency would have told the phrasing. | [ADR-012](decisions/ADR-012-the-interview-model-boundary.md) §2. Removing a whitelist field is free; adding one is an amendment. |
| **D5** | **The interview interleaves. It never holds the queue.** "Not now" defers the question into quiet pending state; it returns to the ranked queue when new evidence touches its subject, or when the person opens the pending list themselves. | Ranking by consequence is settled, and an interview that outranked a larger finding would be incoherent. Deferring into pending rather than into silence is how *"it always comes back"* and *"never a nag"* are both true. |
| **D6** | **Essentials terminate the interview, and gate net worth.** An interview is over when every essential question is answered or declined. An asserted asset whose essential cost is unfilled is reported as a **disclosed gap** — never a zero, never a guess, never silently omitted. | Naming the account fixes half the audit finding; the other half is a named asset whose number nobody stated. X2 and principle 2. |
| **D7** | **Tags gain account scope. The model copies the person's own word and never coins one.** | The union pattern one level up from merchant scope, and `interpret-v2` already carries the rule *"copy their word; do not invent one."* Keeps [categories-and-tags.md](categories-and-tags.md) D2 intact — no model mints personal meaning. |
| **D8** | **Cycle 1 is deterministic. The model selector is cycle 2, and must beat cycle 1 on measured grounds.** | Without a baseline, "the model asks better questions" is a feeling with nothing to compare against. Build the dumb walk, feel how dumb it is, then beat it with a number. |
| **D9** | **Jurisdiction is an attribute of the account; the country tag is *derived* from it.** Every schema is jurisdiction-tagged, an account created from one records its jurisdiction as an attribute — a fact, graded, upgradeable by a document — and the country tag is a read over that attribute rather than a second stored label. | *Vishnu, 2026-08-01.* One source of truth, so "show me everything in India" works across accounts, movements and holdings without two vocabularies drifting apart. It does not breach [categories-and-tags.md](categories-and-tags.md) D2: what that forbids is a *model* minting personal meaning; a tag derived deterministically from a fact the person stated or a document attested is the opposite of a guess. Jurisdiction is the *instrument's* home, not the person's, and it is not currency (I1) — a person may hold an INR instrument from anywhere. |

---

## The blocks

### 1 · The schema pack — shape as data, the fourth pack

A schema states **what exists and what it needs known**. It never says how to read a document and never classifies raw text; it is shape, not a word list — the same standing this project already gives its own controlled vocabularies.

An entry, sketched:

```
kind:          property
jurisdiction:  [us, in]
version:       1
account_shape: Assets:Property:<name>
questions:
  - key: purchase_price   essential  answer: money
      unlocks:      "net worth can carry this asset at cost"
      corroborated_by: closing_disclosure | sale_deed
  - key: purchase_date    essential  answer: date
  - key: financed         essential  answer: yes_no
      opens: mortgage          # a yes starts the liability's own interview
  - key: rate             optional   answer: rate
      unlocks:      "your true borrowing cost"
```

Three fields carry more weight than they look:

- **`essential`** does three jobs: it ranks, it terminates the interview, and it gates net worth (D6).
- **`unlocks`** is the benefit sentence the persona pack's tone rules already require — *"if you share the rate, I can show your true borrowing cost."* It exists so a question can always explain why it is worth answering.
- **`opens`** is how branching is expressed as **data rather than a loop**. *"Yes, I'm paying an EMI"* opens the mortgage interview and links the two accounts. This is the entire mechanism by which the conversation follows the answer, and it needs no model at all.

Jurisdiction tags are present from the first entry, and **India ships in v1** — it is the author's own exposure and the I2/I5 proof already owed.

### 2 · The interview, derived

There is no interview object and no interview event. For a subject (an account) whose kind has a schema, the projection knows which questions are answered, which are declined, and which remain. The queue gains one source that yields the next unanswered essential, ranked with everything else (D5).

- **An answer** is `RulingRecorded(scope="attribute", subject="<account>:<key>")`, graded `asserted`, upgraded to `corroborated` when a document states the same fact. The generic scoped ruling earns another scope; nothing new is minted.
- **"Not now"** is the existing decline event, and D5's pending state is a read over it.
- **Termination** is a derived property: no essentials outstanding.
- **A kind with no schema** yields nothing and records a coverage gap — it never asks a question whose answer it could not use.

### 3 · The selector

**Cycle 1 — deterministic.** Next essential by consequence, worded from the persona pack. This is the baseline, and it never goes away: it is also cycle 2's permanent fallback.

**Cycle 2 — the model selects and words, within the vocabulary.** Governed entirely by [ADR-012](decisions/ADR-012-the-interview-model-boundary.md): the whitelisted envelope, no speculative calls, out-of-vocabulary keys dropped, the no-new-facts validator on generated wording, verbatim capture with prompt version and model. Nothing in this document relaxes any of it.

### 4 · Where answers land

- **The account is created by a confirmed Proposal, never by a tap.** The tier-2 yes returns a Proposal, and existing accounts are offered before a new one is minted. This is the audit finding's structural fix and it is not optional. **Amended 2026-08-15:** the Proposal carries **no suggested name**, and the code refuses to invent one. This said the name came from the merchant's canonical name and subcategory; account resolution does not work that way. A path is built from the words the person used, and a yes that says "I still have it" without saying *what* returns no path at all — the verdict is `unnamed`, which is a **question** (*you now own or owe something, and it has no name yet*), because a path built from a placeholder is a thing nobody named reaching net worth. Everything else in this bullet stands: the confirmed Proposal is still the only way an account is created here, and existing accounts are still offered first, by name, with a near-match returning `ambiguous` rather than minting a second one.
- **An asset records cost, valuation class `estimated`** (M1). A liability's balance stays honestly unknown until a statement arrives.
- **Every account keeps its `origin: asserted`**, and a document arriving upgrades it.
- **A figure in an attribute answer must appear in the person's own words.** Same guard, same boundary, as the invented-split rule: a model may not supply a number the sentence did not contain. An attribute money value is `(value, currency)` (I1), parsed by the locale-aware money parser (I2).

### 5 · Net worth's disclosed gap

An asserted asset with unfilled essentials is neither counted nor hidden. It appears as a stated gap — *one asset, value not yet stated* — and coverage says so, exactly as a liability with an unknown balance already does. A zero would be a number nobody stated, and this product does not put those in front of people.

### 6 · Tags at account scope

A tag on an account flows to every movement touching it, union with movement and merchant scope, complete set re-asserted. `known_tags()` continues to offer the vocabulary before a new label is minted, which is where "suggest the same intelligently" already comes from. No model coins a tag (D7); tag totals still deliberately do not sum, and still say so.

---

## The three cycles

**Cycle 1 — the interview exists at all.**
*Open state:* every question is single-turn; a tier-2 yes applies immediately; a tier-3 tap can mint `Assets:Other:Unnamed` into the curve.
*Implementation:* the schema pack (seeded, jurisdiction-tagged, US + India) and its loader · essential/optional/`unlocks`/`opens` · the derived interview and its queue source · attribute rulings · the Proposal-only account creation with a name the person saw · `resolve_account` ambiguity surfaced in the confirmed sentence · pending state and its return rule · net worth's disclosed gap.
*Done-tests:* a tier-2 yes returns a Proposal and creates nothing until confirmed · a tier-3 asset answer with an empty hint asks rather than mints · the next essential ranks *with* other questions, not ahead of them · "not now" leaves the ranked queue and returns only on a new event touching the subject or on opening pending · an interview with all essentials settled yields nothing further · a kind with no schema raises no question and records the gap · an asset with an unfilled essential cost is a disclosed gap, neither zero nor omitted · **no new event type: a vault built before this slice replays identically** · a figure in an attribute answer that is absent from the person's words is refused.

**Cycle 2 — the model drives, inside the vocabulary.** Everything in ADR-012.
*Done-tests:* a build-failing test rejects any envelope field outside the whitelist · an off-schema key is dropped, the deterministic next renders, and the drop is **counted** · generated wording carrying a fact absent from the envelope is rejected and counted · **the refusal rate is reported** — a validator that never refuses is not validating · a rendered queue fires zero model calls (no speculation) · every call captured under `phase="interview"` with prompt version and model · measured against cycle 1: questions-to-settle, essentials unfilled at termination, off-schema rate, confidently-wrong rate.

**Cycle 3 — the rest.**
*Implementation:* multi-proposal `interpret` so one sentence yields several facts · attribute upgrade `asserted → corroborated` on a document · account-scope tags · the generated-schema promotion path.
*Done-tests:* the five-fact sentence yields five proposals and no figure the person did not say · a later statement upgrades an attribute without rewriting ruling history · an account tag reaches movements touching the account, union with the other scopes, and tag totals still do not sum and still say so · a coined tag is rejected; a copied one is accepted · an unreviewed generated schema is flagged as such and promotion requires a read.

**Standing gate on all three:** a slice is not done until it has run on a real document and a real answer. Every mini-slice worth having came from one; the one declared done without one had two defects.

## Boundaries (what this must never become)

- **Never a chat agent.** The interview is a bounded form with an intelligent order of asking. It terminates. There is no open loop and Slice 9 — Viva speaks — stays separate and unbuilt.
- **The model never chooses a subject**, only an order and a wording, and only from a reviewed set.
- **The model never supplies a value, picks an account, emits a figure, or writes.**
- **Never a nag.** Deferred questions go quiet; they return on evidence or on the person's own action, never on a timer.
- **A schema never describes how to read a document.** That is the parser anti-goal wearing a new hat.
- **A schema question may never ask for an identifier.** No account number, policy number, address, UAN, PAN, SSN, VIN, registration number or plate. An interview that collects identifiers becomes the most attractive file on the machine, and none of them make an answer better — a nickname does everything an identifier would do here. Enforced as a lint over the pack, not remembered.
- **No question whose answer the product could not use**, and none the person could not honestly be expected to know — ask for the document instead.
- **No amount leaves in an envelope**, ever, without an ADR-012 amendment.

## Impact pass (order + amendments)

Reading-guide slot: section 3, immediately after [viva-persona-and-interview.md](viva-persona-and-interview.md), whose P3 this supersedes and absorbs.

Amendments owed as cycles build: **viva-persona-and-interview.md** — P3 is now this document; its open question on decline semantics for optional attributes is answered by D5 · **the-question-queue.md** — a new source, and questions gain a next step · **where-the-intelligence-goes.md** — the implication block gains a schema reference and the tier-2 proposal gains a successor · **net-worth.md** — the disclosed-gap rule for an asserted asset with unfilled essentials · **categories-and-tags.md** — account scope added; D2 (no model-minted tags) explicitly unchanged · **learning-mode.md** — the Asset primitive's deferred block is now scheduled here · **archived/the-repair-list-2026-07.md** (now historical) — A4's recommendation is superseded by D1/§4; record it rather than leaving two answers on the record · **implementation-roadmap.md** — the capability paragraphs, once built · **decisions/README.md** — the ADR-012 row.

## Open questions

- ~~The seeded pack's exact membership.~~ **Answered** — the appendix below, nine kinds in the seed and five named for arrival. Written as drafted; a strike-and-add pass is a data edit to `schemas-v1.json`, and a released pack is frozen by digest, so a change is a new pack version.
- **Pending, on the surface.** Vishnu's sketch is a small marker — a star or a question mark — saying something else is waiting. Deliberately parked: it belongs to the presentation layer's own design conversation, and D5 only requires that pending state *exists* and is reachable.
- **Does `opens` create the second account immediately, or ask first?** A mortgage opened from a property answer is still an account coming into being, so X3 says it is confirmed — but confirming twice in one breath may read as friction. Worth deciding on the first real run rather than now.
- **Attribute decline for essentials.** An optional decline is settled (D5). An *essential* declined leaves the interview terminated but the asset gapped forever — correct, and it should be visible in coverage rather than merely true.

---

# Appendix — the seed pack

**Drafted 2026-08-01. Awaiting Vishnu's strike-and-add pass before the Builder writes pack data.**

Two jurisdictions in v1: **`us`** and **`in`**. They are in from the first entry rather than added later, because a pack written for one country and internationalized afterwards is exactly the migration pain I5 exists to prevent — and because the author's own financial life spans both, so the omissions are checkable rather than theoretical.

Every kind below states its **essentials** (which rank, terminate the interview, and gate net worth), its **optionals**, what a "yes" **opens**, and what document would **corroborate** it — with the country deltas called out, because the delta is the whole point of tagging.

**Reading the deltas.** Where the two countries differ it is almost never a difference of *concept* — it is the same fact attested by a different instrument. A US mortgage's Form 1098 and an Indian home loan's provisional interest certificate do the same job. A US certificate of deposit and an Indian fixed deposit are the same instrument. That is the shape a jurisdiction-tagged pack should have: one kind, two attestations. Where the *concept* genuinely differs — a PPF lock-in, a sovereign gold bond — it earns a jurisdiction-scoped field rather than a separate kind.

## Tier A — the seed (nine kinds)

**1 · `property`** — `Assets:Property:<nickname>`
*Essentials:* purchase_price · purchase_date · use *(occupied | rented | land)* · financed *(yes → **opens** `home_loan`)*
*Optionals:* ownership_share · improvements_since_purchase
*Corroborated by:* **us** closing disclosure, settlement statement · **in** sale deed, registration and stamp-duty receipt, builder demand letters
*Note:* the nickname is the name; the address is never asked for and never stored. `use: rented` is an attribute rather than a separate kind, because a rented property differs in what it *earns*, not in what it *is*.

**2 · `vehicle`** — `Assets:Vehicles:<nickname>`
*Essentials:* purchase_price · purchase_date · financed *(yes → **opens** `vehicle_loan`)*
*Optionals:* description label
*Corroborated by:* **us** bill of sale, title · **in** dealer invoice, registration certificate

**3 · `home_loan`** — `Liabilities:HomeLoan:<lender>`
*Essentials:* lender · original_amount · start_date · secures *(link → `property`)*
*Optionals:* rate · term · instalment_amount · prepayments_made
*Corroborated by:* **us** mortgage statement, Form 1098 · **in** sanction letter, provisional interest certificate, amortisation schedule
*Note:* this is the kind that makes the compound-payment answer possible at all, and the one whose corroborating document the expectations registry already asks for.

**4 · `vehicle_loan`** — `Liabilities:VehicleLoan:<lender>`
*Essentials:* lender · original_amount · start_date · secures *(link → `vehicle`)*
*Optionals:* rate · term · instalment_amount
*Corroborated by:* **us** retail instalment contract, servicer statement · **in** sanction letter, hypothecation endorsement

**5 · `card_account`** — `Liabilities:Cards:<issuer>`
*Essentials:* issuer · nickname
*Optionals:* apr · annual_fee · credit_limit · rewards_programme
*Corroborated by:* card statement (both)
*Note:* essentials are thin on purpose — the balance comes from statements, so nothing here gates net worth. This is the persona guide's existing nudge library, arriving as pack data.

**6 · `deposit_account`** — `Assets:Bank:<institution>`
*Essentials:* institution · sub_kind
*Sub-kinds:* **us** checking · savings · certificate of deposit · **in** savings · current · fixed deposit · recurring deposit
*Essentials when the sub-kind is a term deposit (CD / FD / RD):* principal · maturity_date · rate
*Corroborated by:* account statement; deposit advice or receipt for a term deposit
*Note:* a US certificate of deposit and an Indian fixed deposit are the same instrument under two names — one kind, one sub-kind vocabulary, no second code path.

**7 · `brokerage_account`** — `Assets:Brokerage:<institution>`
*Essentials:* institution · tax_treatment *(taxable | tax-advantaged)*
*Optionals:* purpose — personal, never enriched, never shared (T9)
*Corroborated by:* **us** brokerage statement, 1099-B, 1099-DIV · **in** demat holding statement, contract notes, capital-gains statement, annual information statement

**8 · `retirement_account`** — `Assets:Retirement:<scheme>:<institution>`
*Essentials:* scheme · institution · contribution_source *(link → employer / pay stub)*
*Scheme vocabulary:* **us** 401(k) · 403(b) · Traditional IRA · Roth IRA · HSA · **in** EPF · PPF · NPS · gratuity · superannuation
*Optionals:* employer_match · vesting · lock_in *(India-scoped: PPF's fifteen years and NPS's exit age are structural facts with no US analogue, and an answer path that assumes withdrawal-at-will would be wrong here)*
*Corroborated by:* **us** plan statement, Form 5498, 1099-R · **in** EPF passbook / UAN statement, PPF passbook, NPS CRA statement
*Note:* this is the entry that most tests I5. A single `401k` kind would have been the natural US-shaped mistake.

**9 · `precious_metals`** — `Assets:Valuables:<nickname>`
*Essentials:* acquisition_cost · acquisition_date · form *(jewellery | coin | bar | sovereign gold bond)*
*Optionals:* weight · custody *(home | locker | dematerialised)*
*Corroborated by:* **in** purchase invoice, SGB allotment certificate · **us** dealer invoice
*Note:* included deliberately as the pack's own proof that it is not US-shaped. Household gold is a material asset class in an Indian financial life and a list written from the US would never have contained it. The sovereign gold bond is the sharper case — it pays interest and matures, so it is not physical gold wearing a different label, and a schema that treated it as one would be wrong rather than merely coarse.

## Tier B — named, not written; they arrive on first encounter (D3)

- **`education_loan`** — a liability with an interest-deduction story in both countries and a moratorium period in India.
- **`personal_loan`** — the residual liability kind; deliberately last, because everything routed here is something a better kind would have caught.
- **`business_interest`** — equity in a private company, LLC or partnership. Valuation is the hard part and it is exactly the case where `estimated` earns its keep.
- **`agricultural_land`** — India-specific, and separate from `property` because its tax treatment differs enough that folding it in would make one of the two wrong.
- **`insurance_policy`** — **blocked, and stated as such.** Protection-only cover is not an asset; a policy with a surrender value is. India's endowment and unit-linked policies make that split load-bearing rather than academic. The document-coverage list already flags an insurance declaration as the thing that forces the Provision question, and that question should be settled on its own before a schema encodes an answer to it by accident.

## What the appendix does not settle

The **first-encounter generation path (D3) is what makes this list adequate rather than complete.** Nine kinds do not describe a financial life; they describe the part of one the author can check against real documents this month. Everything else arrives by being met, drafted, flagged unreviewed, and promoted on a read — which is the same bargain the merchant catalog and the expectations registry already run on.

---

# As built — cycle 1

**How a schema finds an account.** The spec assumed an account's path names its
kind. It does not: an ingested account is `acct:<institution>:<last4>`, and an
account a tier-2 ruling opens is `<Root>:<group>:<name>` where the group is a
word a model wrote at enrichment. Ruled by Vishnu, 2026-08-01: resolve by the
**ledger's account kind**, with three sources of evidence, strongest first.

| | Evidence | Applies to |
|---|---|---|
| 1 | the path's `account_shape` | accounts the interview created |
| 2 | the **document types** an issuer produced for it (`document_types`) | anything ingested |
| 3 | the **ledger's account kind** (`account_kinds`), *only when one kind claims it* | the rest |

Step 2 names types from the ingestion pipeline's own registry rather than a
second vocabulary, and the lint refuses an alias — a document resolves to its
canonical type, so an alias would match nothing. Step 3 refuses an ambiguous
answer: a loan and a card are both `liability`, so that word alone resolves
nothing and the interview records the gap instead of asking a question built on
a guess.

**A classified document answers the question its own type settles.** A checking
statement has already said the account is a checking account, so
`answered_by_document` (pack data: document type → answer) marks the question
answered and the queue stays quiet. Without it the first thing the queue asked
about a bank account was the thing its own statement had just said.

**Two amendments to the decisions.**

- **D6 gains a pack field.** Which essential gates net worth is
  `gates_net_worth` in the pack, and which one dates the carried figure is
  `dates_net_worth`; the curve does not infer either from an answer type. An
  asserted asset with a stated cost is a line *at cost*, graded `verified` and
  origin `asserted`, and it **replaces** any cash-derived line for that account
  rather than adding to it.
- **The attribute value is a new field on `RulingRecorded`, and the only
  write-side addition.** `value` and `currency`, at attribute scope alone. A
  figure it carries must appear among the numbers the person wrote, a
  non-finite value is refused, and a negative one is refused. Attribute rulings
  are kept as a **history**, so a correction does not reach backwards into an
  earlier point on the curve. *(Amended 2026-08-12: `value` is no longer at
  attribute scope alone — a `rhythm` ruling carries the periodicities a person
  confirmed. The fence around it is unrelaxed and net tighter: an attribute
  value is open, so it is guarded against a figure the words do not carry; a
  rhythm value is a closed vocabulary, so it is guarded against any word outside
  it, at construction. Every other scope still refuses a value outright.)*

**Also built, beyond the cycle-1 list:** a pending list the person can open
(D5 required only that pending state exist and be reachable), and the confirmed
sentence now names an existing account it guessed at rather than choosing one
silently.

**Not built, and owed.** An attribute ruling does not stamp the schema pack
version the way the persona and prompt packs stamp theirs. D9's jurisdiction as
a graded attribute with the country tag derived is not implemented — the field
is stored on the account and defaults to empty, meaning nobody has said. A
retirement account is unreachable from a document, because `401k_statement` and
`ira_statement` alias to `brokerage_statement`. Two conflicting document types
on one account degrade to step 3 rather than refusing — defensible, not yet
ruled. And **cycle 1 has not run on a real document and a real answer**, which
the standing gate requires before it is called done.
