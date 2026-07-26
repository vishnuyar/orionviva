"""How much of your money does Viva already understand? — the tier measurement.

    python -m viva.debug_tiers            # VIVA_PASSPHRASE / VIVA_VAULT_DIR

This is the number that decides whether the three-tier design was worth doing,
and the honest *before* to compare against (docs/where-the-intelligence-goes.md).

The rule the whole queue rests on: **ask only where the counterparty cannot tell
us.** Every movement lands in one of four states, and only two of them deserve a
person's attention at all:

  settled     an ordinary counterparty implying nothing   → silence
  structural  the counterparty implies a relationship     → an informed proposal
  unknown     an instrument or a peer                     → a real question
  unenriched  we have not identified the counterparty yet → enrich first

A high `settled` share is the point, not a disappointment: it is the fraction of
a person's financial life the product handles without troubling them. The
questions-per-hundred-movements line is the one to watch over time.

Pure projection — reads the vault, writes nothing, needs no model.
"""

from __future__ import annotations

import os
import pathlib
import sys
from decimal import Decimal

TIER_ORDER = ("settled", "structural", "unknown", "unenriched")
TIER_MEANS = {
    "settled": "known, implies nothing  → SILENCE",
    "structural": "implies a relationship  → propose",
    "unknown": "a peer or instrument → ask, one at a time",
    "unenriched": "a business we have not identified yet → enrich",
}


def _money(amount: Decimal) -> str:
    return f"{amount:,.2f}"


def report(proj) -> str:
    """The tier picture, plus the queue length it implies."""
    from .questions import open_questions

    summary = proj.tier_summary()
    total = sum(r["count"] for r in summary.values()) or 1
    money = sum(r["amount"] for r in summary.values())

    lines = [f"movements: {total}   ·   {_money(money)} in total", ""]
    for tier in TIER_ORDER:
        row = summary.get(tier)
        if not row:
            continue
        share = row["count"] / total
        bar = "█" * int(round(share * 30))
        lines.append(f"  {tier:11} {row['count']:5}  {share:5.1%} {bar}")
        lines.append(f"  {'':11} {_money(row['amount']):>13}  across "
                     f"{row['merchants']} counterpart(y|ies)   {TIER_MEANS[tier]}")
    asked = open_questions(proj, limit=10_000)
    per_hundred = asked["total"] / total * 100
    lines += [
        "",
        f"  questions the queue would ask: {asked['total']}"
        f"   ({per_hundred:.1f} per 100 movements)",
    ]
    settled = summary.get("settled", {}).get("count", 0)
    if settled:
        lines.append(f"  handled without asking:        {settled}"
                     f"   ({settled / total:.0%} of everything)")
    # Say plainly what is NOT yet knowable, rather than implying the picture is
    # complete. An unenriched vault will look artificially question-heavy.
    if summary.get("unenriched"):
        lines += ["", "  NOTE: some counterparties are not enriched yet, so this "
                  "understates",
                  "        `settled` and overstates the queue. Run `python -m "
                  "viva.enrich` first."]
    return "\n".join(lines)


def main() -> None:
    from .env import load_dotenv
    from .vault import Vault

    # Every other CLI in this package loads `.env` first; this one didn't, and
    # told the author to set a variable he had already set. A tool that says
    # "you forgot" when you didn't is worse than one that just fails.
    load_dotenv()
    passphrase = os.environ.get("VIVA_PASSPHRASE") or (
        sys.argv[1] if len(sys.argv) > 1 else None)
    if not passphrase:
        raise SystemExit("Set VIVA_PASSPHRASE (or pass it as the first argument).")
    vault_dir = os.environ.get("VIVA_VAULT_DIR", os.path.expanduser("~/.viva-vault"))
    if not pathlib.Path(vault_dir).exists():
        raise SystemExit(f"No vault at {vault_dir}.")
    vault = Vault.open(vault_dir, passphrase)
    print(f"vault: {vault_dir}\n")
    print(report(vault.ledger.projection()))


if __name__ == "__main__":
    main()
