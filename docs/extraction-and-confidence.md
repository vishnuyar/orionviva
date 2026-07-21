# Extraction & Calibrated Confidence

**Status:** Draft · **Last updated:** 2026-07-19

## The problem, precisely

The project principles call this "the actual hard problem," and the research confirms it: models systematically *bluff*. OpenAI's own 2025 analysis showed training objectives and leaderboards reward confident guessing over calibrated uncertainty. A model's self-reported "confidence: 0.95" is a generated token, not a measurement. So the design question is not "how do we get the model to tell us how sure it is" — it's "how do we *construct* a trustworthy confidence signal around a model that can't be trusted to report one."

## Signals available, ranked by current evidence

1. **Sample disagreement (self-consistency).** Extract the same document N times (or with varied prompts/models); figures that agree across samples are reliable, disagreement is a direct, mechanical doubt signal. Reported as the most dependable practical signal in 2026. Costs N× inference — acceptable because statements are ingested rarely, not queried rarely. Extraction is where the money goes; queries then run against verified data.
2. **Deterministic cross-checks (the strongest signal, and model-free).** Financial documents are self-auditing: opening balance + transactions = closing balance; line items sum to totals; dates are ordered; a statement's closing balance should equal the next month's opening. Every check that passes is *proof*, not inference. This is our structural advantage — most extraction domains have no arithmetic ground truth; ours is saturated with it.
3. **Cross-model agreement.** Two different model families agreeing is stronger than one model agreeing with itself (self-consistent errors are a documented failure mode — "too consistent to detect").
4. **Structured-output discipline.** Schema-required `source` (page/region) and `confidence` fields; empty source triggers a refusal path in application code, never a shrug in the answer.
5. **Token logprobs / post-hoc calibration** (temperature scaling, isotonic regression). Useful later, once we have accumulated ground truth to calibrate against; not a v0 dependency.

## Working architecture hypothesis

**Extract → verify → reconcile → store, with confidence as an output of verification, not of the model.**

- Extraction (model): document → structured records, each with claimed source region.
- Verification (deterministic code): arithmetic identities, cross-sample agreement, cross-statement continuity. Produces a per-figure confidence *grade* — e.g., `verified` (passed arithmetic identity), `corroborated` (multi-sample/multi-model agreement, no identity available), `unverified` (single extraction, no check possible), `conflicted` (checks failed — surfaced to user, never silently stored).
- Storage: figure + source pointer + grade + verification trail. The trail is what lets Viva say *why* it's sure, not just that it is.
- Answering: deterministic arithmetic over stored figures; the answer inherits the *weakest* grade of any figure it stands on, and says so in plain language.

The user-facing principle: confidence language in answers maps 1:1 to verification grades. "I'm sure" is only ever backed by `verified`. That's how "never bluff a number" becomes an enforced invariant instead of a prompt instruction.

## What discovery must test (feeds experiment 1)

- Do arithmetic identities actually cover most figures on real statements, or is coverage patchy (e.g., brokerage statements with implied but unstated totals)?
- How often do N samples agree on a *wrong* figure (the scary case)? Cross-model disagreement rate on those?
- Can models reliably report source regions (page + bounding area) for click-through provenance?
- Cost/latency of N-sample extraction per statement at current API prices — what N buys what error rate.

## First measured finding (2026-07-21, viva-bench bake-off)

**Cross-model agreement must be matched on VALUE + POSITION, not on model-generated
labels.** The first key-drafting pass merged two frontier drafters' claims by
`(type, normalized label)`. It reported only ~21% agreement (55 of 266 claims on
the Fidelity 1099) — alarming, until inspection showed it as an *artifact of
labelling*, not disagreement: Claude writes `"<ticker> proceeds"` where Gemini writes
`"proceeds"`, so identical values land in different buckets and count as
conflicts. Re-matched by value (the Decimal-exact verifier), the same two models
agree on **99–100%** of amounts. Consequence for the product's claims layer and
answer-key design: **a claim's identity is its (value, page, region), and its
label is a free-text annotation, never a join key.** Matching on labels
manufactures false conflicts and would bury the human auditor in phantom work.
Recorded here because it directly shapes the "structured-output discipline" and
"cross-model agreement" signals above.

_(Second-order: on the corroborated subset, both frontier models score ~100%
recall in every input mode; the only real discrimination is among small/open
models, and at N=1 it is directional, not conclusive — a full N=5 run is needed
before any accuracy verdict. See docs/document-preprocessing.md for the mode
results.)_

## Open questions

- Q1 (the register's headline question) — everything above is hypothesis until the benchmark runs.
- Human-in-the-loop design: `conflicted` and `unverified` figures need a graceful correction UX; corrections are also the seed of the personal memory moat.
- Does the confidence grade vocabulary above survive contact with real documents? Keep it small either way.

## Sources

- [Lakera: LLM hallucinations 2026 guide](https://www.lakera.ai/blog/guide-to-hallucinations-in-large-language-models)
- [FutureAGI: reducing hallucinations, structured-output patterns](https://futureagi.com/blog/taming-hallucination-beast-strategies-reliable-llms/)
- [Too Consistent to Detect: self-consistent errors in LLMs](https://arxiv.org/pdf/2505.17656)
- [BaseCal: unsupervised confidence calibration](https://arxiv.org/pdf/2601.03042)
- [Calibrating LLM confidence via perturbed representation stability](https://arxiv.org/pdf/2505.21772)
