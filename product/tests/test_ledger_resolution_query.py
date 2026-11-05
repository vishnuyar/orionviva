"""Scalar resolution reads retain authentication, isolation and terminal semantics."""
from decimal import Decimal
import json
from threading import Event as ThreadEvent, Thread

import pytest

from viva.crypto import CryptoError
from viva.ingest import RawStore, ReadResult, StatementFacts, capture_and_ingest
from viva.ledger import Ledger
from viva.ledger.ledger import _owned_projection_identity
from viva.ledger.projection import LedgerProjection
from viva.ledger.events import document_captured

PW = 'synthetic-resolution-passphrase'


def _ledger(tmp_path):
    return Ledger.open(tmp_path/'events.jsonl', PW)


def _ingest(raw, ledger, label, *, closing='0'):
    def reader(data, doc_id):
        facts = StatementFacts(doc_id=doc_id, doc_type='checking_statement',
            doc_type_confidence=1.0, account_ref='Synthetic '+label, currency='USD',
            opening_amount=Decimal('0'), opening_date='2026-01-01',
            closing_amount=Decimal(closing), closing_date='2026-01-31',
            transactions=[], opening_page=1, closing_page=1)
        return ReadResult('checking_statement', 1.0, facts)
    return capture_and_ingest(raw, ledger, label.encode(), reader, captured_at='2026-02-01')


def test_cold_and_warm_scalar_authenticate_without_publishing(tmp_path, monkeypatch):
    ledger = _ledger(tmp_path)
    assert ledger._basis is None and ledger._proj is None
    publications, authentications, constructions = [], [], []
    constructor = LedgerProjection.__init__

    def constructed(self, *args, **kwargs):
        constructions.append(1)
        constructor(self, *args, **kwargs)

    monkeypatch.setattr(LedgerProjection, '__init__', constructed)
    publish, authenticate = ledger._publish_basis, ledger.store.authenticated_identity

    def published():
        publications.append(1)
        return publish()

    def authenticated():
        authentications.append(1)
        return authenticate()

    monkeypatch.setattr(ledger, '_publish_basis', published)
    monkeypatch.setattr(ledger.store, 'authenticated_identity', authenticated)
    assert ledger.is_resolved('absent') is False
    basis = ledger._basis
    assert basis is not None and ledger._proj is None
    assert ledger.is_resolved('absent') is False
    assert ledger._basis is basis and ledger._proj is None
    assert publications == [] and len(authentications) == 2
    assert constructions == [1]
    # Existing public callers still receive their detached mutable view.
    assert ledger.projection().is_resolved('absent') is False
    assert publications == [1] and ledger._proj is not basis


def test_posted_held_and_component_only_instrument_resolution_match_public_view(tmp_path):
    raw = RawStore.open(tmp_path/'raw', PW)
    ledger = _ledger(tmp_path)
    posted = _ingest(raw, ledger, 'posted')
    held = _ingest(raw, ledger, 'held', closing='1')
    assert posted.action == 'posted' and held.action == 'conflict'
    assert ledger.is_resolved(posted.doc_id) is True
    assert ledger.is_resolved(held.doc_id) is True
    assert ledger.is_resolved('never-captured') is False
    from test_instrument_contracts import identity, printed
    from test_instrument_projector_b import ingest
    # Reuse the existing terms-only instrument scenario: no invented balance.
    certificate = {'identity': identity('CD-A'), 'subtype': 'opening', 'terms': {
        'principal': printed('1000'), 'opened': printed('2021-01-01'),
        'maturity': printed('2022-01-01'),
        'withdrawal_restriction': printed('No withdrawal until maturity')}}
    instrument = ingest(raw, ledger, 'resolution-certificate', certificate, 'term_deposit_statement')
    projection = ledger.projection()
    assert instrument.action == 'awaiting'
    assert any(state.doc_id == instrument.doc_id for state in projection.instrument_component_states().values())
    assert instrument.doc_id not in projection.core._posted
    assert instrument.doc_id not in projection.core._held
    for doc_id in (posted.doc_id, held.doc_id, instrument.doc_id, 'never-captured'):
        assert ledger.is_resolved(doc_id) is projection.is_resolved(doc_id)


def test_external_writer_refreshes_scalar_without_publication(tmp_path, monkeypatch):
    ledger = _ledger(tmp_path)
    raw = RawStore.open(tmp_path/'raw', PW)
    document = RawStore.fingerprint(b'external')
    assert ledger.is_resolved(document) is False
    old_identity = ledger._projection_identity
    other = Ledger.open(tmp_path/'events.jsonl', PW)
    outcome = _ingest(raw, other, 'external')
    assert outcome.action == 'posted' and outcome.doc_id == document

    def no_publication():
        raise AssertionError('scalar published a mutable projection')

    monkeypatch.setattr(ledger, '_publish_basis', no_publication)
    assert ledger.is_resolved(document) is True
    assert ledger._projection_identity != old_identity and ledger._proj is None
    assert ledger.fresh_projection().is_resolved(document) is True


@pytest.mark.parametrize('tamper', ['forged_mac', 'missing_head', 'rollback'])
def test_scalar_refuses_invalid_current_head_and_discards_basis(tmp_path, tamper):
    ledger = _ledger(tmp_path)
    path = tmp_path/'events.jsonl'
    head = path.with_suffix(path.suffix+'.head')
    older_head = head.read_bytes()
    ledger.append(document_captured('captured', 'synthetic.pdf', 1, 'unknown', 0.0, '2026-01-01'))
    assert ledger.is_resolved('captured') is False and ledger._basis is not None
    public = ledger.projection()
    assert _owned_projection_identity(public) is not None
    current_head, log_before = head.read_bytes(), path.read_bytes()
    if tamper == 'forged_mac':
        forged = json.loads(current_head)
        forged['mac'] = '0'*64
        head.write_text(json.dumps(forged)+'\n')
    elif tamper == 'missing_head':
        head.unlink()
    else:
        head.write_bytes(older_head)
    with pytest.raises(CryptoError):
        ledger.is_resolved('captured')
    assert ledger._basis is None and ledger._proj is None
    assert _owned_projection_identity(public) is None
    assert path.read_bytes() == log_before
    # Failed handles stay failed; genuine restored metadata needs a fresh owner.
    head.write_bytes(current_head)
    with pytest.raises(CryptoError):
        ledger.is_resolved('captured')
    reopened = Ledger.open(path, PW)
    assert reopened.is_resolved('captured') is False
    assert path.read_bytes() == log_before


def test_scalar_waits_for_ledger_operation_lock(tmp_path):
    ledger = _ledger(tmp_path)
    started, done = ThreadEvent(), ThreadEvent()
    values, errors = [], []

    def query():
        started.set()
        try:
            values.append(ledger.is_resolved('absent'))
        except BaseException as error:
            errors.append(error)
        finally:
            done.set()

    with ledger._lock:
        thread = Thread(target=query)
        thread.start()
        assert started.wait(2)
        assert not done.wait(.05)
    thread.join(timeout=5)
    assert done.is_set() and not thread.is_alive()
    assert errors == [] and values == [False]


def test_public_projection_mutation_cannot_poison_scalar_or_successor(tmp_path):
    raw = RawStore.open(tmp_path/'raw', PW)
    ledger = _ledger(tmp_path)
    outcome = _ingest(raw, ledger, 'posted')
    assert outcome.action == 'posted'
    public = ledger.projection()
    public.core._posted.clear()
    public.core._posted.add('invented-document')
    assert ledger.is_resolved(outcome.doc_id) is True
    assert ledger.is_resolved('invented-document') is False
    ledger.append(document_captured('later', 'later.pdf', 1, 'unknown', 0.0, '2026-02-02'))
    successor = ledger.projection()
    assert successor is not public
    assert successor.is_resolved(outcome.doc_id) is True
    assert successor.is_resolved('invented-document') is False
    assert ledger.fresh_projection().posted_doc_ids() == successor.posted_doc_ids()


def test_pipeline_does_not_publish_a_projection_before_reader(tmp_path, monkeypatch):
    raw = RawStore.open(tmp_path/'raw', PW)
    ledger = _ledger(tmp_path)
    publications, reads = [], []
    publish = ledger._publish_basis

    def published():
        publications.append(1)
        return publish()

    def reader(data, doc_id):
        assert publications == []
        assert ledger._basis is not None and ledger._proj is None
        reads.append(1)
        return ReadResult('unknown', 0.0, None, error='synthetic unreadable input')

    monkeypatch.setattr(ledger, '_publish_basis', published)
    result = capture_and_ingest(raw, ledger, b'new-synthetic-source', reader)
    assert reads == [1] and result.action == 'parked'


def test_scalar_retains_atomic_store_reentry_refusal(tmp_path):
    ledger = _ledger(tmp_path)
    ledger.append(document_captured('old', 'old.pdf', 1, 'unknown', 0.0, '2026-01-01'))
    public = ledger.projection()
    assert _owned_projection_identity(public) is not None
    path = tmp_path/'events.jsonl'
    head = path.with_suffix(path.suffix+'.head')
    before = path.read_bytes(), head.read_bytes()
    entered = []

    def decide(projection):
        entered.append(1)
        assert projection.is_resolved('old') is False
        ledger.is_resolved('old')
        raise AssertionError('scalar query escaped store decision exclusion')

    with pytest.raises(CryptoError, match='cannot be called from its own atomic decision callback'):
        ledger.append_atomically(decide)
    assert entered == [1]
    assert (path.read_bytes(), head.read_bytes()) == before
    assert ledger._basis is None and ledger._proj is None
    assert _owned_projection_identity(public) is None
    assert ledger.store._decision_owner is None
    assert ledger.is_resolved('old') is False


def test_external_suffix_fold_failure_propagates_and_revokes_cached_state(tmp_path, monkeypatch):
    ledger = _ledger(tmp_path)
    raw = RawStore.open(tmp_path/'raw', PW)
    ledger.append(document_captured('old', 'old.pdf', 1, 'unknown', 0.0, '2026-01-01'))
    public = ledger.projection()
    assert _owned_projection_identity(public) is not None
    other = Ledger.open(tmp_path/'events.jsonl', PW)
    posted = _ingest(raw, other, 'external-posted')
    assert posted.action == 'posted'
    path = tmp_path/'events.jsonl'
    committed_bytes = path.read_bytes()
    folds = []

    def failed_fold(projection, event):
        folds.append(event.event_type)
        raise RuntimeError('synthetic suffix fold failure')

    with monkeypatch.context() as patch:
        patch.setattr(LedgerProjection, 'apply', failed_fold)
        with pytest.raises(RuntimeError, match='synthetic suffix fold failure'):
            ledger.is_resolved(posted.doc_id)
    assert folds == ['DocumentCaptured']
    assert ledger._basis is None and ledger._proj is None
    assert _owned_projection_identity(public) is None
    assert path.read_bytes() == committed_bytes
    # This was derived-work failure, so fresh authentication/reconstruction can
    # recover the genuine external commit once the injected fault is removed.
    assert ledger.is_resolved(posted.doc_id) is True
    assert ledger.fresh_projection().is_resolved(posted.doc_id) is True
    assert path.read_bytes() == committed_bytes
