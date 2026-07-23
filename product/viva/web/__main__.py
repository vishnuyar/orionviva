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

from ..ingest import ReadResult
from ..vault import Vault
from .sample import seed_sample
from .server import serve


def _parking_reader(data, doc_id):
    """Default reader: no model configured, so a real read can't happen — the
    document is captured and parked rather than guessed at."""
    return ReadResult("unknown", 0.0, None, "no model configured for live reading")


def main() -> None:
    passphrase = os.environ.get("VIVA_PASSPHRASE")
    if not passphrase:
        raise SystemExit("Set VIVA_PASSPHRASE (it is never stored) to open the vault.")
    vault_dir = os.environ.get("VIVA_VAULT_DIR", str(Path.home() / ".viva-vault"))
    vault = Vault.open(vault_dir, passphrase)
    if os.environ.get("VIVA_SAMPLE") == "1":
        seed_sample(vault)

    host, port = "127.0.0.1", 8765
    httpd = serve(vault, _parking_reader, host, port)
    print(f"Viva is at http://{host}:{port}   (vault: {vault_dir})")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
