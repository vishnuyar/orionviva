"""Build and open the persistent fictional sample vault."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

from .env import CONFIG_HOME

# Public passphrase for the fictional sample vault.
DEMO_PASSPHRASE = "a-sample-vault-anybody-may-open"

# Tests may relocate the persistent sample directory with ``VIVA_DEMO_HOME``.
DEMO_DIRECTORY = "sample-vault"

# Reader identity recorded for fictional sample documents.
READER_MODEL = "sample-reader"
READER_PROMPT = "sample-read-v1"


def demo_home(base: Path | None = None) -> Path:
    """Return the sample directory, honoring ``VIVA_DEMO_HOME``."""
    import os

    if base is not None:
        return Path(base) / DEMO_DIRECTORY
    stated = os.environ.get("VIVA_DEMO_HOME", "").strip()
    if stated:
        return Path(stated).expanduser()
    return CONFIG_HOME / DEMO_DIRECTORY


def open_demo_vault(base: Path | None = None) -> tuple[Any, bool]:
    """Return the opened sample vault and whether this call created it."""
    from .vault import Vault, holds_a_vault

    home = demo_home(base)
    if holds_a_vault(home):
        vault, made = Vault.open(home, DEMO_PASSPHRASE, create=False), False
        try:
            _prepare_demo_read_store(vault)
        except Exception:
            vault.close()
            raise
    else:
        home.mkdir(parents=True, exist_ok=True)
        vault, made = build_demo_vault(home), True
    return vault, made


def _prepare_demo_read_store(vault) -> None:
    """Publish the sample's authenticated SQL generation before returning."""
    from .read_store import ReadStoreDegraded, ReadStoreError

    state = vault.synchronize_read_store()
    if state not in {"equal", "caught_up", "rebuilt"} or vault.read_store is None:
        raise ReadStoreDegraded("sample read projection is unavailable")
    expected = vault.ledger.store.authenticated_identity()
    try:
        with vault.read_store.open_reader() as revision:
            source = vault.read_store.authenticated_source_identity(revision)
        if source.get("count") != expected[0] or source.get("head") != expected[1]:
            raise ReadStoreDegraded("sample read projection is not current")
    except ReadStoreDegraded:
        raise
    except ReadStoreError as exc:
        raise ReadStoreDegraded(
            "sample read projection could not be authenticated") from exc


def build_demo_vault(directory: Path):
    """Populate the fictional sample through production vault APIs."""
    from .ledger import (Provenance, account_opened,
                         closing_balance_observed, document_captured,
                         opening_balance_observed, read_recorded,
                         simple_transaction)
    from .ingest.statement import StatementFacts
    from .ledger.events import (merchant_enriched, position_observed,
                                ruling_recorded, statement_held)
    from .vault import Vault

    vault = Vault.open(directory, DEMO_PASSPHRASE)

    def document(body: str, doc_type: str, captured_at: str, filename: str,
                 declares: dict | None = None) -> str:
        """Capture a sample document and record its reading."""
        doc_id = vault.raw.put(body.encode("utf-8"))
        # Preserve a distinct display filename for each sample document.
        vault.ledger.append(document_captured(
            doc_id, filename, len(body.encode("utf-8")), doc_type,
            0.98, captured_at, Provenance(doc_id=doc_id)))
        reply = {"doc_type": doc_type, "doc_type_confidence": 0.98,
                 **(declares or {})}
        vault.ledger.append(read_recorded(
            doc_id, READER_MODEL, READER_PROMPT, "text+image",
            json.dumps(reply, sort_keys=True), 0.0, 0, 0, True, None,
            captured_at, Provenance(doc_id=doc_id)))
        return doc_id

    def parked(body: str, filename: str, captured_at: str) -> str:
        """Capture a sample document without reading or posting it."""
        doc_id = vault.raw.put(body.encode("utf-8"))
        vault.ledger.append(document_captured(
            doc_id, filename, len(body.encode("utf-8")), "unknown", 0.0,
            captured_at, Provenance(doc_id=doc_id)))
        return doc_id

    def period(opening: tuple[str, str], closing: tuple[str, str]) -> dict:
        """Return a statement period mapping."""
        return {"opening": {"amount_raw": opening[0], "date_raw": opening[1]},
                "closing": {"amount_raw": closing[0], "date_raw": closing[1]}}

    def opening(account: str, amount: str, day: str, doc: str, page: int):
        return opening_balance_observed(
            account, amount, day,
            Provenance(doc_id=doc, page=page, note="opening balance"))

    def closing(account: str, amount: str, day: str, doc: str, page: int,
                confirmed_by: str = ""):
        return closing_balance_observed(
            account, amount, day,
            Provenance(doc_id=doc, page=page, note="closing balance"),
            confirmed_by=confirmed_by)

    # Reconciled account.
    checking_doc = document("everyday checking, sixth month", "bank_statement",
                            "2026-07-02", "everyday-checking-2026-06.pdf",
                            period(("1000.00", "2026-06-01"),
                                   ("3081.45", "2026-06-30")))
    vault.ledger.append(account_opened(
        "acct:everyday-checking", "depository", "Everyday Checking", "USD",
        "2026-06-01", institution="Sample Mutual",
        account_number="000000004417", account_names=["SAMPLE HOLDER"]))
    vault.ledger.append(opening("acct:everyday-checking", "1000.00",
                                "2026-06-01", checking_doc, 1))
    vault.ledger.append(simple_transaction(
        "acct:everyday-checking", "2400.00", "salary", "2026-06-05"))
    vault.ledger.append(simple_transaction(
        "acct:everyday-checking", "-318.55", "rent", "2026-06-08",
        provenance=Provenance(doc_id=checking_doc, page=2,
                              region="transactions:rent")))
    # Record a source-backed merchant classification for Activity.
    vault.ledger.append(merchant_enriched(
        "rent", "housing", subcategory="rent", grade="corroborated",
        occurred_at="2026-07-03", by="model",
        provenance=Provenance(doc_id=checking_doc, page=2,
                              region="transactions:rent")))
    vault.ledger.append(closing("acct:everyday-checking", "3081.45",
                                "2026-06-30", checking_doc, 3))

    # Account with a positive amount owed.
    card_doc = document("household card, sixth month", "credit_card_statement",
                        "2026-07-02", "household-card-2026-06.pdf",
                        period(("240.00", "2026-06-01"),
                               ("400.00", "2026-06-30")))
    vault.ledger.append(account_opened(
        "acct:household-card", "liability", "Household Card", "USD",
        "2026-06-01", institution="Sample Card Company",
        account_number="000000008802", account_names=["SAMPLE HOLDER"]))
    vault.ledger.append(opening("acct:household-card", "240.00", "2026-06-01",
                                card_doc, 1))
    vault.ledger.append(simple_transaction(
        "acct:household-card", "160.00", "annual fee", "2026-06-11"))
    vault.ledger.append(closing("acct:household-card", "400.00", "2026-06-30",
                                card_doc, 2))

    # Account with a credit balance.
    travel_doc = document("travel card, sixth month", "credit_card_statement",
                          "2026-07-02", "travel-card-2026-06.pdf")
    vault.ledger.append(account_opened(
        "acct:travel-card", "liability", "Travel Card", "USD", "2026-06-01",
        institution="Sample Card Company", account_number="000000005190",
        account_names=["SAMPLE HOLDER"]))
    vault.ledger.append(closing("acct:travel-card", "-75.00", "2026-06-30",
                                travel_doc, 1))

    # Account without an attested closing balance.
    vault.ledger.append(account_opened(
        "acct:rainy-day-savings", "depository", "Rainy Day Savings", "USD",
        "2026-06-01", institution="Sample Mutual",
        account_number="000000006723", account_names=["SAMPLE HOLDER"]))
    savings_doc = document("rainy day savings, opening", "bank_statement",
                           "2026-07-02", "rainy-day-savings-2026-06.pdf")
    vault.ledger.append(opening("acct:rainy-day-savings", "5000.00",
                                "2026-06-01", savings_doc, 1))
    vault.ledger.append(simple_transaction(
        "acct:rainy-day-savings", "12.50", "interest", "2026-06-30"))

    # Account with cash and instrument positions measured on separate dates.
    brokerage_doc = document("growth portfolio, sixth month",
                             "brokerage_statement", "2026-07-02",
                             "growth-portfolio-2026-06.pdf")
    vault.ledger.append(account_opened(
        "acct:growth-portfolio", "investment", "Growth Portfolio", "USD",
        "2026-05-31", institution="Sample Brokerage",
        account_number="000000003311", account_names=["SAMPLE HOLDER"]))
    vault.ledger.append(closing("acct:growth-portfolio", "500.00", "2026-06-30",
                                brokerage_doc, 1))
    vault.ledger.append(position_observed(
        "acct:growth-portfolio", "SAMPLE INDEX FUND", "100", "12000.00", "USD",
        "2026-05-31", cost_basis=Decimal("9000.00"),
        provenance=Provenance(doc_id=brokerage_doc, page=2,
                              note="holdings table")))

    # Account whose closing observation and movements disagree.
    joint_doc = document("joint checking, sixth month", "bank_statement",
                         "2026-07-02", "joint-checking-2026-06.pdf",
                         period(("800.00", "2026-06-01"),
                                ("980.00", "2026-06-30")))
    vault.ledger.append(account_opened(
        "acct:joint-checking", "depository", "Joint Checking", "USD",
        "2026-06-01", institution="Sample Mutual",
        account_number="000000002264",
        account_names=["SAMPLE HOLDER", "SECOND SAMPLE HOLDER"]))
    vault.ledger.append(opening("acct:joint-checking", "800.00", "2026-06-01",
                                joint_doc, 1))
    vault.ledger.append(simple_transaction(
        "acct:joint-checking", "-120.00", "utilities", "2026-06-14"))
    vault.ledger.append(closing("acct:joint-checking", "980.00", "2026-06-30",
                                joint_doc, 2))

    # Account held in a second currency.
    abroad_doc = document("abroad account, sixth month", "bank_statement",
                          "2026-07-02", "abroad-current-2026-06.pdf")
    vault.ledger.append(account_opened(
        "acct:abroad-current", "depository", "Abroad Current", "EUR",
        "2026-06-01", institution="Sample Bank Abroad",
        account_number="000000007745", account_names=["SAMPLE HOLDER"]))
    vault.ledger.append(closing("acct:abroad-current", "642.10", "2026-06-30",
                                abroad_doc, 1))

    # Account whose newest observation is stale.
    dormant_doc = document("dormant savings, eleventh month of the year before",
                           "bank_statement", "2025-12-04",
                           "dormant-savings-2025-11.pdf")
    vault.ledger.append(account_opened(
        "acct:dormant-savings", "depository", "Dormant Savings", "USD",
        "2025-11-01", institution="Sample Mutual",
        account_number="000000001038", account_names=["SAMPLE HOLDER"]))
    vault.ledger.append(closing("acct:dormant-savings", "1250.00", "2025-11-30",
                                dormant_doc, 1))

    # Liability ruling without a source-backed balance or account record.
    vault.ledger.append(simple_transaction(
        "acct:rainy-day-savings", "-450.00", "sample lender", "2026-06-20"))
    vault.ledger.append(ruling_recorded(
        scope="merchant", subject="sample lender",
        legs=[{"major": "liability", "account": "Liabilities:Loan:Sample"}],
        occurred_at="2026-07-05", by="human"))

    # Captured document without a reading.
    parked("a document this vault holds and has not read", "unread-note.txt",
           "2026-07-02")

    # Read document held for a statement-period gap.
    unposted_doc = document("everyday checking, eighth month", "bank_statement",
                            "2026-09-04", "everyday-checking-2026-08.pdf",
                            period(("3081.45", "2026-08-01"),
                                   ("3402.10", "2026-08-31")))
    vault.ledger.append(statement_held(
        unposted_doc,
        StatementFacts(
            doc_id=unposted_doc, doc_type="bank_statement",
            doc_type_confidence=0.98, account_ref="acct:everyday-checking",
            currency="USD", opening_amount=Decimal("3081.45"),
            opening_date="2026-08-01", closing_amount=Decimal("3402.10"),
            closing_date="2026-08-31", transactions=[], opening_page=1,
            closing_page=2, account_number="000000004417",
            institution="Sample Mutual",
            account_names=["SAMPLE HOLDER"]).to_dict(),
        None, "gap", "2026-09-04", Provenance(doc_id=unposted_doc)))
    _states_every_screen_can_be_in(vault)
    _prepare_demo_read_store(vault)
    return vault


def _states_every_screen_can_be_in(vault) -> None:
    """Populate sample states for Activity, Plans, Review, and Trust."""
    from .ledger import (Provenance, goal_created, goal_funds_reserved,
                         read_recorded, simple_transaction)
    from .ledger.events import (agent_acted, question_declined, transfer_linked,
                                transfer_suggested)

    # Same-day movements linked as an own-account transfer.
    vault.ledger.append(simple_transaction(
        "acct:everyday-checking", "-600.00", "transfer to savings",
        "2026-06-18"))
    vault.ledger.append(simple_transaction(
        "acct:rainy-day-savings", "600.00", "transfer from checking",
        "2026-06-18"))
    # Include an unresolved transfer suggestion beside the linked pair.
    vault.ledger.append(simple_transaction(
        "acct:everyday-checking", "-275.00", "possible transfer to savings",
        "2026-06-22"))
    vault.ledger.append(simple_transaction(
        "acct:rainy-day-savings", "275.00", "possible transfer from checking",
        "2026-06-23"))
    moved = {movement.description: movement.key
             for movement in vault.ledger.projection().movements()}
    out, back = (moved.get("transfer to savings"),
                 moved.get("transfer from checking"))
    if out and back:
        vault.ledger.append(transfer_linked(
            out, back, "corroborated",
            {"same_day": True, "same_amount": True,
             "decided_by": "named_account"}, "2026-06-19", by="auto"))
    possible_out, possible_back = (
        moved.get("possible transfer to savings"),
        moved.get("possible transfer from checking"))
    if possible_out and possible_back:
        vault.ledger.append(transfer_suggested(
            possible_out, [possible_back],
            {"verdict": "suggested", "amount": "275.00", "currency": "USD"},
            "2026-06-23"))

    # Plan with a separately recorded account reservation.
    created = goal_created(
        "goal:sample-trip", "Sample journey", "USD", "2400.00",
        "2026-07-01", target_date="2026-12-15",
        monthly_contribution="350.00", contribution_day=15,
        proposal_id="proposal:sample-trip")
    created.event_id = "event:sample-trip-created"
    vault.ledger.append(created)
    reserved = goal_funds_reserved(
        "goal:sample-trip", "acct:everyday-checking", "600.00",
        "2026-07-02", proposal_id="proposal:sample-trip-reserve")
    reserved.event_id = "event:sample-trip-reserved"
    vault.ledger.append(reserved)

    # Set-aside review question.
    vault.ledger.append(question_declined(
        "sample-question-set-aside", "merchant", "2026-07-06",
        reason="not_now"))

    # Completed unattended work receipt.
    vault.ledger.append(agent_acted(
        "merchant-grammar", "enrichment", "sample lender", "done",
        "2026-07-08", calls=1, detail="wrote a grammar for a sample merchant"))

    # Recorded conversation answer.
    spoken = {
        "question": "What is this sample picture missing?",
        "shape": {"figures": [{"id": "sample-net-worth",
                               "record_ids": ["sample-record-net-worth"],
                               "grade": "corroborated"}]},
        "verdict": {"answered": True, "refusal": "", "calls": 1},
    }
    # Bind the recorded turn to the installed compiler version.
    from .answer_program.compiler import COMPILER_VERSION

    vault.ledger.append(read_recorded(
        "speak:sample-session:1:1", READER_MODEL, COMPILER_VERSION, "text",
        json.dumps(spoken, sort_keys=True), 0.0, 0, 0, True, None,
        "2026-07-09", Provenance(), phase="speak"))
