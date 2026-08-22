"""The harness over a vault, and the refusal rate built once.

What the harness that existed measured is a model against a frozen key. What a
vault can be asked is a different set of questions, and the difference between
them is what every test here is about.
"""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys

import pytest

from viva.honesty import harness, rate, refusal_rate, report, turns_of
from viva.ledger.events import document_captured, read_recorded

FROZEN = pathlib.Path(__file__).resolve().parents[1] / "evals/honesty_turns.json"
ROOT = pathlib.Path(__file__).resolve().parents[2]


def _turn(question: str, answered: bool, refusal: str = "", figures=(), n: int = 1):
    payload = {
        "question": question,
        "shape": {"figures": list(figures)},
        "verdict": {"answered": answered, "refusal": refusal, "calls": 1},
    }
    return read_recorded(f"speak:s:{n}:1", "a-model", "speak-v1", "text",
                         json.dumps(payload), 0.0, 1, 2, True, None,
                         "2026-07-01", phase="speak")


# ------------------------------------------------------- a rate over nothing


def test_a_rate_over_nothing_is_not_a_zero_rate():
    """A harness reporting zero over a vault nobody had asked anything is a
    check giving a clean bill it had no way to withhold."""
    assert rate(0, 0) is None
    assert refusal_rate(0, 0) is None
    assert rate(0, 4) == 0.0


def test_the_refusal_rate_has_one_definition():
    """Two implementations of "how often did it decline" would disagree the
    first time somebody decided whether a broken call counts."""
    import viva.eval_listen as eval_listen

    assert eval_listen.refusal_rate is refusal_rate


# ------------------------------------------------ what a vault can be asked


def test_the_confidently_wrong_rate_is_not_reported_over_a_vault():
    """A key is what says an answer was wrong, and a vault has none. Reporting
    zero here would be the overstatement this item exists to correct."""
    measured = harness([_turn("q", True)])

    assert measured["confidently_wrong_rate"] is None
    assert measured["confidently_wrong_is_unmeasurable_here"] is True


def test_the_report_says_what_it_could_not_measure_before_what_it_could():
    """A reader who takes the figures for the confidently-wrong rate has been
    misled by a report that was accurate line by line."""
    said = report(harness([_turn("q", True)]))

    assert said.index("NOT MEASURED HERE") < said.index("answers")


def test_the_refusal_rate_is_measured_over_the_answers_a_person_got():
    measured = harness([_turn("a", True, n=1), _turn("b", False, "no", n=2),
                        _turn("c", True, n=3), _turn("d", True, n=4)])

    assert measured["turns"] == 4
    assert measured["refused"] == 1
    assert measured["refusal_rate"] == 0.25


def test_a_turn_retried_before_it_answered_is_one_answer_not_three():
    """What is measured is what a person was told, not how much work it took to
    tell them."""
    retried = [_turn("the same question", False, "no", n=n) for n in (1, 2, 3)]

    measured = harness(retried)

    assert measured["turns"] == 1
    assert measured["refusal_rate"] == 1.0


def test_a_figure_stated_with_nothing_behind_it_is_counted_and_not_called_wrong():
    """It is checkable without a key, which is exactly why it is not the same
    measurement as the confidently-wrong rate."""
    measured = harness([
        _turn("a", True, figures=[{"id": "f1", "record_ids": ["doc-1"]}], n=1),
        _turn("b", True, figures=[{"id": "f2", "record_ids": []}], n=2),
    ])

    assert measured["figures"] == 2
    assert measured["unsupported_figures"] == 1
    assert measured["unsupported_rate"] == 0.5
    assert measured["confidently_wrong_rate"] is None


def test_nothing_but_a_recorded_conversation_turn_is_counted():
    """A model call from another pass is a document being read, which is a
    different question with a different key."""
    events = [
        document_captured("d", "f.pdf", 1, "statement", 0.0, "2026-07-01"),
        read_recorded("d", "a-model", "p", "text", "{}", 0.0, 1, 2, True, None,
                      "2026-07-01", phase="extract"),
        _turn("a", True),
    ]

    assert len(turns_of(events)) == 1


def test_a_record_this_build_cannot_read_is_skipped_rather_than_counted():
    """A turn nobody can read is not evidence of a refusal or of an answer, and
    guessing which would move a rate on the strength of a parse failure."""
    broken = read_recorded("speak:s:1:1", "a-model", "p", "text", "not json",
                           0.0, 1, 2, False, "bad", "2026-07-01", phase="speak")

    assert turns_of([broken]) == []
    assert harness([broken])["turns"] == 0


def test_the_whole_measurement_is_json_safe():
    json.dumps(harness([_turn("a", True)]), allow_nan=False)


# ----------------------------------------------------------- the build's run


def test_the_frozen_record_the_build_reads_is_present_and_measurable():
    """The build runs this on every change with no vault, no passphrase and no
    model, which is what the file is for."""
    assert FROZEN.is_file()

    measured = harness(_events_from(FROZEN))

    assert measured["turns"] > 0
    assert measured["refusal_rate"] is not None


def _events_from(path: pathlib.Path):
    from viva.ledger.events import Event

    return [Event.from_dict(item)
            for item in json.loads(path.read_text(encoding="utf-8"))]


def _run(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "viva.honesty", *arguments],
        cwd=ROOT, capture_output=True, text=True,
        env={"PYTHONPATH": f"{ROOT}:{ROOT / 'product'}:{ROOT / 'core'}:{ROOT / 'merchant'}",
             "PATH": "/usr/bin:/bin"})


def test_the_run_reports_and_holds_a_ceiling(tmp_path):
    clean = _run("--events", str(FROZEN), "--max-unsupported-rate", "0.0")
    breached = _run("--events", str(FROZEN), "--max-refusal-rate", "0.0")

    assert clean.returncode == 0, clean.stderr
    assert "NOT MEASURED HERE" in clean.stdout
    assert breached.returncode == 1
    assert "above the" in breached.stderr


def test_a_ceiling_is_not_enforced_where_nothing_was_measured(tmp_path):
    """Failing a build on a rate that is `None` would fail it for having
    nothing to measure, which is not the same fault and not this gate's."""
    empty = tmp_path / "none.json"
    empty.write_text("[]")

    answered = _run("--events", str(empty), "--max-refusal-rate", "0.0")

    assert answered.returncode == 0
    assert "not measured" in answered.stdout


def test_a_run_naming_neither_a_vault_nor_a_file_asks_rather_than_guessing():
    answered = _run()

    assert answered.returncode == 2
    assert "--vault" in answered.stderr
