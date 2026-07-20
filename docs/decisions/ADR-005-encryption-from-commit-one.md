# ADR-005 · Encryption at Rest from Commit One, Versioned Envelope

**Status:** Accepted · **Date:** 2026-07-19 · **Door type:** one-way in the failure direction (a leak cannot be unleaked)

## Context

The first user is the author with real statements — meaning real financial data exists in the system from the first day of development. "We'll add encryption before release" is the plaintext phase this ADR forbids: encryption posture is reversible while keys are held, but a single leak is absorbing (the Taleb constraint).

## Decision

No plaintext phase, ever — including development, including test fixtures derived from real documents. All data at rest (database, document blobs, event log, model I/O captures) is encrypted from the first commit that touches real data. Every encrypted object carries a **versioned crypto envelope**: a small header recording algorithm, key-derivation parameters, and format version, so ciphers can be upgraded by re-encryption without archaeology.

## Alternatives considered

**Encrypt "sensitive fields" only** — smaller blast radius per query, but classification errors are silent and permanent; in a financial dataset, *everything* is sensitive, including metadata (payee names, timestamps). Rejected: whole-store encryption is simpler and classification-proof.

**Rely on OS full-disk encryption alone** (FileVault etc.) — protects against device theft only; any process running as the user reads everything, backups inherit whatever the backup target does. Rejected as sole measure; welcome as an extra layer.

**Defer until the storage engine is chosen** — the tempting sequencing error. Rejected: the doctrine is engine-independent; SQLCipher vs. alternatives (the storage doc) is a two-way door *behind* this one-way posture.

**Unversioned formats** — every future crypto migration becomes forensic reconstruction. Rejected: the envelope is a dozen bytes.

## Consequences

Development ergonomics must be solved honestly (test keys, fixtures from synthetic documents) rather than by "temporarily" disabling encryption. Key custody design (the storage doc, B3) is the companion decision — this ADR makes lost-key = lost-data real, so the dual-wrap recovery scheme graduates from sketch to requirement.

## Would reverse this

Nothing. Algorithm choices rotate freely under the envelope; the posture does not.
