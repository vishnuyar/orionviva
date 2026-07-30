"""Export everything a person told this vault, as plain JSON.

    python -m viva.export_rulings  [out.json]

A rebuild replays documents; it cannot replay the rulings, categories, identity
confirmations and corrections a person gave, and no amount of re-reading
reconstructs them. This writes them out — defaulting to
`<vault>/rulings-export.json` — and prints a count per event type plus the first
ten sentences somebody typed. Run it before `viva.rebuild`.

The same file is the answer key `viva.diff_rulings` scores a rebuilt vault
against.

Contains personal data by construction: merchant names, your own words, account
ids. Write it somewhere private; it is not for the repo.
"""

from __future__ import annotations

import json
import os
import pathlib
import sys

# Everything a person authored, and nothing a rebuild can re-derive from the
# documents.
HUMAN_EVENTS = (
    "RulingRecorded",          # the four majors, in your words
    "CategoryAssigned",        # per-transaction categories
    "MerchantCategorized",     # "this merchant is X, everywhere"
    "MerchantEnriched",        # only where by=human
    "AccountAliasConfirmed",   # "yes, that is the same account"
    "TransferConfirmed", "TransferRejected",
    "CorrectionApplied",       # a figure you attested after review
    "ClosingBalanceObserved",  # only where confirmed_by=human
)


def _is_human(event) -> bool:
    body = event.body or {}
    if body.get("by") == "human" or body.get("confirmed_by") == "human":
        return True
    # Some human events carry no `by` because only a person can produce them.
    return event.event_type in ("AccountAliasConfirmed", "TransferConfirmed",
                                "TransferRejected", "CorrectionApplied")


def collect(events) -> list[dict]:
    """Every human-authored event, in order, as plain dicts."""
    out = []
    for e in events:
        if e.event_type in HUMAN_EVENTS and _is_human(e):
            out.append({"event_type": e.event_type, "occurred_at": e.occurred_at,
                        "body": e.body})
    return out


def summarize(rulings: list[dict]) -> str:
    by_type: dict[str, int] = {}
    for r in rulings:
        by_type[r["event_type"]] = by_type.get(r["event_type"], 0) + 1
    lines = [f"{len(rulings)} thing(s) you told this vault:"]
    for kind, n in sorted(by_type.items(), key=lambda x: -x[1]):
        lines.append(f"  {n:4}  {kind}")
    said = [r for r in rulings if (r["body"] or {}).get("said")]
    if said:
        lines += ["", "  in your own words:"]
        for r in said[:10]:
            lines.append(f"    “{r['body']['said']}”")
    return "\n".join(lines)


def main() -> None:
    from .env import load_dotenv
    from .vault import Vault

    load_dotenv()
    passphrase = os.environ.get("VIVA_PASSPHRASE")
    if not passphrase:
        raise SystemExit("Set VIVA_PASSPHRASE (or put it in .env).")
    vault_dir = os.environ.get("VIVA_VAULT_DIR", os.path.expanduser("~/.viva-vault"))
    out = pathlib.Path(sys.argv[1] if len(sys.argv) > 1
                       else pathlib.Path(vault_dir) / "rulings-export.json")

    vault = Vault.open(vault_dir, passphrase)
    rulings = collect(vault.ledger.store.events())
    out.write_text(json.dumps({"source": str(vault_dir), "count": len(rulings),
                               "rulings": rulings}, indent=2), encoding="utf-8")
    print(f"vault:  {vault_dir}")
    print(f"wrote:  {out}\n")
    print(summarize(rulings))
    if rulings:
        print("\n  Keep this. It is your answer key for the rebuild, and the only\n"
              "  part of the vault a re-read cannot reconstruct.")


if __name__ == "__main__":
    main()
