"""Automatic curated appends compared with fresh full verification at each prefix."""
from contextlib import contextmanager
from dataclasses import FrozenInstanceError, fields, is_dataclass
import copy
from decimal import Decimal
import secrets

import pytest

from viva.crypto import seal
from viva.ingest.pipeline_models import ReadResult
from viva.sql_authority import AuthorityError, CuratedSource, IntegrityError, SQLAuthority
from viva.sql_authority import incremental
from viva.sql_authority import application_history as history
from viva.sql_authority.application import ApplicationSQLAuthority
from viva.sql_authority.application_io import RecoveryRequired
from viva.sql_authority.schema import KEYS, TABLES


pytestmark = pytest.mark.production_kdf
MIXED = (
    ("D0001", "pay_stub"), ("D0002", "credit_card_statement"),
    ("D0007", "brokerage_statement"), ("D0009", "401k_statement"),
    ("D0010", "term_deposit_statement"), ("D0012", "mortgage_statement"),
    ("D0013", "checking_statement"), ("D0156", "property_tax_receipt"),
    ("D0311", "refinance_settlement"),
)
INSTRUMENTS = {"term_deposit_statement", "mortgage_statement", "property_tax_receipt", "refinance_settlement"}


@pytest.fixture(scope="module")
def source():
    return CuratedSource.open()


def _document(source, family="checking_statement", index=0):
    return [row for row in source.documents if row["doc_type"] == family][index]


@contextmanager
def _owner(tmp_path, source, label):
    secret = secrets.token_urlsafe(32)
    with SQLAuthority.create(tmp_path.resolve() / label, secret, verification="complete", application=True) as owner:
        owner.attach_curated(source)
        assert owner.verify()["verified"]
        assert owner._incremental_checkpoint is not None
        yield owner, secret


def _state(owner):
    result = {}
    for table, columns in TABLES.items():
        rows = owner._engine._db.execute('SELECT ' + ','.join('"' + name + '"' for name in columns)
                                         + ' FROM "' + table + '"').fetchall()
        result[table] = {tuple(row[columns.index(key)] for key in KEYS[table]): dict(zip(columns, row)) for row in rows}
    return result


def _views(owner, documents):
    result = {"head": owner.head, "terminal": owner.terminal, "receipts": {}, "originals": {},
              "items": {}, "payroll": {}, "investment": {}, "accounts": {}, "transfers": {}}
    for document in documents:
        doc, family = document["sha256"], document["doc_type"]
        result["receipts"][doc] = owner.receipt(doc)
        result["originals"][doc] = owner.original(doc)
        item = owner.item(doc)
        result["items"][doc] = item
        if family == "pay_stub":
            result["payroll"][doc] = (owner.payroll_facts(doc), owner.payroll_component(doc),
                                      owner.payroll_decisions(doc), owner.payroll_postings(doc))
        if family in {"brokerage_statement", "401k_statement"}:
            result["investment"][doc] = (owner.investment_component(doc), owner.investment_cash_period(doc),
                                         owner.investment_activity(doc), owner.investment_postings(doc),
                                         owner.investment_history(doc))
        if item["account_id"]:
            account_id = item["account_id"]
            result["accounts"][account_id] = (owner.account(account_id), owner.transactions(account_id))
    result["transfers"] = (owner.transfer_links(), owner.transfer_suggestions(), owner.transfer_assertions(),
                            owner.transfer_decisions(), owner.transfer_inventory(), owner.transfer_bindings())
    return result


def _full_reference(owner, secret, source, documents):
    checkpoint = owner._incremental_checkpoint
    actual, actual_state = _views(owner, documents), _state(owner)
    # Open a DIFFERENT handle at the same physical root. Its mandatory full
    # bootstrap checks the same ciphertext, identifiers and authenticated chain;
    # it cannot reset the incremental handle's private semantic checkpoint.
    with SQLAuthority.open(owner.root, secret, verification="complete", application=True, curated_source=source) as reference:
        assert reference._engine.verification == "complete"
        exported = reference.export_audit()
        reconstructed = reference._engine._reconstruct(exported, reference.head)
        assert actual_state == reconstructed == _state(reference)
        assert actual == _views(reference, documents)
        assert owner.export_audit() == exported
    assert owner._incremental_checkpoint is checkpoint
    return actual, actual_state


def _counts(owner):
    return copy.deepcopy(owner._incremental_metrics)


def _assert_duplicate_noop(owner, documents, before):
    previous_views, previous_state, previous_export = before
    actual_views = _views(owner, documents)
    previous_terminal = previous_views["terminal"]
    terminal = actual_views["terminal"]
    assert {key: value for key, value in actual_views.items() if key != "terminal"} == {
        key: value for key, value in previous_views.items() if key != "terminal"}
    assert _state(owner) == previous_state and owner.export_audit() == previous_export
    assert terminal["sequence"] == previous_terminal["sequence"] + 1
    assert (terminal["sql_revision"], terminal["sql_head"]) == (
        previous_terminal["sql_revision"], previous_terminal["sql_head"])
    path = owner.root / "history" / f"{terminal['sequence']:020d}.json"
    record, payload = owner._history._record_and_payload(path.read_bytes(), previous=previous_terminal)
    assert record["kind"] == "noop" and history.terminal_of(record) == terminal
    assert payload["issued"]["kind"] == "transaction"
    assert payload["issued"]["prior_terminal"] == previous_terminal
    assert payload["body"] == {"intent_sha256": history.digest(history.encoded(payload["issued"]))}


def test_automatic_mixed_prefixes_equal_fresh_full_reference_without_rebootstrap(tmp_path, source, monkeypatch):
    from viva.sql_authority import investment_verify, payroll_verify, transfer_verify
    documents = []
    members = {row["id"]: row for row in source.documents}
    with _owner(tmp_path, source, "mixed-prefixes") as (owner, secret):
        full_calls = []
        actual_full = owner._engine._verify_current
        def full(*args, **kwargs):
            full_calls.append((owner._committed, owner._pending is not None))
            return actual_full(*args, **kwargs)
        current_advances = []
        actual_payroll, actual_investment, actual_transfer = payroll_verify._advance, investment_verify._advance, transfer_verify._advance
        def payroll_step(store, checkpoint, revision, operations, memo):
            if store is owner._engine:
                assert revision == store._db.execute("SELECT revision FROM control WHERE singleton=1").fetchone()[0]
                current_advances.append(("payroll", revision))
            return actual_payroll(store, checkpoint, revision, operations, memo)
        def investment_step(store, checkpoint, revision, operations):
            if store is owner._engine:
                assert revision == store._db.execute("SELECT revision FROM control WHERE singleton=1").fetchone()[0]
                current_advances.append(("investment", revision))
            return actual_investment(store, checkpoint, revision, operations)
        def transfer_step(store, checkpoint, state, operations, *, finish=True):
            if store is owner._engine:
                assert len(operations) <= 1, "automatic advancement may not replay earlier operation batches"
            return actual_transfer(store, checkpoint, state, operations, finish=finish)
        before_metrics = _counts(owner)
        with monkeypatch.context() as patch:
            patch.setattr(owner._engine, "_verify_current", full)
            patch.setattr(payroll_verify, "_advance", payroll_step)
            patch.setattr(investment_verify, "_advance", investment_step)
            patch.setattr(transfer_verify, "_advance", transfer_step)
            for identity, family in MIXED:
                document = members[identity]
                assert document["doc_type"] == family
                original = source.original(document["sha256"])
                result = owner.ingest_curated(original, source)
                documents.append(document)
                assert result.doc_id == document["sha256"]
                receipt = owner.receipt(result.doc_id)
                assert receipt["raw_reading"]["facts"] is None
                assert owner.original(result.doc_id) == original
                if family in INSTRUMENTS:
                    assert result.status == "unsupported" and result.reason == "unsupported_family"
                    assert receipt["facts_type"] == "curated_instrument_retained_v1"
                    assert receipt["reading"]["authority_context"]["financial_admission"] is False
                    assert owner.postings(result.doc_id) == [] and owner.source_occurrences(result.doc_id) == []
                elif family == "pay_stub":
                    assert result.status == "pending"
                else:
                    assert result.status == "accepted"
                _full_reference(owner, secret, source, documents)
                assert owner._pending_incremental_checkpoint is None
                assert not list((owner.root / "pending").iterdir())
            before_duplicate = (_views(owner, documents), _state(owner), owner.export_audit())
            duplicate = owner.ingest_curated(source.original(members["D0013"]["sha256"]), source)
            assert duplicate.status == "accepted"
            _assert_duplicate_noop(owner, documents, before_duplicate)
            _full_reference(owner, secret, source, documents)
        assert full_calls == [], "covered lock/custody/receipt/settlement boundaries may not replay historical finances"
        assert current_advances
        metrics = _counts(owner)
        assert metrics["full_bootstraps"] == before_metrics["full_bootstraps"]
        assert metrics["advances"] > before_metrics["advances"]
        assert metrics["custody_extensions"] - before_metrics["custody_extensions"] == 9
        assert metrics["lock_extensions"] - before_metrics["lock_extensions"] == 9
        pay, bank = members["D0001"]["sha256"], members["D0013"]["sha256"]
        assert owner.payroll_component(pay)["state"] == "accepted"
        assert [row["action"] for row in owner.payroll_decisions(pay)] == ["activate"]
        assert len(owner.payroll_postings(pay)) == 6
        assert sum(Decimal(row["amount"]) for row in owner.payroll_postings(pay)) == 0
        assert Decimal(owner.payroll_facts(pay)["gross"]) == Decimal("18333.33")
        account = owner.account(owner.item(bank)["account_id"])
        assert Decimal(account["running_balance"]) == Decimal("105054.45")
        assert [Decimal(row["amount"]) for row in owner.transactions(account["account_id"])] == [
            Decimal("-500"), Decimal("-1000"), Decimal("-1000"), Decimal("-300"),
            Decimal("-200"), Decimal("12450"), Decimal("-4395.55")]


def test_temporal_dependency_guards_and_actual_postcommit_fallback(tmp_path, source, monkeypatch):
    with _owner(tmp_path, source, "temporal-inputs") as (owner, secret):
        documents = [_document(source), _document(source, "pay_stub"), _document(source, "brokerage_statement")]
        for document in documents:
            owner.ingest_curated(source.original(document["sha256"]), source)
        _full_reference(owner, secret, source, documents)
        checkpoint, state = owner._incremental_checkpoint, _state(owner)
        assert incremental._dependencies_unchanged(checkpoint, state)
        bank, pay, investment = (row["sha256"] for row in documents)
        for change in ("negative_payroll", "native_facts", "old_doc_range", "account_identity",
                       "backdated_account", "backdated_claim", "consumed_membership", "period_owner", "snapshot_owner"):
            altered = copy.deepcopy(state)
            if change == "negative_payroll":
                altered["payroll_facts"][(bank,)] = {**next(iter(altered["payroll_facts"].values())), "doc_id": bank}
            elif change == "native_facts":
                altered["investment_facts"][(bank,)] = {**next(iter(altered["investment_facts"].values())), "doc_id": bank}
            elif change == "old_doc_range":
                row = next(row for row in altered["transactions"].values() if row["doc_id"] == bank)
                altered["transactions"][("f" * 64,)] = {**row, "txn_id": "f" * 64, "line_index": 999}
            elif change == "account_identity":
                altered["accounts"][(owner.item(bank)["account_id"],)]["identity"] = "synthetic foreign identity"
            elif change == "backdated_account":
                row = next(iter(altered["account_keys"].values()))
                altered["account_keys"][("e" * 64,)] = {**row, "account_id": "e" * 64, "logical_key": "synthetic-backdated", "creation_order": 1}
            elif change == "backdated_claim":
                row = next(iter(altered["reference_claims"].values()))
                altered["reference_claims"][("e" * 64,)] = {**row, "claim_id": "e" * 64, "claim_order": 1}
            elif change == "consumed_membership":
                altered["documents"].pop((bank,))
            elif change == "period_owner":
                next(iter(altered["periods"].values()))["doc_id"] = "f" * 64
            else:
                altered["investment_components"][(investment,)]["snapshot_state"] = "unavailable"
            assert not incremental._dependencies_unchanged(checkpoint, altered), change
        irrelevant = copy.deepcopy(state)
        irrelevant["investment_components"][(investment,)]["revision"] += 1000
        assert incremental._dependencies_unchanged(checkpoint, irrelevant)
        unrelated = copy.deepcopy(state)
        unrelated["documents"][("f" * 64,)] = {"doc_id": "f" * 64, "byte_count": 1, "contract": "synthetic-unrelated"}
        assert incremental._dependencies_unchanged(checkpoint, unrelated)
        actual_guard, actual_full = incremental._dependencies_unchanged, owner._engine._verify_current
        forced, full_calls = [], []
        def conservative_guard(proof, candidate):
            answer = actual_guard(proof, candidate)
            if owner._committed and not forced:
                forced.append(True)
                return False
            return answer
        def full(*args, **kwargs):
            full_calls.append(owner._committed)
            return actual_full(*args, **kwargs)
        before = _counts(owner)
        following = _document(source, index=1)
        with monkeypatch.context() as patch:
            patch.setattr(incremental, "_dependencies_unchanged", conservative_guard)
            patch.setattr(owner._engine, "_verify_current", full)
            assert owner.ingest_curated(source.original(following["sha256"]), source).status == "accepted"
        assert forced == [True] and full_calls and all(full_calls)
        assert sum(_counts(owner)["fallbacks"].values()) > sum(before["fallbacks"].values())
        _full_reference(owner, secret, source, documents + [following])


def test_checkpoint_is_private_immutable_and_readers_release_both_locks(tmp_path, source):
    with _owner(tmp_path, source, "private-checkpoint") as (owner, secret):
        document = _document(source)
        result = owner.ingest_curated(source.original(document["sha256"]), source)
        checkpoint = owner._incremental_checkpoint
        assert is_dataclass(checkpoint)
        with pytest.raises(FrozenInstanceError):
            setattr(checkpoint, fields(checkpoint)[0].name, None)
        def immutable(value):
            assert type(value) not in (dict, list, set, bytearray)
            if is_dataclass(value):
                for field in fields(value):
                    immutable(getattr(value, field.name))
            elif type(value) is tuple:
                for item in value:
                    immutable(item)
        immutable(checkpoint)
        returned = owner.receipt(result.doc_id)
        returned["reading"]["authority_context"]["synthetic_untrusted"] = True
        assert "synthetic_untrusted" not in owner.receipt(result.doc_id)["reading"]["authority_context"]
        with pytest.raises(TypeError):
            owner.ingest_curated(source.original(result.doc_id), source, incremental=True)
        before = owner.head
        assert owner._root_lock.owner is None and not owner._engine._db.in_transaction
        with SQLAuthority.open(owner.root, secret, verification="complete", application=True, curated_source=source) as other:
            with other._root_lock.hold():
                assert owner._root_lock.owner is None
                other._engine._db.execute("BEGIN IMMEDIATE")
                other._engine._db.execute("ROLLBACK")
        assert owner.head == before and owner._incremental_checkpoint is checkpoint
        unchanged = _state(owner)
        with pytest.raises(AuthorityError):
            owner.ingest_curated(source.original(result.doc_id), object.__new__(CuratedSource))
        assert _state(owner) == unchanged and owner._automatic_import is None
        owner._engine._curated_owner = None
        try:
            with pytest.raises(AuthorityError):
                owner.receipt(result.doc_id)
        finally:
            owner._engine._curated_owner = source
        assert owner._certificate is None and owner._pending_incremental_checkpoint is None
        assert _state(owner) == unchanged
        assert owner._incremental_checkpoint is None
        bootstraps = owner._incremental_metrics["full_bootstraps"]
        checked_receipt = owner.receipt(result.doc_id)
        assert checked_receipt["raw_reading"] == returned["raw_reading"]
        assert owner._incremental_checkpoint is not None and owner._incremental_checkpoint is not checkpoint
        assert owner._incremental_metrics["full_bootstraps"] == bootstraps + 1
        _full_reference(owner, secret, source, [document])


def test_external_extension_uses_fresh_bootstrap_and_unknown_sources_keep_full_path(tmp_path, source, monkeypatch):
    with _owner(tmp_path, source, "external-extension") as (owner, secret):
        first, following = _document(source), _document(source, index=1)
        owner.ingest_curated(source.original(first["sha256"]), source)
        checkpoint, full_calls = owner._incremental_checkpoint, []
        actual_full = owner._engine._verify_current
        def full(*args, **kwargs):
            full_calls.append(True)
            return actual_full(*args, **kwargs)
        with SQLAuthority.open(owner.root, secret, verification="complete", application=True, curated_source=source) as other:
            assert other.ingest_curated(source.original(following["sha256"]), source).status == "accepted"
        with monkeypatch.context() as patch:
            patch.setattr(owner._engine, "_verify_current", full)
            assert owner.item(following["sha256"])["state"] == "accepted"
        assert full_calls and owner._incremental_checkpoint is not checkpoint
        _full_reference(owner, secret, source, [first, following])
        full_calls.clear()
        with monkeypatch.context() as patch:
            patch.setattr(owner._engine, "_verify_current", full)
            outcome = owner.ingest(b"synthetic incremental unknown source", lambda *_args: ReadResult("unknown", 1.0),
                                   contract="synthetic-unknown-v1")
        assert outcome.status == "unsupported" and full_calls
        assert owner._automatic_import is None


def test_same_head_old_rows_and_historical_prefix_tampering_refuse(tmp_path, source):
    for mutation in ("financial_row", "old_audit", "old_commit", "old_history", "old_blob"):
        with _owner(tmp_path, source, mutation) as (owner, _secret):
            document = _document(source)
            result = owner.ingest_curated(source.original(document["sha256"]), source)
            head = owner.head
            if mutation == "financial_row":
                owner._engine._db.execute("UPDATE postings SET amount='999' WHERE doc_id=? AND account_id=?", (result.doc_id, result.account_id))
            elif mutation == "old_audit":
                owner._engine._db.execute("UPDATE audit SET envelope='{}' WHERE sequence=1")
            elif mutation == "old_commit":
                owner._engine._db.execute("UPDATE commits SET mac=? WHERE revision=1", ("0" * 64,))
            elif mutation == "old_history":
                path = sorted((owner.root / "history").iterdir())[0]
                record = history.decode(path.read_bytes());record["mac"] = "0" * 64
                path.write_bytes(history.encoded(record))
            else:
                path = owner.root / "sql" / "originals" / (result.doc_id + ".blob")
                path.write_bytes(history.encoded(seal(owner._engine._raw._key, source.original(result.doc_id), aad=result.doc_id.encode())))
            assert owner._engine._db.execute("SELECT revision,head FROM control WHERE singleton=1").fetchone() == (head["revision"], head["head"])
            with pytest.raises((AuthorityError, IntegrityError)):
                owner.account(result.account_id)
            assert owner._certificate is None and owner._pending_incremental_checkpoint is None


def test_automatic_custody_lock_and_directory_races_never_promote_unchecked_state(tmp_path, source, monkeypatch):
    from viva.ingest import raw_store
    for mutation in ("old_blob", "new_blob", "foreign_lock", "directory"):
        with _owner(tmp_path, source, "race-" + mutation) as (owner, _secret):
            first, following = _document(source), _document(source, index=1)
            accepted = owner.ingest_curated(source.original(first["sha256"]), source)
            prior = owner.terminal
            fired = []
            saved_directory = tmp_path / ("saved-originals-" + mutation)
            original_directory = owner.root / "sql" / "originals"
            actual_decrypt = raw_store.open_sealed
            def decrypt(key, envelope, *, aad):
                plaintext = actual_decrypt(key, envelope, aad=aad)
                if aad == following["sha256"].encode() and not fired:
                    fired.append(mutation)
                    if mutation in {"old_blob", "new_blob"}:
                        doc = accepted.doc_id if mutation == "old_blob" else following["sha256"]
                        (original_directory / (doc + ".blob")).write_bytes(history.encoded(seal(key, source.original(doc), aad=doc.encode())))
                    elif mutation == "foreign_lock":
                        (original_directory / (("f" * 64) + ".lock")).touch(mode=0o600)
                    else:
                        original_directory.rename(saved_directory)
                        original_directory.mkdir(mode=0o700)
                return plaintext
            full_calls = []
            actual_full = owner._engine._verify_current
            def full(*args, **kwargs):
                full_calls.append(True)
                return actual_full(*args, **kwargs)
            try:
                with monkeypatch.context() as patch:
                    patch.setattr(raw_store, "open_sealed", decrypt)
                    patch.setattr(owner._engine, "_verify_current", full)
                    if mutation == "foreign_lock":
                        try:
                            owner.ingest_curated(source.original(following["sha256"]), source)
                        except (AuthorityError, IntegrityError, OSError):
                            assert owner._certificate is None
                        else:
                            assert full_calls, "an unexpected member cannot receive incremental certification"
                            _full_reference(owner, _secret, source, [first, following])
                    else:
                        with pytest.raises((AuthorityError, IntegrityError, OSError)):
                            owner.ingest_curated(source.original(following["sha256"]), source)
                assert fired == [mutation]
                assert owner._pending_incremental_checkpoint is None
                if mutation != "foreign_lock":
                    assert owner._certificate is None
                assert prior["sequence"] <= history.decode((owner.root / "terminal.json").read_bytes())["sequence"]
            finally:
                if saved_directory.exists():
                    original_directory.rename(tmp_path / ("retained-raced-members-" + mutation))
                    saved_directory.rename(original_directory)


def test_actual_financial_delta_reaches_shared_checker_after_commit_and_keeps_pending(tmp_path, source, monkeypatch):
    from viva.sql_authority import identity, transfer_verify
    with _owner(tmp_path, source, "semantic-forgery") as (owner, secret):
        document = _document(source)
        put = owner._engine._put
        forged, checked = [], []
        actual_identity, actual_transfer = identity._advance_semantics, transfer_verify._advance
        def mutate(table, row):
            if table == "transfer_bindings" and row["doc_id"] == document["sha256"] and not forged:
                row = {**row, "amount": str(Decimal(row["amount"]) + 1)}
                forged.append((owner._incremental_checkpoint, owner._engine._revision))
            return put(table, row)
        def identity_check(*args, **kwargs):
            if forged:
                checked.append(("identity", owner._committed, owner._engine._db.in_transaction))
            return actual_identity(*args, **kwargs)
        def transfer_check(*args, **kwargs):
            if forged:
                checked.append(("transfer", owner._committed, owner._engine._db.in_transaction))
            return actual_transfer(*args, **kwargs)
        with monkeypatch.context() as patch:
            patch.setattr(owner._engine, "_put", mutate)
            patch.setattr(identity, "_advance_semantics", identity_check)
            patch.setattr(transfer_verify, "_advance", transfer_check)
            with pytest.raises(IntegrityError):
                owner.ingest_curated(source.original(document["sha256"]), source)
        assert len(forged) == 1 and checked and all(committed for _kind, committed, _snapshot in checked)
        assert not owner._engine._db.in_transaction
        revision = owner._engine._db.execute("SELECT revision FROM control WHERE singleton=1").fetchone()[0]
        assert revision == forged[0][1]
        assert owner._engine._db.execute("SELECT count(*) FROM transactions WHERE doc_id=?", (document["sha256"],)).fetchone()[0] == 7
        assert list((owner.root / "pending").iterdir())
        assert owner._pending_incremental_checkpoint is None
        assert owner._incremental_checkpoint is None or owner._incremental_checkpoint is forged[0][0]
        with pytest.raises(RecoveryRequired):
            owner.item(document["sha256"])
        root = owner.root
        retained = {str(path.relative_to(root)): path.read_bytes() for path in (root / "pending").rglob("*") if path.is_file()}
    with pytest.raises((IntegrityError, RecoveryRequired)):
        ApplicationSQLAuthority.recover(root, secret, curated_source=source)
    assert retained == {str(path.relative_to(root)): path.read_bytes() for path in (root / "pending").rglob("*") if path.is_file()}


def test_postcommit_lost_ack_recovers_exact_prefix_without_duplicate_effects(tmp_path, source, monkeypatch):
    with _owner(tmp_path, source, "lost-ack") as (owner, secret):
        document = _document(source)
        trusted, fired = owner.terminal, []
        def lose_ack(point):
            if point == "after_sql_commit" and any(op["table"] == "transactions" for op in owner._engine._operations):
                fired.append(point)
                raise RuntimeError("controlled incremental committed acknowledgement loss")
        with monkeypatch.context() as patch:
            patch.setattr(owner, "_fault", lose_ack)
            with pytest.raises(RuntimeError, match="controlled incremental committed acknowledgement loss"):
                owner.ingest_curated(source.original(document["sha256"]), source)
        assert fired == ["after_sql_commit"]
        assert owner._engine._db.execute("SELECT count(*) FROM transactions WHERE doc_id=?", (document["sha256"],)).fetchone() == (7,)
        assert owner._pending_incremental_checkpoint is None
        assert list((owner.root / "pending").iterdir())
        with pytest.raises(RecoveryRequired):
            owner.receipt(document["sha256"])
        root = owner.root
    result = ApplicationSQLAuthority.recover(root, secret, curated_source=source, expected_prefix=trusted)
    assert result["outcome"] == "committed"
    with SQLAuthority.open(root, secret, verification="complete", application=True, curated_source=source) as recovered:
        state = _state(recovered)
        assert len(state["transactions"]) == 7
        before = (_views(recovered, [document]), state, recovered.export_audit())
        assert recovered.ingest_curated(source.original(document["sha256"]), source).status == "accepted"
        _assert_duplicate_noop(recovered, [document], before)
        assert recovered.verify()["verified"]


def test_automatic_capture_faults_preserve_exact_custody_and_recover_once(tmp_path, source, monkeypatch):
    points = ("after_original_publication", "after_prepared_file", "after_prepared_intent",
              "after_history_publication", "after_terminal_publication", "after_intent_cleanup", "after_pending_cleanup")
    for point in points:
        with _owner(tmp_path, source, "capture-fault-" + point) as (owner, secret):
            first, following = _document(source), _document(source, index=1)
            seed = owner.ingest_curated(source.original(first["sha256"]), source)
            assert seed.status == "accepted"
            old_head, old_terminal, old_state = owner.head, owner.terminal, _state(owner)
            old_history = {path.name: path.read_bytes() for path in (owner.root / "history").iterdir()}
            captured, entered = [], []
            original_capture = owner.capture
            def automatic_capture(doc, original):
                assert incremental._capability(owner, doc)
                assert owner._certificate is not None and owner._incremental_checkpoint is not None
                entered.append(doc)
                return original_capture(doc, original)
            def interrupt(actual):
                if (actual == point and owner._pending is not None
                        and owner._pending[1]["kind"] == "capture" and not captured):
                    path, issued = owner._pending
                    assert issued["capture"]["doc_id"] == following["sha256"]
                    assert owner._automatic_import is not None
                    blob = owner.root / "sql" / "originals" / (following["sha256"] + ".blob")
                    prepared = path / "prepared-publication.json"
                    published = owner.root / "history" / f"{old_terminal['sequence'] + 1:020d}.json"
                    if actual == "after_original_publication":
                        assert not prepared.exists() and not published.exists()
                        publication = None
                    else:
                        publication = prepared.read_bytes() if prepared.exists() else published.read_bytes()
                    intent_path = path / "intent.json"
                    intent = intent_path.read_bytes() if intent_path.exists() else None
                    if actual == "after_original_publication":
                        assert intent is not None
                    if intent is not None:
                        outer, inner = owner._history.read_intent(intent)
                        assert inner["issued"] == issued
                        if actual == "after_original_publication":
                            assert outer["stage"] == "initial"
                    captured.append((blob.read_bytes(), publication, intent))
                    raise RuntimeError("controlled automatic custody interruption")
            with monkeypatch.context() as patch:
                patch.setattr(owner, "capture", automatic_capture)
                patch.setattr(owner, "_fault", interrupt)
                with pytest.raises(RuntimeError, match="controlled automatic custody interruption"):
                    owner.ingest_curated(source.original(following["sha256"]), source)
            assert entered == [following["sha256"]] and len(captured) == 1
            assert _state(owner) == old_state
            assert owner._engine._db.execute("SELECT revision,head FROM control WHERE singleton=1").fetchone() == (
                old_head["revision"], old_head["head"])
            assert owner._certificate is None and owner._incremental_checkpoint is None
            assert owner._pending_incremental_checkpoint is None and owner._automatic_import is None
            published_points = {"after_history_publication", "after_terminal_publication", "after_intent_cleanup", "after_pending_cleanup"}
            terminal_points = published_points - {"after_history_publication"}
            disk_terminal = history.decode((owner.root / "terminal.json").read_bytes())
            assert disk_terminal["sequence"] == old_terminal["sequence"] + (point in terminal_points)
            assert (disk_terminal["sql_revision"], disk_terminal["sql_head"]) == (
                old_head["revision"], old_head["head"])
            assert len(list((owner.root / "history").iterdir())) == len(old_history) + (point in published_points)
            assert bool(list((owner.root / "pending").iterdir())) == (point != "after_pending_cleanup")
            for name, data in old_history.items():
                assert (owner.root / "history" / name).read_bytes() == data
            root = owner.root
        intents = [member.read_bytes() for member in (root / "pending").glob("*/intent.json")]
        assert intents == ([] if captured[0][2] is None else [captured[0][2]])
        recovered = ApplicationSQLAuthority.recover(root, secret, curated_source=source, expected_prefix=old_terminal)
        assert recovered["outcome"] in {"custody", "cleanup_only", "already_ready"}
        assert not list((root / "pending").iterdir())
        with SQLAuthority.open(root, secret, verification="complete", application=True, curated_source=source) as reopened:
            assert reopened.head == old_head and _state(reopened) == old_state
            assert reopened.original(following["sha256"]) == source.original(following["sha256"])
            blob = root / "sql" / "originals" / (following["sha256"] + ".blob")
            assert blob.read_bytes() == captured[0][0]
            publication = root / "history" / f"{old_terminal['sequence'] + 1:020d}.json"
            recovered_publication = publication.read_bytes()
            if captured[0][1] is not None:
                assert recovered_publication == captured[0][1]
            record, payload = reopened._history._record_and_payload(recovered_publication, previous=old_terminal)
            assert record["kind"] == "custody"
            assert payload["body"] == {"doc_id": following["sha256"],
                                       "byte_count": len(source.original(following["sha256"])),
                                       "blob_sha256": history.digest(captured[0][0])}
            terminal, records, payloads = reopened._history.scan()
            custody = [payload["body"] for record, payload in zip(records, payloads)
                       if record["kind"] == "custody" and payload["body"]["doc_id"] == following["sha256"]]
            assert len(custody) == 1 and terminal["sequence"] == old_terminal["sequence"] + 1
            assert reopened.ingest_curated(source.original(following["sha256"]), source).status == "accepted"
            _full_reference(reopened, secret, source, [first, following])
            before = (_views(reopened, [first, following]), _state(reopened), reopened.export_audit())
            assert reopened.ingest_curated(source.original(following["sha256"]), source).status == "accepted"
            _assert_duplicate_noop(reopened, [first, following], before)
            assert blob.read_bytes() == captured[0][0] and publication.read_bytes() == recovered_publication
            _terminal, records, payloads = reopened._history.scan()
            assert sum(record["kind"] == "custody" and payload["body"].get("doc_id") == following["sha256"]
                       for record, payload in zip(records, payloads)) == 1
            assert reopened.verify()["verified"]


def test_committed_old_document_range_change_falls_back_at_semantic_boundary(tmp_path, source, monkeypatch):
    from viva.sql_authority import identity, transfer_verify
    with _owner(tmp_path, source, "committed-late-range") as (owner, secret):
        first, following = _document(source), _document(source, index=1)
        accepted = owner.ingest_curated(source.original(first["sha256"]), source)
        assert accepted.status == "accepted"
        old_rows = [row for row in _state(owner)["transactions"].values() if row["doc_id"] == accepted.doc_id]
        assert len(old_rows) == 7
        engine_fault = owner._engine._fault
        actual_guard, actual_full = incremental._dependencies_unchanged, owner._engine._verify_current
        actual_semantics = identity._advance_semantics
        actual_transfer = transfer_verify._advance
        changed, guards, fallback, semantic = [], [], [], []
        def add_late_row(point):
            if point == "before_audit" and not changed and any(
                    op["table"] == "transactions" and op["row"]["doc_id"] == following["sha256"]
                    for op in owner._engine._operations):
                extra = {**old_rows[0], "txn_id": secrets.token_hex(32), "line_index": 999,
                         "description": "Synthetic late old-document range counterfact"}
                owner._engine._put("transactions", extra)
                changed.append((extra, owner._engine._revision))
            return engine_fault(point)
        def guard(checkpoint, state):
            answer = actual_guard(checkpoint, state)
            if changed:
                assert owner._committed and not answer
                assert state["transactions"][(changed[0][0]["txn_id"],)] == changed[0][0]
                assert sum(row["doc_id"] == accepted.doc_id for row in state["transactions"].values()) == 8
                guards.append(False)
            return answer
        def full(*args, **kwargs):
            if changed:
                assert owner._committed and guards == [False]
                fallback.append(True)
            return actual_full(*args, **kwargs)
        def semantics(*args, **kwargs):
            if changed:
                assert owner._committed and fallback
                semantic.append("identity")
            return actual_semantics(*args, **kwargs)
        def transfer_semantics(*args, **kwargs):
            if changed:
                assert owner._committed and fallback
                semantic.append("transfer")
            return actual_transfer(*args, **kwargs)
        with monkeypatch.context() as patch:
            patch.setattr(owner._engine, "_fault", add_late_row)
            patch.setattr(incremental, "_dependencies_unchanged", guard)
            patch.setattr(owner._engine, "_verify_current", full)
            patch.setattr(identity, "_advance_semantics", semantics)
            patch.setattr(transfer_verify, "_advance", transfer_semantics)
            with pytest.raises(IntegrityError):
                owner.ingest_curated(source.original(following["sha256"]), source)
        assert len(changed) == 1 and guards == [False] and fallback == [True]
        assert "identity" in semantic and "transfer" in semantic
        assert not owner._engine._db.in_transaction
        assert owner._engine._db.execute("SELECT revision FROM control WHERE singleton=1").fetchone() == (changed[0][1],)
        assert owner._engine._db.execute("SELECT count(*) FROM transactions WHERE doc_id=?", (accepted.doc_id,)).fetchone() == (8,)
        assert owner._pending is not None and list((owner.root / "pending").iterdir())
        assert owner._certificate is None and owner._pending_incremental_checkpoint is None
        path, issued = owner._pending
        record, payload = owner._history._record_and_payload((path / "prepared-publication.json").read_bytes(), previous=issued["prior_terminal"])
        assert record["kind"] == "sql_commit" and record["sql_revision"] == changed[0][1]
        actual_audit = owner._engine._db.execute("SELECT sequence,previous_hash,envelope,record_hash FROM audit WHERE sequence=?", (changed[0][1],)).fetchone()
        assert payload["body"]["record"] == list(actual_audit)
        assert {key: value for key, value in history.decode((owner.root / "terminal.json").read_bytes()).items()
                if key in history.BOUNDARY} == issued["prior_terminal"]
        with pytest.raises(RecoveryRequired):
            owner.item(accepted.doc_id)
        root = owner.root
        pending = {str(member.relative_to(root)): member.read_bytes() for member in (root / "pending").rglob("*") if member.is_file()}
    recovery_semantics = []
    def checked_recovery(*args, **kwargs):
        recovery_semantics.append("identity")
        return actual_semantics(*args, **kwargs)
    def checked_recovery_transfer(*args, **kwargs):
        recovery_semantics.append("transfer")
        return actual_transfer(*args, **kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(identity, "_advance_semantics", checked_recovery)
        patch.setattr(transfer_verify, "_advance", checked_recovery_transfer)
        with pytest.raises(IntegrityError):
            ApplicationSQLAuthority.recover(root, secret, curated_source=source)
    assert "identity" in recovery_semantics and "transfer" in recovery_semantics
    assert pending == {str(member.relative_to(root)): member.read_bytes() for member in (root / "pending").rglob("*") if member.is_file()}


def test_checkpoint_decimal_keys_roundtrip_without_rounding_or_mutable_alias():
    from decimal import Inexact, Overflow, Rounded, Underflow, localcontext
    key = ("USD", Decimal("12345678901234567890.4500"), "source")
    zero_key = ("USD", Decimal("-0.000"), "destination")
    values = (Decimal("1.2300E+999999"), Decimal("1.2300E-999999"), Decimal("-0.00000"))
    original = {"admission_buckets": {key: ["synthetic-movement"], zero_key: []},
                "nested": [{"values": list(values)}]}
    expected_keys = {"source": key[1].as_tuple(), "destination": zero_key[1].as_tuple()}
    expected_values = [value.as_tuple() for value in values]
    with localcontext() as arithmetic:
        arithmetic.prec = 2
        arithmetic.Emax = 9
        arithmetic.Emin = -9
        for signal in (Inexact, Rounded, Overflow, Underflow):
            arithmetic.traps[signal] = True
        frozen = incremental._freeze(original)
        first, second = incremental._thaw(frozen), incremental._thaw(frozen)
        for restored in (first, second):
            assert type(restored) is dict and type(restored["admission_buckets"]) is dict
            assert {bucket[2]: bucket[1].as_tuple() for bucket in restored["admission_buckets"]} == expected_keys
            assert all(type(bucket[1]) is Decimal for bucket in restored["admission_buckets"])
            assert [value.as_tuple() for value in restored["nested"][0]["values"]] == expected_values
            assert all(type(value) is Decimal for value in restored["nested"][0]["values"])
        assert first == second == original
        assert first is not second and first["admission_buckets"][key] is not second["admission_buckets"][key]
        assert first["nested"][0]["values"] is not original["nested"][0]["values"]
        first["admission_buckets"][key].append("synthetic caller mutation")
        first["nested"][0]["values"][0] = Decimal("2")
        assert original["admission_buckets"][key] == second["admission_buckets"][key] == ["synthetic-movement"]
        assert incremental._thaw(frozen) == second
        original["admission_buckets"][key].append("synthetic later input mutation")
        original["nested"][0]["values"][1] = Decimal("3")
        assert incremental._thaw(frozen) == second
    for nonfinite in (Decimal("NaN"), Decimal("sNaN"), Decimal("Infinity"), Decimal("-Infinity")):
        for unsafe in (nonfinite, {"nested": [nonfinite]}, ("USD", nonfinite, "source")):
            with pytest.raises(IntegrityError):
                incremental._freeze(unsafe)
    class UnsupportedMutable:
        def __init__(self):
            self.values = []
    class ListSubstitute(list):
        pass
    for unsafe in (UnsupportedMutable(), ListSubstitute(["synthetic"]), bytearray(b"synthetic")):
        with pytest.raises(IntegrityError):
            incremental._freeze(unsafe)


def test_recovery_full_verification_phase_requires_real_lock_and_binding_ownership(tmp_path, source, monkeypatch):
    import threading
    with _owner(tmp_path, source, "owned-recovery-phase") as (owner, secret):
        document = _document(source)
        trusted, interrupted = owner.terminal, []
        def lose_ack(point):
            if point == "after_sql_commit" and any(op["table"] == "transactions" for op in owner._engine._operations):
                interrupted.append(point)
                raise RuntimeError("controlled owned-recovery acknowledgement loss")
        with monkeypatch.context() as patch:
            patch.setattr(owner, "_fault", lose_ack)
            with pytest.raises(RuntimeError, match="controlled owned-recovery acknowledgement loss"):
                owner.ingest_curated(source.original(document["sha256"]), source)
        assert interrupted == ["after_sql_commit"]
        root, engine = owner.root, owner._engine
        committed = engine._export_current()
        raw_receipt = engine._row("receipts", "doc_id=?", (document["sha256"],))
        blob = root / "sql" / "originals" / (document["sha256"] + ".blob")
        ciphertext = blob.read_bytes()
        prior_history = {path.name: path.read_bytes() for path in (root / "history").iterdir()}
        assert engine._db.execute("SELECT count(*) FROM transactions").fetchone() == (7,)
        assert list((root / "pending").iterdir())
        # Merely setting the private recovery marker must not admit ordinary
        # pending reads/writers; only the narrowly owned verifier phase may nest.
        with monkeypatch.context() as patch:
            patch.setattr(owner, "_recovering", True)
            for action in (lambda: owner.receipt(document["sha256"]),
                           lambda: owner.reject_transfer("synthetic pending reference", today="2021-02-01")):
                with pytest.raises(RecoveryRequired):
                    action()
        assert engine._export_current() == committed
    observed = []
    actual_original = SQLAuthority.original
    def original(store, doc_id):
        recovery_owner = store._application_binding.owner
        if recovery_owner._recovering is True and store._verifying:
            thread = threading.get_ident()
            observed.append((recovery_owner._depth > 0, recovery_owner._thread == thread,
                             recovery_owner._root_lock.owner == thread,
                             store._lock._is_owned(), store._db.in_transaction, store._verified_operation))
        return actual_original(store, doc_id)
    with monkeypatch.context() as patch:
        patch.setattr(SQLAuthority, "original", original)
        recovered = ApplicationSQLAuthority.recover(root, secret, curated_source=source, expected_prefix=trusted)
    assert recovered["outcome"] == "committed" and observed and all(all(flags) for flags in observed)
    assert not list((root / "pending").iterdir())
    assert blob.read_bytes() == ciphertext
    for name, data in prior_history.items():
        assert (root / "history" / name).read_bytes() == data
    with SQLAuthority.open(root, secret, verification="complete", application=True, curated_source=source) as owner:
        engine = owner._engine
        assert owner.export_audit() == committed
        assert engine._row("receipts", "doc_id=?", (document["sha256"],)) == raw_receipt
        assert len(_state(owner)["transactions"]) == 7
        assert owner.original(document["sha256"]) == source.original(document["sha256"])
        _full_reference(owner, secret, source, [document])
        before_duplicate = (_views(owner, [document]), _state(owner), owner.export_audit())
        assert owner.ingest_curated(source.original(document["sha256"]), source).status == "accepted"
        _assert_duplicate_noop(owner, [document], before_duplicate)

        def refused():
            phase = owner._depth, owner._thread
            with pytest.raises(AuthorityError):
                owner._recovery_full_verify()
            assert (owner._depth, owner._thread) == phase
        with owner._root_lock.hold(), engine._snapshot():
            refused()  # All real locks/transaction exist, but recovery is false.
        with monkeypatch.context() as recovery:
            recovery.setattr(owner, "_recovering", True)
            with owner._root_lock.hold(), engine._lock:
                assert not engine._db.in_transaction
                refused()
            with owner._root_lock.hold():
                assert not engine._lock._is_owned()
                engine._db.execute("BEGIN")
                try:
                    refused()  # Manual BEGIN alone never owns the SQL RLock.
                    assert engine._db.in_transaction
                finally:
                    engine._db.execute("ROLLBACK")
            with engine._lock:
                engine._db.execute("BEGIN")
                try:
                    refused()  # SQL ownership without the root lock is insufficient.
                finally:
                    engine._db.execute("ROLLBACK")
            with owner._root_lock.hold(), engine._snapshot():
                changes = ((owner, "_binding", object()),
                           (owner._binding, "pid", owner._binding.pid + 1),
                           (owner._binding, "root_identity", (0, 0)),
                           (engine, "_application_binding", None),
                           (engine, "root", owner.root / "synthetic-foreign-engine"),
                           (engine, "_verification", "indexed"),
                           (engine, "_verifying", True),
                           (owner, "_closed", True),
                           (owner._root_lock, "owner", -1))
                for target, name, value in changes:
                    with monkeypatch.context() as patch:
                        patch.setattr(target, name, value)
                        refused()
                    assert engine._db.in_transaction
                with monkeypatch.context() as patch:
                    patch.setattr(owner, "_depth", 2)
                    patch.setattr(owner, "_thread", -1)
                    refused()
                thread_errors = []
                def foreign_thread():
                    try:
                        owner._recovery_full_verify()
                    except AuthorityError:
                        thread_errors.append("refused before foreign native verification")
                thread = threading.Thread(target=foreign_thread)
                thread.start(); thread.join(timeout=5)
                assert not thread.is_alive() and thread_errors == ["refused before foreign native verification"]
                assert engine._db.in_transaction
                previous_phase = owner._depth, owner._thread
                for depth, previous_thread in ((0, None), (2, threading.get_ident())):
                    owner._depth, owner._thread = depth, previous_thread
                    def fail_full():
                        assert (owner._depth, owner._thread) == (depth + 1, threading.get_ident())
                        assert engine._lock._is_owned() and engine._db.in_transaction
                        raise RuntimeError("controlled full-checker failure")
                    try:
                        with monkeypatch.context() as patch:
                            patch.setattr(engine, "_verify_current", fail_full)
                            with pytest.raises(RuntimeError, match="controlled full-checker failure"):
                                owner._recovery_full_verify()
                        assert (owner._depth, owner._thread) == (depth, previous_thread)
                        assert engine._db.in_transaction
                    finally:
                        owner._depth, owner._thread = previous_phase
            # The existing native OLD finalizer owns BEGIN IMMEDIATE, not a
            # read-only snapshot. Its already-owned transaction remains valid.
            with owner._root_lock.hold(), engine._lock:
                engine._db.execute("BEGIN IMMEDIATE")
                phase = owner._depth, owner._thread
                try:
                    assert owner._recovery_full_verify()["verified"]
                    assert (owner._depth, owner._thread) == phase and engine._db.in_transaction
                finally:
                    engine._db.execute("ROLLBACK")
        assert owner._recovering is False and owner._depth == 0 and owner._thread is None
        assert owner.verify()["verified"]
        assert owner.export_audit() == committed
        assert len(_state(owner)["transactions"]) == 7
