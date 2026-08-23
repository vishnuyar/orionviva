# Pay Stubs & Income — the first divergent document, and decomposing a deposit

**State:** built
**Rules:** MON-37, MON-38, MON-39, MON-40, MON-41, MON-42, MON-43

**Invariants touched:** T1 · T2 · T4 · I1 · I5 · X2 · principle 2 · principle 7.

## Rules

### MON-37 — a pay stub is a divergent profile, selected as data
**State:** enforced
**Code:** product/viva/ingest/registry.py (the `pay_stub` profile, `identity="paystub"`); product/viva/ingest/statement_projector.py:411 (`post_paystub`)
**Test:** product/tests/test_registry.py::test_pay_stub_is_a_divergent_projectable_profile

1. A profile names its facts shape, its identity and its post-projector; the reader dispatches after classify to the right extraction prompt and parser, and the pipeline dispatches on the profile's identity.
2. `can_project` asks whether a projector exists for the type, not whether the type is balance-shaped.
3. Adding a differently-shaped document type is a registry row, not a dispatch change (product/tests/test_paystub.py::test_pay_stub_routes_to_its_own_projector).
4. The balance family is unchanged by the generalization (product/tests/test_paystub.py::test_balance_statements_still_work).

### MON-38 — the identity is `gross − Σ deductions = net`, and a failure holds
**State:** enforced
**Code:** core/vivacore/verify/arithmetic.py:71 (`check_paystub_identity`)
**Test:** product/tests/test_paystub.py::test_paystub_identity

1. The check is deterministic `Decimal` arithmetic; the model never certifies it.
2. A stub that does not balance to the cent is held with a localized finding, through the same forced/suggested/unlocalized contract a statement uses, and nothing is posted (product/tests/test_paystub.py::test_unbalanced_paystub_is_held_with_a_localized_finding).

### MON-39 — the decomposition explains a deposit and counts income once
**State:** enforced
**Code:** product/viva/ledger/postings.py:167 (`paystub_decomposition`)
**Test:** product/tests/test_paystub.py::test_paystub_decomposes_the_deposit_income_counted_once

1. Gross posts to `Income:Salary`, graded from the employer's attestation.
2. The deposit's `Income:Uncategorized` placeholder is cancelled for the net, so the same money is not counted twice.
3. The legs sum to zero, and the checking inflow itself is untouched.

### MON-40 — either arrival order works
**State:** enforced
**Code:** product/viva/ingest/paystub_projector.py:53 (`heal_paystubs`)
**Test:** product/tests/test_paystub.py::test_paystub_without_deposit_waits_then_heals

1. A pay stub with no matching deposit yet is held awaiting the deposit rather than posted or dropped.
2. The heal pass posts it when the deposit lands.

### MON-41 — deductions go into universal buckets
**State:** enforced
**Code:** product/viva/ledger/postings.py:87 (`DEDUCTION_ACCOUNTS`)
**Test:** product/tests/test_paystub.py::test_paystub_decomposes_the_deposit_income_counted_once

1. Each deduction posts by the model's proposed category — tax, retirement, insurance, other — graded `unverified` until a person confirms.
2. Jurisdiction is an attribute, so a US 401k, an Indian EPF and a UK ISA land in the same retirement bucket with no per-country table.
3. Retirement posts as an asset, so it is never counted as spending.

### MON-42 — income means attributed income
**State:** enforced
**Code:** product/viva/ledger/projection/balances.py:134 (`income_by_currency`)
**Test:** product/tests/test_paystub.py::test_income_is_counted_once_and_a_stub_awaiting_its_deposit_is_held

1. The income figure sums the `Income:*` accounts and excludes the `Income:Uncategorized` placeholder.
2. An inflow nothing has attributed is not reported as income.

### MON-43 — the net leg cites the specific deposit
**State:** unmet
**Code:** none found
**Test:** none

1. The pay stub's net leg carries a provenance edge to the checking deposit it explains.

## Why

The doc-type registry and transfer links only ever handled the **balance family** — checking, savings, card — which all share one shape, `opening + Σ = closing`. A pay stub is the first genuinely different document: its identity is `gross − deductions = net`, with no opening, no closing and no running balance. It is where the registry's central claim — that a new type with its own shape *and its own verification formula* is data, not new plumbing — gets its first real test. Every later divergent type inherits the same dispatch: a brokerage statement's positions-and-cash tally, a 1099's box sums, an insurance document's provisions.

A pay stub **explains** a deposit; it does not invent a parallel number. The checking statement already posts the net-pay direct deposit as undifferentiated income. The stub says: that deposit was the net of a larger gross, and here is where the rest went. So gross is recognized as income and allocated, the net cancels the placeholder rather than adding a second inflow, and the withheld parts become their own legs. Income recognized once, net counted once, order-independent, provenance and grade on every leg.

Income is not one shape, and a generic income abstraction would be a mistake. A W-2 pay stub is per-period, has a deduction identity, and decomposes *one* deposit. A 1099 is an annual total, usually has no deductions at all, and its money arrived as *many* deposits — so its relationship to the ledger is a **completeness check** ("do my deposits from this payer sum to the total they report?"), not a decomposition. Two income types coexist, neither bent to fit the other, which is the whole point of the registry.

Deductions land in universal buckets because a per-country table would be I5's failure mode: the model extracts the label as printed *and* proposes a bucket from world knowledge, graded like any claim, and jurisdiction rides as an attribute.

The finding that came out of running this on a real vault belongs to the whole system rather than to pay stubs: **the `Uncategorized` counter-leg was categorized by the sign of the account leg**, which is asset-centric and inverted for a liability, so a card purchase filed as income. Every statement still posted and reconciled — the liability's own balance was correct — and every income or spending total built on those buckets was polluted. Reconciliation guards the figures a document states; it does not guard the interpretation layered on top. The immediate correction here was to report only *recognized* income and to relabel the spending figure as what it actually measured; the root fix is the kind-aware counter-leg in [categorization-and-spending.md](categorization-and-spending.md). Real data is what exposed it.

## Open

- The net↔deposit link is by amount and date rather than an explicit provenance edge (MON-43). Correct for totals today, less precise for tap-through; reclassifying an already-categorized deposit is the same increment.
- No correction action exists for a mis-balanced stub — it is shown with its finding and is read-only. The human-in-the-loop correction path for the pay-stub shape is a later increment.
- 1099 and other annual tax documents are a **sibling** profile, unbuilt. Their identity is a completeness check across many deposits, not a decomposition of one; do not force them through this shape.
- Recurring-salary detection seeding an inbound obligation is unbuilt; the employer identity and pay dates captured here are its inputs.
- The 401k employer match and composing retirement deductions into a retirement asset and net worth are unbuilt.
- The employer as a first-class **Party** is unbuilt, as is graduating deduction categories from model-proposed to learned-and-confirmed.
