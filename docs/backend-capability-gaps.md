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

The grounded obligations and quiet-findings slice is live. It reuses the
existing rhythm evidence, advances monthly and annual dates with calendar
semantics, distinguishes exact amounts from ranges, calls an item due only
inside adequate evidence coverage, ranks deterministic findings in the
backend, and records set-aside as an evidence-staked append-only event. The
typed Overview contract and desktop consume that projection without a new
destination, notification path, urgency mechanic or Viva initiation.

Current-period control is also live on Overview. It projects qualified
recurring income and obligations over issuer-backed depository balances for
thirty days, independently by currency, and carries the range, completeness,
assumptions, exclusions, evidence and backend-authored series as one reviewed
answer. Recorded local goal reservations and future active contributions now
compose into that horizon; planned discretionary spending remains a disclosed
missing input.

## Capabilities still absent or incomplete

- **Account aggregation.** A person can open a local or sample vault and upload
  documents, but no bank-connection or aggregation capability is registered.
  Manual, encrypted capture remains the only acquisition path.
- **Activity correction breadth.** `activity.movements` now advertises
  movement-scoped assignment from a complete bounded existing-category
  vocabulary, complete-set tag replacement from a complete bounded tag
  vocabulary, explicit spending/loan/loan-repayment treatment correction, and
  backend-qualified transfer confirmation, rejection and unlinking. Treatment
  correction is direction-checked. A repayment is offered only for a receivable
  that was already open on that movement's date and whose remaining principal
  can accept the amount. A bounded replacement may introduce a new local tag.
  It does not expose merchant-wide changes, new category creation, or bulk
  correction. Inherited merchant tags also keep complete-set
  movement replacement unavailable when that action could not remove the
  effective overlay honestly.
- **Deterministic scenarios.** No registered `project` read or scenario library
  supplies amortisation, compounding, payoff, runway, or affordability results
  with enumerated assumptions and inherited evidentiary basis.
- **General drafted-and-confirmed financial action.** Conversation and settings have
  bounded proposal-and-confirm flows, but there is no general action model that
  records a complete financial-action draft, re-checks its basis immediately
  before application, and records proposal, consent, and outcome separately.
  Any future execution belongs to separately gated action capabilities outside
  the agent's read-tool registry.
- **Audio voice.** `conversation.viva` provides a durable text conversation
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
- **General background-job resumption.** Interrupted work is not automatically
  resumed. Statements now offers explicit saved-original retries for bounded
  pre-posting interruptions, after consent and a ledger check. Settling or
  partially posted documents and other job types remain non-resumable.

## Intentionally deferred

- unattended folder, email, and phone capture;
- merchant enrichment across the reviewed privacy boundary;
- autonomous financial action and counterparty disclosure;
- a separate Settings destination (configuration currently lives in Trust).

Each deferred item needs its own design decision before it becomes a registered
surface capability. A roadmap checkbox alone does not authorize it.

## Bounded interrupted-document recovery

Protocol 2.1 adds `viva.documents.recover` with `job_id` and explicit
`confirm_reading: true`. Job receipts can bind an opaque document address and a
reading/settling boundary. Statements offers an explicit saved-original read
after restart even if the selected source file has disappeared. The configured
reader and its existing consent still apply; retry may send the document and
incur charges again. No background retry occurs.

Before spending, recovery authenticates the saved blob and checks the ledger
under the same per-document process lock used by ordinary ingestion. Posted or
held documents are refused without another read; any recorded event for an
unresolved document or a settling receipt blocks retry. This deliberately does
not resume a partially posted statement/paystub or repair an interrupted ledger
tail. The original and existing entries remain available for inspection and
verified-copy/support recovery. Cancelled jobs, legacy jobs without bindings,
and receipts evicted from the bounded job registry are not retryable here.

Jobs listing remains independent of SQL rebuild and whole-ledger replay:
its offer is a candidate to check, with authoritative reconciliation performed
only when requested. A later receipt suppresses older offers for the same
original. New raw envelopes and headers are flushed before atomic publication;
job receipts are also flushed before publishing their stage.

## Closed by the live desktop bridge

The current desktop reaches account overview, activity, document upload and
rescan, job state and cancellation, durable conversation, question answering, proposal confirmation and decline,
settings proposal and confirmation, outbound history, update lifecycle, vault
export and restore, maintenance, diagnostics, sample-vault opening, capability
discovery, build identity, backend-declared quiet proof, and the bounded Activity
category, treatment, tag and transfer actions described above, plus the bounded
current-period control and save-up Plans. Plans include pure deterministic
drafts, explicit goal and reservation events, exact persisted proposals,
stale-basis checks, conversational entry, and a reviewed desktop consumer.
These no longer belong in a backend gap list.

The durable conversation is a clean-start contract. It stores turns, typed
outcomes, citations and correction proposals as ledger events; it re-fetches
current evidence on each turn and uses prior turns only as context. Earlier
technical read records are deliberately not treated as conversation history,
and no migration exists because no public vault predates this capability.

## Open

- Each absent or incomplete capability above needs its own approved brief before
  implementation; this inventory does not register or authorize one.
- When a capability closes, remove it here only after the registry, operation,
  desktop consumer, and tests agree.
