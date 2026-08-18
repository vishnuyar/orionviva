# Breaking up the projection — and the tool registry it becomes

**Status:** ✅ Ruled 2026-08-01 (Vishnu accepted every recommendation, D1–D5) · **Built 2026-08-01** — the decomposition, registry v1 and the envelope stand; see *What the build did* at the end. **The citation gate described below is deleted as of 2026-08-07** and replaced by shapes, typed holes and bindings — read the closing amendment first, then the rest for how the problem was understood. Outstanding: the real-vault run of the replacement. · **Created:** 2026-08-01 · **Last updated:** 2026-08-08 (the quantity check's falsified property is repaired — a division carries its operands' kind)
**Invariants touched:** T1 (every answer figure is a cited tool result), T2/ADR-010 (deterministic math; no arithmetic in the model), T4 (untouched — this brief writes no events), T6 (no tool touches the network), X3 (no tool can do anything irreversible), I5 (code universal, specifics are data), and the standing principle *read side early, write side late*.

---

## 1. The goal, restated

Two asks, one seam.

`projection.py` has grown to **1,564 lines**: one class, roughly sixty public reads (eighty-one methods in the file counting helpers and dataclasses), and about **thirty modules** call into it — the answer path, net worth, the question queue, ingest, enrichment, the maintenance agent, the interview, the web service, and a dozen debug commands. It has become the place every read-side idea lands, which is exactly what *abstract the read side early* predicted would happen — and it is now unwieldy to navigate, review, and test.

At the same time, Slice 9 (Viva speaks) needs the agent's **read tools**, and the projection is where their substance lives. The ask: break the file apart so that the same seams that make it maintainable also define the tools the financial agent calls.

Your third observation is the key to both: **most of these methods are not tools.** They are plumbing — for ingest continuation checks, for the enrichment queue, for the question queue's tiering, for the transfer matcher. The agent-toolset doc's scaling law ("tools scale with verbs, not with nouns") turns out to hold in the code: sixty methods collapse into **four read verbs** plus internals. The decomposition should make that visible in the file layout itself.

## 2. What already exists

- **`docs/agent-toolset.md`** — the verbs Viva may ever use, decided at design level, with the forbidden list (no network, no writes outside the three memory verbs, every figure cited). It deferred the registry to Slice 9 — *"formalizing ~40 projection methods before then would be abstraction ahead of evidence."* The evidence has now arrived: the file is unwieldy and the verbs are stable. Its two named open questions (`query_ledger`'s shape; whether `find_patterns` / `list_obligations` are true tools) are D3 and D2 here.
- **`answer.py`** — the deterministic answer path. Its `Answer` dataclass (text, amount, grade, provenance, coverage, caveats, machine-tagged refusal) is the embryo of the tool-result envelope. Nothing about it needs inventing; it needs generalizing (D5).
- **The `Ledger` facade** keeps one live projection so reads never re-replay the encrypted log. Any decomposition must preserve that: one fold, shared caches, no per-call replays (the standing performance practice).
- **What exists nowhere:** the invocation modality — how a model call becomes a tool call and back. That is D4, the genuinely new decision in this brief.

## 3. The inventory — what becomes a tool, what stays plumbing

Every public read on `LedgerProjection`, grouped by concern. "Tool-facing" means its substance surfaces through a registry verb; "plumbing" means another subsystem consumes it and the agent never sees it directly.

| Family | Representative methods | Consumed by | Becomes |
|---|---|---|---|
| **Event fold & state** | `apply`, `_apply`, `_AccountState`, overlay dicts | everything | the core — never a tool |
| **Balances & reconciliation** | `balance`, `account_value`, `cash_value`; `running_balance`, `earliest_opening`, `is_seeded` | answer path; ingest continuation | `query_ledger` (first three); plumbing (rest) |
| **Accounts & identity** | `accounts`, `account_info(s)`, `document_types_of`; `resolve` | answer path, interview; ingest | `query_ledger`; `resolve` stays ingest plumbing |
| **Movements, nature, transfers** | `movements`, `transactions`; `transfer_links`, `transfer_suggestions`, `linked_keys`, `movement_key` | aggregates, matcher, queue | `query_ledger` (movements/transactions); plumbing (matcher, queue) |
| **Merchant identity & implications** | `merchant_keys_of`, `implication_of/for`, `counterparty_kind`, `uncategorized_merchants` | enrichment, queue, tiers | plumbing — surfaces only as a `group_by: merchant` |
| **Categories & tags** | `spending_by_category/subcategory/tag`, `derived_category`; `canonical_*`, `known_*`, alias maps | answer path; queue, surface pickers | `query_ledger` aggregations; vocab methods are plumbing *and* the source of the query schema's legal values |
| **Tiers & attention** | `tier_of`, `tier_summary`, `uncategorized_expenses`, `declined_questions` | question queue | plumbing; `tier_summary` feeds `check_completeness`'s honesty line |
| **Positions & valuation** | `positions`, `snapshot_positions`, `holdings_value`, `unrealized_gain`, `holdings_as_of` | net worth, answer path | `query_ledger` (holdings) |
| **Ingest coverage** | `captured_docs`, `posted_doc_ids`, `open_holds`, `gap_holds`, `is_resolved` | pipeline, coverage summary | `check_completeness` |
| **Rulings & derived accounts** | `rulings`, `ruled_accounts`, `undecomposed`, `excluded_from_spending` | net worth, listen | `query_ledger` + the explain side of `get_provenance` |
| **Agent activity** | `agent_log`, `agent_attempts`, `agent_calls_spent` | maintenance runner | `get_transparency` |

The verdict this table gives: at this stage the projection provides the substance of exactly **four** of the twelve verbs — `query_ledger`, `check_completeness`, `get_provenance`, `get_transparency`. `compute` is small and pure and lives beside them. `project`, `search_documents`, and the three memory verbs have their own homes and their own slices; nothing in this brief builds them, and the registry must refuse them honestly rather than stub them.

---

## 4. The decisions

### D1 — The shape of the decomposition

**Option (a): mixins.** Split the class into mixin classes (`BalanceReads`, `MerchantReads`, …) composed back into `LedgerProjection`. This is the cheapest move: no call site changes, the diff is mostly moved lines. But the god object survives — sixty methods still share one namespace and one implicit pile of mutable state, only now the state's owners are scattered across files, which is arguably *harder* to read. And the tool registry would still bind to the whole surface rather than to families. It is a two-way door that buys little. Mixins are how a large class hides, not how it gets smaller.

**Option (b): a small core plus view modules.** A `ProjectionCore` that does exactly one job — fold events into state (`apply`, `_AccountState`, the overlay dicts, the memoized caches) — and per-family view modules over it: balances, movements (with the nature ladder and transfer reads), merchants, categories-and-tags, tiers, positions, coverage, activity. The existing `LedgerProjection` remains as a **thin facade** delegating to the views, so all ~thirty callers keep working unchanged and migrate at leisure. The cost is a real refactor: the families are layered (tiers read categories, categories read merchants, nature reads merchants and rulings), so the module graph must be explicitly ordered, and the caches that today live as `self._mkeys` etc. must live on the core so views share them and the one-live-projection performance property is preserved. The payoff is that **tool families become module boundaries**: `query_ledger`'s balance branch is `balances.py`, `check_completeness` is `coverage.py`. The registry then imports views, not a god object. Behavior must be provably unchanged — the real-vault before/after diff is the proof (step 0 below). Two-way door.

**Option (c): tool-first, split later.** Write the registry now against the existing class and defer the decomposition. Fastest route to Slice 9, and it answers the second ask while ignoring the first — the unwieldy file stays unwieldy, and worse, the registry's internal shape gets dictated by the current class rather than by the verbs, which is the tail wagging the dog.

**My lean: (b).** It is the only option that serves both asks with one set of seams, and the facade makes it a no-behavior-change refactor the verifier can check mechanically. Evidence that would change my mind: if the family interdependence turns out so dense that the views degenerate into one module importing all the others, mixins (a) become the honest answer — but the table above suggests the layering is a clean DAG (core → merchants → categories → movements/nature → tiers).

Proposed layout, names describing behavior:

```
viva/ledger/projection/
    core.py         — the event fold, account state, overlays, shared caches
    balances.py     — grading, reconciliation, openings, account value
    movements.py    — enumeration, movement keys, the nature ladder, transfer reads
    merchants.py    — key resolution, catalog lookups, implications
    categories.py   — derived category, aliases, vocabulary, tags
    tiers.py        — attention tiers, question-queue reads
    positions.py    — snapshots, holdings, valuation composition
    coverage.py     — the ingest read-model (captured / posted / held)
    activity.py     — the agent's own log
    __init__.py     — LedgerProjection, the facade with today's exact surface
```

### D2 — Which tools exist in registry v1

**Option (a): all twelve now.** The registry is complete on day one; seven of twelve tools either wrap machinery that does not exist yet (`project`'s formula library, `search_documents`' index) or belong to the write direction. Stubs that pretend would violate *never bluff*; stubs that refuse are just noise in the schema the model sees, and a model offered a tool that always refuses will waste calls learning not to use it.

**Option (b): the four read verbs this code can honestly serve, plus `compute`.** `query_ledger`, `check_completeness`, `get_provenance`, `get_transparency`, `compute`. Each is fully real on day one. The other seven arrive with the slices that give them substance — the registry's *contract* (schema shape, envelope, refusal semantics) is what gets decided now, so a later tool is an entry, not a redesign. The agent-toolset doc's open question about `find_patterns` and `list_obligations` resolves itself here: they are **not in v1**, and when they come, they can begin life as named projections surfaced through `query_ledger` and be promoted to verbs only if their argument shapes refuse to fit — the verb count is the interface either way, as the doc said.

**My lean: (b).** Five real tools beat twelve half-real ones, and it keeps the doc's own discipline: pressure to add a tool is a signal to examine, not a default.

### D3 — `query_ledger`'s query shape (the workhorse's contract)

**Option (a): a structured filter object.** A typed, validated argument: roughly `{entity: balances|transactions|holdings|aggregate, filters: {account?, category?, tag?, merchant?, nature?, window?}, group_by?, currency?}`. Every field is enumerable and validated **against the vault's own vocabulary** — the account list, `known_categories()`, `known_tags()`, the merchant catalog — which the projection already maintains as learned data. An unknown value gets a refusal that names the known values, exactly the `UnknownAccountError` → honest-refusal pattern the answer path already has. No parsing, no injection surface, trivially testable, and it is what model tool-calling is natively good at. The enumerations of `entity` and `group_by` are schema we deliberately own (the `PRIMARY_CATEGORIES` precedent — a mapping of our own structured values, not descriptor classification, so it does not violate the no-word-list rule).

**Option (b): a constrained DSL string.** `"spending by category where window=2026-Q2"`. Compact and expressive, but it needs a parser we maintain, error messages for a grammar we invent, and a model that learns our private language. Everything it can express, (a) expresses with schema validation for free. This is the option the agent-toolset doc flagged as a design task of its own — and (a) makes that task mostly disappear.

**Option (c): many narrow named tools** (`get_balance`, `get_spending_by_category`, …). No query language at all — but the tool count then scales with question types, which is the per-institution-parser mistake reborn one layer up. The scaling law is the review test, and this fails it.

**My lean: (a), strongly.** It was already the doc's implied direction ("safe, structured — not raw SQL from a model"), and the vocabulary-validation move keeps I5 intact: the schema's legal values are data read from the vault, never a list in code.

### D4 — The invocation modality (the new decision)

How does a model's intention become a tool call? Three real options, and one reframe that softens the choice.

**Option (a): native tool-calling through the model adapter.** Modern models — hosted and local (llama.cpp, Ollama, vLLM all support it now) — accept JSON-schema tool definitions and emit structured tool-call messages. The loop is: model sees the question and the tool schemas → emits a call → we validate and execute → the result envelope goes back → repeat until the model composes the answer. This is what current models are explicitly trained for, so call quality is highest here, and adaptivity is free: a refusal ("I don't hold that account") can redirect the very next call. Cost: each model adapter must translate our registry schema to its provider's tool format, and tool-call quality on small local models varies — which matters for a local-first product.

**Option (b): a text protocol.** The model emits a fenced JSON block; we parse, validate against the same schemas, execute, and append the result. Provider-agnostic — one code path for every model ever, including ones with no tool-calling support — and the validation is identical to (a). The cost is a somewhat higher malformed-output rate (mitigated by schema-guided retry, but each retry is a spent call) and prompts that must teach the protocol rather than lean on training.

**Option (c): plan-then-execute.** The model reads the question and emits a whole plan of tool calls once; a deterministic executor runs the plan; the composer writes the answer from the results. Fewest model calls and the most auditable shape — the plan is an artifact you can log and replay. But it cannot adapt mid-flight: a step that returns a refusal or a surprising figure needs a second planning round anyway, and for the multi-hop chains in the stress-test mapping ("liquid → obligations → compute → answer inherits weakest grade") adaptivity is the point.

**The reframe: the registry contract is modality-neutral, so decide the contract now and make the wire format an adapter concern.** The registry defines typed schemas, the result envelope, and refusal semantics. The model adapter — which already exists as a boundary (`VIVA_MODEL` / `VIVA_MODEL_ADAPTER`, ADR-001's hybrid strategy) — decides whether those schemas are presented natively or as a text protocol. That keeps the decision reversible per model rather than global.

**My lean: the reframe, with (a) as the primary path and (b) as the degradation path** for models without native support. Either way the composer's T1 check — refuse any figure that arrives without a record ID — sits *outside* the modality, in code, identically for all three. Evidence that would change my mind: if the local models you actually run turn out to emit unusable native tool calls, (b) becomes primary and nothing upstream changes — which is the reframe earning its keep.

### D5 — The result envelope

Generalize `answer.py`'s `Answer` into the one shape every tool returns: data, grade, the date it is good as of, provenance (record IDs down to document and region), a coverage statement, caveats, and a machine-tagged refusal when no figure can be asserted. Three rules ride on it:

- **Refusal is a first-class result, not an exception.** `UnknownAccountError` and its siblings become refusal envelopes at the tool boundary, with the "here is what I *do* have" line the answer path already writes.
- **Composition inherits the weakest grade**, exactly as the stress-test mapping requires — the envelope carries the grade so the composer can do this without arithmetic of its own.
- **Every figure carries a record ID or the composer refuses the answer** — T1 enforced in code, not prompt, per the toolset doc.

This is less a decision than a ratification: the answer path already behaves this way, and the envelope makes it the law for every tool. Listed as a decision because its field set becomes a public contract the moment the registry exists.

---

## 5. Scope fence

This brief deliberately does **not** include: any write path or event schema change (T4 untouched — the projection stays read-only); any model call inside any tool (T2); any network access (T6); `project`, `search_documents`, or the memory verbs; changes to `questions.py`, enrichment, ingest, or the web surface beyond import paths; any change to any figure any existing caller sees — the real-vault before/after diff must be empty. The Builder can be held to this and the Verifier can check against it.

## 6. Order of work — strictly by reversibility

- **Step 0 — characterize before touching.** Capture the real vault's current outputs (`debug.tiers`, `debug.networth`, `debug.vault`, the test suite) as the *before*. Changes nothing; this is the yardstick every later step is measured against.
- **Step 1 — extract the core.** `ProjectionCore` (fold + state + caches) behind the untouched facade. Suite and diff must be clean.
- **Step 2 — move one family at a time** into its view module, facade delegating, diff after each family. Any family that resists cleanly separating is evidence for revisiting D1, cheaply, mid-flight.
- **Step 3 — registry v1.** Schemas, envelope, refusal semantics; the five tools of D2 implemented over the view modules.
- **Step 4 — adapter wiring** for D4's chosen modality, plus eval-style tests: a question in, tool calls observed, a cited answer out, uncited figures refused.
- **Step 5 — the real-vault run** (the standing practice): the stress-test questions from `agent-toolset.md` asked against your actual vault, every figure carrying its citation.

Steps 1–2 are pure refactor and fully reversible; the registry only begins once the seams have proven themselves.

## 7. Open questions for Vishnu

1. **D1** — core + view modules with a compatibility facade, or one of the alternatives?
2. **D2** — registry v1 as the five honest tools, or do you want the full twelve declared with explicit refusals?
3. **D3** — the structured filter object for `query_ledger`?
4. **D4** — the modality reframe (contract now, wire format per adapter, native-first with text fallback) — or do you want one modality committed globally?
5. Where should this land when approved — a design doc beside `agent-toolset.md` (whose status line and open questions it would amend), with the Steward slotting it into the reading guide?

> **Ruled 2026-08-01:** every recommendation accepted as written — (1) core + views
> behind the facade, (2) the five honest tools, (3) the structured filter object,
> (4) the modality reframe, (5) this document, slotted beside `agent-toolset.md`.

---

## What the build did (2026-08-01)

**The decomposition.** `projection.py` (1,564 lines, one class) became the
`viva/ledger/projection/` package: `core.py` (the event fold, account state,
overlays and shared caches) and view modules `accounts`, `balances`,
`movements`, `merchants`, `categories`, `rulings`, `tiers`, `positions`,
`coverage`, `activity`, with `LedgerProjection` in `__init__.py` as the facade
carrying today's exact surface — including the six private members other
modules were found to reach (`_state`, `_posted`, `_merchant_tags`,
`_attribute_history`, `_is_expense`, `_counts_as_spending`) and the
`_NATURE_OF_MAJOR` table one report imports. Two modules more than section 4's
sketch: **accounts** and **rulings** were families in the inventory table that
the sketch had not given files, and giving them files beat burying them in a
neighbor.

The proof of no behavior change is a characterization harness: a synthetic
event stream exercising every event type, every public read serialized to JSON
— 70KB of behavior — captured before the split and after it. **The diff is
empty**, and the full suite passes with exactly the baseline's numbers.

**The registry.** `viva/tools/`: an envelope (`ToolResult` — data, grade,
value-time, record ids, provenance, coverage, caveats, and refusal as a
first-class result), a `Registry` that validates every call against the tool's
schema and refuses with the legal values named, and the five tools:
`query_ledger`, `check_completeness`, `get_provenance`, `get_transparency`,
`compute`. Filter vocabulary is validated against the vault's own learned
values — its accounts, categories, tags, merchants, currencies — never a list
in code. `compute` parses, never evaluates: four operators, integer literals
only, every decimal figure arriving through `inputs` as an exact string, the
result inheriting the weakest input grade.

**Model-facing text stayed out of code.** Tool descriptions live in
`viva/prompts/` (`tools-v1.txt` at this point), versioned and digest-pinned
like every other prompt; the registry refuses to register a tool that has no
description section, so a tool cannot reach a model unexplained.

**The runner and the gate.** `viva/tools/runner.py` drives any *planner* — a
provider adapter doing native tool-calling, a text-protocol parser, or a
scripted function in a test — through the same loop, bounded by a call budget.
The T1 gate runs on every answer: each declared figure must cite record ids the
run actually read and a value some tool actually returned, and every number in
the answer's text must be traceable to this run's results. An answer that
fails is refused in code, whatever the modality.

**Verification.** A fresh-context Verifier ran the full lane: suite at
baseline, characterization diff empty, decomposition confirmed faithful
line-by-line — and four real defects found in the new tools, the two serious
ones being an income aggregate that silently ignored a date window (a lifetime
figure answering a dated question) and provenance document states reported
inverted. All four were fixed and adversarially re-verified: unsupported
filters now refuse and name what each read supports, income cites its source
accounts and carries the weakest posting grade, document states report as
posted / held / captured truthfully, and the citation gate matches numeric
tokens whole, never as substrings. The lesson worth keeping: the refusal
discipline has to cover *filters a read would ignore*, not only values a vault
does not hold — accepted-and-dropped is the quiet way a true row answers the
wrong question.

**Still to do.** The standing real-vault run: the stress-test questions from
[agent-toolset.md](agent-toolset.md) asked against the real vault, every figure
carrying its citation.

**What followed (built 2026-08-01, the conversation loop).** The D4 reframe
paid out as designed: `converse` on the OpenAI-compatible adapter presents the
registry's schemas natively (covering the hosted route and local servers with
one wire format), a text-protocol planner covers every other model through the
unchanged `extract` contract, and both drive the same runner and the same gate.
The gate itself was hardened when a live-model planner became real: refusals
and argument echoes no longer ground figures, and pass-through record ids never
join the citation pool — the residual (a deliberate derivation through
`compute`) is recorded under the gate-tightening item this doc's build notes
already owed. Every conversation exchange is captured in the vault
(`ReadRecorded`, `phase="speak"`) with its prompt digests, model, tokens and
cost. The entrypoint is `viva.speak`; no model has yet met the real vault.

**What the availability cycle changed (2026-08-04).** The residual recorded
just above — a deliberate derivation through `compute` grounding a fabricated
figure, and a grade the caller simply declares — was the subject. Closing it
meant giving a number an identity.

Every tool now emits each number it asserts as a **figure**: a value, what it
is, what it rests on, and an id the runner stamps in emission order across the
whole run. An answer cites ids; it does not restate values. A number no tool
emitted has no id to cite, so an invention has nothing to stand on rather than
merely failing a check afterwards. Four kinds exist, and only two are claims
about the person's money: `financial` and `computed` carry a grade, while
`activity` (what the agent itself did or holds on record, standing on whatever
recorded it) and `hypothetical` (a value resting on the person's own premise)
carry none. A grade is inherited from a figure's operands. Ruled with it: since
arithmetic is deterministic, a sum of corroborated figures is corroborated —
`compute` returns kind `computed` and inherits, rather than downgrading.

`compute` follows from that. Its operands are figure ids, or values the person
stipulated in this turn's question and which the question demonstrably
contains; a decimal typed straight into `inputs` refuses on the first call and
names the figures that are available. A supposition does not wear off — a
result with any hypothetical operand is hypothetical however many times it is
recomputed. Two things this cycle left wrong were settled the next day, in
*What the two-axis cycle changed* below: the arithmetic trapped an inexact
result rather than rounding it, refusing a number the vault knows exactly; and
a magnitude written into the *expression* string rather than passed as an
operand (`balance + 987654`) came back carrying the balance's document and
grade.

**The workhorse split in two.** `query_ledger` answers in totals and returns no
rows; `list_movements` returns the individual rows and refuses a call that
names none of account, category, merchant, tag or window. Six tools are
registered, and the descriptions file was `tools-v2` at this point; it is
`tools-v10` since the cycles below.

**What a result costs became a design constraint rather than an afterthought.**
A tool result is resent in full on every model call for the rest of the turn,
so its size is paid once per remaining call — which is what decides whether a
small local model can hold the conversation at all. A figure's records no
longer travel to the model at all: it cites an id and the runner resolves the
rest, so only their count is sent. Every uncapped read is bounded by a named
constant, and none of them grows with the ledger — measured at the reference
vault shape and at ten times it.

**Two shapes of honesty beside the gate.** Every read declares what it is
attested for, per account. And a refused turn is spoken in Viva's voice: the
planner composes the refusal once through `deliver_refusal`, checked by the
same number rule as an answer, with the machine's blunt sentence standing if
the composition fails or reaches for a figure it cannot cite.

**Verification.** Two fresh-context rounds, both reporting FAIL, both repaired.
The lesson worth keeping came from the second: its worst finding was a defect
the first round's repair had introduced. A repair to a guard is itself a change
to a guard, and needs the same mutation proof the guard got.

**What the two-axis cycle changed (2026-08-05).** Both defects left open above
have the same cause: one property was being asked two unrelated questions.
*What does this number rest on?* is an evidence question, answered by documents
and a grade. *Did the arithmetic come out cleanly?* is a precision question,
answered by the derivation itself and having nothing to do with evidence.
Collapsing them produced both failure modes — a fabricated magnitude inherited
evidence it never earned, and a division that does not terminate refused a
number the vault knows exactly, which is the product saying *"I cannot know"*
about something it does know.

A figure now answers each separately. `grade` and `record_ids` say what stands
behind the value; a new `exactness` says whether the derivation terminated.
Exactness is not a grade: it carries no evidentiary meaning and never moves
one.

**Attestation follows the shape of the operator.** Multiplying or dividing by a
bare magnitude is a change of units — it rescales an attested quantity and
leaves it attested, so the result stands on every record either operand carries
and takes the weakest grade among those that carry one; a graded count hands
its evidence to what it scales rather than losing it. Adding or subtracting a
bare magnitude injects a quantity nothing measured, so a total is attested only
when every term is: one term standing on no record leaves the whole standing on
none, with no grade either. That asymmetry is dimensional analysis applied to
provenance. `computed` stays a money kind, so the gate that refuses a money
figure citing no record is what turns *rests on nothing* into *cannot be said* —
no new machinery, and the fabrication loophole is closed twice over: on
dimensions where the injected magnitude meets money, and on attestation where
it meets a plain number.

**A quantity states what it measures.** Money in one currency, or dimensionless
— a count, a ratio, a literal. Money adds to money and scales by a plain
number; two amounts divide into a ratio and can never be multiplied; an amount
and a plain number do not add at all. A currency clash is a property of the
expression rather than of the call, so a figure bound to a name the arithmetic
never reaches decides nothing. This only works if the reads say what they
measure, so every amount a tool emits now states its currency and every count
states none — including a window in which nothing moved, whose total is zero
*of a currency*, resting on the accounts whose statements answer for the
period. A summary whose movements are not all in one currency refuses rather
than totalling them.

**`inexact` no longer refuses.** A quotient that does not terminate comes back
marked as rounded, and the runner attaches an approx term to any bare statement
of its value after the model has spoken. The hedge cannot be dropped, because
the model never writes it — the same reason it cannot say a number no tool
emitted — and it is a substitution rather than a vocabulary check, so it is not
a word list of size one. Money is written at hundredths, the precision money
has. A dimensionless result is written to six **significant figures**, not to
decimal places: a fixed decimal scale writes a small enough ratio as `0.00`,
which is not an approximation of it but a different claim, and a
significant-figures rule cannot round a nonzero value to zero at any magnitude.
Counting from the leading digit also means a power of ten moves the point
without moving the digits, so a proportion and the same proportion per hundred
agree. The rounding is taken once, on the result, at a working precision far
wider than the scale anything is finally written at.

Six tools are still registered; the descriptions file was `tools-v5` at this
point.

**Recorded, not fixed.** The approx term is attached by inserting it in front
of the value, and that mangles sentences of known shapes — a currency symbol
in front of the digits becomes `$approx 85.71`, and a range written with a
hyphen is taken apart. The mechanism that is safe is substitution on figure
ids, which the run itself minted; substitution into prose the model composed is
not. That, and the same value printed unhedged by the terminal footer one line
below the answer, are open items in the TODO rather than shipped fixes.

**What the names-and-dates cycle changed (2026-08-06).** The first acceptance
run against the real vault answered 6 of 11 and got no number wrong. Every
failure was a correct, grounded sentence the gate would not release, and two
shared one cause: **the gate could not tell a magnitude from a digit string.**
An account's last four and a row's date are not claims about money — one is a
name and the other a coordinate — and both were read as unlicensed numbers.

The fix is the move figure identity already made, applied one layer out. A run
holds a ledger of what it established, and an answer may say what is in it. So
the ledger now holds three kinds of thing rather than one:

**Names.** A read that speaks about an account returns the names it used, in
`identifiers` — the id every filter takes, and the masked form of the number,
which is what the surface already shows a person. The gate blanks a whole name
out of the answer before it counts numbers, exactly as it already did for
figure ids. A name is therefore licensed **whole and only whole**: the masked
form says which account, and the four digits inside it, written bare, remain a
number nothing emitted. A name that is itself a quantity licenses nothing, so
calling a magnitude a label is not a way past the gate.

Dates are deliberately held to a weaker rule than names, and the asymmetry is
the decision rather than an inconsistency. A date's parts are bounded tokens —
a day, a month, a four-digit year — and the declared-date rule already licensed
them at a cost taken openly. An account's last four is an unbounded four-digit
number that looks exactly like an amount, so it gets the stricter treatment.

**Dates.** A date some result carries may now be said without being declared.
Declaring one was never a check: the gate accepted any declaration of a date
the run already held, so the ceremony refused true sentences and prevented
nothing. What it did protect survives — a date no result carries must still be
declared, and is admitted only inside a period the run is attested for. A
listing read is usable in prose again as a result: writing fifty rows no longer
means declaring fifty dates. The accepted cost, taken knowingly: the parts of
every date a read asserted are sayable, so a small integer that coincides with
a day of the month passes. That was already reachable by declaring it.

**And a summary states how many months it spans**, as a figure with an id and
no currency. The period count existed in the payload, where arithmetic could
not reach it — so "what do I spend a month" had no divisor, and the model spent
three tool calls in the acceptance run hunting for one before refusing. A
divisor nothing emitted cannot be cited, and a number that cannot be cited
cannot be computed with.

T1 is untouched. Nothing about what licenses a *figure* moved; this cycle
widened what may be **said**, never what may be asserted as money. Six tools
are still registered; the descriptions file is `tools-v6`, and the speak
prompts are the v6 trio.

**Recorded, not fixed.** Two things this cycle surfaced and deliberately left.
A movement's *description* is the statement's own words and may carry digits of
its own — a store number in a payment line — so a listing answer that writes
descriptions is still refused. Licensing descriptions wholesale is unsafe,
because a description can contain an amount; it needs its own ruling. And the
approx-term insertion recorded above now has a wider blast radius: it
substitutes into a licensed name, so a rounded figure whose value equals an
account's last four renders as `••••approx 4417`.

**What the shape cycle changed (2026-08-07). The gate described above no longer
exists.** Everything from *the runner and the gate* onward — the token scanner,
the six licence sources, the name-blanking and id-blanking passes, the
date-declaration mechanism, `ground.prose`, the approx-term insertion and the
model-composed refusal through `deliver_refusal` — is deleted. Read those
sections for how the problem was understood; nothing in them describes the
code. What survives whole is the *envelope*: figure identity, the four figure
kinds, `grade`/`record_ids`/`exactness`, `covers`, and the one rule the gate
had that was never about tokens — **a money-kind figure with no `record_ids`
refuses.**

The second acceptance run is why. It answered 5 of 9 answerable questions on
the hosted target against a bar of 9 of 11, spent 67% of its model budget on
refused turns, and got no number wrong on either target. **Every refusal was
triggered by a date or an identifier token; not one by a bad figure.** Six of
seventeen turns refused for a bare four-digit year, in one case the year the
person had just asked about. A whitelist over free-form language had taken five
cycles of new rules without closing, and each new rule made the clause
underneath harder to remove.

**So a model writes no digits, in either direction.** An answer is a **shape**
— a list of clauses, each a run of literal words with typed holes in it — and
the shape is committed *before any tool is on the table*. A clause whose own
words carry a digit is rejected before a read happens, which is a character
class over one field rather than a list of allowed words. Then the reads run;
everything they establish gets an identity in the run's ledger — figures, the
accounts and counterparties they spoke about, the days they carry, the spans
they attest, the caveats they wrote. Then the planner says which of those fills
which hole. Every binding is a reference; not one is text. What is checked is
that structure: totality, existence, type, records, and that every caveat
standing behind a stated figure is placed. Nothing reads the sentence.

**A number carries what it measures.** Typed holes make a magnitude impossible
to invent and do nothing about a real one put where something else belongs —
the failure the first run produced and only coincidence stopped, when a gross
sum of postings including card settlements and own-account transfers was called
*the total you spent*. So every figure declares a quantity from the closed
vocabulary in `viva/quantity.py`, every hole holding a magnitude declares what
it is asking for, and code compares the two declarations. ADR-010 is untouched:
no model checks another model, and an emitter that cannot name what it measured
fails the build rather than a person.

**An account is an entity.** `identifiers` carries attributes rather than
strings, and one function chooses which of an account's names a person reads,
adding the masked number only where another account in the same sentence would
otherwise read identically. The three-forms-of-a-name split the last run found
has nothing left to happen in: the model never writes the name.

**A refusal is a reviewed sentence chosen by machine tag.** Twenty-one tags,
twenty-one sentences in the persona pack, the bijection enforced at build time.
Nothing is composed at the moment of refusing, so a refused turn binds nothing
and costs no model call. What it can no longer do — say what it *could* have
told you — is the subject of [the-suggestions-channel.md](the-suggestions-channel.md).

**A hole nothing can fill costs its clause, not the turn.** The clause is
dropped and a pack phrase names what was missing, which is where the
availability was supposed to come from. `PAYLOAD_TARGET` rose 4000 → 5000 to
pay for the entity identities and the per-figure quantity, and sits at 96% of
its ceiling.

**Not built, and it is the largest piece of the design that is not.** §5.4's
third consequence — computing from the registry whether a slot *can* be filled
before a call is made — is unbuilt. `{document}` is the proof: it is a declared
type, taught to the model and placed by three question phrasings, and no tool
emits one. That is where the 67% of spend on refusals was supposed to go. Also
unbuilt: `{tag}`, twelve of thirteen slot types having shipped. _(The count is
of that day. `rows` and `supposed` were added afterwards and `grade` was retired
on 2026-08-17; eleven types are declared today and `{tag}` is still not one of
them.)_ **And none of this has run against real data** — the acceptance runs
above tested the machinery it replaces.

**What the real vault then said (2026-08-08).** It has run now, three times: two
local models side by side, and a read-only audit of a live sitting.

The ordering rule holds. A model asked to author a shape before any tool is on
the table does it, and does it first time — seven shapes from one model with
none rejected, one from another under the text protocol. **The condition nobody
had costed is the channel, not the shape:** the second model emitted no tool
call in twenty native-protocol replies, so it never reached a shape at all, and
the configuration in force was pointed at it. Whether this design works is a
per-model question with a real answer, and the answer differs.

**A wrong number reached a person, and the shape mechanism is not where it came
from.** Four faults compounded — a rate renderer wrong by a factor of a hundred
([#3](https://github.com/vishnuyar/orionviva/issues/3)), the card-direction
defect ([#1](https://github.com/vishnuyar/orionviva/issues/1)) feeding the
numerator, a model reaching for a read that answered a different question, and
the quantity check ([#4](https://github.com/vishnuyar/orionviva/issues/4)).
**That last one falsifies a property stated three paragraphs up.** "Code
compares the two declarations" is true and is not sufficient: a division
compares only the *result's* declaration against the hole's, so two operands of
the wrong kind divide into a result of the right kind and the check passes. The
same check refused a bad binding correctly one turn earlier in the same session.
It sees a figure; it does not see through an operator.

`{document}` is still unobserved rather than disproved — three runs and no model
has ever authored one — and no turn has ever dropped a clause, so the clause-
level degradation this design traded a clean refusal for has not been read by a
person yet. Both are recorded as open coverage, not as passes.

**The hole the division left is closed (2026-08-08).** A quotient now carries
what its operands measured: two figures of one kind divide into
`ratio_of_<kind>`, two of different kinds into bare `ratio`, and a hole asking
about a particular quantity takes only its own. So the check no longer looks
through an operator at a result of the right kind with the wrong operands
behind it — the operands' kind is *in* the result. The eight `ratio_of_` names
are taught to the model in a new released prompt (`speak-shape-v3`); `ratio`
survives for the comparison of two unlike kinds, where no single name is true.

Two of the other three faults in that paragraph are closed with it: the rate
renderer carries a proportion as the quotient and writes it per hundred at one
place, and the transactions summary reads direction off the account's kind
rather than the posting's sign. The read that answered a different question is
untouched. **And the direction fix is the summary only** — `list_movements`
handed the model a row whose `amount` was the raw posting sign with nothing
in the row from which direction can be derived, so a model reading rows rather
than totals can still call a card purchase money received.

**What a figure does not cover is placed by the run, not by the shape
(2026-08-09).** The rule above — every caveat standing behind a stated figure
is placed — was enforced by refusing an answer that left one unplaced, which
made the shape answerable for it. A shape is authored before any read, so
whether there will be a caveat at all is not knowable when a hole for one must
be declared. That is a bet with no winning side: author the hole and read no
caveats, and the clause holding it is dropped for a hole nothing could fill;
leave it out and read one, and the turn refuses. A real turn lost every clause
that way and refused `nothing_established` while holding three correct,
corroborated balances.

So the hole became optional and the rule became the runner's. An unfilled
caveat hole is erased from its clause and the claim around it stands; every
caveat owed by a stated figure and not already placed by the answer is appended
verbatim after it, introduced by one pack line. The disclosure is now a
property of the machine rather than an instruction a planner can fail. The
`caveat_unplaced` tag is gone and the bijection stands at twenty tags; `pack-v6`
carries the new line and drops the sentence nothing can reach, and `speak-v9`,
`speak-shape-v4` and `speak-final-v9` teach the hole as optional.

What this costs is text: a hole erased from mid-phrase leaves the phrase, so
`"...{trust}, and {limit}"` becomes `"...corroborated, and"`. Repairing that
would need a list of connective words, which is the sentence-reading this
design exists to avoid, so the released shape prompt asks for the hole at a
clause end or in its own sentence and the mechanism guarantees only that the
caveat is said. The alternative considered and rejected was retiring the hole
outright and always appending; it removes the awkward case and the second
placement path with it, and remains available if the guidance does not hold.

**Two identity defects the same runs surfaced, both repaired.** The claim above
that a masked number is added *only* where another account would otherwise read
identically was false in practice: the run minted a fresh entity id per
occurrence, so one account named by four reads became four entities, collided
with itself, and was written with its own masked number appended to a name
nothing was competing with — `Everyday Checking ••••4417` for an account that
was the only one in the sentence. Caveats
had the same shape of bug one field over — a fresh id per occurrence meant four
ids for one sentence, and the placement rule then demanded it be said four
times. An identity now belongs to the thing rather than to the occurrence.

Separately the citation footer cited one entry per *hole* rather than per
figure, and displayed each figure's words keyed by figure id, so a figure
filling both an amount hole and a grade hole appeared twice and showed whichever
hole was read last — the total's amount never reached the footer at all. _(That
pairing is no longer expressible: the grade hole was retired on 2026-08-17, in
the closing amendment. The footer defect itself was real and is fixed.)_ The
footer is the surface that makes an answer checkable without re-checking it, so
a footer that silently shows a grade where the sentence said an amount is worse
than a duplicated line.

**And the clause-level degradation has now been read by a person.** The open
coverage noted above — that no turn had ever dropped a clause — closed in the
worst available way: the first turn to drop clauses dropped all of them. The
mechanism worked as designed. What it revealed is that a design where the model
must bet, before reading, on what the reads will contain has no safe play, and
that is the thing the repair addresses rather than the dropping itself.

**The caveat hole is retired, and the aggregate is dated by its stalest input
(2026-08-09, later the same day).** The amendment above made the hole optional
and left two ways to place a caveat — the answer's own hole and the runner's
append — with an erased hole still able to leave a dangling phrase behind it.
Both close by removing the hole: `caveat` is no longer a kind a hole may
declare, no binding names one, and the runner places what every stated figure
owes. One path, no erasure, and nothing a planner can get wrong. `unknown_caveat`
goes with `caveat_unplaced` and the vocabulary stands at nineteen tags;
`pack-v7` drops the two sentences nothing can reach and `speak-v10`,
`speak-shape-v5` and `speak-final-v10` teach the shorter grammar.

Separately, `_aggregate_net_worth` dated its totals by the point's own `as_of`,
which with no window asked for is the day the question was asked. A real run
therefore stated a total "as of" today over balances two years old. The
arithmetic was exact and the date was a claim the evidence did not support, so
a total is now dated by the oldest line inside it. The per-account figures were
already honest and are unchanged.

**Two other things the same pass settled.** An account that answers to two
names — the tail of its ledger path and what its statements call it — matched
twice in `listen._candidates`, and the exact-match branch counted pairs rather
than accounts, so it reported "more than one of your accounts is called X"
about one account. That is the same self-collision the entity ids had, in a
third place. And the category vocabulary, which rides into the interpreter
prompt on every ruling, is now held to `is_shareable` before it crosses to a
model (T9, D2's owed ruling). The gate is a merchant-descriptor heuristic doing
a category's job: it withholds `" to "` and `" from "` phrasings, peer-app
names and non-ASCII letters, so it catches a category naming a person in a
payment phrasing and misses one named after a person outright. It fails closed,
and what it costs is a prior rather than a match — `settled_category` still
reads the whole vocabulary locally, so an answer still lands on the person's
own spelling.

**What a model is told and what a person may say are two lists (2026-08-09,
after review).** The T9 gate above was applied to a slot's `choices`, which
carries two jobs at once: the vocabulary a reply is validated against, and the
vocabulary the interpreter prompt is given. Narrowing it narrowed both, so a
category the person had coined and already used became unanswerable on a
merchant question — refused as outside the vocabulary, with the alternatives
read back to them omitting their own word. The gate had been described as
costing a prior and never an answer; on that path it cost the answer.

A slot now declares `offered` beside `choices`: what a model may be told,
`None` meaning all of it and an empty tuple meaning none of it. The fence stays
the whole vocabulary. The gate moved into the two places a category slot is
built, so no call site decides it, and a slot whose `offered` is not part of
its `choices` fails at construction rather than telling a model about an option
it would then refuse.

**An aggregate with an undated line now carries no date at all.** The stalest-
input rule reused an inline `min` rather than `NetWorthPoint.oldest_input`,
which was already computed and already in the payload. The property returns
empty when any line carries no date; the inline version skipped that line and
dated the total by the oldest *known* one, which understates staleness exactly
where it matters. The property is now what the tool reads. The consequence is
that a point holding one undated asserted asset dates nothing — honest, and it
means the run supplies no bindable date for that read. What the answer then
does is not settled by any test and is named as a Witness case.

**A caveat's identity stopped travelling.** The run still gives one an id —
that is how it knows which caveats a stated figure owes — but the id no longer
reaches the model, because no binding can name a caveat any more. Two released
prompts had taught that exact shape, and a model still emitting one would have
cost a whole turn rather than a clause.

**The dating rule is reversed, and a row stops carrying two numbers
(2026-08-09, fourth amendment).** The stalest-input rule above was shipped and
reversed the same day. Vishnu's ruling: a balance carries forward — absent a
newer statement, the last value observed is still what the account holds — so a
total is dated by the day it is good *for*, not by the day its evidence was
taken. With no `as_of` asked for that is today; how old the evidence under it
is rides on each line's own date. Two things came out of the reversal. It
opened a hole, because `as_of` was validated for shape alone and echoed into
the result's date, which is what founds a day an answer may state: a future
`as_of` let a figure be spoken as good for a day that had not happened. A read
now refuses one. And the ruling turned out to be written down rather than
built — `net_worth` with no argument dates its point by its newest input, so
the tool passes today explicitly. The test that should have caught that was a
tautology over the line it was testing, in a fixture where every date was the
same; it now uses three distinct dates and asserts the ruling.

Separately, `_movement_row` carried both the raw signed posting and the
direction-corrected `effect`. `list_movements` filtered to `effect`;
`get_provenance` returned the row whole and built its figure from the raw
amount. So one card charge produced two figures with the same description, the
same declared quantity and opposite signs, both citable in one turn — in the
tool whose whole purpose is to stand behind a figure. The field is gone from
the row rather than filtered out of two of three readers, which is the
difference between a rule and a habit.

**And a caveat stated a figure that was not the figure.** A ruling can carry a
category that is present and empty, and the read grouped by category defaulted
only on a *missing* key — so that money sat in a nameless group the "still
uncategorized" caveat never counted. A caveat is joined into the answer
verbatim, so a person read a confident amount, with no id and no grade behind
it, understating what the agent did not know. Every path now treats missing and
empty as the same absence.

## The third axis: what a figure covers (2026-08-10)

A figure said two things about itself. `grade` and `record_ids` say what it
rests on; `exactness` says whether its arithmetic terminated. Neither says
**which set the number was taken over**, so a figure that was one of six
account balances and a figure that was the total of all six made the same
declaration, and the check that exists to stop a real number being spoken as a
claim about something else compares two strings that both read `balance`.

A figure now carries `boundary`: whether the set it ranged over is everything
the quantity it declares would range over, how many of a countable set it
counted, what a filter narrowed it to, and what it leaves out. It is a
structured field rather than prose, because a sentence appended to an answer
cannot be compared between two answers and cannot become the scope clause of a
claim shown to a counterparty. It is not in the model-facing payload; the run
places its sentences the way it places caveats, so the disclosure is a property
of the machine rather than an instruction a planner can fail. `pack-v8` carries
the nine sentences the boundary places — one for a figure over some of the
accounts a person holds, one for each way a filter narrows a set, and one for
what a figure measures and leaves out — and `tools-v8` teaches the reads that
populate it. _(Version ids added 2026-08-14: this section named none, which left
`pack-v7` as the highest pack this document mentioned while `pack-v9` was in
force.)_

The three reads that populate it hold the knowledge already: balances knows a
per-account figure is one of many, the spending read knows what its filters
narrowed it to, and the net-worth point knows what it could not count. A gap
carries a reason from a closed vocabulary, and whether it may name a remedy
follows from that reason: a figure the point refused names what would settle
it, and an account nothing measured names nothing, because a remedy there would
be invented.

Two shapes only a real vault produced. One account can be **both** a ruling
target and an opened account with no statement, arriving as two gaps whose
reasons contradict; gaps collapse by account. And a document read but not
posted is a gap that names no account at all, since it may attest an account
that does not exist yet — it is counted rather than named.

*Not covered:* narrowing by tag, nature or currency records a boundary and
places no sentence, because naming one needs a written form none of them has.
What would settle a gap travels as data and is not spoken, since those words
live where the gap is computed rather than in a reviewed pack.

---

_Amended 2026-08-16 (the shape does not know how many rows it has). A
boundary gains a second half. Beside how the read was narrowed, a figure now
carries a **`cut`** — the one slice THIS figure was taken over — because a read
narrows once and cuts into as many groups as it has, and which cut a figure is
is a property of the figure. Every grouping the schema offers names its slices
now, including the three the vault holds no entity for: a subcategory pair, a
tag and a currency are each written as the label the vault holds them under,
which is a statement of that figure's scope and makes no promise to be a handle
a follow-up accepts. That is what let a group key with no entity be spoken at
all. A cut is also the one boundary entry a whole figure may carry, since
naming which slice a figure is is not a way of falling short of anything._

_The *not covered* line above keeps its verdict and loses its reason.
Narrowing by a **tag or a currency still places no sentence**, but no longer
because none of them has a written form: `pack-v10` carries a sentence for
each, in the narrowing voice, and the table that maps a filter to a boundary
entry is simply still account, category and merchant. The gap is a wiring one
now rather than a design one, and it is named rather than closed. Nature has
neither._

_The run's ledger gains a member. Alongside figures, the accounts and
counterparties a read spoke about, the days it carries, the spans it attests and
the caveats it wrote, it now holds **readings** — so the enumeration under *So a
model writes no digits* above is one short from this cycle on. A read is a thing
an answer can refer to and not only a bag of things it establishes, which is
what a `rows` hole binds to: how many figures a read will hold is not knowable
when the sentence holding them is authored._

_Four families moved with it. `speak-shape-v7` teaches the `rows` hole, whose
filling is a block the machine writes a line of per figure, so how many rows
there are never reaches the model; `speak-final-v11` teaches the sixth kind of
reference, `{"read": "rN"}`, which names a whole reading rather than one thing
in it; `tools-v10` teaches the `vocabulary` mode of `query_ledger` — what
labels this vault holds under any of the six groupings, and how many, which is
a different number from how many groups its spending falls into; and
`pack-v10` carries the seven sentences that go with all of it. `speak-final-v10`,
`speak-shape-v6`, `tools-v9` and `pack-v9` were in force until this cycle._

---

_Amended 2026-08-17 (a blank is not a filter). **An empty optional field means
the field was not sent**, decided once in `Registry.call` and so true of every
tool at once. A JSON schema says what a field may hold and cannot say that a
field must be left out rather than sent empty, so a caller that fills in every
box it is shown was asking the vault which account is named `''` — four
consecutive questions against a real vault came back refused, one having spent
a whole turn's budget of calls peeling empty boxes without reading the ledger
once. The rule keeps the two lines the validator already drew: only fields the
schema names, so an open map of caller-chosen keys is untouched and a
misspelled filter still refuses by name, and only optional ones, so a required
field sent empty is still a fault._

_**A filter refusal now names every fault it can see**, under the machine tag
`invalid_filters` when there is more than one, the way the registry's own
validator has always answered. One fault still comes back under its own tag._

_**The *not covered* line above closes for the reads that record a boundary at
all.** Narrowing by a tag and by a currency each place a sentence now — two
entries in the table that maps a filter to a boundary entry, using wording
`pack-v10` already carried — and narrowing by nature cannot happen, because
`nature` is **withdrawn as a filter**. Not given a sentence: withdrawn, from
the filter-support table for all three reads, from `QUERY_LEDGER_PARAMS`, and
from the movement test underneath. The rule that a filter an entity would
ignore is refused rather than accepted-and-dropped, read one step on: a set
narrowed in a way no sentence can state is the same fault, so the narrowing
stops rather than the disclosure being invented. **What it does not close is
four reads that populate no boundary at all** — the transactions and holdings
entities of `query_ledger`, its income metric, and `list_movements`, which
honour six, two, one and six filters — so nothing any of them narrows by can be
said in an answer, there being no boundary for a sentence to be placed from; and
a fifth, the balances read, records account counts and never records what it was
narrowed to, so filtering it by currency is unsayable too. This paragraph as
first written claimed the general form — that every filter a read honours can
now be said in an answer — which was **generalised from two wired lines on the
spending read and was false the day it was committed**. What stood beside it as
holding it does not: that test compares three sets of names — the filters the
reads honour, the filters the form offers, the filters the writing table can
word — and never asks a read whether it records anything. The general claim is
closed, and the generalisation named as the fault it was, in this day's later
amendment below. This removes a capability — **`show me my transfers` is no
longer askable**, and nothing else offers it; it returns in
its own cycle with a wording authored to carry it. The `nature?` field in D3's
sketch above is a design option from before the tool existed and was never
built as written; what shipped is the filter list in `tools-v11`, which is the
descriptions file in force._

_**A spending group whose movements name no counterparty is named rather than
dropped.** Four of the five spending groupings already guarded their key;
merchant did not, so a blank description reached `bounded()`, which refuses to
record a set narrowed to something unnamed — an exception out through a
boundary whose module says a call never raises — and a whitespace-only one,
which is truthy, passed that guard and reached a person as a line with a real
amount and no name. Both now land in one named residual, so the grouping still
reconciles with the total and count the same read states. Dropping them
instead would have left a figure claiming to be the whole of the spending while
covering part of it, which is the failure the boundary exists to prevent. The
residual label is minted as no entity, for the reason a subcategory pair is
not: it is the scope of a number, never a handle a follow-up accepts. The blank
key also leaves the held-merchant set and the counterparty vocabulary, so
`merchant: ""` refuses and a count of counterparties never counts nobody._

_Recorded and not fixed: a description of nothing but punctuation is still its
own group, still mints an entity, and is still refused as a filter — so an
answer can name a counterparty the follow-up bounces. Unchanged by this cycle
and needing its own, because whether such a label joins the residual is a
decision rather than a repair._

---

_Amended 2026-08-17 (the read's own account of why it could not answer). **A
refusal is a reviewed pack sentence chosen by machine tag, and that now holds
one call frame lower down.** A turn that reached its delivery with nothing, or
spent its whole budget of calls, says the verdict and then the cause: the
verdict in the pack's words for the runner's own tag, unchanged, then the cause
in the pack's words for the tag of the read that stopped. `pack-v11` carries
those seven sentences and `pack-v10`'s moments otherwise verbatim; `pack-v10`
was in force until this cycle._

_**Which causes may be spoken is a closed set, and it lives with the envelope
rather than at the refusal sites.** A read declares nothing new: `envelope.py`
holds `SPEAKABLE_REFUSALS`, and the pack's sentences and that set are held to
each other at build time, the way the runner's own tags and their sentences
already are. No tool file gained person-facing prose._

_**What admits a tag to that set.** A cause is speakable when it concerns the
reach between the question and the records — what the records hold, how they
can be narrowed, whether anything was named to narrow by — and when its whole
account survives having every value the caller supplied stripped out of it. Two
kinds of tag fail the second half. One whose stripped account is only about the
form of the call is an instruction to whoever called the read, and a person
reading it would be reading the product's own vocabulary. One whose account
depends on what its payload happens to contain is not a declaration but a bag,
and no single sentence can be true of two different causes — which is why the
multi-fault tag that aggregates several faults under one name is not in the set,
however vault-facing the faults inside it might have been. Clearing both halves
is a gate and not an entitlement: a tag that clears them still earns no sentence
unless what is left, once the caller's values are gone, tells a person something
the verdict did not already tell them, and that is why `not_a_balance_account`
is out._

_**No sentence has a slot, and that is the point rather than a saving.** The
reads' own texts quote the value they were called with, and the caller is a
model this project has recorded inventing filter values when refused, so
speaking one would tell a person that a category they never named does not
exist in their records. A vague true cause beats a precise invented one._

_**Which read, and when: the last entry a registered tool produced, and only if
it refused.** Eligibility routes on registry membership, so the runner's own
note about a shape and a step naming no registered tool are passed over rather
than recognised, and nothing reads a result's words, its payload or what
constructed it. A turn whose last read succeeded says the verdict alone: a cause
that stopped being the reason is true and not the answer, which is the shape of
failure this refuses. Whether the strict rule covers a useful share of the turns
that produced it is a question for the record of a real run, not for the suite._

_**Only two verdicts defer**, and both mean the delivery offered nothing:
`nothing_established` and `call_budget_exhausted`. A broken protocol has nothing
to do with what a read said, and every binding-gate fault means the run did
establish things and reached wrongly — replacing that confession with a hint
about narrowing would be the reverse of this product's argument._

_**`RunResult` gains `diagnosis`**, carrying the read's tag into `to_dict`, into
the recorded verdict of every speak event and into the debug reader's per-turn
line, so the next sweep can count which read refusal most often ends a turn.
Its meaning is fixed and permanent: **empty means no cause was spoken, not that
no read refused.**_

---

_Amended 2026-08-17 (every clause carries a hole). **The structure listed under
*So a model writes no digits* was one check short.** A clause comes into being
only if it places at least one hole, refused by the same constructor that
rejects a digit — so the reader of what a model sends inherits the rule rather
than restating it, and there is no second code path that could come to disagree
with the first. A clause with no hole could not go unfilled and so could never
be dropped, cited no figure, owed no caveat, placed no statement of where its
claim ended and added nothing to the grade: model prose that nothing in the run
examined. Two false claims reached a person through that gap, one of them a
sentence the persona pack already places on a condition, written unconditionally
beside the very figure it denied._

_**What is closed and what is not.** Every clause can now drop, every asserting
clause answers for its records, its caveats, its scope and its grade, and a turn
that established nothing refuses rather than speaking. The words a model writes
*around* a hole are still read by nobody — ADR-013's residual, narrowed and
standing. `speak-shape-v8` teaches the rule and merges the words introducing a
list into the clause holding its `rows` hole, so a list nothing can fill takes
its own introduction away with it; `speak-repairs-v2` carries the nineteenth
repair, `hole_the_clause`. `speak-shape-v7` and `speak-repairs-v1` were in force
until this cycle._

---

_Amended 2026-08-17 (the reads that say no scope). **A read that narrows a set
records what it narrowed it to, and a test asks the read rather than the
table.** That is the general form of what the earlier amendment of this day got
wrong, and it now holds without an exemption list: the transactions read, the
holdings read, the income metric, `list_movements` and the balances read all
record what narrowed them, and
`test_every_filter_a_read_honours_can_be_said_in_the_answer` holds every read to
it by calling each one with each filter it honours, on more than one shape of
vault, and reading the figures that come back. **Where it is not yet proved,
said plainly rather than generalised over:** the vaults it calls are ones where
every filter names something the vault holds, and there is one case below —
income narrowed by a currency on a vault of several — that comes back with no
figures at all, so the rule has nothing there to be true of. That case is named
open, not covered by the claim._

_**The claim corrected, and how it was made.** The earlier amendment said every
filter a read honours can now be said in an answer. It was generalised from two
wired lines on the spending read, and it was false when written: four reads —
the transactions and holdings entities of `query_ledger`, its income metric, and
`list_movements` — populated no boundary at all, and the balances read recorded
account counts without ever recording what narrowed it. What was offered beside
the claim as holding it compares three sets of names, never calls a read, and
could not have seen any of it; it is renamed to what it does, and the name that
asserts the claim now belongs to the behavioural test. Two tests must not both
bear a name asserting the same claim, and only one of them can fail when the
claim stops being true._

_**A read that groups cuts as many ways as it groups.** The transactions read
cuts twice in one read, a figure per account and a figure per month over the
same movements, and each figure now names which slice it is — a month's slice
being the **calendar month**, first day to last, because the cut names the
group and the group is the month; written from the first and last day something
actually moved it would be a fact about the data rather than about the grouping,
and two vaults' January would be different periods. A figure is the whole of
what its quantity ranges over only where nothing narrowed the read and that
grouping produced the one group._

_**A block of rows over a read that cuts more than one way is refused.** The
block is built from every figure of a read that named a slice, so a read
declaring slices in two vocabularies would state the same money once for each
way it cuts, under a claim of delivery. The guard compares the declared cut
kinds and is keyed to no read and no tool; it reuses the existing wrong-kind
refusal, which already has a reviewed sentence. Nothing regresses — a block over
that read refused before this, for the poorer reason that it had named no slice
at all. The day it is decided which grouping a list enumerates, the guard is
where that lands._

_**A row is a member of a set and never a slice of one.** A listed movement
declares **whole** — one movement is all of what the quantity `movement`
measures — and names no slice, because naming one would need a way of narrowing
a set to a single movement and there is none. So that read records what narrowed
it on **one count figure over the whole matching set**, which is also what makes
*how many payments went to that counterparty* answerable with a number. What the
row cap left out moves into a caveat as well as the coverage line, so a list
showing fifty of three hundred tells a person and not only its caller; the half
naming which filters would reach the rest is instruction to the caller and stays
there._

_**Holdings and income.** A holding is a member of what the holdings read
ranged over rather than a slice of it, so its figures name no slice and each
carries what a filter chose. A member of a set is also never the whole of what
a balance measures: what is held beside one instrument is the other instruments
and the cash this read cannot see, so a per-holding figure declares it is not
whole on every vault, however few rows came back and whether or not anything
narrowed the read. Declaring one whole would be worse than recording nothing —
a whole figure places no scope sentence, so the claim would delete every clause
the answer around it carried, which is the inversion this cycle exists to
remove. Not whole is still a declaration, and it costs a person nothing to
read. The count beside them is a different quantity, how many holdings were
measured, and over a read nothing narrowed that is all of them._

_The income metric does cut, by currency, so each of its figures names the
currency it is the income in and declares the whole only where nothing narrowed
the read and there is the one currency to be in. A slice is named in the vault's
own vocabulary, and an income bucket carries no currency of its own: where the
accounts declare more than one, the read groups everything under a key that
names no currency anybody holds, and such a figure carries no slice rather than
putting a person's income under a currency they hold nothing in. So the
consequence worth naming is a conditional one — a block of rows over the income
read, which refused before because that read named no slice, builds **where the
vault's currencies are known to it**, one line per currency, and refuses as it
did before where they are not._

_**The balances read's `whole` and its `selected` are one question.** It gained
what narrowed it, and in the same change both places that computed "whole" from
account counts alone gained the requirement that nothing narrowed the read.
Separately they contradict: a one-account vault, or one where every account is
in the currency asked for, would build a figure claiming to cover everything
while naming what it leaves out, which the boundary constructor refuses — an
exception out of a read and through a registry whose module states that a call
never raises. Wherever a read decides wholeness from what narrowed it, the two
are now read off one list rather than off the filters twice; and where a figure
is a member of the set rather than the set, it is not whole whatever the
filters said._

_**Open, and named rather than discovered later: `compute` carries no
boundary.** A total computed from two bounded operands comes out unbounded, so
arithmetic is where a scope declaration is still lost. It is not the same rule
as inheriting a grade — two operands taken over different sets produce a result
over neither — and it is its own decision rather than a wiring gap._

_**Open beside it: income narrowed by a currency can record its narrowing
nowhere.** On a vault whose accounts declare more than one currency, the income
read groups under a key that matches no currency a `currency` filter may name,
so narrowing it by a currency the vault does hold comes back `ok` with no
figures at all — and a read that emits no figure records what narrowed it in no
figure. That much is a read saying too little. The second symptom on the same
vault is not: the placeholder key is also what the figure declares as its
currency, so an unnarrowed income read renders `? 500.00` to a person. The
cause of both is upstream of the tools, in how an income bucket with no
currency of its own is attributed. Deferred rather than repaired here, so the
scope check meets it as a known thing._

_**Open, and older than this cycle: a date is checked structurally, in ASCII
only by accident.** `_is_iso_date` tests its digits with `str.isdigit`, and the
month parse this cycle added tests its own with `int`; both accept non-ASCII
decimal digits, and `int` accepts a leading sign as well. So a stored key of
Arabic-Indic digits passes as a calendar month and a person could read a scope
sentence built from a string nothing validated. It is **I2's** business —
normalization is locale-aware, versioned and deterministic — rather than this
read's, since the same acceptance sits under every date the tools compare.
Named here because the month parse is where it now shows._

_**No version id is claimed by this cycle.** The ten narrowing sentences are
already in the pack in force, the block guard's refusal has a reviewed sentence
already, and the cap sentence is computed text of the kind the spending read
already writes beside its own cap. Nothing model-facing changed._

---

_Amended 2026-08-17 (a grade is placed, not asked for). **How well an answer is
stood behind is the third property of a figure the machine holds, and now the
third it places.** Caveats went that way on 2026-08-09 and a figure's scope the
day after; a grade had the identical shape and had not. Until this cycle the
answer-level grade — the weakest among every money figure an answer stated — was
computed, travelled out on the result, reached the transcript and the developer's
console, and **was in no sentence a person read**. The only route by which a
strength word reached anybody was a `grade` hole a model had to author before it
had read anything, so whether uncertainty was visible at all was a bet a model
made in ignorance. That is what the three instances share, and it is the sentence
a fourth reader should find before reinventing the question: **a property of a
figure that the machine holds is placed by the machine, never asked for through a
hole.**_

_**What replaced it.** `grade` is no longer a type a hole may declare. Its branch
in the binding gate, its entry in the table pairing a hole's type to the one kind
of reference it may hold, and the renderer that wrote the ladder's word are all
deleted, and with them the `ungraded_figure` refusal and the phrase that named a
missing grade as a gap; the tag vocabulary drops to nineteen. The runner states
the grade of what the answer stated in **one whole reviewed sentence per word on
the ladder** — never a frame with a machine's word dropped into a model's, which
is what three of the four grade-wording defects the sweep found were made of. It
lands after the boundary sentences and before the caveats: scope, then strength,
then what the claim does not cover, because a confidence word heard before a
claim's extent invites reading it as wider than it is. Where nothing stated
carries a grade, nothing is said._

_**The computation set and the placement condition are two questions, and
separating them is what makes the two sentences safe to read together.** The
answer's word is computed over **every** money figure it stated, lines of a block
included; the sentence is placed only where at least one of them was stated as a
number in a sentence rather than only as a line of a block. Both facts come off
the binding registry — which slot type a reference filled — and neither reads the
shape of a payload. The earlier reasoning that a block "has already said its own
grade, the same rule as scope" is **reversed**: two scopes are two facts, but a
set's grade and its superset's grade **compose**. Excluding the block's lines
produced two adjacent sentences over disjoint sets that a person could read as
disagreeing, and the dangerous direction — a strong trailing line under a weak
block — was unreachable by any fixture in the repo, so wording alone would have
left it live and untested. Nested rather than disjoint, the outer sentence is
weaker than or equal to the inner by construction, and the word a person hears is
the word `result.grade` carries._

_**And four counts of the agent's own paperwork stopped being claims about
money.** `check_completeness` emitted documents held, documents posted, documents
awaiting review and counterparties with no category yet as financial figures with
no grade — the exact shape `ungraded_figure` existed to refuse, so whether a
person got a correct count or a refusal turned on whether a model had reserved a
place for a grade that did not exist. All four now declare `activity`, and the
words describing that kind widen from what the agent *did* to what it did or
holds on record. The test that sorts a count is the durable one: **what would a
wrong number here move?** If it moves a figure about the person's money the count
is financial and carries a grade; if it moves only the account the agent gives of
its own records, it is activity and carries none. `months these movements span`
is the divisor of a monthly average and stays financial by that test; `documents
awaiting review` moves nothing, because the money consequence of an unposted
document is already carried on every money figure's own boundary. Two
consequences: an empty vault can say it holds nothing, where a financial zero
citing no record refused the whole answer; and a document count can no longer be
divided into a spending total, which the arithmetic refuses as a number that
would be a claim of neither kind._

_**The tier summary leaves the completeness payload and the figure is renamed.**
One result carried two counts of counterparties awaiting attention over different
sets — the tier read skips instruments, peers and unshareable descriptors and
falls back to a raw descriptor, while the completeness read counts every
counterparty with no category and skips movements with no merchant key — so each
can exceed the other and both are correct. A model reading two irreconcilable
numbers in one payload is a defect whichever is right, so only one reaches it
now, and *counterparties not yet identified* becomes *counterparties with no
category yet*, which is what it counts. **This reconciles the presentation and
not the measurements**; what the queue owes is its own question._

_**What stays open**, narrowed rather than closed: nothing stops a model typing
the word "verified" into the literal text of its own clause. Nothing reads those
words, by design and permanently — a forbidden-word list is a standing anti-goal.
Two things narrow it. The clause is authored before any read, so such a model is
betting on a grade it has not seen; and the machine's own sentence is now in the
same answer to contradict it when the bet was wrong. Beside it, `figure()` still
accepts a money-kind figure with no grade. No emitter produces one, and now that
the answer's sentence claims something of "every figure in it", the fix when it
comes is structural at the emitter rather than a check at the speaking end._

_**Five families moved.** `speak-shape-v9` drops the grade from the types a hole
may declare; `speak-final-v12` drops it from what a figure reference may fill;
`speak-v11` rewrites the paragraph that taught the hole to mirror the caveat
paragraph beneath it, keeping what a model still needs a grade *for*, which is
judging whether to state a figure at all; `pack-v12` carries two families of four
reviewed lines, one naming the answer and one naming the list, each paired
against the ladder in both directions, and drops the refusal sentence for an
ungraded figure and the phrase for a missing grade; `tools-v12` stops saying
`check_completeness` counts "how many counterparties are still unidentified".
`speak-shape-v8`, `speak-final-v11`, `speak-v10`, `pack-v11` and `tools-v11` were
in force until this cycle._

---

_Amended 2026-08-18 (a hole declares what its number is a number of). **A
boundary reached the check, and not only the disclosure.** Since 2026-08-10 a
figure has declared what set it was taken over, and until now that declaration
was read by the sentences the run places beside a number and by nothing else: a
total narrowed to one counterparty and a total over the whole ledger both said
`spending`, so a real number could be spoken as a claim about something else
with every guard on the answering path satisfied. The general form is the
sentence to carry forward: **a figure declares what it measured and what set it
was taken over, and a sentence is checked against both — the first stops a
number meaning something else, and only the second stops it being about
something else.**_

_**A cut is a set of axes rather than one slice.** A figure declares every axis
it is the intersection of — what narrowed the read it came from, plus the slice
of what came back that it is — so a counterparty's total declares one axis and
its groceries group declares two, and the two are told apart by what their
emitters wrote down rather than by anything inspecting a payload. An axis is
named once, since two values of one axis offered as one set describe no single
set; the entries are sorted by axis in the constructor, so one set has one
written form wherever two boundaries are compared with `==`. A read narrowed on
the same axis it groups by therefore has no list in it, and `_line_of` says so
directly: a figure is a line of its read where its cut set is the read's
narrowing plus **exactly one** further axis._

_**The substrate that check needed.** Every figure every read emits now declares
a set: `check_completeness`'s counts and `get_provenance`'s figures declare the
whole, per-account balances and net-worth per-account lines name the account
they are of, and a net-worth part in one of several currencies names its
currency and declares whole only on a vault holding one. **A per-holding figure
names no slice**, because a holding is *in* an account rather than a slice of
one and no member of the narrowing vocabulary names an instrument. `compute`
composes the declaration instead of losing it — identical operand boundaries are
inherited, differing ones produce a number over neither set, a literal
contributes no set and takes none away, and a value the person supposed declares
itself over no nameable set — which closes the open item the 2026-08-17
amendment named. A counterparty is named by its key everywhere, so what a read
says it spoke about and what a figure declares its slice as are one string; a
movement's own description stays on the row a person reads. And a month group of
a windowed read declares that month **intersected with the window**, from the
two declarations already in the code, so a read asked for the 15th onward no
longer labels its group with a month that starts on the 1st._

_**What it costs, and every piece of it is deliberate.** A holding's value is
unspeakable, as a row and as a number — per-instrument only; the holdings read's
own total and its total narrowed to one account still answer — and the successor
is chartered as its own item, *what a holding is a slice of*, after the
reachability and wording items. A figure over two disagreeing operands can be
stated as neither a whole nor a slice. A monthly average computed over one span
and spoken under another refuses rather than answering, because the span a
figure's operands were measured over is a third object nothing in this product
computes: it is neither the coverage a document attests nor the window a read
was asked for, and restoring the answer needs a decision about where a measured
extent lives on a figure. Beside it, *what a count is a count of* is chartered:
a count of things found cites only what it found, so a count of none cites
nothing and refuses at the citation gate._

_**Open, and named rather than discovered later.** The **value** of a period is
unchecked — the vocabulary holds no entity for a span, so what the check
compares is the axes and only the axes, and a sentence naming the wrong window
binds a figure cut by `period` as happily as the right one. The words a model
writes around a hole are still read by nobody, so a clause may name a slice in
its own literal text, declare the whole, bind a real total and pass. And two
things are now dead weight rather than mechanism: `check_completeness`'s
per-account date figures, which can fill no hole and are kept exactly as they
are, and the run-wide pool of days the runner still records at two sites and
reads nowhere, now that a day is bound from a figure the same clause states._

_**Four families moved.** `speak-shape-v10` teaches the scope declaration and
the set it takes; `speak-repairs-v3` carries a line per new repair;
`speak-final-v13` corrects what a block of rows is and states the scope sibling
of the quantity sentence, so a model is told what will happen rather than
reaching; `pack-v13` carries the two reviewed refusals, one for a figure taken
over a different set and one for a figure of a different thing, since the repair
differs — so the tag vocabulary goes from nineteen to **twenty-one**, and four
new repairs bring those to twenty-three. `speak-shape-v9`, `speak-repairs-v2`, `speak-final-v12` and `pack-v12`
were in force until this cycle. No tools version is claimed: nothing about what
a read is asked for changed._
