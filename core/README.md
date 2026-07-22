# vivacore

The crown-jewel modules of [OrionViva](https://orionviva.com), shared by the
product and the benchmark (`viva-bench`) so there is exactly one copy of the
code that decides whether a number can be trusted.

- `vivacore/verify/` — **the verification layer.** Locale-aware normalization
  (ambiguity is a first-class result, never a guess), exact-`Decimal` arithmetic
  identities, and claim matching. Deterministic, ferociously tested. This is the
  code that ADR-010 says must never move into a model.
- `vivacore/models/` — **the provider-agnostic model access layer.** A
  `ModelSpec` (how to call a model) and two plain-HTTP adapters: `anthropic` and
  the universal `openai-compatible` socket (OpenAI, OpenRouter, Ollama, HF …).
  Version-pinned, no SDK dependencies.
- `vivacore/claims.py` — the **claim schema**: the typed shape a model's
  extraction is parsed into (the first draft of the product's claims layer).
- `vivacore/prompts.py` — the shared extraction prompt (versioned).

Everything here is domain-agnostic: it knows about documents, claims, and
verification, not about benchmarks or the product's ledger. Both `bench/` and
the product depend on it.

```bash
pip install -e ./core        # then bench and the product can import vivacore
pytest core/tests
```
