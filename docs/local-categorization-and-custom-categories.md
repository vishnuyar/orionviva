# Local Categorization & Custom Categories (per-transaction, private)

**State:** partial
**Rules:** MON-90, MON-91, MON-92, MON-22, MON-23

**Invariants touched:** T1 · T4 · **T9** · I5 · the moat (a human assignment is `verified` and outranks any model prior).

## Rules

### MON-90 — a peer descriptor is ruled per transaction, never everywhere
**State:** enforced
**Code:** product/viva/listen.py:566 (`generalizes = merchant and is_shareable(descriptor) and not instrument`); product/viva/engine.py (`_write_answer`)
**Test:** product/tests/test_questions.py::test_a_peer_payment_is_scoped_to_itself_not_a_rule

1. A commercial merchant's ruling is scoped to the merchant and settles every payment to it.
2. A peer or instrument descriptor is scoped to the single movement.
3. A movement-scoped answer covering more than one movement with no key is refused rather than quietly applied to the whole conduit bucket.
4. Answering a one-scoped merchant question assigns the category only to the movement keys the question carried; it creates no merchant-wide prior.

### MON-91 — a custom category is personal, and what crosses to a model is the shareable part of the vocabulary
**State:** enforced
**Code:** product/viva/listen.py:110 (`category_vocabulary`), :131 (`shareable_categories`), :161 (`ruling_slots`)
**Test:** product/tests/test_category_identity.py::test_the_known_vocabulary_is_what_every_minting_path_is_offered

1. A category is the person's own words and stays in the encrypted vault.
2. What a model is told is the slot's `offered` list, which `ruling_slots` narrows to `shareable_categories` — the vocabulary filtered through `is_shareable`, the same gate the merchant path uses (product/viva/listen.py:131, :161; product/viva/reply.py:138, :323).
3. The whole vocabulary survives only as `choices`: what a reply is validated against, and what `settled_category` matches on. It is never sent.

### MON-92 — a per-transaction assignment can say what a movement *is*
**State:** enforced
**Code:** product/viva/ingest/categorize.py:96 (`assign_category(..., nature=)`); product/viva/ledger/projection/movements.py:270 (the overlay's `nature` read at the ruling rung)
**Test:** product/tests/test_nature.py::test_a_human_ruling_beats_the_implication

1. A category assignment may carry a nature — `spending`, `transfer` or `settlement`.
2. The projection honours it above any category hint when it derives nature, so a lone peer payment ruled "loan repaid" leaves spending.

### MON-22 — a personal category never reaches a shared surface
**State:** enforced
**Code:** product/viva/ingest/categorize.py:298 (`export_catalog`)
**Test:** product/tests/test_merchants.py::test_export_catalog_is_linted_and_carries_no_amounts

1. Nothing personal — a custom label, an amount, a raw descriptor — enters the exported catalog, `merchantcore`, or the commons (T9).
2. Only the shareable taxonomy crosses that boundary.

### MON-23 — a category exists by being used
**State:** enforced
**Code:** product/viva/listen.py:110 (`category_vocabulary`), product/viva/engine.py:606 (`assign_category_to`)
**Test:** product/tests/test_category_identity.py::test_a_vault_with_no_seed_is_shown_exactly_what_it_uses, product/tests/test_reply.py::test_a_category_the_vault_does_not_know_is_refused_rather_than_minted

1. The vocabulary is the seed labels plus every label already in the vault, with no two spellings of one name.
2. Minting a category needs no event and no migration; assigning it is what creates it.
3. There is no `CategoryDefined` event: a category exists by being used, consistent with abstracting the write side late.
4. A category the vault does not know is refused rather than minted by a model.

## Why

Merchant-level categorization is right when the merchant *is* the category: a warehouse club is always groceries, a streaming service always entertainment. It is wrong when the "merchant" is a person. A peer-transfer descriptor normalizes to a peer, and peers have no stable category — the same counterpart is a gift one month, a loan repayment the next, a split dinner the third. `is_shareable` already keeps these out of enrichment for privacy (T9), which is exactly why they sit uncategorized after a run: they cannot be solved by the shareable, commons path *by construction*. They need a local, per-transaction path that never leaves the vault.

Two of those transaction types are not even spending. A loan repaid, or money a friend paid back, is a transfer or a settlement, so the local path must be able to say *what a movement is*, not only which spending bucket it falls in — otherwise the honesty guarantee (spending excludes non-spending) breaks the moment a person categorizes their first peer payment. Letting the assignment carry a nature keeps the person's action one gesture; routing it to a one-sided transfer mechanism is reserved for when a real counterpart appears and can corroborate.

Almost none of this needed new mechanism. The category overlay already derives as *per-movement override, else merchant prior, else Uncategorized*; the assignment is already keyed to the individual movement, graded `verified`, and already beats the merchant-level default. Two peer payments already carry different categories through two events on different movement keys. Categories are already open strings. What was left was exposure, plus the two genuine modeling decisions above.

The scale is what made the boundary concrete: a real enrichment run left a large share of the vault sitting as peer and settlement money the commons path cannot and should not touch.

## Open

- `product/viva/listen.py:168` cites this document's rule by its former id, `D2`. The rule is now MON-91; the comment is stale until someone with the code lane fixes it.

- A first-class `CategoryDefined` event (name, colour, icon) is unbuilt, so there is nothing a picker can enumerate, rename, or style. The implicit half — a label exists by being used — is what is built.
- A Review answer can assign a category the vault already knows to one peer movement. No surface can mint, enumerate, rename or style a custom category; that needs the first-class category work above.
- Near-duplicate labels a fold cannot close: `Groceries` lands on `groceries`, and `Grocery` still mints a second category beside it ([issue #7](https://github.com/vishnuyar/orionviva/issues/7)). Closing it needs either a fence, which contradicts MON-91, or a stemming rule, which is the keyword-table class of workaround this project has deleted twice. The ruling is Vishnu's.
- Learned auto-apply for peer descriptors — "this counterpart is usually rent" — is a later projection over the recorded assignments, exactly as merchant learning was; nothing here forecloses it and nothing needs re-ingesting.
- Merchant-as-Party and counterpart identity resolution are deferred.
