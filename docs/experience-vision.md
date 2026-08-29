# Experience Vision — a day with Viva, and the machinery each moment demands

**State:** partial
**Rules:** VOICE-30, VOICE-31, VOICE-33, VOICE-34, VOICE-36

The debug surface that existed was deliberately not this. See
[user-interface-architecture-and-delivery.md](user-interface-architecture-and-delivery.md)
for the delivery direction proposed since.

## Rules

### VOICE-30 — Viva is summoned, never ambient
**State:** untestable
**Code:** none found
**Test:** none

1. Viva never initiates. Anything she notices — anomalies, missing statements, low-confidence figures — becomes visible quiet state: a badge, a soft row.
2. The person pulls; the product never pushes. There is no notification philosophy because there are no notifications.
3. Background deterministic checks still run; their findings go to a quiet panel, not to an interruption.
4. There is no scheduler, notifier or push path in the product.

### VOICE-31 — the product opens as a picture, not a chat
**State:** by-review
**Code:** desktop/src/app/App.tsx, desktop/src/features/conversation/ConversationDrawer.tsx
**Test:** none

1. Opening OrionViva shows the financial picture — net worth, accounts, trends — not a chat window. **This half holds:** the shell opens on `overview`, titled *Your financial picture* (desktop/src/app/App.tsx:20, :36), and conversation is a summoned overlay (:44).
2. Conversation is a surface you summon, and it shares the evidence machinery every other figure uses. **Built for text:** the summoned drawer reads durable turns, current citations, open questions and correction proposals through one live conversation contract. Voice remains absent.

A panel earns its existence from data — day one is a greeting and a drop zone,
the first statement births an account card, the third month births trends. The
rule behind it lives once, as **VOICE-105** in
[user-interface-architecture-and-delivery.md](user-interface-architecture-and-delivery.md).

### VOICE-33 — a capture surface creates no hosted data
**State:** unmet
**Code:** none found
**Test:** none

1. Email capture is the application, on the person's own machine, watching the person's own mailbox — credentials in the OS keychain, nothing new hosted.
2. A hosted forwarding address is never shipped as "email capture"; it only ever happens as an attested-enclave service, if ever.
3. No readable financial document passes through an OrionViva server.

### VOICE-34 — a spoken answer is mirrored in text
**State:** unmet
**Code:** none found
**Test:** none

1. Text and voice share one session and one runtime.
2. Every spoken reply is mirrored in text so its evidence stays tappable.

Every displayed figure carries its grade and its source. That rule lives once,
as **VOICE-103** in
[user-interface-architecture-and-delivery.md](user-interface-architecture-and-delivery.md).
Tap-to-source *region* highlighting is not built — see that document's Open.

### VOICE-36 — a correction is an event, permanently remembered
**State:** enforced-with-exception
**Code:** product/viva/ledger/events.py:341 (`category_assigned`), product/viva/engine.py:606 (`assign_category_to`)
**Test:** product/tests/test_reset_categorization.py::test_reset_drops_model_categorization_but_keeps_my_rulings, product/tests/test_category_identity.py::test_the_ruling_is_retroactive_and_rewrites_nothing

1. One sentence — *"that's groceries, not dining"* — becomes an appended event, never an overwrite, keyed to the stable movement key so it survives a reingest.
2. A correction records who made it: a model's suggestion is graded `unverified`, a person's confirmation `verified`.
3. Corrections are the memory moat's front door.

**Exception:** a correction is attributed to a person or a model but not to a *model version* — `product/viva/ledger/events.py:355` records `by`, and no version stamp — so a correction is not yet an error attributed to the release that made it, and cannot yet feed a per-model scorecard.

## Why

Four decisions define the product's personality, and together they make a quiet,
information-rich command center where the dashboard carries the state, Viva
carries the understanding, and nothing ever interrupts. **Dashboard-first**, so
the product opens as a picture rather than a prompt. **Speak only when spoken
to**, which is maximum discretion and resolves the notification question in the
simplest possible way — there isn't one. **All four capture surfaces** — drag
and drop, watched folder, phone camera and share sheet, and email — because
capture is the lifelong act this product is built around. **Text and voice**,
because talking to a butler is the natural register for this persona.

**Dashboard-first and "simple as a Google homepage" are reconciled by
progressive disclosure**, not by compromise. On day one the dashboard is nearly
empty. Panels *earn their existence* as data arrives. The rich command center is
what the product grows into, not what it confronts a newcomer with: the Google
homepage is the day-one state, the dense terminal is the year-one state, and
every person is at their own point on that path.

**The day, as decided.** The glance: accounts, numbers, and a quiet completeness
strip — *current through yesterday*, *June card statement not yet seen* —
with anything needing eyes sitting as a visible badge until touched. A document
arrives by any surface; the pipeline runs; the result appears as dashboard state
— *47 transactions, reconciled* or *1 figure needs your eyes* — and never as a
notification. The question, typed or spoken, answered by planning deterministic
tool calls and composing from tool results only, with every figure tappable to
its source. The correction, one sentence, becoming an event. Viva noticing
things, into a panel rather than into an interruption; when the person next
talks to her she may mention the panel exists. And the trust moment: a standing
dashboard element, not a buried setting — *what has ever left this machine*,
every model call, every anchor fingerprint, complete and plain.

**Email capture is the honest tension in the list.** A forwarding address means
a server somewhere receives financial documents in plaintext — SMTP delivers
plaintext, and even an encrypt-immediately-and-delete design has a trust-us
window. That is the first crack in "we hold no user data," and cracks widen. The
alternative preserves the whole convenience with none of it: the app, running on
the person's machine, watches the person's own mailbox. Same gesture, zero new
servers, nothing leaves.

**Voice is cheap in architecture and expensive in product.** The runtime is
modality-blind, and transcription in and synthesis out are available on-device
on modern operating systems, which is consistent with local-first. The real cost
is UX: how does *tap the number to see its source* work when the answer was
spoken? That earns its own design pass, and until then spoken answers are always
mirrored in text so provenance stays tappable.

**What this makes concrete for everything downstream:** uncertainty language now
has surfaces to live on, the persona now has an interruption policy — never —
and onboarding is progressive disclosure of an empty dashboard. The parts it
demands are the component list any architecture must cover: capture surfaces,
the extraction and verification pipeline, the event ledger and its projections,
the agent runtime with a small deterministic toolset, memory as events with
provenance, a background check scheduler feeding a quiet panel, a dashboard with
progressive disclosure, a conversation surface in text and voice, a provenance
viewer, and a transparency panel showing the outbound ledger.

## Open

- Email capture: the local mailbox watcher's design — IMAP, a provider API, or local label conventions. Hosted forwarding is permanently deferred to attested-enclave territory.
- Voice interaction design for provenance and corrections: what replaces tapping a figure when the answer was spoken.
- Dashboard progressive-disclosure choreography: exactly what earns a panel into existence.
- Memory of corrections, preferences and goals as events with provenance is specified in principle and still needs design.
- The background check scheduler, and how a quiet "noticed" panel is populated without ever becoming a ping.
