# Categorization & Spending — where your money went, and the moat that learns it

**State:** built
**Rules:** MON-13, MON-14, MON-15, MON-16, MON-17, MON-18, MON-93

**Invariants touched:** T1 · T2 · T4 · **M2** · I1 · I5 · X2 · principle 2 · principle 7.

## Rules

### MON-13 — the counter-leg is a function of kind and direction
**State:** enforced
**Code:** product/viva/ledger/postings.py:73 (`counter_account`)
**Test:** product/tests/test_categorize.py::test_counter_account_is_kind_aware

1. Money into a depository account posts its counter-leg to `Income:Uncategorized`; money out to `Expenses:Uncategorized`.
2. A charge on a liability posts to `Expenses:Uncategorized` — a purchase is spending.
3. A payment on a liability posts to `Transfers:Uncategorized` — a debt reduction, never income (product/tests/test_categorize.py::test_card_purchase_is_expense_not_income).

### MON-14 — a category is a graded overlay, appended and never a re-post
**State:** enforced
**Code:** product/viva/ledger/events.py (`category_assigned`); product/viva/ingest/categorize.py (`assign_category`)
**Test:** product/tests/test_categorize.py::test_categorization_survives_a_replay

1. `CategoryAssigned(movement_key, descriptor, category, grade, by)` is append-only, reversible, and keyed to the stable movement key, so it survives a reingest.
2. The projection reads the overlay and moves the movement's counter-leg out of `Uncategorized`; nothing is rewritten.
3. A `by="model"` assignment is graded `unverified`; a `by="human"` one is `verified`, and supersedes it (product/tests/test_categorize.py::test_model_suggestion_is_unverified_human_confirmation_verified).

### MON-15 — Core suggests and confirms; it never auto-applies
**State:** enforced
**Code:** product/viva/ingest/categorize.py (`suggest_categories`)
**Test:** product/tests/test_categorize.py::test_model_suggestion_is_unverified_human_confirmation_verified

1. A model's category is recorded as a claim graded `unverified`, shown as a suggestion against the source, never asserted as fact.
2. The model edge is injected (`suggest_fn`), so the mechanism runs offline.
3. Nothing in Core applies a category on a model's word alone.

### MON-16 — the taxonomy is data, two-level and jurisdiction-neutral
**State:** enforced
**Code:** merchant/merchantcore/taxonomy.py (`PRIMARY_CATEGORIES`, 16 labels); product/viva/ingest/categorize.py (`SEED_CATEGORIES`)
**Test:** product/tests/test_category_identity.py::test_the_known_vocabulary_is_what_every_minting_path_is_offered

1. The primary set is a controlled list held in one file and is the single source of truth for it.
2. A subcategory is the finer slice, and any string is a valid label — no country-shaped table anywhere.
3. `spending_by_category` groups by primary; `spending_by_subcategory` is the finer view.

### MON-17 — every assignment captures the raw descriptor
**State:** enforced
**Code:** product/viva/ledger/events.py:341 (`descriptor` on the event body)
**Test:** product/tests/test_categorize.py::test_spending_by_category_and_assignment

1. Each `CategoryAssigned` records the movement's raw merchant string alongside the category.
2. Merchant learning is therefore a projection over events already written, with nothing re-read and nothing re-done.

### MON-18 — the derived category is read through one funnel
**State:** enforced
**Code:** product/viva/ledger/projection/categories.py (`derived_category`)
**Test:** product/tests/test_merchants.py::test_per_transaction_override_beats_the_merchant_rule

1. A movement's effective category is its human or model per-transaction override, else the strongest catalog record among its canonical and legacy merchant keys, else its unverified import default, else `Uncategorized`. Import applies an already-installed exact alias match before writing the default and without a model call. The default is movement-scoped and intentionally yields to later merchant knowledge; a person's correction still wins over both.
2. Labels are canonicalized at that one funnel, so one alias ruling corrects every aggregate at once.

### MON-93 — the spending answer says what its total is made of
**State:** enforced-with-exception
**Code:** product/viva/answer.py:191 (`answer_spending`); product/viva/tools/ledger_aggregates.py:211 (the uncategorized caveat), :232 (the grade over the movements counted)
**Test:** product/tests/test_categorize.py::test_answer_spending_reports_categories

1. The spending answer carries a grade — how much of it is confirmed versus model-suggested — and provenance, the source lines.
2. `answer_spending` reports the uncategorized share honestly, as a caveat beside the total rather than folded into it (product/tests/test_tool_runner.py::test_an_amount_inside_a_caveat_is_written_like_every_other_amount).
3. A total made of `unverified` guesses says so.

**Exception:** the confirmed-versus-suggested *mix* of assertion 1 is not computed anywhere. `answer_spending` returns an `Answer` with `grade=None` and no provenance, and the tool read states a single grade — the weakest of the counted movements' grades (product/viva/tools/ledger_aggregates.py:232) — so a total holding one unverified assignment reads `unverified`, which is assertion 3, and how much of it is confirmed is never stated. The uncategorized caveat on the tool read is written only where the read is grouped by category (:212).

## Why

Every non-account leg once landed in `Uncategorized`, and the bucket's sign was asset-centric: a card *purchase* raised what was owed, so it filed as **income**. Every statement still reconciled — the liability's own balance was correct — but any income or spending total built on those buckets was polluted. Reconciliation guards the figures a document states; it does not guard the interpretation layered on top. Making the counter-leg a function of `(kind, direction)` is the prerequisite everything else sits on, and it was retroactive for free: the user-facing aggregates re-derive from the immutable movement legs at query time, so every already-ingested statement reports correctly with no reingest. Only the raw `*:Uncategorized` account balances keep their old bucket, which is cosmetic and read by no answer.

The kind-aware fix was a property of one path, and a later path did not inherit it. `query_ledger`'s transactions summary, written much later against the movement rows directly, split money in from money out by the posting's sign, and so reported every card purchase as money *received* — the right magnitude, the right records and the right grade under a false description. Direction is now a named derivation with the account's kind deciding it (M2), and a reader holding no kind raises rather than falling back to the sign. That rule was re-broken within three days of being written, by the streams module the rhythm detector is built on, which is why it is a standing invariant rather than a note beside the code.

A category is an *overlay*, not a re-post, for the same reason a transfer link is: per-statement reconciliation must keep holding, and merging or rewriting postings breaks the gate that makes any of it trustworthy. Keeping it an append-only event keyed to content also means a reingest cannot lose it.

The suggest-and-confirm split is the moat. Installed knowledge can populate spending immediately at `corroborated`, while a model may later propose knowledge for an honest miss; a person's confirmation remains the authoritative event and the one thing a model call cannot regenerate. That is also why the descriptor is captured on every assignment: it costs nothing at the time and buys the entire merchant layer later as a projection over events already held — the categorizing done by using the product *is* the training signal. Because a merchant's category is a **prior, not truth**, a person's override always wins locally, and the shared layer stays impersonal: structurally justified normalized identity candidates and a linted example, never amounts or raw descriptors (T9).

Exclusion belongs to nature rather than to the category. "Spending excludes transfers" once held only for *linked* transfers, so a movement categorized `transfers` or `loan_payments` was still counted, and one label covered two opposite natures. The rule generalized to derived movement nature, with the category demoted to a suggestion rung — see MON-1 and MON-3 in [honest-aggregates-and-the-learning-loop.md](honest-aggregates-and-the-learning-loop.md).

## Open

- The live model categorizer is injected but not wired to a real model call on this path.
- Merchant normalization, permanent ids, reviewed exact aliases and merchant→category auto-apply are built locally. Known shipped or learned merchants categorize during statement import without a model call; unknown movements receive replaceable defaults instead of routine import questions. No fuzzy identity inference or alias-approval UI exists, and the networked commons registry remains unbuilt.
- Amount-splits — one movement divided across categories, still balancing — are a separate overlay, unbuilt, and compose with the single-category work.
- The external **Party** — a merchant, an employer, a landlord — is unbuilt. External counterparty attribution (a payment to a real person or biller is a real outflow, not a transfer) is the categorization-side of transfer-linking, and the same descriptor-capturing events seed it.
- Per-transaction custom categories for peer descriptors: [local-categorization-and-custom-categories.md](local-categorization-and-custom-categories.md).
