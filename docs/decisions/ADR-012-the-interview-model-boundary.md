# ADR-012 · The Interview's Model Boundary — what may cross when Viva asks the next question

_This records reasoning, not current behaviour._

**Status:** Accepted · **Date:** 2026-08-01 · **Decided by:** Vishnu · **Binds:** the interview's second cycle, before a line of it is written · **Door type:** the envelope whitelist is one-way in trust (the first interview call carrying an amount breaks promise 4 whether or not anyone notices); the selection mechanism is two-way

**State:** design-only
**Rules:** ADR-012
**Invariants touched:** T2, T3, T6, T8, T9, X2, X3, I5, I6

## Rules

### ADR-012 — Two enumerated outbound flows, a whitelisted envelope, and a model that selects and words but never decides
**State:** unmet
**Code:** none found (the deterministic baseline of assertion 14 is product/viva/interview.py:164)
**Test:** product/tests/test_interview.py::test_a_jurisdiction_scoped_question_does_not_travel (the deterministic baseline of assertion 14 only; no test reaches the enumerated flows or the envelope whitelist)

1. Two outbound flows exist in the interview path and no third: the schema request, and the interview envelope. Any further model call requires an amendment here.
2. The envelope is a whitelist enforced in code rather than a convention described in prose. Permitted: the schema id and version and the interview's kind; the merchant category and the implied relationship, never the raw descriptor; recurrence count and cadence; the jurisdiction tag; which attribute keys are filled and which are blank, names only and never values; this interview's own questions and the person's verbatim answers to them.
3. Structurally excluded from the envelope: amounts and currency, balances, account numbers or names, dates of individual movements, other accounts, any attribute value, and any read of the ledger outside this interview.
4. The schema request carries no vault data at all — the kind, the jurisdiction tag, the pack version — and a generated schema inherits the commons lint before any sharing (T9).
5. The model's reply is untrusted input: a question key not in the schema is dropped and the deterministic next-essential-by-consequence renders instead.
6. Generated wording passes a no-new-facts validator — every figure, merchant and claim in the sentence is present in the envelope — and a failure renders the pack template.
7. The model selects a key and writes a sentence, and nothing else. It never supplies a value, picks an account, emits a figure or writes anything.
8. Answers continue through interpretation, then Proposal, then explicit confirmation, then deterministic apply (X3).
9. One call per explicit person-action. No prefetch, no background warming, no batch pre-generation across the vault, no timer.
10. Every call is captured verbatim and versioned in the claims layer under `phase="interview"`, stamped with prompt version and model (T3).
11. A generated schema is an artifact rather than a runtime answer: written to the pack, flagged unreviewed, asked from immediately, promoted on review.
12. Both flows appear in the outbound record with the envelope inspectable.
13. A whitelist test fails the build if any field outside assertion 2 can reach the envelope.
14. The deterministic baseline ships first, and this mechanism has to beat it on measured grounds.

This record binds a cycle that has not started. There is no model call anywhere in the interview path, no envelope, no whitelist, no whitelist test and no `phase="interview"` capture — `product/viva/interview.py` is the deterministic walk of assertion 14 and reads no model. Only assertion 14's baseline exists (product/viva/interview.py:164).

## Why

Every question in the product was single-turn by construction. A tier-2 proposal opened with an informed sentence and offered two buttons; a yes applied. There was no second question anywhere in the queue, because a `Question` had no next step. That is the whole of what "it feels like a list of buttons" describes, and no amount of better wording addresses it.

The fix is a new primitive: an interview, where the next question follows from the last answer. Something has to decide what that next question is. A schema pack — versioned, reviewable, jurisdiction-tagged, impersonal — enumerates every question that may ever be asked for a kind, with essentials marked, and that closed vocabulary is what makes it safe for a model to choose *within* it.

Choosing within it requires the model to know something about the situation, and that is new outbound traffic. T6 says new outbound bytes of any kind are a decision with an ADR and a promise check, never an implementation detail.

The two flows carry very different privacy weight. The schema request happens once per previously-unseen kind and is impersonal by construction. The interview envelope happens per person-action and is personal in one field only, and the whole design exists to keep it that way. Neither changes the recipient: both go to the same user-configured provider, client to provider.

**Deterministic selection only, with no outbound call**, is not rejected — it is adopted as the baseline that must be built first and that this mechanism has to beat on measured grounds. Its weakness is real: a rigid order, and no recovery from an answer the schema did not anticipate.

**Enrichment-time generation only** — putting every scrap of interview intelligence into the cached schema and walking it deterministically forever — is the cheapest possible posture and remains the *majority* of the intelligence here. It is rejected as the whole answer because which question comes next, and how it is worded, genuinely depend on what this person just said, which no artifact cached before they said it can know.

**A free conversation loop carrying ledger context** is rejected. An unbounded envelope defeats the whitelist that makes this decision small; a growing transcript makes `prompt_version` stop meaning "what produced this reading"; and an open loop has no terminating condition, which is both the never-a-chat-agent boundary and, in practice, the phantom-account ruin case — inventing structure where none exists, across a whole vault.

**A local model for selection** is deferred rather than rejected, and recorded so this does not read as a permanent cloud commitment. A competent local selector removes the outbound question entirely and is the preferred destination.

On promises: promise 1 is intact structurally, because the validator rejects a generated question containing any fact absent from the envelope and the template renders instead. Promise 3 is intact — nothing is hosted, and the envelope carries no key material, no account, no balance. Promise 4 is honored by three things together: enumeration, the no-speculative-call rule, and the outbound record; this adds a new outbound *flow* and no new class of recipient. Promise 8 is intact, because the interview proposes and Proposal remains the only path to a change. No promise is added or amended.

Adopting this without the deterministic baseline would make "the model asks better questions" unfalsifiable, which is the failure mode the project's method exists to avoid. A policy this important is not left to review, which is why the whitelist is a build-failing test rather than a convention.

## Would reverse this

The **envelope whitelist** is one-way in trust: removing a field is free, adding one is an amendment here, deliberately, in the open.

The **selection mechanism** is two-way and cheaply so. The deterministic walk never goes away, so falling back is a switch rather than a rewrite. Moving selection to a local model reverses the outbound flow altogether, and is the reversal this record would most like to be reversed by.

## Open

- Nothing governed by this record is built: no envelope, no whitelist test, no interview model call, no `phase="interview"` capture.
- The eval gains an interview subject when the mechanism ships — questions-to-settle, essential blanks left unfilled, off-schema selection rate, the standing confidently-wrong headline, and how often the validator refuses. A validator that never refuses is not validating.
- The outbound-record surface would need a row type, and the threat-model page an honest line: the person's own sentences, and the shape of their interview, reach the model provider.
- If the schema pack is ever shared, generated schemas are a new artifact class needing the T9 lint before publication.
