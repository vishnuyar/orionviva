"""Did Viva learn to say it first? — the answer key, scored.

    VIVA_VAULT_DIR=<rebuilt> python -m viva.diff_rulings <rulings-export.json>

Every ruling in the export is something a person had to **say by hand** under the
old design. So the honest test of the counterparty-implication work is not a tier
percentage — it is:

> **Does the product now PROPOSE what you previously had to TELL it?**

Four outcomes per ruling, and the middle two are the interesting ones:

  ANTICIPATED   the rebuilt vault reaches the same conclusion unprompted.
                Exactly what the work was for.
  PROPOSED      it raises the counterparty as a question or proposal, but does
                not yet reach your conclusion. Half credit: it noticed.
  MISSED        silence. It still needs to be told. Not a bug — a gap, and the
                list of them is the honest to-do.
  CONTRADICTED  it reaches a DIFFERENT conclusion than you gave. **The only
                dangerous outcome**, and the one to read first: a product that
                confidently disagrees with its user is worse than one that asks.

This is a comparison, not a restore. Nothing is written to either vault.
"""

from __future__ import annotations

import json
import os
import pathlib
import sys
from collections import Counter

ANTICIPATED, PROPOSED, MISSED, CONTRADICTED = (
    "anticipated", "proposed", "missed", "CONTRADICTED")


def _subject_of(ruling: dict) -> str:
    """The counterparty a ruling is about, however it was recorded."""
    b = ruling.get("body") or {}
    for field in ("subject", "merchant", "descriptor"):
        if b.get(field):
            return str(b[field]).strip().lower()
    return ""


def _conclusion_of(ruling: dict) -> str:
    """What the person concluded, reduced to something comparable."""
    b = ruling.get("body") or {}
    legs = b.get("legs") or []
    if legs:
        return "+".join(sorted({leg.get("major", "") for leg in legs}))
    if b.get("nature"):
        return f"nature:{b['nature']}"
    if b.get("category"):
        return f"category:{b['category']}"
    return ""


def score(proj, rulings: list[dict]) -> list[dict]:
    """Grade each human ruling against what the rebuilt vault says on its own."""
    from .ledger.merchants import normalize_merchant
    from .ledger.projection import _NATURE_OF_MAJOR
    from .questions import open_questions

    asked = {}
    for q in open_questions(proj, limit=10_000)["questions"]:
        key = (q.get("refs") or {}).get("merchant") or ""
        if key:
            asked[key] = q

    rows = []
    for ruling in rulings:
        subject = _subject_of(ruling)
        if not subject:
            continue
        key = normalize_merchant(subject) or subject
        mine = _conclusion_of(ruling)

        implied = proj.implication_for(key)
        verdict, saw = MISSED, ""
        if implied:
            saw = implied.get("relationship") or implied["major"]
            got = implied["major"]
            if mine.startswith("nature:"):
                # An old three-nature answer compares through the majors map.
                same = _NATURE_OF_MAJOR.get(got) == mine.split(":", 1)[1]
            else:
                same = got in mine.split("+")
            verdict = ANTICIPATED if same else CONTRADICTED
        elif key in asked:
            verdict, saw = PROPOSED, asked[key]["text"][:70]
        rows.append({"verdict": verdict, "subject": subject, "yours": mine,
                     "viva": saw, "type": ruling["event_type"]})
    return rows


def report(rows: list[dict]) -> str:
    counts = Counter(r["verdict"] for r in rows)
    n = len(rows) or 1
    out = [f"{len(rows)} thing(s) you told the old vault, re-judged by the new one:",
           ""]
    for verdict in (ANTICIPATED, PROPOSED, MISSED, CONTRADICTED):
        c = counts.get(verdict, 0)
        out.append(f"  {verdict:14} {c:4}  {c / n:5.0%}")
    out.append("")
    if counts.get(CONTRADICTED):
        out += ["  READ THESE FIRST — Viva disagrees with you:"]
        for r in rows:
            if r["verdict"] == CONTRADICTED:
                out.append(f"    {r['subject'][:38]:38} you: {r['yours']:22} "
                           f"viva: {r['viva']}")
        out.append("")
    if counts.get(ANTICIPATED):
        out += ["  it now says these without being asked:"]
        for r in rows:
            if r["verdict"] == ANTICIPATED:
                out.append(f"    {r['subject'][:38]:38} {r['viva']}")
        out.append("")
    if counts.get(MISSED):
        out += ["  still needs to be told:"]
        for r in rows[:40]:
            if r["verdict"] == MISSED:
                out.append(f"    {r['subject'][:38]:38} you: {r['yours']}")
    out += ["", "  " + _verdict(counts, n)]
    return "\n".join(out)


def _verdict(counts: Counter, n: int) -> str:
    if counts.get(CONTRADICTED):
        return (f"VERDICT: {counts[CONTRADICTED]} contradiction(s). Fix those before "
                "reading anything else — confidently disagreeing with the person "
                "is the one failure mode worse than asking.")
    learned = counts.get(ANTICIPATED, 0)
    if learned / n > 0.5:
        return (f"VERDICT: it anticipates {learned / n:.0%} of what you used to have "
                "to say. The implication work is doing its job.")
    if learned + counts.get(PROPOSED, 0) == 0:
        return ("VERDICT: it anticipates nothing. Either enrichment has not run on "
                "this vault, or the implications are coming back empty — check "
                "`debug_tiers` for a structural tier before concluding anything.")
    return (f"VERDICT: partial — {learned}/{n} anticipated. Worth looking at what "
            "the misses have in common; that is the next batch of world knowledge.")


def main() -> None:
    from .env import load_dotenv
    from .vault import Vault

    load_dotenv()
    if len(sys.argv) < 2:
        raise SystemExit("Usage: python -m viva.diff_rulings <rulings-export.json>")
    passphrase = os.environ.get("VIVA_PASSPHRASE")
    if not passphrase:
        raise SystemExit("Set VIVA_PASSPHRASE (or put it in .env).")
    vault_dir = os.environ.get("VIVA_VAULT_DIR", os.path.expanduser("~/.viva-vault"))

    data = json.loads(pathlib.Path(sys.argv[1]).read_text())
    vault = Vault.open(vault_dir, passphrase)
    print(f"vault:  {vault_dir}")
    print(f"key:    {sys.argv[1]}  (from {data.get('source', '?')})\n")
    print(report(score(vault.ledger.projection(), data.get("rulings", []))))


if __name__ == "__main__":
    main()
