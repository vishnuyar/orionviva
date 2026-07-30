"""Induce one bank's line grammar from the lines themselves.

The call this module makes is the opposite of the one it is easy to mistake it
for. It never asks a model *"how does this bank encode its descriptors?"* — that
is a recall question about undocumented, drifting, per-bank behaviour that no
model was trained on, and it would be answered fluently anyway. It shows the
model real descriptors from the statement in hand — a few examples of each line
shape it prints — and asks what templates produced them. The model perceives
what is in front of it and is never believed about the world.

Three things bound what can come back.

**The vocabulary.** The reply may name slots from a closed list and nothing
else, and it may not contain a regular expression — the expression is compiled
here, from the template. So a grammar cannot express more than the vocabulary
permits, and the same closed list is rendered into the prompt and enforced by
the validator, which is why the two cannot drift apart.

**The held-out measurement.** Coverage is scored against every descriptor the
institution produced, never the sample the model saw. A grammar that explains its
own examples and nothing else has learned the sample rather than the bank, and
only the held-out number tells the difference.

**The gate.** A profile that does not clear the threshold is returned with its
verdict attached and is not written. Being wrong here is not one bad read — it is
the same wrong read on every line that bank will ever print.
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

# A released prompt version is never edited — and that rule starts at the first
# commit, not before it. Everything induced up to 2026-07-28 was pre-test: two
# prompt versions and three throwaway profiles, none committed, run against a
# vault that is being rebuilt. They were collapsed back into a single v1 so the
# first real test starts from one version rather than from an archaeology of
# our own experiments. Nothing was "released" and then changed.
#
# What that v1 carries, learned from those pre-tests: `counterparty_handle`,
# because a peer payment addresses somebody by name, phone, email or username,
# and a vocabulary with only a name slot sent the model looking for somewhere
# else to put a phone number.
# v2 (2026-07-29) exists because the pack rules were written down TWICE — stated
# here for the model, enforced in code — and only the enforcement was versioned.
# `PACK_RULES` went to v2 and then v3 teaching the code that a bank's fixed
# phrase is a template, while rule 4 of v1 went on telling the model the
# opposite. We were discouraging the single line this vault most needed
# (`PAYMENT THANK YOU - WEB`, 78 movements) and then accepting it when the model
# disobeyed. v2 also names two failures the first live run produced: a truncated
# fixed phrase, and one hole name used twice on a line that carries two
# identifiers.
INDUCTION_VERSION = "induce-profile-v2"

# How many descriptors ride in one induction call. Enough to show every line
# shape a statement uses, small enough that the model is reading rather than
# summarizing — and the number the design was written against.
DEFAULT_SAMPLE = 40

# Below this share of held-out lines, a grammar is not a grammar. Deliberately
# not 1.0: a bank's long tail always contains one-off lines, and a profile that
# honestly covers most is worth more than one that claims all by being vague
# (which is rule 8 of the prompt, enforced here).
MIN_COVERAGE = 0.80

# How many times a grammar may be sent back for what it missed. Each round sees
# only the unexplained lines, so the tail is chased with fresh templates rather
# than a vaguer version of the ones that already work. Bounded because the tail
# is not infinite but a one-off line is: without a cap, a statement with forty
# singletons would burn forty calls chasing lines that occur once.
MAX_ROUNDS = 3

# Share of distinct lines withheld from induction entirely — never sampled,
# never used to choose between candidate grammars, never seen until the number
# is reported. Without it, coverage is measured on the same lines that chose the
# grammar, and `--best-of N` turns that from a small optimism into a real one:
# picking the best of N on a set makes that set's number a selection maximum
# rather than an estimate. The holdout is the only number that estimates what a
# grammar will do on a line it has never met, which is every future line.
HOLDOUT_SHARE = 0.20

# Below this many distinct lines, do not induce. A new account arrives with a
# handful of lines, and a grammar fitted to a handful is a grammar that
# memorised them: the sample IS the population, so training coverage is
# meaningless and a 20% holdout is three or four lines of noise.
#
# Nothing is lost by waiting. A pair with no grammar still resolves through
# Layer 0 and the normalizer — worse, but honestly worse — so induction is an
# improvement to run when a bank has printed enough to be characteristic, never
# a step that blocks an account from working.
MIN_LINES_TO_INDUCE = 30


def holdout_split(counts: dict, share: float = HOLDOUT_SHARE,
                  salt: str = PROFILE_FORMAT) -> tuple[dict, dict]:
    """Partition `{descriptor: movements}` into (train, holdout), deterministically.

    Split by hash of the descriptor, not at random and not by position, for three
    reasons: the same vault always splits the same way, so two runs are
    comparable; the split does not depend on dict order; and a descriptor stays
    on the same side as the vault grows, so today's holdout number and next
    month's are measuring the same thing.

    Split by DISTINCT LINE rather than by movement. A line shape is what a
    grammar has to explain; holding out movements would leave every shape
    represented on both sides and measure nothing."""
    train, test = {}, {}
    for d, n in counts.items():
        digest = hashlib.sha256((salt + "\x00" + d).encode("utf-8")).hexdigest()
        bucket = int(digest[:8], 16) % 10_000
        (test if bucket < share * 10_000 else train)[d] = n
    # A holdout that swallowed everything, or nothing, measures nothing. Fall
    # back to training on all of it and saying the number is unvalidated.
    return (counts, {}) if not train or not test else (train, test)

PROMPTS = pathlib.Path(__file__).resolve().parent / "prompts"
_PROMPT = promptstore.load(PROMPTS, INDUCTION_VERSION)


def vocabulary_block() -> str:
    """The closed slot list, rendered for the prompt from the same dict the
    validator enforces. Written once, used twice: a prompt that offered a name
    the validator rejects would burn a call on a grammar that cannot be
    accepted, and one that omitted a name the validator allows would leave the
    model with nowhere to put a field it can plainly see."""
    return "\n".join(f"   - {{{name}}} — {desc}" for name, desc in SLOTS.items())


def build_induction_prompt(descriptors) -> tuple[str, str]:
    """Compose the induction prompt for a sample, and the version that produced
    it (prompt + profile format, so a grammar can be re-derived)."""
    lines = "\n".join(f"  {d}" for d in descriptors)
    prompt = _PROMPT.format(slots=vocabulary_block(), descriptors=lines)
    return prompt, machinery_version()


def machinery_version() -> str:
    """Everything that decides what an induction produces, in one string.

    The prompt, the storage format that bounds the vocabulary, and the pack
    rules that judge what comes back. Composed here rather than in each caller,
    because two places that build the same version string are two places that
    can disagree about what a recorded version meant."""
    return f"{INDUCTION_VERSION}+{PROFILE_FORMAT}+{PACK_RULES}"


_DIGITY = re.compile(r"\d")


def skeletons(descriptors) -> dict:
    """Group lines by the template that plausibly produced them.

    Log-template mining reached this first and measured it: masking the variable
    parts BEFORE grouping raises Drain's template-accuracy F1 by 109% and its
    grouping F1 by 48% on the same data ("Preprocessing is All You Need", 2024).
    Grouping on the raw line does the opposite of what it looks like — twenty-one
    lines that differ only in a leading posting date become twenty-one groups,
    and one template eats half the sample.

    Two masks, and the second is the one that does the work:

    - **A token containing a digit is a filler.** Dates, trace numbers, masked
      account refs, confirmation ids.
    - **A word occurring in exactly ONE distinct line is a filler.** Template
      literals repeat by definition — that is what makes them literals — while
      a merchant name printed once is the hole. Parameter-free, and it needs no
      list of known words, which is the whole point.

    What survives both masks is the line's literal spine, and lines sharing a
    spine are lines one template produced.
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
    """`{template: distinct lines it matches}` for templates matching 0 or 1.

    This replaces a check that flagged "literal words appearing in only one
    descriptor". On a real vault that check fired nine times and was wrong most
    of them: `{brand} Payroll PPD ID: {company_id}` was flagged for the word
    `Payroll`, which is a genuine NACHA Company Entry Description and exactly
    the field the template was right to make literal. It only *looked* baked-in
    because one originator on this statement uses it.

    Counting what a template MATCHES is the honest version of the same worry.
    Rule 4 says a template reproducing one line is an example, not a grammar, and
    that is measurable rather than inferred. A name baked into literal text shows
    up here too, for the same reason — it can only ever match its own line."""
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

    A template literal is, by definition, text the bank prints on many lines. A
    literal appearing in exactly one descriptor is therefore not a literal — it
    is a filler the model baked into the template. That happens two ways, and
    both matter:

    - it copied an example instead of generalising it (rule 4), so the template
      matches one line and still looks like a grammar;
    - it put a *name* in the literal text instead of in ``{counterparty}``
      (rule 7), which is the failure that would carry a person's name into a
      file whose whole premise is that it is impersonal.

    Deterministic, no model, and it runs before anyone reads the templates —
    which matters, because reading is the other line of defence and reading is
    the one people skip.

    Returns ``{template: [suspect words]}``."""
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
    """Pick lines that are as UNLIKE each other as possible.

    The instinct is to show the most common line in a group, and it is measurably
    wrong: LogBatcher found similarity-based selection cost 7.7% accuracy against
    diversity-based selection, and DivLog found replacing diverse sampling with
    random cost 11% parsing accuracy and 28% template precision. The reason is
    plain once stated — a model learns where the holes are by seeing one template
    with DIFFERENT fillers. Three near-identical lines teach it nothing about
    which part varies.

    Greedy farthest-first on token sets, seeded by the longest line (the one
    carrying the most structure). Deterministic: ties break on the text."""
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
    """Choose which descriptors to show: every template once, then diversity.

    `counts` maps a raw descriptor to how many movements carry it. Groups are
    ordered by weight so the shapes carrying the statement are shown first, and
    the sample is taken round-robin across them — every candidate template gets
    an example before any gets a second. Within a group the picks maximise
    difference rather than frequency. Deterministic end to end: two runs over one
    vault choose the same forty."""
    groups = skeletons(counts)
    order = sorted(groups, key=lambda s: (-sum(counts.get(d, 0) for d in groups[s]), s))
    # At most five examples of any one template, and at least two. Five is where
    # LogBatcher measured the return flattening (5-10 entries per batch, larger
    # batches slightly worse) — past that a group is repeating itself. So a
    # statement with three shapes sends fifteen lines rather than padding to
    # forty, and a statement with twenty shapes gives each of them two.
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
    """Whether a slotless template is a bank's FIXED PHRASE, not a memorised line.

    Rule 4 refused every template with no holes, on the reasoning that a template
    reproducing one line is an example rather than a grammar. That is right about
    memorised lines and wrong about a whole class of real ones: a fee has no
    variable part. `Payment Thank You - Web`, `Domestic Incoming Wire Fee`, an
    ATM fee — the bank prints the identical string every time, and that
    constancy is what the line IS. On the first live agent run those were
    proposed correctly and dropped twenty-odd times, burning a round of calls per
    attempt re-discovering them, and leaving the commonest line on a card
    statement permanently unexplained in the one pair that then missed the gate.

    The signal needs no new rule and no new data: an example memorised from the
    sample occurs ONCE; a bank's fixed phrase RECURS. Same principle as the rest
    of this layer — what does not vary is what the thing is.

    Matched through the compiled expression rather than by string equality, so a
    truncated template (`Non-Chase ATM Fee-With`) still explains nothing and is
    still dropped — now for the reason that is actually true of it."""
    return any(n > 1 and rx.match(d) for d, n in (counts or {}).items())


def parse_induction(text: str, institution: str, kind: str, version: str,
                    induced_from: int = 0, counts: dict | None = None) -> Profile | None:
    """Parse a reply into a Profile, dropping templates the vocabulary refuses.

    One unusable template does not sink the call — the others are still a
    grammar, and the drop is logged so a pattern of refusals is visible rather
    than inferred. Returns None only when nothing survives, which is a clean
    'this call produced no grammar' rather than an empty profile that would
    match nothing and look like a bank with no templates."""
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

    Carries the profile, the held-out coverage, the lines it could not explain,
    the lines that were never eligible, and the verdict — kept together because
    the profile alone is exactly the thing nobody should act on without the
    number beside it."""

    def __init__(self, profile: Profile | None, coverage: float,
                 unmatched: list[str], threshold: float, version: str,
                 sample: list[str], refused: list[str] | None = None,
                 rounds: int = 1, holdout: float | None = None,
                 holdout_lines: int = 0):
        self.profile = profile
        self.coverage = coverage
        # The honest number: measured on lines the model never saw AND that
        # never took part in choosing this grammar over another.
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
        """The number to gate and compare on. Holdout when there is one."""
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
    """Is this grammar still explaining what the bank prints?

    The spec claimed the lossless check doubles as a drift detector. It did not,
    because nothing ever ran it twice: coverage was computed once at induction
    and frozen into the profile, so a grammar could fall to half its measured
    number and still be labelled with the number it had on the day it was
    written.

    Two figures, and the second is the one that moves first. **Lifetime**
    coverage falls slowly, because old lines outnumber new ones — at twenty
    thousand movements a brand-new template shape barely dents it. **Recent**
    coverage falls immediately, because a bank that changed its composition
    changed it for everything printed since. A grammar at 84% lifetime and 40%
    on the last quarter is a grammar that stopped working three months ago.

    Returns what it measured. It decides nothing: a drop is a prompt to induce
    the next version, and versions are never edited."""
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
    """A handful of model calls per (institution × kind), once, ever.

    `extract_fn(prompt) -> text` is injected, so the whole path is offline
    testable and the live edge is swappable — the same arrangement enrichment
    uses."""

    def __init__(self, extract_fn, sample_size: int = DEFAULT_SAMPLE,
                 min_coverage: float = MIN_COVERAGE, rounds: int = MAX_ROUNDS):
        self._extract = extract_fn
        self._sample_size = max(1, int(sample_size))
        self._min_coverage = float(min_coverage)
        self._rounds = max(1, int(rounds))

    def induce(self, institution: str, kind: str, counts: dict) -> Induction:
        """Induce a grammar for one (institution × kind) from `{descriptor:
        movements}`, measuring against ALL of them, in up to `rounds` passes.

        Each round is shown only what the accumulated grammar could not explain.
        That is the shape log-template mining converged on — LogBatcher compiles
        a returned template to a regex, matches it against the corpus, and sends
        the unmatched lines back as a fresh cluster — and it fits the material:
        a bank's common shapes are learned in round one, and its long tail is a
        different set of templates rather than a vaguer version of the same ones.

        Round N's templates are appended after round N-1's. Safe by
        construction, because a line reaching round N is a line no earlier
        template matched, so first-match-wins cannot shadow them."""
        eligible = {d: n for d, n in counts.items() if not is_never_templatable(d)}
        # Withheld before anything else touches the lines. The model never sees
        # them, `--best-of` never selects on them, and the number they produce is
        # therefore an estimate rather than a maximum.
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
            # Judged against the TRAINING lines, never the holdout: what is kept
            # must not be decided by the lines that will later score it.
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
            # A template that explains no remaining line earns no place in the
            # grammar. Round 3 of a real run returned three templates and
            # explained zero lines with them; carrying those forward would grow
            # the grammar while adding nothing, and every template is applied to
            # every line this bank will ever print.
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
                # Explaining nothing is a stronger stop than returning nothing:
                # a round can produce new text and still not move the number.
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
        # Scored on every eligible line, never the sample, and weighted by
        # movements: a template that explains one rare line and misses the daily
        # one is not half right.
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
