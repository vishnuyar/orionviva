"""Layer 0: what a descriptor gives up without a model and without a profile.

A card descriptor is the flattened tail of ISO 8583 DE43, which is positional
and fixed-width — merchant name, then city, then a state or country code. The
card networks specify further structures that hold at every bank: an asterisk
at index 2, 3, 7 or 12 separating a brand prefix from a product or
sub-merchant, and the 13-character city slot carrying a phone number or URL
instead of a place when the card was not present. An ACH line carries the NACHA
Standard Entry Class code and Company Identification in its tail. All of that
is specification, so it is parsed rather than learned or guessed.

A span is claimed only where a rule proves the claim. What is left over comes
back as ``residue`` rather than being assigned to a plausible-looking field,
and ``coverage`` reports how much of the string went unclaimed, so a parse that
explains nothing says so.

Design rationale: docs/the-conduit-and-the-counterparty.md
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

PARSER_VERSION = "desc-v2"

# The asterisk is a separator at exactly these indexes: a 2, 3, 7 or 12
# character brand prefix, then '*', then the product or sub-merchant.
# Processor-mandated, positional, and the same in every country.
#
# Constraint: a processor prefix is claimed by the asterisk's position, never by
# a list of processor names.
_ASTERISK_AT = (2, 3, 7, 12)

_DATE = re.compile(r"\b\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?\b")
_PHONE_SLOT = re.compile(r"\b\d{3}-[A-Za-z0-9]{4,9}\b")
_DOMAIN = re.compile(
    r"\b[a-z0-9][a-z0-9-]{1,}\.(?:com|net|org|co|io|us|uk|in)(?:/[A-Za-z0-9._~%-]*)*",
    re.I)
_STORE = re.compile(r"(?:\bstore\s*)?#\s*\d+\b|\bstore\s+\d{2,}\b", re.I)
_REGION_TAIL = re.compile(r"\b([A-Z]{2})\s*$")
_REFERENCE = re.compile(r"\b(?=[A-Z0-9]*\d)[A-Z0-9]{6,}\b")
_LONGNUM = re.compile(r"\b\d{4,}\b")

# Fedwire/SWIFT field tags. `Imad:` and `Omad:` are the input and output
# message accountability data identifiers, `Bnf/` the beneficiary tag, `A/C:`
# the account tag — message format, not English words.
#
# A wire is a Fedwire/SWIFT message dumped into a display line, and it carries
# an operator free-text `Ref:` field holding whatever the sender typed. No slot
# name can describe a field whose contents are unconstrained, so this is the one
# line shape refused a grammar rather than parsed. Two distinct markers are
# required, so an ordinary line printing "Ref:" is not swept up.
_WIRE_MARKERS = (r"\bvia:", r"\ba/c:", r"\bimad:", r"\bomad:", r"\btrn:",
                 r"\bbnf/", r"\bref:")
_WIRE = re.compile("|".join(_WIRE_MARKERS), re.I)
WIRE_RULE = "wire_message_dump"


# The NACHA batch header, rendered. An ACH line ends with the Standard Entry
# Class code and the Company Identification, in that order:
#
#     <Company Name (16)> <Company Entry Description (10)> <SEC (3)> ID: <id (10)>
#
# The split between Company Name and Company Entry Description is not
# recoverable from one line: the fields are fixed-width in the file and the
# bank collapsed the padding on the way to the display line. `split_ach_heads`
# recovers it from the statement as a whole.
#
# _SEC_CODES is the complete closed set from the published standard. Unlike the
# asterisk indexes it is US-scope: nothing outside this rule may depend on an
# SEC code being present.
_SEC_CODES = ("PPD", "CCD", "CTX", "WEB", "TEL", "ARC", "BOC", "POP", "RCK", "IAT")
_ACH_TAIL = re.compile(
    r"\b(" + "|".join(_SEC_CODES) + r")\s+ID:\s*(\S+)\s*$", re.I)


def is_never_templatable(raw: str) -> bool:
    """True for a line no induced grammar may claim: two or more wire markers.

    A boundary judgement rather than a parsing one: a wire's operator free-text
    field can hold anything, so no slot name can describe it. Consulted before
    any template is tried."""
    return len({m.group(0).lower() for m in _WIRE.finditer(raw or "")}) >= 2


@dataclass(frozen=True)
class Slot:
    """One claimed span, the rule that claimed it, and how it was obtained.

    `certain` is True when a published layout proves the slot and False when
    only adjacency suggests it; the distinction rides into the record as
    `provenance`."""
    name: str
    text: str
    start: int
    end: int
    rule: str
    certain: bool = True


@dataclass
class DescriptorParse:
    raw: str
    slots: list[Slot] = field(default_factory=list)
    residue: str = ""
    coverage: float = 0.0
    card_not_present: bool = False
    never_templatable: bool = False
    ach: bool = False

    def get(self, name: str) -> str:
        for s in self.slots:
            if s.name == name:
                return s.text
        return ""

    @property
    def rules(self) -> list[str]:
        return [s.rule for s in self.slots]

    residue_runs: int = 0

    @property
    def clean(self) -> bool:
        """At most one unclaimed run remains.

        Layer 0 cannot claim the merchant name, since no published rule says
        where it ends, so zero residue is not achievable here. One contiguous
        run is a brand with the structure stripped away around it; scattered
        fragments mean the rules fired in the wrong places."""
        return self.residue_runs <= 1

    def to_dict(self) -> dict:
        return {"raw": self.raw, "residue": self.residue,
                "coverage": round(self.coverage, 3),
                "residue_runs": self.residue_runs, "clean": self.clean,
                "card_not_present": self.card_not_present,
                "never_templatable": self.never_templatable,
                "ach": self.ach,
                "parser_version": PARSER_VERSION,
                "slots": [{"name": s.name, "text": s.text, "rule": s.rule,
                           "provenance": "parsed" if s.certain else "inferred"}
                          for s in self.slots]}


def _claim(taken: list[bool], start: int, end: int) -> bool:
    """Mark a span as claimed, returning whether it was.

    A span overlapping an already-claimed one is refused and nothing is marked,
    so two rules cannot both own the same characters."""
    if any(taken[start:end]):
        return False
    for i in range(start, end):
        taken[i] = True
    return True


def parse_descriptor(raw: str) -> DescriptorParse:
    """Claim every span a published rule can prove, and report the rest."""
    text = (raw or "").strip()
    out = DescriptorParse(raw=text, never_templatable=is_never_templatable(text))
    if not text:
        return out
    taken = [False] * len(text)

    def add(name: str, m: re.Match, rule: str, certain: bool = True) -> None:
        if _claim(taken, m.start(), m.end()):
            out.slots.append(Slot(name, m.group(0).strip(), m.start(), m.end(),
                                  rule, certain))

    # The asterisk convention, first — it decides what the leading token means.
    for i in _ASTERISK_AT:
        if i < len(text) and text[i] == "*":
            if _claim(taken, 0, i + 1):
                out.slots.append(Slot("aggregator", text[:i].strip(), 0, i + 1,
                                      f"asterisk_at_{i}"))
            break

    # The ACH tail, before anything else can claim its digits. The Company
    # Identification is a long number, so the reference rules below would
    # otherwise take it.
    am = _ACH_TAIL.search(text)
    if am:
        if _claim(taken, am.start(1), am.end(1)):
            out.slots.append(Slot("sec_code", am.group(1).upper(),
                                  am.start(1), am.end(1), "nacha_sec_code"))
            out.ach = True
        if _claim(taken, am.start(2), am.end(2)):
            out.slots.append(Slot("company_id", am.group(2),
                                  am.start(2), am.end(2), "nacha_company_id"))
        # The literal " ID:" between them belongs to neither field.
        _claim(taken, am.end(1), am.start(2))

    # A phone or a URL where the city belongs means the card was not present.
    for rx, rule in ((_PHONE_SLOT, "phone_in_city_slot"), (_DOMAIN, "url_in_city_slot")):
        for m in rx.finditer(text):
            before = len(out.slots)
            add("contact", m, rule)
            if len(out.slots) > before:
                out.card_not_present = True

    for m in _DATE.finditer(text):
        add("posting_date", m, "date_fragment")
    for m in _STORE.finditer(text):
        add("store_number", m, "store_token")

    # DE43 adjacency: a two-letter code at the end is the state/country subfield,
    # and the token immediately before it is the city subfield.
    m = _REGION_TAIL.search(text)
    if m and _claim(taken, m.start(1), m.end(1)):
        out.slots.append(Slot("region", m.group(1), m.start(1), m.end(1), "de43_region_tail"))
        head = text[:m.start(1)].rstrip()
        cm = re.search(r"([A-Za-z][A-Za-z.'-]*)\s*$", head)
        free = cm and (cm.start(1) == 0 or text[cm.start(1) - 1].isspace())
        if free and _claim(taken, cm.start(1), cm.end(1)):
            out.slots.append(Slot("city", cm.group(1), cm.start(1), cm.end(1),
                                  "de43_city_before_region", certain=False))

    for m in _REFERENCE.finditer(text):
        add("reference", m, "reference_run")
    for m in _LONGNUM.finditer(text):
        add("reference", m, "long_number")

    # Whatever no rule could prove. Named, not assigned.
    runs, current = [], []
    for i, c in enumerate(text):
        if taken[i]:
            if current:
                runs.append("".join(current)); current = []
        else:
            current.append(c)
    if current:
        runs.append("".join(current))
    runs = [r for r in (re.sub(r"\s+", " ", r).strip(" *-,/") for r in runs) if r]
    out.residue_runs = len(runs)
    out.residue = " ".join(runs)
    body = [c for c in text if not c.isspace()]
    claimed = [c for i, c in enumerate(text) if taken[i] and not c.isspace()]
    out.coverage = (len(claimed) / len(body)) if body else 0.0
    out.slots.sort(key=lambda s: s.start)
    return out


def word_owners(descriptors) -> dict:
    """`{word: set of normalized keys printing it}`, for alphabetic words only.

    A diagnostic for the streams report; nothing keys on the counts. The count
    is over normalized keys, which fragment one merchant into several.

    Returns {} for fewer than ten distinct non-empty lines."""
    lines = [d for d in {x for x in descriptors if x} if d.strip()]
    if len(lines) < 10:
        return {}
    from .normalize import normalize_merchant
    owners: dict[str, set] = {}
    for d in lines:
        key = normalize_merchant(d) or d.lower()
        for tok in {t.lower().strip(".,:;#*/-") for t in d.split()}:
            if tok and tok.isalpha():
                owners.setdefault(tok, set()).add(key)
    return owners


def linted_example(descriptor: str) -> str:
    """The most the enrichment boundary may carry: brand words, and nothing else.

    Every span a published rule can prove is removed first, then every
    remaining token carrying a digit, then anything shorter than two
    characters. Truncated to 64 characters. Lossy by design — the example
    exists to help identify a brand.

    Guarantees that no number, date, reference or contact detail crosses. Does
    not guarantee the result is impersonal: a peer payment's residue is a
    person's name, and only the slot it came from settles that (an induced
    grammar's ``{counterparty}``, or ``is_shareable`` where no grammar
    exists)."""
    candidate = brand_candidate(parse_descriptor(descriptor or ""))
    words = [w for w in re.split(r"\s+", candidate)
             if w and not any(c.isdigit() for c in w)]
    words = [w.strip(".,:;*/-#") for w in words]
    return " ".join(w for w in words if len(w) > 1)[:64].strip()


def split_ach_heads(descriptors) -> dict:
    """Split each ACH head into Company Name and Company Entry Description,
    using the statement as a whole.

    A single line cannot give this: the two fields are fixed-width in the NACHA
    file (16 characters then 10), and the bank collapsed the padding on the way
    to the display line, so `Acmeco ACH Pmt` carries no boundary a per-line
    rule could find.

    The corpus gives it, from the same property `skeletons` uses: the entry
    description recurs across originators and the company name does not. So the
    longest trailing phrase of up to four words that at least one other
    originator also prints is the description, and what precedes it is the name.

    Parameter-free; no vocabulary of known descriptions is consulted. An
    originator appearing once, with a description no other originator uses,
    cannot be split and comes back name-only with an empty description.

    Returns ``{descriptor: (company_name, entry_description)}`` for ACH lines.
    """
    heads: dict[str, list[str]] = {}
    for d in {x for x in descriptors if x}:
        p = parse_descriptor(d)
        if p.ach and p.residue:
            heads[d] = p.residue.split()

    # How many distinct originators end with each trailing phrase. A phrase
    # ending two originators' heads is the bank's, not a company's.
    tail_owners: dict[str, set] = {}
    for d, words in heads.items():
        for i in range(1, min(len(words), 4) + 1):     # a description is 1-4 words
            phrase = " ".join(w.lower() for w in words[-i:])
            tail_owners.setdefault(phrase, set()).add(" ".join(words[:-i]).lower())

    out: dict[str, tuple] = {}
    for d, words in heads.items():
        best = ""
        # Longest trailing phrase that more than one originator also prints.
        for i in range(min(len(words), 4), 0, -1):
            if len(words) == i:
                continue                      # a head that is all description names nobody
            phrase = " ".join(w.lower() for w in words[-i:])
            if len(tail_owners.get(phrase, ())) > 1:
                best = " ".join(words[-i:])
                break
        name = " ".join(words[:len(words) - len(best.split())]) if best else " ".join(words)
        out[d] = (name.strip(), best.strip())
    return out


def brand_candidate(parse: DescriptorParse) -> str:
    """The part of a descriptor most likely to name the merchant.

    The residue, once every provable span is removed — unless the residue holds
    no alphabetic run of three characters or more, in which case the
    `aggregator` slot is returned instead (a marketplace printing an order id
    where the retailer belongs leaves nothing usable).

    A candidate for identification, not an identity."""
    residue = parse.residue
    usable = any(len(tok) >= 3 and tok.isalpha() for tok in re.split(r"[^A-Za-z]+", residue))
    return residue if usable else parse.get("aggregator")
