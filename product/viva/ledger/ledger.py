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
from threading import RLock
from typing import Iterator

from .events import Event
from .projection import LedgerProjection
from .store import EventStore


class Ledger:
    """An EventStore wrapped with a cached, incrementally-updated projection."""

    def __init__(self, store: EventStore, resolve_keys=None) -> None:
        self.store = store
        # How a descriptor becomes the key its merchant knowledge is filed
        # under. Held so an `as_of` projection resolves merchants the same way
        # the live one does.
        self._resolve_keys = resolve_keys
        self._lock = RLock()
        self._proj = LedgerProjection([], resolve_keys=resolve_keys)
        for event in store.events():
            self._proj.apply(event)
        self._projection_size = self.store.path.stat().st_size

    def fork(self) -> "Ledger":
        """An independently cached ledger over the same durable log."""
        return Ledger(self.store.fork(), resolve_keys=self._resolve_keys)

    def _replay(self) -> LedgerProjection:
        return LedgerProjection(self.store.snapshot_events(),
                                resolve_keys=self._resolve_keys)

    def _sync_if_external_write(self) -> None:
        size = self.store.path.stat().st_size
        if size != self._projection_size:
            self._proj = self._replay()
            self._projection_size = size

    @classmethod
    def open(cls, path, passphrase: str, resolve_keys=None) -> "Ledger":
        return cls(EventStore.open(path, passphrase), resolve_keys=resolve_keys)

    def append(self, event: Event) -> dict:
        """Persist an event and fold it into the live projection."""
        with self._lock:
            complete: list[Event] = []

            def choose(events: tuple[Event, ...]) -> tuple[Event, ...]:
                complete.extend(events)
                complete.append(event)
                return (event,)

            record = self.store.append_atomically(choose)[0]
            # Rebuild the cache from the locked prefix plus this event.
            self._proj = LedgerProjection(complete,
                                          resolve_keys=self._resolve_keys)
            self._projection_size = self.store.path.stat().st_size
            return record

    def projection(self) -> LedgerProjection:
        """The live projection, synchronized after another handle writes."""
        with self._lock:
            self._sync_if_external_write()
            return self._proj

    def fresh_projection(self) -> LedgerProjection:
        """Replay the durable stream, including writes from other instances."""
        with self._lock:
            return self._replay()

    def append_atomically(
        self, decide: Callable[[LedgerProjection], Iterable[Event]]
    ) -> list[dict]:
        """Compare against a locked fresh projection and append one decision."""
        chosen: list[Event] = []
        complete: list[Event] = []

        def choose(events: tuple[Event, ...]) -> tuple[Event, ...]:
            projection = LedgerProjection(events, resolve_keys=self._resolve_keys)
            chosen.extend(decide(projection))
            complete.extend(events)
            complete.extend(chosen)
            return tuple(chosen)

        with self._lock:
            records = self.store.append_atomically(choose)
            # Refresh the live projection from the complete stream.
            self._proj = LedgerProjection(complete,
                                          resolve_keys=self._resolve_keys)
            self._projection_size = self.store.path.stat().st_size
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
