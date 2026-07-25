"""Inspect what is actually in a vault — the answer to 'I uploaded it, where is it?'

Opens the vault with your passphrase and prints a summary: how many events and
of what kind, the raw blobs held, the accounts and their balances, anything held
for review, and the coverage line. Read-only.

Usage (from product/, auto-loads ./.env for VIVA_PASSPHRASE / VIVA_VAULT_DIR):

    PYTHONPATH=../core:. python3 -m viva.debug_vault
"""

from __future__ import annotations

import collections
from decimal import Decimal
import os
import pathlib
import sys

from .env import load_dotenv
from .logs import configure as configure_logging


def main() -> None:
    load_dotenv()
    configure_logging()
    from .answer import coverage_summary
    from .ingest import held_items
    from .vault import Vault

    passphrase = os.environ.get("VIVA_PASSPHRASE") or (sys.argv[1] if len(sys.argv) > 1 else None)
    if not passphrase:
        raise SystemExit("Set VIVA_PASSPHRASE (or pass it as the first argument).")
    vault_dir = os.environ.get("VIVA_VAULT_DIR", os.path.expanduser("~/.viva-vault"))
    print(f"vault: {vault_dir}")
    if not pathlib.Path(vault_dir).exists():
        raise SystemExit("No vault at that path yet — nothing has been ingested here.")

    vault = Vault.open(vault_dir, passphrase)
    events = list(vault.events())
    print(f"events: {len(events)}")
    for etype, n in collections.Counter(e.event_type for e in events).most_common():
        print(f"    {etype}: {n}")
    print(f"raw blobs (captured files): {len(vault.raw.doc_ids())}")

    from .ingest.identity import masked
    proj = vault.ledger.projection()
    infos = proj.account_infos()
    print(f"accounts posted: {len(infos)}")
    for i in infos:
        ba = proj.balance(i.account)
        owed = " owed" if i.kind == "liability" else ""
        print(f"    {i.name} [{i.kind} {i.currency}] = {ba.amount}{owed} ({ba.grade})")
        print(f"        id={i.account}  institution={i.institution!r}  "
              f"number={masked(i.number)}  holders={i.names}")

    held = held_items(proj)
    print(f"held for review: {len(held)}")
    for h in held:
        f = h.finding or {}
        if h.reason == "gap":
            print(f"    {h.account_ref}: GAP — opens {h.facts.opening_amount} "
                  f"({h.facts.opening_date}); chain held at {h.held_balance}")
        elif h.reason == "identity":
            print(f"    {h.account_ref}: IDENTITY — {f.get('message')} "
                  f"(candidate: {f.get('candidate_name')})")
        else:
            print(f"    {h.account_ref}: CONFLICT — {f.get('kind')}/{f.get('status')}: "
                  f"{(f.get('message') or '')[:120]}")

    # Transfers (Slice 3): recognized internal movements + anything suggested.
    links = proj.transfer_links()
    print(f"transfer links: {len(links)}")
    for lk in links:
        print(f"    [{lk.get('grade')}/{lk.get('by')}] {lk['a']}  <->  {lk['b']}")
    sugg = proj.transfer_suggestions()
    if sugg:
        print(f"transfer suggestions (awaiting your ruling): {len(sugg)}")
        for s in sugg:
            ev = s.get("evidence", {})
            print(f"    {s['a']}  ~  {len(s.get('candidates', []))} candidate(s) "
                  f"({ev.get('currency','')} {ev.get('amount','')})")
    spend = proj.spending_by_currency()
    if spend:
        print("external spending (transfers excluded): "
              + ", ".join(f"{c} {v}" for c, v in spend.items()))
    by_cat = proj.spending_by_category()
    if by_cat:
        ranked = sorted(by_cat.items(), key=lambda x: x[1], reverse=True)
        print("spending by category (non-spending natures excluded): "
              + ", ".join(f"{c} {v}" for c, v in ranked))
        # Slice 6.5: what was kept OUT and why, and how much is weakly evidenced.
        excluded = proj.excluded_from_spending()
        if excluded:
            by_reason: dict[str, Decimal] = {}
            for m in excluded:
                by_reason[m.nature_reason] = (by_reason.get(m.nature_reason, Decimal("0"))
                                              + abs(m.amount))
            print("    excluded as not-spending: "
                  + ", ".join(f"{r} {v} ({sum(1 for m in excluded if m.nature_reason == r)})"
                              for r, v in sorted(by_reason.items(),
                                                 key=lambda x: x[1], reverse=True)))
        prov = proj.provisional_spending()
        if prov:
            print(f"    provisional (weak evidence, could move): {prov}")
        mcat = proj.merchant_categories()
        unknown = proj.uncategorized_merchants()
        print(f"    merchants categorized: {len(mcat)}; unknown merchants "
              f"awaiting: {len(unknown)} ({len(proj.uncategorized_expenses())} txns)")
        sub = proj.spending_by_subcategory()
        if len(sub) > 1:
            top = sorted(sub.items(), key=lambda x: x[1], reverse=True)[:8]
            print("    by subcategory: " + ", ".join(f"{c} {v}" for c, v in top))
    positions = proj.positions()
    if positions:
        print(f"holdings (measured, Slice 6): {len(positions)} position(s)")
        for p in positions:
            ug = p.unrealized_gain()
            print(f"    {p.instrument}: {p.units} units = {p.currency} "
                  f"{p.market_value} as of {p.as_of} [{p.valuation_class}]"
                  + (f"  (unrealized {ug})" if ug is not None else ""))
        for i in infos:
            if i.kind == "investment":
                print(f"    {i.name} total value = {proj.account_value(i.account)} "
                      f"(cash {proj.balance(i.account).amount} + holdings "
                      f"{proj.holdings_value(i.account)})")

    income = proj.income_by_currency()
    if income:
        print("recognized income (gross): "
              + ", ".join(f"{c} {v}" for c, v in income.items()))
    awaiting = [b for b in proj.open_holds() if b.get("reason") == "awaiting_deposit"]
    if awaiting:
        print(f"pay stubs awaiting their deposit: {len(awaiting)}")

    # Documents captured but not posted (parked) — checking-classified or not.
    print(f"coverage: {coverage_summary(proj).text}")

    captured = [(e.body.get('doc_id', '')[:10], e.body.get('doc_type'))
                for e in events if e.event_type == "DocumentCaptured"]
    print("captured documents (id, model's doc_type):")
    for did, dt in captured:
        print(f"    {did}…  {dt}")

    reads = [e for e in events if e.event_type == "ReadRecorded"]
    if reads:
        print("model reads recorded (claims layer):")
        for e in reads:
            b = e.body
            print(f"    {b.get('doc_id','')[:10]}…  model={b.get('model')}  "
                  f"prompt={b.get('prompt_version')}  cost=${b.get('cost_usd',0):.4f}  "
                  f"parse_ok={b.get('parse_ok')}  resp_chars={len(b.get('response_text') or '')}"
                  + (f"  error={b.get('parse_error')}" if not b.get('parse_ok') else ""))


if __name__ == "__main__":
    main()
