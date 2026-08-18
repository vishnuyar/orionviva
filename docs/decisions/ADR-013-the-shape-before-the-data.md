# ADR-013 · A Sentence's Shape Is Authored Before Its Data — in both directions

**Status:** Accepted — this record carries decisions Vishnu made across the shape
cycle (§§19–27, 2026-08-05/06) and shipped in `07d9520` and `24d938d`; the file
itself waits at the commit gate like any tracked change · **Date:** 2026-08-08 ·
**Decided by:** Vishnu · **Binds:** the answer path and the question path, both
surfaces, every planner · **Door type:** the **ordering** is one-way in trust —
the first sentence composed after its data is seen is a tailored sentence whether
or not anyone notices; the **mechanism** (which planner, which protocol, which
model) is two-way and deliberately so
**Invariants touched:** T1 (a figure has an identity; a grade is inherited from
operands, never declared by a caller) · T2 (arithmetic is deterministic; models
never certify) · T3 (raw capture — every shape and every binding is recorded) ·
T8 (models pinned, provider-swappable, never trusted) · X2 (uncertainty visible,
never decorative) · X3 (an irreversible action waits for an explicit yes, and a
confirmation is a question like any other)

---

## Context

This project has one sentence it keeps rediscovering, in a different place each
time:

> **A run holds a ledger of what it established, and an answer may say only what
> is in it.**

It was first written down in a brief that has since been archived, which ruled it
deserved a document *once proven* and named its first three instances. All three
are shipped:

1. **Figure identity** (T1, refined 2026-08-04). Every number a tool asserts is
   emitted with an id, and an answer cites the id rather than restating the
   value — so a number no tool emitted has nothing to cite.
2. **Names.** An account is licensed by a read, in the full form the read gave
   it. A bare four-digit fragment refuses, because it looks exactly like an
   amount.
3. **Dates.** A date is licensed by the read that carried it, and its parts are
   bounded tokens rather than an unbounded number.

The fourth instance is the general case, and it is what this ADR records:
**shapes and bindings.** An answer is a structure the machine built out of things
the run established, not a sentence a model wrote about them. That is why these
belong in one decision rather than four: the first three are the rule applied to
three kinds of token, and the fourth is the rule applied to the sentence itself.

The evidence that made this writable is that it has now met real data three
times. The load-bearing assumption — that a capable model, shown no data at all,
can author a well-formed shape — **held**: seven shapes authored and none
rejected on one local model, one authored and accepted first try on another under
the text protocol. That measurement is what turns this from a design intention
into a decision worth pinning. The same runs also produced the residuals in §4,
which are recorded here rather than in a footnote, because an ADR that reported
only the confirmation would be doing the thing this project exists not to do.

---

## Decision

**1. The ordering is enforced, not requested.** A turn has three stages and they
run in this order:

- **The shape**, committed before any tool is on the table: clauses of literal
  words with typed holes in them, and **no digits anywhere**. Nothing has been
  read, so no claim can be tailored to a figure that turned up.
- **The reads.** Everything a read establishes gains an identity in this run's
  own ledger — figures, the accounts and counterparties it spoke about, the days
  its results carry, the spans its documents attest, and the caveats it wrote
  about its own numbers.
- **The bindings.** The planner says which thing in that ledger fills which hole.

**2. A run's ledger is the whole of what may be said.** Nothing may appear in an
answer that no read established. This is the rescued sentence, in force.

**3. Every binding is a reference, never text.** A model names a thing; it never
writes a value. It is not enough that code chooses the shape: if the model chose
which figure fills a hole by writing the figure, tailoring would return through
the binding one layer down and harder to see.

**4. What is checked is the structure, never the sentence.** Every hole has one
binding and every binding names a hole; the thing referred to exists in this run's
ledger; its type is the type the hole declared; a figure filling a magnitude hole
measures the quantity that hole asked for; a figure about money standing on no
record refuses; every caveat riding behind a bound figure is placed. **There is
no scanning, no token matching, and no list of what may be said.**

**5. The quantity check is code comparing two declarations, and this does not
re-derive ADR-010.** The tool that emitted a figure declared what it measured;
the shape declared what its sentence is asking for; both are members of one
closed list; the check is an equality test between two strings the code itself
put there. **No model is asked to check another model's work.** ADR-010 —
verification never moves into model weights — is untouched by this, and it is
stated here explicitly so that a later reader who finds a model on both sides of
a check does not conclude the two decisions conflict. They do not: the model
proposes structure at both ends and certifies nothing at either.

**6. A hole nothing can fill costs its clause, not the turn.** The clause is
dropped and a phrase from the persona pack says what could not be established, so
a partial answer with a stated gap is the ordinary way this degrades.

**7. A refusal is shaped blind too.** It is a reviewed sentence in the persona
pack, one per machine tag, written before the turn that needed it and chosen by
the tag alone. Nothing is composed at the moment of refusing, so a refused turn
costs no model call and binds nothing. Where a refusal does carry holes, **code
fills them from the run's own record** — for the reason in §3.

_**Amended 2026-08-17 — a refused turn may now say two reviewed sentences, and
nothing above changes.** Where the delivery established nothing, or the turn
spent its whole budget of calls, the verdict in the pack's words for the
runner's own tag is followed by the cause, in the pack's words for the machine
tag of the read that stopped last. Both were written before the turn and chosen
by a tag alone, so the ordering is untouched and a refused turn still costs no
model call. The causes that may be spoken are a closed set of seven read tags in
`viva/tools/envelope.py`, held to `pack-v11`'s sentences at build time, and not
one of those sentences has a slot: the reads' own texts quote the value the
caller supplied, and the caller is a model this project has recorded inventing
filter values when refused, so a hole there would tell a person that a category
they never named is absent from their records. The interim cost recorded under
_Alternatives_ narrows accordingly — a refusal still offers nothing the run
could have told them instead, which is what `docs/the-suggestions-channel.md`
exists to restore, but it is no longer one sentence and no more._

**8. The question direction obeys the same rule, mirrored.** A question declares
typed slots and the model fills those; deterministic code decides what was said
and what to write. **A model writes no digits, in either direction.** Model
proposes structure, code disposes, both ways. An answer that would do something
irreversible comes back as a proposal, and the yes that applies it is a question
like any other — a declared slot, a model reading the person's words into it,
code deciding (X3, as refined 2026-08-06).

**9. Every shape and every binding is recorded.** What was said is recorded as
the *structure* it was — the committed shape and its bindings ride into
`ReadRecorded` — so a sentence's provenance is structural rather than a field
someone remembered to set. Raw-capture rules bind: never delete a capture, never
drop `prompt_version` or `model`.

**10. The planner is an interface, not a provider.** Any callable that, shown the
question, the tool schemas and the results so far, returns the next step is a
planner — a native tool-calling adapter, a text-protocol adapter parsing a JSON
block, a scripted function in a test. The mechanism runs identically for all of
them, which is what keeps §11 a swap rather than a rewrite.

**Amended 2026-08-16 — an answer may now say more than one of a thing, and none
of the above changes.** A hole may be of type `rows`, and a binding may name a
whole read — `{"read": "r2"}`, a sixth kind of reference — rather than one thing
in it. The machine writes a line per figure that read took over a named slice;
the model writes no words at any line and never learns how many there are, which
is §3 taken further rather than loosened: a shape authored blind could not carry
a clause per row, and the way out was the model referring to more, not writing
more. The run's ledger of §2 accordingly holds **readings** alongside figures,
entities, days, spans and caveats — a read is a thing an answer can refer to, and
two identical reads are two readings, since a person shown a block is shown one
particular reading of their ledger.

It also pays part of one residual below. *A model-authored template is reviewed
by nobody* is paid **zero times inside a block**: every line is a reviewed pack
sentence with machine-written holes, so the unreviewed prose is the one clause
introducing the list however many rows follow. The residual stands everywhere
else. *Capability honesty is unbuilt* stands too, and now has its missing input:
`query_ledger` answers what labels a vault holds under any of its groupings,
which is the enumeration nothing could do before.

**Amended 2026-08-18 — a magnitude hole declares two things, and §4's list of
what is checked gains two comparisons.** A hole holding a magnitude said what
its number measures. It now also says **what set that number is a number of**:
the axes its sentence narrows on, drawn from the closed vocabulary a figure's
boundary already declares into, or `whole` for everything the quantity ranges
over. It is a set, because a sentence narrows on as many axes as it names;
`whole` is exclusive of the rest; and the declaration is required on every
magnitude hole and forbidden on every other, because a field a model may leave
out is a check a model can switch off. This is not §7's rule reversed. A
boundary is not among the fields a planner is shown and the shape is authored
before anything is read, so what the hole declares is a claim about the sentence
being written rather than a property of a figure the machine holds — the same
footing the quantity declaration has stood on since the mechanism shipped.

**The third comparison:** the axes a figure declares it is the intersection of
and the axes a hole declares its sentence narrows on are **equal**, or the
figure is not what the sentence is about. Equality both ways rather than
containment — one counterparty's total for one month fills neither a hole about
that counterparty nor a hole about that month, and that counterparty's
whole-history total fills neither of those either. A figure that declares no set
at all fills none of them: nothing has said what it was taken over, which is not
the same as saying the set was everything.

**The fourth takes the clause as its unit**, because every check above resolves
one hole at a time against everything the run established, so a real figure of
one thing and a real thing of the same kind can each be true and belong to
different sentences. Where a clause states a figure and names, through a hole, a
thing of a kind that figure was cut by, the figure's own boundary must name what
the clause names, on every axis it was cut by. **An entity belongs to a figure
when the figure's own boundary names it.** Both halves are strings the code
wrote, and no word of the clause is read. The same move answers a day and a
span: a `date` hole is filled from the `dated` of a figure its own clause
states, and a `period` hole from a span such a figure declares itself taken
over — never from the days or the spans the turn as a whole happens to carry.
Arithmetic composes the new declaration by agreement or by nothing: identical
operand boundaries are inherited, differing ones produce a number over neither
set that fills no hole of any kind, and a literal contributes no set and takes
none away. Two refusals join the vocabulary of §7 — one for a figure taken
over a different set, one for a figure of a different thing, because what
each asks of the model differs — so it stands at twenty-one tags.
`speak-shape-v10`, `speak-repairs-v3`, `speak-final-v13`, `pack-v13`.

---

## What this costs, honestly — the residuals

These are properties of the decision as shipped, not defects awaiting a fix. Two
of them are the reason the companion **design doc** over the vocabulary and the
codecs is deliberately not yet written.

**A model-authored template is reviewed by nobody before it is spoken.** A
persona-pack phrasing is read by a person before release and frozen by digest. A
shape is authored at the moment of answering, by a model, and reaches a person
without any review at all. The structure is checked exhaustively; the *prose
around the holes* is checked by nothing. So a claim that no figure measures can
still be asserted in the literal words of a clause, and a magnitude spelled out in
words rather than digits is a blind guess rather than a laundered figure — but is
still not caught. This is the honest price of the ordering rule, and it is paid
knowingly: a pre-written template library would have no such gap and would also
be unable to answer a question nobody anticipated. **The road back is named in
§11.**

_**Amended 2026-08-17 — the residual narrows in one respect and stands in every
other.** What closes: a clause comes into being only if it places at least one
hole, so there is no longer a clause with no hole for prose to be *around*.
Every clause is droppable, every asserting clause answers for its records, its
caveats, its statement of where its claim ends and the answer's grade, and a
turn whose clauses all rest on something the run could not establish refuses
rather than speaking. The instance the 2026-08-16 amendment named — "the
unreviewed prose is the one clause introducing the list however many rows
follow" — is closed with it: the introducing words and the `rows` hole are one
clause, so a list nothing can fill takes its own introduction away rather than
leaving a person a colon with nothing under it. What stands: the residual
itself, unchanged. The words a model writes **around** a hole are read by nobody
before a person reads them, and a figure that is right can still be described
falsely by them. A hole makes a clause conditional on something the run
established; it says nothing about whether the words are true of it._

_And one kind of hole rests on the person rather than on a read: a `supposed`
hole holds a value the person put into their own question, cites no record and
carries no grade, so a clause that no read touched can still be spoken. It is
narrower than what closed — the question must contain the value whole, and the
clause drops when it does not — but a hedge written around such a hole is the
old shape at one remove, and it is where the prose residual above is widest._

_**Amended again 2026-08-17 — a block asks one more thing of the read it names.**
The 2026-08-16 rule stands: a line per figure that read took over a named slice.
Added to it, a read whose figures name slices of **more than one kind** fills no
block and the binding refuses under the existing wrong-kind tag, because one
read may cut the same set several ways at once — a figure per account and a
figure per month over the same movements — and a line per slice would state the
same money once for each way it cuts. The guard reads the declared kinds and is
keyed to no read and no tool. Which grouping a list of such a read should
enumerate is undecided, and the guard is where that decision lands._

_**Amended once more 2026-08-17 — a shape can no longer ask how well a figure is
stood behind, and §4's list of what is checked loses a line.** `grade` is not a
type a hole may declare. A shape is authored before anything is read, so a
`grade` hole asked a model to reserve a place for a word it could not know would
exist, and every move left when it did not was bad: bind something else and pass
the type check, reword and be refused by the ordering rule, or leave it unbound
and lose the clause together with any correct figure it also stated. This is the
same argument that retired the caveat hole on 2026-08-09 and placed a figure's
scope the day after, and it generalises: **a property of a figure that the
machine holds is placed by the machine, never asked for through a hole.** The
runner now states the grade of what the answer stated, in one whole reviewed
`pack-v12` sentence per word on the ladder, after the boundary sentences and
before the caveats; `speak-shape-v9` teaches the shorter grammar. Nothing about
the ordering changes — the sentence is chosen by a word the machine computed,
exactly as a refusal is chosen by a tag, and no clause and no binding is
involved. The `ungraded_figure` tag and its reviewed sentence go with the hole,
since nothing can raise it any more; the vocabulary of §7 stands at nineteen
tags._

_It also widens one residual by a hair and closes nothing. The prose a model
writes **around** a hole is still read by nobody, so a model may still type the
word "verified" into a clause of its own — but it is now betting against a
machine-placed sentence in the same answer, which will contradict it when the
bet was wrong._

_**Amended 2026-08-18 — the residual narrows at its sharpest point, and the
amendment says so in both directions.** What closes: a sentence can no longer be
about a set the figure beside it was not taken over, and a sentence naming a
thing through a hole can no longer state a different thing's number. Those were
the two ways a true figure was described falsely with no word being read, and
they are closed by two declarations rather than by anyone reading one. What
stands, unchanged: the words **around** a hole are read by nobody. A clause may
still write the name of a slice into its own literal text, declare `whole`, bind
a real total and pass. Closing that would take the further rule that a figure
naming a slice may only be stated in a clause binding that slice's entity, and
it is rejected for now on a measured cost rather than on taste: of the nine ways
a set may be narrowed only three have an entity a hole could bind, so the rule
would make every breakdown by subcategory, by tag, by currency and by month
unspeakable — a large silent loss to close a loophole nobody has yet measured
being walked through. Three narrower ones ship open beside it. Two figures and
two entities of one kind in one clause can be exchanged, because closing that
needs positional pairing and position is the sentence. The **value** of a period
is unchecked, because the vocabulary holds no entity for a span, so the check
compares the axes and only the axes. And a value the person supposed declares no
set at all — it is not a measurement over one — so a hedge written around such a
hole is still where this residual is widest._

**Viability is per-model, and the model in force was on the wrong side of it.**
The blind-authoring assumption was phrased as "a capable model", and that phrase
was doing quiet work nobody had costed. On the two-model run, one model emitted
**zero tool calls across twenty native-protocol replies** — advertising the
capability, producing prose, inventing a third-party application and two tool
names — and so never reached a shape at all. Under the text protocol the same
model parsed all nine replies cleanly and authored a well-formed three-clause
shape first try. **A channel failure, not a capability one — and the product has
no way to notice it.** Nothing detects that a configured model never calls a
tool. This decision therefore rests on a property of the model in force, and the
shipped default did not have it.

**The check has a known hole and the vocabulary a known collision.** The rider of
§5 refused a bad binding correctly one turn earlier in the same session and was
then defeated by a division, because it compares a result's declaration against a
hole's and never the operands
([#4](https://github.com/vishnuyar/orionviva/issues/4)); and one renderer writes
every proportion a hundred times too small, because `ratio` means per-one on the
computed side and per-hundred on the written side
([#3](https://github.com/vishnuyar/orionviva/issues/3)). **A wrong number reached
a person on 2026-08-07** with every trust signal correct, and while none of the
four compounding faults was in the shape mechanism, two of them were in the check
this ADR names as the thing that stops a true number being spoken as an untrue
claim. Recorded here so that this document cannot be read, in the window before
those are fixed, as a claim that the guarantee is currently whole.

**Capability honesty is unbuilt.** Nothing computes from the registry whether a
slot can be filled before a call is made, so "I cannot answer that" is a
judgement rather than a property. `{document}` is the standing proof: a declared
slot type, taught to the model and placed by three question phrasings, that no
tool emits.

---

## Promise-compatibility analysis

- **Promise 1 — never bluff a number.** This is the mechanism that serves it, and
  the residuals above are where it is currently short. The structural half holds:
  a number no tool emitted has nothing to cite, and a figure about money standing
  on no record refuses.
- **Promise 2 — say what is uncertain.** A hole nothing can fill drops its clause
  and says so; a value the arithmetic could not write exactly carries the term
  that says so, placed by the figure's own exactness rather than by anyone
  remembering (X2).
- **Promise 4 — nothing leaves silently.** Unchanged. This adds no outbound flow
  and no class of recipient; it constrains what comes *back*.
- **Promise 8 — nothing irreversible without your explicit yes.** Intact via §8.
  The 2026-08-07 audit is the caution here: the gate held and **two duplicate
  accounts were created anyway**, because the sentence the person was given to
  decide on was false about their own vault. An intact gate in front of a false
  proposal is a formality
  ([#2](https://github.com/vishnuyar/orionviva/issues/2)).

No promise is added or amended by this ADR.

---

## Alternatives considered

**A reviewed template library — every sentence pre-written and frozen.** The
strongest alternative, and it wins on exactly one axis: every sentence a person
reads would have been read by a person first, which is the residual §4 opens.
Rejected because a fixed library can answer only anticipated questions, and the
product's whole claim is that it answers what you actually ask. **Not foreclosed,
and deliberately so:** §9 records every shape, which keeps open a *reviewed shape
library* — recurring shapes reviewed and promoted, a promoted shape preferred
over a fresh one. That is the template library **earned** rather than assumed. It
costs nothing to keep open and nothing has been built on it.

**The model writes the sentence; a checker reads it afterwards.** The obvious
design, and the one this replaces. Rejected because checking prose means
scanning, and scanning means a list of what may be said — which is a word-list
mechanism, a standing anti-goal, and was tried: a gate built on that principle
was shipped, then falsified by the acceptance run that tested it, and deleted. It
also fails the ordering test at the root: a sentence composed after its data was
seen is a tailored sentence, and no downstream reader can tell a tailored true
sentence from an untailored one.

**The model writes digits and code verifies them.** Rejected. It makes every
figure a re-derivation problem, it puts the model on the certifying side of
ADR-010, and it gives up the one property that makes the rest cheap: if the model
never writes a digit, a digit in an answer that no tool emitted is impossible
rather than improbable.

**Keep the refusal path composed by a model.** Rejected in §27 of the shape
brief. A composed refusal is a sentence written after the data was seen — the
exception would have been roughly a third of turns wide — and the reference run
spent **67% of its model budget on refused turns**. The accepted interim cost is
that a refusal now says strictly less: one reviewed sentence per tag, and no
"here is what I could tell you instead". `docs/the-suggestions-channel.md` exists
to restore it.

---

## Consequences

- **The design doc over the vocabulary and the codecs waits**, and this ADR is
  the reason it can. It is the how-it-works document, and documenting a renderer
  that is wrong by a hundred and a check defeatable by a division would be
  documenting a lie for the length of one cycle. When it is written it owes two
  concepts declared nowhere today: the **stock/flow split** in
  `product/viva/quantity.py`, and **`gross_flow`'s deliberate
  direction-blindness**, which is a decision and not an omission.

  **Amended 2026-08-18 — the deferral's first ground is spent, so the document
  is owed rather than waiting.** The hole this bullet named is closed: a figure
  can no longer be spoken as a claim about a set it was not taken over, and
  arithmetic no longer launders a scope, because a computed figure inherits its
  operands' declaration or declares itself over neither set. The renderer that
  is wrong by a hundred is untouched and belongs to the wording item. What the
  document owes has grown with the closure: four declarations compared pairwise,
  a rule whose unit is the clause rather than the hole, and a composition rule
  for boundaries through arithmetic — a mechanism a later reader cannot
  reconstruct from amendments spread across three files. It is chartered as its
  own item, after the reachability and wording items, and this is the record of
  the debt and of why it came due.
- **A model that never calls a tool must become detectable.** The residual in §4
  is not a thing to live with quietly: nothing in the product notices, and ten
  turns cost four minutes each to produce ten identical apologies touching no
  data. Two questions are unruled — whether the runner detects it and falls back
  to the text protocol, and what the shipped default is.
- **The eval gains subjects it did not have:** shapes authored and rejected, holes
  that could not be filled, clauses dropped, and the rate at which the quantity
  check refuses. A check that never refuses is not checking.

  **Amended 2026-08-16 — half of that is now measured, and not in the eval.**
  Two of the four subjects exist: `viva.debug.speak` counts shapes authored and
  shapes rejected over every recorded exchange, and breaks the second down by
  the repair the check named — which includes both ways the quantity check
  refuses, a hole that measures nothing carrying a quantity and a hole that
  names one its kind cannot be of. It prints them at the head of its listing.
  **The other two are still counted by nothing**: holes that could not be
  filled, and clauses dropped.

  The consequence is not discharged, because a debug reader is not the eval.
  The numbers exist only when a person opens the vault and runs the command;
  nothing watches them, nothing fails on them, and no change is measured
  against them between one release and the next. What was bought is that a
  question lost this way can now be counted after the fact instead of
  reconstructed from a person's memory of losing it. Moving them into the
  eval harness remains owed.
- **A pack's stamp still carries no digest** (`"pack-v5"`, not
  `pack-v5@aefde3a9`), while §9 now records a typed template. A typed shape is a
  stronger artifact than a whitelisted one and deserves a stronger pin; that work
  folds into the ledger/event-store ADR.
- **`prompt_version` becomes load-bearing in a new place.** A recorded shape is
  only interpretable against the prompt that taught the model to author it, which
  is why the release rule — a new version file, never an edit — binds harder
  after this than before.

---

## Would reverse this

**The ordering is one-way in trust.** Composing a sentence after its data is seen
is a different product, and no amount of downstream checking recovers what the
ordering gives for free. Reversing it would mean accepting that the answer path
can tailor, and saying so publicly.

**Everything else is two-way and cheaply so.** The planner is an interface (§10),
so a protocol, a provider or a model is a swap. The refusal path's pack sentences
are data. The shape library (§ *Alternatives*) is an addition that would move the
product *toward* review without changing the rule.

**What would most like to reverse a residual:** a local model that reliably calls
tools, which turns the per-model viability caveat from a live risk into a
footnote — and a capability-honesty layer, which turns "I cannot answer that"
from a judgement into a property of the registry.
