"""What are you worth, and on what evidence? — the net-worth curve (Slice 7).

    VIVA_VAULT_DIR=<vault> python -m viva.debug_networth            # latest point
    VIVA_VAULT_DIR=<vault> python -m viva.debug_networth 2026-03-31 # any date
    VIVA_VAULT_DIR=<vault> python -m viva.debug_networth --series   # the curve

Net worth here is a **function of date**, not a number with a date attached, so
there is no single figure to be wrong about — only `net_worth(D)`, built from
every account's last-known measurement at or before D.

What this prints that a bank app will not:

  * every line's **own** as-of date, which is usually earlier than the point it
    belongs to. That gap is the truth about your coverage.
  * the **provable** subtotal — the part backed by a document whose arithmetic
    checks. The rest counts (we trust you) and is marked.
  * what is **missing**, and the document that would settle it. A total that
    silently omits a mortgage is a lie of omission; this one says so.

Pure projection: reads the vault, writes nothing, needs no model.
"""

from __future__ import annotations

import os
import pathlib
import sys


def _money(amount) -> str:
    return f"{amount:>14,.2f}"


def report_point(point) -> str:
    if not point.lines and not point.missing:
        return ("Nothing to value yet — no dated measurement in this vault.\n"
                "  That is the honest answer, not zero.")
    out = [f"NET WORTH as of {point.as_of}"
           + ("" if point.complete else "     ⚠ INCOMPLETE"), ""]

    for currency, row in sorted(point.by_currency().items()):
        out.append(f"  {currency}")
        out.append(f"    assets       {_money(row['assets'])}")
        out.append(f"    liabilities  {_money(row['liabilities'])}")
        out.append(f"    ── net       {_money(row['net'])}")
        out.append(f"       of which provable {_money(row['provable'])}"
                   "   (a document attests it and the arithmetic checks)")
        out.append("")

    out.append("  what it stands on")
    for line in sorted(point.lines, key=lambda l: (l.currency, l.account)):
        stale = "" if line.as_of == point.as_of else "   ← measured earlier"
        mark = "✓" if line.provable else "·"
        out.append(f"    {mark} {line.account[:34]:34} {_money(line.amount)} "
                   f"{line.currency}  as of {line.as_of}{stale}")
    if point.oldest_input and point.oldest_input != point.as_of:
        out += ["", f"  oldest input: {point.oldest_input} — this total is only "
                    "as current as that."]

    if point.missing:
        out += ["", "  NOT COUNTED — and your true net worth is LOWER because "
                    "of it:"]
        for m in point.missing:
            out.append(f"    {m['account']}")
            out.append(f"      {m['why']}")
            out.append(f"      I would ask: \"{m['ask']}\"")
            out.append(f"      settled by: {m['would_fix']}")
    return "\n".join(out)


def report_series(points) -> str:
    if not points:
        return "No dated measurements — the curve has no points yet."
    out = [f"THE CURVE — {len(points)} point(s), "
           f"{points[0].as_of} → {points[-1].as_of}", ""]
    currencies = sorted({c for p in points for c in p.by_currency()})
    for currency in currencies:
        out.append(f"  {currency}")
        for p in points:
            row = p.by_currency().get(currency)
            if row is None:
                continue
            flag = "" if p.complete else "  ⚠ incomplete"
            out.append(f"    {p.as_of}  {_money(row['net'])}"
                       f"   (provable {_money(row['provable'])}){flag}")
        out.append("")
    out.append("  An earlier point never moves when a later document arrives —")
    out.append("  which is what makes comparing two of them mean anything.")
    return "\n".join(out)


def main() -> None:
    from .env import load_dotenv
    from .ledger.networth import net_worth, series
    from .vault import Vault

    load_dotenv()
    passphrase = os.environ.get("VIVA_PASSPHRASE")
    if not passphrase:
        raise SystemExit("Set VIVA_PASSPHRASE (or put it in .env).")
    vault_dir = os.environ.get("VIVA_VAULT_DIR", os.path.expanduser("~/.viva-vault"))
    if not pathlib.Path(vault_dir).exists():
        raise SystemExit(f"No vault at {vault_dir}.")

    args = [a for a in sys.argv[1:] if a != "--series"]
    proj = Vault.open(vault_dir, passphrase).ledger.projection()
    print(f"vault: {vault_dir}\n")
    if "--series" in sys.argv:
        print(report_series(series(proj)))
    else:
        print(report_point(net_worth(proj, args[0] if args else None)))


if __name__ == "__main__":
    main()
