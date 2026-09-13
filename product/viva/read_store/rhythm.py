"""Revision-local merchant rhythm and obligation composition from SQL facts.

This module consumes normalized rows from one immutable read-store revision
or ``LedgerProjection``.  The latter remains the parity oracle in tests.
"""
from __future__ import annotations

import calendar
import statistics
from datetime import date, timedelta
from decimal import Decimal

from merchantcore.enrich import BILLING_EITHER, BILLING_STANDING, KIND_BUSINESS

from ..ledger.events import (PERIOD_ANNUAL, PERIOD_IRREGULAR, PERIOD_MONTHLY,
                             periodicities_in, rhythm_subject)
from ..ledger.movement_identity import movement_key
from ..ledger.streams import IN, MIN_FOR_CADENCE, OUT, Flow, Occurrence, money_effect


MAX_RHYTHM_POSTING_ROWS = 10_000
MAX_MERCHANT_HISTORY = 4_000
MAX_RHYTHM_RULINGS = 2_000
MAX_TRANSFER_HISTORY = 10_000
MAX_RHYTHM_GROUPS = 500
MAX_GROUP_MOVEMENTS = 2_000
MAX_OBLIGATION_RHYTHMS = 500
MAX_RHYTHM_ACCOUNTS = 10_000
MAX_RESOLVER_PROFILES = 4_000
MAX_RHYTHM_JSON_BYTES = 1_000_000
MAX_RHYTHM_LOOKBACK_DAYS = 3_660
_GRADE = {"verified": 3, "corroborated": 2, "unverified": 1, "": 0}
_LICENSED_BILLING = (BILLING_STANDING, BILLING_EITHER)
_CADENCE_PROPOSES = {PERIOD_MONTHLY: PERIOD_MONTHLY, PERIOD_ANNUAL: PERIOD_ANNUAL}
_SUPPORTED = frozenset((PERIOD_MONTHLY, PERIOD_ANNUAL))


class RhythmReadError(ValueError):
    """A rhythm read is invalid or exceeds its explicit work envelope."""


def _bounded(connection, sql, parameters, bound: int, label: str):
    rows = connection.execute(sql + " LIMIT ?", (*parameters, bound + 1)).fetchall()
    if len(rows) > bound:
        raise RhythmReadError(f"{label} exceeds its {bound}-row read bound")
    return rows


def _rank(grade) -> int:
    return _GRADE.get(str(grade or ""), 0)


def _iso(value: str) -> date:
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError) as exc:
        raise RhythmReadError("rhythm reads require an ISO read date") from exc


def _merchant_records(connection, as_of: str):
    from .scalar_bounds import selected as scalar_selected, refuse as refuse_scalars
    columns = ("merchant_key", "grade", "category")
    selected, bounds = scalar_selected(columns)
    expressions = selected.split(",")
    rows = _bounded(
        connection,
        f"SELECT {expressions[0]},"
        "CASE WHEN length(CAST(attributes_json AS BLOB))<=? THEN attributes_json END,"
        "CASE WHEN length(CAST(aliases_json AS BLOB))<=? THEN aliases_json END,"
        f"{expressions[1]},source_sequence,{expressions[2]} "
        "FROM merchant_history WHERE occurred_at<=? ORDER BY occurred_at,source_sequence",
        (bounds[0], MAX_RHYTHM_JSON_BYTES, MAX_RHYTHM_JSON_BYTES,
         bounds[1], bounds[2], as_of),
        MAX_MERCHANT_HISTORY, "merchant history")
    rows.sort(key=lambda row: row[4])
    refuse_scalars([(row[0], row[3], row[5]) for row in rows], columns,
                   label="merchant vocabulary labels")
    import json
    records = {}
    for key, attributes, aliases, grade, _sequence, category in rows:
        if attributes is None or aliases is None:
            raise RhythmReadError("merchant history exceeds its UTF-8 byte bound")
        incoming = {"attributes": json.loads(attributes), "aliases": json.loads(aliases),
                    "grade": grade, "category": category}
        prior = records.get(key)
        if prior is None or _rank(grade) >= _rank(prior["grade"]):
            incoming["aliases"] = sorted(set(incoming["aliases"]) |
                                         set((prior or {}).get("aliases", ())))
            records[key] = incoming
        elif incoming["aliases"]:
            prior["aliases"] = sorted(set(prior.get("aliases", ())) |
                                      set(incoming["aliases"]))
    owners, conflicts = {}, set()
    for key, record in records.items():
        for alias in record.get("aliases", ()):
            if alias in owners and owners[alias] != key:
                conflicts.add(alias)
            else:
                owners[alias] = key
    return records, owners, conflicts


def _live_links(connection, as_of: str):
    rows = _bounded(
        connection,
        "SELECT event_type,movement_a,movement_b,source_sequence FROM transfer_history "
        "WHERE occurred_at<=? ORDER BY occurred_at,source_sequence",
        (as_of,), MAX_TRANSFER_HISTORY, "transfer history")
    rows.sort(key=lambda row: row[3])
    state = {}
    for event_type, left, right, _sequence in rows:
        if event_type in ("TransferLinked", "TransferUnlinked"):
            state[frozenset((left, right))] = event_type == "TransferLinked"
    return {key for pair, live in state.items() if live for key in pair}


def _rhythm_rulings(connection, as_of: str):
    rows = _bounded(
        connection,
        "SELECT subject,value_text,grade,occurred_at,source_sequence "
        "FROM ruling_history WHERE scope='rhythm' AND occurred_at<=? "
        "ORDER BY occurred_at,source_sequence",
        (as_of,), MAX_RHYTHM_RULINGS, "rhythm ruling history")
    rows.sort(key=lambda row: row[4])
    state = {}
    for subject, value, grade, occurred, sequence in rows:
        prior = state.get(subject)
        if prior is None or grade == "verified" or prior[1] != "verified":
            state[subject] = (value, grade, occurred, sequence)
    return state


def _movement_rows(connection, as_of: str):
    lower = (_iso(as_of) - timedelta(days=MAX_RHYTHM_LOOKBACK_DAYS)).isoformat()
    if connection.execute(
            "SELECT 1 FROM transactions WHERE occurred_at<? LIMIT 1", (lower,)).fetchone():
        raise RhythmReadError(
            f"rhythm history exceeds its {MAX_RHYTHM_LOOKBACK_DAYS}-day candidate window")
    accounts = {}
    from .scalar_bounds import selected as scalar_selected, refuse as refuse_scalars
    account_columns = ("event_type", "account_id", "kind", "currency", "institution")
    selected, bounds = scalar_selected(account_columns)
    account_rows = _bounded(
        connection,
        f"SELECT {selected} "
        "FROM accounts INDEXED BY accounts_by_source_date "
        "WHERE occurred_at<=? ORDER BY source_sequence", (*bounds, as_of),
        MAX_RHYTHM_ACCOUNTS, "account history")
    refuse_scalars(account_rows, account_columns, label="rhythm account labels")
    for event_type, account, kind, currency, institution in account_rows:
        if event_type == "AccountOpened":
            accounts[account] = {"kind": kind or "", "currency": currency or "",
                                 "institution": institution or ""}
        else:
            state = accounts.setdefault(
                account, {"kind": "", "currency": "", "institution": ""})
            state["institution"] = state["institution"] or institution or ""
    from .scalar_bounds import selected as scalar_selected, refuse as refuse_scalars
    posting_columns = (
        "t.source_sequence", "p.posting_index", "p.account_id", "t.occurred_at",
        "p.amount_text", "p.grade", "t.description", "t.provenance_doc_id",
        "t.provenance_page", "t.provenance_region", "t.provenance_note")
    selected, bounds = scalar_selected(
        posting_columns, ("t.source_sequence", "p.posting_index",
                          "t.provenance_page"))
    rows = _bounded(
        connection,
        f"SELECT {selected} "
        "FROM transactions t JOIN postings p ON p.source_sequence=t.source_sequence "
        "WHERE t.occurred_at>=? AND t.occurred_at<=? ORDER BY t.occurred_at,"
        "t.source_sequence,p.posting_index",
        (*bounds, lower, as_of), MAX_RHYTHM_POSTING_ROWS,
        "rhythm joined posting input")
    refuse_scalars(rows, posting_columns,
                   ("t.source_sequence", "p.posting_index", "t.provenance_page"),
                   label="rhythm joined posting input")
    rows.sort(key=lambda row: (row[2], row[3], row[6], row[4], row[0], row[1]))
    from merchantcore.profile import Profile, is_inducible
    from ..ledger.merchant_keys import resolve_keys
    from ..ledger.merchants import normalize_merchant
    profile_columns = ("institution", "account_kind")
    selected, bounds = scalar_selected(profile_columns)
    profile_rows = _bounded(
        connection,
        f"SELECT {selected},"
        "CASE WHEN length(CAST(profile_json AS BLOB))<=? THEN profile_json END "
        "FROM resolver_profiles ORDER BY institution,account_kind",
        (*bounds, MAX_RHYTHM_JSON_BYTES), MAX_RESOLVER_PROFILES,
        "resolver profile input")
    refuse_scalars([row[:2] for row in profile_rows], profile_columns,
                   label="resolver profile labels")
    if any(profile_json is None for _institution, _kind, profile_json in profile_rows):
        raise RhythmReadError("resolver profile input exceeds its UTF-8 byte bound")
    profiles = {(institution, kind): Profile.from_dict(__import__("json").loads(profile_json))
                for institution, kind, profile_json in profile_rows}
    def profile_for(institution, kind):
        return profiles.get((institution, kind)) if is_inducible(kind) else None
    resolver_inputs = tuple(dict.fromkeys(
        (row[2], accounts.get(row[2], {}).get("institution", ""),
         accounts.get(row[2], {}).get("kind", ""), row[6]) for row in rows
        if accounts.get(row[2], {}).get("kind") in
        ("depository", "liability", "investment")))
    resolved = resolve_keys(resolver_inputs, profile_for=profile_for)
    counts, out = {}, []
    for seq, posting, account, occurred, amount, grade, description, doc, page, region, note in rows:
        state = accounts.get(account, {})
        kind, currency = state.get("kind", ""), state.get("currency", "")
        if kind not in ("depository", "liability", "investment"):
            continue
        signature = (doc, account, occurred, amount, description)
        occurrence = counts.get(signature, 0); counts[signature] = occurrence + 1
        stable = movement_key(doc, account, occurred, amount, description, occurrence)
        descriptor = normalize_merchant(description)
        brand = resolved.get((account, description), descriptor)
        structural = tuple(resolved.candidates.get((account, description), ()))
        person = (account, description) in resolved.persons
        out.append({"key": stable, "source_sequence": seq, "posting_index": posting,
                    "account": account, "kind": kind, "date": occurred,
                    "amount": Decimal(amount), "grade": grade, "currency": currency,
                    "description": description, "doc_id": doc, "page": page,
                    "region": region, "note": note, "brand": brand,
                    "structural": structural,
                    "descriptor": descriptor, "person": bool(person)})
    return out


def _amount_runs(flow: Flow):
    order = sorted(range(len(flow.occurrences)),
                   key=lambda i: (abs(flow.occurrences[i].amount),
                                  flow.occurrences[i].date,
                                  flow.occurrences[i].description))
    runs = []
    for index in order:
        grown = ([flow.occurrences[j] for j in runs[-1]] + [flow.occurrences[index]]
                 if runs else [])
        if grown and Flow(flow.direction, grown).amount_is_fixed:
            runs[-1].append(index)
        else:
            runs.append([index])
    return runs


def _parts(flow: Flow):
    whole = [list(range(len(flow.occurrences)))]
    repeated = [run for run in _amount_runs(flow) if len(run) > 1]
    if not repeated:
        return whole
    stable = max(repeated, key=lambda run: (
        len(run), sum(abs(flow.occurrences[index].amount) for index in run)))
    held = set(stable)
    remainder = [index for index in range(len(flow.occurrences)) if index not in held]
    return whole if not remainder else [sorted(stable), remainder]


def _component(flow: Flow, rows, indexes):
    part = Flow(flow.direction, [flow.occurrences[index] for index in indexes])
    measured = part.n >= MIN_FOR_CADENCE
    steady = measured and part.interval_is_steady
    named = (_CADENCE_PROPOSES.get(part.cadence_class) if steady
             else PERIOD_IRREGULAR if measured else None)
    interval = part.median_interval_days if steady else None
    if isinstance(interval, float) and interval.is_integer():
        interval = int(interval)
    return {"count": part.n, "amount": part.total,
            "amount_stability": part.amount_stability, "measured": measured,
            "steady": steady, "cadence": part.cadence_class if measured else "",
            "interval_days": interval, "proposed": (named,) if named else (),
            "movements": tuple(rows[index]["key"] for index in indexes)}


def _rhythms(connection, *, as_of: str, limit: int, result_label: str):
    """Compose rhythms under a caller-specific bounded result envelope."""
    _iso(as_of)
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
        raise RhythmReadError("rhythm composition limit must be positive")
    records, alias_owner, conflicts = _merchant_records(connection, as_of)
    linked, rulings = _live_links(connection, as_of), _rhythm_rulings(connection, as_of)
    rows = _movement_rows(connection, as_of)
    leading, candidate_rows = set(), {}
    for row in rows:
        canonical = next((alias_owner[key] for key in row["structural"]
                          if key in alias_owner and key not in conflicts), "")
        candidates = tuple(dict.fromkeys(key for key in
            (canonical, row["brand"], *row["structural"], row["descriptor"]) if key)) or ("",)
        row["candidates"] = candidates; row["merchant"] = candidates[0]
        leading.add(candidates[0])
        for key in candidates:
            candidate_rows.setdefault(key, set()).update(candidates)
    aliases = {key: tuple(sorted(known, key=lambda item: (item not in leading, item)))
               for key, known in candidate_rows.items()}
    groups = {}
    for row in rows:
        if row["key"] in linked or row["person"] or not row["merchant"]:
            continue
        try:
            direction = IN if money_effect(row["kind"], row["amount"]) > 0 else OUT
        except ValueError:
            continue
        groups.setdefault((row["merchant"], direction), []).append(row)
    if len(groups) > MAX_RHYTHM_GROUPS:
        raise RhythmReadError(
            f"rhythm candidates exceed their {MAX_RHYTHM_GROUPS}-group read bound")
    result = []
    for (merchant, direction), members in groups.items():
        if len(members) > MAX_GROUP_MOVEMENTS:
            raise RhythmReadError(
                f"rhythm {merchant!r} exceeds its {MAX_GROUP_MOVEMENTS}-movement bound")
        members.sort(key=lambda row: (row["date"], row["amount"], row["description"]))
        prior = None
        for row in members:
            for candidate in row["candidates"]:
                found = records.get(candidate)
                if found is not None and (prior is None or
                                           _rank(found["grade"]) > _rank(prior["grade"])):
                    prior = found
        attributes = (prior or {}).get("attributes") or {}
        billing = str(attributes.get("billing", ""))
        if (str(attributes.get("counterparty_kind", "")) != KIND_BUSINESS
                or billing not in _LICENSED_BILLING):
            continue
        flow = Flow(direction, [Occurrence(_iso(row["date"]), row["amount"],
                                           row["account"], row["kind"],
                                           row["description"]) for row in members])
        components = tuple(_component(flow, members, indexes) for indexes in _parts(flow))
        whole = components[0] if len(components) == 1 else None
        period = str(attributes.get("billing_period", ""))
        proposed = ()
        if whole is not None:
            proposed = (whole["proposed"] if whole["measured"] else
                        ((period,) if period in _SUPPORTED else ()))
        best = None
        for key in aliases.get(merchant, (merchant,)):
            found = rulings.get(rhythm_subject(key, direction))
            if found is not None and (best is None or
                    (_rank(found[1]), found[2]) > (_rank(best[1]), best[2])):
                best = found
        result.append({"merchant": merchant, "direction": direction,
                       "count": flow.n, "amount": flow.total,
                       "currency": next((row["currency"] for row in members
                                         if row["currency"]), ""),
                       "example": members[0]["description"],
                       "movements": [row["key"] for row in members],
                       "billing": billing, "billing_period": period,
                       "measured": bool(whole and whole["measured"]),
                       "steady": bool(whole and whole["steady"]),
                       "cadence": whole["cadence"] if whole else "",
                       "interval_days": whole["interval_days"] if whole else None,
                       "amount_stability": whole["amount_stability"] if whole else "",
                       "proposed": proposed,
                       "confirmed": periodicities_in(best[0]) if best else (),
                       "components": components,
                       "subject": rhythm_subject(merchant, direction)})
    result.sort(key=lambda item: (item["merchant"], item["direction"]))
    if len(result) > limit:
        # Stable keyset pagination belongs to the consuming question slice;
        # this semantic result refuses instead of silently presenting a prefix.
        raise RhythmReadError(f"{result_label} exceeds its requested {limit}-row bound")
    return result, {row["key"]: row for row in rows}


def rhythms(connection, *, as_of: str, limit: int = 200):
    """Return bounded rhythm hypotheses from one immutable SQL revision."""
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 200:
        raise RhythmReadError("rhythm limit must be between 1 and 200")
    return _rhythms(connection, as_of=as_of, limit=limit,
                    result_label="rhythm result")


def _advance(last: date, cadence: str, interval: int, anchor: int | None):
    if cadence == PERIOD_MONTHLY:
        year, month = (last.year + 1, 1) if last.month == 12 else (last.year, last.month + 1)
        return date(year, month, min(anchor or last.day, calendar.monthrange(year, month)[1]))
    if cadence == PERIOD_ANNUAL:
        year = last.year + 1
        return date(year, last.month,
                    min(anchor or last.day, calendar.monthrange(year, last.month)[1]))
    return last + timedelta(days=interval)


def obligations(connection, *, today: str, limit: int = 200,
                evidence_as_of: str | None = None):
    """Return bounded outgoing obligations with canonical stable identities."""
    on = _iso(today)
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 200:
        raise RhythmReadError("obligation limit must be between 1 and 200")
    # Obligations are a qualified subset of outgoing rhythms.  The public
    # rhythm page limit must not hide an obligation behind unrelated incoming
    # rhythms, so composition gets its own bounded candidate envelope before
    # the requested obligation limit is applied below.
    hypotheses, movement_map = _rhythms(
        connection, as_of=evidence_as_of or today, limit=MAX_OBLIGATION_RHYTHMS,
        result_label="obligation rhythm candidates")
    output = []
    for hypothesis in hypotheses:
        if hypothesis["direction"] != OUT:
            continue
        rows = [movement_map[key] for key in hypothesis["movements"] if key in movement_map]
        currencies = {row["currency"] for row in rows if row["currency"]}
        if len(hypothesis["components"]) != 1 or len(currencies) != 1:
            continue
        dated = sorted(((_iso(row["date"]), row) for row in rows),
                       key=lambda item: (item[0], item[1]["key"]))
        confirmed = tuple(value for value in hypothesis["confirmed"] if value in _SUPPORTED)
        measured = (hypothesis["measured"] and hypothesis["steady"]
                    and hypothesis["cadence"] in _SUPPORTED
                    and hypothesis["count"] >= MIN_FOR_CADENCE
                    and bool(hypothesis["interval_days"]))
        proposed = tuple(value for value in hypothesis["proposed"] if value in _SUPPORTED)
        cadence = (confirmed[0] if len(confirmed) == 1 else
                   hypothesis["cadence"] if measured else
                   proposed[0] if len(proposed) == 1 else "")
        if not cadence or not dated or (len(confirmed) == 1 and len(dated) < 2):
            continue
        basis = "confirmed" if len(confirmed) == 1 else "measured" if measured else "observed"
        gaps = [(right[0] - left[0]).days for left, right in zip(dated, dated[1:])]
        interval = max(1, int(round(hypothesis["interval_days"] if measured else
                                    statistics.median(gaps) if gaps else
                                    30 if cadence == PERIOD_MONTHLY else 365)))
        expected = _advance(dated[-1][0], cadence, interval,
                            max(when.day for when, _row in dated))
        if on > expected + timedelta(days=interval):
            continue
        amounts = [abs(row["amount"]) for _when, row in dated]
        grades = [row["grade"] for row in rows if row["grade"]]
        weakest = min(grades, key=_rank) if grades else ""
        records = tuple(sorted({row["key"] for row in rows} |
                               {row["doc_id"] for row in rows if row["doc_id"]}))
        accounts = tuple(sorted({row["account"] for row in rows if row["account"]}))
        caveats = (() if basis == "confirmed" else
                   ("measured_not_confirmed",) if basis == "measured" else
                   ("observed_prior_only",))
        output.append({"id": f"obligation:{hypothesis['subject']}",
                       "subject": hypothesis["merchant"], "cadence": cadence,
                       "expected_date": expected.isoformat(),
                       "amount_min": min(amounts), "amount_max": max(amounts),
                       "currency": hypothesis["currency"], "basis": basis,
                       "status": "due" if basis in ("confirmed", "measured") and on >= expected else "expected",
                       "grade": weakest, "count": len(rows),
                       "dated_from": dated[0][0].isoformat(),
                       "dated_to": dated[-1][0].isoformat(),
                       "record_ids": records, "account_ids": accounts,
                       "caveats": caveats})
    output.sort(key=lambda item: (item["expected_date"], item["subject"], item["currency"]))
    if len(output) > limit:
        raise RhythmReadError(f"obligation result exceeds its requested {limit}-row bound")
    return output
