---
name: orionviva-acceptance-repair
description: Run OrionViva's independent acceptance suite, classify its structured failures, and carry full-lane defects through the repair and ship workflow. Route eligible localized deterministic defects through WORKFLOW.md's small bug lane. Use when asked to test, repair, or iterate OrionViva.
---

# OrionViva acceptance repair

Coordinate the product at the repository containing this skill and the independent
evaluator at `../orionviva-acceptance`. Read the product's `WORKFLOW.md` before
acting. The evaluator is an independent, read-only observer of the product: never
edit its assertions or product pack merely to turn a failure green.

Use `scripts/repair_loop.py` for preflight, evaluator execution, and deterministic
report validation. The script does not interpret product intent, edit code, or
commit.

## Choose the lane

Read `WORKFLOW.md` and classify the work before requiring the independent
acceptance pack. A defect may use the small bug lane only with the product
owner's approval and only when it satisfies every condition stated there. For
that lane, require its regression, complete affected-package checks, fresh
Verifier, Interface Designer when applicable, Steward rituals, and commit gate.
The independent end-to-end evaluator is informative rather than a ship gate;
report unrelated acceptance gaps without blocking an otherwise complete small
bug lane.

Use the rest of this skill's acceptance-run, full repair-lane, and committed-
revision requirements for full-lane work. Bounce a purported small bug into the
full lane as soon as its scope or evidence violates `WORKFLOW.md`'s boundary.

## Start a run

1. Run `python3 .codex/skills/orionviva-acceptance-repair/scripts/repair_loop.py preflight`.
2. Work on a dedicated `codex/` branch or worktree. Preserve unrelated changes.
3. The evaluator accepts tracked changes but deliberately rejects nearly all
   untracked product files. If preflight lists `working_tree_refused_untracked`,
   stage only the intended repair files after reviewing them; do not stage unrelated
   work or sensitive artifacts.
4. Run the complete suite against the working tree:

   `python3 .codex/skills/orionviva-acceptance-repair/scripts/repair_loop.py run --mode working-tree`

The command prints JSON containing the output directory and normalized report
classification. Run evidence stays under the product's ignored `runs/` directory.

## Classify before changing the product

- `product_failure`: deterministic behavior failed. Start the full repair lane.
  The report may also contain acceptance gaps; those remain blockers to final pass.
- `acceptance_gap`: cases are blocked, incomplete, not verified, omitted, or the
  report lacks required coverage. Improve or authorize the acceptance capability;
  do not change product behavior to hide the gap.
- `invalid_report`: stop. A missing, malformed, stale, or contradictory report is
  not evidence about the product.
- `pass`: the tested working tree is eligible for Steward review and the commit
  gate. It is not final until the committed-revision run also passes.

Read the report's case IDs, deterministic failures, blockers, and evidence paths.
Do not give general advisory findings the authority of deterministic oracles.
Never expose vaults, real financial values, credentials, provider responses, or
sensitive screenshots to repair roles or commits.

## Repair lane

For `product_failure`, perform one bounded cycle:

1. **Designer:** produce a standalone brief from the failed case IDs and evidence.
   Include expected behavior, affected invariants, a scope fence, and decisions
   that require the owner. Follow Checkpoint 1 in `WORKFLOW.md`; use the Director
   only within its recorded warrant.
2. **Builder:** implement only the approved brief and provide the required
   walkthrough. Do not commit.
3. **Verifier:** use a fresh subagent/context that did not build the change. Check
   the diff against the brief, run relevant product tests, and rerun acceptance.
4. **Interface Designer:** when the interface changed, use another fresh context
   alongside the Verifier. It reports craft and accessibility findings without
   changing code.
5. Return actionable findings to the Builder. A scope-fence problem returns to the
   Designer. After focused checks pass, rerun the complete working-tree suite.
6. Stop after three unsuccessful repair cycles. Report repeated failure signatures,
   attempted fixes, remaining evidence, and the next owner decision rather than
   continuing speculative edits.

The Builder never grades its own work. A scenario whose correct financial meaning
is not settled by the ledger goes to the owner before a test or fix is invented.

## Ship and prove a full-lane commit

When the complete working-tree result is `pass`, run the Steward rituals from
`WORKFLOW.md`. Present the proposed commit and wait at Checkpoint 3. A normal commit
requires the product owner's own authorization. In a delegated run, the Director
may authorize only the bounded off-main `wip(...)` commit permitted by its warrant;
never push, merge, or release on that authority.

After an authorized commit, require a clean product tree and run:

`python3 .codex/skills/orionviva-acceptance-repair/scripts/repair_loop.py run --mode committed`

Finish only when that report classifies as `pass`, reports `decision: ready`,
executes every case declared by the evaluator pack, and identifies the committed
revision. Otherwise classify the result and begin another bounded cycle.

The maintained product catalog currently contains 45 human-readable scenarios.
The evaluator's complete-pack coverage is a separate executable declaration.
Report both counts in preflight and never claim that all 45 catalog scenarios are
automated unless a reviewed mapping proves it.
