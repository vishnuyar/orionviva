"""Derive counterparty-and-rail streams and per-direction flow statistics.

Streams retain every movement, its evidence-derived role and identity
candidates. The module holds no state and writes no hypotheses.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from merchantcore.descriptor import split_ach_heads
from merchantcore.normalize import normalize_merchant
from merchantcore.resolve import rail_of, resolve_descriptor

STREAM_VERSION = "stream-v2"

# Below this many observations a stream is reported but never described as
# recurring: one interval is not a rhythm.
MIN_FOR_CADENCE = 3

# An interval is "steady" when its mean absolute deviation is within this share
# of the median. Generous enough that a monthly bill landing on business days —
# 28, 30 and 31-day gaps — reads as one rhythm.
STEADY_INTERVAL_RATIO = 0.25

# Amounts are "fixed" below this coefficient of variation. A subscription that
# changes price once a year is still fixed; a utility is not.
FIXED_AMOUNT_CV = 0.05

# Which way the money went. A flow is one of these.
IN, OUT = "in", "out"


def money_effect(kind: str, amount: Decimal) -> Decimal:
    """The amount as it moved the person's money: positive in, negative out.

    The account's kind decides the sign, not the posting's. A liability records
    a charge positive — what is owed grew — so its sign is read the other way
    up; every other kind reads as recorded.

    Raises ValueError on an empty kind: the posted amount alone cannot say
    which way money went, and on a liability it says the opposite."""
    if not (kind or "").strip():
        raise ValueError(
            "which way a movement's money went is decided by its account's "
            "kind, and no kind was given; a posted sign alone reads a "
            "liability backwards"
        )
    return -amount if kind == "liability" else amount


def _as_date(value):
    """Coerce a movement's date to a real `date`, or None if it will not parse.

    The ledger carries dates as ISO strings, which other projections compare
    lexically; streams subtract them, so the two representations meet here at
    the boundary rather than inside an interval property."""
    if isinstance(value, date):
        return value
    text = str(value or "").strip()[:10]
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


@dataclass
class Occurrence:
    """One movement's place in a stream: the date, amount, account, account
    kind and description its features are computed from.

    ``kind`` is the account's kind, and it has no default: it is what decides
    ``direction``, which the posted amount cannot answer on its own."""
    date: date
    amount: Decimal
    account: str
    kind: str
    description: str

    @property
    def direction(self) -> str:
        """`in` or `out`, from the account's kind and the posted amount."""
        return IN if money_effect(self.kind, self.amount) > 0 else OUT


@dataclass
class Flow:
    """One direction of one stream, and the rhythm those movements make.

    Every statistic describing a rhythm lives here rather than on the stream, so
    none of them can be taken across a two-way relationship: a stream with a
    steady outflow and irregular inflows reports both, separately."""

    direction: str
    occurrences: list = field(default_factory=list)

    @property
    def n(self) -> int:
        return len(self.occurrences)

    # ---- shape ---------------------------------------------------------

    @property
    def dates(self) -> list:
        return sorted(o.date for o in self.occurrences)

    @property
    def first_seen(self):
        return self.dates[0] if self.occurrences else None

    @property
    def last_seen(self):
        return self.dates[-1] if self.occurrences else None

    @property
    def intervals(self) -> list:
        d = self.dates
        return [(b - a).days for a, b in zip(d, d[1:])]

    @property
    def median_interval_days(self):
        iv = self.intervals
        return statistics.median(iv) if iv else None

    @property
    def interval_mad(self):
        """Mean absolute deviation from the median interval, or None with no
        intervals. Used instead of standard deviation so one missed month does
        not make a steady stream look erratic."""
        iv, med = self.intervals, self.median_interval_days
        return (sum(abs(x - med) for x in iv) / len(iv)) if iv else None

    @property
    def interval_is_steady(self) -> bool:
        med, mad = self.median_interval_days, self.interval_mad
        return bool(self.n >= MIN_FOR_CADENCE and med and mad is not None
                    and mad <= STEADY_INTERVAL_RATIO * med)

    # ---- money ---------------------------------------------------------

    @property
    def total(self) -> Decimal:
        return sum((abs(o.amount) for o in self.occurrences), Decimal("0"))

    @property
    def amount_median(self) -> Decimal:
        vals = sorted(abs(o.amount) for o in self.occurrences)
        return vals[len(vals) // 2] if vals else Decimal("0")

    @property
    def amount_cv(self):
        """Coefficient of variation, or None below two observations — a single
        amount has nothing to compare, which is not the same as 0.0."""
        vals = [float(abs(o.amount)) for o in self.occurrences]
        if len(vals) < 2:
            return None
        mean = sum(vals) / len(vals)
        return (statistics.pstdev(vals) / mean) if mean else None

    @property
    def amount_is_fixed(self):
        cv = self.amount_cv
        return None if cv is None else cv <= FIXED_AMOUNT_CV

    @property
    def day_of_month_mode(self):
        if not self.occurrences:
            return None
        days = [o.date.day for o in self.occurrences]
        return max(set(days), key=lambda d: (days.count(d), -d))

    @property
    def day_of_month_is_stable(self) -> bool:
        """True when every occurrence falls within three days of one anchor day,
        wrapping around month end. A bill due on the 1st posts on the 1st, 2nd
        or 3rd depending on the weekend, and those are one rhythm."""
        mode = self.day_of_month_mode
        if mode is None or self.n < MIN_FOR_CADENCE:
            return False
        return all(min(abs(o.date.day - mode),
                       31 - abs(o.date.day - mode)) <= 3 for o in self.occurrences)

    # ---- what this is allowed to say -----------------------------------

    @property
    def cadence_class(self) -> str:
        """weekly | biweekly | monthly | quarterly | annual | irregular |
        unknown — measured from this flow's own intervals, never borrowed from
        a brand's usual cadence or from the other direction.

        `unknown` below ``MIN_FOR_CADENCE`` observations; `irregular` above it
        when the intervals are not steady or match no band."""
        if self.n < MIN_FOR_CADENCE or not self.interval_is_steady:
            return "unknown" if self.n < MIN_FOR_CADENCE else "irregular"
        med = self.median_interval_days
        for label, lo, hi in (("weekly", 5, 9), ("biweekly", 12, 16),
                              ("monthly", 26, 35), ("quarterly", 85, 96),
                              ("annual", 350, 380)):
            if lo <= med <= hi:
                return label
        return "irregular"

    @property
    def amount_stability(self) -> str:
        fixed = self.amount_is_fixed
        return "unknown" if fixed is None else ("fixed" if fixed else "variable")

    @property
    def recurring(self) -> bool:
        return self.cadence_class not in ("unknown", "irregular")

    def to_dict(self) -> dict:
        return {"direction": self.direction, "n": self.n,
                "first_seen": str(self.first_seen), "last_seen": str(self.last_seen),
                "median_interval_days": self.median_interval_days,
                "interval_mad": (round(self.interval_mad, 2)
                                 if self.interval_mad is not None else None),
                "interval_is_steady": self.interval_is_steady,
                "amount_cv": (round(self.amount_cv, 4)
                              if self.amount_cv is not None else None),
                "day_of_month_mode": self.day_of_month_mode,
                "day_of_month_is_stable": self.day_of_month_is_stable,
                "cadence_class": self.cadence_class,
                "amount_stability": self.amount_stability,
                "recurring": self.recurring}


@dataclass
class Stream:
    """One counterparty on one rail, and what the ledger says about it."""

    counterparty: str
    channel: str
    occurrences: list = field(default_factory=list)
    is_person: bool = False
    brand: str = ""
    layer: str = "normalizer"
    entry_description: str = ""
    refused: bool = False
    identity_candidates: list[str] = field(default_factory=list)
    roles: list = field(default_factory=list)     # one per occurrence
    # Every impersonal value each slot has ever held on this stream, not just
    # the first, so `agreed` can tell a brand-level fact from a per-visit one.
    field_values: dict = field(default_factory=dict)   # slot -> set of values

    @property
    def role(self) -> str:
        return _stream_role(self.roles) if self.roles else COUNTERPARTY

    def agreed(self) -> dict:
        """Slot values every occurrence of this stream agreed on, `{slot: value}`.

        What varies belongs to the visit; what does not belongs to the
        counterparty. A shop seen once in one city keeps its city; a chain seen
        in five has none."""
        return {k: next(iter(v)) for k, v in sorted(self.field_values.items())
                if len(v) == 1}

    @property
    def linked_share(self) -> float:
        """How much of this stream the transfer matcher linked. Below 1.0 on a
        `mixed` stream is the size of the gap."""
        return (sum(1 for r in self.roles if r == INTERNAL) / len(self.roles)
                if self.roles else 0.0)

    # ---- identity ------------------------------------------------------

    @property
    def key(self) -> tuple:
        return (self.counterparty, self.channel)

    @property
    def n(self) -> int:
        return len(self.occurrences)

    # ---- shape ---------------------------------------------------------

    @property
    def dates(self) -> list:
        return sorted(o.date for o in self.occurrences)

    @property
    def first_seen(self):
        return self.dates[0] if self.occurrences else None

    @property
    def last_seen(self):
        return self.dates[-1] if self.occurrences else None

    # ---- money ---------------------------------------------------------

    @property
    def direction_mix(self) -> str:
        signs = {o.direction for o in self.occurrences}
        return signs.pop() if len(signs) == 1 else "both"

    @property
    def total(self) -> Decimal:
        """How much money crossed, in either direction. A size, not a balance:
        a stream that took 100 and gave 100 back moved 200."""
        return sum((abs(o.amount) for o in self.occurrences), Decimal("0"))

    # ---- what this is allowed to say -----------------------------------

    @property
    def flows(self) -> list:
        """This stream's directions, inflow first, each with its own rhythm.

        A one-way relationship has one flow and a two-way one has two; a
        direction nothing moved in is absent rather than empty."""
        out = []
        for direction in (IN, OUT):
            occ = [o for o in self.occurrences if o.direction == direction]
            if occ:
                out.append(Flow(direction=direction, occurrences=occ))
        return out

    def flow(self, direction: str):
        """The flow going one way, or None when nothing went that way."""
        for f in self.flows:
            if f.direction == direction:
                return f
        return None

    @property
    def recurring(self) -> bool:
        """Whether some direction of this stream has a rhythm.

        Composed from the flows rather than measured across them: a steady
        outflow is a rhythm whether or not anything ever came back."""
        return any(f.recurring for f in self.flows)

    def to_dict(self) -> dict:
        return {"counterparty": self.counterparty, "channel": self.channel,
                "role": self.role, "linked_share": round(self.linked_share, 3),
                "agreed": self.agreed(),
                "brand": self.brand, "is_person": self.is_person,
                "layer": self.layer, "entry_description": self.entry_description,
                "identity_candidates": list(self.identity_candidates),
                "n": self.n, "direction": self.direction_mix,
                "first_seen": str(self.first_seen), "last_seen": str(self.last_seen),
                "flows": [f.to_dict() for f in self.flows],
                "recurring": self.recurring,
                "stream_version": STREAM_VERSION}


COUNTERPARTY, INTERNAL, ACTIVITY, MIXED = ("counterparty", "internal",
                                           "activity", "mixed")


def movement_role(movement, account_kind=None) -> str:
    """One movement's role, from evidence about the OTHER SIDE only.

    An investment account's own line is `activity`. Otherwise the only signal
    consulted is `linked`, a live transfer link proving the other side is an
    account of yours; `nature` is not consulted, because it answers a spending
    question rather than a counterparty one."""
    if (account_kind or "") == "investment":
        return ACTIVITY
    return INTERNAL if getattr(movement, "linked", False) else COUNTERPARTY


def _stream_role(roles) -> str:
    """One role for the whole stream. Disagreement is reported, not resolved:
    a stream mixing `counterparty` and `internal` roles is `mixed`, and any
    other disagreement resolves to `activity` if present, else `mixed`."""
    seen = set(roles)
    if len(seen) == 1:
        return seen.pop()
    if seen <= {COUNTERPARTY, INTERNAL}:
        return MIXED
    return ACTIVITY if ACTIVITY in seen else MIXED


def build_streams(movements, profile_for=None, kind_for=None) -> list:
    """Group movements into streams. A pure function of the SET of movements.

    `movements` is any iterable of objects with `date`, `amount`, `account` and
    `description`. `profile_for(movement) -> Profile | None` supplies the induced
    grammar for the movement's (institution × kind), or None where none has been
    induced — which is every bank today and must stay a working case.
    `kind_for(movement) -> str` gives the account kind. It is required: the
    kind decides which way a movement's money went, and it marks an investment
    account's own activity lines rather than reading them as counterparties.
    Raises ValueError when it is missing, and when it yields an empty kind for
    a movement, rather than falling back to the posted sign.

    Two passes, because a rail is a fact about a counterparty rather than about
    a line: the first resolves every descriptor and notes which rails each
    counterparty is *proven* to use on each account, the second keys each
    movement with that in hand. The inference is bounded to one account, so a
    channel proven at one institution never explains a line from another.

    Ingest order is never consulted and no state survives the call, so the
    result depends only on the set of movements passed in."""
    if kind_for is None:
        raise ValueError(
            "build_streams needs kind_for: which way a movement's money went "
            "is decided by its account's kind, and a posted sign alone reads "
            "a liability backwards"
        )
    movements = list(movements)
    # The ACH name/description split needs the statement as a whole, so it is
    # computed once here over every descriptor rather than per line.
    ach_split = split_ach_heads(m.description for m in movements)

    resolved, proven = [], {}
    for m in movements:
        res = resolve_descriptor(m.description,
                                 profile_for(m) if profile_for else None,
                                 ach_split)
        # A person is keyed by the party a slot named; everyone else by
        # `merchant_key`, the same property the read side resolves through, so a
        # merchant is filed and looked up under one name. A refused line is
        # still keyed and still counted, it simply gets no decomposition.
        counterparty = res.counterparty if res.is_person else res.merchant_key
        when = _as_date(m.date)
        # A movement with an unreadable date is skipped rather than defaulted
        # into a rhythm it would put wrong.
        if not counterparty or when is None:
            continue
        resolved.append((m, res, counterparty, when))
        if res.channel != "unknown":
            proven.setdefault((counterparty, m.account), set()).add(res.channel)

    streams: dict = {}
    for m, res, counterparty, when in resolved:
        kind = kind_for(m)
        if not (kind or "").strip():
            raise ValueError(
                f"no account kind for a movement on {m.account!r}: which way "
                "its money went cannot be read from the posted amount alone"
            )
        role = movement_role(m, kind)
        rail = rail_of(res, proven.get((counterparty, m.account), ()))
        st = streams.get((counterparty, rail))
        if st is None:
            st = Stream(counterparty=counterparty, channel=rail,
                        is_person=res.is_person, brand=res.brand, layer=res.layer,
                        entry_description=res.fields.get("entry_description", ""),
                        refused=res.refused,
                        identity_candidates=list(res.identity_candidates))
            streams[st.key] = st
        else:
            st.identity_candidates = sorted(set(
                [*st.identity_candidates, *res.identity_candidates]))
        st.occurrences.append(Occurrence(date=when, amount=m.amount,
                                         account=m.account, kind=kind,
                                         description=m.description))
        st.roles.append(role)
        for slot, value in res.shareable().items():
            if isinstance(value, str) and value.strip():
                st.field_values.setdefault(slot, set()).add(value.strip())
    # Sorted so the output itself is order-independent, not merely the features.
    for st in streams.values():
        st.occurrences.sort(key=lambda o: (o.date, o.amount, o.description))
    for st in streams.values():
        st.roles.sort()                  # order-independent, like the occurrences
    return sorted(streams.values(),
                  key=lambda s: (-s.n, -float(s.total), s.counterparty, s.channel))
