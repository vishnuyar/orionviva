"""Doing one proposed thing, and reporting honestly how it went.

`policy.assess` decides *what*; this does it. The split matters because the
deciding half is pure and testable and the doing half spends money, and keeping
a boundary between them is what lets the whole plan be rehearsed with
`--dry-run` against the same code that would run for real.

Two rules hold here.

**Nothing raises into the loop.** Every failure becomes an `Outcome` with a
reason. An agent whose third action kills the run leaves the first two
unrecorded, and unrecorded work is work that will be done again — which for this
agent means paid for again.

**Calls are counted, not estimated.** `Action.estimated_calls` is what got the
action past the budget; it is a property of the plan. What the invoice will
agree with is how many times the extractor was actually called, which differs
whenever induction converges early — its loop stops as soon as a round explains
nothing new, so a three-round budget routinely spends one or two. The estimate
is the only number available before the fact and the actual is the only one
worth recording after it, so both exist and neither is asked to be the other.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

# How many independent inductions to run before keeping the best lives in
# `policy.RULES["induce_missing"]["best_of"]`, NOT here. It multiplies the call
# estimate, so the number the budget reasons about and the number the code obeys
# have to be one number — they were two until 2026-07-29, and the plan said three
# calls where the run would have spent nine.
BEST_OF = 3          # fallback only, for a direct call that names no rule


@dataclass
class Outcome:
    """What happened, in the vocabulary the event records."""

    outcome: str                      # done | refused | failed
    calls: int = 0
    produced: str = ""
    replaced: str = ""
    detail: str = ""
    result: dict = field(default_factory=dict)   # counts, for the report


class Meter:
    """Counts model calls by sitting between the caller and the extractor.

    `merchantcore.enrich.model_extractor` returns the reply text and throws the
    `ModelResult` away, so tokens, latency and cost do not reach this layer at
    all. Counting invocations is therefore the only actual figure available —
    which is also why `within_budget` is denominated in calls. Worth being
    plain about the limit: this is a call count, not a bill. No product
    `ModelSpec` sets `cost_per_mtok_*`, so every `cost_usd` in this codebase is
    0.00 and would be a false comfort if reported as money."""

    def __init__(self) -> None:
        self.calls = 0

    def wrap(self, extract_fn):
        def _counted(prompt: str) -> str:
            self.calls += 1
            return extract_fn(prompt)
        return _counted


def _spec(name: str):
    from vivacore.models import ModelSpec
    return ModelSpec(
        name=name, adapter=os.environ["VIVA_MODEL_ADAPTER"],
        model=os.environ["VIVA_MODEL"],
        base_url=os.environ.get("VIVA_MODEL_BASE_URL"),
        api_key_env=os.environ.get("VIVA_MODEL_KEY_ENV", "OPENROUTER_API_KEY"),
        json_mode=True)


def _extractor(name: str):
    from merchantcore.enrich import model_extractor
    return model_extractor(_spec(name))


# --------------------------------------------------------------------- induce


def do_induce(action, obs, best_of: int = BEST_OF) -> Outcome:
    """Learn one bank's grammar and write it, or say why not.

    Everything the `--best-of` CLI does, minus the printing, plus the one thing
    a person doing it by hand supplies for free: a record that it was tried."""
    from merchantcore.induce import MIN_LINES_TO_INDUCE, Inducer
    from merchantcore.descriptor import is_never_templatable
    from merchantcore.profile import ProfileError

    inst, _, kind = action.target.partition("/")
    counts = obs.pairs.get((inst, kind))
    if not counts:
        return Outcome("failed", detail=f"no movements for {action.target} any more")

    # `assess` counts distinct lines including wires; induction never sees them.
    # Checking here rather than there keeps the policy free of merchantcore's
    # eligibility rules, and a refusal recorded against a stake is self-
    # correcting: it stays quiet until the line count moves.
    eligible = {d: n for d, n in counts.items() if not is_never_templatable(d)}
    if len(eligible) < MIN_LINES_TO_INDUCE:
        return Outcome("refused",
                       detail=f"{len(eligible)} templatable line(s), below the "
                              f"{MIN_LINES_TO_INDUCE} a grammar needs to learn "
                              f"rather than memorise")

    meter = Meter()
    try:
        inducer = Inducer(meter.wrap(_extractor("grammar-inducer")))
    except Exception as e:                                  # noqa: BLE001
        return Outcome("failed", detail=f"{type(e).__name__}: {e}"[:200])

    # Each attempt is guarded on its own. The first live run lost all three to
    # one exception on the first — three model calls spent, nothing kept, and
    # two perfectly good attempts never made. Independent attempts should fail
    # independently or they are not independent.
    attempts, errors = [], []
    for n in range(max(1, best_of)):
        try:
            attempts.append(inducer.induce(inst, kind, counts))
        except Exception as e:                              # noqa: BLE001
            errors.append(f"{type(e).__name__}: {e}")
            log.warning("agent: attempt %d of %d for %s failed: %s",
                        n + 1, best_of, action.target, e)
    if not attempts:
        return Outcome("failed", calls=meter.calls,
                       detail="; ".join(dict.fromkeys(errors))[:300])

    # The held-out score, ties to the smaller grammar. Selecting on training
    # coverage picks the luckiest overfit of N, which is what withholding a fifth
    # of the lines existed to prevent.
    result = max(attempts, key=lambda r: (r.scored,
                                          -len(r.profile.templates) if r.profile else 0))
    spread = [round(r.scored, 4) for r in attempts]
    if errors:
        # Reported, never swallowed: an agent that keeps the best of three and
        # says nothing about the two that died looks identical to one that made
        # three good attempts.
        log.info("agent: %d of %d attempt(s) for %s failed and were skipped",
                 len(errors), best_of, action.target)
    if result.profile is None or not result.accepted:
        return Outcome("refused", calls=meter.calls,
                       detail=str(result.verdict)[:200],
                       result={"attempts": spread})

    prior = obs.store.latest_for(inst, kind)
    profile = result.profile
    profile.version = obs.store.next_version(inst, kind)
    profile.measured = result.coverage
    try:
        obs.store.write(profile, against=counts)
    except ProfileError as e:
        # The write-guard doing its job: a version that covers less than the one
        # it succeeds. Recording it is the whole reason this event exists — the
        # calls are spent either way and without a record the next wake proposes
        # exactly this again.
        return Outcome("refused", calls=meter.calls, detail=str(e)[:300],
                       replaced=prior.id if prior else "",
                       result={"attempts": spread})

    return Outcome("done", calls=meter.calls, produced=profile.id,
                   replaced=prior.id if prior else "",
                   detail=f"{len(profile.templates)} template(s), "
                          f"{result.scored:.1%} held-out",
                   result={"attempts": spread, "templates": len(profile.templates),
                           "scored": round(result.scored, 4),
                           "coverage": round(result.coverage, 4)})


# --------------------------------------------------------------------- enrich


def do_enrich(vault, action, obs) -> Outcome:
    """Buy records for brands nobody here has identified yet."""
    from ..ingest import enrich_merchants

    meter = Meter()
    try:
        res = enrich_merchants(vault.ledger, obs.catalog,
                               meter.wrap(_extractor("merchant-enricher")),
                               profile_for=obs.profile_for, kind_for=obs.kind_for)
    except Exception as e:                                  # noqa: BLE001
        log.warning("agent: enrichment failed: %s", e)
        return Outcome("failed", calls=meter.calls, detail=f"{type(e).__name__}: {e}"[:200])

    if res.get("enriched"):
        return Outcome("done", calls=meter.calls,
                       detail=f"{res['enriched']} brand(s) identified, "
                              f"{res.get('synced', 0)} synced to the ledger",
                       result=dict(res))
    return Outcome("failed", calls=meter.calls,
                   detail=f"{res.get('submitted', 0)} brand(s) asked about, none "
                          f"came back",
                   result=dict(res))


def perform(vault, action, obs, best_of: int = BEST_OF) -> Outcome:
    """Dispatch one action. Unknown kinds are reported, never silently skipped."""
    if action.kind in ("induce", "reinduce"):
        return do_induce(action, obs, best_of=best_of)
    if action.kind == "enrich":
        return do_enrich(vault, action, obs)
    return Outcome("failed", detail=f"no hands for a {action.kind!r} action yet")
