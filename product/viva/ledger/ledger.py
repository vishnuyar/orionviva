"""The ledger facade: canonical events, a private fold and detached read views.

Only authenticated events update the private financial basis. Callers receive
mutable projections detached from it, so retained or modified read views cannot
become the basis of a later canonical append. Atomic decisions receive their
own speculative copy.

Canonical reads and writes still authenticate the entire physical chain.
Financial folds and unchanged-record decryption reuse authenticated prior work;
``as_of`` queries and explicit replay construct a fresh financial projection.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from copy import deepcopy
from contextvars import ContextVar
from dataclasses import dataclass
from threading import RLock, get_ident
from types import MethodType
from typing import Iterator
from weakref import WeakKeyDictionary, ref

from .events import Event
from .projection import LedgerProjection
from .projection.core import ProjectionCore
from .store import EventStore
from .work_cache import ValidationMemo, memo_scope


@dataclass(frozen=True)
class _ProjectionOwnership:
    owner: ref
    core: ref
    generation: int
    revision: tuple
    identity: tuple[int, str]


_owned_projections = WeakKeyDictionary()
_owned_cores = WeakKeyDictionary()


def _revoke_projection(projection: LedgerProjection) -> None:
    record = _owned_projections.pop(projection, None)
    if record is None:
        shared = _owned_cores.get(projection.core)
        original = shared() if shared is not None else None
        if original is not None:
            _revoke_projection(original)
        return
    core = record.core()
    if core is not None:
        _owned_cores.pop(core, None)


def _guarded_core_apply(core, event):
    # Dispatch through the actual bound instance, including after deepcopy.
    projection_ref = _owned_cores.get(core)
    if projection_ref is not None:
        projection = projection_ref()
        if projection is not None:
            _revoke_projection(projection)
    return ProjectionCore.apply(core, event)


def _owned_projection_identity(projection: LedgerProjection) -> tuple[int, str] | None:
    """Read an existing owner's exact cache witness without refreshing it."""
    if projection is None:
        return None
    record = _owned_projections.get(projection)
    if record is None:
        return None
    owner = record.owner()
    core = record.core()
    if owner is None or core is None:
        return None
    with owner._lock:
        guard = core.apply
        if (owner._proj is not projection
                or owner._cache_generation != record.generation
                or projection.core is not core
                or projection.as_of is not None
                or core._classification_revision != record.revision
                or getattr(guard, '__self__', None) is not core
                or getattr(guard, '__func__', None) is not _guarded_core_apply
                or owner._projection_identity[:2] != record.identity
                or owner.store._cached_identity()[:2] != record.identity
                or owner.store._write_failed):
            _revoke_projection(projection)
            return None
        return record.identity


@dataclass(frozen=True)
class _StageAuthority:
    owner: ref
    thread: int
    operation: object


_active_stage_operation = ContextVar("active_stage_operation", default=None)
_active_stages = WeakKeyDictionary()


def _stage_capability(stage):
    """Return only an opaque active operation/generation witness."""
    if type(stage) is not _StagedLedger:
        return None
    authority = _active_stages.get(stage)
    if authority is None:
        return None
    owner = authority.owner()
    if (owner is None or authority.thread != get_ident()
            or _active_stage_operation.get() is not authority.operation
            or owner.store._decision_owner != authority.thread
            or not stage._active or stage._failed or stage._invalidating):
        return None
    return authority.operation, stage._generation


def _stage_on_invalidation(stage, callback):
    if _stage_capability(stage) is None:
        return False
    stage._work_cleanup.append(callback)
    return True


class Ledger:
    """An EventStore wrapped with a cached, incrementally-updated projection."""

    def __init__(self, store: EventStore, resolve_keys=None) -> None:
        self.store = store
        # How a descriptor becomes the key its merchant knowledge is filed
        # under. Held so an `as_of` projection resolves merchants the same way
        # the live one does.
        self._resolve_keys = resolve_keys
        self._lock = RLock()
        self._validation_memo = ValidationMemo()
        # Desktop SQL reads do not require this projection; legacy consumers
        # construct it on their first request.
        self._proj: LedgerProjection | None = None
        self._basis: LedgerProjection | None = None
        self._cache_generation = 0
        # Begin at the authenticated identity established by EventStore.open.
        self._projection_identity = store._cached_identity()

    def _revoke_cache(self) -> None:
        self._cache_generation += 1
        if self._proj is not None:
            _revoke_projection(self._proj)

    def _set_basis(self, projection, identity, *, witnessed: bool) -> None:
        self._proj = None
        self._projection_identity = identity
        count = identity[0]
        self._basis = (projection if witnessed and
                       (count is None or count == projection._event_count()) else None)

    def _publish_basis(self) -> None:
        """Publish a detached mutable view; it can never feed the private fold."""
        assert self._basis is not None
        self._revoke_cache()
        projection = deepcopy(self._basis)
        self._proj = projection
        count, head = self._projection_identity[:2]
        if (type(count) is int and isinstance(head, str)
                and head and count == projection._event_count()):
            core = projection.core
            core.apply = MethodType(_guarded_core_apply, core)
            _owned_projections[projection] = _ProjectionOwnership(
                ref(self), ref(core), self._cache_generation,
                core._classification_revision, (count, head))
            _owned_cores[core] = ref(projection)

    def _basis_reusable(self):
        count, head = self._projection_identity[:2]
        return (self._basis is not None and type(count) is int
                and isinstance(head, str) and bool(head)
                and count == self._basis._event_count())

    def _install_cache(self, events, identity, *, witnessed: bool) -> None:
        self._revoke_cache()
        projection = LedgerProjection(deepcopy(events), resolve_keys=self._resolve_keys)
        self._set_basis(projection, identity, witnessed=witnessed)

    def _advance_cache(self, events, reusable):
        """Fold authenticated suffix events into a basis never given to callers."""
        if reusable:
            projection = self._basis
            assert projection is not None
            count = projection._event_count()
            for event in events[count:]:
                projection.apply(deepcopy(event))
            return projection
        return LedgerProjection(deepcopy(events), resolve_keys=self._resolve_keys)

    def fork(self) -> "Ledger":
        """An independently cached ledger over the same durable log."""
        return Ledger(self.store.fork(), resolve_keys=self._resolve_keys)

    def _replay(self) -> LedgerProjection:
        return LedgerProjection(self.store.snapshot_events(),
                                resolve_keys=self._resolve_keys)

    def _sync_if_external_write(self) -> None:
        # Authentication still checks the entire physical committed chain.
        # Only decryption and financial folds reuse the private canonical basis.
        reusable = self._basis_reusable()
        try:
            identity = self.store.authenticated_identity()
            if self._basis is None or identity != self._projection_identity or not reusable:
                self._revoke_cache()
                from ..startup_diagnostics import span
                with span("event_authenticated_snapshot"):
                    events, identity = self.store.snapshot_events_with_identity()
                with span("projection_construction"):
                    projection = self._advance_cache(events, reusable)
                    self._set_basis(projection, identity, witnessed=True)
            if self._proj is None or _owned_projection_identity(self._proj) is None:
                self._publish_basis()
        except BaseException:
            self._revoke_cache()
            self._proj = None
            self._basis = None
            raise

    @classmethod
    def open(cls, path, passphrase: str, resolve_keys=None) -> "Ledger":
        return cls(EventStore.open(path, passphrase), resolve_keys=resolve_keys)

    def append(self, event: Event) -> dict:
        """Persist an event and fold it into the live projection."""
        return self.append_many((event,))[0]

    def append_many(self, events: Iterable[Event]) -> list[dict]:
        """Commit already-decided events together, preserving their order."""
        submitted = deepcopy(tuple(events))
        return self._append_decision(None, submitted)

    def projection(self) -> LedgerProjection:
        """The live projection, synchronized after another handle writes."""
        with self._lock:
            self._sync_if_external_write()
            assert self._proj is not None
            return self._proj

    def fresh_projection(self) -> LedgerProjection:
        """Replay the durable stream, including writes from other instances."""
        with self._lock:
            return self._replay()

    def snapshot_projection(self) -> tuple[LedgerProjection, tuple[Event, ...]]:
        """Return one resolver-aware projection and its exact event snapshot.

        Consumers which bind a read contract to an event-stream revision need
        both values to describe the same immutable prefix.  Taking the two
        reads separately would leave a window for an external writer between
        them.
        """
        with self._lock:
            events = self.store.snapshot_events()
            return (LedgerProjection(events, resolve_keys=self._resolve_keys),
                    events)

    def append_atomically(
        self, decide: Callable[[LedgerProjection], Iterable[Event]]
    ) -> list[dict]:
        """Compare against a detached locked projection and append one decision."""
        return self._append_decision(decide, ())

    def stage_atomically(self, operation):
        """Settle deterministic work with one durable all-or-none append.

        The operation receives an isolated in-memory ledger, without a store
        or provider capability. Capture and external requests belong outside
        this boundary. Its return value is delivered only after commit.
        """
        result = None

        def decide(projection):
            nonlocal result
            staged = _StagedLedger(projection, self._resolve_keys)
            operation_id = object()
            _active_stages[staged] = _StageAuthority(ref(self), get_ident(), operation_id)
            token = _active_stage_operation.set(operation_id)
            try:
                result = operation(staged)
                staged._check_active()
                return tuple(staged._additions)
            finally:
                staged._active = False
                staged._invalidate_work()
                _active_stages.pop(staged, None)
                _active_stage_operation.reset(token)

        self.append_atomically(decide)
        return result

    def _append_decision(self, decide, submitted):
        with self._lock, memo_scope(self._validation_memo):
            reusable = self._basis_reusable()
            self._revoke_cache()
            projection = None
            chosen = ()
            prefix_identity = None

            def choose(events):
                nonlocal projection, chosen, prefix_identity
                prefix_identity = self.store._cached_identity()
                projection = self._advance_cache(events, reusable)
                # A decision can retain or mutate every input it receives. Its
                # speculative fold must never become the owner's financial basis.
                chosen = deepcopy(tuple(decide(deepcopy(projection)))) if decide is not None else submitted
                return chosen

            try:
                records = self.store.append_atomically(choose)
                identity = self.store._cached_identity()
                assert projection is not None
                for event in chosen:
                    projection.apply(deepcopy(event))
                if records:
                    witnessed = (records[-1]['seq'] + 1, records[-1]['record_hash']) == identity[:2]
                else:
                    witnessed = prefix_identity == identity
                self._set_basis(projection, identity, witnessed=witnessed)
                return records
            except BaseException:
                self._revoke_cache()
                self._proj = None
                self._basis = None
                raise

    def projection_as_of(self, as_of: str | None) -> LedgerProjection:
        """A projection as of a past date. None returns the live one; otherwise
        a filtered projection is built on demand."""
        if as_of is None:
            return self.projection()
        with self._lock:
            return LedgerProjection(self.store.snapshot_events(), as_of=as_of,
                                    resolve_keys=self._resolve_keys)

    def events(self) -> Iterator[Event]:
        return iter(self.store.snapshot_events())

    def __len__(self) -> int:
        return len(self.store)


class _StagedLedger:
    """A private speculative basis with detached mutable views and decisions."""

    def __init__(self, projection, resolve_keys):
        self.__basis = projection
        self.__view = None
        self._resolve_keys = resolve_keys
        self._additions = []
        self._active = True
        self._failed = False
        self._thread = get_ident()
        self._generation = 0
        self._invalidating = False
        self._work_cleanup = []

    def __copy__(self):
        raise TypeError("staged ledger capabilities cannot be copied")

    def __deepcopy__(self, memo):
        raise TypeError("staged ledger capabilities cannot be copied")

    def _check_active(self):
        if _stage_capability(self) is None:
            raise RuntimeError("staged ledger is closed, failed or outside its owning thread")

    def _invalidate_work(self):
        self._generation += 1
        callbacks, self._work_cleanup = self._work_cleanup, []
        self._invalidating = True
        try:
            for callback in callbacks:
                try:
                    callback()
                except BaseException:
                    # Cleanup cannot prevent revocation or canonical closure.
                    # A generation mismatch independently prevents reuse.
                    pass
        finally:
            self._invalidating = False

    def projection(self):
        self._check_active()
        if self.__view is None:
            self.__view = deepcopy(self.__basis)
        return self.__view

    def append(self, event):
        self.append_many((event,))

    def append_many(self, events):
        self._check_active()
        try:
            chosen = deepcopy(tuple(events))
            if not chosen:
                return
            self._invalidate_work()
            self.__view = None
            for event in chosen:
                if not isinstance(event, Event):
                    raise TypeError("a staged append accepts only events")
                self.__basis.apply(deepcopy(event))
            self._additions.extend(chosen)
        except BaseException:
            self._failed = True
            self.__view = None
            self._invalidate_work()
            raise

    def append_atomically(self, decide):
        self._check_active()
        chosen = deepcopy(tuple(decide(deepcopy(self.__basis))))
        self.append_many(chosen)
        return deepcopy(chosen)

    def events(self):
        self._check_active()
        return iter(deepcopy(tuple(self.__basis._source_events)))

    def __len__(self):
        self._check_active()
        return self.__basis._event_count()
