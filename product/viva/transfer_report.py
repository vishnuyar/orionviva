"""What the transfer matcher has done, and what it would do at other windows.

    PYTHONPATH=../core:../merchant:. python3 -m viva.transfer_report
    PYTHONPATH=../core:../merchant:. python3 -m viva.transfer_report --private

No model calls. Read-only unless `--unlink-stale` is passed.

Reports, in order: the links that already exist with their leg gaps and the rule
that decided each; which of them today's rule would still make; what a scan would
auto-link and ask at each window width from 0 to `--max-window`; and how far apart
the legs of the candidate pairs actually are.

`--private` adds the descriptions behind each decision. Calls `transfers.weigh`
and `transfers.decide` rather than reimplementing them, so the rehearsal matches
what a scan performs.

Design rationale: docs/transfer-links-and-cross-document-corroboration.md
"""

from __future__ import annotations

import argparse
import collections
import os
import pathlib


def main() -> int:
    ap = argparse.ArgumentParser(
        description="What the transfer matcher would do at each window width.")
    ap.add_argument("--private", action="store_true",
                    help="also print the descriptions behind each decision")
    ap.add_argument("--max-window", type=int, default=7)
    ap.add_argument("--unlink-stale", action="store_true",
                    help="THE ONE THING HERE THAT WRITES. Revokes the existing "
                         "auto-links today's rule would not make, by appending a "
                         "TransferUnlinked event for each. Nothing is deleted — "
                         "the original link stays in the log, overruled.")
    args = ap.parse_args()

    from .env import load_dotenv
    load_dotenv()
    from .ingest import transfers as T
    from .vault import Vault

    passphrase = os.environ.get("VIVA_PASSPHRASE")
    if not passphrase:
        print("Set VIVA_PASSPHRASE - it opens the vault and is never stored.")
        return 1
    vault_dir = os.environ.get("VIVA_VAULT_DIR", os.path.expanduser("~/.viva-vault"))
    if not pathlib.Path(vault_dir).exists():
        print(f"No vault at {vault_dir}.")
        return 1

    vault = Vault.open(vault_dir, passphrase)
    proj = vault.ledger.projection()
    movements = proj.movements()
    already = [m for m in movements if getattr(m, "linked", False)]

    original = T.DATE_WINDOW_DAYS
    print(f"\nvault            {len(movements)} movement(s)")
    print(f"already linked   {len(already)} movement(s) "
          f"({len(already) // 2} pair(s))")
    print(f"current setting  DATE_WINDOW_DAYS = {T.DATE_WINDOW_DAYS}")
    print("\n  Changing the constant does NOT unlink any of those. The matcher\n"
          "  only ever looks at movements where `linked` is false, so the\n"
          "  setting governs the next scan and never the last one.")

    # Existing links. The forward sweep below sees only unlinked movements,
    # which on a scanned vault is almost nothing.
    dist = T._distinctive(proj)
    profile_for = T.default_profile_for(proj)
    by_key = {m.key: m for m in movements}
    made = []
    for link in proj.transfer_links():
        a, b = by_key.get(link["a"]), by_key.get(link["b"])
        if a is None or b is None:
            continue
        src, dst = (a, b) if T._flow(a) == "source" else (b, a)
        made.append((T._days_apart(a.date, b.date), src, dst,
                     link.get("grade", ""), link.get("by", ""),
                     link.get("decided_by", "")))
    if made:
        print(f"\n{'-' * 72}\nTHE LINKS THAT ALREADY EXIST  ({len(made)})\n{'-' * 72}")
        gap = collections.Counter(d for d, *_ in made)
        run = 0
        for d in sorted(gap):
            run += gap[d]
            print(f"    {d} day(s) apart   {gap[d]:>4} link(s)   "
                  f"cumulative {run}/{len(made)}")
        would_survive = sum(n for d, n in gap.items() if d <= original)
        print(f"\n  {would_survive} of {len(made)} have legs within the current "
              f"window of {original}.")
        if would_survive < len(made):
            print(f"  The other {len(made) - would_survive} were made when the "
                  f"window was wider and are\n  still here — narrowing the "
                  f"constant does not revisit them.")

        by_rule = collections.Counter(m[5] or "(before reasons were recorded)"
                                      for m in made)
        print("\n  What decided each one:")
        for rule, n in by_rule.most_common():
            print(f"    {n:>4}   {rule}")

        auto = [m for m in made if m[4] == "auto"]
        stale = [m for m in auto if not _names(T, proj, m[1], m[2], dist)]
        print(f"\n  {len(auto)} of {len(made)} were made automatically; "
              f"{len(made) - len(auto)} you confirmed.")
        if auto:
            print(f"  Of the automatic ones, today's rule would still make "
                  f"{len(auto) - len(stale)}.")
            if stale:
                print(f"\n  {len(stale)} would NOT be made today: nothing in either")
                print("  description names one of the two accounts distinctively.")
                print("  --private prints them.")
            else:
                print("\n  Every automatic link still stands under today's rule.")

            if stale and args.unlink_stale:
                # `by="auto"`: a rule revoked these, not a person.
                from .ledger.events import transfer_unlinked
                from datetime import date
                today = date.today().isoformat()
                print(f"\n{'=' * 72}\nREVOKING {len(stale)} LINK(S)\n{'=' * 72}")
                for _d, src, dst, _g, _b, _r in stale:
                    vault.ledger.append(transfer_unlinked(
                        src.key, dst.key, today, by="auto"))
                    print(f"  unlinked  {src.account} <-> {dst.account}  "
                          f"{src.currency} {abs(src.amount)}")
                print("\n  The original TransferLinked events are still in the log.")
                print("  Both movements are loose again and the next scan will")
                print("  offer them as questions if they still match.")
            elif stale:
                print("\n  Pass --unlink-stale to revoke them. It appends a")
                print("  TransferUnlinked event each; nothing is deleted.")

    rows = []
    try:
        for w in range(0, max(1, args.max_window) + 1):
            T.DATE_WINDOW_DAYS = w
            graph, sources = T._candidates(proj)
            # The matcher's own scoring and verdict, not a reimplementation.
            strength, reasons = T.weigh(proj, graph, sources, dist, profile_for)
            verdicts = T.decide(graph, strength)

            by_key = {c.key: c for cands in graph.values() for c in cands}
            detail, asked = [], []
            for skey in sorted(graph):
                src = sources[skey]
                cands = graph[skey]
                dkey = verdicts.get(skey)
                if dkey is not None:
                    dst = by_key[dkey]
                    detail.append((T._days_apart(src.date, dst.date), src, dst,
                                   reasons.get((skey, dkey), "")))
                else:
                    # Name which of the four situations produced the question.
                    scores = {c.key: strength.get((skey, c.key), 0) for c in cands}
                    best = max(scores.values(), default=0)
                    if best < T._EV_FLOOR:
                        why = "no account named"
                    elif sum(1 for v in scores.values() if v == best) > 1:
                        why = f"{len(cands)} candidates, evidence tied"
                    else:
                        dkey = next(k for k, v in scores.items() if v == best)
                        rivals = [strength[(s, dkey)] for s in graph
                                  if (s, dkey) in strength]
                        why = ("another source claims it more strongly"
                               if best < max(rivals, default=0)
                               else "tied with another source for the same credit")
                    asked.append((T._days_apart(src.date, cands[0].date), src,
                                  cands, why))
            rows.append((w, len(graph), len(detail), len(asked), detail, asked))
    finally:
        T.DATE_WINDOW_DAYS = original

    print(f"\n{'-' * 72}")
    print("  window   sources w/ candidates   AUTO-LINK   would ASK")
    print(f"{'-' * 72}")
    for w, n, auto, ask, _d, _a in rows:
        mark = "  <- current" if w == original else ""
        print(f"    {w:>3}   {n:>20}   {auto:>9}   {ask:>9}{mark}")
    print("\n  Read this column-wise, not row-wise. AUTO-LINK does not rise")
    print("  monotonically with the window: a wider window finds a second")
    print("  candidate for a source that had one, and that source moves from")
    print("  the AUTO column to the ASK column. Widening buys questions.")

    cur = next((r for r in rows if r[0] == original), None)
    if cur and cur[5]:
        print(f"\n{'-' * 72}\nWHAT THE {cur[3]} QUESTION(S) AT WINDOW {original} "
              f"WOULD BE ABOUT\n{'-' * 72}")
        why = collections.Counter(w for *_r, w in cur[5])
        for reason, n in why.most_common():
            print(f"    {n:>4}   {reason}")
        print("\n  'no account named' is the bucket to watch. Those are single,")
        print("  uncontested, same-amount matches where nothing in either line")
        print("  identifies the other account — the exact shape the deleted word")
        print("  list used to auto-link. They are questions now, not links, which")
        print("  is the intended trade: a coincidence you are asked about beats a")
        print("  coincidence recorded as fact.")

    gaps = collections.Counter()
    widest = rows[-1]
    for days, _s, _d, _r in widest[4]:
        gaps[days] += 1
    if gaps:
        print(f"\n{'-' * 72}\nHOW FAR APART THE LEGS ACTUALLY ARE (at window "
              f"{widest[0]})\n{'-' * 72}")
        run = 0
        for d in sorted(gaps):
            run += gaps[d]
            print(f"    {d} day(s)   {gaps[d]:>4} pair(s)   "
                  f"cumulative {run}/{sum(gaps.values())}")
        print("\n  A window at N catches everything at or below N. If almost all")
        print("  pairs sit at 0-1 days, widening buys nothing and only creates")
        print("  competing candidates; if they spread, narrowing loses real ones.")

    if args.private:
        stale = [m for m in made if m[4] == "auto"
                 and not _names(T, proj, m[1], m[2], dist)]
        if stale:
            print(f"\n{'=' * 72}\nPRIVATE - the {len(stale)} existing auto-link(s) "
                  f"today's rule would NOT make.\n{'=' * 72}")
            for days, src, dst, _g, _b, _r in sorted(stale, key=lambda r: -r[0]):
                print(f"\n  {days} day(s) apart, {src.currency} {abs(src.amount)}")
                print(f"    out  {src.account}  {src.description}")
                print(f"    in   {dst.account}  {dst.description}")
        if cur and cur[4]:
            print(f"\n{'=' * 72}\nPRIVATE - what a scan at window {original} would "
                  f"link now. Yours alone.\n{'=' * 72}")
            for days, src, dst, reason in sorted(cur[4], key=lambda r: -r[0]):
                print(f"\n  {days} day(s) apart, {src.currency} {abs(src.amount)}"
                      f"   [{reason}]")
                print(f"    out  {src.account}  {src.description}")
                print(f"    in   {dst.account}  {dst.description}")
        if cur and cur[5]:
            print(f"\n{'=' * 72}\nPRIVATE - the {cur[3]} question(s) a scan at "
                  f"window {original} would raise.\n{'=' * 72}")
            for days, src, cands, reason in sorted(cur[5], key=lambda r: -abs(r[1].amount)):
                print(f"\n  {src.currency} {abs(src.amount)}   [{reason}]")
                print(f"    out  {src.date}  {src.account}  {src.description}")
                for c in cands[:4]:
                    print(f"    in?  {c.date}  {c.account}  {c.description}")
                if len(cands) > 4:
                    print(f"         ... and {len(cands) - 4} more")
    else:
        print("\n  (the descriptions behind each decision are under --private)")
    return 0


def _names(T, proj, src, dst, dist=None) -> bool:
    """True when `transfers._strong_hint` accepts this pair.

    `dist` is the distinctive-token map; it is recomputed if omitted."""
    d = dist if dist is not None else T._distinctive(proj)
    return bool(T._strong_hint(proj, src, dst, d))


if __name__ == "__main__":
    raise SystemExit(main())
