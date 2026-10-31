"""Raw source comparisons preserve evidence and repeated occurrences."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


_path = Path(__file__).resolve().parents[2] / "scripts" / "validate_sql_authority.py"
_spec = importlib.util.spec_from_file_location("sql_authority_source_comparison_harness", _path)
harness = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(harness)


def assertions():
    provenance = {"doc_id": "a" * 64, "page": 1, "region": "", "note": ""}
    rows = []
    for ordinal, occurrence in enumerate(("E000001", "E000002")):
        rows.append({"ordinal": ordinal,
                     "occurrence": {"line_index": ordinal, "event_id": occurrence,
                                    "date": "2001-01-01", "page": 1, "raw": "-7.00"},
                     "date": "2001-01-01", "description": "Synthetic repeated source row",
                     "source_reference": "", "counterparty_reference": "",
                     "provenance": dict(provenance),
                     "postings": [{"account": "logical-account", "amount": "-7", "grade": "verified"},
                                  {"account": "Expenses:Uncategorized", "amount": "7", "grade": "unverified"}]})
    opening = {"date": "2001-01-01", "amount": "100",
               "provenance": {**provenance, "note": "opening balance"}}
    return {"transactions": rows,
            "asserted_observations": [{**opening, "kind": "opening", "account": "logical-account"}],
            "printed_openings": [opening]}


def test_exact_raw_assertions_and_repeated_occurrences_match():
    expected = assertions()
    harness.compare_source_document(expected, deepcopy(expected))
    assert len(expected["transactions"]) == 2
    assert expected["transactions"][0]["occurrence"] != expected["transactions"][1]["occurrence"]


def test_all_declared_source_mutation_controls_reject_changes():
    assert harness.source_comparison_controls(assertions()) == [
        "counterpart amount", "counterpart grade", "counterpart account", "date",
        "provenance", "occurrence pairing", "occurrence multiplicity"]


@pytest.mark.parametrize("field", ["transactions", "asserted_observations", "printed_openings"])
def test_missing_source_evidence_fails_even_when_other_dimensions_match(field):
    expected = assertions()
    actual = deepcopy(expected)
    actual[field] = []
    with pytest.raises(harness.HarnessFailure, match="raw source parity"):
        harness.compare_source_document(expected, actual)


def test_swapping_equal_occurrences_fails_without_set_comparison():
    expected = assertions()
    actual = deepcopy(expected)
    left, right = actual["transactions"]
    left["occurrence"], right["occurrence"] = right["occurrence"], left["occurrence"]
    with pytest.raises(harness.HarnessFailure, match="transactions"):
        harness.compare_source_document(expected, actual)


def test_printed_opening_cannot_replace_a_genuine_legacy_opening_assertion():
    expected = assertions()
    actual = deepcopy(expected)
    actual["asserted_observations"] = []
    assert actual["printed_openings"] == expected["printed_openings"]
    with pytest.raises(harness.HarnessFailure, match="asserted_observations"):
        harness.compare_source_document(expected, actual)


def test_extra_unasserted_opening_is_not_fabricated_as_a_legacy_event():
    expected = assertions()
    expected["asserted_observations"] = []
    actual = deepcopy(expected)
    actual["asserted_observations"] = [{**expected["printed_openings"][0],
                                        "kind": "opening", "account": "logical-account"}]
    with pytest.raises(harness.HarnessFailure, match="asserted_observations"):
        harness.compare_source_document(expected, actual)


@pytest.mark.parametrize("state,matched,error,label", [
    ("accepted", True, False, "promoted-and-matched"),
    ("accepted", False, False, "mismatched"),
    ("unsupported", False, False, "declared unsupported"),
    ("pending", False, False, "pending"),
    ("read_uncertain", False, False, "pending"),
    ("accepted", True, True, "admission error"),
    ("unsupported", False, True, "admission error"),
])
def test_disposition_precedence_is_exclusive(state, matched, error, label):
    assert harness.final_source_disposition(admission_error=error, state=state, matched=matched) == label


def envelope():
    return {"source_event_ids": ["E000001", "E000002"], "source_cells": [
        {"association": {"kind": "event", "row_reference": occurrence, "date": "2001-01-01"},
         "page": 1, "raw": "-7.00"}
        for occurrence in ("E000001", "E000002") for _ in range(2)]}


def test_occurrence_cell_binding_retains_equal_amount_multiplicity_and_order():
    result = harness.source_occurrences(envelope())
    assert [row["line_index"] for row in result] == [0, 1]
    assert [row["event_id"] for row in result] == ["E000001", "E000002"]
    assert [row["raw"] for row in result] == ["-7.00", "-7.00"]


@pytest.mark.parametrize("mutation", ["missing", "conflicting", "repeated"])
def test_missing_conflicting_or_repeated_occurrence_witness_fails(mutation):
    value = envelope()
    if mutation == "missing":
        value["source_cells"] = value["source_cells"][:2]
    elif mutation == "conflicting":
        value["source_cells"][0]["page"] = 2
    else:
        value["source_event_ids"][1] = value["source_event_ids"][0]
    with pytest.raises(harness.HarnessFailure):
        harness.source_occurrences(value)


class MappingStore:
    def __init__(self):
        self.accounts = {
            "sql-later": {"creation_order": 19, "logical_key": "logical-later", "kind": "liability",
                          "currency": "USD", "label": "Synthetic later", "institution": "Synthetic issuer",
                          "number": "", "names": "[]"},
            "sql-first": {"creation_order": 4, "logical_key": "logical-first", "kind": "depository",
                          "currency": "USD", "label": "Synthetic first", "institution": "Synthetic issuer",
                          "number": "", "names": "[]"},
        }

    def item(self, doc_id):
        return {"state": "accepted", "account_id": doc_id}

    def account(self, account_id):
        return self.accounts[account_id]


def opening_events():
    return [SimpleNamespace(event_type="AccountOpened", body={
        "account_id": account, "kind": kind, "currency": "USD", "name": label,
        "institution": "Synthetic issuer", "account_number": "", "account_names": []})
        for account, kind, label in (("legacy-first", "depository", "Synthetic first"),
                                     ("legacy-later", "liability", "Synthetic later"))]


def test_account_mapping_uses_order_of_noncontiguous_persisted_keys():
    legacy, physical, logical = harness.map_source_accounts(opening_events(), MappingStore(),
                                                           ["sql-later", "sql-first"])
    assert legacy == {"legacy-first": "account-1", "legacy-later": "account-2"}
    assert physical == {"sql-first": "account-1", "sql-later": "account-2"}
    assert logical == {"logical-first": "account-1", "logical-later": "account-2"}


@pytest.mark.parametrize("mutation", ["missing", "metadata", "reordered", "duplicate_order"])
def test_mapping_does_not_hide_missing_accounts_or_changed_identity(mutation):
    store = MappingStore()
    documents = ["sql-later", "sql-first"]
    if mutation == "missing":
        documents.pop()
    elif mutation == "metadata":
        store.accounts["sql-first"]["number"] = "830000001111"
    elif mutation == "reordered":
        store.accounts["sql-first"]["creation_order"] = 24
    else:
        store.accounts["sql-first"]["creation_order"] = 19
    with pytest.raises(harness.HarnessFailure):
        harness.map_source_accounts(opening_events(), store, documents)


def resolution():
    return {"account_id": "legacy-first", "key": "acct:synthetic", "verdict": "ambiguous",
            "candidate": "legacy-first", "candidate_name": "Synthetic first",
            "candidates": ("legacy-first", "legacy-later"), "reason": "Synthetic unresolved rivals"}


def test_resolution_comparison_maps_ids_but_keeps_every_existing_field():
    expected = {"resolution": resolution(), "account_order": ["legacy-first", "legacy-later"]}
    actual = {"resolution": {**resolution(), "account_id": "logical-first", "candidate": "logical-first",
                             "candidates": ["logical-first", "logical-later"]},
              "account_order": ["logical-first", "logical-later"],
              "logical_to_physical": {"logical-first": "sql-first", "logical-later": "sql-later"}}
    harness.compare_source_resolution(expected, actual,
                                      {"legacy-first": "account-1", "legacy-later": "account-2"},
                                      {"logical-first": "account-1", "logical-later": "account-2"},
                                      {"sql-first": "account-1", "sql-later": "account-2"})


@pytest.mark.parametrize("field,replacement", [
    ("key", "changed-key"), ("verdict", "same"), ("candidate", "unmapped"),
    ("candidate_name", "Changed label"), ("candidates", ["legacy-first"]), ("reason", "Changed reason"),
])
def test_resolution_gate_rejects_changed_fields_or_an_omitted_rival(field, replacement):
    expected = {"resolution": resolution(), "account_order": ["legacy-first", "legacy-later"]}
    actual = deepcopy(expected)
    actual["resolution"][field] = replacement
    with pytest.raises(harness.HarnessFailure, match="exact source resolver"):
        harness.compare_source_resolution(expected, actual, {}, {}, {})


def test_resolution_mapping_cannot_silently_pair_a_logical_key_with_another_account():
    expected = {"resolution": resolution(), "account_order": ["legacy-first", "legacy-later"]}
    actual = {**deepcopy(expected), "logical_to_physical": {"legacy-first": "sql-later", "legacy-later": "sql-first"}}
    with pytest.raises(harness.HarnessFailure, match="logical-to-physical account identity binding"):
        harness.compare_source_resolution(expected, actual,
                                          {"legacy-first": "account-1", "legacy-later": "account-2"},
                                          {"legacy-first": "account-1", "legacy-later": "account-2"},
                                          {"sql-first": "account-1", "sql-later": "account-2"})


def test_failed_packet_retains_one_exclusive_disposition_for_every_input(tmp_path, monkeypatch):
    def fail(_output, checkpoint):
        checkpoint["records"] = {
            str(index): {"doc_id": str(index), "state": "not_attempted", "matched": False,
                         "admission_error": index == 0} for index in range(420)}
        raise harness.HarnessFailure("synthetic stopped packet")
    monkeypatch.setattr(harness, "_run_curated_source", fail)
    with pytest.raises(harness.HarnessFailure, match="synthetic stopped packet"):
        harness.run_curated_source(tmp_path)
    report = json.loads((tmp_path / "source-dispositions.json").read_text())
    assert report["count"] == len(report["documents"]) == sum(report["final_counts"].values()) == 420
    assert report["final_counts"] == {"admission error": 1, "declared unsupported": 0,
                                      "pending": 419, "promoted-and-matched": 0, "mismatched": 0}


@pytest.mark.parametrize("last,passed", [(200, True), (201, False)])
def test_reference_growth_keeps_all_inputs_and_the_fixed_two_times_gate(last, passed):
    samples = [{"vm_instructions": 100} for _ in range(420)]
    samples[-20:] = [{"vm_instructions": last} for _ in range(20)]
    report = harness.source_identity_growth(samples)
    assert report["count"] == 420
    assert report["threshold"] == 2.0
    assert report["passed"] is passed


@pytest.mark.parametrize("mutation", ["zero", "missing"])
def test_reference_growth_cannot_drop_inputs_or_zero_work(mutation):
    samples = [{"vm_instructions": 100} for _ in range(420)]
    if mutation == "zero":
        samples[200]["vm_instructions"] = 0
    else:
        samples.pop()
    with pytest.raises(harness.HarnessFailure):
        harness.source_identity_growth(samples)


class SourceStore:
    def __init__(self):
        self.doc_id = "a" * 64
        self.observations = [
            {"doc_id": self.doc_id, "account_id": "sql", "kind": kind, "date": dated,
             "amount": amount, "event_asserted": True,
             "provenance": {"doc_id": self.doc_id, "page": 1, "region": "", "note": kind + " balance"}}
            for kind, dated, amount in (("opening", "2001-01-01", "100"), ("closing", "2001-01-02", "93"))]
        self.occurrence_doc = self.doc_id

    def source_transactions(self, _doc_id):
        return [{"ordinal": 0, "date": "2001-01-01", "description": "Synthetic row", "source_reference": "",
                 "counterparty_reference": "", "tags": [], "grade": "verified",
                 "provenance": {"doc_id": self.doc_id, "page": 1, "region": "", "note": ""}}]

    def source_occurrences(self, _doc_id):
        return [{"doc_id": self.occurrence_doc, "line_index": 0, "ordinal": 0, "event_id": "E000001",
                 "date": "2001-01-01", "page": 1, "raw": "-7.00"}]

    def postings(self, _doc_id):
        return [{"ordinal": 0, "leg": leg, "account": account, "amount": amount, "grade": grade}
                for leg, account, amount, grade in ((0, "sql", "-7", "verified"),
                                                   (1, "Expenses:Uncategorized", "7", "unverified"))]

    def source_observations(self, _doc_id):
        return deepcopy(self.observations)

    def item(self, _doc_id):
        return {"state": "accepted"}

    def receipt(self, _doc_id):
        return {"facts_type": "balance", "facts": {
            "doc_id": self.doc_id, "doc_type": "checking_statement", "doc_type_confidence": 1.0,
            "account_ref": "Synthetic account", "currency": "USD", "opening_amount": "100",
            "opening_date": "2001-01-01", "opening_page": 1, "closing_amount": "93",
            "closing_date": "2001-01-02", "closing_page": 1,
            "transactions": [{"date": "2001-01-01", "description": "Synthetic row", "amount": "-7", "page": 1}]}}


def test_accepted_source_observations_bind_independent_immutable_receipt():
    store = SourceStore()
    actual = harness.sql_source_assertions(store, store.doc_id, {"sql": "logical"})
    assert actual["printed_openings"][0]["amount"] == "1E+2"
    assert sorted(row["kind"] for row in actual["asserted_observations"]) == ["closing", "opening"]


@pytest.mark.parametrize("ordinal", [0, 1])
def test_altered_accepted_observation_cannot_replace_unchanged_receipt(ordinal):
    store = SourceStore()
    store.observations[ordinal]["amount"] = "999"
    with pytest.raises(harness.HarnessFailure, match="bind immutable receipt"):
        harness.sql_source_assertions(store, store.doc_id, {"sql": "logical"})


def test_sql_event_flag_is_not_inferred_from_the_legacy_oracle():
    store = SourceStore()
    expected = harness.sql_source_assertions(store, store.doc_id, {"sql": "logical"})
    store.observations[0]["event_asserted"] = False
    actual = harness.sql_source_assertions(store, store.doc_id, {"sql": "logical"})
    assert actual["printed_openings"] == expected["printed_openings"]
    with pytest.raises(harness.HarnessFailure, match="asserted_observations"):
        harness.compare_source_document(expected, actual)


def test_occurrence_from_another_document_cannot_match_by_ordinal_alone():
    store = SourceStore()
    store.occurrence_doc = "b" * 64
    with pytest.raises(harness.HarnessFailure, match="document and ordinal binding"):
        harness.sql_source_assertions(store, store.doc_id, {"sql": "logical"})
