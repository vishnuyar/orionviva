# Merchant Catalog & the Categorization Commons — categorize the merchant, once, for everyone

**State:** partial — the local catalog, versioned merchant identity aliases, first shipped business seed and import-time application are built; the networked commons registry is not
**Rules:** MER-40, MER-41, MER-42, MER-43, MER-44, MER-45, MER-46, MER-47, MER-48, MER-49, MER-59

## Rules

### MER-40 — Categorize the merchant, not the transaction
**State:** enforced
**Code:** product/viva/ledger/projection/categories.py (`derived_category`), product/viva/ingest/categorize.py (`assign_merchant_category`)
**Test:** product/tests/test_merchants.py::test_merchant_ruling_fills_all_its_transactions, product/tests/test_merchants.py::test_merchant_ruling_survives_a_replay

1. The reusable unit of categorization is the permanent merchant id. A normalized descriptor is recognition evidence, not the identity itself. Movement-scoped corrections and import defaults are append-only overlays rather than rewritten postings.
2. The derivation is: a human or model per-transaction override, else the strongest catalog record the merchant is filed under, else a replaceable unverified import default, else `Uncategorized`.
3. Because it is a projection, one ruling categorizes every transaction from that merchant, past and future.
4. A merchant rule is an append-only event; the catalog is a projection over the encrypted log, so it survives a replay.

### MER-41 — The catalog is a prior; the override wins
**State:** enforced
**Code:** product/viva/ledger/projection/categories.py (`_record_for`), product/viva/ledger/projection/merchants.py (`merchant_graded`), merchant/merchantcore/catalog.py (`_GRADE_RANK`)
**Test:** product/tests/test_merchants.py::test_per_transaction_override_beats_the_merchant_rule, product/tests/test_merchant_enrich.py::test_human_override_beats_the_synced_enrichment

1. The grade ladder is `verified` > `corroborated` > `unverified` > `Uncategorized`.
2. A human per-transaction ruling is `verified` and beats any merchant-level prior. An ordinary model movement override also wins at its recorded grade; only `by="default"` is deliberately replaceable by merchant knowledge.
3. A model batch and a commons prior both enter as `corroborated`, never as fact.

### MER-42 — Every lookup preserves canonical and legacy keys
**State:** enforced
**Code:** product/viva/ledger/projection/merchants.py:59 (`merchant_keys_of`), :96 (`merchant_graded`); product/viva/ingest/categorize.py (`assign_merchant_category`)
**Test:** product/tests/test_merchant_keys.py::test_reviewed_aliases_group_two_location_forms_under_one_merchant, ::test_a_verified_old_alias_record_beats_the_canonical_commons_prior, ::test_a_descriptor_keyed_answer_still_reads, ::test_the_brand_wins_a_tie

1. A movement first tries the canonical id resolved from exact reviewed aliases, then its structural/brand candidates and normalized descriptor.
2. The highest-graded record among the candidates answers; ties go to the canonical id.
3. Knowledge recorded before grammars existed sits under the descriptor and is not stranded by a lookup that only knew the brand.
4. A question's resolved key is recorded exactly when the projection already holds it; only an unresolved raw descriptor is normalized again before filing.

### MER-43 — The sync reaches only merchants this vault holds
**State:** enforced
**Code:** product/viva/ingest/categorize.py (`sync_merchant_records`)
**Test:** product/tests/test_merchant_enrich.py::test_a_record_about_a_merchant_this_vault_never_paid_is_not_synced

1. Only keys this vault offered, plus keys its ledger already carries a record for, are synced into the ledger.
2. A catalog record about a merchant this vault never paid appends no event to this vault's append-only log.
3. A balance-statement import performs the same bounded sync for that document before assigning defaults. A shipped or learned hit therefore categorizes immediately without an enrichment/model call; a miss keeps the replaceable default.

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
**Code:** merchant/merchantcore/taxonomy.py (`PRIMARY_CATEGORIES`, `FALLBACK_CATEGORY`, `canonical_primary`); product/viva/ingest/categorize.py (`SEED_CATEGORIES`, assertion 3 imports that same list)
**Test:** merchant/tests/test_merchantcore.py::test_sixteen_primary_categories

1. There are sixteen controlled primary buckets plus one fallback.
2. A proposed category outside the set becomes the fallback rather than being stored as offered.
3. `merchantcore.taxonomy.PRIMARY_CATEGORIES` is the one list the product's category picker also reads.

### MER-46 — The unencrypted catalog carries no money
**State:** enforced
**Code:** merchant/merchantcore/catalog.py (`export`, `_save`), product/viva/ingest/categorize.py (`export_catalog`)
**Test:** product/tests/test_merchants.py::test_export_catalog_is_linted_and_carries_no_amounts

1. The raw descriptor never leaves the encrypted ledger.
2. What is written unencrypted or shared holds merchant knowledge only: no amounts, no dates, no transaction links.
3. A record is exported only when its permanent id and every reviewed alias pass the privacy lint and its typed counterparty is a business. Peer, person-name and financial-instrument records are filtered out entirely.

### MER-47 — The taxonomy is a versioned data pack
**State:** enforced
**Code:** merchant/merchantcore/versions.json (`taxonomy` family), merchant/merchantcore/data/cat-v3.json, merchant/merchantcore/taxonomy.py:31 (`TAXONOMY_VERSION`), :111 (the file declares its own version)
**Test:** merchant/tests/test_merchantcore_versions.py::test_the_manifest_and_the_files_agree, merchant/tests/test_subcategory_seed.py::test_a_file_whose_version_is_not_its_name_is_refused

1. The seed vocabulary ships in a file named for the taxonomy version it is, so a record's stamped version resolves to the exact list that produced it (T8).
2. The version in force is read from the manifest, never written as a literal.
3. The vocabulary is authored against the primaries from world knowledge, never from a vault (T9).

### MER-48 — Merchant recognition is deterministic and versioned, never fuzzy
**State:** enforced
**Code:** merchant/merchantcore/normalize.py (`normalize_merchant`), merchant/merchantcore/resolve.py (`Resolution.identity_candidates`), merchant/merchantcore/catalog.py (`CATALOG_FORMAT`, `IDENTITY_VERSION`, `resolve`)
**Test:** merchant/tests/test_merchantcore.py::test_store_number_boundaries_offer_exact_identity_candidates, ::test_reviewed_aliases_resolve_exactly_and_near_names_do_not, ::test_a_broken_v2_identity_pack_is_refused, product/tests/test_merchant_keys.py::test_reviewed_aliases_do_not_match_a_near_name_or_arbitrary_text

1. Normalization and structural parsing produce ordered recognition candidates: a proven grammar brand, a published-parser brand, the exact prefix before a proven occurrence slot such as a store number, and the normalized full descriptor.
2. Only an exact, reviewed alias can map a candidate onto a permanent merchant id. Substrings, token similarity, edit distance, embeddings, model judgement, city lists, wildcards and regexes have no identity authority.
3. Catalog format and identity algorithm versions travel with the alias pack; incompatible or malformed packs, unnormalized aliases and collisions are refused.
4. A model-authored `canonical_name` remains display metadata. It cannot mint or merge identity, and an unmatched descriptor remains honestly unknown.

### MER-49 — An unknown merchant stays unknown while its movement gets a replaceable default
**State:** enforced
**Code:** product/viva/ledger/projection/categories.py (`derived_category` and `_record_for`), product/viva/ingest/categorize.py (`assign_default_categories`), product/viva/engine.py (`upload`)
**Test:** product/tests/test_categorize.py::test_import_defaults_peer_payments_before_asking_questions, product/tests/test_merchants.py::test_merchant_ruling_fills_all_its_transactions

1. A successfully posted bank or card statement gives each otherwise unknown movement an unverified, movement-scoped first category, so import does not become an interview. A grammar slot that declared a person permits the `transfers` default and its transfer treatment, keeping it outside spending unless the person corrects it; every other unidentified movement starts at `other` and ordinary spending treatment.
2. The default does not identify the merchant and does not generalize to older or future movements. Unknown merchants remain in the pending enrichment set, and later catalog knowledge replaces the default on the read side.
3. A person's movement correction outranks both the import default and catalog knowledge.

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

Recognition is deterministic and versioned, never fuzzy matching, because fuzzy
merges the wrong things — "Costco" against "Costa Coffee", "Chase" against
"Chevron". The normalizer leaves merchant words as read. Where parsing proves a
store-number boundary, its left-hand prefix becomes one exact candidate; a
reviewed alias may map that candidate to a permanent id. Thus `costco`, `costco
at`, and `costco whse` converge across locations, while arbitrary text containing
`costco` does not. With no structural proof or exact alias, the full normalized
descriptor remains the key and the merchant remains unknown.

Batching is what makes it cheap and honest at once. A known merchant
auto-categorizes for free on a catalog lookup; an unknown one is shown as
unknown — not guessed — and joins a pending set that a later batched pass
resolves retrospectively. Honest unknowns are X2 doing its job. The run also
reports which catalog it loaded and how much is in it, because a shared store
that silently loads the wrong file is worse than no sharing at all.

The key had to move. Enrichment once filed under the brand while every read
looked under the descriptor, so a vault could hold a full catalog and read as
though it held none. Reads now consider canonical identity, structural/brand
candidates and the legacy descriptor, then let grade decide. A verified local
answer therefore survives an alias migration and still outranks a commons prior.

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

- The commons *registry* itself: a git repo of `permanent merchant id → category`
  packs with an explicit identity-algorithm version and locale,
  corroborated-by-count and reviewed aliases for rebrands. `export` is its input;
  the registry, the PR flow and the merge
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
