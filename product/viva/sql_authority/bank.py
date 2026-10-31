"""Indexed balance-family validation inside the authority write transaction."""
from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
import hashlib
import secrets

from vivacore.verify.arithmetic import check_balance_identity
from ..ingest.registry import BALANCE_IDENTITY, profile_for
from ..ingest.statement import StatementFacts, TxnFact
from ..ledger.identity import usable_full_number, conflicting_number_signals, canonical_institution
from ..ledger.postings import simple_transaction
from .store import canonical
from .schema import supported_amount


def amount_key(amount):
    value = Decimal(amount)
    if not value.is_finite():
        raise ValueError("non-finite financial amount")
    if value == 0:
        return "0"
    return format(value, "f").rstrip("0").rstrip(".") if "." in format(value, "f") else format(value, "f")


def _identity(facts, kind):
    number = usable_full_number(facts.account_number)
    if not number or not number.isascii() or not canonical_institution(facts.institution) or conflicting_number_signals(facts.account_number, facts.account_ref):
        return ""
    return hashlib.sha256(canonical([kind, canonical_institution(facts.institution), number]).encode()).hexdigest()


def _reason(store, doc_id, code, detail, *, account="", unsupported=False):
    store._put("findings", dict(doc_id=doc_id, code=code, detail=detail))
    state = "unsupported" if unsupported else "pending"
    store._put("validation_runs", dict(run_id=secrets.token_hex(16), doc_id=doc_id,
                                       state=state, revision=store._revision, detail=code))
    store._item(doc_id, state, code, account)


def valid_observations(facts):
    strings = (facts.doc_id, facts.doc_type, facts.account_ref, facts.currency,
               facts.opening_date, facts.closing_date, facts.account_number,
               facts.institution, facts.source_account_ref)
    if any(type(value) is not str or len(value.encode()) > 4096 for value in strings):
        return False
    if facts.validated_source_page_count is not None and (type(facts.validated_source_page_count) is not int or not 1 <= facts.validated_source_page_count <= 200):
        return False
    if type(facts.transactions) is not list or len(facts.transactions) > 10000:
        return False
    if any(type(line) is not TxnFact for line in facts.transactions):
        return False
    if type(facts.account_names) is not list or len(facts.account_names) > 100 or any(type(name) is not str or len(name.encode()) > 4096 for name in facts.account_names):
        return False
    if not facts.currency or not facts.currency.isascii() or not facts.currency.isalpha() or len(facts.currency) != 3:
        return False
    try:
        if date.fromisoformat(facts.opening_date).isoformat() != facts.opening_date or date.fromisoformat(facts.closing_date).isoformat() != facts.closing_date or facts.opening_date > facts.closing_date:
            return False
        amounts = [facts.opening_amount, facts.closing_amount]
        pages = [facts.opening_page, facts.closing_page, facts.source_account_ref_page]
        for line in facts.transactions:
            if any(type(value) is not str or len(value.encode()) > 4096 for value in
                   (line.date, line.description, line.source_doc_id, line.grade,
                    line.note, line.source_reference, line.counterparty_reference)):
                return False
            if date.fromisoformat(line.date).isoformat() != line.date or not facts.opening_date <= line.date <= facts.closing_date:
                return False
            if line.source_doc_id or line.grade or line.note:
                return False
            amounts.append(line.amount)
            if line.running_balance is not None:
                amounts.append(line.running_balance)
            pages.append(line.page)
        if any(not supported_amount(value) for value in amounts):
            return False
        if any(value is not None and (type(value) is not int or value < 1 or value > 200) for value in pages):
            return False
        if facts.validated_source_page_count is not None and any(value is not None and value > facts.validated_source_page_count for value in pages):
            return False
        return True
    except (ValueError, TypeError, InvalidOperation):
        return False


def bound_reading(reading, facts):
    from ..ingest.statement import from_model_json
    if not reading.get("source_locale"):
        return False
    parsed, error = from_model_json(reading["raw_text"], facts.doc_id, reading["source_locale"], facts.currency)
    if parsed is None or error:
        return False
    if parsed.doc_type == "unknown":
        parsed.doc_type = reading["doc_type"]
    expected, actual = facts.to_dict(), parsed.to_dict()
    for key in ("doc_type_confidence", "acquisition", "validated_source_page_count"):
        expected.pop(key, None)
        actual.pop(key, None)
    return expected == actual


def settle(store, doc_id):
    """Promote only the supported observations; unsupported rungs stay explicit."""
    row = store._row("receipts", "doc_id=?", (doc_id,))
    if row is None:
        return
    import json
    reading = json.loads(row["body"])
    from .reading import interpret
    import time
    interpretation_started = time.perf_counter()
    normalized = interpret(store, row)
    store.last_source_timings["interpretation_seconds"] = time.perf_counter()-interpretation_started
    if normalized["facts_type"] == "source_rejected":
        _reason(store, doc_id, "source_admission_requires_review", "The retained pinned source cannot be authenticated or interpreted.")
        return
    if normalized["facts_type"] == "contract_changed":
        _reason(store, doc_id, "extraction_contract_changed", "The read-time interpretation contract is missing or differs from the installed validator.")
        return
    if normalized["facts_type"] == "invalid_reading":
        _reason(store, doc_id, "invalid_reading", "Classification, raw response and locale require their declared text types.")
        return
    row = {**row, **normalized}
    if row["facts_type"] == "invalid_balance":
        _reason(store, doc_id, "unsupported_observation", "Typed financial observations require exact Decimal values and bounded provenance.")
        return
    if row["facts_type"] != "balance":
        _reason(store, doc_id, "unsupported_family", "No accepted financial rows were created.", unsupported=True)
        return
    facts = StatementFacts.from_dict(json.loads(row["facts"]))
    curated = store._row("source_admissions", "doc_id=?", (doc_id,)) is not None
    if not curated and reading.get("raw_text") and not bound_reading(reading, facts):
        _reason(store, doc_id, "extraction_binding", "Typed observations do not match the retained original extraction response.")
        return
    if facts.doc_id != doc_id or reading["doc_type"] != facts.doc_type or reading.get("error"):
        _reason(store, doc_id, "extraction_binding", "The reading does not bind this original and classification.")
        return
    profile = profile_for(facts.doc_type)
    context = json.loads(normalized["context"])
    from .reading import profile_descriptor
    from vivacore.verify import normalize
    if (context.get("implementation") != store._implementation_identity
            or context.get("normalization_rules_version") != normalize.RULES_VERSION
            or context.get("profile_descriptor") != profile_descriptor(profile)):
        _reason(store, doc_id, "extraction_contract_changed", "The retained profile differs from the installed deterministic validator.")
        return
    if profile is not None and (context.get("profile_version"), context.get("profile_identity"), context.get("profile_kind")) != (profile.profile_version, profile.identity, profile.account_kind):
        _reason(store, doc_id, "extraction_contract_changed", "The retained profile differs from the installed deterministic validator.")
        return
    if profile is None or profile.identity != BALANCE_IDENTITY or profile.account_kind not in {"depository", "liability"}:
        _reason(store, doc_id, "unsupported_family", "No accepted financial rows were created.", unsupported=True)
        return
    if not valid_observations(facts) or any(line.amount == 0 for line in facts.transactions):
        _reason(store, doc_id, "unsupported_observation", "Dates, amounts, provenance or zero movements require review.")
        return
    kind = profile.account_kind
    identity = _identity(facts, kind)
    store._put("staged_statements", dict(doc_id=doc_id, identity=identity, kind=kind,
        currency=facts.currency, opening_amount=str(facts.opening_amount), opening_date=facts.opening_date,
        closing_amount=str(facts.closing_amount), closing_date=facts.closing_date))
    for ordinal, line in enumerate(facts.transactions):
        store._put("staged_lines", dict(doc_id=doc_id, line_index=ordinal, date=line.date,
            amount=str(line.amount), description=line.description, page=line.page,
            running_balance=None if line.running_balance is None else str(line.running_balance)))
    if not check_balance_identity(facts.opening_amount, [line.amount for line in facts.transactions], facts.closing_amount).passed:
        _reason(store, doc_id, "arithmetic_requires_review", "The statement does not reconcile; correction and corroboration are not implemented.")
        return
    decision = None
    if identity:
        candidates = store._read("SELECT account_id,identity FROM accounts WHERE kind=? AND normalized_number=?", (kind, usable_full_number(facts.account_number)))
        if any(candidate_identity != identity for _account_id, candidate_identity in candidates):
            _reason(store, doc_id, "institution_requires_review", "The same full number has incompatible institution evidence.")
            return
        account = store._row("accounts", "identity=?", (identity,))
    else:
        from .identity import source_claim, resolve_source, record_decision
        from ..ledger.identity import identity_number_key
        if not curated or not source_claim(facts).eligible() or identity_number_key(facts.account_number, facts.account_ref):
            _reason(store, doc_id, "identity_requires_review", "This identity needs full-number evidence or an eligible bound source reference.")
            return
        decision = resolve_source(store, facts)
        resolution = decision["resolution"]
        if resolution["verdict"] == "ambiguous":
            record_decision(store, facts, decision, "")
            _reason(store, doc_id, "identity_requires_review", resolution["reason"])
            return
        physical = decision["logical_to_physical"].get(resolution["account_id"])
        account = store._row("accounts", "account_id=?", (physical,)) if physical else None
        identity = account["identity"] if account is not None else hashlib.sha256(secrets.token_bytes(32)).hexdigest()
    if account is not None:
        if account["currency"] != facts.currency:
            if decision is not None:
                record_decision(store, facts, decision, account["account_id"])
            _reason(store, doc_id, "currency_requires_review", "The account has accepted evidence in another currency.", account=account["account_id"])
            return
        prior = store._row("periods", "account_id=? AND period_end=?", (account["account_id"], facts.closing_date))
        if prior is not None:
            if decision is not None:
                record_decision(store, facts, decision, account["account_id"])
            if prior["closing_amount"] == str(facts.closing_amount):
                _reason(store, doc_id, "economic_duplicate", "This account period was already accepted; no duplicate postings.", account=account["account_id"])
            else:
                _reason(store, doc_id, "period_reissue", "This account period has conflicting closing evidence.", account=account["account_id"])
            return
        if facts.opening_amount == Decimal(account["current_amount"]) and facts.opening_date >= account["current_date"]:
            direction = "forward"
        elif facts.closing_amount == Decimal(account["earliest_amount"]) and facts.closing_date <= account["earliest_date"]:
            direction = "backward"
        else:
            if decision is not None:
                record_decision(store, facts, decision, account["account_id"])
            for name, value in (("forward", facts.opening_amount), ("backward", facts.closing_amount)):
                store._put("dependencies", dict(doc_id=doc_id, identity=identity, boundary_amount=amount_key(value), direction=name, active=1))
            _reason(store, doc_id, "chain_gap_or_overlap", "This period does not continue either accepted boundary.", account=account["account_id"])
            return
    else:
        direction = "new"
        account = dict(account_id="acct:sql:" + secrets.token_hex(16), identity=identity,
            kind=kind, currency=facts.currency, number=facts.account_number, normalized_number=usable_full_number(facts.account_number), institution=facts.institution,
            label=facts.account_ref, names=canonical(facts.account_names),
            earliest_amount=str(facts.opening_amount), earliest_date=facts.opening_date,
            current_amount=str(facts.closing_amount), current_date=facts.closing_date)
    if direction == "forward":
        account.update(current_amount=str(facts.closing_amount), current_date=facts.closing_date)
    elif direction == "backward":
        account.update(earliest_amount=str(facts.opening_amount), earliest_date=facts.opening_date)
    store._put("accounts", account)
    from .identity import map_account, maintain_claim, record_decision
    mapped = map_account(store, account, facts)
    if decision is not None:
        record_decision(store, facts, decision, account["account_id"], promoted=True)
    if curated and facts.source_account_ref:
        maintain_claim(store, dict(claim_id=doc_id + ":account", account_id=account["account_id"],
            reference=facts.source_account_ref, doc_id=doc_id, scope="account",
            page=facts.source_account_ref_page, identity_page_count=facts.validated_source_page_count,
            claim_order=store._revision))
    account_id = account["account_id"]
    store._put("periods", dict(account_id=account_id, period_end=facts.closing_date, doc_id=doc_id,
        opening_date=facts.opening_date, opening_amount=str(facts.opening_amount), closing_amount=str(facts.closing_amount)))
    for ordinal, line in enumerate(facts.transactions):
        event = simple_transaction(account_id, line.amount, line.description, line.date,
            provenance=line.provenance(doc_id), kind=kind, source_reference=line.source_reference,
            counterparty_reference=line.counterparty_reference)
        txn_id = hashlib.sha256(canonical([doc_id, ordinal]).encode()).hexdigest()
        store._put("transactions", dict(txn_id=txn_id, doc_id=doc_id, line_index=ordinal,
            account_id=account_id, date=line.date, description=line.description, page=line.page,
            amount=str(line.amount), source_reference=line.source_reference,
            counterparty_reference=line.counterparty_reference))
        for leg, posting in enumerate(event.body["postings"]):
            store._put("postings", dict(txn_id=txn_id, leg=leg, account_id=posting["account"],
                amount=posting["amount"], grade=posting["grade"], currency=facts.currency,
                doc_id=doc_id, page=line.page))
    for name, amount, dated, page in (("opening", facts.opening_amount, facts.opening_date, facts.opening_page),
                                     ("closing", facts.closing_amount, facts.closing_date, facts.closing_page)):
        store._put("balance_observations", dict(observation_id=doc_id + ":" + name,
            doc_id=doc_id, account_id=account_id, kind=name, date=dated, amount=str(amount),
            page=page, currency=facts.currency, grade="corroborated",
            event_asserted=int(name == "closing" or direction in {"new", "backward"})))
    store._put("validation_runs", dict(run_id=secrets.token_hex(16), doc_id=doc_id,
        state="accepted", revision=store._revision, detail="balance_identity"))
    for name in ("forward", "backward"):
        dependency = store._row("dependencies", "doc_id=? AND direction=?", (doc_id, name))
        if dependency is not None and dependency["active"]:
            store._put("dependencies", {**dependency, "active": 0})
    from .transfers import admit
    admit(store, account, mapped, facts)
    store._item(doc_id, "accepted", "", account_id)
    store._fault("after_financial_rows")
    pending = set()
    for name, boundary in (("forward", account["current_amount"]), ("backward", account["earliest_amount"])):
        matches = store._read("SELECT d.doc_id FROM dependencies d JOIN items i ON i.doc_id=d.doc_id WHERE d.identity=? AND d.boundary_amount=? AND d.direction=? AND d.active=1 AND i.state='pending' ORDER BY d.doc_id", (identity, amount_key(boundary), name))
        for (pending_id,) in matches:
            if pending_id != doc_id:
                pending.add(pending_id)
    return sorted(pending)
