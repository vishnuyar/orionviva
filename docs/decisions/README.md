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
