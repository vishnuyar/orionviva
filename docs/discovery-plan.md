# Discovery Plan

**Status:** Draft · **Last updated:** 2026-07-19

## Purpose

We are deliberately in a discovery/research phase before writing product code. The goal is to make the expensive decisions (data model, extraction architecture, storage, stack) with evidence rather than momentum. Speed is not the constraint; being right about the load-bearing choices is.

## Phases

**Discovery (now).** Map the landscape: agent frameworks, model capabilities, competitive products, storage/crypto options. Output: the research docs, each with findings and open questions.

**De-risking experiments (next).** The questions that can't be settled by reading get settled by small, throwaway experiments before any product code:

1. **Extraction benchmark** — take 10–20 real statements (author's own, per "first user is the author"), run cloud frontier models vs. the best local VLMs, measure per-figure accuracy and whether stated confidence correlates with correctness. This is the single most important experiment: it grades the hybrid model strategy (ADR-001) and tells us whether local-only is viable sooner than assumed.
2. **Data model spike** — attempt to represent the author's real accounts (bank, cards, brokerage, retirement, loans, property) in one schema; find where the abstraction leaks.
3. **Provenance round-trip** — extract a figure, store it with source + confidence, answer a question citing it, and click through back to the exact source region of the document. If this loop works end-to-end for one number, the architecture is sound.

**Architecture & build plan.** Only after the experiments: pick stack and form factor (the form-factor doc graduates to an ADR), write the v0 architecture doc, start Phase 0 of ROADMAP.md.

## Decisions made so far

- **ADR-001 — Hybrid model strategy** (amended with the domain-model doc specialization flywheel).
- **ADR-002–010 — the one-way doors** (the discovery map): MIT license, raw capture doctrine, append-only anchored event log, encryption from commit one, zero exfiltration, hybrid record identity, promise inventory, DCO, verification-never-in-weights. Full index: [decisions/](decisions/README.md).

## Open questions register

| # | Question | Where it's being worked | Settles when |
|---|---|---|---|
| Q1 | Can any model give *calibrated* per-figure confidence on messy statements, and by what mechanism? | the extraction doc | Extraction benchmark |
| Q2 | Form factor: CLI, local web, or native desktop for v0? | the form-factor doc | After experiments (informed by stack choice) |
| Q3 | Language/stack: Python vs TypeScript (vs Rust core)? | the form-factor doc | After experiments |
| Q4 | Agent harness: Claude Agent SDK vs direct API loop vs framework? | the agent-landscape doc | Architecture phase |
| Q5 | Storage: SQLCipher vs SQLite + file-level encryption; key custody UX | the storage doc | Architecture phase |
| Q6 | How do Era/OpenBudget-style MCP aggregators change positioning — threat, complement, or distribution channel? | the competitive-landscape doc | Ongoing; revisit quarterly |
| Q7 | Account aggregation (Plaid/MX/SimpleFIN) vs document-only for Phase 1 — privacy cost vs coverage | the competitive-landscape doc, future doc | Before Phase 1 |
| Q8 | Local model floor: at what point do on-device VLMs make local-only extraction honest to offer? | agent-landscape + extraction docs | Extraction benchmark, re-run periodically |
| Q9 | Specialization flywheel: how many verified extraction pairs before a personal LoRA beats frontier on the user's own formats? | the domain-model doc | Extraction benchmark baseline, then accumulation |
| Q10 | River AI trajectory: does auditable parametric personalization become viable? | the domain-model doc | Ongoing watch |
| Q11 | Subscription-OAuth for third-party apps (Sign in with Claude/ChatGPT/Gemini): when, and on what terms? | adoption doc | Ongoing watch; gates onboarding rung 2 |
| Q12 | Attested-cloud inference (PCC pattern): compatible with the promise inventory's language? | adoption doc | Dedicated analysis before any such tier is announced |
| Q13 | On-device-class model capability floor (AFM-tier) for zero-setup extraction | adoption doc | Extraction benchmark (include one) |
| Q14 | Blind-relay design: build tiny vs adapt existing E2EE sync; double as backup target? | multi-device doc | Architecture phase |
| Q15 | Browser-rung crypto integrity (signed bundles etc.) + honest caveat wording | multi-device doc | Before any web client ships |
| Q16 | Own-device-hub option (Route A) at v1 or later? | multi-device doc | Architecture phase |
| Q17 | Phase 4 registry: join existing utility vs Sidetree-class overlay on Bitcoin vs diverse consortium chain | own-chain doc | Phase 4 entry, not before |
| Q18 | Internationalization sequencing: which locales after US, and what triggers each (community pack? demand signal?) | design-invariants (I1–I6) | Post-v0; invariants ensure nothing blocks it |
| Q19 | Email capture: local mailbox-watcher design (IMAP/Gmail API/label conventions); hosted forwarding deferred to attested-enclave territory | experience-vision | Architecture phase |
| Q20 | Input-mode benchmark: implement `text` + `text+image`, measure accuracy/recall/cost/provenance vs `image` on real corpus | document-preprocessing | Next viva-bench iteration |
| Q21 | Product local pipeline: which local OCR tool (Marker/Docling/olmOCR/native) for scans | document-preprocessing | Later `parsed`-mode benchmark |
| Q22 | Provenance under text-first: carry tool char/box coordinates as region anchor vs VLM self-reported regions | document-preprocessing | With Q20 |
| Q24 | Own-account registry: how the user's own accounts get fingerprinted; auto-detect internal transfer vs ask | data-model-spike | Architecture phase |
| Q25 | StatementFacts vs Transaction boundary: dividend-as-transaction vs 1099-summary-as-fact must reconcile not double-count | data-model-spike | Architecture phase |
| Q26 | v2 corpus: add monthly mortgage stmt + brokerage positions stmt + insurance declarations to test escrow/holdings/provisions | data-model-spike | Before build v0 |
| Q27 | Double-entry plug postings: how an un-attestable balancing leg is graded and surfaced (never silently balanced) | data-model-spike | Architecture phase |
| Q28 | Spotlighting delimiter spec + a viva-bench red-team mode (inject instruction into a test PDF, confirm it never actuates and is caught) | threat-model | Architecture phase |
| Q29 | Format-commons/knowledge-registry governance: review bar + privacy lint that make contribution safe at scale | threat-model | Community phase (E5) |
| Q30 | Live-session malware: how far OS sandboxing shrinks the unlocked-window exposure per platform | threat-model | Build v0 |
| Q31 | Eval case-set curation: how many adversarial cases, who reviews additions (the eval set needs the two-drafter+audit rigor too) | eval-harness | Build v0 |
| Q32 | Eval alarm thresholds: what confidently-wrong movement blocks a commit vs warns | eval-harness | After frozen-key baseline |
| Q33 | Eval regression triage/attribution: red light points at cause (model/prompt/verify/tool) | eval-harness | Build v0 |
| Q34 | Opening-balance confidence + explaining "unexplained history" (OBE) to a non-accountant without the word equity | individual-as-enterprise | Architecture phase |
| Q35 | How far back the butler pursues history (recency/materiality/goal bounds) without badgering | individual-as-enterprise | Build v0 |
| Q36 | Cash/accrual boundary: which obligations modeled as accrual vs left cash-only | individual-as-enterprise | Architecture phase |
| Q37 | v0 event store engine: encrypted SQLite (SQLCipher) vs append-only encrypted JSONL vs embedded event-store lib | v0-scope | Build step 2 |
| Q38 | v0 double-entry posting shape for a checking statement + Opening Balance Equity seeding | v0-scope | Build step 2 |
| Q39 | v0 minimal viewer tech (plain HTML+JS vs small framework) | v0-scope | Build step 5 |

## Scope note

This plan covers the *current* discovery tracks. The full-scope inventory — every domain needing discovery, and the classification of decisions by reversibility (one-way / sticky / two-way doors) — lives in [the discovery map](discovery-map-and-reversibility.md), which is the master map. The discovery map's sequencing section supersedes the phase list above where they differ.

## Cadence

Landscape docs (01, 04) get refreshed when something material changes — new model generations, new entrants — not on a schedule. The register above is the heartbeat: a question leaves it only via an ADR or an experiment result.
