# Financial conversation campaign

Run after all 19 documents are processed and reviewed in the current final vault. Replace bracketed phrases with actual covered accounts and periods. Establish source expectations before asking. Record the exact question/answer and verdict privately.

## Inventory, balances and coverage

1. What accounts have I uploaded, and which dates do the statements cover?
2. What is the latest balance in each account? Give the measurement dates.
3. What is the balance of [named account]? Repeat with a unique indirect description.
4. How much cash do I have, and what does that include?
5. How much credit-card debt do I have?
6. What is my net worth based on these documents?
7. Which statements or periods are missing?
8. Which questions still need my review?

Check latest-per-account selection, liability signs, mixed dates, incomplete external inventory and currency boundaries. A known-vault denominator does not establish all accounts the person holds.

## Spending and income

9. How much did I spend in [covered calendar month]?
10. How does that compare with [previous month]? Ask as a follow-up, then test a separate new-question context.
11. What were my ten largest purchases?
12. What did I spend by category during [period]?
13. Show the transactions behind the largest category.
14. Which merchants did I spend the most with?
15. How much did I spend on groceries? On travel?
16. Why was [exact displayed transaction] given that category?
17. What income came into my checking account?
18. How much of that was payroll?
19. Which transactions are transfers between my own accounts?
20. Are my credit-card payments counted as spending twice?
21. Did I receive refunds or credits?
22. How much did I pay in fees and interest?
23. Which recurring payments or subscriptions can you see?
24. Do any transactions look duplicated?
25. Show the source statement for the largest purchase.

Check actual calendar boundaries, ranking, category totals/unknowns, merchant identity evidence, payment/transfer exclusion, payroll versus unknown deposits, refunds/signs and source scope. Avoid treating descriptor resemblance as personal identity or recurrence certainty.

## Brokerage

26. What was the brokerage account worth at each statement date?
27. Why did its balance change between [two covered periods]?
28. How much did I deposit into it?
29. How much did I receive in dividends and interest?
30. Which investments did I hold on the latest statement date?
31. How much brokerage cash was available, and which cash measure are you using?
32. What were my realized and unrealized gains?
33. Are investment purchases included in spending?

Distinguish deposits/withdrawals from trades, current-period from year-to-date amounts, market movement from realized gain, and holdings from overlapping cash/credit measures. Refusal is preferable to unsupported arithmetic.

## Limits, explanation and navigation

34. What are you least certain about in my finances?
35. What can you tell me about [a period not covered by any document]?
36. Show exactly how you calculated the credit-card total.
37. Which unanswered questions would change that total?
38. What is each card's minimum payment and due date?
39. Ask one supported question with a short paraphrase and one abbreviated follow-up.
40. Open an answer's cited source, inspect the exact supporting row/page, reload, and check the answer/receipt remains consistent.

Do not penalize an honest unsupported feature as a fabricated-answer bug. Record capability, usefulness and factual accuracy separately. Ask additional questions when the actual documents suggest meaningful risks; the list is coverage guidance, not a substitute for judgment. Any established product bug triggers the reviewed diagnosis/repair method in SKILL.md. Honor an explicitly authorized retained-vault continuation for non-ingestion repairs when state remains suitable; ingestion/durable-state repairs retain the full restart rule.

## Current financial capability continuation

Read the product repository’s `acceptance/real-document-test.md` and `acceptance/scenarios/financial-capabilities.md` for the authoritative public continuation and GUIDE-007–GUIDE-026 checks. All 19 uploaded files remain in the retained vault whose identity has been checked when the owner authorized non-ingestion continuation; do not automatically reupload. Historical inventory questions above are exploratory, not claims that every feature is supported.

Exercise all 17 current additions: spending by category/merchant/account, comparison, movement search, attributed income, surplus, observed recurring spending; recorded cash, dated account history, held statement coverage, known remainder, next obligations, local goal progress; savings, loan payoff, cash flow. Recurrence accepts optional currency, not a merchant/account/custom-period filter. Cash needs a held account; coverage needs a held account and dates. Known remainder and upcoming obligations use a bounded horizon in days; local goal progress accepts optional currency only. Establish numerical source totals, dates, roles, currency and weakest grades before asking; category/treatment do not require separate evidence gates.

Use these whole current-question forms after family selection. Replace placeholders, repeat one three-letter currency code, use semicolons and year-month-day dates:

```text
Simulate savings in [currency]: initial amount [currency] [amount]; monthly contribution [currency] [amount]; nominal annual rate [rate] percent; horizon [months] months; opening date [date]

Simulate loan payoff in [currency]: principal [currency] [amount]; monthly payment [currency] [amount]; nominal annual rate [rate] percent; horizon [months] months; first payment date [date]

Simulate cash flow in [currency]: initial amount [currency] [amount]; monthly income [currency] [amount]; monthly outflow [currency] [amount]; one-off outflow [currency] [amount]; one-off at month [month]; horizon [months] months; opening date [date]
```

For a recorded start, replace initial amount (savings/cash) or principal (loan) with `starting account [exact held account name]`, never both. Preserve every other clause. Prior-assistant numbers and partial replies cannot supply missing premises. Nominal annual percent is divided by 12; APY/effective yield/monthly rates are not converted. Normalize once to cents with HALF_EVEN, then round monthly interest/endpoints. Savings/cash first endpoint is one month after opening; loan first payment follows a full monthly interest period. Independently clamp each target month to the original anchor day. Explicit one-off amount/month is required even for zero.

All derived scenarios are hypothetical with empty grades; actual starting measurement date/view/source/grade remains separate. Check stock versus flow, final/minimum/first-negative/payoff dates, positive-payment count, sample labels and full result refusal without truncation. At zero rate genuine zero payment leaves debt unchanged/no payoff; positive payment rounding to zero with positive modeled debt refuses.

Retain owner-deferred local goal receipt navigation, D16 wording, D19 validation and older internal missing label. Source page/region access, actual browser receipt usability, signing/binding and paid 123-case qualification remain separate unverified gates. No private source records, exact answers or spending authorization belong in this reference.
