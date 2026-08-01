"""The schema pack — what may be asked about a kind of asset or liability.

A schema states **what exists and what it needs known**. It never says how to
read a document and never classifies raw text; it is shape, not a word list.
The pack is impersonal by construction — kinds, question keys, jurisdiction
tags — so it holds no vault data and is reviewable in one sitting.

Three fields carry the weight:

* ``essential`` ranks the question, terminates the interview when the last one
  is settled, and decides whether an asserted account is a disclosed gap.
* ``unlocks`` is the benefit sentence, so a question can always say why it is
  worth answering.
* ``opens`` expresses branching as data rather than as a loop: a yes on
  ``financed`` starts the loan's own interview, with no model involved.

A question's answer type comes from the closed vocabulary in ``ANSWER_TYPES``,
which has no member meaning "a string an issuer assigned": a parsed type holds
a figure, a ``choice`` holds one of the alternatives the question enumerates,
and the two free-form types hold the person's own word for something and the
public name of a company. ``lint`` rejects a pack outside that vocabulary.
"""

from __future__ import annotations

import json
import pathlib
from dataclasses import dataclass, field
from functools import lru_cache

_DIR = pathlib.Path(__file__).resolve().parent

ACTIVE_PACK = "schemas-v1"

# The closed answer vocabulary. A pack entry outside it does not load.
ANSWER_MONEY = "money"
ANSWER_DATE = "date"
ANSWER_RATE = "rate"
ANSWER_YES_NO = "yes_no"
ANSWER_CHOICE = "choice"
ANSWER_LABEL = "label"
ANSWER_INSTITUTION = "institution"
ANSWER_LINK = "link"
ANSWER_TYPES = (ANSWER_MONEY, ANSWER_DATE, ANSWER_RATE, ANSWER_YES_NO,
                ANSWER_CHOICE, ANSWER_LABEL, ANSWER_INSTITUTION, ANSWER_LINK)

# The types whose value is parsed rather than kept as the person wrote it.
PARSED_TYPES = (ANSWER_MONEY, ANSWER_DATE, ANSWER_RATE)

# A free-form answer is a phrase, not a document. Longer than this is a
# paste rather than an answer.
MAX_FREE_FORM = 120

# The account fields a question may declare itself already answered by. Closed,
# so a schema cannot reach into the ledger for anything else.
ACCOUNT_FIELDS = ("institution", "name", "currency")

# What the LEDGER calls an account. A schema may claim one of these, and a kind
# no pack entry claims uniquely stays unresolved rather than guessed.
LEDGER_KINDS = ("depository", "liability", "investment", "asset")


class SchemaPackError(ValueError):
    """A pack that cannot be trusted to ask a safe question."""


@dataclass(frozen=True)
class SchemaQuestion:
    """One thing a kind needs known, and what answering it buys."""

    key: str
    essential: bool
    answer: str
    asks: str = ""                 # the plain question, reviewed as pack data
    unlocks: str = ""
    choices: tuple = ()
    opens: str = ""                # the kind a yes starts an interview for
    links_to: str = ""             # the kind this answer points at
    corroborated_by: tuple = ()    # documents that would attest it, this juris.
    required_when: dict = field(default_factory=dict)
    names_the_account: bool = False
    personal: bool = False         # never enriched, never shared
    known_from: str = ""           # an account field that already answers it
    # Document type -> the answer that document already gives. A classified
    # statement has said what kind of account it is; asking is not listening.
    answered_by_document: dict = field(default_factory=dict)
    # Whether net worth can carry the thing once this is answered. The pack
    # says so; the curve does not guess it from an answer type.
    gates_net_worth: bool = False
    # Whether this answer is the DATE the carried figure belongs to, so a flat
    # bought years ago does not appear as a step on the day it was mentioned.
    dates_net_worth: bool = False

    def required(self, answered: dict) -> bool:
        """Whether this question is essential *given what is answered so far*.

        A conditional essential — a term deposit's principal, maturity and rate
        — is not owed until the answer it depends on has arrived, so an
        interview is never gated on a question that does not apply."""
        if not self.essential:
            return False
        cond = self.required_when or {}
        if not cond:
            return True
        got = answered.get(cond.get("key", ""))
        if got is None:
            return False
        # An answer is a record of what was said and what it parsed to; the
        # condition reads the parsed value.
        if isinstance(got, dict):
            got = got.get("value", "")
        allowed = [str(c).strip().lower() for c in cond.get("is_one_of", [])]
        return str(got).strip().lower() in allowed


@dataclass(frozen=True)
class Schema:
    """One kind, resolved for one jurisdiction."""

    kind: str
    version: int
    account_shape: str
    reviewed: bool
    label: str = ""                # the kind in plain words
    questions: tuple = ()

    def question(self, key: str) -> SchemaQuestion | None:
        return next((q for q in self.questions if q.key == key), None)

    @property
    def essentials(self) -> tuple:
        return tuple(q for q in self.questions if q.essential)

    def outstanding(self, answered: dict, declined: set = frozenset()) -> tuple:
        """The essentials still owed, in pack order — the interview's spine.

        Pack order is the deterministic selector: a schema is written with the
        question that unlocks the most first."""
        return tuple(q for q in self.questions
                     if q.required(answered)
                     and q.key not in answered and q.key not in declined)

    def naming_question(self) -> SchemaQuestion | None:
        """The question whose answer becomes the account's name, if any."""
        return next((q for q in self.questions if q.names_the_account), None)


@lru_cache(maxsize=4)
def load(version: str = ACTIVE_PACK) -> dict:
    """The pack, loaded and linted once. A pack that fails the lint raises —
    a question nobody could review is worse than no question."""
    data = json.loads((_DIR / f"{version}.json").read_text())
    lint(data)
    return data


def _norm(text) -> str:
    return str(text or "").strip().lower()


def lint(pack: dict) -> None:
    """Raise ``SchemaPackError`` on a pack that could ask something it should
    not.

    Structural checks only: the closed answer vocabulary, a choice that
    enumerates its alternatives, a question that says what it asks and what it
    unlocks, ``opens``/``links_to`` naming kinds the pack holds, ``known_from``
    within ``ACCOUNT_FIELDS``, ``account_kinds`` within ``LEDGER_KINDS``, and
    document types that resolve to their own canonical name in the pipeline's
    registry. Whether a key is a good question is a review judgement."""
    kinds = {k.get("kind", "") for k in pack.get("kinds", [])}
    for entry in pack.get("kinds", []):
        kind = entry.get("kind", "")
        if not kind:
            raise SchemaPackError("a schema entry with no kind")
        if not entry.get("jurisdictions"):
            raise SchemaPackError(f"{kind}: a schema must be jurisdiction-tagged")
        if not entry.get("account_shape"):
            raise SchemaPackError(f"{kind}: a schema must say what account it shapes")
        from ..ingest.registry import profile_for
        for named in (list(entry.get("document_types", []))
                      + [d for q in entry.get("questions", [])
                         for d in (q.get("answered_by_document") or {})]):
            # Canonical names only: a document resolves to its profile's
            # canonical type, so an alias here would match nothing.
            profile = profile_for(named)
            if profile is None:
                raise SchemaPackError(
                    f"{kind}: document type {named!r} is not one the pipeline "
                    "classifies")
            if profile.doc_type != named:
                raise SchemaPackError(
                    f"{kind}: {named!r} is an alias; name the canonical type "
                    f"{profile.doc_type!r}, which is what a document resolves to")
        for named in entry.get("account_kinds", []):
            if named not in LEDGER_KINDS:
                raise SchemaPackError(
                    f"{kind}: account kind {named!r} is not one the ledger "
                    f"uses {LEDGER_KINDS}")
        seen: set = set()
        for q in entry.get("questions", []):
            key = q.get("key", "")
            if not key:
                raise SchemaPackError(f"{kind}: a question with no key")
            if key in seen:
                raise SchemaPackError(f"{kind}: asks {key!r} twice")
            seen.add(key)
            answer = q.get("answer", "")
            if answer not in ANSWER_TYPES:
                raise SchemaPackError(
                    f"{kind}.{key}: answer type {answer!r} is outside the "
                    f"vocabulary {ANSWER_TYPES}")
            if answer == ANSWER_CHOICE and not q.get("choices"):
                raise SchemaPackError(
                    f"{kind}.{key}: a choice must enumerate its alternatives, "
                    "or it is a free-form answer wearing a closed one's name")
            if not q.get("unlocks"):
                raise SchemaPackError(
                    f"{kind}.{key}: a question must say what answering it "
                    "unlocks, or it cannot explain itself")
            if not q.get("asks"):
                raise SchemaPackError(
                    f"{kind}.{key}: a question must carry the words it asks; "
                    "a key is not a question")
            opens = q.get("opens", "")
            if opens and opens not in kinds:
                raise SchemaPackError(f"{kind}.{key}: opens unknown kind {opens!r}")
            links = q.get("links_to", "")
            if links and links not in kinds:
                raise SchemaPackError(
                    f"{kind}.{key}: links to unknown kind {links!r} — a link "
                    "whose target the pack does not hold can never be answered")
            known = q.get("known_from", "")
            if known and known not in ACCOUNT_FIELDS:
                raise SchemaPackError(
                    f"{kind}.{key}: known_from {known!r} is not one of the "
                    f"account fields a schema may read {ACCOUNT_FIELDS}")
            cond = q.get("required_when") or {}
            if cond and cond.get("key") not in seen | {q.get("key")}:
                raise SchemaPackError(
                    f"{kind}.{key}: depends on {cond.get('key')!r}, which is "
                    "not asked before it")


def _resolve(value, jurisdiction: str):
    """A field that may be one value or one per jurisdiction."""
    if isinstance(value, dict):
        return value.get(jurisdiction, ())
    return value or ()


def schema_for(kind: str, jurisdiction: str = "",
               version: str = ACTIVE_PACK) -> Schema | None:
    """One kind, resolved for one jurisdiction, or None when the pack has no
    schema for it — which is the honest answer that raises no question."""
    juris = _norm(jurisdiction)
    for entry in load(version)["kinds"]:
        if _norm(entry.get("kind")) != _norm(kind):
            continue
        if juris and juris not in [_norm(j) for j in entry.get("jurisdictions", [])]:
            return None
        questions = []
        for q in entry.get("questions", []):
            only = [_norm(j) for j in (q.get("jurisdictions") or [])]
            if only and juris and juris not in only:
                continue
            # A choice whose alternatives are named per jurisdiction cannot be
            # asked where we do not know which one applies: an empty picker is
            # a question with no answer, and every reply to it would be refused.
            if (q["answer"] == ANSWER_CHOICE
                    and not tuple(_resolve(q.get("choices"), juris))):
                continue
            questions.append(SchemaQuestion(
                key=q["key"], essential=bool(q.get("essential")),
                answer=q["answer"], asks=q.get("asks", ""),
                unlocks=q.get("unlocks", ""),
                choices=tuple(_resolve(q.get("choices"), juris)),
                opens=q.get("opens", ""), links_to=q.get("links_to", ""),
                corroborated_by=tuple(_resolve(q.get("corroborated_by"), juris)),
                required_when=dict(q.get("required_when") or {}),
                names_the_account=bool(q.get("names_the_account")),
                personal=bool(q.get("personal")),
                known_from=q.get("known_from", ""),
                answered_by_document=dict(q.get("answered_by_document") or {}),
                gates_net_worth=bool(q.get("gates_net_worth")),
                dates_net_worth=bool(q.get("dates_net_worth"))))
        return Schema(kind=entry["kind"], version=int(entry.get("version", 1)),
                      account_shape=entry["account_shape"],
                      reviewed=bool(entry.get("reviewed")),
                      label=entry.get("label", ""),
                      questions=tuple(questions))
    return None


def known_kinds(jurisdiction: str = "", version: str = ACTIVE_PACK) -> list[str]:
    """Every kind the pack can ask about here, sorted."""
    juris = _norm(jurisdiction)
    out = []
    for entry in load(version)["kinds"]:
        tags = [_norm(j) for j in entry.get("jurisdictions", [])]
        if not juris or juris in tags:
            out.append(entry["kind"])
    return sorted(out)


def shape_of(kind: str, jurisdiction: str = "",
             version: str = ACTIVE_PACK) -> str:
    """The account root a kind's accounts live under, or ''."""
    schema = schema_for(kind, jurisdiction, version)
    return schema.account_shape if schema else ""


def kind_of_account(account: str, jurisdiction: str = "",
                    ledger_kind: str = "", doc_types=(),
                    version: str = ACTIVE_PACK) -> str:
    """Which kind of thing an account is, or '' when nothing says.

    Three sources of evidence, strongest first, because an account path is only
    one of the ways this product names an account and it is the weakest:

    1. **The path's shape.** Only accounts this interview created carry one, and
       for those it is exact. Longest match wins, so a specific root is never
       shadowed by a shorter one that prefixes it.
    2. **The documents an issuer produced for it.** A card statement means a
       card. This is the strongest evidence there is, and it is why the
       ingestion pipeline's own doc-type registry — not a second vocabulary —
       is what a schema names.
    3. **The ledger's account kind**, and only when exactly one kind in the pack
       claims it. A loan and a card are both liabilities, so that kind alone
       decides nothing, and an ambiguous answer is no answer: the interview
       raises nothing and records the gap rather than asking a question built
       on a guess.
    """
    entries = [e for e in load(version)["kinds"]
               if not jurisdiction
               or _norm(jurisdiction) in [_norm(j) for j in e.get("jurisdictions", [])]]

    best, best_len = "", 0
    for entry in entries:
        shape = entry.get("account_shape", "")
        if shape and account.startswith(shape + ":") and len(shape) > best_len:
            best, best_len = entry["kind"], len(shape)
    if best:
        return best

    seen = {str(d) for d in (doc_types or ())}
    by_document = [e["kind"] for e in entries
                   if seen & {str(d) for d in e.get("document_types", [])}]
    if len(set(by_document)) == 1:
        return by_document[0]

    by_kind = [e["kind"] for e in entries
               if ledger_kind and ledger_kind in e.get("account_kinds", [])]
    return by_kind[0] if len(set(by_kind)) == 1 else ""
