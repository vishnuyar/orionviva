"""Executable boundary between the typed ledger vocabulary and SQL families."""

import ast
import inspect
import json
import re
from pathlib import Path

import pytest

from viva.ledger import events
from viva.ledger import EventStore, Provenance
from viva.ledger.projection import core
from viva.read_store import ReadStore, ReadStoreError
from viva.read_store import store


# Each row names the primary materialization, its representation, and the
# desktop consumers whose field-level contracts require separate parity proof.
FAMILIES = {
    "AccountOpened": ("accounts", "typed", "Overview Accounts Statements Plans"),
    "AccountIdentityObserved": ("accounts", "typed", "Overview Accounts Statements"),
    "OpeningBalanceObserved": ("balance_observations", "typed", "Overview Accounts Statements Trust"),
    "ClosingBalanceObserved": ("balance_observations", "typed", "Overview Accounts Statements Trust"),
    "TransactionRecorded": ("transactions", "typed+ordered-child", "Overview Accounts Activity Spending Statements Trust"),
    "PositionObserved": ("positions", "typed", "Overview Accounts Activity Statements Trust"),
    "DocumentCaptured": ("documents", "typed", "Statements Review Trust"),
    "ReadRecorded": ("document_reads", "typed+body-json", "Statements Review Trust"),
    "StatementHeld": ("document_holds", "typed+nested-json", "Statements Review Conversation"),
    "BrokerageActivityHeld": ("document_holds", "typed+nested-json", "Statements Review Conversation"),
    "BrokerageActivityResolved": ("document_hold_resolutions", "typed", "Statements Review"),
    "CorrectionApplied": ("document_corrections", "typed", "Statements Review Activity"),
    "TransferLinked": ("transfer_history", "typed+nested-json", "Activity Spending Review Trust"),
    "TransferUnlinked": ("transfer_history", "typed+nested-json", "Activity Spending Review Trust"),
    "TransferSuggested": ("transfer_history", "typed+nested-json", "Activity Review Conversation"),
    "CategoryAssigned": ("category_history", "typed", "Activity Spending Review"),
    "MerchantCategorized": ("merchant_history", "typed+nested-json", "Activity Spending Review"),
    "MerchantEnriched": ("merchant_history", "typed+nested-json", "Activity Spending Review"),
    "MovementTagged": ("tag_history", "typed+ordered-json", "Activity Spending Review"),
    "RulingRecorded": ("ruling_history", "typed+ordered-json", "Overview Activity Spending Review Trust"),
    "AccountAliasConfirmed": ("account_alias_history", "typed+ordered-json", "Accounts Statements Review"),
    "QuestionDeclined": ("review_decisions", "body-json", "Review Conversation"),
    "FindingSetAside": ("review_decisions", "body-json", "Review Conversation"),
    "GoalCreated": ("goal_event_history", "typed+body-json", "Overview Plans Review Conversation"),
    "GoalTermsChanged": ("goal_event_history", "typed+body-json", "Overview Plans Review Conversation"),
    "GoalFundsReserved": ("goal_event_history", "typed+body-json", "Overview Plans Review Conversation"),
    "GoalFundsReleased": ("goal_event_history", "typed+body-json", "Overview Plans Review Conversation"),
    "GoalStateChanged": ("goal_event_history", "typed+body-json", "Overview Plans Review Conversation"),
    "GoalProposalRecorded": ("goal_proposal_history", "body-json", "Plans Review Conversation"),
    "GoalProposalResolved": ("goal_proposal_history", "body-json", "Plans Review Conversation"),
    "ConversationTurnOpened": ("conversation_turn_history", "body-json", "Conversation Review"),
    "ConversationTurnSettled": ("conversation_turn_history", "body-json", "Conversation Review"),
    "ConversationProposalRecorded": ("conversation_proposal_history", "body-json", "Conversation Review"),
    "ConversationProposalResolved": ("conversation_proposal_history", "body-json", "Conversation Review"),
    "AgentActed": ("agent_action_history", "typed+body-json", "Trust Review"),
}


BODY_FIELDS = {
    "AccountAliasConfirmed": "account_id alias_key by doc_id kind learn_signal match_label match_names",
    "AccountIdentityObserved": "account_id account_names account_number institution",
    "AccountOpened": "account_id account_names account_number currency institution jurisdiction kind name origin",
    "AgentActed": "by calls detail kind outcome produced replaced rule stake target",
    "BrokerageActivityHeld": "doc_id facts finding reason",
    "BrokerageActivityResolved": "doc_id",
    "CategoryAssigned": "by category category_by category_grade descriptor grade movement_key nature subcategory subcategory_by subcategory_grade",
    "ClosingBalanceObserved": "account_id amount confirmed_by",
    "ConversationProposalRecorded": "proposal proposal_id question_id stake summary turn_id",
    "ConversationProposalResolved": "message outcome proposal_id reason turn_id",
    "ConversationTurnOpened": "context_mode kind mirrored prompt question_id said turn_id",
    "ConversationTurnSettled": "answer message outcome proposal_id reason turn_id",
    "CorrectionApplied": "by doc_id from target to",
    "DocumentCaptured": "byte_len doc_id doc_type doc_type_confidence filename",
    "FindingSetAside": "by finding_id kind stake",
    "GoalCreated": "contribution_day currency goal_id kind monthly_contribution proposal_id target_amount target_date title",
    "GoalFundsReleased": "account_id amount goal_id proposal_id reason",
    "GoalFundsReserved": "account_id amount goal_id proposal_id",
    "GoalProposalRecorded": "proposal proposal_id stake summary verb",
    "GoalProposalResolved": "outcome proposal_id reason",
    "GoalStateChanged": "goal_id proposal_id state",
    "GoalTermsChanged": "contribution_day currency goal_id kind monthly_contribution proposal_id target_amount target_date title",
    "MerchantCategorized": "by category grade merchant",
    "MerchantEnriched": "aliases attributes by canonical_name category category_by category_grade grade merchant subcategory subcategory_by subcategory_grade",
    "MovementTagged": "by scope subject tags",
    "OpeningBalanceObserved": "account_id amount",
    "PositionObserved": "account_id cost_basis currency grade instrument market_value units valuation_class",
    "QuestionDeclined": "amount by count kind pack_version question_id reason",
    "ReadRecorded": "cost_usd doc_id input_mode input_tokens model model_role output_tokens parse_error parse_ok phase prompt_version resolved_model response_text usage_reported",
    "RulingRecorded": "by corroborates currency grade legs prompt_version said same_as scope subject value",
    "StatementHeld": "doc_id facts finding reason",
    "TransactionRecorded": "description postings tags",
    "TransferLinked": "a b by evidence grade status",
    "TransferSuggested": "a candidates evidence status",
    "TransferUnlinked": "a b by status",
}


def _declared_constructor_families():
    tree = ast.parse(inspect.getsource(events))
    declared = set()
    for function in (node for node in tree.body if isinstance(node, ast.FunctionDef)):
        if function.name.startswith("_"):
            continue
        for node in ast.walk(function):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == "Event" and node.args):
                continue
            first = node.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                declared.add(first.value)
            elif isinstance(first, ast.Name):
                value = getattr(events, first.id, None)
                assert isinstance(value, str), (function.name, first.id)
                declared.add(value)
            else:
                raise AssertionError((function.name, ast.dump(first)))
    return declared


def _assert_complete_register(declared):
    assert declared == set(FAMILIES)


def test_typed_vocabulary_has_exactly_one_materialized_destination_register():
    declared = _declared_constructor_families()
    _assert_complete_register(declared)
    projection = inspect.getsource(core.ProjectionCore._apply)
    projected = set(re.findall(r'["\']([A-Z][A-Za-z]+)["\']', projection))
    assert declared - {"CorrectionApplied"} <= projected
    materializer = inspect.getsource(store.ReadStore._materialize_event)
    for family, (table, representation, destinations) in FAMILIES.items():
        assert family in materializer, family
        assert f"INSERT INTO {table}" in materializer, (family, table)
        assert representation and destinations
        assert set(destinations.split()) <= {
            "Overview", "Accounts", "Activity", "Spending", "Statements",
            "Plans", "Review", "Conversation", "Trust",
        }


def test_register_refuses_a_new_unmapped_typed_family():
    declared = _declared_constructor_families() | {"FutureTypedFamily"}
    with pytest.raises(AssertionError):
        _assert_complete_register(declared)


def test_representative_typed_events_cover_every_registered_field():
    from product.tests import test_read_store_typed_field_coverage as typed
    from product.tests import test_read_store_overlay_field_coverage as overlays
    from product.tests import test_read_store_document_field_coverage as documents

    corpus = (_json_family_corpus() + typed._corpus() + overlays._corpus()
              + documents._corpus())
    observed = {}
    for event in corpus:
        if event.event_type == "FutureUnknown":
            continue
        observed.setdefault(event.event_type, set()).update(event.body)
    assert set(BODY_FIELDS) == set(FAMILIES) == set(observed)
    for family, names in BODY_FIELDS.items():
        assert set(names.split()) == observed[family], family


PASSPHRASE = "correct horse battery staple"
JSON_BODY_TABLES = (
    "goal_event_history", "goal_proposal_history", "conversation_turn_history",
    "conversation_proposal_history", "review_decisions", "agent_action_history",
)


def _json_family_corpus():
    source = Provenance("文書-α", 0, "領域", "note ☕")
    empty = Provenance()
    return [
        events.goal_created("goal-α", "家", "USD", "999999999999.000000001",
                            "2026-01-01", monthly_contribution="0.0001",
                            contribution_day=1, provenance=source),
        events.goal_terms_changed("goal-α", "家", "USD", "0.0001",
                                  "2026-01-02", provenance=empty),
        events.goal_funds_reserved("goal-α", "account-α", "1.2300",
                                   "2026-01-03", provenance=source),
        events.goal_funds_released("goal-α", "account-α", "1.2300",
                                   "reassigned", "2026-01-04", provenance=empty),
        events.goal_state_changed("goal-α", "paused", "2026-01-05",
                                  provenance=source),
        events.goal_proposal_recorded(
            "gp-α", "change_terms", "", {"null": None, "empty": "",
             "zero": 0, "repeated": ["雪", "雪"], "decimal": "0.0000"},
            {"nested": {"amount": "999999999999.000000001"}},
            "2026-01-06", source),
        events.goal_proposal_resolved("gp-α", "stale", "2026-01-07",
                                      provenance=empty),
        events.conversation_turn_opened("turn-α", "ask", "Question?",
                                        "2026-01-08", question_id="q-α",
                                        mirrored=False, context_mode="new_question",
                                        provenance=source),
        events.conversation_turn_settled(
            "turn-α", "proposal", "", "2026-01-09",
            answer={"null": None, "empty": [], "zero": 0},
            proposal_id="cp-α", provenance=empty),
        events.conversation_proposal_recorded(
            "cp-α", "turn-α", "q-α", "", {"rows": ["α", "α"], "amount": "1.2300"},
            {"null": None, "zero": 0}, "2026-01-10", source),
        events.conversation_proposal_resolved("cp-α", "turn-α", "set_aside",
                                              "", "2026-01-11", provenance=empty),
        events.question_declined("q-α", "merchant", "2026-01-12",
                                 amount="0.0000", count=0, provenance=source),
        events.finding_set_aside("f-α", "fee_observed",
                                 {"amount": "1.2300", "items": ["雪", "雪"]},
                                 "2026-01-13", provenance=empty),
        events.agent_acted("rule-α", "induce", "target-α", "refused",
                           "2026-01-14", calls=0,
                           stake={"amount": "1.2300", "zero": 0},
                           provenance=source),
        events.Event("FutureUnknown", "2026-01-15",
                     {"opaque": {"amount": "1.2300"}}, empty),
    ]


def _rows(revision):
    return {table: revision.connection.execute(
        f"SELECT * FROM {table} ORDER BY source_sequence").fetchall()
        for table in JSON_BODY_TABLES}


@pytest.mark.parametrize("cut", [1, 4, 7, 11])
def test_json_body_families_preserve_exact_typed_fields_across_suffix_restart_and_held(
        tmp_path: Path, cut: int):
    corpus = _json_family_corpus()
    canonical = EventStore.open(tmp_path / "events.jsonl", PASSPHRASE)
    for event in corpus[:cut]:
        canonical.append(event)
    split_path = tmp_path / "split"
    with ReadStore.create(split_path, PASSPHRASE) as split:
        assert split.synchronize(canonical).state == "rebuilt"
        held = split.open_reader()
        before = _rows(held)
        for event in corpus[cut:]:
            canonical.append(event)
        assert split.synchronize(canonical).state == "caught_up"
        assert _rows(held) == before
        held.close()
        with split.open_reader() as after:
            split_rows = _rows(after)
            for sequence, event in enumerate(corpus[:-1]):
                table = FAMILIES[event.event_type][0]
                row = after.connection.execute(
                    f"SELECT body_json,provenance_doc_id,provenance_page,"
                    f"provenance_region,provenance_note FROM {table} "
                    "WHERE source_sequence=?", (sequence,)).fetchone()
                assert row is not None, event.event_type
                assert json.loads(row[0]) == event.body
                assert row[1:] == (event.provenance.doc_id, event.provenance.page,
                                   event.provenance.region, event.provenance.note)
            assert after.connection.execute(
                "SELECT event_type FROM applied_events WHERE sequence=?",
                (len(corpus) - 1,)).fetchone() == ("FutureUnknown",)
            assert sum(len(rows) for rows in split_rows.values()) == len(corpus) - 1

    with ReadStore.open(split_path, PASSPHRASE) as restarted:
        with restarted.open_reader() as revision:
            assert _rows(revision) == split_rows

    with ReadStore.create(tmp_path / "full", PASSPHRASE) as full:
        assert full.synchronize(canonical).state == "rebuilt"
        with full.open_reader() as revision:
            assert _rows(revision) == split_rows


@pytest.mark.parametrize("sequence,wrong_type", [
    (0, "ConversationTurnOpened"),
    (5, "GoalCreated"),
    (7, "GoalProposalRecorded"),
    (11, "AgentActed"),
    (13, "FindingSetAside"),
])
def test_json_family_rows_refuse_authenticated_family_substitution(
        tmp_path: Path, sequence: int, wrong_type: str):
    canonical = EventStore.open(tmp_path / "events.jsonl", PASSPHRASE)
    for event in _json_family_corpus()[:-1]:
        canonical.append(event)
    with ReadStore.create(tmp_path / "read-model", PASSPHRASE) as reads:
        assert reads.synchronize(canonical).state == "rebuilt"
        generation = reads.current_generation

        def substitute(connection):
            connection.execute(
                "UPDATE applied_events SET event_type=? WHERE sequence=?",
                (wrong_type, sequence))

        with pytest.raises(store.sqlcipher.IntegrityError,
                           match="FOREIGN KEY constraint failed"):
            reads.publish(substitute, copy_current=True)
        assert reads.current_generation == generation
        with reads.open_reader() as revision:
            assert revision.connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_unknown_event_advances_authenticated_identity_without_domain_row(
        tmp_path: Path):
    canonical = EventStore.open(tmp_path / "events.jsonl", PASSPHRASE)
    canonical.append(events.account_opened(
        "account-α", "depository", "A", "USD", "2026-01-01"))
    canonical.append(events.Event("FutureUnknown", "2026-01-02",
                                  {"nested": [None, 0, ""]}))
    with ReadStore.create(tmp_path / "read-model", PASSPHRASE) as reads:
        assert reads.synchronize(canonical).state == "rebuilt"
        held = reads.open_reader()
        canonical.append(events.opening_balance_observed(
            "account-α", "1.2300", "2026-01-03"))
        assert reads.synchronize(canonical).state == "caught_up"
        assert held.connection.execute(
            "SELECT event_type FROM applied_events ORDER BY sequence").fetchall() == [
                ("AccountOpened",), ("FutureUnknown",)]
        held.close()
        with reads.open_reader() as revision:
            assert revision.connection.execute(
                "SELECT source_count FROM projection_meta WHERE singleton=1"
            ).fetchone() == (3,)
            assert revision.connection.execute(
                "SELECT sequence,event_type FROM applied_events ORDER BY sequence"
            ).fetchall() == [
                (0, "AccountOpened"), (1, "FutureUnknown"),
                (2, "OpeningBalanceObserved")]
            assert revision.connection.execute(
                "SELECT source_sequence FROM event_provenance "
                "WHERE source_sequence=1").fetchone() == (1,)
            for table in {record[0] for record in FAMILIES.values()}:
                assert revision.connection.execute(
                    f"SELECT 1 FROM {table} WHERE source_sequence=1").fetchone() is None
            assert revision.connection.execute(
                "SELECT amount_text FROM balance_observations "
                "WHERE source_sequence=2").fetchone() == ("1.2300",)


def test_unrecognized_generation_format_refuses_open(tmp_path: Path):
    path = tmp_path / "read-model"
    with ReadStore.create(path, PASSPHRASE) as reads:
        generation = reads.current_generation
        key = bytes(reads._database_key)
    database = path / "generations" / generation / "projection.db"
    connection = store._connect(database, key)
    connection.execute("UPDATE read_store_identity SET format_version=?",
                       ("future-format",))
    connection.commit()
    connection.close()
    with pytest.raises(ReadStoreError):
        ReadStore.open(path, PASSPHRASE)
