# Encrypted read store implementation TODO

**Status:** Encrypted foundations, SQL-native desktop destinations (including
historical Overview/Activity and account-ledger pagination), SQL-native
question composition, and progressive startup are implemented. Jobs remains
registry-backed. Containment, whole-system, and release gates remain open.
This is a non-release integration state:
cross-platform signing, notarization, and clean-host compatibility are deferred
to the release phase and remain unproven.
**Owner ruling:** Keep encrypted, hash-chained, append-only events authoritative.
Add an encrypted SQLite materialized read store for incremental, indexed reads.
Keep raw documents outside routine startup. Load the desktop progressively and
bound every operation so one expensive surface cannot freeze the application.

This is a full-lane architecture cycle. A checked box means its named evidence
exists; passing a later phase cannot excuse a missing earlier gate.

## Completion standard

- Existing vaults open without changing canonical event or raw-document bytes.
- A current read store permits warm open without replaying the complete log.
- A stale store consumes only the authenticated suffix; a missing, corrupt,
  divergent, ahead, or incompatible store is never trusted and is rebuilt.
- Materialized personal data, indexes, journals, temporary files, and backups
  contain no plaintext financial data.
- Routine startup neither opens nor enumerates raw documents.
- The first useful screen appears within 3 seconds on the witnessed real vault;
  startup-priority panels settle within 15 seconds.
- A blocked surface cannot block navigation or leave sustained CPU work.
- Every materialized answer has parity with deterministic event replay.
- No monetary value is stored or calculated with SQLite `REAL`.
- Export, restore, integrity verification, and recovery remain independent of
  the disposable read store.
- Product, desktop, packaging, privacy, independent acceptance, interface, and
  real-vault Witness gates all pass on the same build.

## Non-negotiable invariants

- [ ] Every state change remains an event; surfaces never write read tables.
- [x] Event sequence, record hash, authenticated head, and atomic append remain
      the sole canonical history and write boundary.
- [ ] Corrections and rulings append history; materialization never rewrites it.
- [ ] The interface performs no financial arithmetic.
- [ ] Grades, provenance, dates, currencies, coverage, caveats, and stable
      identities survive materialization exactly.
- [ ] Raw originals remain encrypted, content-addressed external blobs.
- [ ] Writes and the user's original vault-open action are never replayed.
      One internal reopen of the exact active vault may restore an idempotent
      read generation.
- [x] A read-store failure cannot weaken canonical authentication or prevent
      export, restore, verification, or rebuild.
- [ ] The vault-open coordinator supplies the passphrase once to EventStore,
      RawStore, and ReadStore. Each independently derives its domain-separated
      sibling key using its own versioned salt and KDF metadata; ReadStore
      never receives or derives from either sibling key.
- [x] EventStore owns authenticated-prefix validation and suffix delivery,
      including legacy-header recovery; ReadStore never parses canonical log
      frames or invents a second authenticity rule.
- [x] One writer publishes immutable read revisions and any number of readers
      hold a named revision. A write reply and its following reads refer to one
      coherent revision; no reader observes a half-applied generation.
- [ ] Historical/as-of answers use the same resolver and projector semantic
      versions as current answers. A change to either invalidates the store.

## Phase 0 — Reproduce and measure before changing behavior

- [ ] Add privacy-safe spans for credential KDF, authenticated event snapshot,
      projection construction,
      bridge queue wait, each surface execution, raw-store access, frontend
      first-content time, process generation, timeout, and termination.
      Credential, authenticated-snapshot, projection, surface, raw-access,
      host request-wait, generation, timeout, and termination spans exist.
      Actual queue-entry-to-execution-start and committed/painted first useful
      content remain unobservable and must not be inferred from total request
      latency or dispatch completion.
- [x] Existing Python and Rust startup diagnostic emitters allow only
      operation/surface id, duration, state, generation, and termination
      result—never paths, payloads, values, names, document text, credentials,
      raw frames, or event counts from a private vault.
- [ ] Add a deterministic synthetic corpus at small, current-scale, 10x, and
      100x sizes with no real financial content.
- [x] Add a failing regression for the current all-surface aggregation barrier:
      one blocked secondary surface prevents the aggregate snapshot promise
      from settling even after another surface has completed. This is not yet
      a React render or first-content assertion.
- [ ] Add a packaged-process regression: a permanently CPU-bound read produces
      one generation failure, one termination/reap, settles all peer requests,
      and leaves no orphan or sustained CPU use.
- [x] Add a startup raw-store spy over every public blob-access route that fails
      if routine surface reads list, hash, write, decrypt, parse, or check raw
      blobs. Vault opening still authenticates the separate raw-store header.
- [ ] Measure the current implementation and name the actual hot operations.
- [ ] Record the exact pre-fix and counterfactual commands, fixture seed/scale,
      build kind, platform, elapsed spans, and expected failing assertion so a
      second machine can reproduce the comparison without a private vault.

**Gate:** The pre-repair failure is executable and separates file/KDF cost,
projection cost, queue delay, and containment failure. No root-cause claim is
accepted from file size or mocks alone.

### Slice 0 reproducibility record

- Desktop aggregation-barrier regression: `cd desktop && npm test -- --run
  src/surface/load-private-snapshot.test.ts`; the active priority and
  destination reads settle independently while a secondary aggregate read is
  blocked. Complete action aggregates still wait for all six secondary reads
  and a matching authenticated priority confirmation. This test does not
  observe React commit or browser paint and is not first-content evidence.
- Raw-store gate: `cd product && ../.venv/bin/pytest -q
  tests/test_desktop_bridge_vault.py -k routine_startup`; routine startup omits
  Documents, Trust, and Plans and touches no raw-blob API.
- Privacy record contract: `cd product && ../.venv/bin/pytest -q
  tests/test_startup_diagnostics.py`; only the five allowlisted fields may be
  emitted. Enable records with `VIVA_STARTUP_DIAGNOSTICS=1`; leave it unset for
  ordinary operation.
- Native containment: `cd desktop/src-tauri && cargo test hung_`. One
  real-process case proves the current timeout path terminates a silent process
  and a later request reaches a replacement. The peer case proves only that an
  explicit shutdown settles peers and reaps the process; it does not prove an
  automatic generation coordinator or CPU-bound packaged containment. Those
  remain unchecked above and due in Phase 5/Phase 6.
- Fixture seed and scales for the still-due synthetic corpus are fixed as
  `orionviva-read-store-v1` and `1x`, `10x`, `100x`; no private event counts are
  a scale input or diagnostic field.

## Phase 1 — Prove encrypted SQLite packaging first

- [x] Spike and pin one SQLCipher Python binding: `sqlcipher3==0.6.2`.
      The earlier candidate name `sqlcipher3-binary==0.6.2` does not exist;
      the accepted distribution publishes self-contained CPython 3.12 wheels
      for all four release targets. Adoption remains conditional on all gates
      below.
- [ ] On macOS arm64/x64, Windows x64, and Linux x64, install binary-only,
      freeze with the production PyInstaller path, and launch the sidecar.
- [ ] Assert `PRAGMA cipher_version` is nonempty in every packaged artifact.
- [ ] Prove create/write/close/reopen, wrong-key refusal, integrity check, and
      crash/reopen in every packaged artifact.
- [ ] Prove stock SQLite cannot read the database and recursive artifact scans
      cannot find unique synthetic sentinels or `SQLite format 3`.
- [x] Pin the exact dependency version and CPython 3.12 release-target wheel
      filenames and hashes in a dedicated lock. Both desktop workflows install
      it in a separate binary-only `--require-hashes --no-deps` step before the
      product is installed `--no-deps`, so an editable install cannot bypass
      the lock; collect native libraries
      explicitly if PyInstaller does not do so reliably.
- [ ] If any release target lacks a reproducible audited binary, stop and choose
      a supported binding or build audited wheels in CI. Never fall back to
      plaintext SQLite or plaintext derived tables.

**Gate:** The actual shipped sidecar—not an interpreter-only test—opens an
encrypted database on every release target.

### Slice 1 foundation evidence

- The dependency is `sqlcipher3==0.6.2`, not the nonexistent
  `sqlcipher3-binary==0.6.2`. CPython 3.12 hashes pin the macOS arm64, macOS
  x64, Windows x64, and Linux x64 wheels used by the release matrix.
- Upstream wheels are not backed by PyPI Trusted Publishing attestations.
  ADR-015 records the accepted limitation and the migration path to audited
  project-built wheels. Hashes establish artifact identity, not provenance.
- `product/requirements-sqlcipher-wheels.txt` maps the supported CPython 3.12
  filenames to their PyPI digests: macOS universal2 for arm64, macOS x64,
  Windows amd64, and manylinux
  x86_64. Release and desktop-quality jobs enforce this file with
  `--only-binary=:all: --require-hashes --no-deps`; build tools and editable
  product installation are deliberately separate.
- The macOS arm64 development sidecar was frozen with Python 3.13 and launched
  through its real JSON-lines handshake. Startup now fails before accepting a
  request unless `PRAGMA cipher_version` proves SQLCipher is present. This is
  local packaging evidence only; it is not the four-target Phase 1 gate.
- `ReadStore.create` and `ReadStore.open` prove create/write/close/reopen,
  wrong-passphrase refusal, authenticated independent KDF metadata, required
  settings, stock-SQLite refusal, ciphertext sentinel absence, and POSIX
  owner-only permissions in focused interpreter tests. Packaged encrypted
  database operations, crash/reopen, recursive artifact scans, Windows ACLs,
  and every non-local release target remain due.

## Phase 2 — Read-store foundation and recovery

- [ ] Add `viva/read_store/` with isolated connection, schema, projection,
      query, rebuild, and migration boundaries.
      The isolated public connection boundary exists; projection schema,
      query, rebuild, and migration boundaries remain due.
- [x] Derive a third independent, versioned 32-byte read-store sibling key
      directly from the supplied vault passphrase, using ReadStore-owned salt
      and KDF metadata; never derive it from or access EventStore/RawStore keys,
      and never store or log passphrase/key bytes.
      Opening requires the exact versioned `(n, r, p)` tuple, not merely a
      bounded tuple; a correctly authenticated weaker envelope is refused.
      The opened `ReadStore` retains neither passphrase nor raw derived key.
      Python cannot guarantee erasure of immutable strings, interpreter
      temporaries, or copies inside the native binding, so the boundary
      promptly copies the immutable derivation result into a mutable key
      buffer, releases that temporary, and overwrites the owned buffer after
      `PRAGMA key`. This is only best-effort lifetime reduction, not guaranteed
      process-memory zeroization.
- [x] Use explicit cipher settings, including
      `cipher_plaintext_header_size=0`, `foreign_keys=ON`,
      `trusted_schema=OFF`, bounded busy handling, `synchronous=FULL`, and
      in-memory temp storage. Assert every setting after connection.
- [x] Begin with rollback-journal mode for the serialized sidecar. Any later WAL
      adoption must treat the database, WAL, and SHM as one encrypted state.
- [x] Create `projection_meta` containing schema, projector, key-derivation,
      source count/head, last sequence/hash, and `building|ready` state.
- [x] Create idempotent applied-event identity constraints without treating
      that table as a second source of truth.
- [x] Store read revisions under one private vault-local generation directory
      with owner-only permissions. Build a new immutable generation beside the
      current one, verify and fsync it, then publish a small current-generation
      pointer with a Windows-safe replace protocol (close handles before
      replace, retry only sharing violations, and recover an old or new valid
      pointer after interruption). Never depend on replacing an open database.
- [x] Preserve the last known-good store until replacement succeeds; safely
      discard only validated incomplete rebuild artifacts. Define bounded
      retention for superseded generations and cleanup on open, never while a
      reader holds that revision. Reader selection, connection opening, and
      reference acquisition share one lifecycle lock with cleanup. A failed
      native reader close retains its reference and reports the failure rather
      than making that generation eligible for deletion.
- [x] Document exact read-model paths, filenames, permissions, temporary-file
      rules, backup exclusions, revision retention, and secure deletion limits
      on macOS, Windows, and Linux.
- [x] Exclude the disposable store from vault export and restore. Restore
      rebuilds it from canonical events.
- [ ] Add wrong-key, corrupt-store, unknown-version, interrupted-build,
      interrupted-migration, and replacement-crash tests. Wrong key,
      authenticated-manifest tampering, all five publication boundaries,
      incomplete-build cleanup, old/new reader isolation, retention, and
      Windows sharing-violation retry semantics are covered. Schema migration
      does not exist yet, so interrupted-migration remains due.

### Slice 2 generation contract

- The private root contains `key.json`, authenticated `current.json`,
  `writer.lock`, `generations/`, and `quarantine/`. Each opaque
  `generations/g-<128-bit-random>/` contains one encrypted `projection.db`.
  A build exists first with `projection_meta.state=building`; it becomes
  eligible for publication only after a committed `ready` state, close,
  database and directory sync, and verification through a fresh read-only
  connection.
- Publication creates and syncs `current.g-<id>.tmp`, closes its handle, then
  atomically replaces `current.json`. That replace is the commit point: after
  it succeeds the referenced generation is retained and publication returns
  success even if the subsequent root-directory sync reports an observable
  durability warning. If replace reports an uncertain result, the coordinator
  rereads and authenticates `current.json` before deciding whether the new
  generation may be quarantined. Windows retries are bounded and limited
  to sharing/lock violations; the protocol never renames or replaces an open
  database. The authenticated pointer carries a monotonically increasing
  publication epoch and the projection's source count/head/sequence/hash; open
  requires those values to match the encrypted generation. Recovery completes
  only one valid temporary and rejects zero or multiple valid candidates; it
  never chooses by mutable filesystem time. Once pointer replacement and root
  sync succeed, publication has succeeded: bounded cleanup is best-effort and
  its latest error is observable for retry without reversing that result.
- The epoch detects an older authenticated pointer replay while the coordinator
  retains a higher observed epoch. It cannot detect rollback of the entire
  disposable read-model directory across process restart: an attacker able to
  restore `key.json`, the pointer, and its matching generation can also restore
  their authenticated epoch. Full restart-persistent anti-rollback requires a
  monotonic anchor outside this directory (for example canonical trusted state
  or an OS-protected counter) and remains deliberately unclaimed. Canonical
  events are unchanged by this slice.
- One bounded cross-process file lock plus an in-process lock admits one
  writer. Readers use SQLCipher read-only/query-only connections and bind to
  the manifest generation they observed. In-process reference counts prevent
  cleanup while those readers remain open. The serialized sidecar owns this
  coordinator; cross-process readers are not supported by this contract.
- Cleanup retains the current generation and two highest-epoch unreferenced
  ready predecessors. Invalid or incomplete unreferenced directories move to
  `quarantine/`; only its two newest entries remain. POSIX roots/directories
  are mode `0700` and files `0600`. Windows owner-only ACL proof remains a
  release-runner gate.
- The read model is disposable and excluded from the canonical export/restore
  contract by design; no export integration was changed in this slice.
  Unlinking files is not secure erasure on APFS, NTFS, ext4, SSDs, snapshots,
  or backups. Confidentiality after cleanup rests on SQLCipher and key
  destruction, not overwrite claims. Backups should exclude the entire
  read-model root; including it is safe only to the extent the encrypted vault
  passphrase remains safe.
- Root, metadata, lock, current/temporary manifests, generation directories,
  database files, rollback-mode WAL/SHM exclusions, and quarantine entries are
  validated as ordinary filesystem objects and must remain lexically beneath
  the read-model root. Where the platform provides `O_NOFOLLOW`, final file
  opens refuse a link substituted between validation and use; a regression
  covers that boundary. In-process lifecycle/writer locks serialize OrionViva's
  own mutations. This Python, cross-platform implementation does not claim to
  prevent every parent-directory swap or hostile concurrent filesystem mutation
  performed outside OrionViva; protecting against that requires platform-native
  descriptor-relative directory traversal (or an equivalent trusted runtime).

**Gate:** An encrypted empty read store is disposable, recoverable, packaged,
and cannot affect canonical vault truth.

## Phase 3 — Incremental event projection

- [x] Add an authenticated suffix API: given an EventStore-minted authenticated
      cursor, validate it and return only later committed events plus new head.
      This is a public EventStore API, owns legacy and current head semantics,
      and performs no unauthenticated seek based on read-store metadata.
- [x] Implement normalized tables only for existing surface needs: accounts,
      balances/closings, postings/movements, document metadata, positions,
      transfer/category/tag/ruling overlays, questions/findings, goals/plans,
      conversation, and outbound/trust metadata.
      The lossless event table and the accounts, opening/closing observations,
      transaction/posting, position, and captured-document tables now exist;
      Append-only transfer, category, merchant, tag, ruling, account-alias, and
      provenance histories plus a revision-derived movement table now exist.
      Movement materialization applies the frozen resolver, collision-safe
      reviewed merchant aliases, component category precedence, category/tag
      alias graphs, movement/merchant rulings, own-account evidence,
      category-implied nature, and live transfer/suggestion resolution. The
      goal, conversation, review-decision, document-read, and unattended-agent
      histories now complete the canonical surface-input event vocabulary.
      SQL composition is complete for findings, obligations, the full
      current-period payload, and the complete question queue. All converted
      desktop destinations now have bounded SQL-native sources and named queries
      under the independently verified 4M destination matrix.
- [x] Preserve exact decimal text initially; introduce scaled integers only
      after a separately versioned currency-scale and overflow decision.
- [x] Apply a committed suffix once, in sequence, inside one database
      transaction; advance projection metadata as the final statement.
- [x] Keep writes event-first. If materialization fails after event commit,
      report a degraded read store and catch up/rebuild—never repeat the write.
- [x] Prove read-after-write coherence: an acknowledged event write is followed
      by catch-up/publication and all refreshed surfaces bind to that published
      revision; on failure the old revision remains visible with an explicit
      stale/degraded state rather than a mixture of old and new rows.
- [x] Detect equal, behind-valid-prefix, ahead, divergent, corrupt, wrong-key,
      and incompatible states using authenticated identity, not mtime or size.
- [x] Persist schema, projector, resolver, and as-of semantic versions. Rebuild
      on projector/resolver/as-of-semantic changes; migrate in place only for
      mechanically lossless, tested schema additions.
- [ ] Add fault injection before/during/after event commit, row updates,
      metadata advance, database commit, rebuild, migration, and reply.
- [ ] For every event prefix and legal batch boundary, prove incremental rows
      equal a complete deterministic replay.

**Gate:** Reopen at an equal head performs zero event folds; suffix work is
proportional to new events; every crash yields an old complete or new complete
revision, never mixed state.

### Slice 3 control contract

- `EventStore.committed_snapshot()` and `committed_suffix_after()` are the only
  projection inputs. Both run under the canonical writer lock and reuse the
  existing authenticated-header, authenticated-head, legacy, uncommitted-tail,
  hash-chain, and decryption rules. Full and legacy snapshots strictly validate
  sequence continuity, previous hashes, recomputed record hashes, and every
  sealed event. A modern suffix carries its prior byte boundary as an
  EventStore-MACed cursor; even the empty/genesis cursor must be minted by that
  EventStore, so arbitrary, cross-store, and forged offsets are refused. The
  authenticated current head is the cryptographic commitment to the intended
  canonical history. Equal-head work hashes and decrypts zero event records,
  and suffix work validates and decrypts only committed records after that
  cursor. Consequently neither fast path claims to detect a same-length physical
  mutation before its saved boundary. `EventStore.verify_committed_log()` is the
  explicit full physical-log integrity audit: it recomputes the whole chain and
  authenticates every sealed record. Full snapshots, rebuild/export paths, and
  canonical append validation retain their complete validation behavior.
- `applied_events(sequence PRIMARY KEY, event_id UNIQUE, record_hash UNIQUE,
  event_type, UNIQUE(sequence, event_type))`
  stores each canonical event id as a disposable idempotency witness, not
  history. Its count, contiguous last sequence, and terminal hash must agree
  with `projection_meta`; every row must also hold a nonblank event id and a
  canonical lowercase 64-hex record hash. Gaps, malformed identities, and
  duplicate ids or hashes abort the candidate generation transaction or force
  rebuild before equality can be accepted. Control schema v3 also stores a
  domain-separated ordered digest over every
  `(sequence, event_id, record_hash, event_type)`
  mapping. Its explicit empty genesis binds the schema and projector versions;
  each suffix extends it in the same metadata-last transaction. The authenticated
  generation manifest repeats that digest, and equality recomputes it from all
  rows, so plausible replacements away from the terminal row cannot be trusted.
  Control schema v6 persists the authenticated cursor, an authenticated
  canonical event-family discriminator, the frozen resolver profile mapping
  and its content hash, and the first materialized financial tables;
  older/incompatible control layouts rebuild rather than partially migrate.
  The schema also binds projector, resolver, as-of, and read-key metadata
  versions.
- Catch-up copies the current immutable encrypted generation, applies only the
  authenticated suffix, records each identity, and advances projection metadata
  last in one SQL transaction. Ahead, divergent, internally corrupt, or
  version-incompatible control state triggers a full rebuild from an
  authenticated committed snapshot. Wrong read-store keys still fail before
  this coordinator is available.
- SQL or projector failure leaves the previous generation published and raises
  an explicit degraded-read-store result. Canonical append has already won and
  is never retried by this path; a later synchronization catches up once.
  Tests cover restart, external canonical writers, equal/catch-up/rebuild,
  failure before/during/after row application and metadata advance, and failure
  after the SQL commit but before publication. Adversarial control tests cover
  plausible event-id replacement, nonterminal record-hash replacement, row
  reordering, gaps, duplicates, suffix digest continuity, digest-update
  rollback, and disagreement between the manifest and database metadata.
- EventStore invokes projection maintenance only after its authenticated head
  commit and treats that observer as best-effort, so projection failure cannot
  reverse an acknowledged write. Vault-owned synchronization authenticates the
  published generation against canonical identity before claiming it current;
  a source advance during publication is exposed as stale and the next suffix
  catch-up applies it once. Tests cover event-head interruption, post-commit SQL
  failure, observer failure, external append during publication, retry without
  replay, read-model deletion/reconstruction, and export/restore exclusion.
  Migration and worker-reply fault injection remain open in the broader fault
  matrix above.

## Phase 4 — Convert desktop reads in verified vertical slices

Each slice adds named queries, only the indexes those queries need,
`EXPLAIN QUERY PLAN` assertions, bounded limits, stable keyset ordering, full
contract parity, and then removes its replay path.

- [x] 4A — Accounts, closings, positions, and the Overview destination.
      A current-read backend prerequisite now composes the complete reviewed
      Overview payload from one immutable SQL revision, including account-card
      cash/position values and proof, net-worth picture and asserted assets,
      caveats, utility/current-period blocks, and spending by currency. Frozen
      parity covers a multi-account, multi-currency, mixed-vintage, asserted-
      property corpus plus suffix batches, restart, held-reader isolation,
      explicit bounds, planner inspection, and runtime guards against
      EventStore, RawStore, and LedgerProjection. Historical `as_of` Overview
      remains incomplete because current-period composition needs a separate
      evidence cutoff from its forward-looking horizon date. The backend
      prerequisite separates the complete committed-evidence boundary from
      the `today` used to date presentation and forecasts. Parity includes a
      future-dated account and balance plus a later-appended backfill. Position
      snapshots take one newest applicable statement date for cash and one for
      non-cash holdings, with the last source row winning a same-day instrument
      correction. Accounts, observations, positions, movements, documents, and
      rulings each have a literal refusal regression and return no partial
      projection when exceeded. Account balances, identity, provenance, and
      document types are batch-loaded: the prerequisite executes 15 statements
      for both the reviewed corpus and a 40-account corpus, down from the
      reported 145-query fan-out; the complete nested Overview contract is held
      to a 70-statement ceiling on the reviewed corpus. Every prerequisite
      statement is captured as executed, explained against the materialized
      schema, and refuses temporary sorting; this path contains no recursive
      CTE. Recursive goal-reservation folds used by nested current-period work
      retain their explicit preceding cardinality probes. Direct bridge
      Historical Overview and the whole-vault UI performance gate remain open.
      The current desktop bridge now opens and synchronizes the independently
      keyed read store during vault lifecycle, then returns Overview and
      Accounts together from one immutable generation in the typed
      `overview_accounts` envelope. Routine current reads do not construct a
      `LedgerProjection` or touch canonical/raw storage. Catch-up failure keeps
      the prior complete revision explicitly stale; Retry performs only another
      catch-up/read and canonical writes are never replayed.
- [x] 4B — Movements, categories, transfers, spending breakdowns, and the
      Activity destination. Current Activity (`as_of == ''`) and Spending now
      compose from one held encrypted SQL generation and refuse a stale,
      rebuilding, degraded, missing, or unreadable read model without opening
      the event log, raw store, or a `LedgerProjection`. Historical Activity
      uses the separate value-time SQL path completed in 4G-A. The current
      movement protocol preserves Decimal text, posting grade, evidence links,
      canonical category components, direct and inherited tags, loan ruling
      accounts, and complete-or-refused transfer links and suggestions. Its
      display query is pending-first, exact-counted, focus-aware, limited to
      100 rows, and uses `movements_by_activity_order` without a temporary
      sort; prerequisite movement/action inputs retain literal overflow
      refusal. Spending reconstructs accepted statement records only from the
      latest successful extract reply plus its accepted closing observation,
      preserving declared opening dates/amounts, corrected closing values,
      exact duplicate semantics, attested grades, and Decimal arithmetic. The
      register uses the named statement, document, and document-read indexes.
      Frozen whole-payload parity, pending/focus/count, planner, immutable
      held-generation, current-path deny-access, historical isolation, and
      stale/no-fallback regressions are executable evidence. Activity controls
      expose existing-choice category correction, supported spending/loan
      treatment correction, complete tag replacement, and transfer actions only
      when their bounded vocabularies or relationship evidence are complete;
      `desktop/src/surface/adapters/activity.test.ts` and
      `product/tests/test_surface_activity.py` hold that contract.
- [x] 4C — Document metadata and the Statements destination. Current Documents
      now composes its complete payload from one immutable authenticated SQL
      revision, including lifecycle, read outcome, accepted contribution,
      statement and brokerage-activity status, and complete held-review
      evidence. It refuses stale, rebuilding, degraded, missing, oversized, or
      unreadable read models without opening the event log or constructing a
      `LedgerProjection`. Raw reconciliation is scoped to explicit Documents
      navigation and enumerates only content identities needed for
      `raw_available` and `raw_document_count`; routine startup and every other
      converted destination remain raw-store free. The read is bounded to 200
      distinct documents with capped capture, reading, contribution, and hold
      histories. Named order-compatible indexes cover captured documents,
      readings, accepted statement contributions, and posted identities.
      Frozen sample parity, N+1 refusal, query plans, held-generation isolation,
      raw-access spies, stale refusal before raw access, and acknowledged-write
      coherence are executable evidence.
- [x] 4D — Current Review destination. The existing `ReviewSummary.v1`
      composer now receives the exact actionable question queue from one
      immutable authenticated SQL revision. Its transaction target uses the
      same revision's bounded movement, account, and statement inputs for
      identity/deduplication checks; ambiguous or incomplete references retain
      the canonical conversation target. Existing SQL question composition
      applies exact source-order declines, while SQL findings and set-asides
      remain backend prerequisites rather than an invented Review item kind.
      The current bridge path refuses stale/degraded generations without
      opening EventStore, RawStore, or `LedgerProjection`. Frozen payload parity
      at limits 1/100/500, held-reader isolation, acknowledged-decline
      coherence, and current-path deny-access tests are executable evidence.
- [x] 4E — Current Plans destination. `GoalsAndPlans.v1` now composes goal
      state, calendar math, account availability/evidence, open proposals,
      actions, and reviewed copy from one immutable authenticated SQL revision.
      The proposal fold applies first-recorded identity, source-order
      resolution, exact body text, and event receipts with explicit history,
      body-byte, and open-proposal bounds. Current bridge reads refuse
      stale/degraded generations without `fresh_projection()`, EventStore, or
      RawStore fallback. Complete surface parity, proposal resolution, N+1
      refusal, source-order planner evidence, held-generation stability, and
      acknowledged-write coherence are executable tests.
- [x] 4F — Current Conversation drawer and Trust destination. Conversation
      combines the as-of actionable SQL question queue with current durable
      turn/proposal folds and exact Review bindings from one held authenticated
      revision. Trust composes every recorded model phase and explicit
      maintenance absence from that same revision boundary, retaining the
      existing outbound formatter and exact Decimal accumulation. Both routes
      refuse stale/degraded state without canonical event, raw, or projection
      fallback. Full payload parity, held-generation isolation, acknowledged
      proposal resolution, N+1 refusal, source-order planner evidence, and
      structural deny-access tests cover the cutover.
- [x] 4G — Historical/as-of reads and account-ledger cursor pagination.
      The [temporal SQL matrix](historical-read-store-matrix.md) defines phase
      A's exact value-time/source-order inputs and counterfactual corpus.
      - [x] A1 — Record the temporal semantic matrix and failing replay/
        backfill counterfactuals before changing the read path.
      - [x] A2 — Bounded historical Activity SQL composer. Eligible normalized
        account, transaction, posting, category, merchant, tag, ruling,
        transfer, alias, and document rows are selected by value-time then
        folded in source order under one held generation. The adapter supplies
        movement identity/nature, exact Decimal text, merchant resolution,
        inherited tags, controls/vocabulary, evidence links, pending-first
        paging/count/focus, and loan treatments to the unchanged Activity
        surface. Complete sample and adversarial payload parity covers future
        exclusion, late backfills, same-date ties, duplicate movements,
        category/ruling aliases, transfer suggestions, and post-write held
        isolation. Each allowlisted event family/postings has explicit N+1 refusal and
        planner evidence. A4 completed the desktop route and its no-replay
        counterfactuals now pass.
      - [x] A3 — Bounded historical Overview SQL composer. One held revision
        supplies value-time account identity, Decimal balances, positions,
        movement-derived spending, document/ruling evidence, obligations,
        findings, questions, goals, and current-period inputs to the unchanged
        Overview surface. The evidence cutoff is `as_of`; forecast shape and
        freshness remain dated by `read_on`. Full-dict sample and composition
        corpus parity covers multiple horizons and a future/late-backfill
        counterexample. Direct tests forbid canonical/raw reads, assert held
        old-payload isolation, an observation N+1 refusal, fixed query count
        across 1 and 40 accounts, and planner use of persistent indexes.
        A4 completed the desktop historical route.
      - [x] A4 — Historical Overview and Activity desktop routes now open one
        held authenticated SQL revision and compose from their bounded
        temporal adapters. The three event-prefix counterfactuals pass;
        direct and bridge tests cover full payload parity, future exclusion,
        late backfill, stale/degraded and unreadable-generation refusal,
        acknowledged post-write catch-up, failed post-write sync refusal,
        and no canonical/raw fallback. Current-route behavior is unchanged.
        The inherited A2/A3 tests cover per-family bounds, planner evidence,
        and held-generation isolation. Account-ledger Phase B is verified below.
      Phase A converts historical Overview and Activity only. It requires a
      bounded temporal SQL fold over eligible normalized event-family rows:
      filter by event value-time first, then apply surviving rows in canonical
      source order. Current `movements`, tags, links, and suggestions are
      disposable latest-state tables and cannot be date-filtered into history;
      historical reads must derive their own temporal movement/overlay state.
      Keep every historical input in one held authenticated generation, with
      explicit N+1 refusal and no EventStore/RawStore/`LedgerProjection`
      fallback. Phase B owns account-ledger keyset pagination:
      - [x] B1 — Persist revision-derived per-account statement ownership and
        deduplicated movement components during encrypted generation build or
        catch-up. The bounded direct SQL semantic oracle scopes movements by
        requested account, parses latest accepted statement replies, folds
        coverage/overlap/exact duplicates, and refuses another account's valid
        statement evidence. Each encrypted generation now atomically stores
        per-account component rows under a descending keyset index, plus
        locale, ready/refused/identity-error state, exact component count,
        coverage, and overlap/dedup summary. Direct tests cover N+1 movement/
        statement and nested-byte caps, parser-locale binding, schema rebuild,
        held-generation isolation, rollback on projection failure, and index
        plans. The direct oracle still reads up to 10,000 account movements;
        only generation publication may invoke it, never a page request.
        Request-side reads reject a component index whose parser locale differs
        from the requested locale. Persisted schema and semantic parity passed
        independent B1 verification.
      - [x] B2 — Keyset page, exact remaining count, source/epoch-bound
        authenticated cursor, and complete row/source composition from the
        persisted component index without `OFFSET` or a full requested-account
        movement scan. A held-revision direct page API and v2 HMAC cursor are
        implemented. Direct tests exercise every safe sample account page,
        stale/forged/noncanonical/account-mismatched cursors, locale and limit
        refusal, keyset planner/cap+1, replay/raw denial, and generation-wide
        component bound. Independent B2 verification passed.
      - [x] B3 — Desktop bridge cutover, no canonical/raw fallback, full payload
        parity, stale/degraded/post-write and planner/limit gates. The bridge
        now routes through the held SQL page API and retains its session cursor
        key and `AccountLedger.v1` payload. Direct bridge tests cover sample
        page parity, statement overlap/coverage/evidence, stale/degraded and
        post-write revision behavior, no canonical/raw access, cursor forgery,
        and unsupported identity refusal. Independent B3 verification passed.
        `revision` is now the authenticated SQL source head, not the
        former whole-event semantic digest; clients treat it as an opaque
        change identity. Cursor v2 binds the account, authenticated source,
        publication epoch, generation, and page anchor to the provider session
        key. The frozen cross-language sample validates those two live tokens,
        then replaces only their nondeterministic bytes with explicit markers;
        every other field remains byte-compared and live cursor behavior has
        separate bridge regressions.
      Both phases passed whole-payload parity and structural counterfactual
      tests. Jobs was verified separately under 4H.
- [x] 4H — Jobs read, preserving its non-financial registry semantics while
      binding any post-write refresh to the same desktop revision contract.
      Jobs remains the in-memory/durable sidecar registry, with no SQL Jobs
      table. A degraded SQL generation does not prevent a registry read.
      Desktop startup and Activity correction no longer await a Jobs reply
      before publishing their financial read; old-vault job events and registry
      replies cannot attach to a replacement source. A terminal job requests
      a fresh authenticated priority revision before the wider reread.
      The wider post-job reread is bracketed by equal current authenticated
      priority revisions; a mismatch retains the prior view with a stale
      refusal. A single background registry-read slot now keeps a blocked
      Jobs handler off the serial vault request loop, and a real subprocess
      counterfactual exercises active priority service, duplicate refusal,
      and replacement retirement. A failed candidate reopen leaves the prior
      vault identity and its pending Jobs reply intact; a successful reopen
      retires the old reply. The independent full gate passed 2,813 product,
      869 desktop (plus one expected failure), and 16 native tests. Phase 5's
      packaged/manual state matrix remains open separately; this
      does not constitute real-vault or release acceptance.
- [x] 4M — Complete the materialized semantic prerequisites for every desktop
      destination. Overview/Accounts and current Activity, Spending, Documents,
      Review, Plans, Conversation, and Trust have bounded SQL-native sources
      and named queries. Historical/as-of and account-ledger routes have SQL
      verified implementations under 4G; Jobs was verified under 4H.
      The direct current Overview route and the legacy aggregate reread now
      use the same SQL Overview composer as the priority bundle, with typed
      stale/degraded refusal and no canonical/raw replay. The aggregate's
      six secondary reads are now bracketed by matching authenticated priority
      revisions for action and terminal-job aggregate publication. The
      destination field/query and read-time bound packets are registered and
      independently tested. The final optional-source whole-payload packet and
      consolidated inventory passed independent verification: 61 focused tests
      and 2,992/2,992 full product tests. This closes the desktop SQL semantic
      fence, not Phase 5 containment or Phase 6 release proof.
      `test_read_store_coverage_register.py` now derives the public typed
      constructor vocabulary and registers all 35 families against their
      primary typed/JSON SQL materialization and desktop consumers. This
      includes 34 families handled in the projection core and the separate
      `CorrectionApplied` document/review family. A new typed family without
      a register entry fails the test. The register is a vocabulary boundary,
      not itself field-level parity. A dynamic JSON-body packet now covers all
      five goal events, both goal proposals, both conversation turns, both
      conversation proposals, question decline, finding set-aside, and agent
      action. It checks exact typed bodies with absent/empty/null/zero nested
      values, repeated order, lexical Decimal strings and four provenance
      fields across four suffix cuts, fresh rebuild, restart, and a held reader;
      wrong-family publication is refused, and an unknown event advances the
      authenticated source identity without creating a domain-family row. The
      destination field/query matrix and per-family N+1/byte bounds were
      subsequently proved by the route and bounded-read packets below.
      A second dynamic packet covers the typed account/identity, opening and
      closing observations, transaction/posting, position, and captured-document
      rows. It compares every selected typed column, ordered duplicate/empty
      names, tags, and postings, high-scale lexical money, zero-versus-empty-
      versus-NULL fields, Unicode, and all provenance values across four suffix
      cuts, restart, full rebuild, and a held reader. These rows feed current
      Overview/Accounts through `SQLOverviewProjection` and `_identity_core`,
      historical Activity through `eligible_family`/`eligible_postings`,
      Documents through `SQLDocumentsProjection`, and account ledger through
      the persisted component builder; the remaining overlay/history query
      mapping and destination-by-field audit are still open.
      The overlay packet now compares every `transfer_history`,
      `category_history`, `merchant_history`, `tag_history`, `ruling_history`,
      `attribute_history`, and `account_alias_history` column against its typed
      event; the document packet does the same for read, hold, resolution, and
      correction rows. Their ordered nested arrays, source-tied category and
      merchant revisions, missing-versus-empty alias evidence, lexical values,
      and all four provenance fields survive multiple suffix cuts, rebuild,
      restart, and held readers. Wrong authenticated event-family substitutions
      are refused. The rhythm-control read proves tied keyset order, enforced
      limits, and its named index without a temporary sort.

      | Source fields | Read-model rows | Current destination/query evidence |
      | --- | --- | --- |
      | Transfer identity, candidate order, evidence, grade | `transfer_history` | Historical Activity/Spending: `temporal_activity.eligible_family`; current movement materialization: `ReadStore._refresh_movements`; Review/Conversation: `ReadRevision.transfer_links` and `transfer_suggestions` |
      | Category and merchant grade/actor subfields, aliases/attributes | `category_history`, `merchant_history` | Historical Activity/Spending: `temporal_activity.eligible_family`; current movement materialization: `ReadStore._refresh_movements`; Trust rhythms: `rhythm._merchant_records` |
      | Tag scope/subject and ordered canonical tags | `tag_history` | Historical Activity/Spending: `temporal_activity.eligible_family`; current movement materialization: `ReadStore._refresh_movements` |
      | Ruling scope, ordered legs, exact value/statement | `ruling_history`, `attribute_history` | Overview/Trust/Review: `SQLOverviewProjection._load_rulings`, `ReadRevision.obligation_control_history`, `questions._corroboration_questions`; Activity: `temporal_activity.eligible_family` |
      | Account alias evidence and optional identity distinctions | `account_alias_history` | Accounts/Statements/Review: `held._identity_core`; Activity: `temporal_activity.eligible_family` |
      | Model exchange, hold facts/finding, correction text | `document_reads`, `document_holds`, `document_hold_resolutions`, `document_corrections` | Statements/Review/Trust: `ReadRevision.document_read_history`, `ReadRevision.document_hold_history`, `ReadRevision.review_decision_history`, `SQLDocumentsProjection` |

      This is the packet's source-to-query map, not yet an exhaustive
      destination-field audit. Full route-level N+1/byte proofs remain open
      under 4M.
      The 35-family representative corpus now has an executable body-field
      register: every public typed constructor family appears and its observed
      body keys must match the declared field set. A new typed constructor
      family fails the vocabulary register. A separately tested unknown event
      between known events advances authenticated source identity and its
      provenance row, but creates no domain-family row or prevents the next
      known event from materializing at its exact sequence. An unrecognized
      encrypted-generation format refuses `ReadStore.open`; a format-version
      change therefore cannot silently serve an old generation. This closes
      the vocabulary/format part of 4M, not the destination field/query and
      per-family cap/byte gates.
      A route-bound audit found current Overview's `ruling_history.legs_json`
      was row-count bounded but could be arbitrarily large. The SQL select now
      returns a refusal sentinel instead of the oversized blob above one
      million UTF-8 bytes; direct tests prove exact-limit acceptance,
      limit-plus-one refusal before JSON decoding, and a plan without a
      temporary sort. The aggregate's authenticated priority start/confirm
      bracket now proves publication on one source revision; other destination
      read paths still need field/query and byte-bound evidence.
      The joined statement register used by Review/Spending also had a
      row-count limit but fetched unbounded extracted `response_text` before
      parsing. Its SQL select now substitutes a refusal sentinel above one
      million UTF-8 bytes. The new test demonstrates the previous missing
      refusal, exact-limit acceptance, and limit-plus-one typed refusal for
      ASCII and multibyte Unicode payloads;
      the statement-register scan uses the existing reversed account/date
      index without a temporary sort while preserving chronological records
      within each account. A two-account/two-period oracle checks complete
      Overview payload, per-account record order, and the production query plan.
      The shared SQL rhythm input for Overview, Review/Conversation questions,
      and Trust now bounds merchant attributes, merchant aliases, and frozen
      resolver-profile JSON to one million UTF-8 bytes each in the SELECT,
      returning a typed refusal sentinel before JSON decoding. Exact-limit
      and limit-plus-one tests cover ASCII and multibyte merchant fields and
      valid canonical profile JSON at the actual one-million-byte threshold.
      The old unbounded selects decode each oversized body in a counterfactual
      assertion before the production read refuses it. The merchant and
      profile scans are row-capped and have no
      temporary sort. This closes those three columns, not the remaining
      route-level field/query and byte audit.
      `test_read_store_route_contract_register.py` now enumerates every
      converted desktop read and the Jobs registry exception. Each route is
      bound to its held SQL protocol, a known-family body-field set, selected
      optional fields, and a named payload/bound test. It detects an added
      route without a register entry or a removed protocol/declared field.
      The coverage index is paired with the later field/query, byte/N+1, and
      whole-payload tests accepted under 4M.
      A further three-route byte packet closes the previously unbounded
      `document_reads.body_json` Trust select, Conversation turn/proposal
      `body_json` selects, and Plans proposal `body_json` select. Each now
      substitutes a SQL refusal sentinel before an oversized body crosses
      the Python boundary. Valid exact-million and plus-one ASCII/Unicode
      bodies, old unbounded decode counterfactuals, production SQL trace,
      typed refusal, and no-temporary-sort plans are executable tests.
      The held-document question input now also refuses oversized
      `facts_json` and `finding_json` in its SQL SELECT. A non-null oversized
      finding is never misread as absent: both fields use a typed refusal
      sentinel, while an authentic NULL finding remains NULL. Exact-million
      and plus-one ASCII/Unicode bodies, old-select decode counterfactuals,
      source-order query plans, and the downstream held-question suites pass.
      The account-ledger statement component SELECT now refuses an oversized
      extracted response before fetching it; valid exact-million and plus-one
      ASCII/Unicode responses exercise the former select, typed refusal, and
      indexed no-sort plan. Review's latest question/finding decision selectors,
      direct match reads, and history reads now likewise bound decision JSON
      in SQL, with exact byte, old-select, plan, and complete-or-refused tests.
      The cross-account ownership response has its own exact-byte and
      empty-response test. Its latest-currency source-order lookup needed a
      matching `accounts_by_identity_source` index; schema 29 rebuilds prior
      disposable generations so the named plan has no temporary sort. Direct
      document-response and model-exchange history APIs now bound their
      response/body fields in SQL with exact-byte and empty-value tests.
      Transfer candidate/evidence JSON now has SQL-side prefetch sentinels in
      current Activity, Review/Conversation questions, historical Activity,
      account-ledger context, and direct transfer-suggestion history. A common
      decoded envelope caps container width, nesting depth, node count, and
      candidate-key byte length; route-specific candidate counts remain
      tighter where required. Exact-million/+1 ASCII and Unicode evidence
      exercises current and historical reads with old-select decode and
      no-sort plans. Candidate arrays at the byte threshold are intentionally
      refused earlier by the 512-byte key cap; plus-one still proves prefetch
      refusal across Activity, Review, and account-ledger context. Existing
      route payload parity tests remain green.
      Account-ledger's persisted page now SQL-gates all five state JSON columns,
      keyset `members_json` (including the cap-plus-one probe row), and
      counterpart `account_json` before Python fetch. Exact-million and
      plus-one ASCII/Unicode tests exercise every column; an old unbounded
      select decodes each valid body, while the page refuses the oversized
      generation whole. Named state/keyset/counterpart plans have no temporary
      sort; nested JSON depth and per-page member cap-plus-one refuse without
      a partial formatter result. Existing complete AccountLedger.v1 payload,
      overlap/coverage, cursor traversal, stale/forgery, and no-fallback tests
      remain the final formatter parity evidence.
      A later formatter packet SQL-gates Documents capture identity/type/name,
      account-ledger movement text, account labels, evidence filenames, tags,
      and transfer/loan text at 4,096 UTF-8 bytes before page formatting.
      Account-ledger component JSON also refuses oversized nested strings,
      keys, containers, and depth. Exact 4,096/+1 ASCII/Unicode tests exercise
      filename, description, account name, and Documents capture columns;
      the page refuses whole and named filename/movement plans have no sort.
      Explicit Documents raw-presence enumeration is capped at 10,000/+1,
      after lifecycle readiness; priority Overview never enumerates it.
      A further account-ledger final-shape packet compares stored coverage
      runs/gaps and overlap groups to their independently recomputed statement
      record facts. The coverage comparison derives canonical runs from the
      statement record balance chain; it never adopts persisted run endpoints
      as its own oracle. Widened and shortened endpoints, a foreign statement
      ID, duplicated statement ID, incorrect gap, false overlap source, or
      malformed/inconsistent deduplication are refused whole; an older held
      generation still answers the exact prior page. Account identity and
      finite balance shapes also refuse malformed valid JSON before the
      formatter.
      A full-dict optional-source corpus now checks statement-only,
      movement-only, and joint evidence; captured and absent filenames; and
      present versus null periods against the canonical surface. The completed
      audit includes (1) a ten-route read-time bounds matrix for direct
      and historical Overview, Accounts, Activity/Spending, Documents, Review,
      Plans, Conversation, Trust, and account ledger, with named query traces,
      row cap-plus-one and SQL preparse byte refusal, including the
      `current_goal_states` body and the separate direct resolver profile read;
      (2) dynamic optional source-field-to-payload parity for each converted
      route, covering missing/empty/null/zero, ordering, provenance and exact
      Decimal, with complete-or-refused/no-fallback results. Packet (1) has
      an executable ten-route register naming row, UTF-8 byte, and planner
      evidence for each SQL destination. A confirmed gap in
      `current_goal_states` is closed: goal history bodies have a SQL-side
      million-byte sentinel and 10,000+1 total-row refusal before JSON parse,
      backed by a source-order index in schema 30. Exact-million/+1 ASCII and
      Unicode, direct cap-plus-one, no-temp-sort plan, and whole Plans bridge
      refusal are tested. The public `ReadRevision.resolver()` loader has a
      separate unbounded profile read but is not called by any converted
      desktop route; route-local rhythm resolution has independent profile
      caps. An actual synthetic ten-route trace now checks every observed
      SELECT: 353 statements in the sample, each with a literal limit or one
      of the declared identity/aggregate/preflight-bound classes. Every
      selected `_json` field in that trace requires a SQL-side byte sentinel.
      The trace exposed and closed unguarded held alias names, corroboration
      ruling legs, historical Activity overlay JSON, and historical resolver
      profiles. Exact-million/+1 ASCII and Unicode tests exercise alias,
      ruling, merchant, and resolver paths with valid old-read counterfactuals
      and no-sort plans. This does not close packet (1): the remaining concrete
      audit is scalar fan-out (account names, descriptions, IDs, labels, and
      provenance text) in shared current/historical routes, which is row-capped
      but not uniformly byte-gated before fetch. Packet (2)'s optional-field
      payload matrix also remains open.
      The first scalar class is now bounded: the shared held-identity fold
      SQL-gates account history text, holder names, alias identities and labels
      at 4,096 UTF-8 bytes before fetch, while retaining NULL distinctions.
      Exact-limit/+1 ASCII and Unicode tests cover the account display name,
      holder name, and alias label; all relevant named plans avoid temporary
      sorts. The other scalar classes are covered below.
      The shared movement/posting input class is now SQL-gated at 4,096 UTF-8
      bytes in current Overview/Activity, question/Review candidates,
      historical Activity transactions/postings, rhythm hypotheses, and
      findings; account-ledger page scalars were already gated. Exact
      4,096/+1 ASCII and Unicode descriptions and provenance notes prove
      old-select validity, no-temp named plans, and full route refusal on
      overflow. Empty provenance remains valid, while source table schemas
      prohibit NULL for these text columns. The later scalar and optional-field
      packets complete the route matrix.
      Overview's current and historical measurement fold now SQL-gates every
      observation/position text column at 4,096 UTF-8 bytes, including account
      and instrument IDs, exact Decimal lexical values, currency/grade labels,
      and all text provenance. The shared goal-account balance pre-read uses
      the same bound for its scoped account, opening/closing observation, and
      posting rows before constructing Overview or Plans. Exact 4,096/+1
      ASCII/Unicode provenance and instrument tests, exact lexical Decimal
      tests, N/N+1 family tests, no-temp plans, whole current/historical bridge
      refusal, and held old-payload stability cover this class. Required
      measurement text is non-NULL by schema; opening observations have a
      nullable `confirmed_by`, and the SQL guard preserves that NULL. Empty
      provenance remains valid. The
      Documents capture/read/post/hold/contribution labels, Conversation
      citation labels and durable turn/proposal history labels, and Trust
      displayed model/phase identities now use SQL-side 4,096-byte UTF-8
      sentinels before Python projection/formatting. Exact 4,096/+1 ASCII and
      Unicode tests cover read phase, citation filename, durable history date,
      and Trust configured/reported model and phase. The old scalar/body SELECT
      returns the oversized value, while the current whole desktop route
      refuses it. Optional absent versus empty reported model, held-reader
      stability, and no-temp production query plans are covered. Current goal
      state and Plans proposal/document reads now gate typed IDs, dates, event
      labels, event IDs, and displayed top-level goal/proposal JSON labels at
      4,096 UTF-8 bytes before Python parsing; all-goal reservation amount and
      account identities are screened before Decimal callbacks/final fetch.
      Rhythm account and frozen resolver profile keys have the same SQL gate,
      including the direct public resolver API, with the profile body retaining
      its separate 1 MB gate and row cap. Exact 4,096/+1 ASCII/Unicode goal ID,
      date, title, proposal, rhythm institution, and resolver-key tests prove
      accepted edge/refused overflow, old-select validity, held stability,
      whole Plans refusal, and named no-temp query plans. Frozen resolver rows
      cannot be independently modified in an authenticated generation, so the
      direct API key edge uses a constrained in-memory SQL fixture. The final
      optional-source corpus now names one declared optional field for each
      of the ten converted SQL routes and compares entire desktop payloads
      with independent canonical surface composers for all ten, plus historical
      Overview and Activity. Its source packet distinguishes absent versus
      present subcategory, empty labels, nested null/zero/repeated order,
      lexical Decimal, and all four provenance values. No-projection/event
      replay guards apply to every converted route. Held readers keep the old
      complete payload after a suffix; restart and a reconstruct-from-events
      generation reproduce every complete payload (opaque priority revision
      excepted). The packet caught and fixed two actual differences: a
      movement-only category incorrectly entered the SQL merchant question
      vocabulary, and an identity observation for a not-yet-open account
      entered historical Overview account listings. Both have discriminating
      regressions. The independent 4M review accepted this combined field,
      bound, plan, and route payload evidence.
- [ ] Index movement date/account/currency/nature/category/document and stable
      identity; observations by account/date; positions by account/date;
      documents by state/date; open review items by status/order; and every
      projector table by source sequence where its query requires it.
      Movement indexes now cover date, account/date, currency/date,
      nature/date, category/date, document/date, merchant/date, and the stable
      primary key. Overlay histories are indexed by their scoped subjects. The
      movement query's date/key cursor is exercised across every page for each
      selector, including many rows tied on the same date; invalid cursors and
      limits are rejected.
- [ ] Use `(date, stable key)` keyset cursors; forbid unbounded `OFFSET` and
      unbounded first-page materialization.
      `ReadRevision.movement_history` now has a 200-row hard bound and a
      `(occurred_at, movement_key)` cursor; direct surface conversion remains
      due.
- [ ] Materialize only measured expensive aggregates, starting with monthly
      spending or current-account summaries when evidence warrants them.

**Gate:** Ordinary surfaces query one named committed revision and match the
legacy projector's complete normalized payload on the frozen parity corpus.
No routine surface constructs a full `LedgerProjection`.

The conversion fence is the seven desktop destinations (Overview, Accounts,
Activity, Statements, Plans, Review, Trust), their conversation drawer and
on-demand spending/account-ledger reads, plus Jobs. CLI, export, restore,
verification, rebuild, and non-desktop consumers retain the canonical path
until separately approved; conversion does not silently widen to them.

### Slice 4 materialization foundation

- [x] Keep only authenticated source identities in `applied_events`; do not
  duplicate canonical event bodies. Unknown event families advance the source
  cursor but add no normalized row. `events.jsonl` remains the only complete
  event vocabulary.
- [x] Store the complete canonical payload of the implemented families:
  account/identity history and repeated names; opening/closing observations;
  transactions, repeated tags, and postings; position history including
  currency, cost basis, valuation class, and grade; and captured-document
  metadata including classification confidence. Every fact family carries all
  four provenance fields, including transfer, category, merchant, tag, ruling,
  and account-alias histories. Empty strings, Unicode, zero pages, and absent
  pages retain their event-contract distinction through explicit nullable
  columns.
- [x] Preserve Decimal lexical strings as `TEXT`, including negative, very
  large, and high-scale values. Preserve confidence with canonical JSON-number
  text rather than SQLite `REAL`. Preserve Unicode and repeated ordered values.
- [x] Bind child identities to their exact canonical event family, transaction, and account
  entity with primary/unique/foreign-key/check constraints. `source_sequence`
  is the fact identity because valid history may repeat every domain value;
  `(source_sequence, ordinal)` identifies ordered names, tags, and postings.
  `account_entities` admits accounts first seen through a posting or observation
  because that is legal projector input while still making orphan references
  impossible. Composite source-sequence/event-family foreign keys prevent a
  normalized row from borrowing another family's authenticated source event;
  the ordered mapping digest also commits the family discriminator. Every
  movement-overlay history has an explicit event-family discriminator, a
  fixed or closed-set check, and the composite foreign key; adversarial tests
  substitute a wrong family independently in each table.
- [x] Bind each immutable revision to its persisted resolver version and a
  canonical snapshot of the complete installed latest-profile mapping. The
  profile rows and their content hash live inside the encrypted generation;
  the hash is repeated by the authenticated manifest. An open revision resolves
  only through its frozen rows. A later installed-profile change invalidates
  equality and publishes a rebuilt revision while existing readers keep their
  original answers. Only registered `resolver-v1` semantics may be materialized
  or returned; version mismatch and unregistered synchronization fail explicitly.
- [x] Exercise rebuild, mixed multi-event suffix catch-up, backfills, repeated
  values, missing optionals, Unicode, extreme Decimals, restart, and `as_of`
  before/exact/between/after boundaries in the frozen normalized corpus.
- [x] Give five named reads five indexes: account identity history,
  account/date observations, postings by account, account/date positions, and
  captured documents by state/date. Representative-cardinality tests let the
  planner choose naturally and assert all five `EXPLAIN QUERY PLAN` results;
  they do not use `INDEXED BY`.
- [x] Bind direct surface contracts to normalized SQL. Every converted desktop
      route uses the bounded revision-local SQL protocol; Jobs remains the
      separately verified vault-local registry route.
- [x] Complete Slice 4M's remaining event families. One coherent prerequisite
      group is now materialized: document model-read history, statement and
      brokerage-activity holds, brokerage-activity resolutions, and document
      corrections. These tables preserve canonical nested facts/findings as
      canonical JSON, preserve response text and optional usage/model fields,
      keep exact cost text out of SQLite `REAL`, and bind every row to its exact
      authenticated event family.
- [x] Add bounded, revision-local document-history, model-read-history, and
      hold-history named reads with stable `(occurred_at, source_sequence)`
      ordering, keyset pagination for the cross-document history, limits of at
      most 200/50 rows, and planner-tested indexes. This is backend
      materialization only; it does not convert the Statements destination or
      reconcile raw presence.
- [x] Materialize the final canonical Trust/review event inputs: `AgentActed`
      unattended-work history and the complete canonical `ReadRecorded` body.
      The former carries rule, kind, target, outcome, call count, stake,
      produced/replaced artifact ids, detail, actor, all four provenance fields,
      and its exact authenticated event-family foreign key. The latter retains
      the complete model-exchange body beside its already-normalized model,
      phase, usage, parse, response, document, and exact canonical cost fields.
      Revision-local model-exchange and agent-action reads are bounded to 200,
      support stable `(occurred_at, source_sequence)` keyset traversal, and
      provide filtered and unfiltered order-compatible indexes. Dedicated
      question-decline and finding-set-aside reads reuse the lossless review
      decision history without conflating the two decision families. The
      frozen corpus proves Unicode/missing optionals, exact lexical stakes,
      tied pagination, arbitrary suffix batches, rebuild/restart equality,
      planner selection, and event-family substitution refusal.
- [x] Materialize the next coherent 4M backend group: statement-period and
      posted-document evidence; lossless question-decline, finding-set-aside,
      ruling, and correction review decisions; and rhythm rulings that control
      obligations/current-period interpretation. Every row carries all four
      provenance fields, an exact event-family composite foreign key, and the
      revision's authenticated ordered mapping digest remains authoritative.
      Bounded named reads provide document lifecycle, statement periods,
      review decision status/order, and obligation-control history with stable
      keyset ordering. Representative multirow planner tests execute the public
      filtered, unfiltered, and cursor shapes and prove order-compatible indexes
      without temporary sorting for document, statement-period, review, and
      rhythm-obligation history. Statement coverage uses the account/period
      index for its first-writer grouping but still needs a bounded final sort
      for its cross-account presentation order. The frozen corpus covers
      backfills, arbitrary suffix batches versus rebuild, historical state
      boundaries, exact Decimal text, foreign-key tampering, and traversal.
- [x] Materialize the Plans/Conversation prerequisite group: complete canonical
      goal creation/term/state history, reservation and release history, goal
      proposal record/resolution history, conversation turn open/settle history,
      and conversation proposal record/resolution history. Each row retains the
      exact canonical body as canonical JSON alongside query identities, exact
      Decimal text where present, all four provenance fields, source order, and
      an exact event-family composite foreign key. Four revision-local history
      reads are bounded to 200 rows, use stable
      `(occurred_at, source_sequence)` keyset cursors, and have filtered and
      unfiltered order-compatible indexes proven with representative-cardinality
      `EXPLAIN QUERY PLAN` checks. Frozen tests cover Unicode, nested proposal and
      stake metadata, backfilled dates, arbitrary suffix batching versus rebuild,
      restart, exact high-scale Decimal text, and family-substitution tampering.
      The later current-goal-state item below now derives the non-calendar
      current state; current Plans and Conversation desktop reads are now
      converted in 4E–4F.
- [x] Materialize bounded current goal state and exact review-decision matching.
      The current-goal read first selects at most 200 eligible goal identities
      in canonical goal-id order, without `OFFSET`, then folds only those
      histories in source order. Canonical-core parity covers pre-create events,
      duplicate creates, multiple goals and limits, tied timestamps, arbitrary
      suffix partitions, restart, releases beyond reservations, and exact
      Decimal lexical representation. Question declines match their latest
      eligible amount/count snapshot and finding set-asides match their latest
      eligible complete nested stake object; repeated and conflicting records,
      missing identities, empty stakes, whitespace, negative Decimal text, and
      nested objects are covered. Captured production SQL is planner-checked
      against the current-goal and review-subject indexes. These are backend
      contracts only; no desktop/public surface changed.
- [x] Materialize the date-dependent supported open-question, obligation,
      finding, and current-period result contracts before direct Overview or
      Review conversion. These are deterministic projections rather than event
      families; the implementation does not invent canonical question or
      obligation events. Exact SQL parity now covers the four supported
      question families, findings, rhythms/obligations, balance availability
      and exclusions, and calendar-dependent goal/current-period presentation.
      This packet alone did not cover held/reconciliation, corroboration,
      expectation, or interview question candidates; later 4M packets below
      completed those contracts.
- [x] Compose deterministic findings and the complete current-period result
      directly from one immutable SQL revision. Finding identities, ranking,
      nested stakes, exact latest set-aside matching, rhythm and fee evidence,
      account/balance exclusions, reservations, calendar goal contributions,
      provenance, grades, caveats, completeness, and stable ordering match the
      canonical contracts in the frozen parity corpus. The same revision now
      composes the transfer, merchant, nature, and rhythm question families,
      including exact latest decline matching and stable tail ranking. Temporal
      scope matches the canonical queue: `as_of` grounds cadence while transfer,
      merchant, nature, and their decisions inspect the complete current
      revision. Review decisions are fetched in fixed batches of at most 200
      subjects with exact latest-source precedence rather than one statement per
      result. Transfer links refuse above 10,000 rows; a suggestion refuses above
      1,000,000 encoded bytes, 200 nested candidates, or 512 UTF-8 bytes per key.
      Production-limit tests exercise 10,001 links, 10,001 reservation events,
      payloads above one MiB, 201 candidates, and UTF-8 keys above 512 bytes
      without monkeypatching. A 205-question production corpus proves the
      public 200-row window's exact deterministic ranking and five-row tail,
      while 201 generated findings prove typed refusal with no partial result.
      Refused current-period parity also covers an issuer-origin depository
      account without a usable currency, an all-ineligible account set, and an
      empty revision, including exact exclusions and
      `no_eligible_liquid_balance`. A complete multi-account/multi-currency corpus
      compares questions, findings, and every nested current-period field across
      arbitrary suffix partitions, restart, and held-reader isolation. More than
      400 question declines and finding set-asides prove exact nested snapshots,
      fixed `ceil(n/200)` batching, and the captured SQL for both event families
      proves indexed `ROW_NUMBER`/`IN` plans without a temporary B-tree across
      the 200-subject boundary. Every
      input/result window is explicit and refuses overflow; no query uses
      `OFFSET`, raw storage, the canonical event store, or `LedgerProjection`.
      Held-document identity/reconciliation, corroboration, expectation,
      interview candidates, and desktop conversion are completed in the
      subsequent 4M and 4A–4H packets.
- [x] **4M-a — held documents and account identity prerequisites.** Fold current
      statement and brokerage-activity holds, explicit activity resolutions,
      posted-document closure, repeated holds, corrections and source-order
      supersession directly from one immutable SQL revision. Balance-family and
      brokerage identity holds now preserve exact Decimal facts, masked labels,
      findings, held running balances, candidate order, stable question ids,
      slots/refs, evidence stakes, deterministic wording/ranking, and exact
      latest-decline behavior. Account identity is reconstructed from bounded
      account/opening/observation/alias histories, including per-document
      rulings, full-number strengthening, conflicting candidates, scoped versus
      legacy learned aliases, duplicate display labels with current balances,
      Unicode and missing fields. Reads accept an explicit `as_of`, use no raw
      store, canonical event store, `OFFSET`, or `LedgerProjection`, refuse
      oversized histories rather than truncate: account and alias histories
      refuse at 10,001 rows, holder names at 20,001, and opening observations,
      closing observations, postings, and positions each at 10,001. The
      duplicate-label value read remains exactly four bounded SQL statements;
      their expanded production SQL uses order-compatible indexes without a
      temporary B-tree. Reads retain arbitrary suffix,
      restart, and held-reader revision isolation. Canonical parity covers gap
      bridge suppression, zero/one/many identity candidates, brokerage activity
      resolution/reopening, posted closure, backfills, and future boundaries.
      This packet was backend composition only; the later 4M question and
      desktop/bridge packets completed the remaining fence.
- [x] **4M-b — corroboration and expectation question families.** Materialize
      captured document classifications and their account attribution, plus
      exact attribute ruling history, without copying raw documents or
      canonical event bodies. Compose asserted-account corroboration stakes,
      source-order/grade ruling precedence, unreliable mixed-payment warnings,
      global document satisfaction, retirement-flow and investment-account
      evidence, and stale-account cadence asks directly from one immutable SQL
      revision. The read accepts explicit `jurisdiction` and `as_of`: the
      jurisdiction filters the versioned registry, while `as_of` grounds the
      cadence horizon exactly as the canonical queue does; the remaining
      families inspect the complete current revision. Question ids, exact
      Decimal stakes, counts, slots, refs, wording, stable ranking, tail totals,
      and latest exact decline matching retain canonical parity. Attribute
      answers first filter by value-time and then apply the latest canonical
      source event per account/key, so a later-recorded backfill wins. Document
      attribution is event/role constrained and retains all four provenance
      fields. Eligible attribute history is cap+1 probed through an index and
      refuses before selection or reduction (including a literal 10,001-row
      single-key case). Production traces hold corroboration, expectation,
      attribute, and account-document reads to 2/4/2/1 SQL statements; every
      traced statement is bounded, its query plan uses the intended indexes,
      and none requires a temporary B-tree. Decision lookup remains fixed-batch indexed SQL, no
      query uses `OFFSET`, and reads never construct `LedgerProjection` or
      access `EventStore`/`RawStore`. Parity covers jurisdiction changes,
      boundary dates, corrections/backfills, contradictory ruling grades,
      duplicate documents/rules, Unicode, multi-account/currency evidence,
      suffix partitions, restart, and held-reader isolation. This is backend
      composition only; interview candidates and desktop/bridge conversion
      are covered by the subsequent interview and desktop packets.
- [x] **4M-c — interview candidates and complete question lookup semantics.**
      Derive schema selection, account-known and document-known answers,
      current attribute answers, conditional essentials, declined-but-live
      questions, link choices, and account-opening branches directly from one
      immutable SQL revision. The complete held, identity, reconciliation,
      transfer, merchant, nature, rhythm, corroboration, expectation, and
      interview queue now shares canonical stake ordering, exact Decimal tail,
      total, and fixed-batch latest-decision semantics. Revision-local
      `find_question` and `pending_questions` use the same candidates and exact
      decline snapshot as `open_questions`; they never replay the event log,
      construct `LedgerProjection`, inspect raw storage, use `OFFSET`, or accept
      unbounded question identities, nested transfer payloads, decision bodies,
      account/document histories, attribute histories, movements, or results.
      Parity covers jurisdiction-dependent schema availability, ledger and
      document answers, source-late attribute answers, Unicode identities,
      declines, and absent question lookup alongside the existing arbitrary
      suffix, restart, and held-reader combined-family corpus. The backend
      dependency inventory is reconciled above; direct destination conversion
      is tracked under 4A–4H.
      The shared question snapshot now applies its 4,000-item cap to unique
      candidate identities before answer or decline filtering: ordinary
      composed ids, every schema-pack id, and every synthetic `opens:` id all
      consume the same envelope. `open_questions`, `find_question`, and
      `pending_questions` use that one composition path and refuse the whole
      read with `RhythmReadError` when it is exceeded. Production-schema
      regressions prove that 571 property accounts (3,997 schema ids plus 571
      synthetic opens ids) refuse in all three APIs, while the exact 4,000-id
      boundary succeeds deterministically.
- [x] Compose merchant rhythm hypotheses and qualified outgoing obligations
      directly from one immutable SQL revision. The read folds account identity,
      frozen resolver profiles, merchant aliases/catalog grades, transfer links,
      and rhythm rulings at the requested `as_of` boundary; future corrections
      cannot leak into an earlier answer. Cadence measurement retains canonical
      amount decomposition, direction, sparse/prior, irregular, confirmation,
      currency-refusal, Decimal, weakest-grade, provenance, and stable-id
      semantics. The candidate window is an indexed ten years and refuses if
      older transaction evidence exists. Inputs also refuse beyond 10,000 account-history
      rows, 4,000 frozen resolver profiles, 10,000 joined transaction/posting rows,
      4,000 merchant-history
      rows, 10,000 transfer decisions, 2,000 rhythm rulings, 500 merchant/direction
      groups, or 2,000 movements in one group. Public rhythm results are capped
      at 200; obligation composition independently considers up to 500 rhythms
      before filtering qualified outgoing obligations and applying its own
      200-row result cap. Every cap refuses instead of silently truncating.
      Production reads use named indexed
      SQL without `OFFSET`, and parity covers date boundaries, sparse and
      irregular cadence, confirmations, multi-currency relationships, live
      transfer exclusion, account-identity evolution, frozen-profile rebuilds,
      alias merges/conflicts and equal-grade ties, backfilled/tied transaction
      order, missing provenance, irregular suffix batches, restart, revision
      isolation, and every independent overflow refusal. This is backend
      composition only. The supported question/finding/current-period
      compositions are complete. Desktop destination conversion is completed
      under 4A–4H.
- [x] Compose the calendar-dependent current goal contract directly from one
      immutable SQL revision. The named read preserves exact Decimal values,
      contribution-calendar boundaries, status/required/projected/deviation
      semantics, reservation history, account availability and exclusion
      reasons, balance grades, provenance, and stable goal/account ordering.
      Account-wide reservations are folded in indexed SQL across every eligible
      current goal before the 1–200 goal output limit is applied, so a goal on a
      later output page cannot overstate a shared account's availability. Money
      remains exact Decimal text through registered SQL callbacks and only one
      final row per reserved account crosses into Python. Selected goal history
      is capped at 2,000 events per goal, account input at 200 identities, and
      transaction replay at 10,000 postings per account. The all-goal fold first
      probes `R` with a 10,001-row envelope and refuses before recursion when
      more than 10,000 eligible reservation/release events exist. Current-period
      composition likewise probes 201 eligible goal identities and refuses
      instead of omitting the 201st goal or its contribution. Each refuses rather
      than silently truncating. The query work is O(R log R + G·H + A·P), with
      R at most 10,000 eligible reservation changes, G at most 200 selected goals, H at
      most 2,000 events per selected goal, A at most 200 accounts, and P at most
      10,000 postings per account. Frozen parity covers dates
      before, equal to, between, and after goal events, mixed currencies,
      issuer and non-depository exclusions, reconciled balances, reservation
      and release history, cross-page shared-account reservations, backfilled
      releases, multiple limits, restart/revision isolation, explicit overflow
      refusal, tamper refusal, traced statement bounds, and actual plans for
      every production query. Those goal semantics now feed the parity-proven
      complete current-period result. The destination inventories and desktop
      conversions are completed under the verified 4M and 4A–4H packets.
- Overview/Accounts and current Activity, Spending, Documents, Review, Plans,
  Conversation, and Trust read their complete contracts from immutable SQL
  revisions. Historical Overview and Activity use separate value-time SQL
  adapters over one held revision. Account-ledger pagination now uses its SQL
  verified keyset route; Jobs (4H) is verified and closed.
  Global 4M is independently verified and closed for the converted desktop
  SQL fence. Phase 5 packaged/manual, Phase 6, Witness, and release gates remain
  open.

## Phase 5 — Progressive desktop startup and containment

- [x] Remove Overview and Accounts from the all-surfaces startup barrier.
      Documents, Review/Conversation, Trust, Activity, and Plans no longer
      enter routine startup. Each loads on destination or when an explicitly
      selected account/evidence flow needs it.
- [x] After canonical authentication, return session state before read-store catch-up,
      load the active destination first, then navigation summaries, and lazily
      load remaining destinations on selection or bounded idle work.
- [ ] Give every surface independent loading, ready, partial, needs-input,
      unavailable, failed, and retry states.
      The five destination-local reads now retain distinct absent, ready,
      partial, needs-input, unavailable, and failed outcomes in session state.
      A late reply from an obsolete navigation cannot replace any of those
      five destinations; each has an announced, keyboard-operable failed-read
      retry. The paired priority Overview/Accounts read retains partial and
      needs-input issues; a same-source degraded retry keeps the last complete
      revision visibly stale, while a replacement source clears prior-vault
      secondary data and selections. Automated tests cover both priority
      destinations' Retry focus/live announcements and 320–620px reachability,
      plus an unresolved old-vault retry after replacement.
      The action aggregate uses a current authenticated priority revision,
      six secondary reads, and a matching current priority confirmation;
      a mismatch retains the prior complete picture and does not replay the
      write. Terminal-job refresh reuses its priority start. Manual webview
      and screen-reader evidence, packaged containment, and the remaining
      all-surface outcome matrix still block this checkbox.
- [x] Keep already rendered Overview/Accounts visible when another read fails or times
      out; never replace a failed initial read with an apparently empty vault.
- [ ] Give each process generation one failure coordinator. On timeout, fail
      every queued/in-flight call from that generation, terminate and reap it
      exactly once, and require coherent vault-level recovery.
- [ ] Ensure late replies never attach to a replacement generation or erase its
      exact active-vault identity.
- [x] Add bounded SQL interruption where safe; isolate unavoidable CPU work in
      a terminable worker rather than the sole vault-owner process.
- [ ] Add keyboard, focus, screen-reader, loading, partial, failure, retry,
      stale-revision, cancellation, and responsive-layout tests.

**Gate:** A deliberately blocked low-priority surface cannot delay the active
screen or navigation, and timeout cleanup leaves no runaway process.

### Slice 5 startup/rebuild containment

- `bridge.open_vault` authenticates EventStore, RawStore, and an available
  ReadStore generation, then starts catch-up/rebuild in a child process. The
  passphrase crosses a private stdin pipe once and is absent from argv,
  environment, files, diagnostics, and logs. The resident worker clears the
  parsed passphrase after deriving its store keys and accepts synchronize
  retries over that pipe until close. The parent retains neither passphrase
  nor rebuild keys.
- A prior authenticated generation remains readable as `stale`; a missing or
  unusable generation reports `rebuilding`. The desktop polls only the bounded
  priority bundle while rebuilding and publishes the new immutable generation
  when an attempt succeeds. Failure retains stale data when one exists and
  otherwise becomes degraded; the same resident worker can retry without a
  reopen or canonical write replay.
- Close, source replacement, and the worker deadline terminate and reap the
  worker. Termination escalates to kill and completes within two seconds.
  Projection work never occupies the foreground JSON-lines request loop, so
  Jobs and other requests remain answerable.
- A modern warm EventStore open authenticates its header, head, and terminal
  record without scanning the prefix. This proves semantic freshness, not a
  full physical audit. Canonical reads, append decisions, rebuild/full
  snapshot, export/verification paths still validate the complete chain and
  sealed events before use; legacy or damaged-tail recovery stays on the full
  validation path.
- Focused gates live in `product/tests/test_startup_rebuild_worker.py` and the
  startup no-read gate in
  `desktop/src/surface/load-private-snapshot.test.ts`. Structural 1k, 10k,
  and 50k event-log gates in `product/tests/test_startup_scale.py` prove that
  warm and missing/corrupt read-model open never enter the committed-event
  iterator and complete each synthetic open within three seconds on the local
  test host. The structural no-replay gate is primary; this local elapsed
  budget is not the Witness's real-vault first-content measurement.
- An opt-in local packaged coordinator test runs the bundled macOS sidecar
  against a synthetic vault whose authenticated scrypt header takes more than
  100 ms to open on the test host. A 100 ms native test deadline interrupts
  that CPU-bound credential read, settles a queued peer, reports the open
  outcome as unknown without replay, reaps the old process, and serves a
  handshake from generation two. Run it with
  `ORIONVIVA_LOCAL_PACKAGED_APP=/absolute/path/OrionViva.app
  ../.venv/bin/pytest -q tests/test_packaged_local_sqlcipher.py
  -k packaged_cpu_bound` from `product`. This is an actual packaged sidecar
  and native coordinator test, but it is not the still-open permanent CPU-loop
  surface-read or GUI/webview containment gate.

## Phase 6 — System proof and documentation

Cross-platform signing, notarization, and clean-host compatibility are owner-
deferred release work. They remain outside this non-release integration pass
and must be proved before any release-ready claim.

Local synthetic fault/scale packet: `product/tests/test_read_store.py` covers
pre/during/after row application, metadata advance, and publication. Its
version-change rebuild matrix also proves that every injected interruption
retains the old held revision and unchanged canonical source, followed by one
successful rebuild and an equal no-op. `product/tests/test_store.py` covers
pre/during/post canonical event commit, while
`product/tests/test_startup_rebuild_worker.py` covers reply identity and late
publication refusal. The 1k/10k/50k valid encrypted-log startup gate above
adds explicit local elapsed budgets. These interpreter-level synthetic tests
do not close packaged, real-vault, or cross-platform Phase 6 gates.
The integrated event-batch matrix resolves pre-head, partial batch, and
post-head lost acknowledgements by reopening the authenticated canonical head
before SQL synchronization. It accepts only the legal whole-batch prefixes,
never repeats the write, and checks the old held revision until catch-up.
The reply matrix refuses a false success after SQL metadata interruption,
then catches up without replay and rejects the late old-token reply.

Internal macOS arm64 packaged packet: a fresh PyInstaller sidecar was staged
in an isolated temporary build tree, then Tauri built `OrionViva.app` there
with `--bundles app`. The staged and bundled sidecar SHA-256 matched. Run
`ORIONVIVA_LOCAL_PACKAGED_APP=/absolute/path/OrionViva.app
../.venv/bin/pytest -q tests/test_packaged_local_sqlcipher.py` from `product`
to exercise the bundled process against only a temporary synthetic vault:
create, forced process-group crash, wrong-key refusal, canonical append,
reopen/catch-up, nonempty SQLCipher `cipher_version`, integrity check, stock
SQLite refusal, and recursive plaintext/header scan of the app and disposable
read-model files. This local build used CPython 3.13 and an ad-hoc macOS
signature; it is not the pinned CPython 3.12 release-wheel provenance or a
signed/notarized/clean-host release artifact. The release wheel hashes remain
in `product/requirements-sqlcipher-wheels.txt`; license metadata for the local
`sqlcipher3==0.6.2` distribution declares MIT, but full release SBOM and ABI
validation remain open. The bundled PyInstaller archive contains the arm64
`sqlcipher3/_sqlite3.cpython-313-darwin.so`, `libcrypto.3.dylib`, and
`libssl.3.dylib`; the app and sidecar are arm64 Mach-O. Ad-hoc
`codesign --verify --deep --strict` does not pass, so signing remains a release
blocker rather than a local-packaged success claim.
An optional `ORIONVIVA_LOCAL_PACKAGED_DMG` path extends the same recursive
sentinel/header probe to a locally built installer. The isolated Tauri DMG
attempt on this host did not produce an installer: `hdiutil create` returned
`Device not configured`. This is an environment packaging gap, not a passed
installer scan or evidence of a product-side SQLCipher failure.

- [ ] Run complete product, desktop, Rust, packaging, architecture, style,
      privacy, denylist, export/restore, tamper, migration, and performance
      suites.
- [ ] Run packaged validation on every release target.
- [ ] Sign and notarize supported desktop artifacts and validate them on clean
      hosts for every release target.
- [ ] Record SQLCipher/binding licenses and provenance, wheel hashes and source
      locations, generated SBOM entries, bundled native-library inventory, and
      ABI/load checks for every release artifact. A license, provenance, SBOM,
      or ABI failure blocks packaging just like an encryption failure.
- [ ] Recursively scan the unpacked application, sidecar, resource directories,
      read-store generation directory (database, journals, temporary and stale
      revisions), crash/diagnostic output, and produced installers for unique
      synthetic plaintext sentinels and `SQLite format 3`; scan filenames and
      file contents without traversing a private vault or user-wide directory.
- [ ] Run the complete independent working-tree acceptance pack; all declared
      cases must execute with revision evidence and `decision: ready`.
      The latest working-tree run executed 11 declared cases: four passed and seven
      lacked complete evidence. Five browser cases passed independently when
      ChromeDriver 152 matched Chrome 152 (the full run had used driver 139).
      The catalog lane needs its evaluator-owned post-job priority refresh and
      current-revision readiness check before the unchanged Activity oracle;
      it currently exits after a valid `current read store is not caught up`
      response. Compatibility still lacks owner-deferred signed/clean-host
      release evidence. Rerun all cases on one final worktree identity; none
      of these diagnostics is a full-pack pass.
- [ ] Run Interface Designer review of every startup/loading/failure state.
- [ ] Run a scrubbed Witness test on the real vault: first useful surface under
      3 seconds, priority surfaces settled under 15 seconds, no raw startup
      activity, warm open without replay, and CPU returning to idle.
- [x] Delete the read store and prove automatic reconstruction from canonical
      events without altered answers or canonical bytes.
- [ ] Prove an older compatible build can ignore the disposable database.
- [ ] Add the encrypted-read-store ADR and update storage/crypto, architecture,
      UI delivery, security/threat model, installation, usage, implementation
      status, and reading guide documents.
- [ ] Find and correct every claim made false by this cycle, especially claims
      that routine views replay directly from the log or that projection
      maintenance is already incremental.
- [ ] Perform Steward comment, TODO, docs, generated-artifact, credential,
      private-data, and tool-footer checks; draft the commit message and stop.
- [ ] Obtain owner authorization before committing.
- [ ] From a clean committed revision, rerun complete acceptance and require
      `pass`, `decision: ready`, every declared case executed, and the exact
      committed revision recorded.

## Explicitly outside this cycle

- Moving canonical events into SQLite.
- Changing event meanings, financial arithmetic, grades, or user rulings.
- Changing raw-blob format or placing raw content in the database.
- Cloud sync, multi-device conflict resolution, server databases, telemetry,
  external anchoring, portable key recovery, or new product capabilities.
- Deleting the legacy projector before every non-desktop consumer and recovery
  tool has an approved replacement.
