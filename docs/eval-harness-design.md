# Eval Harness Design (A8) — how honesty is measured, continuously

**State:** partial
**Rules:** PROG-24, PROG-25, PROG-26, PROG-27, PROG-28, PROG-29, PROG-55

## Rules

### PROG-24 — Honesty is checked before accuracy
**State:** enforced-with-exception
**Code:** product/viva/eval_listen.py:55 (verdict vocabulary), product/viva/eval_listen.py:71
**Test:** product/tests/test_eval_listen.py::test_declining_is_safe_and_never_counted_as_confidently_wrong

1. A case checks honesty, then accuracy, then provenance, in that order.
2. A wrong-but-flagged answer passes the honesty check; a wrong-but-confident answer fails it.
3. A reading the model declines to make is safe, never confidently wrong.

**Exception:** only the sentence-interpretation path is measured. `eval_listen` grades a model reading a sentence into a structured ruling (product/viva/eval_listen.py:1). Document reading has no live measurement, and the answer path is graded by no harness at all.

### PROG-25 — The confidently-wrong rate is the headline, and its target is zero
**State:** enforced
**Code:** product/viva/eval_listen.py:161, product/viva/eval_listen.py:196-202; the rate itself is product/viva/honesty.py:43 (`rate`), imported rather than repeated
**Test:** product/tests/test_eval_listen.py::test_an_invented_split_is_ruin_even_when_the_majors_are_right, product/tests/test_eval_listen.py::test_an_amount_in_the_reply_is_ruin

1. A run reports the confidently-wrong rate as its headline figure, not accuracy.
2. A ratio nobody stated and a figure from the model's head are each ruin, whatever else the reading got right.
3. A figure the person themselves stated is not ruin.

### PROG-26 — A call that never reached the model is scored by nothing
**State:** enforced
**Code:** product/viva/eval_listen.py:60, product/viva/eval_listen.py:150-161
**Test:** product/tests/test_eval_listen.py::test_a_broken_pipe_is_never_reported_as_a_clean_result, product/tests/test_eval_listen.py::test_a_partly_broken_run_scores_only_what_it_measured

1. A call that never reached the model is excluded from every rate and reported on its own.
2. A run in which nothing reached the model reports no confidently-wrong rate at all rather than reporting zero.
3. A declining model is still distinguished from a broken pipe.

### PROG-27 — The eval runs on every change to trust-critical code
**State:** enforced-with-exception
**Code:** product/viva/honesty.py:1, .github/workflows/quality.yml (the `suite` job runs the harness over `product/evals/honesty_turns.json`)
**Test:** product/tests/test_honesty_harness.py::test_the_run_reports_and_holds_a_ceiling, ::test_a_ceiling_is_not_enforced_where_nothing_was_measured

1. A change to trust-critical code — verification, the ledger, the model layer, prompts — re-runs the harness before it lands, in CI, over a frozen record of recorded turns that needs no model, no vault and no passphrase.
2. A change that moves a measured rate above the ceiling the build declares fails it. A rate with an empty denominator is not enforced, because failing a build for having nothing to measure is a different fault.

**Exception:** the half that calls a model does not run here. `eval_listen` needs a model and a key, and a CI job is given neither; a run without one would report nothing while looking like a pass, which is the failure PROG-26 exists to prevent. So the rate the build holds is the unsupported-figure rate and not the confidently-wrong rate, and nothing in CI moves the latter.
3. A new model or a re-tuned local model re-sits the relevant eval slice before it serves ([model-trust-policy.md](model-trust-policy.md), feedback loop 3: every version is a new hire).
4. A scheduled run on the author's real instance catches drift no code change triggered.

### PROG-28 — The frozen case set ships with the code and holds nobody's data
**State:** enforced-with-exception
**Code:** product/viva/eval_listen.py:48 (`evals/listen_cases.json`)
**Test:** product/tests/test_eval_listen.py::test_the_key_names_nobody_real, product/tests/test_eval_listen.py::test_the_key_carries_no_amounts_or_account_numbers

1. The case set is frozen and shipped, so any contributor's change is graded against the same honesty bar.
2. It names no real person, institution or account, and carries no real amounts.
3. Real personal cases stay local, like the corpus.
4. A case may accept a set of correct readings, because some sentences have more than one right answer.

**Exception:** the *names nobody real* half of assertion 2 is unenforced anywhere but the author's machine. `test_the_key_names_nobody_real` reads a gitignored `.denylist` (product/tests/test_eval_listen.py:139) and skips when it is absent, which is every other machine and CI. The no-amounts half is always on.

### PROG-29 — The answer path returns structure, not prose
**State:** enforced-with-exception
**Code:** product/viva/tools/envelope.py:1 (figures carry value, quantity, kind, grade, `record_ids` and boundary)
**Test:** product/tests/test_tool_contract.py::test_balances_match_the_projection_and_carry_grades, product/tests/test_tool_contract.py::test_every_figure_a_tool_emits_says_what_it_measures

1. Every read returns a figure with its grade and the records behind it, not a bare number.
2. A correction is appended as an event and never overwrites a value.
3. A correction is replayable as an eval case: it carries the question, the truth and the source.

**Exception:** assertion 1 is narrower than written: an `activity` figure and a `hypothetical` figure carry no grade at all, by design (product/viva/tools/envelope.py:12-24) — the first costs candour and nothing else, the second rests on the asker's premise rather than on evidence. Assertion 3 is unmet: `correction_applied` (product/viva/ledger/events.py:228) appends the target, the old and new values, who ruled, and the document provenance — and carries no question text, so a stored correction is not yet a replayable eval case.

### PROG-55 — A case states the source it expects and the grade it expects
**State:** unmet
**Code:** none found (a case in `product/viva/evals/listen_cases.json` carries the sentence, the descriptor, a category and subcategory and a set of accepted readings — no source and no grade; nothing in the tree names an `expected_source` or an `expected_grade`)
**Test:** none

1. A case carries an expected source — document, page and region — which is the provenance the answer must cite (T1).
2. A case carries an expected grade: the confidence the system should assign, from the same vocabulary the product grades with.

## Why

The benchmark ([benchmark-harness-design.md](benchmark-harness-design.md), whose one-time exam and frozen keys this reuses) is a driving test: a one-time exam a *model* sits to earn admission. The eval harness is the dashboard warning light: a continuously-running honesty test on the *whole system*, forever after. One asks whether a model is good enough to admit; the other asks, on every code change, model swap and schedule tick, whether the product is still telling the truth.

It exists because an AI system's honesty rots silently. A button that breaks is obvious; a model update or a refactor that makes Viva confidently wrong about two per cent more figures looks like nothing at all. The project's own rule — an untested trust property does not exist — makes this non-negotiable: the eval harness is how "never bluff a number" becomes a thing measured every day, so a slip triggers an alarm instead of a betrayed user.

The asymmetry between the three checks is the whole point. A wrong-but-flagged answer is a bad day, handled. A wrong-but-confident answer is the ruin case, and no amount of accuracy elsewhere buys it back. That is why the headline metric is the confidently-wrong rate and not accuracy, and why a broken pipe is excluded rather than counted as a pass — a harness that scores its own failure to reach a model as a clean result is an instrument that lies in the direction of passing.

Cases are near-free by prior design. Frozen benchmark keys seed the first and highest-quality ones. Every user correction is automatically a case, because "the system said X, the truth is Y" is exactly a known-truth expectation — so the feedback loop that teaches Viva a person is the same machinery that tests her, usage generates the test suite, and each case is anchored to a real past mistake that can never silently return. A small curated adversarial set covers the hardest questions, including the injection tripwire: a case whose document contains a planted instruction, asserting the system never actuates it and grades the poisoned value `conflicted`.

The one genuinely new thing against the benchmark is what is graded. The benchmark grades extraction, document to claims. The eval harness grades the full answer path — question to tools to composed answer to cited figure and grade — so it tests the tool-using agent — the verbs in [agent-toolset.md](agent-toolset.md) — and the refusal of uncited figures, not just the reader. That is why the answer path must return structure rather than prose, and it is the same structure a user interface needs for provenance click-through: one shape serves testing, interface and honesty at once.

## Open

- Document reading has no live measurement. This is the project's largest standing gap: the harness grades sentence interpretation and nothing else.
- Q31: case-set curation — how many hand-written adversarial cases, and who reviews additions. A wrong expected answer erodes the bar silently, so the eval set needs the two-drafter-plus-audit rigour the benchmark keys were designed for.
- Q32: alarm thresholds — what movement in the confidently-wrong rate blocks a commit rather than warning. Setting it honestly needs the frozen-key baseline first.
- Q33: regression triage — when the harness reddens, how a failing case points at the cause (model, prompt, verification rule, or tool), so a red light is actionable rather than merely alarming.
- The injection tripwire case is designed and unbuilt.
