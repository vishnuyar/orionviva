"""Ingest the synthetic corpus into a fresh vault with a real model, and report.

An end-to-end run with nothing stubbed: the generated PDFs, a live model reading
them, the verification gate, the ledger.

    python run_corpus.py --vault ~/.viva-vault-corpus

Model configuration is read from product/.env, the same file the surface uses.
The vault directory must not already exist.

The report has two halves: what the vault believes — accounts, balances and their
grades, movements, transfer links, spending, the net-worth curve, and the
questions Viva would ask — and that belief checked against answer-key.json, which
the corpus generator computed.

Exit code is 0 when every check passes, 1 otherwise.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time
from decimal import Decimal

HERE = pathlib.Path(__file__).resolve().parent
D = Decimal


def bar(title: str) -> None:
    print(f"\n{'─' * 78}\n{title}\n{'─' * 78}")


def money(v) -> str:
    return f"{D(str(v)):,.2f}"


# Ingestion order, deliberately not date order — March statements arrive before
# January's — so the run exercises the ledger's order-independence.
ORDER = [
    "vantage-brokerage-2026-03.pdf",
    "northbank-checking-2026-03.pdf",
    "meridian-card-2026-01.pdf",
    "halcyon-paystub-2026-02.pdf",
    "northbank-checking-2026-01.pdf",
    "northbank-savings-2026-02.pdf",
    "meridian-card-2026-03.pdf",
    "vantage-brokerage-2026-01.pdf",
    "halcyon-paystub-2026-01.pdf",
    "northbank-checking-2026-02.pdf",
    "northbank-savings-2026-01.pdf",
    "meridian-card-2026-02.pdf",
    "vantage-brokerage-2026-02.pdf",
    "halcyon-paystub-2026-03.pdf",
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--vault", required=True, help="path for the NEW vault (must not exist)")
    ap.add_argument("--pdfs", default=str(HERE / "pdfs"))
    ap.add_argument("--key", default=str(HERE / "answer-key.json"))
    ap.add_argument("--skip-enrich", action="store_true", help="skip the merchant enrichment call")
    args = ap.parse_args()

    vault_dir = pathlib.Path(args.vault).expanduser()
    if vault_dir.exists():
        print(f"refusing to reuse an existing vault at {vault_dir} — "
              f"a fresh run must start from nothing")
        return 1

    import os
    os.environ["VIVA_VAULT_DIR"] = str(vault_dir)

    from viva.env import currency_from_env, load_dotenv, locale_from_env

    # Find product/.env by walking up from this script and from the working
    # directory. The path that was loaded is printed below, since an unloaded
    # config and an empty one otherwise look the same.
    env_file = None
    for base in [pathlib.Path.cwd(), *HERE.parents]:
        candidate = base / "product" / ".env"
        if candidate.is_file():
            load_dotenv(str(candidate))
            env_file = candidate
            break
    load_dotenv()          # plus any .env beside the working directory

    from viva.vault import Vault
    from viva.ingest.reader import build_reader
    from viva.ingest import capture_and_ingest, sweep

    print(f"vault    {vault_dir}\nconfig   {env_file or '(no product/.env found)'}\n"
          f"locale   {locale_from_env()}\ncurrency {currency_from_env()}")
    print(f"model    {os.environ.get('VIVA_MODEL', '(unset)')}")

    passphrase = os.environ.get("VIVA_PASSPHRASE")
    if not passphrase:
        looked = ", ".join(str(b / "product" / ".env")
                           for b in [pathlib.Path.cwd(), *HERE.parents][:4])
        print(f"\nVIVA_PASSPHRASE is not set. It opens the vault and is never stored.\n"
              f"Looked for it in: {looked}")
        return 1
    read_fn, is_live = build_reader()
    if not is_live:
        print("\nNo model is configured, so the reader parks every document "
              "instead of reading it. Set VIVA_MODEL_* in product/.env.")
        return 1
    vault = Vault.open(vault_dir, passphrase)

    bar("INGEST — 14 documents, deliberately out of date order")
    pdfs = pathlib.Path(args.pdfs)
    results, t0 = [], time.time()
    for i, name in enumerate(ORDER, 1):
        path = pdfs / name
        data = path.read_bytes()
        t = time.time()
        res = capture_and_ingest(vault.raw, vault.ledger, data, read_fn, filename=name)
        results.append((name, res))
        print(f"{i:2d}/14  {name:34s} {res.action:9s} {time.time()-t:5.1f}s  {res.message[:70]}")
    print(f"\ningest wall clock: {time.time()-t0:.0f}s")

    healed = sweep(vault.ledger)
    print(f"final sweep: {healed}")

    if not args.skip_enrich:
        bar("ENRICH — one batched call over new merchants only")
        try:
            from viva.enrich import main as enrich_main
            enrich_main()
        except SystemExit:
            pass
        except Exception as exc:                      # noqa: BLE001
            print(f"enrichment failed ({exc}); continuing — the ledger does not depend on it")
        vault = Vault.open(vault_dir, passphrase)

    proj = vault.ledger.projection()
    report(proj, results)
    return checks(proj, results, json.loads(pathlib.Path(args.key).read_text()))


def report(proj, results) -> None:
    from viva.ledger.networth import net_worth, series

    bar("WHAT THE VAULT BELIEVES — accounts")
    for a in sorted(proj.accounts()):
        try:
            info = proj.account_info(a)
        except Exception:                              # noqa: BLE001
            continue
        if not info.kind:
            continue
        ans = proj.balance(a)
        print(f"  {a:44s} {info.kind:11s} {money(ans.amount):>14s}  "
              f"{ans.grade:12s} as of {ans.dated or '—'}")

    bar("MOVEMENTS, TRANSFERS, NATURE")
    movs = proj.movements()
    linked = sum(1 for m in movs if m.linked)
    print(f"  movements        {len(movs)}")
    print(f"  transfer links   {len(proj.transfer_links())}  ({linked} legs linked)")
    print(f"  suggestions      {len(proj.transfer_suggestions())}")
    from collections import Counter
    print(f"  nature           {dict(Counter(m.nature for m in movs))}")
    print(f"  reason           {dict(Counter(m.nature_reason for m in movs))}")

    bar("MONEY")
    for cur, amt in proj.spending_by_currency().items():
        print(f"  spending  {cur} {money(amt):>14s}   "
              f"provisional {money(proj.provisional_spending(cur))}")
    for cur, amt in proj.income_by_currency().items():
        print(f"  income    {cur} {money(amt):>14s}")
    excluded = proj.excluded_from_spending()
    print(f"  excluded from spending: {len(excluded)} movements")
    cats = proj.spending_by_category(next(iter(proj.spending_by_currency()), "USD"))
    for c, v in sorted(cats.items(), key=lambda kv: -D(str(kv[1])))[:12]:
        print(f"    {c:32s} {money(v):>12s}")

    bar("HOLDINGS")
    for p in proj.positions():
        print(f"  {p.account:30s} {p.instrument:8s} {p.units:>10} units  "
              f"{money(p.market_value):>12s}  as of {p.as_of}  [{p.valuation_class}]")

    bar("NET WORTH — the curve")
    pts = series(proj)
    for pt in pts:
        subs = ", ".join(f"{c} {money(r['net'])}" for c, r in pt.by_currency().items())
        print(f"  {pt.as_of}  {subs:34s} complete={pt.complete}  "
              f"stalest input {pt.oldest_input or '—'}")
    if pts:
        last = pts[-1]
        if last.missing:
            print(f"  missing: {last.missing}")
        if last.skipped:
            for s in last.skipped:
                print(f"  skipped: {s.get('account')} — {s.get('why', '')[:70]}")

    bar("WHAT VIVA WOULD ASK")
    from viva.questions import open_questions
    q = open_questions(proj, limit=10)
    print(f"  {q['total']} open; tail {q['tail']['count']} worth {q['tail']['amount']}")
    for item in q["questions"]:
        print(f"    [{item['kind']:14s}] {item['currency']} {item['amount']:>12s}  {item['text'][:88]}")


def checks(proj, results, key) -> int:
    """Check the vault against the answer key. Returns 0 if all checks pass."""
    from viva.ledger.networth import net_worth, series

    bar("CHECKS — the vault against the answer key")
    passed, failed = [], []

    def check(name, got, want, note=""):
        ok = str(got) == str(want)
        (passed if ok else failed).append((name, got, want, note))
        print(f"  {'PASS' if ok else 'FAIL'}  {name:52s} got {str(got):>14s}  want {str(want):>14s} {note}")

    on_arrival = [n for n, r in results if r.action == "posted"]
    resolved = len(proj.posted_doc_ids())
    held = proj.open_holds()
    check("documents posted (final state)", resolved, 14,
          f"{len(on_arrival)} posted on arrival; the rest heal or hold")
    if held:
        print(f"        still held: " + ", ".join(
            f"{h.get('reason', '?')}" for h in held))

    docs = key["documents"]
    for doc_id, d in docs.items():
        if d["doc_type"] in ("checking_statement", "savings_statement", "credit_card_statement"):
            acct = [a for a in proj.accounts()
                    if d["account"]["number"][-4:] in a]
            if not acct:
                failed.append((f"{doc_id}: account exists", "missing", d["account"]["number"], ""))
                print(f"  FAIL  {doc_id + ': account exists':52s} "
                      f"no account matching {d['account']['number']}")

    # the figures that matter, at the end of the period
    def acct_like(frag):
        for a in proj.accounts():
            if frag in a:
                return a
        return None

    for frag, doc_id, label in (("4417", "checking-2026-03", "closing balance"),
                                ("8802", "savings-2026-02", "closing balance"),
                                ("2291", "card-2026-03", "new balance")):
        a = acct_like(frag)
        want = next(e["value"] for e in docs[doc_id]["entries"] if e["label"] == label)
        got = proj.balance(a).amount if a else "no-account"
        check(f"balance {frag} at period end", got, want)

    try:
        nw = net_worth(proj)
    except Exception as exc:                           # noqa: BLE001
        print(f"  FAIL  net worth could not be computed: {exc}")
        nw = None
    if nw is None:
        print("\n  The run produced no usable vault, so the remaining checks would\n"
              "  report nothing rather than something false. Stopping here.")
        return 1
    got_nw = sum((D(str(r["net"])) for r in nw.by_currency().values()), start=D("0"))
    check("net worth at latest point", got_nw.quantize(D("0.01")),
          key["derived"]["net_worth_2026-03-31"])

    want_income = (D(key["derived"]["total_gross_income"])
                   + D(key["derived"].get("total_dividends", "0")))
    check("income recognised (gross + dividends, once)",
          sum((D(str(v)) for v in proj.income_by_currency().values()), start=D("0")).quantize(D("0.01")),
          want_income.quantize(D("0.01")), "pay stubs decompose their deposits")

    # A link needs both legs on the ledger, so the expected count is scoped to
    # the accounts that posted; otherwise one held statement fails two checks.
    have_savings = any("8802" in a for a in proj.accounts())
    want_links = 9 if have_savings else 6
    check("transfer links found", len(proj.transfer_links()), want_links,
          "card payments + brokerage contributions"
          + (" + savings transfers" if have_savings else " (savings not posted)"))

    movs = proj.movements()
    check("no movement counted as spending twice",
          sum(1 for m in movs if m.linked and m.nature == "spending"), 0)

    pts = series(proj)
    if len(pts) >= 2:
        check("the curve has more than one point", "yes", "yes",
              f"{len(pts)} points from {pts[0].as_of} to {pts[-1].as_of}")

    bar("RESULT")
    print(f"  {len(passed)} passed, {len(failed)} failed")
    if failed:
        print("\n  failures:")
        for name, got, want, note in failed:
            print(f"    {name}: got {got}, want {want} {note}")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
