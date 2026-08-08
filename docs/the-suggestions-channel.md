# The suggestions channel — what Viva offers when she cannot answer

**Status:** INTAKE, not a design. Nothing is built and no option is chosen. This
records a decision already made, the shape it implies, and the questions a later
cycle must answer — so that cycle starts from a position rather than from
memory. · **Opened:** 2026-08-06 · **Checked 2026-08-08:** coherent, with one
correction of tense and one addition of evidence, both below.

**Read §1's "a refusal is composed after the model has seen every result" as
history, not as code.** By the end of the same cycle a refusal stopped being
composed at all: it is a reviewed sentence in the persona pack chosen by machine
tag, binding nothing, costing no model call. That does not weaken the ruling in
§2 — it is why the ruling was cheap to take, and it raises the bar for anything
built here, because a suggestion would be the *only* thing on the refusal path
that a model has any hand in.

**And the real vault has since made the problem sharper.** On a local run a
refusal was delivered to a person while the correct figure, at the top grade and
bound to the right hole, was already sitting in the run — lost to the syntax of
a reference ([issue #8](https://github.com/vishnuyar/orionviva/issues/8)). That
is the §1 case at its most acute: not a run that established something adjacent,
but a run that established the answer and said nothing. Whatever this channel
becomes should be designed knowing that the thing withheld is sometimes not a
consolation but the answer itself.

**Invariants touched:** T1 (a suggestion carrying a figure stands on a record like
any other) · T2 · X2 (a suggestion is uncertainty made visible, or it is
decoration) · **X3** (a suggestion must never become a proposal a person can
accept without meaning to) · I1/I2.

---

## 1. The problem that produced it

The answer path refuses when it cannot ground what was asked. A refusal is
honest and it is also a dead end: the person learns that Viva could not answer,
and nothing else. Meanwhile the run frequently holds things it *did* establish
which would genuinely help — the read succeeded, the question it answered was
simply not the one asked.

Acceptance run #2 made the cost concrete: **five of nine answerable questions
refused**, four of them hiding a correct and useful result. The person got
"I could not stand this answer on what I hold" and nothing more.

The obvious fix is to let a refusal say what it *can*. That was rejected, for a
reason worth keeping: a refusal is composed **after** the model has seen every
result, so anything it volunteers is chosen with full knowledge of what turned
up. The redesign's load-bearing property is that a claim's shape is committed
before its data exists, precisely so a claim cannot be tailored to a figure that
happened to appear. Letting a refusal carry figures reintroduces tailoring
through the one door the ordering rule cannot cover.

## 2. The ruling (2026-08-06)

**The refusal stays clean; what is useful moves to a separate channel.**

A refusal certifies nothing and asserts nothing. Beside it, a **suggestion** —
structurally distinct, labelled as such, and never presented as the answer.

The reasoning is that the tailoring worry was never that a model *chose*
something true. It was that a chosen thing arrives wearing the authority of an
answer. Labelling the channel removes the authority, so the choice stops
mattering. This dissolves the tension rather than trading against it: the
property survives whole, and the information is not thrown away.

## 3. Two directions, and their risks are not the same

The channel exists on both sides of the machine, and this is the part a later
cycle must not flatten.

**While Viva speaks** — the person asked something and it could not be answered.
A suggestion offers what could be. Its risk is **misreading**: a true sentence
sitting next to a question it does not answer is the easiest place in the
product for a person to take one thing for another. *"I could not total your
groceries, though X moved through that card"* is true, adjacent, and one careless
reading away from being heard as the grocery figure.

**While Viva asks** — the queue puts a question and the product already believes
something about the answer. A suggestion offers that belief. Its risk is
**leading**: a suggested answer shapes the answer given, and on the question side
an answer becomes a **durable, generalising ruling**. A merchant-scope ruling
settles every transaction from that counterparty, past and future. A bad answer
misleads once; a bad ruling persists.

This half is not new ground. `where-the-intelligence-goes.md` already argues that
**the product forms the belief and the person confirms it**, and the three tiers
(silence · informed proposal · real question) are the same idea before it had
this name. A later cycle should treat the asking-side suggestion as that work
continued, not as something fresh.

## 4. The question that decides the shape

**Is a suggestion a question you could ask, or an answer to a question you did
not ask?**

- **A question you could ask** — *"I could tell you what moved through that
  card."* It names a capability. It binds nothing, carries no figure, and is
  structurally incapable of being mistaken for an answer. Small, and weak.
- **An answer to a question you did not ask** — *"I could not total groceries;
  X moved through that card."* It carries real bound figures and is far more
  useful. It is also exactly the shape §3's misreading risk describes.

Vishnu's stated intent — *"not certifying unknown answer but giving user some
info"* — points at the second. If that is where it lands, the decision that
travels with it is whether a suggestion's **words** are constrained more tightly
than an answer's, given that a suggestion sits by construction next to a
question it does not answer.

## 5. What it inherits, and must not lose

- **The binding gate.** A suggestion is a shape with typed holes like any other.
  Its figures are bound to what a read established, or it says nothing. There is
  no second, looser path to a person.
- **The open gap.** Nothing examines the prose *around* the holes. A suggestion
  cannot fabricate a number and can still assert a claim nothing measured. That
  gap is named in the redesign brief and is not closed by this channel — it is
  concentrated by it, because a suggestion is adjacent to a question it does not
  answer.
- **X3.** A suggestion is not a proposal. Nothing a person does to a suggestion
  may write to the ledger without the explicit yes an irreversible action
  already requires.

## 6. What it must not become

- **A second answer path.** One binding gate, one way a figure reaches a person.
  A suggestion that gets its own looser check has defeated the redesign.
- **A nag.** The decline mechanism exists and a suggestion must respect it: a
  thing set aside stays set aside.
- **A leading question.** On the asking side especially — a suggestion that
  narrows what a person would have said produces a confirming answer, and that
  confirmation is what gets recorded, at grade `verified`, by a human.

## 7. Open, for the cycle that takes this up

1. The §4 question: capability, or adjacent answer.
2. Whether a suggestion's prose is more constrained than an answer's.
3. Whether the two directions share one mechanism, as the ask and answer paths
   now do, or whether their different risks earn different rules.
4. How many suggestions is not too many, and what ranks them — the queue already
   ranks by consequence and that may be the same primitive again.
5. Whether a suggestion is recorded. An answer is captured; a suggestion offered
   and ignored may be worth knowing about, or may be noise.
