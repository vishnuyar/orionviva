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


# --- how an account came to exist (Slice 9a, decision A3) -------------------
# Every account before this slice was born from a document an ISSUER produced —
# a bank statement, a pay stub, a brokerage report. Slice 9a introduces accounts
# born from a SENTENCE ("I bought a car"), whose only witness is the person.
#
# That distinction is capturable ONLY at write time, and it is the difference
# between a ledger that can vouch for you to a counterparty and one that cannot:
# an asserted account is not evidence the way a statement is. Recording it costs
# a string today and is unrecoverable later, so it is recorded from the start.
#
# It is also a LADDER, not a label. The corroboration ask (invoice, 1098,
# closing disclosure, loan statement) is precisely the path from `asserted` to
# `issued`, and a document arriving upgrades the account in place.
ISSUED = "issued"        # a document from an issuer attests this account exists
ASSERTED = "asserted"    # only the person says so — honest, and not yet provable
ORIGINS = (ISSUED, ASSERTED)


def account_opened(account_id: str, kind: str, name: str, currency: str,
                   occurred_at: str, jurisdiction: str = "US",
                   institution: str = "", account_number: str = "",
                   account_names: list[str] | None = None,
                   origin: str = ISSUED,
                   provenance: Provenance | None = None) -> Event:
    """Register a value-holding relationship.

    ``origin`` (Slice 9a, A3) records *who says this account exists* — see the
    ORIGINS note above. It defaults to ``issued`` so every existing call site,
    all of which are driven by a real document, keeps its present meaning."""
    if origin not in ORIGINS:
        raise ValueError(f"origin must be one of {ORIGINS}, got {origin!r}")
    return Event(
        "AccountOpened", occurred_at,
        body={"account_id": account_id, "kind": kind, "name": name,
              "currency": currency, "jurisdiction": jurisdiction,
              "institution": institution, "account_number": account_number,
              "account_names": list(account_names or []),
              "origin": origin},
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
                  occurred_at: str, provenance: Provenance | None = None,
                  phase: str = "extract") -> Event:
    """The claims layer (data-model-considerations.md): what a model asserted,
    verbatim, on one read — model + prompt version (T8), the raw response, and
    cost. Immutable and append-only. This is the raw-capture doctrine (ADR-003)
    applied to the reader's output, and the training-pair mine for the flywheel.

    A two-phase read records one of these per phase: ``phase='classify'`` (the
    cheap type decision) and ``phase='extract'`` (the figures). Each carries its
    own prompt version and cost, so nothing a model did is thrown away.

    The request is not stored: it is reconstructable from the captured raw
    document plus the versioned prompt, so we keep the response without
    duplicating megabytes of image data into the log."""
    return Event(
        "ReadRecorded", occurred_at,
        body={"doc_id": doc_id, "model": model, "prompt_version": prompt_version,
              "input_mode": input_mode, "response_text": response_text,
              "cost_usd": cost_usd, "input_tokens": input_tokens,
              "output_tokens": output_tokens, "parse_ok": parse_ok,
              "parse_error": parse_error, "phase": phase},
        provenance=provenance or Provenance(doc_id=doc_id),
    )


def transfer_linked(movement_a: str, movement_b: str, grade: str,
                    evidence: dict, occurred_at: str, by: str = "auto",
                    provenance: Provenance | None = None) -> Event:
    """Assert that two movements (referenced by stable movement key) are one
    internal transfer — a graded, evidenced *relationship* over two existing
    postings (data-model-considerations.md). It is an OVERLAY: neither leg is
    re-posted, so each statement still reconciles on its own. Aggregates that
    measure spending exclude a linked movement. ``by='auto'`` for a decisive
    match, ``'human'`` for a confirmed one (which the projection grades higher).
    Reversible via ``transfer_unlinked`` (T4 — a ruling is an event, not an edit)."""
    return Event(
        "TransferLinked", occurred_at,
        body={"a": movement_a, "b": movement_b, "grade": grade,
              "evidence": evidence, "by": by, "status": "linked"},
        provenance=provenance or Provenance(),
    )


def transfer_unlinked(movement_a: str, movement_b: str, occurred_at: str,
                      by: str = "human", provenance: Provenance | None = None) -> Event:
    """Revoke a transfer link (a person said 'these are not the same money').
    Append-only: the link's history stays replayable; the projection stops
    treating the pair as a transfer."""
    return Event(
        "TransferUnlinked", occurred_at,
        body={"a": movement_a, "b": movement_b, "by": by, "status": "unlinked"},
        provenance=provenance or Provenance(),
    )


def transfer_suggested(movement_a: str, candidates: list[str], evidence: dict,
                       occurred_at: str, provenance: Provenance | None = None) -> Event:
    """A transfer we suspect but cannot force — ``movement_a`` looks like an
    internal transfer, but the counterpart is ambiguous (several candidates) or
    the destination account isn't confirmed yours. Surfaced for a human ruling;
    NOTHING is netted until confirmed (never bluff — principle 2)."""
    return Event(
        "TransferSuggested", occurred_at,
        body={"a": movement_a, "candidates": list(candidates),
              "evidence": evidence, "status": "suggested"},
        provenance=provenance or Provenance(),
    )


def category_assigned(movement_key: str, descriptor: str, category: str,
                      grade: str, occurred_at: str, by: str = "human",
                      nature: str = "",
                      provenance: Provenance | None = None) -> Event:
    """Assign a category to one movement — a graded OVERLAY via correction-as-event
    (Slice 5), keyed to the stable movement key so it survives a reingest and
    never mutates the read. ``by='model'`` is a suggestion graded ``unverified``;
    ``by='human'`` is a confirmation graded ``verified`` (the moat). ``descriptor``
    is the movement's raw merchant string, captured deliberately so merchant
    learning is later a projection over these events — no re-ingestion, nothing
    wasted (Vishnu, 2026-07-24).

    ``nature`` (Slice 6.5, optional) records what the movement *is* — `spending`,
    `transfer`, or `settlement`. Carried here rather than in a new event type, so
    the honest-aggregates work stays a read-side change over events we already
    write; a person's ruling outranks any category hint when nature is derived."""
    return Event(
        "CategoryAssigned", occurred_at,
        body={"movement_key": movement_key, "descriptor": descriptor,
              "category": category, "grade": grade, "by": by,
              "nature": nature},
        provenance=provenance or Provenance(),
    )


# --------------------------------------------------- the ruling (Slice 9a, A1)
#
# The FOUR MAJORS — the complete answer space for "what is this movement's
# counter-leg?", and the vocabulary a person's sentence is interpreted into.
# Closed and universal (I5); everything BELOW a major is free data.
#
# Equity is deliberately absent: for a person, equity IS net worth (assets minus
# liabilities), so it is derived and never asserted. `Equity:OpeningBalance`
# stays system-generated for genuinely unexplained history.
#
# These are stored, never spoken (decision D1). The surface always asks in plain
# language — "do you still have it, in another form?" — and a person never types
# an accounting term to use this product.
MAJOR_EXPENSE = "expense"        # money spent, gone
MAJOR_ASSET = "asset"            # you still have it, in another form
MAJOR_LIABILITY = "liability"    # what you owe changed
MAJOR_INCOME = "income"          # money that arrived
MAJORS = (MAJOR_EXPENSE, MAJOR_ASSET, MAJOR_LIABILITY, MAJOR_INCOME)

# What a ruling is ABOUT. Scope is the whole reason this is one generic event
# rather than a fourth narrow one: the same ruling mechanism has to say "this
# transaction", "this merchant, always", and "this account" without multiplying
# event types (Move 3, earned here — see from-your-words-to-the-ledger.md, A1).
SCOPE_MOVEMENT = "movement"      # subject = a stable movement key
SCOPE_MERCHANT = "merchant"      # subject = a normalized merchant (generalizes)
SCOPE_ACCOUNT = "account"        # subject = an account id
# Slice 7.5: subject = a category or subcategory LABEL, and `same_as` names the
# one it is really the same as. A label is not a thing in the world — it is a
# name for a thing — so two names meaning one thing is not a data error to be
# scrubbed but a fact to be recorded, once, and applied on the read side
# forever after. History is never rewritten: "playing poker" stays in the event
# that recorded it, and every total folds it into "poker" from now on.
SCOPE_CATEGORY = "category"
SCOPE_TAG = "tag"                # same, in the TAG vocabulary (kept apart: a
                                 # tag "poker" and a category "poker" are
                                 # different things and must alias separately)
SCOPES = (SCOPE_MOVEMENT, SCOPE_MERCHANT, SCOPE_ACCOUNT, SCOPE_CATEGORY,
          SCOPE_TAG)


def ruling_recorded(scope: str, subject: str, occurred_at: str,
                    legs: list[dict] | None = None, by: str = "human",
                    grade: str = VERIFIED, said: str = "",
                    corroborates: str = "", prompt_version: str = "",
                    same_as: str = "",
                    provenance: Provenance | None = None) -> Event:
    """A person's ruling about what something *is* — the generic, scoped event
    that Move 3 deferred and Slice 9a earns (A1).

    ``legs`` are the counter-legs this movement's money goes to, each
    ``{"major": <one of MAJORS>, "account": "Liabilities:Mortgage:Acme",
    "share": ""}``. One leg is the ordinary case. Several legs is a compound
    payment — a mortgage is interest *and* principal *and* escrow at once.

    **A leg may carry no ``share``, and that is a first-class outcome, not a
    failure.** The interest/principal/escrow split is printed on a statement
    neither party has; guessing it would put a wrong number in a finance app.
    So an unshared multi-leg ruling means: *these are the components, in this
    order of certainty, proportions unknown.* The projection records the account
    and holds the DECOMPOSITION provisional — the cash movement itself is a
    measured fact and is never held hostage to a missing document.

    ``said`` keeps the person's own sentence verbatim (T3), so a better model
    can re-derive a richer reading later without ever asking them again, and
    ``prompt_version`` records the exact instructions that read it (T8) — so
    tuning the prompt never silently reinterprets what someone already said.
    ``corroborates`` names a document that would *prove* this — an invoice, a
    1098, a closing disclosure. It is a suggestion, never a gate (Vishnu,
    2026-07-25): the account is already created and the cash already posted.

    NO AMOUNT APPEARS HERE, by design. Amounts come from the movement the ruling
    is about. A model interprets meaning and never supplies a figure (T2 /
    ADR-010) — the one place that boundary could leak is this event, so it is
    closed structurally rather than by prompt."""
    if scope not in SCOPES:
        raise ValueError(f"scope must be one of {SCOPES}, got {scope!r}")
    if not subject:
        raise ValueError("a ruling must name its subject")
    clean: list[dict] = []
    for leg in (legs or []):
        major = leg.get("major", "")
        if major not in MAJORS:
            raise ValueError(f"leg major must be one of {MAJORS}, got {major!r}")
        if "amount" in leg:
            raise ValueError("a ruling carries no amount — it comes from the movement")
        clean.append({"major": major, "account": leg.get("account", ""),
                      "share": str(leg.get("share", ""))})
    return Event(
        "RulingRecorded", occurred_at,
        body={"scope": scope, "subject": subject, "legs": clean, "by": by,
              "grade": grade, "said": said, "corroborates": corroborates, "same_as": same_as,
              "prompt_version": prompt_version},
        provenance=provenance or Provenance(),
    )


def merchant_categorized(merchant: str, category: str, grade: str,
                         occurred_at: str, by: str = "model",
                         provenance: Provenance | None = None) -> Event:
    """Categorize a normalized MERCHANT (Slice 5.5) — the prior that fills every
    transaction from it, past and future. ``by='model'`` (a batched call) is a
    graded suggestion (`unverified`/`corroborated`); ``by='human'`` ("categorize
    this merchant everywhere") is `verified`. A per-transaction CategoryAssigned
    override still wins. Append-only; the merchant catalog is a projection over
    these + imported commons priors, and the source of truth stays the log."""
    return Event(
        "MerchantCategorized", occurred_at,
        body={"merchant": merchant, "category": category, "grade": grade,
              "by": by},
        provenance=provenance or Provenance(),
    )


def merchant_enriched(merchant: str, category: str, subcategory: str = "",
                      canonical_name: str = "", attributes: dict | None = None,
                      grade: str = "corroborated", occurred_at: str = "",
                      by: str = "model", provenance: Provenance | None = None) -> Event:
    """The product's applied record of a merchantcore enrichment (Slice 5.6): a
    merchant's primary category, a finer ``subcategory``, and richer attributes
    (logo, mcc, website) synced in from the knowledge package as an event, so the
    ledger stays self-contained (T4) — a replay reproduces the categorization
    with merchantcore absent. The richer sibling of `MerchantCategorized`; both
    feed the same catalog projection with grade precedence."""
    return Event(
        "MerchantEnriched", occurred_at,
        body={"merchant": merchant, "category": category,
              "subcategory": subcategory, "canonical_name": canonical_name,
              "attributes": dict(attributes or {}), "grade": grade, "by": by},
        provenance=provenance or Provenance(),
    )


def position_observed(account_id: str, instrument: str, units: Decimal | str,
                      market_value: Decimal | str, currency: str, occurred_at: str,
                      cost_basis: Decimal | str | None = None,
                      valuation_class: str = "measured", grade: str = CORROBORATED,
                      provenance: Provenance | None = None) -> Event:
    """A holding *measured* at the statement date (Slice 6) — a unit quantity of an
    instrument and its value, NOT a posting. A brokerage account changes value when
    the market reprices holdings already owned, with no money moving; that is a
    revaluation, not a transaction, so it is recorded as a dated measurement (like
    ``ClosingBalanceObserved`` measures a balance) and never posted (M1: cash-flow
    over accrual — only realized cash flows post). Append-only: next period emits a
    NEW measurement for the same instrument; the projection reads the latest as-of.
    ``valuation_class`` is ``measured`` here (a statement value at its date); the
    unrealized gain (market_value − cost_basis) is a derived presentation view, never
    a ledger fact. ``cost_basis`` is optional (absent when the statement omits it —
    never invented)."""
    body = {"account_id": account_id, "instrument": instrument,
            "units": str(Decimal(units)), "market_value": str(Decimal(market_value)),
            "currency": currency, "valuation_class": valuation_class, "grade": grade}
    body["cost_basis"] = "" if cost_basis in (None, "") else str(Decimal(cost_basis))
    return Event("PositionObserved", occurred_at, body=body,
                 provenance=provenance or Provenance())


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


# --- tags (Slice 7.6) --------------------------------------------------------
#
# The rule from discovery, finally built: **double-entry governs the money (one
# balanced truth, verifiable); tags govern the meaning (freely multiple,
# user-owned, the moat).**
#
# A CATEGORY is a PARTITION — exactly one per movement, so the parts sum to the
# whole and "where did my money go?" is checkable. A TAG is an OVERLAY — many
# per movement, overlapping, and tag totals deliberately DO NOT sum to spending.
# Mixing them yields a report whose parts do not add up to its total, which in
# this product is a bluff.
#
# WHY ITS OWN EVENT rather than a field on CategoryAssigned. Two reasons, and
# the second is the important one:
#
#   * different lifecycles — a tag is added without re-ruling the category, and
#     a combined event would re-assert a category on every tag edit.
#   * different PRIVACY. A category is shareable world knowledge: a merchant IS
#     a coffee shop, for everyone, which is why a commons can hold one. A tag is
#     personal meaning — this coffee was on the Japan trip, this withdrawal was
#     poker night — which no commons can ever know. Keeping tags in their own
#     event type makes "tags never leave this device" an EVENT-LEVEL rule (T9)
#     instead of a per-field check inside an event that is itself shareable.
#     Event-level rules are much harder to get wrong by accident.

MOVEMENT_TAGGED = "MovementTagged"


def movement_tagged(subject: str, tags: list, occurred_at: str,
                    scope: str = SCOPE_MOVEMENT, by: str = "human",
                    provenance: Provenance | None = None) -> Event:
    """Tag one movement, or every movement from a merchant.

    ``tags`` is the COMPLETE set for that subject, not a delta — last write
    wins, so removing a tag is appending the set without it. Replay stays
    trivial and the log stays append-only; there is no "untag" event to
    reconcile against an "add" that arrived out of order.

    Merchant scope exists so "everything from this gym is martial arts" is one
    ruling rather than forty. The Slice 5.5 rule still binds: a peer descriptor
    does not generalize, because one payment to a friend is a gift and the next
    is a loan repayment."""
    if scope not in (SCOPE_MOVEMENT, SCOPE_MERCHANT):
        raise ValueError(f"a tag applies to a movement or a merchant, got {scope!r}")
    clean = sorted({t.strip().lower() for t in (tags or []) if t and t.strip()})
    return Event(
        MOVEMENT_TAGGED, occurred_at,
        body={"subject": subject, "scope": scope, "tags": clean, "by": by},
        provenance=provenance or Provenance(),
    )


# --------------------------------------------------------------------------
# Slice 6.10 — the decline: "not now" is an answer, and it is remembered.
#
# The queue's rule is settled → silence. A decline extends that rule to the
# QUESTIONS themselves: a person who set something aside has told us something,
# and asking again tomorrow would be forgetting it — the nag the persona
# exists to never be (principle 6: you direct the pace).
#
# WHY A SNAPSHOT INSTEAD OF A TIMER. Silence-until-a-date is arbitrary and
# jurisdiction-of-the-mind stuff — why three days and not ten? The honest
# trigger is NEW EVIDENCE: the question stays quiet while it would say exactly
# what it said before, and returns the moment its stake changes (a new
# statement adds movements; the amount or count moves). So the event records
# the stake the question showed when declined, and the queue compares.
#
# The amount here is NOT a claim about money (T2 is untouched) — it is a
# fingerprint of the question as asked, computed by the same deterministic
# projection that asked it.

QUESTION_DECLINED = "QuestionDeclined"

DECLINE_NOT_NOW = "not_now"        # "set it aside" — respected until new evidence
DECLINE_DONT_KNOW = "dont_know"    # "I don't know" — reassured, same silence
DECLINE_REASONS = (DECLINE_NOT_NOW, DECLINE_DONT_KNOW)


def question_declined(question_id: str, kind: str, occurred_at: str,
                      reason: str = DECLINE_NOT_NOW, amount: str = "",
                      count: int = 0, pack_version: str = "",
                      by: str = "human",
                      provenance: Provenance | None = None) -> Event:
    """The person set a question aside — recorded so it stays set aside.

    ``question_id`` is the queue's stable id (derived from what the question is
    about, not from event ids). ``amount``/``count`` snapshot the stake shown
    at decline time. ``pack_version`` records which voice asked — the same
    discipline as ``prompt_version``: a recorded version must keep resolving."""
    if reason not in DECLINE_REASONS:
        raise ValueError(f"reason must be one of {DECLINE_REASONS}, got {reason!r}")
    if not question_id:
        raise ValueError("a decline must name the question it sets aside")
    return Event(
        QUESTION_DECLINED, occurred_at,
        body={"question_id": question_id, "kind": kind, "reason": reason,
              "amount": str(amount), "count": int(count),
              "pack_version": pack_version, "by": by},
        provenance=provenance or Provenance(),
    )
