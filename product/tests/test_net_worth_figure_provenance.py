"""Net-worth receipts retain the exact dated operands through durable answers."""
from copy import deepcopy
from types import SimpleNamespace

from viva import quantity
from viva.ledger import EventStore, Ledger, Provenance
from viva.ledger.events import (account_opened, closing_balance_observed,
                                conversation_turn_opened,
                                conversation_turn_settled, document_captured, statement_held)
from viva.surface.conversation import conversation, timeline
from viva.tools import default_registry
from viva.tools.runner import _Ground, _gate
from viva.tools.shape import Clause, Shape, Slot

DAY = "2026-02-28"


def _ledger(tmp_path):
    ledger = Ledger(EventStore.open(tmp_path / "events.jsonl", "synthetic"))
    rows = (
        ("asset", "depository", "USD", "100", "2026-01-31", "doc-old"),
        ("zero", "depository", "USD", "0", "2026-02-15", "doc-zero"),
        ("debt", "liability", "USD", "25", "2026-02-15", "doc-shared"),
        ("overdrawn", "depository", "USD", "-5", "2026-01-20", "unknown-doc"),
        ("credit", "liability", "USD", "-7", "2026-01-25", "doc-shared"),
        ("proofless", "depository", "USD", "3", "2026-01-30", ""),
        ("foreign", "depository", "EUR", "90", "2026-02-01", "doc-eur"),
        ("later", "depository", "USD", "8", "2026-03-31", "doc-later"),
    )
    for account, kind, currency, amount, day, proof in rows:
        ledger.append(account_opened(account, kind, "Synthetic " + account,
                                     currency, "2026-01-01"))
        ledger.append(closing_balance_observed(
            account, amount, day, Provenance(doc_id=proof)))
    ledger.append(account_opened("unmeasured", "depository", "Synthetic missing",
                                 "USD", "2026-01-01"))
    ledger.append(closing_balance_observed(
        "asset", "999", "2026-03-31", Provenance(doc_id="doc-new")))
    for doc in ("doc-old", "doc-shared", "doc-zero", "doc-eur", "doc-new",
                "doc-later", "unrelated"):
        ledger.append(document_captured(doc, doc + ".pdf", 10,
                                        "bank_statement", 1.0, "2026-04-01"))
    ledger.append(statement_held("unrelated", {}, None, "gap", "2026-04-01"))
    return ledger


def _query(ledger, **extra):
    registry = default_registry(ledger.projection(), today=DAY)
    result = registry.call("query_ledger", {
        "entity": "aggregate", "metric": "net_worth", "as_of": DAY, **extra})
    assert result.ok, result.text
    return registry, result


def _net(result, currency):
    return next(item for item in result.figures
                if item["quantity"] == quantity.NET_WORTH
                and item["currency"] == currency)


def test_net_figures_add_only_exact_currency_operands_and_keep_other_figures(tmp_path):
    ledger = _ledger(tmp_path)
    _, result = _query(ledger)
    accounts = ["asset", "credit", "debt", "foreign", "overdrawn", "proofless", "zero"]
    assert _net(result, "USD")["record_ids"] == sorted(accounts + [
        "doc-old", "doc-shared", "unknown-doc", "doc-zero"])
    assert _net(result, "EUR")["record_ids"] == sorted(accounts + ["doc-eur"])
    assert result.data["point"]["by_currency"]["USD"]["net"] == "80"
    assert result.data["point"]["by_currency"]["EUR"]["net"] == "90"
    assert result.dated == DAY
    assert result.data["point"]["complete"] is False
    assert {line["account"] for line in result.data["point"]["skipped"]} == {
        "later", "unmeasured"}
    assert result.caveats
    assert {item["account"] for item in _net(result, "USD")["boundary"]["unmeasured"]} == {"later", "unmeasured"}
    assert _net(result, "USD")["boundary"]["unposted"] == 1
    for item in result.figures:
        if item["quantity"] == quantity.NET_WORTH:
            assert "doc-new" not in item["record_ids"]
            assert "doc-later" not in item["record_ids"]
            assert "unrelated" not in item["record_ids"]
            assert len(item["record_ids"]) == len(set(item["record_ids"]))
        elif item["what"].startswith(("assets in ", "liabilities in ")):
            assert item["record_ids"] == accounts
        else:
            assert item["record_ids"] == [item["boundary"]["cut"][0]["value"]]
    assert result.record_ids == accounts
    _, narrowed = _query(ledger, view="net_by_currency")
    assert narrowed.figures == [item for item in result.figures
                                if item["quantity"] == quantity.NET_WORTH]


def test_query_grounded_answer_receipt_and_durable_reopen_keep_exact_sources(tmp_path):
    ledger = _ledger(tmp_path)
    registry, read = _query(ledger)
    ground = _Ground(question="What is the dated net worth?")
    ground.stamp(read)
    chosen = _net(read, "USD")
    shape = Shape(clauses=(Clause(text="Net worth is {total}.", slots=(
        Slot(name="total", type="money", quantity=quantity.NET_WORTH,
             scope=frozenset({"currency"})),)),))
    result = _gate({"bindings": {"total": {"figure": chosen["id"]}}},
                   [read], ground, shape, "en-US", tools=registry)
    assert result.answered, result.detail
    assert all(caveat in result.text for caveat in ground.caveats.values())
    turn = SimpleNamespace(question="What is the dated net worth?", result=result)
    written = {chosen["id"]: result.written["total"]}
    said = conversation(turn, written, projection=ledger.projection(), turn_id="new")
    figure = said["figures"][0]
    expected_docs = ["doc-old", "doc-shared", "doc-zero"]
    assert [link["document_id"] for link in figure["evidence_links"]] == expected_docs
    assert all(link["page"] == "" for link in figure["evidence_links"])
    assert set(figure["record_ids"]) == set(chosen["record_ids"])
    assert "unknown-doc" in figure["record_ids"]
    assert figure["evidence_id"] == "conversation:new:" + chosen["id"]
    ledger.append(conversation_turn_opened("new", "ask", turn.question, DAY))
    ledger.append(conversation_turn_settled("new", "completed", said["text"], DAY,
                                            answer=said))
    old = deepcopy(said)
    old["figures"][0]["record_ids"] = ["asset"]
    old["figures"][0]["evidence_links"] = []
    ledger.append(conversation_turn_opened("old", "ask", "Earlier answer", DAY))
    ledger.append(conversation_turn_settled("old", "completed", old["text"], DAY,
                                            answer=old))
    reopened = Ledger(EventStore.open(tmp_path / "events.jsonl", "synthetic"))
    durable = timeline(reopened.projection(), {"questions": []})
    answers = {item["id"]: item["answer"] for item in durable["turns"]}
    assert answers["new"] == said
    assert answers["old"]["figures"][0]["evidence_links"] == []
