"""What Viva needs from you, ranked — against a real vault, read-only.

The question queue (Slice 6.5 Move 2) on the command line, the way debug_vault
works. Shows the highest-stake questions first and summarizes the tail, so you
can see at a glance what answering would actually move.

Usage (from product/, auto-loads ./.env for VIVA_PASSPHRASE / VIVA_VAULT_DIR):

    PYTHONPATH=../core:../merchant:. python3 -m viva.ask          # top 10
    PYTHONPATH=../core:../merchant:. python3 -m viva.ask 25       # top 25

Nothing is written and no model is called.
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
    from .questions import DEFAULT_LIMIT, open_questions
    from .vault import Vault

    passphrase = os.environ.get("VIVA_PASSPHRASE") or (
        sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].isdigit() else None)
    if not passphrase:
        raise SystemExit("Set VIVA_PASSPHRASE (it is never stored).")
    vault_dir = os.environ.get("VIVA_VAULT_DIR", os.path.expanduser("~/.viva-vault"))
    if not pathlib.Path(vault_dir).exists():
        raise SystemExit(f"No vault at {vault_dir}.")
    limit = next((int(a) for a in sys.argv[1:] if a.isdigit()), DEFAULT_LIMIT)

    vault = Vault.open(vault_dir, passphrase)
    result = open_questions(vault.ledger, limit=limit)

    total = result["total"]
    if not total:
        print("Nothing needs you right now — everything I hold is settled.")
        return
    print(f"{total} thing(s) need you. The ones that move the most money first:\n")
    for i, q in enumerate(result["questions"], 1):
        money = f"{q['currency']} {q['amount']}".strip()
        scope = "settles this one" if q["scope"] == "one" else \
            f"settles all {q['count']} — and future ones"
        print(f"{i:>2}. [{q['kind']}] {money}   ({scope})")
        print(f"    {q['text']}")
        print(f"    why: {q['why']}")
        if q["options"]:
            print("    " + "  |  ".join(o["label"] for o in q["options"]))
        print()
    tail = result["tail"]
    if tail["count"]:
        print(f"...plus {tail['count']} smaller item(s) worth {tail['amount']} in "
              f"total. Run with a bigger number to see them.")


if __name__ == "__main__":
    main()
