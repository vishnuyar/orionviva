# ADR-007 · Hybrid Record Identity (Permanent Random ID + Content Fingerprint)

_This records reasoning, not current behaviour._

**Status:** Accepted · **Date:** 2026-07-19 · **Decided by:** Vishnu · **Door type:** sticky-verging-on-one-way (every pointer references these forever)

**State:** partial
**Rules:** ADR-007
**Invariants touched:** T7, T4

## Rules

### ADR-007 — Two fields, two jobs: a permanent random identity and a versioned content fingerprint
**State:** contradicted-by-code
**Code:** product/viva/ingest/raw_store.py:44 · product/viva/ledger/projection/movements.py:17 · product/viva/ledger/events.py:127
**Test:** product/tests/test_raw_store.py::test_same_bytes_dedup

1. Identity is a random, permanent, time-ordered id stamped at creation and changed by nothing — not a correction, not a re-categorization, not a schema migration.
2. Recognition is a separate content fingerprint — a deterministic hash of normalized source fields — used at ingestion to detect duplicates and link re-observations of the same fact.
3. Corrections append events referencing the unchanged id, and the original extraction's fingerprint is retained for verification against source.
4. Fingerprint normalization rules are versioned; fingerprints may be recomputed under new rules and ids never are.
5. A fingerprint collision flags a candidate duplicate for the verification layer and never silently merges two records.

**Contradiction:** the decision specifies two fields doing two jobs. The code has one content-derived string doing both. A document's id is the SHA-256 of its own bytes, so the address *is* the fingerprint (product/viva/ingest/raw_store.py:44). A posted movement is referenced by a key composed of that document id, the account, the date, the amount, the description and an occurrence index (product/viva/ledger/projection/movements.py:17), and every overlay — a category assignment, a scoped ruling, a transfer link, a tag — points at that key. Events do carry a random `event_id`, a `uuid4` rather than the time-ordered id the decision specifies (product/viva/ledger/events.py:127), but nothing references it, so it is not the identity this record is about. There is no separate fingerprint field and no versioning of one.

## Why

Every provenance citation, correction, memory entry and cross-reference points at records — transactions, documents, figures, accounts — by id, forever. An identity migration after a year of accumulated pointers is close to a rewrite. The scheme has to survive the product's two defining behaviours: corrections are first-class, and the same reality arrives repeatedly through re-uploaded statements and overlapping exports.

**Content-derived ids only** are elegant and self-verifying — the same record always names itself identically, so dedup is free. The fatal flaw is exactly the product's core case: correct a misread figure and the record's identity changes, orphaning every pointer aimed at it, which in a product where corrections are core demands permanent migration machinery. Patching it by hashing only the immutable original converges on the hybrid anyway.

**Random ids only** are the simplest possible, and duplicate detection must then be solved separately and later, under pressure, probably by adding the very fingerprint field the hybrid adds calmly now.

The argument the code gives for its content-derived key is real: the key survives a reingest, which mints new event ids, because it depends on what was read rather than on the event's identity — a property a random id does not have on its own. It is also incomplete in precisely the way the alternatives section predicted. The key contains the amount and the description, so correcting a misread figure changes the movement's identity and orphans every overlay pointing at the old one. That is latent rather than live only because the sole correction path acts on a statement that is still held, before it posts, so no overlay can exist yet to be orphaned. It becomes live the day anything corrects a movement that has already posted.

## Would reverse this

Nothing reverses issued IDs. Fingerprint algorithms evolve freely behind versioning.

## Open

- Which identity scheme the product carries forward is unanswered. Nothing here ratifies content-derived identity and nothing supersedes the hybrid.
- What a correction to an already-posted movement must do to the pointers aimed at it is undecided, and the work to answer it has not been done.
