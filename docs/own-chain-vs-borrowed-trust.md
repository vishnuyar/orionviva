# An Own Blockchain vs. Borrowed Trust — the node question, examined

**State:** design-only
**Rules:** PROG-50, PROG-51, PROG-52, PROG-53

## Rules

### PROG-50 — The project borrows a fortress and never builds one
**State:** by-review
**Code:** none found (enforced by absence — no chain, consensus, node or token code exists in `product/`, `core/`, `merchant/` or `bench/`)
**Test:** none

1. OrionViva operates no chain and issues no token.
2. Tamper-evidence anchors to infrastructure that already exists; the project visits the notary and never becomes one.

### PROG-51 — The chain head anchors to a public timestamp
**State:** unmet
**Code:** none found
**Test:** none

1. The event log's head hash is submitted periodically to OpenTimestamps or an RFC 3161 authority.
2. Anchoring submits a fingerprint only, so nothing readable leaves the machine.

### PROG-52 — Installed apps may verify, never store for strangers
**State:** unmet
**Code:** none found
**Test:** none

1. An installed app may act as a watchtower: verifying anchors and auditing whatever public registry exists.
2. No installed app holds fragments of another person's financial data, encrypted or otherwise.

### PROG-53 — Proof rests on signatures, an anchored log and selective disclosure
**State:** unmet
**Code:** none found
**Test:** none

1. What makes a fact probative to a counterparty is the issuer's signature, the anchored hash chain, and disclosure of the single claim — never the physical location of the encrypted bytes.
2. Any peer-to-peer replication is an optional, user-chosen backup target, never a default and never load-bearing for proof.

## Why

A ledger's tamper-proofness is not a property of its software; it is the cost of rewriting its history, which comes from the scale and independence of its participants. The numbers are stark: renting enough hashpower to attack Ethereum Classic cost roughly $3,800/hour against roughly $513,000/hour for Bitcoin, and ETC suffered three successful 51% attacks in a single month, reorganising 14,000+ blocks. Research across 2018–2024 found 85% of successful attacks hit chains in their first three years. A new chain would be the softest possible target for years, which makes anchoring to it *strictly weaker* than anchoring to a mature one, at enormously higher engineering cost. This is the bootstrap paradox: a chain's trust requires scale, scale requires adoption, and adoption cannot wait for the chain's trust.

There is a subtler problem. A network where every node runs one vendor's app, updated by one developer, is not decentralised in the trust sense regardless of node count — whoever ships the update controls the rules. It would be a distributed database wearing a chain costume, with this project as the middleman its own theory says nobody should be.

Two precedents settle it from opposite directions. Microsoft ION faced exactly this choice for decentralised identity with effectively unlimited resources and chose *not* to build a chain: Sidetree batches tens of thousands of identity operations into a single Bitcoin transaction and introduces no token. Sovrin built the purpose-run permissioned identity ledger with mission-driven stewards; the foundation dissolved and its MainNet is now a read-only archive on a single cloud server run by one private company, write keys gone — the decentralised public good ending as the most centralised artifact imaginable. A study across 17 permissioned-chain case studies found the single best predictor of decline, in 14 of 17, was the absence of validator economic incentives.

That closes into a trilemma. A sustainable chain needs node incentives; credible incentives at scale mean a token; a token is an explicit anti-goal. No token leads to volunteer nodes and Sovrin's fate. A token leads to the crypto theatre this project forswore. The only stable exit is the ION exit, and [ADR-004](decisions/ADR-004-append-only-log-and-anchoring.md) stands: the recommendation against an own chain is not caution, because the evidence says an own chain is the *less* trustworthy option for its entire early life and its sustainable version requires the token the project has forsworn.

Every-app-a-node fails on physics rather than on theory. Consumer devices churn: laptops sleep, phones kill background processes, home NAT blocks inbound connections, batteries and data caps punish participation. Churn is the central enemy of decentralised storage — more churn demands more redundancy, more redundancy demands more bandwidth, and availability collapses onto always-on participants. Storj erasure-codes files into 80 pieces of which any 29 suffice, tolerating 60% node loss, and sustains that only with paid semi-professional nodes; IPFS without incentives resolves to pinning services, which are servers by another name. A swarm of unpaid phones and sleeping laptops holding fragments of strangers' financial data is the worst known configuration for durability — and it asks users to host others' encrypted financial fragments, a consent and liability conversation nobody wants in an onboarding flow whose target skill is "can install an app". The legitimate kernel survives: decentralised *verification* costs nearly nothing on a consumer device and adds real trust, which is what the watchtower role is.

Chunked storage as proof confuses where bytes live with what makes them probative. Authenticity comes from the issuer's signature, integrity of history from the anchored chain, and privacy from selective disclosure; the physical location of encrypted bytes contributes to none of the three. A copy on the user's own devices plus an encrypted backup is exactly as probative as fragments scattered across a thousand strangers' laptops. Durability is a backup problem with boring, excellent solutions.

**Sources:** [ChainUp: 51% attacks](https://www.chainup.com/blog/51-percent-attacks-explained/) · [MIT Tech Review: blockchains getting hacked](https://www.technologyreview.com/2019/02/19/239592/once-hailed-as-unhackable-blockchains-are-now-getting-hacked/) · [Hacken: 51% attack economics](https://hacken.io/discover/51-percent-attack/) · [CoinDesk: Microsoft ION live on Bitcoin](https://www.coindesk.com/markets/2021/03/25/microsofts-ion-digital-id-network-is-live-on-bitcoin) · [ION repo (Sidetree, no token)](https://github.com/decentralized-identity/ion) · [Autheo: what happened to Sovrin](https://www.autheo.com/blog/what-happened-to-sovrin-network) · [Sovrin Foundation dissolution](https://sovrin.org/the-sovrin-foundation-has-been-dissolved-but-sovrin-mainnet-remains/) · [ID Tech: MainNet shutdown](https://idtechwire.com/the-community-moved-on-sovrin-announces-mainnets-likely-shutdown/) · [Storj v3 whitepaper](https://static.storj.io/storjv3.pdf) · [IPFS comparisons and pinning reality](https://docs.ipfs.tech/concepts/comparisons/) · [arXiv: IPFS opportunities and challenges](https://arxiv.org/pdf/2202.06315)

## Open

- Q17: the Phase 4 registry — join an existing utility, run a Sidetree-class overlay on Bitcoin, or a consortium chain with institutionally diverse validators. The overlay is the leading candidate shape and all-one-vendor nodes are excluded; the decision belongs at Phase 4 entry and not before.
- The watchtower role is on the long-term design list and nothing builds it.
- Anchoring has never run: no OpenTimestamps call, no RFC 3161 call, no periodic job, and every unanchored day is history that stays self-attested.
