# Local-First Storage & Crypto

**State:** partial
**Rules:** PROG-42, PROG-43, PROG-44, PROG-45, PROG-46, PROG-48, PROG-49

## Rules

### PROG-42 — Nothing is readable at rest
**State:** enforced
**Code:** product/viva/crypto.py:86 (`seal`), product/viva/ledger/store.py:95 (`append`)
**Test:** product/tests/test_store.py::test_nothing_readable_at_rest

1. Every event body is sealed with AES-256-GCM before it reaches disk.
2. A copied vault file yields no plaintext to a reader without the passphrase.

### PROG-43 — The key is derived, never stored
**State:** enforced
**Code:** product/viva/crypto.py:78 (`derive_key`), product/viva/crypto.py:125 (`new_vault_header`)
**Test:** product/tests/test_crypto.py::test_the_vault_header_never_stores_the_passphrase_or_the_key

1. The vault key is stretched from a passphrase with scrypt and held only in memory.
2. The stored header carries the salt, the KDF parameters and a sealed check token — never the passphrase and never the key.
3. A wrong passphrase is refused by the header check before any record is read.

### PROG-44 — The crypto envelope is versioned, and its cost parameters are pinned
**State:** enforced
**Code:** product/viva/crypto.py:30 (`VERSION`), product/viva/crypto.py:34 (scrypt cost parameters)
**Test:** product/tests/test_crypto.py::test_the_production_cost_parameters_are_not_quietly_lowered

1. Changing an algorithm or a KDF parameter mints a new envelope version rather than editing the current one.
2. A record written under an unknown envelope version is refused, not guessed at.

### PROG-45 — The log is append-only, hash-chained, and verifiable without the key
**State:** enforced
**Code:** product/viva/ledger/store.py:55 (`_record_hash`), product/viva/ledger/store.py:312 (`verify_chain`), product/viva/ledger/store.py:75 (`write_head`)
**Test:** product/tests/test_store.py::test_the_chain_verifies_without_the_passphrase, product/tests/test_store.py::test_chain_detects_tampering, product/tests/test_store.py::test_records_removed_from_the_end_are_caught, product/tests/test_store.py::test_deleting_the_head_record_is_refused

1. Each record embeds the hash of the record before it, so dropping, reordering or splicing records breaks the chain visibly.
2. Chain verification needs no passphrase, so integrity is checkable by someone who cannot read the contents.
3. A record's sequence number and previous hash are bound into the GCM aad, so a ciphertext moved to another slot no longer decrypts.
4. The length of the log and the hash of its last record are recorded beside it, because the chain alone cannot see a truncation: a log with its final records removed is a shorter log that verifies. The record is written in the clear so clause 2 survives, and authenticated with a key derived from the vault key so it cannot be rewritten to agree with a truncation. A header that declares one and has none is refused, so deleting it is not a way out.

### PROG-46 — Original documents are encrypted, immutable, content-addressed blobs
**State:** enforced
**Code:** product/viva/ingest/raw_store.py:25 (`RawStore`), product/viva/ingest/raw_store.py:51 (`put`)
**Test:** product/tests/test_raw_store.py::test_put_is_content_addressed, product/tests/test_raw_store.py::test_same_bytes_dedup

1. An uploaded file is sealed and stored under the hash of its bytes, so re-adding the same file is a no-op rather than a duplicate.
2. Documents are the ground truth provenance pointers resolve into, so they are kept forever and never rewritten.

### PROG-48 — The key is wrapped twice, so a lost device is not ruin
**State:** unmet
**Code:** none found
**Test:** none

1. The vault key is wrapped once by the OS keychain for daily convenience and once by a user-held recovery phrase for recovery.
2. No cloud escrow is a default; any escrow is the user's own arrangement.

**Note:** What ships derives one key from one passphrase and stores no wrap of any kind (product/viva/crypto.py:16-19 states this in the module's own words). A lost passphrase is a lost vault — the exact "one lost laptop is ruin" outcome this rule exists to prevent. The requirement is deferred, not withdrawn.

### PROG-49 — The chain head is periodically anchored outside the machine
**State:** unmet
**Code:** none found
**Test:** none

1. The head hash of the event log is submitted periodically to a public timestamp (OpenTimestamps, RFC 3161, or an equivalent), so history is tamper-evident to a third party.
2. Anchoring sends a fingerprint only; no data leaves the machine.

## Why

Data at rest must be encrypted with keys the user holds, so a stolen laptop or a copied disk yields nothing. That much is settled engineering; the hard part is the two failure directions the same design has to survive at once. A breach must be a bad day, not ruin — and *equally*, a lost key must not be ruin either. A single unrecoverable key trades one catastrophe for another, which is why the second wrap is a requirement rather than a nicety, and why a recovery story that does not exist is stated out loud instead of implied.

Tamper-evidence is worth having and does not need a chain in the blockchain sense. A local hash chain over an append-only log makes history verifiable without anything leaving the machine, and the head hash can later be anchored to infrastructure that already exists. This is cheap, boring, and exactly the substrate verifiable presentations are built on later. Verification deliberately needs no key, so integrity is checkable by someone who is not allowed to read the contents.

Encryption belongs on the trust-critical path only in forms with long deployment histories; exotic dependencies there buy nothing and cost audit surface. Analytical engines may earn a place later reading *from* the canonical store, never as the store.

The storage layer options were weighed as four. **SQLite + SQLCipher** — the boring, proven default: whole-database transparent encryption, a single file, works everywhere, a huge deployment history, well supported from Python and Node/TS. **SQLite + an OS keychain-wrapped key** — SQLCipher's key itself living in the OS keychain, unlocked by user login or biometrics; good custody UX without inventing anything. **Turso/libSQL, DuckDB and their kin** — interesting, not justified; DuckDB may earn a place later for analytical queries reading from the canonical encrypted store, but is not the system of record. **Original documents** as encrypted blobs on disk (age/XChaCha20-Poly1305 file encryption), referenced from the database, kept forever, encrypted, immutable. The **leaning** among them was SQLCipher-encrypted SQLite as the single system of record, original documents as encrypted immutable blobs, and the key wrapped by the OS keychain with a user-held recovery phrase. That was a leaning and never a decision, which is why it is recorded here rather than as a rule.

Local-first does not mean single-device forever. Designing storage as an encrypted log plus encrypted blobs keeps every sync option open — file-level sync, the user's own cloud drive, or nothing — without baking in an assumption that storage is ever plaintext.

## Open

- The storage leaning was never taken up. The system of record is an encrypted, hash-chained JSONL event log (product/viva/ledger/store.py:1) plus a content-addressed encrypted blob store (product/viva/ingest/raw_store.py:25); no `sqlite`, `sqlcipher` or keychain dependency exists anywhere in `product/`, `core/`, `merchant/` or `bench/`. Whether the leaning is abandoned or merely unbuilt is undecided.
- Key custody: whether the second wrap is a keychain wrap, a printed recovery phrase, or both, and when it lands.
- Key rotation has no story beyond a sketch, and one is needed before any second user.
- Does the event log double as the agent's memory substrate (corrections, preferences), or is memory a separate store? The leaning is one log, many projections.
- Q5: measure whether encryption overhead matters at personal-finance data volumes, in whichever stack the form-factor decision picks.
