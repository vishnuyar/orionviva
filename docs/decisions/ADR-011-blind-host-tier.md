# ADR-011 · Blind-Host Tier (encrypted hosting, client-held keys)

**Status:** Proposed — drafted 2026-07-25 ahead of need, not scheduled · **Door type:** two-way until publicly announced; announcing it is one-way (it becomes a commitment)
**Invariants touched:** T4 (append-only log, multiple writers), T5 (no plaintext phase), T6 (nothing leaves silently), T8 (model access modes), X1 (target user can install an app)

> **Standing rule until adopted:** per ADR-008, no public statement — site, README, build log — may mention this tier until this ADR is Accepted and the ADR-008 amendment below lands with it. This document exists so the reasoning is on the record *before* the pressure to ship it arrives.

## Context

A significant share of future users will not run software on their own machine, however good the installer — they expect the open-source author (or someone) to host it, the way most OSS is actually consumed. X1 points the same direction. The question this ADR answers: can a hosted tier exist without breaking the promise inventory?

Promise 3 was worded carefully: *"no hosted storage of **decryptable** personal financial data, ever."* The non-custodial wallet model — the user's secret opens the vault; the server holds only ciphertext it cannot read — satisfies that wording in letter and in spirit. A breach of such a host yields what a stolen laptop yields in the threat model: ciphertext. A bad day, not ruin. Mature precedents: Bitwarden, Proton, Signal, Ente.

The wallet analogy hides one hard problem: a wallet server never needs to *understand* the data, but Viva must read, verify, and compute. A blind server cannot compute on ciphertext (FHE is impractical for this workload for the foreseeable future). So the tier is defined by a strict split: **hosted storage, client-side compute.**

## Decision (what the tier is, when adopted)

1. **The host is a blind relay.** It stores encrypted blobs and syncs the append-only event log (T4 already assumes multiple writers — the architecture fits this natively). It never holds keys, plaintext, or the ability to acquire either.
2. **Keys never leave the user's device.** Passphrase-wrapped as today (ADR-005). Recovery is user-held (recovery kit / printed code / social recovery) — never escrow of anything decryptable by the host. "Lost secret = lost vault" is softened by recovery UX, not by custody.
3. **All compute is client-side.** Extraction, verification, and answers run in the user's app — including a browser client via WASM + in-browser SQLite. The web app *is* the machine.
4. **Model calls go client → provider directly** (BYOK / OAuth-brokered per ADR-001, T8), never through the relay.
5. **Sync is opt-in and visible.** Enabling it is a user action; every upload appears in the outbound record (promise 4 is honored: user-enabled, fully listed).
6. **The relay is self-hostable.** Anyone may run one; we may run one for convenience; the protocol is the product, so there is no lock-in and we never become a mandatory custodian.
7. **Code delivery becomes the new trust boundary** for the web client: signed builds, subresource integrity, build transparency. Installable apps remain the *trust tier*; the hosted web client is the *convenience tier*, and the threat-model page says so.

## Promise-compatibility analysis

- **Promise 3:** intact — nothing hosted is decryptable by the host.
- **Promise 4:** intact — sync is user-initiated and in the outbound record.
- **New residuals to add to the threat model on adoption, honestly:** (a) the host sees metadata — blob sizes, timing, IP — traffic analysis, not content; (b) a malicious or compromised host could serve hostile JavaScript to web clients, which is why the web tier is labeled convenience, not trust.

## Alternatives considered

**Hosted compute with in-memory decryption** ("encrypted at rest" marketing) — rejected: the server sees plaintext at session time. This is custody with extra steps and breaks promise 3's spirit.

**Fully homomorphic encryption** — rejected for now: orders of magnitude too slow for document extraction and ledger computation. Revisit if that changes.

**Never host anything** — rejected as the reason this ADR exists: refusing convenience forever hands exactly the users this project is for back to custodial products. The promise forbids custody of decryptable data, not making a future user's life easier.

## Consequences

Adoption requires, in order: an ADR-008 amendment clarifying promise 3 ("hosted ciphertext with client-held keys is permitted; hosted decryptable data, never") **before** any public copy; new adversary rows on /what-viva-can-never-do (blind-host breach → ciphertext; hostile host → JS delivery risk on the web tier); and a recovery-kit design, since consumer users will not accept bitcoin's "lose the seed, lose everything" unsoftened.

## Would reverse this

Everything, freely, until it is announced. After announcement: the blind-host property itself (host never able to decrypt) joins the one-way list; implementation details (protocol, providers, web vs. app clients) stay two-way.
