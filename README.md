<div align="center">

# OrionViva

**A personal financial agent you can actually trust.**

*Orion — the stars you steer by. ViVa — you.*

[Website](https://orionviva.com) · [The theory](https://orionviva.com/writing.html) · [Build log](https://orionviva.com/writing.html#build-log)

</div>

---

## What this is

OrionViva is an open-source personal financial agent. It reads your financial
life — statements, accounts, documents — holds one clean picture of it, and
answers your questions in plain language, honestly, proving what it stood on.

It is **local-first** (the vault and keys stay on your machine), **ad-free**
(you're the customer, not the product), and **built in the open** (so "we don't
sell your data" is something you can verify, not a promise you have to take on
faith). If you explicitly configure a model provider, document or question data
needed for that model call can leave the machine; the product records those
calls and exposes the outbound history.

## Why

Your financial life is scattered across a dozen institutions, and none of them
holds the whole picture. Getting a straight answer to a simple question takes an
hour of tab-switching and mental math — so most people never ask. OrionViva
exists to replace that background hum of not-knowing with quiet confidence.

The longer arc: once an agent holds verified, tamper-evident records about you,
it can *vouch* for you — to a lender, a landlord, anyone — only when you allow
it, revealing only what's needed. A trust agent you own, instead of a credit
bureau that profiled you without asking. The reasoning behind this is laid out
in [the theory series](https://orionviva.com/writing.html).

## Principles

- **Trust is the product.** Every decision serves the moment you believe an answer without re-checking it.
- **Honest about uncertainty.** Confident when sure; transparent the moment there's real doubt. Never bluff a number.
- **Your data, your keys.** Local-first. A breach should be a bad day, not a ruin.
- **You own the trust.** The local ledger is encrypted, append-only, and
  tamper-evident. Independent anchoring and issuer-signed source documents are
  longer-term goals, not claims this build makes.

## Status

🚧 **Early.** Being built in public, first user is the author. Watch the
[build log](https://orionviva.com/writing.html#build-log) and this repo's commits.
See [ROADMAP.md](./ROADMAP.md).

## Run it

The supported product interface is the Tauri desktop application backed by a
packaged Python sidecar. Start with the
[desktop setup](./desktop/README.md); backend contributors should also read the
[product package guide](./product/README.md) and the
[documentation reading guide](./docs/reading-guide.md).

## Contributing

Early and moving fast — open an issue to discuss before large changes. Given the
subject matter, security- and privacy-minded review is especially welcome.
Please report vulnerabilities through [SECURITY.md](./SECURITY.md), not a
public issue containing sensitive details.

## License

[MIT](./LICENSE). Maximally permissive on purpose: the promise here is that you
never have to take anything on faith, and that's strongest when nothing stands
between you and reading, running, or reusing the code.

