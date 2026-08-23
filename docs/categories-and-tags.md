# Categories & Tags — one partitions, one overlays

**State:** built
**Rules:** MON-75, MON-76, MON-77, MON-78, MON-79, MON-80, MON-81, MON-82, MON-83, MON-84, MON-19, MON-20, MON-21

**Invariants touched:** **T4** · **T9** · **X2** · principle 2.

## Rules

### MON-19 — a category partitions, a tag overlays
**State:** enforced
**Code:** product/viva/ledger/projection/categories.py:367 (`spending_by_tag`)
**Test:** product/tests/test_tags.py::test_tag_totals_do_not_sum_to_spending_and_the_report_says_so

1. Exactly one category per movement, so the parts sum to the whole.
2. Many tags per movement, overlapping, and the per-tag figures deliberately do not sum to spending.
3. `spending_by_tag()` returns `untagged` and `total` alongside the per-tag figures, and callers show them.
4. A tag never moves a figure in the category partition (product/tests/test_tags.py::test_a_tag_never_touches_the_category_partition).
5. `spending_by_tag()` returns an `overlaps: True` flag, so the data itself says the per-tag figures do not sum (product/viva/ledger/projection/categories.py:389).

### MON-75 — subcategory stays in the partition
**State:** enforced
**Code:** product/viva/ledger/projection/categories.py:237 (`spending_by_subcategory`), :256
**Test:** product/tests/test_category_identity.py::test_two_spellings_of_one_subcategory_are_one_line_in_a_report

1. A subcategory is one per movement and refines its category; it is not a tag.

### MON-76 — enrichment never suggests a tag
**State:** by-review
**Code:** product/viva/ledger/events.py:640 (`merchant_enriched` carries category and subcategory, no tags)
**Test:** none

1. No enrichment path proposes a tag, because a tag is personal meaning the commons cannot know (T9).

### MON-77 — tags start fresh; existing labels are left alone
**State:** untestable
**Code:** none found
**Test:** none

1. Introducing tags migrates no existing label into the tag vocabulary.

### MON-78 — both scopes, and a union rather than an override
**State:** enforced
**Code:** product/viva/ledger/events.py:719 (`movement_tagged`, scope movement or merchant); product/viva/ledger/projection/categories.py:327 (`tags_of`)
**Test:** product/tests/test_tags.py::test_a_movement_tag_and_a_merchant_tag_are_a_union_not_an_override

1. A tag applies to one movement or to every movement from a merchant.
2. A movement's tags are the union of its own and its merchant's, so a movement is found under either.
3. A peer descriptor does not generalize to a merchant-scoped ruling.

### MON-79 — tags live in their own event type
**State:** enforced
**Code:** product/viva/ledger/events.py:716 (`MovementTagged`)
**Test:** product/tests/test_tags.py::test_tags_live_in_their_own_event_type_so_t9_is_one_rule

1. A tag is written by `MovementTagged` and never by the category event.
2. A scope other than movement or merchant raises rather than being recorded (product/tests/test_tags.py::test_a_tag_cannot_be_attached_to_something_that_is_not_money).

### MON-80 — the complete set is re-asserted; last write wins
**State:** enforced
**Code:** product/viva/ledger/events.py:719 (`movement_tagged` takes the whole set); product/viva/ledger/projection/core.py:363
**Test:** product/tests/test_tags.py::test_the_complete_set_is_recorded_so_removing_a_tag_is_appending

1. A tag event carries the complete set for its subject, not a delta.
2. Removing a tag is appending the set without it; there is no untag event.

### MON-81 — tags alias in their own vocabulary
**State:** enforced
**Code:** product/viva/ledger/events.py:387 (`SCOPE_TAG`); product/viva/ledger/projection/categories.py:348 (`canonical_tag`)
**Test:** product/tests/test_tags.py::test_tags_are_normalised_and_alias_separately_from_categories

1. A tag alias and a category alias are separate maps; merging one never merges the other.
2. `known_tags()` is that vocabulary in canonical labels only, offered before a new tag is minted (product/viva/ledger/projection/categories.py:358; product/viva/tools/ledger_common.py:327, where a tag the vault does not hold is refused with the known ones).

### MON-82 — punctuation folds deterministically; nothing past it folds without a ruling
**State:** enforced
**Code:** merchant/merchantcore/taxonomy.py:75 (`subcategory_identity`); product/viva/ledger/projection/categories.py:36 (`derived_category`), :93
**Test:** product/tests/test_category_identity.py::test_punctuation_is_one_label_and_everything_past_it_is_two

1. Underscore, hyphen, whitespace runs and `&` fold to one identity, applied at the read funnel where the alias fold already runs.
2. Number, connective and meaning differences never fold without a recorded ruling.
3. The primary category is untouched by the fold.

### MON-83 — a fold nobody was asked about is reported
**State:** enforced
**Code:** product/viva/ledger/projection/categories.py:190 (`subcategory_merges`); product/viva/enrich.py:194
**Test:** product/tests/test_category_identity.py::test_a_run_can_say_which_spellings_it_folded

1. `subcategory_merges()` names every group the separator fold brought together, and the enrichment run prints it.
2. A group whose spellings met because a person ruled them the same is left out (product/tests/test_category_identity.py::test_a_merge_a_person_ruled_is_not_reported_as_one_nobody_asked_about).
3. A spending read grouped by subcategory carries the fold as a caveat beside the figures it changed (product/viva/tools/ledger_aggregates.py:107).

### MON-84 — a model may propose a fold and may never apply one
**State:** enforced
**Code:** product/viva/listen.py:161 (`ruling_slots` — the vocabulary is a prior, not a fence); product/viva/ledger/projection/categories.py:79 (a fold applies only from a recorded ruling)
**Test:** product/tests/test_category_identity.py::test_a_seed_label_never_displaces_one_a_person_minted

1. A shipped vocabulary leads the list a model is shown and never displaces a label already in use.
2. Merging two labels past punctuation requires a recorded ruling.

### MON-20 — the alias maps are built during replay, not per lookup
**State:** by-review
**Code:** product/viva/ledger/projection/core.py:295 (category and tag maps), :304 (subcategory map)
**Test:** none

1. Both vocabularies fold on the read side from a map maintained as the events replay.
2. No lookup walks the ruling set.

### MON-21 — resolution is a recorded ruling, never a similarity score
**State:** enforced
**Code:** product/viva/ledger/projection/categories.py:79 (`canonical_category`), :93 (`canonical_subcategory`)
**Test:** product/tests/test_category_identity.py::test_two_labels_for_one_thing_split_a_total_until_they_are_ruled

1. Two labels are one only where a ruling says so; nothing merges them on a score.
2. Alias chains are followed and a cycle terminates rather than hanging (product/tests/test_category_identity.py::test_a_chain_of_aliases_resolves_and_a_cycle_does_not_hang).
3. A ruling is retroactive, rewrites nothing, and is reversed by appending (product/tests/test_category_identity.py::test_the_ruling_is_retroactive_and_rewrites_nothing).

## Why

From the data model on: **double-entry governs the money — one balanced truth, verifiable; tags govern the meaning — freely multiple, user-owned, the moat.** An empty `tags` field sat on the transaction event from v0 as the door for exactly this, and the category overlay deferred it deliberately.

The distinction is load-bearing, not stylistic. A partition is what makes *"where did my money go?"* answerable **and checkable** — a hundred per cent accounted for, nothing double-counted. An overlay answers a different question — *"how much on the Japan trip, across every merchant?"* — and mixing them produces a report whose parts do not add up to its total, which in this product is a bluff. So the category report closes, the tag report says what it does not cover, and the second is never dressed as the first.

The question that produced this exposed the category sprawl rather than sitting beside it. The labels in the author's own answer key — *poker*, *playing poker*, *martial arts*, *down payment* — **are tags**, typed into a category field because a category field was the only field there was. Sixteen controlled primaries, and personal meaning going into a slot built for a partition. Aliasing one onto another treats a symptom; the disease was a tag-shaped answer with no home.

The split is also the T9 boundary at the label level. A category is shareable world knowledge — a merchant *is* a coffee shop, for everyone — which is why a commons can hold one and enrichment can produce one. A tag is personal meaning: this coffee was on a trip, this withdrawal was poker night. No commons can ever know it and no model should propose one, because a model minting personal meaning would recreate the sprawl in the one layer where aliasing is hardest and sharing is forbidden. Giving tags their own event type makes *tags never leave this device* an **event-level** rule rather than a per-field check inside an event that is itself shareable, and event-level rules are much harder to get wrong by accident.

Re-asserting the whole set (MON-80) keeps replay trivial: there is no untag event to reconcile against an add that arrived out of order, and the log stays append-only. Both scopes exist because *"everything from this gym is martial arts"* is one ruling instead of forty, and they union rather than override because a person who set both statements meant both.

Three classes of duplicate label came out of a vault that let a model mint its own subcategory vocabulary, and they do not have one owner. **Spelling** — two labels differing only by a separator cannot encode a distinction anybody made. **Number and connective** — fixable by convention going forward, and historically only by English morphology, which I5 forbids. **Meaning** — whether `supermarket` and `grocery store` are one thing is a claim about how *this person's* money should be sliced. Only the first is safe to fold without asking, because it carries no vocabulary at all and cannot merge two labels differing in anything but punctuation. And a fold that moves a figure while appending no event has to be reported, or a total changed with nothing to point at.

Merging two totals deletes a measurement's separateness, which is why a model may propose one and never apply one: a proposal costs a question, an application can delete a distinction a person made, silently and retroactively, at the one funnel every aggregate reads through.

The obvious shortcut for `poker` / `playing poker` is an embedding with a threshold, and it fails twice over. A tuned threshold is a keyword list with decimals — the same hand-maintained judgement this project keeps refusing, wearing a number instead of a word. And a score recomputed each run lets two labels merge on one run and separate on the next, which makes *a total that changed for no reason* a normal event.

Recomputing the fold per lookup is not part of the design either: the naive version is a line shorter and O(movements × rulings), and it took the test suite from thirty-two seconds to over forty-four on a fixture set far smaller than a real vault.

One measured consequence worth keeping: after the seed vocabulary shipped, this vault's fold reported zero merges across seventy-three labels. The problem dissolved as a side effect of one controlled file with one canonical spelling per label, not because the fold did work.

## Open

- A third scope — an account-scope tag, the interview's way of saying "this account belongs to the house" ([the-interview-and-the-schema-pack.md](the-interview-and-the-schema-pack.md)) — is designed and unbuilt. Movement and merchant are the only scopes.
- The asker for classes 2 and 3 — one question per pair, ranked by the money it moves — is designed and unbuilt.
- Amount-splits, tag hierarchies, tag suggestions from any model, and automatic promotion of a heavily-used tag into a category are all out.
