# Breaking up the projection — and the tool registry it becomes

**Status:** ✅ Ruled 2026-08-01 (Vishnu accepted every recommendation, D1–D5) · **Built 2026-08-01** — the decomposition, registry v1, the envelope and the runner's citation gate; see *What the build did* at the end. The provider adapters followed the same day (see the closing note). Outstanding: the real-vault run. · **Created:** 2026-08-01 · **Last updated:** 2026-08-06
**Invariants touched:** T1 (every answer figure is a cited tool result), T2/ADR-010 (deterministic math; no arithmetic in the model), T4 (untouched — this brief writes no events), T6 (no tool touches the network), X3 (no tool can do anything irreversible), I5 (code universal, specifics are data), and the standing principle *read side early, write side late*.

---

## 1. The goal, restated

Two asks, one seam.

`projection.py` has grown to **1,564 lines**: one class, roughly sixty public reads (eighty-one methods in the file counting helpers and dataclasses), and about **thirty modules** call into it — the answer path, net worth, the question queue, ingest, enrichment, the maintenance agent, the interview, the web service, and a dozen debug commands. It has become the place every read-side idea lands, which is exactly what *abstract the read side early* predicted would happen — and it is now unwieldy to navigate, review, and test.

At the same time, Slice 9 (Viva speaks) needs the agent's **read tools**, and the projection is where their substance lives. The ask: break the file apart so that the same seams that make it maintainable also define the tools the financial agent calls.

Your third observation is the key to both: **most of these methods are not tools.** They are plumbing — for ingest continuation checks, for the enrichment queue, for the question queue's tiering, for the transfer matcher. The agent-toolset doc's scaling law ("tools scale with verbs, not with nouns") turns out to hold in the code: sixty methods collapse into **four read verbs** plus internals. The decomposition should make that visible in the file layout itself.

## 2. What already exists

- **`docs/agent-toolset.md`** — the twelve verbs, decided at design level, with the forbidden list (no network, no writes outside the three memory verbs, every figure cited). It deferred the registry to Slice 9 — *"formalizing ~40 projection methods before then would be abstraction ahead of evidence."* The evidence has now arrived: the file is unwieldy and the verbs are stable. Its two named open questions (`query_ledger`'s shape; whether `find_patterns` / `list_obligations` are true tools) are D3 and D2 here.
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
`activity` (what the agent itself did, standing on the ledger events that
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
`tools-v6` since the names-and-dates cycle below.

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
