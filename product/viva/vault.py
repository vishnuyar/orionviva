"""A vault: one directory, one passphrase, holding a person's whole ledger.

Bundles the encrypted event log (`events.jsonl`, via a `Ledger` with a cached
live projection) and the encrypted raw-blob store (`raw/`) under a single
directory, opened with one passphrase. This is the unit the surface and the
agent work against.

`open` creates the directory if it does not exist, which is right for the
engine: a command that is given a path is being told where a vault is to live,
and a missing directory there is not a failure at all.

It is not right for a person typing a path. A mistyped path answered as an
opened, brand-new empty vault, which reads to somebody as their records having
vanished. So the question "is there a vault here" is asked separately, by
:func:`holds_a_vault`, and a caller that must not create one says so — the
sidecar does. The default stays as it was, because every engine entry point
depends on it and changing it under them would be a second defect.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from .ingest.raw_store import RawStore
from .ledger.ledger import Ledger
from .ledger.merchant_keys import installed_resolver

log = logging.getLogger(__name__)

# What makes a directory a vault rather than a directory. The event log is the
# source of truth and everything else is a projection of it, so its presence is
# the question and nothing else is.
EVENTS = "events.jsonl"


class VaultNotFound(FileNotFoundError):
    """There is no vault at that path, and none was made there.

    Raised only where a caller asked not to create one. It carries the path so
    a caller can say which one, and nothing else: what a person is told about
    it is written where sentences are written."""

    def __init__(self, directory: Path) -> None:
        super().__init__(str(directory))
        self.directory = Path(directory)


def holds_a_vault(directory: Path | str) -> bool:
    """Whether there is a vault in that directory.

    Asked before opening, by any caller that must not make one. It reads the
    event log's presence and nothing else — not its contents, not the raw
    store, and not the passphrase, which is a separate question with a separate
    answer."""
    return (Path(directory) / EVENTS).is_file()


@dataclass
class Vault:
    ledger: Ledger
    raw: RawStore
    directory: Path

    @classmethod
    def open(cls, directory: Path, passphrase: str,
             create: bool = True) -> "Vault":
        """Open the vault in ``directory``, making one there if there is none.

        ``create=False`` refuses to make one: it raises :class:`VaultNotFound`
        for a directory holding no event log, and ``NotADirectoryError`` for a
        path that is not a directory at all. A caller that hands a person's
        typed path to this passes False, because the two failures it then gets
        are the two things that person needs to be told apart from a vault that
        opened."""
        directory = Path(directory)
        if not create:
            if directory.exists() and not directory.is_dir():
                raise NotADirectoryError(str(directory))
            if not holds_a_vault(directory):
                raise VaultNotFound(directory)
        directory.mkdir(parents=True, exist_ok=True)
        log.info("opening vault at %s", directory)
        # Every opened vault uses installed merchant identity resolution.
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
