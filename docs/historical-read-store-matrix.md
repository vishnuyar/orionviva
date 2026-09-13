# Historical SQL read matrix (4G-A)

The historical oracle filters canonical events by `occurred_at <= as_of` and
then folds survivors in source sequence. `as_of` is a value-time cutoff, not a
revision or knowledge-time cutoff. A correction appended today with an old
value-time belongs in that old-date picture; a future-dated correction appended
earlier does not. Equal-date records retain source order. The current revision
must be held for the whole read, so later writes cannot change a response in
progress. The event log remains the sole write authority; this is a disposable
read model.

| Surface input | Eligible normalized SQL families | Temporal fold required |
| --- | --- | --- |
| Account identity, aliases, provenance | `accounts`, `account_names`, `account_alias_history`, `account_entities` | Eligible account events in source order; aliases apply only after their own event. |
| Balance and positions | `balance_observations`, `postings`/`transactions`, `positions` | Filter event value-time before selecting closing/opening and position snapshots; sum Decimal text without SQLite REAL. |
| Movement identity and direction | `transactions`, `postings`, account identity histories | Rebuild posting-derived movement identity from eligible events; do not filter the latest-state `movements` table. |
| Classification, tags, transfer state | `category_history`, `merchant_history`, `tag_history`, `ruling_history`, `transfer_history` | Fold eligible overlays in source order with canonical precedence and tie rules; recompute effective movement fields, tags, links, and suggestions. |
| Statement evidence and document links | `documents`, `document_account_history`, `document_reads`, `statement_periods`, `posted_document_events` | Keep only eligible records and select the canonical successful extract/accepted statement pair; document links cannot point forward. |
| Overview obligations, questions, and coverage | Rhythm/obligation records in `ruling_history`, held/review histories, eligible account/movement/document families | Use the historical projection semantics, not the mixed current-state `as_of` queue contract used by Review and Conversation. |
| Activity controls and page | Historical movement/overlay/document families above | Complete-or-refused vocabularies, pending-first order, exact count, and focus from the same held temporal state. |

The existing `applied_events` table is an authenticated identity/mapping ledger,
not a body mirror. The existing `movements`, `movement_tags`, `transfer_links`,
and `transfer_suggestions` tables are replaced with latest-state results at
generation publication. A query that merely adds `WHERE occurred_at <= ?` to
those tables cannot implement this matrix. The implementation should share
the pure folding rules behind current materialization where possible, but the
historical desktop route must not read EventStore, RawStore, or construct
`LedgerProjection` from SQL rows.

The executable corpus in `test_read_store_historical.py` covers full sample
Overview and Activity payloads, forbidden canonical replay, source-order
backfill/future exclusion, stale and unreadable-generation refusal, and
post-write coherence. Direct A2 tests cover Activity overlays, ties,
pagination/focus, bounds, planner, and held-generation cases. Direct A3 tests
cover complete Overview financial, utility, and current-period parity using
separate evidence and read-on clocks. Both desktop routes now use one held SQL
revision. Account-ledger keyset pagination is separate 4G-B work.
