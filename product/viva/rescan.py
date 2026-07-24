"""Rescan an existing vault — link internal transfers and corroborate held
statements across everything already ingested, without a new upload.

Transfer detection and cross-document corroboration normally run during ingest.
Statements ingested *before* that machinery existed (or before a counterpart
arrived) are eligible but were never re-scanned. This runs the full sweep once
over the current vault: stitch gaps, close conflict-holds a counterparty now
attests, and detect transfers among all posted movements. It appends only links
and heals (append-only, T4) — nothing is overwritten, and it is idempotent.

Usage (from product/, auto-loads ./.env for VIVA_PASSPHRASE / VIVA_VAULT_DIR):

    PYTHONPATH=../core:. python3 -m viva.rescan
"""

from __future__ import annotations

import os
import pathlib
import sys

from .env import load_dotenv
from .logs import configure as configure_logging


def main() -> None:
    load_dotenv()
    configure_logging()
    from .ingest import sweep
    from .vault import Vault

    passphrase = os.environ.get("VIVA_PASSPHRASE") or (
        sys.argv[1] if len(sys.argv) > 1 else None)
    if not passphrase:
        raise SystemExit("Set VIVA_PASSPHRASE (or pass it as the first argument).")
    vault_dir = os.environ.get("VIVA_VAULT_DIR", os.path.expanduser("~/.viva-vault"))
    if not pathlib.Path(vault_dir).exists():
        raise SystemExit("No vault at that path yet — nothing to rescan.")

    print(f"vault: {vault_dir}")
    vault = Vault.open(vault_dir, passphrase)
    before = len(vault.ledger.projection().transfer_links())
    result = sweep(vault.ledger)
    proj = vault.ledger.projection()

    print("sweep result:")
    print(f"    gaps healed:            {result['gaps']}")
    print(f"    conflicts corroborated: {result['corroborated']}")
    print(f"    transfers auto-linked:  {result.get('auto', 0)}")
    print(f"    transfers to confirm:   {result.get('suggested', 0)}")
    print(f"  total transfer links now: {len(proj.transfer_links())} "
          f"(was {before})")
    spend = proj.spending_by_currency()
    if spend:
        print("  external spending (transfers excluded): "
              + ", ".join(f"{c} {v}" for c, v in spend.items()))
    sug = proj.transfer_suggestions()
    if sug:
        print(f"  {len(sug)} possible transfer(s) await your confirmation "
              "(open the surface to rule on them).")


if __name__ == "__main__":
    main()
