"""The check that runs the artifact, checked against artifacts that misbehave.

Everything else in this repository checks the source tree. `validate_packaged_
artifact` runs the built executable and speaks the real protocol to it, which is
the one thing a source-tree check cannot do — and which means the check itself
has to be checked, because a validator that passes over a broken build is worse
than no validator.

So each test here builds a stand-in executable that speaks the protocol badly in
exactly one way, and asserts the validator says so. The stand-ins are Python
scripts rather than packaged binaries: what is under test is the validator's
reading of a conversation, and a conversation is the same over either.
"""

from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import validate_packaged_artifact as checker  # noqa: E402

GOOD_FRAME = {"title": "a frame", "detail": "a detail", "leave": "a way out"}


def _spending() -> dict:
    return {
        "contract": "SpendingBreakdown.v1", "state": "ready",
        "title": "Spending breakdown", "as_of": "2026-09-30",
        "timezone_policy": "Inclusive local calendar dates.",
        "period": {"id": "latest_complete_month", "label": "August",
                   "start_date": "2026-08-01", "end_date": "2026-08-31"},
        "granularity": "category", "scope_summary": "Everyday · USD",
        "controls": {
            "periods": [
                {"id": "latest_complete_month", "label": "Last complete month", "requires_custom": False},
                {"id": "current_month", "label": "This month", "requires_custom": False},
                {"id": "last_3_months", "label": "Last 3 months", "requires_custom": False},
                {"id": "year_to_date", "label": "Year to date", "requires_custom": False},
                {"id": "custom", "label": "Custom range", "requires_custom": True},
            ],
            "granularities": [{"id": "category", "label": "Category"},
                              {"id": "subcategory", "label": "Subcategory"}],
            "accounts": [{"id": "acct:one", "label": "Everyday",
                          "currency": "USD", "order": 0}],
            "currencies": [{"id": "USD", "label": "USD", "order": 0}],
            "selected_period": "latest_complete_month",
            "selected_granularity": "category",
            "selected_account_id": "acct:one", "selected_currency": "USD",
        },
        "sections": [{"currency": "USD", "order": 0, "included_count": 1,
                      "total_display": "USD 12.00", "empty_message": "",
                      "bars": [{"id": "food", "order": 0, "label": "Food",
                                "amount_display": "USD 12.00",
                                "share_basis_points": 10000,
                                "bar_basis_points": 10000, "count": 1,
                                "color_token": "category-1"}]}],
        "coverage": {"state": "complete", "label": "Complete coverage.",
                     "covered_from": "2026-08-01", "covered_to": "2026-08-31",
                     "gaps": [], "unsupported_accounts": [],
                     "included_count": 1, "excluded_count": 0},
        "exclusions": [], "notes": ["Currencies remain separate."],
    }


def _stand_in(tmp_path: Path, replies: dict, name: str = "sidecar") -> Path:
    """One executable that answers each operation with what it is given.

    A whole executable rather than a mock, because what is under test is a
    validator that starts a process and reads its output: a mock would test the
    validator against an object it will never meet."""
    script = tmp_path / name
    script.write_text(
        "#!/usr/bin/env python3\n"
        "import copy, json, sys\n"
        f"replies = json.loads({json.dumps(json.dumps(replies))})\n"
        "declined = set()\n"
        "for line in sys.stdin:\n"
        "    if not line.strip():\n"
        "        continue\n"
        "    asked = json.loads(line)\n"
        "    operation = asked['operation']\n"
        "    payload = asked.get('payload') or {}\n"
        "    if operation == 'viva.conversation.decline':\n"
        "        declined.add(payload.get('question_id'))\n"
        "    surface_key = operation + ':' + str(payload.get('surface', ''))\n"
        "    said = replies.get(surface_key, replies.get(operation, replies.get('*')))\n"
        "    if said is None:\n"
        "        said = {'ok': False, 'error': {'code': 'operation_not_allowed'}}\n"
        "    said = copy.deepcopy(said)\n"
        "    data = (said.get('result') or {}).get('data')\n"
        "    if isinstance(data, dict) and declined:\n"
        "        if payload.get('surface') == 'conversation':\n"
        "            data['questions'] = [q for q in data.get('questions', []) if q.get('id') not in declined]\n"
        "            data['total'] = len(data['questions'])\n"
        "            data['tail'] = {'count': 0, 'amount': '0'}\n"
        "        if payload.get('surface') == 'review':\n"
        "            for group in data.get('groups', []):\n"
        "                group['items'] = [i for i in group.get('items', []) if (i.get('target') or {}).get('question_id') not in declined]\n"
        "                group['count'] = len(group['items'])\n"
        "            data['groups'] = [g for g in data.get('groups', []) if g.get('items')]\n"
        "            count = sum(len(g['items']) for g in data['groups'])\n"
        "            data['actionable_count'] = data['shown_count'] = count\n"
        "            data['remaining_count'] = 0\n"
        "    said.setdefault('protocol', '2.0')\n"
        "    said['request_id'] = asked['request_id']\n"
        "    sys.stdout.write(json.dumps(said) + '\\n')\n"
        "    sys.stdout.flush()\n",
        encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return script


def _working(**overrides) -> dict:
    ids = [f"question-{index}" for index in range(11)]
    def binding(identity):
        target = {"kind": "conversation", "question_id": identity,
                  "disclosure": "Open the exact conversation."}
        return {
            "item_id": f"question:{identity}", "question_id": identity,
            "question_kind": "identity", "label": f"Question {identity}",
            "reason": "Synthetic package question.",
            "refs": {"movement": "", "movements": [], "candidates": [],
                     "document": "", "doc_id": "", "account": ""},
            "target": target, "status": "open",
            "primary_action": "open_question",
            "allowed_actions": ["open_question"],
        }
    bindings = {identity: binding(identity) for identity in ids}
    review_items = [{
        "id": f"question:{identity}", "label": f"Question {identity}",
        "reason": "Synthetic package question.", "target": bindings[identity]["target"],
        "status": "open", "primary_action": "open_question",
        "allowed_actions": ["open_question"], "binding": bindings[identity],
    } for identity in ids]
    replies = {
        "bridge.handshake": {"ok": True, "result": {
            "protocol": "2.0", "transport": "json-lines", "revision": "abcdef123456"}},
        "viva.lifecycle.read": {"ok": True, "result": {
            "state": "absent", "origin": "packaged", "revision": "abcdef123456"}},
        "bridge.open_demo_vault": {"ok": True, "result": {
            "state": "opened", "sample": True, "frame": GOOD_FRAME}},
        "viva.surface.read": {"ok": True, "result": {
            "surface": "overview", "job_id": "j", "data": {"state": "ready"}}},
        "viva.surface.read:conversation": {"ok": True, "result": {
            "surface": "conversation", "job_id": "j", "data": {
                "state": "ready", "questions": [{
                    "id": identity, "kind": "identity",
                    "text": f"Question {identity}",
                    "why": "Synthetic package question.", "refs": {},
                    "review_binding": bindings[identity],
                } for identity in ids],
                "total": len(ids), "tail": {"count": 0, "amount": "0"}}}},
        "viva.surface.read:review": {"ok": True, "result": {
            "surface": "review", "job_id": "j", "data": {
                "state": "ready", "groups": [{"items": review_items}],
                "actionable_count": len(ids), "shown_count": len(ids),
                "remaining_count": 0}}},
        "viva.surface.read:spending": {"ok": True, "result": {
            "surface": "spending", "job_id": "j", "data": _spending()}},
        "viva.conversation.decline": {"ok": True, "result": {
            "kind": "completed", "message": "Set aside.", "reason": None,
            "state": None}},
    }
    if "viva.surface.read" in overrides:
        replies.pop("viva.surface.read:conversation")
        replies.pop("viva.surface.read:review")
    replies.update(overrides)
    return replies


def _run(tmp_path: Path, replies: dict) -> list[str]:
    return checker.validate(_stand_in(tmp_path, replies))


# --------------------------------------------------- an artifact that answers


def test_a_build_that_answers_everything_is_reported_in_words(tmp_path: Path):
    said = _run(tmp_path, _working())

    assert any("names itself abcdef123456" in line for line in said)
    assert any("packaged build" in line for line in said)
    assert any("sample vault" in line for line in said)
    assert any("every surface" in line for line in said)
    assert any("beyond index ten" in line for line in said)


@pytest.mark.parametrize("contradiction", ["missing", "duplicate", "reordered"])
def test_a_build_with_unpaired_review_and_conversation_questions_fails(
        tmp_path: Path, contradiction: str):
    replies = _working()
    conversation = replies["viva.surface.read:conversation"]["result"]["data"]
    questions = conversation["questions"]
    if contradiction == "missing":
        questions.pop()
    elif contradiction == "duplicate":
        questions[-1] = dict(questions[0])
    else:
        questions[0], questions[1] = questions[1], questions[0]

    with pytest.raises(SystemExit, match="one-for-one in order"):
        _run(tmp_path, replies)


@pytest.mark.parametrize("contradiction", [
    "review-label", "review-reason", "conversation-label",
    "conversation-reason", "question-kind", "conversation-target",
    "document-ref", "account-target", "canonical-target",
    "requested-target", "member-target", "actions",
])
def test_a_build_with_same_id_but_changed_review_semantics_fails(
        tmp_path: Path, contradiction: str):
    replies = _working()
    item = replies["viva.surface.read:review"]["result"]["data"]["groups"][0]["items"][0]
    question = replies["viva.surface.read:conversation"]["result"]["data"]["questions"][0]
    # The fixture builder intentionally reuses its value objects. Break that
    # Python alias here so each case models two independently serialized reads.
    item["binding"] = json.loads(json.dumps(item["binding"]))
    question["review_binding"] = json.loads(json.dumps(question["review_binding"]))
    if contradiction == "review-label":
        item["label"] = item["binding"]["label"] = "Changed Review label"
    elif contradiction == "review-reason":
        item["reason"] = item["binding"]["reason"] = "Changed Review reason."
    elif contradiction == "conversation-label":
        question["text"] = question["review_binding"]["label"] = "Changed conversation label"
    elif contradiction == "conversation-reason":
        question["why"] = question["review_binding"]["reason"] = "Changed conversation reason."
    elif contradiction == "question-kind":
        question["kind"] = question["review_binding"]["question_kind"] = "merchant"
    elif contradiction == "conversation-target":
        item["target"] = item["binding"]["target"] = {
            **item["target"], "disclosure": "Changed exact conversation target."}
    elif contradiction == "document-ref":
        question["refs"] = {"doc_id": "document-two"}
        question["review_binding"]["refs"]["doc_id"] = "document-two"
    else:
        target = {
            "kind": "transaction", "question_id": question["id"],
            "account_id": "account-one", "movement_id": "member-two",
            "canonical_movement_id": "member-one",
            "member_movement_ids": ["member-one", "member-two"],
        }
        refs = {
            "movement": "member-two", "movements": ["member-one", "member-two"],
            "candidates": [], "document": "", "doc_id": "",
            "account": "account-one",
        }
        item["target"] = item["binding"]["target"] = dict(target)
        item["primary_action"] = item["binding"]["primary_action"] = "open_transaction"
        item["allowed_actions"] = item["binding"]["allowed_actions"] = ["open_transaction"]
        item["binding"]["refs"] = dict(refs)
        if contradiction == "account-target":
            target["account_id"] = refs["account"] = "account-two"
        elif contradiction == "canonical-target":
            target["canonical_movement_id"] = "member-zero"
            target["member_movement_ids"] = ["member-two", "member-zero"]
        elif contradiction == "requested-target":
            target["movement_id"] = "member-one"
        elif contradiction == "member-target":
            target["member_movement_ids"] = ["member-one", "member-three", "member-two"]
        elif contradiction == "actions":
            # Review is already a coherent transaction action; Conversation
            # still says this same ID is a conversation-only action.
            pass
        question["refs"] = {key: value for key, value in refs.items()
                            if value not in ("", [])}
        question["review_binding"]["refs"] = refs
        question["review_binding"]["target"] = target
        question["review_binding"]["primary_action"] = "open_transaction"
        question["review_binding"]["allowed_actions"] = ["open_transaction"]
        if contradiction == "actions":
            question["review_binding"]["primary_action"] = "open_question"
            question["review_binding"]["allowed_actions"] = ["open_question"]

    with pytest.raises(SystemExit, match="semantic.*disagree"):
        _run(tmp_path, replies)


def test_the_sample_vault_is_minted_where_this_run_owns_it(tmp_path: Path, monkeypatch):
    """A validator that minted the sample vault in the home directory of
    whoever ran it would leave a real folder on a real machine."""
    seen: list[str] = []
    real = checker.subprocess.Popen

    def watched(*args, **kwargs):
        seen.append(kwargs["env"]["VIVA_DEMO_HOME"])
        return real(*args, **kwargs)

    monkeypatch.setattr(checker.subprocess, "Popen", watched)
    _run(tmp_path, _working())

    assert seen and not Path(seen[0]).exists()
    assert str(Path.home()) not in seen[0]


# ----------------------------------------------- each way a build can be wrong


def test_a_build_that_cannot_name_itself_fails(tmp_path: Path):
    """The build somebody is filing a report about is the one that most needs
    naming."""
    replies = _working(**{"bridge.handshake": {"ok": True, "result": {
        "protocol": "2.0", "transport": "json-lines", "revision": "unknown"}}})

    with pytest.raises(SystemExit, match="which revision it is"):
        _run(tmp_path, replies)


def test_a_build_that_says_it_is_a_source_tree_fails(tmp_path: Path):
    """A packaged artifact reporting itself as a checkout means the packaging
    step did not write its revision, so the installed copy would say the wrong
    thing about itself for the rest of its life."""
    replies = _working(**{"viva.lifecycle.read": {"ok": True, "result": {
        "state": "absent", "origin": "source"}}})

    with pytest.raises(SystemExit, match="rather than as a packaged build"):
        _run(tmp_path, replies)


def test_a_build_that_speaks_another_protocol_fails(tmp_path: Path):
    replies = _working(**{"bridge.handshake": {"ok": True, "result": {
        "protocol": "3.0", "revision": "abcdef123456"}}})

    with pytest.raises(SystemExit, match="speaks protocol"):
        _run(tmp_path, replies)


def test_a_sample_vault_that_opens_without_its_frame_fails(tmp_path: Path):
    """Nothing would say the money in it is invented."""
    replies = _working(**{"bridge.open_demo_vault": {"ok": True, "result": {
        "state": "opened", "sample": True}}})

    with pytest.raises(SystemExit, match="no frame"):
        _run(tmp_path, replies)


def test_a_build_that_opens_a_private_vault_instead_fails(tmp_path: Path):
    replies = _working(**{"bridge.open_demo_vault": {"ok": True, "result": {
        "state": "opened", "sample": False, "frame": GOOD_FRAME}}})

    with pytest.raises(SystemExit, match="as the sample vault"):
        _run(tmp_path, replies)


def test_a_surface_that_answers_with_nothing_fails(tmp_path: Path):
    replies = _working(**{"viva.surface.read": {"ok": True, "result": {
        "surface": "overview", "job_id": "j", "data": {}}}})

    with pytest.raises(SystemExit, match="nothing a screen could show"):
        _run(tmp_path, replies)


@pytest.mark.parametrize("mutation", [
    "raw_total", "share", "order", "count", "coverage",
    "compact_date", "unknown_period", "unknown_granularity",
    "unknown_selected_currency", "custom_not_custom", "fabricated_missing_id",
])
def test_a_packaged_spending_contract_with_inconsistent_chart_fails(
        tmp_path: Path, mutation: str):
    replies = _working()
    spending = replies["viva.surface.read:spending"]["result"]["data"]
    if mutation == "raw_total":
        spending["sections"][0]["total_exact"] = "12"
    elif mutation == "share":
        spending["sections"][0]["bars"][0]["share_basis_points"] = 9999
    elif mutation == "order":
        spending["sections"][0]["bars"][0]["order"] = 1
    elif mutation == "count":
        spending["coverage"]["included_count"] = 2
    elif mutation == "coverage":
        spending["coverage"]["covered_from"] = "not-a-date"
    elif mutation == "compact_date":
        spending["as_of"] = "20260930"
    elif mutation == "unknown_period":
        spending["period"]["id"] = "fortnight"
        spending["controls"]["selected_period"] = "fortnight"
    elif mutation == "unknown_granularity":
        spending["granularity"] = "merchant"
        spending["controls"]["selected_granularity"] = "merchant"
    elif mutation == "unknown_selected_currency":
        spending["controls"]["selected_account_id"] = ""
        spending["controls"]["selected_currency"] = "GBP"
        spending["sections"][0]["currency"] = "GBP"
    elif mutation == "fabricated_missing_id":
        spending["controls"]["selected_account_id"] = ""
        spending["coverage"]["state"] = "partial"
        spending["coverage"]["unsupported_accounts"] = [{
            "order": 0, "account_id": "unsupported-1", "label": "Missing",
            "currency": "USD", "reason": "missing_account_id",
            "sentence": "Missing has no stable account identity.",
        }]
    else:
        spending["controls"]["periods"][-1]["requires_custom"] = False

    with pytest.raises(SystemExit, match="SpendingBreakdown"):
        _run(tmp_path, replies)


def test_packaged_spending_allows_ordered_missing_identity_disclosures():
    spending = _spending()
    spending["controls"]["selected_account_id"] = ""
    spending["coverage"]["state"] = "partial"
    spending["coverage"]["unsupported_accounts"] = [
        {"order": 0, "account_id": "", "label": "First missing",
         "currency": "USD", "reason": "missing_account_id",
         "sentence": "First missing has no stable account identity."},
        {"order": 1, "account_id": "", "label": "Second missing",
         "currency": "USD", "reason": "missing_account_id",
         "sentence": "Second missing has no stable account identity."},
        {"order": 2, "account_id": "acct:no-name", "label": "No name",
         "currency": "", "reason": "missing_account_name",
         "sentence": "No name has no account name."},
    ]

    checker._spending_contract(spending)


@pytest.mark.parametrize("mutation", [
    "null_empty_message", "boolean_account_order", "boolean_currency_order",
    "boolean_section_order", "boolean_bar_order", "boolean_gap_order",
    "boolean_unsupported_order", "boolean_section_count", "boolean_bar_count",
    "boolean_share_basis_points", "boolean_bar_basis_points",
    "boolean_coverage_included_count", "boolean_coverage_excluded_count",
    "boolean_exclusion_count", "missing_currency_with_value",
])
def test_packaged_spending_rejects_non_exact_json_types_and_reason_fields(
        mutation: str):
    spending = _spending()
    if mutation == "null_empty_message":
        spending["sections"][0]["empty_message"] = None
    elif mutation == "boolean_account_order":
        spending["controls"]["accounts"][0]["order"] = False
    elif mutation == "boolean_currency_order":
        spending["controls"]["currencies"][0]["order"] = False
    elif mutation == "boolean_section_order":
        spending["sections"][0]["order"] = False
    elif mutation == "boolean_bar_order":
        spending["sections"][0]["bars"][0]["order"] = False
    elif mutation == "boolean_gap_order":
        spending["coverage"]["state"] = "partial"
        spending["coverage"]["gaps"] = [{
            "order": False, "account_id": "acct:one", "account_label": "Everyday",
            "from": "2026-08-10", "to": "2026-08-11",
            "reason": "missing_statement_coverage", "sentence": "A gap.",
        }]
    elif mutation == "boolean_unsupported_order":
        spending["controls"]["selected_account_id"] = ""
        spending["coverage"]["state"] = "partial"
        spending["coverage"]["unsupported_accounts"] = [{
            "order": False, "account_id": "acct:no-name", "label": "No name",
            "currency": "USD", "reason": "missing_account_name",
            "sentence": "No name is outside this scope.",
        }]
    elif mutation == "boolean_section_count":
        spending["sections"][0]["included_count"] = True
    elif mutation == "boolean_bar_count":
        spending["sections"][0]["bars"][0]["count"] = True
    elif mutation == "boolean_share_basis_points":
        spending["sections"][0]["bars"][0]["share_basis_points"] = True
    elif mutation == "boolean_bar_basis_points":
        spending["sections"][0]["bars"][0]["bar_basis_points"] = True
    elif mutation == "boolean_coverage_included_count":
        spending["coverage"]["included_count"] = True
    elif mutation == "boolean_coverage_excluded_count":
        spending["coverage"]["excluded_count"] = False
    elif mutation == "boolean_exclusion_count":
        spending["exclusions"] = [{
            "kind": "transfer", "count": True, "sentence": "Excluded."}]
        spending["coverage"]["excluded_count"] = 1
    else:
        spending["controls"]["selected_account_id"] = ""
        spending["coverage"]["state"] = "partial"
        spending["coverage"]["unsupported_accounts"] = [{
            "order": 0, "account_id": "acct:no-money", "label": "No money",
            "currency": "USD", "reason": "missing_account_currency",
            "sentence": "No money has no currency.",
        }]

    with pytest.raises(SystemExit, match="SpendingBreakdown"):
        checker._spending_contract(spending)


def test_packaged_spending_rejects_coherent_unsafe_included_counts():
    spending = _spending()
    unsafe = 2 ** 53
    spending["sections"][0]["bars"][0]["count"] = unsafe
    spending["sections"][0]["included_count"] = unsafe
    spending["coverage"]["included_count"] = unsafe

    with pytest.raises(SystemExit, match="SpendingBreakdown"):
        checker._spending_contract(spending)


def test_packaged_spending_rejects_coherent_unsafe_excluded_counts():
    spending = _spending()
    unsafe = 2 ** 53
    spending["exclusions"] = [{
        "kind": "transfer", "count": unsafe, "sentence": "Excluded."}]
    spending["coverage"]["excluded_count"] = unsafe

    with pytest.raises(SystemExit, match="SpendingBreakdown"):
        checker._spending_contract(spending)


def test_packaged_spending_accepts_coherent_max_safe_counts():
    spending = _spending()
    maximum = 9_007_199_254_740_991
    spending["sections"][0]["bars"][0]["count"] = maximum
    spending["sections"][0]["included_count"] = maximum
    spending["coverage"]["included_count"] = maximum
    spending["exclusions"] = [{
        "kind": "transfer", "count": maximum, "sentence": "Excluded."}]
    spending["coverage"]["excluded_count"] = maximum

    checker._spending_contract(spending)


def test_a_build_that_answers_an_undeclared_operation_fails(tmp_path: Path):
    """An allowlist that answers everything is not an allowlist."""
    replies = _working(**{"*": {"ok": True, "result": {"anything": True}}})

    with pytest.raises(SystemExit, match="nobody declared"):
        _run(tmp_path, replies)


def test_a_build_that_stops_answering_fails_rather_than_hanging(tmp_path: Path):
    script = tmp_path / "silent"
    script.write_text("#!/usr/bin/env python3\nimport sys\nsys.exit(0)\n", encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IXUSR)

    with pytest.raises(SystemExit, match="stopped answering"):
        checker.validate(script)


def test_a_build_that_writes_something_that_is_not_a_frame_fails(tmp_path: Path):
    script = tmp_path / "chatty"
    script.write_text("#!/usr/bin/env python3\n"
                      "import sys\n"
                      "for line in sys.stdin:\n"
                      "    sys.stdout.write('not a frame\\n')\n"
                      "    sys.stdout.flush()\n", encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IXUSR)

    with pytest.raises(SystemExit, match="not a frame"):
        checker.validate(script)


def test_a_file_that_is_not_executable_fails_before_anything_runs(tmp_path: Path):
    plain = tmp_path / "plain"
    plain.write_text("", encoding="utf-8")
    plain.chmod(plain.stat().st_mode & ~stat.S_IXUSR & ~stat.S_IXGRP & ~stat.S_IXOTH)

    with pytest.raises(SystemExit, match="not executable"):
        checker.validate(plain)

    with pytest.raises(SystemExit, match="no such executable"):
        checker.validate(tmp_path / "absent")


# --------------------------------------- what it walks is what it is checking


def test_every_surface_an_opened_vault_serves_is_walked():
    """A surface added to the provider and not here would be a screen this
    check reports as working without ever having asked it anything."""
    from viva.desktop_bridge.vault_surface import OpenedVaultSurfaceProvider

    assert set(checker.SURFACES) == OpenedVaultSurfaceProvider._SURFACES
