# Data Model Considerations — what the unified model must account for

**State:** partial
**Rules:** ING-40, ING-41, ING-42, ING-43, ING-44, ING-45, ING-46, ING-47, ING-48, ING-49, ING-90
**Invariants touched:** T1, T3, T4, T7 (the trust spine below is their schema form), I1 (currency on every amount), I2 (locale-driven normalization feeds the claims layer), I5 (no US-shaped taxonomy — jurisdiction as an attribute, never as a table), X2

## Rules

### ING-40 — Classification is a claim, not a fact
**State:** unmet
**Code:** product/viva/ledger/events.py:241 (`document_captured` stores the type and its confidence as a claim), product/viva/ingest/reader.py:248 (`_peek_classification` yields `unknown` at 0.0 when the reply does not parse)
**Test:** product/tests/test_reader_two_phase.py::test_classify_unreadable_is_unknown_not_a_guess, product/tests/test_pipeline.py::test_unreconciled_statement_is_conflict_not_posted

1. A document's type comes from a model, carries a confidence, and can be wrong.
2. `unknown` is a first-class type: the document is captured, stored raw and parked rather than discarded, and re-read once a projector exists. *The extraction half is not implemented: a type with no projector is parked straight after the classify pass (product/viva/ingest/reader.py:100-107) and only a projectable type is routed onward (product/viva/ingest/brokerage_projector.py:142), so no generic claim extraction runs, there are no claims for fewer checks to apply to, and no answer stands on one to say so (X2).*
3. A misclassification degrades to a visible conflict — the wrong checks fail loudly — and never to silent corruption.
4. Which checks run for a type is a registry row, not code.

### ING-41 — Three layers: claims, facts, projection
**State:** enforced
**Code:** product/viva/ledger/events.py (`read_recorded`, the claims layer), product/viva/ingest/pipeline.py (`capture_and_ingest` records every model phase), product/viva/ledger/ledger.py (projection rebuilt from the log)
**Test:** product/tests/test_pipeline.py::test_cached_projection_matches_a_fresh_replay, product/tests/test_pipeline.py::test_real_read_stores_the_claims_layer, product/tests/test_reader_two_phase.py::test_each_extract_retry_becomes_its_own_outbound_event, product/tests/test_outbound_record.py::test_configured_and_provider_reported_models_are_recorded_separately

1. The claims layer holds what a model asserted, verbatim, per run, with its model and prompt version. It is append-only.
2. The facts layer holds what survived verification, carrying a grade, the verification result, and provenance pointers.
3. The projection layer is query-shaped and rebuildable at any time from the event log; it is never independently authoritative.
4. Every outbound request is its own recorded claim, including a failed parse that is retried. New records keep the configured route separate from the provider-reported model identity, and token counts are present only when the provider reported usage; records without the model-role marker remain explicitly unclassified.

### ING-42 — An amount is a value and a currency
**State:** enforced-with-exception
**Code:** product/viva/ledger/events.py (currency on the account), product/viva/ingest/statement.py (currency on the statement), product/viva/ledger/projection/core.py (`TxnLine.currency` carries the transaction currency), product/viva/ledger/projection/movements.py (currency on the projected movement)
**Test:** core/tests/test_normalize.py::test_currency_conflict_is_invalid_not_silently_resolved, product/tests/test_postings.py::test_posting_rejects_float, product/tests/test_tool_contract.py::test_income_and_surplus_never_add_or_relabel_different_currencies

1. No field, computation or display assumes one currency.
2. Amounts are exact Decimal; a float raises rather than being coerced.
3. Totals are reported per currency rather than summed across currencies.

**Exception:** `Posting` carries `(account, amount, grade)` and no currency of its own. During replay, the transaction fold carries the sole declared real-account currency onto every line, including synthetic income and expense counter-legs; an ambiguous transaction currency stays empty. The pairing is therefore explicit on projected lines and absent from the stored posting primitive.

### ING-43 — A transaction is a list of postings that sum to zero
**State:** enforced
**Code:** product/viva/ledger/postings.py, product/viva/ledger/events.py:684 (`transaction_recorded`)
**Test:** product/tests/test_postings.py::test_transaction_balances_catches_imbalance, product/tests/test_postings.py::test_split_balances_and_covers_whole

1. A transaction is one or more postings, never a fixed pair, and its postings sum to exactly zero.
2. A split by money — one purchase across several categories — is several postings summing to the whole, each carrying its own grade.
3. An account's balance is the running sum of its postings' amounts.

### ING-44 — Double-entry governs the money; tags govern the meaning
**State:** enforced
**Code:** product/viva/ledger/events.py:706-716 (a category is a partition, a tag is an overlay in its own event type)
**Test:** product/tests/test_tags.py::test_a_tag_never_touches_the_category_partition, product/tests/test_tags.py::test_tag_totals_do_not_sum_to_spending_and_the_report_says_so

1. A category is a partition: exactly one per movement, so the parts sum to the whole.
2. A tag is an overlay: many per movement, overlapping, and tag totals do not sum to spending — a report that shows them says so.
3. Tags live in their own event type, so "tags never leave this device" is an event-level rule rather than a per-field check.

### ING-45 — A measurement, a valuation and an estimate are never dressed as one another
**State:** by-review-with-exception
**Code:** product/viva/ledger/events.py:659 (`position_observed` carries `valuation_class`, defaulting to `measured`)
**Test:** none

1. A figure a statement attests is `measured` and carries its date.
2. A revaluation moves no money, so it never touches a balance and is never posted; unrealized gain is derived on the read side.
3. An answer states which class it stands on and never presents one as another.

**Exception:** `valuation_class` exists only on `PositionObserved`. No other primitive carries the distinction, so for everything else the class is implied by which event wrote it rather than declared. Assertion 3 is unsupported on top of that: no code cite and no test names an answer stating which class it stands on.

### ING-46 — Regional variety is an attribute on a primitive, never a new primitive
**State:** by-review
**Code:** product/viva/ledger/events.py:161 (`jurisdiction` on the account, defaulting to empty rather than to a country), product/viva/ingest/registry.py:43 (a type is a registry row)
**Test:** none

1. Account types, tax concepts and document categories extend to non-US instruments by attribute, not by a parallel table.
2. `jurisdiction` names where the instrument lives — not where the person lives and not its currency — and defaults to empty, meaning nobody has said.
3. A stored aggregate never bakes in a calendar-year assumption; atoms are stored and aggregation happens at query time.

### ING-47 — Observations accumulate; they do not just dedup
**State:** enforced-with-exception
**Code:** product/viva/ingest/raw_store.py:51-61 (the content address is the fingerprint, so the same bytes are one document), product/viva/ingest/statement_projector.py:277 (`_period_already_posted` — the same account and period end, whatever the bytes), product/viva/ingest/paystub_projector.py:100 (a pay stub recognised by the decomposition it would write), product/viva/ingest/statement_projector.py:212 (`_try_corroboration`), :99 (`heal_corroboration`)
**Test:** product/tests/test_pipeline.py::test_reupload_is_duplicate_no_double_post, product/tests/test_pipeline.py::test_a_redownloaded_statement_does_not_post_its_transactions_twice, product/tests/test_pipeline.py::test_a_reissued_statement_for_a_posted_period_is_held_not_posted, product/tests/test_brokerage.py::test_a_redownloaded_brokerage_statement_does_not_post_its_activity_twice, product/tests/test_paystub.py::test_a_second_copy_of_a_stub_is_named_a_duplicate_not_a_missing_deposit, product/tests/test_transfers.py::test_cross_document_corroboration_closes_the_gap, product/tests/test_transfers.py::test_corroboration_heals_in_either_order, product/tests/test_transfers.py::test_a_real_misread_is_not_falsely_corroborated

1. The same real transaction seen again — an overlapping statement, a re-upload, a second document type — merges by fingerprint into one fact, never a second copy.
2. Corroboration raises the grade; conflicting observations become `conflicted`, surfaced and never averaged.
3. A re-upload is recognised by what the document *is* — the account it belongs to and the day its period ends — not by the bytes it arrived as. Institutions do not re-serve identical files, so a guard on the bytes alone recognises almost no real re-upload.
4. A second document covering a posted period with a *different* closing figure is a re-issue, not a duplicate. It is held for a person, because which of the two is true is not the product's to decide.

**Exception:** clause 1 held only for a byte-identical re-upload until the period guard existed; a re-downloaded statement arrived with different bytes and posted a second copy of every movement in it, and for a pay stub that doubled income. What the guard does not cover is a re-periodisation — an institution issuing weekly statements over days a monthly one already covered is not a collision on the period end, and would still double-count. What merges by fingerprint is the document and the movement key derived from it, not an observation set. A fact carries one `Provenance` (product/viva/ledger/events.py:39), so a counterparty document attesting the same movement is recorded as a supplied leg citing that document rather than as a second observation on one record. "Multiple observations of one fact" is true at the ledger level and absent at the field level.

### ING-48 — Transfer links are graded facts
**State:** enforced
**Code:** product/viva/ledger/events.py:297 (`transfer_linked` carries its own `grade` and `evidence`), :316 (`transfer_unlinked` revokes it append-only)
**Test:** product/tests/test_transfers.py::test_auto_link_is_corroborated_and_survives_a_replay, product/tests/test_transfers.py::test_a_link_records_which_rule_decided_it, product/tests/test_transfers.py::test_answer_spending_excludes_transfers

1. A payment from checking to a card is one economic non-event, and the link that says so is itself a fact carrying its own confidence and its own evidence.
2. Neither leg is re-posted, so each statement still reconciles on its own and a linked movement is excluded from spending — a wrong link double-counts spending, which is why the link is graded rather than assumed.

### ING-49 — Completeness is data
**State:** enforced-with-exception
**Code:** product/viva/tools/ledger_audit.py (`check_completeness`), product/viva/tools/ledger_common.py (`_attested_coverage` and `_resolve_window_preset`)
**Test:** product/tests/test_tool_contract.py::test_completeness_counts_the_held_document, product/tests/test_tool_contract.py::test_latest_complete_calendar_month_resolves_to_explicit_dates, product/tests/test_tool_runner.py::test_a_window_reaching_past_what_is_attested_is_clipped_and_says_so, product/tests/test_tool_runner.py::test_a_window_outside_what_is_attested_covers_nothing_and_says_which

1. What is missing is one query rather than an inference: `check_completeness` reports every document held, posted and awaiting review, and the date each account's evidence is good as of.
2. Every aggregate states its coverage honestly — the periods its statements attest, and a caveat naming each account in scope that falls short.
3. The latest complete calendar month is derived from posted coverage and resolves to explicit inclusive dates before an aggregate or movement read runs.

**Exception:** the commitment also had an account carry an *expected cadence* ("monthly statement, ~5th") so that a statement nobody sent is itself a gap. `account_opened` (product/viva/ledger/events.py:160) has no cadence field, and a gap is detectable only where a posted statement's opening fails to continue from the balance held (`GAP`, product/viva/ingest/pipeline_models.py:61). A period with no statement at all is silence rather than a named hole.

### ING-90 — Two timelines per fact: when it happened, and when we learned it
**State:** by-review-with-exception
**Code:** product/viva/ledger/events.py:115-120 (`occurred_at` is value time, as the document dates it), product/viva/ledger/store.py:101 (the store stamps ingestion time as `recorded_at` on append)
**Test:** none

1. Every event carries `occurred_at`, the date the money event happened as its own document dates it.
2. Ingestion time is stamped by the store rather than by the caller, so the two timelines are kept apart and neither can be written as the other.

**Exception:** `recorded_at` is sealed into the record and never read back out — `Ledger.events()` (product/viva/ledger/store.py:136) reconstructs the event body alone, and a rewrite preserves the field without exposing it (product/viva/reset_categorization.py:127). The second timeline is therefore written and not queryable, so "what did I know on this date, provably" is not answerable from the log today.

## Why

The pipeline sketch — classify, extract, verify per type, land in a data layer,
query through tools, retain the document for provenance — is right, with two
refinements that do most of the work.

The first is that classification is a *claim*. It comes from a model, so it can
be wrong, and the design question is what a wrong one costs. If a misclassified
document silently lands in the wrong family, the corruption is invisible; if it
runs the wrong checks, the checks fail loudly and the document is held. Making
`unknown` a first-class type rather than an error state is what lets a document
nobody can read yet be captured, acknowledged, and posted retroactively once a
projector exists — without a re-upload.

The second is that there is no single data layer, there are three. The **claims
layer** is what models asserted, verbatim, per run — immutable, append-only, and
incidentally the mine every future training pair is dug out of. The **facts
layer** is what survived verification: typed records carrying a grade, the trail
of which checks ran, and provenance pointers down to the page. The **projection
layer** is query-shaped and rebuildable from the log at any time. That third
layer is what dissolves the pressure to be comprehensive from day one:
comprehensiveness lives in what events *capture*, while projections expose only
what has so far been chosen to model, and can be re-derived richer later.

Finance everywhere reduces to about ten primitives — Party, Account, Asset,
Transaction, Position, BalanceSnapshot, Obligation, Provision, the
Document/Claim/Fact trust spine, and Tag/Category. Regional variety is
attributes on those primitives and never new ones: a 401(k), an EPF, an ISA and
a superannuation fund are one retirement-kind account with a jurisdiction tag,
and the kind-and-subtype registry is data. Insurance is why Provision is core
rather than an afterthought — a policy is mostly attested non-numeric terms and
almost no transactions, which is the test of whether the model is secretly
transaction-shaped.

Categorization is deliberately two mechanisms rather than one, because a person
does not put a purchase in exactly one bucket and pretending otherwise is a lie
about how people think about money. One purchase can at once be an expense,
groceries, a particular merchant, and birthday-related. When the money genuinely
*divides* — a receipt that is partly groceries and partly a gift — that is a
split by amount, native double-entry, several postings summing to the whole,
each with its own grade. When the *same* money wears several labels at once,
those are orthogonal dimensions, not competing buckets, and they belong in a
many-to-many overlay that is descriptive rather than financial. The overlay never
has to balance, which is exactly why a transaction can carry as many tags as the
person likes without touching the ledger's integrity. The rule that keeps trust
intact: double-entry governs the money — one balanced truth, verifiable — and
tags govern the meaning, freely multiple and user-owned.

The trust spine is what no personal-finance schema has and what this product
exists for. Observations *accumulate* rather than dedup: the same real
transaction seen on an overlapping statement, a re-upload, or from two document
types merges into one fact with multiple observations, and corroboration raises
the grade — while conflicting observations become `conflicted`, surfaced, never
averaged. Corrections are events on facts, so a fact's full history is
replayable and nothing is overwritten. Transfer links are themselves graded
facts carrying their own evidence, because a wrong link double-counts spending.
Completeness is data, so an account's expected cadence turns a gap into a query
and lets every aggregate state its coverage honestly. Bitemporality — when it
happened versus when we learned it — is free if respected from the start and
impossible to retrofit, and it is what makes "what did I know on this date,
provably" answerable.

Three provenance classes have to stay distinct: a statement *measures*, a market
price *values*, a property guess *estimates*. Posting a price change that was
not a cash movement fabricates an event that never happened, so revaluations are
derived presentation views rather than ledger facts.

Regional versatility is concrete rather than aspirational. Amounts are always a
value and a currency, with an account-level default and a per-transaction
override for foreign transactions. Conversion happens at answer time from a rate
the answer must cite and date, and a converted total is an estimate by
provenance class and says so. Jurisdiction hangs off the account, not just
locale off the document, because tax treatment and retirement semantics hang off
it. Fiscal years differ, so "this year" is a question about the asker, which is
an answer-time concern the schema must not pre-empt. And statement conventions —
running-balance passbooks with no period totals, DR/CR columns, combined
multi-account statements — are absorbed by the claims layer being shape-agnostic
plus per-type checks, never by a per-region schema.

## Open

- Whether Provision needs structure beyond topic, text, source and grade, or whether typed coverage modeling — deductibles and limits as amounts — earns its complexity. Real policies decide.
- Category taxonomy seed: a minimal neutral seed versus starting empty and learning everything. The moat is the corrections, not the seed.
- FX rate sources at answer time; the schema slot matters now, the source does not until a second currency is live.
- Escrow inside a mortgage payment: one movement, three economic destinations. Modeled analytically and untested against a real monthly statement.
- Pay-stub deductions that are also facts elsewhere — a retirement contribution appears on the stub and on the retirement statement, two observations of one fact.
- Vesting: owned versus vested is either a position attribute or a provision, and no real document has settled it.
- Joint accounts and households: Party exists so another person's card is representable, but the product stays single-user with multi-party data, and the shared product is a door the schema declines to close.
- Asset, Obligation and Provision have no implementation; the ontology above is ahead of the ledger on those three.
- Generic claim extraction on an `unknown` document (ING-40's second half). Today a type with no projector is parked after the classify pass, so nothing is extracted for fewer checks to apply to.
