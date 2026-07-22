"""viva — the OrionViva product package.

The agent the user talks to is Viva; this package is the product that stands
behind that persona. It begins with the trust core — an encrypted, append-only,
double-entry ledger and the projections that answer questions about it honestly,
with a cited source and a confidence signal on every figure.

It depends on ``vivacore`` (the shared crown jewels: deterministic verification,
model access, the claim schema) but adds no model to the answer path: v0's
answers are arithmetic over attested records, not generation.
"""

__version__ = "0.1.0"
