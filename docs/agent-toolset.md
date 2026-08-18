# Agent Toolset — the thirteen verbs Viva may ever use

**State:** partial
**Rules:** PROJ-13, PROJ-14, PROJ-15, PROJ-16, PROJ-17, PROJ-18, PROJ-25

## Rules

### PROJ-13 — the verb set does not depend on what the vault holds
**State:** enforced
**Code:** product/viva/tools/__init__.py:31
**Test:** product/tests/test_docs_track_the_code.py::test_the_registered_tool_count_is_whatever_the_registry_holds

1. Building the registry reads nothing from the projection.
2. Adding an account, a card, a policy, a loan, a document type or a household member adds no verb.

### PROJ-14 — no registered verb touches the network
**State:** by-review
**Code:** product/viva/tools/registry.py:141
**Test:** none

1. A tool that does not declare itself local-only cannot be registered.
2. No registered verb opens a socket, and none moves money or contacts an institution.
3. The model call is the only network egress the product makes.

### PROJ-15 — every figure in an answer is a tool result, cited by id
**State:** enforced
**Code:** product/viva/tools/runner.py:1375
**Test:** product/tests/test_tools.py::test_a_number_no_tool_returned_is_refused

1. A number no tool emitted has no id, so it cannot be cited and cannot be said.
2. A money-kind figure citing no record is refused before the answer is delivered.
3. The check runs in code, outside the invocation modality, identically for every planner.

### PROJ-16 — no registered verb writes
**State:** by-review
**Code:** product/viva/tools/__init__.py:31
**Test:** none

1. Every registered verb is a read.
2. The write direction produces a Proposal that deterministic writers apply after an explicit confirmation; it takes no tool.

### PROJ-17 — a read's requirement is in the schema the model is shown
**State:** enforced
**Code:** product/viva/tools/ledger_tools.py:744
**Test:** product/tests/test_tools.py::test_the_detailed_read_declares_in_its_schema_that_it_takes_filters

1. `list_movements` declares `filters` required in its own schema, so a call naming nothing is refused where arguments are validated rather than after the read is entered.
2. A filter a read honours but that does not narrow it — `currency` on the detailed read — is named in the description as the trap it is.

### PROJ-18 — totals and rows are two verbs
**State:** enforced
**Code:** product/viva/tools/ledger_tools.py:1602, product/viva/tools/ledger_tools.py:777
**Test:** product/tests/test_tools.py::test_the_transactions_read_returns_totals_and_no_rows

1. `query_ledger` answers in totals and returns no rows.
2. `list_movements` returns the rows, and refuses a call naming none of account, category, merchant, tag or window.
3. `list_movements` emits one count figure over the whole matching set, and a capped list says how many of how many it showed.

### PROJ-25 — the model is told what day it is
**State:** enforced
**Code:** product/viva/speak.py:161
**Test:** product/tests/test_speak.py::test_the_day_a_turn_is_asked_on_reaches_the_model

1. The system message carries today's date as a template field of the pinned persona file.
2. Being told the date does not license stating it: a date reaches a person only through a hole bound to a figure the same clause states.

Registry membership, the structured filter contract, the modality-neutral
invocation contract and the result envelope are PROJ-61, PROJ-62, PROJ-63 and PROJ-64 in
[projection-decomposition-and-the-tool-registry.md](projection-decomposition-and-the-tool-registry.md).
What `check_completeness` answers for is PROJ-24 in
[knowledge-and-expectations.md](knowledge-and-expectations.md).

## Why

**Tools scale with verbs, not with nouns.** Accounts, cards, policies and loans
are rows in the ledger; document types are entries in the corpus; household
members are tags in the taxonomy. A toolset that grew per account-type would be
the per-institution-parser mistake reborn one layer up. The stress-test persona
this document was written against — a 45-year-old with a spouse, a son, a
mortgaged house, a 401(k), a stock portfolio, three bank accounts, five cards,
five policies, two cars and three loans — needs **thirteen** verbs, and adding a
rental property, another child or a fourth loan adds none.

Two counts live in this file and must be kept apart. **Thirteen** is the
design-intent verb set. **Six** is what the registry holds, which is derived by
running the code.

### Reading the ledger

| Tool | What it answers |
|---|---|
| `query_ledger(filter, group_by, window)` | The workhorse: balances, holdings, aggregations by account, category, tag or time, and the vault's own vocabulary. Net worth, where money went, spending on our son this year, mortgage interest paid, card balances, 401(k) allocation. |
| `list_movements(filter, window)` | The rows behind a total, behind a mandatory narrowing filter — the workhorse's other half, split out so a total never drags its transactions along. |
| `list_obligations(horizon)` | Forward-looking: bills due, minimum payments, premiums, renewal dates. |
| `find_patterns(kind)` | Recurring charges, subscription creep, fee drift, anomalies — deterministic detection over the ledger, not model musing. |
| `check_completeness()` | Coverage: how current each account is, what is captured, posted or awaiting review, and which counterparties have no category. The honesty input for every other answer. |

### Reading the documents

| Tool | What it answers |
|---|---|
| `search_documents(query, scope)` | The one verb the complex household adds, and insurance is why: *are we covered if the teenager dents the car?* is a provision, not a number. Verified passages with citations. |

### Deterministic math

| Tool | What it answers |
|---|---|
| `compute(expression, inputs)` | Exact Decimal arithmetic over other tools' outputs. The model never adds two numbers itself (ADR-010). |
| `project(scenario)` | The financial-math library: amortization, compounding, avalanche versus snowball, affordability what-ifs. Pure formulas, every assumption enumerated. |

### Memory

| Tool | What it does |
|---|---|
| `recall(topic)` | Preferences, goals, prior corrections, household context. Read-only over memory projections. |
| `remember(fact)` | Writes a goal or preference as an event — visible, editable, revocable. |
| `correct(target, fix)` | Category fixes and figure disputes, as events, attributed to the model version that erred. |

### Trust meta

| Tool | What it answers |
|---|---|
| `get_provenance(record_id)` | Figure → source document → exact region. Powers tap-the-number, and answers *why do you say that?* |
| `get_transparency(question)` | What left my machine; why was this model trusted with that document. Reads the outbound and autonomy ledgers. |

**The forbidden list is what makes it safe to hand over your finances.** No tool
moves money or talks to any institution — Phase 3 "actions" will be drafts
presented for explicit yes, executed by the human or a separately-gated
mechanism. No tool touches the network; every verb operates on local state.
Writes are events. "Nothing irreversible without your explicit yes" is thereby
*structural*: there is no tool with which Viva could be tricked, or
prompt-injected, into doing damage. And every figure in every answer is a tool
result with a record id — T1 enforced in code, not in a prompt.

The stress test is chains, not verbs. *Can we afford the $8K vacation in
December?* is `query_ledger` for liquid funds plus `list_obligations` through
December, then `compute`, with the answer inheriting the weakest grade. *Which
loan do I kill first?* is `query_ledger` for balances and rates plus
`search_documents` for prepayment terms, then `project`. *Mortgage interest for
taxes?* is `query_ledger` plus `check_completeness` — the completeness check is
what makes the answer trustworthy for a tax return.

Two consequences worth keeping. `query_ledger`'s query language is the data
model's public face, which is why it is a structured filter object rather than a
DSL. And tool count is expected to stay at or below about fifteen through Phase
2: pressure to add a verb is treated as a signal that either the data model or
an existing verb is incomplete. That is the review test.

The verb set holds. What has moved is the honesty machinery around it: figures
have identities, a shape is committed before any read, and a refusal is a
reviewed sentence. Widening what may be *said* has never widened what may be
*asserted as money*.

Invariants this leans on: T1 (every answer figure is a cited tool result), T2
(compute and project are deterministic; no arithmetic in the model), T4 (all
writes are events), T6 (no tool touches the network), X3 (irreversibility
structurally impossible).

## Open

- Seven of the thirteen verbs exist in no registered form. `find_patterns` has
  its machinery built and unexposed — rhythm hypotheses and stream building,
  with a CLI report and three consumers — and begins life as a named projection
  through `query_ledger` rather than as a verb. `list_obligations` is half-built:
  a cadence and a last occurrence exist per stream, and nothing computes a next
  expected date or amount; how sure a rhythm must be before a bill is called
  *due* is a design question, not missing machinery. `search_documents` is
  blocked at the data layer: originals are stored content-addressed, there is no
  text index, and what is captured per document is the model's response text
  rather than the document's own. `project`, `recall`, `remember` and `correct`
  have nothing underneath them at all.
- `remember` and `correct` are write verbs in a document that also says the
  write direction takes no tools. Either the count narrows to eleven read verbs
  or those two are something other than tools. Unruled: it is a decision, not a
  tidy-up, and the count stays thirteen until it is taken.
- Whether a slot can be filled at all is not computed from the registry before a
  call is made. `{document}` is a declared slot type that no tool emits.
- The `vocabulary` mode's count carries no grade and no record ids, so *why do
  you say five?* comes back with nothing, and it is declared `activity` — which
  is not what a count of the person's own labels is.
- The draft-and-approve mechanism for Phase 3 actions lives outside this toolset
  by design; its shape is a capability-model question.
- Every capability recorded here is proven mechanically and lightly exercised
  against real data. Read the built ones as working in the suite and unproven in
  a real sitting.
