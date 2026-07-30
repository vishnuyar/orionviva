"""How much of this vault do the patterns we already have explain? No model calls.

    PYTHONPATH=../core:../merchant:. python3 -m viva.pattern_report
    PYTHONPATH=../core:../merchant:. python3 -m viva.pattern_report --private

This is the free half of the match-before-ask design, and it exists to answer
one question before anything is paid for: **does one bank's sentence shape
explain another bank's lines?**

If it does, an account too small to teach a grammar — twenty distinct lines, a
minimum of thirty, forever — is explicable anyway, and the model's job further
down the pipeline is only to spot near-misses. If it does not, borrowing is a
weaker idea than it looks, and we have learned that for nothing.

Four buckets per account, and the fourth is the interesting one:

    own          this bank's own grammar explained the line
    borrowed     another bank's grammar did, and it says whose
    published    a card or ACH specification proved some structure, but no
                 template claimed the whole line
    pile         nothing explained it — the population induction should see

Wires sit outside all four. They are not unexplained: the Fedwire tags identify
them exactly, which is a published specification and not a guess. What cannot be
done is decide which part of the operator's free text is the counterparty, and
that is a question for a person rather than a hole in a pile.

WHAT IS SAFE TO SHARE. By default: counts, percentages, institution names and
profile ids. `--private` adds the masked shapes in the pile — and a masked spine
keeps every word printed twice, which includes a name, so that output is yours.
"""

from __future__ import annotations

import argparse
import collections
import os
import pathlib


def _pct(part: int, whole: int) -> str:
    return f"{(part / whole):.0%}" if whole else "-"


def _gate(pairs, target: str, private: bool) -> int:
    """Why a pair keeps missing the gate, computed without a single model call.

    THE SUSPICION THIS TESTS. The holdout is split by DISTINCT LINE - one line
    in five is withheld, chosen by a hash of its own text - and then scored by
    MOVEMENT. Those two choices fight each other. If one line carries a tenth of
    the account's movements, whether the grammar clears 80% is decided by which
    side of a hash that single line lands on, and not by the grammar at all.

    Six independent inductions of one account returned exactly 79% - across two
    different prompts. A number that stable is not a measurement of a stochastic
    process; it is a fixed obstacle being hit the same way every time."""
    from merchantcore.descriptor import is_never_templatable
    from merchantcore.induce import HOLDOUT_SHARE, holdout_split

    inst, _, kind = target.partition("/")
    counts = pairs.get((inst, kind))
    if not counts:
        print(f"No movements for {target!r}. Pairs: "
              + ", ".join(f"{i}/{k}" for i, k in sorted(pairs)))
        return 1

    eligible = {d: n for d, n in counts.items() if not is_never_templatable(d)}
    train, held = holdout_split(eligible)
    tm, hm = sum(train.values()), sum(held.values())

    print(f"\n{target}")
    print(f"{'-' * 72}")
    print(f"  eligible      {len(eligible)} distinct line(s), "
          f"{tm + hm} movement(s)")
    print(f"  training      {len(train):>4} line(s)  {tm:>5} movement(s)")
    print(f"  HELD OUT      {len(held):>4} line(s)  {hm:>5} movement(s)"
          f"   ({len(held) / max(1, len(eligible)):.0%} of lines, "
          f"{hm / max(1, tm + hm):.0%} of money)")
    if abs(len(held) / max(1, len(eligible)) - HOLDOUT_SHARE) > 0.02:
        print("  (the line share drifts from the target because the split is by "
              "hash,\n   which is what makes it stable across runs)")

    print(f"\n  WEIGHT CONCENTRATION IN THE HELD-OUT SET")
    ranked = sorted(held.items(), key=lambda kv: -kv[1])
    running = 0
    for i, (_d, n) in enumerate(ranked[:8], 1):
        running += n
        print(f"    #{i}  {n:>4} movement(s)   {n / max(1, hm):>5.1%} of the "
              f"holdout   running {running / max(1, hm):.0%}")
    if ranked:
        top = ranked[0][1] / max(1, hm)
        print(f"\n  The single heaviest withheld line is {top:.0%} of the number "
              f"being scored.")
        if top >= 0.10:
            print("  That is the finding. A grammar that misses it alone cannot "
                  "clear a\n  gate set at 80%, however well it explains the other "
                  f"{len(held) - 1} lines - and\n  whether it is withheld at all "
                  "was decided by a hash of its own text.")
        print(f"\n  Scored by LINE instead of by movement, missing that one line "
              f"would\n  cost {1 / max(1, len(held)):.1%} rather than {top:.0%}.")
    if private:
        print(f"\n{'=' * 72}\nPRIVATE - the withheld lines by weight. Yours alone."
              f"\n{'=' * 72}")
        for d, n in ranked[:15]:
            print(f"    {n:>4}   {d}")
    else:
        print("\n  (the lines themselves are under --private)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description="What the patterns we already have explain. No model calls.")
    ap.add_argument("--private", action="store_true",
                    help="also print the masked shapes sitting in the pile")
    ap.add_argument("--no-borrow", action="store_true",
                    help="measure own grammars only, for the before/after")
    ap.add_argument("--pile-threshold", type=int, default=30,
                    help="distinct lines at which the pile is worth inducing from")
    ap.add_argument("--gate", metavar="INSTITUTION/KIND", default="",
                    help="why a pair keeps missing the coverage gate. Free: the "
                         "holdout split is deterministic and needs no model.")
    args = ap.parse_args()

    from .env import load_dotenv
    load_dotenv()
    from merchantcore.induce import skeletons
    from merchantcore.profile import is_inducible
    from merchantcore.resolve import resolve_descriptor
    from .induce_profile import _pairs, profile_store
    from .vault import Vault

    passphrase = os.environ.get("VIVA_PASSPHRASE")
    if not passphrase:
        print("Set VIVA_PASSPHRASE - it opens the vault and is never stored.")
        return 1
    vault_dir = os.environ.get("VIVA_VAULT_DIR", os.path.expanduser("~/.viva-vault"))
    if not pathlib.Path(vault_dir).exists():
        print(f"No vault at {vault_dir}.")
        return 1

    proj = Vault.open(vault_dir, passphrase).ledger.projection()
    pairs, _recent = _pairs(proj)

    if args.gate:
        return _gate(pairs, args.gate, args.private)
    store = profile_store()
    every = [store.load(pid) for pid in store.ids()]
    every = [p for p in every if p is not None]

    print(f"\nvault      {len(proj.movements())} movement(s), {len(pairs)} "
          f"(institution x kind) pair(s)")
    print(f"grammars   {len(every)} known: "
          + (", ".join(p.id for p in sorted(every, key=lambda x: x.id)) or "none"))
    print(f"borrowing  {'OFF (--no-borrow)' if args.no_borrow else 'ON'}")

    pile_lines: dict[str, int] = {}
    pile_where: dict[str, str] = {}
    grand = collections.Counter()

    for (inst, kind), counts in sorted(pairs.items()):
        own = store.latest_for(inst, kind)
        others = [] if args.no_borrow else [
            p for p in every if not (p.institution == inst and p.kind == kind)]
        buckets = collections.Counter()
        moves = collections.Counter()
        lenders = collections.Counter()

        for desc, n in counts.items():
            res = resolve_descriptor(desc, profile=own, borrowed=others)
            if res.refused:
                b = "wire"
            elif not is_inducible(kind):
                # An investment activity line names no counterparty — a trade is
                # against a security, not a party — so no grammar may ever be
                # induced for one. Counting it as "nothing explained it" makes
                # the pile permanently look ready to induce from while a third
                # of it is ineligible, which is the same mistake wires would
                # have made. Its own bucket; instrumentcore's job.
                b = "instrument"
            elif res.layer == "grammar" and res.borrowed_from:
                b = "borrowed"
                lenders[res.borrowed_from] += n
            elif res.layer == "grammar":
                b = "own"
            elif res.layer == "published" and res.fields:
                b = "published"
            else:
                b = "pile"
                pile_lines[desc] = n
                pile_where[desc] = f"{inst}/{kind}"
            buckets[b] += 1
            moves[b] += n
            grand[b] += n

        total_l, total_m = len(counts), sum(counts.values())
        print(f"\n{'-' * 72}\n{inst}/{kind}   {total_l} distinct line(s), "
              f"{total_m} movement(s)")
        print(f"{'-' * 72}")
        print(f"  own grammar   {buckets['own']:>4} line(s)  "
              f"{moves['own']:>5} movement(s)  {_pct(moves['own'], total_m)}"
              + (f"   [{own.id}]" if own else "   [none induced]"))
        print(f"  borrowed      {buckets['borrowed']:>4} line(s)  "
              f"{moves['borrowed']:>5} movement(s)  {_pct(moves['borrowed'], total_m)}"
              + (f"   from {', '.join(f'{k} ({v})' for k, v in lenders.most_common())}"
                 if lenders else ""))
        note = ("   recognised; the counterparty is a question, not a gap"
                if buckets["wire"] else "")
        print(f"  wire          {buckets['wire']:>4} line(s)  "
              f"{moves['wire']:>5} movement(s)  {_pct(moves['wire'], total_m)}{note}")
        if buckets["instrument"]:
            print(f"  instrument    {buckets['instrument']:>4} line(s)  "
                  f"{moves['instrument']:>5} movement(s)  "
                  f"{_pct(moves['instrument'], total_m)}"
                  "   a trade has no counterparty; no grammar can be induced")
        print(f"  published     {buckets['published']:>4} line(s)  "
              f"{moves['published']:>5} movement(s)  {_pct(moves['published'], total_m)}"
              "   structure proved, no template claimed the line")
        print(f"  PILE          {buckets['pile']:>4} line(s)  "
              f"{moves['pile']:>5} movement(s)  {_pct(moves['pile'], total_m)}")

    total_m = sum(grand.values())
    print(f"\n{'=' * 72}\nTHE WHOLE VAULT\n{'=' * 72}")
    for b, label in (("own", "own grammar"), ("borrowed", "borrowed grammar"),
                     ("wire", "wire (recognised)"),
                     ("instrument", "instrument (not inducible)"),
                     ("published", "published rules only"),
                     ("pile", "PILE - nothing explained it")):
        print(f"  {label:<28} {grand[b]:>5} movement(s)   {_pct(grand[b], total_m)}")
    explained = grand["own"] + grand["borrowed"]
    print(f"\n  {_pct(explained, total_m)} of movements are explained by a template "
          f"that names its slots.")
    if grand["borrowed"]:
        print(f"  {_pct(grand['borrowed'], total_m)} of that came from a grammar "
              f"induced for a DIFFERENT bank -\n  which is the whole question this "
              f"report exists to answer, and it is a yes.")
    else:
        print("  No line was explained by another bank's grammar. Borrowing buys "
              "nothing\n  on this vault as it stands - which is worth knowing "
              "before paying to\n  find out.")

    print(f"\n{'-' * 72}\nTHE PILE\n{'-' * 72}")
    shapes = skeletons(pile_lines) if pile_lines else {}
    print(f"  {len(pile_lines)} distinct line(s) explained by nothing, "
          f"{sum(pile_lines.values())} movement(s)")
    print(f"  {len(shapes)} distinct shape(s) after masking the variable parts")
    if pile_lines:
        by_lines = max(shapes.items(), key=lambda kv: len(kv[1]))
        by_moves = max(shapes.items(),
                       key=lambda kv: sum(pile_lines[d] for d in kv[1]))
        print(f"  widest shape covers {len(by_lines[1])} distinct line(s)")
        print(f"  heaviest shape carries "
              f"{sum(pile_lines[d] for d in by_moves[1])} movement(s) on "
              f"{len(by_moves[1])} line(s)")
        print("  - the second is the one that matters: a single line the bank "
              "prints\n    hundreds of times is worth more than twenty it prints "
              "once.")
    ready = len(pile_lines) >= args.pile_threshold
    print(f"\n  {'READY' if ready else 'not yet'} to induce from - "
          f"{len(pile_lines)} of {args.pile_threshold} distinct line(s) needed.")
    if ready:
        print("  Induction over this pile sees only lines nothing explains, which is\n"
              "  the population where forty examples are worth forty examples.")

    per_pair = collections.Counter(pile_where.values())
    if per_pair:
        print("\n  where the pile came from:")
        for pair, n in per_pair.most_common():
            print(f"    {n:>4}  {pair}")

    if args.private and pile_lines:
        print(f"\n{'=' * 72}\nPRIVATE - the pile's shapes. For your eyes only."
              f"\n{'=' * 72}")
        print("  A masked spine keeps every word printed more than once, and that\n"
              "  includes a name. Counts above are safe; these are not.\n")
        for spine, group in sorted(shapes.items(),
                                   key=lambda kv: -sum(pile_lines[d] for d in kv[1])):
            n = sum(pile_lines[d] for d in group)
            print(f"    {len(group):>3} line(s), {n:>4} movement(s)   {spine}")
    elif pile_lines:
        print("\n  (the shapes themselves are under --private)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
