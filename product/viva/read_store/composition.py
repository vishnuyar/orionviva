"""Current findings and current-period answers composed from one SQL revision.

The event log remains canonical.  These reads consume only authenticated,
normalized rows in the selected immutable generation; they never rebuild a
``LedgerProjection`` or inspect raw documents.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from ..ledger.streams import FIXED_AMOUNT_CV, IN, MIN_FOR_CADENCE, OUT, Flow, Occurrence
from .rhythm import (_advance, _iso, _rank, _rhythms, MAX_OBLIGATION_RHYTHMS,
                     MAX_RHYTHM_POSTING_ROWS, RhythmReadError)


MAX_FINDINGS = 200
MAX_CURRENT_PERIOD_ACCOUNTS = 200
MAX_CURRENT_PERIOD_GOALS = 200
# The public finding window is 200, but decision lookup is a reusable bounded
# composition primitive.  Keep its input envelope large enough to exercise the
# same fixed-size batching guarantee as the question queue.
MAX_FINDING_DECISION_SUBJECTS = 1_000
REVIEW_DECISION_BATCH = 200
MAX_FINDING_DECISION_BYTES = 1_000_000
OBLIGATION_VERSION = "obligations-v1"
_IMPORTANCE = {"income_interrupted": 6, "possible_duplicate": 5,
               "expected_outflow_missing": 4, "amount_changed": 3,
               "fee_observed": 2, "recurring_obligation": 1}


@dataclass(frozen=True)
class Finding:
    id: str
    kind: str
    subject: str
    importance: int
    amount: Decimal
    currency: str
    dated: str
    record_ids: tuple[str, ...]
    account_ids: tuple[str, ...]
    stake: dict = field(compare=False)
    expected_date: str = ""
    prior_amount: Decimal | None = None
    current_amount: Decimal | None = None


@dataclass(frozen=True)
class ProjectionStep:
    date: str; kind: str; subject: str
    amount_min: Decimal; amount_max: Decimal
    balance_min: Decimal; balance_max: Decimal
    evidence_dates: tuple[str, ...] = (); record_ids: tuple[str, ...] = ()
    account_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProjectionExclusion:
    kind: str; identity: str; reason: str; currency: str = ""
    evidence_dates: tuple[str, ...] = (); record_ids: tuple[str, ...] = ()
    account_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class CurrentPeriodCompleteness:
    balances: bool; income: bool; obligations: bool
    planned_spending: bool; goals: bool


@dataclass(frozen=True)
class CurrentPeriodSlice:
    currency: str; horizon_start: str; horizon_end: str
    liquid_balance: Decimal; expected_income_min: Decimal
    expected_income_max: Decimal; obligations_min: Decimal
    obligations_max: Decimal; reserved_for_goals: Decimal
    goal_contributions: Decimal; remainder_min: Decimal; remainder_max: Decimal
    grade: str; evidence_dates: tuple[str, ...]; record_ids: tuple[str, ...]
    account_ids: tuple[str, ...]; steps: tuple[ProjectionStep, ...]
    assumptions: tuple[str, ...]; caveats: tuple[str, ...]
    missing_inputs: tuple[str, ...]; completeness: CurrentPeriodCompleteness
    exclusions: tuple[ProjectionExclusion, ...]


@dataclass(frozen=True)
class CurrentPeriodResult:
    horizon_start: str; horizon_end: str; slices: tuple[CurrentPeriodSlice, ...]
    excluded_accounts: tuple[str, ...] = ()
    exclusions: tuple[ProjectionExclusion, ...] = ()
    refusal_reason: str = ""

    @property
    def refused(self):
        return bool(self.refusal_reason)


def _records(rows):
    return tuple(sorted({row["key"] for row in rows} |
                        {row["doc_id"] for row in rows if row["doc_id"]}))


def _accounts(rows):
    return tuple(sorted({row["account"] for row in rows if row["account"]}))


def _finding(kind, identity, amount, currency, dated, rows, *, label="", **extra):
    stake = {"machinery": OBLIGATION_VERSION, "kind": kind,
             "subject": identity, "amount": str(amount), "dated": dated,
             "count": len(rows), "record_ids": list(_records(rows))}
    stake.update({key: str(value) if isinstance(value, Decimal) else value
                  for key, value in extra.items() if value is not None})
    digest = hashlib.sha256(f"{kind}|{identity}".encode()).hexdigest()[:20]
    return Finding(f"finding:{kind}:{digest}", kind, label or identity,
                   _IMPORTANCE[kind], amount, currency, dated, _records(rows),
                   _accounts(rows), stake, str(extra.get("expected_date") or ""),
                   extra.get("prior_amount"), extra.get("current_amount"))


def _shape(hypothesis, rows, today):
    import statistics
    currencies = {row["currency"] for row in rows if row["currency"]}
    if len(hypothesis["components"]) != 1 or len(currencies) != 1:
        return None
    dated = sorted(((_iso(row["date"]), row) for row in rows),
                   key=lambda item: (item[0], item[1]["key"]))
    if not dated:
        return None
    supported = frozenset(("monthly", "annual"))
    confirmed = tuple(x for x in hypothesis["confirmed"] if x in supported)
    measured = (hypothesis["measured"] and hypothesis["steady"] and
                hypothesis["cadence"] in supported and
                hypothesis["count"] >= MIN_FOR_CADENCE and
                bool(hypothesis["interval_days"]))
    proposed = tuple(x for x in hypothesis["proposed"] if x in supported)
    cadence = (confirmed[0] if len(confirmed) == 1 else
               hypothesis["cadence"] if measured else
               proposed[0] if len(proposed) == 1 else "")
    if not cadence or (len(confirmed) == 1 and len(dated) < 2):
        return None
    basis = "confirmed" if len(confirmed) == 1 else "measured" if measured else "observed"
    gaps = [(right[0] - left[0]).days for left, right in zip(dated, dated[1:])]
    interval = max(1, int(round(hypothesis["interval_days"] if measured else
                                statistics.median(gaps) if gaps else
                                30 if cadence == "monthly" else 365)))
    expected = _advance(dated[-1][0], cadence, interval,
                        max(when.day for when, _row in dated))
    return {"dated": dated, "first": dated[0][0], "last": dated[-1][0],
            "expected": expected, "interval": interval,
            "window": max(3, int(round(interval * .25))),
            "adequate": today <= expected + timedelta(days=interval),
            "amounts": [abs(row["amount"]) for _, row in dated],
            "basis": basis, "qualified": basis in ("confirmed", "measured")}


def findings(connection, *, today: str, include_set_aside=False, limit=MAX_FINDINGS,
             evidence_as_of: str | None = None, historical_rows=None):
    on = _iso(today)
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= MAX_FINDINGS:
        raise RhythmReadError(f"finding limit must be between 1 and {MAX_FINDINGS}")
    hypotheses, movement_map = _rhythms(connection, as_of=evidence_as_of or today,
        limit=MAX_OBLIGATION_RHYTHMS, result_label="finding rhythm candidates")
    from .scalar_bounds import selected as scalar_selected, refuse as refuse_scalars
    semantic_columns = (
        "movement_key", "linked", "nature", "category", "merchant_key",
        "account_id", "occurred_at", "amount_text", "currency", "description",
        "account_kind", "provenance_doc_id", "grade")
    selected, bounds = scalar_selected(semantic_columns, ("linked",))
    semantic_rows = historical_rows if historical_rows is not None else connection.execute(
        f"SELECT {selected} FROM movements "
        "ORDER BY occurred_at,movement_key LIMIT ?",
        (*bounds, MAX_RHYTHM_POSTING_ROWS + 1,)).fetchall()
    if len(semantic_rows) > MAX_RHYTHM_POSTING_ROWS:
        raise RhythmReadError(
            f"finding movement input exceeds its {MAX_RHYTHM_POSTING_ROWS}-row read bound")
    if historical_rows is None:
        refuse_scalars(semantic_rows, semantic_columns, ("linked",),
                       label="finding movement input")
    current_rows = {}
    for (key, linked, nature, category, merchant, account, occurred, amount,
         currency, description, kind, doc_id, grade) in semantic_rows:
        current_rows[key] = {
            "key": key, "linked": bool(linked), "nature": nature,
            "category": category, "merchant": merchant or "", "account": account,
            "date": occurred, "amount": Decimal(amount), "currency": currency,
            "description": description, "kind": kind, "doc_id": doc_id,
            "grade": grade,
        }
        if key in movement_map:
            movement_map[key].update(current_rows[key])
            current_rows[key] = movement_map[key]
    rows = list(current_rows.values())
    output = []
    duplicates = {}
    for row in rows:
        if not row.get("linked") and row.get("merchant"):
            key = (row["account"], row["date"], row["merchant"], row["currency"], abs(row["amount"]))
            duplicates.setdefault(key, []).append(row)
    for (account, dated, merchant, currency, amount), members in duplicates.items():
        if len(members) > 1:
            identity = f"{account}|{dated}|{merchant}|{currency}|{amount}"
            output.append(_finding("possible_duplicate", identity,
                amount * (len(members) - 1), currency, dated, members, label=merchant))
    for hypothesis in hypotheses:
        members = sorted((movement_map[key] for key in hypothesis["movements"]
                          if key in movement_map), key=lambda row: (row["date"], row["key"]))
        if len({row["currency"] for row in members if row["currency"]}) != 1:
            continue
        if len(members) >= MIN_FOR_CADENCE:
            prior, current = members[:-1], members[-1]
            flow = Flow(OUT if hypothesis["direction"] == OUT else IN,
                        [Occurrence(_iso(r["date"]), r["amount"], r["account"],
                                    r["kind"], r["description"]) for r in prior])
            median = flow.amount_median
            if (flow.amount_is_fixed is True and median > 0 and
                    abs(abs(current["amount"]) - median) > median * Decimal(str(FIXED_AMOUNT_CV))):
                output.append(_finding("amount_changed", hypothesis["subject"],
                    abs(current["amount"]), current["currency"], current["date"], members,
                    label=hypothesis["merchant"], prior_amount=median,
                    current_amount=abs(current["amount"])))
        shape = _shape(hypothesis, members, on)
        if shape is None:
            continue
        latest = members[-1]
        if hypothesis["direction"] == OUT and shape["adequate"] and shape["qualified"]:
            output.append(_finding("recurring_obligation", hypothesis["subject"],
                abs(latest["amount"]), latest["currency"], latest["date"], members,
                label=hypothesis["merchant"], expected_date=shape["expected"].isoformat()))
        if shape["qualified"] and on > shape["expected"] + timedelta(days=shape["window"]):
            kind = "expected_outflow_missing" if hypothesis["direction"] == OUT else "income_interrupted"
            output.append(_finding(kind, hypothesis["subject"], abs(latest["amount"]),
                latest["currency"], shape["last"].isoformat(), members,
                label=hypothesis["merchant"], expected_date=shape["expected"].isoformat()))
    for row in rows:
        if row.get("nature") == "spending" and str(row.get("category") or "").strip().lower() == "fees":
            output.append(_finding("fee_observed", row["key"], abs(row["amount"]),
                row["currency"], row["date"], [row],
                label=row.get("merchant") or row["description"]))
    unique = {item.id: item for item in output}
    ordered = sorted(unique.values(), key=lambda item:
                     (-item.importance, item.currency, -item.amount, item.id))
    if not include_set_aside:
        decisions = _latest_finding_decisions(
            connection, [item.id for item in ordered], evidence_as_of=evidence_as_of)
        kept = []
        for item in ordered:
            body = decisions.get(item.id)
            if body is None or body.get("stake") != item.stake:
                kept.append(item)
        ordered = kept
    if len(ordered) > limit:
        raise RhythmReadError(f"finding result exceeds its requested {limit}-row bound")
    return ordered


def current_period(revision, *, today: str, horizon_days: int = 30,
                   evidence_as_of: str | None = None):
    start = _iso(today)
    if not isinstance(horizon_days, int) or isinstance(horizon_days, bool) or not 1 <= horizon_days <= 366:
        raise ValueError("current-period horizon must be 1 to 366 calendar days")
    end = start + timedelta(days=horizon_days)
    evidence = evidence_as_of or today
    balances = revision._goal_account_balances(as_of=evidence, limit=MAX_CURRENT_PERIOD_ACCOUNTS)
    reserved = revision._goal_reservations_by_account(as_of=evidence)
    by_currency, exclusions = {}, []
    for account_id in sorted(balances):
        row = balances[account_id]
        if row["kind"] not in ("depository", "liability", "investment"):
            continue
        reason = ("account_not_depository" if row["kind"] != "depository" else
                  "account_not_issuer" if row["origin"] != "issued" else
                  "account_currency_unstated" if not row["currency"] else "")
        if reason:
            exclusions.append(ProjectionExclusion("account", account_id, reason,
                                                  row["currency"], account_ids=(account_id,)))
            continue
        bucket = by_currency.setdefault(row["currency"], {"balance": Decimal(0),
            "reserved": Decimal(0), "grades": [], "dates": set(), "records": set(),
            "accounts": set(), "caveats": [], "expected": []})
        held = reserved.get(account_id, Decimal(0)); bucket["balance"] += row["amount"] - held
        bucket["reserved"] += held; bucket["grades"].append(row["grade"])
        bucket["accounts"].add(account_id)
        if row["dated"]:
            bucket["dates"].add(row["dated"][:10])
            if row["dated"][:10] != start.isoformat(): bucket["caveats"].append("balance_freshness_unconfirmed")
        else: bucket["caveats"].append("balance_undated")
        if row["grade"] == "conflicted": bucket["caveats"].append("balance_conflicted")
        doc = row["provenance"].get("doc_id", "")
        if doc: bucket["records"].add(doc)
    if not by_currency:
        return CurrentPeriodResult(start.isoformat(), end.isoformat(), (),
            tuple(x.identity for x in exclusions), tuple(exclusions), "no_eligible_liquid_balance")
    hypotheses, movement_map = _rhythms(
        revision.connection,
        as_of=today if evidence == "9999-12-31" else evidence,
        limit=MAX_OBLIGATION_RHYTHMS, result_label="current-period rhythm candidates")
    expected = []
    for hypothesis in hypotheses:
        members = [movement_map[k] for k in hypothesis["movements"] if k in movement_map]
        shape = _shape(hypothesis, members, start)
        dates = tuple(sorted({r["date"][:10] for r in members if r["date"]}))
        records, accounts = _records(members), _accounts(members)
        if hypothesis["direction"] == IN:
            if shape is None or not shape["qualified"]:
                exclusions.append(ProjectionExclusion("income", hypothesis["subject"],
                    "incoming_not_qualified", hypothesis["currency"], dates, records, accounts)); continue
            if not shape["adequate"] or shape["expected"] < start:
                exclusions.append(ProjectionExclusion("income", hypothesis["subject"],
                    "incoming_interrupted", hypothesis["currency"], dates, records, accounts)); continue
            if shape["expected"] <= end:
                expected.append(("income", hypothesis["merchant"], shape["expected"],
                    min(shape["amounts"]), max(shape["amounts"]), hypothesis["currency"],
                    min((r["grade"] for r in members if r["grade"]), key=_rank, default=""),
                    dates, records, accounts))
        elif shape is not None and shape["adequate"]:
            if shape["basis"] == "observed":
                exclusions.append(ProjectionExclusion("obligation", "obligation:"+hypothesis["subject"],
                    "obligation_not_qualified", hypothesis["currency"],
                    (shape["first"].isoformat(), shape["last"].isoformat()), records, accounts))
            elif shape["expected"] <= end:
                expected.append(("obligation", hypothesis["merchant"], max(shape["expected"], start),
                    min(shape["amounts"]), max(shape["amounts"]), hypothesis["currency"],
                    min((r["grade"] for r in members if r["grade"]), key=_rank, default=""),
                    (shape["first"].isoformat(), shape["last"].isoformat()), records, accounts))
    goal_count = revision.connection.execute(
        "SELECT COUNT(*) FROM (SELECT goal_id FROM goal_event_history "
        "WHERE event_type='GoalCreated' AND occurred_at<=? AND goal_id<>'' "
        "GROUP BY goal_id LIMIT ?)",
        (evidence, MAX_CURRENT_PERIOD_GOALS + 1)).fetchone()[0]
    if goal_count > MAX_CURRENT_PERIOD_GOALS:
        raise RhythmReadError(
            f"current-period goals exceed their {MAX_CURRENT_PERIOD_GOALS}-goal read bound")
    for goal in revision.current_goal_views(
            today=today, limit=MAX_CURRENT_PERIOD_GOALS,
            evidence_as_of=evidence):
        if goal.get("issues"):
            exclusions.append(ProjectionExclusion("goal", goal["goal_id"],
                                                  "goal_terms_unreadable", goal["currency"])); continue
        if goal["state"] != "active" or goal["monthly_contribution"] is None or not goal["remaining"]:
            continue
        remaining = goal["remaining"]
        for when in revision._contribution_dates(start, goal.get("contribution_day"), through=end):
            amount = min(goal["monthly_contribution"], remaining)
            expected.append(("goal", goal["title"], date.fromisoformat(when), amount, amount,
                             goal["currency"], "", (), (), ()))
            remaining -= amount
            if not remaining: break
    for item in expected:
        if item[5] in by_currency: by_currency[item[5]]["expected"].append(item)
    slices = []
    for currency, bucket in sorted(by_currency.items()):
        relevant = tuple(x for x in exclusions if not x.currency or x.currency == currency)
        if any(x.reason == "incoming_interrupted" for x in relevant): bucket["caveats"].append("income_interrupted")
        low = high = bucket["balance"]; income = omin = omax = goals = Decimal(0)
        base_dates, base_records, base_accounts = (tuple(sorted(bucket["dates"])),
                                                   tuple(sorted(bucket["records"])),
                                                   tuple(sorted(bucket["accounts"])))
        steps = [ProjectionStep(start.isoformat(), "balance", "liquid balance",
                                low, high, low, high, base_dates, base_records, base_accounts)]
        for kind, subject, when, amin, amax, _currency, grade, dates, records, accounts in sorted(
                bucket["expected"], key=lambda x: (x[2], x[0], x[1])):
            when = when.isoformat()
            bucket["grades"].append(grade); bucket["dates"].update(dates)
            bucket["records"].update(records); bucket["accounts"].update(accounts)
            if kind == "income": income += amax; high += amax
            elif kind == "goal": goals += amax; low -= amax; high -= amin
            else: omin += amin; omax += amax; low -= amax; high -= amin
            steps.append(ProjectionStep(when, kind, subject, amin, amax, low, high,
                                        dates, records, accounts))
        slices.append(CurrentPeriodSlice(currency, start.isoformat(), end.isoformat(),
            bucket["balance"], Decimal(0), income, omin, omax, bucket["reserved"], goals,
            low, high, min((g for g in bucket["grades"] if g), key=_rank, default=""),
            tuple(sorted(bucket["dates"])), tuple(sorted(bucket["records"])),
            tuple(sorted(bucket["accounts"])), tuple(steps),
            (("rolling_30_day_horizon" if horizon_days == 30 else "caller_supplied_horizon"),
             "expected_income_not_guaranteed", "qualified_recurring_money_only"),
            tuple(sorted(set(bucket["caveats"]))), ("planned_spending",),
            CurrentPeriodCompleteness(not any(x.kind == "account" for x in relevant),
                not any(x.kind == "income" for x in relevant),
                not any(x.kind == "obligation" for x in relevant), False,
                not any(x.kind == "goal" for x in relevant)), relevant))
    return CurrentPeriodResult(start.isoformat(), end.isoformat(), tuple(slices),
        tuple(x.identity for x in exclusions if x.kind == "account"), tuple(exclusions))


def _latest_finding_decisions(connection, subjects, *, evidence_as_of=None):
    if len(subjects) > MAX_FINDING_DECISION_SUBJECTS:
        raise RhythmReadError("finding decision subjects exceed their input bound")
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
            "FROM review_decisions WHERE event_type='FindingSetAside' "
            f"AND subject_id IN ({placeholders}) "
            "AND (? IS NULL OR occurred_at<=?)) WHERE rn=1 LIMIT ?",
            (MAX_FINDING_DECISION_BYTES, *batch, evidence_as_of,
             evidence_as_of, len(batch))).fetchall()
        for subject, encoded in rows:
            if subject in out:
                continue
            if (not isinstance(encoded, str) or
                    len(encoded.encode("utf-8")) > MAX_FINDING_DECISION_BYTES):
                raise RhythmReadError("finding decision payload exceeds its UTF-8 byte bound")
            try:
                body = json.loads(encoded)
            except (TypeError, ValueError) as exc:
                raise RhythmReadError("finding decision payload is invalid") from exc
            if not isinstance(body, dict):
                raise RhythmReadError("finding decision payload must be an object")
            out[subject] = body
    return out
