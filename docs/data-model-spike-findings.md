# Data Model Spike — findings from real documents

**State:** partial
**Rules:** ING-50, ING-51, ING-52, ING-53, ING-54
**Method:** empirical — the ontology in [data-model-considerations.md](data-model-considerations.md) tested against the actual structure of a fifteen-document corpus. No personal values or names appear here; only shapes.
**Invariants touched:** T1, T2, T4, T7, I1 (multi-currency confirmed real), I5 (jurisdiction as an attribute), X2

## Rules

### ING-50 — A document's type never comes from its filename
**State:** enforced
**Code:** product/viva/ingest/reader.py:62 (`classify` reads the document), product/viva/ingest/brokerage_projector.py:90 (`filename` is recorded on the capture event and is not used to route)
**Test:** product/tests/test_reader_two_phase.py::test_classify_unreadable_is_unknown_not_a_guess

1. The type is extracted from the document's content and graded.
2. No filename, path or corpus label routes a document to a projector.

### ING-51 — A movement between the person's own accounts is not spending
**State:** enforced
**Code:** product/viva/ingest/transfers.py:332 (`link_transfers`), :394 (`find_corroborating_legs`), :66 (`account_tokens_from`, the own-account fingerprints)
**Test:** product/tests/test_transfers.py::test_internal_transfer_auto_links_and_excludes_from_spending, product/tests/test_nature.py::test_payment_to_my_own_card_is_not_spending_even_unlinked

1. Recognizing an internal transfer requires knowing which account fingerprints are the person's own; those come from the accounts the vault holds, not from a model's opinion.
2. A movement between two own accounts nets to zero across net worth and is excluded from spending.
3. A payment whose counterparty is a Party rather than an own account is a real inflow or outflow.

### ING-52 — A tax or annual-summary document produces a fact bundle, not transactions or positions
**State:** unmet
**Code:** none found
**Test:** none

1. A 1099, a 1098 or a jurisdiction-parallel annual form yields `(line, value)` facts keyed to regulated box numbers, attached to an account and a tax year and tagged with its jurisdiction.
2. Such a figure is never posted as a transaction and never as a position: it reports a year, it does not move money.

_No profile for a tax form is registered, so such a document classifies and parks._

### ING-53 — The leg a document attests and the leg the system supplies carry different grades
**State:** enforced
**Code:** product/viva/ledger/events.py:79-82, product/viva/ingest/statement_projector.py:353 (`account_grade=(t.grade or VERIFIED)`), product/viva/ledger/postings.py
**Test:** product/tests/test_postings.py::test_withdrawal_balances_and_grades

1. A posting the document states carries the grade its attestation earns.
2. A balancing posting the system supplies — an expense category, or the matching side of a transfer — carries a weaker grade until it is confirmed or linked.

### ING-54 — A balancing posting is never invented silently
**State:** enforced
**Code:** product/viva/ledger/postings.py (the counter-leg is named `Uncategorized` and graded `unverified`), product/viva/ledger/events.py:80-82
**Test:** product/tests/test_postings.py::test_withdrawal_balances_and_grades, product/tests/test_postings.py::test_split_that_does_not_cover_whole_rejected

1. Where double-entry requires a second leg nothing attests, that leg is named as unknown and graded, never presented as a fact.
2. A split whose parts do not cover the whole is rejected rather than balanced with a plug.

## Why

**Double-entry survives contact with reality, and earns its place.** The
strongest structural idea available — that this is a double-entry ledger where a
document attests one posting and the system infers or links the other, each
posting carrying its own provenance and grade — held on every case a real corpus
could test.

The corpus itself is finding zero: it is tax- and summary-heavy rather than
transactionally complete. Transfer linking, pay-stub deductions, brokerage
density and multi-currency were all testable against real documents. Escrow
split, vesting with cost basis, and insurance provisions were not — the
"mortgage statement" turned out to be an annual tax form with no monthly
principal/interest/escrow split, the brokerage document was a realized-gains
form with no positions, and insurance appeared only as a single line. Those
three are modeled analytically and flagged untested until real documents exist.

**Classification cannot come from filenames**, and the real content proved it
rather than argued it. A file labelled as a card statement was a consolidated
deposit statement; of nine files labelled one way, content showed five were card
statements and three were checking — a mix, not a type. Only the model reading
the document got it right. That is direct empirical support for
classification-is-a-claim, and the product consequence is that a misclassified
document must degrade to visible conflict rather than to silent
miscategorization.

**Double-entry handles a pay stub perfectly, and reveals a second flow.** Gross
pay, then taxes and a retirement deduction, then net, is one balanced
transaction with several postings — and because they balance, the document
self-checks for free. The surprise the real data gave was the *employer match*
on the retirement line: a separate flow, employer to retirement account, that
never touches the paycheck's gross-to-net. A naive single-entry model — "a
paycheck is a deposit" — loses it entirely. Double-entry represents it as its own
transaction, and both the deduction posting and the match posting are balancing
legs into a retirement account that is not in the corpus at all. That is exactly
the cross-document observation the ontology predicted.

**Transfer linking is two jobs, not one.** One month of a real checking
statement contained a payment to the person's own card, an ACH payment to a
mortgage servicer, peer payments to and from named family members, and an
inbound payment from a company. The own-card payment nets to zero across net
worth and must not count as spending, which needs an *own-account registry* —
the system knowing its owner's account fingerprints. Everything else has a Party
on the other side and is a real flow. So transfer linking is own-account
internal netting plus external Party attribution, two mechanisms sharing the
double-entry substrate rather than one graded fact.

**Tax documents are a distinct shape.** Hundreds of amounts on a consolidated
tax form are neither transactions nor positions: they are values keyed to
regulated box numbers — ordinary dividends, capital-gain distributions, foreign
tax paid, per-state withholding. Forcing them into `Transaction` is a category
error, and it also breaks the measurement honesty the model depends on: such a
form *measures a year*, it does not move money.

**Multi-currency is real, not hypothetical** — two currencies in one person's
corpus. Each posting carrying its own value and currency handles it; net worth
is computed per currency and consolidated at answer time with a cited, dated
rate, and the converted total is labelled an estimate. A fixed-deposit sub-shape
alongside a transaction account is just another account kind under the same
Party with its own jurisdiction: no new primitive, so the "regional variety is
an attribute" rule holds.

Three refinements to the ontology follow, all additive and none breaking. A
transaction becomes a set of postings — the single change that dissolves escrow
splits, pay-stub deductions, transfers and the employer match into one
mechanism, and the load-bearing decision of the whole exercise. An own-account
registry joins the record-identity design as a small, first-class requirement.
And tax or annual-summary documents produce a jurisdiction-tagged fact bundle.

The deepest structural point is that the attested-leg/inferred-leg split *maps
onto the grade system*. The posting a document states is attested; the balancing
posting the system supplies is weaker until confirmed or linked. Double-entry
and the trust spine are the same structure viewed twice. And self-checking
documents are a gift: a pay stub, or any statement with opening and closing
balances, balances by construction once its postings are complete — free
verification with no model opinion in it.

## Open

- How a person's own accounts get fingerprinted, and how confidently an internal transfer is auto-detected rather than asked about.
- The boundary between a fact bundle and a transaction: a dividend on a brokerage statement *is* money moved, while the annual form's "total ordinary dividends" is a summary of the same reality. They must reconcile rather than double-count.
- A second corpus needs a monthly mortgage statement, a brokerage positions statement and an insurance declarations page, to test escrow splits, holdings with cost basis, and provisions empirically rather than analytically.
- Whether double-entry's balancing requirement ever forces a posting nothing can attest, and how such a posting is graded and surfaced. It must never be silently balanced.

## Sources

- [hledger — why plain-text double-entry](https://hledger.org/why.html) · [Beancount vs hledger](https://beancount.io/compare/beancount-vs-hledger)
- [Beancount investments: cost basis, unrealized gains, multi-currency](https://beancount.io/docs/introduction-to-beancount) · [hledger: tracking investments](https://hledger.org/investments.html)
- [FDX — Financial Data Exchange (accounts, investments, loans, insurance, tax)](https://financialdataexchange.org/about-fdx/) · [Stripe: what is FDX](https://stripe.com/resources/more/what-is-the-financial-data-exchange-fdx-here-is-what-you-should-know)
- [Open Financial Exchange (OFX) — investment account modeling](https://en.wikipedia.org/wiki/Open_Financial_Exchange)
