# ADR-004 · Append-Only Hash-Chained Event Log, Anchored from Day One

_This records reasoning, not current behaviour._

**Status:** Accepted · **Date:** 2026-07-19 · **Decided by:** Vishnu (anchoring destination) · **Door type:** one-way in time (history cannot be backdated)

**State:** partial
**Rules:** ADR-004
**Invariants touched:** T4, T5, T6

## Rules

### ADR-004 — All state is an append-only hash chain, anchored to two independent external clocks
**State:** enforced-with-exception
**Code:** product/viva/ledger/store.py:44 · product/viva/ledger/store.py:95 · product/viva/ledger/store.py:153
**Test:** product/tests/test_store.py::test_chain_detects_tampering

1. All state changes are events: ingestions, extractions, verification results, corrections, answers given.
2. Each entry embeds the hash of the previous entry.
3. Current state is always a rebuildable projection of the log and is never independently authoritative.
4. The chain verifies without the encryption key.
5. The chain head is anchored from the first event to two independent external timestamps — OpenTimestamps and an RFC 3161 authority.
6. Only the 32-byte head hash ever leaves the machine.
7. Anchoring runs as a quiet periodic job; failures queue and retry, and anchoring lag is recorded rather than hidden.
8. Anchors are additive: a future shared ledger becomes an additional destination and could never have created the proof retroactively.

**Exception:** assertions 5, 6 and 7 have no implementation. No OpenTimestamps call, no RFC 3161 call, no periodic job and no anchor-lag record exists anywhere in the tree; `EventStore.append` (product/viva/ledger/store.py:95) computes a head that nothing carries off the machine.

## Why

Tamper-evidence proves history only from the moment it starts. The trust-agent arc — an agent that vouches for a person — requires a provable record of how the agent came to know what it knows, and that record either begins at commit one or begins with a permanent gap.

**A mutable database with an audit table** is the conventional design and is rejected: audit tables are bypassable by the code that writes them, while a projection-of-log architecture makes unaudited mutation structurally impossible rather than procedurally forbidden.

**A local chain now, anchored later** is a simpler start and was rejected by decision: history before the first anchor is forever self-attested, the gap is permanent, and the later phases would inherit it. That reasoning is what the current state is spending — an anchor placed later proves only that the head existed *then*, so every unanchored day lengthens the stretch a future reader must take on trust.

**A single anchor destination** — OpenTimestamps alone (free, strongest clock, but Bitcoin-adjacent) or RFC 3161 alone (no Bitcoin association, but trusting one company) — is viable either way. Both together were chosen: two independent trust bases at the cost of two small network calls, and the proof survives either one disappearing.

**An own blockchain** is forbidden by the project's principles at this stage. A shared ledger is an ecosystem-scale political decision for the multi-issuer phase, never an authenticity mechanism.

The log doubles as the audit substrate for memory and corrections: one history, many projections.

## Would reverse this

Nothing reverses append-only plus day-one anchoring. Destinations may be added, or retired if one collapses, with the transition itself logged and anchored.

## Open

- No chain head has ever been anchored, so the word *anchored* states a requirement rather than a property the vault can demonstrate.
- Event schema design is a sticky decision that deserves its own ADR, and the ledger/event-store record is owed.
