"""Inspect what is actually in a vault — the answer to 'I uploaded it, where is it?'

Opens the vault with your passphrase and prints a summary: how many events and
of what kind, the raw blobs held, the accounts and their balances, anything held
for review, and the coverage line. Read-only.

Usage (from product/, auto-loads ./.env for VIVA_PASSPHRASE / VIVA_VAULT_DIR):

    PYTHONPATH=../core:. python3 -m viva.debug_vault
"""

from __future__ import annotations

import collections
import os
import pathlib
import sys


def _load_dotenv() -> None:
    if os.environ.get("VIVA_PASSPHRASE"):
        return
    p = pathlib.Path(".env")
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k, v.strip().strip("'").strip('"'))


def main() -> None:
    _load_dotenv()
    from .answer import coverage_summary
    from .ingest import held_items
    from .ledger import LedgerProjection
    from .vault import Vault

    passphrase = os.environ.get("VIVA_PASSPHRASE") or (sys.argv[1] if len(sys.argv) > 1 else None)
    if not passphrase:
        raise SystemExit("Set VIVA_PASSPHRASE (or pass it as the first argument).")
    vault_dir = os.environ.get("VIVA_VAULT_DIR", os.path.expanduser("~/.viva-vault"))
    print(f"vault: {vault_dir}")
    if not pathlib.Path(vault_dir).exists():
        raise SystemExit("No vault at that path yet — nothing has been ingested here.")

    vault = Vault.open(vault_dir, passphrase)
    events = list(vault.events())
    print(f"events: {len(events)}")
    for etype, n in collections.Counter(e.event_type for e in events).most_common():
        print(f"    {etype}: {n}")
    print(f"raw blobs (captured files): {len(vault.raw.doc_ids())}")

    proj = LedgerProjection(events)
    infos = proj.account_infos()
    print(f"accounts posted: {len(infos)}")
    for i in infos:
        ba = proj.balance(i.account)
        print(f"    {i.name} [{i.kind} {i.currency}] = {ba.amount} ({ba.grade})")

    held = held_items(events)
    print(f"held for review: {len(held)}")
    for h in held:
        f = h.finding or {}
        print(f"    {h.account_ref}: reason={h.reason} — "
              f"{f.get('kind')}/{f.get('status')}: {(f.get('message') or '')[:140]}")

    # Documents captured but not posted (parked) — checking-classified or not.
    print(f"coverage: {coverage_summary(events).text}")

    captured = [(e.body.get('doc_id', '')[:10], e.body.get('doc_type'))
                for e in events if e.event_type == "DocumentCaptured"]
    print("captured documents (id, model's doc_type):")
    for did, dt in captured:
        print(f"    {did}…  {dt}")


if __name__ == "__main__":
    main()
