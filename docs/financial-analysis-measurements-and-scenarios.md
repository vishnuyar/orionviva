# Financial analysis, measurements and scenarios

**State:** implemented; expanded exact-model qualification and retained-vault Witness testing pending.

The model selects a reviewed meaning and supplies quoted parameters. Code chooses the fixed local reads, performs the arithmetic and binds the answer. These local reads do not write a plan, change a category, move money, contact a provider or upload a document. Numerical evidence establishes the source of amounts; it does not require additional evidence for category or treatment labels.

## Reviewed meanings

The original six meanings remain available. The analysis pack adds spending by category, merchant and account; spending comparison; movement search; attributed period income; period surplus; and supported recurring spending. Comparison follows the requested claims: percentage change appears only when requested, uses the signed baseline denominator, and preserves both totals and the absolute change when the baseline is zero; only the undefined percentage is omitted and explained. Movement search preserves the bounded records and distinguishes a fully covered empty population from missing coverage. Attributed income excludes separately disclosed unexplained incoming money. Recurring spending reports the existing observed historical total, with the supported-pattern count and historical sources; it does not normalize that total to a monthly rate.

The measurement and projection pack adds recorded cash, account value history, statement period coverage, known remainder, upcoming obligations and goal progress. The scenario pack adds savings, loan payoff and cash flow. Broad account inventory remains unavailable for runtime model selection.

| Read boundary | Fixed views and limits |
|---|---|
| `read_financial_analysis` | Comparison, movement search, attributed income and spending by account. Other analysis meanings reuse existing reads. |
| `read_account_measurements` | Recorded cash, recorded owed and account value history; at most 50 measurements and 50,000 complete serialized bytes. |
| `read_statement_coverage` | Posted statement intervals and uncovered periods; 5,000 complete serialized bytes. |
| `read_financial_projections` | Known remainder, upcoming obligations and local goal progress; 10,000 complete serialized bytes. |
| `simulate_scenario` | The three reviewed scenarios, at most four summary figures and 24 sampled trajectory rows. |

Oversized or unavailable values refuse with the reviewed explanation. Labels, source details and measurements are not silently truncated. Existing global execution, evidence and figure limits remain in force.

## What recorded measurements establish

Accepted document/source order is resolved before selecting measurement dates. A correction that changes a date removes the superseded observation. Historical currency and financial account kind come from the accepted observation context, rather than current metadata. Incompatible source contexts refuse. History lists recorded dates without interpolation or latest-balance backfill. Every delivered amount includes its actual date.

A brokerage's cash component and its whole account value are different measurements. Whole value needs a complete common-source snapshot and the accepted cash-plus-position identity. Same dates across different documents do not establish that snapshot. The code-owned `measurement_view` on each new measurement prevents whole investment value from supplying a cash scenario. Recorded owed accepts sourced, dated liability measurements; a negative owed credit refuses and genuine zero remains valid.

Statement coverage is an activity claim about held posted statements. It does not prove every transaction occurred or that a snapshot covers a period. Account labels are held names and institutions; canonical boundary identities remain unchanged.

## Projections and local numerical inputs

Known remainder uses the existing current-period arithmetic and issuer-depository eligibility. Every included starting amount must agree with its accepted measurement context. It preserves input dates, grades, ranges, reservations and exclusions. Its future summary figures are hypothetical and carry no bank evidence grade. Lossless exclusion references identify a shared exclusion dictionary; they do not remove exclusion details.

Local goal reservations and contributions that participate in that arithmetic retain their actual stable goal identities and event sources. A paused or currency-changed goal may still have a held reservation deducted from an included balance account. An emitted zero contribution still has its schedule lineage. Unrelated goals and inactive or out-of-horizon schedules are excluded. Missing local lineage or disagreement with the helper's included totals and occurrences refuses the entire projection. Local activity sources do not strengthen bank evidence.

Upcoming obligations filters the helper's held next expectations to the requested horizon. It is not a complete payment calendar and does not generate subsequent recurring occurrences. Outgoing lower and upper movements are signed hypothetical values with each expected date. Recorded goal terms are local activity, while derived contribution or completion estimates are hypothetical. Status and limitation codes retain their structured diagnostics and receive closed human explanations.

## Supported scenario input form

Scenario numerical source validation deliberately supports a bounded whole-question form. After the model selects the family, code checks the complete positive question, unique labelled clauses, currency, units, roles and exact quotes. Code does not classify the family from question keywords. Other wording receives a selected-family request to resubmit the whole scenario; arbitrary natural-language premise extraction is not claimed.

Replace the bracketed phrases, use one three-letter currency code, separate clauses with semicolons and write dates as year-month-day. State each item once. These are templates, not financial advice or assumptions supplied by the agent.

```text
Simulate savings in [currency]: initial amount [currency] [amount]; monthly contribution [currency] [amount]; nominal annual rate [rate] percent; horizon [months] months; opening date [date]

Simulate loan payoff in [currency]: principal [currency] [amount]; monthly payment [currency] [amount]; nominal annual rate [rate] percent; horizon [months] months; first payment date [date]

Simulate cash flow in [currency]: initial amount [currency] [amount]; monthly income [currency] [amount]; monthly outflow [currency] [amount]; one-off outflow [currency] [amount]; one-off at month [month]; horizon [months] months; opening date [date]
```

For a recorded start, replace the `initial amount` clause for savings or cash flow, or the `principal` clause for a loan, with `starting account [held account name]`. The held name must resolve uniquely; the complete starting-account clause is independently checked. A loan requires a liability account. Cash uses recorded cash, including brokerage cash when available, rather than whole investment value. Missing measured starts still lower the requested scenario and refuse the required measurement read; they do not become zero.

A numerical proof quotes its complete role-bearing clause from the current question. The amount, role, sign, unit and percent scale must agree. Conventional grouping commas may be removed; negative zero, exponent notation, nonfinite values, unsupported units, unrelated amounts, duplicate roles, quoted or negated contexts, partial dates and prior-assistant scalars refuse. An explicit opening date at the start or end of a named month and year can derive that calendar edge; an unspecified day cannot. The optional semantic `scenario_family` is confined to compatible scenario assumptions or starting-account ambiguity and never enters legacy AnswerProgram fields.

A standalone follow-up amount, account or date cannot establish the rest of a previous scenario. Resubmit its complete current assumptions. APY, effective annual yield, monthly rates or fee-inclusive APR descriptions require a nominal annual percentage assumption; code does not convert them.

## Calculation conventions and receipts

Money inputs are finite nonnegative decimal strings, with at most 15 integer and six fractional digits. Rates range from zero to 100 percent and horizons from one to 600 months. Each modeled monetary input is normalized once to two decimals with HALF_EVEN rounding. Monthly interest and endpoints are rounded to cents; actual contributions, applied payments and interest are accumulated. Exact quoted and observed raw inputs remain in separate receipts.

Savings contributes at each anchored endpoint and uses nominal annual percent divided by twelve. Final balance and contributed principal are hypothetical balance stocks at the final endpoint; growth is a hypothetical net movement over the opening-to-final period, not attributed income.

Loan start date is its first modeled payment date, after one full modeled monthly interest period. Payments are capped at the remaining debt plus interest. At a positive rate, a positive debt requires a payment exceeding initial modeled monthly interest. At zero rate, a stated zero payment leaves positive debt unchanged, with no positive payments or payoff date. A positive payment rounding to zero while modeled debt is positive refuses. Opening zero has no positive payments and no computed payoff date. Remaining debt is hypothetical owed at the final horizon date. Applied repayments and their explicitly labelled interest component use the new `repayment` quantity over the payment-to-horizon period. Generic arithmetic stock/flow rules are unchanged.

Cash uses stipulated monthly incoming and outgoing money and the required one-off amount and one-based modeled month, even when that amount is zero. It reports final cash, lowest monthly endpoint and the first negative endpoint if any. Within-period shortfalls are not measured. It grants no affordability or spending permission.

Calendar advances preserve the original anchor day and clamp each target month independently. January 31 becomes February 28 or 29, then March 31. Savings and cash begin one month after their opening date. Calendar overflow asks for an opening or first-payment date and horizon that fit the supported calendar. There is no daily accrual, prorating, business-day adjustment, tax, fee, inflation or bank-specific policy assumption.

All scenario summaries remain hypothetical with empty grades. Recorded starting values retain their actual measurement view, account, currency, date, source and grade separately; carrying them to the scenario anchor is hypothetical. The held starting-account quote must resolve uniquely in the bounded complete account catalog to the same canonical account as the measurement; exact held canonical identities remain checkable when name coverage is incomplete. Same-run stamped figure references cannot be supplied by producer scalar aliases. Complete scenario results are limited to 10,000 serialized bytes, including all premise and observed-source receipts; an oversized result asks for whole-scenario resubmission without figures. Sampled trajectories retain final, minimum, payoff and first-negative landmarks as applicable and disclose sampling. Decimal calculation precision and monetary rendering cover the full permitted domain.

## Qualification and source access

The default admission corpus combines the unchanged 73 canonical cases with 50 independently frozen capability cases. Supplemental numerical, role, kind, quantity, currency, date, grade, boundary and source expectations are literal independent contracts, rather than generated calculator oracles. Factory selectors and read days are authenticated: canonical cases use their existing March reference day, while supplemental cases use their fixed February reference day across preflight, registry reads and compiler context. Missing, substituted or omitted supplemental cases cannot qualify the expanded catalog.

The active resources are semantic selection v11, retry v9, semantic schema v8, `answer-program-schema-v3` and tools v25. Earlier prompts and schemas remain immutable. Native packaging includes the exact authenticated new and reused numerical/source authority bytes. The normal authority digest is scoped to declared execution paths; whole-candidate binding remains separate.

Model-free checks do not publish a runtime qualification. A future exact-model run needs a concrete funded plan: 123 initial quality attempts, with the existing two-attempt spending ceiling of 246 calls distinguished from each case's first-attempt quality limit. Existing minimum availability and zero financial-integrity thresholds remain unchanged. No new spending is authorized by this implementation.

The conversation viewer currently links captured documents. Local goal event sources and receipts remain structured data and are not visible clickable receipt entries. That source-viewer work is owner-deferred. Browser receipt reachability, retained-vault Witness testing and inherited browser-host/signing gaps are separate acceptance work; this implementation does not claim them complete.

The public [financial acceptance checks](../acceptance/scenarios/financial-capabilities.md) and [real-document continuation plan](../acceptance/real-document-test.md) define browser observation and source-first retained-vault testing. Their declarations do not substitute for qualification or Witness results.
