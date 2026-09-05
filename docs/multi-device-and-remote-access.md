# Multi-Device & Remote Access — reaching Viva from anywhere without a readable server

**State:** design-only
**Rules:** PROG-38, PROG-39, PROG-40, PROG-41

## Rules

### PROG-38 — No server component ever holds a key or decrypts the ledger
**State:** unmet
**Code:** none found (no relay, sync fabric or hosted component exists in the tree)
**Test:** none

1. Anything that carries data between devices holds ciphertext only.
2. Decryption happens on the user's own device, including in a browser client, where the passkey unlocks keys client-side.
3. Inference calls go directly from the client to the user's own model provider, so no relay sees a plaintext question.

### PROG-39 — Two stores, two movement rules
**State:** unmet
**Code:** none found
**Test:** none

1. The document store — originals and model I/O captures — lives encrypted on the device that ingested it and syncs lazily or on demand.
2. The ledger — extracted, verified, graded facts plus the event log — syncs eagerly, because it is small and needed everywhere.
3. A provenance click on a second device fetches the encrypted blob at that moment rather than replicating everything ahead of time.

### PROG-40 — Merging two devices is a union, not a fight over rows
**State:** unmet
**Code:** product/viva/ledger/store.py:95 implements the single-writer append-only log; no merge path exists
**Test:** none

1. Merging two devices' logs is a union of events plus a deterministic ordering.
2. The event schema assumes multiple writers, so multi-device merge is a design requirement rather than a later bolt-on.

### PROG-41 — Recovery comes from something the user holds, never from the relay
**State:** unmet
**Code:** none found
**Test:** none

1. A relay can authorise ciphertext sync and can reset nothing that matters.
2. "Forgot passkey" recovers from the user's own recovery phrase.

**Note:** the recovery phrase this rule leans on does not exist. The desktop protects one default vault credential in macOS Keychain or Windows Credential Manager, but that convenience is local to the device and does not provide cross-device recovery. The product still has no portable recovery phrase, so this rule inherits that gap rather than closing it. See [local-first-storage-and-crypto.md](local-first-storage-and-crypto.md) PROG-48.

## Why

The desire — documents ingested from desktop and phone, a passkey login anywhere, a conversation with Viva about the extracted picture — describes an end-to-end-encrypted multi-device product, not a hosted-data product. Only one implementation route violates the principles, and this document exists to forbid it by name.

Two misconceptions clear first. No node and no server is needed for tamper-evidence: the event log is a private hash chain on the user's own device, with no network, no consensus and no participants, and anchoring is the act of submitting a 32-byte fingerprint to infrastructure that already exists. And local-first is not single-device — the principle is that nobody but the user can ever read the data, not that the data is shackled to one machine. Multi-device sync and even browser access preserve the principle exactly, if the middle is built blind.

Four routes exist through that middle, and three are honest.

*Your own device as hub* — phone and browser reach the desktop over an encrypted tunnel. The purest form, no third party at all, but availability equals "is my machine on", which fails the beach test. Right as an option for sovereignty-minded users, wrong as the mainstream answer.

*The blind mailbox* is the workhorse, and it is the one part of this document already settled, by [ADR-011](decisions/ADR-011-blind-host-tier.md): a hosted relay that stores and forwards ciphertext only, syncing envelopes between devices and serving the web client, with decryption on the user's device. It is a proven pattern with several shipped precedents, and it is the natural paid-convenience candidate precisely because its blindness is verifiable from open client code. One honest caveat belongs in-product: a web page's crypto is only as trustworthy as the code the server serves that session, so a compromised host could ship poisoned JavaScript. Installed apps, which verify updates by signature, remain the gold standard, and the browser rung is a convenience tier that says so.

*The attested enclave* solves the beach test and frontier-quality inference with zero setup, at the cost of the hardest honesty-explanation, and waits on that explanation being sayable to a non-technical person.

*The conventional hosted app*, where a server decrypts the ledger to answer questions, is never built. It is one breach away from ruin, one subpoena away from betrayal, and indistinguishable from every fintech that came before. Its existence as the *easy* route is why this document is written down: the server components simply never hold keys, which makes the route structurally impossible rather than merely discouraged.

One passkey does three standard jobs: it unlocks the local keystore on installed apps, authenticates to the relay that can read nothing, and in the browser derives or unwraps the client-side decryption keys. The consequence is a support-cost truth worth accepting early — a relay that cannot reset what matters is only humane if the person holds something the relay does not.

The promise language survives intact. Nothing here requires softening "your data, your keys"; the blind relay strengthens it into something demonstrable — here is the relay's database, ciphertext; here is the client code, open.

## Open

- Q14: relay design — build a tiny auditable one or adapt an existing end-to-end-encrypted sync framework, and does the relay double as the encrypted backup target?
- Q15: browser-rung integrity — signed web bundles, an extension, or WASM attestation, and what honest caveat wording accompanies whichever is chosen.
- Q16: does the own-device hub ship at v1 as a zero-infrastructure option, or wait? It is nearly free if the relay protocol is device-agnostic, since a peer is a relay with one client.
- The sync fabric is designed in the architecture phase and built later; the ledger/document-store split has to become explicit in the data model before then.
- The web client is the same open codebase delivered as a signed bundle where the platform allows, and its threat model needs writing honestly.
