"""What the agent can see, assembled once per wake.

The impure half of the decision: it opens the vault's projection, reads the
profile store and the merchant catalog off disk, and builds the arguments
`policy.assess` takes. It decides nothing and makes no model calls.

`unknown_brands` is the count `Catalog.submit` would newly queue — offered
hints, minus what the catalog already has a record for, minus what is already
queued — so it matches the number of calls an enrichment would actually make.
`known_records_to_sync` is the separate free half: catalog records this vault
can apply immediately without sending anything to a model.

Design rationale: docs/the-maintenance-agent.md
"""

from __future__ import annotations

import os
import pathlib
from dataclasses import dataclass, field


@dataclass
class Observation:
    """One wake's view of the world. Data only."""

    pairs: dict = field(default_factory=dict)      # (inst, kind) -> {descriptor: n}
    recent: dict = field(default_factory=dict)     # the same, last N days
    unknown_brands: int = 0                        # brands a call would newly buy
    known_records_to_sync: int = 0                 # held catalog records, zero calls
    offered: dict = field(default_factory=dict)    # brand key -> Hint, what may cross
    store: object = None                           # ProfileStore
    catalog: object = None                         # Catalog
    proj: object = None                            # LedgerProjection
    profile_for: object = None                     # movement -> Profile | None
    kind_for: object = None                        # movement -> account kind
    movements: int = 0

    def summary(self) -> dict:
        """Counts only: no descriptor, amount or account appears in the result."""
        return {"movements": self.movements,
                "pairs": len(self.pairs),
                "inducible_pairs": len([k for k in self.pairs
                                        if _is_inducible(k[1])]),
                "grammars": len(self.store.ids()) if self.store else 0,
                "brands_offered": len(self.offered),
                "unknown_brands": self.unknown_brands,
                "known_records_to_sync": self.known_records_to_sync}


def _is_inducible(kind: str) -> bool:
    from merchantcore.profile import is_inducible
    return is_inducible(kind)


def catalog_path() -> pathlib.Path:
    """Where this installation's learned merchant knowledge is kept.

    Delegates to `viva.enrich.catalog_path`, which owns the resolution."""
    from .. import enrich as _enrich
    return _enrich.catalog_path()


def open_catalog():
    from merchantcore import home
    from merchantcore.catalog import Catalog
    return Catalog(catalog_path(), shipped=home.shipped_catalog_file())


def observe(vault, recent_days: int = 120) -> Observation:
    """Everything `assess` needs, read from the vault and from disk.

    Makes no model calls and works with no model configured, so a dry run takes
    this same path. `recent_days` is the window the drift check calls recent."""
    from ..induce_profile import _pairs, profile_store
    from ..ingest import merchant_records_to_sync
    from ..ledger.hints import enrichment_hints
    from ..ledger.streams import build_streams

    proj = vault.ledger.projection()
    movements = proj.movements()
    pairs, recent = _pairs(proj, recent_days=recent_days)

    store = profile_store()
    catalog = open_catalog()

    # The streams the hints are built from are resolved through whatever
    # grammars exist right now, so brands are keyed the way an enrichment in
    # this same wake would key them.
    cache: dict = {}

    def profile_for(m):
        try:
            info = proj.account_info(m.account)
        except Exception:                                   # noqa: BLE001
            return None
        pair = (info.institution or "?", info.kind or "?")
        if pair not in cache:
            cache[pair] = store.latest_for(*pair)
        return cache[pair]

    kinds: dict = {}

    def kind_for(m):
        if m.account not in kinds:
            try:
                kinds[m.account] = proj.account_info(m.account).kind or ""
            except Exception:                               # noqa: BLE001
                kinds[m.account] = ""
        return kinds[m.account]

    offered = enrichment_hints(build_streams(movements, profile_for, kind_for))
    # `queued`, not `pending`: a brand already asked about and never answered
    # stays queued and is not sent again, so it is not unknown work.
    queued = catalog.queued()
    unknown = len([k for k in offered
                   if catalog.get(k) is None and k not in queued])
    known_to_sync = len(merchant_records_to_sync(
        vault.ledger, catalog, offered))

    return Observation(
        pairs=dict(pairs), recent=dict(recent),
        unknown_brands=unknown, known_records_to_sync=known_to_sync,
        offered=offered,
        store=store, catalog=catalog, proj=proj,
        profile_for=profile_for, kind_for=kind_for,
        movements=len(movements))


def model_configured() -> bool:
    """Whether a live model edge is configured. Checked before acting, not
    before observing."""
    return bool(os.environ.get("VIVA_MODEL") and os.environ.get("VIVA_MODEL_ADAPTER"))
