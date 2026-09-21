# OrionViva Desktop

This is the supported OrionViva presentation layer: a React/Vite interface in a
Tauri shell, connected to the Python engine through a packaged JSON-lines
sidecar. Synthetic fixtures still cover presentation states, while private and
sample vault modes exercise the live bridge.

## What is connected

The desktop can open a private vault or the persistent sample vault; read the
overview, accounts, activity, documents, jobs, review queue, Trust record, and
build identity; upload and rescan documents; cancel live jobs; answer or decline
review questions; ask Viva; configure model and presentation settings through a
confirmation step; export or restore a vault; run maintenance; and write a
privacy-filtered diagnostic.

Known limitations are tracked in
[UI implementation status](../docs/user-interface-implementation-status.md)
and [backend capability gaps](../docs/backend-capability-gaps.md).
End-user setup and workflows live in the
[installation guide](../docs/installation-guide.md) and
[usage guide](../docs/usage-guide.md).

## Development

Prerequisites: Node.js/npm, Python 3.11 or newer, Rust, and the
[platform requirements for Tauri 2](https://v2.tauri.app/start/prerequisites/).
Before building the native application, install the Python packages and
sidecar-build requirements as described in the
[installation guide](../docs/installation-guide.md). From this directory:

```sh
npm ci
npm run dev
```

`npm run dev` runs the web interface. To build the actual desktop application
with its sidecar:

```sh
npm run desktop:build
```

## Verification

```sh
npm test
npm run build
npm run check:architecture
npm run check:styles
npm run release:validate
```

`npm run build` proves the web bundle. `npm run desktop:build` additionally
builds the Python sidecar and native installer. A signed release has its own
workflow and prerequisites; see [RELEASING.md](../RELEASING.md).

## Architecture boundaries

- Feature components consume typed surface results; they do not call the
  sidecar directly.
- `src/bridge/client.ts` is the desktop operation client.
- `src/surface/` adapts bridge payloads into interface vocabulary.
- `src-tauri/` owns the native host, file-picker boundary, bundled sidecar, and
  release metadata.
- The capability registry and operation allowlist are owned by the Python
  package, not duplicated as desktop truth.

## Local browser mode

The native **Open in browser** control serves the production-built
`loopback.html` and shared assets from the application's bundle on 127.0.0.1.
`src-tauri/src/browser.rs` owns authenticated session/page admission, revocation,
vault-generation checks and native file/folder dialogs. Both interfaces share
one supervised Python process. Only one interface controls it at a time.
`src/bridge/browser-transport.ts` implements the installed-host transport;
`loopback-transport.ts` remains the independent evaluator's development adapter.

Build the frontend before a native development launch. `npm run build` now emits
both entry points. `npm run desktop:build` packages the interface and engine.

`npm run test:browser-host` builds the production interface and exercises it in
headless Chrome through the actual Rust HTTP handlers and a disposable Python
engine. It requires the sibling evaluator's WebdriverIO dependencies, a local
Chrome driver, and this checkout's Python environment. It creates only synthetic
vaults/files, disables model configuration and protected credential access, and
uses test-only file-dialog selections. Its native test is explicitly opt-in in
`cargo test`; run this command to execute it. It does not prove an OS dialog,
a signed installation, or supported behavior on another platform/browser.
