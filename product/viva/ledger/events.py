"""The ledger's event vocabulary — events are the source of truth.

Everything the ledger knows is an append-only sequence of these events. Balances
and every other view are *projections*, rebuilt by replaying the log. Nothing
here is mutated: a correction is a new event.

Money is always ``Decimal``, carried as a string in the serialised form; a float
is rejected at construction.

Four event types carry the core story:

  - ``AccountOpened``            — registers a value-holding relationship.
  - ``OpeningBalanceObserved``   — the statement's opening figure; the projection
                                   seeds it as an Opening Balance Equity pair.
  - ``TransactionRecorded``      — money moved: a list of postings that sum to
                                   zero (double-entry), plus a many-to-many
                                   ``tags`` overlay.
  - ``ClosingBalanceObserved``   — the statement's closing figure. Not a posting:
                                   it is the reconciliation target the period's
                                   transactions must already reach, and the
                                   citable source of the answer.
"""

from __future__ import annotations

import re
import unicodedata
import uuid
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from .streams import IN, OUT


# ------------------------------------------------------------------ provenance


@dataclass(frozen=True)
class Provenance:
    """Where a fact came from: the document, page and region of a source an
    attested figure points back to, plus a free-text note."""

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

# The confidence a figure carries. Set by deterministic checks downstream,
# never self-reported by a model.
VERIFIED = "verified"          # directly attested by the issuer
CORROBORATED = "corroborated"  # two independent observations agree
UNVERIFIED = "unverified"      # asserted or derived, nothing has checked it
CONFLICTED = "conflicted"      # observations disagree — surfaced, never averaged
GRADES = (VERIFIED, CORROBORATED, UNVERIFIED, CONFLICTED)


# ------------------------------------------------------------------- postings


@dataclass(frozen=True)
class Posting:
    """One leg of a transaction: a signed change to one account.

    Amounts are signed so that a transaction's postings sum to exactly zero, and
    an account's balance is the running sum of its postings' amounts. Each leg
    carries its own grade: the leg a statement attests is ``verified``, while an
    Uncategorized counter-leg is ``unverified`` — its amount is known, its
    classification is not.

    ``amount`` accepts ``str`` or ``int`` and coerces to ``Decimal``. Raises
    TypeError on a float and ValueError on a grade outside ``GRADES``."""

    account: str
    amount: Decimal
    grade: str = UNVERIFIED

    def __post_init__(self) -> None:
        if isinstance(self.amount, float):
            raise TypeError(
                "Posting.amount must be Decimal, never float (T2): "
                "pass Decimal or str"
            )
        # Coerce str/int to Decimal so storage is exact.
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
    """One thing that happened, as data. The domain fields live here; the store
    adds sequence, ingestion time (``recorded_at``) and hash-chaining on append.

    ``occurred_at`` is *value time* — when the money event happened, as the
    document dates it. The two timelines are kept apart.
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


# --- how an account came to exist -------------------------------------------
# Who says an account exists: a document an issuer produced, or the person
# alone. A document arriving later upgrades an asserted account in place.
ISSUED = "issued"        # a document from an issuer attests this account exists
ASSERTED = "asserted"    # only the person says so
ORIGINS = (ISSUED, ASSERTED)


def account_opened(account_id: str, kind: str, name: str, currency: str,
                   occurred_at: str, jurisdiction: str = "",
                   institution: str = "", account_number: str = "",
                   account_names: list[str] | None = None,
                   origin: str = ISSUED,
                   provenance: Provenance | None = None) -> Event:
    """Register a value-holding relationship.

    ``origin`` records who says this account exists, one of ``ORIGINS``; it
    defaults to ``issued``. Raises ValueError on any other value.

    ``jurisdiction`` is where the INSTRUMENT lives — not where the person
    lives, and not its currency. It defaults to empty, meaning *nobody has
    said*: a default naming one country would put a fact in the ledger that no
    document and no person ever stated, and every reader would then treat a
    guess as attested."""
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
    """``confirmed_by='human'`` marks a figure a person attested, e.g. after
    reviewing a held statement; the projection grades that `verified` rather
    than the arithmetic-only `corroborated`."""
    return Event(
        "ClosingBalanceObserved", occurred_at,
        body={"account_id": account_id, "amount": str(Decimal(amount)),
              "confirmed_by": confirmed_by},
        provenance=provenance or Provenance(),
    )


def statement_held(doc_id: str, facts_dict: dict, finding_dict: dict | None,
                   reason: str, occurred_at: str,
                   provenance: Provenance | None = None) -> Event:
    """A statement that was read but not posted — ``reason`` says why (it did
    not reconcile, or there is a gap). The body keeps the extracted ``facts``
    and the ``finding``, so it can be reviewed and ruled on later."""
    return Event(
        "StatementHeld", occurred_at,
        body={"doc_id": doc_id, "reason": reason, "facts": facts_dict,
              "finding": finding_dict},
        provenance=provenance or Provenance(doc_id=doc_id),
    )


def brokerage_activity_held(doc_id: str, facts_dict: dict,
                            finding_dict: dict | None, occurred_at: str,
                            provenance: Provenance | None = None) -> Event:
    """Record a posted brokerage snapshot's quarantined activity stream."""
    return Event(
        "BrokerageActivityHeld", occurred_at,
        body={"doc_id": doc_id, "reason": "activity", "facts": facts_dict,
              "finding": finding_dict},
        provenance=provenance or Provenance(doc_id=doc_id),
    )


def brokerage_activity_resolved(doc_id: str, occurred_at: str,
                                provenance: Provenance | None = None) -> Event:
    """Close one durable brokerage-activity hold after corrected replay."""
    return Event(
        "BrokerageActivityResolved", occurred_at,
        body={"doc_id": doc_id},
        provenance=provenance or Provenance(doc_id=doc_id),
    )


def correction_applied(doc_id: str, target: str, from_value: str,
                       to_value: str, occurred_at: str, by: str = "human",
                       provenance: Provenance | None = None) -> Event:
    """A ruling on a figure: ``target`` moves from ``from_value`` to
    ``to_value``, attributed to ``by``. Appended, never an overwrite."""
    return Event(
        "CorrectionApplied", occurred_at,
        body={"doc_id": doc_id, "target": target, "from": from_value,
              "to": to_value, "by": by},
        provenance=provenance or Provenance(doc_id=doc_id),
    )


def document_captured(doc_id: str, filename: str, byte_len: int,
                      doc_type: str, doc_type_confidence: float,
                      occurred_at: str, provenance: Provenance | None = None) -> Event:
    """This file is now held (raw-captured, encrypted). Recorded for every
    upload, before any judgment about what it is. ``doc_type`` is a
    classification claim carrying ``doc_type_confidence``; it can be wrong, and
    a wrong label surfaces as a conflict downstream rather than a discard."""
    return Event(
        "DocumentCaptured", occurred_at,
        body={"doc_id": doc_id, "filename": filename, "byte_len": byte_len,
              "doc_type": doc_type, "doc_type_confidence": doc_type_confidence},
        provenance=provenance or Provenance(doc_id=doc_id),
    )


def account_alias_confirmed(alias_key: str, account_id: str, doc_id: str,
                            occurred_at: str, by: str = "human",
                            provenance: Provenance | None = None) -> Event:
    """A ruling on an ambiguous account identity: the signal ``alias_key``
    resolves to ``account_id``, which may be an existing account (a merge) or
    the key's own account (a confirmed 'new'). The projection's identity map
    reads these, so the same pattern is not asked about again."""
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
                  phase: str = "extract", resolved_model: str = "",
                  usage_reported: bool | None = None) -> Event:
    """What a model asserted, verbatim, on one read: configured and reported
    model identities, prompt version, input mode, raw response text, cost,
    provider-reported token counts where present, and parse status.

    A two-phase read records one of these per phase — ``phase='classify'`` (the
    type decision) and ``phase='extract'`` (the figures) — each with its own
    prompt version and cost.

    The request is not stored; it is reconstructable from the captured raw
    document plus the versioned prompt."""
    body = {"doc_id": doc_id, "model": model,
            # This marker makes `model` a configured route. Without it, readers
            # treat the field's role as unknown.
            "model_role": "configured_route",
            "prompt_version": prompt_version, "input_mode": input_mode,
            "response_text": response_text, "cost_usd": cost_usd,
            "parse_ok": parse_ok, "parse_error": parse_error,
            "phase": phase}
    # The configured route and the provider's reported model are separate audit
    # facts; the reported field is omitted when the provider supplies none.
    if resolved_model:
        body["resolved_model"] = resolved_model
    # Positive counters without an explicit marker count as measured usage;
    # zero requires the marker because an adapter default is not a measurement.
    measured = (usage_reported is True
                or (usage_reported is None
                    and (input_tokens > 0 or output_tokens > 0)))
    if measured:
        body.update({"input_tokens": input_tokens,
                     "output_tokens": output_tokens,
                     "usage_reported": True})
    return Event("ReadRecorded", occurred_at, body=body,
                 provenance=provenance or Provenance(doc_id=doc_id))


def transfer_linked(movement_a: str, movement_b: str, grade: str,
                    evidence: dict, occurred_at: str, by: str = "auto",
                    provenance: Provenance | None = None) -> Event:
    """Assert that two movements, referenced by stable movement key, are one
    internal transfer — a graded, evidenced relationship over two existing
    postings.

    An overlay: neither leg is re-posted, so each statement still reconciles on
    its own, and aggregates that measure spending exclude a linked movement.
    ``by='auto'`` for a decisive match, ``'human'`` for a confirmed one, which
    the projection grades higher. Reversed by ``transfer_unlinked``."""
    return Event(
        "TransferLinked", occurred_at,
        body={"a": movement_a, "b": movement_b, "grade": grade,
              "evidence": evidence, "by": by, "status": "linked"},
        provenance=provenance or Provenance(),
    )


def transfer_unlinked(movement_a: str, movement_b: str, occurred_at: str,
                      by: str = "human", provenance: Provenance | None = None) -> Event:
    """Revoke a transfer link. Append-only: the link's history stays replayable
    and the projection stops treating the pair as a transfer."""
    return Event(
        "TransferUnlinked", occurred_at,
        body={"a": movement_a, "b": movement_b, "by": by, "status": "unlinked"},
        provenance=provenance or Provenance(),
    )


def transfer_suggested(movement_a: str, candidates: list[str], evidence: dict,
                       occurred_at: str, provenance: Provenance | None = None) -> Event:
    """``movement_a`` looks like an internal transfer whose counterpart is not
    decisive: several ``candidates``, or a destination not confirmed as the
    person's. Surfaced for a ruling; nothing is netted out of spending until a
    link is confirmed."""
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
    """Assign a category to one movement — a graded overlay, keyed to the stable
    movement key so it survives a reingest and never mutates the read.

    ``by='model'`` is a suggestion graded ``unverified``; ``by='human'`` a
    confirmation graded ``verified``. ``descriptor`` is the movement's raw
    merchant string, so merchant learning is a projection over these events.

    ``nature`` (optional) records what the movement *is* — `spending`,
    `transfer`, or `settlement`. A person's ruling outranks any category hint
    when nature is derived."""
    return Event(
        "CategoryAssigned", occurred_at,
        body={"movement_key": movement_key, "descriptor": descriptor,
              "category": category, "grade": grade, "by": by,
              "nature": nature},
        provenance=provenance or Provenance(),
    )


# ---------------------------------------------------------------- the ruling
#
# The four majors — the answer space for "what is this movement's counter-leg?",
# and the vocabulary a person's sentence is interpreted into. Closed; everything
# below a major is free data. Equity is absent: for a person equity is net worth
# (assets minus liabilities), so it is derived rather than asserted, and
# `Equity:OpeningBalance` stays system-generated.
#
# These are stored, never spoken: the surface asks in plain language.
MAJOR_EXPENSE = "expense"        # money spent, gone
MAJOR_ASSET = "asset"            # you still have it, in another form
MAJOR_LIABILITY = "liability"    # what you owe changed
MAJOR_INCOME = "income"          # money that arrived
MAJORS = (MAJOR_EXPENSE, MAJOR_ASSET, MAJOR_LIABILITY, MAJOR_INCOME)

# What a ruling is ABOUT — one generic event covers all of these scopes.
SCOPE_MOVEMENT = "movement"      # subject = a stable movement key
SCOPE_MERCHANT = "merchant"      # subject = a normalized merchant (generalizes)
SCOPE_ACCOUNT = "account"        # subject = an account id
# Subject = a category or subcategory LABEL, and `same_as` names the one it is
# really the same as. Applied on the read side: the recorded history keeps the
# original label and every total folds it into the target from then on.
SCOPE_CATEGORY = "category"
SCOPE_TAG = "tag"                # the same, in the TAG vocabulary, which
                                 # aliases separately from categories
# Subject = "<account>:<key>" — one thing the person told us about an account
# they hold. The value is what they said it is; a document arriving later
# raises its grade without rewriting it.
SCOPE_ATTRIBUTE = "attribute"
# Subject = "<merchant key>|<direction>" — what kind of arrangement a person
# holds with one counterparty, one way round. The value carries the confirmed
# periodicities. Never a rail and never a stream key.
SCOPE_RHYTHM = "rhythm"
SCOPES = (SCOPE_MOVEMENT, SCOPE_MERCHANT, SCOPE_ACCOUNT, SCOPE_CATEGORY,
          SCOPE_TAG, SCOPE_ATTRIBUTE, SCOPE_RHYTHM)

# The directions a rhythm subject may name: the two the ledger measures.
RHYTHM_DIRECTIONS = (IN, OUT)

# What a rhythm ruling may say. Closed, and stored rather than spoken.
# `one_time` and `irregular` are confirmations like the other two: a
# relationship a person says has no rhythm is settled, not deferred.
PERIOD_MONTHLY = "monthly"
PERIOD_ANNUAL = "annual"
PERIOD_ONE_TIME = "one_time"
PERIOD_IRREGULAR = "irregular"
PERIODICITIES = (PERIOD_MONTHLY, PERIOD_ANNUAL, PERIOD_ONE_TIME,
                 PERIOD_IRREGULAR)

# One relationship can hold several arrangements at once, so the value is a
# set rather than a word, written as one string in a fixed order.
_PERIODICITY_SEPARATOR = "+"

# What separates the counterparty from the direction in a rhythm subject.
_RHYTHM_SEPARATOR = "|"


def rhythm_subject(merchant: str, direction: str) -> str:
    """The subject a rhythm ruling about one counterparty, one way round, is
    recorded under. The one definition of the format."""
    return f"{merchant}{_RHYTHM_SEPARATOR}{direction}"


def rhythm_parts(subject: str) -> tuple:
    """`(merchant key, direction)` for a rhythm subject; `("", "")` for
    anything that is not one."""
    merchant, sep, direction = str(subject or "").partition(_RHYTHM_SEPARATOR)
    return (merchant, direction) if sep and merchant and direction else ("", "")


def periodicity_value(periods) -> str:
    """The confirmed periodicities as one value, deduplicated and in the
    vocabulary's own order, so one answer has one written form.

    Words outside ``PERIODICITIES`` are kept as given: what the ledger will
    accept is decided by the guard in `ruling_recorded`, not here."""
    said = [str(p or "").strip() for p in periods]
    known = [p for p in PERIODICITIES if p in said]
    rest = sorted({p for p in said if p and p not in PERIODICITIES})
    return _PERIODICITY_SEPARATOR.join(known + rest)


def periodicities_in(value: str) -> tuple:
    """Every periodicity a rhythm value carries, in the order it was written."""
    return tuple(p for p in str(value or "").split(_PERIODICITY_SEPARATOR) if p)


def _canonical_number(text: str) -> str:
    """A number as a comparable string: Unicode digits folded to ASCII,
    grouping separators dropped, a purely-zero fractional part dropped.

    ``250,000``, ``2,50,000``, ``٢٥٠٠٠٠`` and ``250000.00`` all canonicalize to
    ``250000``. Returns '' for anything that is not a single number."""
    raw = str(text).strip().lstrip("+-")
    folded = []
    for ch in raw:
        if ch.isdigit():
            folded.append(str(unicodedata.digit(ch)))
        elif ch in ",. '  ’":
            folded.append(ch if ch == "." else "")
        else:
            return ""
    text = "".join(folded)
    if not text or not text.replace(".", "", 1).isdigit():
        return ""
    if "." in text:
        whole, _, frac = text.partition(".")
        frac = frac.rstrip("0")
        text = f"{whole}.{frac}" if frac else whole
    return text.lstrip("0") or "0"


def _numbers_said(said: str) -> set:
    """Every number that appears in a sentence, canonicalized.

    Whole tokens, not a run of digits: a value has to be a number the person
    actually wrote, so ``250000`` cannot be assembled out of ``250`` and
    ``3,000``, and ``1,250,000`` is not a place where ``250000`` was said."""
    out = set()
    # Split on anything that is not a digit in ANY script or a grouping
    # separator: the pack ships more than one country, so the numerals a
    # person types are not only the ASCII ones.
    for token in re.split(r"[^\d.,'\xa0\u202f\u2019]+", str(said or ""),
                          flags=re.UNICODE):
        number = _canonical_number(token.strip(".,"))
        if number:
            out.add(number)
    return out


_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def _numbers_in(value: str) -> set:
    """Every number a VALUE carries. A value is checked number by number, not
    by whether the whole of it looks like one — otherwise a currency symbol, a
    unit or an exponent would be enough to skip the check entirely."""
    return _numbers_said(value)


def _is_finite(value: str) -> bool:
    """False for a value that reads as a number but is not one — ``NaN``,
    ``Infinity``. These are the values that cannot be refused later: an
    append-only log has no delete, so one of them in a ledger breaks every
    reading of it, for ever."""
    try:
        number = Decimal(str(value).strip())
    except Exception:                                  # noqa: BLE001 - not a number
        return True
    return number.is_finite()


def ruling_recorded(scope: str, subject: str, occurred_at: str,
                    legs: list[dict] | None = None, by: str = "human",
                    grade: str = VERIFIED, said: str = "",
                    corroborates: str = "", prompt_version: str = "",
                    same_as: str = "", value: str = "", currency: str = "",
                    provenance: Provenance | None = None) -> Event:
    """A ruling about what something *is* — one generic, scoped event.

    ``legs`` are the counter-legs this movement's money goes to, each
    ``{"major": <one of MAJORS>, "account": "Liabilities:Mortgage:Acme",
    "share": ""}``. One leg is the ordinary case; several is a compound payment,
    such as a mortgage that is interest, principal and escrow at once.

    A leg may carry no ``share``. An unshared multi-leg ruling means: these are
    the components, in this order of certainty, proportions unknown. The
    projection records the accounts and holds the decomposition provisional.

    A ``share`` is a fraction of one: half is ``"0.5"``.

    ``said`` keeps the person's own sentence verbatim and ``prompt_version``
    records the instructions that read it, so a later reading can be re-derived
    without asking again. ``corroborates`` names a document that would prove the
    ruling; it is a suggestion, never a gate.

    A leg carries no amount — the money comes from the movement the ruling is
    about. ``value`` belongs to two scopes only. Under attribute scope it is
    what the person said one thing about an account *is*, and a figure there
    must appear in their own words, so a reading cannot supply a number the
    sentence did not contain. Under rhythm scope it is the periodicities they
    confirmed, one or more of ``PERIODICITIES``, written by
    `periodicity_value`.

    Raises ValueError on an unknown scope, an empty subject, a leg whose major
    is outside ``MAJORS``, a leg carrying an ``amount``, a value outside those
    two scopes, an attribute value with nothing said, a figure the words do not
    carry, a rhythm subject that is not '<merchant key>|<direction>' over the
    closed direction set, or a rhythm value carrying a word outside the closed
    vocabulary."""
    if scope not in SCOPES:
        raise ValueError(f"scope must be one of {SCOPES}, got {scope!r}")
    if not subject:
        raise ValueError("a ruling must name its subject")
    if value and scope not in (SCOPE_ATTRIBUTE, SCOPE_RHYTHM):
        raise ValueError("only an attribute or a rhythm ruling carries a value")
    if scope == SCOPE_RHYTHM:
        if rhythm_parts(subject)[1] not in RHYTHM_DIRECTIONS:
            raise ValueError(
                f"a rhythm subject is '<merchant key>|<direction>' with a "
                f"direction in {RHYTHM_DIRECTIONS}, got {subject!r} — both "
                "halves are closed, and a subject naming anything else is one "
                "no read could ever answer")
        outside = [p for p in periodicities_in(value) if p not in PERIODICITIES]
        if not value or outside:
            raise ValueError(
                f"a rhythm value is one or more of {PERIODICITIES}, got "
                f"{value!r} — the vocabulary is closed, and a word outside it "
                "is a rhythm no read could ever match")
    if scope == SCOPE_ATTRIBUTE:
        if ":" not in subject:
            raise ValueError("an attribute subject is '<account>:<key>', "
                             f"got {subject!r}")
        if value and not said.strip():
            raise ValueError("an attribute value must come from what the "
                             "person said; nothing was said")
        # A value carrying a currency is money, and money is a plain number:
        # digits and at most one decimal point.
        if value and currency and not _canonical_number(value):
            raise ValueError(
                f"{value!r} is not a plain amount — an amount is digits, a "
                "decimal point and nothing else, so what is stored is what was "
                "read")
        if value and not _is_finite(value):
            raise ValueError(
                f"{value!r} is not a number anything can be done with, and an "
                "append-only log cannot take it back")
        if value and _canonical_number(value) and str(value).strip()[0] in "-−":
            raise ValueError(
                f"{value!r} is negative — nothing a person states about a "
                "thing they hold is, and a sign nobody wrote is a number "
                "nobody said")
        # An ISO date is exempt from the number check alone — its canonical
        # form renumbers what was written. It still requires `said`.
        unsaid = set() if _ISO_DATE.fullmatch(str(value).strip()) else (
            _numbers_in(value) - _numbers_said(said))
        if unsaid:
            raise ValueError(
                f"the figure(s) {sorted(unsaid)} are not in what they said "
                f"({said!r}) — a reading may not supply a number the sentence "
                "did not carry")
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
              "value": value, "currency": currency,
              "prompt_version": prompt_version},
        provenance=provenance or Provenance(),
    )


def merchant_categorized(merchant: str, category: str, grade: str,
                         occurred_at: str, by: str = "model",
                         provenance: Provenance | None = None) -> Event:
    """Categorize a normalized MERCHANT — the prior for every transaction from
    it, past and future. ``by='model'`` is a graded suggestion
    (`unverified`/`corroborated`); ``by='human'`` is `verified`. A
    per-transaction CategoryAssigned override still wins. The merchant catalog
    is a projection over these events plus imported commons priors."""
    return Event(
        "MerchantCategorized", occurred_at,
        body={"merchant": merchant, "category": category, "grade": grade,
              "by": by},
        provenance=provenance or Provenance(),
    )


def merchant_enriched(merchant: str, category: str, subcategory: str = "",
                      canonical_name: str = "", attributes: dict | None = None,
                      grade: str = "corroborated", occurred_at: str = "",
                      by: str = "model", provenance: Provenance | None = None,
                      aliases: list[str] | None = None) -> Event:
    """The applied record of a merchantcore enrichment: a merchant's primary
    category, a finer ``subcategory``, a display ``canonical_name``, reviewed
    identity ``aliases``, and richer ``attributes`` (logo, mcc, website) synced
    in from the knowledge package.
    Recording it as an event keeps a replay reproducible with merchantcore
    absent. The richer sibling of `MerchantCategorized`; both feed the same
    catalog projection, which keeps the highest-graded record."""
    return Event(
        "MerchantEnriched", occurred_at,
        body={"merchant": merchant, "category": category,
              "subcategory": subcategory, "canonical_name": canonical_name,
              "attributes": dict(attributes or {}), "aliases": list(aliases or []),
              "grade": grade, "by": by},
        provenance=provenance or Provenance(),
    )


def position_observed(account_id: str, instrument: str, units: Decimal | str,
                      market_value: Decimal | str, currency: str, occurred_at: str,
                      cost_basis: Decimal | str | None = None,
                      valuation_class: str = "measured", grade: str = CORROBORATED,
                      provenance: Provenance | None = None) -> Event:
    """A holding measured at the statement date — a unit quantity of an
    instrument and its value. A measurement, not a posting: a revaluation moves
    no money, so it never touches a balance, and only realized cash flows post.

    Append-only: the next period emits a NEW measurement for the same
    instrument, and every measurement is kept. A read takes one snapshot — the
    measurements carried on the latest statement date at or before the date
    asked about — rather than each instrument's own latest value, so an
    instrument the newest statement does not list is no longer held.
    ``valuation_class`` is ``measured`` here — a statement value at its date.
    The unrealized gain (market_value − cost_basis) is derived on the read side,
    never a ledger fact. ``cost_basis`` is absent when the statement omits it."""
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
            # The many-to-many overlapping-label overlay.
            "tags": list(tags or []),
        },
        provenance=provenance or Provenance(),
    )


def postings_of(event: Event) -> list[Posting]:
    """Rebuild the Posting objects from a TransactionRecorded event."""
    return [Posting.from_dict(p) for p in event.body.get("postings", [])]


# --- tags --------------------------------------------------------------------
#
# Double-entry governs the money; tags govern the meaning.
#
# A CATEGORY is a PARTITION — exactly one per movement, so the parts sum to the
# whole. A TAG is an OVERLAY — many per movement, overlapping, and tag totals do
# not sum to spending.
#
# Tags carry personal meaning rather than shareable world knowledge, and they
# live in their own event type, which makes "tags never leave this device" an
# event-level rule rather than a per-field check.

MOVEMENT_TAGGED = "MovementTagged"


def movement_tagged(subject: str, tags: list, occurred_at: str,
                    scope: str = SCOPE_MOVEMENT, by: str = "human",
                    provenance: Provenance | None = None) -> Event:
    """Tag one movement, or every movement from a merchant.

    ``tags`` is the COMPLETE set for that subject, not a delta: last write wins,
    so removing a tag is appending the set without it and there is no untag
    event to reconcile against an add that arrived out of order. The set is
    lowercased, stripped and deduplicated.

    ``scope`` is ``SCOPE_MOVEMENT`` or ``SCOPE_MERCHANT``; merchant scope tags
    every movement from that counterparty. Raises ValueError on any other
    scope."""
    if scope not in (SCOPE_MOVEMENT, SCOPE_MERCHANT):
        raise ValueError(f"a tag applies to a movement or a merchant, got {scope!r}")
    clean = sorted({t.strip().lower() for t in (tags or []) if t and t.strip()})
    return Event(
        MOVEMENT_TAGGED, occurred_at,
        body={"subject": subject, "scope": scope, "tags": clean, "by": by},
        provenance=provenance or Provenance(),
    )


# --------------------------------------------------------------------------
# The decline: "not now" is an answer, and it is recorded.
#
# The event snapshots the STAKE the question showed when it was declined, rather
# than a timer. The queue stays silent while the live stake matches the snapshot
# and asks again the moment new evidence moves it.
#
# The amount is a fingerprint of the question as asked, computed by the same
# deterministic projection that asked it — not a claim about money.

QUESTION_DECLINED = "QuestionDeclined"

DECLINE_NOT_NOW = "not_now"        # "set it aside" — quiet until new evidence
DECLINE_DONT_KNOW = "dont_know"    # "I don't know" — the same silence
DECLINE_REASONS = (DECLINE_NOT_NOW, DECLINE_DONT_KNOW)


# Durable product conversation events; raw model-call capture remains separate.
CONVERSATION_TURN_OPENED = "ConversationTurnOpened"
CONVERSATION_TURN_SETTLED = "ConversationTurnSettled"
CONVERSATION_PROPOSAL_RECORDED = "ConversationProposalRecorded"
CONVERSATION_PROPOSAL_RESOLVED = "ConversationProposalResolved"
CONVERSATION_TURN_KINDS = ("ask", "answer", "decline", "confirm")
CONVERSATION_OUTCOMES = ("completed", "refused", "proposal", "waiting",
                         "stale", "set_aside")


def conversation_turn_opened(turn_id: str, kind: str, prompt: str,
                             occurred_at: str, *, said: str = "",
                             question_id: str = "",
                             mirrored: bool = True,
                             provenance: Provenance | None = None) -> Event:
    """Record the words and target that opened one conversation turn."""
    if not str(turn_id or "").strip():
        raise ValueError("a conversation turn requires an identity")
    if kind not in CONVERSATION_TURN_KINDS:
        raise ValueError(
            f"conversation turn kind must be one of {CONVERSATION_TURN_KINDS}")
    if not str(prompt or "").strip():
        raise ValueError("a conversation turn requires the prompt that opened it")
    if kind in ("answer", "decline") and not str(question_id or "").strip():
        raise ValueError("a queue reply must name the question it answers")
    return Event(
        CONVERSATION_TURN_OPENED, occurred_at,
        body={"turn_id": turn_id, "kind": kind, "prompt": prompt,
              "said": said, "question_id": question_id,
              "mirrored": bool(mirrored)},
        provenance=provenance or Provenance(),
    )


def conversation_turn_settled(turn_id: str, outcome: str, message: str,
                              occurred_at: str, *, reason: str = "",
                              answer: dict | None = None,
                              proposal_id: str = "",
                              provenance: Provenance | None = None) -> Event:
    """Record the terminal product-facing result of one conversation turn."""
    if not str(turn_id or "").strip():
        raise ValueError("a settled conversation turn requires an identity")
    if outcome not in CONVERSATION_OUTCOMES:
        raise ValueError(
            f"conversation outcome must be one of {CONVERSATION_OUTCOMES}")
    if outcome == "refused" and not str(reason or "").strip():
        raise ValueError("a refused conversation turn requires a reason")
    if outcome == "proposal" and not str(proposal_id or "").strip():
        raise ValueError("a proposal outcome requires a proposal identity")
    return Event(
        CONVERSATION_TURN_SETTLED, occurred_at,
        body={"turn_id": turn_id, "outcome": outcome, "message": message,
              "reason": reason, "answer": dict(answer or {}),
              "proposal_id": proposal_id},
        provenance=provenance or Provenance(),
    )


def conversation_proposal_recorded(
        proposal_id: str, turn_id: str, question_id: str, summary: str,
        proposal: dict, stake: dict, occurred_at: str,
        provenance: Provenance | None = None) -> Event:
    """Persist the exact unapplied correction and the state it was based on."""
    if not str(proposal_id or "").strip() or not str(turn_id or "").strip():
        raise ValueError("a conversation proposal requires proposal and turn identities")
    if not str(question_id or "").strip():
        raise ValueError("a conversation correction must name its question")
    if not isinstance(proposal, dict) or not proposal:
        raise ValueError("a conversation proposal requires its typed structure")
    if not isinstance(stake, dict) or not stake:
        raise ValueError("a conversation proposal requires its evidence stake")
    return Event(
        CONVERSATION_PROPOSAL_RECORDED, occurred_at,
        body={"proposal_id": proposal_id, "turn_id": turn_id,
              "question_id": question_id, "summary": summary,
              "proposal": dict(proposal), "stake": dict(stake)},
        provenance=provenance or Provenance(),
    )


def conversation_proposal_resolved(
        proposal_id: str, turn_id: str, outcome: str, message: str,
        occurred_at: str, *, reason: str = "",
        provenance: Provenance | None = None) -> Event:
    """Close one persisted proposal without deleting what was proposed."""
    if not str(proposal_id or "").strip() or not str(turn_id or "").strip():
        raise ValueError("a proposal resolution requires proposal and turn identities")
    if outcome not in ("completed", "refused", "stale", "set_aside"):
        raise ValueError("a proposal resolution requires a terminal outcome")
    if outcome == "refused" and not str(reason or "").strip():
        raise ValueError("a refused proposal resolution requires a reason")
    return Event(
        CONVERSATION_PROPOSAL_RESOLVED, occurred_at,
        body={"proposal_id": proposal_id, "turn_id": turn_id,
              "outcome": outcome, "message": message, "reason": reason},
        provenance=provenance or Provenance(),
    )


# --------------------------------------------------------------------------
# Save-up goals: desired terms and locally reserved funds are separate facts.

GOAL_CREATED = "GoalCreated"
GOAL_TERMS_CHANGED = "GoalTermsChanged"
GOAL_FUNDS_RESERVED = "GoalFundsReserved"
GOAL_FUNDS_RELEASED = "GoalFundsReleased"
GOAL_STATE_CHANGED = "GoalStateChanged"
GOAL_PROPOSAL_RECORDED = "GoalProposalRecorded"
GOAL_PROPOSAL_RESOLVED = "GoalProposalResolved"
GOAL_KINDS = ("save_up",)
GOAL_STATES = ("active", "paused", "set_aside")
GOAL_RELEASE_REASONS = ("reassigned", "used_elsewhere")
GOAL_PROPOSAL_VERBS = ("create", "change_terms", "reserve", "release",
                       "pause", "resume", "set_aside")
GOAL_PROPOSAL_OUTCOMES = ("completed", "refused", "stale", "set_aside")


def _goal_decimal(value, field_name: str) -> str:
    if isinstance(value, (float, bool)):
        raise TypeError(f"{field_name} must be Decimal, string, or integer")
    try:
        amount = Decimal(value)
    except Exception as exc:
        raise ValueError(f"{field_name} must be an exact decimal") from exc
    if not amount.is_finite() or amount <= 0:
        raise ValueError(f"{field_name} must be greater than zero")
    return str(amount)


def _goal_terms(goal_id: str, title: str, currency: str, target_amount,
                target_date: str, monthly_contribution,
                contribution_day: int | None) -> dict:
    if not str(goal_id or "").strip():
        raise ValueError("a goal requires an identity")
    if not str(title or "").strip():
        raise ValueError("a goal requires a title")
    if not str(currency or "").strip():
        raise ValueError("a goal requires a currency")
    target = _goal_decimal(target_amount, "target_amount")
    date_text = str(target_date or "").strip()
    if date_text:
        try:
            date.fromisoformat(date_text)
        except ValueError:
            raise ValueError("target_date must be an ISO calendar date") from None
    contribution = ""
    if monthly_contribution not in (None, ""):
        contribution = _goal_decimal(
            monthly_contribution, "monthly_contribution")
    if contribution_day is not None and (
            not isinstance(contribution_day, int)
            or isinstance(contribution_day, bool)
            or contribution_day < 1 or contribution_day > 28):
        raise ValueError("a contribution day must be from 1 to 28")
    if contribution and contribution_day is None:
        raise ValueError("a monthly contribution requires a day from 1 to 28")
    if contribution_day is not None and not contribution and not date_text:
        raise ValueError("a contribution day requires a target date or contribution")
    return {
        "goal_id": str(goal_id).strip(), "kind": "save_up",
        "title": str(title).strip(), "currency": str(currency).strip().upper(),
        "target_amount": target, "target_date": date_text,
        "monthly_contribution": contribution,
        "contribution_day": contribution_day,
    }


def goal_created(goal_id: str, title: str, currency: str, target_amount,
                 occurred_at: str, *, target_date: str = "",
                 monthly_contribution=None, contribution_day: int | None = None,
                 proposal_id: str = "",
                 provenance: Provenance | None = None) -> Event:
    body = _goal_terms(goal_id, title, currency, target_amount, target_date,
                       monthly_contribution, contribution_day)
    body["proposal_id"] = str(proposal_id or "")
    return Event(GOAL_CREATED, occurred_at, body=body,
                 provenance=provenance or Provenance())


def goal_terms_changed(goal_id: str, title: str, currency: str, target_amount,
                       occurred_at: str, *, target_date: str = "",
                       monthly_contribution=None,
                       contribution_day: int | None = None,
                       proposal_id: str = "",
                       provenance: Provenance | None = None) -> Event:
    body = _goal_terms(goal_id, title, currency, target_amount, target_date,
                       monthly_contribution, contribution_day)
    body["proposal_id"] = str(proposal_id or "")
    return Event(GOAL_TERMS_CHANGED, occurred_at, body=body,
                 provenance=provenance or Provenance())


def goal_funds_reserved(goal_id: str, account_id: str, amount,
                        occurred_at: str, *, proposal_id: str = "",
                        provenance: Provenance | None = None) -> Event:
    if not str(goal_id or "").strip() or not str(account_id or "").strip():
        raise ValueError("a reservation requires goal and account identities")
    return Event(
        GOAL_FUNDS_RESERVED, occurred_at,
        body={"goal_id": str(goal_id).strip(),
              "account_id": str(account_id).strip(),
              "amount": _goal_decimal(amount, "reservation amount"),
              "proposal_id": str(proposal_id or "")},
        provenance=provenance or Provenance())


def goal_funds_released(goal_id: str, account_id: str, amount,
                        reason: str, occurred_at: str, *, proposal_id: str = "",
                        provenance: Provenance | None = None) -> Event:
    if not str(goal_id or "").strip() or not str(account_id or "").strip():
        raise ValueError("a release requires goal and account identities")
    if reason not in GOAL_RELEASE_REASONS:
        raise ValueError(f"release reason must be one of {GOAL_RELEASE_REASONS}")
    return Event(
        GOAL_FUNDS_RELEASED, occurred_at,
        body={"goal_id": str(goal_id).strip(),
              "account_id": str(account_id).strip(),
              "amount": _goal_decimal(amount, "release amount"),
              "reason": reason, "proposal_id": str(proposal_id or "")},
        provenance=provenance or Provenance())


def goal_state_changed(goal_id: str, state: str, occurred_at: str, *,
                       proposal_id: str = "",
                       provenance: Provenance | None = None) -> Event:
    if not str(goal_id or "").strip():
        raise ValueError("a goal state change requires a goal identity")
    if state not in GOAL_STATES:
        raise ValueError(f"goal state must be one of {GOAL_STATES}")
    return Event(
        GOAL_STATE_CHANGED, occurred_at,
        body={"goal_id": str(goal_id).strip(), "state": state,
              "proposal_id": str(proposal_id or "")},
        provenance=provenance or Provenance())


def goal_proposal_recorded(proposal_id: str, verb: str, summary: str,
                           proposal: dict, stake: dict, occurred_at: str,
                           provenance: Provenance | None = None) -> Event:
    if not str(proposal_id or "").strip():
        raise ValueError("a goal proposal requires an identity")
    if verb not in GOAL_PROPOSAL_VERBS:
        raise ValueError(f"goal proposal verb must be one of {GOAL_PROPOSAL_VERBS}")
    if not isinstance(proposal, dict) or not proposal:
        raise ValueError("a goal proposal requires its exact typed payload")
    if not isinstance(stake, dict) or not stake:
        raise ValueError("a goal proposal requires its live state stake")
    return Event(
        GOAL_PROPOSAL_RECORDED, occurred_at,
        body={"proposal_id": str(proposal_id).strip(), "verb": verb,
              "summary": str(summary or ""), "proposal": dict(proposal),
              "stake": dict(stake)},
        provenance=provenance or Provenance())


def goal_proposal_resolved(proposal_id: str, outcome: str, occurred_at: str,
                           *, reason: str = "",
                           provenance: Provenance | None = None) -> Event:
    if not str(proposal_id or "").strip():
        raise ValueError("a goal proposal resolution requires an identity")
    if outcome not in GOAL_PROPOSAL_OUTCOMES:
        raise ValueError(
            f"goal proposal outcome must be one of {GOAL_PROPOSAL_OUTCOMES}")
    return Event(
        GOAL_PROPOSAL_RESOLVED, occurred_at,
        body={"proposal_id": str(proposal_id).strip(), "outcome": outcome,
              "reason": str(reason or "")},
        provenance=provenance or Provenance())


def question_declined(question_id: str, kind: str, occurred_at: str,
                      reason: str = DECLINE_NOT_NOW, amount: str = "",
                      count: int = 0, pack_version: str = "",
                      by: str = "human",
                      provenance: Provenance | None = None) -> Event:
    """A question was set aside — recorded so it stays set aside.

    ``question_id`` is the queue's stable id, derived from what the question is
    about rather than from event ids. ``amount``/``count`` snapshot the stake
    shown at decline time. ``pack_version`` records which voice asked. Raises
    ValueError on an unknown reason or an empty question id."""
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


# A finding is set aside under its own identity and current evidence stake.
# It is not a question and recording this event answers nothing about money.
FINDING_SET_ASIDE = "FindingSetAside"


def finding_set_aside(finding_id: str, kind: str, stake: dict,
                      occurred_at: str, by: str = "human",
                      provenance: Provenance | None = None) -> Event:
    """Keep one deterministic finding quiet while its evidence is unchanged.

    The caller supplies the stake produced by the live finding projection, not
    a duration.  A later read compares the whole JSON-safe snapshot and shows
    the finding again when evidence or the machinery version moves.
    """
    if not str(finding_id or "").strip():
        raise ValueError("a set-aside must name the finding it quiets")
    if not str(kind or "").strip():
        raise ValueError("a set-aside must name the finding kind")
    if not isinstance(stake, dict) or not stake:
        raise ValueError("a set-aside requires the finding's non-empty stake")
    return Event(
        FINDING_SET_ASIDE, occurred_at,
        body={"finding_id": finding_id, "kind": kind,
              "stake": dict(stake), "by": by},
        provenance=provenance or Provenance(),
    )


# --------------------------------------------------------------------------
# The unattended-work journal is unscoped to a document. Refusals record their
# stake for cooldown comparison; bodies contain counts and artifact ids only.

AGENT_ACTED = "AgentActed"

ACT_DONE = "done"           # it ran, and the result was written
ACT_REFUSED = "refused"     # it ran, and a guard rejected what came back
ACT_FAILED = "failed"       # it could not run to completion
ACT_OUTCOMES = (ACT_DONE, ACT_REFUSED, ACT_FAILED)


def agent_acted(rule: str, kind: str, target: str, outcome: str,
                occurred_at: str, calls: int = 0, stake: dict | None = None,
                produced: str = "", replaced: str = "", detail: str = "",
                by: str = "agent",
                provenance: Provenance | None = None) -> Event:
    """One thing the agent did without being asked, and how it went.

    ``rule`` is the RULES entry that fired and ``target`` what it fired on
    ("Northbank/depository", "brands"); together they are the identity a
    cooldown is keyed on. ``calls`` is model calls actually spent, not the estimate that got
    the action past the budget.

    ``stake`` fingerprints the evidence that justified the action — distinct
    lines and movements for an induction, brand count for an enrichment. A
    refused action is re-proposed only when its stake moves.

    ``produced`` and ``replaced`` name the artifact: the grammar written and the
    one it succeeded. Both are ids, never contents.

    Raises ValueError on an outcome outside ``ACT_OUTCOMES``, a missing rule or
    target, or a negative call count."""
    if outcome not in ACT_OUTCOMES:
        raise ValueError(f"outcome must be one of {ACT_OUTCOMES}, got {outcome!r}")
    if not rule or not target:
        raise ValueError("an agent action must name its rule and its target")
    if int(calls) < 0:
        raise ValueError("calls spent cannot be negative")
    return Event(
        AGENT_ACTED, occurred_at,
        body={"rule": rule, "kind": kind, "target": target, "outcome": outcome,
              "calls": int(calls), "stake": dict(stake or {}),
              "produced": produced, "replaced": replaced,
              "detail": detail, "by": by},
        provenance=provenance or Provenance(),
    )
