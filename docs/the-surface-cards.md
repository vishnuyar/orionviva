# The Surface, Rebuilt as Cards

**Status:** **The page this specifies no longer exists (deleted 2026-08-06).** What survives is everything below about *what each kind of instrument must say* — the three honesty elements, and a liability speaking **owed** rather than showing a signed figure. That is still the decision, and it is now held where a figure is **measured** rather than where it is written. _(Corrected 2026-08-14. This said "now enforced in the renderer instead of in a card", which named a plausible home and is the reason nobody checked.)_ The one renderer, `viva/render.py`, writes an amount and not an instrument: no per-kind rule, and the word *owed* does not appear in it. What holds the rule instead is the vocabulary of what a figure measures: a liability's magnitude is emitted as **`owed`** and never as `balance`, by every read that emits one, so a clause asking about a balance can no longer be filled with a debt at all — it refuses. The scripted oracle in `answer.py` speaks both cases too, a card owed on as a debt and an overpaid one as money the card owes the person; until 2026-08-15 it took the absolute value and stated that credit as a debt. What no code settles is the **sentence**: its shape is committed before any read, so the planner cannot know it is about to name a liability, and what buys the ordinary question back is a shape carrying a clause for each case, dropping the one that did not apply. The shape prompt teaches that pattern; whether a live model follows it is not something any test here can establish. **And one case still reads wrong where a person would meet it (2026-08-15, open):** an overpaid card's figure is negative in the owed convention, so a debt clause bound with it comes out as *"You owe -USD 50.00 on ‹card›"* — the right word around a sentence nobody should read. It ships that way knowingly: the wrong *word* is gone, a rendering-time fix was ruled out for the reason above, and which clauses a live model writes is the one thing no test in this repo reaches. `test_shape.py::test_an_overpaid_cards_sign_survives_into_what_is_spoken` holds the sign and says in its own docstring that it does not hold the wording. Read this for the presentation semantics; they are an owed decision, not a shipped one. Do not read it for a surface. Decided 2026-07-26, shipped as `product/viva/web/static/{index.html,app.js}` and removed with the rest of the debug surface. · **Origin:** Vishnu: *"I feel that moving away from index.html created some bugs. Let us do away with React and come back to index.html, create a card for each type of instrument and decide what needs to be shown on that card."*

> _**Amended 2026-08-07.** The surface went because it was scaffolding that had begun costing verification findings of its own — a person shown an empty box, a figure rendered under the *browser's* locale rather than the vault's — and carrying it through the answer path's rewrite would have meant paying for it twice. `viva.ask` is the question direction's terminal path now, the shape `viva.speak` already had for answers; the engine it sat on moved to `viva/engine.py` before anything was deleted, so the door survived the page. The endpoint contract test went with the endpoints. **The real presentation layer is still an unheld design conversation**, and a third surface designed now would have been a fourth thing to throw away._

**Invariants touched:** **X1** (the machinery is invisible; the person sees money) · **X2** (every figure carries its as-of date and grade) · **T1** (a figure names the document behind it) · principle 5 (serve, don't overwhelm).

---

## Why we are reversing the React decision

The compiled surface chose **React + Vite** for "legibility to readers of a public repo and reliability of AI-written code," bounded by static build output. Reasonable then, and a two-way door by design.

The evidence since says the build step costs more than the framework saves:

**The artifact can silently lie.** `static/app.js` is compiled from `ui/src/`. If the build is not re-run, the surface serves last hour's product with no error, no warning, and no way to tell by looking. Checking required grepping the compiled bundle for feature strings.

That is the exact failure shape this project has spent a week finding everywhere else — **a stale artifact that reports success it has not earned.** In a repo whose discipline is *the artifact must not lie*, a compile step between the source and the running thing is a standing liability, and the surface is explicitly a debug tool that does not need one.

**Reversing a two-way door when the evidence changes is the process working**, not a retreat. Recorded here so the reasoning survives, and so nobody re-adopts a build step without answering this.

### What must survive the rewrite

- **The endpoint contract and its tests.** `test_surface_contract.py` asserts every endpoint is called and every overview field is rendered or deliberately excused. It reads the UI source as text, so it keeps working against plain JS — retarget the path, keep the assertions.
- **No CDN, no runtime dependency.** One `index.html`, one `app.js`, one `app.css`, served by the existing stdlib server.
- **Money is formatted, never computed, in the surface (T2).** The ledger decided the figure.

---

## The organising idea: one card per *kind*, not per document

The vault knows three issued account kinds — `depository`, `liability`, `investment` — plus accounts a **ruling** brought into being (`asserted`). A card is a *kind*, because that is what decides which questions make sense and which figures exist.

**Every card carries the same three honesty elements**, because they are the product:

1. **The figure**, with **its own as-of date** — never dressed as "current" (the valuation-class invariant).
2. **Its grade**, plainly: `corroborated` = a document attests it and the arithmetic checks; anything less says what is missing.
3. **What it does not include** — the `skipped` / `missing` lists net worth already produces. A card that silently omits is the lie of omission.

### Depository (checking, savings)

| show | why |
|---|---|
| balance + as-of date + grade | the answer to the only question people ask daily |
| **"as of" prominently when stale** | three of four real accounts were months behind the point they contributed to |
| this period's in / out | direction is the thing a balance alone hides |
| unanswered questions for this account | the queue, scoped |

### Liability (credit cards)

| show | why |
|---|---|
| **owed**, as a positive figure, the number on the bill | the ledger stores owed; net worth negates it. The card speaks the person's language |
| as-of date + grade | same rule |
| **credit balance called out** when the card owes *you* | rare, real, and the opposite of what a "balance" implies |
| statements not reconciled | the −2,640.27 conflict must be visible, not buried |

### Investment (brokerage)

| show | why |
|---|---|
| cash + Σ holdings = total, **as the statement's own identity** | it is the densest model-free cross-check in the product; showing it *is* the trust |
| each holding with its **measurement date** | a price is a measurement, never "current" (M1) |
| **activity NOT posted, and why** | a real statement had 24 cash movements withheld for want of an opening cash figure. Silence there is the worst option |
| unrealized change as a **derived view**, labelled | never a ledger fact |

### Asserted (a car, a house — from your own ruling)

| show | why |
|---|---|
| **cost, and the word "cost"** | what you paid, never what it is worth now |
| **when nobody has said what it cost: the question, not a figure** | added 2026-08-01. An unpriced asserted asset has no cost line at all — it is a disclosed gap in net worth carrying the question that closes it. A stated cost then **replaces** the cash-derived line rather than sitting beside it |
| `asserted` badge — your word | honest, and it is what the disclosure view will later filter on |
| **the document that would corroborate it** | provenance-based: the invoice, the 1098, the closing disclosure |

### The two cards that are not accounts

- **Net worth** — the curve. One point, its stalest input named, the provable subtotal, and what is not counted.
- **What Viva needs** — the question queue, ranked by consequence. **This stays the page's spine**: it is the learning loop's front door and the thing that makes the rest improve.

---

## Why a card must not trust the payload's shape

The rule that a card which throws cannot take the page down was written after one did. A single wrong assumption about the shape of one field in the overview payload replaced the *entire* surface with "I can't reach the ledger" — a message that was not merely unhelpful but false, since the ledger was fine and the page was the broken part. A surface whose whole job is to report honestly must never report its own defect as the engine's failure.

## Open questions for the build

1. **Does the queue sit above the cards, or beside each card?** Above keeps the ranking honest (consequence-ordered across everything); beside makes each card self-contained. Ranking is the more valuable property — start above.
2. **Tag and category controls live on the drill-through, not the card.** A card is for reading; answering is a deliberate act.
3. **One page or per-account pages?** Start with one page; a card links to a detail view for its transactions.

---

## Build order

1. `index.html` + `app.js` + reuse `app.css`, no build step. Delete `ui/` only *after* the new surface renders every field the contract test names.
2. Retarget `test_surface_contract.py` at the new source, keeping both existing assertions (every endpoint called; the three-nature vocabulary stays dead).
3. Cards in this order — **net worth, questions, depository, liability, investment, asserted** — because that is the order of how much each is worth to the person who opens it.
