# ADR-015 — SQLCipher binding for the disposable read store

**Status:** Accepted · **Date:** 2026-09-10

## Context

The canonical encrypted event log remains the source of truth, but desktop
reads need an indexed disposable projection. Plain SQLite would copy private
financial data into an unencrypted database. A system SQLCipher dependency
would also make the packaged sidecar depend on whichever library happened to
be installed on a person's computer.

## Decision

Use the self-contained `sqlcipher3==0.6.2` CPython binding and require a
non-empty `PRAGMA cipher_version` at process start and at every read-store
connection. Pin the CPython 3.12 wheel hashes for macOS arm64, macOS x64,
Windows x64, and Linux x64. Never fall back to Python's `sqlite3` module.
The wheel requirement lives in a dedicated lock and is installed separately
with pip's binary-only, hash-required, no-dependency mode. Editable product and
build-tool installs cannot act as an alternate unhashed dependency route.

The upstream wheels are accepted temporarily. PyPI reports that they were not
uploaded through Trusted Publishing and supplies no build attestation. Hash
pinning identifies the exact binaries but does not make their build
reproducible or independently audited. Every release target must therefore run
the packaged encryption smoke before this dependency passes the release gate.

Read-store metadata accepts exactly its versioned scrypt work tuple. The open
object retains neither its passphrase nor its derived raw key. Python cannot
guarantee erasure of immutable strings, interpreter temporaries, or copies in
the native binding; the implementation overwrites only the mutable key buffer
it owns, immediately after SQLCipher accepts the key. This is best-effort
lifetime reduction, not guaranteed process-memory zeroization.

The binding repository labels its code under a permissive license (its
repository carries the zlib license while current package metadata says MIT).
SQLCipher Community Edition is BSD-style licensed and requires its copyright,
conditions, and disclaimer in a user-accessible location. Its cryptographic
provider adds the applicable OpenSSL Apache-2.0 notice. Release notices must
include all three; the binding metadata discrepancy is treated as requiring
the more conservative union of notices until resolved.

## Alternatives considered

- `pysqlcipher3` publishes only a source distribution and requires a separately
  installed native SQLCipher library. It cannot satisfy binary-only packaging.
- Stock APSW wheels contain SQLite, not SQLCipher. A custom APSW build would
  still require maintaining four native crypto wheels while adding a new API.
- System linkage risks platform drift and accidental ordinary-SQLite linkage.
- Project-built audited wheels are stronger, but add a native release pipeline.

## Reversal condition

Move to project-built wheels from pinned `sqlcipher3` and SQLCipher sources
once the audited wheel pipeline exists. Switch sooner if an upstream hash,
license, ABI, encryption smoke, or artifact scan fails. The database format and
public ReadStore boundary must not depend on who built the binding.
