"""Reviewed evidence explanations and captured source names agree with real reads."""
from decimal import Decimal

import pytest

from viva import persona
from viva.ingest import (POSTED, ReadResult, StatementFacts, TxnFact,
                         capture_and_ingest)
from viva.ledger import LedgerProjection, Provenance, simple_transaction
from viva.ledger.events import (account_opened, closing_balance_observed,
                                opening_balance_observed)
from viva.surface.overview import overview
from viva.tools import default_registry
from viva.vault import Vault
from _shape_test_support import _script, _shape, run
from test_tool_contract import _empty_period_registry, _quiet_metric


ANSWER = ("Read this answer as corroborated: the available records support "
          "what it rests on; this is a step below verified.")
ROWS = ("Read this list as corroborated: the available records support "
        "these figures; this is a step below verified.")
TODAY = "2026-01-31"


@pytest.fixture
def synthetic_vault(tmp_path, monkeypatch):
    env = tmp_path / "empty.env"
    env.write_text("")
    monkeypatch.setenv("VIVA_ENV_FILE", str(env))
    monkeypatch.setenv("MERCHANTCORE_HOME", str(tmp_path / "merchant-learning"))
    return Vault.open(tmp_path / "vault", "synthetic evidence passphrase")


def _statement(vault, *, label="synthetic.pdf", account="Synthetic Checking",
               currency="USD", debit="15.00"):
    facts = StatementFacts(
        doc_id="", doc_type="checking_statement", doc_type_confidence=1,
        account_ref=account, currency=currency,
        opening_amount=Decimal("100.00"), opening_date="2026-01-01",
        closing_amount=Decimal("100.00") - Decimal(debit), closing_date=TODAY,
        transactions=[TxnFact("2026-01-15", "SYNTHETIC PURCHASE", -Decimal(debit))],
        opening_page=1, closing_page=2,
    )

    def read(_data, doc_id):
        facts.doc_id = doc_id
        return ReadResult("checking_statement", 1, facts)

    result = capture_and_ingest(
        vault.raw, vault.ledger, f"synthetic statement {label}".encode(), read,
        filename=label, captured_at=TODAY,
    )
    assert result.action == POSTED
    assert result.grade == "corroborated"
    assert result.reconciliation.passed
    assert Decimal(result.reconciliation.delta) == Decimal("0")
    assert Decimal(result.reconciliation.tolerance) == Decimal("0")
    answer = vault.ledger.projection().balance(result.account)
    assert answer.amount == facts.closing_amount
    assert answer.grade == "corroborated"
    assert answer.provenance.doc_id == result.doc_id
    return result


def _account_figure(vault, result):
    data = overview(vault.ledger.projection(), "en-US", TODAY)
    figure = next(row["balance"] for row in data["accounts"]
                  if row["account"] == result.account)
    assert figure["exact_value"] == "85.00"
    assert figure["grade"] == "corroborated"
    assert figure["exactness"] == "exact"
    assert result.doc_id in figure["record_ids"]
    assert [(row["document_id"], row["relation"]) for row in figure["citations"]] == [
        (result.doc_id, "attests")]
    return figure


def test_reconciled_issuer_closing_has_the_approved_corroborated_explanation(synthetic_vault):
    result = _statement(synthetic_vault)
    assert _account_figure(synthetic_vault, result)["grade_description"] == ANSWER


def test_reconciled_issuer_closing_names_its_captured_source_without_borrowing_a_page(synthetic_vault):
    result = _statement(synthetic_vault)
    citation = _account_figure(synthetic_vault, result)["citations"][0]
    assert citation["label"] == "synthetic.pdf"
    assert citation["page"] == ""


def test_account_and_picture_labels_match_exact_document_ids_across_accounts_and_currencies(synthetic_vault):
    cases = [
        ("synthetic-alpha.pdf", "Synthetic Alpha", "USD", "15.00"),
        ("synthetic-beta.pdf", "Synthetic Beta", "USD", "30.00"),
        ("synthetic-euro.pdf", "Synthetic Euro", "EUR", "36.00"),
    ]
    labels, currencies = {}, {}
    for label, account, currency, debit in cases:
        result = _statement(synthetic_vault, label=label, account=account,
                            currency=currency, debit=debit)
        labels[result.doc_id] = label
        currencies[result.doc_id] = currency
    data = overview(synthetic_vault.ledger.projection(), "en-US", TODAY)
    assert {row["currency"]: row["exact_value"] for row in data["picture"]["figures"]} == {
        "USD": "155.00", "EUR": "64.00"}
    for row in data["accounts"]:
        assert row["balance"]["citations"]
        for citation in row["balance"]["citations"]:
            assert citation["label"] == labels[citation["document_id"]]
            assert currencies[citation["document_id"]] == row["currency"]
            assert citation["relation"] == "attests"
            assert citation["page"] == ""
    for figure in data["picture"]["figures"]:
        assert figure["citations"]
        assert {citation["document_id"] for citation in figure["citations"]} == {
            doc_id for doc_id, currency in currencies.items() if currency == figure["currency"]}
        for citation in figure["citations"]:
            assert citation["label"] == labels[citation["document_id"]]
            assert citation["relation"] == "attests"
            assert citation["page"] == ""


def test_captured_labels_and_reviewed_wording_have_exact_canonical_sql_parity(synthetic_vault):
    result = _statement(synthetic_vault)
    canonical = overview(synthetic_vault.ledger.projection(), "en-US", TODAY)
    synthetic_vault.synchronize_read_store()
    with synthetic_vault.read_store.open_reader() as revision:
        sql = overview(revision.overview_projection(today=TODAY), "en-US", TODAY)
    assert sql == canonical
    assert sql["accounts"][0]["balance"]["citations"][0]["label"] == "synthetic.pdf"
    assert sql["accounts"][0]["balance"]["grade_description"] == ANSWER
    assert result.doc_id == sql["accounts"][0]["balance"]["citations"][0]["document_id"]


def test_uncaptured_document_keeps_blank_account_and_picture_labels():
    provenance = Provenance("synthetic-uncaptured-document", 2, "closing")
    projection = LedgerProjection([
        account_opened("synthetic-checking", "depository", "Synthetic Checking", "USD", "2026-01-01"),
        opening_balance_observed("synthetic-checking", "100.00", "2026-01-01", provenance),
        simple_transaction("synthetic-checking", "-15.00", "SYNTHETIC PURCHASE", "2026-01-15", provenance=provenance),
        closing_balance_observed("synthetic-checking", "85.00", TODAY, provenance),
    ])
    data = overview(projection, "en-US", TODAY)
    citations = [*data["accounts"][0]["balance"]["citations"],
                 *data["picture"]["figures"][0]["citations"]]
    assert citations
    assert all(row["document_id"] == provenance.doc_id and row["label"] == ""
               and row["page"] == "" for row in citations)


def _balance_answer(vault, *, computed=False):
    registry = default_registry(vault.ledger.projection(), "en-US", TODAY)
    shape = _shape(("The supported figure is {balance}.",
                    [("balance", "money", "balance", "account")]))

    def planner(context):
        if not context["shaped"]:
            return {"shape": shape}
        done = [row for row in context["results"] if row["tool"] != "commit_shape"]
        if not done:
            return {"tool": "query_ledger", "args": {"entity": "balances"}}
        if computed and len(done) == 1:
            return {"tool": "compute", "args": {"expression": "a * 2",
                "inputs": {"a": done[0]["figures"][0]["id"]}}}
        return {"bindings": {"balance": {"figure": done[-1]["figures"][0]["id"]}}}

    return run("What is the supported synthetic figure?", planner, registry, locale="en-US")


@pytest.mark.parametrize("computed, expected", [(False, "85.00"), (True, "170.00")])
def test_delivery_uses_the_common_corroborated_sentence_for_issuer_and_computed_figures(synthetic_vault, computed, expected):
    result = _statement(synthetic_vault)
    spoken = _balance_answer(synthetic_vault, computed=computed)
    assert spoken.answered, spoken.detail
    assert spoken.grade == "corroborated"
    assert spoken.figures[0]["value"] == expected
    assert result.doc_id in spoken.figures[0]["record_ids"]
    assert spoken.text.count(ANSWER) == 1


def test_delivery_uses_the_common_corroborated_sentence_for_a_document_supported_empty_period():
    registry = _empty_period_registry()
    observed = _quiet_metric(registry, "income", "2026-01-01", TODAY)
    assert observed.ok and observed.grade == "corroborated"
    assert observed.figures[0]["value"] == "0"
    shape = _shape(("Recorded income is {income}.",
                    [("income", "money", "income", ["period", "currency"])]))
    call = ("query_ledger", {"entity": "aggregate", "metric": "income",
                            "filters": {"window": {"from": "2026-01-01", "to": TODAY}}})
    spoken = run("What income is supported for this synthetic period?",
                 _script(shape, call, bind=lambda rows: {
                     "income": {"figure": rows[-1]["figures"][0]["id"]}}), registry)
    assert spoken.answered, spoken.detail
    assert spoken.grade == "corroborated"
    assert spoken.figures[0]["value"] == "0"
    assert spoken.figures[0]["record_ids"] == ["synthetic-quiet-statement"]
    assert spoken.text.count(ANSWER) == 1
    assert all(caveat in spoken.text for caveat in spoken.caveats)


def test_list_delivery_uses_the_common_reviewed_corroborated_sentence(synthetic_vault):
    _statement(synthetic_vault)
    registry = default_registry(synthetic_vault.ledger.projection(), "en-US", TODAY)
    shape = _shape(("Here are the recorded balances:{balances}", [("balances", "rows")]))
    spoken = run("List the synthetic balances.", _script(shape,
        ("query_ledger", {"entity": "balances"}), bind=lambda rows: {
            "balances": {"read": rows[-1]["id"]}}), registry)
    assert spoken.answered, spoken.detail
    assert spoken.grade == "corroborated"
    assert ROWS in spoken.text.splitlines()


def test_other_grades_keep_their_released_reviewed_sentences():
    released = persona.load("pack-v49")["moments"]
    for grade in ("verified", "unverified", "conflicted"):
        for family in (persona.STOOD_BEHIND_MOMENT, persona.ROWS_STOOD_BEHIND_MOMENT):
            assert persona.moment(family + grade) == released[family + grade]
