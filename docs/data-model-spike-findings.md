# Data Model Spike — findings from real documents

**Status:** Draft (experiment 2 output) · **Last updated:** 2026-07-21 · **Method:** empirical — the ontology in [data-model-considerations.md](data-model-considerations.md) tested against the *actual* structure of the 15-document corpus (model-extracted claims for 3; text-layer structure for the rest). No personal values or names appear here; only shapes.
**Invariants touched:** T1, T2, T4, T7, I1 (multi-currency confirmed real), I5 (jurisdiction as attribute), X2
**Decisions carried in:** one multi-currency life · single-user but tag/party-ready · live holdings matter · empirical spike.

## Headline

**Double-entry survives contact with reality, and earns its place.** The strongest structural idea from the research — *OrionViva is a double-entry ledger where a document attests one posting and the system infers or links the other, each posting carrying its own provenance and grade* — held on every case the real corpus could test. The ten primitives survive with three refinements. And the corpus surfaced two things no amount of armchair reasoning would have: a real transfer-linking case with both legs present, and the fact that half our "known" document types were misclassified by filename.

## What the real data could and couldn't test

The corpus is **tax/summary-heavy**, not transactional-complete. This is itself finding zero:

| Leak candidate | Testable here? | Why |
|---|---|---|
| Transfer linking | **Yes — real case, both legs** | A checking statement shows a "Payment To [own] Card" *and* an ACH mortgage payment; the card is separately in-corpus |
| Pay-stub deductions | **Yes — real** | The pay stub is digital and complete: gross → taxes + retirement → net |
| Brokerage density | **Yes — real** | The Fidelity 1099 has 283 amounts across nested tax boxes |
| Multi-currency | **Yes — real** | USD (Chase, Fidelity) + INR (IDFC, SBI) in one person's corpus |
| Escrow split | **No** | The "mortgage statement" is a **Form 1098** (annual tax), not a monthly statement with a principal/interest/escrow split |
| 401(k) vesting / live holdings + cost basis | **No** | The Fidelity doc is a **1099** (realized/tax); no positions statement present |
| Insurance provisions | **Barely** | Only PMI appears, as a line on the 1098 |

**Recommendation:** a v2 corpus needs three specific documents to finish validating — one *monthly* mortgage statement (escrow split), one brokerage *positions* statement (holdings + cost basis), one insurance *declarations* page (provisions). Until then, those three are modeled analytically, flagged as untested.

## Finding 0 — Classification cannot come from filenames (design choice vindicated)

Real content vs. my `corpus.yaml` guess: the file labeled `sbi-card` is actually a **consolidated deposit statement** (savings + fixed deposits, "available balance - fixed deposit"), not a credit card. Of nine "chase combined bank" files, content shows **five are credit-card statements** and **three are checking** — a mix, not one type. Only the model reading the document got it right. This is direct empirical support for *classification-is-a-claim* (data-model doc, refinement 1): `doc_type` must be extracted and graded, never inferred from a filename or heuristic. In the product, a misclassified document must degrade to visible conflict, not silent miscategorization.

## Finding 1 — Double-entry handles the pay stub perfectly, and reveals a second flow

The real pay stub's structure: **Gross Pay** → Federal Income Tax, Social Security, Medicare, retirement (401k) deduction → **Net Pay**. In double-entry this is *one balanced transaction* with several postings: income in, each tax/deduction out, net to checking. The model reads the postings the document attests (all `verified`); they already balance, so the document *self-checks* (gross = net + sum of deductions — a T2 arithmetic identity, for free).

The surprise the real data gave: **"Employer Match"** on the retirement line. That is a *separate* flow — employer → retirement account — that never touches the paycheck's gross/net balance. A naive single-entry model ("a paycheck is a deposit") loses it entirely. Double-entry represents it as its own transaction. **The 401k deduction posting and the employer-match posting are both the balancing legs of postings into the (here absent) 401k account** — which is exactly the cross-observation the data-model doc predicted: the same economic event seen from two documents becomes two postings of one linked reality.

## Finding 2 — The transfer-linking case is real, and it splits into two sub-problems

The checking statement contains, in one month: a **"Payment To [the user's own] Card"**, an **ACH payment to a mortgage servicer**, and several **peer payments to and from named individuals** (family) and an **inbound payment from a company** (income). Double-entry handles all of these as balanced transactions — but the real data shows transfer-linking is *two* distinct jobs, not one:

1. **Internal transfer** (checking → the user's *own* credit card): both accounts belong to the user, so the movement nets to zero across net worth and must **not** count as spending. Recognizing this needs an **"is this account mine?" registry** — the system must know the user's own account fingerprints. This is a new, small, first-class requirement the spike surfaced: **own-account identity**, distinct from the counterparty Party.
2. **External payment** (peer payment to a family member; ACH to the mortgage servicer; inbound from a company): the counterparty is a *Party*, not the user's account, so it *is* a real inflow/outflow. The "just me, tag-ready" decision pays off here — the family members are Parties the schema can name without modeling their finances.

So transfer-linking = *own-account internal netting* (needs the own-account registry) + *external Party attribution* (needs the Party primitive). The data-model doc treated transfer-linking as one graded fact; the real data says it is **two mechanisms sharing the double-entry substrate**. Refinement.

## Finding 3 — Tax documents are a distinct shape; don't force them into transaction/position

The Fidelity 1099's 283 amounts are not transactions and not positions — they are **tax-line facts**: values keyed to regulated box numbers (1a ordinary dividends, 2a capital-gain distributions, foreign tax paid, per-state withholding). Forcing these into `Transaction` would be a category error. They are best modeled as a **typed fact bundle** attached to an account and a tax year — a document-shaped set of `(tax_line, value)` facts, jurisdiction-tagged (US IRS here; a 1098 is the same shape; an Indian Form 16 would be the jurisdiction-parallel). This is refinement three: alongside Transaction/Position/BalanceSnapshot, tax/summary documents produce a **StatementFacts bundle** — attested figures that are neither money-moved nor holdings, but reported summaries. (It keeps the "measurements" honesty: a 1099 *measures* the year, it doesn't move money.)

## Finding 4 — Multi-currency is real and the Beancount pattern fits

One person, USD and INR, is not hypothetical — it's the corpus. Double-entry multi-currency (each posting carries its `(value, currency)`, per I1) handles it; net worth is computed per-currency and consolidated **at answer time** with a cited, dated FX rate, the converted total labeled an *estimate* (measurements-vs-valuations, honestly). The Indian deposit statement also showed a sub-shape — **fixed deposits** alongside the transaction account — which is just an Account of kind `term_deposit` under the same Party, jurisdiction `IN`. No new primitive; I5 holds (jurisdiction as attribute).

## The refined ontology (what changed)

The ten primitives stand. Three refinements, all *additive*, none breaking:

1. **Transaction becomes a set of Postings.** A transaction is one or more balanced postings, each `(account, value, currency, direction)` with its own provenance and grade. This is the single change that dissolves escrow-split, pay-stub deductions, transfers, and employer-match into one mechanism. **This is the load-bearing decision of the spike.**
2. **Own-account registry** — the system knows the user's own account fingerprints, so internal transfers net out and don't read as spending. Small, first-class, new.
3. **StatementFacts bundle** — tax/annual-summary documents (1099, 1098, Form 16) produce jurisdiction-tagged `(line, value)` fact bundles, not transactions or positions.

Unchanged and confirmed real: Party (family payees), Account + jurisdiction attribute (US + IN, term deposits), multi-currency amounts, Provision (PMI sighting), the claims→facts→provenance spine (each posting attested or inferred with a grade).

## Consequences for architecture

- **Adopt double-entry (postings) as the ledger substrate.** This is now an evidence-backed sticky-door decision for the architecture phase, not a guess — validated on real pay-stub, transfer, and multi-currency data, and converged-upon by both plain-text accounting (Beancount/hledger) and the FDX open-banking standard.
- **The attested-leg/inferred-leg split maps onto the grade system:** the posting a document states is `verified`; the balancing posting the system supplies (expense category, or the matching side of a transfer) is `unverified`/`corroborated` until confirmed or linked. Double-entry and the trust spine are the *same* structure viewed twice.
- **Own-account identity** joins the record-identity design (ADR-007 neighborhood): the user's accounts need stable fingerprints the transfer-linker can match against.
- **Self-checking documents are a gift:** the pay stub and any statement with opening/closing balances balance *by construction* once postings are complete — free T2 verification, no model opinion.

## Open questions (register)

- Q24: Own-account registry — how the user's accounts get fingerprinted (from statements' account numbers/masks) and how confidently an internal transfer is auto-detected vs. asked.
- Q25: StatementFacts vs Transaction boundary — a dividend on a brokerage statement *is* money moved (transaction), but the 1099's "total ordinary dividends" is a summary (fact). The same economic reality appears as both; they must reconcile, not double-count. (Mirrors the observation-merging spine.)
- Q26: v2 corpus — add a monthly mortgage statement, a brokerage positions statement, an insurance declarations page to test escrow-split, holdings+cost-basis, and provisions empirically.
- Q27: Does double-entry's balancing requirement ever force the system to invent a posting it can't attest (e.g., an "unknown source" plug)? How is a plug posting graded and surfaced honestly? (Never silently balanced.)

## Sources

- [hledger — why plain-text double-entry](https://hledger.org/why.html) · [Beancount vs hledger](https://beancount.io/compare/beancount-vs-hledger)
- [Beancount investments: cost basis, unrealized gains, multi-currency](https://beancount.io/docs/introduction-to-beancount) · [hledger: tracking investments](https://hledger.org/investments.html)
- [FDX — Financial Data Exchange (accounts, investments, loans, insurance, tax)](https://financialdataexchange.org/about-fdx/) · [Stripe: what is FDX](https://stripe.com/resources/more/what-is-the-financial-data-exchange-fdx-here-is-what-you-should-know)
- [Open Financial Exchange (OFX) — investment account modeling](https://en.wikipedia.org/wiki/Open_Financial_Exchange)
