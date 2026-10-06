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

How many merchants ride in one model call is `--chunk-size N`, or
`VIVA_CHUNK_SIZE`, and defaults to the package's own.
"""

from __future__ import annotations

import os
import pathlib
import sys
import datetime
import json
import math
import uuid
from decimal import Decimal, InvalidOperation

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


CHUNK_FLAG = "--chunk-size"


def recorded_model_extractor(ledger, spec):
    """Record merchant request attempts locally without inventing receipts.

    Each batch may draw hints from several documents, so its audit identity is
    a new local claim rather than a falsely attributed captured document.
    Response fragments are recorded before merchant parsing and catalog sync.
    """
    from merchantcore.enrich import model_extractor, ENRICHMENT_VERSION
    from merchantcore.taxonomy import TAXONOMY_VERSION
    from merchantcore.normalize import NORMALIZER_VERSION
    from .ledger.events import read_recorded

    version = f"{ENRICHMENT_VERSION}+{TAXONOMY_VERSION}+{NORMALIZER_VERSION}"

    def record(turn, error, attempt, prompt):
        response = getattr(turn, 'response', {}) or {}
        usage = response.get('usage') if isinstance(response, dict) else None
        usage = usage if isinstance(usage, dict) else {}
        cost = None
        value = usage.get('cost')
        if value is not None and not isinstance(value, bool):
            try:
                amount = Decimal(str(value))
                numeric = float(amount)
                if amount.is_finite() and amount >= 0 and math.isfinite(numeric) \
                        and (numeric != 0 or amount == 0):
                    cost = numeric
            except (InvalidOperation, ValueError, OverflowError):
                pass
        tokens = {}
        for target, names in (
                ('input_tokens', ('prompt_tokens', 'input_tokens')),
                ('output_tokens', ('completion_tokens', 'output_tokens'))):
            for name in names:
                value = usage.get(name)
                if type(value) is int and value >= 0:
                    tokens[target] = value
                    break
        reported_model = response.get('model', '') if isinstance(response, dict) else ''
        envelope = {
            'transport_status': 'failed' if error is not None else 'returned',
            'delivery_status': 'unknown' if error is not None else 'response_received',
            'attempt': attempt, 'prompt': prompt,
            'request': getattr(turn, 'request', None), 'response': response,
            'text': getattr(turn, 'text', ''),
            'error_category': type(error).__name__ if error is not None else None,
        }
        event = read_recorded(
            doc_id=f"merchant-enrichment:{uuid.uuid4().hex}", model=spec.model,
            resolved_model=reported_model if isinstance(reported_model, str) else '',
            prompt_version=version, input_mode='text',
            response_text=json.dumps(envelope, sort_keys=True), cost_usd=cost,
            input_tokens=0, output_tokens=0, usage_reported=False,
            parse_ok=False, parse_error='not_evaluated_at_transport_boundary',
            occurred_at=datetime.date.today().isoformat(), phase='merchant_enrich')
        event.body.update(tokens)
        if tokens:
            event.body['usage_reported'] = True
        ledger.append(event)

    return model_extractor(spec, on_exchange=record)


def sync_installed_merchants(vault, doc_id: str) -> int:
    """Apply installed records matched by one posted statement, without a model."""
    from merchantcore import Catalog, home
    from merchantcore.profile import is_inducible

    from .induce_profile import profile_store
    from .ingest import sync_merchant_records
    from .ledger.hints import enrichment_hints
    from .ledger.streams import build_streams

    projection = vault.ledger.projection()
    movements = [movement for movement in projection.movements()
                 if movement.provenance.doc_id == doc_id]
    store = profile_store()
    profiles: dict = {}
    kinds: dict = {}

    def kind_for(movement):
        if movement.account not in kinds:
            kinds[movement.account] = projection.account_info(movement.account).kind or ""
        return kinds[movement.account]

    eligible = [movement for movement in movements
                if is_inducible(kind_for(movement))]

    def grammar_for(movement):
        info = projection.account_info(movement.account)
        pair = (info.institution or "?", info.kind or "?")
        if pair not in profiles:
            profiles[pair] = store.latest_for(*pair)
        return profiles[pair]

    offered = enrichment_hints(build_streams(eligible, grammar_for, kind_for))
    catalog = Catalog(catalog_path(getattr(vault, "directory", None)),
                      shipped=home.shipped_catalog_file())
    return sync_merchant_records(vault.ledger, catalog, offered)


def enrich_live_merchants(vault, *, chunk_size: int | None = None) -> dict:
    """Enrich newly posted merchants before the caller exposes review.

    The interactive document path used to apply only the installed commons
    records. That left a first sighting at the default category, so the review
    surface immediately asked the person to classify a merchant the product
    could have learned itself. Keep this at the same model boundary as the
    explicit enrichment command and make it a no-op when live reading is not
    configured. The returned counts are safe for a job log; no merchant text
    crosses this function's boundary.

    Enrichment is deliberately synchronous from the upload caller's point of
    view. A document is not settled until this attempt has finished, which
    means a review read after the upload cannot race the catalog sync.
    """
    adapter = os.environ.get("VIVA_MODEL_ADAPTER", "").strip()
    model = os.environ.get("VIVA_MODEL", "").strip()
    if not adapter or not model:
        return {"submitted": 0, "enriched": 0, "synced": 0,
                "unanswered": 0, "minted": 0, "offered": 0,
                "withheld_people": 0}

    from merchantcore import Catalog, home
    from vivacore.models import ModelSpec

    from .induce_profile import profile_store
    from .ingest import enrich_merchants

    spec = ModelSpec(
        name="merchant-enricher", adapter=adapter, model=model,
        base_url=os.environ.get("VIVA_MODEL_BASE_URL"),
        api_key_env=os.environ.get("VIVA_MODEL_KEY_ENV", "OPENROUTER_API_KEY"),
        json_mode=True)
    catalog = Catalog(
        catalog_path(getattr(vault, "directory", None)),
        shipped=home.shipped_catalog_file())
    projection = vault.ledger.projection()
    profiles: dict = {}
    kinds: dict = {}

    def profile_for(movement):
        try:
            info = projection.account_info(movement.account)
        except Exception:  # noqa: BLE001
            return None
        pair = (info.institution or "?", info.kind or "?")
        if pair not in profiles:
            profiles[pair] = profile_store().latest_for(*pair)
        return profiles[pair]

    def kind_for(movement):
        if movement.account not in kinds:
            try:
                kinds[movement.account] = (
                    projection.account_info(movement.account).kind or "")
            except Exception:  # noqa: BLE001
                kinds[movement.account] = ""
        return kinds[movement.account]

    return enrich_merchants(
        vault.ledger, catalog, recorded_model_extractor(vault.ledger, spec),
        profile_for=profile_for, kind_for=kind_for, chunk_size=chunk_size)


def read_chunk_size(args, environ=None) -> tuple[int, list[str]]:
    """How many merchants ride in one model call, and the arguments left over.

    `--chunk-size N` (or `--chunk-size=N`) first, then `VIVA_CHUNK_SIZE`, then
    the package's own default. The flag is taken out of the arguments it was
    read from, so the passphrase stays the first thing that is not a flag.

    A value that is not a whole number of at least one raises SystemExit
    before anything is spent; it is never clamped to a usable one."""
    from merchantcore.enrich import DEFAULT_CHUNK_SIZE
    environ = os.environ if environ is None else environ
    rest: list[str] = []
    given, awaiting = None, False
    for arg in args:
        if awaiting:
            given, awaiting = arg, False
        elif arg == CHUNK_FLAG:
            awaiting = True
        elif arg.startswith(CHUNK_FLAG + "="):
            given = arg.split("=", 1)[1]
        else:
            rest.append(arg)
    if awaiting:
        raise SystemExit(f"{CHUNK_FLAG} needs a number: how many merchants "
                         f"ride in one model call.")
    if given is None:
        # An environment variable set to the empty string counts as unset; a
        # flag given no value does not.
        from_env = environ.get("VIVA_CHUNK_SIZE", "")
        if not from_env.strip():
            return DEFAULT_CHUNK_SIZE, rest
        given = from_env
    if not str(given).strip():
        raise SystemExit(f"{CHUNK_FLAG} needs a number: how many merchants "
                         f"ride in one model call.")
    try:
        size = int(str(given).strip())
    except ValueError:
        raise SystemExit(f"chunk size {str(given).strip()!r} is not a number. "
                         f"Nothing was run and nothing was spent.")
    if size < 1:
        raise SystemExit(f"chunk size {size} would send no merchants at all; "
                         f"it is a count of merchants per call, so it is 1 or "
                         f"more. Nothing was run and nothing was spent.")
    return size, rest


def main() -> None:
    load_dotenv()
    configure_logging()
    from merchantcore import Catalog
    from vivacore.models import ModelSpec
    from .induce_profile import profile_store
    from .ingest import enrich_merchants
    from .vault import Vault

    chunk_size, args = read_chunk_size(sys.argv[1:])
    passphrase = os.environ.get("VIVA_PASSPHRASE") or (
        args[0] if args else None)
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

    # What one call will carry, printed before anything is spent.
    print(f"chunk size: {chunk_size} merchant(s) per model call")

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

    result = enrich_merchants(vault.ledger, catalog, recorded_model_extractor(vault.ledger, spec),
                              profile_for=profile_for, kind_for=kind_for,
                              chunk_size=chunk_size)
    print(f"submitted {result['submitted']} new merchant(s); enriched "
          f"{result['enriched']}; synced {result['synced']} into the ledger.")
    print(f"  {result['minted']} subcategory label(s) minted beyond the "
          f"vocabulary shown")
    proj = vault.ledger.projection()
    # Which subcategory spellings now count as one label. The fold moves a
    # figure and appends no event, so the run says so once.
    merges = proj.subcategory_merges()
    if merges:
        print(f"subcategory spellings now counted as one label "
              f"({len(merges)} label(s)):")
        for label, spellings in merges.items():
            print(f"  {label}  ←  " + ", ".join(spellings))
    print(f"merchants known: {len(proj.merchant_categories())}; still unknown: "
          f"{len(proj.uncategorized_merchants())} "
          f"({len(proj.uncategorized_expenses())} transactions)")
    by_cat = proj.spending_by_category()
    if by_cat:
        ranked = sorted(by_cat.items(), key=lambda x: x[1], reverse=True)
        print("spending by category: " + ", ".join(f"{c} {v}" for c, v in ranked))


if __name__ == "__main__":
    main()
