"""Enrich the unknown merchants in a vault — one batched model call, then sync.

Gathers the shareable unknown merchants, sends only impersonal hints (a
normalized key and a linted example) to a batched model call via merchantcore,
persists the merchant catalog as plain JSON at `catalog_path`, and syncs the
results back into the ledger as events, so categorization applies to movements
already posted. Repeatable and idempotent.

Prints the catalog in use and how many merchants it already holds, then what was
submitted, enriched and synced, and the spending by category that results.

Usage (from product/, auto-loads ./.env for VIVA_PASSPHRASE / VIVA_VAULT_DIR and
the model env — VIVA_MODEL_ADAPTER / VIVA_MODEL / VIVA_MODEL_KEY_ENV):

    PYTHONPATH=../core:../merchant:. python3 -m viva.enrich

The passphrase may be given as the first argument instead of in the environment.
"""

from __future__ import annotations

import os
import pathlib
import sys

from .env import load_dotenv
from .logs import configure as configure_logging


def catalog_path(vault_dir=None) -> pathlib.Path:
    """Where the merchant catalog lives — merchantcore's home, not the vault's.

    It holds impersonal merchant knowledge — a brand, a category, attributes —
    and nothing about anyone's money, so one file is reused across every vault.

    `VIVA_CATALOG` overrides. While merchantcore's file does not exist yet, an
    older catalog at `~/.viva/merchant-catalog.json` or beside `vault_dir` is
    returned instead.
    """
    from merchantcore import home
    explicit = os.environ.get("VIVA_CATALOG")
    if explicit:
        return pathlib.Path(explicit).expanduser()
    shared = home.catalog_file()
    if not shared.exists():
        older = [pathlib.Path("~/.viva/merchant-catalog.json").expanduser()]
        if vault_dir:
            older.append(pathlib.Path(vault_dir) / "merchant-catalog.json")
        for old in older:
            if old.exists():
                return old
    return shared


def main() -> None:
    load_dotenv()
    configure_logging()
    from merchantcore import Catalog
    from merchantcore.enrich import model_extractor
    from vivacore.models import ModelSpec
    from .induce_profile import profile_store
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
    cpath = catalog_path(vault_dir)
    from merchantcore import home
    catalog = Catalog(cpath, shipped=home.shipped_catalog_file())
    known = len(catalog.records()) if hasattr(catalog, "records") else len(catalog._records)
    # `submit` skips anything already in the catalog, so a model call means the
    # catalog just loaded does not hold those merchants. Name the file and its
    # size, which is what tells one catalog from another.
    print(f"catalog: {cpath}")
    print(f"  {known} merchant(s) already known"
          + ("" if known else
             "   ← EMPTY. Nothing here has been learned yet, so every merchant\n"
             "        below will cost a model call. If you have a catalog from\n"
             "        another vault, point VIVA_CATALOG at it or copy it here\n"
             "        first — the whole purpose of the catalog is that this\n"
             "        knowledge is bought once."))

    # Both closures are passed. `profile_for` keys records by the induced
    # grammar's name rather than by the normalizer alone; `kind_for` supplies the
    # account kind the allowlist gates on, which is what keeps an investment
    # activity line from being offered to a model as a merchant.
    proj0 = vault.ledger.projection()
    _profiles: dict = {}

    def profile_for(m):
        try:
            info = proj0.account_info(m.account)
        except Exception:                                   # noqa: BLE001
            return None
        pair = (info.institution or "?", info.kind or "?")
        if pair not in _profiles:
            _profiles[pair] = profile_store().latest_for(*pair)
        return _profiles[pair]

    _kinds: dict = {}

    def kind_for(m):
        if m.account not in _kinds:
            try:
                _kinds[m.account] = proj0.account_info(m.account).kind or ""
            except Exception:                               # noqa: BLE001
                _kinds[m.account] = ""
        return _kinds[m.account]

    result = enrich_merchants(vault.ledger, catalog, model_extractor(spec),
                              profile_for=profile_for, kind_for=kind_for)
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
