# Model Trust Policy — guardrails, graduated autonomy, feedback

**State:** partial
**Rules:** VOICE-90, VOICE-91, VOICE-92, VOICE-93, VOICE-94, VOICE-95, VOICE-96

## Rules

### VOICE-90 — trust attaches to the system around a model, never to a model
**State:** enforced-with-exception
**Code:** product/viva/tools/runner.py:760, product/viva/ledger/events.py:558
**Test:** product/tests/test_shape.py::test_a_thing_of_the_wrong_kind_cannot_fill_a_hole

1. A model's output becomes a fact in the ledger only after the system has checked it.
2. Models extract, parse and converse; they never certify.
3. Confidence is an output of verification, never a model's self-report.

**Exception:** assertion 3 is true of a figure's *grade* and not of the classify pass. `product/viva/prompts/classify-v2.txt:4` asks the model for `doc_type_confidence`, and `product/viva/ingest/reader.py:256` reads it straight through onto the result. What ING-1 holds is the narrower rule that keeps it safe: that number is stored as a claim and never becomes, gates or modifies any grade ([extraction-and-confidence.md](extraction-and-confidence.md), ING-1).

### VOICE-91 — the model that reads a document has no tools and no write access
**State:** enforced-with-exception
**Code:** product/viva/ingest/reader.py
**Test:** product/tests/test_reader_two_phase.py::test_two_phase_read_records_both_claims

1. The extraction model receives a document and returns structured claims, and nothing else.
2. A poisoned document can therefore only instruct a model incapable of acting.
3. Arithmetic is deterministic.

**Exception:** the second half of what this rule used to claim — that a *missing source citation* triggers refusal — has no machinery. Nothing in `product/viva/ingest/reader.py` or `core/vivacore/verify/` names a citation, a source region or a refusal on its absence; see ING-6's exception, where `Provenance.region` is declared and never populated.

### VOICE-92 — deterministic verification never relaxes
**State:** enforced
**Code:** core/vivacore/verify/arithmetic.py
**Test:** core/tests/test_arithmetic.py::test_balance_identity_catches_one_cent

1. Arithmetic identities, completeness checks and provenance requirements never relax, for any model. (There are no autonomy levels to relax them at: see VOICE-95, unmet.)
2. Only the statistical layers above that floor are ever tunable.

### VOICE-93 — model versions are pinned; no "latest" alias on the trust path
**State:** unmet
**Code:** product/viva/ingest/reader.py:149 (documented, not checked)
**Test:** none

1. A model id used on the trust path names an exact version, never a moving alias.
2. Nothing in code refuses an alias; the rule lives in documentation only.

### VOICE-94 — every version is a new hire
**State:** unmet
**Code:** none found
**Test:** none

1. Any version change — a provider upgrade, a quantization change of a local model, a re-tuned personal fine-tune — enters as a new candidate.
2. It re-sits the admission exam before touching real work at any autonomy level above probation.

### VOICE-95 — autonomy is earned statistically and revoked automatically
**State:** unmet
**Code:** none found
**Test:** none

1. Every model starts on probation with full redundancy, and autonomy is granted only by accumulated measured evidence crossing thresholds — never by enthusiasm or vendor claim.
2. One regression — a verification-failure rate rising above its band — drops a model back to probation automatically, with no meeting and no judgement call.
3. Every grant, revocation and scorecard update is a logged, tamper-evident event, so *"why did you trust this model with that document?"* is always answerable.

### VOICE-96 — every call names its model, and every version resolves
**State:** enforced-with-exception
**Code:** product/viva/versions.json, core/vivacore/promptstore.py:30
**Test:** product/tests/test_prompt_library.py::test_every_version_the_code_can_emit_resolves

1. The model abstraction layer supports per-call model identification and version pinning as hard requirements.
2. Every prompt version the code can emit resolves to the exact bytes that produced a reading.

**Exception:** per-model scorecards do not exist, and a correction is not attributed to a model version (`product/viva/ledger/events.py:355` records only `by`), so the identification exists without the bookkeeping that would use it.

## Why

**We never reach a position of completely believing a model — by design, and
permanently.** Trust never attaches to a model; it attaches to the *system
around* the model: verification, guardrails, feedback loops. Models — today's
commercial ones, open-source ones, future ones, our own fine-tunes — are
brilliant, untrusted workers whose output only becomes a fact after the system
has checked it.

That dissolves the commercial-versus-open-source-versus-future question rather
than answering it. We do not pick whom to believe; we build the machinery that
lets *any* model, including ones that do not exist yet, work on a person's money
safely from its first day. Models are commodities, and this policy is what makes
them safely interchangeable.

**"Never trust" does not mean "always maximum suspicion".** Permanent full
redundancy is wasteful, so the policy is graduated autonomy, like hiring. Every
model starts on probation with full redundancy — N-sample extraction,
cross-model comparison where available, every deterministic check — and that
applies equally to a new frontier release, a new local model, and a personal
fine-tune. As a *measured* track record accumulates, per model and per document
type, the expensive statistical redundancy relaxes. What never relaxes is the
deterministic floor. And revocation is automatic, because a policy that requires
a judgement call to enforce is a policy that gets argued with.

**Three layers of guardrail, doing different jobs.** *Structural* guardrails
bound what a model can do regardless of quality: models extract and converse but
never certify, arithmetic is deterministic, and the extraction model runs with
no tools and no write access — so even a poisoned PDF can only instruct
something incapable of acting. *Statistical* guardrails catch what quality alone
misses: sample disagreement, cross-model agreement, arithmetic identities. These
produce the per-figure grades, and they also produce the per-model scorecards
the policy runs on. *Procedural* guardrails govern models as changing things
rather than fixed choices: cloud providers update models silently, so a model
that earned autonomy in one month is not the model serving in another, and every
version change enters as a new candidate.

**Four feedback loops, all recorded as events.** Verification outcomes — every
check, pass or fail, logged per model and per document type — are the raw
material of scorecards. User corrections are simultaneously a memory-moat entry,
an error attributed to a model version, and a new evaluation case. Continuous
evaluation re-runs on a schedule against known-answer data, catching drift live
use has not surfaced. And the flywheel: verified pairs accumulate into personal
fine-tunes, which enter through the same probation as everyone else — the system
that distrusts models is also the system that manufactures better ones.

**What this makes the benchmark harness.** The extraction benchmark stops being
a one-time exam to crown a winner. It is the permanent admission and monitoring
instrument: the exam every model must pass to work on a person's money, and keep
passing to keep its autonomy. Today's models merely happen to be the first
candidates to sit it. That is why the harness is designed before any statement
is gathered — it will outlive every model it ever grades.

**Consequences for architecture.** Version pinning and per-call model
identification are hard requirements of the model abstraction layer, not
conveniences. Per-model scorecards are projections of the event log, not a
separate bookkeeping system. Autonomy thresholds are configuration rather than
code, tunable as evidence accumulates, with changes logged.

## Open

- Autonomy level definitions and promotion thresholds need the first benchmark's data. Guessing numbers now would be exactly the false precision this policy exists to prevent.
- Scorecard granularity: per document type is clearly right; is per *institution's format* worth the sparsity?
- Drift alarms for pinned models. Pinning stops silent upgrades, but providers retire pinned versions, and the re-admission path for a successor needs design.
- Does graduated autonomy ever justify single-sample extraction for a long-proven model on a routine format, or is N≥2 a permanent floor?
- Nothing in code refuses a moving model alias; the pinning rule lives only in documentation.
- No autonomy ledger, probation state or per-model scorecard exists in the codebase.
- A correction is attributed to a person or a model, but not to a model version, so the second feedback loop cannot yet close.
