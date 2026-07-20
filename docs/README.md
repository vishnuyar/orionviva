# OrionViva — Working Documents

This folder is the project's thinking made visible: discovery research, options considered, decisions made, and questions still open. Consistent with building in the open, these are honest work-in-progress documents — they record what we don't know as prominently as what we do.

## How to navigate

Filenames are unnumbered by design; **[reading-guide.md](reading-guide.md)** is the single place document order lives — start there. **[decisions/](decisions/README.md)** holds the ADRs: short records of what was decided, why, what alternatives were considered, and what would reverse it.

Every doc carries a status header: **Draft** (actively being shaped), **Stable** (settled unless new evidence arrives), **Living** (kept current continuously), or **Superseded** (kept for the record, pointer to replacement). Research docs end with open questions and sources.

## Ground rules (restated so they're never out of sight)

Every extracted figure carries a source and a confidence signal. Arithmetic is deterministic, never done "in the model's head." Local-first from commit one. No per-institution parsers. No chain, token, or on-chain anything for authenticity. When unsure, apply the decision heuristic: does it increase trust in an answer, keep data and keys with the user, stay honest about what it knows, and is it the simplest thing that works?

The full cross-cutting checklist — including the internationalization invariants — lives in **[design-invariants.md](design-invariants.md)**; every new design doc and ADR states which invariants it touches.
