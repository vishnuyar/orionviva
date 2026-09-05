# ADR-005 · Encryption at Rest from Commit One, Versioned Envelope

_This records reasoning, not current behaviour._

**Status:** Accepted · **Date:** 2026-07-19 · **Door type:** one-way in the failure direction (a leak cannot be unleaked)

**State:** partial
**Rules:** ADR-005
**Invariants touched:** T5

## Rules

### ADR-005 — No plaintext phase, and every sealed object carries a versioned envelope
**State:** enforced-with-exception
**Code:** product/viva/crypto.py:31 · product/viva/crypto.py:34 · product/viva/ingest/raw_store.py:57
**Test:** product/tests/test_crypto.py::test_unknown_version_refused

1. All data at rest — database, document blobs, event log, model I/O captures — is encrypted from the first commit that touches real data.
2. There is no plaintext phase in development, in test fixtures derived from real documents, or in debug output.
3. Every encrypted object carries a versioned crypto envelope recording algorithm, key-derivation parameters and format version, so ciphers can be upgraded by re-encryption rather than archaeology.
4. Development ergonomics are solved with test keys and synthetic fixtures, never by temporarily disabling encryption.
5. Key custody is the companion decision, and the dual-wrap recovery scheme is a requirement rather than a sketch.

**Exception:** assertion 5 remains only partly implemented. What ships derives one key from one vaultphrase with scrypt under the envelope this record decided (product/viva/crypto.py:34). The desktop protects the default vault's directory and vaultphrase in macOS Keychain or Windows Credential Manager for automatic opening on that device, but there is still no portable recovery phrase or second wrap. Losing both the device credential and the owner's vaultphrase still loses the vault.

## Why

The first user is the author with real statements, meaning real financial data exists in the system from the first day of development. "We will add encryption before release" *is* the plaintext phase this record forbids: encryption posture is reversible while keys are held, but a single leak is absorbing.

**Encrypting only sensitive fields** gives a smaller blast radius per query, and classification errors are silent and permanent. In a financial dataset everything is sensitive, metadata included — payee names, timestamps — so whole-store encryption is both simpler and classification-proof.

**Relying on OS full-disk encryption alone** protects against device theft only; any process running as the user reads everything, and backups inherit whatever the backup target does. Rejected as a sole measure, welcome as an extra layer.

**Deferring until the storage engine is chosen** is the tempting sequencing error: the doctrine is engine-independent, and the storage-engine question is a two-way door *behind* this one-way posture.

**Unversioned formats** turn every future crypto migration into forensic reconstruction. The envelope is a dozen bytes.

This record makes lost-key equal to lost-data real, which is exactly why the recovery scheme graduated from sketch to requirement — and why its absence is stated plainly rather than left to be inferred.

## Would reverse this

Nothing. Algorithm choices rotate freely under the envelope; the posture does not.

## Open

- Portable key custody remains deferred: device-protected automatic opening exists, but there is no recovery phrase, portable second wrap, or social recovery.
