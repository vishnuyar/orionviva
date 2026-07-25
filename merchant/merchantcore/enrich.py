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

# Enrichment is N *independent* merchants, so we never gamble a whole run on one
# giant JSON that overruns the model's output budget and truncates mid-object
# (the failure mode that silently returned zero records). We split the batch into
# chunks small enough that each call returns a complete, valid JSON object, and
# merge. One bad chunk cannot sink the rest, and progress is logged per chunk.
DEFAULT_CHUNK_SIZE = 40

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
    """Chunked merchant enrichment. ``extract_fn(prompt) -> text`` is injected;
    ``chunk_size`` bounds how many merchants ride in a single call so the reply
    stays a complete, parseable JSON object."""

    def __init__(self, extract_fn, chunk_size: int = DEFAULT_CHUNK_SIZE):
        self._extract = extract_fn
        self._chunk_size = max(1, int(chunk_size))

    def enrich(self, merchants: dict) -> dict:
        """Enrich ``{key: example}`` → ``{key: MerchantRecord}``, one model call
        per chunk of at most ``chunk_size`` merchants, merged. A chunk whose reply
        fails to parse contributes nothing but never aborts the others."""
        if not merchants:
            return {}
        items = list(merchants.items())
        chunks = [dict(items[i:i + self._chunk_size])
                  for i in range(0, len(items), self._chunk_size)]
        _, version = build_enrichment_prompt(dict(items[:1]))
        log.info("enrich: %d merchant(s) in %d call(s) of <=%d (%s)",
                 len(items), len(chunks), self._chunk_size, version)
        out: dict[str, MerchantRecord] = {}
        for n, chunk in enumerate(chunks, 1):
            prompt, version = build_enrichment_prompt(chunk)
            text = self._extract(prompt)
            records = parse_enrichment(text, list(chunk.keys()), version)
            log.info("enrich: chunk %d/%d → %d/%d record(s)",
                     n, len(chunks), len(records), len(chunk))
            out.update(records)
        log.info("enrich: got %d record(s) total", len(out))
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
        # dropping the tail records (never bluff — principle 2).
        if result.finish_reason == "length":
            log.warning("enrich: reply still truncated after continuation — "
                        "a chunk may be incomplete; consider a smaller chunk_size")
        return result.text

    return _extract
