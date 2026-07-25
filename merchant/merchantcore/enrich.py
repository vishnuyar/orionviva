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

import json
import logging
import re

from .normalize import NORMALIZER_VERSION
from .record import MerchantRecord
from .taxonomy import (PRIMARY_CATEGORIES, TAXONOMY_VERSION, canonical_primary,
                       normalize_subcategory)

log = logging.getLogger(__name__)

ENRICHMENT_VERSION = "enrich-v2"       # v2: 16 primaries + subcategory, mcc, logo

_PROMPT = """\
You are identifying MERCHANTS from bank/card transaction descriptors. For EACH
merchant below, return what you know from general knowledge — nothing about any
person's finances is involved, only who the merchant is.

Return ONLY a JSON object mapping each input key to an object:
{{
  "<key>": {{
    "canonical_name": "the clean merchant name, e.g. 'Amazon', 'Costco'",
    "category": one of [{primaries}],
    "subcategory": "a finer, specific label for slicing, e.g. 'warehouse club', 'coffee shop', 'streaming', 'rideshare' — free text, be specific",
    "mcc": "the 4-digit Merchant Category Code if you know it, else ''",
    "description": "a short (<=8 word) description",
    "website": "the primary website domain if well-known, else ''",
    "logo": "the logo URL or a clearbit-style domain logo if well-known, else ''"
  }}
}}

Rules:
- Use the key EXACTLY as given in your output object.
- "category" MUST be one of the listed primaries — pick the single best one for
  how a typical person classifies spending there. Use "other" only when unclear.
- "subcategory" is your finer value; be specific and consistent so similar
  merchants share a subcategory.
- Do NOT invent order numbers, amounts, or any transaction detail — you are only
  identifying the merchant.

Merchants (key: example descriptor):
"""


def build_enrichment_prompt(merchants: dict) -> tuple[str, str]:
    """Compose the enrichment prompt for a batch (``{key: example}``) and its
    version (taxonomy + prompt + normalizer, so a record can be re-derived)."""
    lines = "\n".join(f"- {key}: {example}" for key, example in merchants.items())
    header = _PROMPT.format(primaries=", ".join(PRIMARY_CATEGORIES) + ", other")
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
    blob = _find_json(text)
    if blob is None:
        return {}
    try:
        data = json.loads(blob)
    except json.JSONDecodeError as e:
        log.warning("enrich: reply not valid JSON: %s", e)
        return {}
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
        out[key] = MerchantRecord(
            key=key, canonical_name=str(d.get("canonical_name", "")).strip(),
            category=canonical_primary(d.get("category", "")),
            subcategory=normalize_subcategory(d.get("subcategory", "")),
            attributes=attrs, grade="corroborated", source="model",
            version=version)
    return out


class Enricher:
    """Batched merchant enrichment. ``extract_fn(prompt) -> text`` is injected."""

    def __init__(self, extract_fn):
        self._extract = extract_fn

    def enrich(self, merchants: dict) -> dict:
        """Enrich ``{key: example}`` in ONE model call → ``{key: MerchantRecord}``."""
        if not merchants:
            return {}
        prompt, version = build_enrichment_prompt(merchants)
        log.info("enrich: one call over %d merchant(s) (%s)", len(merchants), version)
        text = self._extract(prompt)
        records = parse_enrichment(text, list(merchants.keys()), version)
        log.info("enrich: got %d record(s)", len(records))
        return records


def model_extractor(spec):
    """Wrap a ``vivacore.models`` adapter into an ``extract_fn(prompt) -> text``
    for a text-only merchant call (no images). The live edge for production."""
    from vivacore.models import adapter_for
    adapter = adapter_for(spec)

    def _extract(prompt: str) -> str:
        return adapter.extract([], prompt).text

    return _extract
