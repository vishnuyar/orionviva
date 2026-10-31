"""Indexed detached inputs to the existing source-reference account resolver."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import secrets
from types import MappingProxyType

from ..ledger.identity import (SourceAccountIdentity, identity_number_key,
    normalize_name, opaque_account_key, preferred_account_key)
from ..ledger.projection.accounts import resolve
from .store import AuthorityError, IntegrityError, canonical


@dataclass(frozen=True)
class AccountState:
    seen: bool
    kind: str
    number: str
    name: str
    institution: str
    currency: str
    names: tuple


@dataclass(frozen=True)
class ResolverState:
    _acct: object
    _captured: object
    _instrument_account_refs: object
    _document_account_aliases: object
    _aliases: object
    _alias_evidence: object


def detached_state(accounts, claims, captured, *, rulings=None):
    if rulings and any(rulings.values()):
        raise AuthorityError("identity rulings are outside this experimental format")
    ordered = {}
    for row in sorted(accounts, key=lambda row: row["creation_order"]):
        ordered[row["logical_key"]] = AccountState(True, row["kind"], row["number"], row["label"],
            row["institution"], row["currency"], tuple(json.loads(row["names"])))
    references = {}
    for claim in claims:
        references.setdefault(claim["logical_key"], []).append(MappingProxyType({
            "reference": claim["reference"], "doc_id": claim["doc_id"], "page": claim["page"],
            "identity_page_count": claim["identity_page_count"], "scope": claim["scope"]}))
    return ResolverState(MappingProxyType(ordered), frozenset(captured),
        MappingProxyType({key: tuple(values) for key, values in references.items()}),
        MappingProxyType({}), MappingProxyType({}), MappingProxyType({}))


def map_account(store, account, facts):
    existing = store._row("account_keys", "account_id=?", (account["account_id"],))
    if existing is not None:
        return existing
    preferred = preferred_account_key(facts.institution, facts.account_number, facts.account_ref)
    occupied = store._row("account_keys", "logical_key=?", (preferred,))
    logical = opaque_account_key(account["kind"]) if occupied is not None else preferred
    mapped = dict(account_id=account["account_id"], logical_key=logical, creation_order=store._revision)
    store._put("account_keys", mapped)
    for name in sorted({normalize_name(name) for name in facts.account_names if name.strip()}):
        store._put("holder_index", dict(account_id=account["account_id"], normalized_name=name))
    return mapped


def _eligible(claim, captured, *, historical=False):
    return (claim["scope"] == "account" and claim["doc_id"] in captured
        and SourceAccountIdentity(claim["reference"], claim["doc_id"], claim["page"],
            200 if historical else claim["identity_page_count"]).eligible())


def maintain_claim(store, claim):
    """Advance a distinct-reference view using only its prior real witnesses."""
    store._put("reference_claims", claim)
    captured = {claim["doc_id"]} if store._row("documents", "doc_id=?", (claim["doc_id"],)) else set()
    positive, historical = _eligible(claim, captured), _eligible(claim, captured, historical=True)
    if not positive and not historical:
        return
    prior = store._row("reference_views", "account_id=? AND reference=?", (claim["account_id"], claim["reference"]))
    current = dict(prior) if prior else dict(account_id=claim["account_id"], reference=claim["reference"], positive_claim_id="", history_claim_id="")
    for column, eligible in (("positive_claim_id", positive), ("history_claim_id", historical)):
        if not eligible:
            continue
        earlier = store._row("reference_claims", "claim_id=?", (current[column],)) if current[column] else None
        if earlier is None or (claim["claim_order"], claim["claim_id"]) < (earlier["claim_order"], earlier["claim_id"]):
            current[column] = claim["claim_id"]
    store._put("reference_views", current)


def source_claim(facts):
    return SourceAccountIdentity(facts.source_account_ref, facts.doc_id,
                                 facts.source_account_ref_page, facts.validated_source_page_count)


def _account_metadata(store, physical):
    account = store._row("accounts", "account_id=?", (physical,))
    mapping = store._row("account_keys", "account_id=?", (physical,))
    if account is None or mapping is None:
        raise IntegrityError("account identity mapping is missing")
    return {**account, **mapping}


def resolve_source(store, facts):
    claim = source_claim(facts)
    if not claim.eligible() or identity_number_key(facts.account_number, facts.account_ref):
        raise AuthorityError("source-reference identity is not eligible")
    owned_queries = store._queries is None
    if owned_queries:
        store._queries = []
    start_rows, start_queries = store.last_rows_read, len(store._queries)
    opcodes = [0]
    previous = getattr(store, "_progress_callback", None)
    def count():
        opcodes[0] += 1
        store.last_vm_steps += 1
        return 0
    store._db.set_progress_handler(count, 1)
    try:
        kind = __import__("viva.ingest.registry", fromlist=["account_kind_for"]).account_kind_for(facts.doc_type)
        selected = set()
        exact = store._read("SELECT v.account_id FROM reference_views v JOIN accounts a ON a.account_id=v.account_id WHERE v.reference=? AND v.positive_claim_id<>'' AND a.kind=?", (claim.reference, kind))
        selected.update(row[0] for row in exact)
        preferred = preferred_account_key(facts.institution, facts.account_number, facts.account_ref)
        target = store._row("account_keys", "logical_key=?", (preferred,))
        if target is not None:
            selected.add(target["account_id"])
        for name in sorted({normalize_name(name) for name in facts.account_names if name.strip()}):
            selected.update(row[0] for row in store._read("SELECT h.account_id FROM holder_index h JOIN accounts a ON a.account_id=h.account_id WHERE h.normalized_name=? AND a.kind=?", (name, kind)))
        accounts = [_account_metadata(store, physical) for physical in selected]
        accounts.sort(key=lambda row: row["creation_order"])
        claims, captured, distinct = [], {facts.doc_id}, 0
        for account in accounts:
            views = store._read("SELECT account_id,reference,positive_claim_id,history_claim_id FROM reference_views WHERE account_id=?", (account["account_id"],))
            distinct += len(views)
            for _physical, reference, positive, historical in views:
                representative = positive or historical
                if not representative:
                    raise IntegrityError("reference view has no real witness")
                row = store._row("reference_claims", "claim_id=?", (representative,))
                if row is None or row["account_id"] != account["account_id"] or row["reference"] != reference:
                    raise IntegrityError("reference witness differs from its view")
                if store._row("documents", "doc_id=?", (row["doc_id"],)) is not None:
                    captured.add(row["doc_id"])
                claims.append({**row, "logical_key": account["logical_key"]})
        state = detached_state(accounts, claims, captured)
        resolution = resolve(state, facts.institution, facts.account_number, facts.account_ref,
            facts.account_names, kind=kind, doc_id=facts.doc_id, currency=facts.currency, source_identity=claim)
        mapping = {account["logical_key"]: account["account_id"] for account in accounts}
        plans = {
            "reference": store._db.execute("EXPLAIN QUERY PLAN SELECT account_id FROM reference_views WHERE reference=?", (claim.reference,)).fetchall(),
            "holder": store._db.execute("EXPLAIN QUERY PLAN SELECT account_id FROM holder_index WHERE normalized_name=?", ("holder",)).fetchall(),
            "preferred": store._db.execute("EXPLAIN QUERY PLAN SELECT account_id FROM account_keys WHERE logical_key=?", (preferred,)).fetchall()}
        result = {"resolution": asdict(resolution), "logical_to_physical": mapping,
            "account_order": [account["logical_key"] for account in accounts],
            "metrics": {"vm_instructions": opcodes[0], "rows_read": store.last_rows_read-start_rows,
                "queries": list((store._queries or ())[start_queries:]), "plans": plans,
                "closure_accounts": len(accounts), "distinct_references": distinct, "witness_claims": len(claims)}}
        return result
    finally:
        store._db.set_progress_handler(previous, 100 if previous is not None else 0)
        if owned_queries:
            store._queries = None


def record_decision(store, facts, decision, physical, *, promoted=False):
    body = {**decision, "policy": "source_reference", "input": facts.to_dict(), "physical_account": physical, "promoted": promoted}
    store._put("identity_decisions", dict(decision_id=secrets.token_hex(16), doc_id=facts.doc_id,
        body=canonical(body), created_revision=store._revision))


def verify_compact_views(state):
    """Complete immutable-claim mechanism; never grants source authority."""
    captured = {row["doc_id"] for row in state["documents"].values()}
    # This independent complete-claim fold is verification-only. It precedes
    # admission validation so its mechanism can be adversarially tested alone;
    # passing it never grants unauthenticated claims financial authority.
    expected = {}
    for claim in sorted(state["reference_claims"].values(), key=lambda row: (row["claim_order"], row["claim_id"])):
        positive = (claim["scope"] == "account" and claim["doc_id"] in captured
            and SourceAccountIdentity(claim["reference"], claim["doc_id"], claim["page"], claim["identity_page_count"]).eligible())
        historical = (claim["scope"] == "account" and claim["doc_id"] in captured
            and SourceAccountIdentity(claim["reference"], claim["doc_id"], claim["page"], 200).eligible())
        if not positive and not historical:
            continue
        key = (claim["account_id"], claim["reference"])
        view = expected.setdefault(key, dict(account_id=claim["account_id"], reference=claim["reference"], positive_claim_id="", history_claim_id=""))
        if positive and not view["positive_claim_id"]:
            view["positive_claim_id"] = claim["claim_id"]
        if historical and not view["history_claim_id"]:
            view["history_claim_id"] = claim["claim_id"]
    if expected != state["reference_views"]:
        raise IntegrityError("compact references disagree with immutable claim semantics")


def verify_semantics(store, state):
    """Recompute admission, claims, candidate closure and resolution independently."""
    from ..ingest.statement import StatementFacts
    from ..ingest.registry import account_kind_for
    from .curated import derive
    captured = {row["doc_id"] for row in state["documents"].values()}
    verify_compact_views(state)
    facts_by_doc = {}
    for (doc_id,), admission in state["source_admissions"].items():
        receipt = state["receipts"].get((doc_id,))
        interpretation = state["interpretations"].get((doc_id,))
        if receipt is None:
            raise IntegrityError("source admission has no raw receipt")
        try:
            facts, occurrences = derive(store, receipt, json.loads(receipt["body"]))
        except (AuthorityError, ValueError, KeyError, TypeError, IndexError, StopIteration) as error:
            raise IntegrityError("source admission cannot be independently authenticated") from error
        actual_occurrences = {key: row for key, row in state["source_occurrences"].items() if key[0] == doc_id}
        if interpretation is not None and interpretation["facts_type"] == "balance":
            if facts is None or interpretation["facts"] != canonical(facts.to_dict()):
                raise IntegrityError("interpretation differs from immutable pinned receipt")
            if actual_occurrences != {(row["doc_id"], row["line_index"]): row for row in occurrences}:
                raise IntegrityError("source occurrences differ from immutable pinned receipt")
            facts_by_doc[doc_id] = facts
        elif actual_occurrences:
            raise IntegrityError("source occurrences have no admitted balance interpretation")
    accepted_revisions = {}
    for run in state["validation_runs"].values():
        if run["state"] == "accepted":
            accepted_revisions[run["doc_id"]] = run["revision"]
    periods = {row["doc_id"]: row for row in state["periods"].values()}
    for claim in sorted(state["reference_claims"].values(), key=lambda row: (row["claim_order"], row["claim_id"])):
        facts = facts_by_doc.get(claim["doc_id"])
        period = periods.get(claim["doc_id"])
        if facts is None or period is None:
            raise IntegrityError("reference claim has no independently admitted accepted source")
        required = dict(claim_id=facts.doc_id + ":account", account_id=period["account_id"],
            reference=facts.source_account_ref, doc_id=facts.doc_id, scope="account",
            page=facts.source_account_ref_page, identity_page_count=facts.validated_source_page_count,
            claim_order=accepted_revisions.get(facts.doc_id))
        if claim != required:
            raise IntegrityError("reference claim differs from its immutable admitted facts")
    for doc_id, period in periods.items():
        facts = facts_by_doc.get(doc_id)
        if facts is not None and facts.source_account_ref and (doc_id + ":account",) not in state["reference_claims"]:
            raise IntegrityError("accepted source reference claim is missing")
    accounts = []
    for account in state["accounts"].values():
        key = state["account_keys"].get((account["account_id"],))
        account_periods = [p for p in periods.values() if p["account_id"] == account["account_id"]]
        first = min(account_periods, key=lambda p: accepted_revisions[p["doc_id"]]) if account_periods else None
        if key is None or first is None or key["creation_order"] != accepted_revisions[first["doc_id"]]:
            raise IntegrityError("semantic account mapping is missing or out of order")
        first_interpretation = state["interpretations"][(first["doc_id"],)]
        first_facts = StatementFacts.from_dict(json.loads(first_interpretation["facts"]))
        immutable = dict(kind=account_kind_for(first_facts.doc_type), currency=first_facts.currency,
            number=first_facts.account_number, institution=first_facts.institution,
            label=first_facts.account_ref, names=canonical(first_facts.account_names))
        if any(account[field] != value for field, value in immutable.items()):
            raise IntegrityError("account metadata differs from first accepted interpretation")
        accounts.append({**account, **key})
    accounts.sort(key=lambda row: row["creation_order"])
    occupied = set()
    for account in accounts:
        preferred = preferred_account_key(account["institution"], account["number"], account["label"])
        if preferred not in occupied and account["logical_key"] != preferred:
            raise IntegrityError("logical account key differs from creation semantics")
        if preferred in occupied and not account["logical_key"].startswith("acct:" + account["kind"] + ":"):
            raise IntegrityError("occupied logical account key lacks kind-scoped replacement")
        occupied.add(account["logical_key"])
    expected_holders = {(row["account_id"], normalize_name(name)): dict(account_id=row["account_id"], normalized_name=normalize_name(name))
        for row in accounts for name in json.loads(row["names"]) if name.strip()}
    if expected_holders != state["holder_index"]:
        raise IntegrityError("holder index disagrees with immutable account metadata")
    for row in state["identity_decisions"].values():
        decision = json.loads(row["body"])
        facts = facts_by_doc.get(row["doc_id"])
        if facts is None or decision["input"] != facts.to_dict() or decision["policy"] != "source_reference":
            raise IntegrityError("identity input is not its immutable admitted interpretation")
        before = [account for account in accounts if account["creation_order"] < row["created_revision"]]
        keys = {account["account_id"]: account["logical_key"] for account in before}
        historical = [{**claim, "logical_key": keys[claim["account_id"]]} for claim in state["reference_claims"].values()
            if claim["claim_order"] < row["created_revision"] and claim["account_id"] in keys]
        complete = detached_state(before, historical, captured)
        kind = account_kind_for(facts.doc_type)
        expected_resolution = asdict(resolve(complete, facts.institution, facts.account_number, facts.account_ref,
            facts.account_names, kind=kind, doc_id=facts.doc_id,
            currency=facts.currency, source_identity=source_claim(facts)))
        preferred = preferred_account_key(facts.institution, facts.account_number, facts.account_ref)
        holders = {normalize_name(name) for name in facts.account_names if name.strip()}
        selected = set()
        for account in before:
            references = [claim for claim in historical if claim["account_id"] == account["account_id"]]
            positive_match = any(claim["reference"] == facts.source_account_ref
                and claim["scope"] == "account" and claim["doc_id"] in captured
                and SourceAccountIdentity(claim["reference"], claim["doc_id"], claim["page"], claim["identity_page_count"]).eligible()
                for claim in references)
            overlap = holders.intersection(normalize_name(name) for name in json.loads(account["names"]))
            if account["logical_key"] == preferred or (account["kind"] == kind and (positive_match or overlap)):
                selected.add(account["account_id"])
        closure = [account for account in before if account["account_id"] in selected]
        mapping = {account["logical_key"]: account["account_id"] for account in closure}
        if (canonical(expected_resolution) != canonical(decision["resolution"])
                or decision["logical_to_physical"] != mapping
                or decision["account_order"] != [account["logical_key"] for account in closure]):
            raise IntegrityError("identity decision disagrees with complete immutable context")
        period = periods.get(facts.doc_id)
        physical = decision["physical_account"]
        if decision.get("promoted") is True:
            if not physical or period is None or physical != period["account_id"] or accepted_revisions.get(facts.doc_id) != row["created_revision"]:
                raise IntegrityError("identity physical mapping differs from accepted source")
            if expected_resolution["verdict"] == "same" and mapping.get(expected_resolution["account_id"]) != physical:
                raise IntegrityError("identity chose a different existing physical account")
            if expected_resolution["verdict"] == "new" and not any(a["account_id"] == physical and a["creation_order"] == row["created_revision"] for a in accounts):
                raise IntegrityError("new identity does not create its mapped account")
        else:
            chosen = "" if expected_resolution["verdict"] == "ambiguous" else mapping.get(expected_resolution["account_id"], "")
            if physical != chosen or (period is not None and accepted_revisions.get(facts.doc_id) == row["created_revision"]):
                raise IntegrityError("held identity mapping differs from its resolver attempt")
