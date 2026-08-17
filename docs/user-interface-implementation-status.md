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
| Slice 1: installable shell and demo vault | **Partial** | A desktop React/Vite shell and synthetic demo corpus exist. There is no Tauri installer, packaged Python sidecar, typed IPC bridge, or real-vault unlock flow. |
| Slice 2: document journey | **Partial** | Document list/detail states, lifecycle states, evidence navigation, and synthetic statement data exist. Drag/drop, processing jobs, restart recovery, and outbound records are not wired. |
| Slice 3: financial picture | **Partial** | Synthetic overview/read-model projections and evidence-aware cards exist. They are not yet served from a live `viva.surface` bridge and do not cover the full architecture fixture matrix. |
| Slice 4: review and learning | **Partial** | Review-oriented surface states and backend contract coverage exist. Queue reads and answer/decline/confirm actions are not connected to the desktop UI. |
| Slice 5: ask Viva | **Not started in the UI** | Backend ask/speak capabilities exist, but there is no desktop conversation surface or live turn/read integration. |
| Slice 6: activity and organization | **Partial** | Cross-document evidence and transaction-oriented surface groundwork exist. Filters, corrections, categories, tags, transfer actions, and live totals are not complete. |
| Slice 7: trust and maintenance | **Not started** | Capability dispositions classify maintenance and trust destinations, but there is no trust/maintenance UI, outbound history, or build identity view. |
| Slice 8: distribution and capture comfort | **Not started** | No signed installer, watched folder, Windows packaging, update recovery, or diagnostic export flow is implemented. |

**Current UI/backend boundary:** the desktop currently consumes synthetic
fixtures and local read-model adapters. It does not yet consume the Python
surface contracts through `desktop_bridge` or a typed IPC transport. Therefore
the UI can demonstrate presentation states, but it cannot yet utilize all
implemented backend actions end to end.

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
- synthetic four-year statement data;
- overview and account-oriented read models;
- explicit document lifecycle states;
- document and review detail presentation;
- cross-document evidence navigation;
- surface graph regression coverage;
- focused desktop tests and a production build.

These are valuable presentation slices, but they are fixtures and adapters,
not proof of live backend integration.

### Backend capabilities available for future wiring

The capability registry currently classifies surface-relevant backend areas
including review questions, Viva conversation, document ingestion, document
rescan, and maintenance activity. The registry also deliberately keeps
developer-only or deferred operations such as rebuild, reingest, reset,
diagnostics, merchant enrichment, grammar induction, and evaluation out of
ordinary UI navigation.

## Remaining Work To Reach Backend/UI Parity

1. Build `product/viva/desktop_bridge` with a version handshake, allowlisted
   handlers, framed request/response transport, and job progress.
2. Replace the desktop synthetic data source with a typed bridge client while
   retaining fixtures for deterministic UI tests.
3. Implement Slice 1's installable shell, sidecar packaging, offline startup,
   demo-vault reset, and real-vault create/unlock lifecycle.
4. Wire document ingest, rescan, progress, held/parked states, and outbound
   accounting into the document journey.
5. Wire review queue reads and answer, decline, proposal, and confirmation
   actions with post-action refreshes.
6. Add the shared overview, evidence drawer, activity, and transaction detail
   components against live surface read models.
7. Add the conversation surface for `viva.ask` and `viva.speak`, including
   cited turns, refusal states, and protection against document-driven writes.
8. Implement trust and maintenance views, then packaging, update recovery,
   watched-folder capture, and diagnostic export.

## Verification Snapshot

- Python surface suite: **40 passed** under the supported Python 3.12 runtime.
- Surface contract check: **passed**.
- Surface impact check: **passed**.
- Desktop focused tests: **21 passed**.
- Desktop production build: **passed**.
- Branch has not been pushed.

## Update Rule

Update this document whenever a UI slice is committed. A slice may be marked
**Complete** only when its architecture acceptance criteria pass against the
live boundary it claims to use. Synthetic fixtures can prove presentation
states, but cannot by themselves prove backend/UI parity.
