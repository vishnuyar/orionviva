# viva — the OrionViva product

`viva` is the local financial engine behind the desktop application. It owns
the encrypted vault, append-only double-entry ledger, document pipeline,
review queue, cited answer path, maintenance agent, and the typed sidecar
boundary used by the interface.

## Trust boundaries

- Raw documents are encrypted and captured before they are interpreted.
- Events are encrypted, append-only, hash-chained, and projected into current
  views; chain integrity can be checked without decrypting event bodies.
- Verification is deterministic. A model may propose a read or interpret a
  sentence, but it does not certify arithmetic or manufacture a cited figure.
- Model access is optional. With no configured adapter and pinned model,
  documents park locally. When access is configured and confirmed, relevant
  bytes may leave through the single model boundary and the call is recorded.
- The local chain is tamper-evident, not externally anchored or issuer-signed.

The detailed decisions live in
[the documentation guide](../docs/reading-guide.md), with current enforcement
states in [rules.md](../docs/rules.md).

## Repository packages

The product imports three local packages:

- `../core` → `vivacore`, shared verification, claims, and model adapters;
- `../merchant` → `merchantcore`, impersonal merchant normalization and
  enrichment;
- this directory → `viva`, the private financial product.

For development from the repository root:

```sh
python3 -m venv .venv
.venv/bin/pip install -e './core[dev]' -e './merchant[dev]' -e './product[dev,reader]'
```

Editable installs ensure source changes are used immediately. To confirm which
copy Python imports:

```sh
.venv/bin/python -c "import viva, vivacore, merchantcore; print(viva.__file__)"
```

## Main runtime paths

- `viva/desktop_bridge/` — JSON-lines sidecar, allowlisted operations, and live
  vault provider;
- `viva/surface/` — versioned capabilities, read models, fixtures, and
  operation declarations;
- `viva/ingest/` — capture, classify, extract, reconcile, diagnose, and review;
- `viva/ledger/` — events, postings, encrypted store, identity, and projections;
- `viva/speak.py` — cited Ask Viva conversation engine;
- `viva/ask.py` — review-question workflow;
- `viva/configuration.py` — proposal-and-confirmation settings boundary;
- `viva/vault_transfer.py` — verified export and restore into a new location.

The terminal entry points remain useful for engine development, but the product
presentation layer is the desktop application in `../desktop`.

## Configuration

Copy the repository root `.env.example` values you need into a git-ignored
`.env`. `VIVA_PASSPHRASE` opens a private vault. A live reader additionally
requires an accepted adapter (`anthropic` or `openai-compatible`), a pinned
model id, and a key supplied through the named environment variable.

Do not use aliases such as `latest`: the engine rejects model names that can
change underneath a recorded read.

## Useful commands

From the repository root:

```sh
PYTHONPATH=.:product:core:merchant .venv/bin/python -m viva.desktop_bridge
PYTHONPATH=.:product:core:merchant .venv/bin/python -m viva.ask --list
PYTHONPATH=.:product:core:merchant .venv/bin/python -m viva.speak
PYTHONPATH=.:product:core:merchant .venv/bin/python -m viva.reingest
```

Run product tests with:

```sh
PYTHONPATH=.:product:core:merchant .venv/bin/python -m pytest product/tests -q
```

The built-in listen evaluation corpus is package data and can be run from an
installed wheel with `python -m viva.eval_listen`.
