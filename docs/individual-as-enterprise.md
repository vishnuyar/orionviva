# The Individual as an Enterprise — personal books, and onboarding as a lifelong process

**State:** partial
**Rules:** PROG-30, PROG-31, PROG-32, PROG-33, PROG-34

## Rules

### PROG-30 — Opening Balance Equity is permanent and always the earliest known opening
**State:** enforced
**Code:** product/viva/ledger/postings.py:31 (`EQUITY_OPENING`), product/viva/ledger/projection/core.py:96-99, product/viva/ledger/projection/balances.py:56 (`effective`)
**Test:** product/tests/test_pipeline.py::test_backfill_prepends_older_statements, product/tests/test_pipeline.py::test_middle_gap_heals_both_sides

1. Opening Balance Equity is never zeroed out; its balance is the measure of unexplained history.
2. The injection is computed from the account's earliest known opening at query time rather than accumulated per opening event, so a backfilled older statement re-seats it with no double count and no event to reverse.
3. As older statements arrive, the unexplained balance shrinks.

### PROG-31 — An inferred figure is graded and visible, never a silent plug
**State:** enforced
**Code:** product/viva/ledger/projection/balances.py:86 (`balance`), :99-105, :110-121
**Test:** product/tests/test_tools.py::test_balances_match_the_projection_and_carry_grades (assertion 1), product/tests/test_pipeline.py::test_gap_between_months_is_surfaced_not_invented (assertion 2)

1. A lone attested closing with nothing to reconcile against is graded `verified`; an attested closing that its opening and transactions reconcile to is graded `corroborated`, rising to `verified` where a person has confirmed the reading; a balance replayed with no attested closing to check it against is graded `unverified` and carries the explanation why.
2. A gap is surfaced as a quantified gap, never closed by a plug the reader cannot see.

### PROG-32 — P&L and balance sheet are named projections over the posting ledger
**State:** unmet
**Code:** none found (income, spending, balances and net worth exist as separate projections; no income-statement or balance-sheet projection does)
**Test:** none

1. The income statement is the income and expense postings over a period, exposed as one named projection.
2. The balance sheet is the asset and liability account balances at a moment, exposed as one named projection.
3. Both are queries over the posting ledger, built once in the query layer rather than as bespoke features.

### PROG-33 — Reconciliation is the gap detector
**State:** enforced
**Code:** product/viva/ledger/projection/balances.py:108 (`check_balance_identity`), product/viva/ingest/pipeline.py:183, product/viva/ingest/diagnose.py
**Test:** product/tests/test_pipeline.py::test_gap_held_item_reports_the_held_balance, product/tests/test_pipeline.py::test_out_of_order_uploads_self_heal

1. Opening balance plus the transactions seen must equal the closing balance the statement states.
2. Where it does not, the difference is a specific quantified gap over a named span, reported rather than absorbed.

### PROG-34 — There is no setup phase distinct from use
**State:** untestable
**Code:** none found
**Test:** none

1. There is no "connect all your accounts" wizard and no empty-books ceremony.
2. Day one and year five run the identical pipeline: drop a document, extract, verify, post, reconcile.
3. The surface reveals itself as data arrives rather than presenting holes to fill.

## Why

The framing is sound and well-trodden. A personal balance sheet and a personal income statement are standard tools; double-entry personal bookkeeping already exists in hobbyist software. So treating the individual as an enterprise is validated, not novel. What *is* open is that nobody does org-grade accounting for individuals with zero manual effort. The two existing camps each miss half: real accounting at high friction, where the books balance but every line is hand-entered, and low friction with fake accounting, where feeds import beautifully into categorised transaction lists that are not books. The missing quadrant — built on the double-entry decision in [data-model-spike-findings.md](data-model-spike-findings.md), completeness-as-data in [knowledge-and-expectations.md](knowledge-and-expectations.md) and the progressive-disclosure surface in [experience-vision.md](experience-vision.md) — is the rigour of a company's books with the effort of dropping a PDF — the personal CFO the wealthy already buy, democratised, which is a sharper positioning than "budgeting app".

**The asymmetry that is the whole product is not that the law forces companies.** It is that a company's books are complete and closed while an individual's are permanently incomplete and sampled. A company captures every transaction, reconciles to the penny, and closes each period under audit. An individual will never hand over every cash purchase, every peer payment, every receipt, and there is no accountant and no auditor compelling them to. So these books are structurally partial, forever. That is not a defect to hide: honesty about the partiality *is* the product, which is "never bluff a number" applied to the ledger itself. A company that hid a gap commits fraud; this product hiding a gap breaks its one promise. Where accounting software *assumes* completeness, this must measure and surface incompleteness, and everything else follows from that.

Two smaller asymmetries follow. There is no forcing function — companies have law, audit and a paid bookkeeper compelling completeness — so a quiet nudge replaces it, as pull rather than push: gaps become quiet state, not alarms. And individuals think in money-in and money-out rather than earned and incurred, so the ledger is cash-first, with accrual concepts layered only where an obligation is noticed.

**The double-entry dividend.** The income statement and balance sheet are not features to build; they fall out of the double-entry ledger as two standard projections over the same events. Choosing double-entry bought the personal CFO's two core deliverables. The user rarely sees them raw — most people want "can I afford this", not a balance sheet — but they exist as the rigorous substrate every plain answer stands on.

**Why any-order ingestion works.** Event sourcing plus double-entry makes time order irrelevant: every posting is a self-contained, locally balanced event with its own date, and projections re-derive from the full set regardless of arrival order. A statement from three years ago is just events with three-year-old dates. Opening Balance Equity is the standard accounting device for starting in the middle: a balance that was not built from transactions anybody has seen is booked against it.

**And here is the synthesis this document exists for.** In business accounting, Opening Balance Equity is a temporary scaffold zeroed out once setup is complete. For an individual, setup is never complete — onboarding is lifelong — so it is never zeroed. It becomes a permanent, honest account whose balance *is* the measure of unexplained history: how much of a financial life this product has seen no documents for. The completeness of the books becomes a number that can be shown and pursued.

Reconciliation then gives the gap detector for free. Opening balance plus the transactions seen should equal the stated closing balance; where it does not, the difference is precisely the missing activity, quantified and dated. That is the accountant's reconciliation done automatically, feeding the coverage map and the nudge. Incompleteness becomes a measured number gently surfaced rather than a hidden lie.

Which is why onboarding is not a phase. Day one and year five run the same pipeline, and the early sparse part is made to feel like progress — *that is your checking and two cards in; I can see a mortgage payment leaving, so there is a loan statement worth adding when you have it* — rather than a hole to fill.

**Sources:** [Corporate Finance Institute — personal financial statement](https://corporatefinanceinstitute.com/resources/wealth-management/personal-financial-statement/) · [SmartAsset — personal financial statement](https://smartasset.com/financial-advisor/personal-financial-statement) · [MMI — personal balance sheet and net worth](https://www.moneymanagement.org/blog/how-to-create-a-personal-balance-sheet-and-determine-your-net-worth) · [Beancount — Opening Balance Equity](https://beancount.io/ko/blog/2026/05/17/opening-balance-equity-account-set-up-new-books-mid-year-clear-zero-out-retained-earnings-owner-equity-guide) · [FreshBooks — what is opening balance equity](https://www.freshbooks.com/hub/accounting/opening-balance-equity) · [QuickBooks — first reconcile and opening balances](https://quickbooks.intuit.com/learn-support/en-us/help-article/banking/fix-issues-first-time-reconcile-account-quickbooks/L1aksm3QU_US_en_US)

## Open

- Q34: opening-balance confidence — the grade and presentation for an inferred opening balance against a statement-attested one, and how the unexplained balance is explained to a non-accountant without the word "equity".
- Q35: how far back to pursue — the nudge should help reconstruct useful history without badgering for a decade-old statement, and what bounds it (recency, materiality, the person's own goals) is undecided.
- Q36: the cash/accrual boundary — which obligations are modelled as accrual (premiums, instalments, amounts owed) against those left cash-only. Tied to the obligations primitive.
- The income statement and balance sheet are not named projections (PROG-32), so the two deliverables the double-entry choice was made to buy are not exposed as such.
