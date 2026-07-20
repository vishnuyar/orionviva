# Model Trust Policy — guardrails, graduated autonomy, feedback

**Status:** Draft · **Last updated:** 2026-07-19 · **Prompted by:** Vishnu's question — how do we decide we're at a position to completely believe models; what guardrails; what feedback systems?

## The stance

**We never reach a position of completely believing a model — by design, and permanently.** Trust never attaches to a model; it attaches to the *system around* the model: verification, guardrails, and feedback loops. Models — today's commercial ones, open-source ones, future ones, our own fine-tunes — are brilliant, untrusted workers whose output only becomes a fact in the ledger after the system has checked it.

This dissolves the "commercial vs. open-source vs. future models" question rather than answering it. We don't pick whom to believe; we build the machinery that lets *any* model, including ones that don't exist yet, work on the user's money safely from its first day. Models are commodities; this policy is what makes them safely interchangeable.

## Graduated autonomy — earned statistically, revocable instantly

"Never trust" does not mean "always maximum suspicion" — permanent full redundancy is wasteful. The policy is graduated autonomy, like hiring:

- **Probation (every model starts here).** Full redundancy: N-sample extraction, cross-model comparison where available, every deterministic check. This applies equally to a new frontier release, a new local VLM, and a personal LoRA from the specialization flywheel (ADR-001 amendment).
- **Earned autonomy.** As a model's *measured* track record accumulates — per model, per document type — the system relaxes the expensive statistical redundancy: fewer repeat samples, spot-checks instead of full cross-model comparison. Autonomy levels are granted by accumulated evidence crossing thresholds, never by human enthusiasm or vendor claims.
- **The non-negotiable floor.** Deterministic verification (arithmetic identities, completeness checks, provenance requirements) never relaxes, for any model, at any autonomy level, ever (ADR-010). Only the *statistical* layers above the floor are tunable.
- **Revocation.** One regression — a verification-failure rate rising above its band — drops the model back to probation automatically. No meeting, no judgment call.

The autonomy ledger is itself event-sourced (ADR-004): every grant, every revocation, every scorecard update is a logged, tamper-evident event. Viva can always answer "why did you trust this model with that document?"

## Guardrails — three layers

**Structural** (bound what a model *can* do, regardless of quality):
- Models extract and converse; they never certify (ADR-010). Confidence is an output of verification, not a model's self-report (the extraction doc).
- Arithmetic is deterministic. A missing source citation triggers refusal, not a shrug.
- The extraction model runs with *no tools and no write access* — it receives a document and returns structured claims, nothing else. Even a poisoned PDF (prompt injection, B2 in the discovery map) can then only instruct a model that is incapable of acting.

**Statistical** (catch what quality alone misses):
- Sample disagreement, cross-model agreement, arithmetic identities — the extraction doc's machinery. These produce the per-figure grades; they also produce the per-model scorecards this policy runs on.

**Procedural** (govern models as changing things, not fixed choices):
- **Version pinning.** Cloud providers update models silently; a model that earned autonomy in March is not the model serving in June. Model versions are pinned; an unpinned "latest" alias is never used on the trust path.
- **Every version is a new hire.** Any version change — provider upgrade, quantization change of a local model, a re-tuned personal LoRA — enters as a new candidate and re-sits the admission exam before touching real work at any autonomy level above probation.

## Feedback systems — how the system learns

Four loops, all recorded as events:

1. **Verification outcomes** — every check pass/fail, logged per model, per document type. The raw material of scorecards and autonomy decisions.
2. **User corrections** — each correction is simultaneously a memory-moat entry, an error attributed to a model version, and a new evaluation case. The correction UX (C5) is this loop's front door.
3. **Continuous evaluation (A8)** — the eval harness re-runs on schedule against known-answer data, catching drift that live use hasn't surfaced yet.
4. **The flywheel** — verified pairs accumulate into personal fine-tunes (the domain-model doc), which enter through the same probation as everyone else. The system that distrusts models is also the system that manufactures better ones.

## What this makes the benchmark harness

The extraction benchmark stops being a one-time exam to crown a winner. It is the **permanent admission and monitoring instrument**: the exam every model must pass to work on the user's money, and keep passing to keep its autonomy. Today's models merely happen to be the first candidates to sit it. This is why the harness is designed before any statement is gathered — it will outlive every model it ever grades.

## Consequences for architecture

The model abstraction layer must support version pinning and per-call model identification as hard requirements (extends ADR-001's provider-abstraction requirement). Per-model scorecards are projections of the event log, not a separate bookkeeping system. Autonomy thresholds are configuration, not code — tunable as evidence accumulates, with changes logged.

## Open questions

- Autonomy level definitions and promotion thresholds — need the first benchmark's data to set numbers honestly; guessing them now would be exactly the false precision this policy exists to prevent.
- Scorecard granularity: per document type is clearly right; is per *institution's format* worth the sparsity?
- Drift alarms for pinned models: pinning stops silent upgrades, but providers retire pinned versions — the retirement path (re-admission of the successor) needs design.
- Does graduated autonomy ever justify single-sample extraction for a long-proven model on a routine format, or is N≥2 a permanent floor? (Cost data from the benchmark will inform this.)
