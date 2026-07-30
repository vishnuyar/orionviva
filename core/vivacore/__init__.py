"""vivacore — the trust core, shared by the product and viva-bench.

One copy of the code that decides whether a number can be trusted:

- ``vivacore.verify``  — deterministic verification (normalize, arithmetic, match).
- ``vivacore.models``  — provider-agnostic, version-pinned model access.
- ``vivacore.claims``  — the claim schema (extraction parsed into typed claims).
- ``vivacore.prompts`` — the shared, versioned extraction prompt.

Domain-agnostic: it knows documents, claims, and verification — not benchmarks
and not the product's ledger.
"""

__version__ = "0.1.0"
