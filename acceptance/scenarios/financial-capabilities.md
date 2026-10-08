# Financial analysis, measurements and scenarios

These 20 browser-first checks supplement the original 45 acceptance checks. They are human scenarios, not measured passes or hosted-model qualification. Use disposable synthetic data by default. The separately authorized retained-vault campaign follows [the real-document plan](../real-document-test.md). Shared behavior uses the browser; native checks cover only host boundaries.

## Common prerequisites and independent checks

Prepare independently verified source movements, accepted measurements, statement periods and local goal events before asking. Use explicit dates, one currency at a time and held names. Replace bracketed placeholders; do not submit them literally. A source comparison may supplement the browser but cannot replace the visible journey. Evidence is required for numerical origins only; categories and treatment do not need separate evidence gates. Keep amounts, names, documents, exact replies and screenshots outside the repository.

For each case, check numerical value/sign, actual date or modeled endpoint, account/currency boundary, stock or movement role, source set and weakest applicable grade. Hypothetical outputs have empty evidence grades and retain observed sources separately. Repeat a supported paraphrase, inspect the final delivered answer and record first divergence, not just a transient screen. Record Pass, Fail, Blocked or Not run separately for every ID; a declaration is not a pass.

## GUIDE-007 — Spending by category

**Family:** `spending_by_category`.

**Prerequisites:** Independently source-verified records for this read family, with expected numerical sources, dates and results.

**Actions:** In Ask Viva, ask: “Show spending by category in [currency] from [start] to [end].” Inspect the delivered answer and its numerical sources or scenario receipts through the supported browser controls.

**Pass:** Category rows, total and counted movements agree with source transactions. Own transfers are excluded; category labels require no separate evidence approval.

## GUIDE-008 — Spending by merchant

**Family:** `spending_by_merchant`.

**Prerequisites:** Independently source-verified records for this read family, with expected numerical sources, dates and results.

**Actions:** In Ask Viva, ask: “Show spending by merchant in [currency] from [start] to [end].” Inspect the delivered answer and its numerical sources or scenario receipts through the supported browser controls.

**Pass:** Merchant populations and total agree with source movements, preserving multiplicity and excluding own transfers.

## GUIDE-009 — Spending by account

**Family:** `spending_by_account`.

**Prerequisites:** Independently source-verified records for this read family, with expected numerical sources, dates and results.

**Actions:** In Ask Viva, ask: “Show spending by account in [currency] from [start] to [end].” Inspect the delivered answer and its numerical sources or scenario receipts through the supported browser controls.

**Pass:** Readable held account names identify each population; duplicate names remain disambiguated. Amounts retain canonical account scope.

## GUIDE-010 — Spending comparison

**Family:** `spending_comparison`.

**Prerequisites:** Independently source-verified records for this read family, with expected numerical sources, dates and results.

**Actions:** In Ask Viva, ask: “Compare spending in [currency] from [start] to [end] against [baseline start] to [baseline end], including percentage change.” Inspect the delivered answer and its numerical sources or scenario receipts through the supported browser controls.

**Pass:** Both populations, absolute change and requested percentage agree independently. Signed baseline is retained. With a zero baseline, both totals and absolute change remain available, while percentage is omitted and explicitly explained as undefined.

## GUIDE-011 — Movement search

**Family:** `movement_search`.

**Prerequisites:** Independently source-verified records for this read family, with expected numerical sources, dates and results.

**Actions:** In Ask Viva, ask: “Find movements for [held merchant] in [currency] from [start] to [end].” Inspect the delivered answer and its numerical sources or scenario receipts through the supported browser controls.

**Pass:** Every returned date, amount, account and source agrees with matching source rows. Covered empty results differ from unavailable coverage; truncation or range limits are explicit.

## GUIDE-012 — Attributed period income

**Family:** `period_income`.

**Prerequisites:** Independently source-verified records for this read family, with expected numerical sources, dates and results.

**Actions:** In Ask Viva, ask: “What attributed income is recorded in [currency] from [start] to [end]?” Inspect the delivered answer and its numerical sources or scenario receipts through the supported browser controls.

**Pass:** Attributed income excludes own transfers and separately discloses unexplained incoming money; source totals, dates and currency agree. An unclassified deposit is not silently attributed income.

## GUIDE-013 — Period surplus

**Family:** `period_surplus`.

**Prerequisites:** Independently source-verified records for this read family, with expected numerical sources, dates and results.

**Actions:** In Ask Viva, ask: “What is the surplus in [currency] from [start] to [end]?” Inspect the delivered answer and its numerical sources or scenario receipts through the supported browser controls.

**Pass:** Attributed income less spending agrees with the independent population. Unexplained incoming money and uncovered periods remain disclosed.

## GUIDE-014 — Observed recurring spending

**Family:** `recurring_spending`.

**Prerequisites:** Independently source-verified records for this read family, with expected numerical sources, dates and results.

**Actions:** In Ask Viva, ask: “What costs repeat in my records in [currency]?” Inspect the delivered answer and its numerical sources or scenario receipts through the supported browser controls.

**Pass:** Supported pattern count and observed historical amount agree with recorded occurrences. Historical totals are not presented as normalized monthly rates or guaranteed future bills.

## GUIDE-015 — Recorded cash

**Family:** `recorded_cash`.

**Prerequisites:** Independently source-verified records for this read family, with expected numerical sources, dates and results.

**Actions:** In Ask Viva, ask: “Show recorded cash for [exact held account] in [currency].” Inspect the delivered answer and its numerical sources or scenario receipts through the supported browser controls.

**Pass:** Included dated cash measurements agree with sources. Brokerage cash is distinct from total investment value; uncovered/missing measurements and currencies are not guessed or added together.

## GUIDE-016 — Recorded account history

**Family:** `account_value_history`.

**Prerequisites:** Independently source-verified records for this read family, with expected numerical sources, dates and results.

**Actions:** In Ask Viva, ask: “Show recorded value history for [exact held account] in [currency] from [start] to [end].” Inspect the delivered answer and its numerical sources or scenario receipts through the supported browser controls.

**Pass:** Amounts include actual observation dates and sources, without interpolation or latest-value backfill. Corrected dates replace superseded observations; currency/kind conflicts refuse.

## GUIDE-017 — Held statement coverage

**Family:** `statement_period_coverage`.

**Prerequisites:** Independently source-verified records for this read family, with expected numerical sources, dates and results.

**Actions:** In Ask Viva, ask: “What held statement periods cover [exact held account] from [start] to [end]?” Inspect the delivered answer and its numerical sources or scenario receipts through the supported browser controls.

**Pass:** Covered and uncovered intervals agree with posted statement periods. A snapshot is not transaction coverage; an uncovered interval does not claim an issuer failed to issue a statement.

## GUIDE-018 — Known remainder

**Family:** `known_remainder`.

**Prerequisites:** Independently source-verified records for this read family, with expected numerical sources, dates and results.

**Actions:** In Ask Viva, ask: “Show the known remainder in [currency] for the next [days] days.” Inspect the delivered answer and its numerical sources or scenario receipts through the supported browser controls.

**Pass:** Independent arithmetic includes accepted starting measurements, held reservations and in-horizon contribution schedules with their local event sources. Dates, ranges, stale inputs, exclusions and unknown discretionary spending remain visible; this is no spending permission.

## GUIDE-019 — Upcoming obligations

**Family:** `upcoming_obligations`.

**Prerequisites:** Independently source-verified records for this read family, with expected numerical sources, dates and results.

**Actions:** In Ask Viva, ask: “Show the next expected outgoing payments in [currency] within [days] days.” Inspect the delivered answer and its numerical sources or scenario receipts through the supported browser controls.

**Pass:** Signed outgoing ranges and next expected dates agree with supported historical patterns. The answer explains that it filters held next expectations and is not a complete recurring payment calendar.

## GUIDE-020 — Local goal progress

**Family:** `goal_progress`.

**Prerequisites:** Independently source-verified records for this read family, with expected numerical sources, dates and results.

**Actions:** In Ask Viva, ask: “Show progress on my local goals in [currency].” Inspect the delivered answer and its numerical sources or scenario receipts through the supported browser controls.

**Pass:** Held target, reserve and schedule terms agree with local activity; projections remain hypothetical. A reserve is not a bank transfer. Unsupported or stale schedules have useful limits.

## GUIDE-021 — Savings scenario

**Family:** `savings_scenario`.

**Prerequisites:** Complete explicitly stipulated current assumptions, or a compatible recorded start plus all remaining explicit premises, with independent cents/calendar results.

**Actions:** Replace every bracketed placeholder and submit the complete form below in Ask Viva. Inspect the delivered answer and its numerical sources or scenario receipts through the supported browser controls. For a recorded start, replace the starting monetary clause as described in [the continuation plan](../real-document-test.md).

```text
Simulate savings in [currency]: initial amount [currency] [amount]; monthly contribution [currency] [amount]; nominal annual rate [rate] percent; horizon [months] months; opening date [date]
```

**Pass:** Final balance, contributed principal and growth agree with an independent cents-based calculation and anchored calendar. Growth is a hypothetical net movement; stocks have endpoint dates and sampled trajectory is labelled.

## GUIDE-022 — Loan payoff scenario

**Family:** `loan_payoff_scenario`.

**Prerequisites:** Complete explicitly stipulated current assumptions, or a compatible recorded start plus all remaining explicit premises, with independent cents/calendar results.

**Actions:** Replace every bracketed placeholder and submit the complete form below in Ask Viva. Inspect the delivered answer and its numerical sources or scenario receipts through the supported browser controls. For a recorded start, replace the starting monetary clause as described in [the continuation plan](../real-document-test.md).

```text
Simulate loan payoff in [currency]: principal [currency] [amount]; monthly payment [currency] [amount]; nominal annual rate [rate] percent; horizon [months] months; first payment date [date]
```

**Pass:** Remaining debt, applied repayments, interest component, positive-payment count and payoff date agree independently. Owed stock and repayment flows differ; zero-rate zero-payment debt remains unchanged, and zero principal has no fabricated payoff date.

## GUIDE-023 — Cash-flow scenario

**Family:** `cash_flow_scenario`.

**Prerequisites:** Complete explicitly stipulated current assumptions, or a compatible recorded start plus all remaining explicit premises, with independent cents/calendar results.

**Actions:** Replace every bracketed placeholder and submit the complete form below in Ask Viva. Inspect the delivered answer and its numerical sources or scenario receipts through the supported browser controls. For a recorded start, replace the starting monetary clause as described in [the continuation plan](../real-document-test.md).

```text
Simulate cash flow in [currency]: initial amount [currency] [amount]; monthly income [currency] [amount]; monthly outflow [currency] [amount]; one-off outflow [currency] [amount]; one-off at month [month]; horizon [months] months; opening date [date]
```

**Pass:** Final and minimum monthly endpoint balances and first-negative endpoint agree independently with dates. A monthly endpoint model does not establish within-month shortfalls or affordability.

## GUIDE-024 — Numerical lineage and observed versus hypothetical sources

**Prerequisites:** Source-verified dated bank and brokerage measurements, a liability measurement and a local goal whose reservation/contribution enters the projection.

**Actions:** Inspect recorded cash/history, known remainder and each scenario with a recorded start. Compare numerical receipt sources to the independent source records and local event identities. Compare actual measurement dates with scenario dates.

**Pass:** No source, grade, currency, account or role is silently substituted. Cash is not whole brokerage value and liability credit is not sign-flipped into debt. Local goal numerical inputs retain local event lineage without strengthening bank evidence. Stipulated hypothetical amounts can have no document sources only when authenticated to the complete current question; observed and recorded figures still require their sources. Missing receipt navigation is recorded as a visible failure or owner-deferred limitation, never an assumed pass.

## GUIDE-025 — Useful limits, covered zero and complete scenario resubmission

**Prerequisites:** Independent fixtures for a covered zero population, missing period/start, duplicate held names, incompatible source context, unsupported scenario units and an oversized result.

**Actions:** Ask the answerable zero question and each bounded unsupported question. For each scenario family, omit a required item, use a prior assistant's amount or submit a partial follow-up; inspect the family-specific full form, then resubmit the complete current assumptions. Try an ambiguous starting account and a uniquely identified alternative.

**Pass:** Covered zero stays zero; unavailable information does not become zero. Refusals contain no invented figures or raw internal codes and explain a useful next step. Scenario hints name the selected family, currency, semicolon-separated labels and complete date roles without guessing amounts/rates. No partial or prior-assistant premise is reused. Name guidance resolves uniquely without hiding duplicate accounts. Complete serialized result limits refuse without silently dropping rows, source details or premises.

## GUIDE-026 — Browser receipt legibility and retained-state persistence

**Prerequisites:** Long and duplicate synthetic held names, a supported long-value scenario, source caveats and a supported conversation in one vault.

**Actions:** Inspect all four answer views where offered, source/assumption receipts and sampled trajectory. Navigate by keyboard, resize the browser, reload through the supported flow and revisit the conversation and local plan.

**Pass:** Amounts and dates, source versus scenario roles, names, useful caveats and sampling remain readable without clipping or repeated missing explanations. Supported document links open the named captured source. Receipt availability and any unsupported page/region or local-event viewer are disclosed accurately. Reload preserves supported conversation/plan state without repeating writes or mixing vaults. This does not prove signed installation, native dialogs or another platform.
