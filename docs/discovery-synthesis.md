# Discovery Synthesis — the whole forest, on one page

**Status:** Stable · **Last updated:** 2026-07-21 · **Purpose:** the map of the forest after ~26 design docs and 10 ADRs, and the honest bridge into the Architecture phase. Read this to see the whole before committing to build.

## The thesis, in three sentences

As intelligence becomes free and the open data commons fills with AI-generated noise, the scarce thing is *provable trust grounded in operational reality*. A person's financial records are the cleanest such reality they own — money moved, a ledger recorded it — so OrionViva turns them into one honest, always-current picture that answers plainly and proves what it stood on. It starts as a butler for one person (the author, with his own money) and is designed toward becoming a trust agent that can vouch for you to others, on your terms.

## What we now *know* (measured, not assumed)

- **Model confidence is noise.** Every model claimed ~90% sure regardless of correctness. Confidence must be *constructed by verification*, never asked of the model. (Benchmark, Q1.)
- **The ruin case is real and catchable.** A weak model read a bank statement 100% wrong, confidently and self-consistently — and the verification layer caught it. The core mechanism works.
- **A cheap, private path exists.** Frontier-blind extraction is ~$3.50/doc; an open model, verified, matched it for $0.07. Text+image page-at-a-time is the ingestion architecture; local models can carry it.
- **The data model holds on real documents.** Double-entry (postings) validated on a real pay stub, a real transfer, and a genuinely multi-currency (US+India) life. P&L and balance sheet fall out as free projections.
- **The design is safe to feed untrusted documents.** The 2026 defense against document prompt-injection (a powerless reader model) is what we already committed to.

## What is locked (the standing decisions)

- **Ten one-way doors** (ADRs 002–010): MIT, raw-capture, append-only anchored log, encryption from commit one, zero exfiltration, hybrid IDs, promise inventory, DCO, verification-never-in-weights.
- **The invariants** (design-invariants.md): trust T1–T8, internationalization I1–I6, experience X1–X3. Every future doc answers to them.
- **The ledger is double-entry**, event-sourced; the confidence grades (`verified`/`corroborated`/`unverified`/`conflicted`) *are* the attested-vs-inferred posting distinction seen twice.

## The architecture's shape already fell out (answering "where does everything sit?")

Discovery didn't just make decisions — it determined the layered shape, because one pattern kept recurring: **universal code + configuration/data + a thin registry.** "Code is universal; everything specific is data" is the product's constitution. So the three probes resolve without new invention:

| Concern | Where it sits | Universal code | Specific-as-data |
|---|---|---|---|
| **Viva's soul** (voice, discretion, when she speaks) | Conversation/composition layer — a **persona config** over the agent runtime. Presentation only; it never touches whether a number is right. | the agent runtime + composer (refuses uncited figures) | the persona/voice profile, versioned (C1/C3, X2) |
| **Prompts per financial type** | Not a code branch per type. A largely **universal extraction prompt** + type/format *hints* pulled from the **type registry** and **format profiles**. | one extraction path, spotlighting delimiters | registry `doc_type → hints`; format-commons pointed questions |
| **Verification rules per type** | Universal deterministic check *functions* (balance identity, sums, completeness) in `verify/`; the **registry** says *which* apply to a type. | the check functions (verify/) | registry `doc_type → applicable checks` |

The layers, top to bottom: **capture surfaces → extraction (model, powerless) → verify/ (deterministic checks selected by registry) → double-entry ledger (event-sourced, reconciled) → projections (accounts, net worth, P&L, coverage) → agent runtime (12 tools) → composer + persona → dashboard/voice.** Every regional or type-specific thing is data in a registry; the code is one universal path. That is why the architecture phase is mostly *drawing the v0 slice through this*, not inventing structure.

## Accepted risks — stated out loud, not buried

- **The whole has never been assembled.** We have validated *pieces* and coherent *design*; the chain extract→verify→ledger→answer has never produced one cited figure end to end. Confidence is in parts, not a working whole. (That is what Build v0 is for.)
- **Viva has no soul yet.** "Keep the soul" is a non-negotiable, and we've built pure skeleton. The persona/voice work is real, on the thinker track, and must not fall off.
- **Demand is a conviction, not a validation.** We've proven *how*, not that a stranger wants it. Deliberate: first user is the author; trust is earned before expansion. An accepted bet, not an oversight.
- **Single-user, single-device, documents-only** for v0 — household, sync, aggregation, and the trust-agent arc are designed toward but not built.

## The one discipline for Architecture

Discovery's job was breadth — mapping the whole territory so no expensive decision is a guess. **Architecture's job is subtraction:** draw the smallest v0 that produces one honest answer, and let everything in the corpus that isn't on that path wait. The failure mode to guard against is adding more clever subsystems instead of narrowing. The first architecture artifact is the v0 scope — the minimal slice — followed by an ADR per sticky-door decision (data model semantics, grade vocabulary, memory, key custody, aggregation) and the two-way doors decided fast (stack, form factor, harness).

**Verdict: discovery is complete. We have enough — and, as important, we know exactly what we don't yet have.**
