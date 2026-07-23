"""Re-read every already-captured document into a FRESH vault.

The raw-capture payoff: because every uploaded file is stored raw and encrypted,
a prompt/extraction improvement can be propagated to all held documents by
re-reading them — no re-uploading, no hunting for the originals. Reads cost money
(one model call each), so this reads the stored blobs and writes a *new* vault,
leaving the source untouched.

Usage (from product/, auto-loads ./.env for the passphrase + model config):

    PYTHONPATH=../core:. python3 -m viva.reingest  [dest_dir]

Env: VIVA_PASSPHRASE, VIVA_VAULT_DIR (source; default ~/.viva-vault),
     VIVA_MODEL_ADAPTER / VIVA_MODEL / VIVA_MODEL_KEY_ENV (+ key), VIVA_LOCALE,
     VIVA_CURRENCY. A model must be configured — re-reading needs the model.
"""

from __future__ import annotations

import os
import pathlib
import sys
import time

from .env import load_dotenv
from .ingest import capture_and_ingest
from .ingest.raw_store import RawStore
from .logs import configure as configure_logging
from .vault import Vault
from .web.__main__ import build_reader


def main() -> None:
    load_dotenv()
    configure_logging()

    passphrase = os.environ.get("VIVA_PASSPHRASE")
    if not passphrase:
        raise SystemExit("Set VIVA_PASSPHRASE (it is never stored).")
    source = pathlib.Path(os.environ.get("VIVA_VAULT_DIR",
                                         os.path.expanduser("~/.viva-vault")))
    if not source.exists():
        raise SystemExit(f"No vault at {source}.")
    dest = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else source.with_name(
        source.name + "-reingested-" + time.strftime("%Y%m%d-%H%M%S"))

    read_fn, is_live = build_reader()
    if not is_live:
        raise SystemExit("Re-reading needs a model — set VIVA_MODEL_ADAPTER / "
                         "VIVA_MODEL / VIVA_MODEL_KEY_ENV (and the key).")

    src_raw = RawStore.open(source / "raw", passphrase)
    doc_ids = src_raw.doc_ids()
    print(f"re-ingesting {len(doc_ids)} captured document(s)")
    print(f"  from: {source}")
    print(f"  into: {dest}")
    vault = Vault.open(dest, passphrase)

    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    counts: dict[str, int] = {}
    for i, doc_id in enumerate(doc_ids, 1):
        data = src_raw.get(doc_id)
        res = capture_and_ingest(vault.raw, vault.ledger, data, read_fn,
                                 filename=f"{doc_id[:10]}.pdf", captured_at=now)
        counts[res.action] = counts.get(res.action, 0) + 1
        print(f"  [{i}/{len(doc_ids)}] {doc_id[:10]}… -> {res.action}"
              + (f" ({res.grade})" if res.grade else ""))

    print("done: " + ", ".join(f"{n} {a}" for a, n in sorted(counts.items())))
    print(f"open the new vault with:  VIVA_VAULT_DIR={dest} python3 -m viva.web")


if __name__ == "__main__":
    main()
