"""Claim parsing and the answer-key schema.

A model returns free-ish JSON (per prompts.EXTRACTION_PROMPT). This module
turns that into typed Claim objects, tolerantly (models wrap JSON in prose,
fences, etc.), and defines the frozen answer-key format.

Product-embryo-adjacent: the Claim shape here is the first draft of the
product's claims-layer schema (data-model-considerations.md).
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

CLAIM_TYPES = ("amount", "date", "text", "account_id", "meta")


@dataclass(frozen=True)
class Claim:
    type: str
    label: str
    value_raw: str
    page: int | None = None
    region: dict | None = None
    confidence: float | None = None
    group: str | None = None

    def key(self) -> tuple[str, str]:
        """A coarse identity for matching model output to truth: (type, label),
        normalized. Values are compared separately by the verifier."""
        return (self.type, _norm_label(self.label))


def _norm_label(label: str) -> str:
    return re.sub(r"\s+", " ", (label or "").strip().lower())


def parse_claims(text: str) -> tuple[list[Claim], str | None]:
    """Extract claims from a model's text output.

    Returns (claims, error). Tolerant of code fences and surrounding prose;
    strict about the claim shape once JSON is found. A parse failure is data,
    not an exception — the runner already recorded the raw text.
    """
    blob = _find_json(text)
    if blob is None:
        return [], "no JSON object found in output"
    try:
        data = json.loads(blob)
    except json.JSONDecodeError as e:
        return [], f"JSON did not parse: {e}"
    raw_claims = data.get("claims") if isinstance(data, dict) else None
    if not isinstance(raw_claims, list):
        return [], "no 'claims' array in JSON"

    claims: list[Claim] = []
    for rc in raw_claims:
        if not isinstance(rc, dict):
            continue
        ctype = str(rc.get("type", "")).strip().lower()
        if ctype not in CLAIM_TYPES:
            continue
        value_raw = rc.get("value_raw")
        if value_raw is None:
            continue
        conf = rc.get("confidence")
        try:
            conf = float(conf) if conf is not None else None
        except (TypeError, ValueError):
            conf = None
        page = rc.get("page")
        try:
            page = int(page) if page is not None else None
        except (TypeError, ValueError):
            page = None
        claims.append(
            Claim(
                type=ctype,
                label=str(rc.get("label", "")),
                value_raw=str(value_raw),
                page=page,
                region=rc.get("region") if isinstance(rc.get("region"), dict) else None,
                confidence=conf,
                group=str(rc["group"]) if rc.get("group") is not None else None,
            )
        )
    return claims, None


def _find_json(text: str) -> str | None:
    """Locate the outermost JSON object in a possibly-messy string."""
    if not text:
        return None
    # Prefer a fenced block if present.
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence:
        return fence.group(1)
    # Otherwise, first '{' to its matching last '}'.
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start : end + 1]
    return None


# --------------------------------------------------------------- answer key


@dataclass
class KeyEntry:
    """One ground-truth claim, human-verified. Carries locale/currency (I4)."""

    type: str
    label: str
    value_raw: str          # exactly as printed
    locale: str
    currency: str | None = None
    page: int | None = None
    verified_by: str = "unreviewed"   # "arithmetic" | "cross-model" | "human" | "unreviewed"
    notes: str = ""


@dataclass
class AnswerKey:
    doc_id: str
    doc_sha256: str
    locale: str
    currency: str
    entries: list[KeyEntry] = field(default_factory=list)
    frozen: bool = False
    rules_version: str | None = None

    def to_dict(self) -> dict:
        return {
            "doc_id": self.doc_id,
            "doc_sha256": self.doc_sha256,
            "locale": self.locale,
            "currency": self.currency,
            "frozen": self.frozen,
            "rules_version": self.rules_version,
            "entries": [asdict(e) for e in self.entries],
        }

    def canonical_hash(self) -> str:
        """Stable hash over the entries (the frozen ground truth). Order-independent
        so re-serialization can't change it."""
        payload = sorted(
            json.dumps(asdict(e), sort_keys=True, ensure_ascii=False)
            for e in self.entries
        )
        blob = json.dumps(payload, ensure_ascii=False)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    @classmethod
    def from_dict(cls, d: dict) -> "AnswerKey":
        return cls(
            doc_id=d["doc_id"],
            doc_sha256=d["doc_sha256"],
            locale=d["locale"],
            currency=d["currency"],
            frozen=d.get("frozen", False),
            rules_version=d.get("rules_version"),
            entries=[KeyEntry(**e) for e in d.get("entries", [])],
        )


def load_key(path: Path) -> AnswerKey:
    return AnswerKey.from_dict(json.loads(path.read_text()))


def save_key(key: AnswerKey, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(key.to_dict(), indent=2, ensure_ascii=False))
