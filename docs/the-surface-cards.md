# The Surface, Rebuilt as Cards (Slice 6.9)

**Status:** Spec — decided 2026-07-26, unbuilt · **Origin:** Vishnu: *"I feel that moving away from index.html created some bugs. Let us do away with React and come back to index.html, create a card for each type of instrument and decide what needs to be shown on that card."*

**Invariants touched:** **X1** (the machinery is invisible; the person sees money) · **X2** (every figure carries its as-of date and grade) · **T1** (a figure names the document behind it) · principle 5 (serve, don't overwhelm).

---

## Why we are reversing the React decision

Slice 6.7 chose **React + Vite** for "legibility to readers of a public repo and reliability of AI-written code," bounded by static build output. Reasonable then, and a two-way door by design.

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
| `asserted` badge — your word | honest, and it is what the disclosure view will later filter on |
| **the document that would corroborate it** | provenance-based: the invoice, the 1098, the closing disclosure |

### The two cards that are not accounts

- **Net worth** — the curve. One point, its stalest input named, the provable subtotal, and what is not counted.
- **What Viva needs** — the question queue, ranked by consequence. **This stays the page's spine**: it is the learning loop's front door and the thing that makes the rest improve.

---

## Open questions for the build

1. **Does the queue sit above the cards, or beside each card?** Above keeps the ranking honest (consequence-ordered across everything); beside makes each card self-contained. Ranking is the more valuable property — start above.
2. **Tag and category controls live on the drill-through, not the card.** A card is for reading; answering is a deliberate act.
3. **One page or per-account pages?** Start with one page; a card links to a detail view for its transactions.

---

## Build order

1. `index.html` + `app.js` + reuse `app.css`, no build step. Delete `ui/` only *after* the new surface renders every field the contract test names.
2. Retarget `test_surface_contract.py` at the new source, keeping both existing assertions (every endpoint called; the three-nature vocabulary stays dead).
3. Cards in this order — **net worth, questions, depository, liability, investment, asserted** — because that is the order of how much each is worth to the person who opens it.
