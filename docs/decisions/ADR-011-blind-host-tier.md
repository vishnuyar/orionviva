# ADR-011 · Blind-Host Tier (encrypted hosting, client-held keys)

_This records reasoning, not current behaviour._

**Status:** Proposed — drafted ahead of need, not scheduled · **Date:** 2026-07-25 · **Door type:** two-way until publicly announced; announcing it is one-way (it becomes a commitment)

**State:** design-only
**Rules:** ADR-011
**Invariants touched:** T4 (append-only log, multiple writers), T5 (no plaintext phase), T6 (nothing leaves silently), T8 (model access modes), X1 (target user can install an app)

## Rules

### ADR-011 — A hosted tier may store ciphertext and never compute on it
**State:** unmet
**Code:** none found
**Test:** none

1. Until this record is Accepted, no public statement — site, README, build log — may mention this tier (ADR-008).
2. The host is a blind relay: it stores encrypted blobs and syncs the append-only event log, and never holds keys, plaintext, or the ability to acquire either.
3. Keys never leave the person's device. Recovery is user-held — recovery kit, printed code, social recovery — and never escrow of anything the host can decrypt.
4. All compute is client-side: extraction, verification and answers run in the person's app, including a browser client. The web app *is* the machine.
5. Model calls go client to provider directly, never through the relay.
6. Sync is opt-in and visible: enabling it is a person's action, and every upload appears in the outbound record.
7. The relay is self-hostable, so the protocol is the product and no mandatory custodian exists.
8. For the web client, code delivery becomes the new trust boundary: signed builds, subresource integrity, build transparency. Installable apps are the trust tier; the hosted web client is the convenience tier, and the threat model says so.

## Why

A significant share of future users will not run software on their own machine however good the installer; they expect the author, or someone, to host it, the way most open source is actually consumed. X1 points the same way. The question is whether a hosted tier can exist without breaking the promise inventory.

Promise 3 was worded carefully: *no hosted storage of decryptable personal financial data, ever*. The non-custodial wallet model — the person's secret opens the vault, the server holds only ciphertext it cannot read — satisfies that wording in letter and in spirit. A breach of such a host yields what a stolen laptop yields in the threat model: ciphertext. A bad day, not ruin. The precedents are mature.

The wallet analogy hides one hard problem: a wallet server never needs to *understand* the data, while this product must read, verify and compute. A blind server cannot compute on ciphertext, and homomorphic encryption is impractical for this workload for the foreseeable future. So the tier is defined by a strict split — hosted storage, client-side compute.

**Hosted compute with in-memory decryption**, marketed as "encrypted at rest", is rejected: the server sees plaintext at session time, which is custody with extra steps and breaks promise 3's spirit.

**Fully homomorphic encryption** is rejected for now as orders of magnitude too slow for document extraction and ledger computation; revisit if that changes.

**Never hosting anything** is rejected as the reason this record exists: refusing convenience forever hands exactly the people this project is for back to custodial products. The promise forbids custody of decryptable data, not making a future person's life easier.

On promise compatibility: promise 3 is intact because nothing hosted is decryptable by the host, and promise 4 is intact because sync is user-initiated and in the outbound record. Two residuals would join the threat model honestly on adoption — the host sees metadata (blob sizes, timing, IP), which is traffic analysis rather than content; and a malicious or compromised host could serve hostile JavaScript to web clients, which is why the web tier is labeled convenience rather than trust.

Adoption requires, in order: an ADR-008 amendment clarifying promise 3 — hosted ciphertext with client-held keys is permitted, hosted decryptable data never — *before* any public copy; the new adversary rows on the public what-Viva-can-never-do page; and a recovery-kit design, since consumer users will not accept an unsoftened lose-the-seed-lose-everything.

## Would reverse this

Everything, freely, until it is announced. After announcement the blind-host property itself — the host never able to decrypt — joins the one-way list, while implementation details (protocol, providers, web versus app clients) stay two-way.

## Open

- The tier is proposed and not adopted; nothing in the tree implements any part of it.
- Promise 3's clarifying amendment to ADR-008 is unwritten, and no public copy may mention the tier until it lands.
- The recovery-kit design does not exist, and neither does the key custody it would build on (ADR-005).
