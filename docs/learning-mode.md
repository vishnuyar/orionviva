# Learning Mode: compound payments, and rulings in your own words

**State:** superseded by [from-your-words-to-the-ledger.md](from-your-words-to-the-ledger.md), which is the spec for what gets built. This note keeps the diagnosis — it is still the clearest statement of *why* three buttons could not work.
**Rules:** MER-60, MER-61, MER-63, MER-64

## Rules

### MER-60 — A question with no correct answer among its options is not asked
**State:** enforced
**Code:** product/viva/questions.py:356 (a compound implication changes what is asked), product/viva/listen.py:1 (the answer is a sentence, not a fixed set of buttons)
**Test:** product/tests/test_listen.py::test_a_proposal_states_what_it_does_not_know

1. Where the honest answer is not among the offered options, the system says what is missing instead of forcing one — a question it cannot honestly ask is not asked (X2).
2. A closed-option question cannot express a compound truth, so the answer surface is a sentence.

### MER-61 — A compound payment is named as compound, and the ask is for the document
**State:** enforced
**Code:** product/viva/questions.py:355-366 (the compound sentence and the documents that would resolve it), product/viva/ledger/projection/movements.py:44 (`MIXED`), :262 (`provisional`), product/viva/listen.py:367 (`unknown_split`)
**Test:** product/tests/test_ruling.py::test_a_compound_payment_is_neither_counted_nor_dropped, product/tests/test_listen.py::test_a_stated_split_is_kept_and_an_invented_one_is_not

1. A payment whose components are known and whose proportions are not is neither counted as spending nor dropped; it gets its own nature and is marked provisional.
2. The person is never asked to guess the ratios; the ask is for the document that states them.
3. A split is honoured only where the person stated it; an invented one is not kept.
4. A missing document never blocks a ruling — the account is created and the cash is posted; only the decomposition stays provisional.

The model parses a person's intent; it never supplies a figure and never does
arithmetic (T2). That rule lives once, as
**PROJ-26** in
[from-your-words-to-the-ledger.md](from-your-words-to-the-ledger.md).

### MER-63 — The sentence is kept verbatim, and applying is a separate act
**State:** enforced
**Code:** product/viva/ledger/events.py:617 (`said` in the event body), product/viva/listen.py:693, product/viva/listen.py:1 (propose then apply)
**Test:** product/tests/test_listen.py::test_applying_is_a_separate_explicit_act, product/tests/test_listen.py::test_the_button_path_and_the_sentence_path_write_the_same_events

1. A ruling is an append-only event, and the person's own words are stored verbatim on it, so a better model later can re-derive more from them without asking again (T4).
2. A proposal is shown back in plain language and only becomes a `verified` ruling once confirmed.
3. The parse proposes and cannot write; deterministic code applies a ruling, exactly as it applies one made by clicking a button.

### MER-64 — The interim answer for a capital purchase
**State:** contradicted-by-code
**Code:** product/viva/ledger/projection/movements.py:44, :110-114, :262
**Test:** product/tests/test_ruling.py::test_a_compound_payment_is_neither_counted_nor_dropped

1. This document says that until the Asset primitive exists, such a payment is ruled `settlement`, which keeps spending correct and leaves net worth understated, and that this should be said rather than silently done.

**Contradiction:** the doc prescribes ruling a compound or capital payment `settlement` as the better of two wrong answers (this file, MER-64 above). The code does not: a ruling with several majors produces the `MIXED` nature (product/viva/ledger/projection/movements.py:110-114), which is neither counted as spending nor dropped, is flagged `provisional` (:262), and is carried as a named caveat into net worth (product/viva/ledger/networth.py:152). Not resolved here.

## Why

The question queue shipped and immediately asked two questions it had no right to
ask, and both failures have the same shape.

**"You have 13 transactions with your mortgage servicer totalling X, counted as
spending. Is that money spent — or something you now own, or moved between your
own accounts?"** None of the three answers is correct, because a mortgage payment
is three things at once: the interest is money spent and gone; the principal buys
equity, so it is a transfer into your own net worth; the escrow is money you still
own, held on your behalf, later spent on tax and insurance. Forcing one answer is
wrong either way — "spent" overstates spending by principal plus escrow, "moved"
understates it by the interest.

**"You bought a car — is that spending?"** Closer, but the honest answer — no, I
now own a car — lands somewhere the system cannot represent without an Asset
primitive, so answering it correctly makes the money vanish from spending without
appearing anywhere else, and net worth is quietly understated.

A compound payment needs a *split*, not a nature. The mechanism has existed since
v0 and was wired nowhere: one movement whose counter-legs sum to the whole. What
is missing is not code but the ratios, and those are a fact the person does not
know either — they are printed on the mortgage statement or the annual 1098. So
the right behaviour is not to ask the person to guess. Recognize the payment as
compound, say plainly that it cannot be split without the document that states the
split, keep it provisional, and ask for that document instead. That is
[knowledge-and-expectations.md](knowledge-and-expectations.md)'s *documents are
evidence that other documents exist*, arriving as a concrete, high-value ask: one
document resolves thirteen transactions and unlocks a genuinely correct figure.

A capital purchase needs the Asset primitive. `Position` is a subtype that shipped
with positions and investments; the general asset — vehicles, property,
valuables — is the interesting one, because a car has **no issuer statement**, so
its value is `estimated`, never `measured`, which is exactly the distinction the
valuation-class discipline was built for. And a financed car is three facts, not
one: a new liability, an asset, and only the down payment is cash that actually
moved.

The free-text ruling is what both threads converge on. Free text is how people
actually explain money, and the boundary is what makes it safe: the model parses
intent into a structured proposal — never a figure, never arithmetic — the
proposal is shown back in plain language, the person confirms it, and
deterministic code applies it. Model as interpreter, person as ratifier, code as
applier, which keeps ADR-010 intact because the model routes meaning and never
produces a number.

It is worth building rather than a convenience because one sentence carries
structure a button cannot. *"This is my mortgage"* implies the counterparty is a
lender, the payments are compound, a loan account exists, and a statement is worth
asking for — four rulings from six words. A hallucinated structure is caught by
confirm-before-apply; prompt injection is low, since the input is the person's own
text, but the parse must stay powerless — it proposes, it cannot write.

## Open

- Splitting a mortgage payment into interest, principal and escrow. The ratios come
  from the loan statement, and amortization is what makes the split derivable.
- Estimated present-day valuation for an asserted asset. An asserted asset can be
  created with a name its owner gave it, interviewed against a schema, and carried
  at cost or disclosed as a gap ([the-interview-and-the-schema-pack.md](the-interview-and-the-schema-pack.md));
  the estimated valuation is not built.
- Recognizing that a document *implies* another document, as an askable question in
  its own right.
- The discrepancy in MER-64: this note's interim prescription and the code's
  `MIXED` nature are two different answers to one question, and nothing has
  reconciled them.
