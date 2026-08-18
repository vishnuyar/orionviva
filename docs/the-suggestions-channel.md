# The suggestions channel — what Viva offers when she cannot answer

**State:** design-only
**Rules:** VOICE-80, VOICE-81, VOICE-82, VOICE-83, VOICE-84, VOICE-85

Nothing here is built and no option is chosen. This records a decision already
made, the shape it implies, and the questions a later cycle must answer.

## Rules

### VOICE-80 — a refusal certifies nothing and carries no figure
**State:** enforced
**Code:** product/viva/tools/runner.py:350 (`_refused`)
**Test:** product/tests/test_speak.py::test_a_number_echoed_by_a_refusal_cannot_ground_an_answer

1. A refusal asserts nothing and binds nothing.
2. A number echoed by a refusal cannot ground an answer, and a refusal's record ids do not join the grounding pool.

### VOICE-81 — nothing composes words at the moment of refusing
**State:** enforced
**Code:** product/viva/tools/runner.py:322 (`REFUSAL_TAGS`), :341 (`REFUSAL_MOMENT`)
**Test:** product/tests/test_persona_pack.py::test_every_way_a_turn_can_refuse_has_a_reviewed_sentence

1. A refusal is a reviewed sentence in the persona pack, chosen by machine tag, costing no model call.
2. A tag with no sentence is a build failure, not a silence discovered by the person it happens to.
3. A sentence no tag can reach is dead voice and also fails the build.
4. No sentence says the machine's tag out loud.

### VOICE-82 — a turn that ends with nothing says the cause as well as the verdict
**State:** enforced
**Code:** product/viva/tools/envelope.py:268 (`SPEAKABLE_REFUSALS`), product/viva/tools/runner.py:342 (`DIAGNOSIS_MOMENT`)
**Test:** product/tests/test_persona_pack.py::test_every_refusal_whose_cause_may_be_spoken_has_a_reviewed_sentence

1. Where the read that stopped last carries a tag whose cause may be spoken, a second reviewed pack sentence follows the verdict.
2. Not one of these sentences takes a slot, so no value a read was called with can reach a person.
3. The verdict is said first and is unchanged by the cause.

### VOICE-83 — a suggestion binds through the same gate as an answer
**State:** unmet
**Code:** none found
**Test:** none

1. A suggestion is a shape with typed holes like any other; its figures are bound to what a read established, or it says nothing.
2. There is no second, looser path by which a figure reaches a person.

### VOICE-84 — a suggestion is never a proposal
**State:** unmet
**Code:** none found
**Test:** none

1. A suggestion is structurally distinct from an answer, labelled as such, and never presented as the answer.
2. Nothing a person does to a suggestion may write to the ledger without the explicit yes an irreversible action already requires.

### VOICE-85 — a suggestion respects a decline
**State:** unmet
**Code:** none found
**Test:** none

1. A thing set aside stays set aside; a suggestion never becomes a nag.
2. On the asking side especially, a suggestion must not narrow what a person would have said.

## Why

**The problem.** The answer path refuses when it cannot ground what was asked.
A refusal is honest and it is also a dead end: the person learns that Viva could
not answer and nothing else, while the run frequently holds things it *did*
establish that would genuinely help — the read succeeded, the question it
answered was simply not the one asked. An acceptance run made the cost concrete:
five of nine answerable questions refused, four of them hiding a correct and
useful result.

The obvious fix — let a refusal say what it can — was rejected for a reason
worth keeping. A refusal is composed *after* every result is known, so anything
it volunteers is chosen with full knowledge of what turned up. The redesign's
load-bearing property is that a claim's shape is committed before its data
exists, precisely so a claim cannot be tailored to a figure that happened to
appear. Letting a refusal carry figures reintroduces tailoring through the one
door the ordering rule cannot cover.

**The ruling: the refusal stays clean; what is useful moves to a separate
channel.** A refusal certifies nothing. Beside it, a **suggestion** —
structurally distinct, labelled as such, never presented as the answer. The
reasoning is that the tailoring worry was never that a model *chose* something
true; it was that a chosen thing arrives wearing the authority of an answer.
Labelling the channel removes the authority, so the choice stops mattering. That
dissolves the tension rather than trading against it: the property survives
whole, and the information is not thrown away.

**The bar this sets is high, and higher than it looks.** Almost nothing on the
refusal path is a model's to shape. A refusal is not composed at all — it is a
reviewed sentence chosen by machine tag, binding nothing, costing no model call
— and a turn that ends with nothing now says the cause as well as the verdict,
from a second reviewed sentence chosen the same way. What a model still has no
hand in is the words: nothing is composed at the moment of refusing, no sentence
in that set has a slot, and no value a read was called with can reach a person.
A suggestion carrying a figure picked after every result was seen would be over
that line rather than near it.

**And the real vault has made the problem sharper.** On a local run a refusal
was delivered while the correct figure, at the top grade and bound to the right
hole, was already sitting in the run — lost to the syntax of a reference
([issue #8](https://github.com/vishnuyar/orionviva/issues/8)). That is the case
at its most acute: not a run that established something adjacent, but a run that
established the answer and said nothing. Whatever this channel becomes should be
designed knowing the thing withheld is sometimes not a consolation but the
answer itself.

**Two directions, and their risks are not the same.** This is the part a later
cycle must not flatten.

*While Viva speaks*, the person asked something and it could not be answered, so
a suggestion offers what could be. Its risk is **misreading**: a true sentence
sitting next to a question it does not answer is the easiest place in the
product for a person to take one thing for another. *"I could not total your
groceries, though X moved through that card"* is true, adjacent, and one
careless reading from being heard as the grocery figure.

*While Viva asks*, the queue puts a question and the product already believes
something, so a suggestion offers that belief. Its risk is **leading**: a
suggested answer shapes the answer given, and on the question side an answer
becomes a durable, generalising ruling. A merchant-scope ruling settles every
transaction from that counterparty, past and future. A bad answer misleads once;
a bad ruling persists. This half is not new ground —
[where-the-intelligence-goes.md](where-the-intelligence-goes.md) already argues
that the product forms the belief and the person confirms it, and the three
tiers are the same idea before it had this name.

**The question that decides the shape:** is a suggestion *a question you could
ask*, or *an answer to a question you did not ask*? The first — *"I could tell
you what moved through that card"* — names a capability, binds nothing, carries
no figure, and is structurally incapable of being mistaken for an answer. Small,
and weak. The second carries real bound figures, is far more useful, and is
exactly the shape the misreading risk describes. The stated intent — *not
certifying an unknown answer, but giving the person some information* — points
at the second, and if that is where it lands, the decision travelling with it is
whether a suggestion's **words** are constrained more tightly than an answer's,
given that it sits by construction next to a question it does not answer.

**What it inherits and must not lose.** The binding gate, unchanged. The open
gap, unclosed and *concentrated* rather than merely inherited: nothing examines
the prose *around* the holes, so a suggestion cannot fabricate a number and can
still assert a claim nothing measured — and it sits adjacent to a question it
does not answer. And X3: a suggestion is not a proposal.

**What it must not become.** A second answer path — one binding gate, one way a
figure reaches a person, and a suggestion with its own looser check has defeated
the redesign. A nag. Or a leading question, because a suggestion that narrows
what a person would have said produces a confirming answer, and that
confirmation is what gets recorded, at grade `verified`, by a human.

## Open

1. Is a suggestion a capability, or an adjacent answer?
2. Is a suggestion's prose constrained more tightly than an answer's?
3. Do the two directions share one mechanism, as the ask and answer paths now do, or do their different risks earn different rules?
4. How many suggestions is too many, and what ranks them? The queue already ranks by consequence and that may be the same primitive again.
5. Is a suggestion recorded? An answer is captured; a suggestion offered and ignored may be worth knowing about, or may be noise.
6. Issue #8 — a correct, top-grade figure bound to the right hole, lost to the syntax of a reference and delivered as a refusal.
