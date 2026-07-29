"""Layer 0: what a descriptor gives up without a model and without a profile.

A card descriptor is the flattened tail of ISO 8583 DE43, which is positional
and fixed-width — merchant name, then city, then a state or country code. The
card networks additionally specify structures that hold at every bank on earth:
an asterisk at index 3, 7 or 12 separating a brand prefix from a product or
sub-merchant; the 13-character city slot carrying a phone number or URL instead
of a place when the card was not present; a small set of processor prefixes.

None of that needs to be learned, guessed, or asked about. It is specification,
so it is parsed.

What this module refuses to do is as important as what it does. It claims a span
only when a rule proves the claim. Whatever is left over is returned as
``residue`` rather than assigned to a plausible-looking field, and ``coverage``
reports how much of the string went unclaimed. A parse that explains nothing
says so, instead of returning a confident brand that is really a city.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

PARSER_VERSION = "desc-v1"

# The asterisk is a separator at exactly these indexes: a 3, 7 or 12 character
# brand prefix, then '*', then the product or sub-merchant. Processor-mandated.
_ASTERISK_AT = (3, 7, 12)

# Payment facilitators and terminals that put themselves where the merchant goes.
_PROCESSORS = ("sq *", "sq*", "sp *", "sp*", "tst*", "tst *", "pp*", "paypal *",
               "paypal*", "ven*", "venmo*", "wpy*", "eb *", "ic*", "pos debit",
               "pos purchase", "debit card purchase", "checkcard", "ach pmt",
               "web pymt", "ppd id:")

_DATE = re.compile(r"\b\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?\b")
_PHONE_SLOT = re.compile(r"\b\d{3}-[A-Za-z0-9]{4,9}\b")
_DOMAIN = re.compile(
    r"\b[a-z0-9][a-z0-9-]{1,}\.(?:com|net|org|co|io|us|uk|in)(?:/[A-Za-z0-9._~%-]*)*",
    re.I)
_STORE = re.compile(r"(?:\bstore\s*)?#\s*\d+\b|\bstore\s+\d{2,}\b", re.I)
_REGION_TAIL = re.compile(r"\b([A-Z]{2})\s*$")
_REFERENCE = re.compile(r"\b(?=[A-Z0-9]*\d)[A-Z0-9]{6,}\b")
_LONGNUM = re.compile(r"\b\d{4,}\b")

# A wire is not a descriptor with more fields in it. It is a Fedwire/SWIFT
# message dumped into a display line: the beneficiary bank's routing number, the
# beneficiary's account and name, and — the reason this matters — an operator
# free-text ``Ref:`` field carrying whatever the sender typed. On a property
# purchase that is a street address; on a family transfer it can be anything.
#
# No slot name can protect a field whose contents are unconstrained, so this is
# the one line shape refused a grammar outright rather than parsed carefully. It
# stays local and whole. Two distinct markers are required, so an ordinary line
# that happens to print "Ref:" is not swept up with it.
#
# These are Fedwire/SWIFT **field tags**, not words. `Imad:` and `Omad:` are the
# input and output message accountability data identifiers, `Bnf/` the
# beneficiary tag, `A/C:` the account tag — they are the message format, the same
# category of thing as `PPD ID:`. An earlier version of this tuple also carried
# the English phrases "wire transfer" and "swift", which would have been a
# keyword list wearing a specification's clothes: they classify by language, so
# they fail on the first non-English statement. Removed. Coverage is slightly
# narrower and the rule is honest.
_WIRE_MARKERS = (r"\bvia:", r"\ba/c:", r"\bimad:", r"\bomad:", r"\btrn:",
                 r"\bbnf/", r"\bref:")
_WIRE = re.compile("|".join(_WIRE_MARKERS), re.I)
WIRE_RULE = "wire_message_dump"


# The NACHA batch header, rendered. An ACH line ends with the Standard Entry
# Class code and the Company Identification, in that order, always:
#
#     <Company Name (16)> <Company Entry Description (10)> <SEC (3)> ID: <id (10)>
#
# This is specification, not a bank convention — the same shape at every US bank
# — so it is parsed rather than induced. What it CANNOT give deterministically is
# the split between Company Name and Company Entry Description: the fields are
# fixed-width in the file and the bank collapsed the padding on its way to the
# display line, so the boundary is gone from any single line. `split_ach_heads`
# recovers it from the statement as a whole.
# The complete, closed set of NACHA Standard Entry Class codes. An enumeration
# from a published standard, not a guess about the world — the same category of
# constant as the asterisk indexes above, and unlike them it is US-scope, which
# is why nothing outside this rule may depend on an SEC code existing.
_SEC_CODES = ("PPD", "CCD", "CTX", "WEB", "TEL", "ARC", "BOC", "POP", "RCK", "IAT")
_ACH_TAIL = re.compile(
    r"\b(" + "|".join(_SEC_CODES) + r")\s+ID:\s*(\S+)\s*$", re.I)


def is_never_templatable(raw: str) -> bool:
    """True for a line no induced grammar may ever claim.

    Not a parsing judgement — a boundary one. A template that matched a wire
    would put an operator free-text field into a named slot, and every slot name
    in the vocabulary asserts something about its contents that a free-text
    field cannot honour. Refusing the shape is the only honest answer, and it is
    checked in one place so a future grammar cannot reintroduce the claim."""
    return len({m.group(0).lower() for m in _WIRE.finditer(raw or "")}) >= 2


@dataclass(frozen=True)
class Slot:
    """One claimed span, the rule that claimed it, and whether the rule PROVES
    it. A published layout proves its slot; adjacency only suggests one, and the
    difference has to survive into the record or the parse will be read as more
    certain than it is."""
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
        """At most ONE unclaimed run remains.

        Layer 0 deliberately cannot claim the merchant name — no published rule
        says where it ends — so demanding zero residue would fail on every
        descriptor. What it can demand is that the leftovers be *contiguous*:
        one run is a brand with its structure stripped away around it, while
        scattered fragments mean the rules fired in the wrong places and the
        parse should not be trusted. This is Layer 0's reconciliation identity;
        the stricter every-character version belongs to an induced profile,
        which does claim the name."""
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
    """Mark a span as claimed. Refuses to claim a span that overlaps another,
    so two rules can never both own the same characters."""
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
    else:
        low = text.lower()
        for p in _PROCESSORS:
            if low.startswith(p):
                if _claim(taken, 0, len(p)):
                    out.slots.append(Slot("aggregator", text[:len(p)].strip(),
                                          0, len(p), "processor_prefix"))
                break

    # The ACH tail, before anything else can claim its digits. The Company
    # Identification is a long number and the reference rules would otherwise
    # take it, losing the one field that identifies an originator across months.
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
    """`{word: set of normalized keys printing it}` — evidence, not a rule.

    **A rule built on this was removed on 2026-07-28, and the removal is the
    useful part of this docstring.** It classified a word as the bank's own
    template text when it appeared under enough distinct counterparties, and
    stripped such words out of brand candidates. On a real vault of 1,076
    movements it produced, in descending order of frequency:

        141 tx · 70 payment · 59 zelle · 58 plano · 45 to · 29 card · 29 id
        · 25 dallas · 23 frisco · 20 purchase · 20 mckinney · 16 you
        · 15 <a real merchant> · 13 ppd · 12 web · 8 atm · 7 <a real merchant>

    Three populations — the bank's sentence words, geography, and merchants —
    interleaved by frequency, so no threshold separates them. Cut high and the
    genuine ACH markers are missed; cut low and merchant names are destroyed.

    Worse, the metric is circular. It counts distinct *normalized keys*, and
    normalization fragments one merchant into many keys — a merchant with
    fifteen descriptor variants looks like fifteen counterparties agreeing. The
    rule needed merchant identity to count correctly and existed to help produce
    it.

    Identifying a bank's own sentence is Layer 1's job, and Layer 1 does it from
    evidence with a lossless check rather than from a frequency cut. This
    function survives only as a diagnostic for the streams report — it describes
    a vault, it decides nothing.
    """
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
    """The most the boundary may carry: brand words, and nothing else.

    The docs have said for weeks that what crosses to enrichment is "a normalized
    key and a **linted** example". What actually crossed was the raw bank
    descriptor — so store numbers, cities, order ids and posting dates travelled
    to a model provider, and the pending queue persisted them in plain JSON
    (repair-list C2).

    This is the lint. Every span a published rule can prove is removed first,
    then every remaining token carrying a digit, then anything too short to be a
    word. What is left is brand words. It is deliberately *lossy*: the example
    exists to help identify a brand, and a store number has never helped identify
    a brand.

    It cannot promise the result is impersonal — a peer payment's residue is a
    person's name, and only the slot it came from can settle that (an induced
    grammar's ``{counterparty}``, or ``is_shareable`` until then). What it does
    promise is that no number, date, reference or contact detail crosses, which
    is what C2 is about."""
    candidate = brand_candidate(parse_descriptor(descriptor or ""))
    words = [w for w in re.split(r"\s+", candidate)
             if w and not any(c.isdigit() for c in w)]
    words = [w.strip(".,:;*/-#") for w in words]
    return " ".join(w for w in words if len(w) > 1)[:64].strip()


def split_ach_heads(descriptors) -> dict:
    """Split each ACH head into Company Name and Company Entry Description,
    using the statement as a whole.

    A single line cannot give this. The two fields are fixed-width in the NACHA
    file — 16 characters then 10 — but the bank collapsed the padding on the way
    to the display line, so `Acmeco ACH Pmt` and `Bluewave Holdings Payroll`
    offer no boundary a per-line rule could find.

    The statement gives it, from the same property `skeletons()` uses: **the
    entry description recurs and the company name does not.** A bank prints
    `ACH Pmt`, `Payroll`, `Direct Dep`, `Assn Dues`, `Sale` across many
    originators; each originator's name appears on its own lines and nowhere
    else. So a trailing word shared with another originator is the description,
    and everything before it is the name.

    Parameter-free and needs no vocabulary of known descriptions — which matters,
    because a list of known entry descriptions is precisely the kind of table
    this codebase keeps deleting. It is also honest about its limits: an
    originator that appears once, with a description no other originator uses,
    cannot be split and is returned name-only.

    Returns ``{descriptor: (company_name, entry_description)}`` for ACH lines.
    """
    heads: dict[str, list[str]] = {}
    for d in {x for x in descriptors if x}:
        p = parse_descriptor(d)
        if p.ach and p.residue:
            heads[d] = p.residue.split()

    # How many DISTINCT originators end with each trailing word. A word ending
    # two originators' heads is the bank's, not a company's.
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
                continue                      # a head that is ALL description names nobody
            phrase = " ".join(w.lower() for w in words[-i:])
            if len(tail_owners.get(phrase, ())) > 1:
                best = " ".join(words[-i:])
                break
        name = " ".join(words[:len(words) - len(best.split())]) if best else " ".join(words)
        out[d] = (name.strip(), best.strip())
    return out


def brand_candidate(parse: DescriptorParse) -> str:
    """The part of a descriptor most likely to name the merchant.

    Normally what remains once every provable span is removed. But a residue of
    only digits or a stub too short to be a name is not a brand — a marketplace
    that prints an order id where the retailer belongs leaves nothing usable, and
    the aggregator is then the most specific true thing available.

    A candidate offered to identification, never an identity by itself: the
    string that names a brand and the string a bank happened to print are
    different things, and only a knowledge base can say so."""
    residue = parse.residue
    usable = any(len(tok) >= 3 and tok.isalpha() for tok in re.split(r"[^A-Za-z]+", residue))
    return residue if usable else parse.get("aggregator")
