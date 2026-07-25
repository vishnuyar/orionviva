"""Enrich the unknown merchants in a vault — one batched model call, then sync.

Gathers the shareable unknown merchants, sends ONLY impersonal hints (a
normalized key + a linted example) to a batched model call via merchantcore,
persists the merchant catalog beside the vault (plain JSON — impersonal, T9), and
syncs the results back into the ledger as events so categorization is
retrospective. Repeatable and idempotent.

Usage (from product/, auto-loads ./.env for VIVA_PASSPHRASE / VIVA_VAULT_DIR and
the model env — VIVA_MODEL_ADAPTER / VIVA_MODEL / VIVA_MODEL_KEY_ENV):

    PYTHONPATH=../core:../merchant:. python3 -m viva.enrich
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
    from merchantcore import Catalog
    from merchantcore.enrich import model_extractor
    from vivacore.models import ModelSpec
    from .ingest import enrich_merchants
    from .vault import Vault

    passphrase = os.environ.get("VIVA_PASSPHRASE") or (
        sys.argv[1] if len(sys.argv) > 1 else None)
    if not passphrase:
        raise SystemExit("Set VIVA_PASSPHRASE (or pass it as the first argument).")
    vault_dir = os.environ.get("VIVA_VAULT_DIR", os.path.expanduser("~/.viva-vault"))
    if not pathlib.Path(vault_dir).exists():
        raise SystemExit("No vault at that path yet — nothing to enrich.")
    if not os.environ.get("VIVA_MODEL"):
        raise SystemExit("No model configured. Set VIVA_MODEL_ADAPTER / VIVA_MODEL "
                         "/ VIVA_MODEL_KEY_ENV (and the key), or put them in ./.env.")

    print(f"vault: {vault_dir}")
    vault = Vault.open(vault_dir, passphrase)
    spec = ModelSpec(
        name="merchant-enricher", adapter=os.environ["VIVA_MODEL_ADAPTER"],
        model=os.environ["VIVA_MODEL"],
        base_url=os.environ.get("VIVA_MODEL_BASE_URL"),
        api_key_env=os.environ.get("VIVA_MODEL_KEY_ENV", "OPENROUTER_API_KEY"),
        json_mode=True)
    # The catalog lives beside the vault, unencrypted — it holds only impersonal
    # merchant knowledge (T9), never anything about your money.
    catalog = Catalog(pathlib.Path(vault_dir) / "merchant-catalog.json")

    result = enrich_merchants(vault.ledger, catalog, model_extractor(spec))
    print(f"submitted {result['submitted']} new merchant(s); enriched "
          f"{result['enriched']}; synced {result['synced']} into the ledger.")
    proj = vault.ledger.projection()
    print(f"merchants known: {len(proj.merchant_categories())}; still unknown: "
          f"{len(proj.uncategorized_merchants())} "
          f"({len(proj.uncategorized_expenses())} transactions)")
    by_cat = proj.spending_by_category()
    if by_cat:
        ranked = sorted(by_cat.items(), key=lambda x: x[1], reverse=True)
        print("spending by category: " + ", ".join(f"{c} {v}" for c, v in ranked))


if __name__ == "__main__":
    main()
