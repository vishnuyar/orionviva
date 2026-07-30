"""viva — the OrionViva product package.

The product behind the Viva persona. It holds the trust core: an encrypted,
append-only, double-entry ledger and the projections that answer questions about
it, with a cited source and a confidence grade on every figure.

Depends on ``vivacore`` for deterministic verification, model access and the
claim schema. No model sits on the answer path — v0's answers are arithmetic
over attested records.
"""

__version__ = "0.1.0"
