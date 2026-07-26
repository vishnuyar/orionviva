"""Did Viva learn to say it first? — the answer key, scored.

    VIVA_VAULT_DIR=<rebuilt> python -m viva.diff_rulings <rulings-export.json>

Every ruling in the export is something a person had to **say by hand** under the
old design. So the honest test of the counterparty-implication work is not a tier
percentage — it is:

> **Does the product now PROPOSE what you previously had to TELL it?**

Six outcomes per ruling. Only four of them are a grade — the other two exist
because the first real run graded things that were never comparable:

  ANTICIPATED   the rebuilt vault reaches the same conclusion unprompted.
                Exactly what the work was for.
  PROPOSED      it raises the counterparty as a question or proposal, but does
                not yet reach your conclusion. Half credit: it noticed.
  MISSED        silence. It still needs to be told. Not a bug — a gap, and the
                list of them is the honest to-do.
  CONTRADICTED  it reaches a DIFFERENT conclusion than you gave. **The only
                dangerous outcome**, and the one to read first: a product that
                confidently disagrees with its user is worse than one that asks.

  incomparable  you gave a spending CATEGORY, it offers a RELATIONSHIP.
  unknowable    a peer or an instrument. Silence is correct, not a miss.

Both are excluded from the score, because a denominator that includes things no
implementation could ever get right measures the design, not the build.

**Known limitation, stated rather than fixed (2026-07-26).** A counterparty that
is now `settled` — an ordinary business the queue will never ask about — still
scores as `missed`, because this only inspects IMPLICATIONS. A ruling the new
design makes UNNECESSARY is arguably the best outcome there is, and it is being
counted as a failure. It is left visible instead of patched because three
successive corrections to this scorer have each moved the number in the author's
favour, and a fourth needs a colder eye than the one that wrote the first three.

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
# Two verdicts added after the first real run cried wolf (2026-07-26).
#
# INCOMPARABLE — the person gave a spending CATEGORY ("transport", "transfers",
# "down payment") and the vault offers a structural RELATIONSHIP ("auto loan",
# "brokerage account", "property purchase"). Those are different axes, not
# disagreements: a Northwind payment is transport spending AND an auto loan; a
# brokerage MoneyLine is a transfer AND implies a brokerage account. Scoring them
# as CONTRADICTED produced three alarming false accusations out of three.
#
# UNKNOWABLE — the subject is a peer or an instrument. A cheque or an ATM
# withdrawal tells us nothing about itself, BY CONSTRUCTION, so counting it as
# "missed" measures the design rather than the implementation. 12 of 15 "misses"
# on the real run were ATM withdrawals.
INCOMPARABLE, UNKNOWABLE = "incomparable", "unknowable"


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
    from .ledger.merchants import is_shareable, normalize_merchant
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
            if mine.startswith("category:"):
                # Different axes. A spending label and a structural relationship
                # can both be true of the same payment, so there is nothing here
                # to agree or disagree with.
                verdict = INCOMPARABLE
            elif mine.startswith("nature:"):
                # An old three-nature answer compares through the majors map.
                verdict = (ANTICIPATED
                           if _NATURE_OF_MAJOR.get(got) == mine.split(":", 1)[1]
                           else CONTRADICTED)
            else:
                verdict = ANTICIPATED if got in mine.split("+") else CONTRADICTED
        elif key in asked:
            verdict, saw = PROPOSED, asked[key]["text"][:70]
        elif proj.kind_of_merchant(key) in ("instrument", "peer") or (
                not is_shareable(subject)):
            # A peer or an instrument: nothing will ever imply anything about
            # it, so silence is correct rather than a miss.
            #
            # The LEARNED kind is asked first and `is_shareable` is only the
            # fallback, because `is_shareable` is a substring list — it catches
            # "zelle" and " to " but not "ATM WITHDRAWAL 03 15 MAIN ST". The
            # kind comes back from enrichment, which reads the descriptor like a
            # person would. Judging the tool by the weaker of the two tests is
            # how 12 cash withdrawals got scored as misses.
            verdict, saw = UNKNOWABLE, "a peer or instrument — never inferable"
        rows.append({"verdict": verdict, "subject": subject, "yours": mine,
                     "viva": saw, "type": ruling["event_type"]})
    return rows


def report(rows: list[dict]) -> str:
    counts = Counter(r["verdict"] for r in rows)
    n = len(rows) or 1
    out = [f"{len(rows)} thing(s) you told the old vault, re-judged by the new one:",
           ""]
    for verdict in (ANTICIPATED, PROPOSED, INCOMPARABLE, UNKNOWABLE,
                    MISSED, CONTRADICTED):
        c = counts.get(verdict, 0)
        note = {INCOMPARABLE: "  a category vs a relationship — different axes",
                UNKNOWABLE: "  a peer or instrument — correctly silent"}.get(verdict, "")
        out.append(f"  {verdict:14} {c:4}  {c / n:5.0%}{note}")
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
    # Score only what COULD have been anticipated. Peers, instruments and
    # cross-axis answers are not failures of the implication work.
    learned = counts.get(ANTICIPATED, 0)
    scorable = n - counts.get(UNKNOWABLE, 0) - counts.get(INCOMPARABLE, 0) or 1
    if learned / scorable > 0.5:
        return (f"VERDICT: it anticipates {learned / scorable:.0%} of what it "
                "could have. The implication work is doing its job.")
    if learned + counts.get(PROPOSED, 0) == 0:
        return ("VERDICT: it anticipates nothing. Either enrichment has not run on "
                "this vault, or the implications are coming back empty — check "
                "`debug_tiers` for a structural tier before concluding anything.")
    return (f"VERDICT: partial — {learned}/{scorable} of the anticipatable. Worth "
            "looking at what the misses have in common; that is the next batch "
            "of world knowledge to teach enrichment.")


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
