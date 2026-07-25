# The Question Queue (Slice 6.5, Move 2)

**Status:** Design spec — pre-build · **Last updated:** 2026-07-25 · **Block seeded:** the **Question** primitive — the learning loop's front door. Sequel to [honest-aggregates-and-the-learning-loop.md](honest-aggregates-and-the-learning-loop.md).

**Invariants touched:** T1 (a question carries the evidence it rests on) · T2 (questions are raised deterministically — a model never decides *whether* to ask) · **T4 (an answer is an append-only ruling event; we reuse the writers we already have)** · X2 (an unanswered question leaves the figure visibly incomplete, never silently resolved) · principle 5 (**serve, don't overwhelm** — the failure mode is asking about everything) · principle 6 (you direct the pace) · principle 7 (autonomous where safe, deferential where it counts). Extends [verification-findings-and-correction.md](verification-findings-and-correction.md)'s Rung 2 ("the human, asked well") from one document to the whole vault.

---

## Why now

Move 1 made the spending figure honest and, in doing so, **quantified what the system doesn't know**: on a real vault, a third of reported spending rests on a category hint alone, alongside dozens of unknown merchants and a handful of unresolved transfer suggestions. The system knows precisely what it is unsure about and has no way to work through it with the person.

It also already asks four kinds of question — built four separate times:

| Question | Built in | Event it writes | Generalizes to |
|---|---|---|---|
| Whose account is this? | Slice 1.5 | `AccountAliasConfirmed` | every future statement of it |
| Are these the same money? | Slice 3 | `TransferLinked(by=human)` | that pair (patterns learned) |
| What is this merchant? | Slice 5.5 | `MerchantCategorized/Enriched` | every transaction from it |
| Is this spending, or moving? | Slice 6.5 | `CategoryAssigned(nature=…)` | that movement |

Four implementations of one primitive, four queues, four cards in the surface. **The questions Viva asks — and the rulings they produce — are the product** (CLAUDE.md: *memory of the user is the moat*). This slice gives them one front door.

## What a Question is

A **read-side projection** over ambiguity the system already records. No new event type, no ingest change (Move 3 is where a generic `Ruling` event would go, and only once a fifth question type earns it).

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

**2 — Scope: one ruling should clear many.** A question is raised at the **most general unit that is still honest**. Nature questions group by *normalized merchant* — the unit that already generalizes retroactively and forward (Slice 5.5) — so answering once settles every transaction from that counterparty, past and future. A genuine one-off (an ambiguous transfer pair) is scoped to itself.

**3 — Silence by ranking, not by hiding.** Rather than a hard materiality threshold (which would be a currency- and jurisdiction-shaped guess — I1/I5), the queue **surfaces the top N and summarizes the tail**: "plus 34 smaller items worth X in total — ask me if you want them." Nothing is hidden, nothing is pushed. An unanswered question leaves its figure provisional and *labelled* (Move 1 already does this), so silence degrades the picture's precision, never its honesty.

## Viva's voice

Question text is a **deterministic template**, not a model call: the queue must be reproducible, free, and offline-testable, and a model that phrases a question could smuggle a claim into it. Templates carry the figure, the evidence, and the choice:

> "On 3 March you moved $2,400 to Chase. I've treated that as a payment to your own card rather than spending — is that right?"
> "You have 12 transactions with FIRST AMERICAN TITLE totalling $23,512. Is that money spent, or a property purchase — something you now own?"

Slice 9 (Viva) will re-voice these through the persona; the *content* — figure, evidence, options — stays deterministic. This is where the unwritten persona work (C1 uncertainty language, C3 when-to-speak) gets its first concrete surface.

## Scope — the build

- `Question` + `open_questions()` in the projection (ranked, grouped, with consequence).
- Nature questions grouped by normalized merchant; transfer/identity/merchant questions from the existing sources.
- A `python -m viva.questions` CLI — the ranked list against a real vault, the way `debug_vault` works today.
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

## Known limitation (and what Move 3 fixes)

A nature ruling generalizes at the merchant unit. A *category-shaped* pattern ("anything in title-and-escrow is a capital purchase") cannot be recorded as one rule today — answering applies it to the movements at hand. Fixing that needs a ruling that carries its own scope, which is exactly the generic `Ruling` event of **Move 3** — deliberately deferred until a fifth question type (Slice 8's obligations, or Slice 11's loans) proves the shape. Until then the queue re-asks about genuinely new merchants, which is honest, if slightly repetitive.

## Deferred

The generic `Ruling` event and category-scoped rules (Move 3). Model-phrased questions (Slice 9). Proactive *timing* — deciding when to interrupt rather than wait to be opened (Slice 8's trigger). Learned auto-apply for peer descriptors ([local-categorization-and-custom-categories.md](local-categorization-and-custom-categories.md)).
