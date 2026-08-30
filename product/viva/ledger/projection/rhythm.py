"""Derive arrangement hypotheses and rulings from catalog records and flows.

Reads are pure, exclude person-declared counterparties and retain canonical,
structural and legacy keys when resolving prior rulings.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from merchantcore.enrich import BILLING_EITHER, BILLING_STANDING, KIND_BUSINESS

from ..events import (PERIOD_ANNUAL, PERIOD_IRREGULAR, PERIOD_MONTHLY,
                      SCOPE_RHYTHM, periodicities_in, rhythm_subject)
from ..streams import IN, MIN_FOR_CADENCE, OUT, Flow, Occurrence, _as_date
from . import merchants as merchants_view
from . import movements as movements_view
from .core import ProjectionCore, _grade_rank

# The billing models that make an arrangement possible, and therefore make a
# question worth asking. A merchant billed only per purchase is the `settled`
# rung on this axis: silence.
LICENSING = (BILLING_STANDING, BILLING_EITHER)

# The counterparty kinds an arrangement may be proposed about. A record naming
# any other kind, or naming none at all, licenses nothing however it bills.
LICENSED_KINDS = (KIND_BUSINESS,)

# Which measured cadences the confirmable vocabulary has a word for. A steady
# rhythm the vocabulary cannot name proposes nothing at all: it is neither
# rounded to a neighbouring word nor passed back to the prior. Movements that
# never settled into a spacing are the other case, and the vocabulary does
# name those.
_CADENCE_PROPOSES = {PERIOD_MONTHLY: PERIOD_MONTHLY, PERIOD_ANNUAL: PERIOD_ANNUAL}


@dataclass
class RhythmComponent:
    """One part of a relationship that was measured as a single thing.

    Every statistic here was computed over these movements and no others, so a
    component is the largest set anything in this module describes. A
    relationship holding one component is described as one thing; one holding
    two is a mixture.

    ``measured`` says the part cleared the cadence floor, so its ``cadence`` is
    a finding — a band where the spacing held, `irregular` where it did not.
    ``steady`` is the narrower permission: only a part whose intervals held may
    state an interval or be read as one arrangement, so ``interval_days`` is
    filled for those and empty for the rest."""

    count: int
    amount: Decimal
    amount_stability: str
    measured: bool = False
    steady: bool = False
    cadence: str = ""
    interval_days: int | None = None
    proposed: tuple = ()
    movements: tuple = ()


@dataclass
class RhythmHypothesis:
    """One `(merchant, direction)` pair the catalog says an arrangement is
    possible for, with everything the ledger measured about it.

    ``components`` is the movements decomposed by amount, and it is what the
    statistics belong to. The flat fields describe the relationship as a whole
    and are filled only where the whole is one component: where it is a
    mixture, ``measured`` is False and ``cadence``, ``interval_days``,
    ``amount_stability`` and ``proposed`` are empty.

    ``measured`` is True where the whole is one component that cleared the
    cadence floor, and ``steady`` the narrower case where that component's
    intervals also held their spacing — the one condition under which anything
    here may speak of an interval. ``proposed`` is what the hypothesis rests
    on, from the measurement wherever there was one and from the prior only
    below the floor; it is empty where neither says anything specific."""

    merchant: str
    direction: str
    count: int
    amount: Decimal
    currency: str
    example: str
    movements: list = field(default_factory=list)
    billing: str = ""
    billing_period: str = ""
    measured: bool = False
    steady: bool = False
    cadence: str = ""
    interval_days: int | None = None
    amount_stability: str = ""
    proposed: tuple = ()
    confirmed: tuple = ()
    components: tuple = ()

    @property
    def subject(self) -> str:
        return rhythm_subject(self.merchant, self.direction)

    @property
    def mixed(self) -> bool:
        """True where the movements did not decompose into one thing."""
        return len(self.components) > 1


def merchant_key_aliases(core: ProjectionCore) -> dict:
    """`{key: every key that merchant could be filed under}`.

    One resolved identity may retain a canonical id, structural/brand candidates
    and several descriptor keys, so an entry accumulates the candidates of every
    movement sharing its leading identity. A lookup holding any one can find
    knowledge recorded under another.

    Keys are ordered leading-identity-first and alphabetically within that, so
    lookup and equal-grade choice depend on which movements the ledger holds,
    not on arrival order."""
    covered: dict[str, set] = {}
    leading: set[str] = set()
    for m in movements_view.movements(core):
        keys = merchants_view.merchant_keys_of(core, m)
        leading.add(keys[0])
        for key in keys:
            covered.setdefault(key, set()).update(keys)
    return {key: tuple(sorted(known, key=lambda k: (k not in leading, k)))
            for key, known in covered.items()}


def _standing(ruling: dict) -> tuple:
    """Rank a relationship ruling by grade, then occurrence time."""
    return (_grade_rank(ruling.get("grade")), str(ruling.get("occurred_at") or ""))


def rhythm_of(core: ProjectionCore, merchant: str, direction: str,
              aliases: dict | None = None) -> tuple:
    """The periodicities confirmed for one counterparty, one way round.

    Empty when nobody has said anything. Resolves through canonical and legacy
    candidates; the strongest and then latest ruling answers. ``aliases`` is
    `merchant_key_aliases`, recomputed if omitted.
    """
    if not merchant or not direction:
        return ()
    if aliases is None:
        aliases = merchant_key_aliases(core)
    best = None
    for key in aliases.get(merchant, (merchant,)):
        found = core._rulings.get((SCOPE_RHYTHM, rhythm_subject(key, direction)))
        if found is None:
            continue
        if best is None or _standing(found) > _standing(best):
            best = found
    return periodicities_in((best or {}).get("value", ""))


def _prior_of(core: ProjectionCore, movements) -> dict:
    """The attributes of the highest-graded catalog record these movements
    resolve to, or `{}` where none of them has one.

    Resolved the way every other catalog read is: through every key each of
    these movements could be filed under, strongest record winning. A record
    written under a descriptor is still found after a grammar names the
    brand."""
    best = None
    for m in movements:
        found = merchants_view.merchant_record(core, m)
        if found is None:
            continue
        if best is None or _grade_rank(found.get("grade")) > _grade_rank(best.get("grade")):
            best = found
    return (best or {}).get("attributes") or {}


def _flows_by_merchant(core: ProjectionCore) -> dict:
    """`{(merchant key, direction): Flow}` over every movement with a
    counterparty.

    The rail is not in the key: a rhythm is confirmed at the counterparty, so
    the movements a hypothesis is measured over are the same movements a ruling
    would speak about. Movements a live transfer link proves are between the
    person's own accounts are absent, and so is any movement whose date will
    not parse.

    Movements a slot declared a person on are absent too, whatever they do:
    with no flow there is no hypothesis, no question and no subject a ruling
    could be written under.
    """
    groups: dict[tuple, list] = {}
    for m in movements_view.movements(core):
        if getattr(m, "linked", False):
            continue
        if merchants_view.is_person(core, m):
            continue
        when = _as_date(m.date)
        key = merchants_view.merchant_key_of(core, m)
        if not key or when is None:
            continue
        occurrence = Occurrence(date=when, amount=m.amount, account=m.account,
                                kind=m.kind, description=m.description)
        groups.setdefault((key, occurrence.direction), []).append((occurrence, m))
    out = {}
    for pair, rows in groups.items():
        rows.sort(key=lambda r: (r[0].date, r[0].amount, r[0].description))
        out[pair] = (Flow(direction=pair[1], occurrences=[o for o, _ in rows]),
                     [m for _, m in rows])
    return out


def _amount_runs(flow: Flow) -> list:
    """The flow's occurrences as index groups whose amounts the ledger already
    calls one amount.

    The amounts are sorted and accumulated while the run they form still reads
    fixed, so what counts as "the same amount" is `Flow.amount_is_fixed`, and
    the grouping depends on the amounts alone, never on the order the movements
    arrived in.
    """
    order = sorted(range(len(flow.occurrences)),
                   key=lambda i: (abs(flow.occurrences[i].amount),
                                  flow.occurrences[i].date,
                                  flow.occurrences[i].description))
    runs: list[list[int]] = []
    for i in order:
        grown = ([flow.occurrences[j] for j in runs[-1]] + [flow.occurrences[i]]
                 if runs else [])
        if grown and Flow(direction=flow.direction,
                          occurrences=grown).amount_is_fixed:
            runs[-1].append(i)
        else:
            runs.append([i])
    return runs


def _decompose(flow: Flow) -> list:
    """The flow as index groups, each of which may be measured as one thing.

    One group where there is nothing to separate — every amount repeating, or
    none of them doing so. Two at most where both are present: the longest run
    of repeating amounts, which is what a standing arrangement looks like, and
    the remainder, which is what a run of separate decisions looks like and may
    itself hold a further mixture. Which of the two is which arrangement is not
    decided here and is not decidable from a ledger; it is the person's to
    say.
    """
    whole = [list(range(len(flow.occurrences)))]
    repeated = [run for run in _amount_runs(flow) if len(run) > 1]
    if not repeated:
        return whole
    stable = max(repeated, key=lambda run: (
        len(run), sum(abs(flow.occurrences[j].amount) for j in run)))
    rest = [i for i in range(len(flow.occurrences)) if i not in set(stable)]
    return whole if not rest else [sorted(stable), rest]


def _component(flow: Flow, movements: list, indexes: list) -> RhythmComponent:
    """One part of a flow, with every statistic measured over that part alone.

    Enough observations means something was measured, and which thing depends
    on the spacing. Where it held, the cadence is the band the intervals fell
    in and the interval may be stated. Where it did not, the finding is that
    these do not come round on a pattern — `irregular`, one of the words a
    person may confirm. No interval is stated in that case, because a median
    over spacings that never settled would describe nothing."""
    part = Flow(direction=flow.direction,
                occurrences=[flow.occurrences[i] for i in indexes])
    measured = part.n >= MIN_FOR_CADENCE
    steady = measured and part.interval_is_steady
    named = (_CADENCE_PROPOSES.get(part.cadence_class) if steady
             else (PERIOD_IRREGULAR if measured else None))
    return RhythmComponent(
        count=part.n, amount=part.total, amount_stability=part.amount_stability,
        measured=measured, steady=steady,
        cadence=part.cadence_class if measured else "",
        interval_days=part.median_interval_days if steady else None,
        proposed=(named,) if named else (),
        movements=tuple(movements[i].key for i in indexes))


def rhythm_hypotheses(core: ProjectionCore) -> list:
    """Every `(merchant, direction)` pair worth proposing an arrangement for.

    Licensed by two facts on one catalog record and evidenced by the flow. A
    pair is present only where that record says the counterparty is a business
    and says an arrangement with them is possible; a pair whose merchant has no
    record, no billing prior, no counterparty kind, or whose prior says the
    world only sells to them per purchase, is absent.

    Every flow is walked and measured either way: the two facts decide whether
    a pair is proposed, never what is measured about it.

    The movements are decomposed by amount before anything is measured, so no
    statistic here ever spans a mixture. The whole is described only where the
    decomposition found one thing; where it found two, the flat fields stay
    empty and the components carry what was measured about each.

    A pure function of the movement set: the result depends on which movements
    the ledger holds and not on the order they arrived in.
    """
    aliases = merchant_key_aliases(core)
    out: list[RhythmHypothesis] = []
    for (merchant, direction), (flow, movements) in _flows_by_merchant(core).items():
        prior = _prior_of(core, movements)
        kind = str(prior.get("counterparty_kind", ""))
        billing = str(prior.get("billing", ""))
        if kind not in LICENSED_KINDS or billing not in LICENSING:
            continue
        period = str(prior.get("billing_period", ""))
        components = tuple(_component(flow, movements, indexes)
                           for indexes in _decompose(flow))
        whole = components[0] if len(components) == 1 else None
        # One thing measured is what the measurement says, whether what it
        # found was a cadence or the absence of one; one thing below the floor,
        # where nothing was measured at all, is what the world says about the
        # merchant. A mixture is neither, and proposes nothing at all.
        proposed = ()
        if whole is not None:
            proposed = (whole.proposed if whole.measured
                        else ((period,) if period in (PERIOD_MONTHLY, PERIOD_ANNUAL)
                              else ()))
        out.append(RhythmHypothesis(
            merchant=merchant, direction=direction, count=flow.n,
            amount=flow.total,
            currency=next((m.currency for m in movements if m.currency), ""),
            example=movements[0].description,
            movements=[m.key for m in movements],
            billing=billing, billing_period=period,
            measured=bool(whole and whole.measured),
            steady=bool(whole and whole.steady),
            cadence=whole.cadence if whole else "",
            interval_days=whole.interval_days if whole else None,
            amount_stability=whole.amount_stability if whole else "",
            proposed=proposed, components=components,
            confirmed=rhythm_of(core, merchant, direction, aliases)))
    out.sort(key=lambda h: (h.merchant, h.direction))
    return out


__all__ = ["IN", "OUT", "RhythmComponent", "RhythmHypothesis",
           "merchant_key_aliases", "rhythm_hypotheses", "rhythm_of"]
