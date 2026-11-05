"""Opt-in seven-document SQL candidate; independent pinned-source money oracles.

Only four child dispatches belong to this module: shared build, completed reopen,
one owned-child cancellation after committed progress, and partial reopen.
"""
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import secrets
import stat
import sys
import time

import pytest

from viva.crypto import open_sealed
from viva.sample import resources, sql_instances
from viva.sql_authority import CuratedSource
from viva.sql_authority.application import ApplicationSQLAuthority


pytestmark = pytest.mark.production_kdf
VERSION = "sample-sql-candidate-v1"
SELECTION = "mixed-seven-v1"
MANIFEST = "97a92df2512beb4938c498d7f1b43d20d4e3800cc38e9ce83012dda252f46800"
READINGS = "dbd302f394113ecb66c730a6d4bb40636897ba40cb9c3e4345084fb215fe1eab"
SELECTED = (
    (0, "D0001", "pay_stub", "29d840b19e996e2ef4f2a335828c0491b747da4a8000de0ab91a1da2410340d1"),
    (6, "D0007", "brokerage_statement", "b690c92a04f89eb95afc49573eda2b2d0e0cdd58f58eaf4b41ba2251ac5db7e8"),
    (9, "D0010", "term_deposit_statement", "e272e318d157bac62290fa0a732d23091bf3151aeec640bba158956b085a55d7"),
    (11, "D0012", "mortgage_statement", "6d18a3baafd506c8d8125a5b62767640e9380ce46a62f432ff24dfad1d07fbdf"),
    (12, "D0013", "checking_statement", "c9edd43ad2c97de0c3e48b353d60e87a26ab6a73235088b6742c78d0967dc80b"),
    (155, "D0156", "property_tax_receipt", "e36133114c1ecc480e7fe09779d59ed88e5cdf1790e197855dcf1d89877abe34"),
    (310, "D0311", "refinance_settlement", "ff5aa9a6f440fb15682b2e913370c43e81ad9cd49582aeacd4773a2f03a5acdb"),
)
PAY, INVEST, CD, MORTGAGE, BANK, TAX, REFI = (row[3] for row in SELECTED)
INSTRUMENTS = (CD, MORTGAGE, TAX, REFI)
# Frozen from public parser_input/cells, independently of the candidate report.
BANK_SIGNED = ("-500.00", "-1000.00", "-1000.00", "-300.00", "-200.00", "12450.00", "-4395.55")
BANK_EVENTS = ("E000023", "E000028", "E000036", "E000026", "E000027", "E000001", "E000050")
POSITIONS = (("AAPL", "6.00000000", "730.20", "724.20"),
             ("MSFT", "3.00000000", "666.30", "663.30"),
             ("VTSAX", "2.00000000", "180.90", "180.90"))
ACTIVITY = (("contribution", "1000.00"), ("buy", "1207.00"), ("sell", "490.80"),
            ("buy", "1105.50"), ("sell", "446.20"), ("buy", "180.90"), ("dividend", "15.00"))
DEDUCTIONS = (("tax", "3483.33"), ("tax", "1100.00"),
              ("retirement", "1000.00"), ("insurance", "300.00"))
PAYROLL_LEGS = (("Income:Salary", "-18333.33"), ("Income:Uncategorized", "12450.00"),
                ("Expenses:Tax", "3483.33"), ("Expenses:Tax", "1100.00"),
                ("Assets:Retirement", "1000.00"), ("Expenses:Insurance", "300.00"))


@pytest.fixture(scope="module", autouse=True)
def owned_isolated_host():
    """Temporarily remove only the declared runner's proven disabled inputs."""
    names = {"VIVA_ENV_FILE", "ORIONVIVA_MODEL_ENV_FILE", "ORIONVIVA_MODEL_SETTINGS_FILE"}
    unknown = {name for name in os.environ if name.startswith("ORIONVIVA_MODEL_")} - names
    assert not unknown, "undeclared model configuration must not be cleared"
    present = names & set(os.environ)
    with pytest.MonkeyPatch.context() as patch:
        if present:
            assert present == names
            empty = Path(os.environ["VIVA_ENV_FILE"])
            assert empty.is_absolute() and empty.resolve() == empty and not empty.is_symlink()
            out = empty.parent
            packet_root = Path(__file__).resolve().parents[2] / "runs" / "sample-completion" / "continuation-20261105"
            relative = out.relative_to(packet_root)
            assert len(relative.parts) == 2 and relative.parts[1] in {"focus", "independent"}
            assert Path(os.environ["HOME"]) == out / "home"
            assert empty.name == "empty.env"
            assert os.environ["ORIONVIVA_MODEL_ENV_FILE"] == str(empty)
            missing = out / "unfunded-no-settings.json"
            assert os.environ["ORIONVIVA_MODEL_SETTINGS_FILE"] == str(missing)
            assert not missing.exists() and not missing.is_symlink()
            entry, directory = empty.lstat(), out.lstat()
            assert stat.S_ISREG(entry.st_mode) and entry.st_size == 0 and entry.st_nlink == 1
            assert stat.S_IMODE(entry.st_mode) == 0o600 and entry.st_uid == os.getuid()
            assert stat.S_ISDIR(directory.st_mode) and stat.S_IMODE(directory.st_mode) == 0o700
            assert directory.st_uid == os.getuid()
            for name in names:
                patch.delenv(name)
        # Unknown provider configuration remains present and must fail closed;
        # this checks names through the guard, never reads credential contents.
        sql_instances._source_host_guard()
        yield


def _bounded_api(function, *args):
    started = time.monotonic()
    try:
        return function(*args)
    finally:
        assert time.monotonic() - started < 120, "complete API path includes terminal write/fsync and return"


@pytest.fixture(scope="module")
def authentic_source():
    source = CuratedSource.open()
    root = Path(resources.__file__).parent.parent / "sample_data" / "five-year-life-v1"
    manifest_bytes, reading_bytes = (root / "manifest.json").read_bytes(), (root / "readings.json").read_bytes()
    assert hashlib.sha256(manifest_bytes).hexdigest() == MANIFEST
    assert hashlib.sha256(reading_bytes).hexdigest() == READINGS
    manifest = json.loads(manifest_bytes)["documents"]
    readings = {row["document_sha256"]: row for row in json.loads(reading_bytes)["readings"]}
    for index, identity, family, digest in SELECTED:
        assert (manifest[index]["id"], manifest[index]["sha256"]) == (identity, digest)
        assert readings[digest]["doc_type"] == family
        assert hashlib.sha256(source.original(digest)).hexdigest() == digest
    return source, readings


@pytest.fixture(scope="module")
def candidate(tmp_path_factory, authentic_source):
    parent = tmp_path_factory.mktemp("sql-candidate-parent").resolve()
    secret = secrets.token_urlsafe(32)  # RAM only; never a report/file/env field.
    with sql_instances._credential_scope(secret):
        result = _bounded_api(sql_instances.build_sql_candidate, parent / "output")
    return Path(result["instance"]), secret, parent


def _snapshot(owner):
    return {"head": owner.head, "terminal": owner.terminal,
            "receipts": {row[3]: owner.receipt(row[3]) for row in SELECTED},
            "originals": {row[3]: owner.original(row[3]) for row in SELECTED},
            "audit": owner.export_audit()}


def _assert_native_runtime_bindings(instance):
    """Inspect the actual two native aliases, not only a producer's claim."""
    version = f"{sys.version_info.major}.{sys.version_info.minor}"
    executable = Path(sys.executable).resolve(strict=True)
    base = executable.parent.parent
    assert executable.parent.name == "bin"
    assert (base.name, base.parent.name, base.parent.parent.name) == (version, "Versions", "Python.framework")
    raw_base = Path(sys.base_prefix)
    assert raw_base.is_absolute() and raw_base.resolve(strict=True) == base
    assert sql_instances._validate_framework_base(raw_base, base, executable) == base
    assert sql_instances._canonical_framework_base() == base
    standard = base / "lib" / ("python" + version)
    config = standard / ("config-" + version + "-darwin")
    aliases = (config / ("libpython" + version + ".a"),
               config / ("libpython" + version + ".dylib"))
    expected_target = base / "Python"
    assert expected_target.resolve(strict=True) == expected_target
    assert stat.S_ISREG(expected_target.lstat().st_mode) and not expected_target.is_symlink()
    expected_hash = hashlib.sha256(expected_target.read_bytes()).hexdigest()
    runtime = json.loads((instance / "candidate.json").read_bytes())["runtime"]
    assert runtime["framework_base"] == str(base)
    assert str(standard) in runtime["roots"]
    recorded = runtime["native_aliases"]
    assert len(recorded) == 2
    assert {row["alias_path"] for row in recorded} == {str(path) for path in aliases}
    for path in aliases:
        assert path.is_symlink() and path.resolve(strict=True) == expected_target
        actual = sql_instances._runtime_alias_binding(path, standard)
        assert set(actual) == {"alias_path", "raw_link", "resolved_target", "target_kind", "target_sha256"}
        assert actual == {
            "alias_path": str(path), "raw_link": os.readlink(path),
            "resolved_target": str(expected_target), "target_kind": "regular", "target_sha256": expected_hash,
        }
        assert sql_instances._validate_runtime_alias(actual, standard) == actual
        assert actual in recorded
    return standard, recorded


def _assert_finances(owner, public):
    # First verify the literal oracle's public inputs, then actual owned readers.
    bank_input = public[BANK]["envelope"]["parser_input"]
    assert bank_input["opening"]["amount_raw"] == "100000.00"
    assert bank_input["closing"]["amount_raw"] == "105054.45"
    cells = public[BANK]["envelope"]["source_cells"]
    assert tuple(cell["raw"] for cell in cells if cell["field"].endswith("amount_raw")) == BANK_SIGNED
    assert tuple(public[BANK]["envelope"]["source_event_ids"]) == BANK_EVENTS
    bank_item = owner.item(BANK)
    assert bank_item["state"] == "accepted"
    account = owner.account(bank_item["account_id"])
    assert Decimal(account["earliest_opening"]) == Decimal("100000.00")
    assert Decimal(account["running_balance"]) == Decimal("105054.45")
    transactions = owner.transactions(bank_item["account_id"])
    assert len(transactions) == 7
    assert [Decimal(row["amount"]) for row in transactions] == [Decimal(value) for value in BANK_SIGNED]
    assert sum(Decimal(row["amount"]) for row in transactions) == Decimal("5054.45")
    assert sum(1 for row in transactions if Decimal(row["amount"]) == Decimal("12450.00")) == 1
    assert len(owner.source_occurrences(BANK)) == 7

    pay_input = public[PAY]["envelope"]["parser_input"]
    assert (pay_input["gross_raw"], pay_input["net_raw"], pay_input["pay_date_raw"]) == ("18333.33", "12450.00", "2021-01-25")
    assert tuple((row["category"], row["amount_raw"]) for row in pay_input["deductions"]) == DEDUCTIONS
    assert public[PAY]["currency"] == public[BANK]["currency"] == "USD"
    facts = owner.payroll_facts(PAY)
    assert (Decimal(facts["gross"]), Decimal(facts["net"])) == (Decimal("18333.33"), Decimal("12450.00"))
    assert owner.item(PAY)["state"] == owner.payroll_component(PAY)["state"] == "accepted"
    assert sorted((row["account"], Decimal(row["amount"])) for row in owner.payroll_postings(PAY)) == sorted(
        (account, Decimal(amount)) for account, amount in PAYROLL_LEGS)
    assert len(owner.payroll_postings(PAY)) == 6
    assert sum(Decimal(row["amount"]) for row in owner.payroll_postings(PAY)) == 0
    assert [row["action"] for row in owner.payroll_decisions(PAY)] == ["activate"]

    investment_input = public[INVEST]["envelope"]["parser_input"]
    assert (investment_input["opening_cash_raw"], investment_input["cash_raw"], investment_input["total_raw"]) == (
        "100000.00", "99458.60", "101036.00")
    assert tuple((row["instrument"], row["units_raw"], row["market_value_raw"], row["cost_basis_raw"])
                 for row in investment_input["positions"]) == POSITIONS
    assert tuple((row["kind"], row["amount_raw"]) for row in investment_input["activity"]) == ACTIVITY
    item = owner.item(INVEST)
    assert item["state"] == "accepted"
    snapshot = owner.investment_snapshot(item["account_id"], as_of="2021-01-31")
    assert (Decimal(snapshot["cash"]), Decimal(snapshot["total"])) == (Decimal("99458.60"), Decimal("101036.00"))
    assert [(row["instrument"], Decimal(row["units"]), Decimal(row["market_value"]), Decimal(row["cost_basis"]))
            for row in snapshot["positions"]] == [(name, Decimal(units), Decimal(value), Decimal(cost))
                                                 for name, units, value, cost in POSITIONS]
    period = owner.investment_cash_period(INVEST)
    assert (Decimal(period["opening_cash"]), Decimal(period["closing_cash"]), period["state"]) == (
        Decimal("100000.00"), Decimal("99458.60"), "accepted")
    assert [(row["kind"], Decimal(row["amount"])) for row in owner.investment_activity(INVEST)] == [
        (kind, Decimal(amount)) for kind, amount in ACTIVITY]
    assert len(owner.source_occurrences(INVEST)) == 7


def _assert_payroll_transition(owner):
    # Read authenticated operations, not the adapter's self-reported admissions.
    export = owner.export_audit()
    events, checking_receipt_revision = [], None
    for revision, previous, envelope, _digest in export["records"]:
        data = open_sealed(owner._engine._audit_key, json.loads(envelope),
                           aad=json.dumps([revision, previous], sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode())
        for operation in json.loads(data)["operations"]:
            row = operation["row"]
            if operation["table"] == "receipts" and row["doc_id"] == BANK:
                checking_receipt_revision = revision
            if operation["table"] == "items" and row["doc_id"] == PAY:
                events.append((revision, row["state"], row["reason"]))
    pending = [revision for revision, state, reason in events if state == "pending" and reason == "awaiting_deposit"]
    accepted = [revision for revision, state, _reason in events if state == "accepted"]
    assert len(pending) == len(accepted) == 1
    assert pending[0] < checking_receipt_revision < accepted[0]


def test_sql_sample_backend_mixed_seven_conserves_source_and_finances(candidate, authentic_source):
    instance, secret, parent = candidate
    source, public = authentic_source
    assert instance.parent.name == "v1" and instance.parent.parent.name == "sql-sample-candidates"
    assert (instance.stat().st_mode & 0o777) == 0o700
    _assert_native_runtime_bindings(instance)
    with sql_instances._credential_scope(secret), sql_instances._open_owned_candidate(instance) as (owner, _owned):
        assert owner._engine.verification == "complete"
        actual = owner._engine._read("SELECT doc_id FROM receipts ORDER BY rowid")
        assert [row[0] for row in actual] == [row[3] for row in SELECTED]
        assert owner._engine._read("SELECT count(*) FROM documents") == [(7,)]
        for _index, identity, family, digest in SELECTED:
            receipt = owner.receipt(digest)
            assert owner.original(digest) == source.original(digest)
            assert receipt["raw_reading"]["facts"] is None
            assert json.loads(receipt["raw_reading"]["raw_text"]) == public[digest]["envelope"]
            assert receipt["raw_reading"]["doc_type"] == family
            assert public[digest]["document_id"] == identity
            assert owner._engine._row("receipts", "doc_id=?", (digest,))["facts"] == "null"
            if digest in INSTRUMENTS:
                assert owner.item(digest)["state"] == "unsupported"
                assert receipt["facts_type"] == "curated_instrument_retained_v1"
                assert receipt["reading"]["authority_context"]["financial_admission"] is False
                assert receipt["reading"]["authority_context"]["disposition"] == "typed_retained"
                assert owner.postings(digest) == [] and owner.source_occurrences(digest) == []
        _assert_finances(owner, public)
        _assert_payroll_transition(owner)
        assert owner.verify(expected_head=owner.head, expected_terminal=owner.terminal)["verified"]
    assert not list(parent.rglob("events.jsonl"))
    assert not list(parent.rglob("active.json")) and not list(parent.rglob("active-pointer.json"))


def test_sql_sample_backend_reopen_preserves_terminal_and_refuses_foreign_receipts(candidate, authentic_source, monkeypatch):
    instance, secret, _parent = candidate
    with sql_instances._credential_scope(secret), sql_instances._open_owned_candidate(instance) as (owner, _source):
        before = _snapshot(owner)
    with sql_instances._credential_scope(secret):
        result = _bounded_api(sql_instances.reopen_sql_candidate, instance)  # dispatch two
    assert Path(result["instance"]) == instance
    with sql_instances._credential_scope(secret), sql_instances._open_owned_candidate(instance) as (owner, _source):
        assert _snapshot(owner) == before
        _assert_finances(owner, authentic_source[1])
    candidate_path, report_path = instance / "candidate.json", instance / "report.json"
    candidate_bytes, report_bytes = candidate_path.read_bytes(), report_path.read_bytes()
    def forbidden_dispatch(*args, **kwargs):
        pytest.fail("invalid candidate metadata reached child dispatch")
    for mutation in ("version", "selection", "source", "runtime", "sql_head", "application_terminal"):
        value = json.loads(candidate_bytes)
        value[mutation] = ("foreign-profile" if mutation in ("version", "selection") else
                           {"foreign": True})
        candidate_path.write_text(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False))
        before_files = {str(path.relative_to(instance)): path.read_bytes() for path in instance.rglob("*") if path.is_file()}
        try:
            with monkeypatch.context() as patch:
                patch.setattr(sql_instances.subprocess, "Popen", forbidden_dispatch)
                with sql_instances._credential_scope(secret), pytest.raises(sql_instances.SQLSampleBackendError):
                    sql_instances.reopen_sql_candidate(instance)
            assert before_files == {str(path.relative_to(instance)): path.read_bytes()
                                    for path in instance.rglob("*") if path.is_file()}
        finally:
            candidate_path.write_bytes(candidate_bytes)
            report_path.write_bytes(report_bytes)


def test_sql_sample_backend_interruption_is_bounded_and_never_activates_ordinary_sample(tmp_path, authentic_source, candidate, monkeypatch):
    secret = secrets.token_urlsafe(32)
    standard, bindings = _assert_native_runtime_bindings(candidate[0])
    executable = Path(sys.executable).resolve(strict=True)
    base, raw_base = executable.parent.parent, Path(sys.base_prefix)
    # These are pure record counterfacts, so relative or unrelated interpreter
    # spellings never select or inspect a new filesystem root.
    base_counterfacts = (
        (Path("relative-base"), base, executable),
        (raw_base, Path("relative-resolved-base"), executable),
        (raw_base, tmp_path / "mismatched-framework", executable),
        (raw_base, base, Path("relative-executable")),
        (raw_base, base, tmp_path / "bin" / "foreign-python"),
    )
    for raw, resolved, actual_executable in base_counterfacts:
        with pytest.raises(sql_instances.SQLSampleBackendError):
            sql_instances._validate_framework_base(raw, resolved, actual_executable)
    # Closed metadata counterfacts never replace an installed runtime link or
    # follow an untrusted target. Actual binding capture also refuses unknown
    # slots before inspecting their plausible regular-file target.
    target = tmp_path / "untrusted-native-target"
    target.write_bytes(b"synthetic regular target outside accepted closure")
    unknown = tmp_path / "libpython-unknown.dylib"
    unknown.symlink_to(target)
    with pytest.raises(sql_instances.SQLSampleBackendError):
        sql_instances._runtime_alias_binding(unknown, standard)
    alias_counterfacts = (
        {**bindings[0], "alias_path": str(unknown)},
        {**bindings[0], "resolved_target": str(tmp_path / "missing-target"), "target_kind": "missing"},
        {**bindings[0], "resolved_target": str(tmp_path), "target_kind": "directory"},
        {**bindings[0], "target_kind": "nonregular"},
        {**bindings[0], "resolved_target": str(target)},
        {**bindings[0], "target_sha256": "not-a-digest"},
        {**bindings[0], "raw_link": ""},
    )
    for binding in alias_counterfacts:
        with pytest.raises(sql_instances.SQLSampleBackendError):
            sql_instances._validate_runtime_alias(binding, standard)
    request = {"operation": "build", "instance": str(tmp_path.resolve() / "candidate"),
               "selection": SELECTION, "version": VERSION}
    for invalid in ({**request, "operation": "activate"}, {**request, "selection": "full794"},
                    {**request, "version": "sample-instance-v1"}, {**request, "extra": True},
                    {**request, "instance": "x" * 4097}):
        with pytest.raises(sql_instances.SQLSampleBackendError):
            sql_instances._validate_request(invalid)
    with monkeypatch.context() as patch:
        patch.setattr(sys, "frozen", True, raising=False)
        with pytest.raises(sql_instances.SQLSampleBackendError):
            sql_instances._source_host_guard()
    with monkeypatch.context() as patch:
        patch.setenv("OPENAI_API_KEY", "synthetic-forbidden-provider-configuration")
        with pytest.raises(sql_instances.SQLSampleBackendError):
            sql_instances._source_host_guard()
    started = time.monotonic()
    progress_seen = []
    def cancel_after_committed_progress(instance):
        progress = Path(instance) / "progress.json"
        if not progress.exists():
            return False
        value = json.loads(progress.read_bytes())
        assert set(value) == {"version", "selection", "completed_ids"}
        assert value["version"] == VERSION and value["selection"] == SELECTION
        completed = value["completed_ids"]
        assert completed and completed == [row[1] for row in SELECTED[:len(completed)]]
        progress_seen.append(completed)
        return True
    with monkeypatch.context() as patch:
        assert sql_instances._WORKER_SECONDS == 90
        patch.setattr(sql_instances, "_cancel_requested", cancel_after_committed_progress)
        with sql_instances._credential_scope(secret), pytest.raises(sql_instances.SQLSampleBackendError) as cancelled:
            sql_instances.build_sql_candidate(tmp_path.resolve() / "interrupted-output")  # dispatch three
    assert time.monotonic() - started < 120
    assert progress_seen
    assert cancelled.value.result["status"] == "STOP_CANCELLED"
    assert cancelled.value.result["owned_group_absent"] is True
    partial = Path(cancelled.value.instance)
    assert partial.is_dir() and (partial / "candidate.json").is_file()
    # Recover actual durable application state independently before the fourth
    # dispatch. Poll races may retain more than one document; require a proper
    # nonempty manifest prefix rather than claiming an exact one-document stop.
    source = authentic_source[0]
    ApplicationSQLAuthority.recover(partial / "authority", secret, curated_source=source)
    with ApplicationSQLAuthority.open(partial / "authority", secret, curated_source=source) as recovered:
        prefix = [row[0] for row in recovered._engine._read("SELECT doc_id FROM receipts ORDER BY rowid")]
        assert 0 < len(prefix) < 7
        assert prefix == [row[3] for row in SELECTED[:len(prefix)]]
        # A raced final receipt may still await interpretation; conserve its raw
        # immutable row while allowing the separately derived view to complete.
        prefix_receipts = {digest: recovered._engine._row("receipts", "doc_id=?", (digest,)) for digest in prefix}
        prefix_originals = {digest: recovered.original(digest) for digest in prefix}
        assert recovered.verify()["verified"]
    with sql_instances._credential_scope(secret):
        completed = _bounded_api(sql_instances.reopen_sql_candidate, partial)  # dispatch four, exact selection retried idempotently
    assert Path(completed["instance"]) == partial
    with sql_instances._credential_scope(secret), sql_instances._open_owned_candidate(partial) as (owner, _source):
        assert owner._engine._read("SELECT count(*) FROM receipts") == [(7,)]
        assert owner._engine._read("SELECT count(DISTINCT doc_id) FROM receipts") == [(7,)]
        for digest in prefix:
            assert owner._engine._row("receipts", "doc_id=?", (digest,)) == prefix_receipts[digest]
            assert owner.original(digest) == prefix_originals[digest]
        _assert_finances(owner, authentic_source[1])
        _assert_payroll_transition(owner)
        assert owner.verify()["verified"]
    report = partial / "report.json"
    retained = report.read_bytes()
    report.write_bytes(b" " * (8 * 1024 * 1024 + 1))
    try:
        with monkeypatch.context() as patch:
            patch.setattr(sql_instances.subprocess, "Popen", lambda *args, **kwargs: pytest.fail("oversized report reached dispatch"))
            with sql_instances._credential_scope(secret), pytest.raises(sql_instances.SQLSampleBackendError):
                sql_instances.reopen_sql_candidate(partial)
    finally:
        report.write_bytes(retained)
    assert not list(tmp_path.rglob("events.jsonl"))
    assert not list(tmp_path.rglob("active.json")) and not list(tmp_path.rglob("active-pointer.json"))
    assert not list(tmp_path.rglob("sample-vaults"))
