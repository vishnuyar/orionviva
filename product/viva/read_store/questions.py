"""Actionable movement questions composed from normalized revision rows."""
from __future__ import annotations

import json
from datetime import date, timedelta
from decimal import Decimal

from merchantcore import is_shareable
from merchantcore.descriptor import linted_example

from .. import render
from ..ledger.events import MAJORS, PERIODICITIES
from ..ledger.streams import IN, money_effect
from ..persona import say
from ..reply import Slot
from ..schemas import (ANSWER_CHOICE, ANSWER_LABEL, ANSWER_LINK, ANSWER_RATE,
                       ANSWER_YES_NO)
from .rhythm import (_merchant_records, _rank, _rhythms, MAX_OBLIGATION_RHYTHMS,
                     MAX_RHYTHM_POSTING_ROWS, RhythmReadError)


# A held account may contribute several possible schema ids while only one is
# live.  Keep enough headroom for more than 200 simultaneous interviews before
# the final queue's independent 200-row display cap is applied.
MAX_QUESTION_CANDIDATES = 4_000
MAX_TRANSFER_LINK_ROWS = 10_000
MAX_TRANSFER_CANDIDATE_BYTES = 1_000_000
MAX_TRANSFER_CANDIDATES_PER_SUGGESTION = 200
MAX_TRANSFER_CANDIDATE_KEY_BYTES = 512
REVIEW_DECISION_BATCH = 200
MAX_REVIEW_DECISION_BYTES = 1_000_000
MAX_RULING_HISTORY_ROWS = 10_000
MAX_RULING_LEGS_BYTES = 1_000_000
MAX_ACCOUNT_HISTORY_ROWS = 10_000
MAX_DOCUMENT_ROWS = 10_000
MAX_ATTRIBUTE_HISTORY_ROWS = 10_000
MAX_INTERVIEW_ACCOUNT_ROWS = 10_000
MAX_INTERVIEW_DOCUMENT_ROWS = 10_000
MAX_INTERVIEW_QUESTION_KEY_BYTES = 512
DOCUMENT_SLOTS = (Slot(name="have_it", type=ANSWER_YES_NO, required=True),)
_PLAIN = {"expense": "Spent — the money is gone",
          "asset": "I still have it, in another form",
          "liability": "It changed what I owe",
          "income": "Money that came to me"}
_PERIOD_MEANINGS = {
    "monthly": "an arrangement that comes round about every month",
    "annual": "an arrangement that comes round about once a year",
    "one_time": "a one-off — it happened once, and repeats no further",
    "irregular": "nothing arranged with them; the money moves as and when"}


def _ruling_slots(categories):
    return (Slot("legs", required=True, parts=(
                Slot("major", ANSWER_CHOICE, choices=MAJORS,
                     meanings=tuple(_PLAIN.items()), required=True),
                Slot("account_hint", ANSWER_LABEL), Slot("share", ANSWER_RATE))),
            Slot("kind", ANSWER_LABEL),
            Slot("category", ANSWER_LABEL, choices=tuple(categories),
                 offered=tuple(x for x in categories if is_shareable(x))))


def _question(identity, kind, text, why, amount, currency="", count=1,
              scope="one", slots=(), refs=None):
    return {"id": identity, "kind": kind, "text": text, "why": why,
            "amount": str(amount), "currency": currency, "count": count,
            "scope": scope, "slots": [slot.to_dict() for slot in slots],
            "refs": refs or {}}


def _rows(connection):
    from .scalar_bounds import selected as scalar_selected, refuse as refuse_scalars
    names = ("movement_key", "account_id", "account_kind", "occurred_at",
             "amount_text", "currency", "description", "linked", "nature",
             "nature_reason", "merchant_key", "category", "subcategory",
             "category_by", "ruling_account")
    selected, bounds = scalar_selected(names, ("linked",))
    rows = connection.execute(
        f"SELECT {selected} FROM movements "
        "ORDER BY occurred_at,movement_key LIMIT ?",
        (*bounds, MAX_RHYTHM_POSTING_ROWS + 1,)).fetchall()
    if len(rows) > MAX_RHYTHM_POSTING_ROWS:
        raise RhythmReadError(
            f"question movement input exceeds its {MAX_RHYTHM_POSTING_ROWS}-row read bound")
    refuse_scalars(rows, names, ("linked",), label="question movement input")
    return [dict(zip(names, row)) | {"amount": Decimal(row[4])} for row in rows]


def candidates(connection, *, as_of: str, locale: str = "",
               held_as_of: str | None = None):
    # Canonical queue semantics are intentionally mixed: transfer, merchant,
    # and nature questions inspect the complete current projection, while
    # cadence inference alone is grounded at ``as_of``.
    rows = _rows(connection)
    by_key = {row["movement_key"]: row for row in rows}
    records, _owners, _conflicts = _merchant_records(connection, "9999-12-31")
    used = sorted({(record.get("category") or "").strip()
                   for record in records.values()} - {""})
    from merchantcore import FALLBACK_CATEGORY, PRIMARY_CATEGORIES
    categories, seen = [], set()
    for name in (*PRIMARY_CATEGORIES, FALLBACK_CATEGORY, *used):
        normalized = " ".join(name.lower().replace("-", " ").split())
        if normalized and normalized not in seen:
            seen.add(normalized); categories.append(name)
    from .held import question_candidates
    out = question_candidates(connection, as_of=held_as_of or as_of,
                              locale=locale)
    link_rows = connection.execute(
        "SELECT movement_a,movement_b FROM transfer_links "
        "ORDER BY movement_a,movement_b LIMIT ?",
        (MAX_TRANSFER_LINK_ROWS + 1,)).fetchall()
    if len(link_rows) > MAX_TRANSFER_LINK_ROWS:
        raise RhythmReadError(
            f"transfer links exceed their {MAX_TRANSFER_LINK_ROWS}-row read bound")
    linked = {key for row in link_rows for key in row}
    suggestions = connection.execute(
        "SELECT movement_a,CASE WHEN length(CAST(candidates_json AS BLOB))<=? "
        "THEN candidates_json END FROM transfer_suggestions "
        "ORDER BY movement_a LIMIT ?",
        (MAX_TRANSFER_CANDIDATE_BYTES, MAX_QUESTION_CANDIDATES + 1)).fetchall()
    if len(suggestions) > MAX_QUESTION_CANDIDATES:
        raise RhythmReadError("transfer questions exceed their candidate bound")
    for source_key, encoded in suggestions:
        if not isinstance(encoded, str) or len(encoded.encode("utf-8")) > MAX_TRANSFER_CANDIDATE_BYTES:
            raise RhythmReadError("transfer candidate payload exceeds its byte bound")
        try:
            from .transfer_payload import decode as decode_transfer
            decoded = decode_transfer(
                encoded, list, maximum_bytes=MAX_TRANSFER_CANDIDATE_BYTES)
        except (TypeError, ValueError) as exc:
            raise RhythmReadError("transfer candidate payload is invalid") from exc
        if not isinstance(decoded, list):
            raise RhythmReadError("transfer candidate payload must be a list")
        if len(decoded) > MAX_TRANSFER_CANDIDATES_PER_SUGGESTION:
            raise RhythmReadError("transfer candidate payload exceeds its nested candidate bound")
        if any(not isinstance(key, str) or not key
               or len(key.encode("utf-8")) > MAX_TRANSFER_CANDIDATE_KEY_BYTES
               for key in decoded):
            raise RhythmReadError("transfer candidate key exceeds its field bound")
        possible = [key for key in decoded if key not in linked]
        source = by_key.get(source_key)
        if source is None or not possible: continue
        amount = abs(source["amount"])
        out.append(_question(f"transfer:{source_key}", "transfer",
            say("transfer", date=render.date(source["occurred_at"]),
                money=render.money(amount, source["currency"], locale=locale),
                description=render.merchant({"example": source["description"]})),
            say("transfer_why", candidates=render.count(len(possible))), amount,
            source["currency"], slots=(Slot("same_money", ANSWER_YES_NO, required=True),),
            refs={"movement": source_key, "candidates": possible}))
    expenses = [row for row in rows if ((row["account_kind"] == "depository" and row["amount"] < 0)
                or (row["account_kind"] == "liability" and row["amount"] > 0))]
    uncategorized = [row for row in expenses if row["nature"] == "spending" and
                     (not row["category"] or row["category_by"] == "default")]
    groups = {}
    for row in uncategorized:
        key = row["merchant_key"]
        if not key: continue
        group = groups.setdefault(key, {"amount": Decimal(0), "rows": [],
            "currency": row["currency"], "example": linted_example(row["description"]),
            "shareable": is_shareable(row["description"])})
        group["amount"] += abs(row["amount"]); group["rows"].append(row)
    for key, group in groups.items():
        count = len(group["rows"]); shareable = group["shareable"]
        text = say("merchant", example=render.merchant({"example": group["example"]}),
                   count=render.count(count), money=render.money(
                       group["amount"], group["currency"], locale=locale))
        if not shareable: text += " " + say("merchant_peer_note")
        out.append(_question(f"merchant:{key}", "merchant", text,
            say("merchant_why"), group["amount"], group["currency"], count,
            "pattern" if shareable else "one",
            (Slot("category", ANSWER_CHOICE, choices=tuple(categories),
                  offered=tuple(x for x in categories if is_shareable(x)), required=True),),
            {"merchant": key, "example": group["example"], "categories": tuple(categories),
             "movements": [] if shareable else [row["movement_key"] for row in group["rows"]]}))
    singles, structural = [], {}
    for row in expenses:
        if row["nature_reason"] not in ("category_hint", "default"): continue
        record = records.get(row["merchant_key"]) or {}
        attrs = record.get("attributes") or {}
        kind = attrs.get("counterparty_kind", "")
        unknown = kind in ("instrument", "peer") or not is_shareable(row["description"])
        unenriched = not row["category"] or row["category_by"] == "default"
        implications = attrs.get("implies") or []
        direction = "inflow" if money_effect(row["account_kind"], row["amount"]) > 0 else "outflow"
        implied = next((x for x in implications if x.get("on") in (direction, "both")), None)
        if unknown: singles.append(row)
        elif unenriched or not implied: continue
        else:
            group = structural.setdefault(row["merchant_key"], {"rows": [], "implied": implied})
            group["rows"].append(row)
    for row in singles:
        amount = abs(row["amount"])
        out.append(_question(f"nature:{row['movement_key']}", "nature",
            say("nature_single", date=render.date(row["occurred_at"]),
                description=render.merchant({"example": row["description"]}),
                money=render.money(amount, row["currency"], locale=locale)),
            say("nature_single_why"), amount, row["currency"], slots=_ruling_slots(categories),
            refs={"movement": row["movement_key"], "movements": [row["movement_key"]],
                  "descriptor": row["description"], "category": row["category"],
                  "subcategory": row["subcategory"]}))
    for key, group in structural.items():
        members, implied = group["rows"], group["implied"]
        amount = sum((abs(row["amount"]) for row in members), Decimal(0)); first = members[0]
        what = first["subcategory"] if first["subcategory"] != "unclassified" else first["category"]
        text = say("nature_group_head", count=render.count(len(members)),
                   example=render.merchant({"example": first["description"]}),
                   money=render.money(amount, first["currency"], locale=locale))
        if what: text += " " + say("nature_group_meaning", what=render.category(what))
        if implied.get("compound"): text += " " + say("nature_group_compound")
        text += " " + say("nature_group_ask")
        why = say("nature_group_why")
        if implied.get("documents"): why += " " + say("nature_group_why_documents", documents=render.document(implied["documents"]))
        out.append(_question(f"nature:{key}", "nature", text, why, amount,
            first["currency"], len(members), "pattern", _ruling_slots(categories),
            {"merchant": key, "movements": [r["movement_key"] for r in members],
             "descriptor": first["description"], "category": first["category"],
             "subcategory": first["subcategory"], "implied_major": implied.get("major", ""),
             "account_group": implied.get("account_group", ""),
             "documents": implied.get("documents", "")}))
    rhythms, _movement_map = _rhythms(connection, as_of=as_of,
        limit=MAX_OBLIGATION_RHYTHMS, result_label="question rhythm candidates")
    rhythm_slots = (Slot("periods", required=True, parts=(Slot(
        "period", ANSWER_CHOICE, choices=PERIODICITIES,
        meanings=tuple(_PERIOD_MEANINGS.items()), required=True),)),)
    for h in rhythms:
        if h["confirmed"]: continue
        text = say("rhythm_head", count=render.count(h["count"]),
                   example=render.merchant({"example": h["example"]}),
                   money=render.money(h["amount"], h["currency"], locale=locale))
        text += " " + say("rhythm_direction_in" if h["direction"] == IN else "rhythm_direction_out")
        if len(h["components"]) > 1:
            text += " " + say("rhythm_mixture_lead")
            for part in h["components"]:
                key = {"fixed": "rhythm_mixture_part_repeating", "variable": "rhythm_mixture_part_varying", "unknown": "rhythm_mixture_part_lone"}[part["amount_stability"]]
                text += " " + say(key, count=render.count(part["count"]), money=render.money(part["amount"], h["currency"], locale=locale))
            text += " " + say("rhythm_mixture_ask"); why = say("rhythm_why_mixture")
        elif h["measured"] and h["steady"]:
            text += " " + say("rhythm_measured", days=render.count(h["interval_days"]))
            if h["amount_stability"] == "fixed": text += " " + say("rhythm_measured_fixed")
            text += " " + say("rhythm_ask"); why = say("rhythm_why_measured")
        elif h["measured"]:
            text += " " + say("rhythm_irregular")
            if h["amount_stability"] == "fixed": text += " " + say("rhythm_measured_fixed")
            text += " " + say("rhythm_irregular_ask"); why = say("rhythm_why_irregular")
        else:
            text += " " + say("rhythm_prior_standing" if h["billing"] == "standing" else "rhythm_prior_either")
            if h["billing_period"] in ("monthly", "annual"):
                text += " " + say("rhythm_prior_period_" + h["billing_period"])
            text += " " + say("rhythm_ask"); why = say("rhythm_why_prior")
        refs = {"merchant": h["merchant"], "direction": h["direction"],
                "movements": list(h["movements"]), "descriptor": h["example"],
                "billing": h["billing"], "billing_period": h["billing_period"],
                "measured": h["measured"], "steady": h["steady"],
                "cadence": h["cadence"] if h["measured"] else "",
                "proposed": list(h["proposed"]), "components": [{
                    "count": p["count"], "amount": str(p["amount"]),
                    "amount_stability": p["amount_stability"], "measured": p["measured"],
                    "steady": p["steady"], "cadence": p["cadence"],
                    "movements": list(p["movements"])} for p in h["components"]]}
        out.append(_question(f"rhythm:{h['subject']}", "rhythm", text, why,
                             h["amount"], h["currency"], h["count"], "pattern",
                             rhythm_slots, refs))
    if len(out) > MAX_QUESTION_CANDIDATES:
        raise RhythmReadError("question result exceeds its candidate bound")
    return out


def _bounded(connection, sql, parameters, maximum, label):
    rows = connection.execute(sql, (*parameters, maximum + 1)).fetchall()
    if len(rows) > maximum:
        raise RhythmReadError(f"{label} exceeds its {maximum}-row read bound")
    return rows


def _current_accounts(connection):
    rows = _bounded(connection,
        "SELECT source_sequence,event_type,account_id,kind,name,currency,origin,"
        "jurisdiction FROM accounts INDEXED BY accounts_by_source_date "
        "ORDER BY source_sequence LIMIT ?", (),
        MAX_ACCOUNT_HISTORY_ROWS, "question account history")
    accounts = {}
    for _sequence, event_type, account, kind, name, currency, origin, jurisdiction in rows:
        if event_type == "AccountOpened":
            accounts[account] = {"account": account, "kind": kind or "",
                "name": name or "", "currency": currency or "",
                "origin": origin or "issued", "jurisdiction": jurisdiction or ""}
    return accounts


def _corroborating_documents(histories):
    """Map each ruled account to its first canonical corroborating document.

    Rulings reduce in source order (verified remains sticky), while the winning
    rulings retain the canonical key precedence used by the event projection.
    Building the account lookup once keeps question composition linear in the
    ruling history, winning legs, and movement stakes.
    """
    current = {}
    for _seq, scope, subject, legs_json, grade, corroborates in histories:
        prior = current.get((scope, subject))
        if prior is None or grade == "verified" or prior[1] != "verified":
            current[(scope, subject)] = (legs_json, grade, corroborates)
    documents = {}
    for key in sorted(current):
        legs_json, _grade, corroborates = current[key]
        if not corroborates:
            continue
        if not isinstance(legs_json, str):
            raise RhythmReadError("corroboration ruling legs exceed their byte bound")
        try:
            legs = json.loads(legs_json)
        except (TypeError, ValueError, RecursionError) as exc:
            raise RhythmReadError("corroboration ruling legs are invalid") from exc
        if not isinstance(legs, list):
            raise RhythmReadError("corroboration ruling legs have the wrong shape")
        for leg in legs:
            if not isinstance(leg, dict):
                raise RhythmReadError("corroboration ruling legs have the wrong shape")
            account = leg.get("account")
            if account:
                documents.setdefault(account, corroborates)
    return documents


def _corroboration_questions(connection, *, locale=""):
    rows = _rows(connection)
    stakes = {}
    for row in rows:
        account = row["ruling_account"] if "ruling_account" in row else ""
        if not account:
            continue
        stake = stakes.setdefault(account, {"paid": Decimal("0"), "count": 0,
            "currency": row["currency"], "reliable_balance": True})
        if account.startswith("Assets:Loans:"):
            from ..ledger.streams import money_effect
            stake["paid"] += -money_effect(row["account_kind"], row["amount"])
        else:
            stake["paid"] += abs(row["amount"])
        stake["count"] += 1
        if row["nature"] == "mixed":
            stake["reliable_balance"] = False
    # Canonical rulings are a source-order overlay: verified is sticky; otherwise
    # the latest source event wins. Their final view is then sorted by key.
    histories = _bounded(connection,
        "SELECT source_sequence,scope,subject,"
        "CASE WHEN length(CAST(legs_json AS BLOB))<=? THEN legs_json END,"
        "grade,corroborates "
        "FROM ruling_history ORDER BY source_sequence LIMIT ?",
        (MAX_RULING_LEGS_BYTES,),
        MAX_RULING_HISTORY_ROWS, "corroboration ruling history")
    if any(row[3] is None for row in histories):
        raise RhythmReadError("corroboration ruling legs exceed their byte bound")
    documents = _corroborating_documents(histories)
    out = []
    for account, row in sorted(stakes.items()):
        document = documents.get(account, "")
        if not document:
            continue
        why = say("corroboration_why")
        if not row["reliable_balance"]:
            why += " " + say("corroboration_why_unreliable")
        out.append(_question(f"corroboration:{account}", "corroboration",
            say("corroboration", name=render.account({"path": account}),
                money=render.money(abs(row["paid"]), row["currency"], locale=locale),
                document=render.document(document)), why.strip(), row["paid"],
            row["currency"], row["count"], "one", DOCUMENT_SLOTS,
            {"account": account, "document": document}))
    return out


def _balance_inputs(connection):
    opening = {}
    closing = {}
    for account, amount, occurred, sequence, event_type in _bounded(connection,
        "SELECT account_id,amount_text,occurred_at,source_sequence,event_type "
        "FROM balance_observations INDEXED BY observations_by_source "
        "ORDER BY source_sequence LIMIT ?", (),
        MAX_ACCOUNT_HISTORY_ROWS, "expectation balance history"):
        if event_type == "OpeningBalanceObserved":
            prior = opening.get(account)
            if prior is None or occurred < prior[1]: opening[account] = (Decimal(amount), occurred)
        elif (account not in closing or
              (occurred, sequence) > (closing[account][1], closing[account][2])):
            closing[account] = (Decimal(amount), occurred, sequence)
    totals = {}
    for account, amount in _bounded(connection,
        "SELECT account_id,amount_text FROM postings ORDER BY source_sequence,posting_index LIMIT ?",
        (), MAX_RHYTHM_POSTING_ROWS, "expectation posting history"):
        totals[account] = totals.get(account, Decimal("0")) + Decimal(amount)
    ids = set(opening) | set(closing) | set(totals)
    return {account: {"amount": (closing[account][0] if account in closing else
                    opening.get(account, (Decimal("0"), ""))[0] + totals.get(account, Decimal("0"))),
                    "dated": (closing[account][1] if account in closing else
                              opening.get(account, (Decimal("0"), ""))[1])}
            for account in ids}


def _expectation_questions(connection, *, as_of, jurisdiction, locale=""):
    from ..knowledge import load
    try:
        today = date.fromisoformat(as_of)
    except ValueError:
        today = None
    accounts = _current_accounts(connection)
    balances = _balance_inputs(connection)
    documents = _bounded(connection,
        "SELECT doc_type FROM documents INDEXED BY documents_by_source "
        "ORDER BY source_sequence LIMIT ?", (),
        MAX_DOCUMENT_ROWS, "expectation document history")
    seen = {row[0] for row in documents}
    expectations = []
    for entry in load()["entries"]:
        allowed = entry.get("jurisdictions", ["*"])
        if "*" not in allowed and jurisdiction not in allowed:
            continue
        if any(kind in seen for kind in entry.get("expect_doc_types", [])):
            continue
        given = entry.get("given", "")
        if given == "retirement_flow":
            balance = balances.get("Assets:Retirement")
            if not balance or not abs(balance["amount"]): continue
            amount = abs(balance["amount"])
            currency = next((row["currency"] for row in accounts.values()
                             if row["currency"]), "USD")
            fields = {"money": render.money(amount, currency, locale=locale),
                      "document": render.document(entry["document"])}
            expectations.append((f"expectation:{entry['id']}", given,
                entry["document"], "Assets:Retirement", amount, currency, 1, fields))
        elif given == "investment_account":
            held = [row for row in accounts.values() if row["kind"] == "investment"]
            if not held: continue
            amount = sum((abs(balances.get(account, {"amount": Decimal("0")})["amount"])
                          for account in ("Income:CapitalGains", "Income:Dividends")), Decimal("0"))
            currency = held[0]["currency"] or "USD"
            names = render.accounts(sorted(({"name": row["name"], "path": row["account"]}
                                            for row in held),
                                           key=lambda row: row["name"] or row["path"]))
            fields = {"account_name": names,
                      "document": render.document(entry["document"]),
                      "money": render.money(amount, currency, locale=locale)}
            expectations.append((f"expectation:{entry['id']}", given,
                entry["document"], str(names), amount, currency, len(held), fields))
        elif given == "account_cadence":
            if today is None: continue
            horizon = int(entry.get("cadence_days", 45))
            for account, info in sorted(accounts.items()):
                if info["kind"] not in ("depository", "liability"): continue
                dated = balances.get(account, {}).get("dated", "")
                try: last = date.fromisoformat(dated)
                except ValueError: continue
                if today - last <= timedelta(days=horizon): continue
                fields = {"account_name": render.accounts([{"name": info["name"], "path": account}]),
                          "last_date": render.date(dated)}
                expectations.append((f"expectation:{entry['id']}:{account}", given,
                    entry["document"], account, Decimal("0"), info["currency"], 1, fields))
        else:
            raise ValueError(f"registry entry {entry.get('id')!r} names unknown mechanism {given!r}")
    out = []
    for identity, mechanism, document, subject, amount, currency, count, fields in expectations:
        why_fields = {"money": fields.get("money", "")} if mechanism == "investment_account" else {}
        out.append(_question(identity, "expectation",
            say(f"expectation_{mechanism}", **fields),
            say(f"expectation_{mechanism}_why", **why_fields), amount, currency,
            count, "pattern" if count > 1 else "one", DOCUMENT_SLOTS,
            {"document": document, "subject": subject,
             "registry_entry": identity.split(":", 1)[1].split(":", 1)[0]}))
    return out


def attribute_answers(connection, *, as_of: str, account: str = ""):
    """Latest canonical source answer among facts eligible at ``as_of``."""
    clauses, parameters = ["occurred_at<=?"], [as_of]
    if account:
        clauses.append("account_id=?"); parameters.append(account)
    where = " AND ".join(clauses)
    # Refuse from a cap+1 index probe before loading or reducing any history.
    # This preserves the read bound even when every row belongs to one key.
    probe = connection.execute(
        "SELECT 1 FROM attribute_history WHERE " + where + " LIMIT ?",
        (*parameters, MAX_ATTRIBUTE_HISTORY_ROWS + 1)).fetchall()
    if len(probe) > MAX_ATTRIBUTE_HISTORY_ROWS:
        raise RhythmReadError(
            f"attribute answer history exceeds its {MAX_ATTRIBUTE_HISTORY_ROWS}-row read bound")
    rows = connection.execute(
        "SELECT source_sequence,account_id,attribute_key,value_text,currency,grade,said,occurred_at "
        "FROM attribute_history WHERE " + where + " LIMIT ?",
        (*parameters, MAX_ATTRIBUTE_HISTORY_ROWS)).fetchall()
    current = {}
    for sequence, account_id, key, value, currency, grade, said, occurred_at in rows:
        prior = current.get((account_id, key))
        if prior is None or sequence > prior[0]:
            current[(account_id, key)] = (
                sequence, value, currency, grade, said, occurred_at)
    out = {}
    for (account_id, key), (_sequence, value, currency, grade, said, occurred_at) in sorted(current.items()):
        out.setdefault(account_id, {})[key] = {"value": value, "currency": currency,
            "grade": grade, "said": said, "at": occurred_at[:10], "source": "said"}
    return out


def _interview_accounts(connection):
    """Fold the account fields the schema pack is allowed to inspect."""
    rows = _bounded(connection,
        "SELECT source_sequence,event_type,account_id,kind,name,currency,origin,"
        "jurisdiction,institution FROM accounts INDEXED BY accounts_by_source_date "
        "ORDER BY source_sequence LIMIT ?", (), MAX_INTERVIEW_ACCOUNT_ROWS,
        "interview account history")
    accounts = {}
    for _sequence, event_type, account, kind, name, currency, origin, jurisdiction, institution in rows:
        state = accounts.setdefault(account, {"account": account, "seen": False,
            "kind": "", "name": "", "currency": "", "origin": "issued",
            "jurisdiction": "", "institution": ""})
        if event_type == "AccountOpened":
            state.update({"seen": True, "kind": kind or "", "name": name or "",
                "currency": currency or "", "origin": origin or "issued",
                "jurisdiction": jurisdiction or "",
                "institution": institution or ""})
        else:
            state["institution"] = state["institution"] or institution or ""
    return {account: state for account, state in accounts.items() if state["seen"]}


def _interview_document_types(connection):
    from ..ingest.registry import profile_for

    captured = _bounded(connection,
        "SELECT source_sequence,doc_id,doc_type FROM documents "
        "INDEXED BY documents_by_source ORDER BY source_sequence LIMIT ?", (),
        MAX_INTERVIEW_DOCUMENT_ROWS, "interview captured-document history")
    current = {}
    for _sequence, doc_id, doc_type in captured:
        # Captured labels are historical classifier output, so older events may
        # carry any alias accepted by the registry.  The canonical projection
        # resolves those aliases before schema selection; the SQL read must do
        # the same so an alias remains attached to its known document.
        profile = profile_for(doc_type)
        current[doc_id] = profile.doc_type if profile is not None else doc_type
    spoken = _bounded(connection,
        "SELECT account_id,doc_id FROM document_account_history "
        "ORDER BY source_sequence,account_index LIMIT ?", (),
        MAX_INTERVIEW_DOCUMENT_ROWS, "interview account-document history")
    out = {}
    for account, doc_id in spoken:
        doc_type = current.get(doc_id)
        if doc_type:
            out.setdefault(account, set()).add(doc_type)
    return out


def _interview_stakes(connection):
    """Return canonical ruled-account stakes plus movement-touch counts."""
    stakes, touching = {}, {}
    for row in _rows(connection):
        touching[row["account_id"]] = touching.get(row["account_id"], 0) + 1
        account = row["ruling_account"]
        if not account:
            continue
        stake = stakes.setdefault(account, {"paid": Decimal("0"), "count": 0,
                                            "currency": row["currency"]})
        stake["paid"] += (-money_effect(row["account_kind"], row["amount"])
                          if account.startswith("Assets:Loans:")
                          else abs(row["amount"]))
        stake["count"] += 1
    return stakes, touching


def _interview_possible_ids(connection, jurisdiction: str):
    from .. import schemas
    from ..interview import HELD_KINDS, question_id
    accounts = _interview_accounts(connection)
    document_types = _interview_document_types(connection)
    fallback = (jurisdiction or "").lower()
    identities = []
    for account in sorted(accounts):
        info = accounts[account]
        if info["kind"] not in HELD_KINDS:
            continue
        where = (info["jurisdiction"] or fallback).lower()
        kind = schemas.kind_of_account(account, where, ledger_kind=info["kind"],
                                       doc_types=document_types.get(account, ()))
        schema = schemas.schema_for(kind, where) if kind else None
        questions = schema.questions if schema else ()
        identities.extend(question_id(account, question.key)
                          for question in questions)
        # An affirmative answer can compose one additional, synthetic ask for
        # every schema question that opens a related account.  It belongs to
        # the candidate identity envelope even when it is not currently live:
        # answers and declines must not be able to move work outside the cap.
        identities.extend(question_id(account, f"opens:{question.opens}")
                          for question in questions if question.opens)
    if any(len(identity.encode("utf-8")) > MAX_INTERVIEW_QUESTION_KEY_BYTES
           for identity in identities):
        raise RhythmReadError("interview question identity exceeds its UTF-8 byte bound")
    return identities


def _bounded_candidate_identities(questions, interview_ids):
    """Return the unique post-compose identity set or refuse it whole.

    The 4,000-item contract is over possible identities, before live-answer or
    decline filtering.  It includes ordinary composed questions, every schema
    question, and every synthetic ``opens:`` question.  Therefore a decision
    can change visibility but can never make an oversized candidate set pass.
    """
    identities = list(dict.fromkeys(
        [question["id"] for question in questions] + list(interview_ids)))
    if len(identities) > MAX_QUESTION_CANDIDATES:
        raise RhythmReadError("question candidates exceed their identity bound")
    return identities


def _composed_questions(connection, *, as_of: str, jurisdiction: str,
                        locale: str, held_as_of: str | None = None):
    """Compose one bounded question snapshot shared by every public read."""
    generated = candidates(connection, as_of=as_of, locale=locale,
                           held_as_of=held_as_of)
    generated += _corroboration_questions(connection, locale=locale)
    generated += _expectation_questions(connection, as_of=as_of,
                                        jurisdiction=jurisdiction,
                                        locale=locale)
    interview_ids = _interview_possible_ids(connection, jurisdiction)
    identities = _bounded_candidate_identities(generated, interview_ids)
    decisions = _latest_decisions(
        connection, "QuestionDeclined", identities)
    generated += _interview_questions(connection, jurisdiction=jurisdiction,
                                      locale=locale, declined=decisions)
    # Keep the invariant local if a future composer introduces an identity not
    # represented by the preflight universe above.
    _bounded_candidate_identities(generated, interview_ids)
    return generated, decisions


def _interview_questions(connection, *, jurisdiction: str, locale: str = "",
                         declined=()):
    """Compose the next schema question for every eligible account."""
    from .. import schemas
    from ..interview import Interview, HELD_KINDS, question_id

    accounts = _interview_accounts(connection)
    document_types = _interview_document_types(connection)
    stakes, touching = _interview_stakes(connection)
    answers = attribute_answers(connection, as_of="9999-12-31")
    fallback = (jurisdiction or "").lower()
    interviews = []
    declined = set(declined)

    for account in sorted(accounts):
        info = accounts[account]
        if info["kind"] not in HELD_KINDS:
            continue
        where = (info["jurisdiction"] or fallback).lower()
        docs = document_types.get(account, ())
        kind = schemas.kind_of_account(account, where,
            ledger_kind=info["kind"], doc_types=docs)
        schema = schemas.schema_for(kind, where) if kind else None
        answered = {}
        if schema is not None:
            for question in schema.questions:
                if question.known_from and info.get(question.known_from):
                    answered[question.key] = {"value": info[question.known_from],
                        "currency": "", "grade": "", "said": "", "source": "ledger"}
                for doc_type, value in question.answered_by_document.items():
                    if doc_type in docs:
                        answered[question.key] = {"value": value, "currency": "",
                            "grade": "", "said": "", "source": "document"}
                        break
        answered.update(answers.get(account, {}))
        stake = stakes.get(account, {})
        interviews.append(Interview(account=account, kind=kind,
            name=info["name"] or account.split(":")[-1],
            currency=info["currency"] or stake.get("currency", ""),
            stake=stake.get("paid", Decimal("0")),
            settles=max(int(stake.get("count", 0)), touching.get(account, 0)),
            answered=answered,
            declined={question.key for question in (schema.questions if schema else ())
                      if question_id(account, question.key) in declined},
            schema=schema, gap=""))

    out = []
    for interview in interviews:
        if interview.schema is None:
            continue
        asking = [question for question in (interview.next_question,) if question is not None]
        asking += [question for question in interview.schema.questions
                   if question.key in interview.declined
                   and question.key not in interview.answered]
        for question in asking:
            choices = tuple(question.choices)
            if question.answer == ANSWER_LINK:
                choices = tuple(other.account for other in interviews
                                if other.kind == question.links_to
                                and other.account != interview.account)
            text = say("interview", name=render.account({"name": interview.name}),
                       asks=question.asks)
            if question.unlocks:
                text += " " + say("interview_unlocks", unlocks=question.unlocks)
            out.append(_question(question_id(interview.account, question.key),
                "interview", text, say("interview_why"), interview.stake,
                interview.currency, interview.settles, "one",
                (Slot(name=question.key, type=question.answer, choices=choices,
                      required=True, asks=question.asks),),
                {"account": interview.account, "kind": interview.kind,
                 "key": question.key, "unlocks": question.unlocks,
                 "corroborated_by": list(question.corroborated_by)}))

    secured = set()
    for interview in interviews:
        if interview.schema is None:
            continue
        for question in interview.schema.questions:
            if question.answer == ANSWER_LINK and interview.value_of(question.key):
                secured.add((interview.kind, interview.value_of(question.key)))
    for interview in interviews:
        if interview.schema is None:
            continue
        for question in interview.schema.questions:
            value = interview.value_of(question.key).strip().lower()
            if (not question.opens or value not in ("yes", "true", "y")
                    or (question.opens, interview.account) in secured):
                continue
            schema = schemas.schema_for(question.opens, fallback)
            if schema is None:
                continue
            naming = schema.naming_question()
            out.append(_question(question_id(interview.account,
                                             f"opens:{question.opens}"),
                "interview", say("interview_opens",
                    name=render.account({"name": interview.name}),
                    kind_label=schema.label or question.opens),
                say("interview_why"), interview.stake, interview.currency,
                interview.settles, "one",
                (Slot(name="name", type=ANSWER_LABEL, required=True,
                      asks=naming.asks if naming is not None else ""),),
                {"account": interview.account, "opens": question.opens,
                 "key": "", "kind_label": schema.label or question.opens}))
    return out


def open_questions(connection, *, as_of: str, jurisdiction: str = "",
                   locale: str = "", limit=10, held_as_of: str | None = None):
    if limit is not None and (not isinstance(limit, int) or isinstance(limit, bool) or limit < 1 or limit > 500):
        raise ValueError("question limit must be between 1 and 500 or None")
    if not jurisdiction:
        from ..env import jurisdiction_from_env
        jurisdiction = jurisdiction_from_env().upper()
    generated, decisions = _composed_questions(
        connection, as_of=as_of, jurisdiction=jurisdiction, locale=locale,
        held_as_of=held_as_of)
    rows, pending = [], []
    for question in generated:
        body = decisions.get(question["id"])
        declined = (body is not None and body.get("amount") == question["amount"]
                    and int(body.get("count", 0)) == question["count"])
        (pending if declined else rows).append(question)
    rows.sort(key=lambda q: (-Decimal(q["amount"]), q["id"])); pending.sort(key=lambda q: (-Decimal(q["amount"]), q["id"]))
    shown, rest = (rows, []) if limit is None else (rows[:limit], rows[limit:])
    return {"questions": shown, "total": len(rows),
            "tail": {"count": len(rest), "amount": str(sum((Decimal(q["amount"]) for q in rest), Decimal(0)))},
            "pending": {"count": len(pending)}, "invite": say("free_text_invite"),
            "answered_by_document": say("answered_by_document")}


def find_question(connection, question_id: str, *, as_of: str,
                  jurisdiction: str = "", locale: str = ""):
    """Return one live question, including a still-current declined one."""
    if (not isinstance(question_id, str) or not question_id
            or len(question_id.encode("utf-8")) > MAX_INTERVIEW_QUESTION_KEY_BYTES):
        raise ValueError("question id must be a non-empty bounded string")
    if not jurisdiction:
        from ..env import jurisdiction_from_env
        jurisdiction = jurisdiction_from_env().upper()
    generated, _decisions = _composed_questions(
        connection, as_of=as_of, jurisdiction=jurisdiction, locale=locale)
    return next((question for question in generated
                 if question["id"] == question_id), None)


def pending_questions(connection, *, as_of: str, jurisdiction: str = "",
                      locale: str = ""):
    """Return the exact declined subset of the same revision-local queue."""
    if not jurisdiction:
        from ..env import jurisdiction_from_env
        jurisdiction = jurisdiction_from_env().upper()
    generated, decisions = _composed_questions(
        connection, as_of=as_of, jurisdiction=jurisdiction, locale=locale)
    rows = [question for question in generated
            if ((body := decisions.get(question["id"])) is not None
                and body.get("amount") == question["amount"]
                and int(body.get("count", 0)) == question["count"])]
    rows.sort(key=lambda question: (-Decimal(question["amount"]), question["id"]))
    return {"questions": rows, "total": len(rows)}


def _latest_decisions(connection, event_type: str, subjects: list[str]) -> dict[str, dict]:
    """Fetch latest current decisions in fixed, SQLite-safe subject batches."""
    if len(subjects) > MAX_QUESTION_CANDIDATES:
        raise RhythmReadError("review decision subjects exceed their input bound")
    out = {}
    for start in range(0, len(subjects), REVIEW_DECISION_BATCH):
        batch = subjects[start:start + REVIEW_DECISION_BATCH]
        if not batch:
            continue
        placeholders = ",".join("?" for _ in batch)
        rows = connection.execute(
            "SELECT subject_id,CASE WHEN length(CAST(body_json AS BLOB))<=? "
            "THEN body_json END FROM (SELECT subject_id,body_json,"
            "ROW_NUMBER() OVER (PARTITION BY subject_id ORDER BY source_sequence DESC) rn "
            "FROM review_decisions WHERE event_type=? "
            f"AND subject_id IN ({placeholders})) WHERE rn=1 LIMIT ?",
            (MAX_REVIEW_DECISION_BYTES, event_type, *batch, len(batch))).fetchall()
        for subject, encoded in rows:
            if subject in out:
                continue
            if (not isinstance(encoded, str) or
                    len(encoded.encode("utf-8")) > MAX_REVIEW_DECISION_BYTES):
                raise RhythmReadError("review decision payload exceeds its UTF-8 byte bound")
            try:
                body = json.loads(encoded)
            except (TypeError, ValueError) as exc:
                raise RhythmReadError("review decision payload is invalid") from exc
            if not isinstance(body, dict):
                raise RhythmReadError("review decision payload must be an object")
            out[subject] = body
    return out
