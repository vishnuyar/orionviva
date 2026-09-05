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

The live path provides financial picture and account evidence, a user-facing
Transactions workspace (the compatibility destination and contract key remain
`activity`) with movement-scoped existing-choice category, economic-treatment,
complete-set tag and backend-qualified transfer correction, document capture and rescan,
an Accounts index whose rows open an in-app, account-scoped stitched ledger
with backend month groups, coverage and reconciliation disclosures, filters,
transaction evidence drawers, and exact single or visible-selection classification and tag editing,
calendar-aware upcoming obligations and the backend's top three quiet findings
with inspect, Ask Viva and evidence-staked set-aside gestures,
per-currency thirty-day known-remainder ranges and refusals with
backend-supplied assumptions, exclusions, evidence and balance series,
save-up Plans with pure drafts, explicit local reservations, exact persisted
proposal confirmation, account evidence and durable conversational entry,
bounded durable job receipts with live progress and cancellation,
one durable conversation for questions, answers, corrections, proposal confirmation and decline, capability-derived navigation,
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

The shipped shell presents Overview, Accounts, Transactions, Statements,
Review, and served Plans in task order. Review carries the backend-authored
actionable count. Add statement and Ask Viva remain distinct top-level actions;
Trust & settings remains one click away in a separate utility landmark. The
narrow drawer preserves the same destinations, active state, focus trap,
Escape and outside-close behavior. Meaningful interface text has a twelve-pixel
minimum, actionable controls and disclosures keep a forty-four-pixel minimum
hit area at desktop and narrow widths, and the two-card financial picture
stacks before the fixed navigation rail can crowd its authored currency totals.
Source/provenance internals are progressively disclosed while
conflicts, coverage gaps, requests, errors, and pending work remain visible.

## Coverage tables

These tables intentionally repeat only facts that tests derive from executable
registries. The final destination column is a UI statement and the final
operation column is additionally checked by the desktop architecture gate.

| Destination | Live read | Registry destination | Claimed by a surfaced capability | Shipped in the interface |
| --- | --- | --- | --- | --- |
| `overview` | yes | yes | yes | yes |
| `spending` | yes | no | no | yes |
| `plans` | yes | yes | yes | yes |
| `accounts` | no | yes | yes | yes |
| `account_ledger` | yes | no | no | yes |
| `activity` | yes | yes | yes | yes |
| `documents` | yes | yes | yes | yes |
| `jobs` | yes | no | no | yes |
| `review` | yes | yes | yes | yes |
| `conversation` | yes | no | no | no |
| `viva` | no | yes | yes | yes |
| `trust` | yes | yes | yes | yes |
| `settings` | no | yes | yes | no |
| `none` | no | yes | no | no |

`activity` in this implementation table is the stable internal compatibility
name. The destination shown to people is **Transactions**.

| Operation | Allowlisted | Where it is served | Consumed by the desktop |
| --- | --- | --- | --- |
| `bridge.handshake` | yes | before a vault opens | yes |
| `bridge.open_demo_vault` | no | explicit sidecar open branch | yes |
| `bridge.open_vault` | no | explicit sidecar open branch | yes |
| `viva.activity.add_tags` | yes | opened vault | yes |
| `viva.activity.assign_category` | yes | opened vault | yes |
| `viva.activity.assign_classification` | yes | opened vault | yes |
| `viva.activity.assign_meaning` | yes | opened vault | yes |
| `viva.activity.confirm_transfer` | yes | opened vault | yes |
| `viva.activity.reject_transfer` | yes | opened vault | yes |
| `viva.activity.remove_tags` | yes | opened vault | yes |
| `viva.activity.replace_tags` | yes | opened vault | yes |
| `viva.activity.unlink_transfer` | yes | opened vault | yes |
| `viva.conversation.ask` | yes | opened vault | yes |
| `viva.conversation.answer` | yes | opened vault | yes |
| `viva.conversation.confirm` | yes | opened vault | yes |
| `viva.conversation.decline` | yes | opened vault | yes |
| `viva.documents.cancel` | yes | opened vault | yes |
| `viva.documents.rescan` | yes | opened vault | yes |
| `viva.documents.upload` | yes | opened vault | yes |
| `viva.lifecycle.read` | yes | before a vault opens | yes |
| `viva.maintenance.diagnose` | yes | opened vault | yes |
| `viva.maintenance.run` | yes | opened vault | yes |
| `viva.overview.set_aside_finding` | yes | opened vault | yes |
| `viva.plans.confirm` | yes | opened vault | yes |
| `viva.plans.decline` | yes | opened vault | yes |
| `viva.plans.draft` | yes | opened vault | yes |
| `viva.plans.propose` | yes | opened vault | yes |
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
| `has-name product/viva/desktop_bridge/jobs.py#JobRegistry` | Bounded operational receipts survive restart. Work interrupted by exit is restored as failed and is not resumed, so the person must start it again. |
| `has-file desktop/src/features/documents/Documents.tsx` | Page and source-region review, focused correction, and document-level outbound history are not connected in the Statements & documents destination. Current capture, read status, resolution, and contribution remain primary; technical identity, lifecycle, pages, source regions, and provenance are available through disclosure rather than dominating the index. |
| `has-file desktop/src/features/activity/Activity.tsx` | Transactions (internal `activity`) reaches movement-scoped existing-choice category correction; treatment correction for spending, a named loan lent, or a named loan repayment chosen from receivables open on the movement date with enough remaining principal; complete-set tag replacement that may introduce a bounded local tag where the backend advertises it; and backend-qualified transfer confirmation, rejection and unlinking. Search and authored filters lead the workspace, while source statements are disclosed per transaction. The desktop neither infers transfer candidates nor offers merchant-wide changes, new category labels, or bulk editing. |
| `has-file product/viva/surface/account_ledger.py` | AccountLedger.v1 supplies an exact account-scoped, session-authenticated and revision-bound, month-grouped read with normalized attested coverage, gaps, overlap state and account-bound source evidence. Exact economic postings from overlapping statement periods collapse authoritatively before pagination, with canonical/member identities and unioned evidence; probable or conflicting candidates remain separate and disclosed. A transaction-only account remains readable with an explicitly absent balance, and the read carries no write actions. The desktop bridge, strict adapter, stale-safe account-detail route, shell hierarchy, and minimum-type audit now render and edit against it. |
| `has-file desktop/src/features/conversation/ConversationDrawer.tsx` | Conversation is durable across process and interface sessions, includes the deterministic question queue, records proposal identity and exact proposed data separately, and restores confirmation controls after reopening. There is no microphone, speech recognition, or audio playback path; the reply shape remains voice-ready. Because the product is unreleased, this contract intentionally starts clean and performs no migration or backfill from earlier technical read records or prior vault shapes. |
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
