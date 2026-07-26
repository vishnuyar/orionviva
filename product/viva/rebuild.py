"""Rebuild a vault from its stored CLAIMS — no model calls, no money, no re-read.

    python -m viva.rebuild  [dest_dir]

`reingest` re-*reads* every document with the model: it tests the reader, and it
costs one call per document. This does the other half, and it is free: every
model reply is already stored verbatim (`ReadRecorded`, ADR-003/T3), so a vault
can be reconstructed by running **today's parsers** over **yesterday's replies**.

What that buys, all at once:

  * **The largest regression test available.** Every parser meets every document
    you have ever ingested, in one run, for nothing. Brokerage Stage 2 has never
    met real data; this is its first encounter.
  * **A clean slate for measurement.** A queue with pre-answered questions
    measures nothing. Rebuilding drops the derived overlays, so tier counts and
    question counts are honest.
  * **Proof the claims layer was worth building.** It has been carried since v0
    on the argument that a stored reply makes re-derivation free. This is that
    argument being cashed.

**It writes a NEW vault and never touches the source.** Your real money, one
shot: the old vault stays until you have looked at the new one.

**Run `python -m viva.export_rulings` FIRST.** A rebuild replays documents; it
cannot replay you. Everything a person told the vault — rulings, categories,
identity confirmations — is dropped, and only that export can bring it back.
"""

from __future__ import annotations

import os
import pathlib
import sys
import time

from .ingest.pipeline import ReadResult
from .ingest.raw_store import RawStore
from .vault import Vault


def claims_by_doc(events) -> dict[str, dict]:
    """The latest extract-phase claim per document, with its classification.

    Two-phase reads store `classify` and `extract` separately; the extract reply
    is what a parser needs, and the classify reply is what names the type. Later
    claims win — a document re-read after a prompt improvement should rebuild
    from the better reply, not the first one."""
    out: dict[str, dict] = {}
    for e in events:
        if e.event_type != "ReadRecorded":
            continue
        b = e.body or {}
        doc = b.get("doc_id", "")
        if not doc:
            continue
        row = out.setdefault(doc, {"extract": None, "classify": None})
        row[b.get("phase", "extract")] = b
    return out


def _parse(doc_type: str, text: str, doc_id: str, locale: str, currency: str):
    """Run TODAY's parser over a stored reply. The same dispatch the reader uses
    — one place, so a rebuild can never quietly diverge from an ingest."""
    from .ingest.brokerage import from_brokerage_json
    from .ingest.paystub import from_paystub_json
    from .ingest.registry import (BROKERAGE_IDENTITY, PAYSTUB_IDENTITY,
                                  profile_for)
    from .ingest.statement import from_model_json

    profile = profile_for(doc_type)
    if profile is None:
        return None, None            # no profile: the document parks, as it should
    parse_fn = {PAYSTUB_IDENTITY: from_paystub_json,
                BROKERAGE_IDENTITY: from_brokerage_json}.get(
                    profile.identity, from_model_json)
    return parse_fn(text, doc_id, locale, currency)


def rebuild(source: pathlib.Path, dest: pathlib.Path, passphrase: str,
            locale: str = "US", currency: str = "USD", by_date: bool = False,
            log=print) -> dict:
    """Replay every stored claim into a fresh vault. Returns counts by outcome."""
    from .ingest import capture_and_ingest
    from .ingest.reader import _peek_classification

    src = Vault.open(source, passphrase)
    src_raw = RawStore.open(source / "raw", passphrase)
    claims = claims_by_doc(src.ledger.store.events())
    doc_ids = [d for d in src_raw.doc_ids() if d in claims]
    missing = [d for d in src_raw.doc_ids() if d not in claims]

    log(f"documents captured: {len(src_raw.doc_ids())}")
    log(f"with stored claims: {len(doc_ids)}"
        + (f"   ({len(missing)} have no claim and cannot be rebuilt free)"
           if missing else ""))
    log(f"  from: {source}")
    log(f"  into: {dest}\n")

    # WHICH ORDER, and why it is a question at all.
    #
    # `src_raw.doc_ids()` yields content hashes, so a replay arrives in
    # effectively random order. Slice 1 promises that ordering does not matter —
    # "every ordering of a 3-month run yields the identical posted chain, zero
    # gaps" — so hash order SHOULD be fine, and running it that way is how we
    # find out whether that promise still holds on 40 real documents.
    #
    # `by_date=True` replays oldest-first instead. If the two orders disagree,
    # the promise is broken and the difference is the measurement.
    if by_date:
        def _period(doc):
            e = claims[doc].get("extract") or {}
            t = e.get("response_text") or ""
            c = claims[doc].get("classify") or {}
            dt, _ = _peek_classification(c.get("response_text") or t)
            facts, _err = _parse(dt, t, doc, locale, currency)
            return getattr(facts, "opening_date", "") or getattr(
                facts, "as_of", "") or getattr(facts, "period_end", "") or ""
        doc_ids = sorted(doc_ids, key=_period)
    log(f"  order: {'oldest first' if by_date else 'as stored (content hash)'}\n")

    vault = Vault.open(dest, passphrase)
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    counts: dict[str, int] = {}

    for i, doc_id in enumerate(doc_ids, 1):
        row = claims[doc_id]
        extract = row.get("extract") or {}
        classify = row.get("classify") or {}
        text = extract.get("response_text") or ""
        doc_type, confidence = _peek_classification(
            classify.get("response_text") or text)

        def replay(_data, new_doc_id, _text=text, _t=doc_type, _c=confidence,
                   _v=extract.get("prompt_version", ""),
                   _m=extract.get("model", "")):
            """The reader's shape, fed from storage instead of a model.

            The parser runs FRESH — that is the entire point — while the model's
            words do not change. `parse_ok` is deliberately not consulted: a
            claim that failed to parse a month ago may parse today, and finding
            that out is half the reason to do this.

            The original `prompt_version` and `model` ride along, so the rebuilt
            vault's claims still name the instructions that actually produced
            the text (T8). A rebuild must not relabel history as its own."""
            facts, err = _parse(_t, _text, new_doc_id, locale, currency)
            if facts is not None:
                # The balance family's extract JSON carries no doc_type — that
                # comes from the CLASSIFY phase, and the reader stamps it onto
                # the facts after parsing. Omitting this is what parked 33 of 40
                # documents on the first real rebuild: every statement came back
                # as `unknown`, which has no projector, so nothing could post.
                facts.doc_type = _t
                facts.doc_type_confidence = _c
            return ReadResult(doc_type=(facts.doc_type if facts else _t),
                              doc_type_confidence=(facts.doc_type_confidence
                                                   if facts else _c),
                              facts=facts, error=err, raw_text=_text,
                              model=_m, prompt_version=_v, input_mode="replay")

        data = src_raw.get(doc_id)
        res = capture_and_ingest(vault.raw, vault.ledger, data, replay,
                                 filename=f"{doc_id[:10]}.pdf", captured_at=now)
        counts[res.action] = counts.get(res.action, 0) + 1
        why = ""
        if res.action not in ("posted", "prepended"):
            # Say WHY on the line itself. A rebuild that quietly parks every
            # document still prints 35 tidy lines and looks like it worked.
            reason = res.message or (res.finding.explain()
                                     if res.finding else "") or "no facts parsed"
            why = f"   [{reason[:70]}]"
        log(f"  [{i}/{len(doc_ids)}] {doc_id[:10]}… {doc_type:24} -> {res.action}"
            + (f" ({res.grade})" if res.grade else "") + why)

    # A rebuild ingests in whatever order the raw store yields, and gap-healing
    # is a CASCADE: a statement that cannot connect yet is held until its
    # neighbour arrives. During normal use that neighbour comes later and the
    # heal fires; in a single batch run, the last arrivals have nobody left to
    # trigger them. So the sweep runs once at the end — the same sweep `rescan`
    # exists for, which is precisely Slice 1's order-independence promise being
    # kept rather than assumed.
    from .ingest import sweep

    swept = sweep(vault.ledger)
    # ALWAYS report the sweep, including when it healed nothing. A silent zero
    # is how the first run of this looked identical to the run before it and
    # nobody could tell whether the sweep had even happened (2026-07-26).
    log(f"\nsweep: healed {swept.get('gaps', 0)} gap(s), corroborated "
        f"{swept.get('corroborated', 0)} conflict(s), linked "
        f"{swept.get('auto', 0)} transfer(s)")
    held = counts.get("gap", 0)
    if held and not swept.get("gaps"):
        log(f"\n  {held} statement(s) still held as gaps after the sweep.\n"
            "  Either their neighbouring statements are genuinely absent — in\n"
            "  which case a gap is the CORRECT answer and the coverage line\n"
            "  should say so — or ordering decided the outcome, which would\n"
            "  contradict Slice 1. Re-run with --by-date to tell the two apart:\n"
            "  if oldest-first posts them, the cascade is not order-independent.")

    # A tool must check its own outcome. `enrich` on the last rebuilt vault said
    # "0 merchants, 0 transactions" — the vault was empty and nothing had said
    # so, because per-document lines are not a result (2026-07-26).
    proj = vault.ledger.projection()
    movements = len(proj.movements())
    log(f"\nrebuilt vault: {len(proj.accounts())} account(s), {movements} movement(s)")
    if movements == 0:
        log("\n  NOTHING WAS REBUILT. The vault is empty.\n"
            "  This is not a result — do not enrich or measure it. Check, in order:\n"
            "    * the outcomes above: all `parked`/`held` means the PARSER failed,\n"
            "      and the bracketed reason on each line says how;\n"
            "    * `python -m viva.debug_claim <doc_id>` re-parses one stored reply\n"
            "      with today's code and prints exactly where it breaks;\n"
            "    * an unrecognised doc_type has no profile, so it parks by design.")
    return counts


def main() -> None:
    from .env import load_dotenv

    load_dotenv()
    passphrase = os.environ.get("VIVA_PASSPHRASE")
    if not passphrase:
        raise SystemExit("Set VIVA_PASSPHRASE (or put it in .env).")
    source = pathlib.Path(os.environ.get("VIVA_VAULT_DIR",
                                         os.path.expanduser("~/.viva-vault")))
    if not source.exists():
        raise SystemExit(f"No vault at {source}.")
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    by_date = "--by-date" in sys.argv
    dest = pathlib.Path(args[0]) if args else source.with_name(
        source.name + "-rebuilt-" + time.strftime("%Y%m%d-%H%M%S"))
    if dest.exists():
        raise SystemExit(f"{dest} already exists — pick a fresh directory.")

    counts = rebuild(source, dest, passphrase,
                     locale=os.environ.get("VIVA_LOCALE", "US"),
                     currency=os.environ.get("VIVA_CURRENCY", "USD"),
                     by_date=by_date)
    print("\ndone: " + ", ".join(f"{n} {a}" for a, n in sorted(counts.items())))
    print(f"\nnext:  VIVA_VAULT_DIR={dest} python3 -m viva.enrich")
    print(f"       VIVA_VAULT_DIR={dest} python3 -m viva.debug_tiers")
    print(f"       VIVA_VAULT_DIR={dest} python3 -m viva.diff_rulings <export.json>")
    print("\nthe source vault is untouched.")


if __name__ == "__main__":
    main()
