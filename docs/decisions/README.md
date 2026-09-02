# Architecture Decision Records

**State:** built
**Rules:** SPINE-10, SPINE-11

## Rules

### SPINE-10 — A one-way door gets an ADR before product code exists
**State:** unmet
**Code:** none found
**Test:** none

1. Every decision the discovery map classifies as a one-way door has an ADR written before the code that depends on it.
2. An ADR states context, alternatives considered, what was decided, and what would reverse it.
3. An ADR records reasoning at a moment, so it keeps its decision date and its status line; amendments become rules rather than a chain a reader must replay.

### SPINE-11 — A row in the index states a decision, never that it is built
**State:** unmet
**Code:** none found
**Test:** none

1. The table below says what was decided and what kind of door it is; it makes no claim that the decision ships.
2. A requirement the build has not met is recorded in the ADR that decided it, with the decision left standing and no original line removed.
3. A decision is withdrawn only by a superseding decision, never by an absence in the code.

## The index

ADR numbers are serial ids in the order decisions were made, never a reading order.

| ADR | Decision | Door |
|---|---|---|
| [001](ADR-001-hybrid-model-strategy.md) | Hybrid model strategy — cloud default, local path as a trajectory (specialization flywheel) | Two-way by design |
| [002](ADR-002-mit-license.md) | MIT license | One-way at first external contribution |
| [003](ADR-003-raw-capture-doctrine.md) | Raw capture doctrine — originals + model I/O kept forever | One-way (D1) |
| [004](ADR-004-append-only-log-and-anchoring.md) | Append-only hash-chained event log; day-one anchoring to OpenTimestamps + RFC 3161 | One-way (D2) |
| [005](ADR-005-encryption-from-commit-one.md) | Encryption at rest from commit one; versioned crypto envelope | One-way (D3) |
| [006](ADR-006-zero-exfiltration.md) | Zero exfiltration by default; diagnostics by manual export only | One-way (D4) |
| [007](ADR-007-record-identity.md) | Hybrid record identity — permanent random ID + content fingerprint | One-way (D5) |
| [008](ADR-008-public-promise-inventory.md) | Public promise inventory, v1 (8 promises) | One-way per entry (D6) |
| [009](ADR-009-dco-contributions.md) | Contributions under DCO | One-way (D7) |
| [010](ADR-010-verification-never-in-weights.md) | Verification never moves into model weights | One-way (D8) |
| [011](ADR-011-blind-host-tier.md) | Blind-host tier — encrypted hosting with client-held keys, client-side compute (Proposed, not adopted) | Two-way until publicly announced |
| [012](ADR-012-the-interview-model-boundary.md) | The interview's model boundary — two enumerated outbound flows, a whitelisted envelope, no amounts or currency | One-way in trust (the whitelist); mechanism two-way |
| [013](ADR-013-the-shape-before-the-data.md) | A sentence's shape is authored before its data, in both directions — a run holds a ledger of what it established, and an answer may say only what is in it | One-way in trust (the ordering); mechanism two-way |
| [014](ADR-014-financial-meaning-before-executable-programs.md) | The model names financial meaning and typed parameters; deterministic code authors the executable AnswerProgram | Two-way mechanism under ADR-013's one-way ordering |

## Why

A decision taken at the keyboard and never written down is a decision the next reader re-takes, usually differently and usually worse. An ADR is short on purpose: context, the alternatives that were genuinely considered, the ruling, and the condition that would reverse it. The alternatives section carries most of the value, because the cost of a choice is invisible without the thing it beat.

One-way doors get their ADR before the code, because after the code the record is a rationalization rather than a decision. Two-way doors get one only when the reasoning is worth keeping.

An ADR is a record of a moment, which is why it keeps its date while every other document here is written in the present tense. Reading it as a description of current behaviour is the mistake it is most often subject to, so each one says so at the top: the ledger of what is currently true lives in the code and in the invariants, and where the build has not met a decision, the ADR records the gap rather than quietly softening the decision.

## Open

- Four requirements are recorded as unmet by the current build: ADR-003 (the ingest path stores no model request), ADR-004 (no chain head has ever been anchored), ADR-005 (the dual-wrap custody scheme is not built, so a lost passphrase is a lost vault) and ADR-007 (identity and recognition are one content-derived string, with no fingerprint field). None of the four is withdrawn.
- ADR-011 is `Proposed` and not adopted; ADR-012's mechanism is decided and unbuilt.
- Three ADRs are owed and unwritten: the ledger/event-store engine, a formalized confidence-grade vocabulary, and the stack record.
- Nothing checks that a document's ADR references resolve, or that an ADR marked `Accepted` has a rule somewhere naming what enforces it.
