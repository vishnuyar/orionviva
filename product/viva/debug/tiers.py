"""Print how a vault's movements distribute across the four tiers.

    python -m viva.debug.tiers            # VIVA_PASSPHRASE / VIVA_VAULT_DIR

Every movement lands in one of four states, and only two of them are asked about:

  settled     an ordinary counterparty implying nothing   → silence
  structural  the counterparty implies a relationship     → an informed proposal
  unknown     an instrument or a peer                     → a real question
  unenriched  the counterparty is not identified yet      → enrich first

For each tier it prints the count, share, money and number of counterparties,
then the number of questions the queue would raise and that figure per hundred
movements. Where anything is unenriched it says so, since that understates
`settled` and overstates the queue.

Pure projection — reads the vault, writes nothing, needs no model. The
passphrase may be given as the first argument instead of in the environment.
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
    from ..questions import INTERVIEW, open_questions

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
    # `as_of` is the newest date the ledger attests, never the wall clock, so
    # the report is a pure function of the events.
    dates = [b.dated for i in proj.account_infos()
             for b in [proj.balance(i.account)] if b.dated]
    asked = open_questions(proj, limit=10_000,
                           as_of=max(dates) if dates else "1970-01-01")
    # This report is about MOVEMENTS, so its ratio counts the questions that
    # are about movements. An interview asks about an ACCOUNT — it does not
    # belong in a per-hundred-movements figure, and folding it in would make
    # enrichment look worse every time a new account arrived.
    about_accounts = sum(1 for q in asked["questions"] if q["kind"] == INTERVIEW)
    about_movements = asked["total"] - about_accounts
    per_hundred = about_movements / total * 100
    lines += [
        "",
        f"  questions the queue would ask: {about_movements}"
        f"   ({per_hundred:.1f} per 100 movements)",
    ]
    if about_accounts:
        lines.append(f"  and about the accounts themselves: {about_accounts}")
    settled = summary.get("settled", {}).get("count", 0)
    if settled:
        lines.append(f"  handled without asking:        {settled}"
                     f"   ({settled / total:.0%} of everything)")
    # An unenriched vault understates `settled` and overstates the queue, so the
    # report says so rather than presenting the picture as complete.
    if summary.get("unenriched"):
        lines += ["", "  NOTE: some counterparties are not enriched yet, so this "
                  "understates",
                  "        `settled` and overstates the queue. Run `python -m "
                  "viva.enrich` first."]
    return "\n".join(lines)


def main() -> None:
    from ..env import load_dotenv
    from ..vault import Vault

    # Load `.env` before reading the environment, as every CLI here does, so a
    # variable set only in the file is never reported as missing.
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
