# Form Factor & Stack (options, no decision yet)

**Status:** Draft — deliberately undecided · **Last updated:** 2026-07-19 · **Settles:** after de-risking experiments (Q2, Q3)

## Why this is decided last

The experiments (extraction benchmark, data model spike, provenance round-trip) are stack-agnostic and will teach us where the real friction is. Choosing UI technology before knowing what the core needs is optimizing the paint before the engine runs.

## Form factor options

**CLI/terminal first.** Fastest path to a working ingest→verify→ask loop; zero UI investment while the hard problem is unsolved; matches "first user is the author." Cost: "serve, don't overwhelm" and Viva's warmth are hard to embody in a terminal; provenance click-through (see the source region of a figure) is awkward. Verdict: strong candidate for the *experiment phase*, likely wrong for v0-the-product.

**Local web app** (localhost server + browser UI). Easiest UI iteration; chat + document display + click-through provenance are natural; cross-platform free. Cost: "open a browser tab to localhost" is a weaker product feeling; OS integration (keychain, file watching) lives in the server process, which is fine.

**Native desktop (Tauri-class).** Best product feel and OS integration (keychain, file associations, menubar presence — fits the discreet-butler persona); Tauri gives small footprint with a web-tech UI, so a local-web UI can graduate into it. Cost: most build/maintenance surface for one person.

**Emerging leaning:** experiment phase in CLI/scripts → v0 as local web UI → graduate to Tauri shell when the product has earned it. Each stage reuses the previous one's work. But this is a leaning, not a decision.

## Stack options

**Python-centric.** Strongest AI/data ecosystem, fastest experimentation, SQLCipher fine. Weakness: shipping a polished local app to non-developers eventually (packaging pain), UI needs a JS layer anyway.

**TypeScript-centric.** One language across UI + backend; first-class SDKs (including Claude Agent SDK) and MCP tooling; Tauri/Electron-native; good SQLCipher bindings. Weakness: data/ML experimentation is clumsier than Python.

**Rust core + web UI.** Maximum rigor for the trust-critical core (crypto, ledger, verification) — type safety where correctness is a ruin problem. Weakness: slowest iteration, highest cost for a solo builder; premature until the design is stable.

**Split-phase view:** experiments in Python (speed of learning is the only KPI there); product stack chosen afterward with real knowledge. A plausible end-state is TS app + the deterministic verification core kept as a small, ferociously-tested module (whatever the language) — the module where "never bluff a number" lives.

## Decision criteria (agreed now, applied later)

Trust-critical code (verification, crypto, arithmetic) must be boring, testable, and auditable — this outranks developer convenience. One person must be able to maintain all of it. The extraction/model layer must stay provider-swappable. UI must eventually make provenance click-through and honest-uncertainty *visible*, not just present. Simplest thing that works wins ties.

## Open questions

- Q2, Q3 — settle post-experiments via ADR.
- Whether the verification core justifies Rust or just merciless testing in the app language.
- Packaging/distribution story for eventual non-author users (installer, auto-update, code signing) — note now, decide much later.
