"""What recurs in your money — measured, with no model and no inference.

    VIVA_VAULT_DIR=~/.viva-vault python3 -m viva.streams_report
    ... --words          # word recurrence across counterparties, a diagnostic
    ... --private        # amounts and descriptors, for you alone

A **stream** is every movement sharing a counterparty and a rail. This report says
how often each one arrives, how much, how steady, and through which channel. It
contains no hypotheses: nothing here guesses that a stream is a subscription or a
rent payment. Everything it prints can be checked against a statement by hand,
which is the point — the inferential layer that comes next has to be measured
against this, so this has to be trustworthy first.

**Nothing below guesses at what belongs to the bank and what belongs to a
merchant.** A rule that did was removed on 2026-07-28 after this report's own
`--words` section falsified it: on a real vault the bank's sentence words, city
names and merchant names interleave by frequency, so no cut separates them, and
a cut low enough to catch the ACH markers deletes merchant names. Separating the
bank's sentence from the merchant's name is Layer 1's job — an induced grammar
does it from evidence with a lossless check, and until one exists a card stream
carries the bank's prefix in its key. Inelegant, and honest: an unstripped key
is still unique per counterparty, while an over-stripped one is silently merged
with everything the bank prefixed the same way.

The default report is **safe to share**: counts, cadences, channels and rule
statistics. `--private` adds amounts, descriptors and counterparty names — that
output is for the person who owns the vault and nobody else.
"""

from __future__ import annotations

import argparse
import collections
import os
import pathlib
import sys

from .env import load_dotenv


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--words", "--calibrate", action="store_true", dest="words",
                    help="word recurrence across counterparties — a diagnostic")
    ap.add_argument("--min-n", type=int, default=2,
                    help="only show streams with at least this many movements")
    ap.add_argument("--private", action="store_true",
                    help="also print amounts, descriptors and names — for your eyes only")
    args = ap.parse_args()

    load_dotenv()
    from merchantcore.descriptor import word_owners
    from .induce_profile import profile_store
    from .ledger.streams import (ACTIVITY, COUNTERPARTY, INTERNAL, MIXED,
                                 MIN_FOR_CADENCE, build_streams)
    from .vault import Vault

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
        print("This vault holds no movements.")
        return 1

    # An induced grammar for a movement's (institution x kind), when one exists.
    # None everywhere is the ordinary case today and stays a working one.
    store = profile_store()
    cache: dict = {}

    def profile_for(m):
        try:
            info = proj.account_info(m.account)
        except Exception:                                   # noqa: BLE001
            return None
        pair = (info.institution or "?", info.kind or "?")
        if pair not in cache:
            cache[pair] = store.latest_for(*pair)
        return cache[pair]

    kinds: dict = {}

    def kind_for(m):
        if m.account not in kinds:
            try:
                kinds[m.account] = proj.account_info(m.account).kind or ""
            except Exception:                               # noqa: BLE001
                kinds[m.account] = ""
        return kinds[m.account]

    every = build_streams(movements, profile_for, kind_for)
    # `mixed` counts as a counterparty stream: it IS one, with some of its
    # movements linked. Excluding it would hide a real party behind a gap in
    # the transfer matcher.
    streams = [s for s in every if s.role in (COUNTERPARTY, MIXED)]
    grammars = sum(1 for v in cache.values() if v)
    span = sorted(m.date for m in movements if m.date)

    print(f"vault      {vault_dir}")
    print(f"movements  {len(movements)}")
    if span:
        print(f"span       {str(span[0])[:10]} .. {str(span[-1])[:10]}")
    print(f"streams    {len(every)} total")
    print(f"grammars   {grammars} of {len(cache)} (institution x kind) pair(s) have one")
    if not grammars:
        print("           — every stream below was keyed by published rules and the")
        print("             normalizer alone. Inducing grammars is what sharpens them.")

    print(f"\n{'-' * 78}\nWHOSE MONEY IS THIS  (a stream's role, from what the ledger "
          f"already decided)\n{'-' * 78}")
    print("  Not every movement has a counterparty. Paying your own card is a live")
    print("  transfer link; a brokerage's own activity line names no party at all —")
    print("  a capital-gain phrase was minting a stream key of its own. Marked, not")
    print("  dropped: the totals still contain them.\n")
    for role in (COUNTERPARTY, MIXED, INTERNAL, ACTIVITY):
        rs = [s for s in every if s.role == role]
        if rs:
            print(f"    {len(rs):5d} stream(s)  {sum(s.n for s in rs):6d} movement(s)   {role}")
    mixed = [s for s in every if s.role == MIXED]
    if mixed:
        print("\n  A `mixed` stream is ONE counterparty whose movements are only")
        print("  partly transfer-linked — a gap in the matcher, not a second party:")
        for s in sorted(mixed, key=lambda s: -s.n)[:8]:
            name = f"  {s.counterparty}" if args.private else ""
            print(f"    {s.n:5d} movement(s)  {s.linked_share:5.0%} linked{name}")
    print("\n  Everything below counts counterparty and mixed streams.")

    print(f"\n{'-' * 78}\nBY LAYER — which layer named each stream's counterparty\n{'-' * 78}")
    for layer, n in collections.Counter(s.layer for s in streams).most_common():
        moves = sum(s.n for s in streams if s.layer == layer)
        print(f"    {n:5d} stream(s)  {moves:6d} movement(s)   {layer}")

    print(f"\n{'-' * 78}\nBY CHANNEL — the rail, which constrains what a stream can be\n{'-' * 78}")
    for ch, n in collections.Counter(s.channel for s in streams).most_common():
        moves = sum(s.n for s in streams if s.channel == ch)
        print(f"    {n:5d} stream(s)  {moves:6d} movement(s)   {ch}")

    print(f"\n{'-' * 78}\nWHAT RECURS\n{'-' * 78}")
    print(f"  A cadence needs at least {MIN_FOR_CADENCE} observations. Below that the")
    print("  answer is `unknown` rather than a guess — one interval is not a rhythm.\n")
    cad = collections.Counter(s.cadence_class for s in streams)
    for label in ("weekly", "biweekly", "monthly", "quarterly", "annual",
                  "irregular", "unknown"):
        if cad.get(label):
            moves = sum(s.n for s in streams if s.cadence_class == label)
            print(f"    {cad[label]:5d} stream(s)  {moves:6d} movement(s)   {label}")
    recurring = [s for s in streams if s.recurring]
    cp_moves = sum(s.n for s in streams)
    print(f"\n    {len(recurring)} recurring stream(s), covering "
          f"{sum(s.n for s in recurring)} of {cp_moves} counterparty movement(s)")
    for label in ("fixed", "variable", "unknown"):
        n = sum(1 for s in recurring if s.amount_stability == label)
        if n:
            print(f"      {n:5d} of them are {label} in amount")

    print(f"\n{'-' * 78}\nRECURRING STREAMS  (names withheld unless --private)\n{'-' * 78}")
    print("       n  channel  cadence    amount     day  layer")
    for s in sorted(recurring, key=lambda s: (-s.n, s.counterparty))[:40]:
        name = f"  {s.counterparty}" if args.private else ""
        print(f"    {s.n:4d}  {s.channel:7s}  {s.cadence_class:9s}  "
              f"{s.amount_stability:9s} {str(s.day_of_month_mode or '-'):>3s}  "
              f"{s.layer:10s}{name}")

    people = [s for s in streams if s.is_person]
    refused = [s for s in streams if s.refused]
    print(f"\n{'-' * 78}\nTHE BOUNDARY\n{'-' * 78}")
    print(f"    {len(people)} stream(s) whose counterparty a grammar named as a PERSON")
    print("      (these never reach merchantcore, the commons, or a model prompt)")
    print(f"    {len(refused)} stream(s) refused every layer — wire dumps, kept whole")
    if not people and not grammars:
        print("      no person was named because no grammar exists yet; until one does,")
        print("      peer money is keyed by descriptor and treated like any other")

    if args.words:
        print(f"\n{'-' * 78}\nWORD RECURRENCE — a diagnostic, deciding nothing\n{'-' * 78}")
        print("  How many distinct normalized keys print each word. This ranking")
        print("  once drove a rule that stripped 'the bank's words' out of brand")
        print("  candidates. The rule was REMOVED on 2026-07-28 because this very")
        print("  report falsified it: three populations — the bank's sentence")
        print("  words, city names, and merchants — interleave here, so no cut")
        print("  separates them. Read it now as a picture of the vault, and as the")
        print("  clearest available argument for inducing a grammar: the bank's")
        print("  sentence is exactly what a template captures.\n")
        owners = word_owners(m.description for m in movements)
        for word, own in sorted(owners.items(), key=lambda kv: -len(kv[1]))[:35]:
            print(f"    {len(own):5d}  {word}")

    if args.private:
        print(f"\n{'-' * 78}\nPRIVATE — names and amounts. For your eyes only.\n{'-' * 78}")
        for s in sorted(every, key=lambda s: -float(s.total))[:30]:
            print(f"\n  {s.counterparty}   [{s.role}, {s.channel}, {s.layer}, "
                  f"n={s.n}, {s.cadence_class}, {s.amount_stability}]")
            print(f"    total {s.total:,.2f}   median {s.amount_median:,.2f}   "
                  f"{s.first_seen} .. {s.last_seen}")
            for o in s.occurrences[:4]:
                print(f"      {o.date}  {o.amount:>12,.2f}  {o.description[:56]}")
    else:
        print("\n(Names, amounts and descriptors are omitted. `--private` adds them.)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
