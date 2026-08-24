# OrionViva User Interface Implementation Status

**State:** partial
**Rules:** VOICE-120, VOICE-121, VOICE-132

This is the checked current-state counterpart to
[User Interface Architecture and Delivery](user-interface-architecture-and-delivery.md).
The earlier pre-bridge measurement is preserved in
[the archive](archived/user-interface-implementation-status-before-live-desktop.md).

## Rules

### VOICE-120 — a slice is complete only against the live boundary it claims
**State:** untestable
**Code:** none found
**Test:** none

1. A slice may be marked complete only when its architecture acceptance criteria pass against the live boundary it claims to use.

### VOICE-121 — a synthetic fixture proves rendering, never parity
**State:** untestable
**Code:** product/viva/surface/fixtures/surface-v1.json
**Test:** none

1. Fixtures prove presentation states; they cannot by themselves prove backend/UI parity.
2. A packaged, signed, installable application is a separate claim from a compiling one, and neither is proven by the other.

### VOICE-132 — a gap carries the address its measurement is re-taken at
**State:** enforced
**Code:** docs/user-interface-implementation-status.md — the tables under **Open**
**Test:** test_docs_track_the_code.py::test_an_anchored_gap_resolves_at_the_address_it_names, test_a_gap_states_an_anchor_and_a_refusal_is_counted_as_one, test_a_destination_table_is_the_destinations_the_registry_holds, test_a_bridge_operation_table_is_the_operations_the_sidecar_serves

1. Every gap this document states opens with a direction and an address at which its measurement can be re-taken, and a gap whose address stops resolving fails the build.
2. A gap no machine in this repository can hold says so in place of an address, gives a concrete reason, and is counted on the document's face.
3. Where a registry already holds the answer, the document restates nothing: its table is compared against the registry, and the comparison fails when the registry moves and the table does not.

## What is live

The installed-app path is a React/Vite interface inside Tauri, backed by the
packaged Python sidecar. The desktop consumes every operation the sidecar
declares. A private vault and persistent sample vault both use the live bridge;
fixtures remain for deterministic presentation-state coverage.

The live path provides financial picture and account evidence, movement
activity with movement-scoped existing-choice category, complete-set tag and
backend-qualified transfer correction, document capture and rescan,
process-local jobs and cancellation,
review answer, proposal confirmation and decline, Ask Viva text turns, capability-derived navigation,
settings proposal and confirmation, outbound history, build and lifecycle
identity, vault export and restore, maintenance, and privacy-filtered diagnostic
export. Trust refreshes after each Ask Viva turn, separates configured routes
from provider-reported identities, leaves older ambiguous model fields
unlabelled, and reports tokens only for calls whose providers supplied usage.
Canonical Overview figures also consume the backend's `routine` or `required`
proof presentation declaration. A durable device-local **Show verification
details** preference defaults off and removes only routine compact assurance;
required backend-authored qualifications remain in the picture, and the
complete Evidence drawer remains preference-independent, with its route and
payload identity preserved.

## Coverage tables

These tables intentionally repeat only facts that tests derive from executable
registries. The final destination column is a UI statement and the final
operation column is additionally checked by the desktop architecture gate.

| Destination | Live read | Registry destination | Claimed by a surfaced capability | Shipped in the interface |
| --- | --- | --- | --- | --- |
| `overview` | yes | yes | yes | yes |
| `accounts` | no | yes | no | yes |
| `activity` | yes | yes | yes | yes |
| `documents` | yes | yes | yes | yes |
| `jobs` | yes | no | no | yes |
| `review` | yes | yes | yes | yes |
| `viva` | no | yes | yes | no |
| `trust` | yes | yes | yes | yes |
| `settings` | no | yes | yes | no |
| `none` | no | yes | no | no |

| Operation | Allowlisted | Where it is served | Consumed by the desktop |
| --- | --- | --- | --- |
| `bridge.handshake` | yes | before a vault opens | yes |
| `bridge.open_demo_vault` | no | explicit sidecar open branch | yes |
| `bridge.open_vault` | no | explicit sidecar open branch | yes |
| `viva.activity.assign_category` | yes | opened vault | yes |
| `viva.activity.confirm_transfer` | yes | opened vault | yes |
| `viva.activity.reject_transfer` | yes | opened vault | yes |
| `viva.activity.replace_tags` | yes | opened vault | yes |
| `viva.activity.unlink_transfer` | yes | opened vault | yes |
| `viva.conversation.ask` | yes | opened vault | yes |
| `viva.documents.cancel` | yes | opened vault | yes |
| `viva.documents.rescan` | yes | opened vault | yes |
| `viva.documents.upload` | yes | opened vault | yes |
| `viva.lifecycle.read` | yes | before a vault opens | yes |
| `viva.maintenance.diagnose` | yes | opened vault | yes |
| `viva.maintenance.run` | yes | opened vault | yes |
| `viva.review.answer` | yes | opened vault | yes |
| `viva.review.confirm` | yes | opened vault | yes |
| `viva.review.decline` | yes | opened vault | yes |
| `viva.settings.confirm` | yes | before a vault opens | yes |
| `viva.settings.propose` | yes | before a vault opens | yes |
| `viva.settings.read` | yes | before a vault opens | yes |
| `viva.surface.capabilities` | yes | before a vault opens | yes |
| `viva.surface.read` | yes | opened vault | yes |
| `viva.vault.export` | yes | opened vault | yes |
| `viva.vault.restore` | yes | opened vault | yes |

## Open

| Anchor | Gap |
| --- | --- |
| `has-name product/viva/desktop_bridge/jobs.py#JobRegistry` | Job state and cancellation are process-local. Restart recovery is absent, so an interrupted document job cannot resume after the sidecar exits. |
| `has-file desktop/src/features/documents/Documents.tsx` | Page and source-region review, focused correction, and document-level outbound history are not connected in the Documents destination. |
| `has-file desktop/src/features/review/Review.tsx` | A proposal can be confirmed or declined while its answer outcome remains open, but ordinary navigation clears the client's proposal identity while the opened-vault bridge retains the proposal. Returning to Review cannot reach that retained proposal. |
| `has-file desktop/src/features/activity/Activity.tsx` | Activity now reaches movement-scoped existing-choice category correction, complete-set tag replacement where the backend advertises it, and backend-qualified transfer confirmation, rejection and unlinking. The desktop neither infers transfer candidates nor offers nature editing, merchant-wide changes, new labels, or bulk editing. |
| `has-file desktop/src/features/conversation/ConversationDrawer.tsx` | Ask Viva is connected for text, but no read supplies recorded conversation turns; the drawer can show only the answer returned to its current question. There is no microphone, speech recognition, or audio playback path; the reply shape is only voice-ready. |
| `no-file product/viva/surface/connections.py` | No account-aggregation surface exists. Documents and the sample vault are the acquisition paths. |
| `has-name product/viva/surface/outbound.py#outbound` | Trust reports outbound model calls and explicitly reports that no independent anchoring exists; it does not create external anchors or issuer signatures. |
| `has-file .github/workflows/release-desktop.yml` | The release workflow validates metadata and packaged sidecar identity and builds signed target artifacts, but it does not boot each produced installer and exercise recovery on a clean target. |
| `has-file desktop/src/features/trust/Trust.tsx` | Configuration is reachable inside Trust rather than through the registry's own Settings destination. The omission is deliberate for the current navigation, but the destination mismatch remains visible. |

### Gaps no machine in this repository can hold (3)

| Refusal | Gap |
| --- | --- |
| `unaddressable — successful signing, notarization, and publication are facts about a workflow run and external platform services, not this tree.` | A real release still requires reviewing every target job and its draft artifacts. |
| `unaddressable — successful installed startup is a fact about a clean target machine, not source or a generated bundle.` | Offline launch, shutdown, and recovery need a manual release check on every supported target until artifact automation exists. |
| `unaddressable — visual correctness in an operating-system webview depends on installed fonts, scale, and platform rendering that repository tests do not observe.` | Final layout and focus behavior require a packaged-app smoke pass, not only headless component tests. |

## Closing a gap

Close a row only when the capability registry, operation table, sidecar handler,
desktop client, interface behavior, and relevant tests agree. If the claim can
be derived from code, strengthen the gate instead of replacing the row with a
positive prose claim.
