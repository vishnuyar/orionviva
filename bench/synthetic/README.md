# A synthetic financial life, for end-to-end runs

The test suite reads documents through a stubbed reader. That is right for unit
tests and it cannot answer the question this directory exists for: **does the
whole path work — a real PDF, read by a real model, verified, posted, and
answered — and how often does it produce a figure that is wrong?**

Nothing here is real. It is one coherent invented life over three months, which
is the part that matters: the documents refer to each other. A card payment
leaves the checking account and arrives on the card. A pay stub's net equals the
payroll deposit to the dollar. A brokerage contribution leaves checking and
lands as cash. Those cross-document facts are exactly what a stub cannot
produce, and exactly what the ledger's harder promises are about.

## The life

| | |
|---|---|
| Holder | ROWAN E VANCE (invented) |
| Period | January – March 2026, `en-US`, `USD` |
| Checking | Northbank Everyday ••••4417 — 3 statements |
| Savings | Northbank High-Yield ••••8802 — **2 statements: January and February only** |
| Card | Meridian Signature ••••2291 — 3 statements |
| Brokerage | Vantage Individual ••••7734 — 3 statements, holdings *and* cash activity |
| Employer | Halcyon Systems — 3 monthly pay stubs |

Fourteen documents.

Deliberate properties, each aimed at something that has been wrong before:

- **March savings is missing.** The net-worth curve must carry February's
  closing forward as savings' latest measurement and name it as the point's
  stalest input, rather than dropping the account or inventing a zero.
- **Each pay stub's net differs** from the others. A deposit can therefore only
  be explained by one stub, so a matcher that consumes a deposit twice is
  visible instead of accidentally safe.
- **The brokerage statements carry cash activity, not just holdings** —
  contributions, a dividend, buys and a fee — so the cash-flow gate runs. That
  path has never met a real document.
- **Documents are ingested out of date order** by the runner. Order-independence
  is a promise; a run that only feeds documents in order never tests it.
- **Recurring merchants repeat** across months and across both the card and the
  checking account, so merchant normalization and enrichment have something to
  do and category totals have something to add up.

## Why the PDFs are not committed

`.gitignore` excludes `*.pdf`, which is the rule that keeps real statements out
of a public repo. The rule is not worth weakening for test data that a script
can rebuild, so the corpus is committed as **code plus its answer key** and the
PDFs are generated locally:

```
pip install -e 'bench[corpus]'   # or: pip install reportlab
python make_corpus.py            # writes pdfs/ and answer-key.json
```

`reportlab` is a generator-only dependency and is deliberately not a dependency of `core/` or `product/`: it writes test documents and never reads one, so it stays out of the trust path. Rendering the pages with Pillow instead would avoid it, but would produce image-only PDFs with no text layer — a harder path than a real statement, and therefore a less representative test.

The generator computes every balance and **asserts every printed identity before
a page renders** — opening + Σ = closing, gross − deductions = net,
Σ market value + cash = total, and each month opening where the last closed. A
corpus that did not reconcile would be indistinguishable from a model misreading
one that did, so the generator fails rather than emitting one.

`answer-key.json` carries every figure in raw-as-printed form beside its
normalized value, with locale and currency on each entry. That shape is not
decoration: a key without locale cannot be reused for a second region, and it
cannot be retrofitted later.

## Running it

```
python run_corpus.py --vault ~/.viva-vault-corpus
```

Creates a **new** vault — it refuses an existing path, because a run that starts
from previous state is not a first run. Reads model configuration from
`product/.env`, so the model reading these documents is the model configured for
real ones. Real calls, real money.

The report has two halves. First, what the vault came to believe: accounts and
balances with their grades, movements and how each one's nature was decided,
transfer links, spending and what was excluded from it, holdings, the net-worth
curve, and the questions Viva would ask. Second, that belief checked against the
answer key. Exit code is 0 only when every check passes.

A failing check is not automatically a defect in the product — the model may
have misread a figure, which is itself the measurement worth having. The report
distinguishes the two by showing what was extracted next to what was printed.
