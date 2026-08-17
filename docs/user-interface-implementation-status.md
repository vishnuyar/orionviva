# OrionViva User Interface Implementation Status

**Status:** Current branch snapshot  
**Checked:** 2026-08-17  
**Branch:** `codex-ui-surface-refinement`  
**Guiding document:** [User Interface Architecture and Delivery](user-interface-architecture-and-delivery.md)

This document is the implementation ledger for the architecture document. The
architecture document remains the design authority and intentionally retains
its proposed-state language. This status document records what is actually
implemented on the current branch and what is still synthetic, partial, or
planned.

## Summary

| Architecture slice | Status | What is true now |
|---|---|---|
| Slice 0: surface contract and parity machinery | **Complete** | Versioned Python surface contracts, capability registry, deterministic fixture gate, capability coverage, import boundaries, impact gate, and CI wiring are implemented and tested. |
| Slice 1: installable shell and demo vault | **Partial** | The React shell detects the scaffolded Tauri host, presents a directory/passphrase open-vault form, and reads live surfaces with fixture fallback. Reproducible target-sidecar packaging and Tauri build wiring now exist; installer artifacts, signing/update metadata, native picker, and packaged lifecycle validation remain. |
| Slice 2: document journey | **Partial** | Document list/detail states and lifecycle presentation exist, and live document reads can now reach the desktop through the bridge. Drag/drop, processing jobs, restart recovery, and outbound records are not wired. |
| Slice 3: financial picture | **Partial** | The desktop can map live overview/account reads from an opened vault when a host transport is injected. Full financial surface coverage, formatting parity, and host packaging remain incomplete. |
| Slice 4: review and learning | **Partial** | The desktop can receive a live review queue from an opened vault when a host transport is injected. Queue answer/decline/confirm actions and post-action refreshes are not connected. |
| Slice 5: ask Viva | **Not started in the UI** | Backend ask/speak capabilities exist, but there is no desktop conversation surface or live turn/read integration. |
| Slice 6: activity and organization | **Partial** | Cross-document evidence and transaction-oriented surface groundwork exist. Filters, corrections, categories, tags, transfer actions, and live totals are not complete. |
| Slice 7: trust and maintenance | **Not started** | Capability dispositions classify maintenance and trust destinations, but there is no trust/maintenance UI, outbound history, or build identity view. |
| Slice 8: distribution and capture comfort | **Not started** | No signed installer, watched folder, Windows packaging, update recovery, or diagnostic export flow is implemented. |

**Current UI/backend boundary:** the desktop currently consumes synthetic
fixtures and local read-model adapters through an explicit bridge-client
seam. `product/viva/desktop_bridge` now provides a versioned JSON-lines
transport boundary with handshake validation, an allowlisted dispatcher, an
explicit `bridge.open_vault` lifecycle, and opened-vault reads for overview,
documents, and review. The React desktop detects the host transport through
`window.orionVivaBridge` and retains a deterministic fixture fallback. The
TypeScript client defines the host request contract, and the Tauri bootstrap
injects it through `bridge_request`. Target-specific sidecar packaging now has
a pinned PyInstaller spec, target naming, and CI wiring; installer validation
and signing remain before this is a distributable desktop app.

## Implemented Evidence

### Surface contract and parity

- `product/viva/surface/protocol.py` and `models.py` define the versioned
  protocol and common figure, panel, action, and contract models.
- `product/viva/surface/capabilities.py` inventories current backend command
  capabilities and assigns each a surface destination or an explicit
  non-surface disposition.
- `product/viva/surface/fixtures/surface-v1.json` is a deterministic,
  checked-in fixture artifact.
- `scripts/check_surface_contract.py` provides deterministic contract drift
  checking.
- `scripts/check_surface_impact.py` provides the conservative backend-impact
  declaration gate.
- Capability coverage and import-boundary tests are present, and
  `.github/workflows/quality.yml` runs the surface gates.

The implementation was committed in `9cc8d7a`:
`Add surface capability parity gates`.

### Desktop presentation work

The current desktop includes:

- a React/Vite application shell;
- an explicit desktop bridge-client seam with a fixture-backed default;
- a transport-only Python bridge scaffold with version handshake, JSON-lines
  framing, allowlisted dispatch, and a live capability-registry read;
- an injected vault-surface provider contract with typed read results and
  started/completed/failed progress events;
- a concrete opened-vault provider for overview, document, and review reads;
- a runnable JSON-lines sidecar with explicit vault-open lifecycle;
- a typed desktop host transport client with live-read mapping, an exposed
  vault-open call, and fixture fallback;
- a guarded user-facing vault directory/passphrase form that invokes the
  typed open-vault call when a host transport is present;
- a Tauri host scaffold with development sidecar fallback and target-specific
  PyInstaller packaging automation;
- synthetic four-year statement data;
- overview and account-oriented read models;
- explicit document lifecycle states;
- document and review detail presentation;
- cross-document evidence navigation;
- surface graph regression coverage;
- focused desktop tests and a production build.

These are valuable presentation slices. The opened-vault bridge is a real
backend adapter when invoked through a host transport, while the browser/Vite
path remains fixture-backed. Native packaging is automated, but installer and
signed-release validation are still outstanding.

### Backend capabilities available for future wiring

The capability registry currently classifies surface-relevant backend areas
including review questions, Viva conversation, document ingestion, document
rescan, and maintenance activity. The registry also deliberately keeps
developer-only or deferred operations such as rebuild, reingest, reset,
diagnostics, merchant enrichment, grammar induction, and evaluation out of
ordinary UI navigation.

## Remaining Work To Reach Backend/UI Parity

1. Compile the Tauri host and validate the packaged shell, offline startup,
   demo-vault reset, and real-vault create/unlock lifecycle.
2. Add installer manifests/signing and validate target-specific distribution.
3. Wire document ingest, rescan, progress, held/parked states, and outbound
   accounting into the document journey.
4. Wire review queue reads and answer, decline, proposal, and confirmation
   actions with post-action refreshes.
5. Add the shared overview, evidence drawer, activity, and transaction detail
   components against live surface read models.
6. Add the conversation surface for `viva.ask` and `viva.speak`, including
   cited turns, refusal states, and protection against document-driven writes.
7. Implement trust and maintenance views, then update recovery,
   watched-folder capture, and diagnostic export.

## Vault-Backed Read And Job Progress Audit

The current bridge checkpoint does not yet meet the architecture acceptance
criteria for live surface integration:

| Acceptance criterion | Current state |
|---|---|
| Read models are produced from an explicitly opened vault | Implemented at the Python sidecar boundary; `bridge.open_vault` creates the provider and enables overview, documents, and review reads. The packaged native host lifecycle is not yet validated here. |
| Surface operations are typed and allowlisted | Implemented at the transport boundary; the typed React client can send `bridge.open_vault` and `viva.surface.read` through an injected host transport, and the React open-vault form invokes `bridge.open_vault` when that host exists. |
| Long-running work reports honest progress and terminal states | Partial; reads emit started/completed/failed events, and the host now exposes bounded restart/shutdown recovery, but there is no job registry or cancellation. |
| The desktop consumes the live bridge while retaining deterministic fixtures | Implemented as a React/Tauri host seam; the unlock form calls `window.orionVivaBridge` when Tauri internals are present and fixtures remain the browser fallback. A target sidecar has been built and smoke-tested locally; the full packaged Tauri application remains unbuilt here. |
| Failures remain bounded at the bridge boundary | Implemented for malformed requests and handler exceptions; vault lifecycle failures still need a typed contract. |

Slice 1 therefore remains **Partial** because Tauri compilation, installer
creation, signing, and packaged lifecycle validation are not complete. The
next implementation slice is the packaged host plus job registry, cancellation,
and restart recovery.

## Native Host Acceptance Audit

The repository now contains a native desktop host scaffold, but it is not yet
an installed or signed desktop application:

| Native-host requirement | Current state |
|---|---|
| Tauri application and configuration | Scaffolded; `desktop/src-tauri` declares the Tauri app, capabilities, sidecar name, and `bridge_request` command. No Rust/Tauri build has been run in this workspace. |
| Sidecar process launch and lifecycle ownership | Implemented in the Rust host; it owns one JSON-lines child, detects stale exits, reaps it on shutdown, exposes explicit restart/shutdown commands, and cleans up on app exit. Packaged Tauri runtime validation remains outstanding. |
| Frontend bridge injection | Implemented for a Tauri runtime; `desktop/src/tauri-host.ts` injects `window.orionVivaBridge` through `bridge_request`, with browser fixture fallback. It is not yet proven in a packaged app. |
| JSON-lines request/response adapter | Implemented across the Python sidecar and Rust host process-I/O path, with the TypeScript contract on top. Runtime/native build validation remains outstanding. |
| Packaged sidecar resources and distribution metadata | Sidecar packaging implemented; `scripts/build_desktop_sidecar.py` stages target-named executables from a pinned PyInstaller spec, and CI builds before `tauri build`. Installer manifest, signing configuration, update endpoint, and update recovery flow remain. |
| Native vault directory selection | Not present; the React form accepts a directory string, but the host provides no native picker or platform-path validation. |
| Offline startup and failure recovery | Partial; browser fallback, bounded bridge errors, stale-child cleanup, explicit restart, graceful shutdown, and lifecycle contract tests exist. Packaged offline startup, automatic user-facing recovery, and diagnostic export remain unverified or absent. |

The exact remaining gap is the final packaged desktop lifecycle: Rust/Tauri
compilation, installer creation and signing, update metadata, native directory
selection, and startup/shutdown/recovery validation. The React, Rust adapter,
Python bridge, and target-sidecar build boundaries now exist, but they do not
yet constitute a signed distributable desktop application.

## Verification Snapshot

- Last recorded Python surface suite: **40 passed** under the supported Python
  3.12 runtime.
- Last recorded surface contract check: **passed**.
- Last recorded surface impact check: **passed**.
- Desktop bridge, provider-read, progress-event, native-host, packaging, and
  lifecycle suite: **47 passed** in the isolated Python 3.13 environment.
- Sidecar packaging: **passed** in an isolated Python 3.13 environment after
  installing the pinned and product runtime dependencies; the frozen binary
  launched and returned a bounded invalid-request frame.
- Desktop focused tests on the current tree: **37 passed**.
- Desktop production build on the current tree: **passed**.
- JSON metadata validation, Python syntax compilation, packaging contract
  inspection, and `git diff --check`: **passed**.
- Rust/Tauri compilation and installer generation remain unverified because
  `cargo` is not installed in this workspace.
- Branch has not been pushed.

## Update Rule

Update this document whenever a UI slice is committed. A slice may be marked
**Complete** only when its architecture acceptance criteria pass against the
live boundary it claims to use. Synthetic fixtures can prove presentation
states, but cannot by themselves prove backend/UI parity.
