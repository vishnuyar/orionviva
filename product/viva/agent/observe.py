"""What the agent can see, assembled once per wake.

`policy.assess()` is pure and takes its world as arguments — which is what makes
it testable and what makes two wakes a minute apart agree. This module is the
impure half: it opens the vault's projection, reads the profile store and the
merchant catalog off disk, and builds those arguments. Nothing here decides
anything.

The one non-obvious piece is `unknown_brands`, and it is worth stating why it is
not simply the number of brands with no category. `assess` turns that count into
a call estimate, and enrichment submits in batches of forty — so counting brands
the catalog ALREADY knows would budget for calls that will never be made, and on
a warm catalog the over-estimate is most of the number. The honest count is what
`Catalog.submit` would newly queue: hints, minus what is already known, minus
what is already pending. That mirrors `submit`'s own skip rule rather than
approximating it, so the estimate cannot drift away from the behaviour.
"""

from __future__ import annotations

import os
import pathlib
from dataclasses import dataclass, field


@dataclass
class Observation:
    """One wake's view of the world. Data only — no decisions, no side effects."""

    pairs: dict = field(default_factory=dict)      # (inst, kind) -> {descriptor: n}
    recent: dict = field(default_factory=dict)     # the same, last N days
    unknown_brands: int = 0                        # brands a call would newly buy
    offered: dict = field(default_factory=dict)    # brand key -> Hint, what may cross
    store: object = None                           # ProfileStore
    catalog: object = None                         # Catalog
    proj: object = None                            # LedgerProjection
    profile_for: object = None                     # movement -> Profile | None
    kind_for: object = None                        # movement -> account kind
    movements: int = 0

    def summary(self) -> dict:
        """Counts only — safe to print, safe to log, safe to put in a report."""
        return {"movements": self.movements,
                "pairs": len(self.pairs),
                "inducible_pairs": len([k for k in self.pairs
                                        if _is_inducible(k[1])]),
                "grammars": len(self.store.ids()) if self.store else 0,
                "brands_offered": len(self.offered),
                "unknown_brands": self.unknown_brands}


def _is_inducible(kind: str) -> bool:
    from merchantcore.profile import is_inducible
    return is_inducible(kind)


def catalog_path() -> pathlib.Path:
    """Where this installation's learned merchant knowledge is kept.

    The same resolution `viva.enrich` uses, and deliberately not a second copy of
    that logic: two ways to find one file is how an agent enriches into a catalog
    the surface never reads."""
    from .. import enrich as _enrich
    return _enrich.catalog_path()


def open_catalog():
    from merchantcore import home
    from merchantcore.catalog import Catalog
    return Catalog(catalog_path(), shipped=home.shipped_catalog_file())


def observe(vault, recent_days: int = 120) -> Observation:
    """Everything `assess` needs, read from the vault and from disk.

    Makes no model calls. Safe to run on every wake, and safe to run when no
    model is configured at all — which is what makes `--dry-run` an honest
    rehearsal rather than a different code path."""
    from ..induce_profile import _pairs, profile_store
    from ..ledger.hints import enrichment_hints
    from ..ledger.streams import build_streams

    proj = vault.ledger.projection()
    movements = proj.movements()
    pairs, recent = _pairs(proj, recent_days=recent_days)

    store = profile_store()
    catalog = open_catalog()

    # A grammar changes what a brand IS, so the streams the hints are built from
    # must be resolved through whatever grammars exist right now. The enrich CLI
    # omits these two closures and keys brands by the normalizer alone; doing the
    # same here would buy records under names the next induction rewrites.
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
    # `queued`, not `pending`: a brand already asked about and never answered is
    # still in the queue and will NOT be sent again, so counting it here would
    # budget for a call that cannot happen — and would keep proposing enrichment
    # forever over brands no model has been able to name.
    queued = catalog.queued()
    unknown = len([k for k in offered
                   if catalog.get(k) is None and k not in queued])

    return Observation(
        pairs=dict(pairs), recent=dict(recent),
        unknown_brands=unknown, offered=offered,
        store=store, catalog=catalog, proj=proj,
        profile_for=profile_for, kind_for=kind_for,
        movements=len(movements))


def model_configured() -> bool:
    """Whether a live model edge exists. Checked before acting, never before
    observing: an agent that cannot see because it cannot spend is a worse
    diagnostic than one that reports what it would have done."""
    return bool(os.environ.get("VIVA_MODEL") and os.environ.get("VIVA_MODEL_ADAPTER"))
