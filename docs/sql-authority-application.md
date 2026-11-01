# SQL authority application groundwork

Production vaults still use their existing event-log format. The experimental
SQL authority now has a selectable complete-verification profile in preparation
for an application adapter. This change does not activate that adapter, migrate
an existing vault, add document families or qualify an installed application.

`SQLAuthority.create(..., verification="complete")` and
`SQLAuthority.open(..., verification="complete")` select the stronger profile.
The default `"indexed"` profile preserves the experimental reference API; it
is not an approved production fallback. The read-only `verification` property
reports the handle's configuration. Selection is per handle, not a persisted
format upgrade. A future production factory must explicitly choose complete.
Unknown or malformed selections are refused before root creation or opening.

Complete mode retains indexed deterministic admission and adds full verification
before each canonical read decision and each actual write transaction. It checks
SQLCipher page authentication, SQLite structure and foreign keys, reconstructs
the authenticated SQL audit, compares audited tables, runs the existing identity
and transfer semantics, and authenticates retained originals. It also verifies
before create/open returns a ready handle. Retained curated admissions require
an explicitly supplied existing owner:
`SQLAuthority.open(..., verification="complete", curated_source=source)`.
Supplied ownership is checked through the existing private issuance boundary
before root/connection effects and attached before readiness verification. No
owner or source pack is inferred or loaded by `open`. Missing ownership refuses
a complete reopen with retained curated admissions. Indexed callers can still
open and explicitly attach afterward; either policy can use the new keyword.
Unsupported SQLCipher versions and
disabled page authentication are refused; an unknown PRAGMA's empty result is
not treated as evidence that the capability exists.

A read holds an actual SQLite snapshot from a real database read through full
verification and its answer. A write acquires `BEGIN IMMEDIATE` before checking
the committed preimage and retains the existing atomic audited commit. Nested
internal getters can share that one held operation under the instance lock.
Nothing is cached across decisions, handles or revisions. Explicit verification
refuses incompatible in-flight work without committing or rolling it back. The
external extraction callback runs outside financial transactions.

The canonical API covers the head, documents, originals, receipts, accounts,
transactions, postings, balance observations, source admission and occurrences,
source identity resolution, transfer inventory and actions/history, audit export
and explicit verification. Dependency query plans are diagnostics. Curated-source
attachment is configuration; closing a handle is cleanup. Detached
`check_export_structure` remains structural-only and cannot authenticate a live
authority. A supplied expected head remains a separately trusted completeness
boundary, rather than a conclusion derived from stored MACs.

Database snapshots do not make external original blobs an atomic cross-file
snapshot. Every retained source is still authenticated and checked against its
binding and size. Capture precedes canonical transactions: refusing a corrupt
preimage may leave a nonaccepted encrypted orphan original, but cannot advance
audit/head or accepted rows. Refusal does not silently repair stored state.

The owning test first demonstrated accepted synthetic statement facts and the
indexed-read versus explicit-audit-verification gap, then failed at the missing
complete selector. Independent executed verification of the corrected candidate
passed 202 focused cases and all 425 SQL-authority package cases. The full
product suite executed 7,513 cases: 7,421 passed, 92 unchanged historical skips,
and zero failures or errors. Skips remain coverage gaps. The first candidate's
failed gate, including its two control-contract failures, remains retained.

Executed controls cover all canonical readers, corrupt-preimage write refusal,
history/source corruption, actual encrypted-page and foreign-key failures,
snapshot and writer serialization, lifecycle, rollback and recovery. The
corrected ciphertext mutation specifically produced CryptoError; malformed
original JSON specifically produced JSONDecodeError before an account answer.
Fresh native connections established HMAC OFF/ON capability-gate refusal and
success; this does not claim an initialized public handle was disabled.
Response injections remain separately labelled. The genuine curated handoff
control validated the whole immutable 794-document pack through its existing
owner factory and ingested one member into a new disposable test root. Its
setup cost was included in the whole-command clock; this was not a 794-document
replay or an existing sample-vault open.

The full-product result is
`f1f44ebbfaadae2dd9664ce19f4bc8f19adbe3a1a1f8485de5c3c082ef885d47`.
These are keyed verification foundation engineering gates. They do not establish
application activation, 794-document financial correctness, keyless equivalence,
installed native lifecycle or combined-profile performance. The suites executed
on the frozen source snapshot before this documentation correction. Their
results carry forward for unchanged production, test and runtime bytes; this
edit is not a fresh suite execution or a claim of whole-source identity with
the executed snapshot.

Application provider/session integration, all remaining document families,
keyless live/export/completeness guarantees, encrypted backup and restore,
migration and genuine hosted/native acceptance remain separate gates. No
keyless or legacy history promise is waived. No earlier indexed-profile timing
is evidence for this combined profile's performance. The original import and
ready deadlines remain unchanged; the later same-source 794-document comparison
must measure correctness and complete-path cost independently.
