"""What kind of arrangement a person holds with a counterparty.

Two inputs meet here, and each does one half of the work.

**The catalog record licenses the question, on two of its facts.** How a
merchant bills is a fact about the merchant, true for everybody who deals with
them, and what kind of counterparty they are is another. Both must be
affirmative: the record says the counterparty is a business, and says an
arrangement with them is possible. A merchant the world only ever sells to per
purchase implies no arrangement, so nothing is asked about them; neither does a
record naming a rail or a person, whatever it says about billing. A record that
names no kind at all licenses nothing. Either fact may withhold the question;
neither creates one.

**The measured flow proposes the answer.** Above the cadence floor the prior is
not consulted: movements that hold their spacing have a cadence, and movements
that do not are `irregular`, which is a finding about the relationship rather
than an absence of one. Below the floor there is no cadence claim at all — only
the count and what the world says about the merchant, which is the one place
the prior speaks. A rhythm measured at an interval the confirmable vocabulary
has no word for proposes nothing, rather than falling back on the prior.

**A counterparty may be two things at once, and then nothing is measured over
the mixture.** The amounts are what separate a standing arrangement from an
ordinary shop on the same records: an arrangement repeats a figure, a decision
does not. So the movements are decomposed by amount first — the part whose
amounts repeat, and everything else — and every cadence, interval and
steadiness belongs to one part. One part is described as one thing; two are
named as two, with no cadence claimed over the whole.

**A person is not a counterparty here.** What two people arrange between them
is a relationship rather than a billing model, so where a slot declared the
other side a person nothing is measured, nothing is proposed and no subject
exists to record an answer under. The declaration is the enrichment gate's, and
this read makes the same one.

**A confirmation is recorded at the counterparty and a direction, never at a
rail.** Money out to a counterparty and money back from it are two
arrangements, so direction is part of the subject; a merchant billing one
person monthly and annually at once is one subject whose value holds both.

Every read here is derived on each call and writes nothing. Every lookup
considers both merchant keys, so a rhythm confirmed under a descriptor key
still answers after a grammar names the brand.
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

    One brand covers as many descriptors as there are ways its name is written
    on a statement, so a key's entry accumulates the keys of every movement it
    shares a merchant with, and a lookup holding any one of them finds
    knowledge recorded under any other.

    The keys are ordered brand-first and alphabetically within that, so what a
    lookup considers, and which of two equally graded records wins, depend on
    which movements the ledger holds and not on the order they arrived in."""
    covered: dict[str, set] = {}
    brands: set[str] = set()
    for m in movements_view.movements(core):
        keys = merchants_view.merchant_keys_of(core, m)
        brands.add(keys[0])
        for key in keys:
            covered.setdefault(key, set()).update(keys)
    return {key: tuple(sorted(known, key=lambda k: (k not in brands, k)))
            for key, known in covered.items()}


def _standing(ruling: dict) -> tuple:
    """How two rulings about one relationship are ranked against each other:
    grade first, then what was said most recently.

    One brand can be written several ways, so one relationship can carry a
    ruling under each of its descriptors. Grade decides which speaks wherever
    the two differ; where they do not, the later one stands, so correcting an
    arrangement is an ordinary re-answer."""
    return (_grade_rank(ruling.get("grade")), str(ruling.get("occurred_at") or ""))


def rhythm_of(core: ProjectionCore, merchant: str, direction: str,
              aliases: dict | None = None) -> tuple:
    """The periodicities confirmed for one counterparty, one way round.

    Empty when nobody has said anything. Resolves through both merchant keys,
    so a ruling recorded before a grammar named the brand still answers after
    it does, and where more than one of them was ruled on the strongest and
    then the latest is what answers. ``aliases`` is `merchant_key_aliases`,
    recomputed if omitted."""
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
                                description=m.description)
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
