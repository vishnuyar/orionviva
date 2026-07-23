"""A vault: one directory, one passphrase, holding a person's whole ledger.

Bundles the encrypted event log (`events.jsonl`) and the encrypted raw-blob
store (`raw/`) under a single directory, opened with one passphrase. This is the
unit the surface (and later the agent) works against.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .ingest.raw_store import RawStore
from .ledger.store import EventStore


@dataclass
class Vault:
    store: EventStore
    raw: RawStore
    directory: Path

    @classmethod
    def open(cls, directory: Path, passphrase: str) -> "Vault":
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        return cls(
            store=EventStore.open(directory / "events.jsonl", passphrase),
            raw=RawStore.open(directory / "raw", passphrase),
            directory=directory)

    def events(self):
        return self.store.events()
