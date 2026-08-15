# Architecture Decision Records

Short records of decisions: context, alternatives considered, what was decided, what would reverse it. One-way doors (the discovery map) all have ADRs before product code exists.

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

**Amended 2026-08-15 — four requirements are recorded as unmet.** ADR-003 (the ingest path stores no model request), ADR-004 (no chain head has ever been anchored), ADR-005 (the dual-wrap custody scheme is not built, so today a lost passphrase is a lost vault) and ADR-007 (identity and recognition are one content-derived string, with no fingerprint field) each carry a dated note saying what the code does and that the decision is unmet. None of the four is withdrawn and no original line was removed; a row in the table above states a decision, never that it is built.
