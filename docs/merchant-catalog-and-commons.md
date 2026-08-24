# Merchant Catalog & the Categorization Commons — categorize the merchant, once, for everyone

**State:** partial — the catalog and its derivation are built; the commons registry is not
**Rules:** MER-40, MER-41, MER-42, MER-43, MER-44, MER-45, MER-46, MER-47, MER-48, MER-49, MER-59

## Rules

### MER-40 — Categorize the merchant, not the transaction
**State:** enforced
**Code:** product/viva/ledger/projection/categories.py:36 (`derived_category`), product/viva/ingest/categorize.py:190
**Test:** product/tests/test_merchants.py::test_merchant_ruling_fills_all_its_transactions, product/tests/test_merchants.py::test_merchant_ruling_survives_a_replay

1. The unit of categorization is the normalized merchant; a transaction's category is derived, never stored on the transaction.
2. The derivation is: a per-transaction override, else the strongest catalog record the merchant is filed under, else `Uncategorized`.
3. Because it is a projection, one ruling categorizes every transaction from that merchant, past and future.
4. A merchant rule is an append-only event; the catalog is a projection over the encrypted log, so it survives a replay.

### MER-41 — The catalog is a prior; the override wins
**State:** enforced
**Code:** product/viva/ledger/projection/categories.py:28 (`_record_for`), product/viva/ledger/projection/merchants.py:96 (`merchant_graded`), merchant/merchantcore/catalog.py:26 (`_GRADE_RANK`)
**Test:** product/tests/test_merchants.py::test_per_transaction_override_beats_the_merchant_rule, product/tests/test_merchant_enrich.py::test_human_override_beats_the_synced_enrichment

1. The grade ladder is `verified` > `corroborated` > `unverified` > `Uncategorized`.
2. A per-transaction ruling is `verified` and beats any merchant-level prior.
3. A model batch and a commons prior both enter as `corroborated`, never as fact.

### MER-42 — Every lookup considers both keys
**State:** enforced
**Code:** product/viva/ledger/projection/merchants.py:59 (`merchant_keys_of`), :96 (`merchant_graded`); product/viva/ingest/categorize.py (`assign_merchant_category`)
**Test:** product/tests/test_merchant_keys.py::test_a_descriptor_keyed_answer_still_reads, product/tests/test_merchant_keys.py::test_the_brand_wins_a_tie, product/tests/test_merchant_keys.py::test_a_persons_answer_beats_a_models_whichever_key_it_is_under, product/tests/test_questions.py::test_answering_a_resolved_numbered_merchant_closes_that_exact_question

1. A movement's candidate keys are the brand a resolver named and the normalized descriptor, in that order.
2. The highest-graded record among the candidates answers; ties go to the brand.
3. Knowledge recorded before grammars existed sits under the descriptor and is not stranded by a lookup that only knew the brand.
4. A question's resolved key is recorded exactly when the projection already holds it; only an unresolved raw descriptor is normalized again before filing.

### MER-43 — The sync reaches only merchants this vault holds
**State:** enforced
**Code:** product/viva/ingest/categorize.py:270-283
**Test:** product/tests/test_merchant_enrich.py::test_a_record_about_a_merchant_this_vault_never_paid_is_not_synced

1. Only keys this vault offered, plus keys its ledger already carries a record for, are synced into the ledger.
2. A catalog record about a merchant this vault never paid appends no event to this vault's append-only log.

### MER-44 — The subcategory vocabulary is seeded, and grows without displacing
**State:** enforced
**Code:** merchant/merchantcore/taxonomy.py:91 (`read_subcategory_seed`), :157 (`seed_subcategories`), :170 (`subcategory_vocabulary`), merchant/merchantcore/enrich.py:299, :309 (`_new_labels`)
**Test:** merchant/tests/test_subcategory_seed.py::test_the_seed_leads_and_a_vault_label_follows, ::test_a_vault_label_the_seed_does_not_hold_is_never_removed, ::test_the_second_chunk_is_shown_what_the_first_one_minted, ::test_a_run_reports_the_labels_it_minted, product/tests/test_category_identity.py::test_a_seed_label_never_displaces_one_a_person_minted

1. The shipped seed leads the list a model is shown and the vault's own labels follow, deduped under the separator identity.
2. A seed label wins on *spelling* only; it never removes a label already in use.
3. The list grows across a run: a label chunk N minted is in the list chunk N+1 is shown.
4. Minting is never blocked; the run reports how many labels it minted beyond the list it was shown.
5. A file whose faults would corrupt the vocabulary raises rather than loading quietly — a version that is not its filename, a group under a name that is not a primary, a label that is also a primary, a label with no gloss, two labels that are one label under the fold.

### MER-45 — The primary category set is controlled and is the single source
**State:** enforced
**Code:** merchant/merchantcore/taxonomy.py:34 (`PRIMARY_CATEGORIES`), :53 (`FALLBACK_CATEGORY`), :60 (`canonical_primary`); product/viva/ingest/categorize.py:29 (assertion 3 — the product imports that same list and builds `SEED_CATEGORIES` from it)
**Test:** merchant/tests/test_merchantcore.py::test_sixteen_primary_categories

1. There are sixteen controlled primary buckets plus one fallback.
2. A proposed category outside the set becomes the fallback rather than being stored as offered.
3. `merchantcore.taxonomy.PRIMARY_CATEGORIES` is the one list the product's category picker also reads.

### MER-46 — The unencrypted catalog carries no money
**State:** enforced
**Code:** merchant/merchantcore/catalog.py:161 (`export`), :187 (`_save`), product/viva/ingest/categorize.py:298 (`export_catalog`)
**Test:** product/tests/test_merchants.py::test_export_catalog_is_linted_and_carries_no_amounts

1. The raw descriptor never leaves the encrypted ledger.
2. What is written unencrypted or shared holds merchant knowledge only: no amounts, no dates, no transaction links.
3. A peer-payment or person-name key is filtered out of the export entirely.

### MER-47 — The taxonomy is a versioned data pack
**State:** enforced
**Code:** merchant/merchantcore/versions.json (`taxonomy` family), merchant/merchantcore/data/cat-v3.json, merchant/merchantcore/taxonomy.py:31 (`TAXONOMY_VERSION`), :111 (the file declares its own version)
**Test:** merchant/tests/test_merchantcore_versions.py::test_the_manifest_and_the_files_agree, merchant/tests/test_subcategory_seed.py::test_a_file_whose_version_is_not_its_name_is_refused

1. The seed vocabulary ships in a file named for the taxonomy version it is, so a record's stamped version resolves to the exact list that produced it (T8).
2. The version in force is read from the manifest, never written as a literal.
3. The vocabulary is authored against the primaries from world knowledge, never from a vault (T9).

### MER-48 — Normalization is deterministic and versioned, never fuzzy string-matching
**State:** enforced
**Code:** merchant/merchantcore/normalize.py:21 (`NORMALIZER_VERSION`), :49 (`normalize_merchant` — a fixed sequence of strips: processor prefix, date fragment, phone, order id, store number, long number, punctuation)
**Test:** merchant/tests/test_merchantcore.py::test_normalize_is_deterministic_and_versioned, merchant/tests/test_merchantcore.py::test_a_date_fragment_does_not_become_part_of_the_key, product/tests/test_merchants.py::test_normalizer_is_deterministic_and_versioned

1. A raw descriptor becomes a canonical key by deterministic rules that strip the tail varying transaction to transaction; nothing is merged by fuzzy string similarity.
2. The normalizer carries a version, so a catalog key is portable across users — the precondition for the commons.

### MER-49 — An unknown merchant is shown as unknown, not guessed
**State:** enforced
**Code:** product/viva/ledger/projection/categories.py:36 (`derived_category` returns `None` where no override and no catalog record answer), :232 (the `Uncategorized` bucket), :296 (`uncategorized_merchants`, the batched enricher's pending set), product/viva/ingest/categorize.py:33 (`UNCATEGORIZED`)
**Test:** product/tests/test_merchants.py::test_merchant_ruling_fills_all_its_transactions

1. A merchant no record covers derives no category and is shown as `Uncategorized`; nothing fills one in on its behalf (X2).
2. Unknown merchants join the pending set that a later batched pass resolves retrospectively, so waiting costs a visible unknown rather than a guess.

### MER-59 — The enrichment run names the catalog it loaded
**State:** by-review
**Code:** product/viva/enrich.py:141 (`known`), :145 (the file), :146 (how many merchants it already holds, and the empty-catalog warning)
**Test:** none

1. The run reports which catalog file it loaded and how much is in it, before anything is spent.
2. An empty catalog says so, because every merchant below it will then cost a model call.

## Why

Normalization, enrichment and the catalog store itself live in the standalone
package — [merchantcore-package.md](merchantcore-package.md). This document is the
design of how the product *applies* that knowledge to its ledger.

The category overlay shipped per-transaction categorization, and real use showed
the flaw within a day: you categorize one Amazon charge and the next Amazon
charge asks again — twenty purchases, twenty asks. A vault holds thousands of
transactions but a few hundred distinct merchants, so categorizing the *merchant*
turns an O(transactions) model cost into an O(new-merchants) one. The same move
produces the artifact a commons can share, because a merchant→category mapping is
the small impersonal unit.

Splitting what is unencrypted is the load-bearing privacy decision. Raw
descriptors carry order ids and peer names, so they stay in the encrypted ledger;
only a privacy-linted merchant→category catalog is ever unencrypted or shared.
Even then, the *set* of merchants you frequent is mildly identifying, so local
plaintext is fine and contribution is opt-in and popular-biased.

Normalization is deterministic and versioned, never fuzzy matching, because fuzzy
merges the wrong things — "Costco" against "Costa Coffee", "Chase" against
"Chevron". The normalizer strips the tail that varies transaction to transaction
and leaves the merchant words as read; a model then groups the deduped list.
Location does not fragment the category, and versioning the normalizer is what
makes keys portable across users, which is a precondition for the commons.

Batching is what makes it cheap and honest at once. A known merchant
auto-categorizes for free on a catalog lookup; an unknown one is shown as
unknown — not guessed — and joins a pending set that a later batched pass
resolves retrospectively. Honest unknowns are X2 doing its job. The run also
reports which catalog it loaded and how much is in it, because a shared store
that silently loads the wrong file is worse than no sharing at all.

The key had to move. Enrichment always filed under the brand while every read
looked under the descriptor, so a vault could hold a full catalog and read as
though it held none. Considering both candidates and letting the higher-graded
record answer is what stops knowledge recorded before grammars existed from being
stranded — and a person's own answer is the most trustworthy record in the vault,
so losing it to a key change would be the worst possible failure.

The subcategory was an open value a model invented per call, and a run told call
N+1 nothing about what call N had decided, so one idea came back under three
spellings with the split falling on a call boundary. Two halves of one fix: ship a
vocabulary as a versioned pack, and let the list a chunk is shown grow by what the
previous chunk minted. The seed leads and the vault follows, so a seed label wins
on spelling only and never removes a label already in use — which is the general
rule that a model may propose a fold and may never apply one (T9; MON-82–MON-84 in
[categories-and-tags.md](categories-and-tags.md)).

Two traps were disarmed rather than features added. `Catalog` took a `shipped`
path with no loader to serve it and a `load()` that replaced its record dict
wholesale, so the day a file landed in `data/` construction would raise, and a
correct loader would have been erased by the first learned catalog anyway. And
`enrich_merchants` synced *every* record in the catalog into the ledger; since the
catalog is shared by every vault on the machine and may one day be seeded, that
would write events about merchants this person never paid into an append-only log
that has no delete. Both were no-ops on the day they were closed, which is exactly
why they were cheap to close.

Measured on a real vault, the seed took subcategory labels from 23.2% to 98.6% of
distinct labels and from 35.1% to 99.5% of merchants, with one label minted beyond
the shipped list; of 190 keys in both catalogs, 124 moved minted→seed and none
moved the other way. The honest limit is that the file groups labels under a
primary and glosses each, but the loader returns a flat tuple, so the model sees
bare words: at `(primary, label)` granularity the same run reads 31.7% → 87.5%,
with 12% of records landing on a seed word under a primary the seed does not file
it under.

## Open

- The commons *registry* itself: a git repo of `merchant → category` keyed by
  normalizer version and locale, corroborated-by-count, self-healing as merchants
  rebrand. `export` is its input; the registry, the PR flow and the merge
  semantics beyond `Catalog.merge` do not exist. Same lifecycle as
  [format-commons.md](format-commons.md), and this catalog is its seed.
- Merchant as a Party, and per-location analytics (Costco Plano versus Frisco)
  attaching to the same key.
- Amount-splits and tags, deferred from the category overlay; both compose over
  the derived category unchanged.
- Showing the model the seed's grouping, or its glosses, rather than a flat list.
  It is a free experiment nobody has run, and the `(primary, label)` figure is the
  measurement it would move.
- The privacy lint `is_shareable` remains the fallback wherever no grammar exists;
  it over-blocks by design and is retired per institution by inducing one. See
  MER-13 in [the-conduit-and-the-counterparty.md](the-conduit-and-the-counterparty.md).
