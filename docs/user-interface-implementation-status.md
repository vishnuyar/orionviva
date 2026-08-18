# OrionViva User Interface Implementation Status

**State:** partial
**Rules:** VOICE-120, VOICE-121

This document is almost entirely status by its own name, and status rots. So
what was a snapshot table now lives under **Open**, as standing questions about
what is not yet true. Two things in it do not rot: the rule about when a slice
may be called complete, and the rule about what a fixture can and cannot prove.
Those are below. Everything else is a claim to re-check against the tree rather
than to repeat, and the design authority is
[user-interface-architecture-and-delivery.md](user-interface-architecture-and-delivery.md).

## Rules

### VOICE-120 — a slice is complete only against the live boundary it claims
**State:** untestable
**Code:** none found
**Test:** none

1. A slice may be marked complete only when its architecture acceptance criteria pass against the live boundary it claims to use.
2. This document is updated whenever a UI slice is committed.

### VOICE-121 — a synthetic fixture proves rendering, never parity
**State:** untestable
**Code:** product/viva/surface/fixtures/surface-v1.json
**Test:** none

1. Fixtures prove presentation states; they cannot by themselves prove backend/UI parity.
2. A packaged, signed, installable application is a separate claim from a compiling one, and neither is proven by the other.

## Why

The architecture document is the design authority and deliberately keeps its
proposed-state language. Something still has to record what is actually true on
a branch, or the proposal quietly reads as a description. That is this
document's whole job, and it is why the two rules above are the only durable
sentences in it: everything else is a measurement, and a measurement repeated
without being re-taken is a false claim wearing the authority of a checked one.

The distinction the rules protect is the one that is easiest to blur under
pressure. A React shell that renders an account spotlight from a fixture is a
real presentation slice and proves real things about states, focus and layout.
It proves nothing about whether an opened vault produces those numbers. A
sidecar that smoke-tests locally proves the process boundary works; it proves
nothing about a signed installer on a clean machine. Naming which boundary a
claim was checked against is the difference between a status document and a
press release.

The same reasoning explains why the verification snapshot and the branch name
are gone rather than updated. A count of passing tests is true for the minute it
was taken and re-derivable by running the suite; carrying it forward invites
someone to repeat it without re-running anything, which is exactly the failure
this project has a standing rule against.

## Open

The following are the outstanding questions, each of which is a candidate issue.
None of them carries a date; each is either closed by work or re-checked against
the tree.

**Boundary**

1. The desktop consumes synthetic fixtures and local read-model adapters through an explicit bridge-client seam. The opened-vault bridge is a real backend adapter when invoked through a host transport; the browser path remains fixture-backed.
2. Long-running work reports started, completed and failed events, but there is no job registry and no cancellation.
3. Vault lifecycle failures still need a typed contract; malformed requests and handler exceptions are already bounded at the bridge boundary.

**Native host and distribution**

4. Rust and Tauri compilation, installer creation, signing and update metadata, and startup/shutdown/recovery validation against the resulting artifacts, on Cargo-capable target runners.
5. Running the release workflow with real platform signing credentials, publishing installer and updater artifacts, and validating target-specific distribution and update recovery.
6. Packaged offline startup, automatic user-facing recovery, and diagnostic export.
7. Frontend bridge injection is implemented for a Tauri runtime but is not yet proven in a packaged app.

**Surfaces**

8. Document ingest, rescan, progress, held and parked states, and outbound accounting are not wired into the document journey; drag and drop and real background jobs are not wired.
9. Review queue answer, decline, proposal and confirmation actions are still synthetic, and live post-action refreshes are not connected.
10. The shared overview, evidence drawer, activity and transaction detail components do not yet run against live surface read models; full financial surface coverage and formatting parity remain.
11. The conversation surface has no live turn or read integration — cited turns, refusal states, and protection against document-driven writes all remain.
12. Activity's filters, corrections, categories, tags, transfer actions and live totals are incomplete.
13. Trust and maintenance have no UI at all: no outbound history, no build identity view. Capability dispositions classify their destinations and nothing consumes them.
14. Watched-folder capture and diagnostic export remain.

**What is implemented, and therefore what a re-check should confirm rather than
assume:** versioned Python surface contracts, the capability registry, a
deterministic fixture gate, capability coverage, import boundaries, the impact
gate and their CI wiring; a versioned JSON-lines transport with handshake
validation, an allowlisted dispatcher, an explicit vault-open lifecycle, and
opened-vault reads for overview, documents and review; a typed TypeScript host
client with fixture fallback; a Tauri host scaffold that owns one JSON-lines
child, detects stale exits, reaps it on shutdown and exposes explicit restart
and shutdown; target-specific sidecar packaging from a pinned spec with CI
staging before the desktop build; a release target manifest and
release-preparation validator; a tag and manual-dispatch release workflow across
Linux, Windows and both macOS architectures without exposing signing secrets to
pull-request jobs; and a least-privilege native folder picker with manual-entry
fallback.

The capability registry deliberately keeps developer-only and deferred
operations — rebuild, reingest, reset, diagnostics, merchant enrichment, grammar
induction and evaluation — out of ordinary navigation, and that is a decision
rather than an omission.
