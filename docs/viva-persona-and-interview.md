# Viva: the Persona & the Interview — how questions get a voice, and answers build a profile

**Status:** ✅ **P1 (Slice 6.10, the voiced queue) BUILT 2026-07-27** — persona pack + one-question-at-a-time + decline events + the 9a free-text box on the surface at last · ✅ **P2 (Slice 6.11, the expectations engine) BUILT 2026-07-27** — with pack-v2, the model-drafted wording pass in [Viva's own manner](viva-persona.md). P3 (asset interview) specced, next · **Created:** 2026-07-27 · **Origin:** Vishnu, opening the persona phase with his persona sketch (now [viva-persona.md](viva-persona.md)) attached: *"we should be able to utilize the LLMs to take answers from users and at the same time use it to frame our questions intelligently… such as if a document fails arithmetic or if we get a merchant related to mortgage, what questions we can ask to get more details and fill in the blanks and at the same time start building a full picture of the user's financial profile."* · **Blocks seeded:** the **persona pack** (voice as versioned data) · the **expectations engine** (documents pursue documents) · **attribute schemas** (an entity's blanks as ranked questions) · the **decline event** (settled → silence, for questions).

**Invariants touched:** **T2** (a model may phrase and interpret; it never supplies a figure or does arithmetic — every number in a question comes from the deterministic finding behind it) · **T4** (every answer, decline, and inferred expectation is an append-only event; the person's words stored verbatim) · **T9** (the persona pack, attribute schemas, and expectation registry are impersonal world knowledge — shareable; every answer is personal — vault only) · **X2** (a question the system cannot honestly ask is not asked; an unmet expectation is visible quiet state, never a nag) · **I5/I6** (schemas and expectations are jurisdiction-tagged packs, not US-shaped code) · principles **5** (serve, don't overwhelm — one question at a time), **6** (you direct the pace — "not now" is an answer, and it is remembered), **8** (keep the soul — warmth is load-bearing, so it is versioned data, not incidental copy).

---

## The one sentence

**Viva decides *how* to ask, never *what* to ask** — the queue already decides what, deterministically, ranked by consequence; the persona is a rendering-and-interviewing layer over that machinery, plus two new question *sources* (expectations, attribute blanks) that feed the same queue.

## What this is the sequel to

Four positions, already settled, that this design builds on and must not undo:

1. **Speak only when spoken to** ([experience-vision.md](experience-vision.md), 2026-07-20). Viva never initiates; everything she notices is quiet dashboard state. The persona's "one question at a time, when the context is right" ([viva-persona.md](viva-persona.md)) *is* the queue's consequence ranking — the context machinery already exists.
2. **Intelligence at the question, not the answer** ([where-the-intelligence-goes.md](where-the-intelligence-goes.md), Slice 6.8). Three tiers: silence / informed proposal / real question. The persona changes the *words* of tiers 2 and 3; it never promotes a movement between tiers.
3. **Model as interpreter, person as ratifier, code as applier** ([from-your-words-to-the-ledger.md](from-your-words-to-the-ledger.md), Slice 9a). The one place a model touches an answer is parsing intent into a Proposal — never a figure. This boundary survives everything below, unchanged.
4. **A question the system cannot honestly ask is not asked** ([learning-mode.md](learning-mode.md)). The mortgage lesson: when the person cannot know the answer, ask for the *document* that does. The expectations engine below is that lesson made systematic.

## The decisions (Vishnu, 2026-07-27)

| | Decision | Why |
|---|---|---|
| **D1** | **The butler is Viva, as defined in [viva-persona.md](viva-persona.md).** The persona guide's traits, principles, question content and "I don't know" handling are the standing definition; the name and identity are Viva (Orion + ViVa; the docs already say *she*). | The guide is seed content for data packs, not code. |
| **D2** | **Phrasebook now, hybrid later.** The LLM is a *copywriter at design time*: it writes and refreshes a reviewable, versioned template library (the persona pack); runtime fills slots deterministically. Live per-question phrasing is not built until real use shows specific moments where templates demonstrably fall short — then it enters like any model surface: probated, evaluated, guarded. | Intelligence upstream — impersonal, batched, cached (the enrichment lesson). Every sentence Viva can ever say is reviewable before she says it; the failure mode of a template is *stiff*, never *false*. The 9a forward note (a small local model phrasing in the user's own tone) remains the live path's true home. |
| **D3** | **Cards + one question at a time.** Persona v1 lands on the existing surface: the question area shows ONE question (with "next" and "not now"), voiced from the pack, each carrying the 9a "tell me in your words" box. The real presentation layer remains its own upcoming design conversation — held *after* the persona pack exists, because the soul is load-bearing and the real surface should be designed around Viva, not have her added to it. | The pack, phrasing, events and endpoints survive into any future surface; only the pixels are throwaway, and 6.9 made the pixels deliberately cheap. |
| **D4** | **Sequence: voice → expectations → asset interview** (P1 → P2 → P3 below), spec'd in this one doc, built as three slices. | P1 is small and everything after it comes out voiced; P2 is the highest-leverage move for the real vault (one document resolves thirteen transactions); P3 touches the write side — the expensive, one-way side — so it gets the most design care and goes last. |

## The five blocks

### 1 · The persona pack — voice as versioned data

Everything Viva says lives in `product/viva/persona/` as versioned assets, under the prompts-as-files discipline (a test keeps persona text out of code, exactly as `test_no_prompt_text_lives_in_code` does for prompts). The pack has three kinds of entry:

- **Phrasings**: one per (question kind × moment), with named slots. The queue's deterministic intent — kind, refs, amounts, the finding — is the only thing that may fill a slot. *A phrasing may not introduce a number, a merchant, or a claim that is not in its inputs*; a lint test enforces it mechanically (every `{slot}` must name an intent field).
- **Moments**: welcome (empty vault), return-after-break, after-a-session, reassurance ("you can stop any time"), the "I don't know" responses ("not essential — we can move on"). The persona guide's relationship lines ([viva-persona.md](viva-persona.md)).
- **Tone rules**: the traits (patient, wise, discreet, polite; addresses the user by name; explains the benefit when asking — "if you share the rate, I can show your true borrowing cost"). These govern how new phrasings get written, including by the copywriter model.

The pack is impersonal by construction (T9): it contains no user data, so it is shareable, reviewable in a PR, and — later — swappable (a terser Viva, another language: I5's i18n pressure lands here naturally, since a pack is exactly the unit a translation replaces).

### 2 · The interview engine — three sources, one queue

The queue stays the single front door; it gains two new question sources beside the five it has:

- **Expectation-driven** (P2): the [knowledge-and-expectations.md](knowledge-and-expectations.md) three-tier design, built for real. The registry entry fires deterministically on evidence already in the ledger (a merchant enriched `loan_payments/mortgage` → a mortgage account exists → a statement and a 1098 exist somewhere); the unmet expectation becomes a queue item ranked like any other — by the money it would settle. The mortgage ask outranks nearly everything: thirteen provisional transactions, one document.
- **Failure-driven**: a reconciliation finding already names the flagged figure and the candidate rows deterministically. The persona phrases *that finding* — "this statement doesn't add up by {gap}; the figure I doubt is {row}" — through a template. No new intelligence, no model; the smarts are already in the finding ladder ([verification-findings-and-correction.md](verification-findings-and-correction.md)). If real use shows findings the templates can't carry, that is D2's evidence for the live path.
- **Attribute-driven** (P3): an entity with a schema has blanks; each blank is a candidate question with a consequence rank and an *optionality* flag (per the persona guide: the APR is optional; the financed amount is not, because net worth is wrong without it). Settled attributes → silence, the 6.8 rule applied to profile data.

### 3 · The listener, extended — many facts per sentence

9a's interpret handles one ruling per sentence. "I bought the car for X, put Y down, financed the rest at Z% for 60 months" is an asset, a liability, and three attributes — five confirmable proposals from one sentence. The extension: interpret may return a *list* of proposals, each individually confirmed (or edited) before its writer runs; the sentence stays stored verbatim so a better model can re-derive more later (already the 9a rule). The eval extends with multi-fact cases; the disqualifier stays the same — any fabricated amount or split fails the model outright.

### 4 · The profile substrate — where answers land

- **The Asset primitive** ([learning-mode.md](learning-mode.md)'s deferred block, now scheduled): a general asset (vehicle, property, valuables) recorded at **cost**, valuation class `estimated` — never `measured`, because no issuer attests it. 9a already laid the substrate: ruling-created accounts, the `Liabilities:` root, valuation classes from Slice 6.
- **Attributes as events**: an attribute answer (rate, term, purchase date) is a scoped ruling — `RulingRecorded(scope="attribute", subject="<account>:<attr>", …)` — graded `asserted`, upgraded to `corroborated` when a document states the same fact (the net-worth D3 pattern, applied to every attribute). No new event type; the generic scoped ruling earns another scope.
- **Attribute schemas as data**: `vehicle: {purchase_price!, purchase_date!, financed_amount!, rate?, term?}`, `card_account: {apr?, annual_fee?}` — jurisdiction-tagged pack entries (I6, the fourth pack after benchmarks, taxonomy, knowledge). A schema states what exists and relates; it never says how to parse anything.

### 5 · Pacing and the memory of the conversation

- **The decline event.** "Not right now" and "I don't know" become an event: question key, what was declined, when. Declined questions leave the queue and stay silent until *new evidence* arrives on the same subject (a new statement, a new enrichment) — never on a timer alone. This is settled → silence, applied to questions; it also finally gives the surface's `dismiss` action a real flow (today it answers honestly that none exists).
- **One at a time.** The queue already ranks; the surface change is showing rank #1 with "next" and "not now" instead of a list. The tail stays summarized ("11 more, none urgent"), because hiding it would be a lie of omission.
- **Resumption.** "Welcome back — we can continue where we left off" is a moment phrasing over state the ledger already has (last session's answered count, the current top question). No session store; the events are the memory.

## The persona guide, mapped to its destinations

[viva-persona.md](viva-persona.md) is **seed content for data packs, not a spec for code** — the constitution ("code universal, specifics are data") applied to the butler herself:

| Persona guide section | Becomes |
|---|---|
| Personality traits, guiding principles | Persona pack tone rules (and they restate principles 5/6/8 — no conflict) |
| Onboarding flow (steps 1–6) | The empty-vault moment scripts; progressive disclosure already decided in experience-vision |
| Nudge library: card nickname, APR, annual fee | `card_account` attribute schema entries (+ phrasings) |
| Nudge library: income, transfer linking | Already built (Slice 4, Slice 3) — their questions get voiced |
| Nudge library: loan clarify-the-asset, extra payments | `loan` attribute schema + P3 interview |
| Nudge library: investment goal | An attribute (`purpose?`, optional, personal — T9: never enriched, never shared) |
| Unlocking advanced features | Phase 2/3 triggers — out of scope here, recorded as the pack's future `unlock` moments |
| Handling "I don't know" | Decline event + reassurance phrasings |

## The three slices

**P1 — The voiced queue** *(persona pack · pacing · decline events)*
Open state: questions are fixed strings in `questions.py`; dismiss has no flow; the queue renders as a list. Implementation: persona pack v1 (phrasings for the seven existing question kinds + moments), the pack loader with the no-new-facts lint, one-question-at-a-time surface, the decline event + its projection (queue filters declined-until-new-evidence). Done-tests: every question kind has a phrasing (a missing one fails the build, not the render); a phrasing slot naming a non-intent field fails; a declined question stays gone until a new event touches its subject, then returns; the verbatim moment texts render with the user's name.

**P2 — The expectations engine** *(registry · inferred accounts · document asks)*
Open state: the mortgage/1098 knowledge exists only in a design doc; the queue cannot ask for a document. Implementation: tier-1 mechanisms (expectation states as events, deterministic satisfaction by arrival-and-link), tier-2 registry seeded with only the vault's own instrument types (~6 entries: mortgage → statement + 1098; pay stub retirement deduction → 401k statements; brokerage → 1099; card → statement cadence), queue integration (an unmet expectation ranks by the money it would settle), coverage card shows expectation state. Tier-3 model suggestions deliberately deferred. Done-tests: the mortgage enrichment raises the expectation; the ask names the movements it would settle; uploading the document satisfies it and the queue goes quiet; a dismissed expectation does not resurrect from the same evidence.

**P3 — The asset interview** *(Asset primitive · attribute schemas · multi-fact listen)*
Open state: a car purchase can be ruled `asset` but has no attributes and no valuation class; multi-fact sentences lose everything after the first fact. Implementation: the general Asset at cost (`estimated`), attribute schemas as pack data, attribute questions in the queue (optional ones marked so), scope="attribute" rulings with document upgrade, interpret returning proposal lists. Done-tests: the five-fact car sentence yields five proposals and no figure the person didn't say; each confirmed attribute lands `asserted`; a later loan statement upgrades rate/balance to `corroborated` without touching the ruling history; net worth shows the car at cost from its ruling date; an optional attribute declined never returns without new evidence.

**Naming note.** These need slice numbers and the 9b collision taught us to assign them deliberately. Recommendation: **6.10 (P1), 6.11 (P2), 6.12 (P3)** — all three are the queue-and-learning family growing up, none is Viva *speaking* (9b stays reserved for the read direction). Vishnu rules.

## Boundaries (what this must never become)

- **Never a chat agent.** No open-ended conversation loop; the listener answers *questions Viva asked* plus the bounded "tell me in your words" box. 9b remains unbuilt and separate.
- **The model never decides what to ask.** Ranking is deterministic, forever. A model that picks questions could steer the interview toward what it wants to know.
- **No live phrasing until it's earned** (D2), and when it comes: probation, eval, and a validator that rejects any generated question containing a figure absent from its inputs.
- **Never a nag.** Declines are remembered; expectations are quiet state; nothing pings (the experience-vision rule, unweakened).
- **Schemas and the registry never describe how to read a document** — that is the parser anti-goal wearing a new hat.
- **A question that cannot be honestly asked is not asked.** The unanswerable-question test from learning-mode is the standing review gate for every new phrasing and schema entry.

## Impact pass (order + amendments)

Reading-guide slot: section 3, immediately after [viva-listens-and-speaks.md](viva-listens-and-speaks.md). Amendments owed as slices build: **the-question-queue.md** ("question text is a deterministic template" stays true; note templates move to the persona pack, and two new sources feed the queue — amend at P1) · **knowledge-and-expectations.md** (status → building at P2; the queue-integration decision lands there) · **learning-mode.md** (its two deferred threads are now scheduled: document-ask at P2, Asset at P3) · **viva-listens-and-speaks.md** (Stage B multi-fact proposals pulled into P3) · **experience-vision.md** (C1/C3 now have their design home: this doc) · **implementation-roadmap.md** (add 6.10–6.12 entries once numbering is ruled) · **document-coverage.md** (unchanged, but P2 turns its priority order into live asks).

## Open questions

- Slice numbers (naming note above) — Vishnu rules.
- The copywriter workflow: does the model draft phrasings in a PR the author reviews, or does the author write and the model only critiques? (Cheap to decide at P1.)
- Decline semantics for *optional* attributes: is "I don't know" a decline (silent until new evidence) or a soft skip (may return once, much later)? the persona guide implies the former; principle 6 suggests the person could choose.
- When the real presentation layer's design conversation happens — after P1 (Viva has a voice to design around) or after P3 (the full interview exists to shape it)?
- The voice/tone eval: correctness has the confidently-wrong rate; what measures "sounds like Viva"? (Probably the author's ear for a long time — say so honestly.)
