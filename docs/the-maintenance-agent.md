# The Maintenance Agent — what Viva does when nobody asked

**State:** built
**Rules:** MER-50, MER-51, MER-52, MER-53, MER-54, MER-55, MER-56, MER-57, MER-58

**Not to be confused with** [agent-toolset.md](agent-toolset.md), which is the
*read* direction: the verbs Viva may use to answer a question. This document is
the *upkeep* direction: what Viva does to its own knowledge between questions.

## Rules

### MER-50 — Deciding is pure; only performing spends
**State:** enforced
**Code:** product/viva/agent/policy.py:90 (`assess`), product/viva/agent/act.py:177 (`perform`), product/viva/agent/run.py:120 (`_plan`), :133 (`wake`)
**Test:** product/tests/test_policy.py::test_assess_is_pure_and_repeatable, product/tests/test_policy.py::test_assess_asks_nobody_anything, product/tests/test_agent_run.py::test_a_dry_run_spends_nothing_and_writes_nothing

1. `observe` reads the vault; `policy.assess` is pure — no ledger, no model, no clock — and returns `Action`s with estimated costs; `act.perform` does one action; `run.wake` holds the budget and the cooldown.
2. `--dry-run` runs the same planning function and stops before the first model call, writing nothing.
3. `assess` is deterministic: the same inputs yield the same list in the same order — grammars, then brands, then waits.
4. Nothing raises out of `act`; every failure comes back as an `Outcome` with a reason.
5. The plan is remade after every action, so the ceiling means what it says.

### MER-51 — The agent records what it did, never what it saw
**State:** enforced
**Code:** product/viva/ledger/events.py:805 (`agent_acted`), :826 (outcome validation)
**Test:** product/tests/test_agent_run.py::test_the_journal_carries_no_descriptor_and_no_amount, product/tests/test_agent_run.py::test_the_event_refuses_an_outcome_it_does_not_understand, product/tests/test_agent_run.py::test_the_log_keeps_every_attempt_and_the_lifetime_bill

1. `AgentActed` carries rule, kind, target, outcome, calls, stake, produced, replaced, detail and by.
2. It carries no descriptor, no amount and no account.
3. `produced` and `replaced` are artifact ids, never contents.
4. An outcome outside the accepted set, a missing rule or target, or a negative call count raises.
5. It is the only record of the agent's model spend, and the lifetime bill is derived from it.

### MER-52 — A refusal cools until the stake moves, and a code change moves it
**State:** enforced
**Code:** product/viva/agent/run.py:56 (`stake_of`), :42 (`machinery_for`), :69 (`cool`), merchant/merchantcore/induce.py:113 (`machinery_version`)
**Test:** product/tests/test_agent_run.py::test_a_refusal_against_unchanged_evidence_is_not_retried, ::test_changing_the_machinery_lifts_a_cooldown, ::test_the_stake_names_the_machinery_that_would_act, ::test_the_stake_rounds_floats_so_recomputation_is_not_new_evidence, ::test_a_cooldown_is_per_target_not_global

1. A stake is the action's evidence, sorted, floats rounded, plus the version of the machinery that would do the work.
2. An action is held back when its last attempt did not succeed and its stake is unchanged; a "done" attempt cools nothing.
3. `machinery_version()` is `INDUCTION_VERSION + PROFILE_FORMAT + PACK_RULES`, so a code change lifts a refusal and unchanged data does not.
4. The cooldown is derived from the event log, never from a cache beside it.
5. Cooling is per (rule, target), never global.

### MER-53 — Widening a shape moves neither version
**State:** enforced
**Code:** merchant/merchantcore/profile.py:33 (`PROFILE_FORMAT`), :39 (`PACK_RULES`), merchant/merchantcore/induce.py:70 (`holdout_split` salts on `PROFILE_FORMAT`)
**Test:** merchant/tests/test_profile.py::test_a_wider_shape_only_ever_matches_more, merchant/tests/test_profile.py::test_the_pack_rules_version_is_not_the_storage_format

1. `PROFILE_FORMAT` is a compatibility version: it gates `from_dict` and salts the holdout split.
2. `PACK_RULES` is a behaviour version: nothing loads by it.
3. A wider shape only ever matches more, so a stored grammar still loads and still means what it meant; neither version moves for a widening.
4. Only the agent's stake needs both.

### MER-54 — The budget is a ceiling denominated in calls
**State:** enforced
**Code:** product/viva/agent/policy.py:23 (`CALLS`), :61 (`best_of`), :154 (`within_budget`), product/viva/agent/run.py:30 (`DEFAULT_BUDGET_CALLS`), product/viva/agent/act.py:38 (`Meter`)
**Test:** product/tests/test_policy.py::test_a_budget_stops_a_runaway_before_it_costs_anything, ::test_waiting_never_consumes_budget, ::test_the_estimate_counts_attempts_times_rounds, product/tests/test_agent_run.py::test_the_budget_is_a_ceiling_on_what_a_wake_may_spend, ::test_calls_are_counted_not_estimated

1. The budget counts model calls, not money.
2. An estimate is calls per attempt multiplied by the rule's `best_of`, read from one place by both the estimate and the executing code.
3. Actual calls are measured by a meter between the caller and the extractor, and are usually fewer than the estimate.
4. A `wait` action always fits and costs nothing; work that does not fit is deferred to the next wake, never refused.

### MER-55 — Independent attempts, selected on the held-out score
**State:** enforced
**Code:** product/viva/agent/act.py:105 (per-attempt guard), :117 (selection on `scored`), product/viva/agent/policy.py:26 (`RULES`, `best_of`)
**Test:** product/tests/test_agent_run.py::test_best_of_selects_on_the_held_out_score_not_training_coverage, ::test_one_failed_attempt_does_not_lose_the_others, ::test_every_attempt_failing_is_a_failure_not_a_silence

1. `--best-of N` runs N independent inductions and keeps the one with the highest held-out score; ties go to the smaller grammar.
2. Each attempt is guarded separately: one that raises is logged and the rest still run.
3. Failures are logged, never swallowed.
4. Every attempt failing is reported as a failure, not as silence.

### MER-56 — Enrichment does not run unattended
**State:** enforced
**Code:** product/viva/agent/policy.py:53 (`AUTONOMOUS`)
**Test:** product/tests/test_policy.py::test_enrichment_does_not_act_unattended_while_the_crossing_is_ungated, product/tests/test_policy.py::test_mechanics_are_autonomous_and_publishing_is_not

1. `AUTONOMOUS` holds `induce_missing` and `reinduce_drifted`; `enrich_unknown` is not among them.
2. An enrichment is planned, costed and proposed, and a person allows it.
3. Anything restoring `enrich_unknown` to the autonomous set says first what closed the enrichment crossing.
4. Induction is unaffected: it reads lines the vault already holds and writes a grammar.

### MER-57 — The agent proposes nothing for a kind that names no party
**State:** enforced
**Code:** product/viva/agent/policy.py:106 (`is_inducible` guard in `assess`)
**Test:** product/tests/test_policy.py::test_a_kind_that_names_no_party_is_never_proposed

1. A pair whose account kind is outside the allowlist is skipped before any action is proposed.
2. The gate is on the account kind the ledger already holds, never on anything about the text.
3. It is the same allowlist the grammar and the enrichment boundary use (MER-14 in [the-conduit-and-the-counterparty.md](the-conduit-and-the-counterparty.md)).

### MER-58 — Publishing waits for a person
**State:** enforced
**Code:** product/viva/agent/policy.py:58 (`NEEDS_RATIFICATION`), :79 (`Action.autonomous` returns False for any rule in it)
**Test:** product/tests/test_policy.py::test_mechanics_are_autonomous_and_publishing_is_not

1. A rule that changes what other people see is ratified by a person, always.
2. Reading a grammar gates *publishing* it to the commons, never *using* it in a private vault.
3. `NEEDS_RATIFICATION` names `publish_grammar` and `publish_merchant`, so a publish rule added later is proposed and waits rather than acting.

The rule holds vacuously today: neither publish rule exists in `RULES` (product/viva/agent/policy.py:27-43), so no publish action is ever proposed. See *Open*.

## Why

Grammar induction and merchant enrichment both cost model calls, both improve the
vault, and both were run by hand. Running them by hand does not scale past one
person paying attention; running them unattended is spending money nobody
authorised. This is the machinery that lets the second happen safely.

The four-module split is the design. Keeping the deciding half pure is what makes
`--dry-run` meaningful — it is the same function, not a parallel implementation
that can drift. Keeping every failure inside an `Outcome` is what lets the loop
finish and report rather than dying halfway through a plan.

`AgentActed` earns its own event type on the same grounds `MovementTagged` did.
Its lifecycle is unlike anything already recorded: existing events describe what a
document said or what a person ruled, while this describes what the software chose
to do with money nobody had asked it to spend. It is the only record of that
spend, since model calls leave no other trace in the vault. The cooldown has to be
derivable from the log, because a cache beside the ledger would work until it was
deleted and then the agent would repeat every refusal it had ever made. And
`ReadRecorded` could not be ridden: it is document-scoped, while an induction is
scoped to a pair no single document owns.

An action's stake is a fingerprint of the evidence it was decided on. If the
evidence has not moved, the decision has not changed, and re-deciding costs money
for a foregone conclusion — the `QuestionDeclined` idiom pointed at the agent's own
actions. The first version fingerprinted only the data, and that was wrong in a
way worth remembering: a bug in the inducer produced a refusal, the bug was fixed,
and the agent stayed permanently silent about the exact thing the fix had
repaired.

The two versions in `machinery_version` move for different reasons, and a
corollary neither name states is that widening a shape moves neither. Bumping the
compatibility version for a widening would silently invalidate every grammar on
disk *and* move the holdout split underneath a measurement in progress, which is
what keeps a before/after coverage comparison comparable.

The budget is in calls rather than dollars, and that is honesty about a
limitation rather than a design choice. The live extractor returns reply text and
discards the model result, so tokens, latency and cost never reach this layer, and
no product model spec sets a cost per token — every `cost_usd` in the codebase is
zero and would be a false comfort if reported as money. Two numbers exist and
neither is asked to be the other. The estimate was wrong by 3× until `best_of`
moved into the rules: the plan said three calls where the run would spend nine,
because the multiplier lived in the doing half and the budget reasoned about the
deciding half. The number the budget reasons about and the number the code obeys
have to be one number. Actual calls come from a meter, and induction converges
early, so a three-round budget routinely spends one or two.

Two selection rules were learned the expensive way. Picking the best-fitting of N
is picking the luckiest overfit of N, which is precisely what withholding a fifth
of the lines existed to prevent. And the first live run lost all three attempts to
one exception on the first: three calls spent, nothing kept, two perfectly good
attempts never made. Independent attempts should fail independently or they are
not independent. An agent that keeps the best of three and says nothing about the
two that died looks identical to one that made three good attempts.

The default ceiling is set for an agent, not for someone reading each result
before allowing the next. An earlier version had it low on the reasoning that a
grammar should be read before the rest are automated — but reading gates
*publishing* a grammar to the commons, not *using* one in a private vault, and
confusing those two makes the agent useless at the thing it exists for. The CLI
still prints considered / held back / deferred / did, because an autonomous action
nobody can audit afterwards is indistinguishable from a bug.

Enrichment stays out of the autonomous set because of what an enrichment hint
carries. Where an induced grammar labelled a slot `{brand}` and a party's name
landed in it, the hint carries that name to the model and into the pending queue,
which persists to unencrypted JSON when the enriched records are saved — after the
call, so the queue cannot be read ahead of the spend to see what is about to
cross. The corroboration gate at the enrichment boundary narrows that crossing and
does not close it: the ACH half of its evidence is recovered from the corpus and
can hand back a person's name as a company name. See T9 in
[the-conduit-and-the-counterparty.md](the-conduit-and-the-counterparty.md).

The kind gate exists because an investment activity line is not a merchant, and
offering one to a model as if it were is how a catalog fills with nonsense.

## Open

- The rule name `INDUCIBLE_KINDS` governs enrichment as well as induction and
  should be renamed.
- `reinduce_stale_machinery` — an action that re-runs induction when the machinery
  version has moved — is designed and unbuilt.
- The answer key that would let slot *correctness* be measured rather than
  inferred from coverage does not exist. Roughly a hundred lines of work.
- `publish_grammar` and `publish_merchant` are named as needing ratification but
  no such rule exists, so nothing is ever proposed for publication (MER-58).
- The budget cannot be denominated in money until the model edge carries cost
  through to this layer.
