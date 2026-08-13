# Categories & Tags — one partitions, one overlays

**Status:** ✅ **BUILT 2026-07-26** · **Amended 2026-08-13** (three classes of duplicate label, and who may merge each) · **Created:** 2026-07-26 · **Origin:** Vishnu: *"how are we addressing the differentiation between category and tags — user answers should fall under a category and subcategory and at the same time it can be a tag too. I do not think we have come back to the multiple tags discussion."* · **Blocks seeded:** the **tag overlay** (`MovementTagged`) · a second alias vocabulary.

**Invariants touched:** **T4** (an overlay over events already written; the complete tag set is re-asserted, never mutated) · **T9** (a category is shareable world knowledge; **a tag is personal meaning and never leaves the device**) · **X2** (a report whose parts do not sum must say so) · principle 2 (never bluff a number).

---

## The rule, written in discovery and unbuilt for months

From [data-model-considerations.md](data-model-considerations.md):

> **Double-entry governs the money (one balanced truth, verifiable); tags govern the meaning (freely multiple, user-owned, the moat).**

An empty `tags` field has sat on the transaction event since v0 as the door for exactly this. The category overlay deferred it deliberately. Nobody walked through it until the question above.

---

## The distinction is load-bearing, not stylistic

**A category is a PARTITION.** Exactly one per movement, so the parts sum to the whole. That is what makes *"where did my money go?"* answerable **and checkable** — 100% accounted for, nothing double-counted.

**A tag is an OVERLAY.** Many per movement, overlapping, and tag totals **deliberately do not sum** to spending. One movement carrying three tags appears in three lines; money with no tags appears in none.

Mixing them produces a report whose parts do not add up to its total. In this product that is a bluff, so the split is the same rule as everything else here, applied to labels.

So `spending_by_tag()` returns `untagged` and `total` alongside the per-tag figures, and callers must show them. **The category report closes; the tag report answers a different question** — *"how much on the Japan trip, across every merchant?"* — and must never be dressed as the first.

---

## What the question actually exposed

It was not a topic sitting beside the category sprawl. **It explains it.**

Look at the labels in the author's own answer key: `poker`, `playing poker`, `martial arts`, `down payment`. **Those are tags.** They were typed into a category field because a category field was the only field there was. The taxonomy has 16 controlled primaries; personal meaning was going into a slot built for a partition, and it had nowhere else to go.

Aliasing `playing poker → poker` treats a symptom. **The disease was a tag-shaped answer with no home.**

---

## And the split *is* the T9 boundary, at the label level

A **category** is shareable world knowledge: a merchant IS a coffee shop, for everyone, which is why a commons can hold one and why enrichment can produce one.

A **tag** is personal meaning: this coffee was on the Japan trip, this withdrawal was poker night. **No commons can ever know it**, and no model should propose one — a model minting personal meaning would recreate sprawl in the one layer where aliasing is hardest and sharing is forbidden.

That is why tags get **their own event type**. It makes *"tags never leave this device"* an **event-level** rule rather than a per-field check inside an event that is itself shareable, and event-level rules are much harder to get wrong by accident.

---

## The decisions

| | Decision | Why |
|---|---|---|
| **D1** | **Subcategory stays in the partition** | One per movement, comes from world knowledge, refines the category. As a tag it would break drill-down totals. |
| **D2** | **Enrichment never suggests tags** | A tag is your meaning; the commons cannot know it (T9). |
| **D3** | **Start tags fresh; leave existing labels alone** | *Vishnu.* Costs nothing in practice: the rebuilt vault carries **no human labels at all**, so the first answers land with both fields already available. |
| **D4** | **Both scopes — movement and merchant** | *"Everything from this gym is martial arts"* is one ruling instead of forty. A movement tag and a merchant tag are a **union, not an override**: both statements are true and a person who set both expects to find the movement under either. The merchant catalog rule still binds — a peer descriptor does not generalize. |
| **D5** | **Its own event, `MovementTagged`** | Different lifecycles (a tag is added without re-ruling the category) and different privacy. See above. |
| **D6** | **The complete set is re-asserted, last write wins** | Removing a tag is appending the set without it. No `untag` event to reconcile against an `add` that arrived out of order; replay stays trivial and the log stays append-only. |
| **D7** | **Tags alias in their own vocabulary** | A tag `poker` and a category `poker` are different things; merging one must not silently merge the other. `RulingRecorded(scope="tag", same_as=…)` mirrors the category alias exactly. |

_D4 unchanged, with a third scope coming: an account-scope tag — the interview's way of saying "this account belongs to the house" — is designed and unbuilt ([the-interview-and-the-schema-pack.md](the-interview-and-the-schema-pack.md), cycle 3). Movement and merchant remain the only scopes today._

## Two build notes the table does not carry

**Alias maps are maintained as the events replay, not derived per lookup.** Both vocabularies fold on the read side — but the fold reads a map built during replay; it does not walk the ruling set on every call. The naive version is a line shorter and is O(movements × rulings): it took the test suite from 32s to over 44s, on a fixture set far smaller than a real vault. The read-side fold is the design; recomputing it per call is not part of it.

**Resolution is a recorded ruling, never a similarity score.** The obvious shortcut for `poker` / `playing poker` is an embedding with a threshold, and it fails twice over. A tuned threshold is a keyword list with decimals — the same hand-maintained judgement this project keeps refusing, wearing a number instead of a word. And a score recomputed each run lets two labels merge on one run and separate on the next, which makes *a total that changed for no reason* a normal event. A ruling is asked once, recorded, and reversed by appending.

---

## Three classes of duplicate label, and who may merge each (2026-08-13)

A vault that let a model mint its own subcategory vocabulary came back with the
same idea under several labels. They are not one problem, and they do not have
one owner.

1. **Spelling.** `credit_card_payment` / `credit card payment`;
   `peer_to_peer` / `peer-to-peer`; `gym & fitness` / `gym and fitness`. Two
   labels differing only by a separator cannot encode a distinction anybody
   made.
2. **Number and connective.** `restaurant` / `restaurants`;
   `internet cable` / `internet and cable`. Fixable by convention going
   forward; historically only by English morphology, which **I5** forbids.
3. **Meaning.** `supermarket` / `grocery store`; `atm` / `cash withdrawal`.
   Whether two of these are one thing is a claim about how *this person's*
   money should be sliced.

| | Decision | Why |
|---|---|---|
| **D8** | **Class 1 folds deterministically, at the read funnel; classes 2 and 3 never fold without a ruling** | `subcategory_identity` maps underscore, hyphen, whitespace runs and `&` to one identity, and `derived_category` applies it where the alias fold already runs. Characters only, no vocabulary — so it is locale-safe in a way a plural rule is not, and it cannot merge two labels that differ in anything but punctuation. The primary category is untouched; its controlled names carry underscores of their own. |
| **D9** | **A fold that nobody was asked about is reported** | The separator fold moves a figure and appends no event, so `subcategory_merges()` names every group it brought together, the enrichment run prints it once, and a spending read grouped by subcategory carries it as a caveat beside the figures it changed — the three highest-value lines named and the rest counted. A group whose spellings met because a person *ruled* them the same is left out: it has an event behind it and was their own decision. |
| **D10** | **A model may propose a fold and may never apply one** | Merging two totals deletes a measurement's separateness. See **T9** in [design-invariants.md](design-invariants.md); a fold offered as a proposal can only cost a question, a fold applied on a model's word can delete a distinction the person made. The asker for classes 2 and 3 — one question per pair, ranked by the money it moves — is designed and unbuilt. |

The build note above still stands and now covers both maps: the subcategory
fold is maintained during replay, keyed *and* valued by identity, so a ruling
recorded against one spelling reaches every spelling the fold declares the
same, and the read funnel does not rebuild it per movement.

Measured consequence worth recording: after the seed vocabulary shipped, this
vault's fold reports **zero merges** — 73 labels, 73 spellings. The problem
dissolved as a side effect of one controlled file with one canonical spelling
per label, not because the fold did work.

---

## What it looks like

```
CategoryAssigned   → the partition. Shareable in shape; sums to the whole.
MovementTagged     → the overlay. NEVER shared; deliberately does not sum.

proj.tags_of(movement)      the union of its own tags and its merchant's
proj.known_tags()           the vocabulary, offered before a new one is minted
proj.spending_by_tag()      {by_tag, untagged, total, overlaps: True}
```

---

## What this does NOT do

Amount-splits (a $100 purchase as $70 groceries + $30 household) — still deferred, still a separate overlay that composes with both of these. Tag hierarchies. Tag suggestions from any model. Automatic promotion of a heavily-used tag into a category.

---

## Done-tests

`test_tags.py` (8). The load-bearing ones assert arithmetic that deliberately **does not** close: tag totals exceeding total spending, untagged money reported rather than hidden, and a tag never moving a figure in the category partition. Plus one that exists so a future refactor folding tags into `CategoryAssigned` has to argue with something.
