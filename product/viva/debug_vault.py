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

from .env import load_dotenv
from .logs import configure as configure_logging


def main() -> None:
    load_dotenv()
    configure_logging()
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
        if h.reason == "gap":
            print(f"    {h.account_ref}: GAP — opens {h.facts.opening_amount} "
                  f"({h.facts.opening_date}); chain held at {h.held_balance}")
        else:
            f = h.finding or {}
            print(f"    {h.account_ref}: CONFLICT — {f.get('kind')}/{f.get('status')}: "
                  f"{(f.get('message') or '')[:120]}")

    # Documents captured but not posted (parked) — checking-classified or not.
    print(f"coverage: {coverage_summary(events).text}")

    captured = [(e.body.get('doc_id', '')[:10], e.body.get('doc_type'))
                for e in events if e.event_type == "DocumentCaptured"]
    print("captured documents (id, model's doc_type):")
    for did, dt in captured:
        print(f"    {did}…  {dt}")

    reads = [e for e in events if e.event_type == "ReadRecorded"]
    if reads:
        print("model reads recorded (claims layer):")
        for e in reads:
            b = e.body
            print(f"    {b.get('doc_id','')[:10]}…  model={b.get('model')}  "
                  f"prompt={b.get('prompt_version')}  cost=${b.get('cost_usd',0):.4f}  "
                  f"parse_ok={b.get('parse_ok')}  resp_chars={len(b.get('response_text') or '')}"
                  + (f"  error={b.get('parse_error')}" if not b.get('parse_ok') else ""))


if __name__ == "__main__":
    main()
