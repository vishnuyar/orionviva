# The Maintenance Agent — what Viva does when nobody asked

**Status:** Implemented · **Last updated:** 2026-07-30 · **Origin:** the grammar
induction and merchant enrichment paths both cost model calls, both improve the
vault, and both were run by hand. Running them by hand does not scale past one
person paying attention, and running them unattended is spending money nobody
authorised. This is the machinery that lets the second happen safely.

**Invariants touched:** T4 (what it did is an event), T8 (prompts pinned and
versioned), T9 (the record carries no descriptor, amount, or account), X2
(uncertainty visible — a refusal is recorded with its reason), X3 (a budget is a
ceiling, not a suggestion). Principle 7 — autonomous where safe, deferential
where it counts — is the whole subject.

**Not to be confused with** [agent-toolset.md](agent-toolset.md), which is the
*read* direction: the verbs Viva may use to answer a question. This document is
the *upkeep* direction: what Viva does to its own knowledge between questions.

## The shape

`observe` → `plan` → `perform` → record. Four modules, and the split is the
design:

- **`observe.py`** reads the vault and returns an `Observation` — the
  (institution × kind) pairs and their distinct descriptor lines, the brands the
  catalog has never been asked about, whether a model is configured at all.
- **`policy.py`** is pure. Given an observation and the agent's own history it
  returns a list of `Action`s with estimated costs. No ledger, no model, no
  clock. This is what makes `--dry-run` meaningful: it is the same function.
- **`act.py`** does one action and returns an `Outcome`. Nothing raises into the
  loop; every failure becomes an outcome with a reason.
- **`run.py`** holds the budget and the cooldown, and re-plans after every
  action so the ceiling means what it says.

## Why `AgentActed` is its own event

The twentieth event type, admitted on the same grounds as `MovementTagged`:

- Its **lifecycle is unlike anything already recorded.** Existing events describe
  what a document said or what a person ruled. This describes what the software
  chose to do with money nobody had asked it to spend.
- It is the **only record of that spend.** Model calls leave no other trace in
  the vault, so without it the agent's cost is invisible and unauditable.
- **The cooldown has to be derivable from the log.** A cache beside the ledger
  would work until it was deleted, and then the agent would repeat every refusal
  it had ever made. Deriving it from the event log is what makes the quiet
  behaviour reproducible.
- **`ReadRecorded` could not be ridden.** It is document-scoped; an induction is
  scoped to an (institution × kind) pair that no single document owns.

The body carries `rule, kind, target, outcome, calls, stake, produced, replaced,
detail, by`. It carries **no descriptor, no amount, and no account** — the agent
records what it did, never what it saw.

## The stake, and why a code fix must lift a refusal

An action's *stake* is a fingerprint of the evidence it was decided on. If the
evidence has not moved, the decision has not changed, and re-deciding costs
money for a foregone conclusion. So a refusal recorded against a stake keeps the
agent quiet until the stake moves — the `QuestionDeclined` idiom, pointed at the
agent's own actions.

The first version fingerprinted **only the data**, and that was wrong in a way
worth remembering: a bug in the inducer produced a refusal, the bug was fixed,
and the agent stayed permanently silent about the exact thing the fix had
repaired. The stake now includes `machinery_version()` —
`INDUCTION_VERSION + PROFILE_FORMAT + PACK_RULES` — so **a code change lifts a
refusal and unchanged data does not.**

Note the split those three carry: `PROFILE_FORMAT` is a *compatibility* version
(it gates `from_dict` and salts the holdout split), `PACK_RULES` is a *behaviour*
version (nothing loads by it). They move for different reasons and only the
stake needs both.

And a corollary the code carries that neither version's name states: **widening a
shape moves neither version.** A wider shape only ever matches more, so a stored
grammar still loads and still means what it meant; and because `holdout_split`
salts its hash with `PROFILE_FORMAT`, the holdout does not reshuffle, which is
what keeps a before/after coverage measurement comparable. Bumping
`PROFILE_FORMAT` for a widening would silently invalidate every grammar on disk
*and* move the split underneath a measurement in progress. Enforced by
`test_a_wider_shape_only_ever_matches_more`.

## Money

The budget is denominated in **calls**, not dollars, and that is a limitation
being honest rather than a design choice. `merchantcore.enrich.model_extractor`
returns the reply text and discards the `ModelResult`, so tokens, latency and
cost never reach this layer. No product `ModelSpec` sets `cost_per_mtok_*`, so
every `cost_usd` in the codebase is 0.00 and would be a false comfort if
reported as money.

Two numbers exist and neither is asked to be the other:

- **`estimated_calls`** is a property of the plan and is what gets an action past
  the budget. It was wrong by 3× until `best_of` moved into `RULES`: the plan
  said three calls where the run would spend nine, because the multiplier lived
  in the doing half and the budget reasoned about the deciding half. The number
  the budget reasons about and the number the code obeys have to be one number.
- **Actual calls** are counted by a `Meter` that sits between the caller and the
  extractor. Induction converges early — its loop stops as soon as a round
  explains nothing new — so a three-round budget routinely spends one or two.

## Selection, and independent attempts

`--best-of N` runs N independent inductions and keeps one. Two rules were learned
the expensive way:

- **Select on the held-out score, never on training coverage.** Picking the
  best-fitting of N is picking the luckiest overfit of N, which is precisely what
  withholding a fifth of the lines existed to prevent.
- **Guard each attempt separately.** The first live run lost all three to one
  exception on the first: three calls spent, nothing kept, and two perfectly good
  attempts never made. Independent attempts should fail independently or they are
  not independent. Failures are logged, never swallowed — an agent that keeps the
  best of three and says nothing about the two that died looks identical to one
  that made three good attempts.

## The report is not for a person

`DEFAULT_BUDGET_CALLS` is set for an agent, not for someone reading each result
before allowing the next. An earlier version had it low on the reasoning that a
grammar should be read before the rest are automated — but reading gates
**publishing** a grammar to the commons, not **using** one in a private vault.
Confusing those two makes the agent useless at the thing it exists for.

The CLI still prints CONSIDERED / HELD BACK / DEFERRED / DID, because an
autonomous action nobody can audit afterwards is indistinguishable from a bug.

## What it may touch

`INDUCIBLE_KINDS` gates both induction and enrichment to bank and card
statements. An investment activity line is not a merchant, and offering one to a
model as if it were is how a catalog fills with nonsense. The gate is on the
account **kind** — a fact the ledger already holds — never on anything about the
text.

## Open

- The rule name `INDUCIBLE_KINDS` now governs enrichment too and should be
  renamed.
- `reinduce_stale_machinery` — an action that re-runs induction when
  `machinery_version()` has moved — is designed and unbuilt.
- The ~100-line answer key that would let slot *correctness* be measured rather
  than inferred from coverage does not exist.
