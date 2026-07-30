"""The transfer report: what it claims about existing links, and its one write.

The report exists because the two obvious intuitions about `DATE_WINDOW_DAYS`
are both backwards, so the thing under test here is not formatting — it is
whether the report's verdict agrees with the matcher's. A report that says a
link would survive today's rule while the matcher would not make it is worse
than no report, because it is the thing being trusted to decide what to revoke.
"""

from decimal import Decimal

import pytest

from viva.ingest import (RawStore, ReadResult, StatementFacts, TxnFact,
                         capture_and_ingest, link_transfers)
from viva.ledger.events import transfer_linked
from viva.vault import Vault


def _facts(ref, doc_type, number, txns, opening, closing):
    return StatementFacts(
        doc_id="", doc_type=doc_type, doc_type_confidence=0.98, account_ref=ref,
        currency="USD", opening_amount=Decimal(opening), opening_date="2026-01-01",
        closing_amount=Decimal(closing), closing_date="2026-01-31",
        transactions=[TxnFact(date=d, description=desc, amount=Decimal(a))
                      for d, desc, a in txns],
        opening_page=1, closing_page=2, account_number=number, institution="Acme")


def _up(vault, data, f):
    def _stamp(_d, did):
        f.doc_id = did
        return ReadResult(f.doc_type, 0.98, f)
    return capture_and_ingest(vault.raw, vault.ledger, data, _stamp,
                              captured_at="2026-02-01")


CHECKING = [
    # amount  what it is                                    what the report says
    ("2026-01-10", "ONLINE PAYMENT TO CARD 9876", "-2400.00"),   # links (named)
    ("2026-01-14", "ATM Withdrawal 500 Main St Card 8888", "-300.00"),
    ("2026-01-20", "Transfer out", "-750.00"),                   # no account named
    ("2026-01-26", "01/25 PAYMENT TO CARD 9876", "-600.00"),     # links (name+date)
    ("2026-01-27", "PAYMENT TO CARD 9876", "-600.00"),           # loses to the above
    ("2026-01-29", "PAYMENT TO CARD 9876", "-800.00"),           # dead heat
    ("2026-01-29", "PAYMENT TO CARD 9876", "-800.00"),           # dead heat
    ("2026-01-31", "PAYMENT TO CARD 9876", "-950.00"),           # 2 candidates tied
]
CARD = [
    ("2026-01-12", "PAYMENT THANK YOU", "-2400.00"),
    ("2026-01-15", "PAYMENT THANK YOU-MOBILE", "-300.00"),
    ("2026-01-21", "PAYMENT THANK YOU", "-750.00"),
    ("2026-01-22", "PAYMENT THANK YOU", "-750.00"),
    ("2026-01-25", "PAYMENT THANK YOU", "-600.00"),
    ("2026-01-29", "PAYMENT THANK YOU", "-800.00"),
    ("2026-01-31", "PAYMENT THANK YOU", "-950.00"),
    ("2026-02-01", "PAYMENT THANK YOU", "-950.00"),
]


def _closing(opening, txns):
    return str(Decimal(opening) + sum(Decimal(a) for _d, _s, a in txns))


@pytest.fixture()
def vault(tmp_path, monkeypatch):
    """One checking account, one card, and a case for every verdict the report
    can print. The amounts are all distinct so each cluster is independent, and
    the closing balances are derived so a line can be added without arithmetic.

    Deliberately covers all four ask-reasons, because the reasons are the report's
    actual product — a count of 29 questions told us nothing, and the split into
    'the date would answer this' versus 'nothing here names an account' is what
    turned that count into a decision."""
    v = Vault.open(tmp_path / "vault", "pw")
    _up(v, b"chk", _facts("Everyday Checking 1111", "checking_statement",
                          "000000001111", CHECKING, "20000.00",
                          _closing("20000.00", CHECKING)))
    _up(v, b"card", _facts("Rewards Card 9876", "credit_card_statement",
                           "000000009876", CARD, "20000.00",
                           _closing("20000.00", CARD)))
    link_transfers(v.ledger)
    monkeypatch.setenv("VIVA_VAULT_DIR", str(tmp_path / "vault"))
    monkeypatch.setenv("VIVA_PASSPHRASE", "pw")
    return v


def _run(monkeypatch, capsys, *argv):
    import viva.transfer_report as R
    monkeypatch.setattr("sys.argv", ["transfer_report", *argv])
    assert R.main() == 0
    return capsys.readouterr().out


def _forge_stale(vault):
    """A link of the kind the deleted word list used to make: equal amounts,
    opposite directions, one candidate — and nothing naming either account."""
    proj = vault.ledger.projection()
    loose = [m for m in proj.movements() if not getattr(m, "linked", False)]
    a = next(m for m in loose if "ATM" in m.description)
    b = next(m for m in loose if "MOBILE" in m.description)
    vault.ledger.append(transfer_linked(a.key, b.key, "corroborated",
                                        {"kind": "decisive"}, "2026-01-15",
                                        by="auto"))
    return a, b


def test_the_named_link_is_made_and_the_coincidence_is_not(vault):
    """The premise the rest of the file rests on. If this breaks, the report is
    testing the wrong matcher, not the wrong report."""
    proj = vault.ledger.projection()
    linked = {m.description for m in proj.movements() if getattr(m, "linked", False)}
    assert any("CARD 9876" in d for d in linked)
    assert not any("ATM" in d for d in linked)


def test_report_runs_and_does_not_write_without_the_flag(vault, monkeypatch, capsys):
    before = len(list(vault.ledger.events()))
    out = _run(monkeypatch, capsys, "--private")
    assert "THE LINKS THAT ALREADY EXIST" in out
    assert len(list(vault.ledger.events())) == before


def test_it_names_the_reason_each_question_would_be_asked(vault, monkeypatch, capsys):
    """The four ask-reasons want different fixes, so collapsing them into a
    single count is what the old report did and what made it useless."""
    out = _run(monkeypatch, capsys, "--private")
    assert "no account named" in out                              # 'Transfer out'
    assert "candidates, evidence tied" in out                     # the 950 pair
    assert "tied with another source for the same credit" in out  # the 800 twins
    # The fourth reason, "another source claims it more strongly", is absent on
    # purpose and its absence is the finding: a source that loses a destination
    # to a stronger rival normally loses it in the same scan, because the rival
    # links and both legs stop being candidates. It surfaces only when the
    # stronger rival was itself blocked for some other reason, which is rare
    # enough that contriving a fixture for it would test the fixture.


def test_the_printed_date_decides_where_the_name_alone_cannot(vault, monkeypatch,
                                                              capsys):
    """Two identical debits naming the same card, one credit. The one whose line
    prints 01/25 links; the other becomes a question rather than a coin flip."""
    out = _run(monkeypatch, capsys, "--private")
    assert "named_account+printed_date" in out      # the report shows the rule
    proj = vault.ledger.projection()
    by_key = {m.key: m for m in proj.movements()}
    dated = [link for link in proj.transfer_links()
             if link.get("decided_by") == "named_account+printed_date"]
    assert dated, "the date should have decided at least one link"
    for link in dated:
        legs = {by_key[link["a"]].description, by_key[link["b"]].description}
        assert any(d.startswith("01/25") for d in legs)


def test_a_link_todays_rule_would_not_make_is_reported_as_such(vault, monkeypatch,
                                                               capsys):
    _forge_stale(vault)
    out = _run(monkeypatch, capsys, "--private")
    assert "1 would NOT be made today" in out
    assert "--unlink-stale" in out


def test_a_link_todays_rule_would_make_is_left_alone(vault, monkeypatch, capsys):
    out = _run(monkeypatch, capsys, "--unlink-stale")
    assert "Every automatic link still stands" in out
    assert "REVOKING" not in out


def test_unlink_stale_revokes_it_and_leaves_the_original_event(vault, monkeypatch,
                                                               capsys):
    a, b = _forge_stale(vault)
    out = _run(monkeypatch, capsys, "--unlink-stale")
    assert "REVOKING 1 LINK(S)" in out

    # Reopened deliberately. The report holds its own handle on the event file
    # and this fixture's Ledger caches a live projection, so asserting against
    # the fixture's copy would be asking a stale in-memory view whether a write
    # it never saw happened. The file is the authority.
    fresh = Vault.open(vault.directory, "pw")
    proj = fresh.ledger.projection()
    still = {m.key for m in proj.movements() if getattr(m, "linked", False)}
    assert a.key not in still and b.key not in still

    # Append-only: the ruling is overruled in the log, never edited out of it.
    kinds = [e.event_type for e in fresh.ledger.events()]
    assert kinds.count("TransferLinked") == 3        # two real, one forged
    assert kinds.count("TransferUnlinked") == 1


def test_a_revoked_pair_comes_back_as_a_question_not_a_link(vault, monkeypatch,
                                                            capsys):
    """Revoking must not quietly re-link on the next scan — that would make the
    flag a no-op with extra steps."""
    _forge_stale(vault)
    _run(monkeypatch, capsys, "--unlink-stale")
    out = _run(monkeypatch, capsys, "--private")
    assert "Every automatic link still stands" in out
    assert "no account named" in out
