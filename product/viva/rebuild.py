"""Rebuild a vault from its stored claims — no model calls, no re-read.

    python -m viva.rebuild  [dest_dir]

Every model reply is stored verbatim as a `ReadRecorded` event, so a vault can
be reconstructed by running **today's parsers** over **yesterday's replies**.
`reingest` does the other half, re-*reading* every document with the model at
one call per document.

**It writes a NEW vault and never touches the source.**

**Run `python -m viva.export_rulings` first.** A rebuild replays documents, not
people: rulings, categories and identity confirmations are dropped, and only
that export brings them back.

Replays oldest first; `--hash-order` replays in raw-store order instead. Prints
what the stored claims contain before starting, then each document's outcome
with the reason where it did not post, the end-of-run sweep, and the final state
of the rebuilt vault.
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
    claims win, so a document re-read after a prompt change rebuilds from the
    later reply."""
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
    """Run today's parser over a stored reply, through the same dispatch the
    reader uses. Returns `(facts, error)`, or `(None, None)` when the doc type
    has no profile and the document parks."""
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
            locale: str = "US", currency: str = "USD", by_date: bool = True,
            log=print) -> dict:
    """Replay every stored claim into a fresh vault. Returns counts by outcome."""
    from .ingest import capture_and_ingest
    from .ingest.reader import _peek_classification
    from .ingest.registry import doc_type_for_prompt_version

    src = Vault.open(source, passphrase)
    src_raw = RawStore.open(source / "raw", passphrase)
    claims = claims_by_doc(src.ledger.store.events())
    doc_ids = [d for d in src_raw.doc_ids() if d in claims]
    missing = [d for d in src_raw.doc_ids() if d not in claims]

    # What the stored claims contain, counted before anything is attempted.
    #
    # The doc type comes from the classify-phase claim and the figures from the
    # extract-phase one. Without a classify claim every balance-family document
    # comes back `unknown` — that family's extract JSON does not name its own
    # type — and parks with an identical message, so both phases are counted and
    # printed up front.
    with_classify = sum(1 for d in doc_ids if (claims[d].get("classify") or {}).get("response_text"))
    with_extract = sum(1 for d in doc_ids if (claims[d].get("extract") or {}).get("response_text"))

    log(f"documents captured: {len(src_raw.doc_ids())}")
    log(f"with stored claims: {len(doc_ids)}"
        + (f"   ({len(missing)} have no claim and cannot be rebuilt free)"
           if missing else ""))
    log(f"  with a CLASSIFY claim: {with_classify}/{len(doc_ids)}"
        + ("" if with_classify == len(doc_ids) else
           "   ← the doc type comes from this phase; without it the balance\n"
           "        family cannot name itself and every statement parks as "
           "'unknown'"))
    log(f"  with an EXTRACT claim:  {with_extract}/{len(doc_ids)}")
    log(f"  from: {source}")
    log(f"  into: {dest}\n")

    # Which order the documents are replayed in.
    #
    # `src_raw.doc_ids()` yields content hashes, so a replay arrives in
    # effectively arbitrary order. `by_date` replays oldest first and is the
    # default: the two orders agree on the money — the same movement total
    # either way — but not always on the grade, with the same statements coming
    # back `conflicted` under one and `corroborated` under the other.
    # `--hash-order` replays as stored.
    if by_date:
        def _period(doc):
            e = claims[doc].get("extract") or {}
            t = e.get("response_text") or ""
            c = claims[doc].get("classify") or {}
            dt, _ = _peek_classification(c.get("response_text") or t)
            if dt == "unknown":
                dt = doc_type_for_prompt_version(
                    e.get("prompt_version", "")) or dt
            facts, _err = _parse(dt, t, doc, locale, currency)
            return getattr(facts, "opening_date", "") or getattr(
                facts, "as_of", "") or getattr(facts, "period_end", "") or ""
        doc_ids = sorted(doc_ids, key=_period)
    log(f"  order: {'oldest first' if by_date else 'as stored (content hash)'}\n")

    vault = Vault.open(dest, passphrase)
    recovered_types = 0
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    counts: dict[str, int] = {}

    for i, doc_id in enumerate(doc_ids, 1):
        row = claims[doc_id]
        extract = row.get("extract") or {}
        classify = row.get("classify") or {}
        text = extract.get("response_text") or ""
        doc_type, confidence = _peek_classification(
            classify.get("response_text") or text)
        if doc_type == "unknown":
            # No classify claim, or an unreadable one. The extract claim still
            # names its type: the version is a self-describing
            # `extract:<base>+<fragment>` composite, and a fragment belongs to
            # exactly one profile, so a read recorded under `card-v1` was a
            # credit-card statement. Without this the document replays as
            # `unknown`, finds no projector, and parks.
            recovered = doc_type_for_prompt_version(extract.get("prompt_version", ""))
            if recovered:
                doc_type, confidence = recovered, 1.0
                recovered_types += 1

        def replay(_data, new_doc_id, _text=text, _t=doc_type, _c=confidence,
                   _v=extract.get("prompt_version", ""),
                   _m=extract.get("model", "")):
            """The reader's shape, fed from storage instead of a model.

            The parser runs fresh over unchanged text. The stored `parse_ok` is
            not consulted, so a claim that failed to parse before may parse now.

            The original `prompt_version` and `model` ride along, so the rebuilt
            vault's claims still name the instructions that produced the text."""
            facts, err = _parse(_t, _text, new_doc_id, locale, currency)
            if facts is not None:
                # The balance family's extract JSON carries no doc_type: it
                # comes from the classify phase, and the reader stamps it onto
                # the facts after parsing. Without it every statement is
                # `unknown`, which has no projector, so nothing posts.
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
            # Name the reason on the line itself, so a run that parks everything
            # says why on every line rather than only in the totals.
            reason = res.message or (res.finding.explain()
                                     if res.finding else "") or "no facts parsed"
            why = f"   [{reason[:70]}]"
        log(f"  [{i}/{len(doc_ids)}] {doc_id[:10]}… {doc_type:24} -> {res.action}"
            + (f" ({res.grade})" if res.grade else "") + why)

    # Gap healing is a cascade: a statement that cannot connect yet is held
    # until its neighbour arrives and triggers the heal. In a single batch run
    # the last arrivals have nothing left to trigger them, so the same sweep
    # `rescan` runs is run once at the end.
    from .ingest import sweep

    swept = sweep(vault.ledger)
    proj = vault.ledger.projection()
    # Reported even when it healed nothing, so a zero is distinguishable from a
    # sweep that never ran.
    log(f"\nsweep: healed {swept.get('gaps', 0)} gap(s), corroborated "
        f"{swept.get('corroborated', 0)} conflict(s), linked "
        f"{swept.get('auto', 0)} transfer(s)")

    # The final state, not the arrival actions.
    #
    # A per-document line records what happened the moment that document landed.
    # A statement arriving before its neighbour is a gap at that instant and
    # posts when the neighbour heals it, while its arrival line still says
    # "gap", so the outcome below is read from the vault instead.
    if recovered_types:
        log(f"\n  {recovered_types} document(s) had no classify claim; their type\n"
            "  was recovered from the extract prompt version.")
    still_held = len([b for b in proj.gap_holds()])
    log(f"still held after everything: {still_held} gap(s)")
    if counts.get("gap") and not still_held:
        log(f"  ({counts['gap']} statement(s) were a gap ON ARRIVAL and healed "
            "when their neighbours landed — that is the cascade working.)")

    # Whether anything was rebuilt at all, read from the vault rather than from
    # the per-document lines.
    movements = len(proj.movements())
    log(f"\nrebuilt vault: {len(proj.accounts())} account(s), {movements} movement(s)")
    if movements == 0:
        log("\n  NOTHING WAS REBUILT. The vault is empty.\n"
            "  This is not a result — do not enrich or measure it. Check, in order:\n"
            "    * the outcomes above: all `parked`/`held` means the PARSER failed,\n"
            "      and the bracketed reason on each line says how;\n"
            "    * `python -m viva.debug.claim <doc_id>` re-parses one stored reply\n"
            "      with today's code and prints exactly where it breaks;\n"
            "    * an unrecognised doc_type has no profile, so it parks by design.")
    return counts


def main() -> None:
    from .env import currency_from_env, load_dotenv, locale_from_env

    load_dotenv()
    passphrase = os.environ.get("VIVA_PASSPHRASE")
    if not passphrase:
        raise SystemExit("Set VIVA_PASSPHRASE (or put it in .env).")
    source = pathlib.Path(os.environ.get("VIVA_VAULT_DIR",
                                         os.path.expanduser("~/.viva-vault")))
    if not source.exists():
        raise SystemExit(f"No vault at {source}.")
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    by_date = "--hash-order" not in sys.argv
    dest = pathlib.Path(args[0]) if args else source.with_name(
        source.name + "-rebuilt-" + time.strftime("%Y%m%d-%H%M%S"))
    if dest.exists():
        raise SystemExit(f"{dest} already exists — pick a fresh directory.")

    counts = rebuild(source, dest, passphrase,
                     locale=locale_from_env(),
                     currency=currency_from_env(),
                     by_date=by_date)
    print("\ndone: " + ", ".join(f"{n} {a}" for a, n in sorted(counts.items())))
    print(f"\nnext:  VIVA_VAULT_DIR={dest} python3 -m viva.enrich")
    print(f"       VIVA_VAULT_DIR={dest} python3 -m viva.debug.tiers")
    print(f"       VIVA_VAULT_DIR={dest} python3 -m viva.diff_rulings <export.json>")
    print("\nthe source vault is untouched.")


if __name__ == "__main__":
    main()
