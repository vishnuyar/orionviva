"""Store impersonal merchant records, reviewed aliases and enrichment queues.

Records are keyed by permanent merchant id. ``export`` returns the public
business-only payload; ``merge`` applies commons priors under the grade rules.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from .descriptor import linted_example
from .normalize import is_shareable, normalize_merchant
from .record import MerchantRecord

log = logging.getLogger(__name__)

CATALOG_FORMAT = "merchant-catalog-v2"
IDENTITY_VERSION = "merchant-id-v1"
_GRADE_RANK = {"verified": 3, "corroborated": 2, "unverified": 1}
_RECORD_FIELDS = {"key", "aliases", "canonical_name", "category", "subcategory",
                  "attributes", "grade", "source", "version"}
_PUBLIC_FIELDS = {"format", "identity_version", "records"}
_LOCAL_FIELDS = _PUBLIC_FIELDS | {"pending", "unanswered", "restaged"}


def _rank(grade: str) -> int:
    return _GRADE_RANK.get(grade or "", 0)


class Catalog:
    def __init__(self, path: str | Path | None = None, shipped=None):
        self._records: dict[str, MerchantRecord] = {}
        self._aliases: dict[str, str] = {}
        self._pending: dict[str, str] = {}       # key -> example (awaiting enrichment)
        # key -> the example that was asked about and came back with nothing.
        # Holding the example, not just the key, is what retires a non-answer
        # when new evidence arrives.
        self._unanswered: dict[str, str] = {}
        # Restaged keys remain readable while awaiting a replacement record.
        self._restaged: set[str] = set()
        self._path = Path(path) if path else None
        # Shipped records are loaded below installation-learned records.
        self._shipped = Path(shipped) if shipped else None
        if self._shipped and self._shipped.exists():
            self._load_file(self._shipped)
        if self._path and self._path.exists():
            self.load()

    # --- the pending queue (what the product submits) ----------------------

    def submit(self, hints) -> int:
        """Queue unknown merchants for enrichment.

        ``hints`` is an iterable of ``(key, example)``. Each example is linted
        here before it is stored. Merchants already in the catalog, and
        merchants already queued against this same example, are skipped, so
        this is idempotent. Returns how many were newly queued."""
        n = 0
        for key, example in hints:
            if not key or (self.get(key) is not None and key not in self._restaged):
                continue
            example = linted_example(example)
            if self._pending.get(key) == example:
                continue                 # already queued, against this same evidence
            # The persisted pending queue contains only linted examples.
            self._pending[key] = example
            # New evidence retires an old non-answer.
            self._unanswered.pop(key, None)
            n += 1
        return n

    def restage(self, predicate, dry_run: bool = False) -> list:
        """Return records the predicate calls stale to the pending queue.

        ``predicate(record) -> bool`` decides staleness; nothing here infers
        it. A restaged key is accepted by ``submit`` again, so the next
        submission queues it with whatever example the caller currently holds —
        the record itself carries none, and stays exactly as it is until a new
        one replaces it.

        ``dry_run`` returns the same keys and changes nothing: nothing queued,
        nothing saved. The keys come back sorted."""
        keys = sorted(k for k, r in self._records.items() if predicate(r))
        if dry_run:
            return keys
        self._restaged.update(keys)
        if keys:
            self._save()
        return keys

    def restaged(self) -> set:
        """Keys awaiting a re-ask. A key leaves this set when a record for it
        is added, whether or not the new record outranked the old one."""
        return set(self._restaged)

    def pending(self) -> dict:
        """Merchants worth spending a model call on right now.

        The pending queue minus anything already asked about against this very
        example and answered with nothing. A merchant returns here as soon as
        its example changes."""
        return {k: v for k, v in self._pending.items()
                if self._unanswered.get(k) != v}

    def queued(self) -> dict:
        """Everything in the queue, answered or not.

        This is what persists to plain JSON, so it is what a privacy audit
        reads; `pending` is what a caller about to spend a model call reads."""
        return dict(self._pending)

    def unanswered(self) -> dict:
        """What was asked and not answered, with the example that was sent."""
        return dict(self._unanswered)

    def mark_unanswered(self, keys) -> int:
        """Record that these keys were sent to a model and nothing came back.

        Called with the keys of a batch minus the keys that returned a record.
        A key not currently pending is ignored. Returns how many marks were
        newly written, and saves only if any were."""
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
        submitted_key = record.key
        target = self._aliases.get(record.key, record.key)
        prior = self._records.get(target)
        # Identity aliases come only from installed catalog layers. A runtime
        # record may update an existing merchant, but it cannot create a fold.
        aliases = {record.key, target}
        if prior is not None:
            aliases.update(prior.aliases)
        record.key = target
        record.aliases = sorted(aliases)
        if prior is None or _rank(record.grade) >= _rank(prior.grade):
            if prior is not None:
                record.aliases = sorted(set(record.aliases) | set(prior.aliases))
            self._records[record.key] = record
        elif prior is not None:
            prior.aliases = sorted(set(prior.aliases) | aliases)
        self._reindex()
        for key in aliases | {submitted_key}:
            self._pending.pop(key, None)
            self._unanswered.pop(key, None)
            self._restaged.discard(key)
        self._save()

    def add_all(self, records) -> None:
        for r in (records.values() if isinstance(records, dict) else records):
            self.add(r)

    def get(self, key: str) -> MerchantRecord | None:
        target = self._aliases.get(key, key)
        return self._records.get(target)

    def resolve(self, candidates) -> MerchantRecord | None:
        """Return the record named by the first exact reviewed alias."""
        for candidate in candidates or ():
            found = self.get(candidate)
            if found is not None:
                return found
        return None

    def records(self) -> dict:
        return dict(self._records)

    # --- the commons --------------------------------------------------------

    def export(self) -> dict:
        """Return the business-only v2 commons payload.

        Every alias must pass ``is_shareable`` and the record must be typed as
        a business. Pending and unanswered queues are excluded.
        """
        records = {
            key: record.to_dict()
            for key, record in self._records.items()
            if (record.attributes.get("counterparty_kind") == "business"
                and all(is_shareable(alias) for alias in record.aliases))
        }
        return {"format": CATALOG_FORMAT,
                "identity_version": IDENTITY_VERSION,
                "records": records}

    def merge(self, exported: dict) -> int:
        """Import a commons snapshot as priors.

        An imported record is applied only when no local record exists or the
        import's grade is strictly higher. Returns how many were applied."""
        records, _legacy = self._decode(exported, "commons import")
        combined = dict(self._aliases)
        for record in records.values():
            for alias in record.aliases:
                prior_target = combined.get(alias)
                if prior_target is not None and prior_target != record.key:
                    raise ValueError(
                        f"commons import: alias {alias!r} already names "
                        f"record {prior_target!r}")
                combined[alias] = record.key
        n = 0
        for k, r in records.items():
            r.source = "commons"
            prior = self._records.get(k)
            if prior is None or _rank(r.grade) > _rank(prior.grade):
                if prior is not None:
                    r.aliases = sorted(set(r.aliases) | set(prior.aliases))
                self._records[k] = r
                n += 1
        self._reindex()
        self._save()
        return n

    # --- persistence of impersonal records in plain JSON --------------------

    def _save(self) -> None:
        if not self._path:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps({
            "format": CATALOG_FORMAT,
            "identity_version": IDENTITY_VERSION,
            "records": {k: r.to_dict() for k, r in self._records.items()},
            "pending": self._pending,
            "unanswered": self._unanswered,
            "restaged": sorted(self._restaged),
        }, indent=2))

    def _decode(self, data: dict, label: str, *, local: bool = False) -> tuple[dict, bool]:
        """Validate a v2 payload, or lift a legacy record map without folds."""
        if not isinstance(data, dict):
            raise ValueError(f"{label}: a catalog must be a JSON object")
        legacy = "format" not in data and "identity_version" not in data
        if legacy:
            raw_records = data.get("records", data)
            if not isinstance(raw_records, dict):
                raise ValueError(f"{label}: records must be an object")
            records = {}
            for key, value in raw_records.items():
                if not isinstance(value, dict):
                    raise ValueError(f"{label}: record {key!r} must be an object")
                record = MerchantRecord.from_dict({**value, "key": key})
                record.aliases = [key]
                records[key] = record
            return records, True
        if data.get("format") != CATALOG_FORMAT:
            raise ValueError(
                f"{label}: unsupported catalog format {data.get('format')!r}")
        if data.get("identity_version") != IDENTITY_VERSION:
            raise ValueError(
                f"{label}: unsupported identity version "
                f"{data.get('identity_version')!r}")
        allowed_fields = _LOCAL_FIELDS if local else _PUBLIC_FIELDS
        extras = set(data) - allowed_fields
        if extras:
            raise ValueError(f"{label}: unsupported catalog fields {sorted(extras)!r}")
        raw_records = data.get("records")
        if not isinstance(raw_records, dict):
            raise ValueError(f"{label}: records must be an object")
        records: dict[str, MerchantRecord] = {}
        owners: dict[str, str] = {}
        for key, value in raw_records.items():
            if not isinstance(key, str):
                raise ValueError(f"{label}: record ids must be strings")
            if not isinstance(value, dict):
                raise ValueError(f"{label}: record {key!r} must be an object")
            extra_record_fields = set(value) - _RECORD_FIELDS
            if extra_record_fields:
                raise ValueError(
                    f"{label}: record {key!r} has unsupported fields "
                    f"{sorted(extra_record_fields)!r}")
            if value.get("key") != key:
                raise ValueError(
                    f"{label}: record id {key!r} disagrees with its inner key")
            if normalized_key := normalize_merchant(key):
                if normalized_key != key:
                    raise ValueError(f"{label}: record id {key!r} is not normalized")
            else:
                raise ValueError(f"{label}: record id may not be empty")
            if (not isinstance(value.get("aliases"), list)
                    or not all(isinstance(alias, str)
                               for alias in value.get("aliases", []))):
                raise ValueError(f"{label}: record {key!r} aliases must be strings")
            record = MerchantRecord.from_dict(value)
            if not record.aliases or key not in record.aliases:
                raise ValueError(
                    f"{label}: record {key!r} must carry its self-alias")
            if len(record.aliases) != len(set(record.aliases)):
                raise ValueError(f"{label}: record {key!r} repeats an alias")
            for alias in record.aliases:
                normalized = normalize_merchant(alias)
                if not alias or normalized != alias:
                    raise ValueError(
                        f"{label}: alias {alias!r} is not normalized")
                owner = owners.get(alias)
                if owner is not None and owner != key:
                    raise ValueError(
                        f"{label}: alias {alias!r} names both {owner!r} and {key!r}")
                owners[alias] = key
            records[key] = record
        return records, False

    def _install(self, records: dict[str, MerchantRecord], *, learned: bool,
                 legacy: bool) -> None:
        """Install one validated layer, migrating only through reviewed aliases."""
        grouped: dict[str, list[tuple[str, MerchantRecord]]] = {}
        for old_key, incoming in records.items():
            target = self._aliases.get(old_key, old_key) if legacy else old_key
            grouped.setdefault(target, []).append((old_key, incoming))

        for target, candidates in grouped.items():
            highest = max(_rank(record.grade) for _, record in candidates)
            finalists = [(old_key, record) for old_key, record in candidates
                         if _rank(record.grade) == highest]
            direct = [(old_key, record) for old_key, record in finalists
                      if old_key == target]
            if direct:
                old_key, incoming = direct[0]
            elif len(finalists) == 1:
                old_key, incoming = finalists[0]
            else:
                def data_of(record):
                    data = record.to_dict()
                    data.pop("key", None)
                    data.pop("aliases", None)
                    return data

                bodies = {json.dumps(data_of(record), sort_keys=True)
                          for _, record in finalists}
                if len(bodies) != 1:
                    keys = sorted(old for old, _ in finalists)
                    raise ValueError(
                        f"catalog migration: equally ranked records {keys!r} "
                        f"all name {target!r}")
                old_key, incoming = min(finalists, key=lambda item: item[0])

            prior = self._records.get(target)
            incoming.key = target
            layer_aliases = {candidate_key
                             for candidate_key, _ in candidates}
            incoming.aliases = sorted(set(incoming.aliases) | layer_aliases | {target}
                                      | (set(prior.aliases) if prior else set()))
            if prior is None or learned:
                self._records[target] = incoming
        self._reindex()

    def _reindex(self) -> None:
        aliases: dict[str, str] = {}
        for key, record in self._records.items():
            record.aliases = sorted(set(record.aliases) | {key})
            for alias in record.aliases:
                owner = aliases.get(alias)
                if owner is not None and owner != key:
                    raise ValueError(
                        f"catalog alias {alias!r} names both {owner!r} and {key!r}")
                aliases[alias] = key
        self._aliases = aliases

    def _load_file(self, path: Path) -> None:
        """Load shipped records without local queues and mark their source."""
        data = json.loads(path.read_text())
        records, legacy = self._decode(data, str(path))
        for record in records.values():
            record.source = "shipped"
        self._install(records, learned=False, legacy=legacy)

    def load(self) -> None:
        """Overlay learned records and queues on the shipped catalog.

        Learned records take precedence per key; unmatched shipped keys remain.
        """
        data = json.loads(self._path.read_text())
        records, legacy = self._decode(data, str(self._path), local=True)
        self._install(records, learned=True, legacy=legacy)
        self._pending = dict(data.get("pending", {}))
        # A catalog written without this key loads with nothing marked.
        self._unanswered = dict(data.get("unanswered", {}))
        self._restaged = set(data.get("restaged", []))
