# OrionViva Desktop Preview

This is the first UI slice: a minimal, offline shell driven by a clearly
synthetic demo vault. It intentionally has no bridge or sidecar connection
yet. Values are shaped like surface-contract responses so the later bridge can
replace the fixture without changing the shell vocabulary.

## Development

```sh
pnpm install
pnpm dev
```

## Verification

```sh
pnpm test
pnpm run build
```

The next slice can introduce `viva.surface` and a typed bridge behind the
existing feature boundaries.
