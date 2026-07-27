"""Re-read every already-captured document into a FRESH vault.

The raw-capture payoff: because every uploaded file is stored raw and encrypted,
a prompt/extraction improvement can be propagated to all held documents by
re-reading them — no re-uploading, no hunting for the originals. Reads cost money
(one model call each), so this reads the stored blobs and writes a *new* vault,
leaving the source untouched.

Usage (from product/, auto-loads ./.env for the passphrase + model config):

    python3 -m viva.reingest  [dest_dir]
    python3 -m viva.reingest  --only brokerage      # just one family
    python3 -m viva.reingest  --only brokerage --dry-run   # what WOULD be read

**`--only` is what makes this affordable to use on a prompt change.** Re-reading
everything costs one model call per document; re-reading the family whose prompt
you actually changed costs a handful. The filter matches a doc_type or any
substring of it, and the type comes from the stored claim — recovered from the
extract PROMPT VERSION when a document has no classify claim.

**`--dry-run` spends nothing** and prints exactly which documents would be read.
Use it first, every time: this is the one command here that costs real money.

WHAT CHANGED, PER DOCUMENT. The run compares each document's outcome in the
SOURCE vault against its outcome now, and prints only the differences —

    parked -> posted     the improvement you were aiming for
    posted -> parked     a REGRESSION; the new prompt is worse for this document

That second line is the whole point. Without it, a prompt change is an act of
faith: you see forty green lines and no way to tell whether you fixed three
documents or broke thirty.

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


def _source_state(source, passphrase, doc_ids):
    """Each document's TYPE and whether it POSTED, in the source vault.

    Read before a single re-read happens, so the run can report what changed
    rather than only what happened. The type falls back to the extract prompt
    version for documents captured without a classify claim — which is most
    of a real vault's older documents."""
    from .ingest.reader import _peek_classification
    from .ingest.registry import doc_type_for_prompt_version
    from .rebuild import claims_by_doc

    src = Vault.open(source, passphrase)
    proj = src.ledger.projection()
    claims = claims_by_doc(src.ledger.store.events())
    types = {}
    for doc_id in doc_ids:
        row = claims.get(doc_id) or {}
        extract = row.get("extract") or {}
        classify = row.get("classify") or {}
        doc_type, _ = _peek_classification(
            classify.get("response_text") or extract.get("response_text") or "")
        if doc_type == "unknown":
            doc_type = doc_type_for_prompt_version(
                extract.get("prompt_version", "")) or doc_type
        types[doc_id] = doc_type
    return types, set(proj._posted)


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
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    dry_run = "--dry-run" in sys.argv
    only = ""
    if "--only" in sys.argv:
        i = sys.argv.index("--only")
        if i + 1 >= len(sys.argv):
            raise SystemExit("--only needs a doc type, e.g. --only brokerage")
        only = sys.argv[i + 1].strip().lower()
        args = [a for a in args if a != sys.argv[i + 1]]
    changed: list = []

    dest = pathlib.Path(args[0]) if args else source.with_name(
        source.name + "-reingested-" + time.strftime("%Y%m%d-%H%M%S"))

    read_fn, is_live = build_reader()
    if not is_live:
        raise SystemExit("Re-reading needs a model — set VIVA_MODEL_ADAPTER / "
                         "VIVA_MODEL / VIVA_MODEL_KEY_ENV (and the key).")

    src_raw = RawStore.open(source / "raw", passphrase)
    doc_ids = src_raw.doc_ids()

    # What each document IS, and what it DID, in the source vault — read before
    # anything is re-read, so "what changed" is a comparison rather than a guess.
    src_types, src_posted = _source_state(source, passphrase, doc_ids)

    if only:
        doc_ids = [d for d in doc_ids
                   if only in (src_types.get(d) or "").lower()]
        if not doc_ids:
            raise SystemExit(
                f"No captured document matches --only {only!r}.\n"
                f"  types present: "
                + ", ".join(sorted({t for t in src_types.values() if t})))

    print(f"re-ingesting {len(doc_ids)} captured document(s)"
          + (f"   (filtered to {only!r})" if only else ""))
    print(f"  from: {source}")
    print(f"  into: {dest}")
    for d in doc_ids:
        print(f"    {d[:10]}…  {src_types.get(d) or 'unknown':<24}"
              f"  was: {'posted' if d in src_posted else 'not posted'}")
    if dry_run:
        print(f"\nDRY RUN — nothing was read and nothing was spent.\n"
              f"  {len(doc_ids)} model call(s) would be made. Drop --dry-run "
              "to do it for real.")
        return

    vault = Vault.open(dest, passphrase)

    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    counts: dict[str, int] = {}
    for i, doc_id in enumerate(doc_ids, 1):
        data = src_raw.get(doc_id)
        res = capture_and_ingest(vault.raw, vault.ledger, data, read_fn,
                                 filename=f"{doc_id[:10]}.pdf", captured_at=now)
        counts[res.action] = counts.get(res.action, 0) + 1
        was = "posted" if doc_id in src_posted else "not posted"
        now_posted = res.action not in ("parked", "held", "awaiting", "conflict")
        if (doc_id in src_posted) != now_posted:
            changed.append((doc_id, was, res.action))
        print(f"  [{i}/{len(doc_ids)}] {doc_id[:10]}… -> {res.action}"
              + (f" ({res.grade})" if res.grade else ""))

    print("done: " + ", ".join(f"{n} {a}" for a, n in sorted(counts.items())))

    # The only lines that matter for deciding whether a prompt ships.
    gained = [c for c in changed if c[1] != "posted"]
    lost = [c for c in changed if c[1] == "posted"]
    print("")
    if lost:
        print(f"  ⚠ REGRESSION — {len(lost)} document(s) posted before and do NOT now:")
        for doc_id, _was, action in lost:
            print(f"      {doc_id[:10]}…  posted -> {action}")
        print("    Do not ship this prompt version. A document that used to read")
        print("    and now does not is a step backwards however good the new")
        print("    figures look on the ones that improved.")
    if gained:
        print(f"  ✓ {len(gained)} document(s) now post that did not before:")
        for doc_id, was, action in gained:
            print(f"      {doc_id[:10]}…  {was} -> {action}")
    if not changed:
        print("  No document changed outcome. If you expected an improvement,")
        print("  the new prompt did not deliver it; if you expected none, this")
        print("  is the regression check passing.")
    print(f"open the new vault with:  VIVA_VAULT_DIR={dest} python3 -m viva.web")


if __name__ == "__main__":
    main()
