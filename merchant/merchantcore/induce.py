"""Induce one bank's line grammar from the lines themselves.

The model is shown real descriptors from the statement in hand — a few examples
of each line shape it prints — and asked what templates produced them. It is
never asked how a bank encodes its descriptors in general.

Three things bound what can come back.

The vocabulary. A reply may name slots from a closed list and nothing else, and
may not contain a regular expression; the expression is compiled from the
template in `profile.py`. The same closed list is rendered into the prompt and
enforced by the validator, so the two cannot drift apart.

The held-out measurement. A fifth of distinct lines is withheld from sampling
and from choosing between candidate grammars, and the gate reads that number,
so it estimates what a grammar does on a line it has never met.

The gate. A profile below the threshold comes back with its verdict attached
and is not written.

Design rationale: docs/the-conduit-and-the-counterparty.md
"""

from __future__ import annotations

import hashlib
import json
import logging
import pathlib
import re

from vivacore import promptstore

from .descriptor import is_never_templatable
from .profile import (PACK_RULES, PROFILE_FORMAT, Profile, ProfileError, SLOTS, Template,
                      validate_evidence,
                      validate)

log = logging.getLogger(__name__)

# The prompt version. A released version is never edited; a change is a new
# file, so a grammar naming v1 keeps resolving to the text that produced it.
INDUCTION_VERSION = "induce-profile-v2"

# How many descriptors ride in one induction call.
DEFAULT_SAMPLE = 40

# Below this share, a grammar is not accepted.
MIN_COVERAGE = 0.80

# How many times a grammar may be sent back for what it missed. Each round sees
# only the unexplained lines. Capped, because a one-off line is inexhaustible.
MAX_ROUNDS = 3

# Share of distinct lines withheld from induction entirely — never sampled,
# never used to choose between candidate grammars, never read until the number
# is reported.
HOLDOUT_SHARE = 0.20

# Below this many distinct lines, do not induce: the sample would be the whole
# population and a 20% holdout is three or four lines. A pair with no grammar
# still resolves through Layer 0 and the normalizer.
MIN_LINES_TO_INDUCE = 30


def holdout_split(counts: dict, share: float = HOLDOUT_SHARE,
                  salt: str = PROFILE_FORMAT) -> tuple[dict, dict]:
    """Partition `{descriptor: movements}` into `(train, holdout)`.

    Deterministic: the side a descriptor lands on is a hash of the descriptor
    salted with `salt`, so two runs over one vault split identically, the
    result does not depend on dict order, and a descriptor keeps its side as
    the vault grows.

    Split by distinct line, not by movement — a line shape is what a grammar
    has to explain, and holding out movements would leave every shape
    represented on both sides.

    Returns `(counts, {})` when either side would be empty, which the caller
    reads as no holdout."""
    train, test = {}, {}
    for d, n in counts.items():
        digest = hashlib.sha256((salt + "\x00" + d).encode("utf-8")).hexdigest()
        bucket = int(digest[:8], 16) % 10_000
        (test if bucket < share * 10_000 else train)[d] = n
    return (counts, {}) if not train or not test else (train, test)

PROMPTS = pathlib.Path(__file__).resolve().parent / "prompts"
_PROMPT = promptstore.load(PROMPTS, INDUCTION_VERSION)


def vocabulary_block() -> str:
    """The closed slot list, rendered for the prompt.

    Built from `SLOTS`, the same dict the validator enforces, so the prompt
    cannot offer a name the validator rejects or omit one it allows."""
    return "\n".join(f"   - {{{name}}} — {desc}" for name, desc in SLOTS.items())


def build_induction_prompt(descriptors) -> tuple[str, str]:
    """Returns `(prompt, version)` for a sample of descriptors.

    The version is `machinery_version()`, so a grammar can be re-derived."""
    lines = "\n".join(f"  {d}" for d in descriptors)
    prompt = _PROMPT.format(slots=vocabulary_block(), descriptors=lines)
    return prompt, machinery_version()


def machinery_version() -> str:
    """Everything that decides what an induction produces, in one string.

    `INDUCTION_VERSION+PROFILE_FORMAT+PACK_RULES` — the prompt, the storage
    format that bounds the vocabulary, and the pack rules that judge what comes
    back. Composed here rather than in each caller."""
    return f"{INDUCTION_VERSION}+{PROFILE_FORMAT}+{PACK_RULES}"


_DIGITY = re.compile(r"\d")


def skeletons(descriptors) -> dict:
    """Group lines by the template that plausibly produced them.

    Returns `{spine: [descriptors]}`. The variable parts are masked before
    grouping, not after: grouping on the raw line makes twenty-one lines
    differing only in a posting date into twenty-one groups.

    Two masks:

    - a token containing a digit is a filler (dates, trace numbers, masked
      account refs, confirmation ids);
    - a word occurring in exactly one distinct line is a filler, since template
      literals repeat by definition while a merchant name printed once is the
      hole. Parameter-free, and no list of known words is consulted.

    What survives both masks is the line's literal spine, and lines sharing a
    spine are lines one template produced. Blank and duplicate lines are
    dropped; input order does not affect the result.
    """
    lines = [d for d in sorted(set(descriptors)) if d and d.strip()]
    seen: dict[str, int] = {}
    for d in lines:
        for tok in {t.lower() for t in d.split() if not _DIGITY.search(t)}:
            seen[tok] = seen.get(tok, 0) + 1
    groups: dict[str, list[str]] = {}
    for d in lines:
        spine = " ".join("#" if _DIGITY.search(t) else
                         (t.lower() if seen.get(t.lower(), 0) > 1 else "*")
                         for t in d.split())
        groups.setdefault(spine, []).append(d)
    return groups


_HOLES = re.compile(r"\{[a-z_]+(?::[a-z]+)?\}")


def narrow_templates(profile: Profile, descriptors) -> dict:
    """`{template: distinct lines it matches}`, for templates matching 0 or 1.

    A template reproducing a single line is an example rather than a grammar,
    and a name baked into literal text lands here for the same reason: it can
    only ever match its own line. Measured by matching rather than by inspecting
    the literal words, since a genuine literal such as the NACHA entry
    description `Payroll` may occur under one originator on one statement.

    The count is over distinct non-empty descriptors."""
    out: dict = {}
    lines = [d for d in {x for x in descriptors if x} if d.strip()]
    for t in profile.templates:
        rx = t.compile()
        hits = sum(1 for d in lines if rx.match(d))
        if hits <= 1:
            out[t.pattern] = hits
    return out


def _legacy_suspect_literals(profile: Profile, descriptors) -> dict:
    """Literal words in a grammar that occur in only one line of the corpus.

    Superseded by `narrow_templates`, which measures the same worry by counting
    what a template matches. Kept for comparison; nothing calls it.

    Returns ``{template: [suspect words]}``, alphabetic words only."""
    df: dict[str, int] = {}
    for d in {x for x in descriptors if x}:
        for tok in {t.lower().strip(".,:;#*/-") for t in d.split()}:
            if tok:
                df[tok] = df.get(tok, 0) + 1
    out: dict[str, list[str]] = {}
    for t in profile.templates:
        words = [w.lower().strip(".,:;#*/-")
                 for w in _HOLES.sub(" ", t.pattern).split()]
        bad = [w for w in words if w and w.isalpha() and df.get(w, 0) <= 1]
        if bad:
            out[t.pattern] = bad
    return out


def _diverse(lines: list[str], want: int) -> list[str]:
    """Pick up to `want` lines that are as unlike each other as possible.

    Greedy farthest-first on token sets, seeded by the line with the most
    distinct tokens. Deterministic — ties break on the text — and returns the
    lines sorted when `want` covers all of them.

    Diversity rather than frequency: a model learns where a hole is by seeing
    one template with different fillers."""
    if want >= len(lines):
        return sorted(lines)
    toks = {d: {t.lower() for t in d.split()} for d in lines}
    chosen = [max(sorted(lines), key=lambda d: (len(toks[d]), len(d)))]
    while len(chosen) < want:
        far = max(sorted(set(lines) - set(chosen)),
                  key=lambda d: (min(len(toks[d] & toks[c]) / max(
                      len(toks[d] | toks[c]), 1) for c in chosen) * -1, d))
        chosen.append(far)
    return chosen


def sample_descriptors(counts: dict, limit: int = DEFAULT_SAMPLE) -> list[str]:
    """Choose which descriptors to show: every shape once, then diversity.

    `counts` maps a raw descriptor to how many movements carry it. Groups come
    from `skeletons`, ordered by movement weight so the shapes carrying the
    statement are shown first, and the sample is taken round-robin across them,
    so every candidate template gets an example before any gets a second.
    Within a group the picks maximise difference rather than frequency.

    Deterministic end to end. May return fewer than `limit` lines."""
    groups = skeletons(counts)
    order = sorted(groups, key=lambda s: (-sum(counts.get(d, 0) for d in groups[s]), s))
    # At most five examples of any one shape, and at least two. A statement with
    # three shapes sends fifteen lines rather than padding to `limit`, and one
    # with twenty shapes gives each of them two.
    per_group = max(2, min(5, limit // max(len(order), 1)))
    picks = {s: _diverse(groups[s], per_group) for s in order}
    out: list[str] = []
    depth = 0
    while len(out) < limit and any(len(picks[s]) > depth for s in order):
        for s in order:
            if len(picks[s]) > depth:
                out.append(picks[s][depth])
                if len(out) >= limit:
                    break
        depth += 1
    return out


def _find_json(text: str) -> str | None:
    if not text:
        return None
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if fence:
        return fence.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start:end + 1]
    return None


def _fixed_phrase(rx, counts) -> bool:
    """Whether a slotless template is a bank's fixed phrase, not a memorised line.

    True when some line the compiled expression `rx` matches occurs more than
    once in `counts`. A fee has no variable part — `Payment Thank You - Web`,
    `Domestic Incoming Wire Fee` — and the bank prints the identical string
    every time, so recurrence separates a fixed phrase from an example copied
    out of the sample, which occurs once.

    Matched through `rx` rather than by string equality, so a template truncated
    short of the line it meant to describe matches nothing and is refused.
    `counts` of None is False for every template."""
    return any(n > 1 and rx.match(d) for d, n in (counts or {}).items())


def parse_induction(text: str, institution: str, kind: str, version: str,
                    induced_from: int = 0, counts: dict | None = None) -> Profile | None:
    """Parse a reply into a Profile, dropping templates the vocabulary refuses.

    An unusable template is logged and skipped; the rest still form a grammar.
    `counts` feeds `_fixed_phrase`, which decides whether a slotless template
    survives.

    Returns None when the reply carries no JSON object, when it does not parse,
    or when no template survives — never an empty profile."""
    blob = _find_json(text)
    if blob is None:
        log.warning("induce: reply contained no JSON object")
        return None
    try:
        data = json.loads(blob)
    except json.JSONDecodeError as e:
        log.warning("induce: reply not valid JSON: %s", e)
        return None
    kept: list[Template] = []
    for raw in data.get("templates") or []:
        if not isinstance(raw, str) or not raw.strip():
            continue
        t = Template(raw.strip())
        try:
            rx = t.compile()
            if not t.slots() and not _fixed_phrase(rx, counts):
                raise ProfileError("no slots, and no line it explains occurs "
                                   "more than once — an example, not a grammar")
        except ProfileError as e:
            log.warning("induce: dropping template %r — %s", raw, e)
            continue
        kept.append(t)
    if not kept:
        return None
    return Profile(institution=institution, kind=kind, version="v1",
                   templates=kept, induced_from=induced_from)


class Induction:
    """What an induction produced, and whether it may be used.

    Carries the profile, the training and held-out coverage, the lines it could
    not explain, the lines that were never eligible, and the verdict."""

    def __init__(self, profile: Profile | None, coverage: float,
                 unmatched: list[str], threshold: float, version: str,
                 sample: list[str], refused: list[str] | None = None,
                 rounds: int = 1, holdout: float | None = None,
                 holdout_lines: int = 0):
        self.profile = profile
        self.coverage = coverage
        # Measured on lines the model never saw and that took no part in
        # choosing this grammar over another. None when there was no holdout.
        self.holdout = holdout
        self.holdout_lines = holdout_lines
        self.unmatched = unmatched
        self.threshold = threshold
        self.version = version
        self.sample = sample
        self.refused = refused or []
        self.rounds = rounds

    @property
    def scored(self) -> float:
        """The number to gate and compare on: the holdout when there is one,
        otherwise the training coverage."""
        return self.coverage if self.holdout is None else self.holdout

    @property
    def accepted(self) -> bool:
        return self.profile is not None and self.scored >= self.threshold

    @property
    def verdict(self) -> str:
        if self.profile is None:
            return "no grammar came back"
        tail = (f" in {self.rounds} rounds" if self.rounds > 1 else "")
        where = (f"{self.coverage:.0%} of the lines it was induced on"
                 if self.holdout is None else
                 f"{self.holdout:.0%} of {self.holdout_lines} withheld line(s), "
                 f"{self.coverage:.0%} of the rest")
        if not self.accepted:
            return f"covers {where}{tail}, below the {self.threshold:.0%} gate"
        return f"covers {where}{tail}"


def drift(profile: Profile, counts: dict, recent: dict | None = None) -> dict:
    """Re-measure a grammar against what the bank prints now.

    Returns `{profile, measured, now, lines, drop}`, and with `recent` also
    `recent`, `recent_lines` and `recent_drop`. `measured` is the number frozen
    into the profile at induction; `now` and `recent` are computed here.

    The recent figure moves first: lifetime coverage falls slowly because old
    lines outnumber new ones. Decides nothing — a drop is the signal to induce
    the next version."""
    now = profile.weighted_coverage(counts) if counts else 0.0
    out = {"profile": profile.id, "measured": profile.measured, "now": now,
           "lines": len(counts),
           "drop": (profile.measured - now) if profile.measured else 0.0}
    if recent:
        out["recent"] = profile.weighted_coverage(recent)
        out["recent_lines"] = len(recent)
        out["recent_drop"] = (profile.measured - out["recent"]) if profile.measured else 0.0
    return out


class Inducer:
    """A handful of model calls per (institution × kind), once.

    `extract_fn(prompt) -> text` is injected, so the whole path is offline
    testable and the live edge is swappable."""

    def __init__(self, extract_fn, sample_size: int = DEFAULT_SAMPLE,
                 min_coverage: float = MIN_COVERAGE, rounds: int = MAX_ROUNDS):
        self._extract = extract_fn
        self._sample_size = max(1, int(sample_size))
        self._min_coverage = float(min_coverage)
        self._rounds = max(1, int(rounds))

    def induce(self, institution: str, kind: str, counts: dict) -> Induction:
        """Induce a grammar for one (institution × kind), in up to `rounds`
        passes. Returns an Induction, never None.

        `counts` is `{descriptor: movements}`. Lines refused a grammar outright
        are excluded before anything else and reported in `refused`; a fifth of
        what remains is withheld as the holdout. Each round is shown only what
        the accumulated grammar could not explain, and the loop stops early when
        a round returns nothing new or explains no new line.

        Round N's templates are appended after round N-1's. A line reaching
        round N is one no earlier template matched, so first-match-wins cannot
        shadow the new ones."""
        eligible = {d: n for d, n in counts.items() if not is_never_templatable(d)}
        # Withheld before anything else touches the lines: the model never sees
        # them and selection between candidates never reads them.
        eligible, held = holdout_split(eligible)
        refused = sorted(set(counts) - set(eligible))
        if refused:
            log.info("induce: %d line(s) refused a grammar outright (wire dumps)",
                     len(refused))
        total = sum(eligible.values()) or 1

        templates: list[Template] = []
        remaining = dict(eligible)
        first_sample, version, used = [], "", 0
        for round_no in range(1, self._rounds + 1):
            if not remaining:
                break
            sample = sample_descriptors(remaining, self._sample_size)
            prompt, version = build_induction_prompt(sample)
            if round_no == 1:
                first_sample = sample
            log.info("induce: %s/%s round %d — %d line(s) left, showing %d (%s)",
                     institution, kind, round_no, len(remaining), len(sample), version)
            used = round_no
            # Judged against the training lines, never the holdout: what is
            # kept must not be decided by the lines that will later score it.
            got = parse_induction(self._extract(prompt), institution, kind,
                                  version, induced_from=len(sample),
                                  counts=eligible)
            if got is None:
                break
            fresh = [t for t in got.templates
                     if t.pattern not in {x.pattern for x in templates}]
            if not fresh:
                log.info("induce: round %d returned nothing new — stopping", round_no)
                break
            # A template explaining no remaining line is dropped.
            kept, before = [], len(remaining)
            for t in fresh:
                trial = Profile(institution=institution, kind=kind, version="v1",
                                templates=templates + kept + [t])
                left = {d: n for d, n in remaining.items() if trial.apply(d) is None}
                if len(left) < len(remaining):
                    kept.append(t)
                    remaining = left
            templates.extend(kept)
            log.info("induce: round %d kept %d of %d template(s), explained %d more line(s)",
                     round_no, len(kept), len(fresh), before - len(remaining))
            if before == len(remaining):
                # A round can return new template text and still explain no new
                # line, so this stop is checked separately from the one above.
                log.info("induce: round %d explained no new line — stopping", round_no)
                break

        if not templates:
            return Induction(None, 0.0, sorted(eligible), self._min_coverage,
                             version, first_sample, refused, used or 1,
                             holdout=0.0 if held else None,
                             holdout_lines=len(held))
        profile = Profile(institution=institution, kind=kind, version="v1",
                          templates=templates, induced_from=len(first_sample))
        validate(profile)
        validate_evidence(profile, eligible)
        # Scored on every eligible line rather than the sample, and weighted by
        # movements rather than by distinct line.
        matched = total - sum(remaining.values())
        unmatched = sorted(remaining, key=lambda d: (-remaining[d], d))
        held_cov = profile.weighted_coverage(held) if held else None
        unmatched += sorted((d for d in held if profile.apply(d) is None),
                            key=lambda d: (-held[d], d))
        ind = Induction(profile, matched / total, unmatched, self._min_coverage,
                        version, first_sample, refused, used,
                        holdout=held_cov, holdout_lines=len(held))
        log.info("induce: %d template(s), %s", len(templates), ind.verdict)
        return ind
