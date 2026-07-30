"""Generate a synthetic three-month financial life as PDF statements.

The documents are one connected set: a card payment leaves the checking account
and arrives on the card, a pay stub's net equals the payroll deposit, a brokerage
contribution leaves checking and lands as cash. Those cross-document facts are
what an end-to-end run has to recognise.

Every arithmetic identity is computed in `build_life` and checked by
`assert_identities` before any page is rendered, so a document that does not
reconcile never reaches the corpus.

Every institution, person, address and amount here is invented.

Output: a PDF per document, plus answer-key.json carrying every true figure in
raw-as-printed form alongside its normalized value, currency and locale.
"""

from __future__ import annotations

import json
import pathlib
from dataclasses import dataclass, field
from decimal import Decimal

from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas

D = Decimal
OUT = pathlib.Path(__file__).resolve().parent / "pdfs"
LOCALE, CURRENCY = "en-US", "USD"

HOLDER = "ROWAN E VANCE"
ADDRESS = ["1400 ASTER ROW APT 3B", "CEDAR PARK TX 78613"]


def money(d: Decimal) -> str:
    """Printed form: thousands separated, two decimals, minus sign if negative."""
    neg = d < 0
    s = f"{abs(d):,.2f}"
    return f"-{s}" if neg else s


# --------------------------------------------------------------- the life

@dataclass
class Txn:
    date: str
    description: str
    delta: Decimal          # signed effect on the printed balance


@dataclass
class Doc:
    doc_id: str
    kind: str
    filename: str
    facts: dict = field(default_factory=dict)


CHECKING = {"institution": "Northbank", "name": "Everyday Checking", "number": "••••4417"}
SAVINGS = {"institution": "Northbank", "name": "High-Yield Savings", "number": "••••8802"}
CARD = {"institution": "Meridian", "name": "Signature Card", "number": "••••2291"}
BROKER = {"institution": "Vantage", "name": "Brokerage Individual", "number": "••••7734"}
EMPLOYER = "Halcyon Systems Inc."

CHECKING_OPEN = D("4182.66")
SAVINGS_OPEN = D("12400.00")
CARD_OPEN = D("1204.55")

# Pay is monthly, on the last business day. The three nets differ, so each
# payroll deposit matches exactly one stub.
PAY = [
    {"period": ("2026-01-01", "2026-01-31"), "pay_date": "2026-01-30", "gross": D("9850.00"),
     "deductions": [("Federal Income Tax", "tax", D("1772.00")), ("Social Security", "tax", D("610.70")),
                    ("Medicare", "tax", D("142.83")), ("401(k) Pre-Tax", "retirement", D("788.00")),
                    ("Medical PPO", "insurance", D("214.50")), ("Dental", "insurance", D("28.40"))]},
    {"period": ("2026-02-01", "2026-02-28"), "pay_date": "2026-02-27", "gross": D("9850.00"),
     "deductions": [("Federal Income Tax", "tax", D("1772.00")), ("Social Security", "tax", D("610.70")),
                    ("Medicare", "tax", D("142.83")), ("401(k) Pre-Tax", "retirement", D("788.00")),
                    ("Medical PPO", "insurance", D("214.50")), ("Dental", "insurance", D("28.40")),
                    ("Commuter Parking", "other", D("45.00"))]},
    {"period": ("2026-03-01", "2026-03-31"), "pay_date": "2026-03-31", "gross": D("10350.00"),
     "deductions": [("Federal Income Tax", "tax", D("1886.00")), ("Social Security", "tax", D("641.70")),
                    ("Medicare", "tax", D("150.08")), ("401(k) Pre-Tax", "retirement", D("828.00")),
                    ("Medical PPO", "insurance", D("214.50")), ("Dental", "insurance", D("28.40"))]},
]
for p in PAY:
    p["net"] = p["gross"] - sum(d[2] for d in p["deductions"])

CARD_PAYMENTS = {  # (checking date, card posting date, amount) — one movement on two statements
    1: ("2026-01-15", "2026-01-15", CARD_OPEN),
    2: ("2026-02-16", "2026-02-16", None),   # filled once January's closing is known
    3: ("2026-03-16", "2026-03-16", None),
}

CARD_CHARGES = {
    1: [("2026-01-03", "GOLDEN FORK BISTRO CEDAR PARK TX", D("78.40")),
        ("2026-01-08", "ARBOR HOME SUPPLY #14 AUSTIN TX", D("215.66")),
        ("2026-01-11", "SAFEHARBOR MARKET #221 CEDAR PARK TX", D("88.90")),
        ("2026-01-14", "CEDAR PARK PARKING AUTH", D("12.00")),
        ("2026-01-17", "VECTOR FUEL #88 LEANDER TX", D("46.75")),
        ("2026-01-21", "NORTHSTAR AIRLINES 0192244178", D("412.30")),
        ("2026-01-24", "BRIGHT LEAF COFFEE CEDAR PARK TX", D("9.50")),
        ("2026-01-27", "PINEGROVE PHARMACY #7 CEDAR PARK", D("22.15"))],
    2: [("2026-02-02", "SAFEHARBOR MARKET #221 CEDAR PARK TX", D("134.08")),
        ("2026-02-06", "GOLDEN FORK BISTRO CEDAR PARK TX", D("52.75")),
        ("2026-02-09", "VECTOR FUEL #88 LEANDER TX", D("49.20")),
        ("2026-02-13", "ORCHID FLORAL AUSTIN TX", D("86.00")),
        ("2026-02-18", "ARBOR HOME SUPPLY #14 AUSTIN TX", D("41.99")),
        ("2026-02-23", "BRIGHT LEAF COFFEE CEDAR PARK TX", D("11.25")),
        ("2026-02-25", "SAFEHARBOR MARKET #221 CEDAR PARK TX", D("102.66"))],
    3: [("2026-03-04", "GOLDEN FORK BISTRO CEDAR PARK TX", D("64.10")),
        ("2026-03-07", "SAFEHARBOR MARKET #221 CEDAR PARK TX", D("119.42")),
        ("2026-03-10", "VECTOR FUEL #88 LEANDER TX", D("51.85")),
        ("2026-03-15", "ARBOR HOME SUPPLY #14 AUSTIN TX", D("308.77")),
        ("2026-03-19", "BRIGHT LEAF COFFEE CEDAR PARK TX", D("8.75")),
        ("2026-03-22", "PINEGROVE PHARMACY #7 CEDAR PARK", D("46.30")),
        ("2026-03-28", "STREAMLINE MEDIA ANNUAL RENEWAL", D("129.00"))],
}

# Everything on checking except the payroll deposit, the card payment and the
# brokerage contribution, which are generated from the documents they tie to.
CHECKING_OTHER = {
    1: [("2026-01-05", "SAFEHARBOR MARKET #221 CEDAR PARK TX", D("-142.83")),
        ("2026-01-07", "BRIGHT LEAF COFFEE CEDAR PARK TX", D("-6.75")),
        ("2026-01-09", "LUMEN ENERGY UTILITY PMT AUTOPAY", D("-128.40")),
        ("2026-01-12", "TRANSFER TO NORTHBANK SAVINGS 8802", D("-500.00")),
        ("2026-01-16", "STREAMLINE MEDIA MONTHLY", D("-17.99")),
        ("2026-01-20", "SAFEHARBOR MARKET #221 CEDAR PARK TX", D("-96.12")),
        ("2026-01-22", "PINEGROVE PHARMACY #7 CEDAR PARK", D("-34.20")),
        ("2026-01-26", "VECTOR FUEL #88 LEANDER TX", D("-52.10"))],
    2: [("2026-02-04", "SAFEHARBOR MARKET #221 CEDAR PARK TX", D("-118.44")),
        ("2026-02-06", "LUMEN ENERGY UTILITY PMT AUTOPAY", D("-141.07")),
        ("2026-02-10", "CEDAR PARK WATER UTILITY", D("-63.18")),
        ("2026-02-12", "TRANSFER TO NORTHBANK SAVINGS 8802", D("-500.00")),
        ("2026-02-16", "STREAMLINE MEDIA MONTHLY", D("-17.99")),
        ("2026-02-19", "BRIGHT LEAF COFFEE CEDAR PARK TX", D("-7.40")),
        ("2026-02-24", "SAFEHARBOR MARKET #221 CEDAR PARK TX", D("-88.31"))],
    3: [("2026-03-03", "LUMEN ENERGY UTILITY PMT AUTOPAY", D("-135.62")),
        ("2026-03-05", "SAFEHARBOR MARKET #221 CEDAR PARK TX", D("-127.90")),
        ("2026-03-11", "CEDAR PARK WATER UTILITY", D("-58.44")),
        ("2026-03-12", "TRANSFER TO NORTHBANK SAVINGS 8802", D("-500.00")),
        ("2026-03-16", "STREAMLINE MEDIA MONTHLY", D("-17.99")),
        ("2026-03-20", "VECTOR FUEL #88 LEANDER TX", D("-55.30")),
        ("2026-03-25", "SAFEHARBOR MARKET #221 CEDAR PARK TX", D("-104.77")),
        ("2026-03-27", "ATM WITHDRAWAL 1400 ASTER ROW", D("-200.00"))],
}

BROKERAGE_CONTRIB = {1: D("1000.00"), 2: D("1000.00"), 3: D("1500.00")}

INSTRUMENTS = [
    ("VTI", "VANGUARD TOTAL STOCK MKT ETF"),
    ("VXUS", "VANGUARD TOTAL INTL STOCK ETF"),
    ("BND", "VANGUARD TOTAL BOND MKT ETF"),
]
PRICES = {1: {"VTI": D("268.40"), "VXUS": D("64.85"), "BND": D("72.60")},
          2: {"VTI": D("272.15"), "VXUS": D("65.90"), "BND": D("72.05")},
          3: {"VTI": D("259.80"), "VXUS": D("67.40"), "BND": D("73.15")}}
UNITS_OPEN = {"VTI": D("42.000"), "VXUS": D("61.000"), "BND": D("55.000")}
BUYS = {1: [("VTI", D("3.000"))], 2: [("VXUS", D("12.000"))], 3: [("VTI", D("4.000")), ("BND", D("6.000"))]}
DIVIDENDS = {1: D("34.12"), 2: D("0.00"), 3: D("118.46")}
FEES = {1: D("5.00"), 2: D("5.00"), 3: D("5.00")}
BROKER_CASH_OPEN = D("1240.18")

SAVINGS_INTEREST = {1: D("41.33"), 2: D("39.87")}

MONTH_NAME = {1: "January", 2: "February", 3: "March"}
LAST_DAY = {1: "2026-01-31", 2: "2026-02-28", 3: "2026-03-31"}
FIRST_DAY = {1: "2026-01-01", 2: "2026-02-01", 3: "2026-03-01"}


def build_life() -> dict:
    """Compute every balance so that each printed identity holds exactly."""
    life = {"checking": {}, "card": {}, "savings": {}, "brokerage": {}, "pay": PAY}

    # --- card first: its closing balance decides next month's payment
    card_prev = CARD_OPEN
    for m in (1, 2, 3):
        pay_amt = CARD_PAYMENTS[m][2] if CARD_PAYMENTS[m][2] is not None else card_prev
        CARD_PAYMENTS[m] = (CARD_PAYMENTS[m][0], CARD_PAYMENTS[m][1], pay_amt)
        charges = CARD_CHARGES[m]
        closing = card_prev + sum(c[2] for c in charges) - pay_amt
        life["card"][m] = {"opening": card_prev, "closing": closing,
                           "charges": charges, "payment": (CARD_PAYMENTS[m][1], pay_amt)}
        card_prev = closing

    # --- checking: other activity + card payment + brokerage contribution + payroll
    bal = CHECKING_OPEN
    for m in (1, 2, 3):
        txns = list(CHECKING_OTHER[m])
        cd, _, amt = CARD_PAYMENTS[m]
        txns.append((cd, f"PAYMENT TO MERIDIAN CARD 2291", -amt))
        txns.append((f"2026-{m:02d}-28" if m != 2 else "2026-02-25",
                     "CONTRIBUTION TO VANTAGE BROKERAGE 7734", -BROKERAGE_CONTRIB[m]))
        p = PAY[m - 1]
        txns.append((p["pay_date"], "HALCYON SYSTEMS PAYROLL DIRECT DEP", p["net"]))
        txns.sort(key=lambda t: t[0])
        closing = bal + sum(t[2] for t in txns)
        life["checking"][m] = {"opening": bal, "closing": closing,
                               "txns": [Txn(*t) for t in txns]}
        bal = closing

    # --- savings: January and February only. There is no March statement, so at
    #     the end of March savings is the stalest input to the net-worth curve.
    sbal = SAVINGS_OPEN
    for m in (1, 2):
        txns = [Txn(f"2026-{m:02d}-12", "TRANSFER FROM NORTHBANK CHECKING 4417", D("500.00")),
                Txn(LAST_DAY[m], "INTEREST PAID", SAVINGS_INTEREST[m])]
        closing = sbal + sum(t.delta for t in txns)
        life["savings"][m] = {"opening": sbal, "closing": closing, "txns": txns}
        sbal = closing

    # --- brokerage: cash flow, then the holdings snapshot
    cash = BROKER_CASH_OPEN
    units = dict(UNITS_OPEN)
    for m in (1, 2, 3):
        activity, price = [], PRICES[m]
        contrib_date = f"2026-{m:02d}-28" if m != 2 else "2026-02-25"
        activity.append((contrib_date, "CONTRIBUTION - ACH FROM NORTHBANK 4417",
                         "contribution", BROKERAGE_CONTRIB[m]))
        if DIVIDENDS[m]:
            activity.append((f"2026-{m:02d}-15", "DIVIDEND RECEIVED", "dividend", DIVIDENDS[m]))
        for tkr, qty in BUYS[m]:
            activity.append((f"2026-{m:02d}-20", f"BUY {tkr} {qty} SHARES @ {money(price[tkr])}",
                             "buy", -(qty * price[tkr])))
            units[tkr] = units[tkr] + qty
        activity.append((LAST_DAY[m], "ACCOUNT SERVICE FEE", "fee", -FEES[m]))
        activity.sort(key=lambda a: a[0])
        closing_cash = cash + sum(a[3] for a in activity)
        positions = [(tkr, name, units[tkr], price[tkr], (units[tkr] * price[tkr]).quantize(D("0.01")))
                     for tkr, name in INSTRUMENTS]
        total = closing_cash + sum(p[4] for p in positions)
        life["brokerage"][m] = {"opening_cash": cash, "closing_cash": closing_cash,
                                "activity": activity, "positions": positions, "total": total}
        cash = closing_cash
    return life


def assert_identities(life: dict) -> None:
    """Every printed identity, checked before anything is rendered."""
    for m in (1, 2, 3):
        c = life["checking"][m]
        assert c["opening"] + sum(t.delta for t in c["txns"]) == c["closing"], f"checking {m}"
        k = life["card"][m]
        assert k["opening"] + sum(x[2] for x in k["charges"]) - k["payment"][1] == k["closing"], f"card {m}"
        b = life["brokerage"][m]
        assert b["opening_cash"] + sum(a[3] for a in b["activity"]) == b["closing_cash"], f"brokerage cash {m}"
        assert sum(p[4] for p in b["positions"]) + b["closing_cash"] == b["total"], f"brokerage tally {m}"
    for m in (1, 2):
        s = life["savings"][m]
        assert s["opening"] + sum(t.delta for t in s["txns"]) == s["closing"], f"savings {m}"
    for i, p in enumerate(PAY):
        assert p["gross"] - sum(d[2] for d in p["deductions"]) == p["net"], f"pay {i}"
    # forward stitching: each month opens where the last one closed
    for m in (2, 3):
        assert life["checking"][m]["opening"] == life["checking"][m - 1]["closing"]
        assert life["card"][m]["opening"] == life["card"][m - 1]["closing"]
        assert life["brokerage"][m]["opening_cash"] == life["brokerage"][m - 1]["closing_cash"]
    assert life["savings"][2]["opening"] == life["savings"][1]["closing"]
    # the cross-document facts an end-to-end run has to find
    for m in (1, 2, 3):
        cash_out = [t for t in life["checking"][m]["txns"] if "MERIDIAN CARD" in t.description]
        assert len(cash_out) == 1 and -cash_out[0].delta == life["card"][m]["payment"][1]
        dep = [t for t in life["checking"][m]["txns"] if "PAYROLL" in t.description]
        assert len(dep) == 1 and dep[0].delta == PAY[m - 1]["net"]
    nets = [p["net"] for p in PAY]
    assert len(set(nets)) == len(nets), "two pay stubs share a net — a deposit could match either"


# ------------------------------------------------------------------ render

class Page:
    def __init__(self, path: pathlib.Path, title: str):
        self.c = canvas.Canvas(str(path), pagesize=LETTER)
        self.c.setTitle(title)
        self.w, self.h = LETTER
        self.y = self.h - 0.75 * inch

    def hdr(self, institution: str, subtitle: str) -> None:
        self.c.setFont("Helvetica-Bold", 17)
        self.c.drawString(0.75 * inch, self.y, institution)
        self.c.setFont("Helvetica", 9.5)
        self.c.drawRightString(self.w - 0.75 * inch, self.y + 2, subtitle)
        self.y -= 6
        self.c.setStrokeColor(colors.HexColor("#333333"))
        self.c.setLineWidth(1.2)
        self.c.line(0.75 * inch, self.y, self.w - 0.75 * inch, self.y)
        self.y -= 20

    def block(self, lines: list[str], size: float = 9.5, gap: float = 13) -> None:
        self.c.setFont("Helvetica", size)
        for ln in lines:
            self.c.drawString(0.75 * inch, self.y, ln)
            self.y -= gap
        self.y -= 4

    def kv(self, pairs: list[tuple[str, str]], bold_last: bool = False) -> None:
        for i, (k, v) in enumerate(pairs):
            last = bold_last and i == len(pairs) - 1
            self.c.setFont("Helvetica-Bold" if last else "Helvetica", 10)
            self.c.drawString(0.75 * inch, self.y, k)
            self.c.drawRightString(self.w - 0.75 * inch, self.y, v)
            self.y -= 15
        self.y -= 4

    def section(self, title: str) -> None:
        self.y -= 6
        self.c.setFont("Helvetica-Bold", 10.5)
        self.c.drawString(0.75 * inch, self.y, title)
        self.y -= 4
        self.c.setStrokeColor(colors.HexColor("#999999"))
        self.c.setLineWidth(0.6)
        self.c.line(0.75 * inch, self.y, self.w - 0.75 * inch, self.y)
        self.y -= 15

    def row(self, cols: list[tuple[str, float, str]], bold: bool = False) -> None:
        """cols = (text, x_offset_inches, align) where align is 'l' or 'r'."""
        if self.y < 1.0 * inch:
            self.c.showPage()
            self.y = self.h - 0.75 * inch
        self.c.setFont("Helvetica-Bold" if bold else "Helvetica", 9)
        for text, x, align in cols:
            if align == "r":
                self.c.drawRightString(x * inch, self.y, text)
            else:
                self.c.drawString(x * inch, self.y, text)
        self.y -= 13

    def save(self) -> None:
        self.c.save()


def us(iso: str) -> str:
    y, m, d = iso.split("-")
    return f"{m}/{d}/{y}"


def render_bank(path, acct, m, data, kind):
    p = Page(path, f"{acct['institution']} statement")
    p.hdr(acct["institution"].upper(),
          f"{acct['name']} · Statement Period {us(FIRST_DAY[m])} – {us(LAST_DAY[m])}")
    p.block([HOLDER] + ADDRESS + ["", f"Account Number   {acct['number']}",
                                  f"Statement Date   {us(LAST_DAY[m])}"])
    p.kv([("Beginning Balance", money(data["opening"])),
          ("Deposits and Other Credits", money(sum(t.delta for t in data["txns"] if t.delta > 0))),
          ("Withdrawals and Other Debits", money(-sum(t.delta for t in data["txns"] if t.delta < 0))),
          ("Ending Balance", money(data["closing"]))], bold_last=True)
    p.section("TRANSACTION DETAIL")
    p.row([("Date", 0.75, "l"), ("Description", 1.5, "l"),
           ("Amount", 6.4, "r"), ("Balance", 7.75, "r")], bold=True)
    run = data["opening"]
    for t in data["txns"]:
        run += t.delta
        p.row([(us(t.date), 0.75, "l"), (t.description[:48], 1.5, "l"),
               (money(t.delta), 6.4, "r"), (money(run), 7.75, "r")])
    p.row([("", 0.75, "l"), ("Ending Balance", 1.5, "l"), ("", 6.4, "r"),
           (money(data["closing"]), 7.75, "r")], bold=True)
    p.y -= 10
    p.block(["Member FDIC. Questions? Call 1-800-000-0000.",
             "This statement is a synthetic test document. No real account exists."], size=7.5, gap=10)
    p.save()


def render_card(path, m, data):
    p = Page(path, "Meridian Signature Card statement")
    p.hdr("MERIDIAN", f"Signature Card · Billing Period {us(FIRST_DAY[m])} – {us(LAST_DAY[m])}")
    p.block([HOLDER] + ADDRESS + ["", f"Account Number   {CARD['number']}",
                                  f"Statement Closing Date   {us(LAST_DAY[m])}",
                                  f"Payment Due Date   {us(LAST_DAY[m])[:3]}25/2026"])
    charges = sum(c[2] for c in data["charges"])
    p.kv([("Previous Balance", money(data["opening"])),
          ("Payments and Credits", f"-{money(data['payment'][1])}"),
          ("Purchases", money(charges)),
          ("Fees and Interest Charged", money(D('0.00'))),
          ("New Balance", money(data["closing"]))], bold_last=True)
    p.block([f"Minimum Payment Due   {money((data['closing'] * D('0.02')).quantize(D('0.01')))}",
             f"Credit Limit   {money(D('15000.00'))}"])
    p.section("PAYMENTS AND CREDITS")
    p.row([("Date", 0.75, "l"), ("Description", 1.5, "l"), ("Amount", 7.75, "r")], bold=True)
    p.row([(us(data["payment"][0]), 0.75, "l"), ("PAYMENT RECEIVED - THANK YOU", 1.5, "l"),
           (f"-{money(data['payment'][1])}", 7.75, "r")])
    p.section("PURCHASES")
    p.row([("Date", 0.75, "l"), ("Description", 1.5, "l"), ("Amount", 7.75, "r")], bold=True)
    for d, desc, amt in data["charges"]:
        p.row([(us(d), 0.75, "l"), (desc[:52], 1.5, "l"), (money(amt), 7.75, "r")])
    p.y -= 6
    p.row([("", 0.75, "l"), ("New Balance", 1.5, "l"), (money(data["closing"]), 7.75, "r")], bold=True)
    p.y -= 10
    p.block(["A balance shown as a positive figure is an amount you owe.",
             "This statement is a synthetic test document. No real account exists."], size=7.5, gap=10)
    p.save()


def render_paystub(path, idx, p_data):
    p = Page(path, "Halcyon Systems earnings statement")
    p.hdr("HALCYON SYSTEMS INC.", "Earnings Statement")
    start, end = p_data["period"]
    p.block([HOLDER] + ADDRESS + ["",
             f"Employee ID   HS-40928",
             f"Pay Period   {us(start)} – {us(end)}",
             f"Pay Date   {us(p_data['pay_date'])}"])
    p.section("EARNINGS")
    p.row([("Description", 0.75, "l"), ("Rate", 4.2, "r"), ("Hours", 5.3, "r"),
           ("This Period", 6.6, "r"), ("Year to Date", 7.9, "r")], bold=True)
    ytd_gross = sum(PAY[i]["gross"] for i in range(idx + 1))
    p.row([("Regular Salary", 0.75, "l"), ("", 4.2, "r"), ("", 5.3, "r"),
           (money(p_data["gross"]), 6.6, "r"), (money(ytd_gross), 7.9, "r")])
    p.row([("Gross Pay", 0.75, "l"), ("", 4.2, "r"), ("", 5.3, "r"),
           (money(p_data["gross"]), 6.6, "r"), (money(ytd_gross), 7.9, "r")], bold=True)
    p.section("DEDUCTIONS")
    p.row([("Description", 0.75, "l"), ("This Period", 6.6, "r"), ("Year to Date", 7.9, "r")], bold=True)
    for label, _bucket, amt in p_data["deductions"]:
        ytd = sum(a for i in range(idx + 1) for lb, _b, a in PAY[i]["deductions"] if lb == label)
        p.row([(label, 0.75, "l"), (money(amt), 6.6, "r"), (money(ytd), 7.9, "r")])
    total_ded = sum(d[2] for d in p_data["deductions"])
    p.row([("Total Deductions", 0.75, "l"), (money(total_ded), 6.6, "r"), ("", 7.9, "r")], bold=True)
    p.y -= 8
    p.kv([("NET PAY", money(p_data["net"]))], bold_last=True)
    p.block([f"Net pay deposited to {CHECKING['institution']} {CHECKING['name']} {CHECKING['number']}",
             "This earnings statement is a synthetic test document."], size=8, gap=11)
    p.save()


def render_brokerage(path, m, data):
    p = Page(path, "Vantage Brokerage statement")
    p.hdr("VANTAGE INVESTMENTS",
          f"Brokerage Account · {MONTH_NAME[m]} 2026 Statement")
    p.block([HOLDER] + ADDRESS + ["", f"Account Number   {BROKER['number']}",
                                  f"Statement Period   {us(FIRST_DAY[m])} – {us(LAST_DAY[m])}",
                                  f"Valuation Date   {us(LAST_DAY[m])}"])
    p.kv([("Cash and Cash Equivalents", money(data["closing_cash"])),
          ("Market Value of Holdings", money(sum(x[4] for x in data["positions"]))),
          ("Total Account Value", money(data["total"]))], bold_last=True)
    p.section("HOLDINGS AS OF " + us(LAST_DAY[m]))
    p.row([("Symbol", 0.75, "l"), ("Description", 1.6, "l"), ("Quantity", 5.2, "r"),
           ("Price", 6.3, "r"), ("Market Value", 7.9, "r")], bold=True)
    for tkr, name, qty, price, mv in data["positions"]:
        p.row([(tkr, 0.75, "l"), (name, 1.6, "l"), (f"{qty:,.3f}", 5.2, "r"),
               (money(price), 6.3, "r"), (money(mv), 7.9, "r")])
    p.row([("", 0.75, "l"), ("Total Holdings", 1.6, "l"), ("", 5.2, "r"), ("", 6.3, "r"),
           (money(sum(x[4] for x in data["positions"])), 7.9, "r")], bold=True)
    p.section("CASH ACTIVITY")
    p.row([("Date", 0.75, "l"), ("Description", 1.6, "l"), ("Amount", 7.9, "r")], bold=True)
    p.row([("", 0.75, "l"), ("Opening Cash Balance", 1.6, "l"),
           (money(data["opening_cash"]), 7.9, "r")], bold=True)
    for d, desc, _kind, amt in data["activity"]:
        p.row([(us(d), 0.75, "l"), (desc[:52], 1.6, "l"), (money(amt), 7.9, "r")])
    p.row([("", 0.75, "l"), ("Closing Cash Balance", 1.6, "l"),
           (money(data["closing_cash"]), 7.9, "r")], bold=True)
    p.y -= 10
    p.block(["Securities are not FDIC insured. Values shown are as of the valuation date.",
             "This statement is a synthetic test document. No real account exists."], size=7.5, gap=10)
    p.save()


# -------------------------------------------------------------- answer key

def answer_key(life: dict) -> dict:
    """Every true figure, raw-as-printed beside its normalized value."""
    def e(label, raw, value, page=1):
        return {"label": label, "value_raw": raw, "value": str(value),
                "locale": LOCALE, "currency": CURRENCY, "page": page}

    docs = {}
    for m in (1, 2, 3):
        c = life["checking"][m]
        docs[f"checking-2026-{m:02d}"] = {
            "doc_type": "checking_statement", "account": CHECKING,
            "period": [FIRST_DAY[m], LAST_DAY[m]],
            "entries": [e("opening balance", money(c["opening"]), c["opening"]),
                        e("closing balance", money(c["closing"]), c["closing"]),
                        e("transaction count", str(len(c["txns"])), len(c["txns"]))] +
                       [e(f"txn {t.date} {t.description}", money(t.delta), t.delta) for t in c["txns"]]}
        k = life["card"][m]
        docs[f"card-2026-{m:02d}"] = {
            "doc_type": "credit_card_statement", "account": CARD,
            "period": [FIRST_DAY[m], LAST_DAY[m]],
            "entries": [e("previous balance", money(k["opening"]), k["opening"]),
                        e("new balance", money(k["closing"]), k["closing"]),
                        e("payment", money(k["payment"][1]), k["payment"][1])] +
                       [e(f"charge {d} {desc}", money(a), a) for d, desc, a in k["charges"]]}
        b = life["brokerage"][m]
        docs[f"brokerage-2026-{m:02d}"] = {
            "doc_type": "brokerage_statement", "account": BROKER,
            "period": [FIRST_DAY[m], LAST_DAY[m]],
            "entries": [e("opening cash", money(b["opening_cash"]), b["opening_cash"]),
                        e("closing cash", money(b["closing_cash"]), b["closing_cash"]),
                        e("total account value", money(b["total"]), b["total"])] +
                       [e(f"holding {t} units", f"{q:,.3f}", q) for t, _n, q, _p, _mv in b["positions"]] +
                       [e(f"holding {t} market value", money(mv), mv) for t, _n, _q, _p, mv in b["positions"]]}
    for m in (1, 2):
        s = life["savings"][m]
        docs[f"savings-2026-{m:02d}"] = {
            "doc_type": "savings_statement", "account": SAVINGS,
            "period": [FIRST_DAY[m], LAST_DAY[m]],
            "entries": [e("opening balance", money(s["opening"]), s["opening"]),
                        e("closing balance", money(s["closing"]), s["closing"]),
                        e("interest paid", money(SAVINGS_INTEREST[m]), SAVINGS_INTEREST[m])]}
    for i, p in enumerate(PAY):
        docs[f"paystub-2026-{i+1:02d}"] = {
            "doc_type": "pay_stub", "employer": EMPLOYER, "pay_date": p["pay_date"],
            "entries": [e("gross pay", money(p["gross"]), p["gross"]),
                        e("net pay", money(p["net"]), p["net"])] +
                       [e(f"deduction {lb}", money(a), a) for lb, _b, a in p["deductions"]]}

    cross = []
    for m in (1, 2, 3):
        cross.append({"kind": "card_payment", "from": "checking", "to": "card",
                      "amount": str(life["card"][m]["payment"][1]),
                      "expect": "one movement recognised as a transfer, counted once, excluded from spending"})
        cross.append({"kind": "payroll", "stub": f"paystub-2026-{m:02d}", "to": "checking",
                      "amount": str(PAY[m - 1]["net"]),
                      "expect": "the stub decomposes this deposit; gross recognised once"})
        cross.append({"kind": "brokerage_contribution", "from": "checking", "to": "brokerage",
                      "amount": str(BROKERAGE_CONTRIB[m]),
                      "expect": "counted once, not spending"})
    return {"locale": LOCALE, "currency": CURRENCY, "holder": HOLDER,
            "accounts": {"checking": CHECKING, "savings": SAVINGS, "card": CARD, "brokerage": BROKER},
            "documents": docs, "cross_document_facts": cross,
            "derived": {
                "net_worth_2026-03-31": str((
                    life["checking"][3]["closing"] + life["savings"][2]["closing"]
                    + life["brokerage"][3]["total"] - life["card"][3]["closing"]).quantize(D("0.01"))),
                "note": "savings has no March statement, so its February closing is the "
                        "latest measurement at that date and is the stalest input to the point",
                "total_gross_income": str(sum(p["gross"] for p in PAY)),
                "total_net_income": str(sum(p["net"] for p in PAY)),
                "total_dividends": str(sum(DIVIDENDS.values())),
            }}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    life = build_life()
    assert_identities(life)

    made = []
    for m in (1, 2, 3):
        f = OUT / f"northbank-checking-2026-{m:02d}.pdf"
        render_bank(f, CHECKING, m, life["checking"][m], "checking"); made.append(f)
        f = OUT / f"meridian-card-2026-{m:02d}.pdf"
        render_card(f, m, life["card"][m]); made.append(f)
        f = OUT / f"vantage-brokerage-2026-{m:02d}.pdf"
        render_brokerage(f, m, life["brokerage"][m]); made.append(f)
    for m in (1, 2):
        f = OUT / f"northbank-savings-2026-{m:02d}.pdf"
        render_bank(f, SAVINGS, m, life["savings"][m], "savings"); made.append(f)
    for i, p in enumerate(PAY):
        f = OUT / f"halcyon-paystub-2026-{i+1:02d}.pdf"
        render_paystub(f, i, p); made.append(f)

    key = answer_key(life)
    (OUT.parent / "answer-key.json").write_text(json.dumps(key, indent=2))

    print(f"{len(made)} documents written to {OUT}")
    for f in sorted(made):
        print(f"  {f.name:38s} {f.stat().st_size/1024:6.1f} KB")
    print("\nIdentities checked and holding:")
    for m in (1, 2, 3):
        print(f"  checking {m}: {money(life['checking'][m]['opening'])} -> "
              f"{money(life['checking'][m]['closing'])}   "
              f"card {m}: {money(life['card'][m]['opening'])} -> {money(life['card'][m]['closing'])}   "
              f"brokerage {m} total: {money(life['brokerage'][m]['total'])}")
    print(f"\nExpected net worth at 2026-03-31: {key['derived']['net_worth_2026-03-31']} USD")


if __name__ == "__main__":
    main()
