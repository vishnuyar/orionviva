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
        self._proj = LedgerProjection([], resolve_keys=resolve_keys)
        for event in store.events():
            self._proj.apply(event)

    @classmethod
    def open(cls, path, passphrase: str, resolve_keys=None) -> "Ledger":
        return cls(EventStore.open(path, passphrase), resolve_keys=resolve_keys)

    def append(self, event: Event) -> dict:
        """Persist an event and fold it into the live projection."""
        record = self.store.append(event)
        self._proj.apply(event)
        return record

    def projection(self) -> LedgerProjection:
        """The live 'now' projection — always current, never re-replayed."""
        return self._proj

    def fresh_projection(self) -> LedgerProjection:
        """Replay the durable stream, including writes from other instances."""
        return LedgerProjection(self.store.events(), resolve_keys=self._resolve_keys)

    def append_atomically(
        self, decide: Callable[[LedgerProjection], Iterable[Event]]
    ) -> list[dict]:
        """Compare against a locked fresh projection and append one decision."""
        chosen: list[Event] = []

        def choose(events: tuple[Event, ...]) -> tuple[Event, ...]:
            projection = LedgerProjection(events, resolve_keys=self._resolve_keys)
            chosen.extend(decide(projection))
            return tuple(chosen)

        records = self.store.append_atomically(choose)
        # Refresh the live projection from the complete stream.
        self._proj = self.fresh_projection()
        return records

    def projection_as_of(self, as_of: str | None) -> LedgerProjection:
        """A projection as of a past date. None returns the live one; otherwise
        a filtered projection is built on demand."""
        if as_of is None:
            return self._proj
        return LedgerProjection(self.store.events(), as_of=as_of,
                                resolve_keys=self._resolve_keys)

    def events(self) -> Iterator[Event]:
        return self.store.events()

    def __len__(self) -> int:
        return len(self.store)
