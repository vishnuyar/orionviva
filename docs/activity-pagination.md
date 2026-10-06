# Bounded Activity continuation

Activity can serve every eligible movement within its existing projection and transport bounds through versioned continuation. Each read still returns at most 100 rows; the desktop asks for 50. This is complete traversal of a bounded read model, not unlimited-vault support or global search.

## Reader contract

`viva.surface.read` for `activity` accepts `page_version: 1` and an optional bounded `cursor` alongside `limit`, `focus` and `as_of`. An absent or empty cursor starts a chain. A continuation may omit focus: the authenticated cursor retains its initial focus policy. Explicitly changing focus crosses that scope and is refused. Unknown versions, cursor-without-version requests, malformed tokens and changed scopes are refused. Requests without the version retain the original prefix selection, focus replacement and individual `beyond.count`.

A version-one response preserves existing row and vocabulary fields and adds:

```
page:
  version: 1
  revision: opaque revision identity
  next_cursor: bounded string or null
  cumulative_count: distinct movements served by this chain
  remaining_count: eligible movements not yet served
```

The cursor is authenticated by the opened provider's private session key and binds source count/head, publication epoch, generation, historical cutoff, ordering version, page size and focus policy. Its offset belongs to that unchanged ordered selection. Tokens from another provider or changed revision/scope cannot be combined. Tokens remain in session memory and are neither persisted nor logged by this implementation.

Selection retains pending-transfer-first ordering, followed by descending movement date and identity. An initial focus outside the ordinary prefix replaces its last row. The cursor records that focused movement as served, resumes before the displaced ordinary row and omits the focus from later pages. Thus the focused exception introduces neither a gap nor a duplicate. `cumulative_count` and `remaining_count` describe the distinct chain, while legacy `beyond.count` still counts rows omitted from the individual response.

Current paging uses the held normalized projection. Historical paging uses the existing value-time fold before selection; it does not filter latest-state rows by transaction date. Existing movement, relationship, scalar, nested-byte and transport bounds remain unchanged. No ledger event/schema, source figure or financial formula changes.

## Desktop behavior

“Load 50 more” fetches a bounded continuation page and appends only supported metadata and identities belonging to the active chain. The adapter validates version, counts, cursor consistency and duplicate identities. The session additionally checks revision, focus, cumulative progress, total consistency and overlap with displayed rows. Only one continuation can be in flight.

A thrown or resolved failed continuation preserves displayed rows and the last successful cursor, shows a local notice and permits retry. Revision changes, source/vault changes, recovery and successful writes invalidate the chain. Refresh asks for a new 50-row initial page, retaining the selected movement through focus. Delayed old-scope responses cannot append to the refreshed list. If a continuation fails after an otherwise unobserved publication, a bounded priority read can reveal that revision and release a new initial read. Failed refresh keeps existing rows usable with a refresh action; it cannot continue the invalidated cursor.

A new interface can fall back to the legacy initial prefix when an older reader refuses the versioned initial request. It states that further continuation needs an updated local reader, and offers no progressively larger requests. Ordinary transport failures do not automatically fall back. An older interface continues to receive the legacy response.

Search and filters cover loaded rows, and the interface says so. Remaining-row copy uses the chain's `remaining_count`. Source links, selected corrections and Undo retain their existing identities and actions; pagination creates no classification question or proof requirement. Categories and treatment remain inferable, while source numbers require evidence.

## Verification and Witness boundary

Provider-free controls exercise bounded traversal, ties, pending transitions, current/historical scope, outside-prefix focus, authentication, changed scope/revision refusal, legacy behavior, metadata validation, duplicate clicks, resolved failure/retry, delayed publication guards and later-row source navigation. Canonical financial meaning and ingestion are outside this repair.

Independent verification and browser Witness evidence are separate requirements. The owner directed the Witness to retain vault-006 and D01–D04 and continue without re-ingestion. D04 row/source review is complete on the frozen browser test-host candidate; it does not establish installed-host delivery or complete the remaining document and financial-conversation campaign. The earlier nine-pass acceptance result is historical. Pagination does not clear the current acceptance source-binding, browser-journey, compatibility or model-quality gaps.
