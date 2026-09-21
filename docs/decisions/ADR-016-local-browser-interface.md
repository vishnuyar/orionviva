# ADR-016 · Optional local browser interface

_This records the decision, not release certification._

**Status:** Accepted · **Date:** 2026-09-21 · **Door type:** two-way presentation choice

The owner requested “Open OrionViva in your browser” with the ability to create
and open a vault and use real files, then approved the installed-app-backed
scope and browser-default acceptance.

The installed host serves the shared built interface on the same computer and
retains its existing supervised Python engine. Native dialogs choose folders
and files; the existing pipeline encrypts originals before reading. Vault format,
financial semantics, protected credential custody and model egress policy stay
with their existing owners. A separate Node-based packaged helper was considered
and not selected because it would duplicate native lifecycle and custody work.

One interface controls the app at a time. Browser launch is an explicit action,
a one-use credential establishes a revocable page-bound session, and stale vault
requests are refused. Returning to desktop waits for admitted work; stopping
browser access revokes authorization immediately and allows admitted work to
settle before desktop control returns. A same-user instance lock prevents a
second copy of this application build from independently opening the engine.
It does not claim to coordinate arbitrary older binaries or developer tools.

This changes the old exclusion of a localhost browser experience and the global
“no localhost HTTP server” wording. It does not authorize a public server, remote
access, hosted computation, plaintext staging, sync or an installation-free app.
Browser drag-and-drop remains outside the first version; native file selection
is its import path. No new model egress is introduced by the browser connection.

Future shared product acceptance runs in the browser. Native tests cover only
native-specific features: launch/exit, dialogs, credential storage, handoff,
sidecar packaging, signing and installation. Unit/integration tests still verify
their owning packages. A development host or mocked native picker cannot prove
an installed host or an operating-system dialog; reports must identify the
actual boundary exercised and keep missing coverage visible.

Reverse the presentation choice if local browser use cannot meet the existing
privacy and correctness promises. Do not reverse those promises to retain the
presentation choice.
