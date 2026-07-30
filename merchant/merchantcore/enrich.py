"""The enrichment engine — merchantcore makes its own batched model calls.

Given a batch of merchants (a normalized key + a privacy-linted example), the
Enricher builds a versioned prompt, calls a model through a ``vivacore.models``
adapter (provider-agnostic, pinned, cost-tracked — the same socket the reader
uses), and parses each result into a graded ``MerchantRecord``. A model batch is
graded ``corroborated`` — stronger than a lone guess, weaker than a human
``verified``. The model call is *injected* (``extract_fn(prompt) -> text``), so
this is offline-testable and the live edge is swappable; ``model_extractor``
wraps a real adapter for production.

Only impersonal data is ever seen here — the keys and linted examples the product
submits. The Enricher cannot learn anything about amounts, dates, or accounts.
"""

from __future__ import annotations

import pathlib

from vivacore import promptstore

import json
import logging
import re

from .normalize import NORMALIZER_VERSION
from .record import MerchantRecord
from .taxonomy import (PRIMARY_CATEGORIES, TAXONOMY_VERSION, canonical_primary,
                       normalize_subcategory)

log = logging.getLogger(__name__)

ENRICHMENT_VERSION = "enrich-v4"       # the version stamped on records

# The four majors, repeated here rather than imported: merchantcore must not
# depend on the product — the commons knows nothing about a ledger. These are
# the closed answer space an implication may name.
MAJORS = ("expense", "asset", "liability", "income")
KINDS = ("business", "instrument", "peer")

# Enrichment is N *independent* merchants, so a whole run is never gambled on one
# giant JSON that overruns the model's output budget and truncates mid-object,
# returning nothing. The batch is split into chunks small enough that each call
# returns a complete, valid JSON object, and merged. One bad chunk cannot sink
# the rest, and progress is logged per chunk.
DEFAULT_CHUNK_SIZE = 40

PROMPTS = pathlib.Path(__file__).resolve().parent / "prompts"

# The enrichment prompt lives in `prompts/<version>.txt`, never in a literal
# here: a recorded version must always resolve to the exact text that produced
# the record.
_PROMPT = promptstore.load(PROMPTS, ENRICHMENT_VERSION)



def build_enrichment_prompt(merchants: dict,
                            known_subcategories=None) -> tuple[str, str]:
    """Compose the enrichment prompt for a batch (``{key: example}``) and its
    version (taxonomy + prompt + normalizer, so a record can be re-derived).

    ``known_subcategories`` is the vault's EXISTING finer vocabulary. It crosses
    the impersonal-data boundary safely because a subcategory is impersonal by
    construction — "coffee shop" says nothing about who bought coffee, or when,
    or how much."""
    lines = "\n".join(f"- {key}: {example}" for key, example in merchants.items())
    # The vocabulary that already exists is shown to the model BEFORE it invents
    # a new one: preventing subcategory sprawl costs nothing, while resolving or
    # cleaning it up afterwards does.
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
    """Parse a model reply into ``{key: MerchantRecord}``. Unknown/missing keys
    are skipped (never guessed into existence)."""
    return parse_enrichment_chunk(text, keys, version)[0]


def parse_enrichment_chunk(text: str, keys, version: str) -> tuple[dict, bool]:
    """The records, AND whether the reply parsed at all.

    Two failures hide behind an empty result and they are not the same thing:

      * the reply parsed and this merchant was not in it — the model looked and
        declined to name it. Asking again, with the same example, buys the same
        silence.
      * the reply did not parse — truncated, a stray delimiter, a wrapper the
        finder missed. Nothing about the MERCHANT failed. A retry, or a smaller
        chunk, is likely to work.

    Collapsing them costs real money in one direction and buys a permanent
    silence in the other. On the first live agent run, one chunk of forty came
    back as `Expecting ',' delimiter: line 298` and every one of those forty
    merchants would have been recorded as unanswerable."""
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
    """Keep only implications that speak the closed vocabulary, and drop the rest.

    An implication is a claim that someone HOLDS something — a loan, a property,
    an investment account. Acting on a wrong one would create an account nobody
    has, across every transaction with that counterparty, in every vault that
    ever syncs this record. So the parser is strict on the closed fields and
    forgiving on the free ones, and **silence is always an acceptable answer**:
    a merchant that implies nothing is the normal case, not a parse failure."""
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
            "ask": str(item.get("ask", "")).strip()[:160],
        })
    return out


class Enricher:
    """Chunked merchant enrichment. ``extract_fn(prompt) -> text`` is injected;
    ``chunk_size`` bounds how many merchants ride in a single call so the reply
    stays a complete, parseable JSON object."""

    def __init__(self, extract_fn, chunk_size: int = DEFAULT_CHUNK_SIZE,
                 known_subcategories=None):
        self._extract = extract_fn
        self._chunk_size = max(1, int(chunk_size))
        self._known = list(known_subcategories or [])
        # Keys whose CHUNK never parsed. Reported separately from keys the model
        # simply did not mention, because a caller that remembers "asked and got
        # nothing" must not remember a transport failure that way.
        self.unparsed: list[str] = []

    def enrich(self, merchants: dict) -> dict:
        """Enrich ``{key: example}`` → ``{key: MerchantRecord}``, one model call
        per chunk of at most ``chunk_size`` merchants, merged. A chunk whose reply
        fails to parse contributes nothing but never aborts the others."""
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
        # The adapter continues across provider truncation; if it STILL comes back
        # truncated, the chunk may be incomplete — say so rather than quietly
        # dropping the tail records. Never bluff.
        if result.finish_reason == "length":
            log.warning("enrich: reply still truncated after continuation — "
                        "a chunk may be incomplete; consider a smaller chunk_size")
        return result.text

    return _extract
