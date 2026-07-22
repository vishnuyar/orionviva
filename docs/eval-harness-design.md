# Eval Harness Design (A8) — how honesty is measured, continuously

**Status:** Draft · **Last updated:** 2026-07-21 · **Covers:** discovery-map A8. The last discovery design doc.
**Invariants touched:** T1 (every eval case checks a figure *and* its source), T2 (grading is deterministic), T3 (eval runs are captured), X2 (the confidently-wrong rate is the alarm), and it is the enforcement mechanism behind promise #1 ("never bluff a number")
**Related:** [benchmark-harness-design.md](benchmark-harness-design.md) (the one-time exam this reuses), [model-trust-policy.md](model-trust-policy.md) (feedback loop 3).

## What it is, and why it's not the benchmark

The **benchmark** (viva-bench) is a driving test — a one-time exam a *model* sits to earn admission. The **eval harness** is the dashboard warning light — a continuously-running honesty test on the *whole system*, forever after. The benchmark asks "is this model good enough to admit?" The eval harness asks, on every code change, model swap, and schedule tick, "is OrionViva *still* telling the truth today?"

It exists because an AI system's honesty rots **silently**. A button that breaks is obvious; a model update or a refactor that makes Viva confidently wrong about 2% more figures looks like nothing at all. The project's own rule — *an untested trust property doesn't exist* — makes this non-negotiable: the eval harness is how "never bluff a number" becomes a thing measured every day, so a slip triggers an alarm instead of a betrayed user.

## The unit: a canonical eval case

One case is a known-truth expectation the system is asked to satisfy:

```
question:        "What is the closing balance on the March checking statement?"
expected_value:  <the true figure>            # from a frozen key or a user correction
expected_source: {doc, page, region}          # the provenance the answer must cite (T1)
expected_grade:  verified | corroborated | ... # what confidence the system should assign
locale/currency: en-US / USD                   # normalization context (I2)
```

A case checks three things at once, in priority order:
1. **Honesty** — when the system is *wrong or unsure*, does it *say so*? (The load-bearing check.)
2. **Accuracy** — is the figure correct?
3. **Provenance** — does it cite the right source region?

The asymmetry is the whole point: a wrong-but-flagged answer *passes the honesty check* (a bad day, handled); a wrong-but-confident answer *fails it* (the ruin case). The headline metric is the **confidently-wrong rate**, and its target is zero.

## Where cases come from (all near-free, by prior design)

1. **Frozen benchmark keys** — the human-audited answer keys (benchmark-harness) seed the first, highest-quality cases: hundreds of figure+source truths on real documents.
2. **User corrections** — *every* correction is automatically a case: "the system said X, the truth is Y" is exactly a known-truth expectation. The feedback loop that teaches Viva you (the memory moat, trust-policy loop 2) is the *same* machinery that tests her. This is the elegant part: usage generates the test suite for free, and each case is anchored to a real past mistake so the same error can never silently return.
3. **Hand-written adversarial cases** — a small curated set of the hardest, most dangerous questions (multi-currency net worth, a figure from a page with a missing sibling statement, an ambiguous date), plus the **injection tripwire** (threat-model Q28): a case whose document contains a planted instruction, asserting the system never actuates it and grades the poisoned value `conflicted`.

## When it runs

- **On every change to trust-critical code** (verify/, the ledger, the model layer, prompts) — pre-commit and CI. A change that moves the confidently-wrong rate fails the build. This is the adversarial-review policy (ADR-009) given teeth.
- **On every model version change** — a new model or a re-tuned local LoRA re-sits the relevant eval slice before it can serve (trust-policy "every version is a new hire").
- **On a schedule** (nightly) in the product for the author's real instance — catching drift that no code change triggered (a silently-updated cloud model, per T8).

## What it measures (deterministic, reusing viva-bench)

The scorer already exists (benchmark `score.py`): per-case accuracy, provenance validity, and the confidently-wrong rate. The eval harness is mostly *wiring the existing scorer to run continuously against the product's answer path* rather than one-off against raw model output. Outputs a trend line per metric; the alarm is any upward move in confidently-wrong, or a regression past a set band on the others.

**The one genuinely new thing** vs. the benchmark: the benchmark grades *extraction* (document → claims); the eval harness grades *the full answer path* (question → tools → composed answer → cited figure + grade). It tests the twelve-tool agent and the composer's refusal-of-uncited-figures (T1 enforced), not just the reader. So it needs a thin harness that poses a question to the assembled system and inspects the structured answer (figure, grade, source), which only exists once there's a v0 to point at.

## Sequencing (honest about what's buildable when)

- **Now (discovery):** the *design* (this doc) + the *seed corpus* (freeze the benchmark keys). No product to run against yet, so the harness itself waits.
- **Build v0 (Phase IV):** the eval harness runs against the first assembled answer path — and should be wired *before* the first feature is called "done," so honesty is measured from the first commit that answers a question. It is Phase IV infrastructure, not a later add-on.
- **Trust trial (Phase V):** the nightly schedule on the author's real instance; corrections accumulate into the growing case set. This is how "you believe an answer without re-checking it" becomes an *event the harness can witness* (the confidently-wrong rate holding at zero across months of real use) rather than a feeling.

## Consequences for architecture

- The product's answer path must return **structured** answers (figure, grade, source, tools used), not just prose — the eval harness reads that structure, and it's the same structure the UI needs for provenance click-through. One shape serves testing, UI, and honesty.
- Corrections must be stored as **replayable cases** (question + truth + source), not just value overwrites — reinforcing the event-sourced ledger (T4) and the correction-as-event design.
- A frozen, hashed **eval set** ships with the code (the hand-written + benchmark-seed cases; never real personal cases, which stay local like the corpus) so any contributor's change is graded against the same honesty bar — the ADR-009 review policy, automated.

## Open questions (register)

- Q31: Case-set curation — how many hand-written adversarial cases, and who reviews additions (a wrong "expected answer" would erode the bar silently — the eval set itself needs the two-drafter+audit rigor the benchmark keys got).
- Q32: Alarm thresholds — what movement in the confidently-wrong rate blocks a commit vs. warns; needs the frozen-key baseline to set honestly (same "no false precision" discipline as the trust-policy thresholds).
- Q33: Regression triage — when the harness reddens, how the failing case points at the cause (model? prompt? verify rule? tool?), i.e. attribution, so a red light is actionable not just alarming.
