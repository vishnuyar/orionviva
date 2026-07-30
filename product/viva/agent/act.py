"""Performing one action `policy.assess` proposed, and reporting what it cost.

Two contracts a caller relies on:

- Nothing raises out of this module. Every failure comes back as an `Outcome`
  whose `outcome` is "failed" or "refused" and whose `detail` says why.
- `Outcome.calls` is measured, not estimated: it is how many times the extractor
  was actually invoked, which is usually fewer than `Action.estimated_calls`.

Design rationale: docs/the-maintenance-agent.md
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

# Independent inductions per grammar when a caller names no rule. The operative
# value is `policy.RULES[<rule>]["best_of"]`, which the call estimate reads too.
BEST_OF = 3


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

    `wrap(extract_fn)` returns a callable with the same signature that
    increments `calls` on each invocation. A call count, not a bill: tokens,
    latency and cost do not reach this layer."""

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
    """Induce one (institution × kind) grammar and write it, or say why not.

    Runs `best_of` independent attempts and keeps the one with the highest
    held-out score. Returns an `Outcome`; never raises."""
    from merchantcore.induce import MIN_LINES_TO_INDUCE, Inducer
    from merchantcore.descriptor import is_never_templatable
    from merchantcore.profile import ProfileError

    inst, _, kind = action.target.partition("/")
    counts = obs.pairs.get((inst, kind))
    if not counts:
        return Outcome("failed", detail=f"no movements for {action.target} any more")

    # `assess` counts every distinct line; induction only ever sees the
    # templatable ones, so the threshold is re-checked against those.
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

    # Each attempt is guarded on its own: one that raises is logged and the
    # rest still run.
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

    # Selection is on the held-out score, ties going to the smaller grammar.
    result = max(attempts, key=lambda r: (r.scored,
                                          -len(r.profile.templates) if r.profile else 0))
    spread = [round(r.scored, 4) for r in attempts]
    if errors:
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
        # The store's write-guard rejected the new version; the calls are spent
        # either way, so the refusal is returned rather than raised.
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
    """Enrich the brands the catalog has no record for. Never raises."""
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
    """Dispatch one action to its handler.

    Returns an `Outcome` for every action, including a "failed" one for a kind
    this module has no handler for. Never raises."""
    if action.kind in ("induce", "reinduce"):
        return do_induce(action, obs, best_of=best_of)
    if action.kind == "enrich":
        return do_enrich(vault, action, obs)
    return Outcome("failed", detail=f"no hands for a {action.kind!r} action yet")
