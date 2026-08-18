# The Surface, Rebuilt as Cards

**State:** superseded
**Rules:** VOICE-61, VOICE-62, VOICE-63, VOICE-64, VOICE-65, VOICE-66

The page this specified no longer exists. What survives is what each kind of
instrument must say. Read it for presentation semantics; do not read it for a
surface.

## Rules

A liability speaks `owed` and never `balance`. That rule lives once, as
**MON-25** in [net-worth.md](net-worth.md).

### VOICE-61 — a figure whose value denies its quantity's direction fills no hole asserting it
**State:** enforced
**Code:** product/viva/tools/runner.py:775
**Test:** product/tests/test_shape.py::test_a_credit_on_a_card_never_fills_a_hole_that_asserts_a_debt

1. A hole asking for a quantity that asserts a direction is a sentence asserting that direction.
2. A figure carrying a value running the other way fills no such hole, and the clause never reaches a person.
3. An ordinary debt is unaffected: it still fills the hole that asserts one.
4. The refusal is a comparison of two declarations, not a rendering-time fix and not a special case for cards. The sign convention is untouched.

### VOICE-62 — which quantities assert a direction is declared with the vocabulary
**State:** enforced
**Code:** product/viva/quantity.py:119 (`ASSERTS_DIRECTION`)
**Test:** product/tests/test_tools.py::test_which_quantities_assert_a_direction_is_declared_with_the_vocabulary

1. The set lives in the module that owns the quantity vocabulary, is closed, and grows by editing it there.
2. Every member of it is a member of the quantity vocabulary.
3. A quantity outside the set asserts nothing about direction, and no value of it contradicts anything.

### VOICE-63 — the renderer writes an amount, not an instrument
**State:** enforced
**Code:** product/viva/render.py:176 (`money`)
**Test:** product/tests/test_render.py::test_no_module_that_speaks_to_a_person_formats_money_itself

1. There is no per-instrument rule in the renderer; what a figure measures is carried by the figure, not decided at rendering time.
2. No module that speaks to a person formats money itself.
3. A figure written under conventions nobody declared is refused where the sentence is made.

### VOICE-64 — every figure carries its own as-of date and grade
**State:** enforced
**Code:** product/viva/tools/envelope.py:138 (`figure`)
**Test:** product/tests/test_shape.py::test_the_figure_the_hole_asked_about_is_spoken

1. A figure carries the date it is good for; it is never dressed as "current".
2. A figure carries its grade, and a composed total that mixes vintages says so.
3. A card that silently omits is a lie of omission: what a figure does not include is stated.

### VOICE-65 — a card that fails is a card that failed, never a ledger that failed
**State:** unmet
**Code:** none found
**Test:** none

1. A component that throws does not take the surface down.
2. A surface whose whole job is honest reporting never reports its own defect as the engine's failure.

### VOICE-66 — each account kind speaks its own language
**State:** unmet
**Code:** none found
**Test:** none

1. A depository speaks balance, with its as-of date prominent when stale, and this period's in and out.
2. A liability speaks **owed**, as the number on the bill, and calls out a credit balance when the card owes the person.
3. An investment shows cash plus holdings equalling the total as the statement's own identity, each holding with its measurement date, activity that was *not* posted and why, and unrealized change as a labelled derived view rather than a ledger fact.
4. An asserted asset speaks **cost**, and the word "cost"; where nobody has said what it cost there is no cost line at all, but the question that closes the gap; a stated cost replaces the cash-derived line rather than sitting beside it; and it names the document that would corroborate it.

## Why

**The organising idea is one card per *kind*, not per document.** A kind decides
which questions make sense and which figures exist, and the vault knows three
issued kinds — depository, liability, investment — plus accounts a ruling
brought into being.

Every card carries the same three honesty elements, because they *are* the
product: the figure with **its own** as-of date, never dressed as "current"; its
grade plainly, where `corroborated` means a document attests it and the
arithmetic checks and anything less says what is missing; and what it does not
include, because a card that silently omits is the lie of omission.

The per-kind detail each earns its place from something real. A depository's
as-of date is prominent when stale because three of four real accounts were
months behind the point they contributed to. A liability speaks *owed* because
the ledger stores owed and net worth negates it — the card speaks the person's
language — and a credit balance is called out because it is rare, real, and the
opposite of what the word "balance" implies. An investment shows the
cash-plus-holdings identity because it is the densest model-free cross-check in
the product, and showing it *is* the trust; it shows activity withheld and why
because a real statement had 24 cash movements held for want of an opening cash
figure, and silence there is the worst option. An asserted asset speaks cost
because cost is what you paid, never what it is worth now.

**Where the liability rule actually lives.** It is not a per-kind branch in a
renderer, which is a plausible-sounding home and the reason nobody checked it
for a while. What holds the rule is the vocabulary of what a figure *measures*:
a liability's magnitude is emitted as `owed` and never as `balance`, by every
read that emits one, so a clause asking about a balance cannot be filled with a
debt at all — it refuses.

**Why a credit is refused rather than reworded.** An overpaid card's figure is
negative in the owed convention, so a debt clause bound with it came out as
*"You owe -USD 50.00 on ‹card›"*. A hole asking what is owed is a sentence
asserting a debt is there, so a figure whose value denies that direction fills
no such hole. What buys the ordinary question back is a shape carrying a clause
for each case and dropping the one that did not apply — the shape is committed
before any read, so the planner cannot know it is about to name a liability. The
shape prompt teaches that pattern; whether a live model follows it is not
something any test here can establish, so the failure has moved rather than
closed: a turn that used to answer wrongly can now refuse outright.

**Why the React build step was reversed.** The compiled surface chose a
framework for legibility to readers of a public repo and reliability of
AI-written code, bounded by static build output. The evidence since said the
build step cost more than the framework saved: a compiled bundle can silently
serve last hour's product with no error, no warning, and no way to tell by
looking — checking required grepping the bundle for feature strings. That is
the exact failure shape this project spent a week finding everywhere else, a
stale artifact reporting success it has not earned, and in a repo whose
discipline is *the artifact must not lie* a compile step between source and the
running thing is a standing liability. Reversing a two-way door when the
evidence changes is the process working. It is recorded so nobody re-adopts a
build step without answering it.

**Why the surface itself went.** It was scaffolding that had begun costing
verification findings of its own — a person shown an empty box, a figure
rendered under the *browser's* locale rather than the vault's — and carrying it
through the answer path's rewrite would have meant paying for it twice. The
engine it sat on moved to `viva/engine.py` before anything was deleted, so the
door survived the page. A third surface designed at that moment would have been
a fourth thing to throw away.

**What was meant to survive the rewrite, and mostly did:** the endpoint contract
and its tests, because they read the UI source as text and are what caught the
engine outrunning the surface in the first place; no CDN and no runtime
dependency; and money formatted, never computed, in the surface — the ledger
decided the figure.

**Ordering.** The question queue is the page's spine wherever it lands: it is
the learning loop's front door and the thing that makes everything else improve.
Ranking is the more valuable property than self-contained cards, so the queue
sits above rather than beside. A card is for reading; answering is a deliberate
act, so tag and category controls belong on the drill-through.

## Open

- The real presentation layer is still an unheld design conversation. See [user-interface-architecture-and-delivery.md](user-interface-architecture-and-delivery.md) for the direction proposed since, and [the-presentation-layer.md](the-presentation-layer.md) for the debug surface that was deleted.
- Whether a live model actually writes the second clause for the credit case — the one thing no test in this repo reaches.
- One page or per-account pages. Start with one page; a card links to a detail view for its transactions.
- Tap-to-source region highlighting on the document image: provenance is carried but not rendered as a crop.
