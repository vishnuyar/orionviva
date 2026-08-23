# Transfer Links & Cross-Document Corroboration — one movement, two witnesses

**State:** built
**Rules:** MON-56, MON-57, MON-58, MON-59, MON-60, MON-61, MON-62, MON-63, MON-64, MON-65, MON-66, MON-67

**Invariants touched:** T1 · T2 · T4 · T9 · principle 2 · principle 7.

## Rules

### MON-56 — a link is an overlay, and exclusion is derived on the read side
**State:** enforced
**Code:** product/viva/ledger/events.py:297 (`transfer_linked`); product/viva/ledger/projection/movements.py:248 (rung 1 of `decide_nature`)
**Test:** product/tests/test_transfers.py::test_internal_transfer_auto_links_and_excludes_from_spending

1. A `TransferLinked` event references two movement keys and carries the link's grade and evidence; the legs are not recategorized and there is no `Transfers` category.
2. A live link makes both movements nature `transfer` with reason `linked`, and every spending aggregate is on the shape-and-nature predicate.
3. Unlinking is another event; nothing is overwritten and the history stays replayable (product/tests/test_transfers.py::test_reject_dismisses_the_suggestion).
4. Each statement still reconciles on its own.

### MON-57 — a link references a stable movement key, not an event id
**State:** enforced
**Code:** product/viva/ledger/projection/movements.py:18 (`movement_key`)
**Test:** product/tests/test_transfers.py::test_auto_link_is_corroborated_and_survives_a_replay

1. The key is `doc_id|account|date|amount|description|occurrence`, anchored to content rather than to an event's identity.
2. A reingest mints new event ids and the link still resolves.

### MON-58 — decisive auto-links, ambiguous asks, ties are refused
**State:** enforced
**Code:** product/viva/ingest/transfers.py:305 (`decide`), :226 (`_sole_max`), :332 (`link_transfers`)
**Test:** product/tests/test_transfers.py::test_ambiguous_amount_is_suggested_not_auto_linked

1. A decisive pair is appended as a link at grade `corroborated`; anything softer becomes a suggestion at `suggested`, and confirming it records `verified`.
2. Decisive means both directions are unambiguous: the source's best candidate is strictly best, and the source is strictly the best claimant of it.
3. A tie is refused and becomes a question, and the scan is computed over the whole graph first, so no outcome depends on the order a dict iterated (product/tests/test_transfers.py::test_a_tie_is_still_a_question, ::test_the_scan_is_the_same_whichever_order_the_graph_iterates).
4. Candidates require equal magnitude, the same currency, a different account, and a date within the window; currency is matched, never a bare amount (I1).

### MON-59 — the account evidence is the gate and the printed date is only a discriminator
**State:** enforced
**Code:** product/viva/ingest/transfers.py:216 (`_EV_ACCOUNT`, `_EV_DATE`, `_EV_FLOOR`), :283 (`weigh`)
**Test:** product/tests/test_transfers.py::test_the_printed_date_never_links_on_its_own

1. Account evidence — a distinctive token, or a proven `account_ref` slot — is worth 2; a printed date matching the candidate's date is worth 1; nothing links below 2.
2. A matching date can never create a link; it separates pairs that already qualify (product/tests/test_transfers.py::test_the_printed_date_resolves_a_week_of_identical_card_payments).

### MON-60 — genericness is measured, never listed
**State:** enforced
**Code:** product/viva/ledger/identity.py:81 (`distinctive_tokens`), :59 (`account_tokens`)
**Test:** product/tests/test_transfers.py::test_a_generic_word_no_longer_auto_links_anything

1. A token counts only when it belongs to one of the two accounts and to no other account the person holds (product/tests/test_transfers.py::test_a_token_two_of_your_accounts_share_names_neither).
2. A label token must also carry a digit; the institution name is exempt, because uniqueness is the whole test for a name.
3. The account holder's name is never a token — it sits on every account that person owns.
4. No English word list decides a link (product/tests/test_transfers.py::test_a_distinctive_token_still_links_without_asking).

### MON-61 — the printed date is read without knowing the country
**State:** enforced
**Code:** product/viva/ingest/transfers.py:170 (`_prints_date`)
**Test:** product/tests/test_transfers.py::test_the_date_is_read_without_knowing_the_country

1. Both day/month orders are tried, and at most one can match because every candidate is already inside the window.
2. The year is never parsed, so a line printed at the end of one year and posting at the start of the next matches with no year arithmetic (I5).

### MON-62 — a link records the rule that fired, never the value it matched
**State:** enforced
**Code:** product/viva/ingest/transfers.py:481 (`_evidence`, `decided_by`)
**Test:** product/tests/test_transfers.py::test_a_link_records_which_rule_decided_it

1. `decided_by` holds the rule's name, so a link can be audited later without re-deriving it.
2. `account_ref` is a personal slot: the matcher may read it, and nothing it reads may reach anything shareable (T9).

### MON-63 — a counterparty may supply a leg a statement's read dropped
**State:** enforced
**Code:** product/viva/ingest/statement_projector.py:212 (`_try_corroboration`), :99 (`heal_corroboration`); product/viva/ingest/transfers.py:394 (`find_corroborating_legs`)
**Test:** product/tests/test_transfers.py::test_cross_document_corroboration_closes_the_gap

1. Where a statement's gap exactly equals a decisive unmatched movement on another account the person holds, that movement supplies the missing leg, with no model call.
2. The supplied posting's provenance cites the **counterparty document**, at grade `corroborated`, with an explicit note that this statement did not state it.
3. A gap with no decisive counterpart is not closed; it holds for a person (product/tests/test_transfers.py::test_a_real_misread_is_not_falsely_corroborated).
4. The size-N case works the same way: counterparty movements that each distinctively name the account and whose magnitudes uniquely sum to the gap (product/tests/test_transfers.py::test_multi_leg_corroboration_supplies_a_missing_payments_section).
5. It heals in either ingest order (product/tests/test_transfers.py::test_corroboration_heals_in_either_order).

### MON-64 — a movement joins at most one transfer, and dead questions stop being asked
**State:** enforced
**Code:** product/viva/ingest/transfers.py:455 (`confirm_transfer`); product/viva/ledger/projection/movements.py:140 (`transfer_suggestions`)
**Test:** product/tests/test_transfers.py::test_confirming_one_removes_the_shared_movement_from_others

1. Within one scan a movement is consumed once linked and never offered again, and `confirm_transfer` is a guarded no-op if either movement is already linked.
2. A suggestion whose source is linked, or whose every candidate is, is dropped on the read side rather than withdrawn by an event — revoke the link that took the candidate and the question returns (product/tests/test_transfers.py::test_a_question_whose_candidate_was_taken_stops_being_asked).
3. Open questions are a level, not a delta: a sweep reports how many are open, not how many changed.

### MON-65 — both legs must be ingested own accounts
**State:** by-review
**Code:** product/viva/ingest/transfers.py:238 (`_candidates`, which ranges over posted movements only)
**Test:** none

1. A transfer naming a destination the vault has never ingested cannot be auto-confirmed as internal.
2. Every ingested account is by definition the person's; a named-but-unseen account is not.

### MON-66 — the date window is not the dial; the evidence is
**State:** enforced
**Code:** product/viva/ingest/transfers.py:34 (`DATE_WINDOW_DAYS`), :238 (`_candidates` scans unlinked movements only)
**Test:** product/tests/test_transfers.py::test_narrowing_the_window_does_not_unlink_anything

1. Narrowing the window unlinks nothing, because only unlinked movements are scanned: the constant governs the next scan, never the last one.
2. A narrower window can produce *more* auto-links, because auto-linking needs exactly one candidate and a wider window finds more (product/tests/test_transfers.py::test_a_wider_window_can_produce_fewer_auto_links).

### MON-67 — detection runs over a vault that already exists
**State:** enforced
**Code:** product/viva/ingest/statement_projector.py:138 (`sweep`)
**Test:** product/tests/test_transfers.py::test_sweep_links_previously_ingested_statements

1. `sweep()` stitches gaps, corroborates conflict-holds and links transfers over statements ingested before any of this existed, with no re-upload.
2. It is idempotent.

## Why

The moment a person holds several of their own accounts, an internal payment appears on *two* statements, so "how much did I spend" counts the same money twice. Real ingests surfaced a second, deeper case: a statement whose reconciliation gap is *exactly* a movement the counterparty document already attests — a card missing a payment that the checking statement plainly shows. Both are one recognition — **two legs, one movement** — so they are one mechanism.

This slice does own-account netting only. External Party attribution — a payment to a mortgage servicer or a person is a real outflow to someone else — rides the same entity-resolution block later.

The link is an **overlay** because per-statement reconciliation must keep holding: two statements' transactions cannot be merged into one balanced posting-set without breaking the gate that makes any of it trustworthy. A `Transfers` category was tried for the exclusion and could not carry the rule — one label covered two opposite natures — which is why exclusion is decided by derived nature instead ([honest-aggregates-and-the-learning-loop.md](honest-aggregates-and-the-learning-loop.md)).

Autonomy is earned by evidence, because a wrong link double-counts or hides real spending. The trap is two unrelated movements of the same amount on the same day, so decisive means exact amount, tight date, and evidence that pins the pair uniquely.

What that evidence is had to change once, and the reason is the most transferable thing here. Five English word lists used to decide it, and one of them was **always true** — a credit-card statement prints "card" on nearly every line, so for any card destination the hint held for anything, and the surviving constraints were equal amount and uniqueness alone. A rule that is always true is not a loose rule; it is a rubber stamp that reads, in the log, exactly like a check that passed. On a real vault it linked a cash withdrawal to an unrelated card payment of the same amount a day apart, removing both legs from spending: real cash spending vanished from the figure, and a card payment was recorded as a transfer that never happened. Two wrong numbers from one word. The replacement is a property of the data rather than of the language — a token unique to one of these two accounts among all the accounts held — so nothing has to guess which words are generic; genericness is measured.

Deleting the word lists left twenty-nine matches the software could no longer decide, and twenty-four were unanswerable only because nothing read the date the bank had printed on the source line: one checking account paying one card four times in eight days, every credit reading identically, the account evidence equally true of all four. The descriptor parser had been extracting that date as a named slot the whole time. The new signal had to be strictly a discriminator and never a second way in, because the thing just deleted was a signal that had quietly become a way in — which is why the floor sits at the account evidence and a date alone scores below it.

The corroboration rung sits *between* deterministic diagnosis and a bounded re-read in the repair ladder, because it is both cheaper and stronger: no model call, and two independent issuers attesting the movement rather than one. The discipline around it is what keeps it honest. A gap closed on a guessed link is precisely the confident-but-wrong figure the project cannot survive, so cross-document evidence *raises* confidence and never lowers the bar for closing a gap. Provenance points at the counterparty document with a note that this statement did not state it — marked that way it is a strength; merged silently it would be a lie about where the number came from. And the primary read is still recorded as **incomplete**, so reconciliation succeeds and the flywheel still learns the model has a recall problem: never a silent crutch that lets extraction quietly rot.

Why this matters beyond robustness: "the other party vouches" is cross-**issuer** corroboration, the exact trust primitive the endgame is built on — a fact provable because independent parties agree, immune to any single source being wrong. It appearing this early, for free, out of transfer-linking, is the thesis working.

Two intuitions about the date window are both backwards and both cost time before being written down, which is why they are rules rather than folklore.

The candidate index was never built, and that is a measured decision rather than an oversight. `_candidates` is a plain nested scan over unlinked sources by unlinked destinations; at the reference vault's roughly one thousand movements it costs about twenty milliseconds, and it stays under a second to about eight thousand — seven-plus years of statements at that rate. Two things dominate it long before then: the projection derives every movement's nature on the line above, and the scan runs once per posted document inside a pipeline whose per-document cost includes a model call measured in seconds. Build the index if a vault reaches five figures of movements.

The result on the real vault, after the stricter hint: sixty-seven of sixty-eight existing links survived, and the one that did not was the coincidence above, correctly revoked. Of the twenty-nine questions the deletion produced, twenty-four resolved on the printed date, and the five that remain are the five that should — the coincidence again, a payment that collided by amount, a duplicated statement line, and two whose true counterpart is not in the vault because that month's statement was never ingested.

## Open

- The one-sided own-account ask is unbuilt: a transfer naming an unseen destination is not turned into an "is …9876 yours?" question, and a confirmed transfer is not learned as a pattern so future look-alikes auto-link. Until then a one-sided transfer counts as spending until the other account is ingested, then auto-nets.
- A candidate index bucketed by amount and date is headroom nobody has needed to buy.
- A re-read that reorders or merges lines can move a movement fingerprint; revisit if reingest stability bites.
- Making a linked pair **self-net to zero** needs the kind-aware economic sign, which belongs to [net-worth.md](net-worth.md); the equal-magnitude assertion recorded here is its precondition.
- Cross-currency internal transfers have legs that differ by an FX rate rather than equal magnitudes, and are matched by a cited rate at answer time. Out of scope here — this is same-currency only.
- The **general** cross-document witness, where the corroborating statement belongs to someone else, needs the Party primitive and a lower default autonomy.
