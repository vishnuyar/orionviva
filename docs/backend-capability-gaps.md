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

## Capabilities still absent or incomplete

- **Account aggregation.** A person can open a local or sample vault and upload
  documents, but no bank-connection or aggregation capability is registered.
  Manual, encrypted capture remains the only acquisition path.
- **Activity correction breadth.** `activity.movements` now advertises
  movement-scoped assignment from a complete bounded existing-category
  vocabulary, complete-set tag replacement from a complete bounded existing-tag
  vocabulary, and backend-qualified transfer confirmation, rejection and
  unlinking. It does not expose nature editing, merchant-wide changes, new
  category or tag creation, or bulk correction. Inherited merchant tags also
  keep complete-set movement replacement unavailable when that action could not
  remove the effective overlay honestly.
- **Grounded obligation projection.** The stream and rhythm machinery derives
  flows, observed cadence and amount stability, first and last occurrences,
  and confirmed or measured periodicities. The recurring-spending ledger read
  reports supported arrangements already observed; it is not a forecast. No
  projection yet computes a sufficiently grounded next expected date, expected
  amount or honest range, confidence, coverage, or threshold for saying an
  obligation is *due*.
- **Pattern and finding exposure.** Deterministic stream and rhythm machinery
  exists, the diagnostic stream report consumes it, and `query_ledger` can read
  supported recurring spending. There is no registered `find_patterns` verb
  and no typed surface for recurring, subscription, fee, duplicate,
  amount-change, anomaly, or income-interruption findings, including ranking
  and evidence-staked set-aside outcomes.
- **Current-period runway.** No deterministic projection combines liquid
  balances, expected income, obligations, planned spending, goal
  contributions, and completeness into a bounded available-funds or runway
  answer with assumptions and caveats.
- **Durable conversation reads.** `conversation.viva` can answer one text turn,
  but no conversation projection or read supplies recorded turns across the
  current drawer or a later session. An earlier answer therefore has no
  durable conversation contract, and must never be reused as evidence.
- **Goal events and projections.** There is no explicit goal store or event
  vocabulary and no deterministic target, contribution, progress, or deviation
  projection. Existing proposal and ruling events do not make that substrate a
  goal model.
- **Deterministic scenarios.** No registered `project` read or scenario library
  supplies amortisation, compounding, payoff, runway, or affordability results
  with enumerated assumptions and inherited evidentiary basis.
- **General drafted-and-confirmed financial action.** Review and settings have
  bounded proposal-and-confirm flows, but there is no general action model that
  records a complete financial-action draft, re-checks its basis immediately
  before application, and records proposal, consent, and outcome separately.
  Any future execution belongs to separately gated action capabilities outside
  the agent's read-tool registry.
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
discovery, build identity, backend-declared quiet proof, and the bounded Activity
category, tag and transfer actions described above. These no longer belong in a
backend gap list.

## Open

- Each absent or incomplete capability above needs its own approved brief before
  implementation; this inventory does not register or authorize one.
- When a capability closes, remove it here only after the registry, operation,
  desktop consumer, and tests agree.
