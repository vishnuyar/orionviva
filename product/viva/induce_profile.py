"""Induce one bank's descriptor grammar, from your own statements, one call.

    PYTHONPATH=../core:../merchant:. python3 -m viva.induce_profile --list
    PYTHONPATH=../core:../merchant:. python3 -m viva.induce_profile \
        --institution "…" --kind depository

A grammar is per (institution × kind): a checking line and a card line from one
bank are unrelated languages, and the peer-payment templates are a third. `--list`
shows which pairs this vault contains and how many movements sit behind each.

**This is the hand tool; `python3 -m viva.agent` is the one that runs itself.**
That sentence used to end "…so the largest is induced first and read by a person
before the rest are automated", which described bootstrapping and read like a
rule — and contradicted the rule that actually holds. A person reads a grammar
before PUBLISHING it, because a wrong one in the commons is wrong for everybody
and no automated check catches the failure that matters. A grammar used on one
vault needs no such gate: it is wrong for one person, reversibly, and the drift
check surfaces it. Requiring a reading before use would make the agent a chore
with a wrapper around it.

**What crosses the boundary here, and why it is allowed.** This is the one call
that sees a descriptor whole, including a counterparty's name — because the name
is exactly what teaches the model where the `counterparty` slot is, and because
ingest already sent this model every page of the statement that line came from.
Withholding the line now would protect nothing and would cost the slot. Every
*later* call — merchant enrichment — sees only the slots the vocabulary declares
impersonal, and never the descriptor.

**The templates are printed, and they are not automatically safe to paste.**
They are meant to be the bank's grammar — literal text plus named holes,
identical for every customer of that bank. But the literal text comes from the
model, so a template that ignored the rules could carry a person's name baked
into it, and that is exactly the thing you have to see in order to reject. A
deterministic check flags every template matching one distinct line or none —
rule 4's "an example, not a grammar", and the shape a baked-in name takes, since
it can only ever match its own line. Read what it flags before the grammar goes
anywhere. Counts, coverage and shape totals are safe. `--private` adds the
sample, the unexplained lines and the masked shapes — that output is for the
person who owns the vault and nobody else.

**One grammar per (institution × kind) — but not one model call per person.**
A profile carries slots and literals and no values, so it is the bank's
composition rather than yours, and `--verify` measures somebody else's grammar
against your own lines with no model call at all. The first customer of an
institution pays; everyone after them checks the number and reuses it. That
check is what a merchant catalog cannot offer. A pair with no grammar still
works — Layer 0 and the normalizer resolve it, worse but honestly worse — so
induction is an improvement, never a step that blocks an account.

**Induction is stochastic, and the pack rules did not know it.** The same prompt
over the same forty lines returned 27 templates at 84% one run and 33 at 82% the
next. Because the gate is absolute and `latest` wins by version number, the
weaker grammar silently became the one in use. Two guards now: `--best-of N`
induces N times and keeps the best (ties to the smaller grammar, which has
generalised rather than enumerated), and a version that covers less than the one
it succeeds is refused unless `--force` says the lower number is wanted.
"""

from __future__ import annotations

import argparse
import collections
import os
import pathlib
import sys

from .env import load_dotenv
from .logs import configure as configure_logging


def profiles_dir() -> pathlib.Path:
    """Where grammars this installation induced are kept.

    Not in the vault and not under the product's home: a bank's line grammar is
    the bank's, identical for every customer, and it outlives any ledger. It
    lives in merchantcore's learned directory — outside the working tree, so it
    cannot be committed by accident — with the package's shipped seed read
    behind it. `MERCHANTCORE_HOME` (or the older `VIVA_PROFILES`) overrides."""
    from merchantcore import home
    explicit = os.environ.get("VIVA_PROFILES")
    return pathlib.Path(explicit).expanduser() if explicit else home.profiles_dir()


def profile_store():
    """The store both entry points use: learned first, shipped behind it."""
    from merchantcore import home
    from merchantcore.profile import ProfileStore
    return ProfileStore(profiles_dir(), shipped=home.shipped_profiles_dir())


def _pairs(proj, recent_days: int = 120) -> tuple[dict, dict]:
    """(institution, kind) -> {descriptor: movement count}, all-time and recent.

    The recent slice is what a drift check needs. Lifetime coverage falls slowly
    because old lines outnumber new ones; a bank that changed its composition
    changed it only for what it printed since, so the recent number moves first
    and by a lot."""
    out: dict = collections.defaultdict(collections.Counter)
    recent: dict = collections.defaultdict(collections.Counter)
    dates = sorted(str(m.date)[:10] for m in proj.movements() if m.date)
    cutoff = ""
    if dates:
        from datetime import date as _d, timedelta
        try:
            cutoff = str(_d.fromisoformat(dates[-1]) - timedelta(days=recent_days))
        except ValueError:
            cutoff = ""
    for m in proj.movements():
        desc = (m.description or "").strip()
        if not desc:
            continue
        try:
            info = proj.account_info(m.account)
        except Exception:                                   # noqa: BLE001
            continue
        key = (info.institution or "?", info.kind or "?")
        out[key][desc] += 1
        if cutoff and str(m.date)[:10] >= cutoff:
            recent[key][desc] += 1
    return out, recent


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true",
                    help="show the (institution x kind) pairs in this vault and stop")
    ap.add_argument("--institution", help="which institution's grammar to induce")
    ap.add_argument("--kind", help="depository, liability, investment, …")
    ap.add_argument("--sample", type=int, default=40,
                    help="how many descriptors to show the model (default 40)")
    ap.add_argument("--min-coverage", type=float, default=0.80,
                    help="held-out coverage a grammar must reach to be written")
    ap.add_argument("--rounds", type=int, default=3,
                    help="how many times to send back what the grammar missed")
    ap.add_argument("--dry-run", action="store_true",
                    help="choose the sample and stop — no model call, no cost")
    ap.add_argument("--show-prompt", action="store_true",
                    help="print the exact prompt (contains your descriptors)")
    ap.add_argument("--no-write", action="store_true",
                    help="report the grammar but do not store it")
    ap.add_argument("--best-of", type=int, default=1, metavar="N",
                    help="induce N times and keep the best — induction is "
                         "stochastic, and the same prompt returns different "
                         "grammars run to run")
    ap.add_argument("--verify", metavar="PROFILE_ID",
                    help="measure an existing grammar against this vault's lines "
                         "— no model call. How a shared grammar is trusted.")
    ap.add_argument("--force", action="store_true",
                    help="write even if it covers less than the version it "
                         "succeeds, or if there are too few lines to induce from")
    ap.add_argument("--private", action="store_true",
                    help="also print descriptors — for your eyes only")
    args = ap.parse_args()

    load_dotenv()
    configure_logging()
    from merchantcore.descriptor import is_never_templatable
    from merchantcore.induce import (HOLDOUT_SHARE, MIN_LINES_TO_INDUCE, Inducer,
                                     build_induction_prompt, drift,
                                     holdout_split, narrow_templates,
                                     sample_descriptors, skeletons)
    from merchantcore.profile import (INDUCIBLE_KINDS, PERSONAL_SLOTS,
                                      ProfileStore, is_inducible)
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
    pairs, recent = _pairs(proj)
    if not pairs:
        print("This vault holds no movements with descriptors.")
        return 1

    ranked = sorted(pairs.items(), key=lambda kv: -sum(kv[1].values()))
    store = profile_store()
    if args.list or not (args.institution and args.kind):
        print(f"vault     {vault_dir}")
        print(f"profiles  {store.directory}\n")
        print("  movements  distinct  grammar        institution / kind")
        for (inst, kind), counts in ranked:
            have = store.latest_for(inst, kind)
            mark = "" if is_inducible(kind) else "   [no grammar: names no party]"
            print(f"  {sum(counts.values()):9d}  {len(counts):8d}  "
                  f"{(have.id if have else '—'):14s} {inst} / {kind}{mark}")
        skipped = [k for (_i, k) in pairs if not is_inducible(k)]
        if skipped:
            print(f"\n  A grammar finds a counterparty inside a sentence a bank "
                  f"composed.\n  {', '.join(sorted(set(skipped)))} descriptors "
                  f"describe a trade against a security, not a\n  payment to "
                  f"anybody, so there is no party for a slot to hold. Those lines "
                  f"need\n  their own vocabulary (instrumentcore) rather than a "
                  f"mis-slotted version\n  of this one.")
        live = [(k, store.latest_for(*k)) for k in pairs]
        live = [(k, pr) for k, pr in live if pr]
        if live:
            print(f"\n{'-' * 72}\nIS EACH GRAMMAR STILL WORKING?\n{'-' * 72}")
            print("  A coverage number measured once, on the day a grammar was")
            print("  written, says nothing about today. Lifetime coverage falls")
            print("  slowly because old lines outnumber new ones; RECENT coverage")
            print("  falls immediately, because a bank that changed its composition")
            print("  changed it for everything printed since. Watch the recent one.\n")
            print("     measured    lifetime      recent   grammar")
            for k, pr in live:
                d = drift(pr, pairs[k], recent.get(k))
                rec = (f"{d['recent']:9.1%}" if "recent" in d else "        —")
                flag = ""
                if "recent" in d and pr.measured and d["recent_drop"] > 0.15:
                    flag = "   ← induce the next version"
                print(f"    {pr.measured:8.1%}    {d['now']:8.1%}   {rec}   {pr.id}{flag}")
        print("\nInduce one at a time, largest first, and read the templates it "
              "returns:\n  --institution '<name>' --kind <kind>")
        return 0

    if args.verify:
        # No model call. This is how a grammar induced by somebody else — or by
        # you, months ago — is trusted: apply it to your own lines and read the
        # number. A profile carries no values, so there is nothing to trust
        # about its provenance; only its behaviour on your statement matters.
        try:
            candidate = store.load(args.verify)
        except Exception as e:                              # noqa: BLE001
            print(f"{e}")
            return 1
        print(f"\nverifying   {candidate.id}   ({len(candidate.templates)} template(s))")
        print("            no model call — this is a local measurement\n")
        print("   movements   coverage   institution / kind")
        for (inst, kind), counts in ranked:
            if not is_inducible(kind):
                continue
            share = candidate.weighted_coverage(counts)
            mark = "  ← works here" if share >= args.min_coverage else ""
            print(f"   {sum(counts.values()):9d}   {share:8.1%}   {inst} / {kind}{mark}")
        print("\n  A grammar is slots and literals with no values in it, so a")
        print("  stranger's grammar is safe to try: it either explains your lines")
        print("  or it does not, and the number says which. That is the check a")
        print("  merchant catalog cannot offer.")
        return 0

    key = (args.institution, args.kind)
    if key not in pairs:
        print(f"No movements from {args.institution!r} / {args.kind!r}. "
              f"Run --list to see the pairs this vault has.")
        return 1
    if not is_inducible(args.kind):
        print(f"\n{args.kind!r} descriptors name no counterparty, so a grammar over "
              f"them would\nmis-slot rather than parse — a security forced into "
              f"{{brand}} and a realized\ngain into {{purpose}}, confidently, on "
              f"every line that institution prints.\n\nInducible kinds: "
              f"{sorted(INDUCIBLE_KINDS)}. Instrument events are instrumentcore's "
              f"job.")
        return 1
    counts = pairs[key]

    existing = store.latest_for(*key)
    if existing:
        # A released grammar is never edited, so an existing one is not an
        # obstacle to inducing the next version — but it IS the thing to measure
        # the next version against, and quietly inducing over it would lose that.
        # The same measurement the induction reports — weighted by movements.
        # These were two different numbers under one word, 88% here and 84%
        # there for one grammar, and a metric with two meanings is a metric
        # nobody can act on.
        share = existing.weighted_coverage(counts)
        print(f"note: {existing.id} already exists and explains {share:.1%} of "
              f"these movements. A new induction becomes "
              f"{store.next_version(*key)}, and is refused if it covers less "
              f"(--force overrides).")

    refused = [d for d in counts if is_never_templatable(d)]
    eligible = {d: n for d, n in counts.items() if d not in set(refused)}
    print(f"\ninstitution  {args.institution}")
    print(f"kind         {args.kind}")
    print(f"movements    {sum(counts.values())}")
    print(f"distinct     {len(counts)} descriptor(s)")
    if refused:
        print(f"refused      {len(refused)} wire line(s) — never templatable, kept "
              f"local and whole,")
        print("             and excluded from the coverage denominator rather than "
              "counted\n             against it (they are not a grammar failure)")

    trainable = {d: n for d, n in eligible.items()}
    if len(trainable) < MIN_LINES_TO_INDUCE and not args.force:
        print(f"\nOnly {len(trainable)} distinct line(s) — below the "
              f"{MIN_LINES_TO_INDUCE} needed to induce from.\n")
        print("A grammar fitted to a handful of lines has memorised them: the")
        print("sample IS the population, so its coverage means nothing and a 20%")
        print("holdout is three or four lines of noise.")
        print("\nNothing is lost by waiting. This pair already resolves through")
        print("Layer 0 and the normalizer — worse, but honestly worse. Come back")
        print("when the bank has printed enough to be characteristic, or pass")
        print("--force if you want the grammar anyway and will read every template.")
        return 1
    train_only, held_only = holdout_split(trainable)
    print(f"holdout      {len(held_only)} of {len(trainable)} distinct line(s) "
          f"withheld ({HOLDOUT_SHARE:.0%})")
    print("             never sampled, never used to pick between candidate")
    print("             grammars — so their number estimates rather than flatters")

    shapes = skeletons(train_only)
    sample = sample_descriptors(train_only, args.sample)
    print(f"shapes       {len(shapes)} candidate template(s) after masking")
    print(f"sample       {len(sample)} line(s), at most 5 per shape, chosen to be")
    print("             as UNLIKE each other as possible — a model learns where a")
    print("             hole is by seeing one template with different fillers")

    if args.show_prompt or args.dry_run:
        prompt, version = build_induction_prompt(sample)
        print(f"prompt       {version}, {len(prompt)} chars")
        if args.show_prompt:
            print("\n" + "=" * 72 + "\nPROMPT — contains your descriptors\n"
                  + "=" * 72 + f"\n{prompt}\n" + "=" * 72)
        if args.dry_run:
            print("\nDry run: no model call was made, nothing was written.")
            return 0

    if not os.environ.get("VIVA_MODEL"):
        print("\nNo model configured. Set VIVA_MODEL_ADAPTER / VIVA_MODEL / "
              "VIVA_MODEL_KEY_ENV (and the key), or put them in ./.env.")
        return 1

    from merchantcore.enrich import model_extractor
    from vivacore.models import ModelSpec
    spec = ModelSpec(
        name="grammar-inducer", adapter=os.environ["VIVA_MODEL_ADAPTER"],
        model=os.environ["VIVA_MODEL"],
        base_url=os.environ.get("VIVA_MODEL_BASE_URL"),
        api_key_env=os.environ.get("VIVA_MODEL_KEY_ENV", "OPENROUTER_API_KEY"),
        json_mode=True)

    inducer = Inducer(model_extractor(spec), sample_size=args.sample,
                      min_coverage=args.min_coverage, rounds=args.rounds)
    attempts = []
    for attempt in range(1, max(1, args.best_of) + 1):
        if args.best_of > 1:
            print(f"\n  attempt {attempt} of {args.best_of} …")
        attempts.append(inducer.induce(*key, counts))
    # Best by the HELD-OUT score, ties to the SMALLER grammar: two grammars
    # explaining the same lines are not equal, and the one with fewer templates
    # has generalised rather than enumerated.
    #
    # Held-out and not training coverage, which is what this selected on until
    # 2026-07-29. Choosing the best of N on the number the model was fitted to
    # picks the luckiest overfit — and a fifth of the lines were withheld
    # precisely so that a grammar could be judged on lines it had never seen.
    # Selecting on the other number gave that back.
    result = max(attempts, key=lambda r: (r.scored,
                                          -len(r.profile.templates) if r.profile else 0))
    if len(attempts) > 1:
        spread = [f"{r.scored:.1%}" for r in attempts]
        print(f"\n  attempts: {', '.join(spread)} — kept the best. Induction is "
              f"stochastic;\n  one run of this vault gave 84% and the next 82% "
              f"from the same forty lines.")
    if result.profile is None:
        print(f"\nNothing usable came back — {result.verdict}. Nothing written.")
        return 1

    profile = result.profile
    profile.version = store.next_version(*key)
    print(f"\n{'-' * 72}\nTHE GRAMMAR  ({len(profile.templates)} template(s), "
          f"{result.version})\n{'-' * 72}")
    print("  Read these. They are the bank's own composition, they are impersonal,")
    print("  and a wrong one is wrong on every line this bank will ever print.\n")
    for t in profile.templates:
        personal = [n for n, _ in t.slots() if n in PERSONAL_SLOTS]
        mark = f"   ← personal: {', '.join(personal)}" if personal else ""
        print(f"    {t.pattern}{mark}")

    narrow = narrow_templates(profile, eligible)
    if narrow:
        print(f"\n  ⚠ {len(narrow)} template(s) match one distinct line or none. "
              f"Rule 4 calls that\n    an example rather than a grammar — and a "
              f"name baked into literal text\n    lands here too, because it can "
              f"only ever match its own line. Read these:\n")
        for pattern, hits in sorted(narrow.items(), key=lambda kv: kv[1]):
            print(f"    {pattern}\n        matches {hits} distinct line(s)")

    print(f"\n{'-' * 72}\nHELD-OUT COVERAGE\n{'-' * 72}")
    print(f"  Measured on all {sum(eligible.values())} eligible movements, not "
          f"the {len(sample)} the model saw.\n")
    if result.holdout is not None:
        print(f"    {result.holdout:.1%} of WITHHELD movements explained "
              f"(gate: {args.min_coverage:.0%})   ← the honest number")
        print(f"    {result.coverage:.1%} of the lines it was induced on")
        gap = result.coverage - result.holdout
        if gap > 0.10:
            print(f"    a {gap:.0%} gap between them means this grammar fits the "
                  f"lines it saw\n    better than the bank — the tail is where it "
                  f"will fail")
    else:
        print(f"    {result.coverage:.1%} of movements explained "
              f"(gate: {args.min_coverage:.0%})   ← UNVALIDATED, no holdout")
    print(f"    {len(result.unmatched)} of {len(eligible)} distinct line(s) unexplained")
    print(f"    {result.rounds} round(s) — each shown only what the last one missed")
    if result.refused:
        print(f"    {len(result.refused)} wire line(s) excluded before any of this")

    if result.unmatched:
        left = skeletons(result.unmatched)
        big = max((len(g) for g in left.values()), default=0)
        # The shapes themselves are NOT printed here. A masked spine keeps every
        # token that occurs in more than one line, and a person paid twice is a
        # person whose name occurs in more than one line. The counts are safe;
        # the spines are yours, under --private.
        print(f"\n    {len(left)} distinct shape(s) left, largest covering "
              f"{big} line(s)")
        print("    (the shapes themselves are under --private — a masked spine "
              "keeps\n     any word printed twice, and that includes a name)")

    if not result.accepted:
        print(f"\nREFUSED — {result.verdict}. Nothing written.")
        print("  A grammar below the gate is not a grammar with gaps; it is a "
              "grammar\n  that learned the sample. Re-run with a larger --sample, "
              "or read the\n  unexplained heads above and check they are one kind "
              "of line, not many.")
        return 1

    if args.no_write:
        print(f"\nAccepted ({result.verdict}) — not written (--no-write).")
    else:
        profile.measured = result.coverage
        path = store.write(profile, against=counts, force=args.force)
        print(f"\nAccepted ({result.verdict}) — written as {profile.id}")
        print(f"  {path}")
        print("  This version is now frozen. Changing the grammar means inducing "
              f"{store.next_version(*key)}.")

    if args.private:
        print(f"\n{'-' * 72}\nPRIVATE — your descriptors. For your eyes only.\n"
              f"{'-' * 72}")
        print("  the sample the model was shown:")
        for d in sample:
            print(f"      {d}")
        if result.unmatched:
            print("\n  lines the grammar could not explain:")
            for d in result.unmatched[:40]:
                print(f"      {counts[d]:4d}x  {d}")
        if result.refused:
            print("\n  refused a grammar outright (wire dumps, kept local and whole):")
            for d in result.refused[:10]:
                print(f"      {d}")
    else:
        print("\n(Descriptors are omitted. `--private` adds them, for you.)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
