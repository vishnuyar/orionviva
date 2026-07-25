"""One-time cleanup: rewind a vault to *before* categorization, keeping all else.

Categorization is a graded OVERLAY (Slice 5 / 5.5 / 5.6) — three event types that
never touched a posted transaction, balance, transfer, or income figure:

    CategoryAssigned      — a category on one movement
    MerchantCategorized   — a category on a normalized merchant
    MerchantEnriched      — a merchant's category/subcategory/attributes

This tool rebuilds the event log with exactly those events dropped and *every
other event kept byte-for-byte* (documents, reads, postings, transfers, identity
rulings, your confirmations). The result is a clean categorization slate you can
re-fill from the current taxonomy with ``python -m viva.enrich`` — at no model
cost, because nothing is re-read.

Why a rewrite and not just new events: the log is the source of truth, and a
genuinely clean start means the old categorization is *gone*, not merely
superseded in the projection. This is a deliberate offline maintenance migration,
not a runtime mutation of a live ledger — so it is:

  - **Non-destructive.** The source vault is never touched; a fresh vault is
    written beside it. If anything looks wrong, your original is exactly as it was.
  - **Faithful.** Surviving events keep their original ingestion time
    (``recorded_at``) and body; only the chain is recomputed (seq/prev shift once
    events are removed), re-sealed under the *same* key, so the new log verifies.
  - **Verifiable.** It prints a per-type before/after count and re-verifies the
    new hash chain, so you can see that only the three categorization types left.

Usage (from product/, auto-loads ./.env for VIVA_PASSPHRASE / VIVA_VAULT_DIR):

    PYTHONPATH=../core:. python3 -m viva.reset_categorization  [dest_dir]

Then point the surface at the clean vault and re-enrich:

    VIVA_VAULT_DIR=<dest> python3 -m viva.enrich
    VIVA_VAULT_DIR=<dest> python3 -m viva.web
"""

from __future__ import annotations

import collections
import json
import os
import pathlib
import shutil
import sys
import time

from .crypto import open_sealed, open_vault_header, seal
from .env import load_dotenv
from .ledger.store import GENESIS, _canonical, _record_hash
from .logs import configure as configure_logging

# The overlay event types categorization is made of — the only things removed.
CATEGORIZATION_EVENTS = ("CategoryAssigned", "MerchantCategorized",
                         "MerchantEnriched")


def rebuild_log(src_events: pathlib.Path, dst_events: pathlib.Path,
                passphrase: str,
                drop_types: tuple[str, ...] = CATEGORIZATION_EVENTS
                ) -> tuple[collections.Counter, collections.Counter]:
    """Write ``dst_events`` = ``src_events`` with ``drop_types`` events removed,
    re-chained and re-sealed under the same key. Returns (counts_in, counts_out)
    keyed by event_type. Verifies the source chain as it reads (a corrupt source
    refuses to migrate) and never writes over the source."""
    src_events = pathlib.Path(src_events)
    dst_events = pathlib.Path(dst_events)
    if dst_events.resolve() == src_events.resolve():
        raise ValueError("refusing to rewrite the source log in place — "
                         "choose a different destination")

    with src_events.open() as f:
        header_line = f.readline()
    if not header_line.strip():
        raise ValueError(f"{src_events} has no header")
    header = json.loads(header_line)
    key = open_vault_header(header, passphrase)   # fails fast on wrong passphrase

    # Read + decrypt + verify the source chain, collecting surviving payloads whole.
    counts_in: collections.Counter = collections.Counter()
    counts_out: collections.Counter = collections.Counter()
    survivors: list[dict] = []
    prev = GENESIS
    with src_events.open() as f:
        next(f)                                   # skip header
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            seq, rec_prev, sealed, rec_hash = (
                rec["seq"], rec["prev_hash"], rec["sealed"], rec["record_hash"])
            if rec_prev != prev:
                raise ValueError(f"source chain broken at seq {seq}")
            if _record_hash(seq, rec_prev, sealed) != rec_hash:
                raise ValueError(f"source record hash mismatch at seq {seq}")
            aad = f"{seq}:{rec_prev}".encode("utf-8")
            payload = json.loads(open_sealed(key, sealed, aad))  # full payload
            prev = rec_hash
            et = payload["event"]["event_type"]
            counts_in[et] += 1
            if et in drop_types:
                continue
            survivors.append(payload)
            counts_out[et] += 1

    # Write the new log: same header (same key), survivors re-sequenced and
    # re-sealed. The event body — including its original recorded_at — is
    # untouched; only seq and the chain move.
    dst_events.parent.mkdir(parents=True, exist_ok=True)
    prev = GENESIS
    with dst_events.open("w") as f:
        f.write(json.dumps(header, ensure_ascii=False) + "\n")
        for new_seq, payload in enumerate(survivors):
            payload = dict(payload)
            payload["seq"] = new_seq              # keep recorded_at + event as-is
            aad = f"{new_seq}:{prev}".encode("utf-8")
            sealed = seal(key, _canonical(payload).encode("utf-8"), aad)
            rec_hash = _record_hash(new_seq, prev, sealed)
            record = {"seq": new_seq, "prev_hash": prev, "sealed": sealed,
                      "record_hash": rec_hash}
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
            prev = rec_hash

    return counts_in, counts_out


def reset_vault(source: pathlib.Path, dest: pathlib.Path, passphrase: str,
                drop_types: tuple[str, ...] = CATEGORIZATION_EVENTS
                ) -> tuple[collections.Counter, collections.Counter]:
    """Produce a fresh vault at ``dest``: the rebuilt (de-categorized) event log
    plus the raw-blob store copied across verbatim (raw captures are unchanged —
    categorization was never stored there)."""
    source, dest = pathlib.Path(source), pathlib.Path(dest)
    if dest.exists() and any(dest.iterdir()):
        raise ValueError(f"destination {dest} exists and is not empty")
    dest.mkdir(parents=True, exist_ok=True)

    counts_in, counts_out = rebuild_log(
        source / "events.jsonl", dest / "events.jsonl", passphrase, drop_types)

    src_raw = source / "raw"
    if src_raw.exists():
        shutil.copytree(src_raw, dest / "raw")    # raw blobs carried over as-is
    return counts_in, counts_out


def main() -> None:
    load_dotenv()
    configure_logging()

    passphrase = os.environ.get("VIVA_PASSPHRASE")
    if not passphrase:
        raise SystemExit("Set VIVA_PASSPHRASE (it is never stored).")
    source = pathlib.Path(os.environ.get(
        "VIVA_VAULT_DIR", os.path.expanduser("~/.viva-vault")))
    if not (source / "events.jsonl").exists():
        raise SystemExit(f"No vault at {source}.")
    dest = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else source.with_name(
        source.name + "-precat-" + time.strftime("%Y%m%d-%H%M%S"))

    print("reset categorization — rewind to before categorization, keep all else")
    print(f"  from: {source}")
    print(f"  into: {dest}  (source left untouched)")
    counts_in, counts_out = reset_vault(source, dest, passphrase)

    dropped = sum(counts_in[t] for t in CATEGORIZATION_EVENTS)
    kept = sum(counts_out.values())
    print(f"\nevents: {sum(counts_in.values())} in → {kept} kept, {dropped} dropped")
    for et in sorted(counts_in):
        n_in, n_out = counts_in[et], counts_out.get(et, 0)
        mark = "  DROPPED" if et in CATEGORIZATION_EVENTS else ""
        print(f"    {et}: {n_in} → {n_out}{mark}")

    # Re-open the new vault to prove it verifies and reads cleanly.
    from .vault import Vault
    vault = Vault.open(dest, passphrase)
    ok, count = vault.store.verify_chain()
    print(f"\nnew chain verifies: {ok} ({count} records)")
    print(f"\nnext, re-fill categories on the clean vault:")
    print(f"  VIVA_VAULT_DIR={dest} python3 -m viva.enrich")
    print(f"  VIVA_VAULT_DIR={dest} python3 -m viva.web")


if __name__ == "__main__":
    main()
