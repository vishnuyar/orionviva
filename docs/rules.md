# Rules — the index of what is true today

**State:** built
**Rules:** none — this file defines no rule; it indexes every rule the other documents define.

Every rule in this repository is listed once, below, with the state it is in
and the test that pins it. This file is the index and nothing else:

- **The *why* for any rule lives in the document named beside it.** A rule is a
  checkable assertion; the argument that produced it, and what it cost, stay
  where the argument was made.
- **History lives in git and in the ADRs.** An ADR records the reasoning that
  settled a one-way door — the alternatives, the tradeoff, what would reverse
  it. It is not a report on current behaviour, and a decision standing in an
  ADR is not a claim that the code has met it. What the code has met is the
  *state* column here.
- **No entry in this file carries a date.** A dated claim rots silently; a
  state and a test do not.

A state says *how the rule is known*, not how strongly anyone believes it. The
first two are the ones to read carefully: both mean the code does this today,
and only one of them will still mean it next month without anybody looking.

| State | Means |
| --- | --- |
| enforced | The code does this, and a named test holds it there. |
| enforced *(exception)* | The same, except where the document's own **Exception** block says otherwise. |
| by-review | The code does this, a person read it and said so, and no test holds it. True today; free to stop being true silently. A debt, and the list of them should shrink. |
| by-review *(exception)* | The same, with an **Exception** block. |
| **unmet** | The mechanism the rule describes is not built. |
| untestable | The rule is real and no test could hold code to it. Permanent, not a debt. |
| **contradicted** | The code does something the rule forbids, or the rule states something the code does not do. Listed in full at the end. |

`by-review` and `untestable` both mean no test — but they are opposite
requests. One is asking for a test nobody has written; the other is saying not
to bother. A prohibition met by the absence of the thing it forbids counts as
`by-review`, provided its **Code** line says which search established the
absence.

Two lists follow the table: every rule no test pins, and every rule the code
contradicts, with the file and line on both sides.

Nothing here is maintained by hand alone. `test_docs_track_the_code.py` holds
this file to the rule blocks it was drawn from, and holds each state to the
evidence beside it — an `enforced` rule that cites no test, or a `by-review`
rule that cites one, fails the build.

---

## Trust

The nine trust invariants. Every other rule in this file answers to them.

| Rule | Name | State | Doc | Test |
| --- | --- | --- | --- | --- |
| **T1** | Provenance, grade, exactness and boundary on every figure | enforced *(exception)* | [design-invariants.md](design-invariants.md) | `test_a_figure_that_states_no_set_fills_no_hole_asking_for_one` |
| **T2** | Arithmetic is deterministic; models never certify | enforced | [design-invariants.md](design-invariants.md) | `test_float_poison_rejected` |
| **T3** | Capture-first | enforced *(exception)* | [design-invariants.md](design-invariants.md) | `test_put_is_content_addressed` +2 |
| **T4** | Everything is an event | enforced *(exception)* | [design-invariants.md](design-invariants.md) | `test_the_chain_verifies_without_the_passphrase` |
| **T5** | No plaintext phase, anywhere, ever | enforced | [design-invariants.md](design-invariants.md) | `test_nothing_readable_at_rest` |
| **T6** | Nothing leaves silently | by-review | [design-invariants.md](design-invariants.md) | — |
| **T7** | IDs are permanent; fingerprints are versioned | **contradicted** | [design-invariants.md](design-invariants.md) | `test_same_bytes_dedup` |
| **T8** | Models are pinned, provider-swappable, and never trusted | enforced *(exception)* | [design-invariants.md](design-invariants.md) | `test_active_versions_are_frozen` |
| **T9** | The personal/impersonal boundary is drawn at package edges | enforced *(exception)* | [design-invariants.md](design-invariants.md) | `test_a_brand_a_grammar_named_crosses_only_where_a_published_format_agrees` |

## Internationalization

No figure, schema or surface may assume one country.

| Rule | Name | State | Doc | Test |
| --- | --- | --- | --- | --- |
| **I1** | Currency is first-class | enforced *(exception)* | [design-invariants.md](design-invariants.md) | `test_an_amount_whose_currency_is_unknown_is_not_given_one` |
| **I2** | Normalization is locale-aware and versioned | enforced *(exception)* | [design-invariants.md](design-invariants.md) | `test_german_comma_decimal` |
| **I3** | Trust is earned per locale | enforced *(exception)* | [design-invariants.md](design-invariants.md) | `test_scorecards_group_and_calibrate` |
| **I4** | Ground truth carries locale metadata from day one | enforced | [design-invariants.md](design-invariants.md) | `test_german_amount_cross_format` |
| **I5** | No US-shaped taxonomy | enforced | [design-invariants.md](design-invariants.md) | `test_the_pack_loads_and_every_kind_is_jurisdiction_tagged` |
| **I6** | The admission exam is pack-extensible | by-review | [design-invariants.md](design-invariants.md) | — |

## Accounting model

What the ledger records, and which way the money went.

| Rule | Name | State | Doc | Test |
| --- | --- | --- | --- | --- |
| **M1** | Cash-flow over accrual, when in doubt | enforced | [design-invariants.md](design-invariants.md) | `test_unrealized_gain_is_a_derived_as_of_view_not_a_ledger_fact` |
| **M2** | Which way the money went is decided by the account's kind, in one place | enforced | [design-invariants.md](design-invariants.md) | `test_a_stream_cannot_be_built_without_the_account_kind` |

## Experience

What a person may be asked to know, see and confirm.

| Rule | Name | State | Doc | Test |
| --- | --- | --- | --- | --- |
| **X1** | Target user skill: "can install an app" | **unmet** | [design-invariants.md](design-invariants.md) | — |
| **X2** | Uncertainty is visible, never decorative | enforced *(exception)* | [design-invariants.md](design-invariants.md) | `test_every_grade_a_figure_can_carry_has_a_reviewed_sentence` |
| **X3** | Irreversible actions wait for an explicit yes | enforced | [design-invariants.md](design-invariants.md) | `test_a_proposal_that_is_never_confirmed_leaves_the_ledger_untouched` |

## SPINE — how the documents themselves work

Rules about this folder: state, order, supersession, and when an ADR is owed.

| Rule | Name | State | Doc | Test |
| --- | --- | --- | --- | --- |
| **SPINE-1** | A document names no date | enforced | [README.md](README.md) | `test_a_document_names_no_date` |
| **SPINE-2** | Every design doc and ADR names the invariants it touches | untestable | [README.md](README.md) | — |
| **SPINE-3** | No per-institution parsers | enforced | [README.md](README.md) | `test_non_checking_is_parked_not_discarded` |
| **SPINE-4** | Authenticity uses no chain, token or on-chain mechanism | enforced | [README.md](README.md) | `test_chain_detects_tampering` |
| **SPINE-5** | Document order lives here and nowhere else | **unmet** | [reading-guide.md](reading-guide.md) | — |
| **SPINE-6** | Superseded stays, historical is fenced, neither is deleted | **unmet** | [reading-guide.md](reading-guide.md) | — |
| **SPINE-7** | The eval harness ships before the first user who is not the author | enforced *(exception)* | [implementation-roadmap.md](implementation-roadmap.md) | `test_the_refusal_rate_is_measured_over_the_answers_a_person_got` |
| **SPINE-8** | The trust trial runs alongside breadth, never in front of it | untestable | [implementation-roadmap.md](implementation-roadmap.md) | — |
| **SPINE-9** | The phases past the product are gated on earned trust, not on a calendar | untestable | [implementation-roadmap.md](implementation-roadmap.md) | — |
| **SPINE-10** | A one-way door gets an ADR before product code exists | **unmet** | [decisions/README.md](decisions/README.md) | — |
| **SPINE-11** | A row in the index states a decision, never that it is built | **unmet** | [decisions/README.md](decisions/README.md) | — |
| **SPINE-12** | An invariant joins the checklist by deliberate decision | **unmet** | [design-invariants.md](design-invariants.md) | — |
| **SPINE-13** | A document declares the rules it defines | enforced | [README.md](README.md) | `test_a_document_declares_the_rules_it_defines` |
| **SPINE-14** | Every invariant a document cites is one that exists | enforced | [README.md](README.md) | `test_an_invariant_a_document_cites_is_one_that_exists` |

## ADR — the decisions

One rule per decision record. An ADR states what was decided; the rule states what that decision obliges today.

| Rule | Name | State | Doc | Test |
| --- | --- | --- | --- | --- |
| **ADR-001** | Cloud frontier models by default, under the user's own key, with the local path architecturally open | enforced *(exception)* | [decisions/ADR-001-hybrid-model-strategy.md](decisions/ADR-001-hybrid-model-strategy.md) | `test_continuation_stitches_and_drops_images` |
| **ADR-002** | The project is MIT-licensed | by-review | [decisions/ADR-002-mit-license.md](decisions/ADR-002-mit-license.md) | — |
| **ADR-003** | Originals, model I/O and verification trails are captured before parsing and kept forever | enforced *(exception)* | [decisions/ADR-003-raw-capture-doctrine.md](decisions/ADR-003-raw-capture-doctrine.md) | `test_put_is_content_addressed` |
| **ADR-004** | All state is an append-only hash chain, anchored to two independent external clocks | enforced *(exception)* | [decisions/ADR-004-append-only-log-and-anchoring.md](decisions/ADR-004-append-only-log-and-anchoring.md) | `test_chain_detects_tampering` |
| **ADR-005** | No plaintext phase, and every sealed object carries a versioned envelope | enforced *(exception)* | [decisions/ADR-005-encryption-from-commit-one.md](decisions/ADR-005-encryption-from-commit-one.md) | `test_unknown_version_refused` |
| **ADR-006** | Nothing transmits itself, and diagnostics leave only by the person's own hand | by-review *(exception)* | [decisions/ADR-006-zero-exfiltration.md](decisions/ADR-006-zero-exfiltration.md) | — |
| **ADR-007** | Two fields, two jobs: a permanent random identity and a versioned content fingerprint | **contradicted** | [decisions/ADR-007-record-identity.md](decisions/ADR-007-record-identity.md) | `test_same_bytes_dedup` |
| **ADR-008** | The public promises are an explicit inventory, and nothing may promise more than it holds | untestable | [decisions/ADR-008-public-promise-inventory.md](decisions/ADR-008-public-promise-inventory.md) | — |
| **ADR-009** | Contributions come in under the Developer Certificate of Origin | by-review | [decisions/ADR-009-dco-contributions.md](decisions/ADR-009-dco-contributions.md) | — |
| **ADR-010** | Models extract and converse; they never certify | enforced | [decisions/ADR-010-verification-never-in-weights.md](decisions/ADR-010-verification-never-in-weights.md) | `test_float_poison_rejected` |
| **ADR-011** | A hosted tier may store ciphertext and never compute on it | **unmet** | [decisions/ADR-011-blind-host-tier.md](decisions/ADR-011-blind-host-tier.md) | — |
| **ADR-012** | Two enumerated outbound flows, a whitelisted envelope, and a model that selects and words but never decides | **unmet** | [decisions/ADR-012-the-interview-model-boundary.md](decisions/ADR-012-the-interview-model-boundary.md) | `test_a_jurisdiction_scoped_question_does_not_travel` |
| **ADR-013** | A run holds a ledger of what it established, and an answer may say only what is in it | enforced *(exception)* | [decisions/ADR-013-the-shape-before-the-data.md](decisions/ADR-013-the-shape-before-the-data.md) | `test_a_figure_that_states_no_set_fills_no_hole_asking_for_one` |

## MON — money: nature, categories, transfers, net worth, identity

What counts as spending, what a category is, how two accounts are recognized as one, and what a net-worth point may say.

| Rule | Name | State | Doc | Test |
| --- | --- | --- | --- | --- |
| **MON-1** | the nature precedence ladder | enforced | [honest-aggregates-and-the-learning-loop.md](honest-aggregates-and-the-learning-loop.md) | `test_a_ruling_outranks_a_description_that_names_one_of_your_accounts` |
| **MON-2** | a nature says which rung decided it | enforced | [honest-aggregates-and-the-learning-loop.md](honest-aggregates-and-the-learning-loop.md) | `test_excluded_movements_explain_themselves` |
| **MON-3** | spending is shape and nature together | enforced | [honest-aggregates-and-the-learning-loop.md](honest-aggregates-and-the-learning-loop.md) | `test_transfers_never_appear_as_a_spending_line_item` |
| **MON-4** | weak evidence excludes the money and says so | enforced | [honest-aggregates-and-the-learning-loop.md](honest-aggregates-and-the-learning-loop.md) | `test_a_suggested_implication_is_provisional_not_silent` |
| **MON-5** | a ruling whose legs disagree is mixed, and is neither counted nor dropped | enforced | [honest-aggregates-and-the-learning-loop.md](honest-aggregates-and-the-learning-loop.md) | `test_a_compound_payment_is_neither_counted_nor_dropped` |
| **MON-6** | every spending aggregate is on the nature predicate | enforced | [honest-aggregates-and-the-learning-loop.md](honest-aggregates-and-the-learning-loop.md) | `test_currency_and_category_partition_the_same_spending_population` |
| **MON-7** | which way the money went has one derivation (M2) | enforced | [honest-aggregates-and-the-learning-loop.md](honest-aggregates-and-the-learning-loop.md) | `test_a_card_purchase_reads_as_money_out` |
| **MON-8** | the own-account rung is looser than the auto-link bar, deliberately | enforced | [honest-aggregates-and-the-learning-loop.md](honest-aggregates-and-the-learning-loop.md) | `test_an_asserted_account_does_not_make_its_own_payments_internal` |
| **MON-9** | nature is derived, and no event says it | by-review | [honest-aggregates-and-the-learning-loop.md](honest-aggregates-and-the-learning-loop.md) | — |
| **MON-10** | a reset never destroys a person's rulings | enforced | [honest-aggregates-and-the-learning-loop.md](honest-aggregates-and-the-learning-loop.md) | `test_reset_drops_model_categorization_but_keeps_my_rulings` |
| **MON-11** | abstract the read side early, the write side late | untestable | [honest-aggregates-and-the-learning-loop.md](honest-aggregates-and-the-learning-loop.md) | — |
| **MON-12** | route on the registry, not on the shape of the data | untestable | [honest-aggregates-and-the-learning-loop.md](honest-aggregates-and-the-learning-loop.md) | — |
| **MON-13** | the counter-leg is a function of kind and direction | enforced | [categorization-and-spending.md](categorization-and-spending.md) | `test_counter_account_is_kind_aware` |
| **MON-14** | a category is a graded overlay, appended and never a re-post | enforced | [categorization-and-spending.md](categorization-and-spending.md) | `test_categorization_survives_a_replay` |
| **MON-15** | Core suggests and confirms; it never auto-applies | enforced | [categorization-and-spending.md](categorization-and-spending.md) | `test_model_suggestion_is_unverified_human_confirmation_verified` |
| **MON-16** | the taxonomy is data, two-level and jurisdiction-neutral | enforced | [categorization-and-spending.md](categorization-and-spending.md) | `test_the_known_vocabulary_is_what_every_minting_path_is_offered` |
| **MON-17** | every assignment captures the raw descriptor | enforced | [categorization-and-spending.md](categorization-and-spending.md) | `test_spending_by_category_and_assignment` |
| **MON-18** | the derived category is read through one funnel | enforced | [categorization-and-spending.md](categorization-and-spending.md) | `test_per_transaction_override_beats_the_merchant_rule` |
| **MON-19** | a category partitions, a tag overlays | enforced | [categories-and-tags.md](categories-and-tags.md) | `test_tag_totals_do_not_sum_to_spending_and_the_report_says_so` |
| **MON-20** | the alias maps are built during replay, not per lookup | by-review | [categories-and-tags.md](categories-and-tags.md) | — |
| **MON-21** | resolution is a recorded ruling, never a similarity score | enforced | [categories-and-tags.md](categories-and-tags.md) | `test_two_labels_for_one_thing_split_a_total_until_they_are_ruled` |
| **MON-22** | a personal category never reaches a shared surface | enforced | [local-categorization-and-custom-categories.md](local-categorization-and-custom-categories.md) | `test_export_catalog_is_linted_and_carries_no_amounts` |
| **MON-23** | a category exists by being used | enforced | [local-categorization-and-custom-categories.md](local-categorization-and-custom-categories.md) | `test_a_vault_with_no_seed_is_shown_exactly_what_it_uses` +1 |
| **MON-24** | the side is decided by the account's kind, never by the sign of a balance | enforced | [net-worth.md](net-worth.md) | `test_a_card_lands_on_the_liability_side` |
| **MON-25** | a liability's own magnitude is emitted as `owed`, never as `balance` | enforced | [net-worth.md](net-worth.md) | `test_no_read_states_what_is_owed_as_what_is_held` +1 |
| **MON-26** | every point names its stalest input, and a composed line says when its parts differ | enforced | [net-worth.md](net-worth.md) | `test_every_point_names_its_stalest_input` |
| **MON-27** | incompleteness is stated, never absorbed | enforced | [net-worth.md](net-worth.md) | `test_a_point_is_not_complete_while_a_document_sits_held` |
| **MON-28** | cost is never presented as value, and no model is involved | by-review | [net-worth.md](net-worth.md) | — |
| **MON-29** | a holding is a dated measurement, never a posting | enforced | [positions-and-investments.md](positions-and-investments.md) | `test_brokerage_reconciles_and_records_positions_as_measurements` |
| **MON-30** | the internal tally is a hard gate | enforced | [positions-and-investments.md](positions-and-investments.md) | `test_a_misread_holding_fails_the_tally_and_is_held` |
| **MON-31** | the cash flow reconciles when the statement reports it | enforced | [positions-and-investments.md](positions-and-investments.md) | `test_cash_flow_reconciles_and_recognizes_income_fees_gains` |
| **MON-32** | activity counter-legs, and a contribution counted once | enforced | [positions-and-investments.md](positions-and-investments.md) | `test_a_contribution_ties_to_the_funding_account` |
| **MON-33** | a holdings figure is one snapshot, not a composition across statements | enforced | [positions-and-investments.md](positions-and-investments.md) | `test_a_holding_the_newest_statement_no_longer_lists_is_no_longer_held` |
| **MON-34** | one composition, dated by the oldest and graded by the weakest | enforced | [positions-and-investments.md](positions-and-investments.md) | `test_one_account_reads_the_same_from_every_read_that_states_it` |
| **MON-35** | the sweep is cash, decided by which reading closes the tally | enforced | [positions-and-investments.md](positions-and-investments.md) | `test_sweep_counted_once_when_the_cash_line_already_includes_it` |
| **MON-36** | an optional field that cannot be read is unknown, never fatal | enforced | [positions-and-investments.md](positions-and-investments.md) | `test_missing_cost_basis_is_absent_not_invented` |
| **MON-37** | a pay stub is a divergent profile, selected as data | enforced | [pay-stubs-and-income.md](pay-stubs-and-income.md) | `test_pay_stub_is_a_divergent_projectable_profile` |
| **MON-38** | the identity is `gross − Σ deductions = net`, and a failure holds | enforced | [pay-stubs-and-income.md](pay-stubs-and-income.md) | `test_paystub_identity` |
| **MON-39** | the decomposition explains a deposit and counts income once | enforced | [pay-stubs-and-income.md](pay-stubs-and-income.md) | `test_paystub_decomposes_the_deposit_income_counted_once` |
| **MON-40** | either arrival order works | enforced | [pay-stubs-and-income.md](pay-stubs-and-income.md) | `test_paystub_without_deposit_waits_then_heals` |
| **MON-41** | deductions go into universal buckets | enforced | [pay-stubs-and-income.md](pay-stubs-and-income.md) | `test_paystub_decomposes_the_deposit_income_counted_once` |
| **MON-42** | income means attributed income | enforced | [pay-stubs-and-income.md](pay-stubs-and-income.md) | `test_income_is_counted_once_and_a_stub_awaiting_its_deposit_is_held` |
| **MON-43** | the net leg cites the specific deposit | **unmet** | [pay-stubs-and-income.md](pay-stubs-and-income.md) | — |
| **MON-44** | a question is a read-side projection, and answering uses the writers that exist | enforced | [the-question-queue.md](the-question-queue.md) | `test_the_queue_introduces_no_new_event_type` |
| **MON-45** | ranked by consequence, with stable ids | enforced | [the-question-queue.md](the-question-queue.md) | `test_questions_are_ranked_by_what_answering_moves` |
| **MON-46** | a question is raised at the most general unit that is still honest | enforced | [the-question-queue.md](the-question-queue.md) | `test_answering_a_nature_question_settles_the_merchant_and_stops_asking` |
| **MON-47** | silence by ranking, never by hiding | enforced | [the-question-queue.md](the-question-queue.md) | `test_the_tail_is_summarized_never_dropped` |
| **MON-48** | question text is a deterministic template from the persona pack | enforced | [the-question-queue.md](the-question-queue.md) | `test_question_text_no_longer_lives_in_code` |
| **MON-49** | every question declares what structure an answer has | enforced | [the-question-queue.md](the-question-queue.md) | `test_the_model_never_supplies_a_figure` |
| **MON-50** | a substantive answer has no button payload | enforced | [the-question-queue.md](the-question-queue.md) | `test_a_reply_she_could_not_read_leaves_the_question_where_it_was` |
| **MON-51** | confirmation is an explicit typed decision (X3) | enforced | [the-question-queue.md](the-question-queue.md) | `test_an_answer_that_would_open_an_account_is_proposed_before_it_is_written` |
| **MON-52** | a nature question is raised only where the evidence is weak | enforced | [the-question-queue.md](the-question-queue.md) | `test_an_ordinary_known_merchant_is_never_asked_about`, `test_import_defaults_peer_payments_before_asking_questions` |
| **MON-53** | a rhythm question is one proposal per counterparty and direction, licensed by the catalog | enforced | [the-question-queue.md](the-question-queue.md) | `test_a_standing_prior_raises_one_grouped_proposal_per_pair` |
| **MON-54** | a stake is money already measured | enforced | [the-question-queue.md](the-question-queue.md) | `test_a_question_is_ranked_on_money_already_measured` |
| **MON-55** | a cash withdrawal is a spend until an unexplained asset says otherwise | **unmet** | [the-question-queue.md](the-question-queue.md) | — |
| **MON-56** | a link is an overlay, and exclusion is derived on the read side | enforced | [transfer-links-and-cross-document-corroboration.md](transfer-links-and-cross-document-corroboration.md) | `test_internal_transfer_auto_links_and_excludes_from_spending` |
| **MON-57** | a link references a stable movement key, not an event id | enforced | [transfer-links-and-cross-document-corroboration.md](transfer-links-and-cross-document-corroboration.md) | `test_auto_link_is_corroborated_and_survives_a_replay` |
| **MON-58** | decisive auto-links, ambiguous asks, ties are refused | enforced | [transfer-links-and-cross-document-corroboration.md](transfer-links-and-cross-document-corroboration.md) | `test_ambiguous_amount_is_suggested_not_auto_linked` |
| **MON-59** | the account evidence is the gate and the printed date is only a discriminator | enforced | [transfer-links-and-cross-document-corroboration.md](transfer-links-and-cross-document-corroboration.md) | `test_the_printed_date_never_links_on_its_own` |
| **MON-60** | genericness is measured, never listed | enforced | [transfer-links-and-cross-document-corroboration.md](transfer-links-and-cross-document-corroboration.md) | `test_a_generic_word_no_longer_auto_links_anything` |
| **MON-61** | the printed date is read without knowing the country | enforced | [transfer-links-and-cross-document-corroboration.md](transfer-links-and-cross-document-corroboration.md) | `test_the_date_is_read_without_knowing_the_country` |
| **MON-62** | a link records the rule that fired, never the value it matched | enforced | [transfer-links-and-cross-document-corroboration.md](transfer-links-and-cross-document-corroboration.md) | `test_a_link_records_which_rule_decided_it` |
| **MON-63** | a counterparty may supply a leg a statement's read dropped | enforced | [transfer-links-and-cross-document-corroboration.md](transfer-links-and-cross-document-corroboration.md) | `test_cross_document_corroboration_closes_the_gap` |
| **MON-64** | a movement joins at most one transfer, and dead questions stop being asked | enforced | [transfer-links-and-cross-document-corroboration.md](transfer-links-and-cross-document-corroboration.md) | `test_confirming_one_removes_the_shared_movement_from_others` |
| **MON-65** | both legs must be ingested own accounts | by-review | [transfer-links-and-cross-document-corroboration.md](transfer-links-and-cross-document-corroboration.md) | — |
| **MON-66** | the date window is not the dial; the evidence is | enforced | [transfer-links-and-cross-document-corroboration.md](transfer-links-and-cross-document-corroboration.md) | `test_narrowing_the_window_does_not_unlink_anything` |
| **MON-67** | detection runs over a vault that already exists | enforced | [transfer-links-and-cross-document-corroboration.md](transfer-links-and-cross-document-corroboration.md) | `test_sweep_links_previously_ingested_statements` |
| **MON-68** | identity is signals, not a label | enforced | [account-identity-and-entity-resolution.md](account-identity-and-entity-resolution.md) | `test_same_number_different_labels_are_one_account` |
| **MON-69** | the account key is the anchor, and a readable number decides | enforced | [account-identity-and-entity-resolution.md](account-identity-and-entity-resolution.md) | `test_two_readable_numbers_are_two_accounts_and_nobody_is_asked` |
| **MON-70** | one case is ambiguous, and only that one is asked about | enforced | [account-identity-and-entity-resolution.md](account-identity-and-entity-resolution.md) | `test_ambiguous_identity_is_held_then_learned_as_new` |
| **MON-71** | an ambiguous statement is held, and the ruling teaches the map | enforced | [account-identity-and-entity-resolution.md](account-identity-and-entity-resolution.md) | `test_ambiguous_identity_merge_learns_the_alias` |
| **MON-72** | an account carries an identity set | enforced | [account-identity-and-entity-resolution.md](account-identity-and-entity-resolution.md) | `test_ambiguous_identity_merge_learns_the_alias` |
| **MON-73** | a person and their accounts | **unmet** | [account-identity-and-entity-resolution.md](account-identity-and-entity-resolution.md) | — |
| **MON-74** | transactions display in value-time order | enforced | [account-identity-and-entity-resolution.md](account-identity-and-entity-resolution.md) | `test_transactions_sorted_by_date_after_backfill` |
| **MON-75** | subcategory stays in the partition | enforced | [categories-and-tags.md](categories-and-tags.md) | `test_two_spellings_of_one_subcategory_are_one_line_in_a_report` |
| **MON-76** | enrichment never suggests a tag | by-review | [categories-and-tags.md](categories-and-tags.md) | — |
| **MON-77** | tags start fresh; existing labels are left alone | untestable | [categories-and-tags.md](categories-and-tags.md) | — |
| **MON-78** | both scopes, and a union rather than an override | enforced | [categories-and-tags.md](categories-and-tags.md) | `test_a_movement_tag_and_a_merchant_tag_are_a_union_not_an_override` |
| **MON-79** | tags live in their own event type | enforced | [categories-and-tags.md](categories-and-tags.md) | `test_tags_live_in_their_own_event_type_so_t9_is_one_rule` |
| **MON-80** | the complete set is re-asserted; last write wins | enforced | [categories-and-tags.md](categories-and-tags.md) | `test_the_complete_set_is_recorded_so_removing_a_tag_is_appending` |
| **MON-81** | tags alias in their own vocabulary | enforced | [categories-and-tags.md](categories-and-tags.md) | `test_tags_are_normalised_and_alias_separately_from_categories` |
| **MON-82** | punctuation folds deterministically; nothing past it folds without a ruling | enforced | [categories-and-tags.md](categories-and-tags.md) | `test_punctuation_is_one_label_and_everything_past_it_is_two` |
| **MON-83** | a fold nobody was asked about is reported | enforced | [categories-and-tags.md](categories-and-tags.md) | `test_a_run_can_say_which_spellings_it_folded` |
| **MON-84** | a model may propose a fold and may never apply one | enforced | [categories-and-tags.md](categories-and-tags.md) | `test_a_seed_label_never_displaces_one_a_person_minted` |
| **MON-85** | net worth is a curve, defined at every date in range | enforced | [net-worth.md](net-worth.md) | `test_one_statement_gives_one_point` |
| **MON-86** | trust the person; provable-versus-not is an audience question | enforced | [net-worth.md](net-worth.md) | `test_both_figures_are_reported_the_whole_total_and_the_provable_part` |
| **MON-87** | two different unknowns, and only one is a trust problem | enforced | [net-worth.md](net-worth.md) | `test_a_liability_from_cash_flow_alone_is_refused_and_named` |
| **MON-88** | reuse the grade ladder; do not invent an issued/asserted badge | enforced | [net-worth.md](net-worth.md) | `test_provable_is_the_existing_grade_not_a_new_badge` |
| **MON-89** | subtotal per currency; never convert | enforced | [net-worth.md](net-worth.md) | `test_two_currencies_give_two_subtotals_and_no_grand_total` |
| **MON-90** | a peer descriptor is ruled per transaction, never everywhere | enforced | [local-categorization-and-custom-categories.md](local-categorization-and-custom-categories.md) | `test_a_peer_payment_is_scoped_to_itself_not_a_rule` |
| **MON-91** | a custom category is personal, and what crosses to a model is the shareable part of the vocabulary | enforced | [local-categorization-and-custom-categories.md](local-categorization-and-custom-categories.md) | `test_the_known_vocabulary_is_what_every_minting_path_is_offered` |
| **MON-92** | a per-transaction assignment can say what a movement *is* | enforced | [local-categorization-and-custom-categories.md](local-categorization-and-custom-categories.md) | `test_a_human_ruling_beats_the_implication` |
| **MON-93** | the spending answer says what its total is made of | enforced *(exception)* | [categorization-and-spending.md](categorization-and-spending.md) | `test_answer_spending_reports_categories` |

## PROJ — projections, the tool registry, and the shape of an answer

How a read is bounded, what a figure declares, and how a sentence is built from holes nothing but the ledger may fill.

| Rule | Name | State | Doc | Test |
| --- | --- | --- | --- | --- |
| **PROJ-1** | the shape is committed before anything is read | enforced | [projection-decomposition-and-the-tool-registry.md](projection-decomposition-and-the-tool-registry.md) | `test_the_shape_is_committed_before_anything_is_read` |
| **PROJ-2** | a model writes no digits, and every clause carries a hole | enforced | [projection-decomposition-and-the-tool-registry.md](projection-decomposition-and-the-tool-registry.md) | `test_no_words_in_a_shape_may_carry_a_digit` |
| **PROJ-3** | a hole declares what its number is of and what set it is over | enforced | [projection-decomposition-and-the-tool-registry.md](projection-decomposition-and-the-tool-registry.md) | `test_a_hole_holding_a_magnitude_must_say_what_set_it_is_over` |
| **PROJ-4** | a refusal is a reviewed sentence chosen by machine tag | enforced | [projection-decomposition-and-the-tool-registry.md](projection-decomposition-and-the-tool-registry.md) | `test_a_refusal_is_the_packs_reviewed_sentence_for_its_tag` |
| **PROJ-5** | a property of a figure the machine holds is placed by the machine | enforced | [projection-decomposition-and-the-tool-registry.md](projection-decomposition-and-the-tool-registry.md) | `test_a_boundary_is_said_once_inside_the_clause_that_made_it` |
| **PROJ-6** | `compute` takes figure ids and stipulations, never a typed number | enforced | [projection-decomposition-and-the-tool-registry.md](projection-decomposition-and-the-tool-registry.md) | `test_compute_refuses_a_number_typed_in_and_names_what_it_has` |
| **PROJ-7** | an empty optional field means the field was not sent | enforced | [projection-decomposition-and-the-tool-registry.md](projection-decomposition-and-the-tool-registry.md) | `test_an_empty_optional_box_narrows_nothing_and_is_said_to_narrow_nothing` |
| **PROJ-8** | `nature` is not a filter | enforced | [projection-decomposition-and-the-tool-registry.md](projection-decomposition-and-the-tool-registry.md) | `test_nature_is_not_a_filter_any_read_offers` |
| **PROJ-9** | a read records what narrowed it, and every figure declares its set | enforced | [projection-decomposition-and-the-tool-registry.md](projection-decomposition-and-the-tool-registry.md) | `test_every_filter_a_read_honours_can_be_said_in_the_answer` |
| **PROJ-10** | discovery is generous, narrowing is exact | enforced | [projection-decomposition-and-the-tool-registry.md](projection-decomposition-and-the-tool-registry.md) | `test_a_name_buried_inside_a_label_reaches_nothing` |
| **PROJ-11** | model-facing tool text is a versioned file | enforced | [projection-decomposition-and-the-tool-registry.md](projection-decomposition-and-the-tool-registry.md) | `test_a_tool_without_a_description_cannot_register` |
| **PROJ-12** | a read is bounded by a named constant that does not grow with the ledger | enforced | [projection-decomposition-and-the-tool-registry.md](projection-decomposition-and-the-tool-registry.md) | `test_no_uncapped_read_exceeds_what_a_result_may_cost` |
| **PROJ-13** | the verb set does not depend on what the vault holds | enforced | [agent-toolset.md](agent-toolset.md) | `test_the_registered_tool_count_is_whatever_the_registry_holds` |
| **PROJ-14** | no registered verb touches the network | by-review | [agent-toolset.md](agent-toolset.md) | — |
| **PROJ-15** | every figure in an answer is a tool result, cited by id | enforced | [agent-toolset.md](agent-toolset.md) | `test_a_number_no_tool_returned_is_refused` |
| **PROJ-16** | no registered verb writes | by-review | [agent-toolset.md](agent-toolset.md) | — |
| **PROJ-17** | a read's requirement is in the schema the model is shown | enforced | [agent-toolset.md](agent-toolset.md) | `test_the_detailed_read_declares_in_its_schema_that_it_takes_filters` |
| **PROJ-18** | totals and rows are two verbs | enforced | [agent-toolset.md](agent-toolset.md) | `test_the_transactions_read_returns_totals_and_no_rows` |
| **PROJ-19** | expectations are derived, never stored | enforced | [knowledge-and-expectations.md](knowledge-and-expectations.md) | `test_retirement_flow_raises_an_expectation` |
| **PROJ-20** | the registry is jurisdiction-tagged data, never a parser | enforced | [knowledge-and-expectations.md](knowledge-and-expectations.md) | `test_jurisdiction_filters_the_registry` |
| **PROJ-21** | an unknown mechanism fails loudly | enforced | [knowledge-and-expectations.md](knowledge-and-expectations.md) | `test_an_unknown_mechanism_in_the_registry_fails_loudly` |
| **PROJ-22** | satisfaction is deterministic matching | enforced | [knowledge-and-expectations.md](knowledge-and-expectations.md) | `test_satisfaction_is_the_documents_arrival` |
| **PROJ-23** | an unmet expectation is a ranked queue question and never a push | enforced | [knowledge-and-expectations.md](knowledge-and-expectations.md) | `test_cadence_expectation_ranks_below_money_and_names_the_edge` |
| **PROJ-24** | `check_completeness` reports what is held, not what is missing | enforced | [knowledge-and-expectations.md](knowledge-and-expectations.md) | `test_completeness_counts_the_held_document` |
| **PROJ-25** | the model is told what day it is | enforced | [agent-toolset.md](agent-toolset.md) | `test_the_day_a_turn_is_asked_on_reaches_the_model` |
| **PROJ-26** | the model parses meaning and never supplies a figure | enforced | [from-your-words-to-the-ledger.md](from-your-words-to-the-ledger.md) | `test_a_ruling_can_never_carry_a_figure` +1 |
| **PROJ-27** | four majors, fixed at the top and free below | enforced | [from-your-words-to-the-ledger.md](from-your-words-to-the-ledger.md) | `test_the_major_is_fixed_code_and_everything_below_it_is_data` |
| **PROJ-28** | the chart of accounts is materialized by the projection | enforced | [from-your-words-to-the-ledger.md](from-your-words-to-the-ledger.md) | `test_i_bought_a_car_stops_being_spending_with_no_reingest` |
| **PROJ-29** | an unknown split is its own nature | enforced | [from-your-words-to-the-ledger.md](from-your-words-to-the-ledger.md) | `test_a_compound_payment_is_neither_counted_nor_dropped` |
| **PROJ-30** | only a major that brings a thing into being opens an account | enforced | [from-your-words-to-the-ledger.md](from-your-words-to-the-ledger.md) | `test_ordinary_spending_creates_no_account` |
| **PROJ-31** | resolution asks only when ambiguous | enforced | [from-your-words-to-the-ledger.md](from-your-words-to-the-ledger.md) | `test_resolution_asks_only_when_ambiguous` |
| **PROJ-32** | confirmation is scoped to the account, not to every parse | enforced | [from-your-words-to-the-ledger.md](from-your-words-to-the-ledger.md) | `test_an_answer_that_would_open_an_account_is_proposed_before_it_is_written` |
| **PROJ-33** | every asserted account invites the document that would prove it | enforced | [from-your-words-to-the-ledger.md](from-your-words-to-the-ledger.md) | `test_the_corroboration_ask_is_the_path_from_asserted_to_issued` |
| **PROJ-34** | what a counterparty implies is impersonal knowledge, learned once | enforced | [where-the-intelligence-goes.md](where-the-intelligence-goes.md) | `test_a_counterparty_that_implies_structure_is_proposed_not_asked` |
| **PROJ-35** | three tiers, and the rule is ask only where the counterparty cannot tell us | enforced | [where-the-intelligence-goes.md](where-the-intelligence-goes.md) | `test_an_ordinary_counterparty_is_settled_and_silent` |
| **PROJ-36** | direction is part of the implication, never a branch in the caller | enforced *(exception)* | [where-the-intelligence-goes.md](where-the-intelligence-goes.md) | `test_the_same_counterparty_means_opposite_things_by_direction` |
| **PROJ-37** | the confidence ladder decides how decisively an implication is applied | enforced | [where-the-intelligence-goes.md](where-the-intelligence-goes.md) | `test_forced_is_decisive_and_suggested_says_it_is_not` |
| **PROJ-38** | a model writes the rules and deterministic code applies them | by-review *(exception)* | [where-the-intelligence-goes.md](where-the-intelligence-goes.md) | — |
| **PROJ-39** | a rhythm question is licensed by two facts of one record | enforced | [where-the-intelligence-goes.md](where-the-intelligence-goes.md) | `test_a_merchant_with_no_billing_prior_is_never_asked_about` |
| **PROJ-40** | a person is not a counterparty on the rhythm axis | enforced | [where-the-intelligence-goes.md](where-the-intelligence-goes.md) | `test_a_merchant_with_no_billing_prior_is_never_asked_about` |
| **PROJ-41** | knowledge is exactly one of three types, and their storage never mixes | enforced | [orionviva-transaction-intelligence-spec.md](orionviva-transaction-intelligence-spec.md) | `test_peer_payment_is_not_shareable` |
| **PROJ-42** | the ACH line shape is specification, parsed deterministically | enforced | [orionviva-transaction-intelligence-spec.md](orionviva-transaction-intelligence-spec.md) | `test_the_ach_entry_description_is_recovered_from_the_statement` |
| **PROJ-43** | two keys: a stable local key and a portable brand key | enforced | [orionviva-transaction-intelligence-spec.md](orionviva-transaction-intelligence-spec.md) | `test_two_locations_of_one_brand_are_one_key` |
| **PROJ-44** | billing is a fact about the merchant, from a closed set | enforced | [orionviva-transaction-intelligence-spec.md](orionviva-transaction-intelligence-spec.md) | `test_a_billing_model_outside_the_closed_set_is_dropped` |
| **PROJ-45** | the measurement beats the prior, and a measured absence is something the ledger said | enforced | [orionviva-transaction-intelligence-spec.md](orionviva-transaction-intelligence-spec.md) | `test_a_measured_absence_of_rhythm_beats_what_the_world_says` |
| **PROJ-46** | a stream key is a counterparty and a channel, and never drops the party | enforced | [orionviva-transaction-intelligence-spec.md](orionviva-transaction-intelligence-spec.md) | `test_a_stream_key_never_drops_the_party` |
| **PROJ-47** | direction splits the statistics and never the key | enforced | [orionviva-transaction-intelligence-spec.md](orionviva-transaction-intelligence-spec.md) | `test_no_rhythm_is_offered_across_two_directions` |
| **PROJ-48** | a direction is decided by the account's kind, never by the posted sign | enforced *(exception)* | [orionviva-transaction-intelligence-spec.md](orionviva-transaction-intelligence-spec.md) | `test_a_card_purchase_reads_as_money_out` |
| **PROJ-49** | cadence and stability are measured, never asked for | enforced | [orionviva-transaction-intelligence-spec.md](orionviva-transaction-intelligence-spec.md) | `test_cadence_and_stability_are_measured_not_asked_for` |
| **PROJ-50** | the stream projection is a pure function of the set of movements | enforced | [orionviva-transaction-intelligence-spec.md](orionviva-transaction-intelligence-spec.md) | `test_ingest_order_never_changes_a_belief` |
| **PROJ-51** | a split is visible in the sentence, never silent | enforced | [orionviva-transaction-intelligence-spec.md](orionviva-transaction-intelligence-spec.md) | `test_a_mixture_states_what_it_saw_of_each_part_and_asks_which_is_which` |
| **PROJ-52** | a rhythm confirmation is a scoped ruling carrying a set | enforced | [orionviva-transaction-intelligence-spec.md](orionviva-transaction-intelligence-spec.md) | `test_which_is_which_is_recorded_as_one_set_valued_ruling` |
| **PROJ-53** | the question is a stream scope on the queue that already exists | enforced | [orionviva-transaction-intelligence-spec.md](orionviva-transaction-intelligence-spec.md) | `test_a_question_is_ranked_on_money_already_measured` |
| **PROJ-54** | a grammar is not automatically safe to publish | enforced | [orionviva-transaction-intelligence-spec.md](orionviva-transaction-intelligence-spec.md) | `test_a_template_is_judged_by_what_it_MATCHES_not_by_its_words` |
| **PROJ-55** | induced grammars are held outside any working tree until a person promotes them | by-review | [orionviva-transaction-intelligence-spec.md](orionviva-transaction-intelligence-spec.md) | — |
| **PROJ-56** | cold start is answered with silence, not a guess | enforced | [orionviva-transaction-intelligence-spec.md](orionviva-transaction-intelligence-spec.md) | `test_below_the_floor_it_says_unknown_rather_than_guessing` |
| **PROJ-57** | the forecast ledger | **unmet** | [orionviva-transaction-intelligence-spec.md](orionviva-transaction-intelligence-spec.md) | — |
| **PROJ-58** | a search-enabled call is a separate, quarantined path | **unmet** | [orionviva-transaction-intelligence-spec.md](orionviva-transaction-intelligence-spec.md) | — |
| **PROJ-59** | free text is an addition, never a dependency | enforced | [from-your-words-to-the-ledger.md](from-your-words-to-the-ledger.md) | `test_with_no_reader_a_plain_answer_still_lands_and_a_loose_one_does_not` |
| **PROJ-60** | a small core with view modules behind a facade | by-review | [projection-decomposition-and-the-tool-registry.md](projection-decomposition-and-the-tool-registry.md) | — |
| **PROJ-61** | the registry holds only verbs the code can honestly serve | enforced | [projection-decomposition-and-the-tool-registry.md](projection-decomposition-and-the-tool-registry.md) | `test_the_registered_tool_count_is_whatever_the_registry_holds` |
| **PROJ-62** | a structured filter object, validated against the vault's own vocabulary | enforced | [projection-decomposition-and-the-tool-registry.md](projection-decomposition-and-the-tool-registry.md) | `test_unknown_category_refusal_names_the_vocabulary` |
| **PROJ-63** | the registry contract is modality-neutral | enforced | [projection-decomposition-and-the-tool-registry.md](projection-decomposition-and-the-tool-registry.md) | `test_planner_factory_is_native_first_with_text_as_the_fallback` |
| **PROJ-64** | one result envelope, refusal first-class | enforced | [projection-decomposition-and-the-tool-registry.md](projection-decomposition-and-the-tool-registry.md) | `test_unknown_tool_is_a_refusal_not_an_exception` |
| **PROJ-65** | a block of rows is one read's figures, each beside the slice it covers | enforced | [projection-decomposition-and-the-tool-registry.md](projection-decomposition-and-the-tool-registry.md) | `test_a_shape_that_names_no_row_count_answers_whatever_the_count_turns_out_to_be` +2 |
| **PROJ-66** | a hole nothing can fill costs its clause and not the turn | enforced | [projection-decomposition-and-the-tool-registry.md](projection-decomposition-and-the-tool-registry.md) | `test_a_hole_nothing_can_fill_costs_its_clause_and_not_the_turn` +1 |
| **PROJ-67** | a read that groups cuts as many ways as it groups | enforced | [projection-decomposition-and-the-tool-registry.md](projection-decomposition-and-the-tool-registry.md) | `test_each_group_of_the_summary_read_names_its_own_slice` +2 |

## ING — ingestion, extraction, verification and the threat model

What happens between a file arriving and a figure being posted.

| Rule | Name | State | Doc | Test |
| --- | --- | --- | --- | --- |
| **ING-1** | Confidence is constructed, never self-reported | by-review | [extraction-and-confidence.md](extraction-and-confidence.md) | — |
| **ING-2** | The grade vocabulary is closed and four-valued | enforced | [extraction-and-confidence.md](extraction-and-confidence.md) | `test_posting_rejects_unknown_grade` |
| **ING-3** | What each grade means | enforced | [extraction-and-confidence.md](extraction-and-confidence.md) | `test_checking_statement_posts_and_reconciles` |
| **ING-4** | A claim's identity is its value and position, never its label | **contradicted** | [extraction-and-confidence.md](extraction-and-confidence.md) | — |
| **ING-5** | Deterministic cross-checks decide, to the cent | enforced | [extraction-and-confidence.md](extraction-and-confidence.md) | `test_balance_identity_catches_one_cent` +1 |
| **ING-6** | Every stored figure carries a source pointer | by-review *(exception)* | [extraction-and-confidence.md](extraction-and-confidence.md) | — |
| **ING-7** | A person's word is its own rung, below agreement | **unmet** | [extraction-and-confidence.md](extraction-and-confidence.md) | — |
| **ING-10** | text+image is the product's input mode, and every read records it | by-review *(exception)* | [document-preprocessing.md](document-preprocessing.md) | — |
| **ING-11** | Input mode is a benchmark dimension, and the modes are image, text, and text+image | by-review | [document-preprocessing.md](document-preprocessing.md) | — |
| **ING-12** | Provenance anchors to measured character boxes where a text layer exists | **unmet** | [document-preprocessing.md](document-preprocessing.md) | — |
| **ING-13** | Ingestion processes a page at a time | **contradicted** | [document-preprocessing.md](document-preprocessing.md) | — |
| **ING-14** | A scan is detected per page by ink without text, and only a scan routes to OCR | **unmet** | [document-preprocessing.md](document-preprocessing.md) | — |
| **ING-15** | Text extraction is on-device, and cloud document-AI is never on the default path | by-review | [document-preprocessing.md](document-preprocessing.md) | — |
| **ING-16** | Cloud document-AI, if a user configures it, is labelled data-leaving like any model call | **unmet** | [document-preprocessing.md](document-preprocessing.md) | — |
| **ING-20** | A document type counts as covered only when a real one has posted | untestable | [document-coverage.md](document-coverage.md) | — |
| **ING-21** | Real documents are never committed | by-review | [document-coverage.md](document-coverage.md) | — |
| **ING-22** | A document a ruling names is corroboration, never a gate | enforced | [document-coverage.md](document-coverage.md) | `test_an_asserted_account_asks_for_the_document_that_would_prove_it` |
| **ING-30** | A held document is polymorphic, and consumers route on the registry | by-review | [doc-type-registry-and-format-profiles.md](doc-type-registry-and-format-profiles.md) | — |
| **ING-31** | Account kind is derived by the registry, never asked of the model | enforced | [doc-type-registry-and-format-profiles.md](doc-type-registry-and-format-profiles.md) | `test_card_is_a_liability_savings_is_depository` +1 |
| **ING-32** | Classify first, then extract with that type's profile | enforced | [doc-type-registry-and-format-profiles.md](doc-type-registry-and-format-profiles.md) | `test_unsupported_type_records_only_the_cheap_classify` |
| **ING-33** | We own the schema; the model owns the reading | enforced | [doc-type-registry-and-format-profiles.md](doc-type-registry-and-format-profiles.md) | `test_no_prompt_text_lives_in_code` |
| **ING-34** | A profile may be model-authored, but is ratified before it is used | **unmet** | [doc-type-registry-and-format-profiles.md](doc-type-registry-and-format-profiles.md) | — |
| **ING-35** | The verification identity is universal code; the per-type formula is data | enforced | [doc-type-registry-and-format-profiles.md](doc-type-registry-and-format-profiles.md) | `test_whole_balance_family_shares_one_identity` +1 |
| **ING-36** | Personal knowledge and format knowledge are kept strictly apart | by-review | [doc-type-registry-and-format-profiles.md](doc-type-registry-and-format-profiles.md) | — |
| **ING-37** | A profile is versioned, and every read records the version that produced it | enforced *(exception)* | [doc-type-registry-and-format-profiles.md](doc-type-registry-and-format-profiles.md) | `test_active_versions_are_frozen` +2 |
| **ING-40** | Classification is a claim, not a fact | **unmet** | [data-model-considerations.md](data-model-considerations.md) | `test_classify_unreadable_is_unknown_not_a_guess` +1 |
| **ING-41** | Three layers: claims, facts, projection | enforced | [data-model-considerations.md](data-model-considerations.md) | `test_cached_projection_matches_a_fresh_replay` +1 |
| **ING-42** | An amount is a value and a currency | enforced *(exception)* | [data-model-considerations.md](data-model-considerations.md) | `test_currency_conflict_is_invalid_not_silently_resolved` +1 |
| **ING-43** | A transaction is a list of postings that sum to zero | enforced | [data-model-considerations.md](data-model-considerations.md) | `test_transaction_balances_catches_imbalance` +1 |
| **ING-44** | Double-entry governs the money; tags govern the meaning | enforced | [data-model-considerations.md](data-model-considerations.md) | `test_a_tag_never_touches_the_category_partition` +1 |
| **ING-45** | A measurement, a valuation and an estimate are never dressed as one another | by-review *(exception)* | [data-model-considerations.md](data-model-considerations.md) | — |
| **ING-46** | Regional variety is an attribute on a primitive, never a new primitive | by-review | [data-model-considerations.md](data-model-considerations.md) | — |
| **ING-47** | Observations accumulate; they do not just dedup | enforced *(exception)* | [data-model-considerations.md](data-model-considerations.md) | `test_reupload_is_duplicate_no_double_post` +3 |
| **ING-48** | Transfer links are graded facts | enforced | [data-model-considerations.md](data-model-considerations.md) | `test_auto_link_is_corroborated_and_survives_a_replay` +2 |
| **ING-49** | Completeness is data | enforced *(exception)* | [data-model-considerations.md](data-model-considerations.md) | `test_completeness_counts_the_held_document` +2 |
| **ING-50** | A document's type never comes from its filename | enforced | [data-model-spike-findings.md](data-model-spike-findings.md) | `test_classify_unreadable_is_unknown_not_a_guess` |
| **ING-51** | A movement between the person's own accounts is not spending | enforced | [data-model-spike-findings.md](data-model-spike-findings.md) | `test_internal_transfer_auto_links_and_excludes_from_spending` +1 |
| **ING-52** | A tax or annual-summary document produces a fact bundle, not transactions or positions | **unmet** | [data-model-spike-findings.md](data-model-spike-findings.md) | — |
| **ING-53** | The leg a document attests and the leg the system supplies carry different grades | enforced | [data-model-spike-findings.md](data-model-spike-findings.md) | `test_withdrawal_balances_and_grades` |
| **ING-54** | A balancing posting is never invented silently | enforced | [data-model-spike-findings.md](data-model-spike-findings.md) | `test_withdrawal_balances_and_grades` +1 |
| **ING-60** | Diagnosis is deterministic and costs no model call | enforced | [verification-findings-and-correction.md](verification-findings-and-correction.md) | `test_forced_amount_misread_from_running_balance` +1 |
| **ING-61** | A finding is forced, suggested, or unlocalized | enforced | [verification-findings-and-correction.md](verification-findings-and-correction.md) | `test_unlocalized_when_no_clean_explanation` +1 |
| **ING-62** | A forced correction auto-applies at `corroborated` and is always reported | enforced | [verification-findings-and-correction.md](verification-findings-and-correction.md) | `test_forced_correction_auto_applies_and_posts` |
| **ING-63** | A suggested or unlocalized finding never posts | enforced *(exception)* | [verification-findings-and-correction.md](verification-findings-and-correction.md) | `test_unforced_conflict_carries_a_finding` +1 |
| **ING-64** | The diagnosis rules are versioned | by-review | [verification-findings-and-correction.md](verification-findings-and-correction.md) | — |
| **ING-65** | Repair is bounded | enforced *(exception)* | [verification-findings-and-correction.md](verification-findings-and-correction.md) | `test_gives_up_after_the_retry_and_parks` |
| **ING-66** | A correction is an event, and a human ruling grades highest | enforced | [verification-findings-and-correction.md](verification-findings-and-correction.md) | `test_human_correction_posts_at_verified` +1 |
| **ING-70** | The extraction model is a quarantined, powerless worker | by-review | [threat-model-and-ingestion-security.md](threat-model-and-ingestion-security.md) | — |
| **ING-71** | Document content reaches the model as delimited, untrusted data | enforced | [threat-model-and-ingestion-security.md](threat-model-and-ingestion-security.md) | `test_the_documents_own_text_is_closed_off_and_the_last_word_is_ours` +1 |
| **ING-72** | Deterministic verification is the reference monitor | enforced | [threat-model-and-ingestion-security.md](threat-model-and-ingestion-security.md) | `test_unreconciled_statement_is_conflict_not_posted` |
| **ING-73** | Extraction and conversation are separate contexts | by-review | [threat-model-and-ingestion-security.md](threat-model-and-ingestion-security.md) | — |
| **ING-74** | The poisoned document and the exact exchange are retained | enforced | [threat-model-and-ingestion-security.md](threat-model-and-ingestion-security.md) | `test_read_that_throws_is_recorded_not_orphaned` +1 |
| **ING-75** | No provider SDK on the wire | enforced | [threat-model-and-ingestion-security.md](threat-model-and-ingestion-security.md) | `test_the_model_adapters_import_nothing_the_package_did_not_declare` |
| **ING-76** | One key, derived from one passphrase, stored nowhere | enforced | [threat-model-and-ingestion-security.md](threat-model-and-ingestion-security.md) | `test_nothing_readable_at_rest` +2 |
| **ING-77** | Where a document is sent is decided by this process, not by its surroundings | enforced | [threat-model-and-ingestion-security.md](threat-model-and-ingestion-security.md) | `test_a_dotenv_in_the_working_directory_is_not_configuration` +1 |
| **ING-78** | A document may not cost unbounded work to read | enforced | [threat-model-and-ingestion-security.md](threat-model-and-ingestion-security.md) | `test_too_many_pages_is_refused_rather_than_partly_read` +2 |
| **ING-80** | Extraction always works with no profile at all | enforced | [format-commons.md](format-commons.md) | `test_no_template_matching_is_a_legitimate_answer` +1 |
| **ING-81** | A profile describes a form and never a value | enforced | [format-commons.md](format-commons.md) | `test_an_account_number_never_reaches_the_shareable_side` +1 |
| **ING-82** | A profile-guided read passes the same verification floor as a blind one | **unmet** | [format-commons.md](format-commons.md) | — |
| **ING-83** | A profile is versioned, and a released version is never overwritten | enforced | [format-commons.md](format-commons.md) | `test_a_released_profile_cannot_be_overwritten` +1 |
| **ING-84** | Drift demotes a profile automatically | enforced | [format-commons.md](format-commons.md) | `test_drift_shows_up_in_the_recent_number_long_before_the_lifetime_one` +1 |
| **ING-85** | No silent contribution | by-review | [format-commons.md](format-commons.md) | — |
| **ING-86** | What may travel is decided by structure, never by inspecting text | enforced | [format-commons.md](format-commons.md) | `test_personal_and_shareable_are_decided_by_slot_not_by_text` +1 |
| **ING-90** | Two timelines per fact: when it happened, and when we learned it | by-review *(exception)* | [data-model-considerations.md](data-model-considerations.md) | — |

## MER — descriptors, grammars, the merchant catalog and the maintenance agent

How a bank descriptor becomes a counterparty, what may be shared, and what the agent may do unattended.

| Rule | Name | State | Doc | Test |
| --- | --- | --- | --- | --- |
| **MER-1** | The slot vocabulary is closed | enforced | [the-conduit-and-the-counterparty.md](the-conduit-and-the-counterparty.md) | `test_only_names_from_the_vocabulary_compile` +1 |
| **MER-2** | A template explains a whole line or none of it | enforced | [the-conduit-and-the-counterparty.md](the-conduit-and-the-counterparty.md) | `test_a_match_explains_the_whole_line` |
| **MER-3** | Privacy is a slot name | enforced | [the-conduit-and-the-counterparty.md](the-conduit-and-the-counterparty.md) | `test_personal_and_shareable_are_decided_by_slot_not_by_text` +1 |
| **MER-4** | A wire is refused every layer | enforced | [the-conduit-and-the-counterparty.md](the-conduit-and-the-counterparty.md) | `test_a_wire_is_refused_a_grammar_however_good_the_template_looks` +1 |
| **MER-5** | A slotless template needs a line the bank repeats | enforced | [the-conduit-and-the-counterparty.md](the-conduit-and-the-counterparty.md) | `test_a_template_with_no_holes_is_an_example_not_a_grammar` +1 |
| **MER-6** | A profile is a versioned pack, never edited | enforced | [the-conduit-and-the-counterparty.md](the-conduit-and-the-counterparty.md) | `test_a_released_profile_cannot_be_overwritten` +1 |
| **MER-7** | A grammar is gated and chosen on lines it never saw | enforced | [the-conduit-and-the-counterparty.md](the-conduit-and-the-counterparty.md) | `test_a_grammar_is_gated_on_lines_that_never_helped_choose_it` +1 |
| **MER-8** | The induction thresholds | enforced *(exception)* | [the-conduit-and-the-counterparty.md](the-conduit-and-the-counterparty.md) | `test_a_grammar_that_explains_the_rare_lines_and_misses_the_mass_fails` +1 |
| **MER-9** | The layer order, and a borrowed grammar | enforced | [the-conduit-and-the-counterparty.md](the-conduit-and-the-counterparty.md) | `test_the_banks_own_grammar_always_wins` +3 |
| **MER-10** | Identity is brand-level | enforced | [the-conduit-and-the-counterparty.md](the-conduit-and-the-counterparty.md) | `test_two_locations_of_one_brand_are_one_key_and_one_call` +1 |
| **MER-11** | A rail is proven by structure, never by a word | enforced | [the-conduit-and-the-counterparty.md](the-conduit-and-the-counterparty.md) | `test_a_merchant_with_one_proven_channel_does_not_split_across_templates` +1 |
| **MER-12** | The declaration travels with the keys | enforced | [the-conduit-and-the-counterparty.md](the-conduit-and-the-counterparty.md) | `test_a_resolver_declaring_nothing_is_told_apart_from_one_of_the_wrong_shape` +1 |
| **MER-13** | `is_shareable` answers only where no grammar does | enforced | [the-conduit-and-the-counterparty.md](the-conduit-and-the-counterparty.md) | `test_with_no_grammar_the_conservative_list_still_guards_a_peer_payment` +1 |
| **MER-14** | A kind that names no party gets neither a grammar nor enrichment | enforced | [the-conduit-and-the-counterparty.md](the-conduit-and-the-counterparty.md) | `test_a_kind_whose_lines_name_no_party_gets_no_grammar` +2 |
| **MER-15** | A better layer must not return less than a worse one | enforced | [the-conduit-and-the-counterparty.md](the-conduit-and-the-counterparty.md) | `test_the_ach_entry_description_is_recovered_from_the_statement` |
| **MER-16** | Word-recurrence counts decide nothing | enforced | [the-conduit-and-the-counterparty.md](the-conduit-and-the-counterparty.md) | `test_word_recurrence_is_a_diagnostic_and_decides_nothing` |
| **MER-17** | The shape set is kept small on purpose | enforced | [the-conduit-and-the-counterparty.md](the-conduit-and-the-counterparty.md) | `test_a_hash_is_left_out_because_it_slots_wrongly` +1 |
| **MER-18** | The induction diagnostics decide nothing | enforced | [the-conduit-and-the-counterparty.md](the-conduit-and-the-counterparty.md) | `test_a_template_is_judged_by_what_it_MATCHES_not_by_its_words` +1 |
| **MER-19** | A non-English peer line still crosses where no grammar exists | **unmet** | [the-conduit-and-the-counterparty.md](the-conduit-and-the-counterparty.md) | — |
| **MER-20** | Only a key and a linted example cross into the package | enforced | [merchantcore-package.md](merchantcore-package.md) | `test_only_impersonal_hints_cross_the_boundary` +1 |
| **MER-21** | The lint is a property of the store | enforced | [merchantcore-package.md](merchantcore-package.md) | `test_catalog_pending_add_and_linted_export` |
| **MER-22** | An enriched record is graded and stamped | enforced | [merchantcore-package.md](merchantcore-package.md) | `test_enricher_is_one_call_and_grades_records` +1 |
| **MER-23** | Enrichment is chunked, and the chunk size is the caller's | enforced *(exception)* | [merchantcore-package.md](merchantcore-package.md) | `test_enricher_chunks_a_large_batch_into_several_calls` +3 |
| **MER-24** | "Asked and got nothing" is not "the reply did not parse" | enforced | [merchantcore-package.md](merchantcore-package.md) | `test_a_chunk_that_did_not_parse_is_asked_again` +1 |
| **MER-25** | A non-answer is keyed by the example, not by the merchant | enforced | [merchantcore-package.md](merchantcore-package.md) | `test_a_merchant_the_model_could_not_name_is_not_asked_about_again` +1 |
| **MER-26** | `queued` and `pending` answer different questions | by-review | [merchantcore-package.md](merchantcore-package.md) | — |
| **MER-27** | The product imports records as events | enforced | [merchantcore-package.md](merchantcore-package.md) | `test_enrichment_syncs_as_events_and_categorizes_retrospectively` +2 |
| **MER-28** | A version-stale record is restaged, and keeps answering meanwhile | enforced | [merchantcore-package.md](merchantcore-package.md) | `test_a_version_stale_record_is_restaged_and_asked_about_again` +4 |
| **MER-29** | Where merchant knowledge lives: learned first, shipped second | enforced | [merchantcore-package.md](merchantcore-package.md) | `test_a_shipped_catalog_is_read_and_marked_as_shipped` +4 |
| **MER-30** | The commons export is linted, and an import is only a prior | enforced | [merchantcore-package.md](merchantcore-package.md) | `test_catalog_pending_add_and_linted_export` +1 |
| **MER-31** | Billing is a fact about the merchant, validated against closed sets | enforced | [merchantcore-package.md](merchantcore-package.md) | `test_a_billing_model_and_its_period_land_in_the_attributes_bag` +4 |
| **MER-32** | The enrichment prompt says a brand string may be truncated | **unmet** | [merchantcore-package.md](merchantcore-package.md) | — |
| **MER-40** | Categorize the merchant, not the transaction | enforced | [merchant-catalog-and-commons.md](merchant-catalog-and-commons.md) | `test_merchant_ruling_fills_all_its_transactions` +1 |
| **MER-41** | The catalog is a prior; the override wins | enforced | [merchant-catalog-and-commons.md](merchant-catalog-and-commons.md) | `test_per_transaction_override_beats_the_merchant_rule` +1 |
| **MER-42** | Every lookup considers both keys | enforced | [merchant-catalog-and-commons.md](merchant-catalog-and-commons.md) | `test_a_descriptor_keyed_answer_still_reads` +2 |
| **MER-43** | The sync reaches only merchants this vault holds | enforced | [merchant-catalog-and-commons.md](merchant-catalog-and-commons.md) | `test_a_record_about_a_merchant_this_vault_never_paid_is_not_synced` |
| **MER-44** | The subcategory vocabulary is seeded, and grows without displacing | enforced | [merchant-catalog-and-commons.md](merchant-catalog-and-commons.md) | `test_the_seed_leads_and_a_vault_label_follows` +4 |
| **MER-45** | The primary category set is controlled and is the single source | enforced | [merchant-catalog-and-commons.md](merchant-catalog-and-commons.md) | `test_sixteen_primary_categories` |
| **MER-46** | The unencrypted catalog carries no money | enforced | [merchant-catalog-and-commons.md](merchant-catalog-and-commons.md) | `test_export_catalog_is_linted_and_carries_no_amounts` |
| **MER-47** | The taxonomy is a versioned data pack | enforced | [merchant-catalog-and-commons.md](merchant-catalog-and-commons.md) | `test_the_manifest_and_the_files_agree` +1 |
| **MER-48** | Normalization is deterministic and versioned, never fuzzy string-matching | enforced | [merchant-catalog-and-commons.md](merchant-catalog-and-commons.md) | `test_normalize_is_deterministic_and_versioned` +2 |
| **MER-49** | An unknown merchant stays unknown while its movement gets a replaceable default | enforced | [merchant-catalog-and-commons.md](merchant-catalog-and-commons.md) | `test_import_defaults_peer_payments_before_asking_questions` +1 |
| **MER-50** | Deciding is pure; only performing spends | enforced | [the-maintenance-agent.md](the-maintenance-agent.md) | `test_assess_is_pure_and_repeatable` +2 |
| **MER-51** | The agent records what it did, never what it saw | enforced | [the-maintenance-agent.md](the-maintenance-agent.md) | `test_the_journal_carries_no_descriptor_and_no_amount` +2 |
| **MER-52** | A refusal cools until the stake moves, and a code change moves it | enforced | [the-maintenance-agent.md](the-maintenance-agent.md) | `test_a_refusal_against_unchanged_evidence_is_not_retried` +4 |
| **MER-53** | Widening a shape moves neither version | enforced | [the-maintenance-agent.md](the-maintenance-agent.md) | `test_a_wider_shape_only_ever_matches_more` +1 |
| **MER-54** | The budget is a ceiling denominated in calls | enforced | [the-maintenance-agent.md](the-maintenance-agent.md) | `test_a_budget_stops_a_runaway_before_it_costs_anything` +4 |
| **MER-55** | Independent attempts, selected on the held-out score | enforced | [the-maintenance-agent.md](the-maintenance-agent.md) | `test_best_of_selects_on_the_held_out_score_not_training_coverage` +2 *(failing)* |
| **MER-56** | Enrichment does not run unattended | enforced | [the-maintenance-agent.md](the-maintenance-agent.md) | `test_enrichment_does_not_act_unattended_while_the_crossing_is_ungated` +1 |
| **MER-57** | The agent proposes nothing for a kind that names no party | enforced | [the-maintenance-agent.md](the-maintenance-agent.md) | `test_a_kind_that_names_no_party_is_never_proposed` |
| **MER-58** | Publishing waits for a person | enforced | [the-maintenance-agent.md](the-maintenance-agent.md) | `test_mechanics_are_autonomous_and_publishing_is_not` |
| **MER-59** | The enrichment run names the catalog it loaded | by-review | [merchant-catalog-and-commons.md](merchant-catalog-and-commons.md) | — |
| **MER-60** | A question with no correct answer among its options is not asked | enforced | [learning-mode.md](learning-mode.md) | `test_a_proposal_states_what_it_does_not_know` |
| **MER-61** | A compound payment is named as compound, and the ask is for the document | enforced | [learning-mode.md](learning-mode.md) | `test_a_compound_payment_is_neither_counted_nor_dropped` +1 |
| **MER-63** | The sentence is kept verbatim, and applying is a separate act | enforced | [learning-mode.md](learning-mode.md) | `test_applying_is_a_separate_explicit_act` +1 |
| **MER-64** | The interim answer for a capital purchase | enforced | [learning-mode.md](learning-mode.md) | `test_a_compound_payment_is_neither_counted_nor_dropped` |
| **MER-70** | A slot empty across a whole statement means the grammar is wrong | **unmet** | [the-conduit-and-the-counterparty.md](the-conduit-and-the-counterparty.md) | — |
| **MER-71** | A brand slot crosses only where a published format corroborates the line | enforced *(exception)* | [the-conduit-and-the-counterparty.md](the-conduit-and-the-counterparty.md) | `test_a_brand_a_grammar_named_crosses_only_where_a_published_format_agrees` +3 |
| **MER-72** | No token from an occurrence attribute reaches the commons, and a test says so | **unmet** | [the-conduit-and-the-counterparty.md](the-conduit-and-the-counterparty.md) | — |

## VOICE — prompts, persona, the interview, and every surface

What Viva may say, how she is asked, and what a figure must carry to cross into an interface.

| Rule | Name | State | Doc | Test |
| --- | --- | --- | --- | --- |
| **VOICE-1** | no model-facing text lives in code | enforced | [prompts-as-files.md](prompts-as-files.md) | `test_no_prompt_text_lives_in_code` |
| **VOICE-2** | a released version file is immutable | enforced | [prompts-as-files.md](prompts-as-files.md) | `test_editing_a_released_version_fails` |
| **VOICE-3** | a version is declared once, as data, beside the code it governs | enforced *(exception)* | [prompts-as-files.md](prompts-as-files.md) | `test_no_version_id_is_declared_as_a_literal_in_the_modules_that_use_one` |
| **VOICE-4** | a missing version raises rather than defaulting | enforced | [prompts-as-files.md](prompts-as-files.md) | `test_a_missing_version_raises_rather_than_defaulting` |
| **VOICE-5** | a version file may hold a keyed table, and its tags are an interface | enforced | [prompts-as-files.md](prompts-as-files.md) | `test_every_repair_a_check_can_name_has_reviewed_words` |
| **VOICE-6** | a recorded version resolves to the text that produced the reading | enforced | [prompts-as-files.md](prompts-as-files.md) | `test_every_version_the_code_can_emit_resolves` +1 |
| **VOICE-10** | voice is versioned data, never incidental copy | enforced | [viva-persona.md](viva-persona.md) | `test_question_text_no_longer_lives_in_code` |
| **VOICE-11** | a phrasing may not introduce a fact its intent did not supply | enforced | [viva-persona.md](viva-persona.md) | `test_phrasings_use_only_their_intent_fields` |
| **VOICE-12** | every question kind has a phrasing, and no phrasing is orphaned | enforced | [viva-persona.md](viva-persona.md) | `test_every_intent_has_a_phrasing_and_no_orphans` |
| **VOICE-13** | a slot is typed, and a figure reaches a person only through the one renderer | enforced | [viva-persona.md](viva-persona.md) | `test_a_money_slot_cannot_be_handed_a_figure_that_formatted_itself` |
| **VOICE-14** | a decline is an event, and a declined question stays quiet until evidence moves | enforced | [viva-persona.md](viva-persona.md) | `test_a_deferred_question_returns_when_evidence_touches_its_subject` |
| **VOICE-15** | she works in the background, and the work is quiet | **unmet** | [viva-persona.md](viva-persona.md) | — |
| **VOICE-16** | a released persona pack is frozen | enforced | [viva-persona.md](viva-persona.md) | `test_released_packs_are_frozen` |
| **VOICE-23** | the queue carries no instructions for a surface | enforced | [viva-persona-and-interview.md](viva-persona-and-interview.md) | `test_the_queue_carries_no_instructions_for_a_surface` |
| **VOICE-24** | this is never a chat agent | enforced | [viva-persona-and-interview.md](viva-persona-and-interview.md) | `test_a_question_no_longer_being_asked_records_nothing` |
| **VOICE-25** | the butler is Viva, and the persona guide is seed content for data packs | enforced | [viva-persona-and-interview.md](viva-persona-and-interview.md) | `test_every_intent_has_a_phrasing_and_no_orphans` |
| **VOICE-26** | the model is a copywriter at design time, not at run time | enforced | [viva-persona-and-interview.md](viva-persona-and-interview.md) | `test_a_refusal_is_the_packs_reviewed_sentence_for_its_tag` |
| **VOICE-27** | one question at a time, with the tail summarized | enforced | [viva-persona-and-interview.md](viva-persona-and-interview.md) | `test_an_account_with_a_schema_is_asked_one_thing_at_a_time` +3 |
| **VOICE-30** | Viva is summoned, never ambient | untestable | [experience-vision.md](experience-vision.md) | — |
| **VOICE-31** | the product opens as a picture, not a chat | by-review | [experience-vision.md](experience-vision.md) | — |
| **VOICE-33** | a capture surface creates no hosted data | **unmet** | [experience-vision.md](experience-vision.md) | — |
| **VOICE-34** | a spoken answer is mirrored in text | **unmet** | [experience-vision.md](experience-vision.md) | — |
| **VOICE-36** | a correction is an event, permanently remembered | enforced *(exception)* | [experience-vision.md](experience-vision.md) | `test_reset_drops_model_categorization_but_keeps_my_rulings` +1 |
| **VOICE-40** | a schema question may never ask for an identifier | enforced | [the-interview-and-the-schema-pack.md](the-interview-and-the-schema-pack.md) | `test_no_answer_type_means_an_identifier` |
| **VOICE-41** | a schema names only documents the pipeline actually classifies | enforced | [the-interview-and-the-schema-pack.md](the-interview-and-the-schema-pack.md) | `test_a_schema_may_only_name_a_document_the_pipeline_classifies` |
| **VOICE-42** | an account comes into being only through a confirmed Proposal | enforced | [the-interview-and-the-schema-pack.md](the-interview-and-the-schema-pack.md) | `test_an_answer_that_would_open_an_account_comes_back_to_be_confirmed` |
| **VOICE-43** | a figure in an attribute answer must appear in the person's own words | enforced | [the-interview-and-the-schema-pack.md](the-interview-and-the-schema-pack.md) | `test_a_figure_absent_from_their_words_is_refused` |
| **VOICE-44** | a value on a ruling is confined to the scopes that declare one | enforced | [the-interview-and-the-schema-pack.md](the-interview-and-the-schema-pack.md) | `test_a_value_outside_attribute_scope_is_refused` |
| **VOICE-45** | attribute rulings are a history, and a correction does not reach backwards | enforced | [the-interview-and-the-schema-pack.md](the-interview-and-the-schema-pack.md) | `test_an_answer_today_does_not_rewrite_an_earlier_point` |
| **VOICE-46** | a released schema pack is frozen | enforced | [the-interview-and-the-schema-pack.md](the-interview-and-the-schema-pack.md) | `test_released_schema_packs_are_frozen` |
| **VOICE-47** | a kind with no schema asks nothing and records the gap | enforced | [the-interview-and-the-schema-pack.md](the-interview-and-the-schema-pack.md) | `test_a_kind_with_no_schema_asks_nothing_and_records_the_gap` |
| **VOICE-48** | every question says what it unlocks, and a choice enumerates its alternatives | enforced | [the-interview-and-the-schema-pack.md](the-interview-and-the-schema-pack.md) | `test_a_question_must_say_what_it_unlocks` |
| **VOICE-49** | what a document already said is not asked again | enforced | [the-interview-and-the-schema-pack.md](the-interview-and-the-schema-pack.md) | `test_what_a_statement_already_said_is_not_asked_again` |
| **VOICE-50** | a Proposal is the only path to a change, and it is never applied unconfirmed | enforced | [viva-listens-and-speaks.md](viva-listens-and-speaks.md) | `test_applying_is_a_separate_explicit_act` |
| **VOICE-51** | the interpreter never supplies a figure | enforced | [viva-listens-and-speaks.md](viva-listens-and-speaks.md) | `test_the_model_never_supplies_a_figure` |
| **VOICE-52** | the interpreter is an edge, quarantined like the reader | enforced | [viva-listens-and-speaks.md](viva-listens-and-speaks.md) | `test_the_interpreter_is_configured_separately_and_can_be_local` |
| **VOICE-53** | with no model configured, nothing is guessed and the queue still works | enforced | [viva-listens-and-speaks.md](viva-listens-and-speaks.md) | `test_with_no_model_nothing_is_guessed` |
| **VOICE-54** | the button path and the sentence path write the same events | enforced | [viva-listens-and-speaks.md](viva-listens-and-speaks.md) | `test_the_button_path_and_the_sentence_path_write_the_same_events` |
| **VOICE-57** | a figure fills a hole only when kind, quantity and set all agree | enforced | [viva-listens-and-speaks.md](viva-listens-and-speaks.md) | `test_a_thing_of_the_wrong_kind_cannot_fill_a_hole` |
| **VOICE-58** | the same machine runs inbound | enforced | [viva-listens-and-speaks.md](viva-listens-and-speaks.md) | `test_every_question_declares_the_structure_of_its_answer` |
| **VOICE-59** | no agent-memory framework | untestable | [viva-listens-and-speaks.md](viva-listens-and-speaks.md) | — |
| **VOICE-61** | a figure whose value denies its quantity's direction fills no hole asserting it | enforced | [the-surface-cards.md](the-surface-cards.md) | `test_a_credit_on_a_card_never_fills_a_hole_that_asserts_a_debt` |
| **VOICE-62** | which quantities assert a direction is declared with the vocabulary | enforced | [the-surface-cards.md](the-surface-cards.md) | `test_which_quantities_assert_a_direction_is_declared_with_the_vocabulary` |
| **VOICE-63** | the renderer writes an amount, not an instrument | enforced | [the-surface-cards.md](the-surface-cards.md) | `test_no_module_that_speaks_to_a_person_formats_money_itself` |
| **VOICE-64** | every figure carries its own as-of date and grade | enforced | [the-surface-cards.md](the-surface-cards.md) | `test_the_figure_the_hole_asked_about_is_spoken` |
| **VOICE-65** | a card that fails is a card that failed, never a ledger that failed | **unmet** | [the-surface-cards.md](the-surface-cards.md) | — |
| **VOICE-66** | each account kind speaks its own language | **unmet** | [the-surface-cards.md](the-surface-cards.md) | — |
| **VOICE-70** | a surface formats money and never computes it | enforced | [the-presentation-layer.md](the-presentation-layer.md) | `test_no_module_that_speaks_to_a_person_formats_money_itself` |
| **VOICE-71** | a shipped surface needs no toolchain and no runtime fetch | **unmet** | [the-presentation-layer.md](the-presentation-layer.md) | `test_core_does_not_depend_on_product_surface_or_desktop` |
| **VOICE-80** | a refusal certifies nothing and carries no figure | enforced | [the-suggestions-channel.md](the-suggestions-channel.md) | `test_a_number_echoed_by_a_refusal_cannot_ground_an_answer` |
| **VOICE-81** | nothing composes words at the moment of refusing | enforced | [the-suggestions-channel.md](the-suggestions-channel.md) | `test_every_way_a_turn_can_refuse_has_a_reviewed_sentence` |
| **VOICE-82** | a turn that ends with nothing says the cause as well as the verdict | enforced | [the-suggestions-channel.md](the-suggestions-channel.md) | `test_every_refusal_whose_cause_may_be_spoken_has_a_reviewed_sentence` |
| **VOICE-83** | a suggestion binds through the same gate as an answer | **unmet** | [the-suggestions-channel.md](the-suggestions-channel.md) | — |
| **VOICE-84** | a suggestion is never a proposal | **unmet** | [the-suggestions-channel.md](the-suggestions-channel.md) | — |
| **VOICE-85** | a suggestion respects a decline | **unmet** | [the-suggestions-channel.md](the-suggestions-channel.md) | — |
| **VOICE-90** | trust attaches to the system around a model, never to a model | enforced *(exception)* | [model-trust-policy.md](model-trust-policy.md) | `test_a_thing_of_the_wrong_kind_cannot_fill_a_hole` |
| **VOICE-91** | the model that reads a document has no tools and no write access | enforced *(exception)* | [model-trust-policy.md](model-trust-policy.md) | `test_two_phase_read_records_both_claims` |
| **VOICE-92** | deterministic verification never relaxes | enforced | [model-trust-policy.md](model-trust-policy.md) | `test_balance_identity_catches_one_cent` |
| **VOICE-93** | model versions are pinned; no "latest" alias on the trust path | **unmet** | [model-trust-policy.md](model-trust-policy.md) | — |
| **VOICE-94** | every version is a new hire | **unmet** | [model-trust-policy.md](model-trust-policy.md) | — |
| **VOICE-95** | autonomy is earned statistically and revoked automatically | **unmet** | [model-trust-policy.md](model-trust-policy.md) | — |
| **VOICE-96** | every call names its model, and every version resolves | enforced *(exception)* | [model-trust-policy.md](model-trust-policy.md) | `test_every_version_the_code_can_emit_resolves` |
| **VOICE-100** | the product is an installed desktop application, not a server | enforced *(exception)* | [user-interface-architecture-and-delivery.md](user-interface-architecture-and-delivery.md) | `test_handshake_is_versioned_and_framed` |
| **VOICE-101** | the dependency direction is one-way, and a test enforces it | enforced *(exception)* | [user-interface-architecture-and-delivery.md](user-interface-architecture-and-delivery.md) | `test_product_tiers_import_only_along_permitted_edges` +2 |
| **VOICE-102** | the interface renders values and computes no financial fact | enforced *(exception)* | [user-interface-architecture-and-delivery.md](user-interface-architecture-and-delivery.md) | `test_no_module_that_speaks_to_a_person_formats_money_itself` |
| **VOICE-103** | every figure crossing the boundary proves itself | enforced *(exception)* | [user-interface-architecture-and-delivery.md](user-interface-architecture-and-delivery.md) | `test_figure_rejects_float_values` |
| **VOICE-104** | the `measures` vocabulary a figure declares is closed | enforced | [user-interface-architecture-and-delivery.md](user-interface-architecture-and-delivery.md) | `test_figure_declares_a_measure_the_vocabulary_holds` |
| **VOICE-105** | every read model declares one explicit panel state | enforced | [user-interface-architecture-and-delivery.md](user-interface-architecture-and-delivery.md) | `test_panel_states_and_action_outcomes_are_closed` |
| **VOICE-106** | an action returns what happened, never a bare `ok` | enforced | [user-interface-architecture-and-delivery.md](user-interface-architecture-and-delivery.md) | `test_panel_states_and_action_outcomes_are_closed` |
| **VOICE-107** | the protocol refuses rather than guesses | enforced | [user-interface-architecture-and-delivery.md](user-interface-architecture-and-delivery.md) | `test_protocol_accepts_additive_minor_changes_only` |
| **VOICE-108** | every capability has a destination or a recorded reason for not having one | enforced | [user-interface-architecture-and-delivery.md](user-interface-architecture-and-delivery.md) | `test_non_surface_capabilities_have_explicit_disposition_and_reason` +1 |
| **VOICE-109** | the bridge is transport and nothing else | enforced *(exception)* | [user-interface-architecture-and-delivery.md](user-interface-architecture-and-delivery.md) | `test_unknown_operations_are_refused_by_the_allowlist` +1 |
| **VOICE-110** | compiled frontend output is never committed | by-review *(exception)* | [user-interface-architecture-and-delivery.md](user-interface-architecture-and-delivery.md) | — |
| **VOICE-111** | every direction shown comes from the account's kind, never a posted sign | enforced | [user-interface-architecture-and-delivery.md](user-interface-architecture-and-delivery.md) | — |
| **VOICE-112** | the surface never claims machinery the product does not have | **unmet** | [user-interface-architecture-and-delivery.md](user-interface-architecture-and-delivery.md) | — |
| **VOICE-113** | these options are removed from future consideration | untestable | [user-interface-architecture-and-delivery.md](user-interface-architecture-and-delivery.md) | — |
| **VOICE-114** | with no reader configured, a document is saved privately and reading waits | enforced *(exception)* | [user-interface-architecture-and-delivery.md](user-interface-architecture-and-delivery.md) | `test_reader_factory_gates_on_env` +6 |
| **VOICE-120** | a slice is complete only against the live boundary it claims | untestable | [user-interface-implementation-status.md](user-interface-implementation-status.md) | — |
| **VOICE-121** | a synthetic fixture proves rendering, never parity | untestable | [user-interface-implementation-status.md](user-interface-implementation-status.md) | — |
| **VOICE-122** | the interview is a primitive with a next step, and it is read-side | enforced | [the-interview-and-the-schema-pack.md](the-interview-and-the-schema-pack.md) | `test_a_vault_built_before_this_replays_identically` |
| **VOICE-123** | the schema is a closed vocabulary | enforced | [the-interview-and-the-schema-pack.md](the-interview-and-the-schema-pack.md) | `test_an_answer_outside_the_offered_vocabulary_is_refused_not_guessed` |
| **VOICE-124** | seed small, generate on first encounter, promote on review | **unmet** | [the-interview-and-the-schema-pack.md](the-interview-and-the-schema-pack.md) | — |
| **VOICE-125** | no amounts and no currency in the interview envelope | **unmet** | [the-interview-and-the-schema-pack.md](the-interview-and-the-schema-pack.md) | — |
| **VOICE-126** | the interview interleaves and never holds the queue | enforced | [the-interview-and-the-schema-pack.md](the-interview-and-the-schema-pack.md) | `test_an_interview_ranks_with_the_other_questions_not_ahead_of_them` |
| **VOICE-127** | essentials terminate the interview and gate net worth | enforced | [the-interview-and-the-schema-pack.md](the-interview-and-the-schema-pack.md) | `test_an_asset_with_no_stated_cost_is_a_gap_never_a_zero` |
| **VOICE-128** | tags gain account scope, and the model copies the person's word | **unmet** | [the-interview-and-the-schema-pack.md](the-interview-and-the-schema-pack.md) | — |
| **VOICE-129** | cycle 1 is deterministic, and a model selector must beat it on measured grounds | enforced | [the-interview-and-the-schema-pack.md](the-interview-and-the-schema-pack.md) | `test_an_account_with_a_schema_is_asked_one_thing_at_a_time` |
| **VOICE-130** | jurisdiction is an attribute of the account, and the country tag is derived | **unmet** | [the-interview-and-the-schema-pack.md](the-interview-and-the-schema-pack.md) | `test_a_jurisdiction_scoped_question_does_not_travel` |
| **VOICE-131** | the sentence and the parse are captured verbatim | enforced | [viva-listens-and-speaks.md](viva-listens-and-speaks.md) | `test_interpretation_exchanges_are_captured_as_outbound_evidence` |
| **VOICE-132** | a gap carries the address its measurement is re-taken at | enforced | [user-interface-implementation-status.md](user-interface-implementation-status.md) | `test_an_anchored_gap_resolves_at_the_address_it_names` +3 |
| **VOICE-133** | five words, five layers, and none of them is a synonym | untestable | [the-words-the-interface-uses.md](the-words-the-interface-uses.md) | — |
| **VOICE-134** | the interface says receipt; the contract keeps citation | **unmet** | [the-words-the-interface-uses.md](the-words-the-interface-uses.md) | — |
| **VOICE-135** | `disabled` is reserved for nothing; `aria-disabled` says a control is busy | **contradicted** | [the-words-the-interface-uses.md](the-words-the-interface-uses.md) | — |
| **VOICE-136** | a destination and a control render only when the registry and a served read say so | **contradicted** | [surface-charter.md](surface-charter.md) | — |
| **VOICE-137** | one absence sentence per panel; the full account lives in Trust | **contradicted** | [surface-charter.md](surface-charter.md) | — |
| **VOICE-138** | the interface speaks about the person's money, never about its machinery | **contradicted** | [surface-charter.md](surface-charter.md) | — |
| **VOICE-139** | the demo is a place, not a dialect | enforced | [surface-charter.md](surface-charter.md) | `test_the_sample_is_a_vault_the_engine_opens` +2 |
| **VOICE-140** | craft is a gate: tokens, and keyboard reach | **unmet** | [surface-charter.md](surface-charter.md) | — |
| **VOICE-141** | the receipt goes to the passage | **unmet** | [surface-charter.md](surface-charter.md) | — |

## PROG — the programme: benchmarks, evals, storage, distribution

The instruments that measure the product, and where truth is kept.

| Rule | Name | State | Doc | Test |
| --- | --- | --- | --- | --- |
| **PROG-1** | What is built is described by capability, not by slice | untestable | [implementation-roadmap.md](implementation-roadmap.md) | — |
| **PROG-2** | Slice labels are frozen and never renumbered | untestable | [implementation-roadmap.md](implementation-roadmap.md) | — |
| **PROG-3** | Nothing is built ahead of its slice | untestable | [implementation-roadmap.md](implementation-roadmap.md) | — |
| **PROG-4** | The surface gates run in CI | by-review | [implementation-roadmap.md](implementation-roadmap.md) | `product/tests/test_surface_contract.py` |
| **PROG-6** | Grading is deterministic code, never a model | enforced | [benchmark-harness-design.md](benchmark-harness-design.md) | `test_grade_perfect_run` +1 |
| **PROG-7** | No composite score | enforced | [benchmark-harness-design.md](benchmark-harness-design.md) | `test_scorecards_group_and_calibrate` |
| **PROG-8** | The answer key never enters the repo; only its hash does | enforced | [benchmark-harness-design.md](benchmark-harness-design.md) | `test_hash_is_order_independent` +1 |
| **PROG-9** | A claim's identity is its value, page and region | **contradicted** | [benchmark-harness-design.md](benchmark-harness-design.md) | — |
| **PROG-10** | Five runs per document per candidate | by-review *(exception)* | [benchmark-harness-design.md](benchmark-harness-design.md) | — |
| **PROG-11** | Unpinned model aliases are refused | by-review | [benchmark-harness-design.md](benchmark-harness-design.md) | — |
| **PROG-12** | The circularity break is four steps | by-review *(exception)* | [benchmark-harness-design.md](benchmark-harness-design.md) | — |
| **PROG-13** | The budget ceiling is hard, and breaching it is refused before it is spent | by-review *(exception)* | [benchmark-harness-design.md](benchmark-harness-design.md) | — |
| **PROG-14** | Source-region validity is graded | **unmet** | [benchmark-harness-design.md](benchmark-harness-design.md) | — |
| **PROG-15** | Cost and latency are reported per document per candidate | **unmet** | [benchmark-harness-design.md](benchmark-harness-design.md) | — |
| **PROG-16** | Model time and wall-clock time keep distinct names | by-review | [benchmark-harness-design.md](benchmark-harness-design.md) | — |
| **PROG-17** | A frozen key's hash is stable | **contradicted** | [benchmark-harness-design.md](benchmark-harness-design.md) | — |
| **PROG-18** | Truncation during key building is warned about loudly | by-review | [benchmark-harness-design.md](benchmark-harness-design.md) | — |
| **PROG-19** | Two adapters, no provider SDK on the wire | enforced | [benchmark-harness-architecture.md](benchmark-harness-architecture.md) | `test_continuation_stitches_and_drops_images` +1 |
| **PROG-20** | Candidates are configuration, never code | by-review | [benchmark-harness-architecture.md](benchmark-harness-architecture.md) | — |
| **PROG-21** | Every model interaction is captured raw before anything parses it | enforced | [benchmark-harness-architecture.md](benchmark-harness-architecture.md) | `test_chain_appends_and_verifies` +1 |
| **PROG-22** | Results are plain files a stranger can read | by-review | [benchmark-harness-architecture.md](benchmark-harness-architecture.md) | — |
| **PROG-23** | `viva-bench report` emits the scorecards | **contradicted** | [benchmark-harness-architecture.md](benchmark-harness-architecture.md) | — |
| **PROG-24** | Honesty is checked before accuracy | enforced *(exception)* | [eval-harness-design.md](eval-harness-design.md) | `test_declining_is_safe_and_never_counted_as_confidently_wrong` |
| **PROG-25** | The confidently-wrong rate is the headline, and its target is zero | enforced | [eval-harness-design.md](eval-harness-design.md) | `test_an_invented_split_is_ruin_even_when_the_majors_are_right` +1 |
| **PROG-26** | A call that never reached the model is scored by nothing | enforced | [eval-harness-design.md](eval-harness-design.md) | `test_a_broken_pipe_is_never_reported_as_a_clean_result` +1 |
| **PROG-27** | The eval runs on every change to trust-critical code | enforced *(exception)* | [eval-harness-design.md](eval-harness-design.md) | `test_the_run_reports_and_holds_a_ceiling` |
| **PROG-28** | The frozen case set ships with the code and holds nobody's data | enforced *(exception)* | [eval-harness-design.md](eval-harness-design.md) | `test_the_key_names_nobody_real` +1 |
| **PROG-29** | The answer path returns structure, not prose | enforced *(exception)* | [eval-harness-design.md](eval-harness-design.md) | `test_balances_match_the_projection_and_carry_grades` +1 |
| **PROG-30** | Opening Balance Equity is permanent and always the earliest known opening | enforced | [individual-as-enterprise.md](individual-as-enterprise.md) | `test_backfill_prepends_older_statements` +1 |
| **PROG-31** | An inferred figure is graded and visible, never a silent plug | enforced | [individual-as-enterprise.md](individual-as-enterprise.md) | `test_gap_between_months_is_surfaced_not_invented` |
| **PROG-32** | P&L and balance sheet are named projections over the posting ledger | **unmet** | [individual-as-enterprise.md](individual-as-enterprise.md) | — |
| **PROG-33** | Reconciliation is the gap detector | enforced | [individual-as-enterprise.md](individual-as-enterprise.md) | `test_gap_held_item_reports_the_held_balance` +1 |
| **PROG-34** | There is no setup phase distinct from use | untestable | [individual-as-enterprise.md](individual-as-enterprise.md) | — |
| **PROG-35** | The required user skill is "can install an app" | untestable | [adoption-and-distribution.md](adoption-and-distribution.md) | — |
| **PROG-36** | No raw key ships in the app, and no plaintext proxy is ever run | by-review | [adoption-and-distribution.md](adoption-and-distribution.md) | — |
| **PROG-37** | The model layer supports four access modes | **unmet** | [adoption-and-distribution.md](adoption-and-distribution.md) | — |
| **PROG-38** | No server component ever holds a key or decrypts the ledger | **unmet** | [multi-device-and-remote-access.md](multi-device-and-remote-access.md) | — |
| **PROG-39** | Two stores, two movement rules | **unmet** | [multi-device-and-remote-access.md](multi-device-and-remote-access.md) | — |
| **PROG-40** | Merging two devices is a union, not a fight over rows | **unmet** | [multi-device-and-remote-access.md](multi-device-and-remote-access.md) | — |
| **PROG-41** | Recovery comes from something the user holds, never from the relay | **unmet** | [multi-device-and-remote-access.md](multi-device-and-remote-access.md) | — |
| **PROG-42** | Nothing is readable at rest | enforced | [local-first-storage-and-crypto.md](local-first-storage-and-crypto.md) | `test_nothing_readable_at_rest` |
| **PROG-43** | The key is derived, never stored | enforced | [local-first-storage-and-crypto.md](local-first-storage-and-crypto.md) | `test_the_vault_header_never_stores_the_passphrase_or_the_key` |
| **PROG-44** | The crypto envelope is versioned, and its cost parameters are pinned | enforced | [local-first-storage-and-crypto.md](local-first-storage-and-crypto.md) | `test_the_production_cost_parameters_are_not_quietly_lowered` |
| **PROG-45** | The log is append-only, hash-chained, and verifiable without the key | enforced | [local-first-storage-and-crypto.md](local-first-storage-and-crypto.md) | `test_the_chain_verifies_without_the_passphrase` +1 |
| **PROG-46** | Original documents are encrypted, immutable, content-addressed blobs | enforced | [local-first-storage-and-crypto.md](local-first-storage-and-crypto.md) | `test_put_is_content_addressed` +1 |
| **PROG-48** | The key is wrapped twice, so a lost device is not ruin | **unmet** | [local-first-storage-and-crypto.md](local-first-storage-and-crypto.md) | — |
| **PROG-49** | The chain head is periodically anchored outside the machine | **unmet** | [local-first-storage-and-crypto.md](local-first-storage-and-crypto.md) | — |
| **PROG-50** | The project borrows a fortress and never builds one | by-review | [own-chain-vs-borrowed-trust.md](own-chain-vs-borrowed-trust.md) | — |
| **PROG-51** | The chain head anchors to a public timestamp | **unmet** | [own-chain-vs-borrowed-trust.md](own-chain-vs-borrowed-trust.md) | — |
| **PROG-52** | Installed apps may verify, never store for strangers | **unmet** | [own-chain-vs-borrowed-trust.md](own-chain-vs-borrowed-trust.md) | — |
| **PROG-53** | Proof rests on signatures, an anchored log and selective disclosure | **unmet** | [own-chain-vs-borrowed-trust.md](own-chain-vs-borrowed-trust.md) | — |
| **PROG-54** | The pack format is a corpus manifest plus a key, zipped | by-review *(exception)* | [benchmark-harness-architecture.md](benchmark-harness-architecture.md) | — |
| **PROG-55** | A case states the source it expects and the grade it expects | **unmet** | [eval-harness-design.md](eval-harness-design.md) | — |

## A — a sentence becomes a ledger entry

The ruling event and the account registry behind it.

| Rule | Name | State | Doc | Test |
| --- | --- | --- | --- | --- |
| **A1** | one generic scoped ruling event | enforced | [from-your-words-to-the-ledger.md](from-your-words-to-the-ledger.md) | `test_a_person_outranks_a_model_and_the_ruling_generalizes` |
| **A2** | an account born from a sentence lives in the same registry | enforced | [from-your-words-to-the-ledger.md](from-your-words-to-the-ledger.md) | `test_an_account_a_document_opened_is_one_the_vault_already_holds` |
| **A3** | every account records who says it exists | enforced | [from-your-words-to-the-ledger.md](from-your-words-to-the-ledger.md) | `test_an_account_records_who_says_it_exists` |
---

## Rules with no test yet

A rule with no test is a rule that holds by review. Some are honestly
untestable and say so; the rest are places a test could be written and has
not been. Grouped by why the gap exists.

### Built, or partly built, and pinned by nothing

57 rules.

| Rule | Name | State | Doc |
| --- | --- | --- | --- |
| **ADR-002** | The project is MIT-licensed | by-review | [decisions/ADR-002-mit-license.md](decisions/ADR-002-mit-license.md) |
| **ADR-006** | Nothing transmits itself, and diagnostics leave only by the person's own hand | by-review-with-exception | [decisions/ADR-006-zero-exfiltration.md](decisions/ADR-006-zero-exfiltration.md) |
| **ADR-009** | Contributions come in under the Developer Certificate of Origin | by-review | [decisions/ADR-009-dco-contributions.md](decisions/ADR-009-dco-contributions.md) |
| **I6** | The admission exam is pack-extensible | by-review | [design-invariants.md](design-invariants.md) |
| **ING-1** | Confidence is constructed, never self-reported | by-review | [extraction-and-confidence.md](extraction-and-confidence.md) |
| **ING-4** | A claim's identity is its value and position, never its label | contradicted-by-code | [extraction-and-confidence.md](extraction-and-confidence.md) |
| **ING-6** | Every stored figure carries a source pointer | by-review-with-exception | [extraction-and-confidence.md](extraction-and-confidence.md) |
| **ING-10** | text+image is the product's input mode, and every read records it | by-review-with-exception | [document-preprocessing.md](document-preprocessing.md) |
| **ING-11** | Input mode is a benchmark dimension, and the modes are image, text, and text+image | by-review | [document-preprocessing.md](document-preprocessing.md) |
| **ING-13** | Ingestion processes a page at a time | contradicted-by-code | [document-preprocessing.md](document-preprocessing.md) |
| **ING-15** | Text extraction is on-device, and cloud document-AI is never on the default path | by-review | [document-preprocessing.md](document-preprocessing.md) |
| **ING-21** | Real documents are never committed | by-review | [document-coverage.md](document-coverage.md) |
| **ING-30** | A held document is polymorphic, and consumers route on the registry | by-review | [doc-type-registry-and-format-profiles.md](doc-type-registry-and-format-profiles.md) |
| **ING-36** | Personal knowledge and format knowledge are kept strictly apart | by-review | [doc-type-registry-and-format-profiles.md](doc-type-registry-and-format-profiles.md) |
| **ING-45** | A measurement, a valuation and an estimate are never dressed as one another | by-review-with-exception | [data-model-considerations.md](data-model-considerations.md) |
| **ING-46** | Regional variety is an attribute on a primitive, never a new primitive | by-review | [data-model-considerations.md](data-model-considerations.md) |
| **ING-64** | The diagnosis rules are versioned | by-review | [verification-findings-and-correction.md](verification-findings-and-correction.md) |
| **ING-70** | The extraction model is a quarantined, powerless worker | by-review | [threat-model-and-ingestion-security.md](threat-model-and-ingestion-security.md) |
| **ING-73** | Extraction and conversation are separate contexts | by-review | [threat-model-and-ingestion-security.md](threat-model-and-ingestion-security.md) |
| **ING-85** | No silent contribution | by-review | [format-commons.md](format-commons.md) |
| **ING-90** | Two timelines per fact: when it happened, and when we learned it | by-review-with-exception | [data-model-considerations.md](data-model-considerations.md) |
| **MER-26** | `queued` and `pending` answer different questions | by-review | [merchantcore-package.md](merchantcore-package.md) |
| **MER-59** | The enrichment run names the catalog it loaded | by-review | [merchant-catalog-and-commons.md](merchant-catalog-and-commons.md) |
| **MON-9** | nature is derived, and no event says it | by-review | [honest-aggregates-and-the-learning-loop.md](honest-aggregates-and-the-learning-loop.md) |
| **MON-20** | the alias maps are built during replay, not per lookup | by-review | [categories-and-tags.md](categories-and-tags.md) |
| **MON-28** | cost is never presented as value, and no model is involved | by-review | [net-worth.md](net-worth.md) |
| **MON-65** | both legs must be ingested own accounts | by-review | [transfer-links-and-cross-document-corroboration.md](transfer-links-and-cross-document-corroboration.md) |
| **MON-76** | enrichment never suggests a tag | by-review | [categories-and-tags.md](categories-and-tags.md) |
| **PROG-4** | The surface gates run in CI | by-review | [implementation-roadmap.md](implementation-roadmap.md) |
| **PROG-9** | A claim's identity is its value, page and region | contradicted-by-code | [benchmark-harness-design.md](benchmark-harness-design.md) |
| **PROG-10** | Five runs per document per candidate | by-review-with-exception | [benchmark-harness-design.md](benchmark-harness-design.md) |
| **PROG-11** | Unpinned model aliases are refused | by-review | [benchmark-harness-design.md](benchmark-harness-design.md) |
| **PROG-12** | The circularity break is four steps | by-review-with-exception | [benchmark-harness-design.md](benchmark-harness-design.md) |
| **PROG-13** | The budget ceiling is hard, and breaching it is refused before it is spent | by-review-with-exception | [benchmark-harness-design.md](benchmark-harness-design.md) |
| **PROG-16** | Model time and wall-clock time keep distinct names | by-review | [benchmark-harness-design.md](benchmark-harness-design.md) |
| **PROG-17** | A frozen key's hash is stable | contradicted-by-code | [benchmark-harness-design.md](benchmark-harness-design.md) |
| **PROG-18** | Truncation during key building is warned about loudly | by-review | [benchmark-harness-design.md](benchmark-harness-design.md) |
| **PROG-20** | Candidates are configuration, never code | by-review | [benchmark-harness-architecture.md](benchmark-harness-architecture.md) |
| **PROG-22** | Results are plain files a stranger can read | by-review | [benchmark-harness-architecture.md](benchmark-harness-architecture.md) |
| **PROG-23** | `viva-bench report` emits the scorecards | contradicted-by-code | [benchmark-harness-architecture.md](benchmark-harness-architecture.md) |
| **PROG-36** | No raw key ships in the app, and no plaintext proxy is ever run | by-review | [adoption-and-distribution.md](adoption-and-distribution.md) |
| **PROG-50** | The project borrows a fortress and never builds one | by-review | [own-chain-vs-borrowed-trust.md](own-chain-vs-borrowed-trust.md) |
| **PROG-54** | The pack format is a corpus manifest plus a key, zipped | by-review-with-exception | [benchmark-harness-architecture.md](benchmark-harness-architecture.md) |
| **PROJ-14** | no registered verb touches the network | by-review | [agent-toolset.md](agent-toolset.md) |
| **PROJ-16** | no registered verb writes | by-review | [agent-toolset.md](agent-toolset.md) |
| **PROJ-38** | a model writes the rules and deterministic code applies them | by-review-with-exception | [where-the-intelligence-goes.md](where-the-intelligence-goes.md) |
| **PROJ-55** | induced grammars are held outside any working tree until a person promotes them | by-review | [orionviva-transaction-intelligence-spec.md](orionviva-transaction-intelligence-spec.md) |
| **PROJ-60** | a small core with view modules behind a facade | by-review | [projection-decomposition-and-the-tool-registry.md](projection-decomposition-and-the-tool-registry.md) |
| **T6** | Nothing leaves silently | by-review | [design-invariants.md](design-invariants.md) |
| **VOICE-110** | compiled frontend output is never committed | by-review-with-exception | [user-interface-architecture-and-delivery.md](user-interface-architecture-and-delivery.md) |
| **VOICE-31** | the product opens as a picture, not a chat | by-review | [experience-vision.md](experience-vision.md) |
| **VOICE-135** | `disabled` is reserved for nothing; `aria-disabled` says a control is busy | contradicted-by-code | [the-words-the-interface-uses.md](the-words-the-interface-uses.md) |
| **VOICE-136** | a destination and a control render only when the registry and a served read say so | contradicted-by-code | [surface-charter.md](surface-charter.md) |
| **VOICE-137** | one absence sentence per panel; the full account lives in Trust | contradicted-by-code | [surface-charter.md](surface-charter.md) |
| **VOICE-138** | the interface speaks about the person's money, never about its machinery | contradicted-by-code | [surface-charter.md](surface-charter.md) |

### Nothing to test — the mechanism is not built

58 rules.

| Rule | Name | State | Doc |
| --- | --- | --- | --- |
| **ADR-011** | A hosted tier may store ciphertext and never compute on it | unmet | [decisions/ADR-011-blind-host-tier.md](decisions/ADR-011-blind-host-tier.md) |
| **ING-7** | A person's word is its own rung, below agreement | unmet | [extraction-and-confidence.md](extraction-and-confidence.md) |
| **ING-12** | Provenance anchors to measured character boxes where a text layer exists | unmet | [document-preprocessing.md](document-preprocessing.md) |
| **ING-14** | A scan is detected per page by ink without text, and only a scan routes to OCR | unmet | [document-preprocessing.md](document-preprocessing.md) |
| **ING-16** | Cloud document-AI, if a user configures it, is labelled data-leaving like any model call | unmet | [document-preprocessing.md](document-preprocessing.md) |
| **ING-34** | A profile may be model-authored, but is ratified before it is used | unmet | [doc-type-registry-and-format-profiles.md](doc-type-registry-and-format-profiles.md) |
| **ING-52** | A tax or annual-summary document produces a fact bundle, not transactions or positions | unmet | [data-model-spike-findings.md](data-model-spike-findings.md) |
| **ING-82** | A profile-guided read passes the same verification floor as a blind one | unmet | [format-commons.md](format-commons.md) |
| **MER-19** | A non-English peer line still crosses where no grammar exists | unmet | [the-conduit-and-the-counterparty.md](the-conduit-and-the-counterparty.md) |
| **MER-32** | The enrichment prompt says a brand string may be truncated | unmet | [merchantcore-package.md](merchantcore-package.md) |
| **MER-70** | A slot empty across a whole statement means the grammar is wrong | unmet | [the-conduit-and-the-counterparty.md](the-conduit-and-the-counterparty.md) |
| **MER-72** | No token from an occurrence attribute reaches the commons, and a test says so | unmet | [the-conduit-and-the-counterparty.md](the-conduit-and-the-counterparty.md) |
| **MON-43** | the net leg cites the specific deposit | unmet | [pay-stubs-and-income.md](pay-stubs-and-income.md) |
| **MON-55** | a cash withdrawal is a spend until an unexplained asset says otherwise | unmet | [the-question-queue.md](the-question-queue.md) |
| **MON-73** | a person and their accounts | unmet | [account-identity-and-entity-resolution.md](account-identity-and-entity-resolution.md) |
| **PROG-14** | Source-region validity is graded | unmet | [benchmark-harness-design.md](benchmark-harness-design.md) |
| **PROG-15** | Cost and latency are reported per document per candidate | unmet | [benchmark-harness-design.md](benchmark-harness-design.md) |
| **PROG-32** | P&L and balance sheet are named projections over the posting ledger | unmet | [individual-as-enterprise.md](individual-as-enterprise.md) |
| **PROG-37** | The model layer supports four access modes | unmet | [adoption-and-distribution.md](adoption-and-distribution.md) |
| **PROG-38** | No server component ever holds a key or decrypts the ledger | unmet | [multi-device-and-remote-access.md](multi-device-and-remote-access.md) |
| **PROG-39** | Two stores, two movement rules | unmet | [multi-device-and-remote-access.md](multi-device-and-remote-access.md) |
| **PROG-40** | Merging two devices is a union, not a fight over rows | unmet | [multi-device-and-remote-access.md](multi-device-and-remote-access.md) |
| **PROG-41** | Recovery comes from something the user holds, never from the relay | unmet | [multi-device-and-remote-access.md](multi-device-and-remote-access.md) |
| **PROG-48** | The key is wrapped twice, so a lost device is not ruin | unmet | [local-first-storage-and-crypto.md](local-first-storage-and-crypto.md) |
| **PROG-49** | The chain head is periodically anchored outside the machine | unmet | [local-first-storage-and-crypto.md](local-first-storage-and-crypto.md) |
| **PROG-51** | The chain head anchors to a public timestamp | unmet | [own-chain-vs-borrowed-trust.md](own-chain-vs-borrowed-trust.md) |
| **PROG-52** | Installed apps may verify, never store for strangers | unmet | [own-chain-vs-borrowed-trust.md](own-chain-vs-borrowed-trust.md) |
| **PROG-53** | Proof rests on signatures, an anchored log and selective disclosure | unmet | [own-chain-vs-borrowed-trust.md](own-chain-vs-borrowed-trust.md) |
| **PROG-55** | A case states the source it expects and the grade it expects | unmet | [eval-harness-design.md](eval-harness-design.md) |
| **PROJ-57** | the forecast ledger | unmet | [orionviva-transaction-intelligence-spec.md](orionviva-transaction-intelligence-spec.md) |
| **PROJ-58** | a search-enabled call is a separate, quarantined path | unmet | [orionviva-transaction-intelligence-spec.md](orionviva-transaction-intelligence-spec.md) |
| **SPINE-5** | Document order lives here and nowhere else | unmet | [reading-guide.md](reading-guide.md) |
| **SPINE-6** | Superseded stays, historical is fenced, neither is deleted | unmet | [reading-guide.md](reading-guide.md) |
| **SPINE-10** | A one-way door gets an ADR before product code exists | unmet | [decisions/README.md](decisions/README.md) |
| **SPINE-11** | A row in the index states a decision, never that it is built | unmet | [decisions/README.md](decisions/README.md) |
| **SPINE-12** | An invariant joins the checklist by deliberate decision | unmet | [design-invariants.md](design-invariants.md) |
| **VOICE-15** | she works in the background, and the work is quiet | unmet | [viva-persona.md](viva-persona.md) |
| **VOICE-33** | a capture surface creates no hosted data | unmet | [experience-vision.md](experience-vision.md) |
| **VOICE-34** | a spoken answer is mirrored in text | unmet | [experience-vision.md](experience-vision.md) |
| **VOICE-65** | a card that fails is a card that failed, never a ledger that failed | unmet | [the-surface-cards.md](the-surface-cards.md) |
| **VOICE-66** | each account kind speaks its own language | unmet | [the-surface-cards.md](the-surface-cards.md) |
| **VOICE-83** | a suggestion binds through the same gate as an answer | unmet | [the-suggestions-channel.md](the-suggestions-channel.md) |
| **VOICE-84** | a suggestion is never a proposal | unmet | [the-suggestions-channel.md](the-suggestions-channel.md) |
| **VOICE-85** | a suggestion respects a decline | unmet | [the-suggestions-channel.md](the-suggestions-channel.md) |
| **VOICE-93** | model versions are pinned; no "latest" alias on the trust path | unmet | [model-trust-policy.md](model-trust-policy.md) |
| **VOICE-94** | every version is a new hire | unmet | [model-trust-policy.md](model-trust-policy.md) |
| **VOICE-95** | autonomy is earned statistically and revoked automatically | unmet | [model-trust-policy.md](model-trust-policy.md) |
| **VOICE-112** | the surface never claims machinery the product does not have | unmet | [user-interface-architecture-and-delivery.md](user-interface-architecture-and-delivery.md) |
| **VOICE-124** | seed small, generate on first encounter, promote on review | unmet | [the-interview-and-the-schema-pack.md](the-interview-and-the-schema-pack.md) |
| **VOICE-125** | no amounts and no currency in the interview envelope | unmet | [the-interview-and-the-schema-pack.md](the-interview-and-the-schema-pack.md) |
| **VOICE-128** | tags gain account scope, and the model copies the person's word | unmet | [the-interview-and-the-schema-pack.md](the-interview-and-the-schema-pack.md) |
| **VOICE-134** | the interface says receipt; the contract keeps citation | unmet | [the-words-the-interface-uses.md](the-words-the-interface-uses.md) |
| **VOICE-140** | craft is a gate: tokens, and keyboard reach | unmet | [surface-charter.md](surface-charter.md) |
| **VOICE-141** | the receipt goes to the passage | unmet | [surface-charter.md](surface-charter.md) |
| **X1** | Target user skill: "can install an app" | unmet | [design-invariants.md](design-invariants.md) |

### Untestable by nature

19 rules.

| Rule | Name | State | Doc |
| --- | --- | --- | --- |
| **ADR-008** | The public promises are an explicit inventory, and nothing may promise more than it holds | untestable | [decisions/ADR-008-public-promise-inventory.md](decisions/ADR-008-public-promise-inventory.md) |
| **ING-20** | A document type counts as covered only when a real one has posted | untestable | [document-coverage.md](document-coverage.md) |
| **MON-11** | abstract the read side early, the write side late | untestable | [honest-aggregates-and-the-learning-loop.md](honest-aggregates-and-the-learning-loop.md) |
| **MON-12** | route on the registry, not on the shape of the data | untestable | [honest-aggregates-and-the-learning-loop.md](honest-aggregates-and-the-learning-loop.md) |
| **MON-77** | tags start fresh; existing labels are left alone | untestable | [categories-and-tags.md](categories-and-tags.md) |
| **PROG-1** | What is built is described by capability, not by slice | untestable | [implementation-roadmap.md](implementation-roadmap.md) |
| **PROG-2** | Slice labels are frozen and never renumbered | untestable | [implementation-roadmap.md](implementation-roadmap.md) |
| **PROG-3** | Nothing is built ahead of its slice | untestable | [implementation-roadmap.md](implementation-roadmap.md) |
| **PROG-34** | There is no setup phase distinct from use | untestable | [individual-as-enterprise.md](individual-as-enterprise.md) |
| **PROG-35** | The required user skill is "can install an app" | untestable | [adoption-and-distribution.md](adoption-and-distribution.md) |
| **SPINE-2** | An invariant is cited by the rule that bears on it | untestable | [README.md](README.md) |
| **SPINE-8** | The trust trial runs alongside breadth, never in front of it | untestable | [implementation-roadmap.md](implementation-roadmap.md) |
| **SPINE-9** | The phases past the product are gated on earned trust, not on a calendar | untestable | [implementation-roadmap.md](implementation-roadmap.md) |
| **VOICE-30** | Viva is summoned, never ambient | untestable | [experience-vision.md](experience-vision.md) |
| **VOICE-59** | no agent-memory framework | untestable | [viva-listens-and-speaks.md](viva-listens-and-speaks.md) |
| **VOICE-113** | these options are removed from future consideration | untestable | [user-interface-architecture-and-delivery.md](user-interface-architecture-and-delivery.md) |
| **VOICE-120** | a slice is complete only against the live boundary it claims | untestable | [user-interface-implementation-status.md](user-interface-implementation-status.md) |
| **VOICE-121** | a synthetic fixture proves rendering, never parity | untestable | [user-interface-implementation-status.md](user-interface-implementation-status.md) |
| **VOICE-133** | five words, five layers, and none of them is a synonym | untestable | [the-words-the-interface-uses.md](the-words-the-interface-uses.md) |

**Total: 134 of 483 rules are pinned by no test.**
---

## Rules the code contradicts

Eleven rows stand here. Each names where the rule is written and where the code
disagrees with it. A contradiction is a ruling owed, not a bug report: for
several of these the code is right and the sentence is stale. One row is now
narrower than the heading above it — VOICE-135's code no longer contradicts it
anywhere, and the row stays because the state word can rise no further than
`by-review` while the only things holding the rule are a Node gate and
TypeScript tests, and moving it even that far is the product owner's.

| Rule | Doc says | Code does |
| --- | --- | --- |
| **T7** — IDs are permanent; fingerprints are versioned<br>[design-invariants.md:76](design-invariants.md) | Two fields, two jobs: a permanent random id, and a separate versioned content fingerprint. | One content-derived string does both. A document's id is the SHA-256 of its own bytes (`product/viva/ingest/raw_store.py:45`); a movement is keyed by that id plus account, date, amount, description and occurrence (`product/viva/ledger/projection/movements.py:18`). The `uuid4` at `product/viva/ledger/events.py:127` is referenced by nothing. |
| **ADR-007** — a permanent random identity and a versioned content fingerprint<br>[decisions/ADR-007-record-identity.md:13](decisions/ADR-007-record-identity.md) | The same decision, stated as the one-way door it was. | Same divergence as T7: `product/viva/ingest/raw_store.py:45`, `product/viva/ledger/projection/movements.py:18`, `product/viva/ledger/events.py:127`. |
| **ING-4** — a claim's identity is its value and position, never its label<br>[extraction-and-confidence.md:47](extraction-and-confidence.md) | Two extractions are matched on printed value and page position; a model-authored label is an annotation, never a join key. | `bench/vivabench/keybuild.py:113` indexes drafts on `(type, normalized label)` and merges with `setdefault`, so the label *is* the join key and later claims in a bucket are dropped silently. `core/vivacore/claims.py:30` returns that same tuple from `Claim.key()`. |
| **ING-13** — ingestion processes a page at a time<br>[document-preprocessing.md:36](document-preprocessing.md) | A document is extracted page by page, so one bad page is one bad page and no read is capped by a whole-document output ceiling. | `product/viva/ingest/reader.py:118` passes the whole `pages` list to one `adapter.extract` call; the ceiling is handled by continuation (`core/vivacore/models/anthropic_adapter.py:42`). Only the classify pass is bounded to one page (`product/viva/ingest/reader.py:70`). The bench does read page-at-a-time (`bench/vivabench/runner.py:118`), so exam and product differ. |
| **PROG-9** — a claim's identity is its value, page and region<br>[benchmark-harness-design.md:34](benchmark-harness-design.md) | A claim is identified by `(value, page, region)`; the label is an annotation. | Same site as ING-4: `core/vivacore/claims.py:30` and `bench/vivabench/keybuild.py:113`. Page, region and page-namespaced group are written onto every claim by the runner and read by nothing. |
| **PROG-17** — a frozen key's hash is stable<br>[benchmark-harness-design.md:111](benchmark-harness-design.md) | Freezing twice yields the identical key and hash, so a re-run can prove it used the same key. | `bench/vivabench/cli.py:183` re-reads the audit worksheet and appends every resolved row to `key.entries` on every invocation; `bench/vivabench/keybuild.py:158` only sets the flag and hashes what it is handed. Entries grow each pass and each pass commits a different hash. |
| **PROG-23** — `viva-bench report` emits the scorecards<br>[benchmark-harness-architecture.md:42](benchmark-harness-architecture.md) | `report` writes scorecards as markdown and JSON per (model, doc type, locale). | `bench/vivabench/cli.py:287` registers `report` as a bare alias of `cmd_score` without the `--mode` flag `cmd_score` reads (`:233`), so every invocation raises `AttributeError` before a record is read. `bench/tests/` has no CLI coverage. `score` works. |
| **VOICE-135** — `disabled` is reserved for nothing; `aria-disabled` says a control is busy<br>[the-words-the-interface-uses.md:34](the-words-the-interface-uses.md) | `disabled` is reserved for nothing: a control the screen cannot perform at all does not render, and a control it can perform and is only busy with carries `aria-disabled`, so the person keeps the control under their hands. | The attribute appears in no JSX under `desktop/src`, and `desktop/scripts/check-ui-boundaries.mjs` holds it out of the whole tree. The folder picker and vault-open submit in `desktop/src/app/App.tsx` and the conversation's set-aside controls in `desktop/src/features/conversation/Questions.tsx` all carry `aria-disabled` while the vault answers, stay focusable, and refuse a second press in their own handler. Nothing in the code contradicts the rule any longer; what keeps the row here is that no test this index can read holds any of it, and moving the word is the product owner's. |
| **VOICE-136** — a destination and a control render only when the registry and a served read say so<br>[surface-charter.md:37](surface-charter.md) | Navigation is a projection of the capability registry: a destination renders when a surfaced capability claims it and its live read is served, and an affordance renders only when the operation behind it is served and allowlisted. | `desktop/src/app/navigation.ts` still hand-writes five destination memberships while deriving their runtime standing. Activity and Trust are now claimed and live; Accounts still ships without its own live read or claiming capability, so the rule remains contradicted for one destination. |
| **VOICE-137** — one absence sentence per panel; the full account lives in Trust<br>[surface-charter.md:83](surface-charter.md) | A panel states at most one absence, in one plain sentence, and only when the absence changes what the person should do next; the enumeration of what this build cannot do lives on Trust and nowhere else. | Multiple field-level absence sentences remain in `desktop/src/features/conversation/Questions.tsx`, `desktop/src/features/documents/Documents.tsx` and `desktop/src/components/EvidenceDrawer.tsx`. `desktop/src/features/documents/Documents.tsx` also renders an enumeration headed "Unavailable in this preview", and the sidebar carries a standing admission on every destination. |
| **VOICE-138** — the interface speaks about the person's money, never about its machinery<br>[surface-charter.md:125](surface-charter.md) | Contract and delivery vocabulary does not reach a person on a primary surface, and no raw identifier is a primary label. | Conversation no longer renders raw question IDs, contract vocabulary or a separate identity-conflict headline. The remaining contradiction includes person-facing "supplied" wording there and identity-conflict wording in Accounts, Activity and Trust. |
