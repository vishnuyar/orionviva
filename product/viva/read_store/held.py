"""SQL-native held-document and identity-question composition.

The encrypted event log remains authoritative.  This module folds only the
normalized rows in one immutable read-store revision; it never opens raw
documents and never constructs ``LedgerProjection``.
"""
from __future__ import annotations

import datetime
import json
from decimal import Decimal
from types import SimpleNamespace

from .. import render
from ..ingest.brokerage import BrokerageFacts
from ..ingest.registry import (BALANCE_IDENTITY, BROKERAGE_IDENTITY,
                               account_kind_for, identity_of_facts)
from ..ingest.statement import StatementFacts
from ..ledger.identity import masked, masked_label
from ..ledger.projection.accounts import account_info, resolve
from ..ledger.projection.core import UnknownAccountError
from ..persona import say
from ..reply import Slot
from ..schemas import ANSWER_CHOICE, ANSWER_YES_NO
from .store import ReadStoreError


MAX_HELD_ROWS = 1_000
MAX_ACCOUNT_HISTORY_ROWS = 10_000
MAX_ACCOUNT_NAME_ROWS = 20_000
MAX_ALIAS_HISTORY_ROWS = 10_000
MAX_OBSERVATION_HISTORY_ROWS = 10_000
MAX_VALUE_ROWS_PER_ACCOUNT = 10_000
MAX_ENCODED_IDENTITY_BYTES = 1_000_000
MAX_ENCODED_HOLD_BYTES = 1_000_000
MAX_IDENTITY_CANDIDATES_PER_FINDING = 200
MAX_IDENTITY_CANDIDATES_TOTAL = 1_000
MAX_IDENTITY_KEY_BYTES = 512
MAX_IDENTITY_SCALAR_BYTES = 4_096
IDENTITY_SLOTS = (Slot(name="same_account", type=ANSWER_YES_NO, required=True),)


def _bounded(connection, sql, parameters, maximum, label):
    rows = connection.execute(sql, (*parameters, maximum + 1)).fetchall()
    if len(rows) > maximum:
        raise ReadStoreError(f"{label} exceeds its {maximum}-row read bound")
    return rows


def _bounded_text_columns(columns, numeric=()):
    names = columns.split(",")
    selected = [name if name in numeric else
                f"CASE WHEN {name} IS NULL THEN NULL "
                f"WHEN length(CAST({name} AS BLOB))<=? THEN {name} ELSE 1 END"
                for name in names]
    return ",".join(selected), (MAX_IDENTITY_SCALAR_BYTES,) * (
        len(names) - len(numeric))


def _refuse_oversized_text(rows, columns, numeric=()):
    names = columns.split(",")
    for row in rows:
        if any(type(value) is int and value == 1
               for name, value in zip(names, row) if name not in numeric):
            raise ReadStoreError("account identity scalar exceeds its byte bound")


def _decoded(encoded, *, maximum: int, label: str, expected):
    if not isinstance(encoded, str) or len(encoded.encode("utf-8")) > maximum:
        raise ReadStoreError(f"{label} exceeds its UTF-8 byte bound")
    try:
        value = json.loads(encoded)
    except (TypeError, ValueError) as exc:
        raise ReadStoreError(f"{label} is invalid") from exc
    if not isinstance(value, expected):
        raise ReadStoreError(f"{label} has the wrong shape")
    return value


def _identity_candidates(finding: dict) -> tuple[str, ...]:
    encoded = finding.get("candidates") or ()
    if not isinstance(encoded, (list, tuple)):
        raise ReadStoreError("identity candidates must be a list")
    candidates = tuple(encoded)
    if not candidates and finding.get("candidate"):
        candidates = (finding["candidate"],)
    if len(candidates) > MAX_IDENTITY_CANDIDATES_PER_FINDING:
        raise ReadStoreError("identity finding exceeds its nested candidate bound")
    if any(not isinstance(candidate, str) or not candidate or
           len(candidate.encode("utf-8")) > MAX_IDENTITY_KEY_BYTES
           for candidate in candidates):
        raise ReadStoreError("identity candidate exceeds its UTF-8 key bound")
    return candidates


def _identity_core(connection, as_of: str):
    """Fold the account resolver's exact source-order state from SQL rows."""
    account_columns = ("a.source_sequence,a.event_type,a.account_id,a.occurred_at,"
                       "a.kind,a.name,a.currency,a.jurisdiction,a.institution,"
                       "a.account_number,a.origin")
    selected, bounds = _bounded_text_columns(
        account_columns, ("a.source_sequence",))
    rows = _bounded(
        connection,
        f"SELECT {selected} FROM accounts a WHERE a.occurred_at<=? "
        "ORDER BY a.source_sequence LIMIT ?",
        (*bounds, as_of), MAX_ACCOUNT_HISTORY_ROWS, "account identity history")
    _refuse_oversized_text(rows, account_columns, ("a.source_sequence",))
    holder_columns = "n.source_sequence,n.name"
    selected, bounds = _bounded_text_columns(
        holder_columns, ("n.source_sequence",))
    name_rows = _bounded(
        connection,
        f"SELECT {selected} FROM account_names n JOIN accounts a "
        "ON a.source_sequence=n.source_sequence WHERE a.occurred_at<=? "
        "ORDER BY n.source_sequence,n.name_index LIMIT ?", (*bounds, as_of),
        MAX_ACCOUNT_NAME_ROWS, "account holder-name history")
    _refuse_oversized_text(name_rows, holder_columns, ("n.source_sequence",))
    names_by_sequence = {}
    for sequence, holder in name_rows:
        names_by_sequence.setdefault(sequence, []).append(holder)
    core = SimpleNamespace(_acct={}, _aliases={}, _alias_evidence={},
                           _document_account_aliases={})
    for sequence, event_type, account_id, occurred_at, kind, name, currency, jurisdiction, institution, number, origin in rows:
        state = core._acct.setdefault(account_id, SimpleNamespace(
            seen=False, kind="", currency="", name="", institution="",
            number="", names=[], origin="issued", jurisdiction="", opened_at=""))
        names = names_by_sequence.get(sequence, [])
        if event_type == "AccountOpened":
            state.seen = True; state.kind = kind or ""; state.currency = currency or ""
            state.name = name or ""; state.institution = institution or ""
            state.number = number or ""; state.names = names
            state.origin = origin or "issued"; state.jurisdiction = jurisdiction or ""
            state.opened_at = state.opened_at or occurred_at
        else:
            from ..ledger.identity import usable_full_number
            if usable_full_number(number or "") and not usable_full_number(state.number):
                state.number = number or ""
            state.institution = state.institution or institution or ""
            for holder in names:
                if holder and holder not in state.names:
                    state.names.append(holder)
    alias_columns = ("alias_key,account_id,doc_id,learn_signal,"
                     "match_label,account_kind,evidence_scoped")
    selected, bounds = _bounded_text_columns(
        alias_columns, ("learn_signal", "evidence_scoped"))
    selected = selected.split(",")
    selected.insert(4, "CASE WHEN length(CAST(match_names_json AS BLOB))<=? "
                    "THEN match_names_json END")
    aliases = _bounded(
        connection,
        f"SELECT {','.join(selected)} FROM account_alias_history WHERE occurred_at<=? "
        "ORDER BY source_sequence LIMIT ?",
        (*bounds[:3], MAX_ENCODED_IDENTITY_BYTES, *bounds[3:], as_of),
        MAX_ALIAS_HISTORY_ROWS,
        "account alias history")
    _refuse_oversized_text(
        [row[:4] + row[5:] for row in aliases], alias_columns,
        ("learn_signal", "evidence_scoped"))
    for key, account, doc_id, learn, encoded_names, label, kind, scoped in aliases:
        if learn:
            core._aliases[key] = account
            if scoped:
                core._alias_evidence[key] = {
                    "names": _decoded(encoded_names,
                        maximum=MAX_ENCODED_IDENTITY_BYTES,
                        label="account alias identity payload", expected=list),
                    "label": label, "kind": kind}
            else:
                core._alias_evidence.pop(key, None)
        if doc_id:
            core._document_account_aliases[doc_id] = account
    return core


def _running_balance(connection, account: str, as_of: str) -> Decimal | None:
    seen = connection.execute(
        "SELECT 1 FROM account_entities e WHERE e.account_id=? AND (EXISTS(SELECT 1 FROM accounts a WHERE a.account_id=e.account_id AND a.occurred_at<=?) OR EXISTS(SELECT 1 FROM balance_observations b WHERE b.account_id=e.account_id AND b.occurred_at<=?))",
        (account, as_of, as_of)).fetchone()
    if not seen:
        return None
    openings = _bounded(connection,
        "SELECT amount_text FROM balance_observations "
        "WHERE account_id=? AND event_type='OpeningBalanceObserved' AND occurred_at<=? "
        "ORDER BY occurred_at,source_sequence LIMIT ?",
        (account, as_of), MAX_OBSERVATION_HISTORY_ROWS,
        f"account {account!r} opening-observation history")
    opening = openings[0] if openings else None
    postings = _bounded(connection,
        "SELECT p.amount_text FROM postings p JOIN transactions t USING(source_sequence) WHERE p.account_id=? AND t.occurred_at<=? ORDER BY p.source_sequence,p.posting_index LIMIT ?",
        (account, as_of), MAX_VALUE_ROWS_PER_ACCOUNT, f"account {account!r} posting history")
    return (Decimal(opening[0]) if opening else Decimal(0)) + sum(
        (Decimal(row[0]) for row in postings), Decimal(0))


def _account_value(connection, core, account: str, as_of: str) -> Decimal:
    state = core._acct.get(account)
    if state is None or not state.seen:
        raise UnknownAccountError(account)
    closings = _bounded(connection,
        "SELECT amount_text FROM balance_observations "
        "WHERE account_id=? AND event_type='ClosingBalanceObserved' AND occurred_at<=? "
        "ORDER BY occurred_at DESC,source_sequence DESC LIMIT ?",
        (account, as_of), MAX_OBSERVATION_HISTORY_ROWS,
        f"account {account!r} closing-observation history")
    closing = closings[0] if closings else None
    cash = Decimal(closing[0]) if closing else (_running_balance(connection, account, as_of) or Decimal(0))
    rows = _bounded(connection,
        "SELECT occurred_at,instrument_id,value_text,currency FROM positions WHERE account_id=? AND occurred_at<=? ORDER BY occurred_at DESC,source_sequence DESC LIMIT ?",
        (account, as_of), MAX_VALUE_ROWS_PER_ACCOUNT, f"account {account!r} position history")
    noncash_dates = [row[0] for row in rows if row[1].strip().lower() not in ("cash", "cash & equivalents", "cash and equivalents", "sweep")]
    cash_dates = [row[0] for row in rows if row[1].strip().lower() in ("cash", "cash & equivalents", "cash and equivalents", "sweep")]
    for dates, want_cash in ((cash_dates, True), (noncash_dates, False)):
        if not dates: continue
        newest = max(dates)
        cash += sum((Decimal(value) for occurred, instrument, value, currency in rows
                     if occurred == newest
                     and (instrument.strip().lower() in ("cash", "cash & equivalents", "cash and equivalents", "sweep")) == want_cash
                     and (currency or state.currency) == state.currency), Decimal(0))
    return cash


def _account_values(connection, core, accounts: tuple[str, ...], as_of: str):
    """Load values for a bounded candidate set with a fixed query count."""
    unique = tuple(dict.fromkeys(accounts))
    if len(unique) > MAX_IDENTITY_CANDIDATES_TOTAL:
        raise ReadStoreError("identity candidates exceed their total candidate bound")
    if not unique:
        return {}
    placeholders = ",".join("?" for _ in unique)
    closings = _bounded(connection,
        "SELECT account_id,amount_text FROM balance_observations "
        "WHERE event_type='ClosingBalanceObserved' AND occurred_at<=? "
        f"AND account_id IN ({placeholders}) "
        "ORDER BY account_id,occurred_at DESC,source_sequence DESC LIMIT ?",
        (as_of, *unique), MAX_OBSERVATION_HISTORY_ROWS,
        "identity closing-observation history")
    openings = _bounded(connection,
        "SELECT account_id,amount_text FROM balance_observations "
        "WHERE event_type='OpeningBalanceObserved' AND occurred_at<=? "
        f"AND account_id IN ({placeholders}) "
        "ORDER BY account_id,occurred_at,source_sequence LIMIT ?",
        (as_of, *unique), MAX_OBSERVATION_HISTORY_ROWS,
        "identity opening-observation history")
    postings = connection.execute(
        "SELECT p.account_id,p.amount_text "
        "FROM postings p JOIN transactions t USING(source_sequence) "
        f"WHERE t.occurred_at<=? AND p.account_id IN ({placeholders}) "
        "ORDER BY p.account_id,p.source_sequence,p.posting_index LIMIT ?",
        (as_of, *unique, MAX_VALUE_ROWS_PER_ACCOUNT + 1)).fetchall()
    if len(postings) > MAX_VALUE_ROWS_PER_ACCOUNT:
        raise ReadStoreError("identity posting input exceeds its row bound")
    positions = connection.execute(
        "SELECT account_id,occurred_at,instrument_id,value_text,currency FROM positions "
        f"WHERE occurred_at<=? AND account_id IN ({placeholders}) "
        "ORDER BY account_id,occurred_at DESC,source_sequence DESC LIMIT ?",
        (as_of, *unique, MAX_VALUE_ROWS_PER_ACCOUNT + 1)).fetchall()
    if len(positions) > MAX_VALUE_ROWS_PER_ACCOUNT:
        raise ReadStoreError("identity position input exceeds its row bound")
    close_map = {}
    for account, amount in closings:
        close_map.setdefault(account, Decimal(amount))
    running = {}
    for account, amount in openings:
        running.setdefault(account, Decimal(amount))
    for account, amount in postings:
        running[account] = running.get(account, Decimal(0)) + Decimal(str(amount))
    by_account = {}
    for account, occurred, instrument, value, currency in positions:
        by_account.setdefault(account, []).append((occurred, instrument, value, currency))
    values = {}
    for account in unique:
        state = core._acct.get(account)
        if state is None or not state.seen:
            continue
        cash = close_map.get(account, running.get(account, Decimal(0)))
        rows = by_account.get(account, ())
        for want_cash in (True, False):
            selected = [row for row in rows if
                (row[1].strip().lower() in ("cash", "cash & equivalents", "cash and equivalents", "sweep")) == want_cash]
            if not selected:
                continue
            newest = max(row[0] for row in selected)
            cash += sum((Decimal(value) for occurred, _instrument, value, currency in selected
                         if occurred == newest and (currency or state.currency) == state.currency),
                        Decimal(0))
        values[account] = cash
    return values


def _open_hold_rows(connection, as_of: str):
    from .scalar_bounds import selected as scalar_selected, refuse as refuse_scalars
    columns = ("h.source_sequence", "h.event_type", "h.doc_id",
               "h.occurred_at", "h.reason")
    selected, bounds = scalar_selected(columns, ("h.source_sequence",))
    rows = _bounded(connection,
        f"SELECT {selected},"
        "CASE WHEN length(CAST(h.facts_json AS BLOB))<=? THEN h.facts_json ELSE 1 END,"
        "CASE WHEN h.finding_json IS NULL THEN NULL "
        "WHEN length(CAST(h.finding_json AS BLOB))<=? THEN h.finding_json ELSE 1 END "
        "FROM document_holds h WHERE h.occurred_at<=? ORDER BY h.source_sequence LIMIT ?",
        (*bounds, MAX_ENCODED_HOLD_BYTES, MAX_ENCODED_HOLD_BYTES, as_of),
        MAX_HELD_ROWS, "document hold history")
    refuse_scalars([row[:5] for row in rows], columns, ("h.source_sequence",),
                   label="document hold labels")
    selected, bounds = scalar_selected(("doc_id",))
    posted = {row[0] for row in _bounded(connection,
        f"SELECT {selected} FROM posted_document_events "
        "WHERE occurred_at<=? GROUP BY doc_id ORDER BY doc_id LIMIT ?",
        (*bounds, as_of), MAX_HELD_ROWS, "posted-document identity")}
    selected, bounds = scalar_selected(("doc_id",))
    resolved = {row[0]: row[1] for row in _bounded(connection,
        f"SELECT {selected},MAX(source_sequence) FROM document_hold_resolutions "
        "WHERE occurred_at<=? GROUP BY doc_id ORDER BY doc_id LIMIT ?",
        (*bounds, as_of), MAX_HELD_ROWS, "brokerage hold resolution history")}
    if any(type(doc_id) is int and doc_id == 1
           for doc_id in (*posted, *resolved)):
        raise ReadStoreError("document hold identity exceeds its scalar byte bound")
    regular, activity = {}, {}
    for sequence, event_type, doc_id, occurred_at, reason, facts, finding in rows:
        target = activity if event_type == "BrokerageActivityHeld" or reason == "activity" else regular
        target[doc_id] = (sequence, event_type, doc_id, occurred_at, reason,
                          _decoded(facts, maximum=MAX_ENCODED_HOLD_BYTES,
                                   label="held facts payload", expected=dict),
                          None if finding is None else _decoded(
                              finding, maximum=MAX_ENCODED_HOLD_BYTES,
                              label="held finding payload", expected=dict))
    regular = [row for doc, row in regular.items() if doc not in posted]
    activity = [row for doc, row in activity.items() if row[0] > resolved.get(doc, -1)]
    return regular, activity


def held_items(connection, *, as_of: str):
    """Return canonical balance-family holds from one SQL revision."""
    core = _identity_core(connection, as_of)
    regular, _activity = _open_hold_rows(connection, as_of)
    out = []
    for sequence, _event_type, doc_id, occurred_at, reason, body, finding in regular:
        identity = identity_of_facts(body)
        if identity == BALANCE_IDENTITY:
            facts = StatementFacts.from_dict(body)
            closing, opening, opening_date = facts.closing_amount, facts.opening_amount, facts.opening_date
            closing_date, transactions = facts.closing_date, [txn.to_dict() for txn in facts.transactions]
        elif identity == BROKERAGE_IDENTITY and reason == "identity":
            facts = BrokerageFacts.from_dict(body)
            closing, opening, opening_date = facts.total, None, ""
            closing_date, transactions = facts.as_of, []
        else:
            continue
        resolution = resolve(core, facts.institution, facts.account_number,
                             facts.account_ref, facts.account_names,
                             kind=account_kind_for(facts.doc_type), doc_id=facts.doc_id)
        held_balance = (_running_balance(connection, resolution.account_id, as_of)
                        if identity == BALANCE_IDENTITY and resolution.verdict == "same" else None)
        out.append({"source_sequence": sequence, "doc_id": doc_id, "reason": reason,
            "account_ref": facts.account_ref,
            "account_label": masked_label(facts.account_ref).replace("••••", "····"),
            "currency": facts.currency, "opening_amount": "" if opening is None else str(opening),
            "opening_date": opening_date, "closing_amount": str(closing),
            "closing_date": closing_date,
            "period": closing_date if identity == BROKERAGE_IDENTITY else f"{opening_date} – {closing_date}",
            "held_balance": None if held_balance is None else str(held_balance),
            "transactions": transactions, "finding": finding, "facts": facts,
            "resolution": resolution, "occurred_at": occurred_at})
    return out


def _adjacent(earlier: str, later: str) -> bool:
    try: gap = (datetime.date.fromisoformat(later) - datetime.date.fromisoformat(earlier)).days
    except (TypeError, ValueError): return False
    return 0 <= gap <= 1


def question_candidates(connection, *, as_of: str, locale: str = ""):
    """Return canonical held/reconciliation question dictionaries."""
    core = _identity_core(connection, as_of)
    held = held_items(connection, as_of=as_of)
    regular, activity = _open_hold_rows(connection, as_of)
    out, bridges = [], []
    candidates_by_doc = {}
    all_candidates = []
    for item in held:
        if item["reason"] != "identity":
            continue
        candidates = _identity_candidates(item["finding"] or {})
        candidates_by_doc[item["doc_id"]] = candidates
        all_candidates.extend(candidates)
        if len(all_candidates) > MAX_IDENTITY_CANDIDATES_TOTAL:
            raise ReadStoreError("identity candidates exceed their total candidate bound")
    account_values = _account_values(connection, core, tuple(all_candidates), as_of)
    for item in held:
        facts, finding = item["facts"], item["finding"] or {}
        if item["reason"] == "identity" and isinstance(facts, StatementFacts):
            candidates = candidates_by_doc.get(item["doc_id"], ())
            candidate = candidates[0] if len(candidates) == 1 else ""
            balance = _running_balance(connection, candidate, as_of) if candidate else None
            if candidate and balance is not None and facts.opening_amount == balance:
                bridges.append((candidate, facts))
    for item in held:
        facts, finding, reason = item["facts"], item["finding"] or {}, item["reason"]
        amount = abs(getattr(facts, "closing_amount", getattr(facts, "total", 0)))
        slots, refs = (), {"doc_id": item["doc_id"]}
        if reason == "gap":
            account = item["resolution"].account_id
            if any(candidate == account and bridge.closing_amount == facts.opening_amount
                   and _adjacent(bridge.closing_date, facts.opening_date)
                   for candidate, bridge in bridges): continue
            text = say("reconciliation_gap", account_ref=render.account({"name": facts.account_ref}),
                       opening_date=render.date(facts.opening_date), closing_date=render.date(facts.closing_date))
            why = say("reconciliation_gap_why", opening_money=render.money(abs(facts.opening_amount), facts.currency, locale=locale))
        elif reason == "reissue":
            text = say("reconciliation_reissue", account_ref=render.account({"name": facts.account_ref})); why = finding.get("message", "")
        elif reason == "identity":
            why = finding.get("message", ""); candidates = candidates_by_doc.get(item["doc_id"], ())
            if len(candidates) == 1:
                text = say("identity", account_ref=render.account({"name": facts.account_ref})); slots = IDENTITY_SLOTS
            elif len(candidates) > 1:
                infos, entities = [], []
                for account in candidates:
                    try: info = account_info(core, account)
                    except UnknownAccountError: continue
                    infos.append(info); entities.append({"name": info.name or info.institution,
                        "account": info.account, "number_masked": masked(info.number)})
                labels = [str(render.account(entity, among=entities)) for entity in entities]
                choices, targets = [], {}
                for index, (info, label) in enumerate(zip(infos, labels), 1):
                    detail = label
                    if labels.count(label) > 1:
                        detail = f"{label} — balance {render.money(account_values[info.account], info.currency, locale=locale)}"
                    choice = f"{detail} (option {index})"; choices.append(choice); targets[choice] = info.account
                choices.append("a new account"); targets["a new account"] = "new"
                text = say("identity_choice", account_ref=render.account({"name": facts.account_ref}))
                slots = (Slot(name="account_choice", type=ANSWER_CHOICE, choices=tuple(choices), required=True),)
                refs["identity_choices"] = targets
            else:
                text = say("identity_new", account_ref=render.account({"name": facts.account_ref}))
                slots = (Slot(name="account_choice", type=ANSWER_CHOICE, choices=("a new account",), required=True),)
                refs["identity_choices"] = {"a new account": "new"}
        else:
            text = say("reconciliation_flagged", account_ref=render.account({"name": facts.account_ref})); why = finding.get("message", "")
        kind = "identity" if reason == "identity" else "reconciliation"
        out.append({"id": f"{kind}:{item['doc_id'][:12]}", "kind": kind,
            "text": text, "why": why, "amount": str(amount), "currency": facts.currency,
            "count": 1, "scope": "one", "slots": [slot.to_dict() for slot in slots], "refs": refs})
    held_ids = {item["doc_id"] for item in held}
    others = [row for row in regular if row[2] not in held_ids] + activity
    for _sequence, _event_type, doc_id, _occurred, reason, facts, finding in others:
        finding = finding or {}; account_ref = masked_label(facts.get("account_ref", "") or facts.get("employer", "")).replace("••••", "····")
        doc_type = render.document(facts.get("doc_type", "unknown").replace("_", " "))
        text = (say("reconciliation_held_for", doc_type=doc_type, account_ref=render.account({"name": account_ref}))
                if account_ref else say("reconciliation_held", doc_type=doc_type))
        out.append({"id": f"reconciliation:{doc_id[:12]}", "kind": "reconciliation",
            "text": text, "why": finding.get("message", "") or f"held: {reason}",
            "amount": "0", "currency": "", "count": 1, "scope": "one",
            "slots": [], "refs": {"doc_id": doc_id}})
    if len(out) > MAX_HELD_ROWS:
        raise ReadStoreError("held questions exceed their candidate bound")
    return out
