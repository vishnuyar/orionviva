"""A descriptor grammar, held as data.

A bank composes its statement lines from templates — `ZELLE TO {counterparty}`,
`CARD PURCHASE {date} {brand} {city} {region}`. A profile is a list of such
templates and nothing else: literal words, and named holes drawn from a closed
set. A template never carries a regular expression; the expression is compiled
here from the template.

Two properties follow from that structure rather than being checked afterwards.

Losslessness is structural: a template matches the whole descriptor, end to
end, or it does not match at all, so every character of a descriptor a profile
claims landed in a slot.

Privacy is a slot name: `counterparty`, `counterparty_handle` and `account_ref`
are personal by declaration. Nothing downstream inspects extracted text to
decide whether it may travel; the slot it came from already said.

Design rationale: docs/the-conduit-and-the-counterparty.md
"""

from __future__ import annotations

import json
import pathlib
import re
from dataclasses import dataclass, field

from .descriptor import is_never_templatable

# A compatibility version: `from_dict` refuses a profile that does not carry it,
# and `holdout_split` salts its hash with it.
PROFILE_FORMAT = "prof-v1"

# A behaviour version: what a fresh induction would now do differently. Nothing
# loads by it and nothing is salted by it; `machinery_version()` carries it into
# the agent's stake, so a refusal recorded under older rules expires when the
# rules change.
PACK_RULES = "pack-v5"

# The closed slot vocabulary. A profile may name these and nothing else.
SLOTS = {
    "brand":        "the merchant or payee as the statement prints it",
    "city":         "a town or city",
    "region":       "a state, province or country code",
    "store_number":  "an outlet number",
    "counterparty": "a PERSON on the other side of the payment, named",
    "counterparty_handle": "the person on the other side identified by a phone "
                           "number, email or username instead of a name",
    "institution":  "a named bank or platform",
    "account_ref":  "digits identifying an account, possibly masked with # or *",
    "reference":    "a confirmation or order id",
    "trace":        "the number identifying THIS movement on the network",
    "company_id":   "the standing id of the originator, the same every month",
    "contact":      "a phone number or web address the merchant printed",
    "date":         "a date printed inside the line",
    "amount":       "a figure printed inside the line",
    "purpose":      "the bank's own word for what the movement is",
    "noise":        "filler the line always carries and nothing needs",
}

# Slots whose contents are personal by declaration. A property of the slot, not
# a judgement about the text that landed in it.
PERSONAL_SLOTS = frozenset({"counterparty", "counterparty_handle", "account_ref"})

# Slots that name the party a payment was made to or from. A template holding
# none of these describes a payment with nobody in it, which is what `party_slot`
# reads.
PARTY_SLOTS = frozenset({"counterparty", "counterparty_handle", "brand",
                         "institution"})

# The account kinds whose descriptors name a party transacted with. An
# allowlist governing two gates: a grammar may be induced for the kind, and its
# merchants may be enriched. A kind not listed here gets neither.
INDUCIBLE_KINDS = frozenset({"depository", "liability"})


def is_inducible(kind: str) -> bool:
    """Whether an account kind's descriptors name a party.

    True means a grammar may be induced for the kind and applied to it, and its
    merchants may be enriched."""
    return (kind or "").strip().lower() in INDUCIBLE_KINDS

# Unicode combining marks — general category M. Python's `re` has no \p{M} and
# `\w` excludes marks, so a Devanagari virama or vowel sign fails a shape built
# from `\w` alone. Enumerated by range, since this package takes no third-party
# regex dependency.
_MARKS = (r"̀-ͯ҃-҉֑-ֽֿׁ-ׂ"
          r"ׄ-ׅؐ-ًؚ-ٰٟۖ-ۜ"
          r"ܑܰ-݊ަ-ްࠖ-ࣣࠣ-ः"
          r"ऺ-ॏ॑-ॗॢ-ॣঁ-ঃ"
          r"়-্ৗਁ-ਃ਼-ੑଁ-ଃ"
          r"଼-ୗா-்ఀ-ౖഀ-്"
          r"ั-ฺ็-๎༘-྄ါ-ှ"
          r"ᬀ-ᬄ᷀-᷿⃐-⃰︠-︯")

# What a hole may match. All Unicode-aware, so accented Latin, Devanagari and
# Japanese lines are expressible.
#
# The distinction the two general shapes draw:
#
#   a NAME starts with a letter          {city} {institution} {counterparty}
#   a MERCHANT STRING may start with a   {brand} {noise}
#   digit
#
# The first stays narrow so {city} cannot match a bare number and swallow a
# store id.
SHAPES = {
    "words":   rf"[^\W\d_][\w{_MARKS}.'&/-]*(?:\s+[\w{_MARKS}.'&/-]+)*",
    # A card merchant string. What it adds over `words`:
    #
    #   a leading digit   `278 SPICE RACK STORE`
    #   an ampersand      as a word of its own, which `words` allows only
    #                     inside a word
    #   a processor mark  `TST* GOLDEN FORK BISTRO` — the asterisk Layer 0
    #                     already reads as an ISO 8583 DE43 marker
    #
    # `#` is left out: admitting it makes `{brand} {city} {region}` slot
    # `SPICE RACK # 03453 WEST MONROE LA` as brand `SPICE RACK # 03453 WEST`
    # and city `MONROE`. A template writing `#` as literal text with
    # {store_number} after it slots that line correctly.
    "merchant": rf"[^\W_][\w{_MARKS}.'&/*+,()-]*(?:\s+[\w{_MARKS}.'&/*+,()-]+)*",
    "word":    rf"[^\W\d_][\w{_MARKS}.'&/-]*",
    "number":  r"\d+",
    "alnum":   r"[A-Za-z0-9*#-]+",
    "date":    r"\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?",
    # An account reference the bank masked itself — `#####1234`, `xxxx9876`.
    # A digit is required, so the shape cannot swallow a bare word.
    "masked":  r"(?=[#*Xx\d-]*\d)[#*Xx\d-]{2,}",
    "contact": r"(?:\d{3}[.-]\d{3}[.-]\d{4}|\d{3}-[A-Za-z0-9]{4,9}"
               r"|[A-Za-z0-9][A-Za-z0-9-]*\.[A-Za-z]{2,4}(?:/\S*)?)",
    # How a person is addressed on a peer rail: a phone number, an email, an
    # @handle, or a bare subscriber number. Wider than `contact`, which does not
    # accept a bare string of digits.
    "handle":  r"(?:\+?\d[\d.\- ]{6,}\d|[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+"
               r"|@[A-Za-z0-9._-]{2,}|\d{7,})",
    "rest":    r".+",
}
# Each slot's default shape, so a grammar can say {date} and mean a date. A
# slot not listed here takes DEFAULT_SHAPE; a template may override with
# `{name:shape}`.
SLOT_SHAPE = {
    # `brand` and `noise` are the only slots on the wider `merchant` shape.
    # Noise may begin with a digit — a UK card line ends `ON 12 MAR` — and a
    # name may not.
    "brand": "merchant",
    "noise": "merchant",
    "date": "date", "store_number": "number", "account_ref": "masked",
    "amount": "number", "reference": "alnum", "region": "word",
    "trace": "alnum", "company_id": "alnum", "contact": "contact",
    "counterparty_handle": "handle",
}
DEFAULT_SHAPE = "words"


def shape_for(slot: str, explicit: str | None) -> str:
    return explicit or SLOT_SHAPE.get(slot, DEFAULT_SHAPE)

_HOLE = re.compile(r"\{([a-z_]+)(?::([a-z]+))?\}")
# Anything brace-shaped. A construct that looks like a hole but is not a
# well-formed one — `{brand:[A-Z]+}`, `{Brand}`, `{brand` — is refused rather
# than treated as literal text.
_BRACED = re.compile(r"\{[^}]*\}?")


class ProfileError(ValueError):
    """A grammar the vocabulary does not permit. Raised, never repaired."""


@dataclass(frozen=True)
class Template:
    """One line-shape a bank prints, as literals and named holes."""
    pattern: str
    _rx: re.Pattern = field(repr=False, compare=False, default=None)

    def slots(self) -> list[tuple[str, str]]:
        return [(m.group(1), shape_for(m.group(1), m.group(2)))
                for m in _HOLE.finditer(self.pattern)]

    def compile(self) -> re.Pattern:
        """Build the anchored expression for this template.

        Raises ProfileError for a malformed brace construct, an unknown slot or
        shape, or a slot other than `noise` repeated within one template."""
        holes = {(m.start(), m.end()) for m in _HOLE.finditer(self.pattern)}
        for m in _BRACED.finditer(self.pattern):
            if (m.start(), m.end()) not in holes:
                raise ProfileError(
                    f"{m.group(0)!r} is not a hole this vocabulary permits. A "
                    f"hole is a bare lowercase name in braces — no patterns, no "
                    f"character classes, no alternation.")
        out, last, seen = [], 0, set()
        for m in _HOLE.finditer(self.pattern):
            name, shape = m.group(1), shape_for(m.group(1), m.group(2))
            if name not in SLOTS:
                raise ProfileError(f"unknown slot {name!r}; allowed: {sorted(SLOTS)}")
            if shape not in SHAPES:
                raise ProfileError(f"unknown shape {shape!r}; allowed: {sorted(SHAPES)}")
            if name in seen and name != "noise":
                raise ProfileError(f"slot {name!r} appears twice in one template")
            seen.add(name)
            out.append(re.escape(self.pattern[last:m.start()]).replace(r"\ ", r"\s+"))
            out.append(f"(?P<{name}>{SHAPES[shape]})")
            last = m.end()
        out.append(re.escape(self.pattern[last:]).replace(r"\ ", r"\s+"))
        # Anchored at both ends: a template explains the whole line or none of
        # it, which is what makes a match lossless by construction.
        return re.compile(r"^\s*" + "".join(out) + r"\s*$", re.IGNORECASE)


def party_slot(pattern: str) -> str:
    """Returns "contact" when a template's `{contact}` holds the party, else "".

    A template naming no party at all — no brand, no institution, no
    counterparty, no counterparty_handle — is one whose `{contact}` is a
    person's contact detail rather than a shop's public number, so it is
    treated as personal.

    Reads the template's slot composition only, never the value that landed in
    a slot, so it covers grammars frozen before `counterparty_handle` existed."""
    names = {m.group(1) for m in _HOLE.finditer(pattern or "")}
    if names & PARTY_SLOTS:
        return ""
    return "contact" if "contact" in names else ""


@dataclass
class Match:
    template: str
    slots: dict

    def _promoted(self) -> str:
        """The name of a slot that is personal because of where it sits, or ""."""
        return party_slot(self.template)

    def personal(self) -> dict:
        promoted = self._promoted()
        return {k: v for k, v in self.slots.items()
                if k in PERSONAL_SLOTS or k == promoted}

    def shareable(self) -> dict:
        promoted = self._promoted()
        return {k: v for k, v in self.slots.items()
                if k not in PERSONAL_SLOTS and k != "noise" and k != promoted}

    def party(self) -> str:
        """The person on the other side, however the sender addressed them.

        The first non-empty of `counterparty`, `counterparty_handle` and the
        promoted slot; "" when the template names no person."""
        for name in ("counterparty", "counterparty_handle", self._promoted()):
            if name and self.slots.get(name):
                return self.slots[name]
        return ""


@dataclass
class Profile:
    """A bank's line grammar for one kind of statement."""
    institution: str
    kind: str
    version: str
    templates: list[Template] = field(default_factory=list)
    induced_from: int = 0            # how many descriptors it was written against
    measured: float = 0.0            # movement-weighted coverage when it was written
    format: str = PROFILE_FORMAT

    @property
    def id(self) -> str:
        return f"{_slug(self.institution)}-{_slug(self.kind)}-{self.version}"

    def compiled(self) -> list[tuple[Template, re.Pattern]]:
        return [(t, t.compile()) for t in self.templates]

    def apply(self, descriptor: str) -> Match | None:
        """The Match for the first template explaining the whole line, or None.

        Template order is part of the grammar. None is a legitimate answer and
        the signal that a line needs a rule this profile does not have yet."""
        # Checked before any template rather than after, so a shape refused a
        # grammar stays refused however plausible a template looks against it.
        if is_never_templatable(descriptor or ""):
            return None
        for t, rx in self.compiled():
            m = rx.match(descriptor or "")
            if m:
                return Match(t.pattern, {k: (v or "").strip()
                                         for k, v in m.groupdict().items()})
        return None

    def weighted_coverage(self, counts: dict) -> float:
        """Share of movements explained, given `{descriptor: movement count}`.

        Distinct from `coverage`, which weights every distinct line equally: a
        grammar explaining many one-off lines and missing the daily one scores
        well there and poorly here. Returns 0.0 for empty counts."""
        total = sum(counts.values()) or 1
        return sum(n for d, n in counts.items() if self.apply(d)) / total

    def coverage(self, descriptors) -> tuple[float, list[str]]:
        """Returns `(share, unmatched)` over distinct descriptors, unweighted.

        Every distinct line counts once. Measured against every descriptor on
        the statement rather than the sample the model saw."""
        unmatched = [d for d in descriptors if self.apply(d) is None]
        total = len(list(descriptors))
        return ((total - len(unmatched)) / total if total else 0.0), unmatched

    def to_dict(self) -> dict:
        return {"format": self.format, "institution": self.institution,
                "kind": self.kind, "version": self.version,
                "induced_from": self.induced_from,
                "measured": round(self.measured, 4),
                "templates": [t.pattern for t in self.templates]}

    @classmethod
    def from_dict(cls, d: dict) -> "Profile":
        if d.get("format") != PROFILE_FORMAT:
            raise ProfileError(f"unknown profile format {d.get('format')!r}")
        p = cls(institution=d["institution"], kind=d["kind"], version=d["version"],
                templates=[Template(t) for t in d.get("templates", [])],
                induced_from=int(d.get("induced_from", 0)),
                measured=float(d.get("measured", 0.0)))
        validate(p)
        return p

    def dumps(self) -> str:
        return json.dumps(self.to_dict(), indent=2)


def validate(profile: Profile) -> Profile:
    """Refuse a grammar the vocabulary does not permit. Returns the profile.

    Format only: at least one template, and every template compiles under the
    closed slot and shape sets. Raises ProfileError otherwise.

    Does not require a template to have a hole; that rule needs `counts` and
    lives in `validate_evidence`. This also runs at load time, where there is no
    evidence and a frozen fixed phrase must still load."""
    if not profile.templates:
        raise ProfileError("a profile with no templates explains nothing")
    for t in profile.templates:
        t.compile()
    return profile


def validate_evidence(profile: Profile, counts: dict | None) -> Profile:
    """Refuse a slotless template the lines do not support. Returns the profile.

    Induction and write time only, since it needs `counts`. A slotless template
    matches one exact line: a copied example when the line occurred once, the
    bank's own fixed phrase when it recurs, since a fee prints the identical
    string every month. So a slotless template is kept only when some line it
    matches occurs more than once, and raises ProfileError otherwise. `counts`
    of None refuses every slotless template.

    The rule lives only here; `validate` does not carry a second copy."""
    for t in profile.templates:
        if t.slots():
            continue
        rx = t.compile()
        if not any(n > 1 and rx.match(d) for d, n in (counts or {}).items()):
            raise ProfileError(
                f"template {t.pattern!r} has no slots and matches no line this "
                f"institution prints more than once — an example, not a grammar")
    return profile


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").strip().lower()).strip("-") or "unknown"


class ProfileStore:
    """Profiles on disk, one file per version; the filename is the version.

    The same pack convention as prompts, persona packs and the expectations
    registry. `write` refuses to overwrite, so bumping is the only way to change
    a grammar and a superseded version keeps resolving for the records that name
    it.

    Plain JSON, unencrypted, outside the vault: a grammar is the bank's and is
    identical for every customer of that bank.
    """

    def __init__(self, directory, shipped=None):
        self._dir = pathlib.Path(directory).expanduser()
        # What travels with the package. Read, never written; promotion into it
        # is a person's decision.
        self._shipped = pathlib.Path(shipped).expanduser() if shipped else None

    @property
    def directory(self) -> pathlib.Path:
        return self._dir

    def path(self, profile_id: str) -> pathlib.Path:
        return self._dir / f"{profile_id}.json"

    def ids(self) -> list[str]:
        found = set()
        for d in (self._dir, self._shipped):
            if d and d.is_dir():
                found |= {p.stem for p in d.glob("*.json")}
        return sorted(found)

    def _file(self, profile_id: str):
        """The file backing a profile id, or None. Learned first, shipped
        second."""
        for d in (self._dir, self._shipped):
            if d and (d / f"{profile_id}.json").is_file():
                return d / f"{profile_id}.json"
        return None

    def versions(self, institution: str, kind: str) -> list[str]:
        prefix = f"{_slug(institution)}-{_slug(kind)}-"
        return [i for i in self.ids() if i.startswith(prefix)]

    def load(self, profile_id: str) -> Profile:
        path = self._file(profile_id)
        if path is None:
            raise ProfileError(
                f"profile {profile_id!r} not found in {self._dir}. A stored "
                f"decomposition names the grammar that produced it; if this is a "
                f"version that was deleted rather than superseded, recover it "
                f"rather than pointing the id at the current grammar.")
        # A shipped grammar is validated on the way in like any other.
        return Profile.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def latest(self, institution: str, kind: str) -> Profile | None:
        """The highest version for a pair, or None when the pair has none.

        None is a legitimate answer: the signal to induce one."""
        found = self.versions(institution, kind)
        return self.load(sorted(found)[-1]) if found else None

    def next_version(self, institution: str, kind: str) -> str:
        used = {int(m.group(1)) for i in self.versions(institution, kind)
                if (m := re.search(r"-v(\d+)$", i))}
        return f"v{(max(used) + 1) if used else 1}"

    def latest_for(self, institution: str, kind: str) -> "Profile | None":
        """The grammar to apply to this account, or None.

        Always None for a kind that names no party, whatever files exist."""
        return self.latest(institution, kind) if is_inducible(kind) else None

    def write(self, profile: Profile, against: dict | None = None,
              force: bool = False) -> pathlib.Path:
        """Freeze a grammar to disk and return the path it was written to.

        Raises ProfileError when the profile does not validate, when its kind
        names no party, when its id already exists, or when `against` is given
        and the grammar explains a smaller share of those movements than the
        version it succeeds. `force` accepts a lower share deliberately.

        `against` is `{descriptor: movement count}`; without it neither the
        evidence check nor the coverage comparison runs."""
        validate(profile)
        # Evidence is checked only where there is evidence.
        if against:
            validate_evidence(profile, against)
        if not is_inducible(profile.kind):
            raise ProfileError(
                f"{profile.kind!r} descriptors name no counterparty, so a grammar "
                f"over them would mis-slot rather than parse. Inducible kinds: "
                f"{sorted(INDUCIBLE_KINDS)}. Instrument events need their own "
                f"vocabulary (instrumentcore), not this one.")
        prior = self.latest(profile.institution, profile.kind)
        if prior is not None and against and not force:
            was, now = prior.weighted_coverage(against), profile.weighted_coverage(against)
            if now < was:
                raise ProfileError(
                    f"{profile.id} explains {now:.1%} of these movements where "
                    f"{prior.id} explains {was:.1%}. Induction is stochastic — "
                    f"re-running can return a worse grammar — and `latest` wins "
                    f"by version, so writing this would put the weaker one in "
                    f"use. Re-induce, or pass force=True if the lower number is "
                    f"wanted deliberately.")
        path = self.path(profile.id)
        if path.exists():
            raise ProfileError(
                f"{profile.id} already exists at {path}. A released profile is "
                f"never edited — induce the next version instead "
                f"(next free: {self.next_version(profile.institution, profile.kind)}).")
        self._dir.mkdir(parents=True, exist_ok=True)
        path.write_text(profile.dumps() + "\n", encoding="utf-8")
        return path
