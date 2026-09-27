"""Bounded revision-local identity evidence for movement questions."""
from __future__ import annotations

import json

from merchantcore.profile import Profile, is_inducible

from ..ledger.merchant_keys import resolve_keys
from ..ledger.merchants import normalize_merchant
from ..ledger.projection.merchants import candidate_keys, record_for_keys
from .rhythm import (MAX_RESOLVER_PROFILES, MAX_RHYTHM_ACCOUNTS,
                     MAX_RHYTHM_JSON_BYTES, RhythmReadError, _bounded)
from .scalar_bounds import refuse, selected


def movement_records(connection, rows, records):
    """Select the same graded candidate record as the canonical projection.

    Movement rows supply the current canonical key. Resolver inputs and profiles
    come from this same revision, preserving structural and legacy candidates.
    """
    columns = ("event_type", "account_id", "kind", "institution")
    selection, bounds = selected(columns)
    history = _bounded(connection,
        f"SELECT {selection} FROM accounts ORDER BY source_sequence", bounds,
        MAX_RHYTHM_ACCOUNTS, "question evidence account history")
    refuse(history, columns, label="question evidence account labels")
    accounts = {}
    for event_type, account, kind, institution in history:
        if event_type == "AccountOpened":
            accounts[account] = {"kind": kind or "", "institution": institution or ""}
        else:
            state = accounts.setdefault(account, {"kind": "", "institution": ""})
            state["institution"] = state["institution"] or institution or ""

    columns = ("institution", "account_kind")
    selection, bounds = selected(columns)
    profile_rows = _bounded(connection,
        f"SELECT {selection},CASE WHEN length(CAST(profile_json AS BLOB))<=? "
        "THEN profile_json END FROM resolver_profiles ORDER BY institution,account_kind",
        (*bounds, MAX_RHYTHM_JSON_BYTES), MAX_RESOLVER_PROFILES,
        "question evidence resolver profiles")
    refuse([row[:2] for row in profile_rows], columns,
           label="question evidence resolver labels")
    if any(encoded is None for _, _, encoded in profile_rows):
        raise RhythmReadError("question evidence resolver profile exceeds its byte bound")
    profiles = {(institution, kind): Profile.from_dict(json.loads(encoded))
                for institution, kind, encoded in profile_rows}

    def profile_for(institution, kind):
        return profiles.get((institution, kind)) if is_inducible(kind) else None

    inputs = tuple(dict.fromkeys(
        (row["account_id"], accounts.get(row["account_id"], {}).get("institution", ""),
         row["account_kind"], row["description"]) for row in rows))
    resolved = resolve_keys(inputs, profile_for=profile_for)
    out = {}
    for row in rows:
        identity = row["account_id"], row["description"]
        descriptor = normalize_merchant(row["description"])
        if not row["merchant_key"] or resolved.identity_insufficient.get(identity, False):
            out[row["movement_key"]] = None
            continue
        keys = candidate_keys(row["merchant_key"], resolved.get(identity, descriptor),
                              resolved.candidates.get(identity, ()), descriptor)
        out[row["movement_key"]] = record_for_keys(keys, records.get)
    return out
