"""Run the surface:  VIVA_PASSPHRASE=... python -m viva.web

Environment:
  VIVA_PASSPHRASE  (required) — opens the vault; never stored anywhere.
  VIVA_VAULT_DIR   (optional) — vault location; default ~/.viva-vault.
  VIVA_SAMPLE=1    (optional) — seed fabricated sample data on start.

The live document reader (a real model call) is intentionally NOT wired here by
default — uploads park until a model is configured, so nothing leaves the
machine until you choose the real run. The vault is opened locally, the server
binds to localhost only.
"""

from __future__ import annotations

import os
from pathlib import Path

from ..env import load_dotenv
from ..ingest import ReadResult, heal_gaps
from ..logs import configure as configure_logging
from ..vault import Vault
from .sample import seed_sample
from .server import serve


def _parking_reader(data, doc_id):
    """Default reader: no model configured, so a real read can't happen — the
    document is captured and parked rather than guessed at."""
    return ReadResult("unknown", 0.0, None, "no model configured for live reading")


def build_reader():
    """Return (read_fn, is_live). A live reader is wired only when a model is
    configured in the environment — until then uploads park, so nothing leaves
    the machine by accident.

    Env to enable live reading:
      VIVA_MODEL_ADAPTER   'anthropic' or 'openai-compatible'
      VIVA_MODEL           a PINNED model id (never a 'latest' alias)
      VIVA_MODEL_KEY_ENV   name of the env var holding the API key
      VIVA_MODEL_BASE_URL  (openai-compatible only, e.g. OpenRouter)
      VIVA_LOCALE          default 'en-US'      VIVA_CURRENCY default 'USD'
    """
    adapter = os.environ.get("VIVA_MODEL_ADAPTER")
    model = os.environ.get("VIVA_MODEL")
    if not (adapter and model):
        return _parking_reader, False

    from vivacore.models import ModelSpec
    from ..ingest.reader import read_statement

    spec = ModelSpec(
        name="viva-reader", adapter=adapter, model=model,
        base_url=os.environ.get("VIVA_MODEL_BASE_URL"),
        api_key_env=os.environ.get("VIVA_MODEL_KEY_ENV", "ANTHROPIC_API_KEY"))
    locale = os.environ.get("VIVA_LOCALE", "en-US")
    currency = os.environ.get("VIVA_CURRENCY", "USD")

    def reader(data, doc_id):
        return read_statement(data, doc_id, spec, locale, currency)

    return reader, True


def main() -> None:
    load_dotenv()          # pick up VIVA_PASSPHRASE / VIVA_MODEL_* from ./.env
    configure_logging()    # chatty console logs (VIVA_LOG_LEVEL=DEBUG for more)
    passphrase = os.environ.get("VIVA_PASSPHRASE")
    if not passphrase:
        raise SystemExit("Set VIVA_PASSPHRASE (it is never stored), in your "
                         "environment or in a ./.env file, to open the vault.")
    vault_dir = os.environ.get("VIVA_VAULT_DIR", str(Path.home() / ".viva-vault"))
    vault = Vault.open(vault_dir, passphrase)
    if os.environ.get("VIVA_SAMPLE") == "1":
        seed_sample(vault)
    healed = heal_gaps(vault.ledger)    # resolve any gaps that can now stitch
    if healed:
        print(f"  healed {healed} previously-held statement(s)")

    read_fn, is_live = build_reader()
    host, port = "127.0.0.1", 8765
    httpd = serve(vault, read_fn, host, port)
    mode = "live model reading ON" if is_live else "uploads park (no model configured)"
    print(f"Viva is at http://{host}:{port}   (vault: {vault_dir})")
    print(f"  {mode}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
