# Backend Capability Gaps For UI Parity

**State:** design-only
**Rules:** none

## Rules

This document is a handoff list of capabilities the desktop interface is waiting on. It states no behaviour the code can be held to; every item in it is either a gap (under *Open*) or a shaping principle for the work that closes one (under *Why*). Rules arrive with the capabilities themselves, in the documents that specify them.

## Why

The desktop interface already renders a synthetic preview of several surfaces. The gaps that remain are the places where it cannot honestly become "live" without backend support, and the point of naming them is not more interface — it is giving the interface a real, stable contract to consume.

Synthetic state is not backend parity. A preview that simulates a state locally proves the rendering and proves nothing about the product, so treating a preview as evidence of a working surface would bypass the gates that exist to catch exactly that.

Five properties shape everything the backend owes the surface. **Versioned read models**, so the shell can evolve without breaking older builds and an old client meets a contract it understands rather than a shape it must guess at. **Allowlisted actions**, so a surface that needs user input or mutation reaches a named, enumerated set rather than an open door into the product. **Progress and terminal states** for long-running document and sync work, because a job with no reportable state can only be rendered as a spinner or a lie. And **cited evidence, provenance and refusal states** carried through the conversation and review surfaces, because an answer stripped of its citation on the way to a screen is the one failure this whole product exists to prevent. The fifth is **explicit lifecycle and recovery states for native install and update flows**, which the backend owes the shell as squarely as it owes it a read model.

The source of truth for what is currently built is [User Interface Implementation Status](user-interface-implementation-status.md); this document is the complement, listing what is not.

## Open

Capability gaps, by the slice that needs them:

- **Installable shell and demo vault** — packaged runtime validation, installer and update metadata, signed installer publication, native lifecycle and recovery validation. The shell renders preview interface today and still needs a proven native host path to be a distributable desktop app.
- **Document journey** — a document ingest job registry, rescan, held and parked state transitions, progress events, outbound posting and accounting, error and retry states. The interface can show capture and document states and cannot drive real document processing or post document-derived results back into the product.
- **Financial picture** — broader live overview and account read models, formatting parity, evidence and account-coverage details from live data. Account spotlights display today from synthetic figures and local fixtures rather than a complete backend read model.
- **Review and learning** — live review queue reads, answer, decline, proposal and confirm actions, post-action refresh, action outcome state. The interface can show review actions and cannot execute them against the backend or refresh from a live queue.
- **Ask Viva** — a conversation session API, cited turn retrieval, refusal states, live answer generation, prompt and history read models. A synthetic conversation drawer opens today; nothing can ask the backend or render returned cited turns and refusals from a real session.
- **Activity and organization** — live activity and transaction read models, filter endpoints, category and tag mutation endpoints, transfer linking, totals and drilldown data. The groundwork exists; organization features need real transaction semantics, totals and mutation support.
- **Trust and maintenance** — trust and maintenance surface models, outbound history, build identity metadata, update recovery state, watched-folder capture, diagnostic export. There is no trustworthy live maintenance surface until these operational and integrity-related capabilities exist.

The practical priority order: document ingest and job progress first, then live review queue actions, then the conversation session and its citations, then live activity and organization read models, then the trust, maintenance, update and export operational views, and packaged desktop lifecycle validation last.
