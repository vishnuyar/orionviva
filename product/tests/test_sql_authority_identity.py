"""Real SQL candidate closure using detached actual resolver inputs."""
from dataclasses import asdict
from decimal import Decimal as D
import hashlib
import json
import secrets
import statistics
from types import SimpleNamespace

import pytest

from viva.sql_authority import SQLAuthority, AuthorityError
from viva.sql_authority.identity import detached_state, maintain_claim, resolve_source, source_claim
from viva.sql_authority.store import canonical
from viva.ledger.identity import normalize_name, preferred_account_key
from viva.ledger.projection.accounts import resolve
from test_sql_authority_bank import reading

pytestmark = pytest.mark.production_kdf


@pytest.fixture
def store(tmp_path):
    credential = secrets.token_urlsafe(32)
    with SQLAuthority.create(tmp_path.resolve()/"authority", credential) as opened:
        opened._test_credentials = lambda: credential
        yield opened


def seed_account(store, name, *, number="", kind="depository", holder="Owner", institution="Aurora Bank", logical=None):
    physical = "acct:sql:" + hashlib.sha256(name.encode()).hexdigest()[:32]
    row = dict(account_id=physical, identity=hashlib.sha256(name.encode()).hexdigest(), kind=kind,
        currency="USD", number=number, normalized_number=number if number.isdigit() and len(number)>4 else "",
        institution=institution, label=name, names=canonical([holder]), earliest_amount="100", earliest_date="2026-01-01",
        current_amount="100", current_date="2026-01-01")
    mapped = dict(account_id=physical, logical_key=logical or preferred_account_key(institution, number, name),
        creation_order=store._revision)
    store._put("accounts", row)
    store._put("account_keys", mapped)
    store._put("holder_index", dict(account_id=physical, normalized_name=normalize_name(holder)))
    return {**row, **mapped}


def seed_claim(store, account, token, index, *, page=1, bound=1, scope="account"):
    doc_id = hashlib.sha256(f"capture:{index}".encode()).hexdigest()
    store._put("documents", dict(doc_id=doc_id, byte_count=0, contract="synthetic-unit"))
    claim = dict(claim_id=doc_id+":account", account_id=account["account_id"], reference=token,
        doc_id=doc_id, scope=scope, page=page, identity_page_count=bound, claim_order=store._revision)
    maintain_claim(store, claim)
    return {**claim, "logical_key": account["logical_key"]}


def facts(*, label="New Product", token="SOURCE-A", holder="Owner", number=""):
    f = reading("f"*64, number=number, institution="Aurora Bank").facts
    f.account_ref = label
    f.account_names = [holder]
    f.source_account_ref = token
    f.source_account_ref_page = 1
    f.validated_source_page_count = 1
    return f


def oracle(accounts, claims, f):
    # Independent full-history conversion: no candidate adapter constructor.
    ordered = sorted(accounts,key=lambda row:row["creation_order"])
    states = {row["logical_key"]:SimpleNamespace(seen=True,kind=row["kind"],number=row["number"],
        name=row["label"],institution=row["institution"],currency=row["currency"],names=json.loads(row["names"]))
        for row in ordered}
    references = {}
    for claim in claims:
        references.setdefault(claim["logical_key"],[]).append({key:claim[key]
            for key in ("reference","doc_id","page","identity_page_count","scope")})
    state=SimpleNamespace(_acct=states,_captured={f.doc_id,*(claim["doc_id"] for claim in claims)},
        _instrument_account_refs=references,_document_account_aliases={},_aliases={},_alias_evidence={})
    return asdict(resolve(state, f.institution, f.account_number, f.account_ref, f.account_names,
        kind="depository", doc_id=f.doc_id, currency=f.currency, source_identity=source_claim(f)))


def test_positive_compact_witness_and_historical_contradiction(store):
    with store._transaction():
        account = seed_account(store, "Checking")
        a = seed_claim(store, account, "SOURCE-A", 1)
        # An old unmarked reference can contradict, but cannot positively match.
        b = seed_claim(store, account, "SOURCE-B", 2, bound=None)
    decision = resolve_source(store, facts())
    assert decision["resolution"] == oracle([account], [a,b], facts())
    assert decision["resolution"]["verdict"] == "ambiguous"
    assert oracle([account],[a],facts())["verdict"] == "same"
    assert decision["metrics"]["distinct_references"] == 2
    assert decision["metrics"]["witness_claims"] == 2
    assert resolve_source(store, facts(token="SOURCE-B"))["resolution"]["verdict"] != "same"


def test_numeric_holder_rival_and_occupied_crosskind_key_are_in_closure(store):
    f = facts(label="Other Product")
    with store._transaction():
        numeric = seed_account(store, "Numeric Product", number="123456789")
    with store._transaction():
        crosskind = seed_account(store, "Other Product", kind="liability")
    decision = resolve_source(store, f)
    assert decision["resolution"] == oracle([numeric, crosskind], [], f)
    assert decision["resolution"]["verdict"] == "ambiguous"
    assert decision["account_order"] == [numeric["logical_key"],crosskind["logical_key"]]
    # Omitting the numeric holder rival would incorrectly return new.
    assert oracle([crosskind], [], f)["verdict"] == "new"


def test_account_order_matches_complete_context_for_multiple_reference_matches(store):
    with store._transaction():
        first = seed_account(store, "First")
        a = seed_claim(store, first, "SOURCE-A", 1)
    with store._transaction():
        second = seed_account(store, "Second")
        b = seed_claim(store, second, "SOURCE-A", 2)
    decision = resolve_source(store, facts())
    assert decision["resolution"] == oracle([first,second],[a,b],facts())
    assert decision["resolution"]["candidates"] == (first["logical_key"],second["logical_key"])
    assert decision["account_order"] == [first["logical_key"],second["logical_key"]]
    reversed_accounts=[{**first,"creation_order":second["creation_order"]},{**second,"creation_order":first["creation_order"]}]
    assert oracle(reversed_accounts,[a,b],facts())["candidates"] != decision["resolution"]["candidates"]
    with SQLAuthority.open(store.root,store._test_credentials()) as reopened:
        assert resolve_source(reopened,facts())["resolution"] == decision["resolution"]


@pytest.mark.parametrize("token", ["1", "12", "123", "ALPHA-1"])
def test_existing_helper_source_eligibility_not_invented_digit_policy(store, token):
    f = facts(token=token)
    assert source_claim(f).eligible()
    decision = resolve_source(store, f)
    assert decision["resolution"]["verdict"] == "new"
    assert decision["metrics"]["vm_instructions"] > 0


def test_nonempty_rulings_cannot_be_silently_discarded():
    with pytest.raises(AuthorityError):
        detached_state([], [], set(), rulings={"alias": "account"})


def vm_work(store, operation):
    ticks = [0]
    def count():
        ticks[0] += 1
        return 0
    store._db.set_progress_handler(count,1)
    try:
        result = operation()
    finally:
        store._db.set_progress_handler(None,0)
    return ticks[0], result


def test_repeated_claim_and_unrelated_history_vm_work_is_bounded(store):
    # Seven fixed repetitions per size. This is a mechanism unit, not the
    # separately authorized actual-source or 100/1000/5000 qualification packet.
    with store._transaction():
        target = seed_account(store, "Checking")
        representative = seed_claim(store, target, "SOURCE-A", 0)
    measurements, bad_measurements, update_measurements = [], [], []
    complete_accounts, complete_claims = [target], [representative]
    for limit in (100,1000):
        start = 1 if limit == 100 else 100
        for index in range(start, limit):
            with store._transaction():
                complete_claims.append(seed_claim(store,target,"SOURCE-A",index))
                unrelated = seed_account(store, f"Unrelated {index}", holder=f"Different {index}")
                complete_accounts.append(unrelated)
                complete_claims.append(seed_claim(store,unrelated,f"UNRELATED-{index}",100000+index))
        samples = []
        for repetition in range(7):
            decision = resolve_source(store, facts())
            assert decision["resolution"] == oracle(complete_accounts,complete_claims,facts())
            metrics = decision["metrics"]
            assert metrics["closure_accounts"] == metrics["distinct_references"] == metrics["witness_claims"] == 1
            assert metrics["vm_instructions"] > 0
            assert all("SEARCH" in str(plan) and "INDEX" in str(plan) for plan in metrics["plans"].values())
            samples.append(metrics["vm_instructions"])
        measurements.append(samples)
        # Disposable old-history implementation: actually read all repeated
        # per-document claims instead of using compact witness views.
        bad = [vm_work(store, lambda: store._read(
            "SELECT reference,doc_id,page,identity_page_count,scope FROM reference_claims WHERE account_id=? ORDER BY claim_order,claim_id",
            (target["account_id"],)))[0] for _ in range(7)]
        bad_measurements.append(bad)
        updates = []
        for repetition in range(7):
            with store._transaction():
                doc_index = 200000 + limit + repetition
                work, claim = vm_work(store, lambda: seed_claim(store,target,"SOURCE-A",doc_index))
                complete_claims.append(claim)
                updates.append(work)
        update_measurements.append(updates)
    ratio = statistics.median(measurements[1])/statistics.median(measurements[0])
    bad_ratio = statistics.median(bad_measurements[1])/statistics.median(bad_measurements[0])
    update_ratio = statistics.median(update_measurements[1])/statistics.median(update_measurements[0])
    print({"identity_vm_samples_100_1000":measurements,"ratio":ratio,
        "old_history_vm_samples":bad_measurements,"counterfactual_ratio":bad_ratio,
        "view_update_vm_samples":update_measurements,"update_ratio":update_ratio,
        "sqlite":store._db.execute("SELECT sqlite_version()").fetchone()[0],
        "cipher":store._db.execute("PRAGMA cipher_version").fetchone()[0]})
    assert 0 < ratio <= 2
    assert bad_ratio > 2
    assert 0 < update_ratio <= 2


@pytest.mark.parametrize("changes", [
    {"account_ref":"Different printed product"},
    {"source_account_ref":"SOURCE-B", "account_ref":"Checking"},
    {"source_account_ref":"source-a"},
    {"source_account_ref":"SOURCE.A"},
    {"source_account_ref":" SOURCE-A "},
    {"institution":"Aurora Bank National Association"},
    {"institution":"Unrelated Issuer"},
    {"currency":"EUR"},
    {"account_names":["Different Person"]},
    {"account_names":[]},
])
def test_exact_resolver_matrix_against_full_context(store, changes):
    with store._transaction():
        account = seed_account(store,"Checking")
        claim = seed_claim(store,account,"SOURCE-A",1)
    f = facts()
    for name,value in changes.items():
        setattr(f,name,value)
    if source_claim(f).eligible():
        assert resolve_source(store,f)["resolution"] == oracle([account],[claim],f)
    else:
        with pytest.raises(AuthorityError):
            resolve_source(store,f)


@pytest.mark.parametrize("changes", [
    {"source_account_ref":""}, {"source_account_ref":"unknown"},
    {"source_account_ref":"1234"}, {"source_account_ref_page":None},
    {"validated_source_page_count":None}, {"source_account_ref_page":2},
    {"account_number":"123456789"},
])
def test_ineligible_reference_inputs_explicitly_refused(store, changes):
    f = facts()
    for name,value in changes.items():
        setattr(f,name,value)
    with pytest.raises(AuthorityError):
        resolve_source(store,f)


def test_multiple_holder_fallbacks_preserve_creation_order_after_reopen(store):
    with store._transaction():
        first=seed_account(store,"First Product")
    with store._transaction():
        second=seed_account(store,"Second Product")
    incoming=facts(label="")
    expected=oracle([first,second],[],incoming)
    decision=resolve_source(store,incoming)
    assert decision["resolution"]==expected and expected["candidate"]==first["logical_key"]
    reversed_accounts=[{**first,"creation_order":second["creation_order"]},{**second,"creation_order":first["creation_order"]}]
    assert oracle(reversed_accounts,[],incoming)["candidate"]==second["logical_key"]
    with SQLAuthority.open(store.root,store._test_credentials()) as reopened:
        assert resolve_source(reopened,incoming)["resolution"]==expected
