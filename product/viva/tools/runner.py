"""The modality-neutral tool loop, with the composition gate that enforces
"every number the answer says is a number some tool asserted" in code.

The runner takes a *planner* — any callable that, shown the question, the tool
schemas and the results so far, returns either the next tool call or the final
answer. A provider adapter doing native tool-calling is a planner; so is a
text-protocol adapter parsing a model's JSON block; so is a scripted function
in a test. The runner neither knows nor cares which — the contract is data in,
data out, and the gate runs identically for all of them.

The gate rests on one rule: a number the model may say is either a figure some
tool emitted this run, a date declared from what the run is attested for, or a
value the person themselves supplied in this turn's question. There is no
fourth kind. Because tools emit figures with ids and an answer cites ids, an
invented number has nothing to cite, and a value planted in a call's own
arguments is not evidence when a result echoes it back.

One thing besides figures stays sayable: a number a tool wrote into its own
prose. A tool's `text`, `coverage` and `caveats` are sentences the tool chose;
its `data` is raw material. Sentences are sayable; payloads are not.

Dates are declared alongside the figures. A declared date licenses its own
parts and nothing else, and must fall inside a period the run is attested for or
match a date some result carries. An answer that fails any of this is refused
whole, and the refusal is spoken in Viva's voice when the planner can compose
one, with the same number check run over what it composed.
"""

from __future__ import annotations

import datetime
import re
from dataclasses import dataclass, field, replace

from .envelope import MONEY_KINDS, ToolResult, weakest
from .registry import Registry

# One tool call per planner step. Past this the run refuses rather than
# looping.
DEFAULT_MAX_CALLS = 8

# An ISO date matches as one token, so its year, month and day are never
# free-standing numbers here.
_NUMBER = re.compile(r"\d{4}-\d{2}-\d{2}|\d[\d,]*(?:\.\d+)?")

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# A figure id in ordinary prose is a name, not a quantity. Only an id this run
# stamped matches; the digits of anything else are read as a number.
_ID_MENTION = re.compile(r"(?<![A-Za-z0-9])(f\d+)(?![A-Za-z0-9])")


def _without_ids(text: str, ids) -> str:
    """The text with mentions of this run's figure ids blanked out, character
    for character so nothing either side of one moves or joins."""
    if not ids:
        return text
    return _ID_MENTION.sub(
        lambda m: " " * len(m.group(0)) if m.group(1) in ids else m.group(0),
        text)


def _is_real_date(iso: str) -> bool:
    """Whether a `YYYY-MM-DD` string names a day that exists."""
    try:
        datetime.date.fromisoformat(iso)
        return True
    except ValueError:
        return False


def _date_parts(iso: str) -> set:
    """The tokens a person writing this date out loud can produce — the whole
    date, its year, and its month and day with and without a leading zero. A
    declared date licenses exactly these and nothing else. Nothing is removed
    from the answer's text to make room for them: text that is deleted before
    the numbers are counted takes whatever else it overlaps with it."""
    year, month, day = iso.split("-")
    return {iso, year, month, day, month.lstrip("0"), day.lstrip("0")}


def _tokens(text, ids=()) -> set:
    """Every numeric token in a string, commas stripped — matched whole, never
    as a substring, so a fabricated '6' cannot ride on a '600.00'. Mentions of
    this run's own figure ids are names, and are not read as quantities."""
    return {t.replace(",", "")
            for t in _NUMBER.findall(_without_ids(str(text or ""), ids))}


@dataclass
class RunResult:
    """How a run ended: an answer that passed the gate, or a refusal."""
    answered: bool
    text: str = ""
    figures: list = field(default_factory=list)
    grade: str = ""
    refusal: str = ""
    # What went wrong, in the machine's own words, naming the token or the id.
    # It reaches the log, the tests and the model composing the refusal, never
    # the person.
    detail: str = ""
    transcript: list = field(default_factory=list)   # ToolResult dicts, in order
    calls: int = 0

    def to_dict(self) -> dict:
        return {"answered": self.answered, "text": self.text,
                "figures": list(self.figures), "grade": self.grade,
                "refusal": self.refusal, "detail": self.detail,
                "transcript": list(self.transcript), "calls": self.calls}


@dataclass
class _Ground:
    """Everything this run established, and therefore everything it may say.

    The figure book is the run's own id space: ids are stamped in emission
    order across every tool, so two tools can never collide and an id from
    another turn means nothing here."""

    question: set = field(default_factory=set)    # numeric tokens the person wrote
    book: dict = field(default_factory=dict)      # {figure id: figure}
    periods: list = field(default_factory=list)   # (from, to) a read is attested for
    dates: set = field(default_factory=set)       # ISO dates some result carries
    prose: set = field(default_factory=set)       # numbers tools wrote into sentences

    def stamp(self, result: ToolResult) -> None:
        """Absorb one ok result: give its figures ids, and note what it
        attests, what it dates and what it said in words."""
        for span in result.covers or []:
            if span.get("from") and span.get("to"):
                self.periods.append((span["from"], span["to"]))
        if _ISO_DATE.match(result.dated or ""):
            self.dates.add(result.dated)
        for fig in result.figures:
            fig["id"] = f"f{len(self.book) + 1}"
            self.book[fig["id"]] = fig
            if _ISO_DATE.match(str(fig.get("dated") or "")):
                self.dates.add(str(fig["dated"]))
        for sentence in [result.text, result.coverage, *(result.caveats or [])]:
            self.prose |= {t for t in _tokens(sentence) if not _ISO_DATE.match(t)}


# What the person hears when nothing better can be composed: one sentence,
# whatever the machine tag.
_PLAIN_REFUSAL = ("I could not stand this answer on what I hold, so I would "
                  "rather say nothing than say something I cannot show you.")


def _refused(reason: str, detail: str, transcript: list, calls: int) -> RunResult:
    return RunResult(answered=False, refusal=reason, text=_PLAIN_REFUSAL,
                     detail=detail, transcript=transcript, calls=calls)


def run(question: str, planner, registry: Registry,
        max_calls: int = DEFAULT_MAX_CALLS) -> RunResult:
    """Drive the planner until it answers or runs out of budget, gating the
    answer on citation. Deterministic given a deterministic planner."""
    ground = _Ground(question=_tokens(question))
    transcript: list[ToolResult] = []
    # Exhaustion is not fatal: on the last pass the planner is shown only the
    # terminator, so a run already holding a grounded figure can deliver it.
    result = None
    while result is None:
        final_call = len(transcript) >= max_calls
        step = planner({"question": question,
                        "tools": registry.schemas(),
                        "descriptions_version": registry.descriptions_version,
                        "results": [t.to_dict() for t in transcript],
                        "calls_remaining": max(0, max_calls - len(transcript)),
                        "final_call": final_call})
        if not isinstance(step, dict):
            result = _refused("bad_plan", "The planner returned something other "
                              "than a tool call or an answer.",
                              [t.to_dict() for t in transcript], len(transcript))
        elif "refusal" in step:
            # A planner may refuse the whole run with its own machine tag — a
            # model that never produced a usable step, or one that could not be
            # reached at all.
            result = _refused(str(step["refusal"]), str(step.get("text", "")),
                              [t.to_dict() for t in transcript], len(transcript))
        elif "tool" in step:
            if final_call:
                # The planner was shown only the terminator and asked for a
                # read anyway; there is nothing left to spend on it.
                result = _refused(
                    "call_budget_exhausted",
                    f"No answer after {max_calls} tool calls; refusing rather "
                    "than answering without grounds.",
                    [t.to_dict() for t in transcript], len(transcript))
                continue
            called = registry.call(step["tool"], step.get("args"),
                                   figures=ground.book, question=question)
            transcript.append(called)
            if called.ok:
                ground.stamp(called)
        elif "answer" not in step:
            result = _refused("bad_plan", "The planner's step names neither a "
                              "tool nor an answer.",
                              [t.to_dict() for t in transcript], len(transcript))
        else:
            result = _gate(step, transcript, ground)
    if result.answered:
        return result
    return _voice(result, planner, ground, question,
                  [t.to_dict() for t in transcript])


def _check(step: dict, ground: _Ground) -> tuple[list, tuple | None]:
    """The number check, over anything the model composed — an answer or a
    refusal. Returns the cited figures and the problem, if any, as
    `(machine tag, the sentence explaining it)`."""
    cited: list = []
    for entry in step.get("figures") or []:
        fid = str(entry.get("id", "")) if isinstance(entry, dict) else ""
        if fid not in ground.book:
            return [], ("unknown_figure",
                        f"The answer cites a figure {fid!r} that no tool "
                        "emitted in this run.")
        cited.append(ground.book[fid])
    for fig in cited:
        # A money figure with no record behind it is refused. The other kinds
        # rest on ledger events or on the person's own premise, and are not
        # checked for records here.
        if fig["kind"] in MONEY_KINDS and not fig["record_ids"]:
            return [], ("uncited_figure",
                        f"The figure {fig['value']!r} cites no record — every "
                        "figure about your money must stand on one.")

    stipulated: set = set()
    for entry in step.get("stipulated") or []:
        value = str(entry.get("value", "")) if isinstance(entry, dict) else ""
        if not value or not _tokens(value) <= ground.question:
            return [], ("unfounded_stipulation",
                        f"The answer treats {value!r} as something you said, "
                        "but this turn's question does not contain it.")
        stipulated |= _tokens(value)

    sayable: set = set()
    for entry in step.get("dates") or []:
        iso = str(entry.get("iso", "")) if isinstance(entry, dict) else ""
        # Shape first, then reality. The library accepts forms this gate cannot
        # take apart — a compact YYYYMMDD, an ISO week date — and a value that
        # parses but has no parts would raise on the way to being licensed.
        if not _ISO_DATE.match(iso) or not _is_real_date(iso):
            return [], ("unfounded_date", f"A declared date {iso!r} is not a date.")
        if not (any(start <= iso <= end for start, end in ground.periods)
                or iso in ground.dates):
            return [], ("unfounded_date",
                        f"The date {iso!r} falls outside every period this run "
                        "is attested for and matches nothing this run's "
                        "results assert.")
        sayable |= _date_parts(iso)

    # A figure's value is tokenised exactly as the answer's text is, so a
    # movement of -40.00 licenses "40.00". A figure whose value is a date
    # licenses nothing here; dates answer to the date rule alone.
    covered: set = set()
    for fig in cited:
        covered |= {t for t in _tokens(fig["value"]) if not _ISO_DATE.match(t)}
    for token in _NUMBER.findall(
            _without_ids(str(step.get("answer", "")), ground.book)):
        plain = token.replace(",", "")
        if (plain in covered or plain in sayable or plain in stipulated
                or plain in ground.prose):
            continue
        # An undeclared date and an invented number refuse alike; the detail
        # says which one it was.
        owner = next((d for d in sorted(ground.dates)
                      if plain in _date_parts(d)), "")
        if owner:
            return [], ("undeclared_date",
                        f"The answer writes '{token}', part of the date "
                        f"{owner!r} this run read — a date must be declared "
                        "before it can be said.")
        return [], ("unfounded_figure",
                    f"The answer contains '{token}', which no figure in this "
                    "run carries and no result stated in words.")
    return cited, None


def _gate(step: dict, transcript: list, ground: _Ground) -> RunResult:
    """The composition check on a delivered answer. Its grade is the weakest
    among the money figures it cited; activity and hypothetical figures carry no
    grade and do not move it."""
    dicts = [t.to_dict() for t in transcript]
    cited, problem = _check(step, ground)
    if problem is not None:
        return _refused(problem[0], problem[1], dicts, len(transcript))
    return RunResult(
        answered=True, text=str(step.get("answer", "")),
        figures=[dict(f) for f in cited],
        grade=weakest(f["grade"] for f in cited
                      if f["kind"] in MONEY_KINDS),
        transcript=dicts, calls=len(transcript))


def _voice(result: RunResult, planner, ground: _Ground, question: str,
           results: list) -> RunResult:
    """Let the planner say the refusal the way Viva would, once.

    The composed sentence goes through the same number check as an answer, so a
    refusal that reaches for a figure it cannot cite is itself refused and the
    deterministic sentence stands. One attempt, no loop. The machine tag stays
    in the result for the logs and never appears in the prose, and whatever the
    sentence did cite travels with it."""
    compose = getattr(planner, "compose_refusal", None)
    if compose is None or result.refusal == "model_unreachable":
        return result
    step = compose({"tag": result.refusal, "explanation": result.detail,
                    "question": question, "results": results,
                    "established": [f["what"] for f in ground.book.values()
                                    if f.get("what")]})
    if not isinstance(step, dict):
        return result
    spoken = str(step.get("answer", "")).strip()
    if not spoken or result.refusal in spoken:
        return result
    cited, problem = _check(step, ground)
    if problem is not None:
        return result
    return replace(result, text=spoken, figures=[dict(f) for f in cited],
                   grade=weakest(f["grade"] for f in cited
                                 if f["kind"] in MONEY_KINDS))
