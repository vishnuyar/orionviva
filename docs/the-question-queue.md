# The Question Queue

**Status:** BUILT (`product/viva/questions.py`, `python -m viva.ask`, `/api/questions`) · **Last updated:** 2026-07-25 · **Block seeded:** the **Question** primitive — the learning loop's front door. Sequel to [honest-aggregates-and-the-learning-loop.md](honest-aggregates-and-the-learning-loop.md).

**Invariants touched:** T1 (a question carries the evidence it rests on) · T2 (questions are raised deterministically — a model never decides *whether* to ask) · **T4 (an answer is an append-only ruling event; we reuse the writers we already have)** · X2 (an unanswered question leaves the figure visibly incomplete, never silently resolved) · principle 5 (**serve, don't overwhelm** — the failure mode is asking about everything) · principle 6 (you direct the pace) · principle 7 (autonomous where safe, deferential where it counts). Extends [verification-findings-and-correction.md](verification-findings-and-correction.md)'s Rung 2 ("the human, asked well") from one document to the whole vault.

---

> _Forward note, 2026-07-25 — the first real run put two questions in front of the author that its three answers could not hold: a mortgage payment (three things at once) and a car purchase (something he now **owns**). The diagnosis is that a **NATURE** question's option set was an impoverished stand-in for what the counter-leg *is*. **Rulings in your own words** ([from-your-words-to-the-ledger.md](from-your-words-to-the-ledger.md)) widens the answer space to the four majors — expense / asset / liability / income — reached through a sentence rather than a button. **The queue itself does not change**: framing, ranking by consequence, scope, and the tail summary are all untouched, and buttons remain the fast path and the no-model fallback. Free text becomes an additional way to answer a question the queue already asked._


## Why now

Movement nature made the spending figure honest and, in doing so, **quantified what the system doesn't know**: on a real vault, a third of reported spending rests on a category hint alone, alongside dozens of unknown merchants and a handful of unresolved transfer suggestions. The system knows precisely what it is unsure about and has no way to work through it with the person.

It also already asks four kinds of question — built four separate times:

| Question | Built in | Event it writes | Generalizes to |
|---|---|---|---|
| Whose account is this? | account identity resolution | `AccountAliasConfirmed` | every future statement of it |
| Are these the same money? | transfer links | `TransferLinked(by=human)` | that pair (patterns learned) |
| What is this merchant? | the merchant catalog | `MerchantCategorized/Enriched` | every transaction from it |
| Is this spending, or moving? | movement nature | `CategoryAssigned(nature=…)` | that movement |

Four implementations of one primitive, four queues, four cards in the surface. **The questions Viva asks — and the rulings they produce — are the product** (CLAUDE.md: *memory of the user is the moat*). This slice gives them one front door.

## What a Question is

A **read-side projection** over ambiguity the system already records. No new event type, no ingest change (a generic `Ruling` event waited on a fifth question type to earn it, and has since arrived as the generic scoped ruling).

```
Question(
  id,             # stable + derived from what it is about (so it doesn't churn)
  kind,           # identity | transfer | merchant | nature | reconciliation
  text,           # Viva's voice, deterministic template (no model call)
  why,            # the evidence: what we saw that makes this uncertain (T1)
  consequence,    # {amount, currency, count} — how much money the answer moves
  scope,          # "one" (this movement) | "pattern" (everything like it)
  options,        # the answers offered, each mapped to an existing writer
  refs)           # the movement keys / doc ids / merchant the answer applies to
```

`open_questions()` returns them **ranked by consequence, descending.** Answering routes to the writers that already exist (`confirm_transfer`, `assign_category(nature=…)`, `assign_merchant_category`, `apply_identity_ruling`) — this slice adds no write path.

## The three rules that keep it a butler, not a chore list

**1 — Leverage ranking.** Ask the question that moves the most money first. This is the merchant-catalog lesson turned on the questions themselves: on the real vault, two questions (a vehicle purchase and a property closing) resolve roughly half the outstanding uncertainty. A hundred small ones can wait forever without harming the picture.

**2 — Scope: one ruling should clear many.** A question is raised at the **most general unit that is still honest**. Nature questions group by *merchant key* — the brand a resolution layer named, and the normalized descriptor only where none could (amended 2026-08-01) — the unit that already generalizes retroactively and forward (the merchant catalog) — so answering once settles every transaction from that counterparty, past and future. A genuine one-off (an ambiguous transfer pair) is scoped to itself.

**3 — Silence by ranking, not by hiding.** Rather than a hard materiality threshold (which would be a currency- and jurisdiction-shaped guess — I1/I5), the queue **surfaces the top N and summarizes the tail**: "plus 34 smaller items worth X in total — ask me if you want them." Nothing is hidden, nothing is pushed. An unanswered question leaves its figure provisional and *labelled* (movement nature already does this), so silence degrades the picture's precision, never its honesty.

## Viva's voice

Question text is a **deterministic template**, not a model call: the queue must be reproducible, free, and offline-testable, and a model that phrases a question could smuggle a claim into it. _Amended 2026-07-27 (the voiced queue): the templates now live in the persona pack (`viva/persona/`, [viva-persona-and-interview.md](viva-persona-and-interview.md)) rather than in `questions.py` — the rule stands unchanged; a lint test guarantees a phrasing can only place fields the deterministic intent supplied. The persona pack also made "not now" an answer: a declined question is suppressed while its stake (amount, count) is unchanged and returns on new evidence._ Templates carry the figure, the evidence, and the choice:

> "On 3 March you moved $2,400 to Chase. I've treated that as a payment to your own card rather than spending — is that right?"
> "You have 12 transactions with FIRST AMERICAN TITLE totalling $23,512. Is that money spent, or a property purchase — something you now own?"

Slice 9 (Viva) will re-voice these through the persona; the *content* — figure, evidence, options — stays deterministic. This is where the unwritten persona work (C1 uncertainty language, C3 when-to-speak) gets its first concrete surface.

## Scope — the build

- `Question` + `open_questions()` in the projection (ranked, grouped, with consequence).
- Nature questions grouped by merchant key; transfer/identity/merchant questions from the existing sources.
- A `python -m viva.questions` CLI — the ranked list against a real vault, the way `debug.vault` works today.
- The surface: one **"what Viva needs from you"** panel, ranked, replacing the four disconnected review cards (the existing endpoints answer them unchanged).
- Answering is idempotent by construction: a ruling changes state, so the question disappears from the next projection.

## Done criteria / tests

- Questions are ranked by consequence; the highest-value question is first.
- A nature question scoped to a merchant, once answered, settles **every** transaction from that merchant — past and future — and the question does not return.
- A question carries its evidence and the figure it moves; an unanswered question leaves the affected total provisional and labelled.
- The tail is summarized (count + total), never silently dropped.
- Answering routes to the existing writers — no new event type is introduced by this slice.
- Question ids are stable across projections (the same question doesn't churn between reads).
- Existing identity / transfer / merchant / nature tests stay green.

## As-built (2026-07-25)

Three decisions the build forced, all resolved toward the reversible option:

- **What raises a *nature* question.** The spec advertised a vehicle purchase and a property closing as the two highest-leverage questions — but neither is `provisional`; both are confidently categorized and counted as spending. So "ask about provisional items" would have missed exactly what was promised. **A nature question is raised wherever nature rests on weak evidence** (a category hint, rung 4, *or* the plain default, rung 5) for a merchant we already have a category for — and **leverage ranking is the filter**. No list of "capital-looking" categories, which would be jurisdiction-shaped guessing (I5). Big-ticket ambiguity floats up; a grocery run sinks. An *unknown* merchant raises the more fundamental MERCHANT question instead, so the two never collide.
- **Alongside, not replacing.** The four existing review cards stay for this pass; the queue ships as the ranked front door that says *which to do first* and carries the answering actions. Rebuilding four working confirm flows in one go was the higher-risk path; retire them once the queue's answering is proven.
- **Merchant-scope nature rides the existing attributes bag.** `merchant_enriched(attributes={"nature": …})` — no new event type and no new field, so the write side stayed untouched. The nature derivation's rung 3 now reads a ruling from the movement overlay *or* the merchant catalog, which is what makes one answer settle a counterparty past and future. Peer descriptors are excluded from merchant-scope rulings (`is_shareable`) and stay per-movement, per the local-categorization decision.

Built: `Question` + `open_questions()` in `product/viva/questions.py` (held documents → transfer suggestions → unknown merchants → weak-nature merchants, ranked by amount with a stable id per subject); `rule_merchant_nature` writer; `python -m viva.ask` (read-only CLI); `/api/questions` + `/api/rule-nature`. Tests: `test_questions.py` (9) covering ranking, tail summary, both scopes, one-ruling-settles-and-stops-asking, id stability, and that the event vocabulary is unchanged. Full suite 303 green.

## Known limitation: questions it should not ask (added 2026-07-25)

The first real run asked two questions that have no correct answer among the options offered — a **compound payment** (a mortgage is interest *and* principal *and* escrow at once) and a **capital purchase** (a car, which the ledger cannot yet represent as a thing you own). Forcing a nature ruling on either produces a wrong figure in one direction or the other. The fix is not a better option list: it is to recognize these cases and *say what is missing* — the document that states the split, or the Asset primitive — rather than inviting a guess. Recorded in [learning-mode.md](learning-mode.md); deferred by decision.

## Known limitation (and what the generic scoped ruling fixed)

A nature ruling generalizes at the merchant unit. A *category-shaped* pattern ("anything in title-and-escrow is a capital purchase") could not be recorded as one rule — answering applies it to the movements at hand. Fixing that needs a ruling that carries its own scope, which is exactly the **generic scoped ruling** — deferred until a fifth question type (Slice 8's obligations, or Slice 11's loans) proved the shape, and since arrived as `RulingRecorded` carrying `scope` + `same_as`. Until it landed the queue re-asked about genuinely new merchants, which is honest, if slightly repetitive.

## Deferred

The generic `Ruling` event and category-scoped rules — **since arrived** as the generic scoped ruling (`RulingRecorded` with `scope` + `same_as`). Model-phrased questions (Slice 9). Proactive *timing* — deciding when to interrupt rather than wait to be opened (Slice 8's trigger). Learned auto-apply for peer descriptors ([local-categorization-and-custom-categories.md](local-categorization-and-custom-categories.md)).

## A source with a next step (2026-08-01)

The queue gained a seventh source: the **interview**, one question per account whose kind the schema pack can resolve — see [the-interview-and-the-schema-pack.md](the-interview-and-the-schema-pack.md). It is the first source where answering produces *another question*, and it changes nothing about the queue itself: an interview question is ranked with everything else by the cash a ruling has put against the account, so it never outranks a larger finding for being new, and an account whose money its statements already explain carries a stake of zero rather than borrowing its balance.

Two consequences worth knowing. **A declined interview question is still built** — the decline filter is what keeps it out of the ranked list — so it can be found in the pending list and returns when the movements touching its account change. And `open_questions` now returns a `pending` count alongside the tail; `pending_questions` returns the same questions the decline filter removed, built by the same builders so the two lists cannot drift.
