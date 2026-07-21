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

from dataclasses import replace

from .capture import RunStore
from .config import ConfigError, Corpus, load_bench_config, load_corpus
from .corpus import page_texts, text_gaps
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
        base = c.base_url or ""
        if "openrouter.ai" in base:
            cost = "OpenRouter — billed at runtime (exact cost read per call)"
        elif "localhost" in base or "127.0.0.1" in base:
            cost = "local/free"
        elif c.cost_per_mtok_in == 0 and c.cost_per_mtok_out == 0:
            cost = "cost unset (0/M) — budget guard will undercount"
        else:
            cost = f"${c.cost_per_mtok_in}/M in, ${c.cost_per_mtok_out}/M out"
        print(f"  {c.name:<12} {c.adapter:<18} {c.model}  [{cost}]")
    print(f"input mode: {config.input_mode}")
    print(f"documents ({len(corpus.documents)}):")
    missing = 0
    no_text = []
    for d in corpus.documents:
        exists = d.file.exists()
        missing += 0 if exists else 1
        mark = "ok " if exists else "MISSING"
        # Text coverage decides which input modes a document can even be run in.
        cov = ""
        if exists:
            texts = page_texts(d, config.data_dir / "pages")
            gaps = text_gaps(d, config.data_dir / "pages")
            if gaps:
                no_text.append(f"{d.id} (pages {gaps})")
            cov = f"  text {sum(len(t) for t in texts)}ch" + (
                f", NO TEXT on {gaps}" if gaps else "")
        print(f"  [{mark}] {d.id:<20} {d.doc_type:<24} {d.locale} {d.currency} "
              f"({d.quality}){cov}")
    if no_text and config.input_mode in ("text", "text+image"):
        print(f"\n{len(no_text)} document(s) lack a full text layer and cannot run in "
              f"{config.input_mode!r}: {', '.join(no_text)}", file=sys.stderr)
        return 1
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
    # A subset run is the same exam, just less of it: same prompt, same roster,
    # same log. Records land in the real chain, so a subset used to check
    # quality first is not throwaway spend — the full run resumes around it.
    if args.doc:
        wanted = [d.strip() for d in args.doc.split(",") if d.strip()]
        for doc_id in wanted:
            corpus.document(doc_id)      # raises ConfigError on a typo
        corpus = Corpus(documents=[d for d in corpus.documents if d.id in wanted])
        print(f"subset: {len(corpus.documents)} of the corpus ({', '.join(wanted)})")
    if args.mode:
        config = replace(config, input_mode=args.mode)
        print(f"input mode: {args.mode}")
    if args.runs is not None:
        if args.runs < 1:
            print("--runs must be at least 1.", file=sys.stderr)
            return 1
        config = replace(config, runs_per_document=args.runs)
        print(f"subset: {args.runs} run(s) per document instead of "
              f"{load_bench_config(Path(args.models)).runs_per_document}")
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
    if not store.path.exists():
        print(f"no run log yet at {store.path} — nothing to verify.")
        return 0
    intact, checked = store.verify_chain()
    if intact:
        print(f"hash chain intact across {checked} records.")
        return 0
    print(f"HASH CHAIN BROKEN after {checked} records — the log was altered.", file=sys.stderr)
    return 1


def cmd_draft_key(args) -> int:
    from .keybuild import draft_key, merge_drafts
    from .claims import save_key, parse_claims
    import json as _json

    config, corpus, store = _load(args)
    drafters = args.drafters.split(",") if args.drafters else [c.name for c in config.candidates[:2]]
    keys_dir = config.data_dir / "keys"
    docs = [corpus.document(args.doc)] if args.doc else corpus.documents

    logged: dict[tuple[str, str], list] = {}
    if args.from_log:
        # Reuse extractions already paid for, instead of re-calling the models.
        # A key is ground truth about the DOCUMENT, so any input mode's read is a
        # valid source; --mode picks which logged read to draft from.
        for rec in store.iter_records():
            if rec.get("status") != "ok" or rec.get("input_mode", "image") != args.mode:
                continue
            claims, _ = parse_claims(rec.get("text", ""))
            logged[(rec["doc_id"], rec["candidate"])] = claims

    for doc in docs:
        print(f"drafting key for {doc.id} using {drafters} ...")
        if args.from_log:
            extractions = {n: logged.get((doc.id, n), []) for n in drafters}
            have = {n: len(v) for n, v in extractions.items()}
            if any(v == 0 for v in have.values()):
                print(f"  SKIP {doc.id}: no logged {args.mode!r} extraction for "
                      f"{[n for n, v in have.items() if v == 0]}", file=sys.stderr)
                continue
            print(f"  from log ({args.mode}): " +
                  ", ".join(f"{n}={c}" for n, c in have.items()))
            key, drafts = merge_drafts(doc, extractions, drafters)
        else:
            key, drafts = draft_key(doc, config, drafters, config.data_dir / "pages")
        # Auto-resolve nothing; write draft + an audit worksheet the human fills in.
        save_key(key, keys_dir / f"{doc.id}.key.json")
        worksheet = keys_dir / f"{doc.id}.audit.json"
        worksheet.write_text(_json.dumps(
            [{"type": d.type, "label": d.label, "values": d.values,
              "agree": d.agree, "resolved": d.resolved} for d in drafts if not d.agree],
            indent=2, ensure_ascii=False))
        print(f"  wrote {keys_dir}/{doc.id}.key.json (corroborated entries) "
              f"and {doc.id}.audit.json (disagreements to resolve)")
    print("\nNext: fill 'resolved' in each *.audit.json, then `viva-bench freeze-key`.")
    return 0


def cmd_freeze_key(args) -> int:
    from .claims import load_key, save_key, KeyEntry
    from .keybuild import freeze
    import json as _json

    config, corpus, _ = _load(args)
    keys_dir = config.data_dir / "keys"
    docs = [corpus.document(args.doc)] if args.doc else corpus.documents
    for doc in docs:
        kp = keys_dir / f"{doc.id}.key.json"
        if not kp.exists():
            continue
        key = load_key(kp)
        wp = keys_dir / f"{doc.id}.audit.json"
        if wp.exists():
            for row in _json.loads(wp.read_text()):
                if row.get("resolved"):
                    key.entries.append(KeyEntry(
                        type=row["type"], label=row["label"], value_raw=row["resolved"],
                        locale=key.locale, currency=key.currency, verified_by="human"))
        key, digest = freeze(key)
        save_key(key, kp)
        (keys_dir / f"{doc.id}.key.sha256").write_text(digest + "\n")
        print(f"{doc.id}: frozen, {len(key.entries)} entries, sha256 {digest[:16]}...")
    return 0


def cmd_score(args) -> int:
    from .claims import load_key
    from .score import grade_run, build_scorecards
    from .report import write_reports

    config, corpus, store = _load(args)
    keys_dir = config.data_dir / "keys"
    doc_type_of = {d.id: d.doc_type for d in corpus.documents}
    locale_of = {d.id: d.locale for d in corpus.documents}
    keys = {}
    for d in corpus.documents:
        kp = keys_dir / f"{d.id}.key.json"
        if kp.exists():
            keys[d.id] = load_key(kp)
    if not keys:
        print("no answer keys found — run draft-key + freeze-key first.", file=sys.stderr)
        return 1

    run_grades = []
    scored_modes: set[str] = set()
    for rec in store.iter_records():
        if rec.get("status") != "ok":
            continue
        if args.mode and rec.get("input_mode", "image") != args.mode:
            continue
        key = keys.get(rec["doc_id"])
        if key is None:
            continue
        scored_modes.add(rec.get("input_mode", "image"))
        run_grades.append(grade_run(
            rec["doc_id"], rec["candidate"], rec["run_index"], rec.get("text", ""), key))
    if not run_grades:
        print("no scorable runs (need runs whose documents have keys).", file=sys.stderr)
        return 1
    print(f"scoring input mode(s): {', '.join(sorted(scored_modes))}")
    cards = build_scorecards(run_grades, doc_type_of, locale_of)
    md, js = write_reports(cards, config.data_dir / "reports")
    print(f"scored {len(run_grades)} runs into {len(cards)} scorecards.")
    print(f"findings: {md}\nscorecards: {js}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="viva-bench", description=__doc__)
    parser.add_argument("--models", default="models.yaml", help="path to models.yaml")
    parser.add_argument("--corpus", default="corpus.yaml", help="path to corpus.yaml")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("validate").set_defaults(func=cmd_validate)
    run_p = sub.add_parser("run")
    run_p.add_argument("--dry-run", action="store_true")
    run_p.add_argument("--doc", help="only these document ids (comma-separated)")
    run_p.add_argument("--runs", type=int, help="override runs_per_document for this run")
    run_p.add_argument(
        "--mode", choices=("image", "text", "text+image"),
        help="input mode for this run (default: models.yaml input_mode)",
    )
    run_p.set_defaults(func=cmd_run)
    sub.add_parser("verify-log").set_defaults(func=cmd_verify_log)

    dk = sub.add_parser("draft-key", help="two models draft an answer key per document")
    dk.add_argument("--doc", help="single document id (default: all)")
    dk.add_argument("--drafters", help="comma-separated candidate names (default: first two)")
    dk.add_argument("--from-log", action="store_true",
                    help="draft from extractions already in the run log (no new model calls)")
    dk.add_argument("--mode", choices=("image", "text", "text+image"), default="image",
                    help="with --from-log: which logged input mode to draft from")
    dk.set_defaults(func=cmd_draft_key)

    fk = sub.add_parser("freeze-key", help="fold audits, freeze, hash")
    fk.add_argument("--doc", help="single document id (default: all)")
    fk.set_defaults(func=cmd_freeze_key)

    sc = sub.add_parser("score", help="grade runs against frozen keys, emit findings")
    sc.add_argument("--mode", choices=("image", "text", "text+image"),
                    help="only score runs from this input mode (default: all)")
    sc.set_defaults(func=cmd_score)
    sub.add_parser("report").set_defaults(func=cmd_score)  # alias

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except ConfigError as e:
        print(f"config error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
