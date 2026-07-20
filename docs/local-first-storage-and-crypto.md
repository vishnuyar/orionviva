# Local-First Storage & Crypto

**Status:** Draft · **Last updated:** 2026-07-19

## Requirements (derived from principles)

Data at rest encrypted, keys held by the user; a stolen laptop or copied disk yields nothing. Tamper-evidence: the record of what was ingested and answered should be append-only and verifiable — this is also the substrate the Phase 4 trust arc will stand on. Breach = bad day, not ruin (Taleb constraint). Simplest thing that works; no exotic dependencies on the trust-critical path.

## Storage layer options

- **SQLite + SQLCipher** — the boring, proven default. Whole-database transparent encryption (AES-256), single file, works everywhere, huge deployment history. Well supported from Python and Node/TS.
- **SQLite + OS keychain-wrapped key** — SQLCipher's key itself lives in macOS Keychain / OS equivalent, unlocked by user login or biometrics. Good custody UX without inventing anything.
- **Turso/libSQL, DuckDB, etc.** — interesting, not justified. DuckDB may earn a place later for analytical queries, reading from the canonical encrypted SQLite, but is not the system of record.
- **Original documents** stored as encrypted blobs on disk (age/XChaCha20-Poly1305 file encryption), referenced from the DB. Documents are the ground truth the provenance pointers resolve into, so they're kept forever, encrypted, immutable.

**Leaning:** SQLCipher-encrypted SQLite as the single system of record; original documents as encrypted immutable blobs; key wrapped by OS keychain with a user-held recovery phrase.

## Key custody

The hard part is not encryption, it's recovery. A single user key with no recovery = one lost laptop is ruin (violates the Taleb constraint from the *other* side). Working scheme: DB key wrapped twice — once by OS keychain (daily convenience) and once by a passphrase/recovery phrase the user stores offline (recovery). No cloud escrow by default. Optional user-arranged escrow (e.g., printed phrase, family member) is the user's call, not the product's.

## Tamper-evidence without a chain

Per the project's standing principles: signatures and transparency logs, not blockchains. The right-sized v0 mechanism is a **local hash chain over an append-only event log**: every ingestion, extraction, verification result, and correction appended with a hash linking to the previous entry. Optionally anchor the head hash periodically to any public timestamp (e.g., OpenTimestamps or even a signed git commit) — that makes the *history* tamper-evident without any data leaving the machine. This is cheap, boring, and exactly the substrate verifiable presentations can later be built on.

## Sync/backup (later, but don't foreclose)

Local-first ≠ single-device forever. The honest pattern: encrypted-blob sync where the server (if any) only ever sees ciphertext. Designing the storage layer as (encrypted SQLite + encrypted blobs + append-only log) keeps every future option open — file-level sync, user's own cloud drive, or nothing. No decision needed now beyond *not* baking in assumptions that storage is plaintext.

## Open questions

- Q5: validate SQLCipher ergonomics in whichever stack wins the form-factor doc; measure whether encryption overhead matters at personal-finance data volumes (near-certainly not).
- Key rotation story — needed before any real second user, sketch only for v0.
- Does the event log double as the agent's memory substrate (corrections, preferences), or is memory a separate store? Leaning: same log, different projections — one history, many views.

## Sources

Mostly settled engineering knowledge (SQLCipher, age, OS keychains, OpenTimestamps); no landscape volatility here. Revisit only if the stack choice (the form-factor doc) surfaces integration problems.
