"""The enrichment engine — merchantcore makes its own batched model calls.

Given a batch of merchants (a normalized key plus a privacy-linted example),
the Enricher builds a versioned prompt, calls a model, and parses each result
into a ``MerchantRecord`` graded ``corroborated`` — above a lone guess, below a
human ``verified``.

The model call is injected as ``extract_fn(prompt) -> text``, so this path is
offline-testable and the live edge is swappable. ``model_extractor`` wraps a
``vivacore.models`` adapter for production.

Only impersonal data reaches here: the keys and linted examples the product
submits. Nothing about amounts, dates or accounts crosses.
"""

from __future__ import annotations

import pathlib

from vivacore import promptstore, versions

import json
import logging
import re

from .normalize import NORMALIZER_VERSION
from .record import MerchantRecord
from .taxonomy import (PRIMARY_CATEGORIES, TAXONOMY_VERSION, canonical_primary,
                       normalize_subcategory)

log = logging.getLogger(__name__)

PACKAGE = pathlib.Path(__file__).resolve().parent

# The version stamped on records, as `merchantcore/versions.json` declares it.
ENRICHMENT_VERSION = versions.active(PACKAGE, "enrich")

# The closed answer space an implication may name. Spelled out here rather than
# imported: merchantcore does not depend on the product.
MAJORS = ("expense", "asset", "liability", "income")
KINDS = ("business", "instrument", "peer")

# How many merchants ride in one call. Bounds the reply so that a parse failure
# costs one chunk and the rest of the run still lands.
DEFAULT_CHUNK_SIZE = 40

PROMPTS = PACKAGE / "prompts"

# The prompt lives in `prompts/<version>.txt`, so a recorded version resolves
# to the exact text that produced the record.
_PROMPT = promptstore.load(PROMPTS, ENRICHMENT_VERSION)



def build_enrichment_prompt(merchants: dict,
                            known_subcategories=None) -> tuple[str, str]:
    """Compose the enrichment prompt for a batch, and the version it carries.

    ``merchants`` is ``{key: example}``. Returns ``(prompt, version)``, where
    the version is enrichment prompt + taxonomy + normalizer, so a record can
    be re-derived from what produced it.

    ``known_subcategories`` is the vault's existing finer vocabulary, shown to
    the model so it reuses a value rather than inventing a synonym. Impersonal:
    a subcategory says nothing about who bought what, when, or for how much."""
    lines = "\n".join(f"- {key}: {example}" for key, example in merchants.items())
    header = _PROMPT.format(
        primaries=", ".join(PRIMARY_CATEGORIES) + ", other",
        known_subcategories=", ".join(known_subcategories or []) or "none yet")
    version = f"{ENRICHMENT_VERSION}+{TAXONOMY_VERSION}+{NORMALIZER_VERSION}"
    return header + lines, version


def _find_json(text: str) -> str | None:
    if not text:
        return None
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if fence:
        return fence.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start:end + 1]
    return None


def parse_enrichment(text: str, keys, version: str) -> dict:
    """Parse a model reply into ``{key: MerchantRecord}``.

    Keys the reply does not carry are absent from the result rather than
    guessed into existence."""
    return parse_enrichment_chunk(text, keys, version)[0]


def parse_enrichment_chunk(text: str, keys, version: str) -> tuple[dict, bool]:
    """Returns ``(records, parsed)`` — the records, and whether the reply
    parsed at all.

    Two different failures produce an empty ``records``, and the caller needs
    to tell them apart:

      * ``parsed`` is True — the reply was well-formed and this merchant was
        not in it. The same example will buy the same silence.
      * ``parsed`` is False — the reply was truncated or otherwise unreadable.
        Nothing was learned about any merchant in the chunk, and a retry or a
        smaller chunk may work."""
    blob = _find_json(text)
    if blob is None:
        log.warning("enrich: no JSON object found in the reply")
        return {}, False
    try:
        data = json.loads(blob)
    except json.JSONDecodeError as e:
        log.warning("enrich: reply not valid JSON: %s", e)
        return {}, False
    out: dict[str, MerchantRecord] = {}
    for key in keys:
        d = data.get(key)
        if not isinstance(d, dict):
            continue
        attrs = {}
        for src, dst in (("description", "description"), ("website", "website"),
                         ("logo", "logo_url"), ("mcc", "mcc")):
            v = str(d.get(src, "")).strip()
            if v:
                attrs[dst] = v
        kind = str(d.get("counterparty_kind", "")).strip().lower()
        if kind in KINDS:
            attrs["counterparty_kind"] = kind
        implies = clean_implications(d.get("implies"))
        if implies:
            attrs["implies"] = implies
        out[key] = MerchantRecord(
            key=key, canonical_name=str(d.get("canonical_name", "")).strip(),
            category=canonical_primary(d.get("category", "")),
            subcategory=normalize_subcategory(d.get("subcategory", "")),
            attributes=attrs, grade="corroborated", source="model",
            version=version)
    return out, True


def clean_implications(raw) -> list[dict]:
    """Keep only implications that speak the closed vocabulary.

    An implication is a claim that someone holds something — a loan, a
    property, an investment account. An item whose ``major`` is not one of
    MAJORS is dropped and logged; ``on`` and ``confidence`` fall back to
    "both" and "suggested"; the free-text fields are truncated. Returns [] for
    anything that is not a list; an empty list is a normal answer, not a parse
    failure.

    An implication carries structure only — a relationship, a major, a
    direction, an account group, a document — and no sentence for anyone to
    say."""
    out: list[dict] = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        major = str(item.get("major", "")).strip().lower()
        if major not in MAJORS:
            log.warning("enrich: dropping implication with unknown major %r", major)
            continue
        on = str(item.get("on", "both")).strip().lower()
        if on not in ("inflow", "outflow", "both"):
            on = "both"
        confidence = str(item.get("confidence", "suggested")).strip().lower()
        if confidence not in ("forced", "suggested"):
            confidence = "suggested"
        out.append({
            "relationship": str(item.get("relationship", "")).strip()[:60],
            "major": major, "on": on,
            "account_group": str(item.get("account_group", "")).strip()[:40],
            "compound": bool(item.get("compound")),
            "confidence": confidence,
            "documents": str(item.get("documents", "")).strip()[:80],
        })
    return out


class Enricher:
    """Chunked merchant enrichment.

    ``extract_fn(prompt) -> text`` is injected. ``chunk_size`` bounds how many
    merchants ride in a single call, so the reply stays a complete JSON
    object."""

    def __init__(self, extract_fn, chunk_size: int = DEFAULT_CHUNK_SIZE,
                 known_subcategories=None):
        self._extract = extract_fn
        self._chunk_size = max(1, int(chunk_size))
        self._known = list(known_subcategories or [])
        # Keys whose chunk never parsed, reset at the start of every `enrich`.
        # Reported separately from keys the model did not mention, so a caller
        # recording "asked and got nothing" does not record a transport failure.
        self.unparsed: list[str] = []

    def enrich(self, merchants: dict) -> dict:
        """Enrich ``{key: example}`` into ``{key: MerchantRecord}``.

        One model call per chunk of at most ``chunk_size`` merchants, merged. A
        chunk whose reply does not parse contributes nothing and does not abort
        the others; its keys land in ``self.unparsed``. Returns {} for an empty
        input, without calling the model."""
        if not merchants:
            return {}
        items = list(merchants.items())
        chunks = [dict(items[i:i + self._chunk_size])
                  for i in range(0, len(items), self._chunk_size)]
        _, version = build_enrichment_prompt(dict(items[:1]), self._known)
        log.info("enrich: %d merchant(s) in %d call(s) of <=%d (%s)",
                 len(items), len(chunks), self._chunk_size, version)
        out: dict[str, MerchantRecord] = {}
        self.unparsed = []
        for n, chunk in enumerate(chunks, 1):
            prompt, version = build_enrichment_prompt(chunk, self._known)
            text = self._extract(prompt)
            records, parsed = parse_enrichment_chunk(
                text, list(chunk.keys()), version)
            log.info("enrich: chunk %d/%d → %d/%d record(s)%s",
                     n, len(chunks), len(records), len(chunk),
                     "" if parsed else "   [reply did not parse — not an answer]")
            if not parsed:
                self.unparsed.extend(chunk.keys())
            out.update(records)
        log.info("enrich: got %d record(s) total%s", len(out),
                 f", {len(self.unparsed)} in chunk(s) that did not parse"
                 if self.unparsed else "")
        return out


def model_extractor(spec):
    """Wrap a ``vivacore.models`` adapter into an ``extract_fn(prompt) -> text``
    for a text-only merchant call (no images). The live edge for production."""
    from vivacore.models import adapter_for
    adapter = adapter_for(spec)

    def _extract(prompt: str) -> str:
        result = adapter.extract([], prompt)
        # The adapter continues across provider truncation. A reply still
        # truncated after that may be missing tail records, so it is logged.
        if result.finish_reason == "length":
            log.warning("enrich: reply still truncated after continuation — "
                        "a chunk may be incomplete; consider a smaller chunk_size")
        return result.text

    return _extract
