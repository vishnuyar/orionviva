"""The Ledger — an event store plus one live, incrementally-updated projection.

A reusable facade used across the product (ingest, answers, the surface): it owns
the ``EventStore`` and keeps a single ``LedgerProjection`` in sync, updating it
with each appended event rather than replaying and decrypting the whole log on
every read. Reads call :meth:`projection`; appends go through :meth:`append` so
the cache stays current.

This is the performance spine (see the standing practice: optimize regularly,
watch for redundant replays). Before it, a single ingest re-decrypted the entire
log several times; now an append is O(1) over the cache and a read is free.
Historical (`as_of`) queries are rarer and build a filtered projection on demand.
"""

from __future__ import annotations

from typing import Iterator

from .events import Event
from .projection import LedgerProjection
from .store import EventStore


class Ledger:
    """An EventStore wrapped with a cached, incrementally-updated projection."""

    def __init__(self, store: EventStore) -> None:
        self.store = store
        self._proj = LedgerProjection([])
        for event in store.events():
            self._proj.apply(event)

    @classmethod
    def open(cls, path, passphrase: str) -> "Ledger":
        return cls(EventStore.open(path, passphrase))

    def append(self, event: Event) -> dict:
        """Persist an event and fold it into the live projection."""
        record = self.store.append(event)
        self._proj.apply(event)
        return record

    def projection(self) -> LedgerProjection:
        """The live 'now' projection — always current, never re-replayed."""
        return self._proj

    def projection_as_of(self, as_of: str | None) -> LedgerProjection:
        """A projection as of a past date. None returns the live one; otherwise a
        filtered projection is built on demand (the rarer path)."""
        if as_of is None:
            return self._proj
        return LedgerProjection(self.store.events(), as_of=as_of)

    def events(self) -> Iterator[Event]:
        return self.store.events()

    def __len__(self) -> int:
        return len(self.store)
