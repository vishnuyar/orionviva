# ADR-020 — Sealed authoritative history around SQL application storage

Status: experimental storage boundary accepted at bounded Director Checkpoint 2
after a test-only recovery fixture and oracle repair. Fresh independent execution
passed 222 controls with zero failures, errors or skips in 470.945980 seconds
complete path. The earlier 188-pass/34-failure result remains historical failed
evidence. No production activation or migration follows.

## Context

Existing vault promises include append-only authenticated history, rebuildable
state and keyless live structural chain checks. Detached SQL exports cannot
substitute for the live chain. The owner chose indexed admission AND complete
verification for every canonical read/write, without trust/deadline waivers.
The prototype already supplies SQL financial rules; duplicating them or using
legacy projections to answer SQL finances would defeat the purpose.

## Decision

Add `viva-sql-application-v1`, an outer owner of immutable sealed SQL-operation
history, authenticated publication intents, terminal boundaries and original
custody around the original prototype-v3/schema-3 SQL representation. Later
direct-engine families introduce prototype-v5/schema-5 and inner engine-v3; the
original storage evidence does not qualify those later versions. SQL remains the
actual indexed financial engine. Its exact sealed audit records govern checked
tables; mutable tables never win a disagreement. A distinct authenticated child
header prevents prototype-open bypass. Legacy contracts/defaults stay unchanged.

Genesis binds metadata/software schema. SQL commits advance SQL revision once;
custody/noop/abort publications preserve it. Hash links enable keyless structural
checks; domain-separated authenticators/encryption provide keyed semantics.
Two independent header KDF initializations and whole-operation cost are measured.

Bounded root ownership precedes instance/SQL ownership. Extraction runs outside
root/SQL phases. Initial intent precedes possible SQL journal writes; durable
exact preparation precedes commit; publication and cleanup precede acknowledgement.
Recovery distinguishes READY equality from the unique prepared NEXT extension.
OLD rollback becomes an abort preserving proposed bytes, never a repeated
financial action. Partial/invalid/unknown evidence refuses and remains preserved.
No cross-file atomicity, scan-and-adopt or physical-digest rebase is claimed.

Trusted schema descriptors come from installed DDL on a separate native
in-memory database. Target verification is not cached. Custody includes held and
unsupported originals independently of money. Backup/restore copy closed
encrypted membership under root/SQL ownership, freshly verify with the explicit
transient credential, and publish into a nonexistent destination natively.

## Limits

Keyless structure does not authenticate values/pages/originals. A keyed live
handle retains its observed prefix. Trusted expected boundaries remain distinct
from stored MACs. External anchoring is still unimplemented; a fresh unanchored
process cannot detect a coherent older whole-root replacement.

No factory switch, adoption, all-family settlement, migration, legacy ZIP adapter,
browser/native delivery or performance result follows. The current bounded native
journal-finalization controls pass after the test-only repair; earlier base and
qualification failures remain retained. Windows safe directory ownership is not implemented and refuses
before effects. Process death and injected faults do not prove arbitrary power loss.

The meaningful original regression is retained. The first candidate focused run was 176 passed and two failed out of 178.
Its code and failed evidence remain archived. The earlier repair executed 222
controls: 188 passed and 34 failed, including all original 178 passing. The new
44 controls yielded 10 passes and 34 failures. That exhausted admission remains
historical; the test-only repair used a separate bounded admission. An unchanged
RED reproduced the fixture/oracle failure before maintenance assignment. The
corrected 44-control candidate passed, then fresh independent execution passed all
222 controls. The Director accepted that bounded storage result; no further run
is authorized by this evidence. Original
financial/manual/source/native acceptance stays
open. See [the owning contract](../sql-authority-live-history.md). Historical
foundation passes and failed composition work do not qualify this candidate.


## Explicit OLD transaction journal maintenance

A four-arm synthetic native experiment established present-to-absent DELETE
journal finalization for authenticated PREPARED-OLD transactions by assigning the
captured current `main.user_version` to itself once. Its boundary preserved the
header integer, logical export, control, history and pending bytes. Physical page
counters/ciphertext may change; this is no physical database identity guarantee.

The narrow application-local repair permits that operation only during explicit
owned recovery of INITIAL-OLD or exact PREPARED-OLD transaction intent. It checks
actual owner/root/thread/process, one durable pending operation, current published
and SQL prior boundaries, authenticated proposed record bindings and exact
membership. The existing ordinary-open journal refusal remains. Ineligible stages,
unknown/corrupt evidence and unsupported native settings refuse without maintenance.

Root ownership encloses an independent writer and complete checks before and after
the single same-current signed-32-bit header assignment. After native COMMIT,
immediate journal absence and complete held-snapshot/logical/header/pending equality
must precede unchanged abort publication. Failures retain pending evidence and
rollback only an owned still-active SQL transaction. No manual deletion, alternate
header value, `schema_version`, table-update fallback, mode change or acceptance of
proposed financial work is introduced. Journal-absent recovery remains unchanged.

The original 178 case IDs/assertions and original interrupted child remain intact.
The 44 added case IDs/order and original 524-line source prefix remain unchanged.
The test-only residual-journal fixture/oracle repair preserves production
initialization and all production code. Current execution establishes genuine
INITIAL/PREPARED maintenance entry, signed/nonzero same-current native header
assignment and commit, scoped invalid-context/fault refusals, and four native
maintenance-crash milestones. Strict financial, header, history, original,
pending-byte, exactly-one-abort, idempotence and keyless assertions remain.
The failed 44-control addition remains historical; its failures did not themselves
qualify these boundaries.

The independent terminal review and Director ruling are retained under
`runs/sample-completion/continuation-20261105/storage-test-repair-v1/`.
This post-test documentation-only reconciliation is not a new execution or a
whole-source identity claim. Bounded storage acceptance does not qualify
production app integration, other platforms, all document families, the 794 replay,
installed/native delivery or performance.
