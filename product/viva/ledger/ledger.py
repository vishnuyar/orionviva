"""The Ledger — an event store plus one live, incrementally-updated projection.

The facade used across the product (ingest, answers, the surface): it owns the
``EventStore`` and keeps a single ``LedgerProjection`` in sync, folding in each
appended event rather than replaying and decrypting the whole log on every read.
Reads call :meth:`projection`; appends go through :meth:`append` so the cache
stays current.

An append is O(1) over the cache and a read is free. An `as_of` query builds a
filtered projection on demand.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from copy import deepcopy
from dataclasses import dataclass
from threading import RLock
from types import MethodType
from typing import Iterator
from weakref import WeakKeyDictionary, ref

from .events import Event
from .projection import LedgerProjection
from .projection.core import ProjectionCore
from .store import EventStore


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


class Ledger:
    """An EventStore wrapped with a cached, incrementally-updated projection."""

    def __init__(self, store: EventStore, resolve_keys=None) -> None:
        self.store = store
        # How a descriptor becomes the key its merchant knowledge is filed
        # under. Held so an `as_of` projection resolves merchants the same way
        # the live one does.
        self._resolve_keys = resolve_keys
        self._lock = RLock()
        # Desktop SQL reads do not require this projection; legacy consumers
        # construct it on their first request.
        self._proj: LedgerProjection | None = None
        self._cache_generation = 0
        # Begin at the authenticated identity established by EventStore.open.
        self._projection_identity = store._cached_identity()

    def _revoke_cache(self) -> None:
        self._cache_generation += 1
        if self._proj is not None:
            _revoke_projection(self._proj)

    def _install_cache(self, events, identity, *, witnessed: bool) -> None:
        self._revoke_cache()
        projection = LedgerProjection(deepcopy(events), resolve_keys=self._resolve_keys)
        self._proj = projection
        self._projection_identity = identity
        count, head = identity[:2]
        if (witnessed and type(count) is int and isinstance(head, str)
                and head and count == len(events)):
            core = projection.core
            core.apply = MethodType(_guarded_core_apply, core)
            _owned_projections[projection] = _ProjectionOwnership(
                ref(self), ref(core), self._cache_generation,
                core._classification_revision, (count, head))
            _owned_cores[core] = ref(projection)

    def fork(self) -> "Ledger":
        """An independently cached ledger over the same durable log."""
        return Ledger(self.store.fork(), resolve_keys=self._resolve_keys)

    def _replay(self) -> LedgerProjection:
        return LedgerProjection(self.store.snapshot_events(),
                                resolve_keys=self._resolve_keys)

    def _sync_if_external_write(self) -> None:
        # The authenticated head is the cache witness. File size is neither an
        # authenticity check nor enough to notice head-only rollback/tampering.
        try:
            identity = self.store.authenticated_identity()
            if self._proj is None or identity != self._projection_identity:
                self._revoke_cache()
                from ..startup_diagnostics import span
                with span("event_authenticated_snapshot"):
                    events, identity = self.store.snapshot_events_with_identity()
                with span("projection_construction"):
                    self._install_cache(events, identity, witnessed=True)
        except BaseException:
            self._revoke_cache()
            raise

    @classmethod
    def open(cls, path, passphrase: str, resolve_keys=None) -> "Ledger":
        return cls(EventStore.open(path, passphrase), resolve_keys=resolve_keys)

    def append(self, event: Event) -> dict:
        """Persist an event and fold it into the live projection."""
        # The submitted value and final fold own their bodies, independently
        # of the caller's mutable Event and of the store's temporary prefix.
        event = deepcopy(event)
        with self._lock:
            self._revoke_cache()
            complete: list[Event] = []

            def choose(events: tuple[Event, ...]) -> tuple[Event, ...]:
                complete.extend(deepcopy(events))
                complete.append(deepcopy(event))
                return (event,)

            record = self.store.append_atomically(choose)[0]
            identity = self.store._cached_identity()
            witnessed = (record['seq'] + 1, record['record_hash']) == identity[:2]
            self._install_cache(complete, identity, witnessed=witnessed)
            return record

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
        """Compare against a locked fresh projection and append one decision."""
        complete: list[Event] = []
        prefix_identity = None

        def choose(events: tuple[Event, ...]) -> tuple[Event, ...]:
            nonlocal prefix_identity
            # This witness is already authenticated under the writer boundary.
            prefix_identity = self.store._cached_identity()
            baseline = deepcopy(events)
            projection = LedgerProjection(deepcopy(baseline), resolve_keys=self._resolve_keys)
            chosen = deepcopy(tuple(decide(projection)))
            complete.extend(baseline)
            complete.extend(deepcopy(chosen))
            return chosen

        with self._lock:
            self._revoke_cache()
            records = self.store.append_atomically(choose)
            identity = self.store._cached_identity()
            if records:
                witnessed = (records[-1]['seq'] + 1, records[-1]['record_hash']) == identity[:2]
            else:
                witnessed = prefix_identity == identity
            self._install_cache(complete, identity, witnessed=witnessed)
            return records

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
