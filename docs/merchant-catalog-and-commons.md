# Merchant Catalog & the Categorization Commons — categorize the merchant, once, for everyone

**Status:** Design (Slice 5.5) · **Last updated:** 2026-07-24 · **Origin:** Slice 5 ships per-transaction categorization, and real use immediately showed the flaw: you categorize one Amazon charge and the next Amazon charge (a different transaction) asks again — twenty Amazon purchases, twenty asks. The fix is to categorize the **merchant**, not the transaction. A vault has thousands of transactions but ~hundreds of distinct merchants; a merchant→category mapping is the small, *impersonal* unit — so batching turns categorization from an O(transactions) model cost into an O(new-merchants) one, and the mapping is exactly the artifact a **commons** can share. This is Vishnu's batched-catalog idea, refined.

**Invariants touched:** T1 (a derived category carries a grade + points to the merchant rule behind it), T4 (merchant rulings are append-only events; the catalog is a *projection* over them, the source of truth stays the encrypted log), **T5 (personal data never leaves the encrypted layer — the raw descriptor, with its order-ids and peer names, stays encrypted; only an impersonal, privacy-linted merchant→category catalog is ever unencrypted or shared)**, T6 (contributing to the commons is an opt-in *decision*, never silent), T8 (the batched categorizer is a pinned, injected model edge), I3/I5/I6 (merchants are locale-sharded, categories are open data, the commons is pack-extensible). Principle 2 (a merchant category is a *graded prior*, always overridable), principle 7 (known merchants auto-fill safely and reversibly; unknown ones wait and are shown as unknown).

## The architecture (decisions locked with Vishnu, 2026-07-24)

**1. Categorize the merchant, not the transaction.** The unit of categorization becomes the normalized merchant. A transaction's category is *derived*: a per-transaction override if you set one, else the merchant catalog's category, else `Uncategorized`. So one ruling on "Amazon" categorizes every Amazon transaction, past and future.

**2. The catalog is a *prior*; your per-transaction ruling still wins.** The Slice-5 per-transaction overlay is not wasted — it becomes the **override** layer ("this particular Amazon charge was groceries, not shopping"). The grade ladder for a transaction's category: `verified` (you confirmed this exact transaction) → `corroborated` (a merchant rule filled it — your confirmed merchant, the commons, or a model batch) → `unverified` (a lone unconfirmed model guess) → `Uncategorized` (unknown merchant). A prior can be wrong; the override is how you say so.

**3. Split what is unencrypted — the load-bearing privacy decision.** Raw descriptors carry PII ("VENMO TO JOHN SMITH", "AMZN … order 111-897345"), so **the raw descriptor stays in the encrypted ledger** (T5). The only thing ever written unencrypted or shared is a **privacy-linted merchant→category catalog** — canonical *commercial* merchants and their categories, with no amounts, dates, or transaction links. This keeps the personal/format-knowledge split (Slice 2, decision 5) exact and is the only version safe to put in a public repo.

**4. Deterministic normalization + model grouping — never fuzzy string-matching.** Fuzzy matching merges the wrong things ("Costco" vs "Costa Coffee", "Chase" vs "Chevron"). Instead a **deterministic, versioned** normalizer strips the noisy tail (store numbers `#0664`, order ids `US*RA30Z3BP0`, phone numbers, POS/TST*/SQ* prefixes) to a canonical key, shrinking the list; then the **model** categorizes the deduped list and reliably maps "COSTCO WHSE #0664" and "COSTCO PLANO" to Costco → shopping. Location does *not* fragment the category (both are shopping); it rides along as an attribute for later per-location analytics. The normalizer is versioned like `RULES_VERSION`, so catalog keys are portable across users (a precondition for the commons).

**5. Batched, threshold-triggered, retrospective — the cost win.** On ingest, descriptors normalize; a **known** merchant auto-categorizes instantly and for free (a catalog lookup, no model call); an **unknown** merchant goes "plain vanilla" (`Uncategorized`) and joins a pending set. When the pending set crosses a threshold (or on demand), **one** batched model call categorizes them all, they enter the catalog, and every past *and* future transaction from them is filled in retrospectively. New merchants are honestly shown as unknown until the next pass (X2).

**6. The commons falls out of the catalog.** Because the catalog is already the impersonal, shareable unit, contributing it is a content-addressed export (Vishnu's hash idea): the linted commercial subset → a hashed file → an opt-in PR to a merchant registry. Import merges others' entries as `corroborated` priors. Confidence is **corroborated-by-count** (independent contributors agreeing). Your local override always beats an imported prior. This is the first concrete network effect: your Amazon ruling means the next user never categorizes Amazon.

## The mechanism, concretely

- **Events (encrypted, the source of truth + the moat):** `MerchantCategorized(normalized_merchant, category, grade, by)` — a model batch writes these `unverified`/`corroborated`; a human "categorize this merchant everywhere" writes `verified`. The Slice-5 `CategoryAssigned(movement_key, …)` stays as the per-transaction override.
- **The catalog (a projection):** `{normalized_merchant → {category, grade, source, locale}}`, built by replaying `MerchantCategorized` + human merchant confirmations, then merging imported commons priors (lowest precedence). Regenerated from events — no model call is ever repeated.
- **Derivation:** `category(transaction) = override(movement_key) ?? catalog[normalize(descriptor)] ?? "Uncategorized"`. `spending_by_category` consults this. Retrospective by construction (a projection).
- **The batched categorizer:** an injected model edge (like the reader) — `categorize_merchants(list) -> {merchant: category}` — offline-testable, pinned model, run on the pending set at a threshold.
- **The unencrypted export:** a linted snapshot of the catalog for the commons; contribution opt-in (T6), popular-biased, PII-filtered.

## The privacy line (get this right)

The raw descriptor never leaves the encrypted ledger. The unencrypted catalog holds only `merchant → category` for **commercial** merchants — no amounts, no dates, no per-transaction linkage. Even so, the *set* of merchants you frequent is mildly identifying, so: local-unencrypted is fine (on your device), but **contribution is opt-in and biased to popular merchants** — share "Amazon", never "Joe's Corner Store, Plano" which could fingerprint you. Same privacy-lint discipline as format profiles; a peer-payment or person-name descriptor is filtered out entirely.

## Notes for future slices (read these when you build them)

- **The full commons registry (later):** a git repo of `merchant → category` keyed by normalizer version and locale, corroborated-by-count, self-healing as merchants rebrand. Same lifecycle as [format-commons](format-commons.md); this catalog is its seed.
- **Merchant as a Party (later):** the canonical merchant is a **Party**; per-location detail (Costco Plano vs Frisco) and merchant-level analytics attach here, and external counterparty attribution (a payment to a person vs a business) reuses the same normalization.
- **Amount-splits + tags (deferred from Slice 5):** compose over the derived category unchanged.

---

## Slice 5.5 — Merchant catalog & the categorization commons

**Block(s) seeded:** the **merchant catalog** (a normalized merchant → category projection, the categorization prior) + the **deterministic merchant normalizer** (versioned, portable) + the **batched merchant-categorization edge** + the **unencrypted, content-addressed commons export**. Reuses correction-as-event, grade + provenance, the entity-resolution instinct, and the Slice-5 overlay (now the override layer) — genuinely new is the normalizer, the merchant-level event + catalog projection, the batch edge, and the linted export.

**Open state:** categorization is per-transaction, so the same merchant is asked repeatedly and every categorization costs attention (and, at scale, a model call per line). *Proof (red test):* categorizing one Amazon transaction leaves every other Amazon transaction uncategorized.

**Implementation:**
- A deterministic, versioned normalizer (raw descriptor → canonical merchant), PII/peer-payment filtered.
- `MerchantCategorized` event + a catalog projection; `category(transaction) = override ?? catalog ?? Uncategorized`; `spending_by_category` derives through it (retrospective).
- A batched, injected `categorize_merchants` model edge run on the pending (unknown-merchant) set at a threshold; known merchants auto-fill free; unknown ones are shown as unknown with a caveat.
- A "categorize this merchant everywhere" confirmation (`verified` merchant rule) alongside the per-transaction override.
- An unencrypted, linted, content-addressed catalog **export** for the commons; opt-in contribution; import merges as `corroborated` priors.

**Final state:** you categorize a merchant once and every transaction from it — past and future — is filled in; new merchants wait for a cheap batched pass and are honestly shown as unknown meanwhile; model spend scales with *new merchants*, not transactions; and your rulings become a shareable merchant→category commons that spares the next person the same work.

**Done criteria / tests:** categorizing "Amazon" fills every Amazon transaction (retrospective) at `corroborated`, while a per-transaction override stays `verified` and wins; the normalizer maps known variants ("COSTCO #0664", "COSTCO PLANO") to one merchant deterministically and is versioned; an unknown merchant is `Uncategorized` with a visible "not yet known" state until a batched pass categorizes it; the batched edge is one call over the deduped pending set (injected/offline-testable); the exported catalog contains **no** amounts/dates/transaction links and **no** PII-filtered (peer-payment) merchants; importing a commons entry applies it as a `corroborated` prior that a local override beats; Slice-5 spending stays correct through the derivation.

**Why now + future use:** it's what makes categorization usable on a real vault (the thing that just bit) and it's the first real **network effect** — the merchant→category commons — realized cleanly out of the personal/format-knowledge split and the descriptors Slice 5 already captured, with model cost amortized toward the near-zero-cost local endgame. It seeds the Party (merchant) primitive and the commons registry, and every later categorization-adjacent feature composes over the derived category.
