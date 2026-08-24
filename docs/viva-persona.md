# Viva — the Persona

**State:** built
**Rules:** VOICE-10, VOICE-11, VOICE-12, VOICE-13, VOICE-14, VOICE-15, VOICE-16

## Rules

### VOICE-10 — voice is versioned data, never incidental copy
**State:** enforced
**Code:** product/viva/persona/contracts.py, product/viva/persona/pack-v35/ (each newer pack adds a family and copies the rest verbatim; pack-v35 adds reviewed Activity transfer relationship, evidence-state and outcome copy over pack-v34's movement-scoped category and tag correction outcomes)
**Test:** product/tests/test_persona_pack.py::test_question_text_no_longer_lives_in_code

1. Everything Viva says lives in `product/viva/persona/<pack>/` as phrasings, moments and tone rules.
2. Question text in a `.py` file fails the build, exactly as prompt text does.
3. The pack contains no user data, so it is shareable, reviewable and swappable.

### VOICE-11 — a phrasing may not introduce a fact its intent did not supply
**State:** enforced
**Code:** product/viva/persona/contracts.py:12 (`INTENT_FIELDS`), :392 (`slots_of`)
**Test:** product/tests/test_persona_pack.py::test_phrasings_use_only_their_intent_fields

1. Every `{slot}` in a phrasing names a field the question intent supplies.
2. Every named slot declares a type drawn from the renderer's closed set.
3. A slot referencing anything else fails the build, not the render.

### VOICE-12 — every question kind has a phrasing, and no phrasing is orphaned
**State:** enforced
**Code:** product/viva/persona/contracts.py:12 (`INTENT_FIELDS`), :117 (`MOMENT_FIELDS`)
**Test:** product/tests/test_persona_pack.py::test_every_intent_has_a_phrasing_and_no_orphans

1. A question kind with no phrasing fails the build.
2. A phrasing no intent claims fails the build.
3. The same holds for moments.

### VOICE-13 — a slot is typed, and a figure reaches a person only through the one renderer
**State:** enforced
**Code:** product/viva/render.py:55 (`TYPES`), product/viva/persona/contracts.py:403 (`say`)
**Test:** product/tests/test_persona_pack.py::test_a_money_slot_cannot_be_handed_a_figure_that_formatted_itself

1. A money slot accepts only what `render.money` wrote, with its value, currency and one locale's conventions.
2. A declared type that disagrees with what is placed raises where the sentence is made.
3. A missing slot raises; a blank is never rendered in a figure's place.

### VOICE-14 — a decline is an event, and a declined question stays quiet until evidence moves
**State:** enforced
**Code:** product/viva/engine.py:568 (`decline_question`), product/viva/interview.py
**Test:** product/tests/test_interview.py::test_a_deferred_question_returns_when_evidence_touches_its_subject

1. "Not now" and "I don't know" are recorded, not discarded.
2. A declined question leaves the ranked queue and returns only when a new event touches its subject, or when the person opens the pending list.
3. Nothing returns on a timer.

Viva never initiates: she is summoned, never ambient. That rule lives once, as
**VOICE-30** in [experience-vision.md](experience-vision.md).

### VOICE-15 — she works in the background, and the work is quiet
**State:** unmet
**Code:** none found
**Test:** none

1. Work in progress shows a quiet indicator; no spinner theatre.
2. She works in the background — that is the persona, not a loading state dressed up.

### VOICE-16 — a released persona pack is frozen
**State:** enforced
**Code:** product/viva/versions.json (`persona_pack`)
**Test:** product/tests/test_persona_pack.py::test_released_packs_are_frozen

1. A released pack directory is pinned by the digest of its files, hidden files excluded.
2. Changing a phrasing means a new pack version, because a recorded `pack` stamp must resolve to the words a person actually read.

## Why

Viva is not a feature of the application; she is the application's personality,
and her job is to make the person feel guided, supported and in control. Warmth
is load-bearing here, which is exactly why it is written down and versioned
rather than left to incidental copy — a tone that lives in scattered string
literals drifts, and nobody can review what they cannot find in one place.

The traits are the argument for the mechanism. **Patient**: financial matters
are sensitive, so a person can stop at any time and not knowing something is an
acceptable answer. **Wise**: the value is clarity, so observations are offered
grounded in data and never as commands. **Discreet**: she presents findings and
recedes. **Polite**: courteous, using a name where one is known — read from the
person's own documents, never asked of a model — formal without being cold.

Three principles follow. *Serve, don't overwhelm*: no feature and no question
appears before the context that makes it useful, so the dashboard and the
questions evolve with the data. *Empower*: every interaction ends with the
person in control, and "not now" is a real answer that is remembered rather than
a way of postponing a nag. *Build trust through transparency*: an ask explains
its benefit — *"if you share the rate, I can show your true borrowing cost"* —
and no figure ever wears more certainty than the ledger holds.

The conversational arc is the same shape: welcome the person to one low-effort
action and show what one document already reveals before asking for a second;
then gentle contextual questions one at a time, ranked by consequence, with the
tail summarized rather than hidden; then background linking and corroboration
surfacing as quiet state; then budgets and goals, unlocked on evidence rather
than on enthusiasm.

The division of labour is what keeps this safe. The queue decides *what* is
asked, deterministically, ranked by consequence
([viva-persona-and-interview.md](viva-persona-and-interview.md)). Viva decides
only *how it sounds*. Her questions are never free compositions: each kind is
machinery the product already has, wearing her voice — account identity
resolution, the finding ladder, transfer links, the merchant catalog, the four
majors, corroboration asks, the expectations engine, the schema pack and derived
interview ([the-interview-and-the-schema-pack.md](the-interview-and-the-schema-pack.md)),
the rhythm read ([the-question-queue.md](the-question-queue.md)). The failure
mode of a template is *stiff*; the
failure mode of live composition is *false*. Stiff is recoverable.

The bluff is the thing that must never happen, so it is made structural rather
than remembered: a template cannot introduce a number, a merchant or a claim its
intent did not supply, and every slot is typed so a figure that formatted itself
under nobody's conventions cannot get in. Beyond that, she never rushes, never
guilts, never gamifies; never asks what the ledger already knows; and never asks
what a person *cannot* know — she asks for the document that does.

An optional detail declined is never nagged about. An essential one — a figure
honesty depends on — stays visible as quiet incompleteness: named, never pushed.

## Open

- What measures "sounds like Viva"? Correctness has a confidently-wrong rate; voice has the author's ear, and saying so is more honest than inventing a metric.
- The copywriter workflow: does a model draft phrasings in a pull request the author reviews, or does the author write and the model only critique?
- Whether live per-question phrasing is ever earned, and what evidence would earn it.
