"""Bounded value-time inputs for historical Activity composition."""

from __future__ import annotations

import json
from decimal import Decimal
from types import SimpleNamespace

from merchantcore.profile import Profile, is_inducible
from merchantcore.taxonomy import subcategory_identity

from ..ledger.events import Provenance
from ..ledger.movement_identity import movement_key
from ..ledger.projection.movements import MovementInfo
from ..ledger.projection import accounts as account_views
from ..ledger.projection import categories as category_views
from ..ledger.projection import movements as movement_views
from ..ledger.projection import merchants as merchant_views
from ..ledger.merchant_keys import resolve_keys
from .held import _identity_core
from .store import ReadStoreError

MAX_TEMPORAL_ROWS = 10_000
MAX_TEMPORAL_POSTINGS = 50_000
MAX_TRANSFER_PAYLOAD_BYTES = 1_000_000
MAX_TRANSFER_CANDIDATES = 200
MAX_OVERLAY_JSON_BYTES = 1_000_000
MAX_OVERLAY_ITEMS = 200

_FAMILIES = {
    "accounts": "source_sequence,event_type,account_id,occurred_at,kind,currency,institution,account_number,name,origin",
    "transactions": "source_sequence,occurred_at,description,provenance_doc_id,provenance_page,provenance_region,provenance_note",
    "transfer_history": "source_sequence,event_type,occurred_at,movement_a,movement_b,candidates_json,grade,decided_by,by_actor,evidence_json",
    "category_history": "source_sequence,occurred_at,movement_key,descriptor,category,subcategory,nature,grade,by_actor,category_grade,subcategory_grade,category_by,subcategory_by",
    "merchant_history": "source_sequence,occurred_at,merchant_key,category,subcategory,canonical_name,attributes_json,aliases_json,grade,by_actor,category_grade,subcategory_grade,category_by,subcategory_by",
    "tag_history": "source_sequence,occurred_at,scope,subject,tags_json,by_actor",
    "ruling_history": "source_sequence,occurred_at,scope,subject,legs_json,by_actor,grade,same_as",
    "account_alias_history": "source_sequence,occurred_at,alias_key,account_id,learn_signal",
    "documents": "source_sequence,occurred_at,doc_id,filename,doc_type",
}


def eligible_family(revision, family: str, as_of: str):
    """Filter value-time first, then return a bounded source-order sequence."""
    columns = _FAMILIES.get(family)
    if columns is None:
        raise ValueError("unknown temporal Activity family")
    names = columns.split(",")
    selected = list(names)
    parameters = []
    for index, name in enumerate(names):
        if name.endswith("_json"):
            selected[index] = (
                f"CASE WHEN {name} IS NULL THEN NULL "
                f"WHEN length(CAST({name} AS BLOB))<=? THEN {name} "
                "ELSE 1 END")
            parameters.append(
                MAX_TRANSFER_PAYLOAD_BYTES if family == "transfer_history"
                else MAX_OVERLAY_JSON_BYTES)
        elif family == "transactions" and name in {
                "description", "provenance_doc_id", "provenance_region",
                "provenance_note"}:
            from .scalar_bounds import MAX_SCALAR_BYTES
            selected[index] = (
                f"CASE WHEN {name} IS NULL THEN NULL "
                f"WHEN length(CAST({name} AS BLOB))<=? THEN {name} ELSE 1 END")
            parameters.append(MAX_SCALAR_BYTES)
    rows = revision.connection.execute(
        f"SELECT {','.join(selected)} FROM {family} WHERE occurred_at<=? "
        "ORDER BY source_sequence LIMIT ?",
        (*parameters, as_of, MAX_TEMPORAL_ROWS + 1)).fetchall()
    if len(rows) > MAX_TEMPORAL_ROWS:
        raise ReadStoreError("historical Activity input exceeds its row bound")
    for row in rows:
        if any(type(row[index]) is int and row[index] == 1
               for index, name in enumerate(names) if name.endswith("_json")):
            raise ReadStoreError("historical Activity JSON exceeds its byte bound")
        if family == "transactions" and any(
                type(row[index]) is int and row[index] == 1
                for index, name in enumerate(names) if name in {
                    "description", "provenance_doc_id", "provenance_region",
                    "provenance_note"}):
            raise ReadStoreError("historical transaction scalar exceeds its byte bound")
    return [dict(zip(names, row)) for row in rows]


def eligible_postings(revision, as_of: str):
    from .scalar_bounds import selected as scalar_selected, refuse as refuse_scalars
    """Return only postings whose parent transaction is value-time eligible."""
    columns = ("source_sequence", "posting_index", "account_id", "amount_text",
               "grade", "occurred_at", "description", "provenance_doc_id",
               "provenance_page", "provenance_region", "provenance_note")
    expressions = ("p.source_sequence", "p.posting_index", "p.account_id",
                   "p.amount_text", "p.grade", "t.occurred_at",
                   "t.description", "t.provenance_doc_id",
                   "t.provenance_page", "t.provenance_region",
                   "t.provenance_note")
    selected, bounds = scalar_selected(
        expressions, ("p.source_sequence", "p.posting_index", "t.provenance_page"))
    rows = revision.connection.execute(
        f"SELECT {selected} FROM postings p "
        "JOIN transactions t ON t.source_sequence=p.source_sequence "
        "WHERE t.occurred_at<=? ORDER BY p.source_sequence,p.posting_index LIMIT ?",
        (*bounds, as_of, MAX_TEMPORAL_POSTINGS + 1)).fetchall()
    if len(rows) > MAX_TEMPORAL_POSTINGS:
        raise ReadStoreError("historical Activity postings exceed their row bound")
    refuse_scalars(rows, expressions,
                   ("p.source_sequence", "p.posting_index", "t.provenance_page"),
                   label="historical Activity postings")
    return [dict(zip(columns, row)) for row in rows]


def movement_base(revision, as_of: str):
    """Enumerate eligible postings under eligible account identity state."""
    accounts = {}
    for row in eligible_family(revision, "accounts", as_of):
        account = row["account_id"]
        if row["event_type"] == "AccountOpened":
            accounts[account] = {
                "kind": row["kind"] or "", "currency": row["currency"] or "",
                "name": row["name"] or "", "institution": row["institution"] or "",
                "number": row["account_number"] or "", "origin": row["origin"] or "issued"}
        else:
            state = accounts.setdefault(account, {
                "kind": "", "currency": "", "name": "", "institution": "",
                "number": "", "origin": "issued"})
            from ..ledger.identity import usable_full_number
            if (usable_full_number(row["account_number"] or "")
                    and not usable_full_number(state["number"])):
                state["number"] = row["account_number"]
            state["institution"] = state["institution"] or row["institution"] or ""
    rows = eligible_postings(revision, as_of)
    rows.sort(key=lambda row: (
        row["account_id"], row["occurred_at"], row["description"],
        row["amount_text"], row["source_sequence"], row["posting_index"]))
    counts, movements, grades = {}, [], {}
    for row in rows:
        account = row["account_id"]
        state = accounts.get(account, {})
        if state.get("kind") not in ("depository", "liability", "investment"):
            continue
        signature = (row["provenance_doc_id"], account, row["occurred_at"],
                     row["amount_text"], row["description"])
        occurrence = counts.get(signature, 0)
        counts[signature] = occurrence + 1
        key = movement_key(*signature, occurrence)
        movements.append(MovementInfo(
            key=key, account=account, kind=state["kind"],
            date=row["occurred_at"], amount=Decimal(row["amount_text"]),
            description=row["description"], currency=state["currency"],
            provenance=Provenance(row["provenance_doc_id"],
                                  row["provenance_page"],
                                  row["provenance_region"],
                                  row["provenance_note"])))
        grades[key] = row["grade"]
    return movements, grades


def transfer_state(rows):
    """Fold eligible transfer links and suggestions in source order."""
    links, suggestions = {}, {}
    for row in rows:
        kind, a, b = row["event_type"], row["movement_a"], row["movement_b"]
        if kind == "TransferSuggested":
            candidates_json, evidence_json = row["candidates_json"], row["evidence_json"]
            if (not isinstance(candidates_json, str) or not isinstance(evidence_json, str)
                    or len(candidates_json.encode("utf-8")) > MAX_TRANSFER_PAYLOAD_BYTES
                    or len(evidence_json.encode("utf-8")) > MAX_TRANSFER_PAYLOAD_BYTES):
                raise ReadStoreError("historical transfer payload exceeds its byte bound")
            try:
                from .transfer_payload import (candidate_keys,
                                               decode as decode_transfer)
                candidates = candidate_keys(decode_transfer(
                    candidates_json, list, maximum_bytes=MAX_TRANSFER_PAYLOAD_BYTES),
                    maximum_count=MAX_TRANSFER_CANDIDATES)
                evidence = decode_transfer(
                    evidence_json, dict, maximum_bytes=MAX_TRANSFER_PAYLOAD_BYTES)
            except (TypeError, ValueError) as exc:
                raise ReadStoreError("historical transfer payload is invalid") from exc
            if not isinstance(evidence, dict):
                raise ReadStoreError("historical transfer payload has the wrong shape")
            suggestions[a] = {"a": a, "candidates": candidates,
                              "evidence": evidence, "status": "suggested"}
            continue
        pair = frozenset((a, b))
        if kind == "TransferLinked":
            links[pair] = {"status": "linked", "grade": row["grade"],
                           "by": row["by_actor"], "decided_by": row["decided_by"]}
        else:
            links[pair] = {"status": "unlinked"}
        suggestions.pop(a, None)
        suggestions.pop(b, None)
    linked = {key for pair, info in links.items()
              if info["status"] == "linked" for key in pair}
    live_links = [{"a": min(pair), "b": max(pair), **info}
                  for pair, info in links.items() if info["status"] == "linked"]
    live_suggestions = [suggestion for suggestion in suggestions.values()
                        if suggestion["a"] not in linked
                        and (not suggestion["candidates"] or
                             any(candidate not in linked
                                 for candidate in suggestion["candidates"]))]
    return live_links, live_suggestions, linked


def _overlay_json(encoded, kind):
    if not isinstance(encoded, str) or len(encoded.encode("utf-8")) > MAX_OVERLAY_JSON_BYTES:
        raise ReadStoreError("historical overlay payload exceeds its byte bound")
    try:
        value = json.loads(encoded)
    except (TypeError, ValueError) as exc:
        raise ReadStoreError("historical overlay payload is invalid") from exc
    if not isinstance(value, kind) or (isinstance(value, list)
                                       and len(value) > MAX_OVERLAY_ITEMS):
        raise ReadStoreError("historical overlay payload has the wrong shape")
    return value


def merchant_state(rows):
    """Fold eligible merchant facts with canonical grade and alias precedence."""
    rank = {"verified": 3, "corroborated": 2, "unverified": 1, "": 0}
    merchants = {}
    for row in rows:
        key = row["merchant_key"]
        incoming = {
            "merchant": key, "category": row["category"],
            "subcategory": row["subcategory"],
            "canonical_name": row["canonical_name"],
            "attributes": _overlay_json(row["attributes_json"], dict),
            "aliases": _overlay_json(row["aliases_json"], list),
            "grade": row["grade"], "by": row["by_actor"],
            "category_grade": row["category_grade"],
            "subcategory_grade": row["subcategory_grade"],
            "category_by": row["category_by"],
            "subcategory_by": row["subcategory_by"],
        }
        if any(not isinstance(alias, str) for alias in incoming["aliases"]):
            raise ReadStoreError("historical merchant alias has the wrong shape")
        prior = merchants.get(key)
        if prior is None or rank.get(incoming["grade"], 0) >= rank.get(prior["grade"], 0):
            incoming["aliases"] = sorted(set(incoming["aliases"]) |
                                         set((prior or {}).get("aliases", ())))
            merchants[key] = incoming
        elif incoming["aliases"]:
            prior["aliases"] = sorted(set(prior["aliases"]) |
                                      set(incoming["aliases"]))
    return merchants


def tag_state(rows):
    """Retain the latest eligible tags for each authored subject."""
    latest = {}
    for row in rows:
        tags = _overlay_json(row["tags_json"], list)
        if any(not isinstance(tag, str) for tag in tags):
            raise ReadStoreError("historical tag payload has the wrong shape")
        latest[(row["scope"], row["subject"])] = tags
    return latest


class SQLHistoricalActivityProjection:
    """Supply Activity's projection protocol from eligible normalized SQL rows."""

    def __init__(self, revision, as_of: str):
        self._revision, self.as_of = revision, as_of
        identity = _identity_core(revision.connection, as_of)
        movements, self._grades = movement_base(revision, as_of)
        categories = category_overlays(eligible_family(
            revision, "category_history", as_of))
        merchants = merchant_state(eligible_family(
            revision, "merchant_history", as_of))
        tags = tag_state(eligible_family(revision, "tag_history", as_of))
        links, suggestions, linked = transfer_state(eligible_family(
            revision, "transfer_history", as_of))
        rulings, category_aliases, subcategory_aliases, tag_aliases = \
            _ruling_state(eligible_family(revision, "ruling_history", as_of))
        profiles = _resolver_profiles(revision)
        resolver_inputs = list(dict.fromkeys((
            movement.account,
            identity._acct[movement.account].institution,
            movement.kind, movement.description)
            for movement in movements))
        resolved = resolve_keys(resolver_inputs, profile_for=lambda institution, kind:
            profiles.get((institution, kind)) if is_inducible(kind) else None)
        self._core = SimpleNamespace(
            _acct=identity._acct, _aliases=identity._aliases,
            _own_tokens_cache=None, _mkeys=resolved, _mkeys_of={},
            _categories=categories, _merchant_categories=merchants,
            _movement_tags={key: value for (scope, key), value in tags.items()
                            if scope == "movement"},
            _merchant_tags={key: value for (scope, key), value in tags.items()
                            if scope == "merchant"},
            _rulings=rulings, _category_alias_map=category_aliases,
            _subcategory_alias_map=subcategory_aliases,
            _tag_alias_map=tag_aliases)
        for movement in movements:
            movement.linked = movement.key in linked
            movement_views.decide_nature(self._core, movement)
        self._movements = movements
        self._links, self._suggestions, self._linked = links, suggestions, linked
        self._filenames = {row["doc_id"]: row["filename"]
                           for row in eligible_family(revision, "documents", as_of)}

    def movements(self):
        return list(self._movements)

    def movement_grades(self):
        return dict(self._grades)

    def account_info(self, account):
        return account_views.account_info(self._core, account)

    def derived_category(self, movement):
        return category_views.derived_category(self._core, movement)

    def tags_of(self, movement):
        return category_views.tags_of(self._core, movement)

    def inherited_tags_of(self, movement):
        return category_views.inherited_tags_of(self._core, movement)

    def known_tags(self):
        return category_views.known_tags(self._core)

    def known_categories(self):
        return category_views.known_categories(self._core)

    def canonical_category(self, label):
        return category_views.canonical_category(self._core, label)

    def canonical_subcategory(self, label):
        return category_views.canonical_subcategory(self._core, label)

    def merchant_categories(self):
        return merchant_views.merchant_categories(self._core)

    def captured_filenames(self):
        return dict(self._filenames)

    def linked_keys(self):
        return set(self._linked)

    def transfer_links(self):
        return [dict(row) for row in self._links]

    def transfer_suggestions(self):
        return [dict(row) for row in self._suggestions]

    def activity_page(self, limit: int, focus: str = ""):
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise ReadStoreError("Activity limit must be between 1 and 100")
        pending = {row["a"] for row in self._suggestions}
        ordered = sorted(self._movements,
                         key=lambda movement: (movement.key in pending,
                                               movement.date, movement.key),
                         reverse=True)
        shown = ordered[:limit]
        if focus and all(movement.key != focus for movement in shown):
            found = next((movement for movement in ordered
                          if movement.key == focus), None)
            if found is not None:
                shown = [*shown[:-1], found] if shown else [found]
        return shown, len(self._movements) - len({row.key for row in shown})


def _resolver_profiles(revision):
    rows = revision.connection.execute(
        "SELECT institution,account_kind,"
        "CASE WHEN length(CAST(profile_json AS BLOB))<=? "
        "THEN profile_json END FROM resolver_profiles "
        "ORDER BY institution,account_kind LIMIT ?",
        (MAX_OVERLAY_JSON_BYTES, MAX_TEMPORAL_ROWS + 1)).fetchall()
    if len(rows) > MAX_TEMPORAL_ROWS:
        raise ReadStoreError("historical resolver profiles exceed their read bound")
    if any(encoded is None for _institution, _kind, encoded in rows):
        raise ReadStoreError("historical resolver profile exceeds its byte bound")
    return {(institution, kind): Profile.from_dict(_overlay_json(encoded, dict))
            for institution, kind, encoded in rows}


def _ruling_state(rows):
    rulings, category_aliases, subcategory_aliases, tag_aliases = {}, {}, {}, {}
    for row in rows:
        scope, subject, grade, same_as = (row["scope"], row["subject"],
                                          row["grade"], row["same_as"])
        incoming = {"scope": scope, "subject": subject,
                    "legs": _overlay_json(row["legs_json"], list),
                    "grade": grade, "same_as": same_as}
        prior = rulings.get((scope, subject))
        if prior is None or grade == "verified" or prior["grade"] != "verified":
            rulings[(scope, subject)] = incoming
        if scope == "category" and same_as:
            category_aliases[subject] = same_as
            if (subcategory_identity(subject) and subcategory_identity(same_as)
                    and subcategory_identity(subject) != subcategory_identity(same_as)):
                subcategory_aliases[subject] = same_as
        elif scope == "tag" and same_as:
            tag_aliases[subject] = same_as
    return rulings, category_aliases, subcategory_aliases, tag_aliases


def category_overlays(rows):
    """Apply eligible category overlays in canonical source order."""
    rank = {"verified": 3, "corroborated": 2, "unverified": 1, "": 0}
    categories = {}
    for row in rows:
        key = row["movement_key"]
        incoming = {
            "descriptor": row["descriptor"], "category": row["category"],
            "subcategory": row["subcategory"], "nature": row["nature"],
            "grade": row["grade"], "by": row["by_actor"],
            "category_grade": row["category_grade"],
            "subcategory_grade": row["subcategory_grade"],
            "category_by": row["category_by"],
            "subcategory_by": row["subcategory_by"],
        }
        prior = categories.get(key)
        if prior is None:
            categories[key] = incoming
            continue
        cat = (incoming if rank.get(incoming["category_grade"], 0) >=
               rank.get(prior["category_grade"], 0) else prior)
        sub = (incoming if rank.get(incoming["subcategory_grade"]
                                if incoming["subcategory"] else "", 0) >=
               rank.get(prior["subcategory_grade"]
                        if prior["subcategory"] else "", 0) else prior)
        categories[key] = {
            **cat, "subcategory": sub["subcategory"],
            "subcategory_grade": sub["subcategory_grade"],
            "subcategory_by": sub["subcategory_by"],
            "grade": min((cat["category_grade"], sub["subcategory_grade"]),
                         key=lambda value: rank.get(value, 0)),
            "by": (cat["category_by"] if cat["category_by"] == sub["subcategory_by"]
                   else "mixed"),
        }
    return categories
