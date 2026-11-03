"""Payroll explains an admitted bank deposit without booking cash twice."""
from decimal import Decimal as D
import hashlib
import secrets

import pytest

from viva.ingest.paystub import Deduction, PayStubFacts
from viva.ingest.pipeline_models import ReadResult
from viva.ingest.registry import profile_for
from viva.sql_authority import SQLAuthority
from vivacore.verify.arithmetic import check_paystub_identity

from test_sql_authority_bank import ingest

pytestmark = pytest.mark.production_kdf


def test_payroll_decomposes_existing_sql_deposit_once(tmp_path, record_property):
    bank_source = b"synthetic bank payroll deposit"
    payroll_source = b"synthetic payroll source"
    payroll_id = hashlib.sha256(payroll_source).hexdigest()
    facts = PayStubFacts(
        doc_id=payroll_id, doc_type="pay_stub", doc_type_confidence=1.0,
        employer="SyntheticEmployer", currency="USD", pay_date="2026-01-15",
        period_start="2026-01-01", period_end="2026-01-15",
        gross=D("100"), net=D("80"),
        deductions=[Deduction("Synthetic tax", D("20"), "tax")],
        employee_names=["SyntheticPerson"], gross_page=1, net_page=1,
    )

    def reader(original, doc_id):
        assert original == payroll_source
        assert doc_id == payroll_id == facts.doc_id
        return ReadResult("pay_stub", 1.0, facts=facts)

    with SQLAuthority.create(
        tmp_path.resolve() / "authority", secrets.token_urlsafe(48),
        verification="complete",
    ) as store:
        bank = ingest(
            store, bank_source, opening="0", closing="80", movement="80",
            start="2026-01-15", end="2026-01-15", number="1234567",
            institution="SyntheticIssuer", currency="USD",
        )
        assert bank.status == "accepted"
        assert store.account(bank.account_id)["running_balance"] == "80"
        bank_transactions = store.transactions(bank.account_id)
        assert len(bank_transactions) == 1
        assert bank_transactions[0]["amount"] == "80"
        bank_legs = store.postings(bank.doc_id)
        assert [(leg["account"], leg["amount"], leg["grade"]) for leg in bank_legs] == [
            (bank.account_id, "80", "verified"),
            ("Income:Uncategorized", "-80", "unverified"),
        ]
        assert all(leg["provenance"]["doc_id"] == bank.doc_id for leg in bank_legs)
        assert store.original(bank.doc_id) == bank_source
        assert store.receipt(bank.doc_id)["raw_reading"]["facts"]["transactions"][0]["amount"] == "80"
        movements = store.movements()
        assert len(movements) == 1
        assert (movements[0].kind, movements[0].amount, movements[0].date,
                movements[0].currency, movements[0].linked) == (
            "depository", D("80"), "2026-01-15", "USD", False,
        )
        assert store.transfer_links() == []
        assert store.verify()["verified"]
        assert profile_for("pay_stub").identity == "paystub"
        assert check_paystub_identity(
            facts.gross, [deduction.amount for deduction in facts.deductions], facts.net,
        ).passed
        record_property("positive_complete_sql_bank_and_payroll_identity", "passed")

        result = store.ingest(payroll_source, reader, contract="synthetic-payroll-v1")
        assert result.status == "accepted"

        legs = store.payroll_postings(payroll_id)
        assert [(leg["account"], leg["amount"], leg["grade"]) for leg in legs] == [
            ("Income:Salary", "-100", "verified"),
            ("Income:Uncategorized", "80", "unverified"),
            ("Expenses:Tax", "20", "unverified"),
        ]
        assert sum((D(leg["amount"]) for leg in legs), D(0)) == 0
        assert all(leg["provenance"]["doc_id"] == payroll_id for leg in legs)
        assert store.account(bank.account_id)["running_balance"] == "80"
        assert store.transactions(bank.account_id) == bank_transactions
        assert store.postings(bank.doc_id) == bank_legs
        assert store.original(payroll_id) == payroll_source
        assert store.receipt(payroll_id)["contract"] == "synthetic-payroll-v1"
        assert store.verify()["verified"]

        assert store.resume(payroll_id).status == "accepted"
        assert store.payroll_postings(payroll_id) == legs

        def duplicate_reader(*_args):
            pytest.fail("duplicate payroll must use the retained reading")

        assert store.ingest(
            payroll_source, duplicate_reader, contract="synthetic-payroll-v1",
        ).status == "accepted"
        assert store.payroll_postings(payroll_id) == legs
        assert store.account(bank.account_id)["running_balance"] == "80"
        assert store.transactions(bank.account_id) == bank_transactions
        assert store.postings(bank.doc_id) == bank_legs
        assert store.verify()["verified"]


import json

from viva.sql_authority import AuthorityError, CuratedSource, IntegrityError
from viva.sql_authority import store as store_module
from viva.sql_authority.store import canonical
from viva.sql_authority import application_history as history
from viva.ingest.paystub import from_paystub_json


@pytest.fixture
def payroll_store(tmp_path):
    passphrase = secrets.token_urlsafe(48)
    with SQLAuthority.create(tmp_path.resolve() / "payroll", passphrase, verification="complete") as opened:
        opened._test_credentials = lambda: passphrase
        yield opened


def _payroll_facts(doc_id, *, gross="100", net="80", employer="SyntheticEmployer", deductions=None):
    return PayStubFacts(
        doc_id, "pay_stub", 1.0, employer, "USD", "2026-01-15", "2026-01-01", "2026-01-15",
        D(gross), D(net), [Deduction("Synthetic tax", D("20"), "tax")] if deductions is None else deductions,
        ["SyntheticPerson"], 1, 1,
    )


def _payroll(store, source=b"synthetic payroll source", *, change=None, **values):
    def reader(_original, doc_id):
        facts = _payroll_facts(doc_id, **values)
        if change:
            change(facts)
        return ReadResult("pay_stub", 1.0, facts=facts)
    return store.ingest(source, reader, contract="synthetic-payroll-v1")


def _deposit(store, source=b"synthetic bank deposit", *, number="1234567", day="2026-01-15"):
    return ingest(store, source, opening="0", closing="80", movement="80", start=day, end=day,
                  number=number, institution="SyntheticIssuer")


def test_payroll_awaits_late_deposit_without_reader_reexecution(payroll_store):
    store = payroll_store
    payroll = _payroll(store)
    assert (payroll.status, store.payroll_component(payroll.doc_id)["state"]) == ("pending", "awaiting_deposit")
    assert store.payroll_postings() == []
    bank = _deposit(store)
    assert bank.status == "accepted"
    assert store.item(payroll.doc_id)["state"] == "accepted"
    assert len(store.payroll_postings()) == 3
    assert store.account(bank.account_id)["running_balance"] == "80"
    assert len(store.transactions(bank.account_id)) == 1
    assert store.resume(payroll.doc_id).status == "accepted"
    assert len(store.payroll_decisions(payroll.doc_id)) == 1
    assert store.verify()["verified"]


def test_arithmetic_conflict_has_no_financial_effect(payroll_store):
    _deposit(payroll_store)
    payroll = _payroll(payroll_store, gross="101")
    assert payroll.status == "pending"
    assert payroll_store.payroll_component(payroll.doc_id)["state"] == "arithmetic_conflict"
    assert payroll_store.payroll_facts(payroll.doc_id)["gross"] == "101"
    assert payroll_store.payroll_postings() == []
    assert payroll_store.payroll_decisions(payroll.doc_id) == []
    assert payroll_store.verify()["verified"]


@pytest.mark.parametrize("field,value", [
    ("gross", 100.0), ("net", D("NaN")), ("gross", D("1E+100000")),
    ("gross_page", True), ("net_page", 201), ("currency", "US1"),
    ("pay_date", "2026-02-30"), ("doc_id", "0" * 64),
    ("employee_names", ("SyntheticPerson",)),
    ("deductions", [Deduction("Synthetic tax", D("-20"), "tax")]),
    ("deductions", [Deduction("Synthetic tax", D("20"), "invented")]),
])
def test_malformed_payroll_stays_unaccepted(payroll_store, field, value):
    _deposit(payroll_store)
    payroll = _payroll(payroll_store, change=lambda facts: setattr(facts, field, value))
    assert payroll.status == "pending"
    assert payroll_store.payroll_facts(payroll.doc_id) is None
    assert payroll_store.payroll_postings() == []
    assert payroll_store.receipt(payroll.doc_id)
    assert payroll_store.verify()["verified"]


def test_distinct_witnesses_share_effective_legs_and_preserve_provenance(payroll_store):
    _deposit(payroll_store)
    first = _payroll(payroll_store)
    duplicate = _payroll(payroll_store, b"distinct synthetic encoding", gross="100.00", net="80.000",
                         employer="  SYNTHETICEMPLOYER  ")
    assert duplicate.status == "accepted"
    assert payroll_store.payroll_component(duplicate.doc_id)["state"] == "duplicate"
    assert payroll_store.payroll_postings(duplicate.doc_id) == payroll_store.payroll_postings(first.doc_id)
    assert len(payroll_store.payroll_postings()) == 3
    assert all(leg["provenance"]["doc_id"] == first.doc_id for leg in payroll_store.payroll_postings())
    assert len(payroll_store.payroll_decisions(first.doc_id)) == 1
    assert payroll_store.verify()["verified"]


def test_deduction_multiplicity_has_distinct_meaning_and_preserves_retired_legs(payroll_store):
    _deposit(payroll_store)
    first = _payroll(payroll_store)
    before = payroll_store.payroll_postings(first.doc_id)
    other = _payroll(payroll_store, b"different synthetic deductions", deductions=[
        Deduction("Synthetic tax", D("10"), "tax"), Deduction("Synthetic tax", D("10"), "tax"),
    ])
    assert payroll_store.payroll_component(first.doc_id)["state"] == "ambiguous"
    assert payroll_store.payroll_component(other.doc_id)["state"] == "ambiguous"
    assert payroll_store.payroll_postings() == []
    assert [d["action"] for d in payroll_store.payroll_decisions(first.doc_id)] == ["activate", "deactivate"]
    eid = before[0]["explanation_id"]
    assert payroll_store._db.execute("SELECT COUNT(*) FROM payroll_legs WHERE explanation_id=?", (eid,)).fetchone() == (3,)
    assert payroll_store.verify()["verified"]


def test_two_equal_deposits_are_ambiguous_and_retire_prior_income(payroll_store):
    _deposit(payroll_store)
    payroll = _payroll(payroll_store)
    _deposit(payroll_store, b"second synthetic deposit", number="7654321")
    assert payroll_store.payroll_component(payroll.doc_id)["state"] == "ambiguous"
    assert payroll_store.payroll_postings(payroll.doc_id) == []
    assert [d["action"] for d in payroll_store.payroll_decisions(payroll.doc_id)] == ["activate", "deactivate"]
    assert payroll_store.verify()["verified"]


def test_manual_transfer_causally_retires_and_reactivates_payroll(payroll_store):
    from test_sql_authority_transfers import fixed_initial
    store = payroll_store
    fixed_initial(store)
    payroll = _payroll(store, gross="30", net="10",
                       change=lambda facts: setattr(facts, "pay_date", "2024-02-17"))
    assert payroll.status == "accepted"
    suggestion = store.transfer_suggestions()[0]
    a, b = suggestion["a"], suggestion["candidates"][0]
    assert store.confirm_transfer(a, b, today="2024-03-01")
    assert store.payroll_postings() == []
    assert store.unlink_transfer(a, b, today="2024-03-02")
    assert len(store.payroll_postings()) == 3
    decisions = store.payroll_decisions(payroll.doc_id)
    assert [d["action"] for d in decisions] == ["activate", "deactivate", "activate"]
    for decision in decisions[1:]:
        causes = decision["boundary"]["causes"]
        assert causes and all(c["table"] == "transfer_members" for c in causes)
        assert [(c["table"], c["key"]) for c in causes] == sorted({(c["table"], c["key"]) for c in causes})
    assert store.verify()["verified"]


def test_retirement_deduction_remains_unverified_without_destination_claim(payroll_store):
    _deposit(payroll_store)
    payroll = _payroll(payroll_store, deductions=[Deduction("Synthetic retirement", D("20"), "retirement")])
    legs = payroll_store.payroll_postings(payroll.doc_id)
    assert legs[2]["account"] == "Assets:Retirement"
    assert legs[2]["grade"] == "unverified"
    assert legs[2]["provenance"]["page"] is None
    assert payroll_store.verify()["counts"]["accounts"] == 1


def test_mutable_reader_values_and_returned_views_are_detached(payroll_store):
    _deposit(payroll_store)
    held = []
    def reader(_original, doc_id):
        facts = _payroll_facts(doc_id)
        held.append(facts)
        return ReadResult("pay_stub", 1.0, facts=facts)
    payroll = payroll_store.ingest(b"synthetic mutable reader", reader, contract="synthetic-payroll-v1")
    held[0].gross = D("900")
    held[0].employee_names.append("SyntheticOtherPerson")
    facts = payroll_store.payroll_facts(payroll.doc_id)
    facts["gross"] = "900"
    legs = payroll_store.payroll_postings(payroll.doc_id)
    legs[0]["amount"] = "-900"
    legs[0]["provenance"]["doc_id"] = "0" * 64
    assert payroll_store.payroll_facts(payroll.doc_id)["gross"] == "100"
    assert payroll_store.payroll_postings(payroll.doc_id)[0]["amount"] == "-100"
    assert payroll_store.verify()["verified"]


def test_native_rollback_keeps_staged_payroll_resumable_without_reader(payroll_store):
    _deposit(payroll_store)
    before = payroll_store.verify()["counts"]
    def fail(point):
        if point == "before_audit" and any(op["table"] == "payroll_decisions" for op in payroll_store._operations):
            raise RuntimeError("synthetic payroll rollback")
    payroll_store._fault = fail
    with pytest.raises(RuntimeError, match="synthetic payroll rollback"):
        _payroll(payroll_store)
    payroll_store._fault = lambda _point: None
    doc = hashlib.sha256(b"synthetic payroll source").hexdigest()
    assert payroll_store.payroll_postings() == []
    assert payroll_store.verify()["counts"]["transactions"] == before["transactions"]
    assert payroll_store.resume(doc).status == "accepted"
    assert len(payroll_store.payroll_postings()) == 3
    assert payroll_store.verify()["verified"]


def test_payroll_close_reopen_preserves_history_and_effective_legs(payroll_store):
    _deposit(payroll_store)
    payroll = _payroll(payroll_store)
    expected = payroll_store.payroll_postings()
    head = payroll_store.head
    with SQLAuthority.open(payroll_store.root, payroll_store._test_credentials(), verification="complete") as reopened:
        assert reopened.payroll_postings() == expected
        assert reopened.payroll_component(payroll.doc_id)["state"] == "accepted"
        assert reopened.verify(expected_head=head)["verified"]


def test_direct_financial_tamper_is_refused_before_canonical_answer(payroll_store):
    _deposit(payroll_store)
    _payroll(payroll_store)
    payroll_store._db.execute("UPDATE payroll_legs SET amount='-900' WHERE leg=0")
    with pytest.raises(IntegrityError):
        payroll_store.payroll_postings()


@pytest.mark.parametrize("corruption", ["balanced_wrong_income", "missing_leg", "missing_witness", "foreign_witness", "false_decision_boundary"])
def test_consistently_audited_payroll_wrong_state_is_independently_refused(payroll_store, monkeypatch, corruption):
    _deposit(payroll_store)
    foreign = _payroll(payroll_store, b"synthetic arithmetic-held witness", gross="101") if corruption == "foreign_witness" else None
    put = payroll_store._put
    def corrupt(table, row):
        row = dict(row)
        if corruption == "balanced_wrong_income" and table == "payroll_legs" and row["leg"] in {0, 1}:
            row["amount"] = "-101" if row["leg"] == 0 else "81"
        if corruption == "missing_leg" and table == "payroll_legs" and row["leg"] == 2:
            return
        if corruption == "missing_witness" and table == "payroll_witnesses":
            return
        if corruption == "foreign_witness" and table == "payroll_witnesses":
            row["doc_id"] = foreign.doc_id
        if corruption == "false_decision_boundary" and table == "payroll_decisions":
            body = json.loads(row["boundary"])
            body["causes"][0]["source_doc_id"] = "0" * 64
            row["boundary"] = canonical(body)
        return put(table, row)
    monkeypatch.setattr(payroll_store, "_put", corrupt)
    with pytest.raises(IntegrityError, match="payroll semantic mismatch"):
        _payroll(payroll_store)
    monkeypatch.setattr(payroll_store, "_put", put)
    with payroll_store._snapshot():
        export = payroll_store._export_current()
        reconstructed = payroll_store._reconstruct(export, None)
        assert reconstructed["payroll_explanations"]
    with pytest.raises(IntegrityError, match="payroll semantic mismatch"):
        payroll_store.verify()


def test_v3_prototype_refuses_before_sql_connection_without_mutating_bytes(tmp_path, monkeypatch):
    path = tmp_path.resolve() / "old-prototype"
    path.mkdir(mode=0o700)
    metadata = path / "authority.json"
    metadata.write_text(canonical({"format": "viva-sql-authority-prototype-v3", "crypto": {}, "check": {}}))
    metadata.chmod(0o600)
    before = metadata.read_bytes()
    monkeypatch.setattr(store_module, "_connect", lambda *_a, **_kw: pytest.fail("old prototype connected"))
    with pytest.raises(AuthorityError, match="unknown authority format"):
        SQLAuthority.open(path, "synthetic old format passphrase", verification="complete")
    assert metadata.read_bytes() == before
    assert set(p.name for p in path.iterdir()) == {"authority.json"}


@pytest.mark.parametrize("fmt,version,accepted", [
    ("viva-sql-authority-prototype-v3", 3, True),
    ("viva-sql-authority-prototype-v4", 4, True),
    ("viva-sql-authority-prototype-v3", 4, False),
    ("viva-sql-authority-prototype-v4", 3, False),
    ("viva-sql-authority-prototype-v4", True, False),
    ("viva-sql-authority-prototype-v4", "4", False),
    (None, 4, False),
    (["viva-sql-authority-prototype-v4"], 4, False),
])
def test_keyed_genesis_format_pairs_and_keyless_structure_limits(tmp_path, fmt, version, accepted):
    root_id, operation_id = secrets.token_hex(32), secrets.token_hex(32)
    keyed = history.History(tmp_path, root_id, secrets.token_bytes(32))
    issued = dict(version=1, root_id=root_id, operation_id=operation_id, kind="creation",
                  prior_terminal=None, prior_sql={"revision": 0, "head": "0" * 64}, capture=None)
    body = dict(metadata_sha256="1" * 64, sql_metadata_sha256="2" * 64,
                sql_format=fmt, sql_schema_version=version, schema_contract="3" * 64)
    sql_head = {"revision": 0, "head": "0" * 64}
    keyless = history.History(tmp_path, root_id)
    if accepted:
        data = keyed.make(issued, "genesis", body, sql_head)
        record = keyed.record(data)
        assert keyless.record(data) == record
        assert keyed.payload(record, previous=None)["body"] == body
    else:
        with pytest.raises(IntegrityError, match="invalid genesis representation"):
            keyed.make(issued, "genesis", body, sql_head)

        valid_body = dict(body, sql_format="viva-sql-authority-prototype-v4", sql_schema_version=4)
        valid_data = keyed.make(issued, "genesis", valid_body, sql_head)
        valid_record = keyed.record(valid_data)
        assert keyed.payload(valid_record, previous=None)["body"] == valid_body
        assert keyless.record(valid_data) == valid_record

        def sealed_genesis_with_body(value):
            content = {name: item for name, item in valid_record.items()
                       if name not in {"payload", "record_hash", "mac"}}
            content["payload"] = history.canonical(history.seal(
                keyed.keys["payload"], history.encoded({"issued": issued, "body": value}),
                aad=history.aad(content),
            ))
            content["record_hash"] = history.digest(history.encoded(content))
            content["mac"] = history.mac(
                keyed.keys["history"], [root_id, content["sequence"], content["record_hash"]],
            )
            return history.encoded(content)

        data = sealed_genesis_with_body(body)
        record = keyless.record(data)
        assert {name: item for name, item in record.items()
                if name not in {"payload", "record_hash", "mac"}} == {
                    name: item for name, item in valid_record.items()
                    if name not in {"payload", "record_hash", "mac"}}
        with pytest.raises(IntegrityError, match="invalid genesis representation"):
            keyed.record(data)
        with pytest.raises(IntegrityError, match="invalid genesis representation"):
            keyed.payload(record, previous=None)


@pytest.fixture(scope="module")
def payroll_curated_source():
    return CuratedSource.open()


def test_genuine_curated_payroll_retains_source_without_claiming_source_cells(payroll_store, payroll_curated_source):
    source = payroll_curated_source
    document = next(d for d in source.documents if d["doc_type"] == "pay_stub")
    original = source.original(document["sha256"])
    result = payroll_store.ingest_curated(original, source)
    assert result.status == "pending"
    assert payroll_store.payroll_component(result.doc_id)["state"] == "awaiting_deposit"
    assert payroll_store.payroll_facts(result.doc_id)["doc_id"] == result.doc_id
    assert payroll_store.original(result.doc_id) == original
    assert payroll_store.source_occurrences(result.doc_id) == []
    assert payroll_store.source_admission(result.doc_id)["document"] == document
    assert payroll_store.payroll_postings() == []
    assert payroll_store.verify()["verified"]


def test_engine_v1_refuses_before_sql_connection_under_actual_owned_context(tmp_path, monkeypatch):
    from viva.sql_authority import application
    passphrase = secrets.token_urlsafe(48)
    with SQLAuthority.create(tmp_path.resolve() / "new-application", passphrase,
                             verification="complete", application=True) as owner:
        with owner._root_lock.hold():
            path = owner.root / "sql" / "authority.json"
            metadata = history.decode(path.read_bytes())
            assert metadata["format"] == "viva-sql-application-engine-v3"
            metadata["format"] = "viva-sql-application-engine-v1"
            path.write_bytes(history.encoded(metadata))
            before = {p.relative_to(owner.root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                      for p in owner.root.rglob("*") if p.is_file()}
            monkeypatch.setattr(application, "_connect", lambda *_a, **_kw: pytest.fail("old engine connected"))
            with pytest.raises(IntegrityError, match="application child identity differs"):
                owner._open_engine(passphrase)
            assert before == {p.relative_to(owner.root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                              for p in owner.root.rglob("*") if p.is_file()}


@pytest.mark.parametrize("source_version", ["payroll-source-v1", "payroll-source-v2"])
def test_typed_payroll_source_extension_retains_explicit_versioned_wire(payroll_store, source_version):
    from viva.investment.payroll_extraction import HEADERS, DEDUCTION, parse
    from viva.retirement_funding.payroll_v2 import V2_HEADERS
    headers = V2_HEADERS if source_version == "payroll-source-v2" else HEADERS
    extension = {"schema": source_version, "headers": {name: None for name in headers},
                 "deductions": [{name: None for name in DEDUCTION}]}
    _deposit(payroll_store)
    payroll = _payroll(payroll_store, change=lambda facts: setattr(facts, "payroll_source", parse(extension)))
    assert payroll.status == "accepted"
    receipt = payroll_store.receipt(payroll.doc_id)
    assert receipt["raw_reading"]["facts"]["payroll_source"] == extension
    assert receipt["facts"]["payroll_source"] == extension
    assert payroll_store.payroll_facts(payroll.doc_id)["payroll_source"] == extension
    assert payroll_store.verify()["verified"]


def test_duplicate_employee_names_are_not_set_deduplicated(payroll_store):
    _deposit(payroll_store)
    first = _payroll(payroll_store)
    other = _payroll(payroll_store, b"synthetic multiplicity witness",
                     change=lambda facts: facts.employee_names.append("SyntheticPerson"))
    assert payroll_store.payroll_component(first.doc_id)["state"] == "ambiguous"
    assert payroll_store.payroll_component(other.doc_id)["state"] == "ambiguous"
    assert payroll_store.payroll_postings() == []
    assert payroll_store.verify()["verified"]


def test_unrelated_capture_does_not_scan_or_rewrite_all_payroll(payroll_store, monkeypatch):
    _deposit(payroll_store)
    payroll = _payroll(payroll_store)
    before = payroll_store.payroll_component(payroll.doc_id)
    decisions = payroll_store.payroll_decisions(payroll.doc_id)
    from viva.sql_authority import payroll as payroll_module
    affected = payroll_module._affected
    observed = []
    def trace(store, operations):
        queries = []
        read = store._read
        def observe(statement, parameters=()):
            queries.append(statement)
            return read(statement, parameters)
        store._read = observe
        try:
            selected = affected(store, operations)
            observed.append((selected, queries))
            return selected
        finally:
            store._read = read
    monkeypatch.setattr(payroll_module, "_affected", trace)
    payroll_store.ingest(b"synthetic unrelated unsupported source",
                        lambda *_args: ReadResult("unknown", 1.0), contract="synthetic-unknown-v1")
    assert observed and all(selected == [] and queries == [] for selected, queries in observed)
    assert payroll_store.payroll_component(payroll.doc_id) == before
    assert payroll_store.payroll_decisions(payroll.doc_id) == decisions
    assert payroll_store.verify()["verified"]


def test_retained_raw_payroll_response_must_agree_with_typed_facts(payroll_store):
    _deposit(payroll_store)
    raw = json.dumps({"doc_type": "pay_stub", "employer": "SyntheticEmployer", "gross_raw": "100",
                      "net_raw": "70", "pay_date_raw": "2026-01-15", "period_start_raw": "2026-01-01",
                      "period_end_raw": "2026-01-15", "deductions": [
                          {"label": "Synthetic tax", "category": "tax", "amount_raw": "30"}],
                      "employee_names": ["SyntheticPerson"], "gross_page": 1, "net_page": 1})
    def reader(_original, doc_id):
        parsed, error = from_paystub_json(raw, doc_id, "en-US", "USD")
        assert error is None and parsed.net == D("70")
        return ReadResult("pay_stub", 1.0, facts=_payroll_facts(doc_id), raw_text=raw, source_locale="en-US")
    result = payroll_store.ingest(b"synthetic inconsistent payroll response", reader, contract="synthetic-payroll-v1")
    assert result.status == "pending"
    assert payroll_store.receipt(result.doc_id)["raw_reading"]["raw_text"] == raw
    assert payroll_store.payroll_facts(result.doc_id) is None
    assert payroll_store.payroll_postings() == []
    assert payroll_store.verify()["verified"]


def test_forged_curated_owner_cannot_admit_payroll(payroll_store):
    with pytest.raises(AuthorityError, match="ownership"):
        payroll_store.ingest_curated(b"synthetic forged payroll member", object.__new__(CuratedSource))
    assert payroll_store.verify()["counts"]["documents"] == 0
    assert payroll_store.payroll_postings() == []


def test_false_historical_activation_is_refused_even_with_inactive_current_view(payroll_store):
    from viva.sql_authority.bank import settle
    store = payroll_store
    _deposit(store)
    payroll = _payroll(store)
    eid = store.payroll_component(payroll.doc_id)["explanation_id"]
    _deposit(store, b"second synthetic history deposit", number="7654321")
    assert store.payroll_postings() == []
    assert [d["action"] for d in store.payroll_decisions(payroll.doc_id)] == ["activate", "deactivate"]
    def interrupt(point):
        if point == "after_raw_receipt":
            raise RuntimeError("synthetic retained unsupported receipt")
    store._fault = interrupt
    source = b"synthetic unrelated historical cause"
    with pytest.raises(RuntimeError, match="retained unsupported receipt"):
        store.ingest(source, lambda *_a: ReadResult("unknown", 1.0), contract="synthetic-unknown-v1")
    store._fault = lambda _point: None
    doc = hashlib.sha256(source).hexdigest()
    with store._transaction():
        settle(store, doc)
        boundary = canonical({"version": 1, "causes": [
            {"table": "interpretations", "key": doc, "source_doc_id": doc}]})
        start = store._db.execute("SELECT MAX(ordinal) FROM payroll_decisions").fetchone()[0] + 1
        for offset, action in enumerate(("activate", "deactivate")):
            store._put("payroll_decisions", dict(ordinal=start + offset, explanation_id=eid,
                       action=action, revision=store._revision, boundary=boundary))
        active = store._row("payroll_active", "explanation_id=?", (eid,))
        store._put("payroll_active", dict(active, active=0, decision_ordinal=start + 1, revision=store._revision))
    with store._snapshot():
        export = store._export_current()
        reconstructed = store._reconstruct(export, None)
        assert reconstructed["payroll_active"][(eid,)]["active"] == 0
        assert len(reconstructed["payroll_decisions"]) == 4
    with pytest.raises(IntegrityError, match="payroll semantic mismatch"):
        store.verify()


@pytest.mark.parametrize("mismatch", ["economic_amounts", "integer_confidence", "extra_null_source"])
def test_typed_payroll_admission_holds_separate_facts_disagreeing_with_retained_wire(payroll_store, monkeypatch, mismatch):
    _deposit(payroll_store)
    put = payroll_store._put
    original_bodies = []
    def alter_separate_facts(table, row):
        if table == "receipts":
            original_bodies.append(row["body"])
            facts = json.loads(row["facts"])
            if mismatch == "economic_amounts":
                facts["gross"] = "101"
                facts["deductions"][0]["amount"] = "21"
            elif mismatch == "integer_confidence":
                facts["doc_type_confidence"] = 1
            else:
                facts["payroll_source"] = None
            row = dict(row, facts=canonical(facts))
        return put(table, row)
    monkeypatch.setattr(payroll_store, "_put", alter_separate_facts)
    payroll = _payroll(payroll_store)
    assert payroll.status == "pending"
    assert payroll_store.payroll_facts(payroll.doc_id) is None
    assert payroll_store.payroll_postings() == []
    assert payroll_store.payroll_decisions(payroll.doc_id) == []
    receipt = payroll_store._row("receipts", "doc_id=?", (payroll.doc_id,))
    assert receipt["body"] == original_bodies[0]
    body = json.loads(receipt["body"])
    assert body["raw_text"] == ""
    assert body["facts"]["gross"] == "100"
    assert body["facts"]["deductions"][0]["amount"] == "20"
    assert canonical(body["facts"]) != canonical(json.loads(receipt["facts"]))
    assert payroll_store.verify()["verified"]


def test_independent_verifier_refuses_consistent_finances_unbound_from_retained_payroll_wire(payroll_store, monkeypatch):
    from viva.sql_authority import reading as reading_module
    _deposit(payroll_store)
    put = payroll_store._put
    interpret = reading_module.interpret
    original_bodies = []
    def alter_separate_facts(table, row):
        if table == "receipts":
            original_bodies.append(row["body"])
            facts = json.loads(row["facts"])
            facts["gross"] = "101"
            facts["deductions"][0]["amount"] = "21"
            row = dict(row, facts=canonical(facts))
        return put(table, row)
    def feed_incorrect_wire_to_admission(store, receipt):
        body = json.loads(receipt["body"])
        body["facts"] = json.loads(receipt["facts"])
        return interpret(store, dict(receipt, body=canonical(body)))
    monkeypatch.setattr(payroll_store, "_put", alter_separate_facts)
    monkeypatch.setattr(reading_module, "interpret", feed_incorrect_wire_to_admission)
    with pytest.raises(IntegrityError, match="payroll semantic mismatch"):
        _payroll(payroll_store)
    doc = hashlib.sha256(b"synthetic payroll source").hexdigest()
    with payroll_store._snapshot():
        export = payroll_store._export_current()
        reconstructed = payroll_store._reconstruct(export, None)
        receipt = reconstructed["receipts"][(doc,)]
        assert receipt["body"] == original_bodies[0]
        assert json.loads(receipt["body"])["facts"]["gross"] == "100"
        assert json.loads(receipt["facts"])["gross"] == "101"
        assert json.loads(reconstructed["interpretations"][(doc,)]["facts"])["gross"] == "101"
        component = reconstructed["payroll_components"][(doc,)]
        assert component["state"] == "accepted"
        eid = component["explanation_id"]
        legs = [reconstructed["payroll_legs"][(eid, index)] for index in range(3)]
        assert [leg["amount"] for leg in legs] == ["-101", "80", "21"]
        assert sum((D(leg["amount"]) for leg in legs), D(0)) == 0
        assert reconstructed["payroll_active"][(eid,)]["active"] == 1
    with pytest.raises(IntegrityError, match="payroll semantic mismatch"):
        payroll_store.verify()
