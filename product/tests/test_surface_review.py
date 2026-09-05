from __future__ import annotations

from copy import deepcopy
import importlib
from types import SimpleNamespace

from viva.demo import build_demo_vault
from viva.questions import ACTIONABLE_QUESTION_WINDOW, open_questions
from viva.desktop_bridge.vault_surface import OpenedVaultSurfaceProvider
from viva.surface.review import _item, _transaction_target, review


def _synthetic_queue(size, limit):
    questions = [{"id": f"question-{index:03d}", "kind": "identity",
                  "text": f"Question {index}", "why": "Synthetic test question."}
                 for index in range(size)]
    return {"questions": questions[:limit], "total": size,
            "tail": {"count": max(0, size - limit), "amount": "0"},
            "pending": {"count": 0}, "invite": "", "answered_by_document": ""}


def _transaction_question(projection):
    queue = open_questions(projection, limit=100, as_of="2026-09-30", locale="en-US")
    for question in queue["questions"]:
        if _transaction_target(projection, question, "en-US")[0] is not None:
            return deepcopy(question)
    raise AssertionError("demo vault supplied no transaction-bound question")


def test_review_is_the_backend_question_order_and_count(tmp_path):
    vault = build_demo_vault(tmp_path / "vault")
    projection = vault.ledger.projection()
    queue = open_questions(projection, limit=100, as_of="2026-09-30", locale="en-US")

    read = review(projection, "en-US", limit=100, as_of="2026-09-30")

    assert read["contract"] == "ReviewSummary.v1"
    assert read["actionable_count"] == queue["total"]
    assert [item["target"]["question_id"] for item in read["groups"][0]["items"]] == [question["id"] for question in queue["questions"]]
    assert read["types"] == [{"id": "questions", "label": "Questions", "count": read["shown_count"]}]


def test_transaction_targets_bind_exact_account_and_canonical_members(tmp_path):
    vault = build_demo_vault(tmp_path / "vault")
    projection = vault.ledger.projection()
    items = review(projection, "en-US", as_of="2026-09-30")["groups"][0]["items"]
    targets = [item["target"] for item in items if item["target"]["kind"] == "transaction"]

    assert targets
    movement_accounts = {str(movement.key): movement.account for movement in projection.movements()}
    for target in targets:
        assert target["movement_id"] in target["member_movement_ids"]
        assert target["canonical_movement_id"] in target["member_movement_ids"]
        assert {movement_accounts[identity] for identity in target["member_movement_ids"]} == {target["account_id"]}


def test_review_is_bounded_without_hiding_the_authored_total(tmp_path):
    vault = build_demo_vault(tmp_path / "vault")
    read = review(vault.ledger.projection(), "en-US", limit=1, as_of="2026-09-30")

    assert read["shown_count"] == 1
    assert read["actionable_count"] > 1
    assert read["remaining_count"] == read["actionable_count"] - 1


def test_duplicate_movement_inputs_fall_back_to_the_exact_conversation(tmp_path):
    projection = build_demo_vault(tmp_path / "vault").ledger.projection()
    question = _transaction_question(projection)
    identity = question["refs"].get("movement") or question["refs"]["movements"][0]
    question["refs"]["movements"] = [identity, identity]

    item = _item(projection, question, "en-US")

    assert item["target"]["kind"] == "conversation"
    assert item["target"]["question_id"] == question["id"]
    assert item["primary_action"] == "open_question"


def test_non_string_movement_or_candidate_falls_back_without_raising(tmp_path):
    projection = build_demo_vault(tmp_path / "vault").ledger.projection()
    for field in ("movements", "candidates"):
        question = _transaction_question(projection)
        question["refs"][field] = [{"not": "an identity"}]

        item = _item(projection, question, "en-US")

        assert item["target"]["kind"] == "conversation"
        assert item["target"]["question_id"] == question["id"]


def test_contradictory_document_aliases_never_choose_one(tmp_path):
    projection = build_demo_vault(tmp_path / "vault").ledger.projection()
    question = _transaction_question(projection)
    identity = question["refs"].get("movement") or question["refs"]["movements"][0]
    movement = next(item for item in projection.movements() if str(item.key) == identity)
    document = str(movement.provenance.doc_id)
    question["refs"].update({"document": document, "doc_id": f"{document}-contradiction"})

    assert _transaction_target(projection, question, "en-US")[0] is None


def test_unrelated_candidate_cannot_be_presented_as_exact_context(tmp_path):
    projection = build_demo_vault(tmp_path / "vault").ledger.projection()
    question = _transaction_question(projection)
    target, _ = _transaction_target(projection, question, "en-US")
    assert target is not None
    unrelated = next(str(item.key) for item in projection.movements()
                     if str(item.key) not in target["member_movement_ids"])
    question["refs"]["candidates"] = [unrelated]

    assert _transaction_target(projection, question, "en-US")[0] is None


def test_consistent_document_alias_and_member_candidate_remain_valid(tmp_path):
    projection = build_demo_vault(tmp_path / "vault").ledger.projection()
    question = _transaction_question(projection)
    target, _ = _transaction_target(projection, question, "en-US")
    assert target is not None
    movement = next(item for item in projection.movements()
                    if str(item.key) == target["movement_id"])
    document = str(movement.provenance.doc_id)
    question["refs"].update({"document": document, "doc_id": document,
                              "candidates": [target["movement_id"]]})

    repeated, _ = _transaction_target(projection, question, "en-US")

    assert repeated is not None
    assert repeated["account_id"] == target["account_id"]
    assert repeated["member_movement_ids"] == target["member_movement_ids"]


def test_review_and_conversation_share_the_same_actionable_question_window(monkeypatch):
    review_module = importlib.import_module("viva.surface.review")
    vault_surface_module = importlib.import_module("viva.desktop_bridge.vault_surface")
    limits = []

    for size in (15, ACTIONABLE_QUESTION_WINDOW + 7):
        def authored(_projection, *, limit, **_kwargs):
            limits.append(limit)
            return _synthetic_queue(size, limit)

        monkeypatch.setattr(review_module, "open_questions", authored)
        monkeypatch.setattr(vault_surface_module, "open_questions", authored)
        review_read = review_module.review(object(), "en-US")

        projection = SimpleNamespace(
            conversation_proposals=lambda: [], conversation_turns=lambda: [])
        provider = object.__new__(OpenedVaultSurfaceProvider)
        provider._vault = SimpleNamespace(
            ledger=SimpleNamespace(projection=lambda: projection))
        conversation_read = provider._conversation({})

        review_ids = [item["target"]["question_id"]
                      for group in review_read["groups"]
                      for item in group["items"]]
        conversation_ids = [item["id"] for item in conversation_read["questions"]]
        assert review_ids == conversation_ids
        assert len(review_ids) == min(size, ACTIONABLE_QUESTION_WINDOW)
        assert review_read["actionable_count"] == conversation_read["total"] == size
        assert review_read["shown_count"] == len(conversation_ids)
        assert review_read["remaining_count"] == conversation_read["tail"]["count"]

    assert limits == [ACTIONABLE_QUESTION_WINDOW] * 4


def test_review_and_conversation_share_each_question_semantics(tmp_path):
    vault = build_demo_vault(tmp_path / "vault")
    provider = OpenedVaultSurfaceProvider(vault, cursor_secret=b"r" * 32)

    conversation = provider.read_surface(
        "conversation", {"as_of": "2026-09-30", "locale": "en-US"})
    review_read = provider.read_surface(
        "review", {"as_of": "2026-09-30"})
    questions = conversation["questions"]
    items = [item for group in review_read["groups"] for item in group["items"]]

    assert len(questions) == len(items) > 10
    for question, item in zip(questions, items):
        binding = question["review_binding"]
        assert binding == item["binding"]
        assert binding["item_id"] == item["id"]
        assert binding["question_id"] == question["id"]
        assert binding["question_kind"] == question["kind"]
        assert binding["label"] == question["text"] == item["label"]
        assert binding["reason"] == question["why"] == item["reason"]
        assert binding["target"] == item["target"]
        assert binding["status"] == item["status"]
        assert binding["primary_action"] == item["primary_action"]
        assert binding["allowed_actions"] == item["allowed_actions"]
        assert set(binding["refs"]) == {
            "movement", "movements", "candidates", "document", "doc_id",
            "account",
        }
