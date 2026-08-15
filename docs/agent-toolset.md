# Agent Toolset — the thirteen verbs Viva may ever use

**Status:** Design; **the read verbs are built and a model can now call them** — the registry implements `query_ledger`, `list_movements`, `check_completeness`, `get_provenance`, `get_transparency` and `compute` in `viva/tools/`, per [projection-decomposition-and-the-tool-registry.md](projection-decomposition-and-the-tool-registry.md), and the conversation loop above them exists: provider adapters (native tool-calling for every OpenAI-compatible endpoint, a text protocol for any other model), a planner that composes from tool results behind the citation gate, and `viva.speak` as the entrypoint. The remaining verbs await their machinery. · **Last updated:** 2026-08-06 · **Origin question (a stress test):** a 45-year-old with a spouse, a son, a mortgaged house, 401(k), stock portfolio, 3 bank accounts, 5 credit cards, 5 insurance policies, 2 cars, 3 loans: how many tools until Viva can answer any expected question?
**Invariants touched:** T1 (every answer figure is a cited tool result), T2 (compute/project are deterministic; no arithmetic in the model), T4 (all writes are events), T6 (no tool touches the network), X3 (irreversibility structurally impossible — no tool can do anything irreversible)

## The scaling law

**Tools scale with verbs, not with nouns.** Accounts, cards, policies, and loans are rows in the ledger; document types are entries in the corpus; household members are tags in the taxonomy. A toolset that grew per account-type would be the per-institution-parser mistake reborn one layer up. The stress-test persona — a genuinely complex household — needs exactly **thirteen tools** — twelve until the workhorse split of 2026-08-04, see the amendment below — and adding a rental property, another child, or a fourth loan adds zero more.

_**Corrected 2026-08-14.** Six sentences in this file said twelve while its own section headings summed to thirteen. The split registered `list_movements` as a verb in its own right and the *Reading the ledger* heading went from (4) to (5); the prose totals did not follow, and five other documents had copied the number. Note the two counts this file carries and keep them apart: **thirteen** is the design-intent verb set, seven of whose members exist in no code at all, and **six** is what the registry holds — that one is derived by running the code and has never drifted._

## The thirteen

### Reading the ledger (5)

| Tool | What it answers |
|---|---|
| `query_ledger(filter, group_by, window)` | The workhorse (~70% of questions): balances, transactions, holdings, aggregations by account/category/tag/time. Net worth, "where did money go," "spending on our son this year," "mortgage interest paid in 2025," card balances, 401(k) allocation. Every returned figure carries its verification grade and record ID. |
| `list_obligations(horizon)` | Forward-looking: bills due, minimum payments, premiums, renewal dates. "What's due in the next two weeks?" |
| `find_patterns(kind)` | Recurring charges, subscription creep, fee drift, anomalies — deterministic pattern detection over the ledger, not model musing. |
| `list_movements(filter, window)` | The rows behind a total, behind a mandatory narrowing filter — the workhorse's other half, split out so a total never drags its transactions along. |
| `check_completeness()` | Coverage map: how current each account is, what is captured, posted or awaiting review, and which counterparties are unidentified. _(It does **not** report which statements are missing — that is the expectations engine's job, and it reaches a person only as a queue question. Corrected 2026-08-14.)_ "Is my picture up to date?" — and the honesty input for every other answer ("...but May brokerage is missing"). |

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

> _Amended 2026-07-25: this doc describes the **read** direction (Viva answering). The **write** direction — rulings in your own words — needs no tools at all: it produces a **Proposal** that deterministic writers apply after confirmation. The toolset becomes an explicit registry only when Slice 9 starts; formalizing ~40 projection methods before then would be abstraction ahead of evidence. See [viva-listens-and-speaks.md](viva-listens-and-speaks.md)._

## The forbidden list (what makes it safe to hand over your finances)

- **No tool moves money or talks to any institution.** Phase 3 "actions" will be *drafts* presented for explicit yes — and even then executed by the human or a separately-gated mechanism, never by this toolset.
- **No tool touches the network.** All thirteen operate on local state (ledger, document store, memory, logs). The only network egress in the entire system is the model call itself and the 32-byte anchor — both outside the toolset. _(Noted 2026-08-14: the anchor is decided and **unbuilt** — no chain head has ever been anchored. See ADR-004's amendment. Today the model call is the only egress there is.)_
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

- The agent runtime is now specifiable: one planner (the conversation model), thirteen typed tools, a composer that refuses uncited figures. Tool *schemas* become part of the v0 architecture doc.
- `query_ledger`'s query language (safe, structured — not raw SQL from a model) is a design task of its own; it is the data model's public face (A1/A7 now joined).
- `project`'s formula library is verify/-grade code: deterministic, ferociously tested, assumptions-explicit.
- `search_documents` needs the document store to index verified extractions *and* raw text — a requirement flowing back into the pipeline design.
- Tool count is expected to stay ≤ ~15 through Phase 2; pressure to add a tool is treated as a signal that either the data model or an existing verb is incomplete (the scaling law is the review test).

## Open questions

- ~~The `query_ledger` query language shape (structured filters vs constrained DSL)~~ — **settled 2026-08-01: a structured filter object**, every value validated against the vault's own learned vocabulary and refused with the known values named. See [projection-decomposition-and-the-tool-registry.md](projection-decomposition-and-the-tool-registry.md), D3.
- ~~Whether `find_patterns` and `list_obligations` are true tools or named projections exposed through `query_ledger`~~ — **settled 2026-08-01: neither is in registry v1**; when their machinery exists they begin as named projections through `query_ledger` and are promoted to verbs only if their argument shapes refuse to fit (D2, same doc).
- Phase 3 preview: the draft-and-approve mechanism for actions lives *outside* this toolset by design — its shape is a B6 (capability model) question, not a toolset question.

> _Amended 2026-08-01: the invocation modality — how a model's intention becomes
> a tool call — is settled as a **modality-neutral contract**: the registry
> defines schemas, envelope and refusal semantics; the model adapter chooses the
> wire format (native tool-calling first, text protocol as degradation), so the
> choice is reversible per model rather than a global bet. The composer's T1
> gate — refuse any figure without a record id — runs in code, outside the
> modality, in `viva/tools/runner.py`. Tool descriptions are a versioned,
> digest-pinned prompt file (`tools-v1`), never Python literals._

> _Amended again 2026-08-01, after both modalities were built: the gate also
> refuses **echoes**. A refusal envelope grounds nothing; a number that entered
> the run through the planner's own tool-call arguments grounds nothing until a
> result carries it independently; record ids that merely pass through a tool
> (`compute` declares this on its spec) never join the citation pool; and ISO
> dates travel as whole tokens, so a window filter cannot taint the dated rows
> it returns. Known residual, deferred to the structured-answers decision: a
> deliberately constructed derivation through `compute` can still ground a
> fabricated figure, and a figure's grade is caller-declared, unvalidated. Both
halves are closed in the 2026-08-05 amendment below._

> _Amended again 2026-08-04, after the availability cycle. **The workhorse split
> in two.** `query_ledger` answers in totals and returns no rows; the individual
> movements are `list_movements`, which refuses any call naming none of account,
> category, merchant, tag or window — so a read that could return the whole
> ledger cannot be called without narrowing it first. Six verbs are registered,
> and the descriptions file was `tools-v2` at this point (`tools-v5` since the
> amendment below).
>
> **The residual above is half closed.** Every number a tool asserts is now a
> figure with an id; an answer cites ids rather than restating values; and
> `compute`'s operands are figure ids or values the person stipulated in this
> turn's question, never a decimal the model typed. So a grade is inherited from
> the operands rather than declared by the caller, and a value resting on a
> supposition stays `hypothetical` through every later hop. What stayed open was
> a magnitude written into `compute`'s *expression* string rather than passed as
> an operand: `balance + 987654` came back wearing the balance's document and
> grade. That is closed in the amendment below.
>
> **Two shapes of honesty were added beside the gate:** every read declares what
> it is attested for, per account; and a refused turn is spoken in Viva's voice
> by the same model, checked by the same number rule as an answer, with the
> machine's blunt sentence standing if that composition fails._

> _Amended again 2026-08-05, after the two-axis cycle. **A figure answers two
> questions separately.** What it rests on is `grade` and `record_ids`; how its
> arithmetic came out is `exactness`, which carries no evidentiary meaning and
> never moves a grade. Asking one property both questions is what produced the
> two residuals above at once.
>
> **The fabrication residual is closed.** In `compute`, multiplying or dividing
> by a bare magnitude changes the units and preserves attestation; adding or
> subtracting one injects a quantity nothing measured, so a total with any
> unattested term stands on no record and carries no grade. `computed` remains a
> money kind, so the existing gate refuses such a figure rather than delivering
> it. **A grade is no longer merely inherited but validated** — a value off the
> ladder raises where the figure is written, rather than travelling as a
> strength claim that composition ignores; an unrecognised exactness raises in
> the same place.
>
> **Every figure now says what it measures.** An amount states its currency, a
> count states none, and nothing states a null — which is what lets the
> arithmetic tell money from a plain number, refuse `money × money` and return
> `money ÷ money` as a ratio in no currency. A quiet window is still an amount:
> zero *of a currency*, resting on the accounts whose statements answer for the
> period.
>
> **An inexact result is delivered, not refused.** A division that does not
> terminate returns a figure marked rounded, and the runner attaches an approx
> term to any bare statement of its value after the model has spoken, so the
> hedge is not something the model can drop. Money is written at hundredths; a
> dimensionless value is written to significant figures, because a fixed decimal
> scale can write a nonzero ratio as `0.00` and a significant-figures rule
> cannot. Six verbs are registered, and the descriptions file was `tools-v5` at
> this point (`tools-v6` since the amendment below).
> Recorded and not fixed: the term is attached by insertion and mangles known
> sentence shapes (`$approx 85.71`); see the TODO and the closing sections of
> [projection-decomposition-and-the-tool-registry.md](projection-decomposition-and-the-tool-registry.md)._

> _Amended again 2026-08-06, after the first acceptance run against the real
> vault. It answered 6 of 11 with no number wrong: every failure was a correct,
> grounded sentence the gate would not release. **A name and a date are not
> magnitudes**, and the gate had no way to tell one from a digit string, so an
> account's own last four refused the answer that named it and a fifty-row
> listing needed fifty date declarations to be speakable.
>
> **The run's ledger now holds names and dates, not only figures.** A read that
> speaks about an account returns the names it used — the id, and the masked
> form of the number — and the gate blanks a whole name out of the answer
> before counting numbers, the way it already did for figure ids. A name is
> licensed whole and only whole, so the masked form says which account while
> the bare digits inside it stay unsayable; a name that is itself a quantity
> licenses nothing. A date some result carries needs no declaring, because
> declaring one the run already held was a ceremony that admitted everything it
> was shown; a date no result carries must still be declared and must fall
> inside an attested period. **A summary also states how many months it spans**,
> as a citable figure, so a per-period average has a divisor at all.
>
> T1 is untouched: this widened what may be *said*, never what may be asserted
> as money. Six verbs are registered, and the descriptions file is `tools-v6`.
> Recorded and not fixed: a movement's description may carry digits of its own,
> so listing descriptions is still refused._

> _Amended again 2026-08-07, after the second acceptance run and the shape
> cycle. **The gate the three amendments above describe is deleted.** It
> answered 5 of 9 answerable questions and spent 67% of the run's budget on
> refusals, every one of them triggered by a date or an identifier token and
> none by a bad figure. A whitelist over free-form language had taken five
> cycles of new rules without closing.
>
> **A model now writes no digits at all, in either direction.** An answer is a
> shape — clauses of literal words with typed holes — committed before any tool
> is on the table, so a claim cannot be tailored to a figure that turned up. A
> clause whose own words carry a digit is rejected before a read happens. The
> holes are then filled by references into the run's ledger, and one renderer
> turns each reference into words. Nothing inspects the sentence.
>
> **Every figure declares what it measures**, from the closed vocabulary in
> `viva/quantity.py`, and every hole holding a magnitude declares what it is
> asking for. Code compares the two declarations, so a gross sum of postings
> cannot be spoken as spending. ADR-010 is untouched: no model checks a model.
>
> **A refusal is a reviewed pack sentence chosen by machine tag** — no
> composition, no call, no binding. The thirteen verbs are unchanged; six are
> registered; the descriptions file was `tools-v7` at this point (`tools-v8`
> since the 2026-08-09/-10 cycles recorded in
> [projection-decomposition-and-the-tool-registry.md](projection-decomposition-and-the-tool-registry.md),
> and **`tools-v9` since 2026-08-15**, which teaches that an account someone
> owes on is measured as `owed` rather than as `balance` — see
> [net-worth.md](net-worth.md)).
>
> Recorded and not fixed: whether a slot can be filled at all is still not
> computed from the registry before a call is made, which is where the refused
> spend was supposed to go. `{document}` is a declared slot type that no tool
> emits. And none of this has met real data — the Witness runs next._
