"""Generate a synthetic statement set that mirrors the backend's statement shapes.

The goal is not realism for its own sake; it is a local, reproducible corpus
that exercises the same branches the real vault does:

- checking statements with merchant transactions
- savings statements with only balance / interest activity
- brokerage statements with holdings, cash, and a second holdings page
- credit card statements with payments and household spending

The output is a bundle of PDFs plus a JSON manifest that other tools can load.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterable

from pypdf import PdfReader, PdfWriter
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "output" / "pdf" / "synthetic_statements"
CATALOG = Path("/Users/vishnu/Downloads/catalog.json")


def merchant_name(catalog: dict[str, dict], key: str) -> str:
    return catalog[key]["canonical_name"]


@dataclass(frozen=True)
class StatementSpec:
    file_name: str
    kind: str
    institution: str
    account: str
    statement_title: str
    period: str
    opening: str
    closing: str
    transactions: list[tuple[str, str, str, str]]
    notes: list[str]
    holdings: list[list[str]] | None = None
    merchants: list[str] | None = None
    family: str = ""
    family: str = ""


def build_styles():
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="Title2", parent=styles["Title"], fontName="Helvetica-Bold", fontSize=20, leading=24, textColor=colors.HexColor("#24352f"), spaceAfter=8))
    styles.add(ParagraphStyle(name="Sub2", parent=styles["Normal"], fontName="Helvetica", fontSize=9.5, leading=12, textColor=colors.HexColor("#66736b")))
    styles.add(ParagraphStyle(name="H2", parent=styles["Heading2"], fontName="Helvetica-Bold", fontSize=12.5, leading=15, textColor=colors.HexColor("#355044"), spaceBefore=10, spaceAfter=6))
    styles.add(ParagraphStyle(name="Small2", parent=styles["BodyText"], fontName="Helvetica", fontSize=8, leading=10, textColor=colors.HexColor("#68756d")))
    return styles


def build_statement_pdf(path: Path, spec: StatementSpec, styles) -> None:
    doc = SimpleDocTemplate(str(path), pagesize=letter, rightMargin=42, leftMargin=42, topMargin=44, bottomMargin=42)
    story = [
        Paragraph(spec.institution, styles["Title2"]),
        Paragraph(spec.statement_title, styles["H2"]),
        Paragraph(spec.period, styles["Sub2"]),
        Spacer(1, 0.16 * inch),
    ]

    info = [
        ["Account", spec.account],
        ["Statement period", spec.period],
        ["Opening balance", spec.opening],
        ["Closing balance", spec.closing],
    ]
    summary = Table(info, colWidths=[1.6 * inch, 4.8 * inch])
    summary.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#edf3ec")),
        ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor("#2f3a36")),
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("LEADING", (0, 0), (-1, -1), 11),
        ("BOX", (0, 0), (-1, -1), 0.7, colors.HexColor("#cfd8cf")),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#dfe5dc")),
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.white, colors.HexColor("#fafbf7")]),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.extend([summary, Spacer(1, 0.16 * inch), Paragraph("Transactions", styles["H2"])])

    rows = [["Date", "Merchant / Description", "Amount", "Notes"]]
    rows.extend([[date, merchant, amount, note] for date, merchant, amount, note in spec.transactions])
    transactions = Table(rows, colWidths=[1.05 * inch, 2.6 * inch, 1.0 * inch, 2.2 * inch], repeatRows=1)
    transactions.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#264238")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.6),
        ("LEADING", (0, 0), (-1, -1), 10.5),
        ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor("#cfd8cf")),
        ("INNERGRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#dde4db")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8faf5")]),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(transactions)
    story.append(Spacer(1, 0.15 * inch))

    for line in spec.notes:
        story.append(Paragraph(line, styles["Small2"]))
        story.append(Spacer(1, 0.05 * inch))

    def footer(c, d):
        c.saveState()
        c.setFont("Helvetica", 8)
        c.setFillColor(colors.HexColor("#6c766f"))
        c.drawString(42, 28, f"Synthetic statement set - {spec.institution}")
        c.drawRightString(570, 28, f"Page {d.page}")
        c.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)


def add_holdings_page(path: Path, rows: list[list[str]]) -> None:
    buf = Path(path.parent / f".{path.name}.holdings.tmp")
    packet = canvas.Canvas(str(buf), pagesize=letter)
    packet.setFont("Helvetica-Bold", 20)
    packet.setFillColor(colors.HexColor("#24352f"))
    packet.drawString(42, 752, "Holdings Summary")
    packet.setFont("Helvetica", 9.5)
    packet.setFillColor(colors.HexColor("#66736b"))
    packet.drawString(42, 734, "Synthetic holdings summary for local UI and document-processing tests.")
    table = Table(rows, colWidths=[2.6 * inch, 1.0 * inch, 1.2 * inch, 1.2 * inch])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#264238")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor("#cfd8cf")),
        ("INNERGRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#dde4db")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8faf5")]),
    ]))
    width, height = table.wrapOn(packet, 520, 600)
    table.drawOn(packet, 42, 680 - height)
    packet.setFont("Helvetica", 8)
    packet.setFillColor(colors.HexColor("#6c766f"))
    packet.drawString(42, 28, "Synthetic statement set - Northgate Investments")
    packet.drawRightString(570, 28, "Page 2")
    packet.save()
    packet_pdf = PdfReader(str(buf))
    reader = PdfReader(str(path))
    writer = PdfWriter()
    writer.append_pages_from_reader(reader)
    writer.add_page(packet_pdf.pages[0])
    with open(path, "wb") as stream:
        writer.write(stream)
    buf.unlink(missing_ok=True)


def manifest_for(specs: Iterable[StatementSpec]) -> dict:
    docs = []
    for spec in specs:
        docs.append({
            "file": spec.file_name,
            "type": spec.kind,
            "family": spec.family,
            "institution": spec.institution,
            "account": spec.account,
            "period": spec.period.replace(" - ", " to "),
            "merchants": spec.merchants or [],
        })
    return {
        "generated_at": "2026-08-17",
        "source_catalog": str(CATALOG),
        "purpose": "synthetic statement set for local UI and document-processing tests",
        "documents": docs,
    }


def _month_period(year: int, month: int) -> str:
    start = date(year, month, 1)
    if month == 12:
        end = date(year, 12, 31)
    else:
        end = date(year, month + 1, 1) - date.resolution
    return f"{start.isoformat()} - {end.isoformat()}"


def _money(value: float) -> str:
    return f"${value:,.2f}"


def specs_from_catalog(catalog: dict[str, dict], years: int = 4) -> list[StatementSpec]:
    years_list = list(range(2023, 2023 + years))
    specs: list[StatementSpec] = []
    for offset, year in enumerate(years_list):
        bank_open = 6200.00 + offset * 1090.15
        bank_close = bank_open + 3800.73 + offset * 110.12
        sav_open = 40000.00 + offset * 2200.00
        sav_close = sav_open + 200.00 + offset * 80.00
        brk_open = 64210.44 + offset * 5400.00
        brk_close = brk_open + 4783.66 + offset * 350.00
        cc_open = 1842.77 + offset * 190.00
        cc_close = cc_open + 272.86 + offset * 65.00

        specs.extend([
        StatementSpec(
            file_name=f"north-river-checking-june-{year}.pdf",
            kind="bank_statement",
            institution="Silverline Bank",
            account="Everyday Checking",
            statement_title="Checking Account Statement",
            period=_month_period(year, 6),
            opening=_money(bank_open),
            closing=_money(bank_close),
            transactions=[
                (f"{year}-06-30", "Direct Deposit", "+4,800.00", "Payroll deposit from employer"),
                (f"{year}-06-28", merchant_name(catalog, "saffron grocers"), "-86.42", "Grocery purchase"),
                (f"{year}-06-27", merchant_name(catalog, "cashlink"), "-145.00", "Peer transfer"),
                (f"{year}-06-24", merchant_name(catalog, "wal mart"), "-154.83", "Household supplies"),
                (f"{year}-06-22", merchant_name(catalog, "lunchline"), "-42.50", "School lunch payment"),
                (f"{year}-06-18", merchant_name(catalog, "riverbend market"), "-118.79", "Household and office order"),
            ],
            notes=[
                "Memo: synthetic merchants are drawn from the merchant catalog for UI and parsing exercises.",
                "The balance history is illustrative only and intended for local testing.",
            ],
            merchants=["Saffron Grocers", "Cashlink", "Valuemart", "Lunchline", "Riverbend Market"],
        ),
        StatementSpec(
            file_name=f"north-river-savings-june-{year}.pdf",
            kind="bank_statement",
            institution="Silverline Bank",
            account="North River Savings",
            statement_title="Savings Account Statement",
            period=_month_period(year, 6),
            opening=_money(sav_open),
            closing=_money(sav_close),
            transactions=[
                (f"{year}-06-15", "Interest", "+12.11", "Monthly interest credit"),
                (f"{year}-06-03", "Transfer from checking", "+1,500.00", "Automated savings transfer"),
                (f"{year}-06-01", "Opening balance", _money(sav_open), "Beginning of period balance"),
            ],
            notes=[
                "Interest is represented as a standard bank credit.",
                "No card payments or merchant liabilities appear in this account.",
            ],
            merchants=[],
        ),
        StatementSpec(
            file_name=f"retail-banking-may-{year}.pdf",
            kind="bank_statement",
            institution="Silverline Bank",
            account="Everyday Checking",
            statement_title="Bank Statement",
            period=_month_period(year, 5),
            opening=_money(5976.02 + offset * 1080.00),
            closing=_money(bank_open),
            transactions=[
                (f"{year}-05-31", "Payroll Deposit", "+4,600.00", "Employer payroll credit"),
                (f"{year}-05-29", merchant_name(catalog, "saffron grocers"), "-74.11", "Groceries"),
                (f"{year}-05-23", merchant_name(catalog, "wal mart"), "-131.02", "Household goods"),
                (f"{year}-05-18", merchant_name(catalog, "cashlink"), "-95.00", "Transfer to friend"),
                (f"{year}-05-11", merchant_name(catalog, "riverbend market"), "-88.44", "Online purchase"),
                (f"{year}-05-04", merchant_name(catalog, "lunchline"), "-38.00", "Lunch account top-up"),
            ],
            notes=["Useful for testing mixed transaction categories and recurring cash flow."],
            merchants=["Saffron Grocers", "Valuemart", "Cashlink", "Riverbend Market", "Lunchline"],
        ),
        StatementSpec(
            file_name=f"northgate-brokerage-may-{year}.pdf",
            kind="brokerage_statement",
            institution="Northgate Investments",
            account="Taxable Brokerage",
            statement_title="Brokerage Statement",
            period=_month_period(year, 5),
            opening=_money(brk_open),
            closing=_money(brk_close),
            transactions=[
                (f"{year}-05-02", merchant_name(catalog, "fid bkg svc llc"), "-2,500.00", "Cash contribution to brokerage"),
                (f"{year}-05-12", merchant_name(catalog, "riverbend market"), "-224.19", "Discretionary purchase"),
                (f"{year}-05-19", merchant_name(catalog, "voltway charging"), "-58.30", "Travel expense reclassed to spending"),
                (f"{year}-05-28", "Dividend", "+96.45", "Qualified dividend reinvested"),
            ],
            notes=["Holdings are summarized on the next page to exercise investment statement layouts."],
            holdings=[["Security", "Shares", "Price", "Market Value"], ["GBLX", f"{120 + offset * 1.5:.3f}", _money(210.12 + offset * 2.15), _money(25214.40 + offset * 625.70)], ["AAPL", f"{48 + offset * 2:.3f}", _money(198.44 + offset * 2.33), _money(9525.12 + offset * 540.25)], ["VXUS", "95.000", _money(57.28 + offset * 0.73), _money(5441.60 + offset * 89.10)], ["Cash", "-", "-", _money(28812.98 + offset * 1510.00)]],
            merchants=["Northgate Brokerage Services", "Riverbend Market", "Voltway Charging", "Cashlink"],
        ),
        StatementSpec(
            file_name=f"northgate-brokerage-june-{year}.pdf",
            kind="brokerage_statement",
            institution="Northgate Investments",
            account="Taxable Brokerage",
            statement_title="Brokerage Statement",
            period=_month_period(year, 6),
            opening=_money(brk_close),
            closing=_money(brk_close + 2808.45 + offset * 320.00),
            transactions=[
                (f"{year}-06-04", merchant_name(catalog, "fid bkg svc llc"), "+3,000.00", "Brokerage cash inflow"),
                (f"{year}-06-11", "SPY", "+14.22", "Unrealized gain on market movement"),
                (f"{year}-06-17", "AAPL", "+22.88", "Appreciation in equity positions"),
                (f"{year}-06-26", merchant_name(catalog, "cashlink"), "-300.00", "Transfer to checking"),
            ],
            notes=["Holdings are summarized on the next page to exercise investment statement layouts."],
            holdings=[["Security", "Shares", "Price", "Market Value"], ["GBLX", f"{121.5 + offset * 1.5:.3f}", _money(212.40 + offset * 2.15), _money(25820.10 + offset * 625.70)], ["AAPL", f"{50 + offset * 2:.3f}", _money(201.33 + offset * 2.33), _money(10066.50 + offset * 540.25)], ["VXUS", "95.000", _money(58.01 + offset * 0.73), _money(5510.95 + offset * 89.10)], ["Cash", "-", "-", _money(30405.00 + offset * 1510.00)]],
            merchants=["Northgate Brokerage Services", "Cashlink"],
        ),
        StatementSpec(
            file_name=f"harborline-card-june-{year}.pdf",
            kind="credit_card_statement",
            institution="Harborline",
            account="Harborline Signature",
            statement_title="Credit Card Statement",
            period=_month_period(year, 6),
            opening=_money(cc_open),
            closing=_money(cc_close),
            transactions=[
                (f"{year}-06-28", merchant_name(catalog, "saffron grocers"), "-86.42", "Groceries"),
                (f"{year}-06-24", merchant_name(catalog, "wal mart"), "-64.17", "General merchandise"),
                (f"{year}-06-19", merchant_name(catalog, "voltway charging"), "-31.80", "Charging"),
                (f"{year}-06-14", merchant_name(catalog, "riverbend market"), "-144.55", "Shopping"),
                (f"{year}-06-10", merchant_name(catalog, "payment to harborline card ending in"), "+1,200.00", "Payment received from checking"),
            ],
            notes=[
                "Card payment and purchase activity reference merchants present in the merchant catalog.",
                "Payments toward this card are shown as account reductions in the bank statement set.",
            ],
            merchants=["Saffron Grocers", "Valuemart", "Voltway Charging", "Riverbend Market", "Harborline"],
        ),
        StatementSpec(
            file_name=f"meridian-card-june-{year}.pdf",
            kind="credit_card_statement",
            institution="Meridian",
            account="Meridian Everyday",
            statement_title="Credit Card Statement",
            period=_month_period(year, 6),
            opening=_money(620.14 + offset * 175.00),
            closing=_money(cc_close + 150.00 + offset * 40.00),
            transactions=[
                (f"{year}-06-29", merchant_name(catalog, "ridgeline svcg ach"), "-1,250.00", "Mortgage payment from bank account"),
                (f"{year}-06-21", merchant_name(catalog, "brightpath tutoring"), "-180.00", "Monthly tutoring"),
                (f"{year}-06-16", merchant_name(catalog, "lunchline"), "-57.60", "School meals"),
                (f"{year}-06-11", merchant_name(catalog, "penmark ach"), "-42.12", "Subscription charge"),
                (f"{year}-06-07", merchant_name(catalog, "meridian card online"), "+900.00", "Card payment"),
            ],
            notes=[
                "This card statement includes loan-payment and housing-related merchants for categorization tests.",
                "The final payment line should be easy to cross-check against the bank statement series.",
            ],
            merchants=["Ridgeline Servicing", "Brightpath", "Lunchline", "Penmark", "Meridian"],
        ),
        ])
    return specs


def main(out_dir: Path = DEFAULT_OUT) -> None:
    if not CATALOG.exists():
        raise FileNotFoundError(f"merchant catalog not found: {CATALOG}")
    catalog = json.loads(CATALOG.read_text())["records"]
    out_dir.mkdir(parents=True, exist_ok=True)
    for pdf in out_dir.glob("*.pdf"):
        pdf.unlink()
    styles = build_styles()
    specs = specs_from_catalog(catalog, years=4)
    for spec in specs:
        pdf = out_dir / spec.file_name
        build_statement_pdf(pdf, spec, styles)
        if spec.holdings:
            add_holdings_page(pdf, spec.holdings)
    manifest = manifest_for(specs)
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"generated {len(specs)} pdfs and manifest in {out_dir}")


if __name__ == "__main__":
    main()
