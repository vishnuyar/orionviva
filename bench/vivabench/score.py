"""The scorer: deterministic grading of runs against a frozen answer key.

Two levels, reported separately on one Scorecard:
  - raw model: per-claim accuracy, recall (claims the model omitted),
    self-consistency across repeat runs, and stated-confidence calibration.
  - system: verified-coverage and the confidently-wrong rate, derived from
    agreement across the N runs.

Everything here is a pure function of (runs, key): no model calls, and no floats
in the money path — value comparison goes through `vivacore.verify` on Decimal.

Design rationale for the metrics: docs/benchmark-harness-design.md
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from statistics import mean

from vivacore.claims import AnswerKey, Claim, KeyEntry, parse_claims
from vivacore.verify.match import match_amount, match_date, match_text


# --------------------------------------------------------------- matching one run


@dataclass
class ClaimGrade:
    label: str
    type: str
    matched: bool             # semantically correct vs a truth entry
    strict: bool              # character-exact
    truth_value: str | None
    model_value: str | None
    model_confidence: float | None
    detail: str


@dataclass
class RunGrade:
    doc_id: str
    candidate: str
    run_index: int
    parse_ok: bool
    grades: list[ClaimGrade] = field(default_factory=list)
    missed: list[str] = field(default_factory=list)   # truth labels no claim matched (recall)
    spurious: int = 0                                   # model claims matching no truth entry

    @property
    def n_truth(self) -> int:
        return len(self.grades) + len(self.missed)

    @property
    def n_correct(self) -> int:
        return sum(1 for g in self.grades if g.matched)

    @property
    def accuracy(self) -> float:
        matchable = [g for g in self.grades]
        return (sum(1 for g in matchable if g.matched) / len(matchable)) if matchable else 0.0

    @property
    def recall(self) -> float:
        return (self.n_correct / self.n_truth) if self.n_truth else 0.0


def _match_entry(entry: KeyEntry, claim: Claim) -> tuple[bool, bool, str]:
    if entry.type == "amount":
        r = match_amount(claim.value_raw, entry.value_raw, entry.locale, entry.currency)
    elif entry.type == "date":
        r = match_date(claim.value_raw, entry.value_raw, entry.locale)
    else:
        r = match_text(claim.value_raw, entry.value_raw)
    return bool(r.correct), r.strict, r.detail


def grade_run(
    doc_id: str,
    candidate: str,
    run_index: int,
    output_text: str,
    key: AnswerKey,
) -> RunGrade:
    """Grade one run's output against `key`.

    Each key entry takes the best of the claims sharing its type and normalized
    label; a claim is consumed by at most one entry. Returns a RunGrade holding
    the per-entry grades, the labels nothing matched, and the count of unmatched
    claims. Never raises: unparseable output comes back as ``parse_ok=False``
    with everything missed."""
    claims, err = parse_claims(output_text)
    if err is not None:
        # A run that does not parse matched nothing, so every truth entry is
        # missed and recall is 0.
        return RunGrade(
            doc_id=doc_id, candidate=candidate, run_index=run_index,
            parse_ok=False, grades=[],
            missed=[e.label for e in key.entries], spurious=0,
        )

    # Index model claims by (type, normalized label); a key may hold several.
    by_key: dict[tuple[str, str], list[Claim]] = defaultdict(list)
    for c in claims:
        by_key[c.key()].append(c)

    grades: list[ClaimGrade] = []
    missed: list[str] = []
    used: set[int] = set()

    for entry in key.entries:
        cand_list = by_key.get((entry.type, _norm(entry.label)), [])
        best = None
        for c in cand_list:
            cid = id(c)
            if cid in used:
                continue
            matched, strict, detail = _match_entry(entry, c)
            # Prefer a correct match; otherwise keep the first as the attempt.
            if best is None or (matched and not best[1]):
                best = (c, matched, strict, detail)
            if matched:
                break
        if best is None:
            missed.append(entry.label)
            continue
        c, matched, strict, detail = best
        used.add(id(c))
        grades.append(ClaimGrade(
            label=entry.label, type=entry.type, matched=matched, strict=strict,
            truth_value=entry.value_raw, model_value=c.value_raw,
            model_confidence=c.confidence, detail=detail,
        ))

    spurious = sum(1 for c in claims if id(c) not in used)
    return RunGrade(
        doc_id=doc_id, candidate=candidate, run_index=run_index,
        parse_ok=True, grades=grades, missed=missed, spurious=spurious,
    )


def _norm(label: str) -> str:
    import re
    return re.sub(r"\s+", " ", (label or "").strip().lower())


# --------------------------------------------------------------- aggregation


@dataclass
class CalibrationBin:
    lo: float
    hi: float
    n: int = 0
    n_correct: int = 0

    @property
    def stated(self) -> float:
        return (self.lo + self.hi) / 2

    @property
    def actual(self) -> float:
        return (self.n_correct / self.n) if self.n else 0.0


@dataclass
class Scorecard:
    candidate: str
    doc_type: str
    locale: str
    n_runs: int = 0
    n_parse_fail: int = 0
    accuracy: float = 0.0            # mean per-run accuracy of matched claims
    recall: float = 0.0             # mean per-run recall (catches silent omission)
    strict_rate: float = 0.0        # fraction character-exact among correct
    self_consistency: float = 0.0   # agreement of a claim's correctness across runs
    mean_spurious: float = 0.0
    calibration: list[CalibrationBin] = field(default_factory=list)
    ece: float | None = None        # expected calibration error (0 = perfect)
    # System-level (across the N runs for each document):
    system_verified_coverage: float = 0.0
    system_confidently_wrong: float = 0.0


def _calibration(grades: list[ClaimGrade], n_bins: int = 5) -> tuple[list[CalibrationBin], float | None]:
    bins = [CalibrationBin(i / n_bins, (i + 1) / n_bins) for i in range(n_bins)]
    have_conf = False
    for g in grades:
        if g.model_confidence is None:
            continue
        have_conf = True
        c = min(max(g.model_confidence, 0.0), 1.0)
        idx = min(int(c * n_bins), n_bins - 1)
        bins[idx].n += 1
        if g.matched:
            bins[idx].n_correct += 1
    if not have_conf:
        return bins, None
    total = sum(b.n for b in bins)
    ece = sum(b.n / total * abs(b.actual - b.stated) for b in bins if b.n) if total else None
    return bins, ece


def build_scorecards(run_grades: list[RunGrade], doc_type_of: dict, locale_of: dict) -> list[Scorecard]:
    """Group grades by (candidate, doc_type, locale) and summarize."""
    groups: dict[tuple[str, str, str], list[RunGrade]] = defaultdict(list)
    for rg in run_grades:
        dt = doc_type_of.get(rg.doc_id, "unknown")
        lc = locale_of.get(rg.doc_id, "unknown")
        groups[(rg.candidate, dt, lc)].append(rg)

    cards: list[Scorecard] = []
    for (cand, dt, lc), rgs in sorted(groups.items()):
        card = Scorecard(candidate=cand, doc_type=dt, locale=lc, n_runs=len(rgs))
        card.n_parse_fail = sum(1 for r in rgs if not r.parse_ok)
        ok = [r for r in rgs if r.parse_ok]
        if ok:
            card.accuracy = round(mean(r.accuracy for r in ok), 4)
            card.recall = round(mean(r.recall for r in ok), 4)
            all_grades = [g for r in ok for g in r.grades]
            correct = [g for g in all_grades if g.matched]
            card.strict_rate = round(sum(1 for g in correct if g.strict) / len(correct), 4) if correct else 0.0
            card.mean_spurious = round(mean(r.spurious for r in ok), 2)
            card.calibration, card.ece = _calibration(all_grades)
            if card.ece is not None:
                card.ece = round(card.ece, 4)
        card.self_consistency = round(_self_consistency(ok), 4)
        cov, cw = _system_metrics(ok)
        card.system_verified_coverage = round(cov, 4)
        card.system_confidently_wrong = round(cw, 4)
        cards.append(card)
    return cards


def _self_consistency(runs: list[RunGrade]) -> float:
    """Mean per-label agreement on correctness across runs.

    1.0 means every truth label was unanimously right or unanimously wrong;
    0.5 means the runs split evenly. Fewer than two runs returns 1.0."""
    if len(runs) < 2:
        return 1.0
    per_label: dict[str, list[bool]] = defaultdict(list)
    for r in runs:
        got = {g.label: g.matched for g in r.grades}
        for r2 in runs:
            for g in r2.grades:
                per_label.setdefault(g.label, [])
        for label in per_label:
            per_label[label].append(got.get(label, False))
    if not per_label:
        return 1.0
    agreements = []
    for outcomes in per_label.values():
        frac_true = sum(outcomes) / len(outcomes)
        agreements.append(max(frac_true, 1 - frac_true))  # 1 if unanimous
    return mean(agreements)


def _system_metrics(runs: list[RunGrade]) -> tuple[float, float]:
    """Return `(verified_coverage, confidently_wrong)` for one group of runs.

    A label is system-accepted when a majority of runs produced it. Coverage is
    accepted / truth entries; confidently-wrong is accepted-but-wrong / accepted.
    Agreement only — arithmetic verification is not folded in here."""
    if not runs:
        return 0.0, 0.0
    label_votes: dict[str, list[bool]] = defaultdict(list)
    n_truth = max(r.n_truth for r in runs)
    for r in runs:
        for g in r.grades:
            label_votes[g.label].append(g.matched)
    accepted = 0
    accepted_wrong = 0
    for label, votes in label_votes.items():
        # present in a majority of runs, and those runs agree on correctness
        if len(votes) >= (len(runs) / 2) and sum(votes) >= (len(votes) / 2):
            accepted += 1
            if sum(votes) < len(votes):  # accepted, but not unanimously correct
                pass
        elif len(votes) >= (len(runs) / 2) and sum(votes) < (len(votes) / 2):
            accepted += 1
            accepted_wrong += 1
    coverage = accepted / n_truth if n_truth else 0.0
    confidently_wrong = accepted_wrong / accepted if accepted else 0.0
    return coverage, confidently_wrong
