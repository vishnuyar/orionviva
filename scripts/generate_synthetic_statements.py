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
    packet.drawString(42, 28, "Synthetic statement set - Fidelity Investments")
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


def specs_from_catalog(catalog: dict[str, dict]) -> list[StatementSpec]:
    return [
        StatementSpec(
            file_name="north-river-checking-june-2026.pdf",
            kind="bank_statement",
            institution="Silverline Bank",
            account="Everyday Checking",
            statement_title="Checking Account Statement",
            period="2026-06-01 - 2026-06-30",
            opening="$8,240.18",
            closing="$12,420.91",
            transactions=[
                ("2026-06-30", "Direct Deposit", "+4,800.00", "Payroll deposit from employer"),
                ("2026-06-28", merchant_name(catalog, "patel brothers"), "-86.42", "Grocery purchase"),
                ("2026-06-27", merchant_name(catalog, "venmo"), "-145.00", "Peer transfer"),
                ("2026-06-24", merchant_name(catalog, "wal mart"), "-154.83", "Household supplies"),
                ("2026-06-22", merchant_name(catalog, "schoolcafe"), "-42.50", "School lunch payment"),
                ("2026-06-18", merchant_name(catalog, "amzn mktp us"), "-118.79", "Household and office order"),
            ],
            notes=[
                "Memo: synthetic merchants are drawn from the merchant catalog for UI and parsing exercises.",
                "The balance history is illustrative only and intended for local testing.",
            ],
            merchants=["Patel Brothers", "Venmo", "Walmart", "SchoolCafe", "Amazon Marketplace"],
        ),
        StatementSpec(
            file_name="north-river-savings-june-2026.pdf",
            kind="bank_statement",
            institution="Silverline Bank",
            account="North River Savings",
            statement_title="Savings Account Statement",
            period="2026-06-01 - 2026-06-30",
            opening="$40,000.00",
            closing="$40,000.00",
            transactions=[
                ("2026-06-15", "Interest", "+12.11", "Monthly interest credit"),
                ("2026-06-03", "Transfer from checking", "+1,500.00", "Automated savings transfer"),
                ("2026-06-01", "Opening balance", "+40,000.00", "Beginning of period balance"),
            ],
            notes=[
                "Interest is represented as a standard bank credit.",
                "No card payments or merchant liabilities appear in this account.",
            ],
            merchants=[],
        ),
        StatementSpec(
            file_name="retail-banking-may-2026.pdf",
            kind="bank_statement",
            institution="Silverline Bank",
            account="Everyday Checking",
            statement_title="Bank Statement",
            period="2026-05-01 - 2026-05-31",
            opening="$5,976.02",
            closing="$8,240.18",
            transactions=[
                ("2026-05-31", "Payroll Deposit", "+4,600.00", "Employer payroll credit"),
                ("2026-05-29", merchant_name(catalog, "patel brothers"), "-74.11", "Groceries"),
                ("2026-05-23", merchant_name(catalog, "wal mart"), "-131.02", "Household goods"),
                ("2026-05-18", merchant_name(catalog, "venmo"), "-95.00", "Transfer to friend"),
                ("2026-05-11", merchant_name(catalog, "amzn mktp us"), "-88.44", "Online purchase"),
                ("2026-05-04", merchant_name(catalog, "schoolcafe"), "-38.00", "Lunch account top-up"),
            ],
            notes=["Useful for testing mixed transaction categories and recurring cash flow."],
            merchants=["Patel Brothers", "Walmart", "Venmo", "Amazon Marketplace", "SchoolCafe"],
        ),
        StatementSpec(
            file_name="fidelity-brokerage-may-2026.pdf",
            kind="brokerage_statement",
            institution="Fidelity Investments",
            account="Taxable Brokerage",
            statement_title="Brokerage Statement",
            period="2026-05-01 - 2026-05-31",
            opening="$64,210.44",
            closing="$68,994.10",
            transactions=[
                ("2026-05-02", merchant_name(catalog, "fid bkg svc llc"), "-2,500.00", "Cash contribution to brokerage"),
                ("2026-05-12", merchant_name(catalog, "amzn mktp us"), "-224.19", "Discretionary purchase"),
                ("2026-05-19", merchant_name(catalog, "tesla supercharger u"), "-58.30", "Travel expense reclassed to spending"),
                ("2026-05-28", "Dividend", "+96.45", "Qualified dividend reinvested"),
            ],
            notes=["Holdings are summarized on the next page to exercise investment statement layouts."],
            holdings=[["Security", "Shares", "Price", "Market Value"], ["VTI", "120.000", "$210.12", "$25,214.40"], ["AAPL", "48.000", "$198.44", "$9,525.12"], ["VXUS", "95.000", "$57.28", "$5,441.60"], ["Cash", "-", "-", "$28,812.98"]],
            merchants=["Fidelity Brokerage Services", "Amazon Marketplace", "Tesla Supercharger", "Venmo"],
        ),
        StatementSpec(
            file_name="fidelity-brokerage-june-2026.pdf",
            kind="brokerage_statement",
            institution="Fidelity Investments",
            account="Taxable Brokerage",
            statement_title="Brokerage Statement",
            period="2026-06-01 - 2026-06-30",
            opening="$68,994.10",
            closing="$71,802.55",
            transactions=[
                ("2026-06-04", merchant_name(catalog, "fid bkg svc llc"), "+3,000.00", "Brokerage cash inflow"),
                ("2026-06-11", "SPY", "+14.22", "Unrealized gain on market movement"),
                ("2026-06-17", "AAPL", "+22.88", "Appreciation in equity positions"),
                ("2026-06-26", merchant_name(catalog, "venmo"), "-300.00", "Transfer to checking"),
            ],
            notes=["Holdings are summarized on the next page to exercise investment statement layouts."],
            holdings=[["Security", "Shares", "Price", "Market Value"], ["VTI", "121.500", "$212.40", "$25,820.10"], ["AAPL", "50.000", "$201.33", "$10,066.50"], ["VXUS", "95.000", "$58.01", "$5,510.95"], ["Cash", "-", "-", "$30,405.00"]],
            merchants=["Fidelity Brokerage Services", "Venmo"],
        ),
        StatementSpec(
            file_name="chase-card-june-2026.pdf",
            kind="credit_card_statement",
            institution="Chase",
            account="Chase Sapphire",
            statement_title="Credit Card Statement",
            period="2026-06-01 - 2026-06-30",
            opening="$1,842.77",
            closing="$2,115.63",
            transactions=[
                ("2026-06-28", merchant_name(catalog, "patel brothers"), "-86.42", "Groceries"),
                ("2026-06-24", merchant_name(catalog, "wal mart"), "-64.17", "General merchandise"),
                ("2026-06-19", merchant_name(catalog, "tesla supercharger u"), "-31.80", "Charging"),
                ("2026-06-14", merchant_name(catalog, "amzn mktp us"), "-144.55", "Shopping"),
                ("2026-06-10", merchant_name(catalog, "payment to chase card ending in"), "+1,200.00", "Payment received from checking"),
            ],
            notes=[
                "Card payment and purchase activity reference merchants present in the merchant catalog.",
                "Payments toward this card are shown as account reductions in the bank statement set.",
            ],
            merchants=["Patel Brothers", "Walmart", "Tesla Supercharger", "Amazon Marketplace", "Chase"],
        ),
        StatementSpec(
            file_name="citi-card-june-2026.pdf",
            kind="credit_card_statement",
            institution="Citi",
            account="Citi Double Cash",
            statement_title="Credit Card Statement",
            period="2026-06-01 - 2026-06-30",
            opening="$620.14",
            closing="$884.02",
            transactions=[
                ("2026-06-29", merchant_name(catalog, "newrez shellpoin ach"), "-1,250.00", "Mortgage payment from bank account"),
                ("2026-06-21", merchant_name(catalog, "kumon learning"), "-180.00", "Monthly tutoring"),
                ("2026-06-16", merchant_name(catalog, "schoolcafe"), "-57.60", "School meals"),
                ("2026-06-11", merchant_name(catalog, "imprintp2 ach"), "-42.12", "Subscription charge"),
                ("2026-06-07", merchant_name(catalog, "citi card online"), "+900.00", "Card payment"),
            ],
            notes=[
                "This card statement includes loan-payment and housing-related merchants for categorization tests.",
                "The final payment line should be easy to cross-check against the bank statement series.",
            ],
            merchants=["Newrez", "Kumon", "SchoolCafe", "Imprint", "Citi"],
        ),
    ]


def main(out_dir: Path = DEFAULT_OUT) -> None:
    if not CATALOG.exists():
        raise FileNotFoundError(f"merchant catalog not found: {CATALOG}")
    catalog = json.loads(CATALOG.read_text())["records"]
    out_dir.mkdir(parents=True, exist_ok=True)
    for pdf in out_dir.glob("*.pdf"):
        pdf.unlink()
    styles = build_styles()
    specs = specs_from_catalog(catalog)
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
