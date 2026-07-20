"""viva-bench command line.

Commands:
  validate    check configs, corpus files, and the run plan (no network)
  run         administer the exam (respects budget ceiling; resumable)
  verify-log  recheck the hash chain of the run log
  draft-key   (step 3 — not yet built)
  score       (step 4 — not yet built)
  report      (step 4 — not yet built)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .capture import RunStore
from .config import ConfigError, load_bench_config, load_corpus
from .runner import BudgetExceeded, plan, run_exam


def _load(args):
    config = load_bench_config(Path(args.models))
    corpus = load_corpus(Path(args.corpus))
    store = RunStore(config.data_dir / "runs" / "runs.jsonl")
    return config, corpus, store


def cmd_validate(args) -> int:
    config, corpus, store = _load(args)
    print(f"candidates ({len(config.candidates)}):")
    for c in config.candidates:
        cost = (
            "local/free" if c.cost_per_mtok_in == 0 and c.cost_per_mtok_out == 0
            else f"${c.cost_per_mtok_in}/M in, ${c.cost_per_mtok_out}/M out"
        )
        print(f"  {c.name:<12} {c.adapter:<18} {c.model}  [{cost}]")
    print(f"documents ({len(corpus.documents)}):")
    missing = 0
    for d in corpus.documents:
        exists = d.file.exists()
        missing += 0 if exists else 1
        mark = "ok " if exists else "MISSING"
        print(f"  [{mark}] {d.id:<20} {d.doc_type:<24} {d.locale} {d.currency} ({d.quality})")
    p = plan(config, corpus, store)
    print(
        f"\nrun plan: {p.total_cells} cells total, {p.remaining_cells} remaining, "
        f"${p.spent_usd:.2f} spent of ${p.budget_usd:.2f} ceiling"
    )
    if missing:
        print(f"\n{missing} document file(s) missing — fix corpus.yaml paths.", file=sys.stderr)
        return 1
    print("validate: OK")
    return 0


def cmd_run(args) -> int:
    config, corpus, store = _load(args)
    p = plan(config, corpus, store)
    print(
        f"{p.remaining_cells} of {p.total_cells} cells remaining; "
        f"${p.spent_usd:.2f} spent of ${p.budget_usd:.2f} ceiling"
    )
    if args.dry_run:
        print("dry run: no calls made.")
        return 0
    try:
        run_exam(config, corpus, store, page_cache=config.data_dir / "pages")
    except BudgetExceeded as e:
        print(f"\nBUDGET STOP: {e}", file=sys.stderr)
        return 2
    print(f"\ndone. total spent ${store.spent_usd:.2f}. raw log: {store.path}")
    return 0


def cmd_verify_log(args) -> int:
    config, _, store = _load(args)
    intact, checked = store.verify_chain()
    if intact:
        print(f"hash chain intact across {checked} records.")
        return 0
    print(f"HASH CHAIN BROKEN after {checked} records — the log was altered.", file=sys.stderr)
    return 1


def _not_yet(step: str):
    def _cmd(args) -> int:
        print(f"'{step}' is a later build step (see docs/benchmark-harness-architecture.md §7).")
        return 1
    return _cmd


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="viva-bench", description=__doc__)
    parser.add_argument("--models", default="models.yaml", help="path to models.yaml")
    parser.add_argument("--corpus", default="corpus.yaml", help="path to corpus.yaml")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("validate").set_defaults(func=cmd_validate)
    run_p = sub.add_parser("run")
    run_p.add_argument("--dry-run", action="store_true")
    run_p.set_defaults(func=cmd_run)
    sub.add_parser("verify-log").set_defaults(func=cmd_verify_log)
    for step in ("draft-key", "score", "report"):
        sub.add_parser(step).set_defaults(func=_not_yet(step))

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except ConfigError as e:
        print(f"config error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
