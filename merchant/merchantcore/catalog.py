"""The merchant catalog — the knowledge base, unencrypted because impersonal.

Holds enriched ``MerchantRecord``s keyed by normalized merchant, plus a *pending
queue* of merchants submitted for enrichment. Persists to a plain JSON file (it
carries no personal data — only merchant knowledge, T9). ``export`` produces the
privacy-linted, commercial-only snapshot a commons contribution is hashed from;
``merge`` imports commons priors (a local ruling always outranks an import).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from .normalize import is_shareable
from .record import MerchantRecord

log = logging.getLogger(__name__)

_GRADE_RANK = {"verified": 3, "corroborated": 2, "unverified": 1}


def _rank(grade: str) -> int:
    return _GRADE_RANK.get(grade or "", 0)


class Catalog:
    def __init__(self, path: str | Path | None = None):
        self._records: dict[str, MerchantRecord] = {}
        self._pending: dict[str, str] = {}       # key -> example (awaiting enrichment)
        self._path = Path(path) if path else None
        if self._path and self._path.exists():
            self.load()

    # --- the pending queue (what the product submits) ----------------------

    def submit(self, hints) -> int:
        """Queue unknown merchants for enrichment. ``hints`` is an iterable of
        ``(key, example)`` — impersonal only. Already-known or already-pending
        merchants are skipped (idempotent). Returns how many were newly queued."""
        n = 0
        for key, example in hints:
            if not key or key in self._records or key in self._pending:
                continue
            self._pending[key] = example
            n += 1
        return n

    def pending(self) -> dict:
        return dict(self._pending)

    # --- enriched records ---------------------------------------------------

    def add(self, record: MerchantRecord) -> None:
        prior = self._records.get(record.key)
        if prior is None or _rank(record.grade) >= _rank(prior.grade):
            self._records[record.key] = record
        self._pending.pop(record.key, None)
        self._save()

    def add_all(self, records) -> None:
        for r in (records.values() if isinstance(records, dict) else records):
            self.add(r)

    def get(self, key: str) -> MerchantRecord | None:
        return self._records.get(key)

    def records(self) -> dict:
        return dict(self._records)

    # --- the commons --------------------------------------------------------

    def export(self) -> dict:
        """The privacy-linted, shareable snapshot: commercial merchants only, no
        pending queue, no personal data. The content a commons PR is hashed from."""
        return {k: r.to_dict() for k, r in self._records.items()
                if is_shareable(k)}

    def merge(self, exported: dict) -> int:
        """Import a commons snapshot as priors — a local higher-grade ruling wins.
        Returns how many entries were newly applied."""
        n = 0
        for k, d in exported.items():
            r = MerchantRecord.from_dict(d)
            r.source = r.source or "commons"
            prior = self._records.get(k)
            if prior is None or _rank(r.grade) > _rank(prior.grade):
                self._records[k] = r
                n += 1
        self._save()
        return n

    # --- persistence (plain JSON — impersonal, so unencrypted is safe) ------

    def _save(self) -> None:
        if not self._path:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(
            {"records": {k: r.to_dict() for k, r in self._records.items()},
             "pending": self._pending}, indent=2))

    def load(self) -> None:
        data = json.loads(self._path.read_text())
        self._records = {k: MerchantRecord.from_dict(v)
                         for k, v in data.get("records", {}).items()}
        self._pending = dict(data.get("pending", {}))
