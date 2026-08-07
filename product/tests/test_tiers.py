"""Ask only where the counterparty cannot tell us.

Asking *"is this money spent, or is it something you now own?"* about a
counterparty already enriched as `loan_payments / mortgage` asks for something
we already know.

So these tests are mostly about **silence** — the hardest thing to assert and the
whole point of the design. A product that asks about a supermarket is not being
careful, it is being useless.
"""

from decimal import Decimal

from viva.ingest import (RawStore, ReadResult, StatementFacts, TxnFact,
                         capture_and_ingest)
from viva.ledger import EventStore, Ledger
from viva.ledger.events import merchant_enriched
from viva.ledger.projection import (TIER_SETTLED, TIER_STRUCTURAL,
                                    TIER_UNENRICHED, TIER_UNKNOWN, TRANSFER)
from viva.persona import say
from viva.questions import NATURE, open_questions


def _vault(tmp_path, txns, opening="100000.00"):
    raw = RawStore.open(tmp_path / "raw", "pw")
    ledger = Ledger(EventStore.open(tmp_path / "events.jsonl", "pw"))
    total = sum(Decimal(a) for _, _, a in txns)
    facts = StatementFacts(
        doc_id="", doc_type="checking_statement", doc_type_confidence=0.98,
        account_ref="Chase Total Checking", currency="USD",
        opening_amount=Decimal(opening), opening_date="2026-03-01",
        closing_amount=Decimal(opening) + total, closing_date="2026-03-31",
        transactions=[TxnFact(d, desc, Decimal(a)) for d, desc, a in txns],
        account_number="000000001122", institution="Chase")

    def read(data, did):
        facts.doc_id = did
        return ReadResult(facts.doc_type, 0.98, facts)

    capture_and_ingest(raw, ledger, b"chk", read, captured_at="2026-04-01")
    return ledger


def _enrich(ledger, merchant, category, implies=(), kind="business", sub=""):
    ledger.append(merchant_enriched(
        merchant, category, subcategory=sub, grade="corroborated",
        occurred_at="2026-04-01", by="model",
        attributes={"counterparty_kind": kind, "implies": list(implies)}))


LOAN_OUT = [{"relationship": "a home loan", "major": "liability", "on": "outflow",
             "account_group": "Mortgage", "compound": True,
             "confidence": "suggested", "documents": "mortgage statement or 1098",
             "ask": "Shall I set up the loan?"}]
BORROWED_IN = [{"relationship": "money you borrowed", "major": "liability",
                "on": "inflow", "account_group": "Loans", "compound": False,
                "confidence": "suggested", "documents": "loan agreement",
                "ask": "Was this a loan?"}]


def _tiers(ledger):
    proj = ledger.projection()
    return {m.description: proj.tier_of(m) for m in proj.movements()}


# ------------------------------------------------------------------- the tiers


def test_an_ordinary_counterparty_is_settled_and_silent(tmp_path):
    """The single largest change: we already knew, so we say nothing."""
    ledger = _vault(tmp_path, [("2026-03-06", "WHOLE FOODS MKT", "-180.00"),
                               ("2026-03-07", "NETFLIX.COM", "-15.00")])
    _enrich(ledger, "whole foods mkt", "food", sub="grocery")
    _enrich(ledger, "netflix com", "entertainment", sub="streaming")

    assert set(_tiers(ledger).values()) == {TIER_SETTLED}
    assert open_questions(ledger, as_of="2026-04-01")["total"] == 0


def test_a_counterparty_that_implies_structure_is_proposed_not_asked(tmp_path):
    ledger = _vault(tmp_path, [("2026-03-01", "LENDER ACH PMT", "-4400.00")])
    _enrich(ledger, "lender ach pmt", "housing", implies=LOAN_OUT, sub="mortgage")

    assert list(_tiers(ledger).values()) == [TIER_STRUCTURAL]
    (q,) = [q for q in open_questions(ledger)["questions"] if q["kind"] == NATURE]
    # A hypothesis with its grounds — not "what is this?"
    assert "normally mean a home loan" in q["text"]
    assert "several things at once" in q["text"]        # compound, stated up front
    # The closing ask is the pack's. What the counterparty implies reaches the
    # question as structure — the relationship, the document, the category —
    # and never as a sentence written at enrichment.
    assert "Shall I set up the loan?" not in q["text"]
    assert say("nature_group_ask") in q["text"]
    assert "mortgage statement or 1098" in q["why"]
    # What the implication suggests travels as references — structure a lint can
    # check — rather than as a pre-answered button.
    assert q["refs"]["implied_major"] == "liability"
    assert q["refs"]["account_group"] == "Mortgage"


def test_an_instrument_is_unknown_and_asked_one_at_a_time(tmp_path):
    ledger = _vault(tmp_path, [("2026-03-04", "Check # 1201", "-20000.00"),
                               ("2026-03-11", "Check # 1202", "-500.00")])
    _enrich(ledger, "check", "other", kind="instrument")

    assert set(_tiers(ledger).values()) == {TIER_UNKNOWN}
    qs = [q for q in open_questions(ledger)["questions"] if q["kind"] == NATURE]
    assert len(qs) == 2 and all(q["scope"] == "one" for q in qs)


def test_an_unidentified_counterparty_waits_for_enrichment(tmp_path):
    """Not a nature question — we don't know who they are yet, and asking what
    the money BECAME before knowing who got it is the wrong order."""
    ledger = _vault(tmp_path, [("2026-03-04", "MYSTERY CO", "-100.00")])
    assert list(_tiers(ledger).values()) == [TIER_UNENRICHED]
    assert not [q for q in open_questions(ledger)["questions"] if q["kind"] == NATURE]


# --------------------------------------------------------------- direction


def test_the_same_counterparty_means_opposite_things_by_direction(tmp_path):
    """Money OUT to a lender repays borrowing; money IN from one IS the
    borrowing. One counterparty, opposite signs, opposite meanings — carried as
    data on the implication rather than a branch in the queue."""
    ledger = _vault(tmp_path, [("2026-03-04", "ACME LENDING", "-500.00"),
                               ("2026-03-20", "ACME LENDING", "9000.00")])
    _enrich(ledger, "acme lending", "loan_payments",
            implies=list(LOAN_OUT) + list(BORROWED_IN))
    proj = ledger.projection()
    out = [m for m in proj.movements() if m.amount < 0][0]
    inn = [m for m in proj.movements() if m.amount > 0][0]
    assert proj.implication_of(out)["relationship"] == "a home loan"
    assert proj.implication_of(inn)["relationship"] == "money you borrowed"


def test_an_implication_that_does_not_apply_this_way_is_ignored(tmp_path):
    ledger = _vault(tmp_path, [("2026-03-20", "ACME LENDING", "9000.00")])
    _enrich(ledger, "acme lending", "loan_payments", implies=LOAN_OUT)  # outflow only
    proj = ledger.projection()
    assert proj.implication_of(proj.movements()[0]) is None


# ------------------------------------------------------- confidence, and doubt


def test_forced_is_decisive_and_suggested_says_it_is_not(tmp_path):
    """The forced / suggested ladder, reused from the verification findings
    rather than invented: acting confidently and admitting doubt are different
    behaviours and must not share a rung."""
    for confidence, provisional in (("forced", False), ("suggested", True)):
        ledger = _vault(tmp_path / confidence,
                        [("2026-03-08", "ACME BROKERAGE", "-1000.00")])
        _enrich(ledger, "acme brokerage", "investments", implies=[
            {"relationship": "a brokerage account", "major": "asset",
             "on": "outflow", "account_group": "Investments", "compound": False,
             "confidence": confidence, "documents": "", "ask": ""}])
        proj = ledger.projection()
        m = proj.movements()[0]
        assert m.nature == TRANSFER
        assert m.provisional is provisional, confidence


def test_no_implication_means_no_claim(tmp_path):
    """The safe default, and the one the eval guards hardest: a merchant that
    implies nothing must produce nothing. Inventing structure would create
    accounts nobody has, across a whole vault."""
    ledger = _vault(tmp_path, [("2026-03-06", "CORNER CAFE", "-8.00")])
    _enrich(ledger, "corner cafe", "dining", sub="coffee shop")
    proj = ledger.projection()
    assert proj.implication_of(proj.movements()[0]) is None
    assert proj.ruled_accounts() == {}
    assert sum(proj.spending_by_category().values()) == Decimal("8.00")


# ----------------------------------------------------------- the measurement


def test_the_tier_summary_is_the_before_and_after_number(tmp_path):
    from viva.debug.tiers import report

    ledger = _vault(tmp_path, [("2026-03-06", "WHOLE FOODS MKT", "-180.00"),
                               ("2026-03-07", "NETFLIX.COM", "-15.00"),
                               ("2026-03-01", "LENDER ACH PMT", "-4400.00"),
                               ("2026-03-04", "Check # 1201", "-20000.00")])
    _enrich(ledger, "whole foods mkt", "food", sub="grocery")
    _enrich(ledger, "netflix com", "entertainment", sub="streaming")
    _enrich(ledger, "lender ach pmt", "housing", implies=LOAN_OUT, sub="mortgage")
    _enrich(ledger, "check", "other", kind="instrument")

    proj = ledger.projection()
    summary = proj.tier_summary()
    assert summary[TIER_SETTLED]["count"] == 2
    assert summary[TIER_STRUCTURAL]["count"] == 1
    assert summary[TIER_UNKNOWN]["count"] == 1

    text = report(proj)
    assert "settled" in text and "50.0%" in text
    assert "questions the queue would ask: 2" in text     # not 4
    assert "handled without asking" in text


def test_every_cli_reads_dotenv_the_same_way():
    """A CLI that reads VIVA_PASSPHRASE without loading `.env` tells the user to
    set a variable they have already set. One entry point behaving differently
    from its siblings is a small bug with an outsized cost: it makes the tool
    look broken at the exact moment someone is trying to use it for the first
    time."""
    import ast
    import pathlib

    viva = pathlib.Path(__file__).resolve().parents[1] / "viva"
    for module in viva.glob("*.py"):
        source = module.read_text()
        if 'if __name__ == "__main__"' not in source:
            continue                      # not a CLI entry point
        if "VIVA_PASSPHRASE" not in source:
            continue                      # doesn't need the vault
        assert "load_dotenv()" in source, (
            f"{module.name} reads VIVA_PASSPHRASE but never loads .env — it "
            f"will tell the user to set something they already set.")


# ----------------------------------- the rebuild: claims in, fresh vault out


def _claim_vault(tmp_path):
    """A vault built the way a real one is: the model's REPLY is stored, and the
    facts come from parsing it. Only such a vault can be rebuilt for free."""
    import json as _json

    from viva.ingest import RawStore, capture_and_ingest
    from viva.ingest.pipeline import ReadResult
    from viva.ingest.statement import from_model_json

    reply = _json.dumps({
        "doc_type": "checking_statement", "doc_type_confidence": 0.98,
        "account_ref": "Chase Total Checking", "currency": "USD",
        "opening": {"amount_raw": "100000.00", "date_raw": "2026-03-01"},
        "closing": {"amount_raw": "99805.00", "date_raw": "2026-03-31"},
        "transactions": [
            {"date_raw": "2026-03-06", "description": "WHOLE FOODS MKT",
             "amount_raw": "180.00", "balance_effect": "decrease"},
            {"date_raw": "2026-03-07", "description": "NETFLIX.COM",
             "amount_raw": "15.00", "balance_effect": "decrease"}],
        "account_number": "000000001122", "institution": "Chase"})

    raw = RawStore.open(tmp_path / "raw", "pw")
    ledger = Ledger(EventStore.open(tmp_path / "events.jsonl", "pw"))

    def read(_data, did):
        facts, err = from_model_json(reply, did, "US", "USD")
        return ReadResult(doc_type="checking_statement", doc_type_confidence=0.98,
                          facts=facts, error=err, raw_text=reply,
                          model="test", prompt_version="extract:base-v1+checking-v1",
                          input_mode="text+image")

    capture_and_ingest(raw, ledger, b"chk", read, captured_at="2026-04-01")
    return ledger


def test_a_rebuild_replays_claims_through_todays_parsers(tmp_path):
    """The claims layer's whole promise, cashed: a vault reconstructed from
    stored model replies, with no model call and no money spent."""
    from viva.rebuild import claims_by_doc, rebuild

    src = tmp_path / "src"
    ledger = _claim_vault(src)
    _enrich(ledger, "whole foods mkt", "food", sub="grocery")   # a human-era overlay
    assert len(ledger.projection().movements()) == 2

    claims = claims_by_doc(ledger.store.events())
    assert claims, "the source vault must carry claims to rebuild from"

    dest = tmp_path / "dest"
    counts = rebuild(src, dest, "pw", log=lambda *_: None)
    assert counts and sum(counts.values()) == len(claims)

    from viva.vault import Vault
    rebuilt = Vault.open(dest, "pw").ledger.projection()
    # The MONEY came back, parsed fresh from yesterday's reply...
    assert len(rebuilt.movements()) == 2
    # ...and the derived overlay did not. That is the point: a queue with
    # pre-answered questions measures nothing.
    assert rebuilt.merchant_categories() == {}


def test_a_rebuild_never_touches_the_source(tmp_path):
    """Real money, one shot. The old vault stands until the new one is trusted."""
    from viva.rebuild import rebuild
    from viva.vault import Vault

    src = tmp_path / "src"
    ledger = _claim_vault(src)
    before = len(list(ledger.store.events()))

    rebuild(src, tmp_path / "dest", "pw", log=lambda *_: None)
    assert len(list(Vault.open(src, "pw").ledger.store.events())) == before


def test_the_export_captures_what_a_rebuild_cannot_replay(tmp_path):
    """A rebuild replays documents; it cannot replay a person. Anything they
    authored has to be written down first or it is simply gone."""
    from viva.export_rulings import collect
    from viva.ledger.events import MAJOR_ASSET, SCOPE_MERCHANT, ruling_recorded

    ledger = _vault(tmp_path, [("2026-03-04", "BIG MOTORS", "-30000.00")])
    ledger.append(ruling_recorded(SCOPE_MERCHANT, "big motors", "2026-07-25",
                                  legs=[{"major": MAJOR_ASSET, "account": "Assets:Car"}],
                                  said="i bought a car"))
    _enrich(ledger, "other co", "food")            # by=model — NOT a human ruling

    rulings = collect(ledger.store.events())
    assert len(rulings) == 1
    assert rulings[0]["body"]["said"] == "i bought a car"


# ------------------------------------------- the diff: did it learn to say it?


def _key(subject, major, said="x"):
    return {"event_type": "RulingRecorded", "occurred_at": "2026-07-25",
            "body": {"subject": subject, "legs": [{"major": major}], "said": said}}


def test_the_diff_scores_anticipated_missed_and_contradicted(tmp_path):
    """The measure that matters. A product that now says it first has learned;
    one that stays silent has a gap; one that DISAGREES is dangerous, and the
    report puts that case first."""
    from viva.diff_rulings import (ANTICIPATED, CONTRADICTED, MISSED, report,
                                   score)

    ledger = _vault(tmp_path, [("2026-03-01", "LENDER ACH PMT", "-4400.00"),
                               ("2026-03-04", "QUIET CO", "-100.00"),
                               ("2026-03-05", "WRONG CO", "-50.00")])
    _enrich(ledger, "lender ach pmt", "housing", implies=LOAN_OUT)
    _enrich(ledger, "wrong co", "food", implies=[
        {"relationship": "a brokerage account", "major": "asset", "on": "outflow",
         "account_group": "Investments", "compound": False,
         "confidence": "suggested", "documents": "", "ask": ""}])
    _enrich(ledger, "quiet co", "food")            # known, implies nothing

    rows = score(ledger.projection(), [
        _key("lender ach pmt", "liability", "this is my mortgage"),
        _key("quiet co", "expense"),
        _key("wrong co", "liability", "that paid my loan"),
    ])
    got = {r["subject"]: r["verdict"] for r in rows}
    assert got["lender ach pmt"] == ANTICIPATED      # it says it first now
    assert got["quiet co"] == MISSED                 # silence: an honest gap
    assert got["wrong co"] == CONTRADICTED           # it disagrees with the person

    text = report(rows)
    assert text.index("READ THESE FIRST") < text.index("it now says these")
    assert "contradiction" in text


def test_the_diff_writes_nothing(tmp_path):
    """A comparison, not a restore."""
    from viva.diff_rulings import score

    ledger = _vault(tmp_path, [("2026-03-01", "LENDER ACH PMT", "-4400.00")])
    _enrich(ledger, "lender ach pmt", "housing", implies=LOAN_OUT)
    before = len(list(ledger.store.events()))
    score(ledger.projection(), [_key("lender ach pmt", "liability")])
    assert len(list(ledger.store.events())) == before


def test_a_rebuild_that_produces_nothing_says_so(tmp_path):
    """Per-document output is not a result. A rebuild that prints tidy
    per-document lines and a cheerful summary while producing an EMPTY vault has
    reported nothing: a tool must check its own outcome, and the failure has to
    be louder than the progress."""
    from viva.ingest import RawStore
    from viva.ingest.pipeline import ReadResult
    from viva.rebuild import rebuild

    src = tmp_path / "src"
    raw = RawStore.open(src / "raw", "pw")
    ledger = Ledger(EventStore.open(src / "events.jsonl", "pw"))

    from viva.ingest import capture_and_ingest

    def unreadable(_data, did):
        # A stored reply today's parser cannot use — the realistic failure.
        return ReadResult(doc_type="mystery_document", doc_type_confidence=0.4,
                          facts=None, error="no profile", raw_text="{}",
                          model="test", prompt_version="classify-v2")

    capture_and_ingest(raw, ledger, b"doc", unreadable, captured_at="2026-04-01")

    lines = []
    rebuild(src, tmp_path / "dest", "pw", log=lines.append)
    text = "\n".join(lines)
    assert "NOTHING WAS REBUILT" in text
    assert "not a result" in text
    assert "debug.claim" in text          # and what to run next


def test_a_rebuild_stamps_the_classified_doc_type_onto_the_facts(tmp_path):
    """The balance family's extract JSON carries no `doc_type` — that comes from
    the CLASSIFY phase, and the reader stamps it onto the facts after parsing.
    A replay that skips that step brings every statement back as `unknown`,
    which has no projector, so nothing can post. Brokerage and pay stubs are
    unaffected because their extract JSON names its own type, which is what
    makes the failure look selective."""
    from viva.rebuild import rebuild
    from viva.vault import Vault

    src = tmp_path / "src"
    _claim_vault(src)
    dest = tmp_path / "dest"
    counts = rebuild(src, dest, "pw", log=lambda *_: None)

    assert counts.get("posted"), f"expected a posting, got {counts}"
    rebuilt = Vault.open(dest, "pw").ledger.projection()
    assert len(rebuilt.movements()) == 2
    # The classified type survived into the posting — an `unknown` document has
    # no projector and could not have produced movements at all.
    assert rebuilt.movements()[0].kind == "depository"


def test_a_rebuild_sweeps_at_the_end_so_order_does_not_decide(tmp_path):
    """Any ingest order yielding the same posted chain is a CASCADE: a statement
    that cannot connect yet waits for its neighbour. In normal use the neighbour
    arrives later and the heal fires. In a batch run the last arrivals have
    nobody left to trigger them and hold as gaps, so the sweep at the end is
    that promise being kept rather than assumed."""
    import inspect

    from viva import rebuild as mod

    source = inspect.getsource(mod.rebuild)
    assert "sweep(vault.ledger)" in source
    # And it runs BEFORE the vault reports its own outcome, or the count lies.
    assert source.index("sweep(vault.ledger)") < source.index("movements == 0")


def test_a_gap_on_arrival_is_not_a_gap_in_the_vault(tmp_path):
    """A gap counted on arrival is TRANSIENT. A statement arriving before its
    neighbour is a gap at that instant and posts the moment the neighbour heals
    it — the cascade working as designed.

    Arrival counters keep saying "gap" forever, so a sum of MOMENTS read as a
    STATE accuses correct code of a bug. Report the vault's final state; never
    the sum of moments."""
    from viva.rebuild import rebuild
    from viva.vault import Vault

    src = tmp_path / "src"
    _claim_vault(src)
    counts = rebuild(src, tmp_path / "dest", "pw", log=lambda *_: None)

    proj = Vault.open(tmp_path / "dest", "pw").ledger.projection()
    assert list(proj.gap_holds()) == []      # whatever the arrival counters said
    assert counts.get("posted")




def test_an_unshareable_counterparty_is_unknown_not_unenriched(tmp_path):
    """`unenriched` promises "we'll identify this later" — but sending a peer
    name or a cheque number to the commons is forbidden, so enrichment will
    never see those counterparties and they could never become `settled`.

    `unknown` is the truth about them, and it is also the tier that asks one
    transaction at a time, which is exactly right for a Zelle or a check."""
    ledger = _vault(tmp_path, [("2026-03-04", "ZELLE PAYMENT TO JOHN", "-200.00"),
                               ("2026-03-05", "MYSTERY CO", "-100.00")])
    proj = ledger.projection()
    tiers = {m.description: proj.tier_of(m) for m in proj.movements()}
    assert tiers["ZELLE PAYMENT TO JOHN"] == TIER_UNKNOWN
    # A plain business we simply have not enriched yet is still `unenriched` —
    # that one really will be identified later.
    assert tiers["MYSTERY CO"] == TIER_UNENRICHED
