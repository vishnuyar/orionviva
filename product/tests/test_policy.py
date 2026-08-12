"""The rules an agent reads instead of a person typing commands.

`assess` is pure — no model calls, no writes, no questions — so an agent can
re-run it on every wake and get the same proposals. These tests pin the division
of labour as much as the logic: what the agent may do alone, what waits for a
person, and what it must refuse to do at all.
"""

import pytest
from merchantcore.profile import Profile, ProfileStore, Template
from viva.agent import AUTONOMOUS, NEEDS_RATIFICATION, assess, within_budget


def _lines(n, prefix="LINE"):
    return {f"{prefix} {chr(65 + i // 26)}{chr(65 + i % 26)} SOMETHING": 2
            for i in range(n)}


def _store(tmp_path, **profiles):
    store = ProfileStore(tmp_path)
    for pair, measured in profiles.items():
        inst, kind = pair.split("/")
        store.write(Profile(inst, kind, "v1",
                            [Template("PAID {brand} {city} {region}")],
                            measured=measured))
    return store


def _kinds(actions):
    return {a.target: a.kind for a in actions}


# --- what the agent proposes ------------------------------------------------

def test_a_bank_with_enough_lines_and_no_grammar_is_proposed(tmp_path):
    acts = assess({("Chase", "depository"): _lines(60)}, {}, _store(tmp_path))
    assert _kinds(acts) == {"Chase/depository": "induce"}
    assert acts[0].autonomous and acts[0].estimated_calls > 0


def test_too_few_lines_is_reported_as_waiting_not_omitted(tmp_path):
    """An agent that reports nothing to do is indistinguishable from one that is
    broken. Waiting is a state, and it says how far off it is."""
    acts = assess({("Chase", "depository"): _lines(9)}, {}, _store(tmp_path))
    assert _kinds(acts) == {"Chase/depository": "wait"}
    assert acts[0].estimated_calls == 0
    assert acts[0].evidence["needed"] > acts[0].evidence["distinct_lines"]


def test_a_grammar_that_stopped_keeping_up_is_proposed_for_reinduction(tmp_path):
    store = _store(tmp_path, **{"Meridian/liability": 0.92})
    fresh = {f"NEW SHAPE {chr(65 + i)} Z": 4 for i in range(30)}
    acts = assess({("Meridian", "liability"): fresh},
                  {("Meridian", "liability"): fresh}, store)
    assert _kinds(acts) == {"Meridian/liability": "reinduce"}
    assert acts[0].evidence["drop"] > 0.15


def test_a_grammar_still_working_proposes_nothing(tmp_path):
    store = _store(tmp_path, **{"Meridian/liability": 0.95})
    working = {f"PAID SHOP{chr(65 + i)} PLANO TX": 3 for i in range(26)}
    assert assess({("Meridian", "liability"): working},
                  {("Meridian", "liability"): working}, store) == []


def test_a_kind_that_names_no_party_is_never_proposed(tmp_path):
    # An investment activity line describes a trade against a security. There is
    # no counterparty in it, so there is nothing for a grammar to find.
    assert assess({("Fidelity", "investment"): _lines(200)}, {},
                  _store(tmp_path)) == []


def test_grammars_are_ordered_before_brands(tmp_path):
    """Not cosmetic. A grammar changes what a brand IS, so enriching first buys
    records keyed on a string the next action rewrites."""
    acts = assess({("Chase", "depository"): _lines(60)}, {}, _store(tmp_path),
                  unknown_brands=50)
    assert [a.kind for a in acts] == ["induce", "enrich"]


# --- the division of labour -------------------------------------------------

def test_mechanics_are_autonomous_and_publishing_is_not():
    """Blast radius decides who ratifies. A wrong grammar on this vault is wrong
    for one person and drift will catch it. A wrong grammar in the commons is
    wrong for everybody, and no automated check catches the failure that
    matters — a grammar can cover 90% of lines while putting cities in {brand},
    and only reading it finds that."""
    assert {"induce_missing", "reinduce_drifted"} <= AUTONOMOUS
    assert not (AUTONOMOUS & NEEDS_RATIFICATION)
    assert {"publish_grammar", "publish_merchant"} <= NEEDS_RATIFICATION


def test_enrichment_does_not_act_unattended_while_the_crossing_is_ungated():
    """Blast radius again, and the reason is a person's name rather than a
    grammar. An enrichment hint carries a party's name whenever a slot the
    model labelled impersonal holds one, and the crossing writes it to an
    unencrypted queue before any model call, on a path nobody is reading.

    The corroboration gate narrows that crossing and does not close it: a name
    an ACH head recovers as a company name still crosses. So enrichment is
    proposed and waits, and what restores it here says first what closed the
    crossing."""
    assert "enrich_unknown" not in AUTONOMOUS


def test_assess_asks_nobody_anything(tmp_path):
    # Nothing here decides what a movement MEANS. That goes to the question
    # queue and to a person, because only a person knows whether five hundred to
    # a friend was rent or a loan.
    acts = assess({("Chase", "depository"): _lines(60)}, {}, _store(tmp_path),
                  unknown_brands=5)
    assert all(a.kind != "ask" for a in acts)


def test_assess_is_pure_and_repeatable(tmp_path):
    """An agent re-assesses on every wake. Two runs a minute apart must propose
    the same things, or it will oscillate."""
    store = _store(tmp_path, **{"Meridian/liability": 0.9})
    pairs = {("Chase", "depository"): _lines(60),
             ("Citi", "liability"): _lines(5, "S"),
             ("Meridian", "liability"): _lines(40, "PAID")}
    first = [a.to_dict() for a in assess(pairs, {}, store, unknown_brands=12)]
    second = [a.to_dict() for a in assess(pairs, {}, store, unknown_brands=12)]
    assert first == second


# --- the ceiling ------------------------------------------------------------

def test_a_budget_stops_a_runaway_before_it_costs_anything(tmp_path):
    """Counted in calls, not currency: a call count is a property of the plan,
    while a price is the adapter's business and changes without warning."""
    acts = assess({("Chase", "depository"): _lines(60),
                   ("Meridian", "liability"): _lines(60, "PAID")}, {},
                  _store(tmp_path), unknown_brands=200)
    fits, deferred = within_budget(acts, remaining_calls=3)
    assert sum(a.estimated_calls for a in fits) <= 3
    assert deferred and all(a.estimated_calls > 0 for a in deferred)


def test_waiting_never_consumes_budget(tmp_path):
    acts = assess({("Citi", "liability"): _lines(4)}, {}, _store(tmp_path))
    fits, deferred = within_budget(acts, remaining_calls=0)
    assert len(fits) == 1 and not deferred        # reported even at zero budget


def test_the_rules_are_data_a_person_can_edit(tmp_path):
    # Tuning the agent must be editing a value, not editing behaviour — the same
    # choice this project already made for the doc-type and expectations
    # registries.
    strict = {"induce_missing": {"min_lines": 500, "why": "stricter"}}
    acts = assess({("Chase", "depository"): _lines(60)}, {}, _store(tmp_path),
                  rules=strict)
    assert acts[0].kind == "wait" and acts[0].evidence["needed"] == 500


def test_the_estimate_counts_attempts_times_rounds(tmp_path):
    """The bug the first real dry run caught, pinned so it cannot come back.

    `CALLS["induce"]` is calls per ATTEMPT — merchantcore's rounds — and
    `best_of` is how many attempts. They multiply. Budgeting three inductions at
    three calls each against a ceiling of twelve, and then running three attempts
    apiece, would have spent twenty-seven. A ceiling computed from an estimate
    that omits a multiplier is not a ceiling."""
    from viva.agent.policy import CALLS, RULES
    acts = assess({("Chase", "depository"): _lines(60)}, {}, _store(tmp_path))
    assert acts[0].estimated_calls == CALLS["induce"] * RULES["induce_missing"]["best_of"]

    once = {"induce_missing": {**RULES["induce_missing"], "best_of": 1}}
    cheaper = assess({("Chase", "depository"): _lines(60)}, {}, _store(tmp_path),
                     rules=once)
    assert cheaper[0].estimated_calls == CALLS["induce"]
