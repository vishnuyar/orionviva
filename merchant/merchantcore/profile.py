"""A descriptor grammar, held as data.

A bank composes its statement lines from templates. `ZELLE TO {counterparty}`,
`CARD PURCHASE {date} {brand} {city} {region}`. Those templates are the
bank's, not the merchant's, and they are the same for every customer of that
bank — which makes them impersonal, shareable, and worth learning exactly once.

A profile is a list of such templates and nothing else. The model that induces
one may write **only** what this vocabulary allows: literal words, and named
holes drawn from a closed set. It never writes a regular expression — the regex
is compiled here, from the template, so a grammar cannot express more than the
vocabulary permits.

Two properties fall out of that choice rather than being checked afterwards.

**Losslessness is structural.** A template must match the whole descriptor, end
to end, or it does not match at all. So any descriptor a profile claims is a
descriptor every character of which landed in a slot. There is no partial parse
to mistake for a complete one.

**Privacy is a slot name.** `counterparty` and `account_ref` are personal by
declaration, in the vocabulary, in code. Nothing downstream inspects extracted
text to decide whether it may travel: the slot it came from already said.
"""

from __future__ import annotations

import json
import pathlib
import re
from dataclasses import dataclass, field

from .descriptor import is_never_templatable

PROFILE_FORMAT = "prof-v1"

# The closed slot vocabulary. A profile may name these and nothing else.
SLOTS = {
    "brand":        "the merchant or payee as the statement prints it",
    "city":         "a town or city",
    "region":       "a state, province or country code",
    "store_number":  "an outlet number",
    "counterparty": "a PERSON on the other side of the payment, named",
    # A peer payment identifies the other party however the sender addressed
    # them — a name, a phone number, an email, a username. All four are the same
    # thing wearing different clothes, and a vocabulary that only had a name slot
    # sent a model looking for somewhere else to put a phone number. It found
    # {contact}, which was not personal, and a person's phone number became
    # shareable. Found on the first real induction.
    "counterparty_handle": "the person on the other side identified by a phone "
                           "number, email or username instead of a name",
    "institution":  "a named bank or platform",
    "account_ref":  "digits identifying an account, possibly masked with # or *",
    "reference":    "a confirmation or order id",
    # A real ACH line carries two ids at once — the trace number the network
    # assigned this movement, and the originator's standing company id. They
    # differ in what they identify and in how long they last, so they are two
    # names rather than one name used twice.
    "trace":        "the number identifying THIS movement on the network",
    "company_id":   "the standing id of the originator, the same every month",
    "contact":      "a phone number or web address the merchant printed",
    "date":         "a date printed inside the line",
    "amount":       "a figure printed inside the line",
    "purpose":      "the bank's own word for what the movement is",
    "noise":        "filler the line always carries and nothing needs",
}

# Slots whose contents are personal by declaration. Not a judgement about the
# text — a property of the slot, decided once, here.
PERSONAL_SLOTS = frozenset({"counterparty", "counterparty_handle", "account_ref"})

# Slots that name the party a payment was made to or from. A template with none
# of these describes a payment with nobody in it, which is what makes the rule
# in `party_slot` structural rather than a guess about text.
PARTY_SLOTS = frozenset({"counterparty", "counterparty_handle", "brand",
                         "institution"})

# Account kinds whose descriptors name a PARTY YOU TRANSACTED WITH, and are
# therefore worth a grammar. Deliberately narrow.
#
# A grammar exists to find a counterparty inside a sentence a bank composed. A
# depository line and a card line both describe money moving between you and
# somebody — a merchant, an employer, a person, another institution. An
# investment activity line does not: `You Sold Short-term gain: $602.78`
# describes a trade against a security, and there is no party in it at all.
#
# Inducing over those lines would be worse than useless. Every name in this
# vocabulary asserts something about a party or a place, so a model shown trade
# activity must either fail the coverage gate or force `Short-term gain` into a
# slot called `{purpose}` and a security into `{brand}` — a confident,
# consistent mis-slotting applied to every line that institution ever prints,
# which is the exact failure the closed vocabulary exists to prevent.
#
# Instrument events need their own vocabulary — security, action, quantity,
# price, realized gain — and that belongs to `instrumentcore`, deferred by
# decision. Until it exists the honest answer for an investment line is that no
# grammar applies, which is the same answer the stream engine reaches when it
# marks those movements `activity` rather than giving them a counterparty.
INDUCIBLE_KINDS = frozenset({"depository", "liability"})


def is_inducible(kind: str) -> bool:
    """Whether a grammar may be induced for an account kind, and applied to it."""
    return (kind or "").strip().lower() in INDUCIBLE_KINDS

# What a hole may match. Deliberately few: a bank template is words and numbers
# in a fixed order, and every shape added here is a shape a model can misuse.
SHAPES = {
    "words":   r"[A-Za-z][A-Za-z.'&/-]*(?:\s+[A-Za-z0-9][A-Za-z0-9.'&/-]*)*",
    "word":    r"[A-Za-z][A-Za-z.'&/-]*",
    "number":  r"\d+",
    "alnum":   r"[A-Za-z0-9*#-]+",
    "date":    r"\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?",
    # An account reference the bank masked itself — `#####1234`, `xxxx9876`.
    # It must still carry a digit, so the shape cannot swallow a bare word.
    "masked":  r"(?=[#*Xx\d-]*\d)[#*Xx\d-]{2,}",
    "contact": r"(?:\d{3}[.-]\d{3}[.-]\d{4}|\d{3}-[A-Za-z0-9]{4,9}"
               r"|[A-Za-z0-9][A-Za-z0-9-]*\.[A-Za-z]{2,4}(?:/\S*)?)",
    # How a person is addressed on a peer rail: a phone number, an email, an
    # @handle, or a bare subscriber number. Wider than `contact` because it must
    # accept a bare string of digits, and that is exactly why it is personal.
    "handle":  r"(?:\+?\d[\d.\- ]{6,}\d|[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+"
               r"|@[A-Za-z0-9._-]{2,}|\d{7,})",
    "rest":    r".+",
}
# Each slot's natural shape, so a grammar can say {date} and mean a date. A
# vocabulary whose obvious spelling is the wrong one is a trap for the model
# that writes into it, and the model does not get to see this file.
SLOT_SHAPE = {
    "date": "date", "store_number": "number", "account_ref": "masked",
    "amount": "number", "reference": "alnum", "region": "word",
    "trace": "alnum", "company_id": "alnum", "contact": "contact",
    "counterparty_handle": "handle",
}
DEFAULT_SHAPE = "words"


def shape_for(slot: str, explicit: str | None) -> str:
    return explicit or SLOT_SHAPE.get(slot, DEFAULT_SHAPE)

_HOLE = re.compile(r"\{([a-z_]+)(?::([a-z]+))?\}")
# Anything brace-shaped at all. A construct that LOOKS like a hole but is not a
# well-formed one — `{brand:[A-Z]+}`, `{Brand}`, `{brand` — must be refused, not
# quietly treated as literal text: as a literal it would simply never match, so
# the grammar would look accepted and explain nothing, which is the failure mode
# hardest to see from the outside.
_BRACED = re.compile(r"\{[^}]*\}?")


class ProfileError(ValueError):
    """A grammar that the vocabulary does not permit. Raised rather than
    repaired: a profile is applied to every line a bank ever prints, so one
    accepted-but-wrong template is wrong thousands of times."""


@dataclass(frozen=True)
class Template:
    """One line-shape a bank prints, as literals and named holes."""
    pattern: str
    _rx: re.Pattern = field(repr=False, compare=False, default=None)

    def slots(self) -> list[tuple[str, str]]:
        return [(m.group(1), shape_for(m.group(1), m.group(2)))
                for m in _HOLE.finditer(self.pattern)]

    def compile(self) -> re.Pattern:
        """Build the anchored expression. The model supplies the template; the
        expression is written here, which is what bounds the vocabulary."""
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
        # it. That is what makes a match lossless by construction.
        return re.compile(r"^\s*" + "".join(out) + r"\s*$", re.IGNORECASE)


def party_slot(pattern: str) -> str:
    """Whether a template's `{contact}` is the MERCHANT's or the PARTY's.

    A frozen grammar already on disk contains `Zelle Payment To {contact}
    {reference}` — a person addressed by phone number, in a slot declared
    shareable. The vocabulary caused it: rule 7 said `{counterparty}` is for a
    person "you would recognise by name", a phone number is not a name, and
    `{contact}` was the only other place to put one. `counterparty_handle` fixes
    that for every induction from now on, but a released profile is never
    edited, so the grammars written today would keep leaking until they are
    superseded.

    This closes it for those too, without inspecting a single character of
    extracted text. A template describes a payment, and a payment has a party.
    If a template names no party at all — no brand, no institution, no
    counterparty — then whatever else it holds IS the party, and a `{contact}`
    in that position is a person's contact detail rather than a shop's.

    Structural, not textual: it reads the template's slot composition, which the
    vocabulary already fixed, and never the value that landed in the slot."""
    names = {m.group(1) for m in _HOLE.finditer(pattern or "")}
    if names & PARTY_SLOTS:
        return ""
    return "contact" if "contact" in names else ""


@dataclass
class Match:
    template: str
    slots: dict

    def _promoted(self) -> str:
        """A slot that is personal only because of where it sits."""
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
        """The person on the other side, however the sender addressed them."""
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
        """First template that explains the WHOLE line wins. None means this
        grammar has nothing to say, which is a legitimate answer and the signal
        that a line needs a rule the profile does not have yet."""
        # Checked before any template, not after: a shape refused a grammar must
        # be refused however plausible a template looks against it, or the
        # refusal is only as strong as the templates that happen to exist today.
        if is_never_templatable(descriptor or ""):
            return None
        for t, rx in self.compiled():
            m = rx.match(descriptor or "")
            if m:
                return Match(t.pattern, {k: (v or "").strip()
                                         for k, v in m.groupdict().items()})
        return None

    def weighted_coverage(self, counts: dict) -> float:
        """Share of MOVEMENTS explained, given `{descriptor: movement count}`.

        The number that matters, and the only one this project should print.
        `coverage()` weights every distinct line equally, so a grammar that
        explains three hundred one-off lines and misses the daily one scores
        well — and the two numbers were being shown side by side under the same
        word, one at induction time and one when reporting an existing profile.
        A metric with two meanings is a metric nobody can act on."""
        total = sum(counts.values()) or 1
        return sum(n for d, n in counts.items() if self.apply(d)) / total

    def coverage(self, descriptors) -> tuple[float, list[str]]:
        """Share of descriptors this grammar explains, and the ones it does not.

        Measured against every descriptor on the statement, not the sample the
        model was shown. A grammar that explains its own examples and nothing
        else has learned the sample rather than the bank."""
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
    """Refuse a grammar the vocabulary does not permit, before it is applied.

    Every template must compile under the closed slot and shape sets, and a
    template with no holes is a literal that matches one exact line — almost
    always a sign the model copied an example instead of generalizing it."""
    if not profile.templates:
        raise ProfileError("a profile with no templates explains nothing")
    for t in profile.templates:
        t.compile()
        if not t.slots():
            raise ProfileError(f"template {t.pattern!r} has no slots — it is an example, "
                               "not a grammar")
    return profile


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").strip().lower()).strip("-") or "unknown"


class ProfileStore:
    """Profiles on disk, one file per version, the filename IS the version.

    The fourth pack in this project to work this way, after prompts, persona
    packs and the expectations registry, and it earns it for the strongest
    reason of the four: a profile is applied to every line a bank ever prints.
    A template accepted and then quietly corrected would leave two different
    meanings sharing one id, and every record stamped with that id becomes
    unreadable. So `write` REFUSES to overwrite. Bumping is the only way to
    change a grammar, and the superseded version keeps resolving for the records
    that name it.

    Plain JSON, unencrypted, outside the vault: a grammar is the bank's, not the
    account holder's, and it is identical for every customer of that bank.
    """

    def __init__(self, directory, shipped=None):
        self._dir = pathlib.Path(directory).expanduser()
        # What travels with the package. Read, never written: promotion into it
        # is a person's decision, because a grammar published there is published
        # to everybody and only reading catches a mis-slotted one.
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
        """Learned first, shipped second — what this installation worked out
        beats what it was handed, the same precedence a local ruling has over a
        commons import."""
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
        # A shipped grammar is validated on the way in like any other: it is
        # data from elsewhere, and the door does not open wider for it.
        return Profile.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def latest(self, institution: str, kind: str) -> Profile | None:
        """The highest version for a pair, or None if this bank has no grammar
        yet — which is a legitimate answer and the signal to induce one."""
        found = self.versions(institution, kind)
        return self.load(sorted(found)[-1]) if found else None

    def next_version(self, institution: str, kind: str) -> str:
        used = {int(m.group(1)) for i in self.versions(institution, kind)
                if (m := re.search(r"-v(\d+)$", i))}
        return f"v{(max(used) + 1) if used else 1}"

    def latest_for(self, institution: str, kind: str) -> "Profile | None":
        """The grammar to apply to this account, or None.

        None for a kind that names no party — checked HERE rather than at each
        call site, so a profile that should never have existed cannot be applied
        by whoever forgets."""
        return self.latest(institution, kind) if is_inducible(kind) else None

    def write(self, profile: Profile, against: dict | None = None,
              force: bool = False) -> pathlib.Path:
        """Freeze a grammar. Refuses one measurably worse than what it succeeds.

        Induction is stochastic: the same prompt over the same forty lines
        produced 27 templates at 84% one run and 33 at 82% the next. Nothing in
        the pack rules noticed, because the gate is absolute — and `latest` wins
        by version number, so a worse re-run silently became the grammar in use.

        A version must therefore beat its predecessor on the same measurement
        over the same lines, or say so and be refused. `force` exists for the
        case where a worse number is wanted deliberately — a grammar that covers
        less but slots more honestly — and it has to be asked for."""
        validate(profile)
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
