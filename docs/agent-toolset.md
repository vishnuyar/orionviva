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
**Code:** product/viva/tools/runner_binding.py:104 · product/viva/tools/runner_delivery.py:219
**Test:** product/tests/test_answer_program_contracts.py::test_executor_stamps_evidence_then_binder_reuses_the_single_claim_gate

1. A number no tool emitted has no id, so it cannot be cited and cannot be said.
2. A money-kind figure citing no record is refused before the answer is delivered.
3. The check runs in code, outside the invocation modality, identically for every planner.

### PROJ-16 — no registered verb writes
**State:** by-review
**Code:** product/viva/tools/__init__.py:31
**Test:** none

1. Every verb in the executable agent registry is read-only; `compute` reasons
   over returned figures and person-supplied inputs but writes nothing.
2. A proposal and the separately gated operation that may apply it are not
   registry tools. Deterministic writers apply only after the required explicit
   confirmation.
3. Future action execution remains outside this read-tool registry, with one
   allowlisted operation per action so the operation table stays the complete
   readable write surface.

### PROJ-17 — a read's requirement is in the schema the model is shown
**State:** enforced
**Code:** product/viva/tools/ledger_movements.py:229
**Test:** product/tests/test_tool_limits.py::test_the_detailed_read_declares_in_its_schema_that_it_takes_filters

1. `list_movements` declares `filters` required in its own schema, so a call naming nothing is refused where arguments are validated rather than after the read is entered.
2. A filter a read honours but that does not narrow it — `currency` on the detailed read — is named in the description as the trap it is.

### PROJ-18 — totals and rows are two verbs
**State:** enforced
**Code:** product/viva/tools/ledger_vocabulary.py:115, product/viva/tools/ledger_movements.py:262
**Test:** product/tests/test_tool_limits.py::test_the_transactions_read_returns_totals_and_no_rows

1. `query_ledger` answers in totals and returns no rows.
2. `list_movements` returns the rows, and refuses a call naming none of account, category, merchant, tag or window.
3. `list_movements` emits one count figure over the whole matching set, and a capped list says how many of how many it showed.

### PROJ-25 — the model is told what day it is
**State:** enforced
**Code:** product/viva/session.py (`QuestionContext` construction)
**Test:** product/tests/test_answer_program_contracts.py::test_question_context_round_trips_without_financial_results

1. The versioned `QuestionContext` carries today's date to the compiler.
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
running the code. The tables below describe that design vocabulary, not a claim
that every named verb is registered or has product substrate today.

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

**The forbidden list is what makes it safe to hand over your finances.** No
registered read tool moves money, writes a correction, or talks to any
institution. Action execution is outside this registry: a later financial
action is drafted for an explicit yes and then handled by a separately gated,
allowlisted operation or by the person. No tool touches the network; every
registered verb operates on local state. Writes are events. "Nothing
irreversible without your explicit yes" is thereby *structural*: there is no
read tool with which Viva could be tricked, or prompt-injected, into doing
damage. And every figure in every answer is a tool result with a record id — T1
enforced in code, not in a prompt.

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
  deterministic substrate but no verb: streams group counterparty relationships
  by rail and separate their directional flows; rhythm hypotheses measure and
  decompose cadence and amount stability, consult confirmed rhythm rulings, and
  feed the diagnostic report and a supported-recurring-spending mode of
  `query_ledger`. Overview now has a separate grounded obligation and
  quiet-finding projection with expected dates, amount shapes, coverage and the
  due threshold, but neither `find_patterns` nor `list_obligations` is a
  registered agent read. `search_documents` is
  blocked at the data layer: originals are stored content-addressed, there is no
  text index, and what is captured per document is the model's response text
  rather than the document's own. `project`, `recall`, `remember` and `correct`
  have nothing underneath them at all.
- `remember` and `correct` are write verbs in a document that also says the
  executable registry is read-only and action execution belongs outside it.
  Either the design count narrows to eleven read verbs or those two become
  separately gated actions rather than tools. This document records the
  contradiction and does not resolve it; the count stays thirteen until a
  dedicated ruling is taken.
- Whether a slot can be filled at all is not computed from the registry before a
  call is made. `{document}` is a declared slot type that no tool emits.
- The `vocabulary` mode's count carries no grade and no record ids, so *why do
  you say five?* comes back with nothing, and it is declared `activity` — which
  is not what a count of the person's own labels is.
- The general draft-and-confirm mechanism for financial actions does not yet
  exist. It remains outside this read toolset by design; its proposal, policy,
  state re-check, consent, application, and outcome shapes are a later
  capability-model question.
- Every capability recorded here is proven mechanically and lightly exercised
  against real data. Read the built ones as working in the suite and unproven in
  a real sitting.
