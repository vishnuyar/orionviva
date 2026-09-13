"""Executable inventory of desktop SQL routes and their typed source contracts."""

import importlib
import inspect
import re
from contextlib import contextmanager

import pytest

from viva.desktop_bridge.vault_surface import OpenedVaultSurfaceProvider
from viva.demo import build_demo_vault
from viva.read_store.store import ReadRevision

from product.tests.test_read_store_coverage_register import BODY_FIELDS, FAMILIES


# The field families are source-body fields, not a claim that every body field is
# rendered by the named destination. Evidence tests exercise the composed wire
# payload, refusal, and named query separately.
ROUTES = {
    "overview": ("_overview", ("overview_projection", "historical_overview_projection"),
                 "Overview", "test_read_store_temporal_overview:test_composition_corpus_historical_overview_full_payload_parity"),
    "overview_accounts": ("_overview_accounts", ("overview_projection",),
                          "Accounts", "test_read_store_overview:test_overview_queries_are_bounded_indexed_and_offset_free"),
    "spending": ("_spending", ("spending_projection",),
                 "Spending", "test_desktop_bridge_read_store:test_current_activity_and_spending_deny_canonical_and_raw_paths"),
    "documents": ("_documents", ("documents_projection",),
                  "Statements", "test_read_store_documents:test_current_documents_sql_matches_the_complete_surface_payload"),
    "review": ("_review", ("review_projection",),
               "Review", "test_read_store_review:test_current_review_sql_matches_complete_canonical_payload"),
    "activity": ("_activity", ("activity_projection", "historical_activity_projection"),
                 "Activity", "test_read_store_temporal_activity:test_historical_activity_direct_sql_matches_complete_canonical_payload"),
    "plans": ("_plans", ("plans_projection",),
              "Plans", "test_read_store_plans:test_current_plans_sql_matches_complete_surface_payload"),
    "conversation": ("_conversation", ("conversation_projection",),
                     "Conversation", "test_read_store_conversation_trust:test_current_conversation_matches_complete_payload_and_held_revision"),
    "trust": ("_trust", ("outbound_events", "has_agent_actions"),
              "Trust", "test_read_store_conversation_trust:test_trust_all_phases_and_decimal_match_canonical_and_refuse_stale"),
    "account_ledger": ("_account_ledger", ("account_ledger_page",),
                       "Accounts", "test_read_store_account_ledger:test_indexed_page_has_explicit_limit_locale_and_index_plan"),
}

OPTIONAL_SOURCE_FIELDS = {
    "overview": {"RulingRecorded": "legs", "GoalCreated": "monthly_contribution"},
    "overview_accounts": {"AccountOpened": "account_number",
                          "AccountIdentityObserved": "account_names"},
    "spending": {"CategoryAssigned": "subcategory", "TransferLinked": "evidence"},
    "documents": {"DocumentCaptured": "doc_type_confidence",
                  "ReadRecorded": "response_text", "StatementHeld": "facts"},
    "review": {"QuestionDeclined": "amount", "FindingSetAside": "stake"},
    "activity": {"TransactionRecorded": "tags", "MerchantEnriched": "aliases"},
    "plans": {"GoalCreated": "contribution_day", "GoalProposalRecorded": "proposal"},
    "conversation": {"ConversationTurnSettled": "answer",
                     "ConversationProposalRecorded": "stake"},
    "trust": {"ReadRecorded": "cost_usd", "AgentActed": "produced"},
    "account_ledger": {"OpeningBalanceObserved": "amount",
                       "AccountAliasConfirmed": "match_names"},
}


READ_TIME_EVIDENCE = {
    "overview": (
        "test_read_store_overview:test_overview_refuses_every_input_family_whole",
        "test_read_store_overview_byte_bounds:test_overview_refuses_oversized_ruling_legs_before_decoding",
        "test_read_store_temporal_overview:test_historical_overview_eligible_fact_queries_use_persistent_indexes"),
    "overview_accounts": (
        "test_read_store_overview:test_overview_refuses_every_input_family_whole",
        "test_read_store_statement_byte_bounds:test_statement_register_refuses_oversized_response_before_parser",
        "test_read_store_overview:test_overview_queries_are_bounded_indexed_and_offset_free"),
    "spending": (
        "test_read_store_overview:test_activity_page_is_pending_first_exact_focused_and_index_planned",
        "test_read_store_transfer_payload_bounds:test_transfer_evidence_refuses_exact_utf8_plus_one_before_fetch",
        "test_read_store_overview:test_overview_queries_are_bounded_indexed_and_offset_free"),
    "documents": (
        "test_read_store_documents:test_documents_refuses_the_first_identity_beyond_its_output_bound",
        "test_read_store_documents:test_documents_scalar_prefetch_exact_utf8_boundary_and_refusal",
        "test_read_store_documents:test_documents_queries_use_named_order_compatible_indexes"),
    "review": (
        "test_read_store_review:test_review_sql_refuses_out_of_contract_limit",
        "test_read_store_review_decision_bytes:test_review_decision_json_exact_utf8_bound_and_prefetch_refusal",
        "test_read_store_review:test_review_binding_inputs_have_named_order_compatible_plans"),
    "activity": (
        "test_read_store_temporal_activity:test_each_temporal_family_refuses_n_plus_one_before_folding",
        "test_read_store_transfer_payload_bounds:test_transfer_candidate_array_prefetch_refuses_plus_one_before_nested_key",
        "test_read_store_temporal_activity:test_temporal_category_query_uses_source_order_primary_key"),
    "plans": (
        "test_read_store_goal_views:test_goal_history_total_row_cap_refuses_instead_of_truncating",
        "test_read_store_goal_views:test_goal_history_body_prefetch_exact_utf8_boundary_and_whole_read_refusal",
        "test_read_store_goal_views:test_goal_view_production_queries_have_indexed_plans_and_bounded_crossings"),
    "conversation": (
        "test_read_store_conversation_trust:test_conversation_history_refuses_n_plus_one",
        "test_read_store_json_fetch_bounds:test_route_body_byte_bound_is_enforced_in_select_before_decode",
        "test_read_store_conversation_trust:test_conversation_and_trust_use_source_order_without_temporary_sort"),
    "trust": (
        "test_read_store_conversation_trust:test_trust_exchange_history_refuses_cap_plus_one_whole",
        "test_read_store_json_fetch_bounds:test_route_body_byte_bound_is_enforced_in_select_before_decode",
        "test_read_store_conversation_trust:test_conversation_and_trust_use_source_order_without_temporary_sort"),
    "account_ledger": (
        "test_read_store_account_ledger:test_page_member_cap_plus_one_refuses_without_truncated_groups",
        "test_read_store_account_ledger:test_page_state_json_refuses_exact_utf8_plus_one_before_fetch",
        "test_read_store_account_ledger:test_component_index_keyset_order_uses_named_index_without_temp_sort"),
}


@pytest.mark.parametrize("route", sorted(ROUTES))
def test_desktop_route_is_bound_to_declared_sql_protocol_and_body_fields(route):
    handler, protocols, destination, evidence = ROUTES[route]
    provider_source = inspect.getsource(getattr(OpenedVaultSurfaceProvider, handler))
    assert "store.open_reader()" in provider_source, route
    assert "projection_as_of" not in provider_source, route
    assert "snapshot_events" not in provider_source, route
    assert "fresh_projection" not in provider_source, route
    for protocol in protocols:
        if route == "trust":
            assert f"{protocol}(revision)" in provider_source, (route, protocol)
        else:
            assert f"revision.{protocol}(" in provider_source, (route, protocol)
            assert callable(getattr(ReadRevision, protocol))
    family_fields = {family: set(BODY_FIELDS[family].split())
                     for family, (_table, _representation, consumers)
                     in FAMILIES.items() if destination in consumers.split()}
    assert family_fields, route
    assert all(family_fields.values()), route
    for family, field in OPTIONAL_SOURCE_FIELDS[route].items():
        assert family in family_fields, (route, family)
        assert field in family_fields[family], (route, family, field)
    module_name, test_name = evidence.split(":", 1)
    module = importlib.import_module(f"product.tests.{module_name}")
    assert callable(getattr(module, test_name)), evidence


def test_jobs_is_the_only_non_sql_registry_route():
    assert set(ROUTES) == OpenedVaultSurfaceProvider._READS - {"jobs"}
    assert set(OPTIONAL_SOURCE_FIELDS) == set(ROUTES)
    assert "self._job_registry()" in inspect.getsource(
        OpenedVaultSurfaceProvider.read_surface)


@pytest.mark.parametrize("route", sorted(READ_TIME_EVIDENCE))
def test_each_desktop_sql_route_has_named_row_byte_and_plan_evidence(route):
    assert set(READ_TIME_EVIDENCE) == set(ROUTES)
    for evidence in READ_TIME_EVIDENCE[route]:
        module_name, test_name = evidence.split(":", 1)
        module = importlib.import_module(f"product.tests.{module_name}")
        assert callable(getattr(module, test_name)), (route, evidence)


def test_public_resolver_loader_is_not_a_desktop_route_dependency():
    for module_name in (
            "viva.desktop_bridge.vault_surface", "viva.read_store.overview",
            "viva.read_store.activity", "viva.read_store.historical",
            "viva.read_store.documents", "viva.read_store.questions",
            "viva.read_store.plans", "viva.read_store.conversation",
            "viva.read_store.trust", "viva.read_store.account_ledger_page",
            "viva.read_store.composition", "viva.read_store.rhythm"):
        try:
            module = importlib.import_module(module_name)
        except ModuleNotFoundError:
            continue
        assert ".resolver(" not in inspect.getsource(module), module_name


def test_all_ten_desktop_routes_trace_only_capped_or_identity_scoped_sql_reads(
        tmp_path, monkeypatch):
    vault = build_demo_vault(tmp_path / "sample")
    with vault.read_store.open_reader() as revision:
        account_id = revision.connection.execute(
            "SELECT account_id FROM accounts LIMIT 1").fetchone()[0]
    original = vault.read_store.open_reader
    traced = []

    @contextmanager
    def traced_reader():
        with original() as revision:
            revision.connection.set_trace_callback(traced.append)
            yield revision

    monkeypatch.setattr(vault.read_store, "open_reader", traced_reader)
    provider = OpenedVaultSurfaceProvider(vault)
    routes = [
        ("overview", {"read_on": "2026-08-29"}),
        ("overview", {"as_of": "2026-01-31", "read_on": "2026-08-29"}),
        ("overview_accounts", {"read_on": "2026-08-29"}),
        ("spending", {"read_on": "2026-08-29"}),
        ("documents", {}), ("review", {}), ("activity", {}),
        ("activity", {"as_of": "2026-01-31"}),
        ("plans", {"read_on": "2026-08-29"}),
        ("conversation", {}), ("trust", {}),
        ("account_ledger", {"account_id": account_id}),
    ]
    bounded_without_literal_limit = (
        "FROM account_entities e WHERE e.account_id=",  # one existence result
        "SELECT COUNT(*) FROM movements",  # one aggregate result
        "FROM accounts a WHERE a.event_type=",  # bounded account-id IN set
        "FROM balance_observations b WHERE b.event_type=",  # same IN set
        "FROM postings p JOIN transactions t ON t.source_sequence=p.source_sequence",
        "FROM account_ledger_component_state WHERE account_id=",  # primary key
        "FROM projection_meta WHERE singleton=1",  # singleton key
        "WITH RECURSIVE created AS (",  # preflight-capped reservation fold
    )
    observed = set()
    for route, parameters in routes:
        traced.clear()
        provider.read_surface(route, parameters)
        selects = [" ".join(sql.split()) for sql in traced
                   if sql.lstrip().upper().startswith(("SELECT", "WITH"))]
        assert selects, route
        observed.add(route)
        for sql in selects:
            if "LIMIT" not in sql.upper():
                assert any(marker in sql for marker in bounded_without_literal_limit), (
                    route, sql)
            selected = sql.split(" FROM ", 1)[0]
            if re.search(r"\b[a-z_]+_json\b", selected, re.I):
                assert "length(CAST(" in sql, (route, sql)
    assert observed == set(ROUTES)
