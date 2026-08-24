# Backend Capability Gaps For UI Parity

**State:** partial
**Rules:** none

This is the current complement to
[User Interface Implementation Status](user-interface-implementation-status.md).
The capability registry and operation table own what exists; this document only
records product capabilities that are still absent or intentionally incomplete.
The pre-desktop handoff is preserved in
[the archive](archived/backend-capability-gaps-before-live-desktop.md).

## Source of truth

- `product/viva/surface/capabilities.py` owns capability disposition,
  destination, contract, actions, availability, and trust effects.
- `product/viva/surface/operations.py` owns every sidecar operation and the read
  contracts those operations serve.
- `desktop/src/bridge/client.ts` is the typed desktop consumer.
- [User Interface Implementation Status](user-interface-implementation-status.md)
  records checked gaps in the running interface.

Counts and operation names are deliberately not copied here. Tests compare the
registry, operation table, status tables, and desktop client so those facts have
one executable source rather than another prose snapshot.

## Capabilities still absent

- **Account aggregation.** A person can open a local or sample vault and upload
  documents, but no bank-connection or aggregation capability is registered.
  Manual, encrypted capture remains the only acquisition path.
- **Category and tag editing in the desktop.** The ledger supports both
  concepts, but `activity.movements` is read-only and advertises no write action.
  A future surface must keep the one-category partition separate from the
  many-tag overlay.
- **Audio voice.** `conversation.viva` provides one text conversation session
  and a voice-ready reply shape, but no microphone, speech recognition, or audio
  playback implementation exists. Voice must remain a modality on the same
  cited turn rather than a second answer path.
- **Per-term source regions for composed figures.** A composed figure can cite
  its supporting records, but not every term can point to a page region of its
  own. The interface must continue to state that limitation rather than invent a
  precise location.
- **External trust anchoring and issuer signatures.** The local event chain is
  tamper-evident. Nothing publishes its head to an independent witness and
  source institutions do not sign imported documents. Trust exposes these
  absences explicitly.
- **Automatic updates.** The application reports its build and explains that no
  update channel exists. Releases are downloaded and installed manually.
- **Durable background-job recovery.** Jobs and cancellation are live while the
  sidecar runs; an interrupted job does not survive process restart.

## Intentionally deferred

- unattended folder, email, and phone capture;
- merchant enrichment across the reviewed privacy boundary;
- autonomous financial action and counterparty disclosure;
- a separate Settings destination (configuration currently lives in Trust).

Each deferred item needs its own design decision before it becomes a registered
surface capability. A roadmap checkbox alone does not authorize it.

## Closed by the live desktop bridge

The current desktop reaches account overview, activity, document upload and
rescan, job state and cancellation, review answer, proposal confirmation and decline, Ask Viva,
settings proposal and confirmation, outbound history, update lifecycle, vault
export and restore, maintenance, diagnostics, sample-vault opening, capability
discovery, and build identity. These no longer belong in a backend gap list.

## Open

- The first six absent capabilities above need briefs before implementation.
- When a capability closes, remove it here only after the registry, operation,
  desktop consumer, and tests agree.
