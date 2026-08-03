"""The modality-neutral tool loop, with the composition gate that enforces
"every figure is a cited tool result" in code.

The runner takes a *planner* — any callable that, shown the question, the tool
schemas and the results so far, returns either the next tool call or the final
answer. A provider adapter doing native tool-calling is a planner; so is a
text-protocol adapter parsing a model's JSON block; so is a scripted function
in a test. The runner neither knows nor cares which — the contract is data in,
data out, and the T1 gate runs identically for all of them.

The gate: an answer's every figure must cite record ids the run actually saw,
and every number appearing in the answer's text must be traceable to a tool
result from this run. Dates are declared alongside the figures, as the ISO
dates the results carried, because prose writes a date in forms no ISO token
matches; a declared date licenses its own parts and nothing else. An answer
that fails is refused — not softened, not partially delivered.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .envelope import ToolResult, weakest
from .registry import Registry

# One tool call per planner step, bounded: a runaway planner meets a refusal,
# never an endless loop.
DEFAULT_MAX_CALLS = 8

# An ISO date travels as ONE token. Split into fragments, a window filter's
# year would taint every dated row that call returns, and a date-shaped
# invention could shed its hyphens into free-standing citable digits.
_NUMBER = re.compile(r"\d{4}-\d{2}-\d{2}|\d[\d,]*(?:\.\d+)?")

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _date_parts(iso: str) -> set:
    """The tokens a person writing this date out loud can produce — the whole
    date, its year, and its month and day with and without a leading zero. A
    declared date licenses exactly these and nothing else."""
    year, month, day = iso.split("-")
    return {iso, year, month, day, month.lstrip("0"), day.lstrip("0")}


@dataclass
class RunResult:
    """How a run ended: an answer that passed the gate, or a refusal."""
    answered: bool
    text: str = ""
    figures: list = field(default_factory=list)
    grade: str = ""
    refusal: str = ""
    transcript: list = field(default_factory=list)   # ToolResult dicts, in order
    calls: int = 0

    def to_dict(self) -> dict:
        return {"answered": self.answered, "text": self.text,
                "figures": list(self.figures), "grade": self.grade,
                "refusal": self.refusal, "transcript": list(self.transcript),
                "calls": self.calls}


def _strings_in(value) -> set:
    """Every string anywhere in a nested payload, plus the string form of
    every number — the pool a cited figure must be drawn from."""
    out: set = set()
    if isinstance(value, str):
        out.add(value)
    elif isinstance(value, bool):
        pass
    elif isinstance(value, (int, float)):
        out.add(str(value))
    elif isinstance(value, dict):
        for k, v in value.items():
            out |= _strings_in(k)
            out |= _strings_in(v)
    elif isinstance(value, (list, tuple)):
        for v in value:
            out |= _strings_in(v)
    return out


def _tokens_in(strings: set) -> set:
    """Every numeric token appearing in the pool, commas stripped — matched
    whole, never as a substring, so a fabricated '6' cannot ride on a
    '600.00' some tool returned."""
    out: set = set()
    for s in strings:
        for token in _NUMBER.findall(s):
            out.add(token.replace(",", ""))
    return out


def _refused(reason: str, text: str, transcript: list, calls: int) -> RunResult:
    return RunResult(answered=False, refusal=reason, text=text,
                     transcript=transcript, calls=calls)


def run(question: str, planner, registry: Registry,
        max_calls: int = DEFAULT_MAX_CALLS) -> RunResult:
    """Drive the planner until it answers or runs out of budget, gating the
    answer on citation. Deterministic given a deterministic planner."""
    transcript: list[ToolResult] = []
    seen_ids: set = set()
    seen_strings: set = set()
    grounded_tokens: set = set()
    while True:
        step = planner({"question": question,
                        "tools": registry.schemas(),
                        "descriptions_version": registry.descriptions_version,
                        "results": [t.to_dict() for t in transcript]})
        if not isinstance(step, dict):
            return _refused("bad_plan", "The planner returned something other "
                            "than a tool call or an answer.",
                            [t.to_dict() for t in transcript], len(transcript))
        if "refusal" in step:
            # A planner may refuse the whole run with its own machine tag — a
            # model that never produced a usable step, or one that could not
            # be reached at all. Refusal, never an exception, is the worst case.
            return _refused(str(step["refusal"]), str(step.get("text", "")),
                            [t.to_dict() for t in transcript], len(transcript))
        if "tool" in step:
            if len(transcript) >= max_calls:
                return _refused(
                    "call_budget_exhausted",
                    f"No answer after {max_calls} tool calls; refusing rather "
                    "than answering without grounds.",
                    [t.to_dict() for t in transcript], len(transcript))
            args = step.get("args")
            result = registry.call(step["tool"], args)
            transcript.append(result)
            # Only a result that asserts something can ground a figure, and
            # even then, never by echoing the caller's own words back. A
            # refusal restating an unknown account id, an ok result restating
            # a caller-chosen date, and a computation citing caller-supplied
            # record ids are all echoes: numbers and ids that entered through
            # the call's arguments ground nothing until some result carries
            # them independently of the arguments that planted them.
            if result.ok:
                arg_tokens = _tokens_in(_strings_in(args))
                if not registry.caller_supplies_record_ids(step["tool"]):
                    seen_ids |= set(result.record_ids)
                result_strings = _strings_in(result.to_dict())
                seen_strings |= result_strings
                grounded_tokens |= (_tokens_in(result_strings) - arg_tokens)
            continue
        if "answer" not in step:
            return _refused("bad_plan", "The planner's step names neither a "
                            "tool nor an answer.",
                            [t.to_dict() for t in transcript], len(transcript))
        return _gate(step, transcript, seen_ids, seen_strings,
                     grounded_tokens)


def _gate(step: dict, transcript: list, seen_ids: set, seen_strings: set,
          grounded_tokens: set) -> RunResult:
    """The composition check. Every declared figure must carry record ids the
    run saw and a value some result asserted; every number in the answer text
    must be covered by a figure or grounded by a result — where grounded
    excludes anything that entered the run through the planner's own
    arguments."""
    text = str(step.get("answer", ""))
    figures = step.get("figures", []) or []
    dicts = [t.to_dict() for t in transcript]
    grades = []
    for figure in figures:
        if not isinstance(figure, dict) or "value" not in figure:
            return _refused("uncited_figure",
                            "A figure was declared without a value.",
                            dicts, len(transcript))
        ids = figure.get("record_ids") or []
        if not ids:
            return _refused(
                "uncited_figure",
                f"The figure {figure['value']!r} cites no record — every "
                "figure must stand on one.", dicts, len(transcript))
        missing = [i for i in ids if i not in seen_ids]
        if missing:
            return _refused(
                "uncited_figure",
                f"The figure {figure['value']!r} cites records this run never "
                "read: " + ", ".join(map(str, missing)), dicts, len(transcript))
        if str(figure["value"]) not in seen_strings:
            return _refused(
                "unfounded_figure",
                f"The figure {figure['value']!r} appears in no tool result "
                "from this run.", dicts, len(transcript))
        tainted = [t for t in _NUMBER.findall(str(figure["value"]))
                   if t.replace(",", "") not in grounded_tokens]
        if tainted:
            return _refused(
                "unfounded_figure",
                f"The figure {figure['value']!r} rests on numbers this run's "
                "results only echo from the planner's own arguments.",
                dicts, len(transcript))
        if figure.get("grade"):
            grades.append(figure["grade"])
    # A date is a claim about when, not about how much, and prose writes it in
    # forms no ISO token matches. So it is declared like a figure and checked
    # like one: the ISO date must be something this run's results asserted, and
    # only then may the answer say its parts.
    sayable: set = set()
    for entry in step.get("dates", []) or []:
        iso = str(entry.get("iso", "")) if isinstance(entry, dict) else ""
        if not _ISO_DATE.match(iso):
            return _refused(
                "unfounded_date",
                f"A declared date {iso!r} is not a date this run could have "
                "read.", dicts, len(transcript))
        if iso not in grounded_tokens:
            return _refused(
                "unfounded_date",
                f"The date {iso!r} appears in no tool result from this run.",
                dicts, len(transcript))
        sayable |= _date_parts(iso)

    seen_dates = sorted(d for d in grounded_tokens if _ISO_DATE.match(d))
    covered = {str(f["value"]).replace(",", "") for f in figures}
    for token in _NUMBER.findall(text):
        plain = token.replace(",", "")
        if plain in covered or plain in grounded_tokens or plain in sayable:
            continue
        # Saying which failure this is matters: a date left undeclared and a
        # number invented outright are the same refusal to the gate and very
        # different news to the person reading it.
        owner = next((d for d in seen_dates if plain in _date_parts(d)), "")
        if owner:
            return _refused(
                "undeclared_date",
                f"The answer writes '{token}', part of the date {owner!r} this "
                "run read — a date must be declared before it can be said.",
                dicts, len(transcript))
        return _refused(
            "unfounded_figure",
            f"The answer contains '{token}', which no tool result from this "
            "run contains and no declared figure covers.",
            dicts, len(transcript))
    return RunResult(answered=True, text=text, figures=list(figures),
                     grade=weakest(grades), transcript=dicts,
                     calls=len(transcript))
