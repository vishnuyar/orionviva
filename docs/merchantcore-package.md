# merchantcore — the merchant enrichment package

**Status:** Implemented · **Superseded-in-part 2026-07-28** (see the note at the end) · **Last updated:** 2026-08-14 (amendments through 2026-08-13 live in the as-built section) · **Origin:** the merchant catalog built merchant categorization *inside the product*. But a merchant — its canonical name, category, website, socials, reviews — is **impersonal, reusable knowledge** (true for everyone, about the merchant not your money), and it wants to grow into a multi-attribute entity and a shared commons. So it becomes its own package, a peer to `vivacore`, that the product *consumes*: `vivacore` is the trust/verification core, `merchantcore` is the merchant knowledge base. This doc is the deep design — the package boundary, how it makes its own model calls, and how the product gets the data back.

**Invariants touched:** **T5 drawn at a package boundary** (only *impersonal* data crosses product → merchantcore: a normalized merchant key and a privacy-linted example — never amounts, dates, accounts, or peer/PII descriptors), T4 (the product's ledger stays the source of truth: merchantcore is a knowledge *cache/service*, and the product imports its results as events, so a replay is self-contained), T6 (contributing to the commons is an opt-in decision), T8 (merchantcore makes provider-agnostic, pinned model calls through `vivacore.models`), I3/I5/I6 (merchants are locale-sharded, categories/attributes are open data, the commons is pack-extensible). Principle 2 (an enriched attribute is a *graded* claim; the personal override always wins).

## The shape: a knowledge service, not a data store

```
   vivacore  (verify · models · claims — the trust core)
      ▲
      │ depends on
   merchantcore  (normalize · enrich · catalog · commons — merchant knowledge)
      ▲
      │ consumes (impersonal boundary)
   viva / product  (encrypted ledger — applies merchant knowledge to YOUR money)
```

Clean, one-directional dependency DAG. The product knows nothing about how enrichment works; merchantcore knows nothing about amounts, accounts, or which transactions exist. They meet at one narrow, impersonal interface.

## What lives where

**merchantcore (impersonal, reusable, unencrypted-safe):**
- `normalize(descriptor) -> key` + `NORMALIZER_VERSION` + `is_shareable(descriptor)` — moved out of the product (deterministic, versioned, portable keys; the privacy lint).
- `MerchantRecord` — the merchant **entity**: `{key, canonical_name, category, attributes{}, grade, source, version}`. Category is attribute #1; `attributes` is an open bag for `website`, `description`, socials, reviews — added later as fields, never a restructure.
- `Enricher` — the batched model-call engine + its **versioned enrichment prompt**. Given a model spec and a set of merchants, it returns records. Self-contained: it builds the prompt, calls `vivacore.models`, parses, and grades.
- `Catalog` — the merchant knowledge base: an unencrypted local store (`{key -> MerchantRecord}`) plus a **pending queue** (submitted, not-yet-enriched merchants), plus commons `import`/`export` (content-addressed, linted).
- (Later) web/API enrichers (Yelp, website, socials) that fill more of `attributes`.

**product (personal, encrypted):**
- The `MerchantEnriched` event (generalized from `MerchantCategorized`) — the product's *applied* record of a merchant ruling in its ledger, so categories replay without merchantcore present.
- The projection's derivation (`override ?? merchant catalog ?? Uncategorized`) — now populated by syncing merchantcore records into events.
- The per-transaction override, the surface, the spending projection — unchanged.

## The three flows (the deep part)

### 1. Product → merchantcore: submit unknown merchants (the impersonal boundary)

The product's projection already knows its unknown merchants (`uncategorized_merchants()` → `{key: {count, example, shareable}}`). It sends **only the shareable ones**, and **only impersonal fields**:

```
merchantcore.submit([MerchantHint(key="amzn mktp us", example="AMZN MKTP US")])
```

`MerchantHint` carries the normalized key and a *linted example* (the example gives the model more signal than the stripped key; `is_shareable` guarantees no peer-payment/PII). **No amount, date, account, count, or transaction reference ever crosses.** This is T5 enforced at the API surface — merchantcore literally cannot learn anything about your money, only that "a merchant named roughly this exists." merchantcore drops hints it already has in its catalog, so submit is idempotent and cheap.

### 2. merchantcore, on its own: enrich via batched model calls

merchantcore owns the model call end-to-end. `Enricher.run(model_spec, batch_size)`:
1. Pulls a batch of pending (unenriched) merchants from the queue.
2. Builds the **versioned enrichment prompt** — "for each merchant, return `{canonical_name, category (one of the seed set), description, website?}`" — from the linted examples.
3. Calls the model through a `vivacore.models` adapter (provider-agnostic, pinned, cost-tracked — the same socket the reader uses).
4. Parses each result into a `MerchantRecord`, graded `corroborated` (a model batch is stronger than a lone guess, weaker than a human `verified`), tagged with the enrichment-prompt + normalizer version.
5. Writes records to the catalog and clears them from the queue.

It is **batched and decoupled**: enrichment runs on merchantcore's schedule (a threshold of pending merchants, a periodic pass, or an explicit call), never blocking the product's ingest. The catalog persists across runs, so a merchant is enriched **once**, ever — the O(new-merchants) cost. Cost scales with genuinely-new merchants, and the commons drives even that toward zero.

### 3. merchantcore → product: the product syncs the results in

The product does not read merchantcore live at derivation time (that would break T4's self-contained ledger). Instead it **pulls and imports** — an idempotent sync, in the spirit of `heal`/`sweep`:

```
for record in merchantcore.catalog.records():
    if record.key not in already_imported:
        ledger.append(merchant_enriched(record))   # a MerchantEnriched event
```

The projection's derivation then categorizes every past and future transaction from that merchant retrospectively. Because the enrichment is now an **event in the product's own ledger**, a replay (or a reingest) reproduces the categorization with merchantcore absent — the ledger stays the source of truth (T4); merchantcore is the *source of the knowledge*, not the store of the answer. The sync runs on startup and after an enrichment pass, like the other heals.

### And the loop closes: contribution

When you *confirm* a merchant's category (`verified` — you overruled or ratified the enrichment), that ruling is the moat. Opt-in (T6), the product hands it back to merchantcore as a stronger signal, and merchantcore's linted, content-addressed `export` is what a commons PR is built from — so your Amazon ruling raises the corroborated-by-count prior that spares the next person the model call entirely.

## The privacy boundary, stated once

Everything that crosses product → merchantcore is impersonal: a normalized merchant key and a linted example. Everything merchantcore holds — the catalog, the commons — is merchant knowledge with **no amounts, dates, accounts, transaction links, or peer/PII merchants**. The catalog is unencrypted *because* it is impersonal; the personal application (which of your transactions, for how much) never leaves the encrypted product ledger. The one residual exposure — the *set* of merchants you frequent — is why contribution is opt-in and biased to popular merchants (share "Amazon", never "Joe's Corner Store, Plano").

## Graded knowledge

A transaction's category grade is the max of the rulings that reach it: `verified` (you confirmed this exact transaction, or this merchant) > `corroborated` (a model batch, or a commons prior with enough independent contributors) > `unverified` (a lone unconfirmed guess) > `Uncategorized`. The trust envelope rides all the way from a document read to a spending answer — a merchant category never enters the trusted layer as fact; it enters as a graded prior you can always overrule.

## The restructuring (bounded)

- **New package `merchantcore/`** (its own `pyproject`, depends on `vivacore`): `normalize`, `MerchantRecord`, `Enricher` (+ the enrichment prompt), `Catalog` (+ commons import/export). The normalizer + `is_shareable` + `export_catalog` move here from the product.
- **Product, lightly rewired:** `ledger/merchants.py` and `ingest/merchants.py` become re-exports from `merchantcore`; the projection imports `merchantcore.normalize`; `MerchantCategorized` generalizes to `MerchantEnriched` (carrying a record); `categorize_merchants_batch` calls `merchantcore.Enricher` (still injectable for offline tests); a `sync_merchants` step imports catalog records as events. The ledger, ingest pipeline, and other slices are untouched.
- Dependency DAG stays clean and one-directional; the product gains a `merchantcore` dependency alongside `vivacore`.

## Implementation status (as built, 2026-07-24)

- ✅ **The package exists** (`merchant/`, `pyproject` name `merchantcore`, depends on `vivacore`): `normalize` (moved out of the product), `MerchantRecord` (multi-attribute — `attributes` bag), `Enricher` (+ the versioned enrichment prompt, `enrich-v2` — the id the package shipped at; `enrich-v1` never existed, see [prompts-as-files.md](prompts-as-files.md)) via `vivacore.models`, `Catalog` (records + pending queue + JSON persistence + linted `export` + `merge`). Product `ledger/merchants.py` + `ingest/merchants.py` are now re-exports.
- ✅ **The impersonal boundary** (T9): `enrich_merchants` submits only `(normalized key, linted example)`; a test asserts no amount, account number, or date reaches the model prompt, and a peer-payment merchant is filtered out entirely.
- ✅ **Own model calls**: `Enricher.enrich` is a batched, injected call per chunk of `chunk_size` merchants (40 by default) → graded (`corroborated`) records carrying the taxonomy + prompt + normalizer version. `model_extractor(spec)` is the live text-only edge. **Amended 2026-08-13:** the chunk size is an argument the caller sets, reachable from the product's enrichment entry point as `--chunk-size N` or `VIVA_CHUNK_SIZE` — the failure message for a truncated reply advises a smaller chunk, and until now there was no way to set one without editing source. The vocabulary a chunk is shown grows across a run by whatever the previous chunk minted.
- ✅ **Two-level taxonomy + richer attributes (enrich-v2, cat-v2).** Informed by an industry scan (Plaid's Personal Finance Categories are 16 primary + 104 detailed; Ntropy adds MCC, recurrence, custom categories — see below): the record now carries a **primary category** from **16 controlled buckets** (`merchantcore.taxonomy.PRIMARY_CATEGORIES`, the single source of truth the product's category picker also uses), a **model-provided `subcategory`** (open value, lightly normalized — "warehouse club", "streaming" — the commons converges on it), and `attributes` for **logo_url, mcc, website, description**. The product syncs `subcategory` into the `MerchantEnriched` event and exposes `projection.spending_by_subcategory` — the finer slice-and-dice axis. **Amended 2026-08-13 (cat-v3):** the subcategory is no longer invented from nothing. A vocabulary of 156 labels ships as `data/cat-v3.json`, pinned in `versions.json` under a new `taxonomy` family, and `TAXONOMY_VERSION` is read from the manifest. It is a prior and not a fence — a model is shown the list, mints only where nothing fits, and the run reports how many labels it minted; a person's own label is never displaced. See [merchant-catalog-and-commons.md](merchant-catalog-and-commons.md) for the measured result and its limits.
- ✅ **How a merchant bills (enrich-v6, 2026-08-12).** The record's `attributes`
  bag gains **`billing`** (`standing` · `per_purchase` · `either`) and
  **`billing_period`** (`monthly` · `annual` · `either`, present only where a
  billing model admits one) — how a merchant charges everybody who deals with
  them, not what any person arranged with them, so it passes the same T9 test
  `category` passes. Both are validated in code against closed sets and dropped
  with a log line when the reply speaks outside them; absent is the expected
  answer wherever the model is unsure, and a period offered without a model goes
  with it. The prompt asks for it in a section of its own rather than through
  `implies`: a wrong implication writes a phantom account into a balance sheet,
  a wrong billing model licenses a question and nothing else. No dataclass
  change, no new event type, no change to `export` or `merge`.
- ✅ **`Catalog.restage(predicate, dry_run=…)`.** Nothing compared a record's
  version to the one in force, so a released prompt reached only merchants with
  no record at all. `restage` returns version-stale records to the pending queue
  (`enrichment_is_stale` is a string comparison against the stamped enrichment
  version; a record carrying no version is not stale), the record keeps
  answering until a new one replaces it, and a restaged key leaves the set when
  any record for it arrives — so a re-ask costs one call, not one per run. The
  dry run measures the spend before anybody authorizes it. Persisted under a
  `restaged` key in the catalog JSON; a file written without it loads with
  nothing marked.
- ✅ **Sync-as-events** (T4): the product imports catalog records as `MerchantEnriched` events; categorization is retrospective (a merchant ruling fills every transaction), idempotent, and survives a **replay with merchantcore absent** — tested.
- ✅ **Runnable on a real vault**: `python -m viva.enrich` gathers unknowns, enriches in one call, persists the catalog beside the vault (plain JSON, impersonal), and syncs. `MerchantEnriched` and `MerchantCategorized` share the catalog projection with grade precedence; a human `verified` override still wins.

Install note: the product now depends on `merchantcore`, so `pip install -e ./merchant` alongside `./core` and `./product`. Deferred: web/API enrichers, the git commons registry, merchant-as-Party. Tests: `merchant/tests/test_merchantcore.py` (6) + `product/tests/test_merchant_enrich.py` (4); full suite 244 green.

## Slice-and-dice: the dimensions, and where each comes from

The goal of enrichment is to let a person slice their finances any way. That is not one richer category — it's a few **orthogonal dimensions**, sourced from three places (an industry scan — Plaid, Ntropy — confirmed this shape):

- **merchantcore (impersonal, shareable):** primary **category** (16) + **subcategory** (model value) + **MCC** + **logo** + website. Done (enrich-v2).
- **the product, from transaction patterns:** **recurrence / subscriptions** — recurring inflow/outflow *streams* grouped by merchant + amount + cadence (Plaid/Ntropy both do this; matured at 3+ occurrences). This is **Slice 8 (Obligations)** and a first-class slice axis ("my subscriptions", "recurring vs discretionary").
- **the product, from the user:** **tags** — the free, many-to-many personal axis ("reimbursable", "vacation-2024", "business"). Deferred in the category overlay; the axis that lets someone slice *their own way* (Ntropy's "custom categories"). A strong pull-forward candidate.
- **per-transaction (from the statement read):** **location** (city/store) and **payment_channel** (in-store vs online) — these are transaction attributes (a merchant has many locations), so they belong to the reader/extraction, not the merchant record.

## Two operational rules, and what forced them

**Enrichment is chunked, and the chunk size is not a tuning knob.** An oversized batch does not fail loudly — it returns zero records, which reads exactly like "there was nothing to enrich". Chunking bounds the reply so that a parse failure costs one chunk and the rest of the run still lands.

**The pending set is every uncategorized counterparty, not the expense-shaped ones.** Walking only expenses made employers, transfers, card payments and every inflow structurally invisible to enrichment — permanently unidentified, never asked about, never settled. It surfaced when two instruments that should have agreed did not: one reported 46 unknown merchants while the other reported 428 unenriched movements. The gap between two counts of the same population *was* the bug. Two instruments disagreeing is a finding, not a nuisance.

## Notes for future slices

- **Multi-attribute enrichment:** the `attributes` bag grows — model-world-knowledge fields (canonical name, description, website, mcc, logo) come from the same batched call; **looked-up / dynamic** fields (live Yelp reviews, current socials) are a separate enricher layer with a freshness story, opt-in, cached in the commons.
- **Tags + recurrence** are the remaining slice dimensions (above); subcategory + these three are what deliver "slice and dice".
- **The commons registry:** a git repo of `MerchantRecord`s keyed by normalizer version + locale, corroborated-by-count, self-healing when merchants rebrand. `Catalog.export` is its input; `import` merges as priors.
- **Merchant as a Party:** the canonical merchant is the Party primitive; per-location detail and external-counterparty attribution attach to the same key.

---

## Extract merchantcore + the live enrichment engine

**Block(s) seeded:** the `merchantcore` package (normalize · MerchantRecord · Enricher · Catalog · commons), the impersonal product↔package boundary, and the sync-as-events import. Reuses `vivacore.models` (the model socket), the grade + provenance spine, and the merchant catalog's events/projection (generalized).

**Open state:** merchant knowledge lives inside the product, is category-only, and the enrichment model call is an unwired stub. *Proof:* there is no package boundary, no `MerchantRecord`, and `categorize_fn` is injected with no real prompt.

**Implementation:** create `merchantcore` (peer package, depends on vivacore); move the normalizer + lint + export there; add `MerchantRecord` (multi-attribute), the `Enricher` (batched, versioned enrichment prompt via `vivacore.models`), and the `Catalog` (unencrypted store + pending queue + content-addressed commons export/import); rewire the product to submit impersonal hints, run enrichment (injectable), and sync results as `MerchantEnriched` events; generalize `MerchantCategorized` → `MerchantEnriched`.

**Final state:** merchant knowledge is a reusable package the product consumes over a strictly-impersonal boundary; merchantcore enriches merchants on its own via batched model calls and holds a persistent, shareable catalog; the product pulls results in as events and categorizes retrospectively, with the ledger still self-contained; the enrichment is multi-attribute-ready and commons-ready.

**Done criteria / tests:** the product→merchantcore boundary accepts only key + linted example (a test asserts no amount/date/account can cross, and a peer-payment hint is rejected); `Enricher.run` makes one batched, injected model call and produces graded `MerchantRecord`s; the product syncs records to `MerchantEnriched` events and categorizes retrospectively (survives replay with merchantcore absent); `Catalog.export` contains only linted merchant records (no financial data); a human `verified` override still wins; the full suite stays green through the extraction.

**Why now + future use:** it makes the merchant knowledge base a first-class, reusable, shareable asset — the home for the enrichment prompt, multi-attribute records, web enrichers, and the commons registry — cleanly separated from the personal ledger by the impersonal boundary. It is the second shared crown-jewel package (after vivacore), and the concrete substrate for the network effect the format-commons chapter promised.


---

## What 2026-07-28 changed

Three claims in this document are no longer accurate, and the reasons are worth
more than the corrections.

**"The product submits a normalized key and a linted example."** It submitted
`m.description` — the raw bank descriptor, verbatim — and the pending queue
persisted those raw lines into plain JSON that is unencrypted by decision and
shared across vaults by decision. Repair-list C2. Fixed twice over: the example
is linted at the call site, and the store lints again on submit, so the
invariant is a property of the store rather than of whoever writes the next
caller.

**The key was the descriptor, so a chain was one row per city.** Two locations of
one shop were two keys, two model calls, two commons rows and two chances to
disagree with itself — while this project's own research chapter records the
whole field converging on brand-level identity. Enrichment now keys on the
`{brand}` slot an induced grammar produces, and the context that travels is only
what every occurrence agreed on: a shop seen in one city keeps its city, a chain
seen in five has none.

**The gate was `is_shareable`.** A ten-item substring list, which refused every
English descriptor containing " to " and admitted a name in any other language —
on the author's real vault, 183 of 365 keys blocked. A stream is now withheld
because a grammar *slot* said a person is in it. The list survives only where no
grammar exists, as the conservative answer to "we cannot tell". See
[the-conduit-and-the-counterparty.md](the-conduit-and-the-counterparty.md).

**And the catalog moved.** It sat under the product's home directory, which
quietly said it belonged to the product. A brand's category is nobody's money
and outlives every ledger: it is merchantcore's. Two locations now — a shipped
seed committed inside the package, and learned data at `~/.merchantcore`
(`MERCHANTCORE_HOME`), deliberately outside any working tree so a record that
should not be published cannot be committed by accident. Learned wins on lookup;
promotion into the shipped seed is a person's decision.

## Two rules about not paying twice for the same silence

Both live in the code and in neither doc, and both exist because an empty result
has more than one cause.

**The unanswered set is keyed by the example, not by the merchant key.** A
merchant that was sent to a model and came back unnamed should not be paid for
again on the same evidence, so `mark_unanswered` records the *example that was
asked about*. When the example changes — a better linted string arriving with a
new occurrence — the non-answer retires by itself and the merchant returns to
`pending`. `submit` does the same on the way in. A key-based non-answer would be
permanent; an example-based one expires exactly when the evidence improves.

Relatedly, `queued()` and `pending()` are two readers of the same store for a
stated reason. `queued()` is everything that persists to plain unencrypted JSON,
so it is what a privacy audit walks. `pending()` is what a caller about to spend
a model call reads. They answer different questions and are deliberately not one
function.

**"Asked and got nothing" is not "the reply did not parse."** Both produce an
empty `records`, and conflating them is a one-way loss: a truncated or unreadable
reply says nothing about any merchant in the chunk and should be retried, while a
well-formed reply that omits a merchant means the same example will buy the same
silence. `parse_enrichment_chunk` returns `(records, parsed)` and
`Enricher.unparsed` collects the second case, so a caller recording a non-answer
cannot record a transport failure that way.
