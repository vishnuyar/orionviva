"""Measure the shape of a vault's counterparty descriptors.

Two questions decide how merchant knowledge should be stored and what may be
shared, and both are answerable from a vault with no model calls:

  1. How many distinct descriptors resolve to one merchant? If the answer is
     near one, caching decompositions buys nothing. If it is large, the
     subtraction step is doing real work and a merchant-keyed commons is much
     smaller than a descriptor-keyed one.

  2. How much of a descriptor is left over once the merchant is removed, and how
     often is that remainder a person rather than a store number? That decides
     how narrow the personal path is.

Run it against your own vault:

    VIVA_VAULT_DIR=~/.viva-vault python -m viva.debug_descriptors

The default report is **safe to share**: counts, distributions and head tokens
that are shared by three or more distinct counterparties. A token that heads
three unrelated descriptors is not a person's name, which is the same property
the design leans on for publication.

`--private` adds amounts and the descriptors themselves. That output is for the
person who owns the vault and nobody else; nothing in it should be pasted
anywhere.
"""

from __future__ import annotations

import argparse
import collections
import os
import pathlib
import sys
from decimal import Decimal

from .env import load_dotenv
from merchantcore.descriptor import brand_candidate, parse_descriptor
from merchantcore.normalize import _DATE_FRAGMENT
from .ledger.merchants import is_shareable, normalize_merchant
from .vault import Vault

SAFE_FANOUT = 3          # a head shared by this many distinct tails may be printed


def _bar(title: str) -> None:
    print(f"\n{'-' * 72}\n{title}\n{'-' * 72}")


def _hist(counts: list[int], edges=(1, 2, 3, 5, 10, 25, 100)) -> str:
    buckets: dict[str, int] = collections.OrderedDict()
    for i, e in enumerate(edges):
        lo = edges[i - 1] + 1 if i else 1
        buckets[f"{lo}" if lo == e else f"{lo}-{e}"] = 0
    buckets[f"{edges[-1]}+"] = 0
    for c in counts:
        for i, e in enumerate(edges):
            lo = edges[i - 1] + 1 if i else 1
            if c <= e:
                buckets[f"{lo}" if lo == e else f"{lo}-{e}"] += 1
                break
        else:
            buckets[f"{edges[-1]}+"] += 1
    width = max(buckets.values()) or 1
    return "\n".join(f"    {k:>7s}  {'#' * int(28 * v / width):28s} {v}"
                     for k, v in buckets.items() if v)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--private", action="store_true",
                    help="also print amounts and descriptors — for your eyes only")
    args = ap.parse_args()

    load_dotenv()
    passphrase = os.environ.get("VIVA_PASSPHRASE")
    if not passphrase:
        print("Set VIVA_PASSPHRASE — it opens the vault and is never stored.")
        return 1
    vault_dir = os.environ.get("VIVA_VAULT_DIR", os.path.expanduser("~/.viva-vault"))
    if not pathlib.Path(vault_dir).exists():
        print(f"No vault at {vault_dir}.")
        return 1

    proj = Vault.open(vault_dir, passphrase).ledger.projection()
    movements = proj.movements()
    if not movements:
        print("This vault holds no movements, so there is nothing to measure.")
        return 1

    # normalized descriptor -> movement count, and head token -> distinct tails
    per_key: collections.Counter = collections.Counter()
    money: dict[str, Decimal] = collections.defaultdict(lambda: Decimal("0"))
    heads: dict[str, set] = collections.defaultdict(set)
    head_moves: collections.Counter = collections.Counter()
    raw_forms: dict[str, set] = collections.defaultdict(set)

    for m in movements:
        key = normalize_merchant(m.description)
        if not key:
            continue
        per_key[key] += 1
        money[key] += abs(m.amount)
        raw_forms[key].add(m.description)
        head = key.split(" ", 1)[0]
        heads[head].add(key)
        head_moves[head] += 1

    total_moves = sum(per_key.values())
    print(f"vault      {vault_dir}")
    print(f"movements  {len(movements)} ({total_moves} with a usable descriptor)")

    _bar("HOW MANY RAW DESCRIPTORS RESOLVE TO ONE NORMALIZED KEY")
    print("  If this is near 1, normalization is already collapsing the variants")
    print("  and a per-descriptor cache buys nothing.\n")
    print(_hist([len(v) for v in raw_forms.values()]))
    print(f"\n    distinct raw descriptors  {sum(len(v) for v in raw_forms.values())}")
    print(f"    distinct normalized keys  {len(per_key)}")

    _bar("HOW MANY NORMALIZED KEYS SHARE A HEAD TOKEN")
    print("  A head shared by many distinct tails is a conduit: the tail varies")
    print("  because the tail is a counterparty. A head that leads only itself is")
    print("  an ordinary merchant that repeats whole.\n")
    print(_hist([len(v) for v in heads.values()]))
    print(f"\n    distinct head tokens      {len(heads)}")
    print(f"    keys                      {len(per_key)}")
    collapse = len(per_key) - len(heads)
    print(f"    keys that would collapse  {collapse} "
          f"({collapse * 100 // max(len(per_key), 1)}% smaller if keyed by head)")

    _bar(f"HEADS SHARED BY {SAFE_FANOUT}+ DISTINCT COUNTERPARTIES  (safe to share)")
    print("  These are the conduit candidates. A token heading this many unrelated")
    print("  descriptors is not a person's name — which is the same property the")
    print("  publication rule relies on, applied here to what may be printed.\n")
    fanning = sorted(((len(v), h) for h, v in heads.items() if len(v) >= SAFE_FANOUT),
                     reverse=True)
    if not fanning:
        print("    none — every descriptor in this vault heads only itself")
    for n, h in fanning[:40]:
        print(f"    {n:4d} distinct tails   {h}")
    covered = sum(head_moves[h] for _n, h in fanning)
    print(f"\n    movements under a fanning head  {covered} "
          f"({covered * 100 // max(total_moves, 1)}% of all movements)")

    _bar("WHAT THE CURRENT PRIVACY GATE DECIDES")
    blocked = [k for k in per_key if not is_shareable(k)]
    blocked_moves = sum(per_key[k] for k in blocked)
    print(f"    keys refused by is_shareable   {len(blocked)} of {len(per_key)}")
    print(f"    movements behind them          {blocked_moves} "
          f"({blocked_moves * 100 // max(total_moves, 1)}%)")
    blocked_fanning = [k for k in blocked if len(heads[k.split(' ', 1)[0]]) >= SAFE_FANOUT]
    print(f"    ...of which head a fanning family {len(blocked_fanning)} "
          f"(a conduit, so only the tail is personal)")
    print(f"    ...and head only themselves       {len(blocked) - len(blocked_fanning)} "
          f"(refused whole, though nothing varies after them)")

    _bar("WHERE THE DESCRIPTORS COME FROM  (institution x kind)")
    print("  A grammar is per (institution, rail, document type) — a checking line")
    print("  and a card line from one bank are unrelated languages. This counts how")
    print("  many profiles would even be needed.\n")
    pairs: collections.Counter = collections.Counter()
    for m in movements:
        try:
            info = proj.account_info(m.account)
        except Exception:                              # noqa: BLE001
            continue
        pairs[(info.institution or "?", info.kind or "?")] += 1
    for (inst, kind), n in pairs.most_common():
        print(f"    {n:5d} movements   {inst:24s} {kind}")
    print(f"\n    distinct (institution, kind) pairs  {len(pairs)}")

    _bar("THE DATE FRAGMENT  (what the normalizer fix removes)")
    dated = [d for forms in raw_forms.values() for d in forms if _DATE_FRAGMENT.search(d)]
    print(f"    raw descriptors carrying a posting date  {len(dated)}")
    print("    Each one used to head a key of its own, so a merchant seen in two")
    print("    months became two merchants. Keys above are already computed under")
    print("    the fixed rule; re-running enrichment re-derives the catalog.")

    _bar("LAYER 0 COVERAGE  (published card rules, no model, no profile)")
    print("  How much of each descriptor a deterministic parse can account for.")
    print("  This number decides whether induced per-bank grammars are the")
    print("  centrepiece or a long-tail tool.\n")
    parses = {k: parse_descriptor(next(iter(raw_forms[k]))) for k in per_key}
    buckets = collections.Counter()
    for pr in parses.values():
        pct = int(pr.coverage * 100)
        buckets["nothing (0%)" if pct == 0 else
                "1-25%" if pct <= 25 else "26-50%" if pct <= 50 else
                "51-75%" if pct <= 75 else "76-100%"] += 1
    order = ["nothing (0%)", "1-25%", "26-50%", "51-75%", "76-100%"]
    width = max(buckets.values()) or 1
    for b in order:
        v = buckets.get(b, 0)
        print(f"    {b:>13s}  {'#' * int(28 * v / width):28s} {v}")
    clean = sum(1 for pr in parses.values() if pr.clean)
    cnp = sum(1 for pr in parses.values() if pr.card_not_present)
    moved = sum(per_key[k] for k, pr in parses.items() if pr.coverage > 0)
    print(f"\n    leftovers contiguous (parse is coherent)  {clean} of {len(parses)}")
    print(f"    identified as card-not-present            {cnp}")
    print(f"    movements the parse says something about  {moved} "
          f"({moved * 100 // max(total_moves, 1)}%)")
    changed = sum(1 for k, pr in parses.items() if brand_candidate(pr) and
                  normalize_merchant(brand_candidate(pr)) != k)
    print(f"    keys whose brand candidate differs        {changed} "
          f"(what Layer 0 would hand to identification)")

    _bar("ENRICHMENT REACH")
    enriched = proj.merchant_categories()
    known = [k for k in per_key if k in enriched]
    print(f"    keys with an enriched record   {len(known)} of {len(per_key)}")
    print(f"    movements they cover           "
          f"{sum(per_key[k] for k in known) * 100 // max(total_moves, 1)}%")

    if args.private:
        _bar("PRIVATE — amounts and descriptors. For your eyes only.")
        print("  Do not paste this section anywhere.\n")
        for n, h in fanning[:15]:
            tails = sorted(heads[h])
            print(f"  {h}  ({n} tails, {head_moves[h]} movements, "
                  f"{sum(money[t] for t in tails):,.2f})")
            for t in tails[:8]:
                print(f"      {per_key[t]:4d}x  {money[t]:>12,.2f}  {t}")
        print("\n  refused whole by the gate, no fanning family:")
        for k in sorted(set(blocked) - set(blocked_fanning))[:25]:
            print(f"      {per_key[k]:4d}x  {money[k]:>12,.2f}  {k}")
    else:
        print("\n(Amounts and descriptors are omitted. `--private` adds them, for you.)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
