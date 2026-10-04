# ADR-017 — Apply accounting interpretations and learn from corrections

**Status:** Accepted by the owner, 2026-10-04; implementation verification in progress.

## Decision

Replace proactive classification review with automatic, reversible accounting interpretation. Valid transactions contribute to working balance-sheet and profit-and-loss reports immediately. Models determine meaning from a bounded categorical envelope; deterministic code owns all amounts and report arithmetic. Human explanations apply without a redundant confirmation and establish scoped learning. Source documents, account kinds, supported links and explicit allocations remain stronger than guesses.

Original events remain immutable. Separate accounting control and restoration events retain correction history and allow undo. Classification evidence cannot strengthen measurement evidence. Unknown debt components or missing balances remain visible without generating classification questions.

## Consequences

M1 permits automatically inferred asset/liability treatment with provenance and reversibility. X3 reserves confirmation for irreversible operations and unresolved targets, not reversible interpretation. Previous question-first documents remain historical descriptions of their requested-editor substrate; the active behavior is specified in [automatic-accounting.md](../automatic-accounting.md).

No private transaction descriptors, amounts or account identifiers enter the automatic classification envelope. Only shipped public taxonomy labels and bounded sanitized examples may be transmitted. Current extraction adapters lack search tools; broader public research is an explicitly unsupported capability rather than a hidden assumption.

The cost is more responsibility for inference attribution, scoped matching, correction receipts, source-link navigation and exact canonical/SQL parity. Uncertainty becomes visible coverage and provisional contribution rather than user homework.
