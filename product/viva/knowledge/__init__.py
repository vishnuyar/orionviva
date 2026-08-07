"""The expectations engine — documents are evidence that other documents exist.

Completeness knowledge is not a parser and not a nag — it is a small set of
universal MECHANISMS (code, below) driven by a declarative REGISTRY (data,
``expectations-v1.json``). A registry entry states what exists in the world and
how it relates — never how to read anything. Jurisdiction tags make an entry set
a knowledge pack.

Deliberately READ-SIDE (the read-early/write-late principle): an expectation is
*derived* on every projection from evidence already in the ledger — no new
event type, nothing to migrate, wrong entries fixable by editing data. The two
states that need memory already have it: *declined* is the decline event (the
question stays quiet until the stake changes), and *satisfied* is deterministic
— the expected document type is present among captured documents.
Model-suggested expectations are deliberately not built.

What ships in v1 is three mechanisms:

- ``retirement_flow``    — money is flowing into a retirement bucket (pay-stub
                           deductions land in ``Assets:Retirement``) and no
                           statement has ever shown where it lands.
- ``investment_account`` — an investment account exists, so its jurisdiction's
                           annual tax document exists somewhere too (US: 1099).
- ``account_cadence``    — an account's last attested balance is older than the
                           cadence its kind implies; a newer statement likely
                           exists. Stake 0: it settles no money, it improves
                           currency — so it ranks below every money question,
                           honestly.
"""

from __future__ import annotations

import json
import pathlib
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from functools import lru_cache

from vivacore import versions

from ..render import accounts, date as render_date, document, money

_DIR = pathlib.Path(__file__).resolve().parent

ACTIVE_REGISTRY = versions.active(_DIR.parent, "expectations")


@lru_cache(maxsize=4)
def load(version: str = ACTIVE_REGISTRY) -> dict:
    return json.loads((_DIR / f"{version}.json").read_text())


@dataclass
class Expectation:
    """One unmet expectation: a document that should exist, and the stake."""

    id: str                      # stable — "expectation:<entry>:<subject>"
    entry_id: str                # the registry row that raised it
    kind: str                    # the mechanism name (phrasing selector)
    document: str                # what to ask for, in plain words (from data)
    subject: str                 # account / bucket the evidence points at
    amount: Decimal              # the money the document would attest / settle
    currency: str = "USD"
    count: int = 1
    fields: dict = field(default_factory=dict)   # slots for the phrasing


def _doc_type_seen(proj, doc_types: list) -> bool:
    """Satisfaction, deterministically: the expected document type has arrived.
    Matching is by the classifier's doc_type — never by content opinion."""
    seen = set(proj.captured_docs().values())
    return any(dt in seen for dt in doc_types)


def _retirement_flow(proj, entry: dict, as_of: str,
                     locale: str = "") -> list[Expectation]:
    from viva.ledger import UnknownAccountError
    try:
        bal = proj.balance("Assets:Retirement")
    except UnknownAccountError:
        return []
    amount = abs(bal.amount)
    if not amount or _doc_type_seen(proj, entry.get("expect_doc_types", [])):
        return []
    # A deduction bucket carries no currency of its own; borrow the vault's —
    # the first real account's currency, deterministically.
    currency = bal.currency or next(
        (i.currency for i in proj.account_infos() if i.currency), "USD")
    return [Expectation(
        id=f"expectation:{entry['id']}", entry_id=entry["id"],
        kind="retirement_flow", document=entry["document"],
        subject="Assets:Retirement", amount=amount, currency=currency,
        fields={"money": money(amount, currency, locale=locale),
                "document": document(entry["document"])})]


def _investment_account(proj, entry: dict, as_of: str,
                        locale: str = "") -> list[Expectation]:
    from viva.ledger import UnknownAccountError
    held = [i for i in proj.account_infos() if i.kind == "investment"]
    if not held or _doc_type_seen(proj, entry.get("expect_doc_types", [])):
        return []
    # The stake: investment income already recorded, which the tax document
    # would attest (and refine into short/long-term — money currently discarded).
    amount = Decimal("0")
    currency = held[0].currency or "USD"
    for acct in ("Income:CapitalGains", "Income:Dividends"):
        try:
            amount += abs(proj.balance(acct).amount)
        except UnknownAccountError:
            continue
    names = accounts(sorted(({"name": i.name, "path": i.account}
                             for i in held),
                            key=lambda e: e["name"] or e["path"]))
    return [Expectation(
        id=f"expectation:{entry['id']}", entry_id=entry["id"],
        kind="investment_account", document=entry["document"],
        subject=str(names), amount=amount, currency=currency, count=len(held),
        fields={"account_name": names, "document": document(entry["document"]),
                "money": money(amount, currency, locale=locale)})]


def _account_cadence(proj, entry: dict, as_of: str,
                     locale: str = "") -> list[Expectation]:
    out: list[Expectation] = []
    horizon = int(entry.get("cadence_days", 45))
    try:
        today = date.fromisoformat(as_of)
    except ValueError:
        return []
    for info in proj.account_infos():
        if info.kind not in ("depository", "liability"):
            continue
        ba = proj.balance(info.account)
        if not ba.dated:
            continue
        try:
            last = date.fromisoformat(ba.dated)
        except ValueError:
            continue
        if today - last <= timedelta(days=horizon):
            continue
        out.append(Expectation(
            id=f"expectation:{entry['id']}:{info.account}",
            entry_id=entry["id"], kind="account_cadence",
            document=entry["document"], subject=info.account,
            amount=Decimal("0"), currency=info.currency,
            fields={"account_name": accounts([{"name": info.name,
                                               "path": info.account}]),
                    "last_date": render_date(ba.dated)}))
    return out


_MECHANISMS = {
    "retirement_flow": _retirement_flow,
    "investment_account": _investment_account,
    "account_cadence": _account_cadence,
}


def evaluate(proj, as_of: str, jurisdiction: str = "US",
             version: str = ACTIVE_REGISTRY,
             locale: str = "") -> list[Expectation]:
    """Every unmet expectation the registry raises against this ledger.

    Pure and deterministic: same events + same registry + same date → same
    expectations. Declines are NOT filtered here — that is the queue's job, so
    the suppression rule lives in exactly one place.

    ``locale`` decides how the stake is written; the amount itself is on the
    expectation either way, so nothing here computes a figure it also formats."""
    out: list[Expectation] = []
    for entry in load(version)["entries"]:
        allowed = entry.get("jurisdictions", ["*"])
        if "*" not in allowed and jurisdiction not in allowed:
            continue
        mechanism = _MECHANISMS.get(entry.get("given", ""))
        if mechanism is None:
            # An entry naming an unknown mechanism is a data error — loud, not
            # silently skipped, or the registry rots invisibly.
            raise ValueError(f"registry entry {entry.get('id')!r} names unknown "
                             f"mechanism {entry.get('given')!r}")
        out.extend(mechanism(proj, entry, as_of, locale))
    return out
