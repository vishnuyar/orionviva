# Authenticated document-resolution query

Parent direction, 2026-11-05: continue independent performance work while the native upload is blocked on app-access approval; preserve the prepared app and vault. Investigate the projection copy used for a boolean lookup, remove the unused local read, and measure caller-attributed impact without removing necessary copies.

Director admitted construction on a durable linked Git worktree from ef42690, with factual review confirming the seam. Worktree: /Users/vishnu/orionviva-resolution-query; branch: codex/consolidated-resolution-query. The consolidated source checkout and prepared native bundle remain unchanged. This isolated branch belongs to the same Git repository and is retained for later consolidation; no merge, push or commit is authorized here.

## Implementation fence

The shared Ledger synchronization retains its existing RLock callers, authenticated identity, event snapshot, incremental private fold, external-write refresh and BaseException cache revocation. A backward-compatible `publish=True` keyword gates only publication of a detached mutable public projection. New `Ledger.is_resolved` holds the same RLock, synchronizes with publication disabled, and returns the existing private projection predicate's boolean. Posted, held and instrument-component resolution semantics remain identical. No private mutable state escapes. Existing `projection()` retains its detached public view behavior and all mutation-isolation copies.

The pipeline replaces only `ledger.projection().is_resolved(doc_id)` with the scalar operation and removes the unused early `posted_before` assignment. The actual staged settlement's posted IDs and financial finalization remain unchanged. No other caller, staging authority, event schema, financial meaning, provider or SQL implementation changes.

## Validation and measurement

Focused controls cover cold/warm lookup without public publication, all resolution arms, external writes, forged/missing/rolled-back authenticated heads, revocation after errors, same-lock serialization, and hostile public view mutation. Run the affected existing ledger, store, pipeline and replay tests with a fresh independent Verifier; preserve actual counts and failures. Existing test KDF settings are not changed.

The measurement helper runs the same first 25 public PDFs through normal Vault.open, CuratedReader and capture_and_ingest, once on frozen baseline and once on candidate, in separate processes and fresh durable output directories. Same cProfile and wrapper instrumentation records actual Ledger.projection callers, private publication counts/time and direct deepcopy caller edges. Time only the same ingress scope; distinguish nested cumulative time from independent costs. Reuse the pinned prior conservation control, then sweep, synchronize SQL, verify originals/read receipts/canonical identity/SQL identity and fresh financial replay, close/reopen and verify again.

No measurement starts until source/control review. One pair, no automatic retry, 600-second watchdog per worker, isolated HOME/config/environment, RAM-only random disposable secret, audit-refused process/network operations, no paid calls or full load. Preserve partial output on any failure. Wrong source/import identity, forbidden operation, integrity/replay mismatch, changed prepared-app sources, financial ambiguity or genuine hang stops execution. This diagnostic pair is profiled, small, sequential and nonrandomized; it cannot qualify native upload, prove a stable unprofiled speedup or extrapolate to 794 documents.
