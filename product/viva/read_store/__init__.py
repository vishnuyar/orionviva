"""Encrypted disposable read storage.

The event log remains authoritative.  This package owns a separate SQLCipher
database and derives its key directly from the supplied passphrase using
read-store-owned metadata; it never receives an EventStore or RawStore key.
"""

from .store import (ReadRevision, ReadStore, ReadStoreBusy, ReadStoreDegraded,
                    ReadStoreError, SynchronizeResult, assert_sqlcipher_runtime)

__all__ = ["ReadRevision", "ReadStore", "ReadStoreBusy", "ReadStoreDegraded",
           "ReadStoreError", "SynchronizeResult", "assert_sqlcipher_runtime"]
