# The Presentation Layer

**State:** superseded
**Rules:** VOICE-70, VOICE-71

The page, the server, the endpoints and their contract test are gone; the engine
beneath them moved to `product/viva/engine.py` first. It was explicitly a debug
surface, never the product's presentation layer, and it was thrown away as one.
Read this for the rulings and the reasoning, never for what exists.

## Rules

### VOICE-70 — a surface formats money and never computes it
**State:** enforced
**Code:** product/viva/render.py:176 (`money`)
**Test:** product/tests/test_render.py::test_no_module_that_speaks_to_a_person_formats_money_itself

1. The ledger decides the figure; a surface renders it.
2. A figure is written under the vault's locale, never the browser's.

### VOICE-71 — a shipped surface needs no toolchain and no runtime fetch
**State:** unmet
**Code:** none found for assertions 1 and 2
**Test:** product/tests/test_surface_import_boundaries.py::test_core_does_not_depend_on_product_surface_or_desktop (assertion 3 only)

1. A build step is a developer concern, so it is compatible with X1 only while the shipped artifact stays static and offline.
2. No runtime CDN fetch, because local-first would break.
3. No new dependency enters `core/` or `product/`'s financial modules; a toolchain is a UI-only concern. **This half holds**, and is the one the cited test asserts; assertions 1 and 2 are unchecked by anything.

Categories stay implicit: one exists by being used, and no event defines one.
That rule lives once, as **MON-23** in
[local-categorization-and-custom-categories.md](local-categorization-and-custom-categories.md).

## Why

The page existed so the author could see and exercise what the engine knew while
building it, and nothing more. Treating it as a decided design, or accumulating
features on it, was the failure mode it was most exposed to — which is why it
carried a standing instruction not to.

**Why it was built at all: the engine had outrun the surface, measurably.** Four
endpoints were exposed that the page never called, two of them reachable only by
`curl` since the category overlay shipped. The overview payload carried seven
fields the page ignored, including all of positions and investments, the two
honesty signals of movement nature, and a held brokerage statement whose
invisibility had been fixed in the *data* and remained on screen. Roughly three
slices' output had no surface at all, and the question queue's whole point — one
front door — existed only in a CLI. A product whose promise is "open it and it's
handled" cannot keep its best work in JSON.

**The spine it proposed** honours the calls already made — dashboard-first,
findings as quiet state rather than notifications, and panels earned rather than
assumed: the picture, with total, coverage and an honesty line saying what is
provisional and what was excluded and why; what Viva needs, as the ranked queue
with answers inline; your money, with holdings and their as-of dates for an
investment account; where it went, expandable to subcategory; and a way to add
documents.

**The rulings that were taken on it.** Answering was made hybrid: one-tap
answers inline in the ranked list, and anything needing context — a held
statement, a merchant's transactions, two sides of a transfer — opening a
focused detail view. The reason is that the highest-stakes decision should not
be visually squashed between quick ones, and clearing ten small items should not
cost ten page loads. Custom categories were made implicit rather than
first-class, with a known and accepted wrinkle: a category named but not yet
applied does not survive a reload, and if that friction shows up in real use it
is the signal to make categories first-class. Peer descriptors got
per-transaction categorization, so one Zelle can be a gift and the next a loan
repayment.

The stack ruling — a framework with a build step, emitting static files served
by the existing stdlib server — was reversed within a day by
[the-surface-cards.md](the-surface-cards.md), for the stale-artifact reason
recorded there. The original reasoning is worth keeping because it was sound for
what it was choosing: a public repo where a familiar framework is a legible
signal, the largest ecosystem, and the place AI-written code is most reliable —
which matters on a project where "the AI drifts and the human catches it" is a
documented failure mode. What the reversal showed is that a compile step between
source and running thing outweighs all of it in a repo whose discipline is *the
artifact must not lie*.

**What was meant to survive, and is the durable lesson.** The contract tests:
every endpoint called, every payload field either rendered or deliberately
dropped, asserted mechanically so the gap cannot silently reopen. They are what
caught the engine outrunning the surface in the first place, and they are the
idea that carried forward into
[user-interface-architecture-and-delivery.md](user-interface-architecture-and-delivery.md).

The honesty elements it specified are the same ones any surface owes: a spending
figure carrying a quiet "…and X I'm not certain about", expanding to what was
excluded grouped by the rung that excluded it; holdings with units, value and
as-of date, and the mixed-vintage warning when a composed total rests on
measurements from different dates; unrealized gain as a derived as-of view and
never a ledger figure; a summarized tail rather than a hidden one; and held
documents with no fix-it flow appearing as questions saying what they are and
why they are waiting.

An answer that would open an account returns a proposal to confirm rather than
applying in the same request, and a set-aside question is opened rather than
pushed.

## Open

- The real presentation layer is an unheld design conversation: information architecture, what a person actually opens this for, the persona's voice, progressive disclosure done properly, mobile. See [user-interface-architecture-and-delivery.md](user-interface-architecture-and-delivery.md) for the direction proposed since.
- How pending state *looks* is still owed to that conversation.
- Chat and natural-language entry as a surface; charts and trends; tap-to-source region highlighting on the document image; mobile-specific layout.
- Whether categories ever become first-class, and the friction that would signal it.
