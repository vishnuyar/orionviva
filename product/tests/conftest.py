"""Mint test vaults at a cheap scrypt cost, and nothing else.

scrypt is slow **on purpose** — the production cost parameters are interactive-
login grade, and one derivation costs about a tenth of a second. That is a
security property, and it is the right price for a real vault. It is the wrong
price for a test suite: nearly every product test opens a vault, and
`Vault.open` opens two encrypted stores (the event log and the raw-blob store),
each re-deriving the key from its own header. The suite was paying login-grade
stretching roughly eight hundred times a run — 156 seconds, of which about 150
bought nothing but the KDF proving it is slow.

The design already allowed the fix without a special case. The cost parameters
are data: they travel in the vault header (`header["kdf"]`), and every open path
re-derives with whatever the header says. A vault minted with a cheaper `n`
therefore opens correctly through the *identical* product code — no branch, no
environment variable, no test-only path shipped to a user. The only thing that
hardcodes the production cost is `KdfParams.new()`, so that is the single thing
this replaces.

Everything else stays real: a real random salt, a real `Scrypt.derive`, a real
header round-trip. Only the work factor moves.

The files whose subject *is* the vault opt out with
`pytestmark = pytest.mark.production_kdf` and pay the real cost, so the
production parameters are still exercised end to end on every run — see
`test_crypto.py`, `test_store.py`, `test_raw_store.py`. Together they cost about
seven seconds, which is why they are not gated behind "did vault code change":
a skipped test reports as a pass, and unnoticed missing coverage on the one
component whose failure loses the vault is not worth seven seconds.
"""

import os

import pytest

from viva import crypto

# Cheap enough to be free, real enough to still be scrypt. This number is never
# written by the product and never reaches a user's vault; it exists only in
# headers minted under this conftest.
TEST_SCRYPT_N = 2 ** 4


@pytest.fixture(autouse=True)
def _cheap_vault_kdf(request, monkeypatch):
    """Replace `KdfParams.new` so vaults minted during a test are cheap to open.

    Patched on the class, not on the module constant: `n` is a dataclass field
    default bound at class creation, so reassigning `crypto.SCRYPT_N` would be a
    silent no-op — `new()` passes only the salt and picks the default up from
    the field. Product code reaches the classmethod by attribute lookup at call
    time, so this covers `new_vault_header` and every caller beneath it.
    """
    if request.node.get_closest_marker("production_kdf"):
        return

    def cheap_new(cls):
        return cls(salt=os.urandom(crypto.SALT_LEN), n=TEST_SCRYPT_N)

    monkeypatch.setattr(crypto.KdfParams, "new", classmethod(cheap_new))


# The two settings that decide whether a live reader can be built at all. What
# they hold changes what the product says about a document that has not been
# read, so a machine where they are set would run a different suite from one
# where they are not — including the generated parity artifact, whose bytes are
# compared exactly.
_READER_ENV = ("VIVA_MODEL_ADAPTER", "VIVA_MODEL")


@pytest.fixture(autouse=True)
def _no_reader_configured_unless_a_test_says_so(monkeypatch):
    """Start every test on a machine that names no reader.

    A test whose subject is a configured environment sets these itself, and its
    own setting lands after this one. Everything else runs from a known floor
    rather than from whatever the developer's shell happens to export — a suite
    that passes only where the environment is unset is not a gate, and one
    whose verdict moves with a shell variable is worse.
    """
    for name in _READER_ENV:
        monkeypatch.delenv(name, raising=False)
