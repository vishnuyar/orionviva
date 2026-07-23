# Verification Findings & Correction — how the hard cases are handled (and how they build the moat)

**Status:** Design (architecture phase) · **Last updated:** 2026-07-22 · **Origin question:** when a statement fails verification — a misread figure, a missed transaction, or a document that isn't a statement at all — do we make more model calls, guess, or ask the user? And how does the answer ripple into every later slice?
**Invariants touched:** T1 (the best "ask" is the source, cropped to the exact spot), T2 (verification localizes failure, it doesn't just detect it), T4 (corrections are events; nothing is overwritten), T7 (completeness/coverage stated honestly), X2 (answers say what they stand on). Serves principles P1 (trust earned on the hard cases), P2 (never bluff a number), P6 (you pace it), P7 (autonomous where safe, deferential where it counts).

## The situation

Upload seven checking statements. Five reconcile and post silently. Two fail — either they aren't statements, or they are but a figure was misread or a transaction missed. **The five easy ones win no trust; the two hard ones are the entire game.** This document is the standing design for the two, and the contract it sets is inherited by every document type we ever add.

## The core principle: never "more calls vs. guess" — a cheap-first escalation ladder

The instinctive framing ("make more model calls, or guess and ask") skips the most important and cheapest move. The real shape is three rungs, climbed only as far as needed:

**Rung 0 — deterministic diagnosis. Zero model calls.** A reconciliation failure's *delta* is highly informative. A 9-cent gap is not "wrong document"; it is a digit misread or transposition. Arithmetic localizes it:
- Does the delta equal a transaction amount? → a missed or duplicated line.
- Is the delta a multiple of 9? → a classic digit transposition.
- **The running-balance column is a second, independent identity.** Most checking statements print a running balance per line: `prev_balance ± amount = this_line's_balance`. Walking it pinpoints the *single* row where the chain breaks, and the value that would repair it. A correction the running balance *forces* is **not a guess — it is arithmetic**, and when the repaired value also closes the opening→closing reconciliation, two independent identities agree on it.

**Rung 1 — targeted, bounded re-read. One cheap model call, only where doubt was localized.** If diagnosis narrows it to "the amount on line 14," we re-read *only that region* (the cropped line), ideally with a second/cheaper model, and check it against the deterministic implication. This is the cross-model-corroboration pattern from the answer-key builder, reused. **Hard cap: one repair pass.** We never re-read the whole document hoping it comes out consistent — unbounded retry-with-mutation is precisely how a system converges on a confident *wrong* answer, the one failure a trust product cannot survive.

**Rung 2 — the human, asked well.** Only what survives Rungs 0–1 reaches the person, and the *quality of the ask* is everything: "Your December statement is off 9¢ — most likely line 14 (Starbucks, I read $45.67; your running balance implies $45.76). Is it $45.76?" One tap. The person does the minimum irreducible judgment, never re-keys a statement.

## The line through "never bluff a number"

Presenting a value *as a fact* because it makes things reconcile is the forbidden ruin case. Presenting it *as a clearly-labelled hypothesis requiring confirmation*, with its evidence, while nothing enters the trusted ledger until confirmed-or-forced, is deferral, not bluffing. The distinction is load-bearing and is encoded in the finding's **status**:

- **forced** — a correction implied by an *independent identity* (the running-balance chain), and which also closes the reconciliation. Safe to auto-apply, at grade `corroborated` (two identities agree — not `verified`, which is reserved for human attestation), and **always reported** so the person can catch a bad auto-fix.
- **suggested** — a correction a *heuristic* proposes (transposition, delta-matches-a-line). **Never auto-applied.** Surfaced to the human — and shown *against the source pixels*, not led by our number, to avoid anchoring the person into rubber-stamping our guess.
- **unlocalized** — the delta has no clean explanation. Likely not this document type at all → reclassify, don't correct.

A "forced" correction that is really a heuristic misfire would post a wrong number at `corroborated` — so the forced-vs-suggested boundary is a **trust boundary**, and the diagnosis rules are deterministic and **versioned** (like the normalization `RULES_VERSION`) so a verdict can always explain and reproduce itself.

## The "not a statement" branch

Some failures are classification misses, not extraction errors, and reconciliation catches them naturally (no coherent opening/closing/transactions). The response is *reclassify*, not correct: "I don't think this is a checking statement — looks like a pay stub. I've held it. What is it?" The person's answer is a labelled example (see the flywheel), and a "no, it really *is* a checking statement" is a loud signal that our read is weak on *that issuer's format* — a direct feed into the format-profile work.

## Why this is an asset, not a cost: correction-as-event and the flywheel

Every confirmation or forced fix is an **event on a fact** (T4 — nothing overwritten; the full history model-asserted → checks-ran → human-ruled is replayable). It does three things at once:

1. **Fixes this statement** — the corrected figure posts (human-confirmed → `verified`, the highest grade; identity-forced → `corroborated`).
2. **Becomes a training pair** — `(model read X, truth is Y, on this doc-type/format)` — the eval seed and eventual few-shot / fine-tune material.
3. **Teaches Viva about this user and this format** — the moat. The next statement of the same shape pre-empts the same misread.

The hard cases are the *only* place the product learns. A system that never had to ask would never get better at your documents.

## Model-call economics

- **Cost scales with difficulty, not volume.** The five that reconcile cost one read each, forever. Only failures incur repair calls, and only after free diagnosis fails to force an answer.
- **Cheap-first.** The benchmark established that cheap models compete and text+image is the default — so targeted re-reads use a cheap model and second-model cross-checks are near-free.
- **Bounded, never open-ended.** One repair pass, one localized region. Deferring automated re-read (Rung 1) keeps the cost curve flat as document volume grows — exactly what the near-zero-cost, fully-local ingestion endgame needs.

## How this ripples into future slices (the reason to get it right once)

1. **The finding shape is a universal contract.** The gate returns a *structured diagnosis* (which identity failed, delta, localized region, forced/suggested/unlocalized, confidence). Every future document type plugs its own identities into the same shape — pay stub (`gross − deductions = net`), brokerage (`positions × price + cash = total`), 1099 (box sums). The escalation ladder is universal code; the per-type checks are **registry data**.
2. **Correction-as-event is the single spine under all future human teaching.** "That figure is 45.76 not 45.67," "that Uncategorized leg is Groceries," "these two lines are the same transfer" are the *identical mechanism* — a graded correction event on a fact. Built for amounts here, it is reused verbatim for categorization, tagging, and transfer-linking. HITL-for-amounts now *is* the categorization-correction engine later.
3. **The moat compounds from the first hard statement.** Corrections carrying `(model-said, truth-is, doc-context)` start the training-pair mine immediately; the later NL-agent and persona slices train and evaluate against a growing corpus of *real corrections on this user's documents*.
4. **The confirmation surface becomes an agent primitive.** "Confirm this reading," "which category?", "same money?" are one interaction — show source → collect graded confirmation → emit correction event. The conversational agent *composes* this primitive; it does not rebuild it. It is the same surface as tap-to-source (T1): HITL and provenance are one system, and the Step-5 viewer is the correction surface.
5. **Autonomy calibration gets its boundary.** "Post when it reconciles, ask when it doesn't" is the concrete seed of P7's graduated autonomy. Every future autonomous action — recategorizing, drafting a budget, flagging a fee — calibrates against the same "checks-passed-and-low-stakes → act; else → ask" boundary, with the finding's confidence as the dial.

## What v0 builds now, and what it defers

**Now (headless, model-light, tested):** running-balance extraction (the second identity); deterministic diagnosis producing the typed `ReconciliationFinding` (forced / suggested / unlocalized), versioned; **forced** corrections auto-applied at `corroborated` and reported; **suggested/unlocalized** held with their finding, never posted. No repair model calls.

**With Step 5 (the viewer = correction surface):** the human confirmation flow — show the source crop, collect the ruling, emit the correction event at `verified`.

**Later slice:** Rung 1 (automated targeted re-read — the first *repair* model call), added once the human-ask rate justifies the plumbing and spend.

_This design may graduate to an ADR once the finding shape has proven itself across a second document type._
