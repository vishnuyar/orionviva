# Agent Toolset — the twelve verbs Viva may ever use

**Status:** Draft · **Last updated:** 2026-07-20 · **Origin question (a stress test):** a 45-year-old with a spouse, a son, a mortgaged house, 401(k), stock portfolio, 3 bank accounts, 5 credit cards, 5 insurance policies, 2 cars, 3 loans: how many tools until Viva can answer any expected question?
**Invariants touched:** T1 (every answer figure is a cited tool result), T2 (compute/project are deterministic; no arithmetic in the model), T4 (all writes are events), T6 (no tool touches the network), X3 (irreversibility structurally impossible — no tool can do anything irreversible)

## The scaling law

**Tools scale with verbs, not with nouns.** Accounts, cards, policies, and loans are rows in the ledger; document types are entries in the corpus; household members are tags in the taxonomy. A toolset that grew per account-type would be the per-institution-parser mistake reborn one layer up. The stress-test persona — a genuinely complex household — needs exactly **twelve tools**, and adding a rental property, another child, or a fourth loan adds zero more.

## The twelve

### Reading the ledger (4)

| Tool | What it answers |
|---|---|
| `query_ledger(filter, group_by, window)` | The workhorse (~70% of questions): balances, transactions, holdings, aggregations by account/category/tag/time. Net worth, "where did money go," "spending on our son this year," "mortgage interest paid in 2025," card balances, 401(k) allocation. Every returned figure carries its verification grade and record ID. |
| `list_obligations(horizon)` | Forward-looking: bills due, minimum payments, premiums, renewal dates. "What's due in the next two weeks?" |
| `find_patterns(kind)` | Recurring charges, subscription creep, fee drift, anomalies — deterministic pattern detection over the ledger, not model musing. |
| `check_completeness()` | Coverage map: which statements are missing, how current each account is. "Is my picture up to date?" — and the honesty input for every other answer ("...but May brokerage is missing"). |

### Reading the documents (1)

| Tool | What it answers |
|---|---|
| `search_documents(query, scope)` | The one verb the complex household adds, and insurance is why: "are we covered if the teenager dents the car?" is a *provision*, not a number. Retrieves verified passages from stored documents with citations (page/region). Also: loan terms, policy conditions, plan rules. |

### Deterministic math (2)

| Tool | What it answers |
|---|---|
| `compute(expression, inputs)` | Exact Decimal arithmetic over other tools' outputs. The model never adds two numbers itself (ADR-010). |
| `project(scenario)` | The financial-math library: amortization ("payoff at +$500/month"), compounding, loan-avalanche vs snowball, affordability what-ifs. Pure formulas; every assumption enumerated in the result and repeated in the answer. |

### Memory (3)

| Tool | What it does |
|---|---|
| `recall(topic)` | Preferences, goals, prior corrections, household context ("the son" → tag). Read-only over memory projections. |
| `remember(fact)` | Writes a goal/preference **as an event** — visible, editable, revocable. |
| `correct(target, fix)` | The correction verb: category fixes, figure disputes — as events, attributed to the model version that erred (trust-policy feedback loop 2). |

### Trust meta (2)

| Tool | What it answers |
|---|---|
| `get_provenance(record_id)` | Figure → source document → exact region. Powers tap-the-number; also Viva's answer to "why do you say that?" |
| `get_transparency(question)` | "What left my machine?" "Why was this model trusted with that document?" — reads the outbound ledger and the autonomy ledger (ADR-006, trust policy). |

## The forbidden list (what makes it safe to hand over your finances)

- **No tool moves money or talks to any institution.** Phase 3 "actions" will be *drafts* presented for explicit yes — and even then executed by the human or a separately-gated mechanism, never by this toolset.
- **No tool touches the network.** All twelve operate on local state (ledger, document store, memory, logs). The only network egress in the entire system is the model call itself and the 32-byte anchor — both outside the toolset.
- **Writes are events, only through the three memory verbs.** Append-only, attributed, reversible by compensating event. "Nothing irreversible without your explicit yes" is thereby *structural* — there is no tool with which Viva could be tricked (or prompt-injected, B2) into doing damage.
- **Every figure in every answer is a tool result with a record ID.** An answer containing a number with no ID fails composition — refused before the user sees it (T1 enforced in code, not prompt).

## Stress-test mapping (persona → chains)

- "What's our net worth and which way is it heading?" → `query_ledger` (positions, history) → `compute` (deltas)
- "Can we afford the $8K vacation in December?" → `query_ledger` (liquid) + `list_obligations` (through December) → `compute` → answer inherits weakest grade
- "Which loan do I kill first?" → `query_ledger` (3 loan balances/rates) + `search_documents` (prepayment terms) → `project` (avalanche vs snowball)
- "Extra $500/month on the mortgage?" → `query_ledger` + `project` (amortization) — assumptions stated
- "Covered if the teenager dents the car?" → `recall` (household: son, cars) → `search_documents` (auto policy, collision/liability provisions) → cited passages, *no interpretation beyond the text without saying so*
- "How much did our son cost us this year?" → `recall` (tag) → `query_ledger` (tag aggregation) — with honesty about tagging coverage
- "Mortgage interest for taxes?" → `query_ledger` (interest line items) + `check_completeness` (all 12 statements present?) — the completeness check is what makes the answer *trustworthy for a tax return*
- "Why do you say $2,542.34?" → `get_provenance` → statement, page, region, grade, checks passed

## Consequences

- The agent runtime is now specifiable: one planner (the conversation model), twelve typed tools, a composer that refuses uncited figures. Tool *schemas* become part of the v0 architecture doc.
- `query_ledger`'s query language (safe, structured — not raw SQL from a model) is a design task of its own; it is the data model's public face (A1/A7 now joined).
- `project`'s formula library is verify/-grade code: deterministic, ferociously tested, assumptions-explicit.
- `search_documents` needs the document store to index verified extractions *and* raw text — a requirement flowing back into the pipeline design.
- Tool count is expected to stay ≤ ~15 through Phase 2; pressure to add a tool is treated as a signal that either the data model or an existing verb is incomplete (the scaling law is the review test).

## Open questions

- The `query_ledger` query language shape (structured filters vs constrained DSL) — architecture phase, with the data model.
- Whether `find_patterns` and `list_obligations` are true tools or named projections exposed through `query_ledger` (implementation detail; the verb count is the interface either way).
- Phase 3 preview: the draft-and-approve mechanism for actions lives *outside* this toolset by design — its shape is a B6 (capability model) question, not a toolset question.
