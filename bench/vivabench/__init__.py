"""viva-bench — the admission exam for models that want to read financial documents.

Part of OrionViva (https://orionviva.com). See docs/benchmark-harness-design.md
(what and why) and docs/benchmark-harness-architecture.md (how).

Two modules in this package are product embryos, held to a stricter standard:

- ``vivabench.verify``  — normalization, arithmetic identities, claim matching.
  The first draft of OrionViva's verification layer (ADR-010's crown jewel).
- ``vivabench.models`` — the provider-agnostic, version-pinned model access
  layer required by ADR-001 and the model trust policy.

Everything else is honest utility-grade code.
"""

__version__ = "0.1.0"
