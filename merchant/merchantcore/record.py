"""MerchantRecord — the merchant as a multi-attribute entity.

Category is attribute #1; ``attributes`` is an open bag (website, description,
socials, reviews), so the record grows by adding fields rather than by
restructuring. Every record carries a grade — ``corroborated`` for a model
enrichment or a commons prior, ``verified`` for a human ruling — and a version
(normalizer + the enrichment prompt that produced it), so a stale record can be
re-derived.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class MerchantRecord:
    key: str                              # the normalized merchant id
    canonical_name: str = ""              # the merchant's own name for itself
    category: str = ""                    # PRIMARY category (one of the 16 buckets)
    subcategory: str = ""                 # the finer, model-provided value ("streaming")
    attributes: dict = field(default_factory=dict)   # website, logo_url, mcc,
                                          # description, billing, billing_period
    grade: str = "corroborated"           # verified | corroborated | unverified
    source: str = "model"                 # model | human | commons
    version: str = ""                     # taxonomy + normalizer + prompt version

    def to_dict(self) -> dict:
        return {"key": self.key, "canonical_name": self.canonical_name,
                "category": self.category, "subcategory": self.subcategory,
                "attributes": dict(self.attributes),
                "grade": self.grade, "source": self.source, "version": self.version}

    @classmethod
    def from_dict(cls, d: dict) -> "MerchantRecord":
        return cls(key=d["key"], canonical_name=d.get("canonical_name", ""),
                   category=d.get("category", ""),
                   subcategory=d.get("subcategory", ""),
                   attributes=dict(d.get("attributes", {})),
                   grade=d.get("grade", "corroborated"),
                   source=d.get("source", "model"), version=d.get("version", ""))
