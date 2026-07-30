"""The merchant catalog — the knowledge base, unencrypted because impersonal.

Holds enriched ``MerchantRecord``s keyed by normalized merchant, plus a *pending
queue* of merchants submitted for enrichment. Persists to a plain JSON file (it
carries no personal data — only merchant knowledge). ``export`` produces the
privacy-linted, commercial-only snapshot a commons contribution is hashed from;
``merge`` imports commons priors (a local ruling always outranks an import).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from .descriptor import linted_example
from .normalize import is_shareable
from .record import MerchantRecord

log = logging.getLogger(__name__)

_GRADE_RANK = {"verified": 3, "corroborated": 2, "unverified": 1}


def _rank(grade: str) -> int:
    return _GRADE_RANK.get(grade or "", 0)


class Catalog:
    def __init__(self, path: str | Path | None = None, shipped=None):
        self._records: dict[str, MerchantRecord] = {}
        self._pending: dict[str, str] = {}       # key -> example (awaiting enrichment)
        # key -> the example that was ASKED ABOUT and came back with nothing.
        # Without this, a merchant whose reply never parses is re-sent on every
        # single run, at full price, silently — invisible when a person runs
        # enrichment by hand and expensive the moment an agent does.
        self._unanswered: dict[str, str] = {}
        self._path = Path(path) if path else None
        # The seed that travels with the package, laid down FIRST so anything
        # this installation learned or a person confirmed sits on top of it.
        # Same precedence as a commons import: what you worked out beats what
        # you were handed.
        self._shipped = Path(shipped) if shipped else None
        if self._shipped and self._shipped.exists():
            self._load_file(self._shipped)
        if self._path and self._path.exists():
            self.load()

    # --- the pending queue (what the product submits) ----------------------

    def submit(self, hints) -> int:
        """Queue unknown merchants for enrichment. ``hints`` is an iterable of
        ``(key, example)`` — impersonal only. Already-known or already-pending
        merchants are skipped (idempotent). Returns how many were newly queued."""
        n = 0
        for key, example in hints:
            if not key or key in self._records:
                continue
            example = linted_example(example)
            if self._pending.get(key) == example:
                continue                 # already queued, against this same evidence
            # Linted HERE as well as at the caller, deliberately. The pending
            # queue is persisted to plain JSON that is unencrypted by decision
            # and shared across vaults by decision, and anything submitted but
            # never enriched sits in it indefinitely. Making the lint a property
            # of the store rather than of every call site is what stops the next
            # caller from reintroducing repair-list C2.
            self._pending[key] = example
            # New evidence retires an old non-answer. The same snapshot rule the
            # question queue uses for a decline: stay quiet while nothing has
            # changed, ask again the moment it has.
            self._unanswered.pop(key, None)
            n += 1
        return n

    def pending(self) -> dict:
        """Merchants worth spending a model call on right now.

        Excludes anything already asked about, against this very example, that
        came back with nothing. A model that could not name a brand from one
        example will not name it from the same example an hour later, and the
        difference between those two beliefs is a call per merchant per run."""
        return {k: v for k, v in self._pending.items()
                if self._unanswered.get(k) != v}

    def queued(self) -> dict:
        """Everything in the queue, answered or not.

        Separate from `pending` deliberately: this is what persists to plain
        JSON, so it is what a privacy audit has to look at, while `pending` is
        what a spender has to look at. One method answering both questions is how
        a lint that guards the file drifts away from the file."""
        return dict(self._pending)

    def unanswered(self) -> dict:
        """What was asked and not answered, with the example that was sent."""
        return dict(self._unanswered)

    def mark_unanswered(self, keys) -> int:
        """Record that these keys were sent to a model and nothing came back.

        Called with the keys of a batch minus the keys that returned a record —
        parsing failures, omissions, and merchants the model declined to name,
        which are indistinguishable from here and want the same treatment."""
        n = 0
        for k in keys:
            example = self._pending.get(k)
            if example is not None and self._unanswered.get(k) != example:
                self._unanswered[k] = example
                n += 1
        if n:
            self._save()
        return n

    # --- enriched records ---------------------------------------------------

    def add(self, record: MerchantRecord) -> None:
        prior = self._records.get(record.key)
        if prior is None or _rank(record.grade) >= _rank(prior.grade):
            self._records[record.key] = record
        self._pending.pop(record.key, None)
        self._unanswered.pop(record.key, None)
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
             "pending": self._pending,
             "unanswered": self._unanswered}, indent=2))

    def load(self) -> None:
        data = json.loads(self._path.read_text())
        self._records = {k: MerchantRecord.from_dict(v)
                         for k, v in data.get("records", {}).items()}
        self._pending = dict(data.get("pending", {}))
        # Absent in catalogs written before this existed. An old catalog simply
        # starts with nothing marked, which costs one more round of calls once.
        self._unanswered = dict(data.get("unanswered", {}))
