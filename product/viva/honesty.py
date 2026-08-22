"""The honesty harness, over a vault — and the refusal rate, built once.

The harness that existed graded a single model call against a frozen synthetic
key. That measures a model. It does not measure this product answering about a
person's own money, and citing it as though it did overstates the position by
exactly the width of SPINE-7's own exception.

**What a vault can be asked, and what it cannot.** A key is what says an answer
was wrong. A live vault has no key: nothing in it records that a figure a person
was told was untrue, so the confidently-wrong rate cannot be computed here and
this module says so in the read rather than reporting a zero. What a vault *can*
answer is a set of structural questions with the same shape — how often an
answer was refused, how often a figure was stated with nothing on record behind
it, and how often a graded figure went out without the sentence saying how well
it is stood behind. Each of those is a way of being confidently unsupported, and
each is checkable without a key.

**A rate is one function.** The refusal rate is computed here and imported by
everything that reports one, because two implementations of "how often did it
decline" would disagree the first time somebody decided whether a broken call
counts.

**A rate over nothing is not zero.** Every rate here is `None` when its
denominator is empty. A harness that reported a clean bill over a vault nobody
had asked anything is a check reporting a result it could not have withheld.

A pure fold over an event stream. It opens nothing, calls nothing, and knows
nothing about how the payload travels.
"""

from __future__ import annotations

import json
from typing import Any, Iterable

# The event a conversation turn is recorded as, and the pass it is recorded
# under. A model call from any other pass is a document being read, which is a
# different question with a different key.
READ_RECORDED = "ReadRecorded"
SPEAK = "speak"


def rate(part: int, whole: int) -> float | None:
    """One rate, or nothing.

    `None` where the denominator is empty. An unknown rate is not a zero rate,
    and a harness that reported zero over nothing would be giving a clean bill
    it had no way to withhold.

    This is the one definition. Everything that reports a rate imports it, so
    two reports of the same measurement cannot disagree about what happens at
    the edges."""
    if whole <= 0:
        return None
    return round(part / whole, 3)


def refusal_rate(refused: int, turns: int) -> float | None:
    """How often an answer was declined, out of the answers that were attempted.

    Named rather than inlined, because it is the measurement the charter says
    should be built once — and because "out of what" is the whole of the
    question: a turn that never reached a model is not a turn that was
    refused, and is excluded by the caller before it gets here."""
    return rate(refused, turns)


def turns_of(events: Iterable[Any]) -> list[dict[str, Any]]:
    """Every conversation turn a vault recorded, read back.

    The payload is the verbatim record the session wrote. A record this build
    cannot parse is skipped rather than counted as anything: a turn nobody can
    read is not evidence of a refusal or of an answer, and guessing which would
    move a rate on the strength of a parse failure."""
    found: list[dict[str, Any]] = []
    for event in events:
        if getattr(event, "event_type", "") != READ_RECORDED:
            continue
        body = getattr(event, "body", {}) or {}
        if body.get("phase") != SPEAK:
            continue
        try:
            payload = json.loads(body.get("response_text", ""))
        except (TypeError, ValueError):
            continue
        if isinstance(payload, dict) and isinstance(payload.get("verdict"), dict):
            found.append(payload)
    return found


def harness(events: Iterable[Any]) -> dict[str, Any]:
    """What this vault can say about how honestly it has answered.

    Every figure here is counted off what the vault recorded about its own
    turns. Nothing is asked of a model, nothing is graded against a key, and
    nothing claims to be the confidently-wrong rate."""
    turns = turns_of(events)
    # One exchange per model call, and a turn can take several. What is counted
    # is the answer a person got, so exchanges of one turn collapse into it: a
    # turn that was retried twice and then refused is one refusal, not three.
    answers = _answers(turns)
    refused = [answer for answer in answers if not answer["answered"]]
    figures = [figure for answer in answers for figure in answer["figures"]]
    unsupported = [figure for figure in figures if not figure.get("record_ids")]
    graded = [figure for figure in figures if figure.get("grade")]
    return {
        "turns": len(answers),
        "refused": len(refused),
        # The measurement the charter said should be built once. It is built
        # here and imported by everything that reports one.
        "refusal_rate": refusal_rate(len(refused), len(answers)),
        "figures": len(figures),
        # A figure stated with nothing on record behind it. Not the
        # confidently-wrong rate and never called that: it is checkable without
        # a key, which is exactly why it is not the same measurement.
        "unsupported_figures": len(unsupported),
        "unsupported_rate": rate(len(unsupported), len(figures)),
        "graded_figures": len(graded),
        # What a vault cannot answer, stated in the read rather than left as a
        # zero somebody would read as a clean bill. A key is what says an
        # answer was wrong, and a live vault has none.
        "confidently_wrong_rate": None,
        "confidently_wrong_is_unmeasurable_here": True,
    }


def _answers(turns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One row per answer a person got, out of the exchanges that produced it.

    Exchanges of one turn carry the same question and the same verdict, so they
    are collapsed on the pair. A turn the model was asked twice about is one
    answer: what is being measured is what a person was told, not how much work
    it took to tell them."""
    seen: dict[tuple[str, str], dict[str, Any]] = {}
    for payload in turns:
        verdict = payload.get("verdict") or {}
        question = str(payload.get("question", ""))
        key = (question, str(verdict.get("refusal", "")))
        seen[key] = {
            "question": question,
            "answered": bool(verdict.get("answered")),
            "refusal": str(verdict.get("refusal", "")),
            "figures": _figures(payload),
        }
    return list(seen.values())


def _figures(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Every figure the recorded shape stated.

    Read off the shape the run wrote, which is the same structure the sentence
    was built from. A payload whose shape is not a mapping states no figures
    this can count, and counts none rather than assuming any."""
    shape = payload.get("shape")
    if not isinstance(shape, dict):
        return []
    figures = shape.get("figures")
    if not isinstance(figures, list):
        return []
    return [figure for figure in figures if isinstance(figure, dict)]


def report(measured: dict[str, Any]) -> str:
    """The harness's own account of itself, in plain lines.

    It says what it could not measure before what it could, because a reader
    who takes the figures below for the confidently-wrong rate has been misled
    by a report that was accurate line by line."""
    lines = [
        "honesty over this vault",
        "",
        "  confidently-wrong rate: NOT MEASURED HERE.",
        "    A key is what says an answer was wrong, and a vault has none.",
        "    The single-call eval measures a model against a frozen key; it",
        "    does not measure this product answering about real money.",
        "",
        f"  answers          {measured['turns']:3}",
        f"  refused          {measured['refused']:3}   "
        + _said(measured["refusal_rate"]),
        f"  figures stated   {measured['figures']:3}",
        f"  unsupported      {measured['unsupported_figures']:3}   "
        + _said(measured["unsupported_rate"])
        + "   stated with nothing on record behind it",
    ]
    return "\n".join(lines)


def _said(value: float | None) -> str:
    """A rate in words, or the fact that there is none.

    An empty denominator prints as a phrase rather than as `0%`, because those
    two are the same characters on a screen and opposite facts."""
    return "not measured" if value is None else f"{value:.1%}"


def main() -> int:
    """Run the harness over a vault, or over the synthetic one the build holds.

    Two ways in, and they measure the same thing. `--vault` opens a real one and
    needs its passphrase, which is a Witness's window and nobody else's.
    `--events` reads a file of recorded events, which is how the build runs this
    on every change without a vault, a passphrase or a model.
    """
    import argparse
    import os
    import sys

    from .env import load_dotenv

    # Every command reads the same `.env` in the same fixed place. A command
    # that told a person to set something they had already set would be telling
    # them their configuration does not work.
    load_dotenv()

    parser = argparse.ArgumentParser(description="How honestly this vault has answered.")
    parser.add_argument("--vault", help="a vault directory; its passphrase comes from VIVA_PASSPHRASE")
    parser.add_argument("--events", help="a JSON file of recorded events, for a run that opens nothing")
    parser.add_argument("--json", action="store_true", help="print the measurement rather than the report")
    parser.add_argument("--max-refusal-rate", type=float, default=None,
                        help="fail when the refusal rate is above this")
    parser.add_argument("--max-unsupported-rate", type=float, default=None,
                        help="fail when the unsupported-figure rate is above this")
    args = parser.parse_args()

    if args.events:
        measured = harness(_events_from(args.events))
    elif args.vault:
        from .vault import Vault

        passphrase = os.environ.get("VIVA_PASSPHRASE")
        if not passphrase:
            print("Set VIVA_PASSPHRASE (it is never stored).", file=sys.stderr)
            return 2
        measured = harness(Vault.open(args.vault, passphrase, create=False).events())
    else:
        print("Name a vault with --vault or a file of events with --events.",
              file=sys.stderr)
        return 2

    print(json.dumps(measured, indent=2) if args.json else report(measured))
    # A ceiling is only enforced where something was measured. Failing a build
    # on a rate that is `None` would fail it for having nothing to measure,
    # which is not the same fault and not this gate's.
    for ceiling, name in ((args.max_refusal_rate, "refusal_rate"),
                          (args.max_unsupported_rate, "unsupported_rate")):
        found = measured[name]
        if ceiling is not None and found is not None and found > ceiling:
            print(f"{name} is {found:.1%}, above the {ceiling:.1%} this build allows.",
                  file=sys.stderr)
            return 1
    return 0


def _events_from(path: str) -> list[Any]:
    """Recorded events out of a file, as the objects this module folds over.

    A file rather than a vault, so the build can run this on every change with
    no passphrase and no model. What it holds is what a vault holds, minus the
    encryption — which is why the file the build reads carries no real money."""
    import pathlib

    from .ledger.events import Event

    held = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    return [Event.from_dict(item) for item in held]


if __name__ == "__main__":
    raise SystemExit(main())
