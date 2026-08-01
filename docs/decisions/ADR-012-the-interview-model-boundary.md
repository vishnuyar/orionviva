# ADR-012 · The Interview's Model Boundary — what may cross when Viva asks the next question

**Status:** Accepted · **Date:** 2026-08-01 · **Decided by:** Vishnu · **Binds:** the interview's second cycle, before a line of it is written · **Door type:** the envelope whitelist is one-way in trust (the first interview call carrying an amount breaks promise 4 whether or not anyone notices); the selection mechanism is two-way
**Invariants touched:** T2 (a model may perceive and infer; deterministic code decides and posts) · T3 (raw capture) · T6 (nothing leaves silently) · T8 (models pinned, provider-swappable, never trusted) · T9 (the personal/impersonal boundary at package edges) · X2 · X3 · I5/I6

## Context

Every question in the product today is single-turn by construction. The tier-2
proposal opens with an informed sentence — the count, the money, the relationship,
and an ask sentence a model wrote at enrichment — and then offers two buttons.
A yes applies. There is no second question anywhere in the queue, because
`Question` has no next step. That is the whole of what "it feels like a list of
buttons" describes, and no amount of better wording addresses it.

The fix is a new primitive: an interview, where the next question follows from
the last answer. Something has to decide what that next question is. A schema
pack — versioned, reviewable, jurisdiction-tagged, impersonal — enumerates every
question that may ever be asked for a kind, with essentials marked. That closed
vocabulary is what makes it safe for a model to choose *within* it.

Choosing within it requires the model to know something about the situation, and
that is new outbound traffic. T6 says new outbound bytes of any kind are a
decision with an ADR and a promise check, never an implementation detail. This
ADR is that decision.

Two flows arise, and they have very different privacy weights:

- **The schema request** — once per previously-unseen asset or liability kind, to
  draft that kind's schema. Impersonal by construction.
- **The interview envelope** — per person-action inside an interview, to select
  and word the next question. Personal in one field only, and the whole design
  below exists to keep it that way.

Neither changes the recipient: both go to the same user-configured provider under
ADR-001/T8, client to provider, as the existing `interpret` call already does.

## Decision

1. **Two outbound flows, both enumerated, and no third.** Any further model call
   in the interview path is out of scope for this ADR and requires an amendment.

2. **The envelope is a whitelist enforced in code, not a convention described in
   prose.** Permitted, and nothing else:
   - the schema id and version, and the interview's kind
   - the merchant **category** and the implied relationship — never the raw
     descriptor
   - recurrence count and cadence
   - the jurisdiction tag
   - which attribute keys are **filled** and which are **blank** — names only,
     never values
   - this interview's own questions, and the person's verbatim answers to them

   Structurally excluded: **amounts and currency** (Vishnu, 2026-08-01 — the count
   is what makes a question feel informed; the money adds nothing to selection and
   is the most sensitive field in the envelope, and the jurisdiction tag already
   carries what currency would have told the phrasing), balances, account numbers
   or names, dates of individual movements, other accounts, any attribute *value*,
   and any read of the ledger outside this interview.

3. **The schema request carries no vault data at all** — the kind, the
   jurisdiction tag, the pack version. It is impersonal by construction and
   therefore T9-safe in the same way enrichment is; a generated schema is a
   candidate commons artifact and inherits the commons lint before any sharing.

4. **The model's reply is untrusted input.** A returned question key that is not
   in the schema is dropped and the deterministic next-essential-by-consequence
   renders instead. Generated wording passes the no-new-facts validator — every
   figure, merchant and claim in the sentence must be present in the envelope —
   and a failure renders the pack template. This is the discipline `interpret`
   already applies to legs, pointed at questions.

5. **The model selects a key and writes a sentence. That is all.** It never
   supplies a value, picks an account, emits a figure, or writes anything. Answers
   continue through `interpret` → Proposal → explicit confirmation → deterministic
   apply, so X3 stays a property of the type rather than a rule to remember.

6. **No speculative calls.** One call per explicit person-action — opening an
   interview, submitting an answer. No prefetch of the next question, no
   background warming, no batch pre-generation across the vault, no timer. This is
   what keeps promise 4's *user-initiated* wording literally true rather than
   nearly true.

7. **Every call is captured and versioned.** Envelope and reply stored verbatim in
   the claims layer under `phase="interview"`, stamped with prompt version and
   model, so a stored interview resolves to the exact instructions that produced
   it — and so the eval corpus accrues at zero marginal cost, as it does for every
   other model surface.

8. **A generated schema is an artifact, not a runtime answer.** It is written to
   the pack, flagged unreviewed, asked from immediately, and promoted on review.
   Early schemas are read by the author; the review requirement relaxes as the
   surface earns it, on the standing probation pattern rather than by default
   (Vishnu, 2026-08-01).

9. **The outbound record shows both flows.** Promise 4 requires the product to
   display a complete account of everything that has ever left; interview calls
   appear there with the envelope inspectable, so a person can read exactly what
   was sent — ADR-006's diagnostics-bundle rule applied to a live path.

## Promise-compatibility analysis

- **Promise 1 — never bluff a number.** Intact, and structurally: the validator
  rejects a generated question containing any fact absent from the envelope, and
  the template renders instead.
- **Promise 3 — your data and keys stay with you.** Intact. Nothing is hosted; the
  envelope carries no key material, no account, no balance.
- **Promise 4 — nothing leaves silently.** Honored by three things together:
  enumeration (two flows, whitelisted), the no-speculative-call rule, and the
  outbound record. **This adds a new outbound *flow*; it adds no new class of
  recipient.**
- **Promise 8 — nothing irreversible without your explicit yes.** Intact. The
  interview proposes; Proposal remains the only path to a change.

No promise is added or amended by this ADR.

## Alternatives considered

**Deterministic selection only — no outbound call.** Not rejected: adopted as the
baseline that must be built first and that this mechanism has to beat on measured
grounds. Its weakness is real — a rigid order, and no recovery from an answer the
schema did not anticipate ("no, it's my brother's house, I just pay the EMI").

**Enrichment-time generation only** — put every scrap of interview intelligence
into the cached schema and walk it deterministically forever. This is the cheapest
possible T6 posture and it remains the *majority* of the intelligence here.
Rejected as the whole answer because which question comes next, and how it is
worded, genuinely depend on what this person just said — which no artifact cached
before they said it can know.

**A free conversation loop carrying ledger context.** Rejected. An unbounded
envelope defeats the whitelist that makes this decision small; a growing
transcript makes `prompt_version` stop meaning "what produced this reading"; and
an open loop has no terminating condition, which is both the *never a chat agent*
boundary and, in practice, the phantom-account ruin case — inventing structure
where none exists, across a whole vault.

**Local model for selection.** Deferred, not rejected, and recorded so this ADR
does not read as a permanent cloud commitment: a competent local selector removes
the T6 question entirely and is the preferred destination. The flip-to-local bar
is already a standing watch item.

## Consequences

- A **whitelist test that fails the build** if any field outside §2 can reach the
  envelope — the same shape as the guard that keeps prompt text out of code. A
  policy this important is not left to review.
- **Cycle 1 must ship first.** Adopting this without a deterministic baseline
  makes "the model asks better questions" unfalsifiable, which is the failure mode
  this project's method exists to avoid.
- The eval gains an interview subject: questions-to-settle, essential blanks left
  unfilled, off-schema selection rate, and the standing confidently-wrong
  headline. Per the recent bench lesson, **it must also measure how often the
  validator refuses** — a validator that never refuses is not validating.
- The claims layer gains `phase="interview"`; raw-capture rules bind (never delete
  a capture, never drop `prompt_version` or `model`).
- The outbound-record surface gains a row type, and the threat-model page gains an
  honest line: the person's own sentences, and the shape of their interview, reach
  the model provider.
- If the schema pack is ever shared, generated schemas are a new artifact class
  and need the T9 lint before publication.

## Would reverse this

The **envelope whitelist** is one-way in trust. Removing a field is free; adding
one is an amendment to this ADR, deliberately, in the open.

The **selection mechanism** is two-way and cheaply so: the deterministic walk
built in cycle 1 never goes away, so falling back is a switch rather than a
rewrite. Moving selection to a local model reverses the outbound flow altogether,
and is the reversal this ADR would most like to be reversed by.
