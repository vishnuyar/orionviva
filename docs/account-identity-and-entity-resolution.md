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

### MON-69 — the account key is the anchor, and a readable number decides
**State:** enforced
**Code:** product/viva/ledger/identity.py:41 (`account_key`), :24 (`number_key`)
**Test:** product/tests/test_pipeline.py::test_two_readable_numbers_are_two_accounts_and_nobody_is_asked

1. The key is the institution plus the last four digits of the number, so *same number, different name* is already the same key and resolves automatically.
2. Two readable, different account numbers are two accounts, with no question asked.
3. Where neither statement shows a number, two different product labels are two accounts, compared as slugs.
4. The comparison is scoped to one account kind, so a card and a checking account sharing a holder are two accounts (product/tests/test_pipeline.py::test_card_and_checking_same_holder_are_two_accounts).

### MON-70 — one case is ambiguous, and only that one is asked about
**State:** enforced
**Code:** product/viva/ledger/projection/accounts.py:84 (`resolve`)
**Test:** product/tests/test_pipeline.py::test_ambiguous_identity_is_held_then_learned_as_new

1. A verdict is `same`, `new`, or `ambiguous`; never guessed.
2. `ambiguous` is raised only where a **holder name** overlaps a held account of the same kind and nothing stronger tells them apart.
3. A wrong split is visible and a merge ruling repairs it; a wrong merge corrupts a balance silently, so ambiguity is narrowed rather than widened.

### MON-71 — an ambiguous statement is held, and the ruling teaches the map
**State:** enforced
**Code:** product/viva/ingest/pipeline.py:414 (the `identity` hold); product/viva/ingest/review.py:111 (`apply_identity_ruling`)
**Test:** product/tests/test_pipeline.py::test_ambiguous_identity_merge_learns_the_alias

1. The statement is held under an `identity` reason carrying the candidate account, its name and the reason — never posted on a guess.
2. The person's ruling is an append-only correction event that updates the identity map.
3. The next matching statement resolves automatically, with no re-ask.

### MON-72 — an account carries an identity set
**State:** enforced
**Code:** product/viva/ledger/projection/core.py:126 (the learned `signal-key → account_id` map), :243 (its replay)
**Test:** product/tests/test_pipeline.py::test_ambiguous_identity_merge_learns_the_alias

1. Confirmation events replay into a `signal → account` map, and `account_id_for` consults it rather than a raw label.
2. Known signals resolve automatically; only new or ambiguous ones ask.

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

Which cases are ambiguous narrowed deliberately, against the intuition that more questions are safer. The number is the anchor, and a checking and a savings account at one institution share a holder by definition, so two readable different numbers are simply two accounts — that arrangement is the most ordinary in personal finance, and asking about it meant asking on almost every real vault. The mirror case never reaches the matcher at all, because the key already folds it. What survives is the weakest signal there is: a holder's name, which sits on every account that person owns. The rule underneath is the asymmetry — a wrong split is visible and a merge ruling repairs it; a wrong merge corrupts a balance silently.

The same block is reused everywhere else identity is needed. Merchants, employers and transfer counterparties are all entity resolution — the identical signals-to-graded-match-to-ask-to-learn shape. Accounts are just its first use, and the learning-from-corrections is the moat, turned on from the first ambiguous statement.

The bundled fix came from the same finding: the ledger is bitemporal, so a backfilled older statement lands last in knowledge time while a person reads a statement chronologically. Sorting the *view* by value time makes that visible without touching the log.

## Open

- **Party is unbuilt** (MON-73). Holder names are a flat list of strings on the account and they do not accumulate: the list is *replaced* by the statement that opened the account, and the opening event is emitted at most once per account, so a second statement that first reveals a joint holder never records that name. "Joint" survives only as the reason the list is a list.
- Three questions this block was designed to ask are not asked: *matches your name but a different number*, *same number different name*, and *two names — a joint account?*. The first two are settled by rule instead, and the third has nothing to record an answer into until Party exists.
- The identity hold carries no reconciliation `Finding`; the same held-statement path and event carry it under an `identity` reason.
- The **graded** match in the shape above is not built. `Resolution` (product/viva/ledger/projection/accounts.py:31) carries `account_id`, `key`, `verdict`, `candidate`, `candidate_name` and `reason`, and no grade; the deterministic rules in MON-69 settle the cases a score was to have graded.
- Jurisdiction is a plain field with no source and no grade. Making it a graded attribute, with the country tag derived, is designed and unbuilt.
