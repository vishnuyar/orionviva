# Multi-Device & Remote Access — reaching Viva from anywhere without a readable server

**Status:** Draft · **Last updated:** 2026-07-20 · **Origin question:** ingest documents from desktop and mobile, then log in somewhere with a passkey and chat with Viva about the extracted picture (not the documents). Is that possible without clouding the core principles?

## The short answer

Yes — the desire is fully compatible with the principles. The user's picture ("my verified financial data follows me; documents stay wherever I put them; I reach Viva with a passkey") describes an end-to-end-encrypted, multi-device product, not a hosted-data product. Only one implementation route would violate the principles — a conventional server that decrypts the ledger to serve chat — and it is exactly the route this doc exists to forbid. Everything else is engineering.

## Clearing two misconceptions first

**No node, no server, is needed for tamper-evidence.** The event log (ADR-004) is a private hash chain on the user's own device — a tamper-evident journal, not a blockchain; it has no network, no consensus, no participants. Anchoring is *submitting* a 32-byte fingerprint to infrastructure that already exists (OpenTimestamps calendars, an RFC 3161 authority) — we visit the notary, we never become the notary. Nothing runs overnight anywhere. Node-running enters the story only if the Phase 4 ecosystem ledger ever exists — a deliberately deferred, multi-institution decision, not a prerequisite for anything current.

**"Local-first" ≠ "single-device."** The principle is *no one but the user can ever read the data* — not *the data is shackled to one machine*. Multi-device sync and even browser access can preserve the principle exactly, if the middle is built blind.

## The architectural split the postulate got right

Two stores with different weights and different movement rules:

- **The document store** — originals, model I/O captures (ADR-003). Heavy, immutable, rarely needed after extraction (provenance click-through, re-extraction, audits). Lives encrypted on the device that ingested it; syncs lazily or on demand. A provenance click on another device fetches the encrypted blob then.
- **The ledger** — extracted, verified, graded facts plus the event log. Small (megabytes for a whole financial life), needed everywhere, syncs eagerly.

Every device holds keys (unlocked by passkey/biometric via OS keystore); whatever carries data between them holds only ciphertext. Conflict handling is tractable because the log is append-only — merging two devices' events is a union plus deterministic ordering, not a fight over mutable rows. (This hardens the ADR-004 consequence: multi-device merge is an event-log design requirement, not a bolt-on.)

## The middle: four routes, three honest

**Route A — your own device is the hub.** Phone and browser reach the user's desktop over an encrypted tunnel (Tailscale-class, zero-config). The purest form; no third party at all. Cost: availability equals "is my machine on," which fails the beach test. Right as an *option* for sovereignty-minded users, wrong as the mainstream answer.

**Route B — the blind mailbox (the workhorse).** A hosted relay that stores and forwards *ciphertext only*: sync envelopes between devices, plus serving the web client. Decryption happens on the user's device — including in the browser, where the passkey unlocks keys client-side and inference calls go *directly* from the client to the user's model provider (adoption-doc rungs 2/3), so the relay never sees plaintext data or plaintext questions. Proven pattern (Bitwarden, Proton, Ente). This is also the natural F1 business-model candidate: the relay is a paid convenience, and its blindness is verifiable from the open client code. Honest caveat, stated in-product someday: a web page's crypto is only as trustworthy as the code the server serves that session — a compromised host could ship poisoned JavaScript. Installed apps (which verify updates by signature) remain the gold standard; the browser rung is a convenience tier and says so.

**Route C — the attested enclave.** Hosted Viva inside verifiable can't-read hardware (the adoption doc's PCC pattern). Solves the beach test *and* frontier-quality inference with zero setup, at the cost of the hardest honesty-explanation. Future rung, gated on Q12.

**Route D — the conventional hosted app, where the server decrypts the ledger to answer questions. Never.** This is the "destruction at the end" architecture the postulate rightly distrusted: one breach away from ruin, one subpoena away from betrayal, and indistinguishable from every fintech that came before. Its existence as the *easy* route is why this doc is written down.

The product ships B as the default multi-device fabric, offers A for purists, holds C for later, and treats D as structurally impossible (the server components simply never hold keys).

## What the passkey does

One credential, three jobs, all standard: unlocks the local keystore on installed apps; authenticates to the relay (which authorizes ciphertext sync but can read nothing); and in the browser, derives/unwraps the client-side decryption keys. Recovery remains the storage doc's dual-wrap scheme — the relay must be useless to an attacker who fully compromises it, which also means the relay can never reset what matters. "Forgot passkey" recovers from the user's own recovery phrase, not from us — a support-cost truth to accept early.

## Consequences

- The sync fabric (encrypted envelopes, append-only merge) gets designed in the architecture phase — still built later, but the event schema must assume multiple writers from day one.
- The ledger/document-store split becomes explicit in the data model (A1).
- Web client = same open codebase, delivered as a signed bundle where platform support allows; its threat model documented honestly.
- Promise language survives intact: nothing here requires softening "your data, your keys" — Route B strengthens it into something demonstrable ("here is the relay's database: ciphertext; here is the client code: open").

## Open questions (register)

- Q14: Relay design — build (tiny, auditable) vs. adapt existing E2EE sync frameworks; and does the relay double as the encrypted backup target?
- Q15: Browser-rung integrity — signed web bundles / extension / WASM attestation options for hardening web-delivered crypto, and what honest caveat wording accompanies it.
- Q16: Does Route A (own-device hub) ship at v1 as a zero-infrastructure option, or wait? (It's nearly free if the relay protocol is device-agnostic — a peer is just a relay with one client.)
