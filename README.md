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

## Start here

The supported product interface is the Tauri desktop application backed by a
packaged Python sidecar.

- [Installation guide](./docs/installation-guide.md) — install a release or
  build a local desktop application on macOS, Windows, or Linux.
- [Usage guide](./docs/usage-guide.md) — create or open a vault, add statements,
  inspect evidence, use Review and Ask Viva, and understand privacy boundaries.
- [Desktop contributor guide](./desktop/README.md) — frontend and native-host
  commands and architecture.
- [Product package guide](./product/README.md) — Python engine setup, tests, and
  runtime paths.
- [Documentation reading guide](./docs/reading-guide.md) — the design and rule
  system behind the implementation.

## Security model

Private financial data is encrypted inside a local vault. After a successful
private-vault open, the desktop application protects that vault's directory and
vaultphrase in macOS Keychain or Windows Credential Manager and opens it by
default on that device. The vault file itself does not contain the vaultphrase;
moving it to another device still requires the vaultphrase.

Model access is optional. When configured, only data required for an explicit
document-reading or question request crosses the model boundary, and OrionViva
records the observed outbound activity. Read
[SECURITY.md](./SECURITY.md) and the
[storage and cryptography design](./docs/local-first-storage-and-crypto.md)
before changing either boundary.

## Repository layout

- `desktop/` — React/Vite interface and Tauri native host.
- `product/` — encrypted vault, ledger, ingestion, surfaces, and desktop
  sidecar.
- `core/` — shared claims, verification, and model adapters.
- `merchant/` — merchant normalization and shared catalog knowledge.
- `bench/` — synthetic and evaluation harnesses.
- `docs/` — current rules, architecture, design decisions, and historical
  records.

## Maintainer quick start

Use Python 3.11 or newer, Node.js with npm, Rust, and the platform prerequisites
for Tauri 2. From the repository root:

```sh
python3 -m venv .venv
.venv/bin/pip install -e './core[dev]' -e './merchant[dev]' -e './product[dev,reader]' -e './bench[dev]' -r product/requirements-sidecar-build.txt
cd desktop
npm ci
npm test
npm run build
npm run check:architecture
npm run check:styles
```

Build the complete native application, including the packaged sidecar, with:

```sh
cd desktop
npm run desktop:build
```

Run the Python suites from the repository root with:

```sh
PYTHONPATH=.:product:core:merchant:bench .venv/bin/python -m pytest product core merchant bench -q
```

See the [installation guide](./docs/installation-guide.md) for platform
packages and the [release guide](./RELEASING.md) for versioning, signing,
notarization, and publication.

## Contributing

Early and moving fast — open an issue to discuss before large changes. Given the
subject matter, security- and privacy-minded review is especially welcome.
Please report vulnerabilities through [SECURITY.md](./SECURITY.md), not a
public issue containing sensitive details.

Before submitting a change, keep generated installers, sidecars, credentials,
private vaults, source documents, and local diagnostics out of Git. Changes to
surface contracts, security promises, or user-facing copy should update the
corresponding tests and current-state documents in the same commit.

## License

[MIT](./LICENSE). Maximally permissive on purpose: the promise here is that you
never have to take anything on faith, and that's strongest when nothing stands
between you and reading, running, or reusing the code.
