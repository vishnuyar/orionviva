# SQL application live history

This experimental storage implementation executed its bounded controls and
remains stopped after the final repair yielded 188 passes and 34 failures. It
has not been accepted. The actual application factory still uses the event-log vault.
There is no migration, default switch, new document-family settlement or current
794-document performance result in this change.

`SQLAuthority.create(root, passphrase, verification="complete", application=True)`
creates a new `viva-sql-application-v1` root. The corresponding `open` accepts
only that format. The default prototype API remains separate. An authenticated
child header prevents bypass by opening the child SQL directory as a prototype.
The returned facade has no public database or key getter.

The outer root contains `application.json`, permanent `application.lock`,
`history/`, `terminal.json`, `pending/`, and `sql/`. The child contains its own
authenticated `authority.json`, encrypted `authority.db`, and encrypted
`originals/`. Independent header salts mean **two KDF initializations** during
create/open. `lifecycle_timings` records both KDF costs and the whole operation;
previous single-KDF/indexed timings do not apply. Passphrases are transient
caller inputs. Python memory zeroization is not promised.

Immutable numbered publications are authoritative sealed SQL operation history.
SQL remains the actual indexed financial settlement/query engine; its checked
representation must agree exactly with those operations. There is no second
settlement engine or legacy Ledger fallback. Each SQL commit's exact existing
sealed audit record and commitment is retained without resealing. Genesis binds
metadata and the trusted software schema. Custody binds originals separately
from financial acceptance. A zero-change transaction records a noop; an
interrupted rollback records an abort retaining original proposed bytes when
they existed, without counting those bytes as accepted financial operations.

Every answer performs complete keyed checks within its actual SQL snapshot.
Each actual writer checks inside `BEGIN IMMEDIATE`. Exact software schema,
history equality and the entire custody set are checked as well. Unexpected
triggers, views, indexes, substituted tables or sources refuse. The expected
schema is constructed from installed DDL on a separate native in-memory
connection, never learned from the target. Only the software descriptor can be
retained across operations; target verification results cannot.

Root ownership precedes instance/SQL ownership. Document exclusion precedes
root ownership and survives the reader callback, which holds neither root nor
SQL transaction. Independent handles/processes coordinate bounded native and
process-local locks. Busy is explicit. Root/lock replacement, inherited
ownership and forged/copied/expired engine bindings refuse. Closing active work
refuses; closing idle resources does not clear pending evidence.

## Keyless and keyed claims

`ApplicationSQLAuthority.verify_live_chain(root, expected_terminal=...)` requires
no passphrase or SQL connection. It checks the actual immutable sealed event
chain, publication ordering, SQL revision continuity and terminal structure.
Success explicitly says `authenticated=False`. Opaque MAC bytes do not
authenticate themselves. SQL pages, balances, plaintext contents and originals
require complete keyed checking.

A trusted final terminal has exactly `root_id`, `sequence`, `head`,
`sql_revision`, and `sql_head`. It comes from a separately trusted boundary,
not a stored MAC. A live handle retains its observed prefix and permits only
verified forward extension. External anchoring remains unimplemented: a fresh
process without a trusted boundary cannot detect a coherent older whole-root
replacement. Stored MACs are not external anchors.

## Interruption and recovery

Authenticated initial intent precedes writer transactions/persistent capture.
Exact preparation precedes SQL commit. Exact immutable publication, terminal
replacement and cleanup precede acknowledgement. Native SQLite atomicity does
not make arbitrary history/source files an atomic group.

Ordinary open and keyless checks report `RecoveryRequired` on unfinished work.
Explicit keyed `recover(root, passphrase, expected_prefix=...)` may finish a
verified prepared NEXT SQL extension, finish a zero-change preparation, or
publish an OLD rollback as an abort. It never repeats extraction or settlement.
An exact accepted record can finish terminal/cleanup once. An empty pending
directory is removable only for the latest authenticated accepted operation
after full SQL/schema/custody verification. Early creation cannot invent genesis.

Partial/invalid original or abort drafts, torn intents/metadata, unexplained
terminal drafts, unknown members, inconsistent lineage and missing required
prepared bytes are diagnosed refusals. Evidence is preserved; these do not earn
automatic-recovery credit. No scan-and-adopt or physical DB digest rebasing is
introduced.

Immutable publication uses native no-replace operations and directory durability;
even an existing empty directory cannot be overwritten. Only mutable protocol
heads use application-local descriptor-relative `os.replace`, exact installed
identity/bytes checks and fsync on the same continuously held parent descriptor.
No descriptor-path namespace or shared legacy-helper change is used. The base candidate has native controls, with the two journal-retention
recovery failures retained below; the final repair failed qualification and remains held. Windows currently refuses before root effects because equivalent
safe directory ownership is not implemented. Unsupported primitives/filesystems
or durability refuse. Process termination and injected flush failures remain
distinct controls; neither proves arbitrary hardware power loss.

## Encrypted backup boundary

`backup(destination, passphrase=..., expected_terminal=...)` holds source root
and SQL snapshot, verifies the supplied credential before staging, copies the
closed encrypted membership, creates an independent lock, freshly verifies
staging and publishes without replacement. `restore(backup_directory,
destination, passphrase, ...)` uses the same verified-copy boundary. Existing
destinations refuse. Incomplete private staging remains on failure. No generic
SQL backup/serialization encryption behavior is assumed. Genuine curated-source
ownership is propagated explicitly when necessary.

These are encrypted-directory APIs, not an installed archive format, legacy
export adapter or migration. Providers/actions/import progress/sessions/source
page witnesses, other document families, hosted/manual/native acceptance and the
fresh same-source 794 comparison remain separate work.

## Evidence state

The original regression passed accepted synthetic complete SQL, exact
balance/postings/original, keyed audit and detached structure before failing at
missing `application=True`. Its node and assertions remain preserved. The first storage candidate executed 178 focused cases: 176 passed and two
actual process recovery cases failed when native SQL journaling remained after
an interrupted transaction. That failed packet and the original cases remain
unchanged. A separate four-arm native experiment established journal removal
for authenticated PREPARED-OLD cases using a single assignment of the actual
current `main.user_version`, with complete logical equality and retained
pending evidence. It does not establish INITIAL-OLD, nonzero headers, maintenance
crashes, other platforms or production application acceptance. The final repair
executed 222 controls: 188 passed and 34 failed, with all original 178 passing.
The added 44 controls yielded 10 passes and 34 failures; many stopped before
maintenance-helper entry. That failed result and the no-retry hold remain.
Historical foundation 202-focused/425-package/
7,421-full passes are predecessor evidence, not a current storage-candidate or
original-acceptance pass.


## Native journal finalization during explicit OLD recovery

A retained native DELETE journal still refuses ordinary open and READY. Explicit
recovery may finalize it only for a genuine currently owned transaction with the
exact published and SQL OLD boundary. The intent is reauthenticated from private
regular bytes. INITIAL requires only its initial intent; PREPARED requires exactly
the intent and its authenticated, digest-bound proposed SQL commit. Foreign,
unknown, missing, corrupt, already published, capture, creation and abort-prepared
contexts do not acquire this maintenance authority.

The root remains exclusively owned while the engine takes an independent
`BEGIN IMMEDIATE`. Complete verification and exact logical export/control/history
and pending-byte equality surround one assignment of the actual captured signed
32-bit `main.user_version` to itself. Separate header equality is mandatory because
the logical SQL export does not contain that integer. Native DELETE/FULL/HMAC/normal
settings are checked and never changed. There is no alternate value, table-update
fallback, `schema_version` assignment or journal unlink. Native page counters and
encrypted physical bytes may change; financial values, SQL revision/head and the
captured header integer may not.

COMMIT must be followed immediately by journal absence and complete held-snapshot
verification with the same pending evidence. Only then does existing abort
publication run, retaining the proposed bytes as history rather than accepting
another financial action. An error refuses with pending evidence retained;
rollback applies only to a transaction actually owned and still active. A crash
before COMMIT retains the authenticated OLD context for a later explicit recovery.
A crash after COMMIT but before abort publication retains the original pending
bytes and uses the existing journal-absent route. Partial work is never READY.
The native phase/header/crash controls and labeled faults were included in the
failed final repair. Their intended maintenance boundaries remain unqualified;
no arbitrary hardware-power-loss or new platform qualification follows.
