"""A vault: one directory, one passphrase, holding a person's whole ledger.

Bundles the encrypted event log (`events.jsonl`, via a `Ledger` with a cached
live projection) and the encrypted raw-blob store (`raw/`) under a single
directory, opened with one passphrase. This is the unit the surface and the
agent work against. `open` creates the directory if it does not exist.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from .ingest.raw_store import RawStore
from .ledger.ledger import Ledger
from .ledger.merchant_keys import installed_resolver

log = logging.getLogger(__name__)


@dataclass
class Vault:
    ledger: Ledger
    raw: RawStore
    directory: Path

    @classmethod
    def open(cls, directory: Path, passphrase: str) -> "Vault":
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        log.info("opening vault at %s", directory)
        # Wired here rather than at each entry point: a vault opened without a
        # merchant-key resolver reads its catalog under descriptors while
        # enrichment files it under brands, and the knowledge becomes
        # unreadable.
        return cls(
            ledger=Ledger.open(directory / "events.jsonl", passphrase,
                               resolve_keys=installed_resolver()),
            raw=RawStore.open(directory / "raw", passphrase),
            directory=directory)

    @property
    def store(self):
        """The underlying event store (the Ledger owns it and the live projection)."""
        return self.ledger.store

    def events(self):
        return self.ledger.events()
