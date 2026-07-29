"""Streams — the same money, arriving again.

A **stream** is every movement sharing a counterparty and a rail. It is the unit
at which recurring money is actually understandable: one rent, one payroll, one
subscription, one person you settle up with. A transaction is too small a unit to
carry that meaning and a category is too large.

Two decisions shape everything here.

**The key is (counterparty, rail), not counterparty alone.** A large retailer
is both a monthly subscription and a shop you visit; one institution receives both
a savings sweep and a loan repayment. Keyed on the counterparty alone, the
interval and amount statistics are computed over a mixture and describe nothing.

**Streams are derived, never stored.** This module is a projection over the
ledger and holds no state between calls, which is what makes the invariant in
`order_independent` true rather than aspirational: a person who loads a year in
one afternoon and a person who loads one statement a month must arrive at the
same beliefs about the same money. Every tempting optimisation here — incremental
feature updates, cached statistics keyed by last-seen — breaks that quietly.

**Not every movement has a counterparty.** A real vault made that obvious in a
way the design had not: the two largest streams by count were a person paying
their own credit cards, and dozens of singleton streams were brokerage activity
lines — `You Sold Short-term gain: $155.46` mints a stream key of its own, and
there is no counterparty anywhere in it. Measuring a rhythm in money that never
left your life, or in a phrase describing a capital gain, is measuring noise with
a straight face.

So a stream carries a **role**:

    counterparty   somebody was on the other side
    internal       the other side is an account of YOURS — proven by a live
                   transfer link, not inferred
    activity       an investment account's own line, which names no party
    mixed          the occurrences disagree, which is itself a finding

Marked, never dropped. Dropping would hide movements the totals still contain;
marking lets the report separate them and lets a later layer decide.

Two corrections a real vault forced, both worth keeping visible.

**Role is derived from the stream, not carried in its key.** Keyed on role, one
counterparty split in two the moment the transfer matcher linked *some* of its
movements and not others — the same money appearing twice under one name, which
is exactly the failure this module exists to prevent. A stream whose occurrences
disagree is now `mixed`, and that is a signal about missing links rather than a
second stream.

**Role does not consult `nature`.** It did, and a mortgage servicer came back
`internal`: `nature` answers *"does this count as spending?"* and role answers
*"is there someone on the other side?"* A mortgage payment is not spending and
still has a party. Only a live transfer link proves the other side is yours.

This module deliberately contains **no hypotheses**. It reports what the ledger
holds: how often, how much, how steady, through which rail. That is useful on its
own, it is checkable against a statement by hand, and it is the evidence any later
inference has to be measured against.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from merchantcore.descriptor import split_ach_heads
from merchantcore.normalize import normalize_merchant
from merchantcore.resolve import resolve_descriptor

STREAM_VERSION = "stream-v1"

# Below this many observations there is no cadence to speak of — one interval is
# not a rhythm. Reported, but never described as recurring.
MIN_FOR_CADENCE = 3

# An interval is "steady" when its mean absolute deviation is within this share
# of the median. Deliberately generous: a monthly bill lands on business days,
# so 30/31/28-day gaps and weekend drift are the same rhythm.
STEADY_INTERVAL_RATIO = 0.25

# Amounts are "fixed" below this coefficient of variation. A subscription that
# changes price once a year is still fixed; a utility never is.
FIXED_AMOUNT_CV = 0.05


def _as_date(value):
    """Coerce a movement's date to a real `date`.

    The ledger carries dates as **ISO strings** — `MovementInfo.date` is a `str`,
    and every other projection compares them lexically, which is correct for
    ordering and silently wrong for arithmetic. Streams are the first thing here
    that subtracts two dates, so this is where the two representations have to
    meet.

    Coerced at the boundary rather than defended against everywhere: an interval
    is the whole point of a stream, and `str - str` failing deep inside a
    property is a worse error than a bad date failing here."""
    if isinstance(value, date):
        return value
    text = str(value or "").strip()[:10]
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


@dataclass
class Occurrence:
    """One movement's place in a stream — enough to compute features and to show
    a person the receipt, and nothing else."""
    date: date
    amount: Decimal
    account: str
    description: str


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
    roles: list = field(default_factory=list)     # one per occurrence
    # Every impersonal value each slot has ever held on this stream, not just
    # the first. A brand's city is only its city if every visit agreed — and a
    # stream that kept one occurrence's slots could never notice the
    # disagreement, so it would report a chain's first city as a fact about the
    # chain.
    field_values: dict = field(default_factory=dict)   # slot -> set of values

    @property
    def role(self) -> str:
        return _stream_role(self.roles) if self.roles else COUNTERPARTY

    def agreed(self) -> dict:
        """Slot values every occurrence of this stream agreed on.

        What varies belongs to the visit; what does not belongs to the
        counterparty. A shop seen once in one city keeps its city; a chain seen
        in five has none, and that absence is the correct answer rather than a
        missing one."""
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
        """Mean absolute deviation from the median interval. Chosen over standard
        deviation because one missed month should not make a steady stream look
        erratic, and MAD is what a person would compute by eye."""
        iv, med = self.intervals, self.median_interval_days
        return (sum(abs(x - med) for x in iv) / len(iv)) if iv else None

    @property
    def interval_is_steady(self) -> bool:
        med, mad = self.median_interval_days, self.interval_mad
        return bool(self.n >= MIN_FOR_CADENCE and med and mad is not None
                    and mad <= STEADY_INTERVAL_RATIO * med)

    # ---- money ---------------------------------------------------------

    @property
    def direction_mix(self) -> str:
        signs = {("in" if o.amount > 0 else "out") for o in self.occurrences}
        return signs.pop() if len(signs) == 1 else "both"

    @property
    def total(self) -> Decimal:
        return sum((abs(o.amount) for o in self.occurrences), Decimal("0"))

    @property
    def amount_median(self) -> Decimal:
        vals = sorted(abs(o.amount) for o in self.occurrences)
        return vals[len(vals) // 2] if vals else Decimal("0")

    @property
    def amount_cv(self):
        """Coefficient of variation. `None` below two observations — a single
        amount has no variation, and reporting 0.0 would read as 'perfectly
        fixed' when it means 'nothing to compare'."""
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
        """Within three days of one anchor. A bill due on the 1st posts on the
        1st, the 2nd or the 3rd depending on the weekend, and treating those as
        three different rhythms would hide every real one."""
        mode = self.day_of_month_mode
        if mode is None or self.n < MIN_FOR_CADENCE:
            return False
        return all(min(abs(o.date.day - mode),
                       31 - abs(o.date.day - mode)) <= 3 for o in self.occurrences)

    # ---- what this is allowed to say -----------------------------------

    @property
    def cadence_class(self) -> str:
        """Observed, never asked for. §2 of the transaction-intelligence spec
        classes this K3 for exactly this reason: which cadence a person is on is
        a fact about their plan, and the ledger holds it directly.

        `unknown` below the observation floor, and it stays `unknown` rather than
        borrowing a brand's usual cadence — that borrowing is what the precedence
        rule forbids."""
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
        return {"counterparty": self.counterparty, "channel": self.channel,
                "role": self.role, "linked_share": round(self.linked_share, 3),
                "agreed": self.agreed(),
                "brand": self.brand, "is_person": self.is_person,
                "layer": self.layer, "entry_description": self.entry_description,
                "n": self.n, "direction": self.direction_mix,
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
                "recurring": self.recurring,
                "stream_version": STREAM_VERSION}


COUNTERPARTY, INTERNAL, ACTIVITY, MIXED = ("counterparty", "internal",
                                           "activity", "mixed")


def movement_role(movement, account_kind=None) -> str:
    """One movement's role, from evidence about the OTHER SIDE only.

    `linked` is a live transfer link — the transfer matcher proved the other
    side is an account of yours. That is the only thing consulted, deliberately:
    `nature` was tried and removed, because it answers a spending question and a
    mortgage servicer is not spending and is still a party."""
    if (account_kind or "") == "investment":
        return ACTIVITY
    return INTERNAL if getattr(movement, "linked", False) else COUNTERPARTY


def _stream_role(roles) -> str:
    """One role for the whole stream. Disagreement is reported, not resolved.

    A counterparty whose movements are partly linked is one counterparty with
    some links missing — a finding about the transfer matcher, not two
    counterparties."""
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
    `kind_for(movement) -> str` gives the account kind, so an investment
    account's own activity lines are marked rather than read as counterparties.

    Ingest order is never consulted, and no state survives the call. That is the
    whole of the order-independence guarantee; there is nowhere else for it to
    leak from."""
    movements = list(movements)
    # The ACH name/description split needs the statement as a whole, so it is
    # computed once here over every descriptor rather than per line.
    ach_split = split_ach_heads(m.description for m in movements)

    streams: dict = {}
    for m in movements:
        res = resolve_descriptor(m.description,
                                 profile_for(m) if profile_for else None,
                                 ach_split)
        # A refused line still recurs and is still money; it simply gets no
        # decomposition. Keying it on the whole normalized line keeps it visible
        # instead of dropping it, which is what "kept local and whole" means.
        # The brand when a layer could name one, the deterministic key when not.
        # `normalize_merchant` runs over the brand too, so the key stays a
        # canonical form rather than whatever casing the bank used this month.
        counterparty = (res.counterparty if res.is_person
                        else (normalize_merchant(res.brand) or res.key))
        if not counterparty:
            continue
        role = movement_role(m, kind_for(m) if kind_for else None)
        st = streams.get((counterparty, res.rail))
        if st is None:
            st = Stream(counterparty=counterparty, channel=res.rail,
                        is_person=res.is_person, brand=res.brand, layer=res.layer,
                        entry_description=res.fields.get("entry_description", ""),
                        refused=res.refused)
            streams[st.key] = st
        when = _as_date(m.date)
        if when is None:
            # A movement with an unreadable date cannot join a rhythm. Skipped
            # from the stream rather than defaulted into one, because a wrong
            # date does not make a stream noisy — it makes its cadence wrong.
            continue
        st.occurrences.append(Occurrence(date=when, amount=m.amount,
                                         account=m.account,
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
