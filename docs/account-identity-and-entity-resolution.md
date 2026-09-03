# Account Identity & Entity Resolution — a learning building block

**State:** partial
**Rules:** MON-68, MON-69, MON-70, MON-71, MON-72, MON-73, MON-74

**Invariants touched:** T1 · T2 · T4 · T7 · I5. Serves the moat: identity learned per person, per institution, forever.

## Rules

### MON-68 — identity is signals, not a label
**State:** enforced
**Code:** product/viva/ledger/events.py:160 (`account_opened`, carrying institution, number and `account_names[]`)
**Test:** product/tests/test_pipeline.py::test_same_number_different_labels_are_one_account

1. Each statement contributes `account_number`, `institution` and `account_names[]` as dedicated signals rather than one free-text label.
2. Jurisdiction defaults to empty — *nobody has said* — never to a country nothing attested.
3. Per-format specifics live in a registry as data, so no code branches per country (I5).

### MON-69 — account ids are opaque when signals collide, and a readable number decides
**State:** enforced
**Code:** product/viva/ledger/identity.py (`account_key`, `identity_number_key`, `usable_full_number`, `opaque_account_key`); product/viva/ledger/projection/accounts.py (`resolve`)
**Test:** product/tests/test_pipeline.py::test_different_full_numbers_with_matching_last_four_both_post_and_replay; ::test_masked_value_with_more_than_four_digits_is_not_treated_as_full; product/tests/test_projection.py::test_issuer_legal_aliases_and_full_numbers_do_not_split_an_account; ::test_last_four_and_a_shared_issuer_word_do_not_merge_distinct_people_or_products; ::test_a_damaged_short_number_yields_to_an_explicit_printed_last_four

1. A usable full number is an unmasked field containing more than four digits; mask characters never become full-number evidence merely because more than four trailing digits remain visible. An explicitly printed last four is a partial signal. One to three trailing digits are not promoted into an account number.
2. Two readable, different account numbers are two accounts, with no question asked.
3. A full number survives issuer display-name variation. A shared last four is weaker: it resolves only when account kind, holder, issuer legal core and product are compatible, and conflicting number signals never merge.
4. Where neither statement shows a usable number, different product labels are separate accounts, compared as slugs.
5. The comparison is scoped to one account kind, so a card and a checking account sharing a holder are two accounts (product/tests/test_pipeline.py::test_card_and_checking_same_holder_are_two_accounts).
6. The historical institution-plus-last-four key is retained when unoccupied. A collision receives a persisted random, kind-scoped id; no digest of the full account number appears in an id or surface response.
7. The event log, not re-derivation from source files, is the identity authority. Replay and encrypted reopen preserve opaque ids exactly. A destructive from-source rebuild can assign the historical key and random collision id in a different arrival order, so anything exported outside a vault must treat account ids as vault-local references and carry an explicit remapping if a vault is rebuilt.

### MON-70 — one case is ambiguous, and only that one is asked about
**State:** enforced
**Code:** product/viva/ledger/projection/accounts.py:84 (`resolve`)
**Test:** product/tests/test_pipeline.py::test_ambiguous_identity_is_held_then_learned_as_new

1. A verdict is `same`, `new`, or `ambiguous`; never guessed.
2. `ambiguous` covers conflicting number signals and weak overlaps that do not justify a merge. A last four and shared issuer alone are insufficient.
3. A wrong split is visible and a merge ruling repairs it; a wrong merge corrupts a balance silently, so ambiguity is narrowed rather than widened.

### MON-71 — an ambiguous statement is held, and the ruling teaches the map
**State:** enforced
**Code:** product/viva/ingest/statement_projector.py:287 (the `identity` hold); product/viva/ingest/review.py:111 (`apply_identity_ruling`)
**Test:** product/tests/test_pipeline.py::test_ambiguous_identity_merge_learns_the_alias; ::test_masked_multi_candidate_can_be_assigned_to_a_specific_account; product/tests/test_questions.py::test_zero_candidate_identity_hold_can_be_confirmed_as_new

1. The statement is held under an `identity` reason carrying every compatible candidate and the reason — never posted on a guess.
2. The person's ruling is an append-only correction event that settles that exact document. A single-candidate ruling may also teach the signal map together with the ruled holder, product and account-kind signature; it generalizes only when those facts remain compatible. A multi-candidate last-four ruling may not teach the signal map, because the same lossy signal can name several accounts.
3. A safe single-candidate signal ruling resolves the next matching statement
   automatically. A multi-candidate ruling deliberately settles only its exact
   document, so a later lossy statement is reviewed independently.
4. An identity-held statement exactly adjacent to the observed coverage edge suppresses the duplicate gap question; a nonadjacent hold does not hide a real gap.

### MON-72 — an account carries an identity set
**State:** enforced
**Code:** product/viva/ledger/projection/core.py (the learned signal and document maps and their replay)
**Test:** product/tests/test_pipeline.py::test_ambiguous_identity_merge_learns_the_alias

1. Confirmation events replay into both a signature-scoped learned `signal → account` map and an exact `document → account` ruling map. Legacy events without a signature retain their historical replay behavior.
2. `account_id_for` remains the historical pure signal-key helper for compatibility. Any caller with a projection uses `resolve`, because only the projection can know learned, legacy, opaque, or document-specific identities.
3. Known signals resolve automatically; only new or ambiguous ones ask.
4. `AccountIdentityObserved` strengthens a masked account with later compatible full-number evidence without changing its persisted account id.

### MON-73 — a person and their accounts
**State:** unmet
**Code:** none found
**Test:** none

1. A `Party` exists as a primitive, and an account links to the parties who hold it, so a joint account is representable.

### MON-74 — transactions display in value-time order
**State:** enforced
**Code:** product/viva/ledger/projection/movements.py:221 (`transactions`)
**Test:** product/tests/test_pipeline.py::test_transactions_sorted_by_date_after_backfill

1. The log stays append-only in knowledge time; only the display is chronological.

## Why

The finding was real and dull: the same checking account arrived sometimes labelled by product name and sometimes by holder name, so a free-text label produced different account ids and statements failed to stitch. The fix is not a smarter label; it is a *learning* identity block.

Account identity is open-ended — same name with a different number, same number with a different name, two names on a joint account, reissued numbers, and endless per-country and per-institution formats. You cannot hardcode the cases; you will never finish. So identity uses the system's universal shape: **extract signals → produce a graded match → act automatically when confident, ask only when ambiguous → learn from the answer.** That one shape absorbs every case including unseen ones, and the intelligence being added is the *learning*: a person confirms each new kind of ambiguity once, and the system resolves that pattern automatically ever after, for all account types, with no bank-specific code.

Which cases are ambiguous narrowed deliberately, against the intuition that more questions are safer. A usable full number is the strongest anchor, while a printed last four is only one signal among kind, holder, issuer and product. That distinction lets an account survive harmless issuer-name variation without letting two cards that share four trailing digits collapse into one. Conflicting number evidence is held, not smoothed over. The rule underneath is the asymmetry — a wrong split is visible and a merge ruling repairs it; a wrong merge corrupts a balance silently.

The same block is reused everywhere else identity is needed. Merchants, employers and transfer counterparties are all entity resolution — the identical signals-to-graded-match-to-ask-to-learn shape. Accounts are just its first use, and the learning-from-corrections is the moat, turned on from the first ambiguous statement.

The bundled fix came from the same finding: the ledger is bitemporal, so a backfilled older statement lands last in knowledge time while a person reads a statement chronologically. Sorting the *view* by value time makes that visible without touching the log.

## Open

- **Party is unbuilt** (MON-73). Holder names remain a flat, incomplete list of strings on the account. `AccountIdentityObserved` can add names when a compatible masked account first gains full-number evidence, but an ordinary later statement that first reveals a joint holder still records no identity event. "Joint" survives only as the reason the list is a list.
- Three questions this block was designed to ask are not asked: *matches your name but a different number*, *same number different name*, and *two names — a joint account?*. The first two are settled by rule instead, and the third has nothing to record an answer into until Party exists.
- The identity hold carries no reconciliation `Finding`; the same held-document path and event carry it under an `identity` reason for balance and brokerage statements.
- The **graded** match in the shape above is not built. `Resolution` (product/viva/ledger/projection/accounts.py) carries `account_id`, `key`, `verdict`, one candidate or a candidate set, names and a reason, but no grade; the deterministic rules in MON-69 settle the cases a score was to have graded.
- Jurisdiction is a plain field with no source and no grade. Making it a graded attribute, with the country tag derived, is designed and unbuilt.
