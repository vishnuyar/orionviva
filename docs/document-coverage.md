# Document Coverage — every instrument a financial life produces

**Status:** Living checklist · **Created:** 2026-07-25 · **Purpose:** the corpus plan *and* the profile/prompt roadmap in one place. A document type is "covered" when a **real** one has passed through ingest, reconciled, and posted — not when a profile row exists.

**Invariants touched:** I5 (no US-shaped taxonomy — the India column is not an afterthought) · I6 (regional packs run through identical machinery; real statements are never committed) · T3 (every document is raw-captured, so coverage grows by re-reading, not re-uploading) · the practice: [a slice isn't done until real documents pass through it](implementation-roadmap.md).

---

## Why this list exists

Five document types are covered. A financial life produces something closer to forty. Every gap here is a place the product will either **park a document honestly** (fine) or **answer a question wrongly because it never saw the evidence** (not fine) — the mortgage split is exactly that: the answer is unknowable until a mortgage statement or 1098 is read.

The list doubles as the **prompt/profile backlog**: each row is eventually a registry row + a prompt fragment + an identity, and most are *data, not code*.

Status key: **✅ covered** (real document posted) · **🟡 partial** (reads, doesn't fully post/reconcile) · **⬜ not started** · **📄 have a real one to test with**

## Banking & cards

| Document | Status | Identity / what it proves | Slice |
|---|---|---|---|
| Checking statement | ✅ | `opening + Σ = closing` | 2 |
| Savings / money-market statement | ✅ | same balance family | 2 |
| Credit card statement | ✅ | balance family, liability | 2 |
| Certificate of deposit | ⬜ | balance + maturity term (a Provision) | 11 |
| India: bank passbook / SBI card / IDFC savings | 📄 | balance family, en-IN/INR — the I2 locale test | 2 |

## Income

| Document | Status | Identity / what it proves | Slice |
|---|---|---|---|
| Pay stub | ✅ | `gross − deductions = net` | 4 |
| W-2 | ⬜ | annual totals corroborate the *sum* of pay stubs — a completeness check | 11 |
| 1099-NEC / MISC (self-employment) | ⬜ | annual total corroborates many deposits; **sibling profile, not a subtype** | 11 |
| 1099-INT / DIV | ⬜ | corroborates interest/dividend income already posted | 11 |
| 1099-B (proceeds) | 📄 | realized gains, **short vs long term** — the tax seam we currently discard | 11 |
| Social Security statement | ⬜ | future income projection, not a ledger fact | later |
| India: Form 16 / ITR | ⬜ | the Indian pay-and-tax equivalent (I5 — must not be a US table) | 11 |

## Investments & retirement

| Document | Status | Identity / what it proves | Slice |
|---|---|---|---|
| Brokerage statement | ✅ | `Σ positions + cash = total`; cash-flow stitching | 6 |
| Retirement (401k / IRA / 403b) | ⬜ | positions + **employer match** as a distinct inflow | 6 / 11 |
| HSA / FSA | ⬜ | an account that is *both* health and investment | 11 |
| 529 | ⬜ | positions, restricted purpose | 11 |
| Employee equity (RSU / ESPP / options) | ⬜ | **vesting** — a schedule, not a balance; one of the six data-model leak candidates | 11 |
| Crypto exchange statement | ⬜ | positions with no issuer attestation; valuation class `estimated` | later |
| India: mutual fund (CAMS/Karvy), Demat, PPF/EPF | ⬜ | positions + provident fund; the I5 proof for retirement | 11 |

## Debt

| Document | Status | Identity / what it proves | Slice |
|---|---|---|---|
| **Mortgage statement** | 📄 | **the interest/principal/escrow split** — blocks an honest answer *today* | **11** |
| 1098 (mortgage interest) | ⬜ | annual interest corroborates the monthly splits | 11 |
| Escrow analysis | ⬜ | why the payment changed; the escrow balance you own | 11 |
| Auto loan statement | ⬜ | amortization; pairs with the vehicle Asset | 11 |
| Student loan statement | ⬜ | amortization + interest deduction | 11 |
| HELOC / personal loan | ⬜ | revolving vs amortizing liability | 11 |

## Property & assets

| Document | Status | Identity / what it proves | Slice |
|---|---|---|---|
| Closing disclosure / settlement statement | ⬜ | a property purchase: cash out, asset in, liability created — **three facts from one document** | Asset / 11 |
| Property tax bill | ⬜ | recurring obligation; escrow's destination | 8 |
| Vehicle purchase agreement | ⬜ | the Asset primitive's first non-security instance | Asset |
| Home / auto valuation | ⬜ | valuation class `estimated` — no issuer attests it | Asset |

## Insurance

| Document | Status | Identity / what it proves | Slice |
|---|---|---|---|
| Policy declarations (auto/home/life/health) | ⬜ | **Provision** — attested non-numeric terms, searchable ("am I covered for X?") | 11 |
| Premium notice | ⬜ | recurring obligation | 8 |
| Explanation of benefits (EOB) | ⬜ | what was billed vs paid vs owed — a three-way reconciliation | 11 |

## Tax & obligations

| Document | Status | Identity / what it proves | Slice |
|---|---|---|---|
| Federal / state return | ⬜ | the annual truth many other documents corroborate | 11 |
| Estimated tax payments | ⬜ | outflow that is neither spending nor transfer | 11 |
| Recurring bills (utility, phone, internet) | ⬜ | mostly transaction-level; the document matters for Obligations | 8 |
| Lease / rent receipts | ⬜ | recurring obligation; a Party | 8 |

## The near-term testing list

What to gather next, in the order it unblocks something real:

1. **Mortgage statement + 1098** — unblocks the compound-payment split ([learning-mode.md](learning-mode.md)). Currently the single highest-value gap: it makes a wrong answer right.
2. **1099-B / consolidated 1099** — short vs long-term realized gains, plus wash sales, which brokerage ingest reads and discards today.
3. **Retirement statement (401k)** — positions plus employer match, the second income shape.
4. **India pack (one bank, one card, one mutual fund)** — the I2/I5 proof that locale and taxonomy are data. Non-negotiable before claiming international support.
5. **Closing disclosure** — the three-facts-from-one-document case that forces the Asset primitive.
6. **One insurance declaration** — proves Provision (non-numeric attested terms) doesn't need a new engine.

**Discipline:** real documents are never committed (I6, and the gitignore enforces it). They live in the local vault and `bench/bench-data/`; what ships is the *profile*, never the document.
