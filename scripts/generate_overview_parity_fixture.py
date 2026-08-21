#!/usr/bin/env python3
"""Generate the artifact the backend and the interface are both held to.

The bytes this writes are what the real provider returns for a real vault,
carried through the real bridge dispatch. Nothing in it is authored by hand.

The vault it reads is built here, in code, from the event constructors the
ingest path posts through, and holds eight shapes of account: one that
reconciles, one owed on, one owed on and in credit, one nothing attested, one
holding instruments, one whose records disagree, one in a second currency, and
one whose newest record is old. Every name and number in it is invented.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import shutil
import sys
import tempfile
from decimal import Decimal
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ARTIFACT = (ROOT / "product" / "viva" / "surface" / "fixtures"
                    / "overview-parity-v1.json")

# The day the fixture is written as of, and the conventions its amounts are
# written under. Both are stated rather than taken from the machine that runs
# this, so the bytes do not depend on where or when it ran.
TODAY = "2026-09-30"
LOCALE = "en-US"

# Every setting the product reads that would otherwise move these bytes, stated
# here and applied for the length of the run. The locale decides how amounts
# are written; the two reader settings decide which sentence the documents read
# says about reading, so a machine with them exported would generate a
# different artifact from the same product. A generator whose output depends on
# whose machine ran it is not a single writer of anything. `None` means the
# setting is removed rather than given a value.
STATED_ENVIRONMENT: dict[str, str | None] = {
    "VIVA_LOCALE": LOCALE,
    "VIVA_MODEL_ADAPTER": None,
    "VIVA_MODEL": None,
}

# What read the fixture's documents. Named so the artifact says a reading
# happened and says plainly that it was not a real one.
READER_MODEL = "fixture-reader"
READER_PROMPT = "fixture-read-v1"

# The passphrase the fixture vault is minted under. It opens nothing that
# outlives this run: the vault is built in a temporary directory and deleted.
PASSPHRASE = "fixture-vault-passphrase"

# The surfaces the artifact holds. The overview is what this is about; the
# documents read travels with it because a citation is only a route where the
# document it names is a row a person can open.
SURFACES = ("overview", "documents")


def _import_path() -> None:
    for package in ("product", "core", "merchant"):
        path = str(ROOT / package)
        if path not in sys.path:
            sys.path.insert(0, path)


@contextlib.contextmanager
def _stated_environment(settings: dict = STATED_ENVIRONMENT):
    """Run under the settings the fixture declares, whatever the machine's own
    are, and restore the caller's on the way out."""
    before = {name: os.environ.get(name) for name in settings}
    try:
        for name, value in settings.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        yield
    finally:
        for name, value in before.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def build_vault(directory: Path):
    """Eight shapes of account in one vault, and the documents behind them."""
    _import_path()
    from viva.ledger import (Provenance, account_opened,
                             closing_balance_observed, document_captured,
                             opening_balance_observed, read_recorded,
                             simple_transaction)
    from viva.ledger.events import position_observed
    from viva.vault import Vault

    vault = Vault.open(directory, PASSPHRASE)

    def document(body: str, doc_type: str, captured_at: str,
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
        vault.ledger.append(document_captured(
            doc_id, f"{doc_type}.txt", len(body.encode("utf-8")), doc_type,
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
                            "2026-07-02",
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
        "acct:everyday-checking", "-318.55", "rent", "2026-06-08"))
    vault.ledger.append(closing("acct:everyday-checking", "3081.45",
                                "2026-06-30", checking_doc, 3))

    # One is owed on, and the bill prints what is owed as a positive number.
    card_doc = document("household card, sixth month", "credit_card_statement",
                        "2026-07-02",
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
                          "2026-07-02")
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
                           "2026-07-02")
    vault.ledger.append(opening("acct:rainy-day-savings", "5000.00",
                                "2026-06-01", savings_doc, 1))
    vault.ledger.append(simple_transaction(
        "acct:rainy-day-savings", "12.50", "interest", "2026-06-30"))

    # One holds instruments as well as cash, measured on a different day from
    # the cash, so what the account is worth rests on two dates.
    brokerage_doc = document("growth portfolio, sixth month",
                             "brokerage_statement", "2026-07-02")
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
                         "2026-07-02",
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
                          "2026-07-02")
    vault.ledger.append(account_opened(
        "acct:abroad-current", "depository", "Abroad Current", "EUR",
        "2026-06-01", institution="Sample Bank Abroad",
        account_number="000000007745", account_names=["SAMPLE HOLDER"]))
    vault.ledger.append(closing("acct:abroad-current", "642.10", "2026-06-30",
                                abroad_doc, 1))

    # And one whose newest record is old: a confident number that is wrong
    # about when rather than about how much.
    dormant_doc = document("dormant savings, eleventh month of the year before",
                           "bank_statement", "2025-12-04")
    vault.ledger.append(account_opened(
        "acct:dormant-savings", "depository", "Dormant Savings", "USD",
        "2025-11-01", institution="Sample Mutual",
        account_number="000000001038", account_names=["SAMPLE HOLDER"]))
    vault.ledger.append(closing("acct:dormant-savings", "1250.00", "2025-11-30",
                                dormant_doc, 1))

    # And one the vault simply holds. Nothing has read it, so it stands behind
    # no account and no figure cites it.
    parked("a document this vault holds and has not read", "unread-note.txt",
           "2026-07-02")
    return vault


def read_surfaces(vault) -> dict[str, Any]:
    """Every surface the artifact holds, read the way the desktop reads it.

    The real provider, the real dispatcher and the real frame: what this
    records is what a shell would receive, not what a caller of the composer
    would."""
    _import_path()
    from viva.desktop_bridge import dispatch_frame, handlers_with_surface_provider
    from viva.desktop_bridge.vault_provider import create_vault_surface_provider
    from viva.surface import CURRENT_PROTOCOL

    if not SURFACES:
        raise SystemExit("the artifact declares no surface to read; a byte "
                         "comparison over nothing passes without checking "
                         "anything")
    dispatcher = handlers_with_surface_provider(
        create_vault_surface_provider(vault))
    reads = {}
    for surface in SURFACES:
        frame = json.dumps({
            "protocol": CURRENT_PROTOCOL.wire(),
            "request_id": f"parity-{surface}",
            "operation": "viva.surface.read",
            "payload": {"surface": surface, "job_id": f"parity-{surface}"},
        })
        reads[surface] = json.loads(dispatch_frame(frame, dispatcher.handlers))
    return reads


def build_artifact() -> dict[str, Any]:
    """The artifact both languages read, built by running the product.

    Refuses to produce an artifact that holds nothing. A gate whose subject is
    a byte comparison passes over an empty set as readily as over a correct
    one, so the set it walks is checked to be non-empty rather than assumed."""
    _import_path()
    from viva.surface import CURRENT_PROTOCOL

    directory = Path(tempfile.mkdtemp(prefix="orionviva-parity-"))
    try:
        with _stated_environment():
            vault = build_vault(directory / "vault")
            reads = read_surfaces(vault)
    finally:
        shutil.rmtree(directory, ignore_errors=True)
    if not reads or any(not frame.get("ok") for frame in reads.values()):
        raise SystemExit("a surface did not answer; the artifact is not "
                         "written from a failed read")
    return {
        "artifact": "orionviva.overview-parity-v1",
        "protocol": CURRENT_PROTOCOL.wire(),
        "locale": LOCALE,
        "today": TODAY,
        "reads": reads,
    }


def encoded_artifact() -> bytes:
    return (json.dumps(build_artifact(), indent=2, sort_keys=True)
            + "\n").encode("utf-8")


def check_artifact(path: Path = DEFAULT_ARTIFACT) -> None:
    expected = encoded_artifact()
    if not path.exists():
        raise SystemExit(f"overview parity fixture is missing: {path}")
    if path.read_bytes() != expected:
        raise SystemExit(
            "overview parity drift detected; run "
            f"{Path(__file__).name} --write to review the generated update")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true",
                      help="fail when the artifact is stale")
    mode.add_argument("--write", action="store_true",
                      help="write the artifact the product produces")
    parser.add_argument("--artifact", type=Path, default=DEFAULT_ARTIFACT)
    args = parser.parse_args(argv)
    if args.write:
        args.artifact.parent.mkdir(parents=True, exist_ok=True)
        args.artifact.write_bytes(encoded_artifact())
        print(f"wrote {args.artifact}")
    else:
        check_artifact(args.artifact)
        print(f"overview parity fixture is current: {args.artifact}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
