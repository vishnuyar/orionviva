#!/usr/bin/env python3
"""Run a built sidecar the way the application runs it, and say what it did.

Everything else in this repository checks the source tree. This runs the
artifact: it starts the packaged executable as a subprocess, speaks the real
protocol to it over standard input and output, opens a vault through it and
reads every surface an opened vault answers. A build that imports cleanly and
cannot answer a frame is exactly the build a person downloads.

**The vault it opens is the sample one.** It is a real vault the engine mints
in a temporary home, so this exercises the path a person takes rather than a
fixture: no passphrase is passed in, none is printed, and nothing this touches
is anybody's own records. The home is removed on the way out.

**It asserts the build names itself.** A build that cannot say which revision it
is is the one somebody filing a report most needs named, so a handshake that
answers with the word for not knowing fails here rather than reaching a person.

**Nothing here is a substitute for the build having been signed.** This says the
executable runs and answers; whether it was notarised, and by whom, is the
release workflow's own question and is checked there.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, NoReturn

ROOT = Path(__file__).resolve().parents[1]
SIDECAR_NAME = "viva-desktop-bridge"

# The protocol this speaks. Written here rather than imported, because the
# subject is a packaged artifact and importing the product to test the package
# would be asking the source tree what the package does.
PROTOCOL = "2.0"

# The word a build uses for a revision it could not establish. Same reason.
UNKNOWN_REVISION = "unknown"

# What an opened vault must answer. A build that serves four of them is not a
# build a person can use, and a list this walks is the whole of what is
# checked, so a surface added later joins it here.
SURFACES = ("overview", "spending", "documents", "conversation", "review", "jobs", "trust", "activity",
            "account_ledger", "plans")
READ_ON = "2026-09-30"
SPENDING_MAX_SAFE_INTEGER = 9_007_199_254_740_991


def fail(message: str) -> NoReturn:
    raise SystemExit(f"packaged artifact: {message}")


def _canonical_date(value: Any, field: str) -> datetime.date:
    """Accept only the protocol's canonical YYYY-MM-DD calendar spelling."""
    if type(value) is not str:
        fail(f"SpendingBreakdown.v1 supplied an invalid {field}")
    try:
        parsed = datetime.date.fromisoformat(value)
    except ValueError:
        fail(f"SpendingBreakdown.v1 supplied an invalid {field}")
    if parsed.isoformat() != value:
        fail(f"SpendingBreakdown.v1 supplied a non-canonical {field}")
    return parsed


def _spending_text(value: Any, *, nonempty: bool = True) -> bool:
    """Match the desktop adapter's exact JSON string checks."""
    return type(value) is str and (not nonempty or bool(value.strip()))


def _spending_integer(value: Any, minimum: int = 0,
                      maximum: int = SPENDING_MAX_SAFE_INTEGER) -> bool:
    """A JSON boolean is not a SpendingBreakdown integer."""
    return type(value) is int and minimum <= value <= maximum


class Sidecar:
    """One packaged executable, spoken to the way the host speaks to it."""

    def __init__(self, executable: Path, home: Path) -> None:
        environment = dict(os.environ)
        # The sample vault goes somewhere this run owns and deletes. Without
        # this it would be minted in the home directory of whoever ran the
        # check, which is a real folder on a real machine.
        environment["VIVA_DEMO_HOME"] = str(home)
        self._process = subprocess.Popen(
            [str(executable)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, env=environment, cwd=str(home))
        self._request = 0

    def ask(self, operation: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """One request, one reply, in the order the transport guarantees.

        A reply that is not a whole JSON line, or that answers a different
        request, is a protocol failure rather than a value to interpret: the
        host would have nothing to render either."""
        self._request += 1
        request_id = f"validate-{self._request}"
        frame = json.dumps({"protocol": PROTOCOL, "request_id": request_id,
                            "operation": operation, "payload": payload or {}})
        assert self._process.stdin is not None and self._process.stdout is not None
        self._process.stdin.write(frame + "\n")
        self._process.stdin.flush()
        while True:
            line = self._process.stdout.readline()
            if not line:
                fail(f"the sidecar stopped answering during {operation}")
            try:
                answered = json.loads(line)
            except json.JSONDecodeError:
                fail(f"the sidecar wrote a line that is not a frame during {operation}")
            # Progress frames carry no request outcome and are not replies.
            if answered.get("event"):
                continue
            if answered.get("request_id") != request_id:
                fail(f"the sidecar answered {answered.get('request_id')!r} to "
                     f"{request_id!r}")
            return answered

    def close(self) -> None:
        if self._process.stdin is not None:
            self._process.stdin.close()
        try:
            self._process.wait(timeout=20)
        except subprocess.TimeoutExpired:
            self._process.kill()


def _result(answered: dict[str, Any], operation: str) -> dict[str, Any]:
    if not answered.get("ok"):
        error = answered.get("error") or {}
        fail(f"{operation} was refused: {error.get('code', 'no code')}")
    result = answered.get("result")
    if not isinstance(result, dict):
        fail(f"{operation} answered with nothing a host could read")
    return result


def _review_conversation_ids(review: dict[str, Any], conversation: dict[str, Any]) -> list[str]:
    """Validate the actionable pair exactly as the desktop must receive it."""
    groups = review.get("groups")
    questions = conversation.get("questions")
    if not isinstance(groups, list) or not isinstance(questions, list):
        fail("Review and conversation did not supply actionable question lists")
    items = [item for group in groups if isinstance(group, dict)
             for item in group.get("items", []) if isinstance(item, dict)]
    targets = [item.get("target") for item in items]
    if any(not isinstance(target, dict) for target in targets):
        fail("Review supplied an item without a readable target")
    review_ids = [str(target.get("question_id") or "")
                  for target in targets if isinstance(target, dict)]
    conversation_ids = [str(item.get("id") or "")
                        for item in questions if isinstance(item, dict)]
    if (not all(review_ids) or not all(conversation_ids)
            or len(review_ids) != len(set(review_ids))
            or len(conversation_ids) != len(set(conversation_ids))
            or review_ids != conversation_ids):
        fail("Review targets do not match conversation questions one-for-one in order")
    total = conversation.get("total")
    if (not isinstance(total, int) or isinstance(total, bool)
            or review.get("actionable_count") != total
            or review.get("shown_count") != len(review_ids)
            or review.get("remaining_count") != total - len(review_ids)):
        fail("Review and conversation question counts disagree")
    tail = conversation.get("tail")
    if isinstance(tail, dict) and tail.get("count") != review.get("remaining_count"):
        fail("Review remaining count and conversation tail disagree")
    binding_keys = {
        "item_id", "question_id", "question_kind", "label", "reason", "refs",
        "target", "status", "primary_action", "allowed_actions",
    }
    ref_keys = {"movement", "movements", "candidates", "document", "doc_id", "account"}
    for item, question in zip(items, questions):
        if not isinstance(question, dict):
            fail("conversation supplied an unreadable actionable question")
        review_binding = item.get("binding")
        conversation_binding = question.get("review_binding")
        if (not isinstance(review_binding, dict)
                or not isinstance(conversation_binding, dict)
                or set(review_binding) != binding_keys
                or set(conversation_binding) != binding_keys
                or review_binding != conversation_binding):
            fail("Review and conversation semantic bindings disagree")
        refs = conversation_binding.get("refs")
        target = conversation_binding.get("target")
        if not isinstance(refs, dict) or set(refs) != ref_keys or not isinstance(target, dict):
            fail("Review and conversation semantic binding was not closed")
        question_refs = question.get("refs") if isinstance(question.get("refs"), dict) else {}
        normalized_refs = {
            "movement": question_refs.get("movement", ""),
            "movements": question_refs.get("movements", []),
            "candidates": question_refs.get("candidates", []),
            "document": question_refs.get("document", ""),
            "doc_id": question_refs.get("doc_id", ""),
            "account": question_refs.get("account", ""),
        }
        if (conversation_binding.get("item_id") != item.get("id")
                or conversation_binding.get("question_id") != question.get("id")
                or conversation_binding.get("question_kind") != question.get("kind")
                or conversation_binding.get("label") != question.get("text")
                or conversation_binding.get("reason") != question.get("why")
                or refs != normalized_refs
                or target != item.get("target")
                or conversation_binding.get("status") != item.get("status")
                or conversation_binding.get("primary_action") != item.get("primary_action")
                or conversation_binding.get("allowed_actions") != item.get("allowed_actions")):
            fail("Review and conversation question semantics disagree")
    return review_ids


def _spending_contract(spending: dict[str, Any]) -> None:
    """Validate the packaged chart without importing source-tree adapters."""
    expected = {"contract", "state", "title", "as_of", "timezone_policy",
                "period", "granularity", "scope_summary", "controls",
                "sections", "coverage", "exclusions", "notes"}
    if (set(spending) != expected
            or not _spending_text(spending.get("contract"))
            or spending.get("contract") != "SpendingBreakdown.v1"):
        fail("SpendingBreakdown.v1 did not have its closed top-level shape")
    if spending.get("state") not in ("ready", "empty"):
        fail("SpendingBreakdown.v1 used an undeclared top-level state")
    if not all(_spending_text(spending.get(name))
               for name in ("title", "as_of", "timezone_policy", "scope_summary")):
        fail("SpendingBreakdown.v1 omitted authored labels or its read date")
    read_on = _canonical_date(spending["as_of"], "read date")

    period = spending.get("period")
    controls = spending.get("controls")
    coverage = spending.get("coverage")
    if (not isinstance(period, dict)
            or set(period) != {"id", "label", "start_date", "end_date"}
            or not isinstance(controls, dict)
            or set(controls) != {"periods", "granularities", "accounts",
                                 "currencies", "selected_period",
                                 "selected_granularity", "selected_account_id",
                                 "selected_currency"}
            or not isinstance(coverage, dict)
            or set(coverage) != {"state", "label", "covered_from", "covered_to",
                                 "gaps", "unsupported_accounts", "included_count",
                                 "excluded_count"}):
        fail("SpendingBreakdown.v1 controls, period, or coverage were not closed")
    start = _canonical_date(period.get("start_date"), "period start")
    end = _canonical_date(period.get("end_date"), "period end")
    if start > end or end > read_on:
        fail("SpendingBreakdown.v1 supplied a period outside its read date")
    periods = controls.get("periods")
    if (not isinstance(periods, list) or any(
            not isinstance(item, dict)
            or set(item) != {"id", "label", "requires_custom"}
            or not _spending_text(item.get("id"))
            or not _spending_text(item.get("label"))
            or type(item.get("requires_custom")) is not bool
            for item in periods)):
        fail("SpendingBreakdown.v1 date options were invalid")
    period_ids = [item.get("id") for item in periods]
    if period_ids != ["latest_complete_month", "current_month", "last_3_months",
                      "year_to_date", "custom"]:
        fail("SpendingBreakdown.v1 did not supply the exact date controls")
    if any(item["requires_custom"] != (item["id"] == "custom")
           for item in periods):
        fail("SpendingBreakdown.v1 date controls contradicted custom-range semantics")
    granularity_options = controls.get("granularities")
    if (not isinstance(granularity_options, list) or any(
            not isinstance(item, dict) or set(item) != {"id", "label"}
            or not _spending_text(item.get("id"))
            or not _spending_text(item.get("label"))
            for item in granularity_options)):
        fail("SpendingBreakdown.v1 breakdown options were invalid")
    granularities = [item.get("id") for item in granularity_options]
    if granularities != ["category", "subcategory"]:
        fail("SpendingBreakdown.v1 did not supply the exact breakdown controls")
    if (period.get("id") not in period_ids
            or controls.get("selected_period") not in period_ids
            or spending.get("granularity") not in granularities
            or controls.get("selected_granularity") not in granularities
            or period.get("id") != controls.get("selected_period")
            or spending.get("granularity") != controls.get("selected_granularity")):
        fail("SpendingBreakdown.v1 selected controls contradicted its result")

    accounts = controls.get("accounts")
    currencies = controls.get("currencies")
    sections = spending.get("sections")
    if not all(isinstance(value, list) for value in (accounts, currencies, sections)):
        fail("SpendingBreakdown.v1 options or currency sections were not lists")
    if (any(not isinstance(item, dict)
            or set(item) != {"id", "label", "currency", "order"}
            or not all(_spending_text(item.get(name))
                       for name in ("id", "label", "currency"))
            or not _spending_integer(item.get("order"))
            or item.get("order") != index for index, item in enumerate(accounts))
            or any(not isinstance(item, dict)
                   or set(item) != {"id", "label", "order"}
                   or not all(_spending_text(item.get(name))
                              for name in ("id", "label"))
                   or not _spending_integer(item.get("order"))
                   or item.get("order") != index
                   for index, item in enumerate(currencies))
            or any(not isinstance(item, dict)
                   or not _spending_integer(item.get("order"))
                   or item.get("order") != index
                   for index, item in enumerate(sections))):
        fail("SpendingBreakdown.v1 option or section order was inconsistent")
    currency_ids = [item.get("id") for item in currencies if isinstance(item, dict)]
    account_ids = [item.get("id") for item in accounts if isinstance(item, dict)]
    if (len(currency_ids) != len(currencies) or len(set(currency_ids)) != len(currency_ids)
            or len(account_ids) != len(accounts) or len(set(account_ids)) != len(account_ids)
            or any(item.get("currency") not in currency_ids for item in accounts
                   if isinstance(item, dict))):
        fail("SpendingBreakdown.v1 account and currency options disagreed")
    selected_currency = controls.get("selected_currency")
    selected_account = controls.get("selected_account_id")
    if (not _spending_text(selected_account, nonempty=False)
            or not _spending_text(selected_currency, nonempty=False)
            or (selected_account and selected_account not in {
                item["id"] for item in accounts})
            or (selected_currency and selected_currency not in currency_ids)):
        fail("SpendingBreakdown.v1 selected account scope was invalid")
    if selected_account:
        selected_account_currency = next(
            item["currency"] for item in accounts if item["id"] == selected_account)
        if (currency_ids != [selected_account_currency]
                or selected_currency not in ("", selected_account_currency)):
            fail("SpendingBreakdown.v1 selected account and currency disagreed")
    section_currencies = [item.get("currency") for item in sections
                          if isinstance(item, dict)]
    expected_sections = [selected_currency] if selected_currency else currency_ids
    if (any(not _spending_text(value)
            for value in section_currencies)
            or len(set(section_currencies)) != len(section_currencies)
            or any(value not in currency_ids for value in section_currencies)
            or section_currencies != expected_sections):
        fail("SpendingBreakdown.v1 combined or misplaced currency sections")

    included = 0
    any_bars = False
    for section in sections:
        if (not isinstance(section, dict)
                or set(section) != {"currency", "order", "included_count",
                                    "total_display", "bars", "empty_message"}
                or not _spending_text(section.get("currency"))
                or not _spending_integer(section.get("order"))
                or not _spending_integer(section.get("included_count"))
                or not _spending_text(section.get("total_display"))
                or not _spending_text(section.get("empty_message"), nonempty=False)
                or not isinstance(section.get("bars"), list)):
            fail("SpendingBreakdown.v1 supplied an invalid currency section")
        bars = section["bars"]
        bar_ids: list[str] = []
        count = 0
        shares = 0
        prior_width = 10001
        for index, bar in enumerate(bars):
            if (not isinstance(bar, dict)
                    or set(bar) != {"id", "order", "label", "amount_display",
                                        "share_basis_points", "bar_basis_points",
                                        "count", "color_token"}
                    or not _spending_integer(bar.get("order"))
                    or bar.get("order") != index
                    or not _spending_integer(bar.get("count"), 1)
                    or not _spending_integer(
                        bar.get("share_basis_points"), 0, 10000)
                    or not _spending_integer(
                        bar.get("bar_basis_points"), 0, 10000)
                    or bar["bar_basis_points"] > prior_width
                    or not all(_spending_text(bar.get(name))
                               for name in ("id", "label", "amount_display", "color_token"))
                    or bar.get("color_token") not in {
                        "category-1", "category-2", "category-3",
                        "category-4", "category-5", "category-6"}):
                fail("SpendingBreakdown.v1 supplied an invalid authored bar")
            bar_ids.append(bar["id"])
            count += bar["count"]
            shares += bar["share_basis_points"]
            prior_width = bar["bar_basis_points"]
        if len(set(bar_ids)) != len(bar_ids):
            fail("SpendingBreakdown.v1 bar identity was ambiguous")
        if bars and (bars[0]["bar_basis_points"] != 10000 or shares != 10000
                     or section.get("empty_message")):
            fail("SpendingBreakdown.v1 bar proportions or empty state disagreed")
        if not bars and (section.get("included_count") != 0
                         or not section.get("empty_message")):
            fail("SpendingBreakdown.v1 empty currency section was inconsistent")
        if section.get("included_count") != count:
            fail("SpendingBreakdown.v1 currency movement count disagreed")
        included += count
        any_bars = any_bars or bool(bars)
    exclusions = spending.get("exclusions")
    exclusion_kinds = {
        "outside_attested_coverage", "unattested_posting", "conflicted_posting",
        "provisional_treatment", "transfer", "debt_or_settlement",
        "mixed_treatment", "income_or_non_expense", "unknown_treatment",
        "undecided_treatment", "duplicate_conflict", "account_scope_conflict",
        "invalid_date"}
    if not isinstance(exclusions, list) or any(
            not isinstance(item, dict) or set(item) != {"kind", "count", "sentence"}
            or not _spending_integer(item.get("count"), 1)
            or not _spending_text(item.get("kind"))
            or item.get("kind") not in exclusion_kinds
            or not _spending_text(item.get("sentence"))
            for item in exclusions):
        fail("SpendingBreakdown.v1 exclusions were invalid")
    if len({item["kind"] for item in exclusions}) != len(exclusions):
        fail("SpendingBreakdown.v1 exclusion identity was ambiguous")
    if (not _spending_integer(coverage.get("included_count"))
            or not _spending_integer(coverage.get("excluded_count"))
            or coverage.get("included_count") != included
            or coverage.get("excluded_count") != sum(item["count"] for item in exclusions)
            or (spending["state"] == "ready") != any_bars):
        fail("SpendingBreakdown.v1 global counts or state disagreed")
    gaps = coverage.get("gaps")
    unsupported = coverage.get("unsupported_accounts")
    if not isinstance(gaps, list) or not isinstance(unsupported, list):
        fail("SpendingBreakdown.v1 coverage details were not lists")
    gap_ends: dict[str, datetime.date] = {}
    account_labels = {item["id"]: item["label"] for item in accounts}
    for index, gap in enumerate(gaps):
        if (not isinstance(gap, dict)
                or set(gap) != {"order", "account_id", "account_label", "from",
                                "to", "reason", "sentence"}
                or not _spending_integer(gap.get("order"))
                or gap.get("order") != index
                or not _spending_text(gap.get("reason"))
                or gap.get("reason") != "missing_statement_coverage"
                or not all(_spending_text(gap.get(name))
                           for name in ("account_id", "account_label", "sentence"))):
            fail("SpendingBreakdown.v1 supplied an invalid coverage gap")
        gap_start = _canonical_date(gap.get("from"), "coverage gap start")
        gap_end = _canonical_date(gap.get("to"), "coverage gap end")
        if gap_start < start or gap_start > gap_end or gap_end > end:
            fail("SpendingBreakdown.v1 supplied a coverage gap outside its period")
        if (account_labels.get(gap["account_id"]) != gap["account_label"]
                or (gap["account_id"] in gap_ends
                    and gap_start <= gap_ends[gap["account_id"]])):
            fail("SpendingBreakdown.v1 supplied ambiguous coverage gaps")
        gap_ends[gap["account_id"]] = gap_end
    unsupported_reasons = {"missing_account_id", "missing_account_name",
                           "unsupported_account_kind", "missing_account_currency"}
    for index, item in enumerate(unsupported):
        if (not isinstance(item, dict)
                or set(item) != {"order", "account_id", "label", "currency", "reason", "sentence"}
                or not _spending_integer(item.get("order"))
                or item.get("order") != index
                or not _spending_text(item.get("reason"))
                or item.get("reason") not in unsupported_reasons
                or not _spending_text(item.get("account_id"), nonempty=False)
                or not _spending_text(item.get("label"))
                or not _spending_text(item.get("currency"), nonempty=False)
                or not _spending_text(item.get("sentence"))):
            fail("SpendingBreakdown.v1 supplied an invalid unsupported account")
        if ((item["reason"] == "missing_account_id")
                != (item["account_id"] == "")
                or (item["reason"] == "missing_account_currency"
                    and item["currency"] != "")):
            fail("SpendingBreakdown.v1 unsupported account fields contradicted its reason")
    unsupported_ids = [item["account_id"] for item in unsupported
                       if item["account_id"]]
    if (len(set(unsupported_ids)) != len(unsupported_ids)
            or any(item in account_ids for item in unsupported_ids)
            or (selected_currency and any(
                item["currency"] and item["currency"] != selected_currency
                for item in unsupported))
            or (selected_account and unsupported)):
        fail("SpendingBreakdown.v1 unsupported account scope was ambiguous")
    state = coverage.get("state")
    covered_from, covered_to = coverage.get("covered_from"), coverage.get("covered_to")
    if (not _spending_text(state)
            or state not in {"complete", "partial", "unavailable"}
            or not _spending_text(coverage.get("label"))
            or not _spending_text(covered_from, nonempty=False)
            or not _spending_text(covered_to, nonempty=False)):
        fail("SpendingBreakdown.v1 supplied an invalid coverage state")
    if covered_from or covered_to:
        covered_start = _canonical_date(covered_from, "coverage start")
        covered_end = _canonical_date(covered_to, "coverage end")
        if covered_start < start or covered_start > covered_end or covered_end > end:
            fail("SpendingBreakdown.v1 supplied coverage outside its period")
    if state == "complete" and (gaps or unsupported or covered_from != period["start_date"] or covered_to != period["end_date"]):
        fail("SpendingBreakdown.v1 complete coverage contradicted its details")
    if state == "partial" and (not covered_from or not covered_to or not (gaps or unsupported)):
        fail("SpendingBreakdown.v1 partial coverage contradicted its details")
    if state == "unavailable" and (covered_from or covered_to or included):
        fail("SpendingBreakdown.v1 unavailable coverage contradicted its details")
    notes = spending.get("notes")
    if (not isinstance(notes, list) or not notes
            or any(not _spending_text(item) for item in notes)
            or len(set(notes)) != len(notes)):
        fail("SpendingBreakdown.v1 notes were invalid")


def validate(executable: Path) -> list[str]:
    """Everything this run establishes about the artifact, in words.

    Returns what it checked rather than printing as it goes, so a run that
    fails half way through has said nothing that reads like a pass."""
    if not executable.is_file():
        fail(f"no such executable: {executable}")
    if not os.access(executable, os.X_OK):
        fail(f"not executable: {executable}")

    home = Path(tempfile.mkdtemp(prefix="orionviva-artifact-"))
    checked: list[str] = []
    sidecar = Sidecar(executable, home)
    try:
        handshake = _result(sidecar.ask("bridge.handshake"), "bridge.handshake")
        if handshake.get("protocol") != PROTOCOL:
            fail(f"the artifact speaks protocol {handshake.get('protocol')!r}")
        revision = str(handshake.get("revision", ""))
        if not revision or revision == UNKNOWN_REVISION:
            fail("the artifact cannot say which revision it is, which is the "
                 "one thing a person filing a report about it needs")
        checked.append(f"answers the handshake, and names itself {revision}")

        lifecycle = _result(sidecar.ask("viva.lifecycle.read"), "viva.lifecycle.read")
        if lifecycle.get("origin") != "packaged":
            fail(f"the artifact reports itself as {lifecycle.get('origin')!r} "
                 "rather than as a packaged build")
        checked.append("reports itself as a packaged build")

        opened = _result(sidecar.ask("bridge.open_demo_vault"), "bridge.open_demo_vault")
        if opened.get("sample") is not True:
            fail("the artifact did not open the sample vault as the sample vault")
        if not (opened.get("frame") or {}).get("title"):
            fail("the artifact opened the sample vault with no frame to draw "
                 "around it, so nothing would say the money in it is invented")
        checked.append("mints and opens the sample vault, with its frame")

        surface_data: dict[str, dict[str, Any]] = {}
        for surface in SURFACES:
            parameters = ({"account_id": "acct:everyday-checking"}
                          if surface == "account_ledger" else
                          {"read_on": READ_ON} if surface == "spending" else {})
            read = _result(sidecar.ask("viva.surface.read", {
                "surface": surface, "job_id": f"validate-{surface}",
                "parameters": parameters}), f"viva.surface.read({surface})")
            data = read.get("data")
            if not isinstance(data, dict) or not data.get("state"):
                fail(f"the {surface} read answered with nothing a screen could show")
            surface_data[surface] = data
        checked.append(f"answers every surface an opened vault serves ({len(SURFACES)})")

        _spending_contract(surface_data["spending"])
        checked.append("validates the packaged SpendingBreakdown.v1 contract and authored chart invariants")

        question_ids = _review_conversation_ids(
            surface_data["review"], surface_data["conversation"])
        if len(question_ids) <= 10:
            fail("the sample supplied no actionable question beyond the old ten-item window")
        beyond_ten = question_ids[10]
        _result(sidecar.ask("viva.conversation.decline", {
            "question_id": beyond_ten, "reason": "not_now"}),
            "viva.conversation.decline")
        refreshed: dict[str, dict[str, Any]] = {}
        for surface in ("conversation", "review"):
            read = _result(sidecar.ask("viva.surface.read", {
                "surface": surface, "job_id": f"validate-refreshed-{surface}",
                "parameters": {}}), f"viva.surface.read({surface})")
            data = read.get("data")
            if not isinstance(data, dict):
                fail(f"the refreshed {surface} read was not data")
            refreshed[surface] = data
        refreshed_ids = _review_conversation_ids(
            refreshed["review"], refreshed["conversation"])
        if beyond_ten in refreshed_ids or len(refreshed_ids) != len(question_ids) - 1:
            fail("an actionable question beyond index ten did not resolve authoritatively")
        checked.append("pairs every shown Review target with conversation and resolves one beyond index ten")

        refused = sidecar.ask("viva.surface.snapshot")
        if refused.get("ok") is not False:
            fail("the artifact answered an operation nobody declared")
        checked.append("refuses an operation the registry does not declare")
    finally:
        sidecar.close()
        shutil.rmtree(home, ignore_errors=True)
    return checked


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executable", type=Path,
                        help="the packaged sidecar to run; defaults to the "
                             "staged one for this host")
    parser.add_argument("--target", help="Rust target triple, for the default path")
    args = parser.parse_args(argv)

    executable = args.executable
    if executable is None:
        if not args.target:
            fail("name an executable with --executable, or a target triple "
                 "with --target")
        suffix = ".exe" if "windows" in args.target else ""
        executable = (ROOT / "desktop" / "src-tauri" / "binaries"
                      / f"{SIDECAR_NAME}-{args.target}{suffix}")

    for said in validate(executable):
        print(f"packaged artifact: {said}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
