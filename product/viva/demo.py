"""The fictional vault a person opens, and where it lives.

The demo used to be told sentence by sentence. Every screen carried a second
dialect — a *Fictional sample* badge beside each figure, an authored fallback
under each missing field — and a person evaluating this product read our
disclaimers instead of the picture we say we can draw. Worse, a qualifier on
one sentence quietly claims the unqualified sentences beside it are different.

**So the demo is a vault rather than a dialect.** What is built here is a real
vault on disk, minted by the same event constructors the ingest path posts
through, opened by the same engine, and read through the same bridge. There is
no fixture behind any screen in it. That is what lets the per-sentence
qualifiers retire: the frame around the whole place is true by construction,
because the place is a vault whose every name and number is invented.

**It has a persistent home.** A vault minted into a temporary directory would
be a new vault every launch, and nothing a person did inside it — answering a
question, capturing a document — would still be there when they came back. It
lives beside the rest of this product's own state, and it is minted once.

**Its passphrase is not a caller's business.** The demo's directory and
passphrase are constants of this module, and the request that opens it carries
neither. A caller cannot point the demo at a directory of their own, and cannot
learn what opens it, because the request has nowhere to say either.

**Nothing here is real.** Every institution, holder, amount and document in
this vault is invented, and the names are self-evidently so.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

from .env import CONFIG_HOME

# What opens the sample vault. It is a constant rather than a secret: the vault
# holds nothing real, and a passphrase a person had to be told would make the
# demo a thing they have to be let into.
DEMO_PASSPHRASE = "a-sample-vault-anybody-may-open"

# Where it lives, beside the rest of this product's own state, so it is the
# same vault the next time the app opens. `VIVA_DEMO_HOME` moves it, which is
# how a test gets one that does not outlive it.
DEMO_DIRECTORY = "sample-vault"

# What read this vault's documents. Named so the vault says a reading happened
# and says plainly that it was not a real one.
READER_MODEL = "sample-reader"
READER_PROMPT = "sample-read-v1"


def demo_home(base: Path | None = None) -> Path:
    """The one directory the sample vault lives in.

    `VIVA_DEMO_HOME` names another, which is how a test gets a sample vault
    that does not outlive it. Nothing else may name one: a caller choosing
    where the demo goes is a caller who can point it at a real vault."""
    import os

    if base is not None:
        return Path(base) / DEMO_DIRECTORY
    stated = os.environ.get("VIVA_DEMO_HOME", "").strip()
    if stated:
        return Path(stated).expanduser()
    return CONFIG_HOME / DEMO_DIRECTORY


def open_demo_vault(base: Path | None = None) -> tuple[Any, bool]:
    """The sample vault, minted where it lives if it is not there yet.

    Returns the vault and whether this call is what made it. Minting is the one
    place in this product where a vault is created without a person saying to,
    and it is safe exactly because the directory and the passphrase are this
    module's rather than a caller's: there is no path by which this makes a
    vault anywhere a person keeps their own."""
    from .vault import Vault, holds_a_vault

    home = demo_home(base)
    if holds_a_vault(home):
        return Vault.open(home, DEMO_PASSPHRASE, create=False), False
    home.mkdir(parents=True, exist_ok=True)
    return build_demo_vault(home), True


def build_demo_vault(directory: Path):
    """The whole fictional vault: eight shapes of account, the documents behind
    them, and one instance of every state a screen in this product can be in.

    Every event here goes through the same constructor the ingest path posts
    through, so what a screen reads out of this vault is what it would read out
    of a real one. Nothing is authored as a rendering."""
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
        """One document as this vault holds it: captured first, always,
        identified by its own content, and carrying the reading that settled it.

        Every document in this vault posts, and a document cannot post through
        this product without something having read it — so a reading is written
        for each one. Without it the artifact would hold a document that is
        settled and that nothing ever read, which is a combination the ingest
        path cannot produce; a parity fixture encoding one proves the rendering
        of something that cannot happen.

        `declares` is what the document said about itself, written into the
        reading verbatim the way a real reply is. The two boxes that bound a
        statement's period are the part of it anything downstream reads, so a
        document carrying both declares both and one carrying neither declares
        neither, exactly as the vault's own events have it."""
        doc_id = vault.raw.put(body.encode("utf-8"))
        # The name a person would see in their own downloads folder. Naming
        # every document after its kind would put eight rows called
        # `bank_statement.txt` on the documents screen, which is a list nobody
        # can tell apart and a demo that shows the screen working worse than it
        # does.
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
        """A document the vault holds and nothing has read.

        Captured and nothing else: no reading, and no account event standing on
        it. It is the ordinary outcome of adding a file with no reader chosen,
        so the artifact holds a row carrying that word and the panel's sentence
        about it — the states the documents read exists to tell apart."""
        doc_id = vault.raw.put(body.encode("utf-8"))
        vault.ledger.append(document_captured(
            doc_id, filename, len(body.encode("utf-8")), "unknown", 0.0,
            captured_at, Provenance(doc_id=doc_id)))
        return doc_id

    def period(opening: tuple[str, str], closing: tuple[str, str]) -> dict:
        """The two boxes a statement prints its period between."""
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

    # One account reconciles: an issuer's closing figure and the period's own
    # movements arrive at the same number.
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
    # An ordinary source-backed merchant classification keeps the sample and
    # parity artifact honest about the complete Activity connective contract:
    # its category hierarchy and provenance are ledger events, not fixture
    # fields authored to make an adapter test pass.
    vault.ledger.append(merchant_enriched(
        "rent", "housing", subcategory="rent", grade="corroborated",
        occurred_at="2026-07-03", by="model",
        provenance=Provenance(doc_id=checking_doc, page=2,
                              region="transactions:rent")))
    vault.ledger.append(closing("acct:everyday-checking", "3081.45",
                                "2026-06-30", checking_doc, 3))

    # One is owed on, and the bill prints what is owed as a positive number.
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

    # One is owed on and in credit: an overpaid card is a negative amount of
    # debt, which says money is held rather than owed.
    travel_doc = document("travel card, sixth month", "credit_card_statement",
                          "2026-07-02", "travel-card-2026-06.pdf")
    vault.ledger.append(account_opened(
        "acct:travel-card", "liability", "Travel Card", "USD", "2026-06-01",
        institution="Sample Card Company", account_number="000000005190",
        account_names=["SAMPLE HOLDER"]))
    vault.ledger.append(closing("acct:travel-card", "-75.00", "2026-06-30",
                                travel_doc, 1))

    # One has nothing attested: its number is the replay of what is on record,
    # with no issuer figure to check it against.
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

    # One holds instruments as well as cash, measured on a different day from
    # the cash, so what the account is worth rests on two dates.
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

    # One disagrees with itself: the issuer's figure and the movements do not
    # meet, and the read says so rather than averaging them.
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

    # One is held in a second currency, so nothing anywhere adds it to the
    # others.
    abroad_doc = document("abroad account, sixth month", "bank_statement",
                          "2026-07-02", "abroad-current-2026-06.pdf")
    vault.ledger.append(account_opened(
        "acct:abroad-current", "depository", "Abroad Current", "EUR",
        "2026-06-01", institution="Sample Bank Abroad",
        account_number="000000007745", account_names=["SAMPLE HOLDER"]))
    vault.ledger.append(closing("acct:abroad-current", "642.10", "2026-06-30",
                                abroad_doc, 1))

    # And one whose newest record is old: a confident number that is wrong
    # about when rather than about how much.
    dormant_doc = document("dormant savings, eleventh month of the year before",
                           "bank_statement", "2025-12-04",
                           "dormant-savings-2025-11.pdf")
    vault.ledger.append(account_opened(
        "acct:dormant-savings", "depository", "Dormant Savings", "USD",
        "2025-11-01", institution="Sample Mutual",
        account_number="000000001038", account_names=["SAMPLE HOLDER"]))
    vault.ledger.append(closing("acct:dormant-savings", "1250.00", "2025-11-30",
                                dormant_doc, 1))

    # And one thing a person holds that no total can carry and no card shows:
    # a debt a ruling brought into being. Cash reaching a lender says nothing
    # about the balance owed, so the point refuses it a figure; nothing opened
    # it, so the accounts read never names it and no currency can be found for
    # it. It is beneath no figure, which is the one shape whose disclosure has
    # nowhere to go but the panel.
    # Paid from the account nothing attests, so no reconciling chain moves and
    # no other shape in this vault changes.
    vault.ledger.append(simple_transaction(
        "acct:rainy-day-savings", "-450.00", "sample lender", "2026-06-20"))
    vault.ledger.append(ruling_recorded(
        scope="merchant", subject="sample lender",
        legs=[{"major": "liability", "account": "Liabilities:Loan:Sample"}],
        occurred_at="2026-07-05", by="human"))

    # And one the vault simply holds. Nothing has read it, so it stands behind
    # no account and no figure cites it.
    parked("a document this vault holds and has not read", "unread-note.txt",
           "2026-07-02")

    # And one that was read and not posted: its period does not join what is
    # already held for the account, so nothing it attests is counted anywhere
    # until the gap between them is settled. It is the other half of what makes
    # a total less than whole, and the one no account can be named for.
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
    return vault


def _states_every_screen_can_be_in(vault) -> None:
    """The rest of what a person meets, beyond the picture and the documents.

    The eight account shapes above were built for a parity artifact over two
    surfaces. A demo is every surface, so this adds one instance of each state
    the other screens can be in: money moving between a person's own pockets,
    a question waiting and a question set aside, unattended work that ran, and
    an answer somebody was given.

    Each is written with the constructor the real path writes it with. A state
    reached any other way would render correctly and be unreachable."""
    from .ledger import (Provenance, goal_created, goal_funds_reserved,
                         read_recorded, simple_transaction)
    from .ledger.events import (agent_acted, question_declined, transfer_linked,
                                transfer_suggested)

    # Money between a person's own pockets, on the same day, in both
    # directions. Activity reads a linked pair as a transfer rather than as
    # spending, which is the one row on that screen that is not what its sign
    # says it is.
    vault.ledger.append(simple_transaction(
        "acct:everyday-checking", "-600.00", "transfer to savings",
        "2026-06-18"))
    vault.ledger.append(simple_transaction(
        "acct:rainy-day-savings", "600.00", "transfer from checking",
        "2026-06-18"))
    # A second pair is deliberately a suggestion, so the real Activity fixture
    # carries the reachable none, suggested and linked relationship states.
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

    # A recorded plan backed by an eligible account. Its target and reserved
    # amount remain separate, and the reservation changes no account posting.
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

    # A question somebody set aside. The queue's other state, and the one that
    # is only reachable by having answered: a vault where nothing was ever
    # declined cannot show what declining looks like.
    vault.ledger.append(question_declined(
        "sample-question-set-aside", "merchant", "2026-07-06",
        reason="not_now"))

    # Unattended work that ran. Trust says "nothing has run over this vault
    # yet" until something has, so a demo where nothing ever ran can only show
    # the absence.
    vault.ledger.append(agent_acted(
        "merchant-grammar", "enrichment", "sample lender", "done",
        "2026-07-08", calls=1, detail="wrote a grammar for a sample merchant"))

    # An answer somebody was given, recorded the way a real turn is. It is what
    # puts a row on the outbound record beside the readings, and what the
    # honesty harness folds over.
    spoken = {
        "question": "What is this sample picture missing?",
        "shape": {"figures": [{"id": "sample-net-worth",
                               "record_ids": ["sample-record-net-worth"],
                               "grade": "corroborated"}]},
        "verdict": {"answered": True, "refusal": "", "calls": 1},
    }
    # The prompt version is read rather than written: a turn recorded under a
    # version this build does not ship would be a recording of something that
    # never ran.
    from .answer_program.compiler import COMPILER_VERSION

    vault.ledger.append(read_recorded(
        "speak:sample-session:1:1", READER_MODEL, COMPILER_VERSION, "text",
        json.dumps(spoken, sort_keys=True), 0.0, 0, 0, True, None,
        "2026-07-09", Provenance(), phase="speak"))
