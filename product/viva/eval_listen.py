"""Measure a model on the one job Slice 9a gives it: reading a sentence.

    python -m viva.eval_listen                    # the configured interpreter
    python -m viva.eval_listen --model qwen3:4b --base-url http://localhost:11434/v1
    python -m viva.eval_listen --repeat 3         # variance, not a single lucky run

**The headline metric is not accuracy.** It is the *confidently-wrong rate* —
the eval-harness thesis, applied to its first real subject. A model that returns
nothing costs a person one tap on a button that was already there; a model that
invents a 60/40 mortgage split writes a wrong number into someone's finances,
grades it `verified` because a human confirmed a sentence they did believe, and
generalizes it across every future payment to that counterparty. Those two
failures are not on the same scale, so this scores them apart:

  SAFE      unreadable         no JSON, or no legs → the buttons still work
  WRONG     wrong_majors       a confident misreading
  RUIN      invented_split     a fabricated ratio nobody stated  ← never non-zero
  RUIN      leaked_amount      a figure from the model's head (T2 / ADR-010)
  WEAK      missed_compound    read a mortgage as one thing

`missed_compound` sits between: it does not fabricate, but it silently collapses
a three-way payment into one nature, which is exactly the error that started
this slice. Worth watching, not disqualifying.

Everything runs against a **frozen, synthetic key** (`evals/listen_cases.json`)
so it is free, offline-capable, reproducible, and safe in a public repo.

Several cases are genuinely ambiguous — is an ATM withdrawal cash you still have,
or money spent? — so the key accepts a *set* of correct readings. A key that
insisted on one would measure obedience rather than understanding.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import statistics
import time

from .listen import interpret

CASES = pathlib.Path(__file__).parent / "evals" / "listen_cases.json"

SAFE, WRONG, RUIN, WEAK, OK = "unreadable", "wrong", "RUIN", "weak", "ok"


def load_cases(path: pathlib.Path = CASES) -> dict:
    return json.loads(path.read_text())


def score_one(case: dict, interp, raw_text: str = "") -> dict:
    """Grade one reading against the key. Returns the verdict and why."""
    if not interp.legs:
        # The safe failure: we could not read it, so we do not guess.
        return {"verdict": SAFE, "why": "no legs returned", "majors": []}

    majors = sorted({leg["major"] for leg in interp.legs})
    accept = [sorted(a) for a in case["accept"]]
    problems = []

    # RUIN 1 — a ratio nobody stated. The single worst thing this model can do.
    if not case.get("shares_stated") and any(leg.get("share") for leg in interp.legs):
        problems.append((RUIN, "invented a split nobody stated"))
    # RUIN 2 — a figure from the model's own head.
    if '"amount"' in (raw_text or "") or any("amount" in leg for leg in interp.legs):
        problems.append((RUIN, "emitted an amount"))

    if majors not in accept:
        problems.append((WRONG, f"read as {'+'.join(majors)}, expected "
                                f"{' or '.join('+'.join(a) for a in accept)}"))
    elif case.get("compound") and len(interp.legs) < 2:
        problems.append((WEAK, "collapsed a compound payment into one leg"))

    if not problems:
        return {"verdict": OK, "why": "", "majors": majors}
    # Worst verdict wins, so one ruin failure is never averaged away by successes.
    rank = {RUIN: 3, WRONG: 2, WEAK: 1}
    problems.sort(key=lambda p: -rank[p[0]])
    return {"verdict": problems[0][0], "why": "; ".join(p[1] for p in problems),
            "majors": majors}


def run(extract_fn, cases: dict, repeat: int = 1) -> dict:
    """Run every case `repeat` times. Repetition is not padding: a model that
    answers correctly two times in three is a different product than one that
    always does, and a single run cannot tell them apart."""
    rows, latencies = [], []
    for case in cases["cases"]:
        for attempt in range(repeat):
            started = time.monotonic()
            captured = {}

            def spy(prompt, _fn=extract_fn, _c=captured):
                out = _fn(prompt)
                _c["raw"] = out
                return out

            interp = interpret(case["said"], case["descriptor"],
                               case.get("category", ""), case.get("subcategory", ""),
                               extract_fn=spy)
            elapsed = time.monotonic() - started
            latencies.append(elapsed)
            row = score_one(case, interp, captured.get("raw", ""))
            row.update(id=case["id"], said=case["said"], attempt=attempt,
                       seconds=round(elapsed, 2), kind=interp.kind)
            rows.append(row)

    n = len(rows) or 1
    counts = {v: sum(1 for r in rows if r["verdict"] == v)
              for v in (OK, SAFE, WEAK, WRONG, RUIN)}
    unstable = sorted({r["id"] for r in rows
                       if len({x["verdict"] for x in rows if x["id"] == r["id"]}) > 1})
    return {
        "n": n, "cases": len(cases["cases"]), "repeat": repeat,
        "counts": counts,
        "rates": {k: round(v / n, 3) for k, v in counts.items()},
        # The number that decides whether this model may be trusted at all.
        "confidently_wrong": round((counts[WRONG] + counts[RUIN]) / n, 3),
        "latency_p50": round(statistics.median(latencies), 2) if latencies else 0,
        "latency_max": round(max(latencies), 2) if latencies else 0,
        "unstable": unstable,
        "rows": rows,
    }


def report(result: dict, key_version: str = "") -> str:
    c, r = result["counts"], result["rates"]
    out = [
        f"listen eval — {result['cases']} cases x{result['repeat']} = {result['n']} readings"
        + (f"  (key {key_version})" if key_version else ""),
        "",
        f"  ok               {c[OK]:3}   {r[OK]:.0%}",
        f"  unreadable       {c[SAFE]:3}   {r[SAFE]:.0%}   safe — the buttons still work",
        f"  missed compound  {c[WEAK]:3}   {r[WEAK]:.0%}   weak — collapses a mortgage",
        f"  wrong majors     {c[WRONG]:3}   {r[WRONG]:.0%}   confidently wrong",
        f"  RUIN             {c[RUIN]:3}   {r[RUIN]:.0%}   fabricated a split or an amount",
        "",
        f"  CONFIDENTLY WRONG RATE: {result['confidently_wrong']:.1%}"
        + ("   <- the number that matters" if result["confidently_wrong"] else "   clean"),
        f"  latency  p50 {result['latency_p50']}s   max {result['latency_max']}s",
    ]
    if result["unstable"]:
        out.append(f"  unstable across runs: {', '.join(result['unstable'])}")
    bad = [x for x in result["rows"] if x["verdict"] not in (OK,)]
    if bad:
        out += ["", "  what it got wrong:"]
        seen = set()
        for x in bad:
            if x["id"] in seen:
                continue
            seen.add(x["id"])
            out.append(f"    [{x['verdict']:10}] {x['id']:18} \"{x['said'][:44]}\" — {x['why']}")
    # An honest verdict, stated in the terms the project actually cares about.
    out += ["", "  " + _verdict(result)]
    return "\n".join(out)


def _verdict(result: dict) -> str:
    if result["counts"][RUIN]:
        return ("VERDICT: do not use this model. It fabricated a figure or a "
                "split — the one failure this project treats as ruin.")
    if result["confidently_wrong"] > 0.10:
        return (f"VERDICT: too risky. {result['confidently_wrong']:.0%} of readings were "
                "confidently wrong, and a wrong ruling generalizes across every "
                "future payment to that counterparty.")
    if result["rates"][SAFE] > 0.25:
        return ("VERDICT: safe but weak — it declines often. Nothing is corrupted; "
                "the person just falls back to buttons more than they should.")
    return ("VERDICT: usable. No fabrication, few confident errors. Re-run after "
            "any prompt change — this is a regression test, not a one-off.")


def main() -> None:
    import os

    ap = argparse.ArgumentParser(description="Measure a model on reading a sentence.")
    ap.add_argument("--model", default=os.environ.get("VIVA_INTERPRET_MODEL")
                    or os.environ.get("VIVA_MODEL"))
    ap.add_argument("--base-url", default=os.environ.get("VIVA_INTERPRET_BASE_URL")
                    or os.environ.get("VIVA_MODEL_BASE_URL"))
    ap.add_argument("--key-env", default=os.environ.get("VIVA_INTERPRET_KEY_ENV", "none"))
    ap.add_argument("--adapter", default=os.environ.get("VIVA_INTERPRET_ADAPTER",
                                                        "openai-compatible"))
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--json", action="store_true", help="machine-readable, for tracking over time")
    args = ap.parse_args()

    if not args.model:
        raise SystemExit("No model. Pass --model, or set VIVA_INTERPRET_MODEL.")

    from merchantcore.enrich import model_extractor
    from vivacore.models import ModelSpec

    spec = ModelSpec(
        name="viva-listen-eval", adapter=args.adapter, model=args.model,
        base_url=args.base_url,
        api_key_env=None if (args.key_env or "").lower() in ("", "none") else args.key_env,
        max_tokens=512, json_mode=True)
    cases = load_cases()
    result = run(model_extractor(spec), cases, repeat=args.repeat)
    if args.json:
        print(json.dumps({k: v for k, v in result.items() if k != "rows"}, indent=2))
    else:
        print(f"model: {args.model}  via {args.base_url or 'default'}\n")
        print(report(result, cases.get("version", "")))


if __name__ == "__main__":
    main()
