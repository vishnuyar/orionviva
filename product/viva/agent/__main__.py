"""Wake the agent once, and say what it did.

    PYTHONPATH=../core:../merchant:. python3 -m viva.agent --dry-run
    PYTHONPATH=../core:../merchant:. python3 -m viva.agent

A peer of `viva.rescan` rather than a step inside it: `sweep()` makes no model
calls, this does.

`--dry-run` takes the same path — the same observation, rules and budget
arithmetic — and stops before the first model call.

Everything printed by default is counts, institution names, grammar ids and
outcomes: no descriptors, no amounts, no account numbers, no merchant names.
`--private` adds the brand names an enrichment would ask about.

Design rationale: docs/the-maintenance-agent.md
"""

from __future__ import annotations

import argparse
import os
import pathlib
import sys

from .run import budget_calls, wake
from ..env import load_dotenv
from ..logs import configure as configure_logging


def _line(ch: str = "-", n: int = 72) -> None:
    print(ch * n)


def report(run) -> None:
    o = run.observation
    print(f"\nvault        {o['movements']} movement(s)")
    print(f"institutions {o['pairs']} (institution x kind) pair(s), "
          f"{o['inducible_pairs']} of them nameable by a grammar")
    print(f"grammars     {o['grammars']} known")
    print(f"brands       {o['brands_offered']} offered, {o['unknown_brands']} "
          f"with no record yet")
    print(f"budget       {run.calls_budget} call(s) this wake; "
          f"{run.calls_lifetime} spent by this agent in total")

    print()
    _line()
    print(f"CONSIDERED  ({len(run.considered)})")
    _line()
    if not run.considered:
        print("  Nothing. Either this vault is fully served or it holds no "
              "movements yet.")
    for a in run.considered:
        mark = " " if a.autonomous else "*"
        print(f"  {mark} {a.kind:<9} {a.target:<28} ~{a.estimated_calls} call(s)")
        print(f"      {a.why}")
        if a.evidence:
            print(f"      {a.evidence}")
    if any(not a.autonomous for a in run.considered):
        print("\n  * needs a person. Publishing changes what other people see, and "
              "no\n    automated check catches the failure that matters — a grammar "
              "can cover\n    90% of lines while filing cities under {brand}.")

    if run.cooled:
        print()
        _line()
        print(f"HELD BACK  ({len(run.cooled)}) — tried before, nothing has changed")
        _line()
        for a, last in run.cooled:
            print(f"    {a.kind:<9} {a.target}")
            print(f"      last {last.get('outcome')} on {last.get('occurred_at')} "
                  f"after {last.get('calls')} call(s)")
            if last.get("detail"):
                print(f"      {last['detail'][:200]}")
        print("\n  These stay quiet until their evidence moves — not until a timer\n"
              "  expires. Re-running would spend the same calls to reach the same\n"
              "  refusal.")

    if run.deferred:
        print()
        _line()
        print(f"DEFERRED  ({len(run.deferred)}) — over the ceiling for this wake")
        _line()
        for a in run.deferred:
            print(f"    {a.kind:<9} {a.target:<28} ~{a.estimated_calls} call(s)")
        if run.could_not_spend:
            print(f"\n  {run.could_not_spend}")
        else:
            print("\n  Deferred is not refused: the next wake picks these up and "
                  "nothing\n  already paid for is paid for twice. Raise --budget "
                  "to finish in one.")

    print()
    _line()
    print(f"{'WOULD DO' if run.dry_run else 'DID'}  ({len(run.performed)})")
    _line()
    if not run.performed:
        print("  Nothing.")
    for a, out in run.performed:
        print(f"    {out.outcome:<8} {a.kind:<9} {a.target:<28} "
              f"{out.calls} call(s)")
        if out.produced:
            print(f"      wrote {out.produced}"
                  + (f", succeeding {out.replaced}" if out.replaced else ""))
        if out.detail:
            print(f"      {out.detail[:300]}")
    if not run.dry_run:
        print(f"\n  {run.calls_spent} model call(s) spent.")
        if any(o.outcome == "done" and a.kind in ("induce", "reinduce")
               for a, o in run.performed):
            print("  A new grammar is in use on this vault already — that is the "
                  "design, not\n  an oversight: a wrong grammar here is wrong for "
                  "one person and the drift\n  check surfaces it. Reading the "
                  "templates is what PUBLISHING one requires,\n  because that is "
                  "wrong for everybody and no automated check finds it:\n"
                  "      python3 -m viva.induce_profile --verify <profile id>")


def main() -> int:
    ap = argparse.ArgumentParser(description="Wake Viva's agent once.")
    ap.add_argument("--dry-run", action="store_true",
                    help="observe, assess and budget, but spend nothing")
    ap.add_argument("--budget", type=int, default=None,
                    help=f"model calls this wake may spend "
                         f"(default {budget_calls()}, or VIVA_AGENT_BUDGET_CALLS)")
    ap.add_argument("--best-of", type=int, default=None,
                    help="override the rules' best_of: independent inductions "
                         "per grammar, the best held-out score winning. Each one "
                         "costs up to MAX_ROUNDS calls, so this multiplies the "
                         "bill")
    ap.add_argument("--recent-days", type=int, default=120,
                    help="the window a drift check calls 'recent'")
    ap.add_argument("--private", action="store_true",
                    help="also print the brand names an enrichment would ask about")
    ap.add_argument("--log", action="store_true",
                    help="print this agent's whole history and do nothing else")
    args = ap.parse_args()

    load_dotenv()
    configure_logging()
    from ..vault import Vault

    passphrase = os.environ.get("VIVA_PASSPHRASE")
    if not passphrase:
        print("Set VIVA_PASSPHRASE — it opens the vault and is never stored.")
        return 1
    vault_dir = os.environ.get("VIVA_VAULT_DIR", os.path.expanduser("~/.viva-vault"))
    if not pathlib.Path(vault_dir).exists():
        print(f"No vault at {vault_dir}.")
        return 1

    vault = Vault.open(vault_dir, passphrase)

    if args.log:
        entries = vault.ledger.projection().agent_log()
        print(f"\n{len(entries)} action(s) taken unattended\n")
        for e in entries:
            print(f"  {e.get('occurred_at')}  {e.get('outcome'):<8} "
                  f"{e.get('kind'):<9} {e.get('target'):<28} "
                  f"{e.get('calls')} call(s)")
            if e.get("produced"):
                print(f"      wrote {e['produced']}")
            if e.get("detail"):
                print(f"      {e['detail'][:200]}")
        if not entries:
            print("  (nothing yet)")
        return 0

    run = wake(vault, remaining_calls=args.budget, dry_run=args.dry_run,
               best_of_override=args.best_of, recent_days=args.recent_days)
    report(run)

    if args.private:
        from .observe import observe
        obs = observe(vault, recent_days=args.recent_days)
        unknown = sorted(k for k in obs.offered
                         if obs.catalog.get(k) is None)
        print()
        _line()
        print("PRIVATE — the brands an enrichment would ask about")
        _line()
        for k in unknown:
            print(f"    {k}")
        print(f"\n  {len(unknown)} brand(s). These are impersonal by "
              "construction — a person\n  withheld by a grammar slot never "
              "reaches this list — but they are\n  still your shopping, so this "
              "output is for you.")

    if run.dry_run:
        print("\nDry run: nothing was spent and nothing was written.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
