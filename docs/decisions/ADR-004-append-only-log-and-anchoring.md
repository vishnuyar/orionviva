# ADR-004 · Append-Only Hash-Chained Event Log, Anchored from Day One

**Status:** Accepted · **Date:** 2026-07-19 · **Decided by:** Vishnu (anchoring destination) · **Door type:** one-way in time (history can't be backdated)

## Context

Tamper-evidence proves history only from the moment it starts. The Phase 4 arc — an agent that vouches for you — requires a provable record of how the agent came to know what it knows. That record either begins at commit one or it begins with a permanent gap.

## Decision

All state changes are events in an append-only log: ingestions, extractions, verification results, corrections, answers given. Each entry embeds the hash of the previous entry (a hash chain); current state (accounts, balances, categories) is always a rebuildable projection of the log, never independently authoritative. The chain head is anchored **from the first event** to **two independent external timestamps**: OpenTimestamps (Bitcoin block header as notary clock — nothing on-chain, no tokens, consistent with the principles' "trusted timestamp / transparency log" allowance) and an RFC 3161 timestamp authority. Only the 32-byte head hash ever leaves the machine; it reveals nothing.

If a shared OrionViva-ecosystem ledger ever exists (Phase 4's political choice), it becomes an *additional* anchor destination from that day — anchors are additive; a future ledger inherits day-one proof but could never have created it retroactively.

## Alternatives considered

**Mutable database with an audit table** — the conventional design. Rejected: audit tables are bypassable by the code that writes them; a projection-of-log architecture makes unaudited mutation structurally impossible rather than procedurally forbidden.

**Local chain now, anchor later** — simpler start. Rejected by decision: history before first anchor is forever self-attested; the gap is permanent and Phase 4 would inherit it.

**Single anchor destination** — OpenTimestamps alone (free, strongest clock, but Bitcoin-adjacent) or RFC 3161 alone (no Bitcoin association, but trusts one company). Both viable; **both together** chosen: two independent trust bases at the cost of two small network calls, and the proof survives either one disappearing.

**Own blockchain** — explicitly forbidden by the project's principles at this stage; a shared ledger is an ecosystem-scale political decision for the multi-issuer phase, not an authenticity mechanism.

## Consequences

Event schema design becomes a sticky decision that deserves care (the discovery map, A-track). Anchoring runs as a quiet periodic job; failures queue and retry (anchoring lag is recorded, never hidden). The log doubles as the audit substrate for memory and corrections (the storage doc open question — one history, many projections).

## Would reverse this

Nothing reverses append-only + day-one anchoring; destinations may be added or (if one collapses) retired, with the transition itself logged and anchored.
