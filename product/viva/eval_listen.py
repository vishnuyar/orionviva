"""Measure a model on one job: reading a sentence into a structured reading.

    python -m viva.eval_listen                    # the configured interpreter
    python -m viva.eval_listen --model qwen3:4b --base-url http://localhost:11434/v1
    python -m viva.eval_listen --repeat 3         # variance across runs

The headline metric is the confidently-wrong rate rather than accuracy. Every
reading is graded into one of:

  SAFE      unreadable         no JSON, or no legs → nothing is recorded and
                               the person is asked again in Viva's voice
  WRONG     wrong_majors       a confident misreading
  RUIN      invented_split     a ratio nobody stated
  RUIN      leaked_amount      a figure from the model's head
  WEAK      missed_compound    a compound payment collapsed into one leg

A call that never reached the model is BROKEN: it is excluded from every rate and
reported on its own.

**This measures ONE call.** The live path gives a model that did not fill the
slots a second attempt before anyone is asked anything; the eval deliberately
does not, because what it is grading is the model's reading, not the harness
around it. So the unreadable rate here is the upper bound on what a person would
actually be asked to repeat.

Cases come from a frozen synthetic key (`evals/listen_cases.json`), so a run is
free, offline-capable and reproducible. Each case accepts a *set* of correct
readings, since some sentences have more than one right answer.

`--repeat N` runs each case N times and names the ids whose verdict varied.
`--json` prints the aggregate without the per-reading rows. `--probe` makes one
call and prints the raw reply. `--no-json-mode` drops `response_format`.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import statistics
import time

from .honesty import rate, refusal_rate
from .ingest.categorize import SEED_CATEGORIES
from .listen import ruling_context, ruling_from, ruling_slots
from .reply import interpret as fill_slots
from .reply import MAX_REPLY_TOKENS, read_reply

CASES = pathlib.Path(__file__).parent / "evals" / "listen_cases.json"

# The slots this instrument asks with: the product's own structure, built by
# the function the live path calls. The harness holds no vault, so the
# vocabulary it offers is the seeds rather than a vault's grown list.
EVAL_SLOTS = ruling_slots(SEED_CATEGORIES)

SAFE, WRONG, RUIN, WEAK, OK = "unreadable", "wrong", "RUIN", "weak", "ok"
# A call that never reached the model at all — a wrong model name, an
# unreachable server, a rejected parameter. Distinct from `unreadable`, which is
# the model answering with something unusable: BROKEN readings are excluded from
# every rate rather than counted as safe.
BROKEN = "BROKEN"


def load_cases(path: pathlib.Path = CASES) -> dict:
    return json.loads(path.read_text())


def score_one(case: dict, interp, raw_text: str = "") -> dict:
    """Grade one reading against the key. Returns the verdict and why."""
    if interp.failure == "unreachable":
        # Not a model result at all. Never scored, never averaged in.
        return {"verdict": BROKEN, "why": f"never reached the model: {interp.detail}",
                "majors": []}
    if not interp.legs:
        # The safe failure: the model answered and we could not use it.
        why = {"unparseable": f"reply was not JSON: {interp.detail}",
               "empty": "valid JSON, but no usable legs"}.get(
                   interp.failure, "no legs returned")
        return {"verdict": SAFE, "why": why, "majors": [],
                "raw": (interp.raw or "")[:200]}

    majors = sorted({leg["major"] for leg in interp.legs})
    accept = [sorted(a) for a in case["accept"]]
    problems = []

    # RUIN 1 — a share, where the case records that nobody stated one.
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
    """Run every case `repeat` times and aggregate.

    Returns the verdict counts, the rates over readings that reached the model,
    `confidently_wrong` (None when nothing was measured), latency p50 and max,
    `unstable` — the case ids whose verdict varied across attempts — and every
    scored row."""
    rows, latencies = [], []
    for case in cases["cases"]:
        for attempt in range(repeat):
            started = time.monotonic()
            captured = {}

            def spy(prompt, _fn=extract_fn, _c=captured):
                out = _fn(prompt)
                _c["raw"] = out
                return out

            # The two halves, run apart rather than through `reply.answer`, so a
            # reading that never reached the model is told apart from one the
            # checks refused — and so the underlying cause survives into the
            # report instead of becoming an unexplained failure.
            filled = fill_slots(
                case["said"], EVAL_SLOTS,
                context=ruling_context(case["descriptor"],
                                       case.get("category", ""),
                                       case.get("subcategory", "")),
                extract_fn=spy)
            checked = read_reply(EVAL_SLOTS, filled.values)
            interp = ruling_from(checked, case["said"])
            interp.raw = filled.raw
            if filled.failure:
                interp.failure, interp.detail = filled.failure, filled.detail
            elapsed = time.monotonic() - started
            latencies.append(elapsed)
            row = score_one(case, interp, captured.get("raw", ""))
            row.update(id=case["id"], said=case["said"], attempt=attempt,
                       seconds=round(elapsed, 2), kind=interp.kind)
            rows.append(row)

    n = len(rows) or 1
    counts = {v: sum(1 for r in rows if r["verdict"] == v)
              for v in (OK, SAFE, WEAK, WRONG, RUIN, BROKEN)}
    # Rates are over readings that reached the model; BROKEN ones are excluded
    # from the denominator rather than counted as safe.
    scored = n - counts[BROKEN] or 1
    unstable = sorted({r["id"] for r in rows
                       if len({x["verdict"] for x in rows if x["id"] == r["id"]}) > 1})
    return {
        "n": n, "cases": len(cases["cases"]), "repeat": repeat,
        "counts": counts,
        "scored": n - counts[BROKEN],
        "rates": {k: rate(v, scored) or 0.0 for k, v in counts.items()},
        # `None` when nothing was measured: an unknown rate is not a zero rate.
        # The definition is the harness's, imported rather than repeated, so
        # two reports of one measurement cannot disagree about the edges.
        "confidently_wrong": (None if counts[BROKEN] == n
                              else rate(counts[WRONG] + counts[RUIN], scored)),
        # How often the model declined to make a reading at all. It is safe and
        # is never confidently wrong, and it is reported because a model that
        # declines everything scores a perfect confidently-wrong rate — the one
        # way that headline can be read as saying more than it does.
        "refusal_rate": refusal_rate(counts[SAFE], scored),
        "latency_p50": round(statistics.median(latencies), 2) if latencies else 0,
        "latency_max": round(max(latencies), 2) if latencies else 0,
        "unstable": unstable,
        "rows": rows,
    }


def report(result: dict, key_version: str = "") -> str:
    c, r = result["counts"], result["rates"]
    if c[BROKEN] == result["n"]:
        # Nothing reached the model, so the report makes no claim about it.
        first = next(x for x in result["rows"] if x["verdict"] == BROKEN)
        return "\n".join([
            f"NOTHING WAS MEASURED — all {result['n']} calls failed before "
            "reaching the model.",
            "",
            f"  {first['why']}",
            f"  latency p50 {result['latency_p50']}s — far too fast for inference,"
            " which is the tell.",
            "",
            "  This is NOT a result. The model has no score, good or bad.",
            "  Check, in order:",
            "    ollama list                      is the model pulled, spelled exactly?",
            "    curl http://localhost:11434/v1/models    is the server up on that port?",
            "    --no-json-mode                   some local servers reject response_format",
        ])
    out = [
        f"listen eval — {result['cases']} cases x{result['repeat']} = {result['n']} readings"
        + (f"  (key {key_version})" if key_version else ""),
        "",
        f"  ok               {c[OK]:3}   {r[OK]:.0%}",
        f"  unreadable       {c[SAFE]:3}   {r[SAFE]:.0%}   safe — nothing recorded, asked again",
        f"  missed compound  {c[WEAK]:3}   {r[WEAK]:.0%}   weak — collapses a mortgage",
        f"  wrong majors     {c[WRONG]:3}   {r[WRONG]:.0%}   confidently wrong",
        f"  RUIN             {c[RUIN]:3}   {r[RUIN]:.0%}   fabricated a split or an amount",
    ] + ([f"  BROKEN           {c[BROKEN]:3}         never reached the model — NOT scored"]
         if c[BROKEN] else []) + [
        "",
        f"  CONFIDENTLY WRONG RATE: {result['confidently_wrong']:.1%}"
        + ("   <- the number that matters" if result["confidently_wrong"] else "   clean"),
        # Beside it, always. A model that declines everything scores a perfect
        # confidently-wrong rate, and the two figures read together are what
        # stop that being mistaken for a good one.
        f"  refusal rate:           "
        + ("not measured" if result["refusal_rate"] is None
           else f"{result['refusal_rate']:.1%}"),
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
    out += ["", "  " + _verdict(result)]
    return "\n".join(out)


def _verdict(result: dict) -> str:
    if result["counts"][BROKEN]:
        return (f"VERDICT: partial — {result['counts'][BROKEN]} call(s) never reached "
                f"the model, so this scores only {result['scored']} readings. Fix the "
                "connection before trusting any of it.")
    if result["counts"][RUIN]:
        return ("VERDICT: do not use this model. It fabricated a figure or a "
                "split — the one failure this project treats as ruin.")
    if result["confidently_wrong"] > 0.10:
        return (f"VERDICT: too risky. {result['confidently_wrong']:.0%} of readings were "
                "confidently wrong, and a wrong ruling generalizes across every "
                "future payment to that counterparty.")
    if result["rates"][SAFE] > 0.25:
        return ("VERDICT: safe but weak — it declines often. Nothing is corrupted; "
                "the person is just asked to say it again more often than they "
                "should have to be.")
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
    ap.add_argument("--no-json-mode", action="store_true",
                    help="drop response_format — some local servers reject it")
    ap.add_argument("--probe", action="store_true",
                    help="one call, printing the raw reply; reach for this the moment "
                         "a real answer comes back unread")
    ap.add_argument("--say", default="i bought a car",
                    help="the sentence to probe with — paste the one that failed")
    ap.add_argument("--counterparty", default="NORTHSIDE MOTORS")
    ap.add_argument("--json", action="store_true", help="machine-readable, for tracking over time")
    args = ap.parse_args()

    if not args.model:
        raise SystemExit("No model. Pass --model, or set VIVA_INTERPRET_MODEL.")

    from vivacore.models import ModelSpec

    from .listen import one_shot_extractor

    spec = ModelSpec(
        name="viva-listen-eval", adapter=args.adapter, model=args.model,
        base_url=args.base_url,
        api_key_env=None if (args.key_env or "").lower() in ("", "none") else args.key_env,
        max_tokens=MAX_REPLY_TOKENS, json_mode=not args.no_json_mode)
    if args.probe:
        return _probe(spec, said=args.say, counterparty=args.counterparty)
    cases = load_cases()
    result = run(one_shot_extractor(spec), cases, repeat=args.repeat)
    if args.json:
        print(json.dumps({k: v for k, v in result.items() if k != "rows"}, indent=2))
    else:
        print(f"model: {args.model}  via {args.base_url or 'default'}\n")
        print(report(result, cases.get("version", "")))


def _probe(spec, said: str = "i bought a car",
           counterparty: str = "NORTHSIDE MOTORS", extract_fn=None) -> None:
    """One call, with the prompt version, the endpoint, the raw reply, the
    checked legs and the failure all printed. An exception here is not swallowed
    the way the eval swallows it: it prints and exits 1.

    The two halves run apart, exactly as `run` runs them, so the reading printed
    is the one that reply produced — no second call, and no second reading of
    the same words. ``extract_fn`` replaces the live model edge, which is what
    lets this be exercised without one."""
    from .listen import one_shot_extractor
    from .reply import INTERPRET_VERSION
    from .ingest.prompt_library import interpret_prompt
    _text, version = interpret_prompt(INTERPRET_VERSION)
    print(f"prompt {version}, said={said!r}")
    print(f"POST {spec.base_url}  model={spec.model}  json_mode={spec.json_mode}\n")
    captured = {}
    call = extract_fn or one_shot_extractor(spec)

    def spy(prompt):
        captured["raw"] = call(prompt)
        return captured["raw"]

    try:
        filled = fill_slots(said, EVAL_SLOTS,
                            context=ruling_context(counterparty),
                            extract_fn=spy)
    except Exception as exc:                       # noqa: BLE001 - this is the point
        print(f"FAILED: {type(exc).__name__}: {exc}")
        raise SystemExit(1)
    print("RAW REPLY:\n" + (captured.get("raw") or "(empty)"))
    if filled.failure == "unreachable":
        print(f"FAILED: {filled.detail}")
        raise SystemExit(1)
    read = read_reply(EVAL_SLOTS, filled.values)
    got = ruling_from(read, said)
    print(f"\nfilled:       {filled.failure or 'ok'}")
    print(f"checked legs: {got.legs or 'NONE'}")
    print(f"category:     {got.category or '(none)'}")
    print(f"failure:      {filled.failure or read.why or got.failure or 'none'}")


if __name__ == "__main__":
    main()
