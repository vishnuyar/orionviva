# An Own Blockchain vs. Borrowed Trust — the node question, examined

**Status:** Stable — deferral raised, examined, and resolved — ADR-004 confirmed (2026-07-20) · **Origin:** a deferral raised against ADR-004 — why anchor to OpenTimestamps instead of our own chain? Could every installed app act as a node, with users' encrypted extracts chunked and replicated across nodes as durable proof for the future loan agent?

## The proposal, split into its three separable ideas

1. **Anchor to our own chain** instead of Bitcoin-via-OpenTimestamps / RFC 3161.
2. **Every installed app acts as a node** of that network.
3. **Encrypted extracts, chunked and replicated across nodes** (BitTorrent/IPFS-style) so the proof survives and is available to a future counterparty agent.

Each gets a different verdict, so they must be judged separately.

## Idea 1 — the own chain: the fortress you can't build young

A ledger's tamper-proofness is not a property of the software; it is the *cost of rewriting history*, which comes from the scale and independence of participants. The numbers are stark: when Ethereum Classic was attacked, renting enough hashpower cost ~$3,800/hour versus ~$513,000/hour for Bitcoin; ETC suffered three successful 51% attacks in one month (2020), reorganizing 14,000+ blocks. Research across 2018–2024 found **85% of successful attacks hit chains in their first three years**. A new OrionViva chain — one node, then dozens — would be the softest possible target for years, which makes anchoring to it *strictly weaker* than anchoring to Bitcoin's fortress, at enormously higher engineering cost. This is the bootstrap paradox: a chain's trust requires scale; scale requires adoption; and our adoption can't wait for the chain's trust.

There's a subtler problem: a network where every node runs one vendor's app, updated by one developer, is not decentralized in the trust sense regardless of node count — whoever ships the update controls the rules. It would be a distributed database wearing a chain costume, and *we* would be the middleman the theory says no one should be.

**The two precedents, one from each direction:**

- **Microsoft ION** faced exactly this choice for decentralized identity and — with effectively unlimited resources — chose *not* to build a chain. ION uses the Sidetree protocol to batch tens of thousands of identity operations into a *single Bitcoin transaction*, explicitly introducing no token ("Bitcoin is the only unit of value relevant"). Borrowed fortress, own overlay. This is the ADR-004 pattern at industrial scale.
- **Sovrin** built the purpose-run identity ledger — permissioned, no token, mission-driven stewards running nodes. The foundation dissolved in May 2025; the MainNet is now a **read-only archive on a single cloud server operated by one private company, write keys gone**. The decentralized public good ended as the most centralized artifact imaginable. A 2024 IEEE study across 17 permissioned-chain case studies found the single best predictor of network decline (14 of 17): **absence of validator economic incentives.**

That last finding closes the loop into a trilemma: a sustainable chain needs node incentives; credible incentives at scale mean a token; a token is an explicit anti-goal. No token → volunteer nodes → Sovrin's fate. Token → the crypto theater the project forswore. The only stable exit is the ION exit: borrow the fortress, never build one.

## Idea 2 — every app a node: the physics of consumer devices

Consumer devices churn: laptops sleep, phones kill background processes, home NAT blocks inbound connections, batteries and data caps punish participation. The decentralized-storage literature is unambiguous — churn is *the* central enemy: more churn demands more redundancy, more redundancy demands more bandwidth, and availability ends up depending on always-on participants. Storj's numbers show what it takes even with **paid, semi-professional** nodes: files erasure-coded into 80 pieces, any 29 sufficient, tolerating 60% node loss — economics only a token subsidy sustains. IPFS without incentives resolves to "pinning services," i.e., servers by another name. A swarm of phones and sleeping laptops, unpaid, holding fragments of strangers' financial data, is the worst known configuration for durability — and asks users to host others' encrypted financial fragments, a consent and liability conversation nobody wants in an onboarding flow whose target skill is "can install an app."

**The legitimate kernel, kept:** every installed app *can* cheaply be a **watchtower** — verifying anchors, auditing the transparency of whatever registry exists, holding the ecosystem honest. Decentralized *verification* costs nearly nothing on a consumer device and adds real trust. Decentralized *storage* is what the physics rejects. If Phase 4 ever runs a Sidetree-style overlay (anchored to Bitcoin, ION pattern), overlay nodes replicate small *public* protocol data — and "every app can be an overlay node" becomes true in a form consumer devices can actually honor.

## Idea 3 — chunked storage as proof: proof doesn't come from where bytes live

What makes evidence probative to a future loan agent is exactly three things: **authenticity** (the issuer's signature on the fact — the bank attests the statement), **integrity of history** (the anchored hash chain proving nothing was rewritten — already built, ADR-004), and **selective disclosure** (proving the fact without revealing the rest — Phase 4's ZK/SD machinery). The physical location of the encrypted bytes contributes nothing to any of the three. A copy on the user's own devices plus an encrypted backup is *exactly as probative* as fragments scattered across a thousand strangers' laptops — this is the project's own founding insight ("signatures stop the fudging; a blockchain only kills the middleman") applied to storage. Durability is a *backup* problem with boring, excellent solutions: the blind relay (multi-device doc, Route B), the user's own cloud drive as an encrypted-blob target, a second device. A P2P backup network could someday be one more *optional, user-chosen* backup target — never the default, never load-bearing for proof.

## What this means

- **ADR-004 stands.** Anchor to OpenTimestamps + RFC 3161; visit the notary, never become one. The recommendation against an own chain is not caution — the evidence says an own chain is the *less* trustworthy option for its entire early life, and its sustainable version requires the token we've forsworn.
- **The deferral has a proper future home, recorded now:** at Phase 4 entry, the registry question reopens as *join vs. build vs. overlay* — with the ION/Sidetree overlay (every app an overlay node; security borrowed from Bitcoin; no token) as the leading candidate shape, and institutionally-diverse consortium validators as the fallback. Never all-one-vendor nodes. (Register: Q17.)
- **Watchtower role** goes on the long-term design list: apps verify anchors and audit registries — decentralized verification as the cheap, honest cousin of decentralized storage.
- The loan-agent proof stack is confirmed as: issuer signatures + anchored log + selective disclosure — all independent of storage topology.

## Open questions (register)

- Q17: Phase 4 registry — join an existing utility, run a Sidetree-class overlay on Bitcoin, or consortium chain with institutionally diverse validators? Decide at Phase 4 entry, not before.

## Sources

- [ChainUp: 51% attacks — ETC, Bitcoin Gold lessons](https://www.chainup.com/blog/51-percent-attacks-explained/) · [MIT Tech Review: blockchains getting hacked](https://www.technologyreview.com/2019/02/19/239592/once-hailed-as-unhackable-blockchains-are-now-getting-hacked/) · [Hacken: 51% attack economics](https://hacken.io/discover/51-percent-attack/)
- [CoinDesk: Microsoft ION live on Bitcoin](https://www.coindesk.com/markets/2021/03/25/microsofts-ion-digital-id-network-is-live-on-bitcoin) · [ION repo (Sidetree, no token)](https://github.com/decentralized-identity/ion)
- [Autheo: What happened to Sovrin](https://www.autheo.com/blog/what-happened-to-sovrin-network) · [Sovrin Foundation dissolution](https://sovrin.org/the-sovrin-foundation-has-been-dissolved-but-sovrin-mainnet-remains/) · [ID Tech: MainNet shutdown](https://idtechwire.com/the-community-moved-on-sovrin-announces-mainnets-likely-shutdown/)
- [Storj v3 whitepaper (churn, erasure coding)](https://static.storj.io/storjv3.pdf) · [IPFS docs: comparisons/pinning reality](https://docs.ipfs.tech/concepts/comparisons/) · [arXiv: IPFS opportunities and challenges](https://arxiv.org/pdf/2202.06315)
