# Verification Findings & Correction — how the hard cases are handled (and how they build the moat)

**State:** partial
**Rules:** ING-60, ING-61, ING-62, ING-63, ING-64, ING-65, ING-66
**Invariants touched:** T1 (the best ask is the source, cropped to the exact spot), T2 (verification localizes failure, it does not merely detect it), T4 (corrections are events; nothing is overwritten), T7 (completeness stated honestly), X2 (answers say what they stand on). Serves the principles that trust is earned on the hard cases, that a number is never bluffed, that the person sets the pace, and that autonomy is graduated.

## Rules

### ING-60 — Diagnosis is deterministic and costs no model call
**State:** enforced
**Code:** product/viva/ingest/diagnose.py:65 (`diagnose`), :116 (`_via_running_balance`)
**Test:** product/tests/test_diagnose.py::test_forced_amount_misread_from_running_balance, product/tests/test_diagnose.py::test_suggested_transposition_multiple_of_nine

1. A reconciliation failure is localized by arithmetic alone before anything else is tried.
2. The printed running-balance column is a second, independent identity, walked to find the single row where the chain breaks and the value that would repair it.
3. A delta equal to a line's amount localizes to that line; a delta that is a multiple of nine cents is read as a transposed digit.

### ING-61 — A finding is forced, suggested, or unlocalized
**State:** enforced
**Code:** product/viva/ingest/diagnose.py:31-34, :37 (`ReconciliationFinding`)
**Test:** product/tests/test_diagnose.py::test_unlocalized_when_no_clean_explanation, product/tests/test_diagnose.py::test_multiple_broken_rows_is_not_forced

1. **forced** — a correction an independent identity implies, which also closes the opening-to-closing reconciliation.
2. **suggested** — a correction a heuristic proposes.
3. **unlocalized** — the delta has no clean explanation.
4. The finding names which identity failed, the delta, the locus, the observed value, the implied value, and its own confidence.

### ING-62 — A forced correction auto-applies at `corroborated` and is always reported
**State:** enforced
**Code:** product/viva/ingest/statement_projector.py:184 (apply the forced correction and re-check), product/viva/ingest/pipeline.py:87 (`_apply_forced`), product/viva/ingest/statement_projector.py:361 (the grade)
**Test:** product/tests/test_pipeline.py::test_forced_correction_auto_applies_and_posts

1. A forced correction is applied only if the corrected statement then reconciles.
2. It posts at `corroborated`, because two identities agree — agreement is not attestation (ING-3).
3. The correction is reported on the result, so a bad auto-fix is visible rather than quiet.

### ING-63 — A suggested or unlocalized finding never posts
**State:** enforced-with-exception
**Code:** product/viva/ingest/statement_projector.py:198-208 (hold, persist the finding, return CONFLICT)
**Test:** product/tests/test_pipeline.py::test_unforced_conflict_carries_a_finding, product/tests/test_review.py::test_failed_statement_is_held_and_listed

1. A statement whose finding is suggested or unlocalized is held with its finding and is not posted.
2. A suggested correction is shown against the source rather than led by our number.

**Exception:** cross-document corroboration runs before the hold. `product/viva/ingest/statement_projector.py:197` calls `_try_corroboration` whatever the diagnosis said; where a counterparty document closes the gap exactly, that path discards the suggested or unlocalized finding, synthesizes a `cross_document` finding at `FORCED`, and posts (pipeline.py:386-397). The hold at :198 is what happens when corroboration returns nothing. So the rule reads: never posts *unless a second document supplies the leg* (MON-63).

### ING-64 — The diagnosis rules are versioned
**State:** by-review
**Code:** product/viva/ingest/diagnose.py:28 (`DIAGNOSIS_VERSION`), :49 (carried on every finding)
**Test:** none

1. Every finding carries the version of the rules that produced it, so a verdict can explain and reproduce itself.

### ING-65 — Repair is bounded
**State:** enforced-with-exception
**Code:** product/viva/ingest/statement_projector.py:154 (`post_statement` makes no model call), product/viva/ingest/reader.py:177 (`read_with_retry`, `max_retries=1`)
**Test:** product/tests/test_reader_retry.py::test_gives_up_after_the_retry_and_parks

1. The whole document is never re-read in the hope that it comes out consistent.
2. A parse failure is re-asked at most once, and the second failure parks the document rather than trying again.

**Exception:** the targeted re-read — one cheap model call over the cropped region doubt was localized to — is not built. `product/viva/ingest/statement_projector.py:154` goes straight from deterministic diagnosis to cross-document corroboration to the hold, with no repair model call anywhere. The one-repair-pass cap is therefore satisfied vacuously.

### ING-66 — A correction is an event, and a human ruling grades highest
**State:** enforced
**Code:** product/viva/ledger/events.py:228 (`correction_applied`), product/viva/ingest/review.py:188 (`post_statement(..., confirmed_by="human")`), product/viva/ledger/projection/core.py:355
**Test:** product/tests/test_review.py::test_human_correction_posts_at_verified, product/tests/test_review.py::test_correction_that_still_fails_is_re_held

1. A ruling is appended as a correction event; nothing is overwritten and the full history stays replayable.
2. The corrected statement re-enters the same reconciliation gate, and is held again if it still does not hold.
3. A statement whose reading a person confirmed posts at `verified`: the issuer attests the figure, and the confirmation settles how it was read (ING-3).

## Why

Upload seven statements. Five reconcile and post silently. Two fail — either
they are not statements, or they are and a figure was misread or a line missed.
**The five easy ones win no trust; the two hard ones are the entire game.** This
is the standing design for the two, and the contract it sets is inherited by
every document type ever added.

The instinctive framing — "make more model calls, or guess and ask" — skips the
cheapest and most important move. The real shape is a ladder climbed only as far
as needed.

**Rung 0 is deterministic diagnosis, at zero model calls.** A reconciliation
failure's *delta* is highly informative. A nine-cent gap is not "wrong
document"; it is a digit misread. Arithmetic localizes it: a delta equal to a
transaction's amount means a missed or duplicated line; a delta that is a
multiple of nine is the classic signature of transposed digits. Best of all,
most checking statements print a running balance per line, which is a second and
independent identity — walking it pinpoints the single row where the chain
breaks and the value that would repair it. A correction the running balance
*forces* is not a guess, it is arithmetic, and when the repaired value also
closes the opening-to-closing reconciliation, two independent identities agree
on it.

**Rung 1 is a targeted, bounded re-read** — one cheap model call, only over the
region doubt was localized to, checked against the deterministic implication.
The hard cap is one repair pass. Re-reading the whole document hoping it comes
out consistent is precisely how a system converges on a confident *wrong*
answer, which is the one failure a trust product cannot survive.

**Rung 2 is the human, asked well.** Only what survives the first two rungs
reaches the person, and the quality of the ask is everything: name the
statement, the gap, the most likely line, what we read, what the running balance
implies, and let one tap settle it. The person does the minimum irreducible
judgment and never re-keys a statement. That principle now applies vault-wide
rather than only to a failed document — the identity, transfer, merchant and
nature loops are one primitive, a ranked [question queue](the-question-queue.md)
asked in order of how much money the answer moves.

The line through "never bluff a number" runs exactly here. Presenting a value
*as a fact* because it makes things reconcile is the forbidden ruin case.
Presenting it as a clearly-labelled hypothesis with its evidence, while nothing
enters the trusted ledger until it is confirmed or forced, is deferral rather
than bluffing. That distinction is encoded in the finding's status, which is why
the forced/suggested boundary is a **trust boundary**: a "forced" correction
that is really a heuristic misfire would post a wrong number at a grade that
claims corroboration. Hence the diagnosis rules are deterministic and versioned,
and a suggested correction is shown against the source pixels rather than led by
our number, so the person is not anchored into rubber-stamping a guess.

Some failures are classification misses rather than extraction errors, and
reconciliation catches them naturally — there is no coherent
opening/closing/transaction structure to find. The response is to *reclassify*,
not to correct. And a person answering "no, it really is a checking statement"
is a loud signal that the read is weak on that issuer's format, which feeds the
format-profile work directly.

The reason this is an asset rather than a cost is that every confirmation or
forced fix is an event on a fact, and it does three things at once: it fixes
this statement, it becomes a training pair of *(model read X, truth is Y, on
this document shape)*, and it teaches the product about this person and this
format so the next statement of the same shape pre-empts the same misread. The
hard cases are the only place the product learns; a system that never had to ask
would never get better at your documents.

The economics work because cost scales with difficulty rather than volume. The
statements that reconcile cost one read each, forever. Only failures incur
repair calls, and only after free diagnosis fails to force an answer. Bounded
repair is what keeps the cost curve flat as document volume grows, which is what
the near-zero-cost fully-local endgame needs.

Five things ripple into every later slice, which is why it is worth getting
right once. The **finding shape is a universal contract** — a structured
diagnosis of which identity failed, the delta, the locus, the status and the
confidence — so every future document type plugs its own identities into the
same shape, with the ladder as universal code and the per-type checks as
registry data. **Correction-as-event is the single spine under all human
teaching**: "that figure is wrong", "that leg is groceries", "these two lines
are the same transfer" are the identical mechanism, so the amount-correction
engine built here *is* the categorization-correction engine later. **The moat
compounds from the first hard statement.** **The confirmation surface is an agent
primitive** — show source, collect a graded confirmation, emit a correction event
— which the conversational agent composes rather than rebuilds, and which is the
same surface as tap-to-source. And **autonomy calibration gets its boundary**:
"post when it reconciles, ask when it doesn't" is the concrete seed of graduated
autonomy, with the finding's confidence as the dial.

## Open

- Rung 1, the automated targeted re-read, is unbuilt. It is the first *repair* model call and waits until the human-ask rate justifies the plumbing and the spend.
- The correction surface itself: showing the source crop and collecting a ruling in one tap is designed; today a ruling arrives through the Viva conversation's question and proposal path.
- Nothing pins the diagnosis version to its rules, so a rule change that forgets to bump the version would be invisible.
- Whether the finding shape survives a document family with no arithmetic identity at all — the case that would decide whether the ladder is genuinely universal.
- This design may graduate to an ADR once the finding shape has proven itself across a second document type.
