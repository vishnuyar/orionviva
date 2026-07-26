"""Diagnose a read we ALREADY PAID FOR — from the claims layer, offline and free.

Every model read is stored verbatim (`ReadRecorded`, ADR-003/T3). So when a
document parks or holds, the evidence is already in the vault: we never need to
re-ask the model to find out what it said. This tool prints that stored response
and re-runs today's parser and identity check over it.

Two things that makes possible, both otherwise expensive:

  - **Diagnose the past for nothing.** "Why did this statement hold?" is answered
    from the log, not from a new call.
  - **Test a parser fix against real data.** Re-parsing an OLD stored read with
    NEW code shows immediately whether a fix would have rescued it — the closest
    thing to a regression test on real documents, at zero cost and with no
    real financial data ever leaving the machine.

Usage (from product/, auto-loads ./.env for VIVA_PASSPHRASE / VIVA_VAULT_DIR):

    PYTHONPATH=../core:../merchant:. python3 -m viva.debug_claim            # list reads
    PYTHONPATH=../core:../merchant:. python3 -m viva.debug_claim fbdcae06   # diagnose one
    PYTHONPATH=../core:../merchant:. python3 -m viva.debug_claim fbdcae06 --raw

Read-only: nothing is written, no model is called.
"""

from __future__ import annotations

import os
import pathlib
import sys

from .env import currency_from_env, load_dotenv, locale_from_env
from .logs import configure as configure_logging


def _parse_and_check(doc_type: str, text: str, doc_id: str, locale: str,
                     currency: str) -> None:
    """Re-parse a stored response with TODAY's code and run its profile's identity,
    reporting what would happen now: POST, HOLD, or PARK."""
    from vivacore.verify.arithmetic import (check_balance_identity,
                                            check_brokerage_identity,
                                            check_paystub_identity)
    from .ingest.brokerage import from_brokerage_json
    from .ingest.paystub import from_paystub_json
    from .ingest.registry import (BROKERAGE_IDENTITY, PAYSTUB_IDENTITY,
                                  profile_for)
    from .ingest.statement import from_model_json

    profile = profile_for(doc_type)
    if profile is None:
        print(f"[parse] no profile for {doc_type!r} — this document PARKS.")
        return
    identity = profile.identity
    parse_fn = {PAYSTUB_IDENTITY: from_paystub_json,
                BROKERAGE_IDENTITY: from_brokerage_json}.get(identity, from_model_json)

    facts, err = parse_fn(text, doc_id, locale, currency)
    if err:
        print(f"[parse] FAILED with today's code: {err}")
        print("        -> would PARK. The raw output above is what the model said;"
              " the fix is a parser/prompt change, not another call.")
        return

    if identity == PAYSTUB_IDENTITY:
        r = check_paystub_identity(facts.gross, [d.amount for d in facts.deductions],
                                   facts.net)
        print(f"[parse] ok — pay stub, employer={facts.employer!r}, "
              f"{len(facts.deductions)} deduction(s)")
        print(f"[verify] {'PASS -> POST' if r.passed else 'FAIL -> HOLD'}. {r.explain()}")
        return

    if identity == BROKERAGE_IDENTITY:
        # Apply the SAME sweep decision the projector makes, so this tool can never
        # disagree with what an ingest would actually do.
        from .ingest.brokerage import resolve_sweep_cash
        facts, sweep_note = resolve_sweep_cash(facts)
        if sweep_note:
            print(f"[sweep]  money-market sweep counted as cash — {sweep_note}.")
        holdings = facts.positions
        print(f"[parse] ok — brokerage, account={facts.account_ref!r} as of {facts.as_of}")
        print(f"        {len(holdings)} holding(s), {len(facts.activity)} activity "
              f"item(s), opening_cash={facts.opening_cash}")
        r = check_brokerage_identity([p.market_value for p in holdings], facts.cash,
                                     facts.total)
        print(f"[tally]  {'PASS' if r.passed else 'FAIL -> HOLD'}. {r.explain()}")
        if not r.passed:
            # The most useful thing we can print: every number the identity used,
            # so the discrepancy can be read off against the paper statement.
            print("        the figures it stood on:")
            for p in holdings:
                print(f"          {p.instrument:<46}{p.units:>12} units {p.market_value:>14}")
            print(f"          {'cash (incl. any folded cash/sweep row)':<46}"
                  f"{facts.cash:>33}")
            print(f"          {'= holdings + cash':<46}"
                  f"{sum((p.market_value for p in holdings), start=facts.cash):>33}")
            print(f"          {'stated total':<46}{facts.total:>33}")
            print(f"          {'difference':<46}{r.delta:>33}")
        if facts.activity and facts.opening_cash is None:
            print(f"        NOTE: {len(facts.activity)} activity item(s) were read "
                  "but no opening cash was, so the cash flow cannot be reconciled "
                  "and the activity is NOT posted.")
        return

    r = check_balance_identity(facts.opening_amount,
                               [t.amount for t in facts.transactions],
                               facts.closing_amount)
    print(f"[parse] ok — {facts.account_ref!r}, {len(facts.transactions)} transactions")
    print(f"[verify] {'PASS -> POST' if r.passed else 'FAIL -> HOLD'}. {r.explain()}")


def main() -> None:
    load_dotenv()
    configure_logging()
    from .vault import Vault

    passphrase = os.environ.get("VIVA_PASSPHRASE")
    if not passphrase:
        raise SystemExit("Set VIVA_PASSPHRASE (it is never stored).")
    vault_dir = os.environ.get("VIVA_VAULT_DIR", os.path.expanduser("~/.viva-vault"))
    if not pathlib.Path(vault_dir).exists():
        raise SystemExit(f"No vault at {vault_dir}.")
    locale = locale_from_env()
    currency = currency_from_env()

    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    show_raw = "--raw" in sys.argv[1:]
    wanted = args[0] if args else ""

    vault = Vault.open(vault_dir, passphrase)
    events = list(vault.events())
    captured = {e.body["doc_id"]: e.body for e in events
                if e.event_type == "DocumentCaptured"}
    reads = [e for e in events if e.event_type == "ReadRecorded"]

    if not wanted:
        print(f"stored reads: {len(reads)} (pass a doc_id prefix to diagnose one)\n")
        for e in reads:
            b = e.body
            did = b.get("doc_id", "")
            cap = captured.get(did, {})
            print(f"  {did[:12]}  {b.get('phase','extract'):<8} "
                  f"{cap.get('doc_type','?'):<22} {b.get('prompt_version',''):<38} "
                  f"parse_ok={str(b.get('parse_ok')):<5} ${b.get('cost_usd',0):.4f}  "
                  f"{cap.get('filename','')}")
        return

    matches = [e for e in reads if e.body.get("doc_id", "").startswith(wanted)]
    if not matches:
        raise SystemExit(f"No stored read whose doc_id starts with {wanted!r}.")

    for e in matches:
        b = e.body
        did = b.get("doc_id", "")
        cap = captured.get(did, {})
        doc_type = cap.get("doc_type", "unknown")
        if doc_type in ("", "unknown"):
            # The capture never recorded a type (no classify claim), but the
            # EXTRACT prompt version names it: T8's self-describing
            # `extract:<base>+<fragment>`. Printing "unknown" while the very
            # next line of this report shows `prompt=extract:base-v1+card-v1`
            # is the tool withholding an answer it already has.
            from .ingest.registry import doc_type_for_prompt_version
            for candidate in [b] + [m.body for m in matches]:
                recovered = doc_type_for_prompt_version(
                    candidate.get("prompt_version", ""))
                if recovered:
                    doc_type = recovered
                    print(f"  (no classify claim; type recovered from the "
                          f"extract prompt version: {recovered})")
                    break
        print("=" * 78)
        print(f"doc {did[:12]}  {cap.get('filename','')}  ({doc_type})")
        print(f"  phase={b.get('phase','extract')}  model={b.get('model')}  "
              f"prompt={b.get('prompt_version')}")
        print(f"  cost=${b.get('cost_usd',0):.4f}  parse_ok_at_the_time="
              f"{b.get('parse_ok')}  error={b.get('parse_error')}")
        text = b.get("response_text") or ""
        print(f"  response: {len(text)} chars")
        if b.get("phase") == "classify":
            print(f"  -> {text.strip()[:200]}")
            continue
        if show_raw:
            print("-" * 26 + " RAW STORED RESPONSE " + "-" * 26)
            print(text)
            print("-" * 78)
        print()
        _parse_and_check(doc_type, text, did, locale, currency)


if __name__ == "__main__":
    main()
