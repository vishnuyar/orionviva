# Document Coverage — every instrument a financial life produces

**State:** partial
**Rules:** ING-20, ING-21, ING-22
**Invariants touched:** I5 (no US-shaped taxonomy — the India column is not an afterthought) · I6 (regional packs run through identical machinery; real statements are never committed) · T3 (every document is raw-captured, so coverage grows by re-reading, not by re-uploading) · the practice that [a slice isn't done until real documents pass through it](implementation-roadmap.md).

## Rules

### ING-20 — A document type counts as covered only when a real one has posted
**State:** untestable
**Code:** product/viva/ingest/registry.py:67 (the registered types), product/viva/ingest/brokerage_projector.py:142 (a projectable type is posted, anything else is parked)
**Test:** none

1. A registry row for a type is not coverage; a real document of that type must have been ingested, reconciled and posted.
2. A type with a registry row but no real document through it is reported as unproven, not as supported.

_Untestable as written: the registry and the projector are checkable, but "a real document of this type has passed through" is a fact about a person's vault, not about the tree. The registry holds rows for checking, savings, credit card, pay stub and brokerage._

### ING-21 — Real documents are never committed
**State:** by-review
**Code:** .gitignore:40 (`bench-data/`, matched at any depth)
**Test:** none

1. Real statements live in the local vault and in an ignored `bench-data/` directory.
2. What ships is the profile and the scorecard, never the document.

### ING-22 — A document a ruling names is corroboration, never a gate
**State:** enforced
**Code:** product/viva/listen.py:25, product/viva/questions.py:514 (`_corroboration_questions`)
**Test:** product/tests/test_listen.py::test_an_asserted_account_asks_for_the_document_that_would_prove_it

1. An account a person's own words create is opened and its cash posted before any document is mentioned.
2. The document is then asked for as a ranked question; declining costs the person a confidence grade and nothing else.

## Why

Five document types are covered. A financial life produces something closer to
forty. Every gap is a place the product will either park a document honestly —
which is fine — or answer a question wrongly because it never saw the evidence,
which is not. The mortgage split is exactly the second case: the interest,
principal and escrow shares of one payment are unknowable until a mortgage
statement or a 1098 is read, so the answer is wrong rather than absent.

The gap list doubles as the prompt and profile backlog. Each row is eventually a
registry row plus a prompt fragment plus an identity, and most of them are data
rather than code — which is the whole claim the doc-type registry rests on.

Coverage is also demand-driven, not a list an author works through. Every
account a ruling creates names the document that would corroborate it: *"I
bought a car"* names the invoice, *"this is my mortgage"* names the statement or
the 1098, *"this paid my car loan"* names the loan statement. The vault
therefore says which document matters next, ranked by the money the answer would
explain. And because the ask is corroboration rather than a gate, wanting the
document never costs the person the ability to record the fact.

The order that unblocks the most is: a mortgage statement plus a 1098, because
it makes a currently-wrong answer right; a consolidated 1099, for short versus
long-term realized gains that brokerage ingest reads and discards; a retirement
statement, for positions plus the employer match as a second income shape; an
India pack of one bank, one card and one mutual fund, which is the proof that
locale and taxonomy are data and is non-negotiable before claiming
international support; a closing disclosure, the three-facts-from-one-document
case that forces the Asset primitive; and one insurance declaration, which
proves that non-numeric attested terms need no new engine.

Documents fall into shapes rather than into a flat list, and the shape is what
decides whether a new one is a registry row or a new primitive. Banking and
cards share the balance family. Income documents split into per-period stubs and
annual totals that corroborate the sum of them. Investments add positions,
vesting schedules and an employer match that never touches a paycheck's
gross-to-net. Debt documents carry an amortization split that is one movement
with three destinations. Property, insurance and tax documents are the ones that
are not transaction-shaped at all — a declarations page is attested non-numeric
terms, and a return is an annual truth that many other documents corroborate.

## Open

- The current card profile and value-retry prompt exclude summary rows in the
  technical suite; a live-model re-read of real-vault document 17 is still
  required to show that the summary is omitted, genuine payments remain, and
  the document reaches the correct ingest state.
- The mortgage statement and 1098 gap: the compound-payment split is unanswerable until one is read, and it is the highest-value document gap open.
- Realized gains, short versus long term, plus wash sales: brokerage ingest reads them and discards them today.
- Retirement statements: positions plus employer match, which is a second income shape and not a variant of the first.
- An India pack (one bank, one card, one mutual fund) as the locale-and-taxonomy proof.
- A closing disclosure, which produces three facts — cash out, asset in, liability created — from one document and forces the Asset primitive.
- An insurance declarations page, to prove that a Provision needs no new engine.
- Certificates of deposit, HSA/FSA, 529, employee equity with vesting, and crypto positions with no issuer attestation: each is a registry row plus one modeling question.
- Estimated tax payments, which are an outflow that is neither spending nor a transfer.
- Recurring bills, leases and premium notices, which matter as obligations more than as transactions.
- A W-2, whose annual totals corroborate the sum of a year's pay stubs — a completeness check rather than a new posting.
- 1099-NEC and 1099-MISC, where an annual total corroborates many deposits; a sibling profile, not a subtype of the pay stub.
- 1099-INT and 1099-DIV, which corroborate interest and dividend income already posted.
- India's Form 16 and ITR, the Indian pay-and-tax equivalent, which must not become a row in a US table.
- A Social Security statement, which is a future income projection and not a ledger fact.
- An escrow analysis, which says why a payment changed and what escrow balance the person owns.
- An auto loan statement: amortization, paired with the vehicle as an Asset.
- A student loan statement: amortization plus an interest deduction.
- A HELOC or personal loan, which is the revolving-versus-amortizing liability distinction.
- A property tax bill, a recurring obligation and escrow's destination.
- A vehicle purchase agreement, the Asset primitive's first non-security instance.
- A home or auto valuation, whose valuation class is `estimated` because no issuer attests it.
- An explanation of benefits, which is a three-way reconciliation of what was billed, paid and owed.
- A federal or state return, the annual truth that many other documents corroborate.
