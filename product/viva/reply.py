"""One reply, read into the slots its question declared.

Every question in the queue declares **what structure an answer to it has** — a
list of typed slots. This module is the one inbound path, and it has two halves
that must stay in that order:

  1. **The model fills the declared slots.** What the person typed, the question
     they were asked and the slots that question declared go in; the same slots,
     filled, come back. The model turns language into structure. It never
     decides what a slot means, never chooses which slots exist, and nothing it
     returns reaches the ledger on its own word.
  2. **Deterministic code validates every filled value against its type**, and
     refuses what does not hold up. An amount goes through the locale-aware
     amount parser; a date through the date parser; an enumerated slot must land
     in the closed vocabulary its question named; a link must resolve to an
     account the vault already holds.

Model proposes structure, code disposes. The difference that makes is what
happens to real language: *"about 250k"* is not an amount any parser reads, but
the model returns ``{"value": "250000", "currency": "USD"}`` and the parser then
confirms that IS an amount in a known currency — or refuses it. A value is never
coerced into something nobody stated.

**What a reply that does not survive the check costs, and who pays it.** The
model is asked again first — once, with what it sent and what was wrong with it,
which is a confirmation step rather than a retry loop. Only when that fails is
the person asked, in Viva's voice, for what she needs. A person told to repeat
themselves because a machine mis-read them is being made to do the machine's
work.

With no model configured the filler degrades to the identity: each declared
scalar slot is offered the sentence as it was typed, and the same deterministic
checks decide. So the queue still answers plainly-written replies on a machine
with nothing configured, and refuses everything else rather than guessing.

This module holds no vault: the caller supplies the locale, the currency in
force and — for a link — a resolver that says whether the vault holds the target
and whether it is of the kind expected. That is what lets a terminal, the web
surface and any future surface reach the same mechanism.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

from vivacore import versions

from .ingest.prompt_library import PACKAGE, interpret_prompt
from .persona import moment
from .quantity import PER_HUNDRED
from .schemas import (ANSWER_CHOICE, ANSWER_DATE, ANSWER_INSTITUTION,
                      ANSWER_LABEL, ANSWER_LINK, ANSWER_MONEY, ANSWER_RATE,
                      ANSWER_TYPES, ANSWER_YES_NO, MAX_FREE_FORM)

log = logging.getLogger("viva.reply")

# What a slot may be. The vocabulary is the schema pack's — what an account
# needs known — because whatever the asking side needs, the answering side
# needs. Nothing is added here: a question whose answer is several things
# declares several slots rather than a type of its own.
SLOT_TYPES = ANSWER_TYPES

# The two words a yes/no lands in. They belong to the type, so a question
# declaring one never has to carry its own alternatives.
YES_NO = ("yes", "no")

# How much room a reply gets. Declared here rather than at each caller so the
# live path and the eval that measures it can never run under different
# ceilings: a reply cut off mid-reason yields no slots at all, so an instrument
# with less room than the thing it measures reports a failure the product does
# not have.
MAX_REPLY_TOKENS = 4096

# One retry, then the person. A reply that did not fill the declared slots goes
# back to the MODEL first — with what came back and what was wrong with it —
# because the model is what failed, and troubling the person for a machine's
# mistake is the wrong order. A second failure is Viva asking, never a third
# call: this is the answer path's own budget, in the other direction.
MAX_RETRIES = 1

# How much of an unusable reply travels back to the model with the complaint.
# Enough to recognise what it sent; not so much that a runaway reply is paid for
# twice.
SHOWN_BACK = 800

# The types kept as the person wrote them: their own word for something, and the
# public name of a company.
FREE_FORM = (ANSWER_LABEL, ANSWER_INSTITUTION)

# What a link resolver may say about a target.
UNKNOWN_ACCOUNT = "unknown_account"
WRONG_KIND = "wrong_kind"
_LINK_REFUSALS = {UNKNOWN_ACCOUNT: "reply_unknown_account",
                  WRONG_KIND: "reply_wrong_kind"}

# An out-of-band marker for "the model ran past its token limit". Not an
# exception: the partial text still travels, for logging and diagnosis.
TRUNCATED_MARK = "\x00truncated\x00"

# The instructions that turn a sentence into filled slots. The text lives in the
# versioned, append-only library and which version is in force is declared in
# `viva/versions.json`, so a recorded reading names the instructions that
# produced it.
INTERPRET_VERSION = versions.active(PACKAGE, "interpret")

# What is added to those instructions when a reply is handed back for a second
# attempt. A reading produced that way is stamped with BOTH ids joined, so the
# recorded version still resolves to the exact text that produced it.
INTERPRET_RETRY_VERSION = versions.active(PACKAGE, "interpret_retry")


@dataclass(frozen=True)
class Slot:
    """One thing a question needs back, and what kind of thing it is.

    ``choices`` is the closed vocabulary a reply must land in — the categories a
    merchant question knows, the alternatives a schema question enumerates. It
    is validation, not a set of buttons: the model is told what the vocabulary
    is and returns a member of it, and anything outside is refused.

    ``meanings`` gives a plain-language gloss for an alternative whose bare
    token would not say what it means. ``parts`` makes the slot hold SEVERAL of
    something — one payment that is genuinely several things at once is the case
    this exists for. ``asks`` is reviewed prose from a pack, never written
    here."""

    name: str
    type: str = ""                  # "" only for a slot that holds parts
    choices: tuple = ()
    meanings: tuple = ()            # (alternative, what it means) pairs
    parts: tuple = ()               # sub-slots; this slot holds several of them
    required: bool = False
    asks: str = ""                  # reviewed prose describing this slot

    def __post_init__(self):
        if self.parts:
            if self.type:
                raise ValueError(
                    f"slot {self.name!r} both holds parts and declares a type; "
                    "a slot is one or the other")
            return
        if self.type not in SLOT_TYPES:
            raise ValueError(
                f"slot {self.name!r} expects {self.type!r}, which nothing "
                f"validates; a slot declares one of {SLOT_TYPES}")
        if self.type == ANSWER_CHOICE and not self.choices:
            raise ValueError(
                f"slot {self.name!r} asks for one of nothing — an enumerated "
                "slot with no alternatives can only ever be refused")

    def to_dict(self) -> dict:
        """The declaration, as data. No action and no arguments: a surface reads
        what is wanted, and has nothing to send but words."""
        out = {"name": self.name, "type": self.type,
               "required": self.required}
        if self.choices:
            out["choices"] = list(self.choices)
        if self.parts:
            out["parts"] = [p.to_dict() for p in self.parts]
        return out


@dataclass
class Filled:
    """What the model returned for the declared slots — untrusted, unvalidated.

    ``failure`` names why there is nothing, when there is nothing: `unreachable`
    (the call never landed) is carried distinctly from `unparseable`, `too_long`
    and `empty`, which are the model answering with something unusable."""

    values: dict = field(default_factory=dict)
    failure: str = ""
    detail: str = ""
    raw: str = ""
    version: str = ""


@dataclass
class Reply:
    """What a person's words were read as, or why they were not.

    ``values`` maps slot name to the validated value — a string, or a list of
    dicts for a slot that holds parts. ``currencies`` carries the currency of an
    amount, which is the one type whose value is not a value on its own. A
    refusal carries the alternatives that would have been accepted, so asking
    again can name them.

    ``retryable`` says whether handing this back to the model could honestly
    produce a different answer. A misread structure could; a disagreement
    between what the person stated and what the vault holds could not, and
    asking again would only invite the model to drop the part that disagreed."""

    ok: bool
    values: dict = field(default_factory=dict)
    currencies: dict = field(default_factory=dict)
    why: str = ""
    message: str = ""
    choices: tuple = ()
    slot: str = ""
    version: str = ""
    detail: str = ""               # the machine reason, for the second attempt
    retryable: bool = True

    def value(self, name: str = "") -> str:
        """One validated value. With no name, the only one there is."""
        if not name:
            name = next(iter(self.values), "")
        got = self.values.get(name, "")
        return got if isinstance(got, str) else ""

    def currency(self, name: str = "") -> str:
        if not name:
            name = next(iter(self.values), "")
        return self.currencies.get(name, "")

    def to_dict(self) -> dict:
        if not self.ok:
            out = {"ok": False, "why": self.why, "message": self.message}
            if self.choices:
                out["choices"] = list(self.choices)
            if self.slot:
                out["slot"] = self.slot
            return out
        return {"ok": True, "values": self.values,
                "currencies": self.currencies}


# ------------------------------------------------------------- the model half


def interpret(said: str, slots, *, asked: str = "", context=(), extract_fn=None,
              version: str = INTERPRET_VERSION, problem: str = "",
              got: str = "") -> Filled:
    """The one model call: a sentence and the declared slots in, those slots
    filled, out.

    Never raises: a model that is unavailable or wrong degrades the surface,
    never the ledger. Nothing here is trusted — every value returned is checked
    by `read_reply` before it can go anywhere.

    With ``problem`` set this is the second attempt: what came back last time
    and what was wrong with it travel with the same instructions, so the model
    is asked to fix its own reply rather than the person being asked to repeat
    themselves. The version reported is both ids joined, because both texts
    produced the reading.

    With no ``extract_fn`` the filler is the identity: each scalar slot is
    offered the sentence verbatim, and the deterministic checks decide."""
    slots = tuple(slots)
    if extract_fn is None:
        return Filled(values={s.name: said for s in slots if not s.parts},
                      version=version)
    text, version = interpret_prompt(version)
    prompt = text.format(asked=asked or "(not recorded)", said=said,
                         context=_render_context(context),
                         slots=_render_slots(slots))
    if problem:
        again, retry_version = interpret_prompt(INTERPRET_RETRY_VERSION)
        prompt += "\n" + again.format(problem=problem,
                                      got=(got or "")[:SHOWN_BACK] or "(nothing)")
        version = f"{version}+{retry_version}"
    try:
        raw = extract_fn(prompt)
    except Exception as exc:                       # noqa: BLE001 - degrade, never raise
        # The call never landed: wrong model name, server down, bad base URL, a
        # rejected parameter. Not the model declining.
        log.warning("reply: could not reach the model (%s)", exc)
        return Filled(failure="unreachable", detail=str(exc), version=version)
    truncated = (raw or "").startswith(TRUNCATED_MARK)
    if truncated:
        raw = raw[len(TRUNCATED_MARK):]
    body = None
    for slot in slots:
        body = _first_json_object(raw, require_key=slot.name)
        if body is not None:
            break
    if body is None:
        if truncated:
            return Filled(failure="too_long", raw=raw, version=version,
                          detail=f"the model ran past its token limit "
                                 f"({len(raw)} chars back)")
        log.warning("reply: no readable JSON object in the reply (%d chars)",
                    len(raw or ""))
        return Filled(failure="unparseable", raw=raw or "", version=version,
                      detail="no complete JSON object in the reply")
    # At least one declared slot is present, or `body` would not have been
    # found. What it holds is still untrusted; `read_reply` decides.
    return Filled(values={s.name: body[s.name] for s in slots if s.name in body},
                  raw=raw or "", version=version)


def _render_context(context) -> str:
    """What is already known, as `name: value` lines. Field names, never prose:
    the instructions live in the prompt file."""
    lines = [f"- {name}: {value}" for name, value in (context or ()) if value]
    return "\n".join(lines) if lines else "- (nothing beyond the question)"


def _render_slots(slots, indent: str = "") -> str:
    """The declaration the model must fill, as data."""
    out = []
    for s in slots:
        if s.parts:
            out.append(f"{indent}- {s.name}: SEVERAL, each with these parts"
                       + (" (required)" if s.required else ""))
            out.append(_render_slots(s.parts, indent + "    "))
            continue
        line = f"{indent}- {s.name}: {s.type}"
        if s.choices:
            gloss = dict(s.meanings)
            line += " — one of: " + ", ".join(
                f"{c} ({gloss[c]})" if c in gloss else c for c in s.choices)
        if s.required:
            line += " (required)"
        if s.asks:
            line += f"\n{indent}    {s.asks}"
        out.append(line)
    return "\n".join(out)


def _first_json_object(text: str, require_key: str = "") -> dict | None:
    """The first complete, balanced JSON object in a reply — preferring one that
    carries ``require_key`` — or None.

    The whole reply need not be JSON: an object wrapped in a code fence,
    prefixed with reasoning or followed by a sentence is still found. Scanning
    for balance respects strings and escapes, so a reply cut off mid-object is
    rejected rather than half-parsed."""
    if not text:
        return None
    for start in range(len(text)):
        if text[start] != "{":
            continue
        depth, in_str, escaped = 0, False, False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        found = json.loads(text[start:i + 1])
                    except Exception:              # noqa: BLE001 - try the next '{'
                        break
                    if not isinstance(found, dict):
                        break
                    # Some providers and json_mode wrappers nest the answer:
                    # {"response": {"legs": [...]}}. The outer object carries no
                    # slots, so `require_key` descends to the one that does.
                    if require_key:
                        hit = _find_key(found, require_key)
                        if hit is not None:
                            return hit
                        break                      # keep scanning for a better one
                    return found
        # unbalanced from here — the reply was cut off
    return None


def _find_key(obj, key: str, depth: int = 0):
    """The nearest dict carrying ``key``, searching one or two levels down."""
    if not isinstance(obj, dict) or depth > 2:
        return None
    if key in obj:
        return obj
    for value in obj.values():
        hit = _find_key(value, key, depth + 1)
        if hit is not None:
            return hit
    return None


# ----------------------------------------------------------- the check behind


def read_reply(slots, filled: dict, *, currency: str = "", locale: str = "",
               resolve_link=None) -> Reply:
    """Validate what the model filled, slot by slot, against the declared types.

    Every branch refuses rather than guesses, and a refusal names what would
    have been accepted. This is the half nothing may bypass: it runs on whatever
    reached it, so a value the model invented and a value the person typed are
    held to exactly the same standard.

    ``currency`` is the currency in force — what the account this is about is
    held in. It is never displaced by a currency the reply carried: the two are
    compared, and a disagreement is a question rather than a conversion."""
    values, currencies = {}, {}
    for slot in tuple(slots):
        raw = filled.get(slot.name)
        if slot.parts:
            members = _read_parts(slot, raw, currency=currency, locale=locale,
                                  resolve_link=resolve_link)
            if members:
                values[slot.name] = members
            elif slot.required:
                return _refuse(slot, "unanswered", "reply_unanswered")
            continue
        text, given = _as_text(raw)
        if not text:
            if slot.required:
                return _refuse(slot, "unanswered", "reply_unanswered")
            continue
        got = _read_one(slot, text, currency, locale, resolve_link, stated=given)
        if not got.ok:
            return got
        values[slot.name] = got.value()
        if got.currency():
            currencies[slot.name] = got.currency()
    return Reply(True, values=values, currencies=currencies)


def _as_text(raw) -> tuple:
    """One filled value as text, plus the currency it came with.

    An amount is the one type whose value is not a value on its own, so the
    model returns it as a value and a currency together; every other type is a
    string. Anything else — a number, a list, an object — is not a filled scalar
    slot and reads as empty."""
    if isinstance(raw, dict):
        return (str(raw.get("value", "")).strip(),
                str(raw.get("currency", "")).strip())
    if isinstance(raw, str):
        return raw.strip(), ""
    return "", ""


def _read_parts(slot: Slot, raw, *, currency: str, locale: str, resolve_link):
    """Every member of a slot that holds several of something.

    A member whose required parts do not validate is dropped and logged, which
    is the closed-vocabulary discipline this path has always kept: one
    unreadable leg of a compound answer must not throw away the rest. A slot
    left with no members is unanswered, and a required one refuses."""
    members = []
    for member in raw if isinstance(raw, list) else []:
        if not isinstance(member, dict):
            log.warning("reply: dropping a member of %r that isn't an object",
                        slot.name)
            continue
        read = {}
        dropped = False
        for part in slot.parts:
            text, given = _as_text(member.get(part.name))
            got = (_read_one(part, text, currency, locale, resolve_link,
                             stated=given) if text else None)
            if got is not None and got.ok:
                read[part.name] = got.value()
                continue
            if part.required:
                log.warning("reply: dropping a member of %r — %s is %s",
                            slot.name, part.name,
                            got.why if got is not None else "missing")
                dropped = True
                break
            # An optional part nothing can read is a part that was not given.
            # Losing a leg's major because its share came back as prose would
            # throw away the answer over the detail.
            read[part.name] = ""
        if not dropped:
            members.append(read)
    return members


def _read_one(slot: Slot, text: str, currency: str, locale: str,
              resolve_link, stated: str = "") -> Reply:
    """One value, against one type. The deterministic half, in one place.

    ``currency`` is what the account is held in; ``stated`` is what the reply
    said the amount was in, which is only ever compared against it."""
    from vivacore.verify.normalize import parse_amount, parse_date

    if slot.type == ANSWER_MONEY:
        held, named = (currency or "").upper(), (stated or "").upper()
        if named and held and named != held:
            # An amount is a value AND a currency, and nothing here converts
            # between currencies — net worth is per-currency subtotals, never a
            # converted total. So a currency that disagrees with the account's
            # is a question for the person, never a figure quietly recorded in
            # the currency they did not say. Handing this back to the model
            # would invite it to drop the currency, which is the same silent
            # substitution wearing a second attempt.
            return _refuse(slot, "currency_conflict", "reply_currency_conflict",
                           retryable=False, stated=named, held=held,
                           reason=f"{named} against an account held in {held}")
        got = parse_amount(text, locale=locale or None,
                           currency=(named or held) or None)
        if not got.ok:
            return _refuse(slot, "unreadable_money", "reply_unreadable_money",
                           reason=got.reason)
        return Reply(True, values={slot.name: str(got.decimal())},
                     currencies={slot.name: got.currency or held or ""})

    if slot.type == ANSWER_DATE:
        got = parse_date(text, locale=locale or None)
        if not got.ok:
            return _refuse(slot, "unreadable_date", "reply_unreadable_date",
                           reason=got.reason)
        return Reply(True, values={slot.name: got.value})

    if slot.type == ANSWER_RATE:
        got = parse_amount(text.replace("%", " ").strip(), locale=locale or None)
        if not got.ok:
            return _refuse(slot, "unreadable_rate", "reply_unreadable_rate")
        # A person writes a proportion per hundred; `quantity.RATIO` is the
        # quotient. `render.rate` applies the same scale the other way.
        return Reply(True, values={slot.name: str(got.decimal() / PER_HUNDRED)})

    if slot.type in (ANSWER_YES_NO, ANSWER_CHOICE):
        allowed = YES_NO if slot.type == ANSWER_YES_NO else tuple(slot.choices)
        landed = next((option for option in allowed
                       if text.lower() == str(option).lower()), None)
        if landed is None:
            return _refuse(slot, "not_in_vocabulary", "reply_not_in_vocabulary",
                           choices=allowed, alternatives=", ".join(allowed))
        return Reply(True, values={slot.name: landed})

    if slot.type == ANSWER_LINK:
        # A link's vocabulary is the accounts the vault holds, so the vault is
        # what says whether one landed — `choices` only tells the model which
        # ones are worth naming. With nothing able to resolve it, a link cannot
        # be accepted: an unresolvable reference is what this type refuses.
        refusal = resolve_link(text) if resolve_link else UNKNOWN_ACCOUNT
        if refusal:
            return _refuse(slot, refusal, _LINK_REFUSALS[refusal])
        return Reply(True, values={slot.name: text})

    # The two free-form types: the person's own word, and a company's name.
    if len(text) > MAX_FREE_FORM:
        return _refuse(slot, "too_long", "reply_too_long")
    return Reply(True, values={slot.name: text})


def _refuse(slot: Slot, why: str, key: str, choices=(), retryable: bool = True,
            **fields) -> Reply:
    """One refusal: what Viva says to the person, and what the model would be
    told if this is worth a second attempt. ``reason`` serves both — the
    person's sentence places it, the model's complaint carries it."""
    return Reply(False, why=why, message=moment(key, **fields),
                 choices=tuple(choices), slot=slot.name,
                 detail=str(fields.get("reason", "")), retryable=retryable)


# ------------------------------------------------------------ both halves


# One honest sentence per way the model can fail to fill anything. A reader that
# is DOWN is a different thing from one that answered with something unusable:
# nothing the person can rephrase reaches a reader that is not there, so that
# one alone is never retried and never turns into a request to say it again.
_FAILURES = {"unreachable": "reply_unreachable",
             "unparseable": "reply_ask_again",
             "too_long": "reply_ask_again"}


def answer(said: str, slots, *, asked: str = "", context=(), extract_fn=None,
           currency: str = "", locale: str = "", resolve_link=None,
           version: str = INTERPRET_VERSION) -> Reply:
    """The whole inbound path: fill the declared slots, then check every value.

    The order is the mechanism. Anything that reverses it — a parser reading the
    raw sentence, a model value written without a check — is the thing this
    exists to prevent.

    A reply that does not fill the slots gets **one** second attempt, and it is
    the MODEL that is asked again, with what it sent and what was wrong with it.
    Only when that fails is the person reached, and then in Viva's voice, naming
    what she needs. The order matters: a person nagged for a machine's mistake
    has been made to do the machine's work."""
    slots = tuple(slots)
    problem, sent_back = "", ""
    read = Reply(False)
    for _attempt in range(MAX_RETRIES + 1):
        filled = interpret(said, slots, asked=asked, context=context,
                           extract_fn=extract_fn, version=version,
                           problem=problem, got=sent_back)
        read = _checked(filled, slots, said=said, currency=currency,
                        locale=locale, resolve_link=resolve_link)
        if read.ok or not read.retryable or extract_fn is None:
            # Nothing to gain from asking again: it landed, or asking again
            # cannot honestly change the answer, or there is no model to ask.
            return read
        problem = f"{read.slot or 'reply'}: {read.why}" + (
            f" ({read.detail})" if read.detail else "")
        sent_back = filled.raw
    return read


def _checked(filled: Filled, slots, *, said: str, currency: str, locale: str,
             resolve_link) -> Reply:
    """One attempt, validated — or the refusal it earned."""
    if filled.failure:
        log.warning("reply: %s (%s) said=%r raw=%r", filled.failure,
                    filled.detail, said, (filled.raw or "")[:400])
        return Reply(False, why=filled.failure, version=filled.version,
                     message=moment(_FAILURES[filled.failure]),
                     detail=filled.detail,
                     # A reader that answered can be asked again; one that was
                     # never reached cannot.
                     retryable=filled.failure != "unreachable")
    read = read_reply(slots, filled.values, currency=currency, locale=locale,
                      resolve_link=resolve_link)
    read.version = filled.version
    return read
