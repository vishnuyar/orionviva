# Breaking up the projection — and the tool registry it becomes

**State:** built
**Rules:** PROJ-60, PROJ-61, PROJ-62, PROJ-63, PROJ-64, PROJ-1, PROJ-2, PROJ-3, PROJ-4, PROJ-5, PROJ-6, PROJ-7, PROJ-8, PROJ-9, PROJ-10, PROJ-11, PROJ-12, PROJ-65, PROJ-66, PROJ-67

## Rules

### PROJ-60 — a small core with view modules behind a facade
**State:** by-review
**Code:** product/viva/ledger/projection/core.py:1
**Test:** none

1. One core module folds events into state and owns the shared caches; nothing else folds events.
2. Each read family is its own module over that core — accounts, balances, movements, merchants, categories, rulings, tiers, positions, coverage, activity, rhythm.
3. `LedgerProjection` remains a facade delegating to the views, so a caller imports one surface.
4. One live projection is kept, so a read never re-replays the encrypted log.

### PROJ-61 — the registry holds only verbs the code can honestly serve
**State:** enforced
**Code:** product/viva/tools/__init__.py:31
**Test:** product/tests/test_docs_track_the_code.py::test_the_registered_tool_count_is_whatever_the_registry_holds

1. `default_registry` registers exactly the read verbs whose machinery exists — today `query_ledger`, `list_movements`, `check_completeness`, `get_provenance`, `get_transparency` and `compute`.
2. A verb with no machinery is not registered and is not stubbed; a model is never offered a tool that always refuses.
3. A verb that later gains machinery is an entry, not a redesign.

### PROJ-62 — a structured filter object, validated against the vault's own vocabulary
**State:** enforced
**Code:** product/viva/tools/ledger_common.py:112
**Test:** product/tests/test_tool_contract.py::test_unknown_category_refusal_names_the_vocabulary, product/tests/test_tool_contract.py::test_latest_complete_calendar_month_resolves_to_explicit_dates, product/tests/test_tool_contract.py::test_an_exact_visible_account_name_narrows_without_a_lookup, product/tests/test_tool_contract.py::test_an_ambiguous_visible_account_name_is_not_guessed, product/tests/test_tool_vocabulary.py::test_native_query_schema_discriminates_filters_by_read_family

1. A read takes a typed filter object, never a query string and never SQL.
2. Every filter value is validated against the vault's own learned values — its accounts, account kinds, categories, tags, counterparties and currencies — and a value the vault does not hold refuses, naming the values it does hold. An account id passes directly; an exact, uniquely matching visible account name resolves to its id after capitalization and repeated whitespace are normalized, while an unknown or ambiguous name refuses.
3. A filter a read would ignore refuses and names what that read supports, rather than being accepted and dropped.
4. The enumerations of `entity` and `group_by` are schema this project owns; the legal *values* are read from the vault, never listed in code.
5. A date window is either explicit inclusive edges or the named latest complete calendar month. The named period resolves to explicit edges before the read, using the newest ended month shared by posted statement coverage.
6. The native schema discriminates by entity and aggregate metric, so it offers only the filters that family honors; the dispatcher retains the same refusal for callers that bypass native validation.

### PROJ-63 — the registry contract is modality-neutral
**State:** enforced
**Code:** product/viva/tools/registry.py:136 (`Registry`)
**Test:** product/tests/test_answer_program_contracts.py::test_text_compiler_uses_the_same_compact_contract_and_one_call_on_success

1. The registry defines typed schemas, the result envelope and refusal semantics, and chooses no wire format.
2. Native structured output is the primary compiler modality and strict text JSON is the degradation modality; both produce the same versioned semantic request.
3. Every check that decides what may be said runs in code, outside the modality.

### PROJ-64 — one result envelope, refusal first-class
**State:** enforced
**Code:** product/viva/tools/envelope.py:138
**Test:** product/tests/test_tool_contract.py::test_unknown_tool_is_a_refusal_not_an_exception

1. Every tool returns one envelope: figures, grade, value-time, record ids, coverage, caveats, and a machine-tagged refusal when no figure can be asserted.
2. A call never raises across the tool boundary; an unknown tool, an unknown argument, a wrong type or a value outside an enum comes back as a refusal that names what would have been accepted.
3. Composition inherits the weakest grade among its parts.
4. A figure declares what it measures from the closed vocabulary in `viva/quantity.py`, and an emitter that names nothing fails the build rather than a person.

### PROJ-1 — the shape is committed before anything is read
**State:** enforced
**Code:** product/viva/answer_program/compiler.py, product/viva/answer_program/validate.py, product/viva/answer_program/execute.py
**Test:** product/tests/test_answer_program_contracts.py::test_static_defects_execute_nothing

1. An answer's clauses, complete read graph and binding selectors arrive in one program before any tool executes.
2. The compiler receives no current-turn financial results, and its only repair also precedes every read.
3. Static defects reject the whole program; execution cannot partially admit a malformed batch.

### PROJ-2 — a model writes no digits, and every clause carries a hole
**State:** enforced
**Code:** product/viva/tools/shape.py:246, product/viva/tools/shape.py:334, product/viva/tools/shape.py:226 (`Clause`)
**Test:** product/tests/test_shape_grammar.py::test_no_words_in_a_shape_may_carry_a_digit

1. A clause whose own literal words carry any digit does not come into being.
2. A clause placing no hole does not come into being.
3. A magnitude, a day and a count reach a person only through a hole the renderer fills.
4. The reader of what a model sends inherits these rules from the same constructor, so no second code path can come to disagree with the first.
5. Deterministic code binds each hole to something the run established and renders it; the model writes no figure and no finished sentence.

### PROJ-3 — a hole declares what its number is of and what set it is over
**State:** enforced
**Code:** product/viva/tools/shape.py:179
**Test:** product/tests/test_shape_binding.py::test_a_hole_holding_a_magnitude_must_say_what_set_it_is_over, product/tests/test_shape_binding.py::test_the_shape_prompt_teaches_every_set_a_hole_can_declare

1. A hole holding a magnitude declares the quantity it asks for, from the closed vocabulary the tools declare into.
2. A hole holding a measurement also declares the set it is a number over: the axes its sentence narrows on, or the whole of what the quantity ranges over.
3. A hole holding no magnitude declares neither.
4. A figure fills a hole only where both of its own declarations match the hole's; code compares declarations and reads no words.

### PROJ-4 — a refusal is a reviewed sentence chosen by machine tag
**State:** enforced
**Code:** product/viva/answer_program/runtime.py, product/viva/answer_program/outcomes.py, product/viva/tools/runner.py (`_refused`)
**Test:** product/tests/test_persona_pack.py::test_every_way_a_turn_can_refuse_has_a_reviewed_sentence, product/tests/test_tool_vocabulary.py::test_an_identical_refused_call_stops_on_the_first_repeat

1. A refused turn speaks a reviewed persona-pack sentence selected by tag; nothing is composed, nothing is bound, and no model call is spent.
2. Every tag the runner can refuse with has exactly one reviewed sentence, and the bijection is enforced at build time.
3. Structured non-answer outcomes distinguish validation failure, missing data, missing capability, clarification, assumptions and outside-domain requests.
4. Account phrases resolve only through complete normalized word sequences in
   visible account names or institutions. Partial-word substrings never select
   an account, and multiple matches refuse rather than choosing a figure.
5. A tag the machine does not know is not spoken as one.
6. The compiler has at most two model attempts; deterministic execution never asks the model what to do next.

### PROJ-5 — a property of a figure the machine holds is placed by the machine
**State:** enforced
**Code:** product/viva/tools/runner_delivery.py:272
**Test:** product/tests/test_shape_claims.py::test_a_boundary_is_said_once_inside_the_clause_that_made_it, product/tests/test_shape_binding.py::test_a_date_can_travel_with_the_figure_stated_beside_it, product/tests/test_shape_binding.py::test_a_figure_date_cannot_float_free_of_its_figure

1. A figure's scope, its caveats and its grade are placed by the runner and are never asked for through a hole.
2. A statement drawn from one figure's boundary is placed under the clause that bound that figure, and again under the next clause that makes it.
3. The order is scope, then strength, then what the claim does not cover.
4. The answer's grade is the weakest among every money figure it stated, block lines included (PROJ-65), and is said only where at least one of them was stated as a number in a sentence.
5. An answer states how many of the accounts a person holds it covers only where every stated figure declares, as data, exactly which accounts it covers.
6. A day carried by a figure may be stated only in the same clause as that figure. The binding names the figure and the machine renders its date; a copied or free-floating day does not fill the hole.

### PROJ-6 — `compute` takes figure ids and stipulations, never a typed number
**State:** enforced
**Code:** product/viva/tools/compute.py:524
**Test:** product/tests/test_tool_compute.py::test_compute_refuses_a_number_typed_in_and_names_what_it_has

1. An operand is a figure some tool emitted in this run, named by its id, or a value the person stipulated in this turn's question and which the question demonstrably contains.
2. The expression is parsed, never evaluated: four operators, parentheses, integer literals and bound names only.
3. Multiplying or dividing by a bare magnitude rescales an attested quantity and leaves it attested; adding or subtracting one leaves the total standing on no record and carrying no grade.
4. A result's set is its operands' set where they agree and neither set where they differ; a literal contributes no set and takes none away.
5. A quotient that does not terminate is returned marked rounded, never refused; how the arithmetic came out never moves a grade.
6. A supposition does not wear off: a result with any hypothetical operand stays hypothetical however many times it is recomputed.

### PROJ-7 — an empty optional field means the field was not sent
**State:** enforced
**Code:** product/viva/tools/registry.py:107
**Test:** product/tests/test_tool_vocabulary.py::test_an_empty_optional_box_narrows_nothing_and_is_said_to_narrow_nothing

1. An optional field the schema names, arriving empty, is treated as a field that was not sent — decided once in `Registry.call`, so it is true of every tool at once.
2. A required field sent empty is still a fault.
3. An open map of caller-chosen keys is never reached into, and a misspelled field still refuses by name.
4. A filter refusal names every fault it can see.

### PROJ-8 — `nature` is not a filter
**State:** enforced
**Code:** product/viva/tools/ledger_common.py:112
**Test:** product/tests/test_tool_vocabulary.py::test_nature_is_not_a_filter_any_read_offers

1. No read accepts `nature` as a filter, and the tool descriptions offer none.
2. A movement's derived nature is untouched: it still decides what counts as spending, and it still comes back on every row a listing returns.

### PROJ-9 — a read records what narrowed it, and every figure declares its set
**State:** enforced
**Code:** product/viva/tools/envelope.py:295
**Test:** product/tests/test_tool_vocabulary.py::test_every_filter_a_read_honours_can_be_said_in_the_answer

1. Every figure every read emits declares the set it was taken over, structured rather than written out.
2. A read that narrows a set records what it narrowed it to on the figures it emits.
3. A figure declares every axis it is the intersection of: what narrowed the read, plus the slice of what came back that it is. An axis is named once.
4. A figure that is a member of a set rather than a slice of it names no slice, and is not the whole of what its quantity measures.
5. A boundary is built only by its own constructor and is never shown to the model.
6. `whole` states whether the read covered its population, independently of evidence gaps. A whole figure may still disclose unmeasured accounts or unposted documents; those are separate boundary fields, never reasons to rewrite the population claim.

### PROJ-10 — discovery is generous, narrowing is exact
**State:** enforced
**Code:** product/viva/tools/ledger_vocabulary.py:36
**Test:** product/tests/test_tool_vocabulary.py::test_a_name_buried_inside_a_label_reaches_nothing

1. `query_ledger` with `entity: "vocabulary"` and a `group_by` returns the labels this vault holds under that grouping, and how many.
2. Its optional `matching` argument looks a name up by three ordered comparisons — key equality, key prefix, whole token of the key — with the vault's own key function applied to both sides. A run of characters buried inside a word reaches nothing.
3. What comes back is labels the vault holds; the caller then passes one as the exact filter value it always was. No figure is ever taken over a pattern.
4. The lookup emits no figure of its own: the count it returns is the whole vocabulary's size.

### PROJ-11 — model-facing tool text is a versioned file
**State:** enforced
**Code:** product/viva/tools/registry.py:33
**Test:** product/tests/test_tool_contract.py::test_a_tool_without_a_description_cannot_register

1. Every tool's description lives in the versioned, digest-pinned prompt file, never as a Python literal.
2. Registering a tool with no description section fails, so a tool cannot reach a model unexplained.
3. The version id travels with the descriptions, so a run records exactly what the model was told.

### PROJ-12 — a read is bounded by a named constant that does not grow with the ledger
**State:** enforced
**Code:** product/viva/tools/ledger_common.py:54
**Test:** product/tests/test_tool_limits.py::test_no_uncapped_read_exceeds_what_a_result_may_cost

1. Every uncapped read is bounded by a named constant, and none of those bounds grows with the size of the ledger.
2. Current-turn figures and records do not travel to the compiler at all; deterministic selectors bind them after execution.
3. A capped read states how many of how many it showed, to a person and not only to its caller.

### PROJ-65 — a block of rows is one read's figures, each beside the slice it covers
**State:** enforced
**Code:** product/viva/tools/runner_binding.py:398 (`_rows_bound`) · product/viva/tools/runner_binding.py:128 · product/viva/tools/runner_delivery.py:289
**Test:** product/tests/test_shape_rows.py::test_a_shape_that_names_no_row_count_answers_whatever_the_count_turns_out_to_be · product/tests/test_shape_rows.py::test_the_set_is_graded_once_above_the_block_and_never_per_row · product/tests/test_tool_vocabulary.py::test_two_figures_over_one_slice_fill_no_block

1. A binding may name a whole reading — `{"read": "rN"}` — rather than one thing in it. A rows hole takes that reference and no other, and no other hole takes it.
2. The machine writes one line per figure of that read, each beside the slice it covers, so how many rows there are never reaches the model.
3. The grade is the weakest among the figures making a claim about money, stated once above the block and never per line: it is one grade computed over the whole read, so a word per row would read as a claim about that row.
4. A read that names no slice fills nothing.
5. A read whose figures name slices of more than one kind fills nothing; a line per slice would state the same money once for each way the read cuts.
6. A read naming one slice more than once fills nothing, for the same reason. The two refusals are in that order, so a read that cuts several ways never hears the second.
7. *Block lines included* means: every figure a block wrote a line for is a figure the answer stated — cited, answerable for its records and its caveats, and inside the set PROJ-5.4 computes the answer's grade over. The read's own total and count, which got no line, are not stated and are not cited.

### PROJ-66 — a hole nothing can fill costs its clause and not the turn
**State:** enforced
**Code:** product/viva/tools/runner_delivery.py:145 · product/viva/tools/runner_delivery.py:287 · product/viva/tools/shape.py:121 (`HOLE_THE_CLAUSE`)
**Test:** product/tests/test_shape_binding.py::test_a_hole_nothing_can_fill_costs_its_clause_and_not_the_turn · product/tests/test_shape_binding.py::test_a_bad_reference_costs_its_clause_and_not_a_grounded_clause · product/tests/test_tool_vocabulary.py::test_a_wrong_subject_costs_its_clause_and_not_an_independent_claim · product/tests/test_shape_binding.py::test_an_answer_whose_every_clause_falls_away_says_so

1. A hole nothing can fill costs its clause and not the turn: the clause is dropped and what could be established still stands. This is the implementation of [ADR-013](decisions/ADR-013-the-shape-before-the-data.md) assertion 15.
2. A reference that is invalid or names the wrong subject is a hole nothing can fill. It drops only its own clause when another clause stands; when every clause fails, the tagged refusal is preserved.
3. A dropped clause is disclosed — a reviewed pack phrase names what was missing by its kind, never a zero and never a silence.
4. A turn whose every clause is dropped rests on nothing this run established, and refuses.

### PROJ-67 — a read that groups cuts as many ways as it groups
**State:** enforced
**Code:** product/viva/tools/ledger_movements.py:189 · product/viva/tools/ledger_common.py:573 (`_month_slice`) · product/viva/tools/ledger_aggregates.py:257 · product/viva/tools/envelope.py:421 (`cut_set`)
**Test:** product/tests/test_tool_vocabulary.py::test_each_group_of_the_summary_read_names_its_own_slice · product/tests/test_tool_vocabulary.py::test_a_months_slice_is_the_calendar_month_not_what_moved_in_it · product/tests/test_tool_scope.py::test_the_only_group_of_a_partitioning_grouping_is_the_whole

1. A read narrows once and cuts into as many groups as it has, and which cut a figure is is a property of the figure. The transactions read cuts twice over the same movements — a figure per account and a figure per month — and each figure names its own slice.
2. A month-shaped group's slice is the calendar month, first day to last, rather than the first and last day money actually moved: the cut names the group, and written from the data two vaults' January would be different periods.
3. Where a window narrowed the read, the narrower edge stands on each edge separately, so a month clipped by a window declares only the days it covers rather than claiming the days before the window opened.
4. A group name that is no calendar month yields no span, and that figure carries no slice.
5. A grouped figure is the whole of what its quantity ranges over only where nothing narrowed the read, the grouping puts every counted movement in exactly one group, and there is that one group.
6. This is the `cut` half of T1's boundary axis: what narrowed the read plus the slice of what came back this figure is.

## Why

Two asks met at one seam. `projection.py` had grown to a single 1,564-line class
of roughly sixty public reads with about thirty modules calling into it — the
place every read-side idea landed, which is exactly what *abstract the read side
early* predicted. At the same time the agent needed read tools, and the
projection was where their substance lived. The observation that solved both:
**most of those methods are not tools.** They are plumbing for ingest
continuation, the enrichment queue, the question queue's tiering, the transfer
matcher. Sixty methods collapse into a handful of read verbs plus internals, and
the decomposition should make that visible in the file layout itself.

**Why views and not mixins.** Mixins are the cheapest move — no call site
changes, a diff of moved lines — but the god object survives: sixty methods
still share one namespace and one implicit pile of mutable state, only now the
state's owners are scattered across files, which is arguably harder to read. And
the registry would still bind to the whole surface rather than to families. A
core plus view modules costs a real refactor, because the families are layered
and the caches must live on the core so views share them, but it makes **tool
families into module boundaries**: the balance branch is `balances.py`,
completeness is `coverage.py`. The registry then imports views, not a god
object. The facade is what makes it a no-behavior-change refactor, and the proof
was a characterization harness — a synthetic event stream exercising every event
type, every public read serialized to JSON, captured before the split and after
it, with an empty diff.

**Why five honest tools rather than twelve half-real ones.** Stubs that pretend
would violate *never bluff*; stubs that refuse are noise in the schema the model
sees, and a model offered a tool that always refuses spends calls learning not
to use it. What gets decided on day one is the *contract* — schema shape,
envelope, refusal semantics — so a later verb is an entry rather than a
redesign. The same reasoning settles whether `find_patterns` and
`list_obligations` are verbs: they begin as named projections through
`query_ledger` and are promoted only if their argument shapes refuse to fit.

**Why a structured filter object.** A constrained DSL needs a parser this
project maintains, error messages for a grammar it invents, and a model that
learns a private language — and everything it can express, a validated schema
expresses for free. Many narrow named tools would make the verb count scale with
question types, which is the per-institution-parser mistake reborn one layer up.
Validating against the vault's own vocabulary is what keeps I5 intact: the
schema's legal values are data read from the vault, never a list in code.

**Why the modality is an adapter concern.** The registry contract is
modality-neutral, so an admitted profile may compile with native structured
output or strict text JSON. Both emit the same versioned program and nothing
upstream changes.

**Why a shape rather than a gate over language.** The first design licensed
tokens: every figure declared, every date declared, names blanked before numbers
were counted. It answered five of nine answerable questions in an acceptance run
and spent 67% of the model budget on refusals — *every one of them triggered by
a date or an identifier token, and not one by a bad figure*. Six of seventeen
turns refused for a bare four-digit year, in one case the year the person had
just asked about. A whitelist over free-form language had taken five cycles of
new rules without closing, and each new rule made the clause underneath harder
to remove.

So the direction inverted: **a model writes no digits at all.** An answer is a
shape — clauses of literal words with typed holes — committed before any tool is
on the table, so a claim cannot be tailored to a figure that turned up. A model
that has never seen an amount cannot call one unusually large. What is checked
is structure: totality, existence, type, records, scope. Nothing reads the
sentence, and nothing ever will: a forbidden-word list is a standing anti-goal.

What survived from the deleted gate is the *envelope* — figure identity, the
four figure kinds, grade, records, exactness, coverage — and the one rule it had
that was never about tokens: **a money-kind figure with no records refuses.**

**Why a number carries what it measures, and what set it was taken over.** Typed
holes make a magnitude impossible to invent and do nothing about a real one put
where something else belongs. That failure happened: a gross sum of postings
including card settlements and own-account transfers was nearly spoken as *the
total you spent*, and only coincidence stopped it. So every figure declares a
quantity, and every magnitude hole declares what it is asking for. Then the same
argument ran one level out: a total narrowed to one counterparty and a total
over the whole ledger both declared `spending`, so a real number could still be
spoken as a claim about something else with every guard satisfied. The sentence
to carry forward is: **a figure declares what it measured and what set it was
taken over, and a sentence is checked against both — the first stops a number
meaning something else, and only the second stops it being about something
else.**

**Why a division needed its own repair.** A wrong number reached a person once,
and four faults compounded to produce it. One of them falsified a property
stated flatly: "code compares the two declarations" is true and was not
sufficient, because a division compared only the *result's* declaration, so two
operands of the wrong kind divided into a result of the right kind and the check
passed. The fix is that a quotient carries what its operands measured, so the
operands' kind is *in* the result. The check no longer looks through an
operator.

**Why the machine places what the machine holds.** Caveats went that way first,
then scope, then the grade. Each had the identical shape: a property of a figure
that the run computes, but that reached a person only if a model had reserved a
hole for it *before reading anything*. That is a bet with no winning side —
author the hole and read no caveat, and the clause is dropped for a hole nothing
can fill; leave it out and read one, and the turn refuses. A real turn lost every
clause that way and refused while holding three correct, corroborated balances.
The rule gained a second half later: **placed beside the thing it is a property
of.** Statements pooled at the end of an answer and deduplicated across it
produced words pointing at nothing, and two figures each over one account became
one sentence claiming a count of one over an answer covering two. A three-clause
answer is wordier, and that is the price of a word meaning something.

**Why a search is generous and a narrowing is exact.** A person can see a
counterparty this product cannot find. The tempting answer is a `contains`
filter, and it is wrong for a reason that generalises: a filter accepting a
pattern makes the narrowing a pattern, and then a figure's boundary must either
name the pattern — a member the closed vocabulary does not have, since no entity
in the vault corresponds to it — or name the resolved labels, which the caller
never named. Either way an answer becomes true of a set the person did not
describe. Putting the generosity in *discovery* costs none of that: a generous
match cannot produce a wrong figure, only a longer list.

**Why `nature` was withdrawn rather than worded.** A filter whose effect an
answer cannot state narrows a set in a way nobody can review, which is the same
fault the refusal of an ignored filter already guards against. So the narrowing
stops until a reviewed sentence exists to carry it. What is withdrawn is the
*filter*: *show me my transfers* is not askable, knowingly, and it returns in
its own cycle with wording authored to carry it.

**Two general lessons worth keeping.** The refusal discipline has to cover
*filters a read would ignore*, not only values a vault does not hold —
accepted-and-dropped is the quiet way a true row answers the wrong question. And
a repair to a guard is itself a change to a guard, and needs the same mutation
proof the guard got: the worst finding of one verification round was a defect the
previous round's repair had introduced.

Invariants this leans on: T1 (every answer figure is a cited tool result),
T2/ADR-010 (deterministic math, no arithmetic in the model, and no model checks
another model), T4 (this path writes no events), T6 (no tool touches the
network), X3 (no tool can do anything irreversible), I5 (code universal,
specifics are data), and the standing principle *read side early, write side
late*. The shape mechanism itself is
[ADR-013](decisions/ADR-013-the-shape-before-the-data.md); what a refusal can no
longer say is [the-suggestions-channel.md](the-suggestions-channel.md).

## Open

- Whether a slot can be filled at all is not computed from the registry before a
  call is made. `{document}` is the proof: a declared slot type taught to the
  model and placed by three question phrasings, which no tool emits. `{tag}` is
  declared by nothing.
- The words a model writes *around* a hole are read by nobody, by design and
  permanently. Two things narrow it — the clause is authored before any read, so
  such a model is betting on a claim it has not seen, and the machine's own
  sentence is in the same answer to contradict it — and nothing closes it.
- The value of a period is unchecked: the vocabulary holds no entity for a span,
  so the scope check compares axes and only axes, and a sentence naming the
  wrong window binds a figure cut by period as happily as the right one. A
  window the model computed is disclosed rather than refused, for the same
  reason.
- A per-holding value is unspeakable, as a row and as a number, because a holding
  is *in* an account rather than a slice of one and nothing a set may be narrowed
  by names an instrument. The holdings read's own total, and its total narrowed
  to one account, still answer. *What a holding is a slice of* is chartered as
  its own item.
- A monthly average computed over one span and spoken under another refuses
  rather than answering: the span a figure's operands were measured over is a
  third object nothing here computes. *What a count is a count of* is chartered
  beside it — a count of things found cites only what it found, so a count of
  none cites nothing and refuses at the citation gate.
- A date is checked structurally and is ASCII-only by accident: the ISO check
  tests its digits with `str.isdigit` and the month parse with `int`, both of
  which accept non-ASCII decimal digits, and `int` accepts a leading sign. It is
  I2's business — normalization is locale-aware, versioned and deterministic —
  rather than any one read's.
- A description of nothing but punctuation is still its own spending group, still
  mints an entity, and is still refused as a filter, so an answer can name a
  counterparty the follow-up bounces. Whether such a label joins the unnamed
  residual is a decision rather than a repair.
- `figure()` still accepts a money-kind figure with no grade. No emitter produces
  one; now that the answer's sentence claims something of every figure in it, the
  fix belongs at the emitter rather than at the speaking end.
- `check_completeness`'s per-account date figures remain a candidate for removal
  if no AnswerProgram selector reaches them in recorded evaluation.
- The standing real-vault run. The ten acceptance questions now have a
  deterministic provider-double test that checks their read plans, including a
  follow-up period carried through conversation history. That proves the
  registry routes and reads; it does not prove that a live model authors a
  usable complete program first time, or that the resulting answer is true of
  the real vault. Whether this design works remains a per-model, real-data
  question for the Witness.
