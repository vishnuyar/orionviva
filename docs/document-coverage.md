# Document Coverage — every instrument a financial life produces

**Status:** Living checklist · **Created:** 2026-07-25 · **Purpose:** the corpus plan *and* the profile/prompt roadmap in one place. A document type is "covered" when a **real** one has passed through ingest, reconciled, and posted — not when a profile row exists.

**Invariants touched:** I5 (no US-shaped taxonomy — the India column is not an afterthought) · I6 (regional packs run through identical machinery; real statements are never committed) · T3 (every document is raw-captured, so coverage grows by re-reading, not re-uploading) · the practice: [a slice isn't done until real documents pass through it](implementation-roadmap.md).

---

## Why this list exists

Five document types are covered. A financial life produces something closer to forty. Every gap here is a place the product will either **park a document honestly** (fine) or **answer a question wrongly because it never saw the evidence** (not fine) — the mortgage split is exactly that: the answer is unknowable until a mortgage statement or 1098 is read.

The list doubles as the **prompt/profile backlog**: each row is eventually a registry row + a prompt fragment + an identity, and most are *data, not code*.

Status key: **✅ covered** (real document posted) · **🟡 partial** (reads, doesn't fully post/reconcile) · **⬜ not started** · **📄 have a real one to test with**

## Banking & cards

| Document | Status | Identity / what it proves | Where it lands |
|---|---|---|---|
| Checking statement | ✅ | `opening + Σ = closing` | built |
| Savings / money-market statement | ✅ | same balance family | built |
| Credit card statement | ✅ | balance family, liability | built |
| Certificate of deposit | ⬜ | balance + maturity term (a Provision) | Slice 11 |
| India: bank passbook / SBI card / IDFC savings | 📄 | balance family, en-IN/INR — the I2 locale test | built |

## Income

| Document | Status | Identity / what it proves | Where it lands |
|---|---|---|---|
| Pay stub | ✅ | `gross − deductions = net` | built |
| W-2 | ⬜ | annual totals corroborate the *sum* of pay stubs — a completeness check | Slice 11 |
| 1099-NEC / MISC (self-employment) | ⬜ | annual total corroborates many deposits; **sibling profile, not a subtype** | Slice 11 |
| 1099-INT / DIV | ⬜ | corroborates interest/dividend income already posted | Slice 11 |
| 1099-B (proceeds) | 📄 | realized gains, **short vs long term** — the tax seam we currently discard | Slice 11 |
| Social Security statement | ⬜ | future income projection, not a ledger fact | later |
| India: Form 16 / ITR | ⬜ | the Indian pay-and-tax equivalent (I5 — must not be a US table) | Slice 11 |

## Investments & retirement

| Document | Status | Identity / what it proves | Where it lands |
|---|---|---|---|
| Brokerage statement | ✅ | `Σ positions + cash = total`; cash-flow stitching | built |
| Retirement (401k / IRA / 403b) | ⬜ | positions + **employer match** as a distinct inflow | positions + Slice 11 |
| HSA / FSA | ⬜ | an account that is *both* health and investment | Slice 11 |
| 529 | ⬜ | positions, restricted purpose | Slice 11 |
| Employee equity (RSU / ESPP / options) | ⬜ | **vesting** — a schedule, not a balance; one of the six data-model leak candidates | Slice 11 |
| Crypto exchange statement | ⬜ | positions with no issuer attestation; valuation class `estimated` | later |
| India: mutual fund (CAMS/Karvy), Demat, PPF/EPF | ⬜ | positions + provident fund; the I5 proof for retirement | Slice 11 |

## Debt

| Document | Status | Identity / what it proves | Where it lands |
|---|---|---|---|
| **Mortgage statement** | 📄 | **the interest/principal/escrow split** — blocks an honest answer *today* | **Slice 11** |
| 1098 (mortgage interest) | ⬜ | annual interest corroborates the monthly splits | Slice 11 |
| Escrow analysis | ⬜ | why the payment changed; the escrow balance you own | Slice 11 |
| Auto loan statement | ⬜ | amortization; pairs with the vehicle Asset | Slice 11 |
| Student loan statement | ⬜ | amortization + interest deduction | Slice 11 |
| HELOC / personal loan | ⬜ | revolving vs amortizing liability | Slice 11 |

## Property & assets

| Document | Status | Identity / what it proves | Where it lands |
|---|---|---|---|
| Closing disclosure / settlement statement | ⬜ | a property purchase: cash out, asset in, liability created — **three facts from one document** | Asset + Slice 11 |
| Property tax bill | ⬜ | recurring obligation; escrow's destination | Slice 8 |
| Vehicle purchase agreement | ⬜ | the Asset primitive's first non-security instance | Asset |
| Home / auto valuation | ⬜ | valuation class `estimated` — no issuer attests it | Asset |

## Insurance

| Document | Status | Identity / what it proves | Where it lands |
|---|---|---|---|
| Policy declarations (auto/home/life/health) | ⬜ | **Provision** — attested non-numeric terms, searchable ("am I covered for X?") | Slice 11 |
| Premium notice | ⬜ | recurring obligation | Slice 8 |
| Explanation of benefits (EOB) | ⬜ | what was billed vs paid vs owed — a three-way reconciliation | Slice 11 |

## Tax & obligations

| Document | Status | Identity / what it proves | Where it lands |
|---|---|---|---|
| Federal / state return | ⬜ | the annual truth many other documents corroborate | Slice 11 |
| Estimated tax payments | ⬜ | outflow that is neither spending nor transfer | Slice 11 |
| Recurring bills (utility, phone, internet) | ⬜ | mostly transaction-level; the document matters for Obligations | Slice 8 |
| Lease / rent receipts | ⬜ | recurring obligation; a Party | Slice 8 |

## The near-term testing list

What to gather next, in the order it unblocks something real:

1. **Mortgage statement + 1098** — unblocks the compound-payment split ([learning-mode.md](learning-mode.md)). Currently the single highest-value gap: it makes a wrong answer right.
2. **1099-B / consolidated 1099** — short vs long-term realized gains, plus wash sales, which brokerage ingest reads and discards today.
3. **Retirement statement (401k)** — positions plus employer match, the second income shape.
4. **India pack (one bank, one card, one mutual fund)** — the I2/I5 proof that locale and taxonomy are data. Non-negotiable before claiming international support.
5. **Closing disclosure** — the three-facts-from-one-document case that forces the Asset primitive.
6. **One insurance declaration** — proves Provision (non-numeric attested terms) doesn't need a new engine.

**Discipline:** real documents are never committed (I6, and the gitignore enforces it). They live in the local vault and `bench/bench-data/`; what ships is the *profile*, never the document.

---

## Documents the product asks *for itself* (added 2026-07-25)

This list was written as *"what should we test against."* Viva listens adds a second, live source: **every account a ruling creates names the document that would corroborate it** ([from-your-words-to-the-ledger.md](from-your-words-to-the-ledger.md)). *"I bought a car"* → the invoice. *"This is my mortgage"* → the statement or 1098. *"This paid my car loan"* → the loan statement.

Two things follow. First, coverage stops being a list the author works through and becomes **demand-driven** — the vault says which document matters next, ranked by the money it would explain. Second, the asks are **corroboration, never gates**: the account is created and the cash posted before the document is mentioned, so declining costs the person nothing but a confidence grade.
