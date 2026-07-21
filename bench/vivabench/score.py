"""The scorer: deterministic grading of runs against a frozen answer key.

Two levels, reported separately (design doc §5):
  - raw model: per-claim accuracy, recall (silent omissions), self-consistency,
    source-region validity, and stated-confidence calibration.
  - system: with N-sample + cross-model agreement + arithmetic, the
    verified-coverage and the ruin metric (confidently-wrong rate).

Everything here is a pure function of (runs, key). No model calls, no floats
in the money path — matching uses verify/ (Decimal). Product-embryo-grade.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from statistics import mean

from .claims import AnswerKey, Claim, KeyEntry, parse_claims
from .verify.match import match_amount, match_date, match_text


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
    claims, err = parse_claims(output_text)
    if err is not None:
        # A non-parsing run misses everything — recall 0, recorded as such.
        return RunGrade(
            doc_id=doc_id, candidate=candidate, run_index=run_index,
            parse_ok=False, grades=[],
            missed=[e.label for e in key.entries], spurious=0,
        )

    # Index model claims by coarse (type, normalized-label) key; allow multiple.
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
            # Prefer a correct match; else keep first as the (wrong) attempt.
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
    """For each truth label, do the runs agree on whether it was gotten right?
    1.0 = every label is unanimously right or unanimously wrong across runs."""
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
    """Approximate the pipeline's behavior: a claim is 'system-accepted' if the
    majority of runs agree on the same value. Coverage = accepted / truth.
    Confidently-wrong = accepted-but-actually-wrong / accepted (the ruin metric).
    A faithful version also folds in arithmetic checks; this is the agreement
    core, which the benchmark's real run refines once the key exists."""
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
        # majority present AND agreeing on correctness
        if len(votes) >= (len(runs) / 2) and sum(votes) >= (len(votes) / 2):
            accepted += 1
            if sum(votes) < len(votes):  # some runs got it wrong → risk marker
                pass
        elif len(votes) >= (len(runs) / 2) and sum(votes) < (len(votes) / 2):
            accepted += 1
            accepted_wrong += 1
    coverage = accepted / n_truth if n_truth else 0.0
    confidently_wrong = accepted_wrong / accepted if accepted else 0.0
    return coverage, confidently_wrong
