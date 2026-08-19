# Viva: the Persona & the Interview — how questions get a voice, and answers build a profile

**State:** built
**Rules:** VOICE-23, VOICE-24, VOICE-25, VOICE-26, VOICE-27

## Rules

### VOICE-25 — the butler is Viva, and the persona guide is seed content for data packs
**State:** enforced
**Code:** product/viva/persona/pack-v14/
**Test:** product/tests/test_persona_pack.py::test_every_intent_has_a_phrasing_and_no_orphans

1. [viva-persona.md](viva-persona.md) is the standing definition of traits, principles, question content and "I don't know" handling.
2. That guide is seed content for pack data, never a spec for code.

### VOICE-26 — the model is a copywriter at design time, not at run time
**State:** enforced
**Code:** product/viva/tools/runner.py:350 (`_refused`), product/viva/persona/
**Test:** product/tests/test_speak.py::test_a_refusal_is_the_packs_reviewed_sentence_for_its_tag

1. Every sentence Viva can say is reviewable before she says it, because runtime fills slots in reviewed templates deterministically.
2. Nothing composes words at the moment of refusing; the sentence is chosen by machine tag.
3. Live per-question phrasing is unbuilt, and when it arrives it enters probated, evaluated and guarded like any other model surface.

### VOICE-27 — one question at a time, with the tail summarized
**State:** enforced
**Code:** product/viva/ask.py:175 (`run`), product/viva/questions.py:41
**Test:** product/tests/test_interview.py::test_an_account_with_a_schema_is_asked_one_thing_at_a_time, product/tests/test_questions.py::test_the_tail_is_summarized_never_dropped, product/tests/test_questions.py::test_the_queue_carries_no_instructions_for_a_surface, product/tests/test_ask.py::test_a_blank_line_ends_the_sitting

1. The question surface shows the top-ranked question.
2. The remaining questions are summarized, never hidden.
3. Every question is answered in language. The surface offers no options, no *next* and no *not now*: a blank line ends the sitting.

What the queue itself does — rank by consequence, summarize the tail, introduce
no event type — lives once, in [the-question-queue.md](the-question-queue.md):
**MON-45**, **MON-47** and **MON-44**. The persona decides *how* to ask and
never *what*, so the rules below are the ones about wording and surface.

### VOICE-23 — the queue carries no instructions for a surface
**State:** enforced
**Code:** product/viva/questions.py
**Test:** product/tests/test_questions.py::test_the_queue_carries_no_instructions_for_a_surface

1. A question carries its intent, refs, amounts and the finding behind it.
2. It carries no layout, no widget name and no rendering directive.

### VOICE-24 — this is never a chat agent
**State:** enforced
**Code:** product/viva/ask.py:1, product/viva/reply.py
**Test:** product/tests/test_reply.py::test_a_question_no_longer_being_asked_records_nothing

1. The listener answers questions Viva asked, plus the bounded "tell me in your words" box.
2. There is no open-ended conversation loop on the asking side.
3. A question no longer being asked records nothing.

## Why

**Viva decides *how* to ask, never *what* to ask.** The queue already decides
what, deterministically, ranked by consequence; the persona is a
rendering-and-interviewing layer over that machinery, plus new question
*sources* that feed the same queue. Everything below rests on four positions
that were settled before it and must not be undone: Viva never initiates
([experience-vision.md](experience-vision.md)); intelligence sits at the
question rather than the answer, in three tiers of silence, informed proposal
and real question ([where-the-intelligence-goes.md](where-the-intelligence-goes.md));
the model interprets, the person ratifies, code applies
([from-your-words-to-the-ledger.md](from-your-words-to-the-ledger.md)); and a
question the system cannot honestly ask is not asked — when a person cannot know
the answer, ask for the document that does ([learning-mode.md](learning-mode.md)).

The phrasebook beat live phrasing because intelligence belongs upstream:
impersonal, batched, cached, reviewable. A model writing sentences at design
time is a copywriter whose work can be read before anyone hears it. A model
writing sentences at run time is a system whose failure mode is *false*, not
merely stiff. Templates are allowed to sound wooden; they are not allowed to
invent. If real use shows moments templates demonstrably cannot carry, that is
the evidence that earns the live path — and the live path still arrives with a
validator that rejects any generated question containing a figure absent from
its inputs.

The persona pack has three kinds of entry, and the split matters. *Phrasings*
are one per question kind and moment, with named slots the deterministic intent
fills. *Moments* are the relationship lines — welcome on an empty vault, return
after a break, reassurance that stopping is fine, the "not essential, we can
move on" responses. *Tone rules* govern how new phrasings get written,
including by the copywriter model. The pack is impersonal by construction, which
is why it is the natural unit a translation replaces.

The queue stays the single front door as sources are added to it — expectations
that fire deterministically on evidence already in the ledger, failure findings
that already name their flagged figure and candidate rows, attribute blanks with
a consequence rank and an optionality flag. None of these is new intelligence.
The mortgage ask outranks nearly everything because one document settles
thirteen provisional transactions, and that is a computation, not a judgement.

Where answers land was designed to mint nothing. An attribute answer is a scoped
ruling — the generic scoped ruling earning another scope — graded `asserted`
and upgraded to `corroborated` when a document says the same thing. A general
asset is recorded at cost with valuation class `estimated`, because no issuer
attests what a car is worth. Multi-fact sentences return a *list* of proposals,
each individually confirmed, with the sentence stored verbatim so a better model
can re-derive more later.

Pacing is the memory of the conversation, and it is all derived. A decline is an
event, so declined questions stay silent until new evidence arrives on the same
subject — never on a timer. Resumption is a moment phrasing over state the
ledger already has: last session's answered count, the current top question. No
session store, because the events are the memory.

The boundaries are what this must never become: never a chat agent; never a
model choosing what to ask, because a model that picks questions could steer the
interview toward what it wants to know; never a nag; and never a schema or
registry entry that describes how to read a document, which is the parser
anti-goal wearing a new hat.

The build order had a reason. The voiced queue came first because it is small
and everything after it comes out already voiced. The expectations engine came
second because it was the highest-leverage move for a real vault. The asset
interview came last because it touches the write side — the expensive, one-way
side — so it got the most design care. The real presentation layer was held
until after the pack existed, because the soul is load-bearing and a surface
should be designed around Viva rather than have her added to it.

## Open

- The copywriter workflow: model drafts and author reviews, or author writes and model critiques?
- The voice eval. Correctness has a confidently-wrong rate; nothing yet measures "sounds like Viva", and the author's ear is the honest answer for now.
- When the real presentation layer's design conversation happens, and what it should be shaped by.
- Whether live per-question phrasing is ever earned, and what specific moments would earn it.

The asset interview this document seeded is superseded by
[the-interview-and-the-schema-pack.md](the-interview-and-the-schema-pack.md),
which owns the schema pack, the derived interview and their rules. Related:
[knowledge-and-expectations.md](knowledge-and-expectations.md),
[the-question-queue.md](the-question-queue.md),
[verification-findings-and-correction.md](verification-findings-and-correction.md),
[viva-listens-and-speaks.md](viva-listens-and-speaks.md),
[categories-and-tags.md](categories-and-tags.md).
