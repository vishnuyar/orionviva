# Backend Capability Gaps For UI Parity

**Purpose:** This document lists the backend capabilities still needed to bring
the desktop UI up to date with the backend. It is written as a handoff note for
the backend team: what the UI is waiting on, why it matters, and what the
backend should expose.

**Source of truth:** [User Interface Implementation Status](user-interface-implementation-status.md)

## Summary

The desktop UI already has a synthetic preview for several surfaces, but the
remaining gaps are the places where the UI cannot honestly become “live” without
backend support.

## Capability Gaps By Slice

| Slice | Backend capability missing | Why the UI needs it |
|---|---|---|
| Slice 1: installable shell and demo vault | Packaged runtime validation, installer/update metadata, signed installer publication, native lifecycle/recovery validation | The shell can render preview UI today, but it still needs a proven native host path to be a distributable desktop app. |
| Slice 2: document journey | Document ingest job registry, rescan, held/parked state transitions, progress events, outbound posting/accounting, error/retry states | The current UI can show capture and document states, but it still cannot drive real document processing or post document-derived results back into the product. |
| Slice 3: financial picture | Broader live overview/account read models, formatting parity, evidence/account coverage details from live data | The UI can display account spotlights, but it still depends on synthetic figures and local fixtures rather than a complete backend read model. |
| Slice 4: review and learning | Live review queue reads, answer/decline/proposal/confirm actions, post-action refresh, action outcome state | The UI can show review actions, but it cannot yet execute those actions against the backend or refresh from a live queue. |
| Slice 5: ask Viva | Conversation session API, cited turn retrieval, refusal states, live answer generation, prompt/history read models | The UI can open a synthetic conversation drawer, but it still cannot ask the backend and render returned cited turns or refusals from a real conversation session. |
| Slice 6: activity and organization | Live activity/transaction read models, filter endpoints, category/tag mutation endpoints, transfer linking, totals and drilldown data | The UI groundwork exists, but organization features need real transaction semantics, totals, and mutation support from the backend. |
| Slice 7: trust and maintenance | Trust/maintenance surface models, outbound history, build identity metadata, update recovery state, watched-folder capture, diagnostic export | The UI has no trustworthy live maintenance surface until the backend exposes these operational and integrity-related capabilities. |

## What The Backend Team Should Implement

1. Expose stable, versioned read models for each surface above.
2. Expose allowlisted actions for the surfaces that need user input or mutation.
3. Add progress and terminal-state reporting for long-running document and sync
   work.
4. Include cited evidence, provenance, and refusal states in the conversation
   and review surfaces.
5. Provide explicit lifecycle and recovery states for native install/update
   flows.
6. Keep these capabilities versioned so the desktop shell can evolve without
   breaking older builds.

## Practical Priority Order

1. Document ingest and job progress.
2. Live review queue actions.
3. Viva conversation session/citations.
4. Live activity and organization read models.
5. Trust/maintenance/update/export operational views.
6. Packaged desktop lifecycle validation.

## Notes

- The current desktop preview can simulate some of these states locally, but
  synthetic state is not backend parity.
- The goal of the missing capabilities is not “more UI”; it is giving the UI a
  real, stable contract to consume.

