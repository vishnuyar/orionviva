# merchantcore

The merchant knowledge base for OrionViva — a peer package to `vivacore`.

`vivacore` is the trust/verification core; `merchantcore` is the merchant
knowledge base: deterministic, versioned merchant normalization; the
multi-attribute `MerchantRecord` (category today; website, socials, reviews
later); a batched model **enrichment** engine (through `vivacore.models`); and a
content-addressed merchant→category **commons**.

It holds and shares **only impersonal knowledge** about merchants — never amounts,
dates, accounts, or personal descriptors. That boundary (design invariant T9) is
why the product can consume it safely and why its catalog is unencrypted-safe.

Dependency direction: `vivacore` ← `merchantcore` ← the product.

See `docs/merchantcore-package.md` for the design.
