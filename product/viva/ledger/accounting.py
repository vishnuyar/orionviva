"""Working financial statements over recorded amounts and effective meaning.

Classification never strengthens amount evidence. Totals remain in their source
currency, and compound payments with no recorded allocation remain disclosed.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal

from .events import SCOPE_MOVEMENT
from .networth import change_dates, net_worth, recorded_shares
from .postings import EXPENSE_UNCATEGORIZED, INCOME_UNCATEGORIZED
from .projection.movements import MIXED, SPENDING, money_effect

_ZERO = Decimal("0")


def _signature(line):
    return (getattr(line, "transaction_id", "") or (line.provenance.doc_id, line.date, line.description))


def _ruling(proj, movement, rulings):
    specific = rulings.get((SCOPE_MOVEMENT, movement.key))
    if specific:
        return specific
    for key in proj.merchant_keys_of(movement):
        found = rulings.get(("merchant", key))
        if found:
            return found
    return {}


def _evidence(proj, movement, ruling):
    category = proj.derived_category(movement) or {}
    by = (ruling.get("by") if ruling.get("legs") else
          category.get("by") if category.get("nature") else "default") or "default"
    return {"reason": movement.nature_reason, "by": by, "category_by": category.get("by", ""),
            "explanation": ruling.get("grounds") or ruling.get("reason", ""),
            "source_refs": ruling.get("source_refs", []),
            "provisional": (by not in ("human", "human_rule", "document")
                            and movement.nature_reason != "linked")}


def _row(proj, movement, root, amount, *, account="", category="",
         classification, grade):
    categories = proj.derived_category(movement) or {}
    evidence = classification
    return {"movement_key": movement.key, "date": movement.date,
            "account": account or movement.account, "currency": movement.currency,
            "root": root, "category": category or categories.get("category") or "Uncategorized",
            "subcategory": categories.get("subcategory") or "Uncategorized",
            "merchant": proj.merchant_key_of(movement) or "Unknown",
            "amount": str(amount), "provisional": evidence["provisional"],
            "amount_evidence": {"grade": grade,
                                "provenance": movement.provenance.to_dict()},
            "classification_evidence": evidence}


def _hierarchy(lines):
    leaves = {}
    for line in lines:
        key = tuple(line[k] for k in ("currency", "root", "category", "subcategory", "merchant"))
        row = leaves.setdefault(key, {**dict(zip(("currency", "root", "category", "subcategory", "merchant"), key)),
                                     "amount": _ZERO, "count": 0})
        row["amount"] += Decimal(line["amount"])
        row["count"] += 1
    flat = [{**row, "amount": str(row["amount"])} for _, row in sorted(leaves.items())]
    trees = {}
    for row in flat:
        current = trees.setdefault(row["currency"], {})
        for field in ("root", "category", "subcategory", "merchant"):
            node = current.setdefault(row[field], {"label": row[field], "amount": _ZERO, "children": {}})
            node["amount"] += Decimal(row["amount"])
            current = node["children"]
    def nodes(bucket):
        return [{"label": node["label"], "amount": str(node["amount"]),
                 "children": nodes(node["children"])} for _, node in sorted(bucket.items())]
    return flat, [{"currency": currency, "roots": nodes(bucket)}
                  for currency, bucket in sorted(trees.items())]


def financial_statements(proj, *, start: str = "", end: str = "", as_of: str = "") -> dict:
    """Inclusive period profit/loss and a dated balance sheet, with provenance.

    Named original income/expense postings (including salary decompositions and
    realized brokerage results) are counted once. Only unexplained ordinary
    movements receive inferred defaults; account openings never become income.
    """
    movements = proj.movements()
    grades = proj.movement_grades()
    rulings = {(row["scope"], row["subject"]): row for row in proj.rulings()}
    postings = (proj.accounting_postings() if hasattr(proj, "accounting_postings")
                else [(account, line) for account in proj.accounts()
                      for line in proj.transactions(account)])
    posting_accounts = defaultdict(list)
    for account, line in postings:
        posting_accounts[account].append(line)
    latest = max([m.date for m in movements] + change_dates(proj), default="")
    end = end or as_of or latest
    as_of = as_of or end
    for value in (start, end, as_of):
        if value:
            date.fromisoformat(value)
    if start and end and start > end:
        raise ValueError("report start must not follow report end")
    inside = lambda value: (not start or value >= start) and (not end or value <= end)
    lines, unresolved, allocations = [], [], []
    movement_signatures = {}
    real_occurrences = defaultdict(list)
    for account, ln in postings:
        real_occurrences[(account, ln.date, ln.description, ln.amount, ln.provenance.doc_id)].append(_signature(ln))
    for m in movements:
        key = (m.account, m.date, m.description, m.amount, m.provenance.doc_id)
        candidates = real_occurrences[key]
        movement_signatures[m.key] = candidates.pop(0) if candidates else _signature(m)
    interpreted_signatures = {movement_signatures[m.key] for m in movements
                              if _ruling(proj, m, rulings).get("legs")}
    named_signatures = set()
    decomposed_keys = set()
    allocation_currencies = {}
    allocation_deposits = {}
    unmatched_allocations = set()
    for ln in posting_accounts[INCOME_UNCATEGORIZED]:
        if ln.amount <= 0:
            continue
        matched_key = getattr(ln, "matched_movement_key", "")
        matched_currency = getattr(ln, "matched_currency", "")
        if matched_key:
            matches = [m for m in movements if m.key == matched_key
                       and m.kind == "depository" and m.amount == ln.amount
                       and m.key not in decomposed_keys
                       and m.currency == matched_currency]
        else:
            matches = [m for m in movements if m.kind == "depository"
                       and not m.linked and m.key not in decomposed_keys
                       and abs((date.fromisoformat(m.date) - date.fromisoformat(ln.date)).days) <= 10
                       and (not ln.currency or m.currency == ln.currency)
                       and m.amount == ln.amount]
        conflicting = {}
        if len(matches) == 1:
            candidate_ruling = _ruling(proj, matches[0], rulings)
            if (candidate_ruling.get("by") in ("human", "human_rule")
                    and candidate_ruling.get("legs")
                    and any(leg.get("major") != "income" for leg in candidate_ruling["legs"])):
                conflicting = candidate_ruling
        if len(matches) == 1 and not conflicting:
            decomposed_keys.add(matches[0].key)
            allocation_currencies[_signature(ln)] = matches[0].currency
            allocation_deposits[_signature(ln)] = matches[0]
        else:
            unmatched_allocations.add(_signature(ln))
            if not inside(ln.date):
                continue
            unresolved.append({"movement_key": matched_key, "date": ln.date,
                               "account": INCOME_UNCATEGORIZED, "currency": matched_currency or ln.currency or "?",
                               "root": "unresolved", "amount": str(ln.amount),
                               "reason": ("Payroll document disagrees with the user's recorded treatment"
                                          if conflicting else "Payroll allocation has no uniquely supported deposit link"),
                               "provisional": False,
                               "supporting_components": [{"account": account, "amount": str(component.amount),
                                                          "provenance": component.provenance.to_dict()}
                                                         for account, component in postings if _signature(component) == _signature(ln)],
                               "amount_evidence": {"grade": ln.grade, "provenance": ln.provenance.to_dict()},
                               "classification_evidence": {"by": "document", "reason": "conflicting_user_treatment" if conflicting else "unsupported_deposit_link",
                                                           "provisional": False, "source_refs": [ln.provenance.doc_id],
                                                           "existing_treatment": {key: conflicting.get(key, "") for key in ("by", "said", "legs", "source_refs")},
                                                           "related_sources": ([{"movement_key": matches[0].key,
                                                                                 "provenance": matches[0].provenance.to_dict()}] if conflicting else [])}})
    for account in posting_accounts:
        if account in (INCOME_UNCATEGORIZED, EXPENSE_UNCATEGORIZED):
            continue
        if account.startswith(("Income:", "Expenses:", "Assets:Investments", "Transfers:")):
            named_signatures.update(_signature(ln) for ln in posting_accounts[account])
    for m in movements:
        if not inside(m.date) or m.key in decomposed_keys:
            continue
        ruling = _ruling(proj, m, rulings)
        classification = _evidence(proj, m, ruling)
        row_args = {"classification": classification, "grade": grades.get(m.key, "")}
        shares = recorded_shares(ruling)
        if shares is not None:
            components = []
            for leg, share in shares:
                amount = abs(m.amount) * share
                major = leg.get("major", "")
                components.append({"major": major, "account": leg.get("account", ""),
                                   "amount": str(amount), "share": str(share)})
                if major not in ("expense", "income"):
                    continue
                root = "expenses" if major == "expense" else "income"
                signed = (-money_effect(m) if major == "expense" else money_effect(m)) * share
                category = (leg.get("account") or "").split(":")[1:]
                row = _row(proj, m, root, signed, account=leg.get("account", ""),
                           category=category[0] if category else "Uncategorized", **row_args)
                row["amount_evidence"]["allocation"] = {"share": str(share), "by": ruling.get("by"),
                                                         "source_refs": ruling.get("source_refs", [])}
                lines.append(row)
            allocation = _row(proj, m, "allocated", abs(m.amount), **row_args)
            allocation["components"] = components
            allocations.append(allocation)
            continue
        if m.nature == MIXED or len(ruling.get("legs") or []) > 1:
            row = _row(proj, m, "unresolved", abs(m.amount), **row_args)
            row["reason"] = "Component amounts are not recorded"
            unresolved.append(row)
            continue
        if movement_signatures[m.key] in named_signatures and not ruling.get("legs"):
            continue
        if m.nature != SPENDING:
            continue
        # A negative liability movement is a payment unless stronger recorded
        # accounting legs explicitly say it reverses an expense.
        legs = ruling.get("legs") or []
        major = legs[0].get("major") if len(legs) == 1 else ""
        if m.kind == "liability" and m.amount < 0 and major != "expense":
            continue
        effect = money_effect(m)
        root = "expenses" if major == "expense" or (not major and effect < 0) else "income"
        amount = -effect if root == "expenses" else effect
        lines.append(_row(proj, m, root, amount, **row_args))
    # Supporting documents can post allocations without a new cash movement.
    # The positive uncategorized income leg cancels the existing net-pay default.
    for account in posting_accounts:
        if not account.startswith(("Income:", "Expenses:")) or account == EXPENSE_UNCATEGORIZED:
            continue
        for ln in posting_accounts[account]:
            if (_signature(ln) in interpreted_signatures
                    or _signature(ln) in unmatched_allocations
                    or not inside(ln.date)
                    or (account == INCOME_UNCATEGORIZED and ln.amount <= 0)):
                continue
            if account == INCOME_UNCATEGORIZED and _signature(ln) in allocation_currencies:
                continue
            root = "income" if account.startswith("Income:") else "expenses"
            deposit = allocation_deposits.get(_signature(ln))
            related = ([{"movement_key": deposit.key, "date": deposit.date,
                         "amount": str(deposit.amount), "currency": deposit.currency,
                         "grade": grades.get(deposit.key, ""),
                         "provenance": deposit.provenance.to_dict()}] if deposit else [])
            lines.append({"movement_key": "", "date": ln.date, "account": account,
                          "currency": ln.currency or allocation_currencies.get(_signature(ln), "?"), "root": root,
                          "category": account.split(":", 1)[1], "subcategory": "Uncategorized",
                          "merchant": "Supporting document", "amount": str(-ln.amount if root == "income" else ln.amount),
                          "provisional": False,
                          "amount_evidence": {"grade": ln.grade, "provenance": ln.provenance.to_dict(), "related_sources": related},
                          "classification_evidence": {"reason": "recorded_posting", "by": "document", "provisional": False,
                                                      "source_refs": sorted({ref for ref in [ln.provenance.doc_id, deposit.provenance.doc_id if deposit else ""] if ref})}})
    totals = defaultdict(lambda: {key: _ZERO for key in ("income", "expenses", "net", "provisional_income", "provisional_expenses")})
    for line in lines:
        row, amount = totals[line["currency"]], Decimal(line["amount"])
        row[line["root"]] += amount
        if line["provisional"]:
            row["provisional_" + line["root"]] += amount
    for row in totals.values():
        row["net"] = row["income"] - row["expenses"]
    flat, tree = _hierarchy(lines)
    balance_sheet = net_worth(proj, as_of or None).to_dict()
    for line in balance_sheet["lines"]:
        aliases = proj.account_aliases()
        sources = [m for m in movements if m.date <= balance_sheet["as_of"]
                   and (m.ruling_account == line["account"] or any(
                       aliases.get(leg.get("account", ""), leg.get("account", "")) == line["account"]
                       for leg in _ruling(proj, m, rulings).get("legs", [])))]
        line["amount_evidence"] = ({"sources": [
            {"movement_key": m.key, "amount": str(m.amount),
             "grade": grades.get(m.key, ""), "provenance": m.provenance.to_dict()}
            for m in sources]} if sources else
            {"grade": line["grade"], "source_refs": [line["proves"]] if line["proves"] else []})
        line["classification_evidence"] = ({"sources": [
            _evidence(proj, m, _ruling(proj, m, rulings)) for m in sources],
            "provisional": any(_evidence(proj, m, _ruling(proj, m, rulings))["provisional"] for m in sources)}
            if sources else {"reason": "recorded_balance", "provisional": False})
    balance_sheet["missing"] = [{k: v for k, v in row.items() if k != "ask"} for row in balance_sheet["missing"]]
    balance_sheet["complete"] = balance_sheet["complete"] and not balance_sheet["skipped"]
    return {"basis": "personal_finance", "balance_sheet": balance_sheet,
            "profit_loss": {"start": start, "end": end, "by_currency": {currency: {k: str(v) for k, v in row.items()} for currency, row in sorted(totals.items())},
                            "lines": sorted(lines, key=lambda r: (r["date"], r["movement_key"], r["account"])),
                            "hierarchy": flat, "hierarchy_tree": tree,
                            "unresolved_components": unresolved, "component_allocations": allocations, "complete": not unresolved}}
