"""The ledger's event vocabulary (ADR-004: events are the source of truth).

Everything the ledger knows is an append-only sequence of these events. Balances
and every other view are *projections* — rebuildable at any time by replaying
the log (data-model-considerations.md, projection layer). Nothing here is ever
mutated: a correction is a new event, never an edit (T4).

Money is always ``Decimal``, carried as a string in the serialised form. A float
never touches an amount — the verification layer raises on floats by design, and
the ledger honours the same discipline at the source.

Four event types carry the whole v0 story:

  - ``AccountOpened``            — registers a value-holding relationship.
  - ``OpeningBalanceObserved``   — the statement's opening figure; projection
                                   seeds it as an Opening Balance Equity pair
                                   (the "unexplained history" bucket).
  - ``TransactionRecorded``      — money moved: a list of postings that sum to
                                   zero (double-entry), plus a free many-to-many
                                   ``tags`` overlay (empty in v0; the door for
                                   categorization's overlapping labels).
  - ``ClosingBalanceObserved``   — the statement's closing figure. NOT a posting
                                   — the postings already carry the account to
                                   this number; it is the reconciliation target
                                   and the citable source of the answer.

The opening/closing asymmetry is correct double-entry, not an oversight: opening
is an equity injection that seeds a balance from nothing; closing is an
assertion the transactions must already reconcile to. Posting both would
double-count.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from decimal import Decimal


# ------------------------------------------------------------------ provenance


@dataclass(frozen=True)
class Provenance:
    """Where a fact came from — the T1 spine. Every attested figure points back
    to an exact spot in a source document so an answer can tap through to it."""

    doc_id: str = ""
    page: int | None = None
    region: str = ""      # a bounding-box id or text anchor within the page
    note: str = ""

    def to_dict(self) -> dict:
        return {"doc_id": self.doc_id, "page": self.page,
                "region": self.region, "note": self.note}

    @classmethod
    def from_dict(cls, d: dict | None) -> "Provenance":
        d = d or {}
        return cls(doc_id=d.get("doc_id", ""), page=d.get("page"),
                   region=d.get("region", ""), note=d.get("note", ""))


# --------------------------------------------------------------------- grades

# The confidence a figure carries (data-model-considerations.md). Constructed by
# deterministic checks downstream, never self-reported by a model (ADR-010).
VERIFIED = "verified"          # directly attested by the issuer
CORROBORATED = "corroborated"  # two independent observations agree
UNVERIFIED = "unverified"      # asserted or derived, nothing has checked it
CONFLICTED = "conflicted"      # observations disagree — surfaced, never averaged
GRADES = (VERIFIED, CORROBORATED, UNVERIFIED, CONFLICTED)


# ------------------------------------------------------------------- postings


@dataclass(frozen=True)
class Posting:
    """One leg of a transaction: a signed change to one account.

    Convention: amounts are signed so that a transaction's postings sum to
    exactly zero (double-entry). An account's balance is the running sum of its
    postings' amounts. Each leg carries its own grade — the checking leg the
    statement attests is ``verified``; a counter-leg whose category we have not
    yet inferred (the Uncategorized bucket, deferred to categorization) is
    ``unverified``: the amount is known, the classification is not."""

    account: str
    amount: Decimal
    grade: str = UNVERIFIED

    def __post_init__(self) -> None:
        if isinstance(self.amount, float):
            raise TypeError(
                "Posting.amount must be Decimal, never float (T2): "
                "pass Decimal or str"
            )
        # Coerce str/int to Decimal so callers can be relaxed but storage is exact.
        if not isinstance(self.amount, Decimal):
            object.__setattr__(self, "amount", Decimal(self.amount))
        if self.grade not in GRADES:
            raise ValueError(f"unknown grade {self.grade!r}; expected one of {GRADES}")

    def to_dict(self) -> dict:
        return {"account": self.account, "amount": str(self.amount), "grade": self.grade}

    @classmethod
    def from_dict(cls, d: dict) -> "Posting":
        return cls(account=d["account"], amount=Decimal(d["amount"]),
                   grade=d.get("grade", UNVERIFIED))


# --------------------------------------------------------------------- events


@dataclass
class Event:
    """One thing that happened, as data. The store adds sequence, ingestion time
    (recorded_at), and hash-chaining on append; the domain fields live here.

    ``occurred_at`` is *value time* — when the money event happened, as the
    document dates it. Ingestion time is added by the store. Two timelines, kept
    apart from the start (bitemporality — free from ADR-004 if respected early).
    """

    event_type: str
    occurred_at: str                                   # ISO 8601 date/datetime
    body: dict = field(default_factory=dict)           # type-specific, JSON-safe
    provenance: Provenance = field(default_factory=Provenance)
    event_id: str = field(default_factory=lambda: uuid.uuid4().hex)

    def to_dict(self) -> dict:
        return {
            "event_type": self.event_type,
            "event_id": self.event_id,
            "occurred_at": self.occurred_at,
            "provenance": self.provenance.to_dict(),
            "body": self.body,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Event":
        return cls(
            event_type=d["event_type"],
            occurred_at=d["occurred_at"],
            body=d.get("body", {}),
            provenance=Provenance.from_dict(d.get("provenance")),
            event_id=d.get("event_id", uuid.uuid4().hex),
        )


# --- typed constructors (the only supported way to build a well-formed event) --


def account_opened(account_id: str, kind: str, name: str, currency: str,
                   occurred_at: str, jurisdiction: str = "US",
                   institution: str = "", account_number: str = "",
                   account_names: list[str] | None = None,
                   provenance: Provenance | None = None) -> Event:
    return Event(
        "AccountOpened", occurred_at,
        body={"account_id": account_id, "kind": kind, "name": name,
              "currency": currency, "jurisdiction": jurisdiction,
              "institution": institution, "account_number": account_number,
              "account_names": list(account_names or [])},
        provenance=provenance or Provenance(),
    )


def opening_balance_observed(account_id: str, amount: Decimal | str,
                             occurred_at: str,
                             provenance: Provenance | None = None) -> Event:
    return Event(
        "OpeningBalanceObserved", occurred_at,
        body={"account_id": account_id, "amount": str(Decimal(amount))},
        provenance=provenance or Provenance(),
    )


def closing_balance_observed(account_id: str, amount: Decimal | str,
                             occurred_at: str,
                             provenance: Provenance | None = None,
                             confirmed_by: str = "") -> Event:
    """``confirmed_by='human'`` marks a figure a person attested (e.g. after
    reviewing a held statement) — the projection grades that `verified`, the
    highest trust, above an arithmetic-only `corroborated`."""
    return Event(
        "ClosingBalanceObserved", occurred_at,
        body={"account_id": account_id, "amount": str(Decimal(amount)),
              "confirmed_by": confirmed_by},
        provenance=provenance or Provenance(),
    )


def statement_held(doc_id: str, facts_dict: dict, finding_dict: dict | None,
                   reason: str, occurred_at: str,
                   provenance: Provenance | None = None) -> Event:
    """A statement we read but did not post (it did not reconcile, or a gap).
    Persisted so the person can review and rule on it later — the claims-layer
    record of a read that is awaiting a human (T4: nothing lost, all replayable)."""
    return Event(
        "StatementHeld", occurred_at,
        body={"doc_id": doc_id, "reason": reason, "facts": facts_dict,
              "finding": finding_dict},
        provenance=provenance or Provenance(doc_id=doc_id),
    )


def correction_applied(doc_id: str, target: str, from_value: str,
                       to_value: str, occurred_at: str, by: str = "human",
                       provenance: Provenance | None = None) -> Event:
    """A person (or a forced identity) ruled on a figure. The correction is an
    event, never an overwrite — the full history stays replayable (T4)."""
    return Event(
        "CorrectionApplied", occurred_at,
        body={"doc_id": doc_id, "target": target, "from": from_value,
              "to": to_value, "by": by},
        provenance=provenance or Provenance(doc_id=doc_id),
    )


def document_captured(doc_id: str, filename: str, byte_len: int,
                      doc_type: str, doc_type_confidence: float,
                      occurred_at: str, provenance: Provenance | None = None) -> Event:
    """We now hold this file (raw-captured, encrypted). Recorded for *every*
    upload before any judgment about what it is (ADR-003 / T3). ``doc_type`` is a
    classification claim carrying confidence — it can be wrong, and a wrong label
    degrades to a visible conflict downstream, never a silent discard."""
    return Event(
        "DocumentCaptured", occurred_at,
        body={"doc_id": doc_id, "filename": filename, "byte_len": byte_len,
              "doc_type": doc_type, "doc_type_confidence": doc_type_confidence},
        provenance=provenance or Provenance(doc_id=doc_id),
    )


def account_alias_confirmed(alias_key: str, account_id: str, doc_id: str,
                            occurred_at: str, by: str = "human",
                            provenance: Provenance | None = None) -> Event:
    """A person ruled on an ambiguous account identity: the signal ``alias_key``
    resolves to ``account_id`` (which may be an existing account — a merge — or
    the key's own account — a confirmed 'new'). The identity map learns it, so
    the same pattern never asks again (T4: the ruling is an event, not an edit)."""
    return Event(
        "AccountAliasConfirmed", occurred_at,
        body={"alias_key": alias_key, "account_id": account_id,
              "doc_id": doc_id, "by": by},
        provenance=provenance or Provenance(doc_id=doc_id),
    )


def read_recorded(doc_id: str, model: str, prompt_version: str, input_mode: str,
                  response_text: str, cost_usd: float, input_tokens: int,
                  output_tokens: int, parse_ok: bool, parse_error: str | None,
                  occurred_at: str, provenance: Provenance | None = None) -> Event:
    """The claims layer (data-model-considerations.md): what a model asserted,
    verbatim, on one read — model + prompt version (T8), the raw response, and
    cost. Immutable and append-only. This is the raw-capture doctrine (ADR-003)
    applied to the reader's output, and the training-pair mine for the flywheel.

    The request is not stored: it is reconstructable from the captured raw
    document plus the versioned prompt, so we keep the response without
    duplicating megabytes of image data into the log."""
    return Event(
        "ReadRecorded", occurred_at,
        body={"doc_id": doc_id, "model": model, "prompt_version": prompt_version,
              "input_mode": input_mode, "response_text": response_text,
              "cost_usd": cost_usd, "input_tokens": input_tokens,
              "output_tokens": output_tokens, "parse_ok": parse_ok,
              "parse_error": parse_error},
        provenance=provenance or Provenance(doc_id=doc_id),
    )


def transaction_recorded(postings: list[Posting], description: str,
                         occurred_at: str, tags: list[str] | None = None,
                         provenance: Provenance | None = None) -> Event:
    return Event(
        "TransactionRecorded", occurred_at,
        body={
            "description": description,
            "postings": [p.to_dict() for p in postings],
            # The many-to-many overlapping-label overlay. Empty in v0; carrying
            # the field now means categorization needs no schema migration later.
            "tags": list(tags or []),
        },
        provenance=provenance or Provenance(),
    )


def postings_of(event: Event) -> list[Posting]:
    """Rebuild the Posting objects from a TransactionRecorded event."""
    return [Posting.from_dict(p) for p in event.body.get("postings", [])]
