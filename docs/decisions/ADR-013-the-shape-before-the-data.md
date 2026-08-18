# ADR-013 · A Sentence's Shape Is Authored Before Its Data — in both directions

_This records reasoning, not current behaviour._

**Status:** Accepted · **Date:** 2026-08-08 · **Decided by:** Vishnu · **Binds:** the answer path and the question path, both surfaces, every planner · **Door type:** the **ordering** is one-way in trust — the first sentence composed after its data is seen is a tailored sentence whether or not anyone notices; the **mechanism** (which planner, which protocol, which model) is two-way and deliberately so

**State:** built
**Rules:** ADR-013
**Invariants touched:** T1, T2, T3, T8, X2, X3

## Rules

### ADR-013 — A run holds a ledger of what it established, and an answer may say only what is in it
**State:** enforced-with-exception
**Code:** product/viva/tools/shape.py:230 · product/viva/tools/runner.py:652 · product/viva/tools/runner.py:761 · product/viva/tools/runner.py:799 · product/viva/tools/compute.py:380 · product/viva/speak.py:604
**Test:** product/tests/test_shape.py::test_a_figure_that_states_no_set_fills_no_hole_asking_for_one

1. A turn runs in three stages and the order is enforced: the shape, then the reads, then the bindings.
2. The shape is committed before any tool is on the table — clauses of literal words with typed holes, and no digits anywhere.
3. Everything a read establishes gains an identity in that run's ledger: figures, the entities it spoke about, the days its results carry, the spans its documents attest, the caveats it wrote about its own numbers, and the readings themselves.
4. Nothing may appear in an answer that no read established.
5. Every binding is a reference and never text: a model names a thing and never writes a value.
6. What is checked is the structure, never the sentence. There is no scanning, no token matching, and no list of what may be said.
7. Every hole has one binding and every binding names a hole; the thing referred to exists in the run's ledger; its type is the type the hole declared; every caveat riding behind a bound figure is placed; and a figure about money standing on no record refuses.
8. A figure filling a magnitude hole measures the quantity that hole asked for — an equality test between two strings the code itself put there, both members of one closed list.
9. A binding fails where the figure's quantity is the vocabulary's own name for having no name: a quotient of two unlike kinds has no unit to be written in.
10. A binding fails where the hole asks for a quantity that asserts a direction by its own name and the figure's value denies it. Which quantities assert a direction is a closed declaration in the module that owns the vocabulary.
11. The axes a figure declares it is the intersection of and the axes a hole declares its sentence narrows on are equal, both ways, or the figure is not what the sentence is about. A figure declaring no set fills no such hole.
12. Where a clause states a figure and names, through a hole, a thing of a kind that figure was cut by, the figure's own boundary names what the clause names, on every axis. An entity belongs to a figure when the figure's own boundary names it.
13. A `date` hole is filled from the `dated` of a figure its own clause states, and a `period` hole from a span such a figure declares — never from the days or spans the turn as a whole happens to carry.
14. Arithmetic composes a boundary by agreement or by nothing: identical operand boundaries are inherited, differing ones produce a number over neither set that fills no hole, and a literal contributes none and removes none.
15. A hole nothing can fill costs its clause and not the turn; a pack phrase says what could not be established.
16. A clause comes into being only if it places at least one hole, refused where every clause is built.
17. A refusal is shaped blind: reviewed pack sentences, one per machine tag, written before the turn that needed them and chosen by tag alone. A refused turn costs no model call and binds nothing.
18. A refused turn may say two reviewed sentences — the verdict for the runner's own tag, then the cause for the machine tag of the read that stopped last, drawn from a closed set of read tags. No refusal sentence has a slot; where a refusal carries a hole, code fills it from the run's own record.
19. The question direction obeys the same rule mirrored: a question declares typed slots, a model fills them, deterministic code decides what was said and what to write. A model writes no digits in either direction.
20. An answer that would do something irreversible comes back as a proposal, and the yes that applies it is a question like any other (X3).
21. Every shape and every binding is recorded as the structure it was, riding into the capture event. Raw-capture rules bind: never delete a capture, never drop `prompt_version` or `model`.
22. The planner is an interface and not a provider: any callable that, shown the question, the tool schemas and the results so far, returns the next step is a planner.
23. A hole may be of type `rows` and a binding may name a whole read. The machine writes a line per figure that read took over a named slice; the model writes no words at any line and never learns how many there are.
24. A read whose figures name slices of more than one kind fills no block, because a line per slice would state the same money once for each way it cuts.
25. `grade` is not a type a hole may declare. A property of a figure that the machine holds is placed by the machine, never asked for through a hole.
26. A statement drawn from one figure's boundary is placed under the clause that bound that figure, said once within it and again under the next clause that makes it.
27. The one statement that is about the answer rather than about a figure — how many of the person's accounts the answer covers — is computed over the answer, placed once after the clauses, and placed only where every stated figure declares, as data, exactly which accounts it covers.

**Exception:** a `supposed` hole is exempt from rule 4 by construction — it holds a value the person put into their own question, so it cites no record and carries no grade, and a clause no read touched can still be spoken (product/viva/render.py:52, :382; product/viva/tools/runner.py:676). Separately, the prose a model writes *around* a hole is read by nobody before a person reads it. See *Why*, under the residuals, for what that costs and for the three narrower cases that ship open with it.

## Why

The project has one sentence it keeps rediscovering, in a different place each time: **a run holds a ledger of what it established, and an answer may say only what is in it.** Figure identity was the rule applied to numbers, names to accounts, dates to days. This is the rule applied to the sentence itself, which is why the four belong in one decision rather than four.

The load-bearing assumption — that a capable model, shown no data at all, can author a well-formed shape — was measured before this was written, not asserted: seven shapes authored and none rejected on one local model, one authored and accepted first try on another under the text protocol.

**Why the ordering rather than a checker.** The obvious design is: the model writes the sentence, a checker reads it afterwards. Checking prose means scanning, and scanning means a list of what may be said, which is a word-list mechanism and a standing anti-goal. It was tried: a gate built on that principle shipped, was falsified by the acceptance run that tested it, and was deleted. It also fails at the root — a sentence composed after its data was seen is a tailored sentence, and no downstream reader can tell a tailored true sentence from an untailored one.

**Why the model writes no digits.** Letting the model write digits and verifying them makes every figure a re-derivation problem, puts the model on the certifying side of ADR-010, and gives up the one property that makes everything else cheap: if the model never writes a digit, a digit in an answer that no tool emitted is *impossible* rather than improbable. The same argument is why a binding is a reference: it is not enough that code chooses the shape, because if the model chose which figure fills a hole by writing the figure, tailoring would return through the binding one layer down and harder to see.

**Why the checks compare declarations.** The tool that emitted a figure declared what it measured; the shape declared what its sentence is asking for; both are members of one closed list, and the check is an equality test between two strings the code itself put there. No model is asked to check another model's work, so ADR-010 is untouched — a later reader who finds a model on both sides should not conclude the two decisions conflict. The model proposes structure at both ends and certifies nothing at either. Every later comparison is that same move again: quantity, then the set a number is a number of, then the thing a clause names, then the unit a quotient could be written in, then the direction a quantity's own name asserts. None of them reads a word of a clause.

**Why set equality rather than containment.** One counterparty's total for one month fills neither a hole about that counterparty nor a hole about that month, and that counterparty's whole-history total fills neither of those either. A figure that declares no set at all fills none of them: nothing has said what it was taken over, which is not the same as saying the set was everything.

**Why the clause is the unit for the fourth check.** Every other check resolves one hole at a time against everything the run established, so a real figure of one thing and a real thing of the same kind can each be true and belong to different sentences. Taking the clause as the unit is what stops a real number being spoken beside the name of something else.

**Why a reviewed template library was rejected.** It wins on exactly one axis: every sentence a person reads would have been read by a person first, which is the residual below. It was rejected because a fixed library can answer only anticipated questions, and the product's whole claim is that it answers what you actually ask. It is not foreclosed: every shape is recorded, which keeps open a *reviewed shape library* — recurring shapes reviewed and promoted, a promoted shape preferred over a fresh one. That is the template library earned rather than assumed.

**Why the refusal path is not composed by a model.** A composed refusal is a sentence written after the data was seen, and the exception would have been roughly a third of turns wide; the reference run spent 67% of its model budget on refused turns. The accepted cost is that a refusal says strictly less. The reads' own texts quote the value the caller supplied, and the caller is a model this project has recorded inventing filter values when refused, so a slot there would tell a person that a category they never named is absent from their records — which is why the reviewed sentences have no slots and a vague true cause beats a precise invented one.

**Why the machine places what the machine holds.** A shape is authored before anything is read, so a hole asking for a grade asked a model to reserve a place for a word it could not know would exist, and every move left when it did not was bad: bind something else and pass the type check, reword and be refused by the ordering rule, or leave it unbound and lose the clause together with any correct figure it also stated. The same argument retired the caveat hole and placed a figure's scope. Placement matters too, and silence about it was a claim: a boundary statement begins with a word pointing at what was just read, so pooling every one of them after the last clause pointed at nothing.

### The residuals, honestly

These are properties of the decision as shipped, not defects awaiting a fix.

**A model-authored template is reviewed by nobody before it is spoken.** A persona-pack phrasing is read by a person before release and frozen by digest. A shape is authored at the moment of answering, by a model, and reaches a person without any review. The structure is checked exhaustively; the prose around the holes is checked by nothing, so a claim no figure measures can still be asserted in the literal words of a clause, and a magnitude spelled out in words rather than digits is a blind guess rather than a laundered figure — and is still not caught. This is the honest price of the ordering rule, paid knowingly.

The residual has narrowed twice and stands. A clause with no hole no longer comes into being, so there is no longer a clause with no hole for prose to be *around*; and a sentence can no longer be about a set the figure beside it was not taken over, nor name a thing through a hole while stating a different thing's number. What stands, unchanged: the words around a hole are read by nobody, and a figure that is right can still be described falsely by them. A hole makes a clause conditional on something the run established; it says nothing about whether the words are true of it.

Three narrower cases ship open beside it, deliberately. A clause may still write the name of a slice into its own literal text, declare `whole`, bind a real total and pass; closing that would need the further rule that a figure naming a slice may only be stated in a clause binding that slice's entity, and it is rejected for now on a measured cost rather than on taste — of the nine ways a set may be narrowed only three have an entity a hole could bind, so the rule would make every breakdown by subcategory, by tag, by currency and by month unspeakable, a large silent loss to close a loophole nobody has yet measured being walked through. Two figures and two entities of one kind in one clause can be exchanged, because closing that needs positional pairing and position is the sentence. And the **value** of a period is unchecked, because the vocabulary holds no entity for a span, so the check compares the axes and only the axes.

One kind of hole rests on the person rather than on a read: a `supposed` hole holds a value out of the question itself, cites no record and carries no grade, so a clause no read touched can still be spoken where the question carried a number. It declares no set at all, because it is not a measurement over one, which is where the prose residual is widest.

**Viability is per-model, and the model in force was on the wrong side of it.** The blind-authoring assumption was phrased as "a capable model", and that phrase was doing quiet work nobody had costed. On a two-model run, one model emitted zero tool calls across twenty native-protocol replies — advertising the capability, producing prose, inventing a third-party application and two tool names — and so never reached a shape at all. Under the text protocol the same model parsed all nine replies cleanly and authored a well-formed three-clause shape first try. A channel failure rather than a capability one, and nothing in the product detects that a configured model never calls a tool.

**Capability honesty is unbuilt.** Nothing computes from the registry whether a slot can be filled before a call is made, so "I cannot answer that" is a judgement rather than a property. The `document` entity kind is the standing proof: a declared type a hole can ask for, taught to the model, that no tool emits.

**A wrong number reached a person with every trust signal correct.** Four faults compounded, none of them in the shape mechanism itself, and two of them in the check this record names as the thing that stops a true number being spoken as an untrue claim. Both of those two are since repaired — a quotient now carries what its operands measured, and a proportion is carried per one and written per hundred — but the episode is what the residuals section exists for: an intact gate in front of a false proposal is a formality, and the same audit created two duplicate accounts because the sentence the person was given to decide on was false about their own vault.

### Promise compatibility

Promise 1 is served by this mechanism, and the residuals are where it is short; the structural half holds, since a number no tool emitted has nothing to cite and a figure about money standing on no record refuses. Promise 2 is served by a hole nothing can fill dropping its clause and saying so, and by a value the arithmetic could not write exactly carrying the term that says so. Promise 4 is unchanged: this adds no outbound flow and no class of recipient, and constrains what comes *back*. Promise 8 is intact via the proposal-and-confirm pair. No promise is added or amended.

## Would reverse this

**The ordering is one-way in trust.** Composing a sentence after its data is seen is a different product, and no amount of downstream checking recovers what the ordering gives for free. Reversing it would mean accepting that the answer path can tailor, and saying so publicly.

**Everything else is two-way and cheaply so.** The planner is an interface, so a protocol, a provider or a model is a swap. The refusal path's pack sentences are data. A shape library is an addition that would move the product toward review without changing the rule.

**What would most like to reverse a residual:** a local model that reliably calls tools, which turns the per-model viability caveat from a live risk into a footnote; and a capability-honesty layer, which turns "I cannot answer that" from a judgement into a property of the registry.

## Open

- The design document over the vocabulary and the codecs is owed rather than waiting. It owes two concepts declared nowhere — the stock/flow split, and `gross_flow`'s deliberate direction-blindness — plus the mechanism a later reader cannot reconstruct from amendments spread across files: four declarations compared pairwise, a rule whose unit is the clause rather than the hole, and a composition rule for boundaries through arithmetic.
- A model that never calls a tool must become detectable. Nothing notices, and ten such turns cost minutes each to produce identical apologies touching no data. Two questions are unruled: whether the runner detects it and falls back to the text protocol, and what the shipped default is.
- Two of the four eval subjects this decision named are counted by a debug reader rather than by the eval — shapes authored and shapes rejected, broken down by the repair the check named. Holes that could not be filled and clauses dropped are counted by nothing. A debug reader is not the eval: the numbers exist only when a person runs the command, nothing watches them, and no change is measured against them between releases.
- A pack's stamp carries no digest, while a shape is a typed template and deserves a stronger pin than a whitelisted one. That work folds into the ledger/event-store ADR.
- `prompt_version` is load-bearing in a new place: a recorded shape is interpretable only against the prompt that taught the model to author it, so the release rule — a new version file, never an edit — binds harder after this than before.
- Which grouping a list over a read that cuts several ways should enumerate is undecided; the guard that refuses such a block is where that decision lands.
- Nothing stops a model typing a strength word into its own clause text, though it is now betting against a machine-placed sentence in the same answer.
