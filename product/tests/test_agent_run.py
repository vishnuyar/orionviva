"""The agent wakes, spends, and remembers — especially what it could not do.

`assess` being deterministic is what makes re-assessing on every wake safe. It is
also what makes an unremembered failure infinite: the same proposal, the same
three calls, the same refusal, forever. Most of what follows tests the memory
rather than the action, because the memory is the part that turns two correct
components into a loop that terminates.

Nothing here calls a model. The extractor is a function under the test's control,
which is also how the call COUNT is checked — an agent that reports estimates as
actuals will agree with the plan and disagree with the invoice.
"""

from decimal import Decimal

import pytest
from merchantcore.profile import Profile, ProfileStore, Template
from viva.agent import Action, cool, stake_of, wake
from viva.agent.act import Meter
from viva.ingest import (RawStore, ReadResult, StatementFacts, TxnFact,
                         capture_and_ingest)
from viva.ledger import EventStore, Ledger
from viva.ledger.events import agent_acted
from viva.vault import Vault


# --------------------------------------------------------------- the event


def _act(ledger, rule="induce_missing", target="Chase/depository",
         outcome="refused", stake=None, calls=3, **kw):
    ledger.append(agent_acted(rule=rule, kind="induce", target=target,
                              outcome=outcome, occurred_at="2026-07-29",
                              calls=calls, stake=stake or {"distinct_lines": 41},
                              **kw))


def _ledger(tmp_path):
    return Ledger(EventStore.open(tmp_path / "events.jsonl", "pw"))


def test_an_agent_action_is_recorded_and_projected(tmp_path):
    ledger = _ledger(tmp_path)
    _act(ledger, outcome="done", produced="chase-depository-v1", calls=2,
         detail="27 template(s), 84.0% held-out")
    entry = ledger.projection().agent_log()[0]
    assert entry["outcome"] == "done"
    assert entry["produced"] == "chase-depository-v1"
    assert entry["calls"] == 2
    assert entry["occurred_at"] == "2026-07-29"


def test_the_event_refuses_an_outcome_it_does_not_understand():
    with pytest.raises(ValueError):
        agent_acted("r", "induce", "t", "sort-of", "2026-07-29")
    with pytest.raises(ValueError):
        agent_acted("", "induce", "t", "done", "2026-07-29")
    with pytest.raises(ValueError):
        agent_acted("r", "induce", "t", "done", "2026-07-29", calls=-1)


def test_the_log_keeps_every_attempt_and_the_lifetime_bill(tmp_path):
    """Not collapsed to the latest. The cooldown only needs the last one; a
    person asking 'what has this thing been doing' needs all of them, and that
    second question is why the event exists at all."""
    ledger = _ledger(tmp_path)
    _act(ledger, outcome="refused", calls=3)
    _act(ledger, outcome="done", calls=1, produced="chase-depository-v2")
    proj = ledger.projection()
    assert len(proj.agent_log()) == 2
    assert proj.agent_calls_spent() == 4
    assert proj.agent_attempts()[("induce_missing", "Chase/depository")]["outcome"] == "done"


def test_the_journal_carries_no_descriptor_and_no_amount(tmp_path):
    """An agent's journal is not a place for the work's inputs to accumulate.
    The stake is counts; the artifact is an id."""
    ledger = _ledger(tmp_path)
    _act(ledger, outcome="done", produced="chase-depository-v1")
    body = ledger.projection().agent_log()[0]
    assert set(body["stake"]) <= {"distinct_lines", "movements", "unknown_brands",
                                  "profile", "measured", "recent", "drop",
                                  "machinery"}
    assert all(isinstance(v, (int, float, str)) for v in body["stake"].values())


# --------------------------------------------------------------- the cooldown


def _induce_action(lines=41, movements=900):
    return Action(rule="induce_missing", kind="induce", target="Chase/depository",
                  why="…", estimated_calls=3,
                  evidence={"distinct_lines": lines, "movements": movements})


def test_a_refusal_against_unchanged_evidence_is_not_retried(tmp_path):
    """The whole reason the event exists. The write-guard refuses a version that
    covers less than the one it succeeds, raises, and writes nothing — so without
    a record, `assess` proposes the identical three-call induction on every wake,
    forever, silently."""
    ledger = _ledger(tmp_path)
    action = _induce_action()
    _act(ledger, outcome="refused", stake=stake_of(action))
    live, cooled = cool([action], ledger.projection().agent_attempts())
    assert not live and len(cooled) == 1
    assert cooled[0][1]["outcome"] == "refused"


def test_new_evidence_wakes_it_again_and_a_timer_never_does(tmp_path):
    """A snapshot, not a clock — the same rule a declined question uses. 'Wait
    six hours' is arbitrary; new lines are a reason."""
    ledger = _ledger(tmp_path)
    _act(ledger, outcome="refused", stake=stake_of(_induce_action(lines=41)))
    attempts = ledger.projection().agent_attempts()
    live, cooled = cool([_induce_action(lines=58)], attempts)
    assert len(live) == 1 and not cooled


def test_success_never_holds_anything_back(tmp_path):
    """A successful action changed the world, so `assess` stops proposing it on
    its own. If it is proposing it again, something really is different."""
    ledger = _ledger(tmp_path)
    action = _induce_action()
    _act(ledger, outcome="done", stake=stake_of(action))
    live, cooled = cool([action], ledger.projection().agent_attempts())
    assert len(live) == 1 and not cooled


def test_a_cooldown_is_per_target_not_global(tmp_path):
    ledger = _ledger(tmp_path)
    a = _induce_action()
    b = Action(rule="induce_missing", kind="induce", target="Meridian/liability",
               why="…", estimated_calls=3, evidence={"distinct_lines": 41,
                                                     "movements": 900})
    _act(ledger, target="Chase/depository", outcome="refused", stake=stake_of(a))
    live, cooled = cool([a, b], ledger.projection().agent_attempts())
    assert [x.target for x in live] == ["Meridian/liability"]
    assert [x.target for x, _ in cooled] == ["Chase/depository"]


def test_the_stake_rounds_floats_so_recomputation_is_not_new_evidence():
    a = Action(rule="reinduce_drifted", kind="reinduce", target="X/depository",
               why="…", evidence={"drop": 0.20000000000000004, "recent": 0.7199999})
    stake = stake_of(a)
    assert stake["drop"] == 0.2 and stake["recent"] == 0.72


# --------------------------------------------------------------- the meter


def test_calls_are_counted_not_estimated():
    """`estimated_calls` is a property of the plan and `calls` is what the
    invoice will agree with. Induction stops as soon as a round explains nothing
    new, so a three-round budget routinely spends fewer."""
    meter = Meter()
    counted = meter.wrap(lambda p: "{}")
    counted("a"), counted("b")
    assert meter.calls == 2


# --------------------------------------------------------------- a whole wake


def _vault_with(tmp_path, descriptors):
    raw = RawStore.open(tmp_path / "raw", "pw")
    ledger = Ledger.open(tmp_path / "events.jsonl", "pw")
    txns = [TxnFact(f"2026-03-{(i % 27) + 1:02d}", d, Decimal("-10.00"))
            for i, d in enumerate(descriptors)]
    facts = StatementFacts(
        doc_id="", doc_type="checking_statement", doc_type_confidence=0.98,
        account_ref="Chase Total Checking", currency="USD",
        opening_amount=Decimal("10000.00"), opening_date="2026-03-01",
        closing_amount=Decimal("10000.00") - Decimal("10.00") * len(txns),
        closing_date="2026-03-31", transactions=txns,
        account_number="000000001122", institution="Chase")

    def read(_data, did):
        facts.doc_id = did
        return ReadResult(facts.doc_type, 0.98, facts)

    capture_and_ingest(raw, ledger, b"doc", read, captured_at="2026-04-01")
    return Vault(ledger=ledger, raw=raw, directory=tmp_path)


def _many_lines(n=45):
    return [f"CARD PURCHASE 03/{(i % 27) + 1:02d} SHOP{chr(65 + i % 26)}{i} "
            f"PLANO TX CARD 1234" for i in range(n)]


@pytest.fixture()
def homed(tmp_path, monkeypatch):
    """Point every piece of learned merchant knowledge at a scratch directory.

    Not tidiness: the real ones live outside any working tree precisely so they
    cannot be written by accident, and a test that wrote into them would teach a
    developer's machine things no statement said."""
    monkeypatch.setenv("MERCHANTCORE_HOME", str(tmp_path / "mc"))
    monkeypatch.setenv("VIVA_PROFILES", str(tmp_path / "mc" / "profiles"))
    monkeypatch.setenv("VIVA_CATALOG", str(tmp_path / "mc" / "catalog.json"))
    monkeypatch.delenv("VIVA_MODEL", raising=False)
    monkeypatch.delenv("VIVA_MODEL_ADAPTER", raising=False)
    return tmp_path


def test_a_dry_run_spends_nothing_and_writes_nothing(homed, tmp_path):
    vault = _vault_with(tmp_path / "v", _many_lines())
    before = len(list(vault.ledger.events()))
    run = wake(vault, dry_run=True)
    assert run.dry_run and run.calls_spent == 0
    assert len(list(vault.ledger.events())) == before
    assert run.considered, "a vault with 45 distinct lines has something to propose"


def test_without_a_model_the_work_is_deferred_and_said_so(homed, tmp_path):
    """Not a crash and not a silent no-op. An agent that cannot spend should
    report what it would have done — that is the more useful diagnostic."""
    vault = _vault_with(tmp_path / "v", _many_lines())
    run = wake(vault)
    assert run.deferred and "no model configured" in run.could_not_spend
    assert not run.performed and run.calls_spent == 0


def test_a_refused_induction_is_recorded_and_not_repeated(homed, tmp_path,
                                                          monkeypatch):
    """End to end: the model answers with nothing usable, the calls are spent,
    the refusal is recorded, and the next wake holds it back instead of paying
    again."""
    monkeypatch.setenv("VIVA_MODEL", "test-model")
    monkeypatch.setenv("VIVA_MODEL_ADAPTER", "openai-compatible")
    calls = {"n": 0}

    def _never_useful(_prompt):
        calls["n"] += 1
        return "{}"                      # parses, yields no template

    monkeypatch.setattr("viva.agent.act._extractor", lambda name: _never_useful)
    vault = _vault_with(tmp_path / "v", _many_lines())

    first = wake(vault, best_of_override=1)
    by_kind = {a.kind: o.outcome for a, o in first.performed}
    assert by_kind["induce"] == "refused"
    # The enrichment in the same wake asks about brands and gets nothing back,
    # which is a different failure with the same consequence: paid for, useless.
    assert by_kind.get("enrich") == "failed"
    assert first.calls_spent == calls["n"] > 0
    assert {e["outcome"] for e in vault.ledger.projection().agent_log()} == {
        "refused", "failed"}

    spent = calls["n"]
    second = wake(vault, best_of_override=1)
    assert not second.performed, "the same refusal must not be bought twice"
    assert calls["n"] == spent
    # The induction is held back by the cooldown; the enrichment is not even
    # proposed, because every brand it would ask about has now been asked about.
    assert [a.target for a, _ in second.cooled] == ["Chase/depository"]
    assert all(a.kind != "enrich" for a in second.considered)


def test_the_budget_is_a_ceiling_on_what_a_wake_may_spend(homed, tmp_path,
                                                          monkeypatch):
    monkeypatch.setenv("VIVA_MODEL", "test-model")
    monkeypatch.setenv("VIVA_MODEL_ADAPTER", "openai-compatible")
    monkeypatch.setattr("viva.agent.act._extractor", lambda name: (lambda p: "{}"))
    vault = _vault_with(tmp_path / "v", _many_lines())
    run = wake(vault, remaining_calls=0, best_of_override=1)
    assert not run.performed
    assert any(a.estimated_calls > 0 for a in run.deferred)


def test_an_existing_grammar_is_not_re_induced(homed, tmp_path):
    """`assess`'s own rule, checked through the runner: the work an agent skips
    is as much a part of it as the work it does."""
    from viva.induce_profile import profile_store
    vault = _vault_with(tmp_path / "v", _many_lines())
    store = profile_store()
    store.write(Profile("Chase", "depository", "v1",
                        [Template("CARD PURCHASE {date} {brand} {city} "
                                  "{region} CARD {account_ref}")],
                        measured=0.95))
    run = wake(vault, dry_run=True)
    assert all(a.kind != "induce" for a in run.considered)


# --------------------------------------------------- the catalog's memory


def test_a_merchant_the_model_could_not_name_is_not_asked_about_again(tmp_path):
    """A chunk whose reply will not parse costs a call and produces nothing, and
    nothing about the next run makes it likelier to parse. Invisible when a
    person runs enrichment by hand; a recurring bill the moment an agent does."""
    from merchantcore.catalog import Catalog
    cat = Catalog(tmp_path / "catalog.json")
    cat.submit([("obscure co", "OBSCURE CO PLANO TX")])
    assert "obscure co" in cat.pending()

    cat.mark_unanswered(["obscure co"])
    assert "obscure co" not in cat.pending()
    assert "obscure co" in cat.queued(), "still queued — it is simply not asked"

    # ...and it survives a reload, which is the point of persisting it.
    assert "obscure co" not in Catalog(tmp_path / "catalog.json").pending()


def test_a_better_example_retires_an_old_non_answer(tmp_path):
    """The same snapshot rule again: quiet while nothing has changed, awake the
    moment it has. A brand seen once more may now agree on a city."""
    from merchantcore.catalog import Catalog
    cat = Catalog(tmp_path / "catalog.json")
    cat.submit([("obscure co", "OBSCURE CO")])
    cat.mark_unanswered(["obscure co"])
    assert not cat.pending()

    cat.submit([("obscure co", "OBSCURE CO PLANO TX")])
    assert "obscure co" in cat.pending()


def test_submitting_the_same_thing_twice_is_still_free(tmp_path):
    from merchantcore.catalog import Catalog
    cat = Catalog(tmp_path / "catalog.json")
    assert cat.submit([("shop", "SHOP PLANO TX")]) == 1
    assert cat.submit([("shop", "SHOP PLANO TX")]) == 0


def test_a_ceiling_too_small_for_one_induction_defers_it(homed, tmp_path):
    """Deferral, not a cheaper attempt. An agent that quietly downgraded
    `best_of` to fit a budget would report a grammar chosen from three
    candidates and have chosen it from one."""
    from viva.agent.policy import CALLS, RULES
    vault = _vault_with(tmp_path / "v", _many_lines())
    full = CALLS["induce"] * RULES["induce_missing"]["best_of"]
    run = wake(vault, remaining_calls=full - 1, dry_run=True)
    assert not [a for a in run.performed if a[0].kind == "induce"]
    assert any(a.kind == "induce" and a.estimated_calls == full
               for a in run.deferred)


def test_the_default_ceiling_finishes_an_ordinary_vault(homed, tmp_path):
    """A ceiling stops a runaway. The runaway this agent can have is REPETITION,
    which `cool()` stops directly — so a ceiling low enough to halt the ordinary
    work of an ordinary vault is not safety, it is a chore. An agent whose
    default settings need a person to say 'continue' is a script with prose."""
    from viva.agent.policy import CALLS, RULES
    from viva.agent.run import DEFAULT_BUDGET_CALLS
    one_grammar = CALLS["induce"] * RULES["induce_missing"]["best_of"]
    assert DEFAULT_BUDGET_CALLS >= one_grammar * 6, \
        "six institution/kind pairs is an ordinary vault, not a large one"

    vault = _vault_with(tmp_path / "v", _many_lines())
    run = wake(vault, dry_run=True)
    assert not run.deferred, "nothing this small should ever need a second wake"


def test_a_deferral_is_not_a_refusal_and_is_never_cooled(homed, tmp_path):
    """Over-budget work must come back on the next wake. Cooling it would turn
    a ceiling into a permanent refusal, which is how an agent silently stops
    doing half its job."""
    vault = _vault_with(tmp_path / "v", _many_lines())
    tight = wake(vault, remaining_calls=1, dry_run=True)
    assert tight.deferred and not tight.cooled
    assert not vault.ledger.projection().agent_log(), \
        "a deferral writes nothing, so nothing can remember it as a failure"


# ------------------------------------- a truncated reply is not an answer


def test_a_chunk_that_did_not_parse_is_asked_again(tmp_path):
    """The first live agent run hit `Expecting ',' delimiter: line 298` on one
    chunk of forty. Nothing about those forty merchants failed — the reply was
    truncated. Marking them 'asked and unanswered' would have silenced a sixth
    of the batch permanently, on a transport error."""
    from merchantcore.enrich import Enricher

    good = '{"shop a": {"canonical_name": "Shop A", "category": "shopping"}}'
    replies = iter([good, '{"shop b": {"canonical_name": "Shop'])   # truncated
    enricher = Enricher(lambda p: next(replies), chunk_size=1)
    records = enricher.enrich({"shop a": "SHOP A", "shop b": "SHOP B"})

    assert set(records) == {"shop a"}
    assert enricher.unparsed == ["shop b"], \
        "a reply that did not parse names its keys as transport, not silence"


def test_a_model_that_looked_and_declined_is_not_asked_again(tmp_path):
    """The other half of the same distinction: this reply parsed perfectly and
    simply had nothing to say about the merchant. Asking again with the same
    example buys the same silence."""
    from merchantcore.enrich import Enricher

    enricher = Enricher(lambda p: '{"shop a": {"canonical_name": "Shop A", '
                                  '"category": "shopping"}}', chunk_size=2)
    records = enricher.enrich({"shop a": "SHOP A", "shop b": "SHOP B"})
    assert set(records) == {"shop a"}
    assert enricher.unparsed == []


# ------------------------------------- a fix must not be held back by the bug


def test_changing_the_machinery_lifts_a_cooldown(tmp_path):
    """A refusal means "this evidence, through this machinery, produced
    nothing". Fix a pack rule or bump a prompt and that sentence is no longer
    the one that was tested — so the refusal has to expire by itself. Without
    this, every code fix would be silently held back by the memory of the bug it
    fixed, and only a person who remembered could release it."""
    ledger = _ledger(tmp_path)
    action = _induce_action()
    old = {**stake_of(action), "machinery": "induce-profile-v0+prof-v0+pack-v0"}
    _act(ledger, outcome="refused", stake=old)
    live, cooled = cool([action], ledger.projection().agent_attempts())
    assert len(live) == 1 and not cooled


def test_the_stake_names_the_machinery_that_would_act(tmp_path):
    from merchantcore.enrich import ENRICHMENT_VERSION
    from merchantcore.induce import machinery_version
    assert stake_of(_induce_action())["machinery"] == machinery_version()
    enrich = Action(rule="enrich_unknown", kind="enrich", target="brands",
                    why="…", evidence={"unknown_brands": 40})
    assert stake_of(enrich)["machinery"] == ENRICHMENT_VERSION
