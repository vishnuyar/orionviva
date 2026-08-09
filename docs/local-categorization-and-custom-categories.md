# Local Categorization & Custom Categories (per-transaction, private)

**Status:** Design note — captured 2026-07-24, unbuilt. It was anchored to "the presentation layer", a milestone that has since passed twice (Slice 6.7, then the surface cards) without it; there is still no `CategoryDefined` event and no custom-category surface. Re-anchor it to a named slice before scheduling · **Origin:** the first real enrichment run (235 merchants) left 116 merchants / 163 transactions / ~$65k Uncategorized, all of them *non-shareable* peer descriptors. Vishnu's observation: one Zelle transaction is a rent payment, another a gift, another a loan repayment — a single merchant-level category is structurally wrong for these.

**Invariants touched:** T1 (provenance rides every assignment) · T4 (a categorization is an append-only event, never an edit) · **T9 (the personal/impersonal boundary — a user's custom category is personal and must NEVER cross into the merchantcore catalog or the commons export)** · I5 (jurisdiction-neutral: custom categories are the user's own words, no locale assumptions) · the moat (a human assignment is `verified` and outranks any model prior).

---

## The problem, precisely

Merchant-level categorization is right when the merchant *is* the category: Costco is always groceries, Netflix always entertainment. It is wrong when the "merchant" is a person. A Zelle/Venmo descriptor normalizes to a peer, and peers have no stable category — the same counterpart is a gift one month, a loan repayment the next, a split dinner the third. `is_shareable` already keeps these out of enrichment (privacy, T9), which is why they sit Uncategorized after a run. They cannot be solved by the shareable, commons path *by construction*. They need a **local, per-transaction** path that never leaves the vault.

Two of these transaction types are not even spending: a loan you repaid, or money a friend paid back, is a transfer/settlement, not an expense. So the local path must be able to say *what a movement is*, not only *which spending bucket it falls in*.

## What the substrate already supports (no new mechanism needed)

The category overlay's derivation is `per-movement override ?? merchant-catalog prior ?? Uncategorized`. `CategoryAssigned` is keyed to the individual **movement key**, graded `verified`, and already **beats** the merchant-level default (proven by `test_human_override_beats_the_synced_enrichment`). So:

- Per-transaction categorization needs **no new event type**. A Zelle payment and a Zelle gift already carry different categories via two `CategoryAssigned` events on different movement keys.
- Categories are already **open strings** — `assign_category` accepts any label — so "create a new category" is, mechanically, "mint and reuse a label."

The presentation layer's job is therefore mostly *exposure*, plus two genuine modeling decisions below.

## Decisions to make with the presentation layer

**D1 — Peer/private descriptors default to per-transaction, not "everywhere."**
The surface already tags non-shareable items `private`. That tag should flip the interaction: a commercial merchant offers "Categorize everywhere" (merchant-level); a peer descriptor offers only per-transaction assignment. One ruling must not smear across a person's many unrelated payments.

**D2 — Custom categories are first-class and strictly local (T9).**
Recommended: a `CategoryDefined` event (name + optional color/icon), so the picker can list, rename, and style a user's own categories ("Gifts", "Loan to Raj", "Rent split"). The alternative — implicit strings, any label used in a `CategoryAssigned` *is* a category — is simpler but gives the UI nothing to enumerate or rename cleanly. Either way, custom categories are a **personal overlay**: they must be excluded from `export_catalog` and can never reach merchantcore or the commons. The 16 primaries remain the only shareable taxonomy; a user's categories live and die in the encrypted vault.

> **The implicit half of D2 is built, and it moved a T9 line nobody ruled on (2026-08-08).** A category exists by being used — `listen.category_vocabulary` is the seeds plus every name already in the vault — and that vocabulary now rides in the `category` slot of every question that can write one, which means it is **rendered into the interpreter prompt and sent to the model on every ruling**. A name like this doc's own "Loan to Raj" is exactly the kind of label that travels. It reaches no catalog, no commons and no export, so the letter of D2 holds; but the model is a boundary this decision never considered, and the merchant path that already sends a name past it is gated by `is_shareable`, while this is not. **Vishnu's ruling is owed, and it is owed before a Witness run** — that run is what would actually send them. The options are the gate (`is_shareable` over the vocabulary, which mutes a person's own words in their own question), the seeds only (which reopens the duplicate the vocabulary was added to close), or accepting it as within T9 because a per-ruling model call is already the path a person's sentence takes.

**D3 — A movement's *nature*: spending vs transfer/settlement.**
Today `spending_by_category` excludes only *linked* transfers. A lone Zelle a user marks "loan repaid" or "gift received" must be excludable from spending too, but it has no counterpart leg to link. Options: (a) let a per-transaction assignment carry a `nature` (spending | transfer | settlement) that the projection honors when aggregating; or (b) route "this is a transfer" to a **one-sided transfer** mechanism (an extension of transfer links) rather than a category. Leaning (a) for the common case — it keeps the user's action a single categorize gesture — with (b) reserved for when a real counterpart later appears and can corroborate. This is the subtle one; settle it before building, because it decides whether "spending" stays honest for peer money.

## Scope split

- **Core (ledger/projection):** whatever D3 chooses (a `nature` on the assignment, honored by `spending_by_category`), and — if D2 picks first-class — the `CategoryDefined` event + a custom-category projection that stays out of every export.
- **Presentation:** the per-transaction assign affordance, the private-vs-commercial interaction split (D1), and a category picker with "+ New category," reading the custom-category projection.

## Deferred (not now)

Learned auto-apply for peer descriptors (e.g. "this Zelle counterpart is usually rent") — a later projection over the recorded `CategoryAssigned` events, exactly as merchant learning was; nothing here forecloses it, and nothing needs re-ingesting to get it. Merchant-as-Party and counterpart identity resolution also deferred.

## Why now (as a note, not a build)

The enrichment run made the boundary concrete and quantified: ~$65k of the vault is peer/settlement money the commons path can't and shouldn't touch. Recording the decisions now means the presentation-layer slice starts from a settled model instead of rediscovering it in UI code — and it keeps the honesty guarantee (spending excludes non-spending) from silently breaking the moment a user categorizes their first Zelle.
