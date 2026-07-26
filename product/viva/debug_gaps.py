"""Why is this statement still held? — the gap diagnosis.

    VIVA_VAULT_DIR=<vault> python -m viva.debug_gaps

A statement posts when it **connects to its account's chain**, and there are
exactly two places it can connect:

    forward   its opening  == the account's CURRENT balance   (extend the head)
    backward  its closing  == the account's EARLIEST opening   (extend the tail)

Everything else is a gap. That rule is deliberate and correct — a statement whose
opening matches nothing might belong to a period we have never seen, and posting
it would invent a balance history that no document attests.

**But the chain can only grow at its two ends.** A statement that belongs in the
MIDDLE of a run has nothing to attach to until both its neighbours are present,
and `heal_gaps` retries until nothing more connects — so in principle the
cascade fills the middle in eventually.

On a real vault it did not: 14 statements held, and a full `sweep` healed zero.
This prints, for every held statement, exactly what it wanted and what the chain
was offering — so the difference is a number you can read rather than a theory.
"""

from __future__ import annotations

import os
import pathlib
from decimal import Decimal


def diagnose(proj) -> list[dict]:
    """For each gap-held statement: what it needs, and what the chain has."""
    from .ingest.pipeline import _resolve
    from .ingest.registry import BALANCE_IDENTITY, identity_of_facts
    from .ingest.statement import StatementFacts

    rows = []
    for body in proj.gap_holds():
        if identity_of_facts(body.get("facts")) != BALANCE_IDENTITY:
            continue
        facts = StatementFacts.from_dict(body["facts"])
        account = _resolve(proj, facts).account_id
        try:
            running = proj.running_balance(account)
            earliest = proj.earliest_opening(account)
        except Exception:                       # noqa: BLE001 - unknown account
            running = earliest = None
        rows.append({
            "doc": (facts.doc_id or body.get("doc_id", ""))[:10],
            "account": account,
            "period": f"{facts.opening_date} – {facts.closing_date}",
            "opens": facts.opening_amount, "closes": facts.closing_amount,
            "head": running, "tail": earliest,
            "forward_gap": (facts.opening_amount - running
                            if running is not None else None),
            "backward_gap": (facts.closing_amount - earliest
                             if earliest is not None else None),
        })
    return sorted(rows, key=lambda r: (r["account"], r["period"]))


def report(proj) -> str:
    rows = diagnose(proj)
    if not rows:
        return "No gap-held statements. Every chain connects."

    out = [f"{len(rows)} statement(s) held as gaps.", ""]
    by_account: dict[str, list] = {}
    for r in rows:
        by_account.setdefault(r["account"], []).append(r)

    for account, group in by_account.items():
        head = group[0]["head"]
        tail = group[0]["tail"]
        out.append(f"{account}")
        out.append(f"  chain currently spans: opening {tail}  →  balance {head}")
        for r in group:
            out.append(f"    {r['doc']}  {r['period']}")
            out.append(f"      opens {r['opens']:>14}   vs head {r['head']}"
                       f"   (off by {r['forward_gap']})")
            out.append(f"      closes {r['closes']:>13}   vs tail {r['tail']}"
                       f"   (off by {r['backward_gap']})")
        out.append("")

    # The diagnosis the numbers imply, stated rather than left to inference.
    exact = [r for r in rows
             if r["forward_gap"] == 0 or r["backward_gap"] == 0]
    if exact:
        out += [f"  {len(exact)} of these connect EXACTLY (off by 0) and are still "
                "held.",
                "  That is a bug in the heal, not missing data — the statement "
                "attaches",
                "  and nothing re-posted it."]
    else:
        out += ["  None of these connect exactly, so each is genuinely waiting for",
                "  a statement the vault does not have. A gap is the CORRECT answer",
                "  here — the honest fix is coverage, not code. The nearest misses",
                "  above tell you which months to go and find."]
    return "\n".join(out)


def main() -> None:
    from .env import load_dotenv
    from .vault import Vault

    load_dotenv()
    passphrase = os.environ.get("VIVA_PASSPHRASE")
    if not passphrase:
        raise SystemExit("Set VIVA_PASSPHRASE (or put it in .env).")
    vault_dir = os.environ.get("VIVA_VAULT_DIR", os.path.expanduser("~/.viva-vault"))
    if not pathlib.Path(vault_dir).exists():
        raise SystemExit(f"No vault at {vault_dir}.")
    vault = Vault.open(vault_dir, passphrase)
    print(f"vault: {vault_dir}\n")
    print(report(vault.ledger.projection()))


if __name__ == "__main__":
    main()
