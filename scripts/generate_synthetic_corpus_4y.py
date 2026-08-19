"""Generate a 4-year synthetic statement corpus from the merchant catalog.

This reuses the existing PDF builders so the output stays visually consistent
with the legacy synthetic statements, but scales the corpus across 48 months
and multiple account families:

- monthly checking
- quarterly savings
- quarterly brokerage
- monthly Harborline card
- monthly Meridian card

The intent is to mirror the backend statement shapes and merchant vocabulary
already present in the repo, while remaining deterministic and local.
"""

from __future__ import annotations

import argparse
import calendar
import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
import sys
from typing import Iterable

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.generate_synthetic_statements import (
    StatementSpec,
    add_holdings_page,
    build_statement_pdf,
    build_styles,
    merchant_name,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "output" / "pdf" / "synthetic_statements_4y"
CATALOG = Path("/Users/vishnu/Downloads/catalog.json")
TWOPLACES = Decimal("0.01")


def _catalog_merchant(catalog: dict[str, dict], *keys: str) -> str:
    for key in keys:
        if key in catalog:
            return merchant_name(catalog, key)
    raise KeyError(f"none of the catalog keys were found: {keys!r}")


def _money(value: Decimal) -> str:
    return f"${value.quantize(TWOPLACES):,.2f}"


def _amount(value: Decimal) -> str:
    value = value.quantize(TWOPLACES)
    sign = "+" if value >= 0 else "-"
    return f"{sign}{abs(value):,.2f}"


def _month_start(year: int, month: int) -> date:
    return date(year, month, 1)


def _add_months(d: date, months: int) -> date:
    year = d.year + ((d.month - 1 + months) // 12)
    month = ((d.month - 1 + months) % 12) + 1
    return date(year, month, 1)


def _month_end(d: date) -> date:
    return date(d.year, d.month, calendar.monthrange(d.year, d.month)[1])


def _period(start: date, months: int = 1) -> tuple[str, date, date]:
    end_start = _add_months(start, months)
    end = end_start - date.resolution
    return f"{start.isoformat()} - {end.isoformat()}", start, end


def _txn(day: date, merchant: str, amount: Decimal, note: str) -> tuple[str, str, str, str]:
    return day.isoformat(), merchant, _amount(amount), note


def _txns_total(txns: Iterable[tuple[str, str, str, str]]) -> Decimal:
    total = Decimal("0")
    for _, _, amount, _ in txns:
        total += Decimal(amount.replace(",", ""))
    return total.quantize(TWOPLACES)


def _manifest(specs: list[StatementSpec], start: date, end: date) -> dict:
    return {
        "generated_at": "2026-08-17",
        "source_catalog": str(CATALOG),
        "purpose": "four-year synthetic statement corpus for local UI and document-processing tests",
        "range": {"from": start.isoformat(), "to": end.isoformat()},
        "documents": [
            {
                "file": spec.file_name,
                "type": spec.kind,
                "family": spec.family,
                "institution": spec.institution,
                "account": spec.account,
                "period": spec.period.replace(" - ", " to "),
                "page_count": 2 if spec.holdings else 1,
                "merchants": spec.merchants or [],
            }
            for spec in specs
        ],
    }


def build_four_year_specs(
    catalog: dict[str, dict],
    years: int = 4,
    start_year: int = 2022,
    start_month: int = 8,
) -> list[StatementSpec]:
    start = _month_start(start_year, start_month)
    months = years * 12
    specs: list[StatementSpec] = []

    checking_balance = Decimal("8420.18")
    chase_balance = Decimal("1842.77")
    meridian_balance = Decimal("620.14")
    savings_balance = Decimal("40000.00")
    brokerage_total = Decimal("68420.44")

    checking_merchants = [
        ("saffron grocers", "Groceries"),
        ("wal mart", "Household"),
        ("riverbend market", "Online shopping"),
        ("starbucks store", "Coffee"),
        ("racetrac", "Fuel"),
        ("panera bread", "Lunch"),
        ("cityhop ride", "Ride"),
        ("walgreens", "Pharmacy"),
        ("kohl s", "Clothing"),
        ("the ups store", "Shipping"),
        ("lowes", "Home project"),
        ("five below", "Household"),
        ("buc ee s", "Travel stop"),
        ("legacy hall plano", "Dining"),
        ("swadeshi plaza frisco", "Groceries"),
        ("chevron", "Fuel"),
    ]
    chase_merchants = [
        ("saffron grocers", "Groceries"),
        ("riverbend market", "Online order"),
        ("voltway charging", "Charging"),
        ("starbucks store", "Coffee"),
        ("cityhop ride", "Ride share"),
        ("burger king", "Dinner"),
        ("lowes", "Home project"),
        ("jcpenney", "Household"),
        ("the donut tree", "Breakfast"),
        ("panera bread", "Lunch"),
        ("kohl s", "Shopping"),
        ("walgreens", "Pharmacy"),
    ]
    meridian_merchants = [
        ("lunchline", "School meals"),
        ("brightpath tutoring", "Tutoring"),
        ("choice home warranty", "Warranty"),
        ("clearwave", "Internet"),
        ("elmwood dental", "Dental"),
        ("whoop", "Subscription"),
        ("ross stores", "Clothing"),
        ("jcpenney", "Household"),
        ("taco bell", "Dinner"),
        ("7 eleven", "Snacks"),
        ("lowes", "Home project"),
        ("walgreens", "Pharmacy"),
    ]

    for idx in range(months):
        month = _add_months(start, idx)
        month_end = _month_end(month)
        period, _, period_end = _period(month, 1)

        payroll = Decimal("4550") + Decimal((idx % 6) * 65) + Decimal((idx // 12) * 45)
        mortgage = Decimal("1720") + Decimal((idx % 4) * 10)
        chase_pay = Decimal("920") + Decimal((idx % 5) * 12)
        meridian_pay = Decimal("690") + Decimal((idx % 3) * 18)
        savings_xfer = Decimal("320") + Decimal((idx % 3) * 25)
        brokerage_xfer = Decimal("180") if idx % 3 == 2 else Decimal("0")
        spend = [
            Decimal("78") + Decimal((idx % 4) * 11),
            Decimal("56") + Decimal((idx % 5) * 9),
            Decimal("42") + Decimal((idx % 3) * 7),
            Decimal("29") + Decimal((idx % 6) * 4),
        ]

        checking_txns = [
            _txn(period_end, "Payroll Deposit", payroll, "Employer payroll credit"),
            _txn(date(month_end.year, month_end.month, 26),
                 _catalog_merchant(catalog, "ridgeline svcg ach"),
                 -mortgage, "Mortgage payment"),
            _txn(date(month_end.year, month_end.month, 22),
                 _catalog_merchant(catalog, "payment to harborline card ending in"),
                 -chase_pay, "Card payment"),
            _txn(date(month_end.year, month_end.month, 21),
                 _catalog_merchant(catalog, "meridian card online"),
                 -meridian_pay, "Card payment"),
            _txn(date(month_end.year, month_end.month, 14),
                 _catalog_merchant(catalog, "online transfer to keystone transaction"),
                 -savings_xfer, "Transfer to savings"),
        ]
        if brokerage_xfer:
            checking_txns.append(
                _txn(date(month_end.year, month_end.month, 8),
                     _catalog_merchant(catalog, "fid bkg svc llc"),
                     -brokerage_xfer, "Brokerage contribution")
            )
        merchant_start = idx % len(checking_merchants)
        monthly_checking = [
            checking_merchants[(merchant_start + j) % len(checking_merchants)]
            for j in range(4)
        ]
        for j, (key, note) in enumerate(monthly_checking):
            day = date(month_end.year, month_end.month, 5 + j * 4)
            checking_txns.append(
                _txn(day, _catalog_merchant(catalog, key),
                     -(spend[j] + Decimal((idx % 5) * 2.5)), note)
            )
        checking_txns.sort(key=lambda row: row[0])
        checking_closing = (checking_balance + _txns_total(checking_txns)).quantize(TWOPLACES)
        specs.append(StatementSpec(
            file_name=f"silverline-checking-{month.strftime('%Y-%m')}.pdf",
            kind="bank_statement",
            family="checking-monthly",
            institution="Silverline Bank",
            account="Everyday Checking",
            statement_title="Checking Account Statement",
            period=period,
            opening=_money(checking_balance),
            closing=_money(checking_closing),
            transactions=checking_txns,
            notes=[
                "Payroll, mortgage, card payments, and household spend repeat across the four-year span.",
                "This series is designed to exercise cross-document references to card and savings statements.",
            ],
            merchants=["Ridgeline Servicing", "Harborline", "Meridian", "Saffron Grocers", "Valuemart", "Riverbend Market", "Voltway Charging", "Cityhop Ride"],
        ))
        checking_balance = checking_closing

        chase_txns = [
            _txn(period_end.replace(day=5),
                 _catalog_merchant(catalog, chase_merchants[(idx + 1) % len(chase_merchants)][0]),
                 Decimal("88") + Decimal((idx % 4) * 6),
                 chase_merchants[(idx + 1) % len(chase_merchants)][1]),
            _txn(period_end.replace(day=9),
                 _catalog_merchant(catalog, chase_merchants[(idx + 3) % len(chase_merchants)][0]),
                 Decimal("64") + Decimal((idx % 5) * 7),
                 chase_merchants[(idx + 3) % len(chase_merchants)][1]),
            _txn(period_end.replace(day=13),
                 _catalog_merchant(catalog, chase_merchants[(idx + 5) % len(chase_merchants)][0]),
                 Decimal("42") + Decimal((idx % 3) * 5),
                 chase_merchants[(idx + 5) % len(chase_merchants)][1]),
            _txn(period_end.replace(day=17),
                 _catalog_merchant(catalog, chase_merchants[(idx + 7) % len(chase_merchants)][0]),
                 Decimal("28") + Decimal((idx % 6) * 4),
                 chase_merchants[(idx + 7) % len(chase_merchants)][1]),
            _txn(period_end.replace(day=23),
                 _catalog_merchant(catalog, "payment to harborline card ending in"),
                 -(Decimal("900") + Decimal((idx % 5) * 15)),
                 "Payment from checking"),
        ]
        chase_closing = (chase_balance + _txns_total(chase_txns)).quantize(TWOPLACES)
        specs.append(StatementSpec(
            file_name=f"harborline-card-{month.strftime('%Y-%m')}.pdf",
            kind="credit_card_statement",
            family="harborline-card-monthly",
            institution="Harborline",
            account="Harborline Signature",
            statement_title="Credit Card Statement",
            period=period,
            opening=_money(chase_balance),
            closing=_money(chase_closing),
            transactions=chase_txns,
            notes=[
                "Charges and a matching payment are carried forward month to month.",
                "These statements intentionally reuse the same merchants as the checking series.",
            ],
            merchants=["Harborline", "Saffron Grocers", "Riverbend Market", "Voltway Charging", "Cityhop Ride"],
        ))
        chase_balance = chase_closing

        meridian_txns = [
            _txn(period_end.replace(day=4),
                 _catalog_merchant(catalog, meridian_merchants[(idx + 1) % len(meridian_merchants)][0]),
                 Decimal("168") + Decimal((idx % 4) * 10),
                 meridian_merchants[(idx + 1) % len(meridian_merchants)][1]),
            _txn(period_end.replace(day=8),
                 _catalog_merchant(catalog, meridian_merchants[(idx + 3) % len(meridian_merchants)][0]),
                 Decimal("94") + Decimal((idx % 5) * 8),
                 meridian_merchants[(idx + 3) % len(meridian_merchants)][1]),
            _txn(period_end.replace(day=15),
                 _catalog_merchant(catalog, meridian_merchants[(idx + 5) % len(meridian_merchants)][0]),
                 Decimal("54") + Decimal((idx % 6) * 5),
                 meridian_merchants[(idx + 5) % len(meridian_merchants)][1]),
            _txn(period_end.replace(day=20),
                 _catalog_merchant(catalog, meridian_merchants[(idx + 7) % len(meridian_merchants)][0]),
                 Decimal("32") + Decimal((idx % 4) * 4),
                 meridian_merchants[(idx + 7) % len(meridian_merchants)][1]),
            _txn(period_end.replace(day=24),
                 _catalog_merchant(catalog, "meridian card online"),
                 -(Decimal("650") + Decimal((idx % 4) * 20)),
                 "Payment from checking"),
        ]
        meridian_closing = (meridian_balance + _txns_total(meridian_txns)).quantize(TWOPLACES)
        specs.append(StatementSpec(
            file_name=f"meridian-card-{month.strftime('%Y-%m')}.pdf",
            kind="credit_card_statement",
            family="meridian-card-monthly",
            institution="Meridian",
            account="Meridian Everyday",
            statement_title="Credit Card Statement",
            period=period,
            opening=_money(meridian_balance),
            closing=_money(meridian_closing),
            transactions=meridian_txns,
            notes=[
                "Monthly household, school, and subscription spend with a single payment line.",
                "The merchant vocabulary is drawn from the repository's catalog seed.",
            ],
            merchants=["Meridian", "Lunchline", "Brightpath", "Clearwave", "Elmwood Dental"],
        ))
        meridian_balance = meridian_closing

        if (idx + 1) % 3 == 0:
            q_start = _add_months(start, idx - 2)
            q_period, _, q_end = _period(q_start, 3)
            q_index = (idx + 1) // 3 - 1

            savings_txns = [
                _txn(q_end.replace(day=3),
                     _catalog_merchant(catalog, "online transfer to keystone transaction"),
                     Decimal("2500") + Decimal(q_index * 35),
                     "Transfer from checking"),
                _txn(q_end.replace(day=15), "Interest",
                     Decimal("12.11") + Decimal(q_index % 5) * Decimal("0.83"),
                     "Quarterly interest credit"),
            ]
            if q_index % 4 == 3:
                savings_txns.append(
                    _txn(q_end.replace(day=27),
                         _catalog_merchant(catalog, "redemption credit"),
                         Decimal("-1500"),
                         "Scheduled sweep to brokerage"),
                )
            savings_closing = (savings_balance + _txns_total(savings_txns)).quantize(TWOPLACES)
            specs.append(StatementSpec(
                file_name=f"north-river-savings-{q_start.strftime('%Y-%m')}-to-{q_end.strftime('%Y-%m')}.pdf",
                kind="bank_statement",
                family="savings-quarterly",
                institution="Silverline Bank",
                account="North River Savings",
                statement_title="Savings Account Statement",
                period=q_period,
                opening=_money(savings_balance),
                closing=_money(savings_closing),
                transactions=savings_txns,
                notes=[
                    "Quarterly sweep and interest activity drawn from the merchant catalog vocabulary.",
                    "This account is intentionally quiet aside from recurring transfers and interest.",
                ],
                merchants=["Interest", "Transfer from checking", "Redemption Credit"],
            ))
            savings_balance = savings_closing

            brokerage_contribution = Decimal("3200") + Decimal(q_index * 75)
            brokerage_dividend = Decimal("96.45") + Decimal((q_index % 4) * 8.20)
            brokerage_withdrawal = Decimal("300") if q_index % 3 == 1 else Decimal("0")
            brokerage_gain = Decimal("1400") + Decimal(q_index * 42)
            brokerage_closing = (
                brokerage_total + brokerage_contribution + brokerage_dividend +
                brokerage_gain - brokerage_withdrawal
            ).quantize(TWOPLACES)
            holdings_cash = (Decimal("22500") + Decimal(q_index * 110) + brokerage_contribution / Decimal("4")).quantize(TWOPLACES)
            total_holdings = (brokerage_closing - holdings_cash).quantize(TWOPLACES)
            vti = (total_holdings * Decimal("0.56")).quantize(TWOPLACES)
            aapl = (total_holdings * Decimal("0.24")).quantize(TWOPLACES)
            vxus = (total_holdings - vti - aapl).quantize(TWOPLACES)
            brokerage_txns = [
                _txn(q_end.replace(day=4),
                     _catalog_merchant(catalog, "fid bkg svc llc"),
                     brokerage_contribution,
                     "Quarterly contribution"),
                _txn(q_end.replace(day=14), "Dividend",
                     brokerage_dividend,
                     "Qualified dividend reinvested"),
                _txn(q_end.replace(day=28), "Market movement",
                     brokerage_gain,
                     "Unrealized appreciation"),
            ]
            if brokerage_withdrawal:
                brokerage_txns.insert(
                    2,
                    _txn(q_end.replace(day=22),
                         _catalog_merchant(catalog, "cashlink"),
                         -brokerage_withdrawal,
                         "Transfer to checking"),
                )
            specs.append(StatementSpec(
                file_name=f"northgate-brokerage-{q_start.strftime('%Y-%m')}-to-{q_end.strftime('%Y-%m')}.pdf",
                kind="brokerage_statement",
                family="brokerage-quarterly",
                institution="Northgate Investments",
                account="Taxable Brokerage",
                statement_title="Brokerage Statement",
                period=q_period,
                opening=_money(brokerage_total),
                closing=_money(brokerage_closing),
                transactions=brokerage_txns,
                notes=[
                    "Holdings appear on a second page to exercise multi-page document handling.",
                    "Quarterly contributions and market movement are mirrored across the corpus.",
                ],
                holdings=[
                    ["Security", "Shares", "Price", "Market Value"],
                    ["GBLX", f"{Decimal('120') + Decimal(q_index) * Decimal('1.125'):.3f}", f"${Decimal('210.12') + Decimal(q_index) * Decimal('2.14'):.2f}", f"${vti:,.2f}"],
                    ["AAPL", f"{Decimal('48') + Decimal(q_index) * Decimal('0.75'):.3f}", f"${Decimal('198.44') + Decimal(q_index) * Decimal('1.83'):.2f}", f"${aapl:,.2f}"],
                    ["VXUS", f"{Decimal('95') + Decimal(q_index) * Decimal('0.5'):.3f}", f"${Decimal('57.28') + Decimal(q_index) * Decimal('0.58'):.2f}", f"${vxus:,.2f}"],
                    ["Cash", "-", "-", f"${holdings_cash:,.2f}"],
                ],
                merchants=["Northgate Brokerage Services", "Cashlink", "Dividend"],
            ))
            brokerage_total = brokerage_closing

    return specs


def main(out_dir: Path = DEFAULT_OUT, years: int = 4, start_year: int = 2022, start_month: int = 8) -> None:
    if not CATALOG.exists():
        raise FileNotFoundError(f"merchant catalog not found: {CATALOG}")
    catalog = json.loads(CATALOG.read_text())["records"]
    out_dir.mkdir(parents=True, exist_ok=True)
    for path in out_dir.glob("*.pdf"):
        path.unlink()
    manifest = out_dir / "manifest.json"
    manifest.unlink(missing_ok=True)
    styles = build_styles()
    specs = build_four_year_specs(catalog, years=years, start_year=start_year, start_month=start_month)
    for spec in specs:
        pdf = out_dir / spec.file_name
        build_statement_pdf(pdf, spec, styles)
        if spec.holdings:
            add_holdings_page(pdf, spec.holdings)
    start = _month_start(start_year, start_month)
    end = _add_months(start, years * 12) - date.resolution
    manifest.write_text(json.dumps(_manifest(specs, start, end), indent=2) + "\n")
    print(f"generated {len(specs)} pdfs and manifest in {out_dir}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate a four-year synthetic statement corpus.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--years", type=int, default=4)
    parser.add_argument("--start-year", type=int, default=2022)
    parser.add_argument("--start-month", type=int, default=8)
    args = parser.parse_args()
    main(
        out_dir=args.output,
        years=args.years,
        start_year=args.start_year,
        start_month=args.start_month,
    )
