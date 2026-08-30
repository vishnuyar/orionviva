# merchantcore — the merchant enrichment package

**State:** built
**Rules:** MER-20, MER-21, MER-22, MER-23, MER-24, MER-25, MER-26, MER-27, MER-28, MER-29, MER-30, MER-31, MER-32

## Rules

### MER-20 — Only a key and a linted example cross into the package
**State:** enforced
**Code:** product/viva/ingest/categorize.py:192 (`enrich_merchants`), product/viva/ledger/hints.py:69 (`Hint.example`), merchant/merchantcore/descriptor.py:265 (`linted_example`)
**Test:** product/tests/test_merchant_enrich.py::test_only_impersonal_hints_cross_the_boundary, product/tests/test_streams.py::test_no_digit_reaches_the_boundary

1. What crosses product → merchantcore is an ordered set of structurally justified, normalized identity candidates and an impersonal example composed of the brand plus context slots.
2. No amount, date, account, transaction reference or count crosses.
3. `linted_example` removes every span a published rule proves, then every token carrying a digit, then anything shorter than two characters, and truncates.
4. A linted example is not a guarantee of impersonality on its own; only the slot a value came from settles that (MER-3, MER-13 in [the-conduit-and-the-counterparty.md](the-conduit-and-the-counterparty.md)).

### MER-21 — The lint is a property of the store
**State:** enforced
**Code:** merchant/merchantcore/catalog.py:55 (`submit`), :67 (lints again on the way in)
**Test:** merchant/tests/test_merchantcore.py::test_catalog_pending_add_and_linted_export

1. `submit` lints every example again, whatever the caller did.
2. The pending queue persists to plain unencrypted JSON, and anything submitted and never enriched sits in it indefinitely, so the invariant belongs to the store rather than to whoever writes the next caller.
3. `submit` skips merchants already in the catalog and merchants already queued against the same example, so it is idempotent.

### MER-22 — An enriched record is graded and stamped
**State:** enforced
**Code:** merchant/merchantcore/enrich.py:117 (`parse_enrichment_chunk`), :93 (version composition), merchant/merchantcore/record.py:16
**Test:** merchant/tests/test_merchantcore.py::test_enricher_is_one_call_and_grades_records, merchant/tests/test_merchantcore_versions.py::test_the_versions_stamped_on_records_come_from_the_manifest

1. A model-produced record is graded `corroborated` — above a lone unconfirmed guess, below a human `verified`.
2. Every record carries `enrichment prompt + taxonomy + normalizer` as its version, and the prompt resolves to the exact file that produced it ([prompts-as-files.md](prompts-as-files.md)).
3. A key the reply does not carry is absent from the result rather than guessed into existence.
4. A `counterparty_kind` outside `business | instrument | peer` is dropped, so a record carries one of those or no kind at all.

### MER-23 — Enrichment is chunked, and the chunk size is the caller's
**State:** enforced-with-exception
**Code:** merchant/merchantcore/enrich.py:65 (`DEFAULT_CHUNK_SIZE`), :265 (`Enricher.enrich`), product/viva/enrich.py:61 (`read_chunk_size`)
**Test:** merchant/tests/test_merchantcore.py::test_enricher_chunks_a_large_batch_into_several_calls, merchant/tests/test_merchantcore.py::test_a_broken_chunk_does_not_sink_the_others, product/tests/test_merchant_enrich.py::test_how_many_merchants_ride_in_one_call_is_the_callers_to_set, product/tests/test_merchant_enrich.py::test_a_chunk_size_that_is_not_a_count_of_merchants_is_refused

1. One model call carries at most `chunk_size` merchants; a chunk whose reply fails costs one chunk and the rest of the run still lands.
2. The size is set by `--chunk-size N` then `VIVA_CHUNK_SIZE` then the package default.
3. A value that is not a whole number of at least one exits before anything is spent, and is never clamped to a usable one.
4. An empty input returns `{}` without calling the model.

**Exception:** assertion 3 is a property of the CLI entry point, not of the package. product/viva/enrich.py:68 raises `SystemExit`; `Enricher.__init__` clamps — `self._chunk_size = max(1, int(chunk_size))` (merchant/merchantcore/enrich.py:253) — so a caller constructing an `Enricher` directly with `0` gets `1` rather than a refusal.

### MER-24 — "Asked and got nothing" is not "the reply did not parse"
**State:** enforced
**Code:** merchant/merchantcore/enrich.py:117 (`parse_enrichment_chunk` returns `(records, parsed)`), :258 (`Enricher.unparsed`), product/viva/ingest/categorize.py:258
**Test:** product/tests/test_agent_run.py::test_a_chunk_that_did_not_parse_is_asked_again, product/tests/test_agent_run.py::test_a_model_that_looked_and_declined_is_not_asked_again

1. A well-formed reply that omits a merchant is a non-answer and is recorded as one.
2. A truncated or unreadable reply says nothing about any merchant in the chunk; those keys stay pending and are asked again.
3. A caller recording a non-answer cannot record a transport failure that way.

### MER-25 — A non-answer is keyed by the example, not by the merchant
**State:** enforced
**Code:** merchant/merchantcore/catalog.py:122 (`mark_unanswered`), :102 (`pending`), :74 (new evidence retires a mark)
**Test:** product/tests/test_agent_run.py::test_a_merchant_the_model_could_not_name_is_not_asked_about_again, product/tests/test_agent_run.py::test_a_better_example_retires_an_old_non_answer

1. `mark_unanswered` records the example that was asked about, not just the key.
2. A merchant returns to `pending` as soon as its example changes.
3. A key not currently pending is ignored rather than marked.

### MER-26 — `queued` and `pending` answer different questions
**State:** by-review
**Code:** merchant/merchantcore/catalog.py:102 (`pending`), :111 (`queued`)
**Test:** none

1. `queued()` is everything that persists to plain unencrypted JSON — what a privacy audit walks.
2. `pending()` is what a caller about to spend a model call reads.
3. They are deliberately not one function.

### MER-27 — The product imports matched records as events
**State:** enforced
**Code:** product/viva/enrich.py (`sync_installed_merchants`), product/viva/ingest/categorize.py (`sync_merchant_records`), product/viva/ledger/events.py (`merchant_enriched`)
**Test:** product/tests/test_categorize.py::test_upload_applies_a_reviewed_commons_alias_before_defaults, product/tests/test_merchant_enrich.py::test_enrichment_syncs_as_events_and_categorizes_retrospectively, ::test_sync_is_idempotent, ::test_human_override_beats_the_synced_enrichment

1. The product does not read merchantcore at derivation time; it pulls records and appends `MerchantEnriched` events.
2. A replay reproduces the categorization with merchantcore absent — the ledger stays the source of truth (T4).
3. The sync is idempotent: a record is imported only where its facts are stronger or it carries a reviewed alias the ledger does not yet hold. Repeating the same record appends nothing.
4. A lower-grade alias update may extend recognition but cannot replace a human `verified` category or attributes.
5. Balance-statement import performs a zero-model-call sync for merchants in that document before defaults are assigned. It never copies unrelated catalog records into the vault.

### MER-28 — A version-stale record is restaged, and keeps answering meanwhile
**State:** enforced
**Code:** merchant/merchantcore/catalog.py:78 (`restage`), :97 (`restaged`), :146, merchant/merchantcore/enrich.py:195 (`enrichment_is_stale`)
**Test:** merchant/tests/test_merchantcore.py::test_a_version_stale_record_is_restaged_and_asked_about_again, ::test_a_restaged_record_is_asked_about_once_not_every_run, ::test_a_record_with_no_version_is_not_stale, ::test_a_new_taxonomy_does_not_restage_a_record, ::test_restaging_survives_a_reload

1. `restage(predicate)` returns the keys the predicate calls stale; nothing in the catalog infers staleness.
2. `enrichment_is_stale` is a string comparison against the stamped enrichment version; a record carrying no version is not stale.
3. A restaged record stays in place and keeps answering until a new one replaces it.
4. A restaged key leaves the set when any record for it arrives, so a re-ask costs one call and not one per run.
5. `dry_run` returns the same keys, queues nothing and saves nothing.
6. Restaging persists under a `restaged` key; a file written without it loads with nothing marked.

### MER-29 — Where merchant knowledge lives: learned first, shipped second
**State:** enforced
**Code:** merchant/merchantcore/home.py:37 (`learned`), :42 (`shipped`), merchant/merchantcore/catalog.py:48, :197 (`_load_file`), :210 (`load`), merchant/merchantcore/profile.py:407 (`ProfileStore._file`)
**Test:** merchant/tests/test_subcategory_seed.py::test_a_shipped_catalog_is_read_and_marked_as_shipped, ::test_a_learned_catalog_does_not_erase_the_seed, ::test_a_learned_record_wins_over_a_shipped_one_whatever_the_grade, ::test_a_seed_survives_the_first_save_and_stays_distinguishable, product/tests/test_merchant_enrich.py::test_the_catalog_is_shared_across_vaults_not_kept_inside_one

1. Merchant knowledge belongs to merchantcore, not to a vault or to the product; one store is reused across every vault on the machine.
2. Two locations: a shipped seed committed inside the package, and learned data outside any working tree at `~/.merchantcore` (`MERCHANTCORE_HOME`).
3. On lookup the learned record wins outright, per permanent id and whatever grade either carries.
4. A shipped record is marked `source="shipped"` so it stays distinguishable after the first save copies it into the learned file.
5. A shipped file's records only are read; a pending queue and an unanswered set are never read from it.
6. Promotion from learned into shipped is a person's decision; nothing moves automatically.
7. A legacy v1 learned key migrates only through an exact reviewed shipped alias. Its data and grade still win, the old key remains an alias, and equal `canonical_name` values never merge records. Same-layer migration is grade-first, then direct-id-first, and refuses an unresolved equal tie.

### MER-30 — The commons export is linted, and an import is only a prior
**State:** enforced
**Code:** merchant/merchantcore/catalog.py (`export`, `merge`)
**Test:** merchant/tests/test_merchantcore.py::test_catalog_pending_add_and_linted_export, ::test_shipped_catalog_is_a_nonempty_business_only_commons, ::test_a_v1_learned_alias_migrates_onto_the_reviewed_id, ::test_an_import_alias_collision_is_atomic, ::test_catalog_merge_prior_loses_to_local_verified

1. Export and merge use `merchant-catalog-v2`: one permanent id per record, a required self-alias, reviewed exact aliases, and an explicit identity algorithm version.
2. `export` returns a record only when every alias passes `is_shareable` and enrichment typed the counterparty as a business. A peer or financial instrument is refused; no pending, unanswered or restaged queue leaves.
3. Loading refuses empty, unnormalized or conflicting aliases, mismatched ids and unsupported versions. One alias cannot name two records, and a runtime/model record cannot author a fold.
4. `merge` is collision-atomic and applies an imported record only where no local record exists or the import's grade is strictly higher.
5. A local `verified` ruling always beats an import.

### MER-31 — Billing is a fact about the merchant, validated against closed sets
**State:** enforced
**Code:** merchant/merchantcore/enrich.py:57 (`BILLINGS`), :61 (`BILLING_PERIODS`), :165 (`clean_billing`), merchant/merchantcore/prompts/enrich-v6.txt:47 (the `billing` section), :64 (`billing_period`), :69 (the separation from `implies`)
**Test:** merchant/tests/test_merchantcore.py::test_a_billing_model_and_its_period_land_in_the_attributes_bag, ::test_a_billing_model_outside_the_closed_set_is_dropped, ::test_a_period_offered_for_a_per_purchase_merchant_is_dropped, ::test_an_unknown_period_is_dropped_and_the_model_survives, ::test_saying_nothing_about_billing_is_a_normal_answer, ::test_the_billing_question_is_separate_from_what_a_merchant_implies

1. `billing` and `billing_period` say how a merchant charges everybody who deals with them, never what any person arranged with them.
2. A billing model outside the closed set is dropped and takes its period with it.
3. A period outside the closed set, or one offered for `per_purchase`, is dropped on its own and the model survives.
4. Absent is a normal answer wherever the model is unsure.
5. Both live in the existing `attributes` bag: no dataclass change, no new event type, no change to `export` or `merge`.
6. The prompt asks for billing in a section of its own rather than through `implies`, and answering it never adds an entry there.

### MER-32 — The enrichment prompt says a brand string may be truncated
**State:** unmet
**Code:** none found — merchant/merchantcore/prompts/enrich-v6.txt carries no clause about truncation
**Test:** none

1. A brand handed to enrichment may be hard-truncated, because a NACHA Company Name is sixteen fixed-width characters and the bank collapsed the padding.
2. The prompt must say so, or a model reads a clipped name as an odd brand name rather than a cut-off one.

## Why

A merchant — its canonical name, category, website, socials — is impersonal,
reusable knowledge: true for everyone, about the merchant rather than about your
money. So it is not a feature of the product but a package the product consumes.
The dependency runs one way, `vivacore` → `merchantcore` → product, and the
product knows nothing about how enrichment works while merchantcore knows nothing
about amounts, accounts, or which transactions exist. They meet at one narrow,
impersonal interface, and that interface is where T9 is drawn.

The catalog is unencrypted *because* it is impersonal, not as an exception to
T5. The personal application — which of your transactions, for how much — never
leaves the encrypted ledger. The one residual exposure is the *set* of merchants
you frequent, which is why contribution is opt-in and biased toward popular
merchants: share "Amazon", never "Joe's Corner Store, Plano".

Cost is the reason for the whole shape. A vault holds thousands of transactions
but a few hundred distinct merchants, and a merchant is enriched once, ever, so
spend scales with genuinely-new merchants and the commons drives even that toward
zero. Enrichment therefore runs on merchantcore's own schedule and never blocks
ingest.

The product syncing results in as events rather than reading merchantcore live is
what keeps T4 intact. merchantcore is the *source of the knowledge*, not the store
of the answer; the ledger holds the answer, so a replay or a reingest reproduces
every categorization with the package absent.

How the product *applies* this knowledge to its own ledger — the derivation, the
override, canonical-plus-legacy lookup — is [merchant-catalog-and-commons.md](merchant-catalog-and-commons.md).

An enriched attribute is a graded claim, never a fact. The ladder is `verified`
(you confirmed this transaction, or this merchant) > `corroborated` (a model
batch, or a commons prior with enough independent contributors) > `unverified` (a
lone unconfirmed guess) > `Uncategorized`, and the personal override always wins.
The trust envelope rides all the way from a document read to a spending answer.

Two operational rules were forced by real runs. **Chunking is not a tuning knob**:
an oversized batch does not fail loudly, it returns zero records, which reads
exactly like "there was nothing to enrich". And **the pending set is every
uncategorized counterparty, not the expense-shaped ones**: walking only expenses
made employers, transfers, card payments and every inflow structurally invisible
to enrichment — permanently unidentified, never asked about, never settled. It
surfaced because two instruments that should have agreed did not, one reporting
46 unknown merchants where the other reported 428 unenriched movements. The gap
between two counts of one population *was* the bug; two instruments disagreeing is
a finding, not a nuisance.

Where a question is asked decides what a wrong answer costs, which is why billing
gets a section of its own rather than riding on `implies`: a wrong implication
writes a phantom account into a balance sheet, a wrong billing model licenses a
question and nothing else.

Two more rules exist because an empty result has more than one cause. A key-based
non-answer would be permanent; an example-based one expires exactly when the
evidence improves. And conflating a declined answer with an unreadable reply is a
one-way loss: the first means the same example will buy the same silence, the
second means nothing was learned about anybody in the chunk.

Three claims this document used to make were falsified by the first real run
against a vault, and the reasons outlive the corrections. The product submitted
the *raw bank descriptor* rather than a linted example, and the pending queue
persisted those raw lines into plain JSON that is unencrypted by decision and
shared across vaults by decision — which is why the lint is now a property of the
store as well as of the caller. The key was the descriptor, so a chain was one row
per city: two locations of one shop meant two model calls, two commons rows and
two chances to disagree with itself, while this project's own research records
the whole field converging on brand-level identity. And the gate was a ten-item
substring list which refused every English descriptor containing " to " and
admitted a name in any other language — 183 of 365 keys blocked on a real vault.

The catalog's address was load-bearing too. It began inside the vault directory,
which quietly contradicted the reason it exists: a catalog scoped to one vault
makes every rebuild start from zero and pay the model again for knowledge already
bought — the network effect running in reverse. It then sat under the *product's*
home, which said it belonged to the product. A brand's category is nobody's money
and outlives every ledger. Learned data lives outside any working tree so a record
that should not be published cannot be committed by accident rather than merely
should not be.

The slice-and-dice goal is not one richer category but a few orthogonal
dimensions, sourced from three places: merchantcore supplies the impersonal,
shareable axes (primary category, subcategory, MCC, logo, website); the product
supplies what only transaction patterns can give (recurrence and subscriptions);
the person supplies tags, the free many-to-many axis that lets someone slice their
own way. Location and payment channel are per-occurrence facts and belong to the
reader, not to the merchant record, because a merchant has many locations.

## Open

- Web and API enrichers (Yelp, website, socials) filling more of `attributes`.
  Model-world-knowledge fields come from the same batched call; looked-up and
  dynamic fields need a separate enricher layer with a freshness story, opt-in,
  cached in the commons.
- The commons registry: a git repo of `MerchantRecord`s keyed by permanent
  merchant id and explicit identity-algorithm version, corroborated-by-count,
  with reviewed aliases for rebrands.
  `Catalog.export` is its input and `merge` its consumer; the registry itself does
  not exist.
- Merchant as a Party: the canonical merchant is the Party primitive, with
  per-location detail and external-counterparty attribution attaching to the same
  key. Unbuilt.
- Tags and recurrence are the remaining slice dimensions; the finer axes deliver
  "slice and dice" only once all three exist.
- `queued()` versus `pending()` has no test asserting the distinction the code
  states.
