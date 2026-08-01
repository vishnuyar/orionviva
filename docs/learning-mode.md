# Learning Mode: compound payments, and rulings in your own words

**Status:** ⚠️ **SUPERSEDED 2026-07-25 (same day) by [from-your-words-to-the-ledger.md](from-your-words-to-the-ledger.md)** — the signal named at the bottom of this note ("the queue keeps asking unanswerable questions") fired immediately, on the very first real run, so both threads it defers were pulled into **rulings in your own words**: the free-text ruling, the Asset primitive, and a compound answer with **honestly unknown proportions**. Read this note for the diagnosis — it is still the clearest statement of *why* three buttons could not work — and read the spec for what gets built. **Original status:** design note, not being built now (Vishnu, 2026-07-25); recorded so the questions stay asked · **Origin:** the first real run of the question queue, which asked two questions it had no right to ask. **Blocks it points at:** amount-split (built in v0, never used) · Asset · the free-text ruling.

**Invariants touched:** T2 (a model may parse a person's *intent*; it must never supply a figure or do arithmetic — ADR-010/CaMeL) · T4 (a ruling is an append-only event; the person's own words are captured verbatim in the claims layer) · **X2 (a question the system cannot honestly ask should not be asked — say what's missing instead)** · principle 2 (never bluff) · principle 6 (you direct the pace).

---

## The two questions the queue got wrong

The queue shipped and immediately asked Vishnu two things it shouldn't have.

**"You have 13 transactions with your mortgage servicer totalling X, counted as spending. Is that money spent — or something you now own, or moved between your own accounts?"**

None of the three answers is correct, because a mortgage payment is **three things at once**: the **interest** is money spent and gone; the **principal** buys equity, so it is a transfer into your own net worth; the **escrow** is money you still own, held on your behalf, later spent on tax and insurance. Forcing one answer is wrong either way — "spent" overstates spending by principal plus escrow, "moved" understates it by the interest.

**"You bought a car — is that spending?"**

Closer, but the honest answer ("no — I now own a car") lands somewhere the system cannot represent. There is no Asset primitive yet, so answering it correctly makes the money vanish from spending without appearing anywhere else, and net worth will be quietly understated.

## What each one actually needs

**Compound payments need a split, not a nature.** The mechanism already exists and has never been used: `split_transaction` — one movement whose counter-legs sum to the whole — was built in v0 and is wired nowhere. What's missing is not code but *the ratios*, and those are a fact the person doesn't know either: they're printed on the mortgage statement or the annual 1098.

So the right behaviour is **not to ask the person to guess**. Recognize the payment as compound, say plainly that it cannot be split without the document that states the split, keep it flagged as provisional, and **ask for that document instead**. That is `knowledge-and-expectations.md`'s "documents are evidence that other documents exist," arriving as a concrete, high-value ask: *"These look like mortgage payments. I can't tell how much was interest, principal and escrow without your mortgage statement or 1098 — do you have one?"* One document resolves thirteen transactions and unlocks a genuinely correct figure.

Amortization, and therefore the split, is Slice 11.

**A capital purchase needs the Asset primitive.** Enumerated in the block inventory, not built: `Position` (securities) is a *subtype* shipped with positions and investments; the general Asset — vehicles, property, valuables — is deferred. The detail that makes it interesting: a car has **no issuer statement**, so its value is `estimated`, never `measured` — which is exactly the distinction the valuation-class discipline was built for. And a financed car is three facts, not one: a new liability, an asset, and only the down payment is cash that actually moved.

**Interim honesty:** until Asset exists, ruling such a payment `settlement` keeps spending correct and leaves net worth understated. That is the better of two wrong answers, but it should be *said*, not silently done.

## Rulings in your own words (Vishnu's postulate, 2026-07-25)

> "I would like to write *this is my mortgage account* — which in theory would go to a model, with the question and answer, which we should send to get a deterministic answer."

The shape is right, and the boundary is what makes it safe:

1. **You write a sentence.** Free text is how people actually explain money.
2. **A model parses intent into a structured proposal** — never a figure, never arithmetic. `{counterparty: lender, payment_kind: compound, implies_document: mortgage_statement}`, not amounts.
3. **The proposal is shown back in plain language and you confirm it.** Only then does it become a `verified` ruling (correction-as-event, T4).
4. **Deterministic code applies it**, exactly as it applies a ruling made by clicking a button.

Model as interpreter, person as ratifier, code as applier — which keeps ADR-010 intact, because the model routes meaning and never produces a number.

Why it's worth building rather than a convenience: one sentence carries a lot of structure a button cannot. *"This is my mortgage"* implies the counterparty is a lender, the payments are compound, a loan account exists, and a statement is worth asking for — four rulings from six words. It is also **Viva arriving early but bounded**: not a chat agent, just a "tell me in your words" box attached to a question, and the first real use of the persona work (C1 uncertainty language, C3 when-to-speak).

**Risks and their answers.** A hallucinated structure is caught by confirm-before-apply. Prompt injection is low (the input is the person's own text) but the parse must stay powerless — it proposes, it cannot write. And the sentence itself should be **stored verbatim in the claims layer**, so a better model later can re-derive more from it without asking again.

## Why this is deferred, and what would pull it forward

Both threads need primitives that belong to later slices (Asset; loan amortization), and the free-text ruling is the learning loop's next capability rather than a fix. Building either now would mean guessing at ratios or storing an asset with nowhere to live.

**The signal to pull it forward:** the queue keeps asking unanswerable questions. Until then, the honest interim is that a compound payment is flagged as provisional and *named as compound* rather than asked about, so the figure states its own incompleteness instead of inviting a wrong answer.

## Deferred (explicitly)

Splitting a mortgage payment into interest/principal/escrow (Slice 11 — the ratios come from the loan statement). The Asset primitive and estimated valuations (the sibling of positions and investments). **Partly arrived 2026-08-01:** an asserted asset can now be created only with a name its owner gave it, interviewed against a schema, and carried at cost or disclosed as a gap — [the-interview-and-the-schema-pack.md](the-interview-and-the-schema-pack.md). Estimated present-day valuation remains unbuilt. The free-text ruling and its parse prompt. Recognizing that a document *implies* another document, as an askable question.
