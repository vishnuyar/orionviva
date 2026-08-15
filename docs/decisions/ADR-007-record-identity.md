# ADR-007 · Hybrid Record Identity (Permanent Random ID + Content Fingerprint)

**Status:** Accepted · **Date:** 2026-07-19 · **Decided by:** Vishnu · **Door type:** sticky-verging-on-one-way (every pointer references these forever)

## Context

Every provenance citation, correction, memory entry, and cross-reference will point at records — transactions, documents, figures, accounts — by ID, forever. An identity migration after a year of accumulated pointers is close to a rewrite. The scheme must survive the product's two defining behaviors: corrections are first-class, and the same reality arrives repeatedly (re-uploaded statements, overlapping exports).

## Decision

Two fields, two jobs. **Identity:** a random, permanent ID (UUIDv7-class, time-ordered) stamped at creation and never changed by anything — not corrections, not re-categorization, not schema migrations. **Recognition:** a content fingerprint (deterministic hash of normalized source fields) stored alongside, used at ingestion to detect duplicates and link re-observations of the same underlying fact. Corrections append events (ADR-004) referencing the unchanged ID; the fingerprint of the *original* extraction is retained for verification against source.

## Alternatives considered

**Content-derived IDs only** — elegant and self-verifying; the same record always names itself identically, so dedup is free. Fatal flaw here: correct a misread $1,200 to $1,300 and the record's identity changes, orphaning every pointer — in a product where corrections are core, this demands permanent migration machinery. (Patching it by hashing only the immutable original converges on the hybrid anyway.)

**Random IDs only** — simplest possible; but duplicate detection must then be solved separately and later, under pressure, and probably by adding the very fingerprint field this ADR adds calmly now.

## Consequences

Fingerprint normalization rules (which fields, how normalized, per record type) become part of the data-model deep-dive (the discovery map, A1) and must be versioned — fingerprints may be recomputed under new rules; IDs never. "Same fingerprint, different documents" (two identical $5.00 coffees on one day) is a known case: fingerprints *flag* candidate duplicates for the verification layer; they never silently merge.

**Amendment (2026-08-15) — what pointers actually reference, and the question
that leaves open.** The hybrid above is not what the code built, and this note
records the divergence without settling it.

What ships is one content-derived string doing both jobs. A document's id is the
SHA-256 of its own bytes — the address *is* the fingerprint — and a posted
movement is referenced by a key composed of that document id, the account, the
date, the amount, the description and an occurrence index. Every overlay that
points at a movement points at that key: a category assignment, a scoped ruling,
a transfer link, a tag. Events do carry a random `event_id` — a `uuid4`, not the
time-ordered UUIDv7-class id the decision specifies — but nothing
references it, so it is not the identity this ADR is about; and there is no
separate fingerprint field, because identity and recognition are the same
string. The reason the code gives is that the key survives a reingest, which
mints new event ids, because it depends on what was read rather than on the
event's identity — and that is true, and is a property a random id does not have
on its own.

It is also incomplete in precisely the way the *Alternatives considered* section
predicted. The key contains the amount and the description, so correcting a
misread figure changes the movement's identity and orphans every overlay
pointing at the old one — the fatal flaw named above when content-derived ids
were rejected. Today that is **latent rather than live**: the only correction
path acts on a statement that is still *held*, before it posts, so no overlay
can exist yet to be orphaned. It becomes live the day anything corrects a
movement that has already posted.

So this records a state and not a decision. It does not ratify content-derived
identity, and it does not supersede the hybrid above. Which scheme the product
should carry forward, and what a correction to a posted movement must do to the
pointers aimed at it, is an **open question** — the work to answer it has not
been done, and nothing here should be read as having answered it.

## Would reverse this

Nothing reverses issued IDs. Fingerprint algorithms evolve freely behind versioning.
