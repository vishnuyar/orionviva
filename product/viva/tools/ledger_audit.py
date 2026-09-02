"""Completeness, provenance, and transparency ledger reads."""

from __future__ import annotations

from .ledger_common import *

# ---------------------------------------------------------- check_completeness

COMPLETENESS_PARAMS = {
    "type": "object",
    "properties": {"view": {"type": "string", "enum": ["attention"]}},
    "additionalProperties": False,
}

def check_completeness(proj, args: dict) -> ToolResult:
    if args.get("view") == "attention":
        return _attention_summary(proj)
    captured = proj.captured_docs()
    posted_ids = proj.posted_doc_ids()
    held = [did for did in captured if did not in posted_ids]
    awaiting_types: dict[str, int] = {}
    for did in held:
        awaiting_types[captured[did]] = awaiting_types.get(captured[did], 0) + 1
    accounts = []
    for info in _real_accounts(proj):
        ba = proj.balance(info.account)
        accounts.append({"account": info.account, "name": info.name,
                         "kind": info.kind, "dated": ba.dated,
                         "grade": ba.grade})
    unidentified = len(proj.uncategorized_merchants())
    holds = [{"doc_id": b.get("doc_id", ""), "reason": b.get("reason", "")}
             for b in proj.open_holds()]
    caveats = []
    if holds:
        caveats.append(f"{len(holds)} document(s) are held awaiting review "
                       "and are not in any figure.")
    if unidentified:
        caveats.append(f"{unidentified} counterparty(ies) have no category "
                       "yet.")
    all_docs = sorted(captured)
    # Four counts of this agent's own paperwork, not of the person's money: a
    # wrong one moves the account the agent gives of its records and no figure
    # about what they hold, so each is activity and carries no grade.
    #
    # This read takes no filters, so each count is taken over every document
    # the agent holds and every counterparty it has seen — the whole of what it
    # counts, with nothing narrowing it and nothing left out.
    figures = [
        figure(len(captured), "documents held", quantity=quantity.COUNT,
               kind=ACTIVITY, record_ids=all_docs,
               boundary=bounded(whole=True)),
        figure(len(captured) - len(held), "documents posted to the ledger",
               quantity=quantity.COUNT, kind=ACTIVITY, record_ids=all_docs,
               boundary=bounded(whole=True)),
        figure(len(held), "documents awaiting review", quantity=quantity.COUNT,
               kind=ACTIVITY, record_ids=all_docs,
               boundary=bounded(whole=True)),
        figure(unidentified, "counterparties with no category yet",
               quantity=quantity.COUNT, kind=ACTIVITY, record_ids=all_docs,
               boundary=bounded(whole=True)),
    ]
    # A day, which is a point in time and not a magnitude: it fills no hole
    # that asks for an amount, a count or a proportion. One account's day is
    # not every account's, so it declares itself not whole rather than saying
    # nothing about what it was taken over.
    figures += [figure(a["dated"], f"{a['name'] or a['account']} — the date "
                       "its evidence is good as of",
                       quantity=quantity.TIME,
                       grade=a["grade"], dated=a["dated"],
                       record_ids=[a["account"]],
                       boundary=bounded(whole=False))
                for a in accounts if a["dated"]]
    return ToolResult(
        tool="check_completeness", ok=True, figures=figures,
        identifiers=_identifiers(proj, (a["account"] for a in accounts)),
        data={"documents_held": len(captured), "posted": len(captured) - len(held),
              "awaiting": len(held), "awaiting_types": awaiting_types,
              "holds": holds, "accounts": accounts,
              "unidentified_counterparties": unidentified},
        record_ids=sorted(captured),
        caveats=caveats,
        coverage="Every captured document and every balance-holding account.",
        text=(f"{len(captured)} document(s) held; {len(captured) - len(held)} "
              f"posted; {len(held)} awaiting review."))


def _attention_summary(proj) -> ToolResult:
    """Summarize the existing ordered queue."""
    from ..questions import open_questions

    payload = open_questions(proj, limit=3)
    questions = list(payload["questions"])
    def label(question):
        refs = question.get("refs") or {}
        subject = (refs.get("example") or refs.get("subject")
                   or refs.get("document")
                   or str(question["id"]).split(":", 1)[-1])
        return f"{question.get('kind') or 'open'} — {subject}"
    figures = [
        # Figure labels describe the count; ranking stakes remain outside them.
        figure(1, label(question),
               quantity=quantity.COUNT, kind=ACTIVITY,
               record_ids=[str(question["id"])],
               boundary=bounded(whole=not payload["tail"]["count"]))
        for question in questions
    ]
    if not figures:
        figures = [figure(0, "open questions needing attention",
                          quantity=quantity.COUNT, kind=ACTIVITY,
                          boundary=bounded(whole=True))]
    return ToolResult(
        tool="check_completeness", ok=True, figures=figures,
        data={"questions": questions, "total": payload["total"],
              "tail": dict(payload["tail"]),
              "pending": dict(payload["pending"])},
        record_ids=[str(question["id"]) for question in questions],
        caveats=(["More open questions remain below this consequence-ordered "
                  "preview."] if payload["tail"]["count"] else []),
        coverage="The highest-consequence open questions, in their existing order.",
        text="The highest-consequence open questions are summarized by kind.")


# ------------------------------------------------------------- get_provenance

PROVENANCE_PARAMS = {
    "type": "object",
    "properties": {"record_id": {"type": "string"},
                   "movement_phrase": {"type": "string"},
                   "from": {"type": "string"},
                   "to": {"type": "string"}},
    "additionalProperties": False,
}


def get_provenance(proj, args: dict) -> ToolResult:
    if args.get("movement_phrase"):
        return _movement_treatment(proj, args)
    rid = str(args.get("record_id") or "")
    if not rid:
        return refusal("get_provenance", "missing_record",
                       "Name one record or one movement description to explain.")
    captured = proj.captured_docs()
    if rid in captured:
        # posted: its figures are in the ledger. held: read but set aside,
        # awaiting review. captured: received and not yet processed.
        state = ("posted" if rid in proj.posted_doc_ids()
                 else "held" if proj.is_resolved(rid) else "captured")
        return ToolResult(
            tool="get_provenance", ok=True, record_ids=[rid],
            data={"kind": "document", "doc_id": rid,
                  "doc_type": captured[rid], "state": state},
            text=f"Document {rid}: a {captured[rid]}, {state}.")
    if proj.seen_account(rid):
        ba = proj.balance(rid)
        ids = [rid] + ([ba.provenance.doc_id] if ba.provenance.doc_id else [])
        measures = _measure_of(proj.account_info(rid).kind)
        # What the account is worth, composed once and the same way every other
        # read of it composes: cash plus the holdings its latest statement
        # measured, dated by the oldest measurement under it and graded by the
        # weakest, with holdings in a second currency kept as a second figure.
        values = proj.composed_values(rid)
        # One account's balance, named as the account it is of: this read
        # reaches one record and knows nothing about how many others there
        # are, so it never claims to be the whole of what a balance measures.
        return ToolResult(
            tool="get_provenance", ok=True,
            grade=weakest(value.grade for value in values),
            dated=min((value.as_of for value in values if value.as_of),
                      default=""),
            figures=[figure(value.amount, f"{rid} — {measures}",
                            quantity=measures,
                            grade=value.grade, dated=value.as_of,
                            currency=value.currency, record_ids=ids,
                            boundary=bounded(whole=False,
                                             cut=[{"kind": BY_ACCOUNT,
                                                   "value": rid}]))
                     for value in values],
            caveats=([MIXED_VINTAGE]
                     if any(_mixed_vintage(value.dates) for value in values)
                     else []),
            identifiers=_identifiers(proj, [rid]),
            record_ids=[rid] + ([ba.provenance.doc_id]
                                if ba.provenance.doc_id else []),
            provenance=[ba.provenance.to_dict()],
            data={"kind": "account", "account": rid,
                  "explanation": ba.explanation,
                  "reconciliation": (ba.reconciliation.explain()
                                     if ba.reconciliation else None)},
            text=ba.explanation)
    match = next((m for m in proj.movements() if m.key == rid), None)
    if match is not None:
        grades = movements_view.movement_grades(proj.core)
        ids = [match.key] + ([match.provenance.doc_id]
                             if match.provenance.doc_id else [])
        # One movement is the whole of what the quantity `movement` ranges
        # over, and a member of the set rather than a slice of it.
        return ToolResult(
            tool="get_provenance", ok=True,
            grade=grades.get(match.key, ""), dated=match.date,
            figures=[figure(movements_view.money_effect(match),
                            f"{match.description} on {match.date}",
                            quantity=quantity.MOVEMENT,
                            grade=grades.get(match.key, ""), dated=match.date,
                            currency=match.currency, record_ids=ids,
                            boundary=bounded(whole=True))],
            identifiers=_identifiers(proj, [match.account]),
            record_ids=[match.key] + ([match.provenance.doc_id]
                                      if match.provenance.doc_id else []),
            provenance=[match.provenance.to_dict()],
            data={"kind": "movement",
                  "movement": _movement_row(proj, match, grades)},
            text=(f"Movement of {movements_view.money_effect(match)} on "
                  f"{match.date}: nature '{match.nature}', decided by rung "
                  f"'{match.nature_reason}'."))
    return refusal("get_provenance", "unknown_record",
                   f"'{rid}' names no document, account or movement I hold.",
                   accepted=["a doc_id from check_completeness",
                             "an account id from query_ledger balances",
                             "a movement record_id from query_ledger "
                             "transactions"])


def _movement_treatment(proj, args: dict) -> ToolResult:
    phrase = _merchant_filter_key(str(args["movement_phrase"]))
    start, end = str(args.get("from") or ""), str(args.get("to") or "")
    if bool(start) != bool(end) or (start and (
            not _is_iso_date(start) or not _is_iso_date(end) or start > end)):
        return refusal("get_provenance", "bad_date",
                       "A movement explanation period needs valid inclusive edges.")
    reached = []
    for movement in proj.movements():
        if start and not start <= movement.date <= end:
            continue
        merchant = _merchant_key(proj, movement)
        tier = max(_match_tier(phrase, merchant),
                   _match_tier(phrase, _merchant_filter_key(
                       movement.description)))
        if tier:
            reached.append((tier, movement))
    if not reached:
        return refusal("get_provenance", "not_found",
                       "No movement uniquely matched that description.")
    best = max(tier for tier, _movement in reached)
    matches = [movement for tier, movement in reached if tier == best]
    treatments = {(movement.nature, movement.nature_reason)
                  for movement in matches}
    if len(treatments) != 1:
        return refusal(
            "get_provenance", "ambiguous_movement_treatment",
            "Matching movements have materially different treatments; name a "
            "date or a more specific description.",
            matching_records=[movement.key for movement in matches])
    grades = movements_view.movement_grades(proj.core)
    nature, reason = next(iter(treatments))
    figures = []
    ids = []
    for movement in matches:
        evidence = [movement.key] + ([movement.provenance.doc_id]
                                    if movement.provenance.doc_id else [])
        ids.extend(evidence)
        figures.append(figure(
            movements_view.money_effect(movement),
            f"{movement.description} — treated as {nature} because {reason}",
            quantity=quantity.MOVEMENT, grade=grades.get(movement.key, ""),
            dated=movement.date, currency=movement.currency,
            record_ids=evidence, boundary=bounded(whole=True)))
    return ToolResult(
        tool="get_provenance", ok=True, figures=figures,
        identifiers=_identifiers(proj, [movement.account for movement in matches]),
        record_ids=sorted(set(ids)),
        provenance=[movement.provenance.to_dict() for movement in matches],
        data={"kind": "movement_treatment", "nature": nature,
              "nature_reason": reason,
              "record_ids": [movement.key for movement in matches]},
        coverage=f"{len(matches)} matching movement(s) share this treatment.",
        text=f"The matching movement treatment is {nature}: {reason}.")


# ----------------------------------------------------------- get_transparency

TRANSPARENCY_PARAMS = {
    "type": "object",
    "properties": {"topic": {"type": "string",
                             "enum": ["agent_activity", "calls_spent",
                                      "declined_questions"]},
                   "since": {"type": "string"}},
    "required": ["topic"]}


# What one journal entry says: when, what fired, on what, how it went, what it
# cost. The evidence behind it and the artifact it produced are not here.
JOURNAL_FIELDS = ("occurred_at", "rule", "target", "outcome", "calls")


def _event_ids(entries) -> list:
    """The ledger events behind a journal read, in order and deduplicated."""
    return sorted({e["event_id"] for e in entries if e.get("event_id")})


def get_transparency(proj, args: dict) -> ToolResult:
    topic = args["topic"]
    since = args.get("since", "")
    if since and not _is_iso_date(since):
        return refusal("get_transparency", "bad_date",
                       f"since must be an ISO date, got '{since}'.")
    # Every number here is a claim about the agent rather than about the
    # person's money, and stands on the ledger events that recorded the
    # behaviour. A day to run from narrows what the two journal topics count,
    # so their figures record it and declare the whole only where nothing was
    # asked for. The questions set aside are not narrowed by it, and their
    # count is over every one of them.
    since_narrowed = [{"kind": BY_SINCE, "value": since}] if since else []
    if topic == "agent_activity":
        log = proj.agent_log()
        if since:
            log = [a for a in log
                   if str(a.get("occurred_at", ""))[:10] >= since]
        # The journal is append-only, so this is the one read whose size grows
        # with time. The most recent entries are shown and the count answers for
        # the rest.
        shown = [{k: a[k] for k in JOURNAL_FIELDS if k in a}
                 for a in log[-MAX_JOURNAL:]]
        events = _event_ids(log)
        said = f"{len(shown)} of {len(log)} unattended action(s) on record"
        said += (", the most recent." if len(shown) < len(log)
                 else "; nothing is collapsed.")
        if len(shown) < len(log):
            said += " Narrow with since to see a different period."
        return ToolResult(
            tool="get_transparency", ok=True,
            data={"topic": topic, "actions": shown, "shown": len(shown),
                  "count": len(log)},
            figures=[figure(len(log), "unattended actions on record",
                            quantity=quantity.COUNT,
                            kind=ACTIVITY, record_ids=events,
                            boundary=bounded(whole=not since_narrowed,
                                             selected=since_narrowed,
                                             cut=cut_set(since_narrowed)))],
            record_ids=events, coverage=said, text=said)
    if topic == "calls_spent":
        log = [a for a in proj.agent_log()
               if not since or str(a.get("occurred_at", ""))[:10] >= since]
        calls = proj.agent_calls_spent(since=since)
        events = _event_ids(log)
        return ToolResult(
            tool="get_transparency", ok=True,
            data={"topic": topic, "calls": calls, "since": since},
            figures=[figure(calls, "model calls the agent spent on its own",
                            quantity=quantity.COUNT,
                            kind=ACTIVITY, record_ids=events,
                            boundary=bounded(whole=not since_narrowed,
                                             selected=since_narrowed,
                                             cut=cut_set(since_narrowed)))],
            record_ids=events,
            caveats=["Counts only the maintenance agent's unattended calls; "
                     "a conversation's own model calls are recorded "
                     "separately."],
            text=(f"{calls} model call(s) spent by the agent"
                  + (f" since {since}." if since else " in total.")))
    declined = proj.declined_questions()
    events = _event_ids(declined.values())
    return ToolResult(
        tool="get_transparency", ok=True,
        data={"topic": topic, "declined": declined, "count": len(declined)},
        figures=[figure(len(declined), "questions set aside",
                        quantity=quantity.COUNT,
                        kind=ACTIVITY, record_ids=events,
                        boundary=bounded(whole=True))],
        record_ids=events,
        text=f"{len(declined)} question(s) set aside.")


__all__ = ['COMPLETENESS_PARAMS', 'check_completeness', 'PROVENANCE_PARAMS',
           'get_provenance', 'TRANSPARENCY_PARAMS', 'JOURNAL_FIELDS',
           '_event_ids', 'get_transparency']
