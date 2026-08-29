"""A turn crosses the bridge, and what a spoken turn owes.

Speech cannot carry a receipt: a figure on a screen opens a drawer that opens a
document, and a figure spoken aloud opens nothing. Every test here is about one
of the three decisions that follow from that.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from viva.desktop_bridge.conversation_actions import ConversationActions
from viva.desktop_bridge.handlers import handlers_for_opened_vault
from viva.persona import STOOD_BEHIND_MOMENT, moment
from viva.surface.conversation import (ANNOUNCE_CITATIONS, SPEAK_GRADE,
                                       SPEAK_TEXT, conversation, unconfigured)
from viva.vault import Vault
from vivacore.models import ModelSpec


class _Result:
    def __init__(self, *, text="", answered=True, refusal="", grade="",
                 figures=(), gaps=(), bindings=None, written=None):
        self.text = text
        self.answered = answered
        self.refusal = refusal
        self.grade = grade
        self.figures = list(figures)
        self.gaps = list(gaps)
        # What each hole in the sentence was bound to, and the words it was
        # written as. The engine's own mapping reads these, and a stand-in that
        # left them out would be testing a shape the engine never produces.
        self.bindings = dict(bindings or {})
        self.written = dict(written or {})


class _Turn:
    def __init__(self, question: str, result: _Result) -> None:
        self.question = question
        self.result = result


# A real spec, because the planner the engine builds from one reads its fields.
# Nothing here reaches it: every test that uses it replaces the session builder.
_SPEC = ModelSpec(name="viva-speak", adapter="anthropic", model="a-pinned-1")

FIGURE = {"id": "f1", "grade": "verified", "what": "the balance on one account",
          "record_ids": ["doc-1", "doc-2"]}
SHOWN = {"f1": "USD 1,200.00"}


class _Projection:
    def captured_docs(self):
        return {"doc-1": "captured", "doc-2": "captured"}

    def captured_filenames(self):
        return {"doc-1": "checking.pdf", "doc-2": "savings.pdf"}


def _answered(**over) -> dict:
    result = _Result(text="You have USD 1,200.00 on that account.",
                     grade="verified", figures=[FIGURE], **over)
    return conversation(_Turn("what is on that account?", result), SHOWN,
                        projection=_Projection(), turn_id="turn-1")


# --------------------------------------------------- the mirror, and the grade


def test_a_figure_carries_the_words_the_sentence_wrote_it_as():
    """The figure under the sentence is the figure in the sentence: its hedge,
    its currency and its conventions are the same string rather than a second
    rendering of the same number."""
    said = _answered()

    assert said["figures"][0]["written"] == "USD 1,200.00"
    assert said["figures"][0]["record_ids"] == ["doc-1", "doc-2"]


def test_a_figure_carries_only_openable_document_receipts():
    class _OneDocumentProjection:
        def captured_docs(self):
            return {"doc-1": "captured"}

        def captured_filenames(self):
            return {"doc-1": "checking.pdf"}

    said = conversation(
        _Turn("what is on that account?", _Result(
            text="You have USD 1,200.00 on that account.", grade="verified",
            figures=[{**FIGURE, "record_ids": ["doc-1", "movement-1"]}])),
        SHOWN, projection=_OneDocumentProjection(), turn_id="turn-1")

    assert said["figures"][0]["evidence_id"] == "conversation:turn-1:f1"
    assert said["figures"][0]["evidence_links"] == [{
        "document_id": "doc-1", "label": "checking.pdf",
        "relation": "attests", "page": ""}]


def test_the_grade_is_a_whole_reviewed_sentence_rather_than_a_word():
    """X2 asks for a sentence, not a frame with a word dropped into it."""
    said = _answered()

    assert said["grade_sentence"] == moment(STOOD_BEHIND_MOMENT + "verified")
    assert said["spoken"]["grade_sentence"] == said["grade_sentence"]


def test_an_answer_stating_no_graded_figure_carries_no_grade_line():
    said = conversation(_Turn("hello", _Result(text="Hello.")), {})

    assert said["grade_sentence"] == ""
    assert SPEAK_GRADE not in said["spoken"]["parts"]


# ------------------------------------------------------- what a voice may say


def test_the_grade_is_among_the_parts_a_voice_says():
    """It is exactly the part a person cannot look up later if they only heard
    the number."""
    assert SPEAK_GRADE in _answered()["spoken"]["parts"]


def test_a_citation_is_announced_and_never_read_out():
    """A document read aloud would be theatre, and is not evidence anyway."""
    spoken = _answered()["spoken"]

    assert ANNOUNCE_CITATIONS in spoken["parts"]
    assert spoken["citation_sentence"] == moment("conversation_spoken_citation")
    assert "doc-1" not in spoken["citation_sentence"]


def test_an_answer_resting_on_nothing_announces_no_citation():
    said = conversation(_Turn("q", _Result(text="I could not find that.")), {})

    assert said["spoken"]["citation_sentence"] == ""
    assert ANNOUNCE_CITATIONS not in said["spoken"]["parts"]


def test_a_non_document_record_is_not_announced_as_an_openable_citation():
    said = conversation(
        _Turn("q", _Result(text="Something.", grade="verified", figures=[{
            **FIGURE, "record_ids": ["movement-1"]}])), SHOWN,
        projection=_Projection(), turn_id="turn-1")

    assert said["figures"][0]["evidence_links"] == []
    assert said["spoken"]["citation_sentence"] == ""
    assert ANNOUNCE_CITATIONS not in said["spoken"]["parts"]


def test_nothing_is_spoken_while_the_text_is_not_in_front_of_the_person():
    """A figure spoken with nowhere to check it is a number somebody has to
    take on trust, which is the one thing this product exists not to ask."""
    result = _Result(text="You have USD 1,200.00 on that account.",
                     grade="verified", figures=[FIGURE])
    said = conversation(_Turn("q", result), SHOWN, mirrored=False)

    assert said["spoken"]["may_speak"] is False
    assert said["spoken"]["parts"] == []
    assert said["spoken"]["text"] == ""
    assert said["spoken"]["withheld"] == moment("conversation_spoken_withheld")


def test_a_voice_is_told_in_words_that_a_remote_path_is_undecided():
    """It would be a new outbound edge, and a decision nobody has made. A
    surface is told rather than finding out by trying."""
    for mirrored in (True, False):
        result = _Result(text="Something.")
        said = conversation(_Turn("q", result), {}, mirrored=mirrored)

        assert said["spoken"]["local_only"] == moment(
            "conversation_voice_local_only")


def test_the_whole_turn_is_json_safe():
    json.dumps(_answered(), allow_nan=False)


def test_a_turn_that_produced_nothing_is_absent_rather_than_empty():
    assert conversation(object(), {})["state"] == "absent"


# ---------------------------------------------------------------- the bridge


def test_the_ask_operation_is_served_by_an_opened_vault():
    assert "viva.conversation.ask" in handlers_for_opened_vault(object()).handlers


def test_a_machine_that_names_no_model_refuses_and_says_where_to_say_yes(
        tmp_path: Path, monkeypatch):
    """There is no branch here that calls a model on a machine that has not
    been told to reach one."""
    import viva.speak as speak

    monkeypatch.setattr(speak, "speak_spec", lambda: None)
    vault = Vault.open(tmp_path / "vault", "pw")

    answered = ConversationActions(vault).ask({"question": "what do I have?"})

    assert answered["kind"] == "refused"
    assert answered["reason"] == "no_model_named"
    assert answered["message"] == moment("conversation_unconfigured")
    assert answered["state"]["state"] == "unavailable"


def test_the_request_carries_a_question_and_whether_its_text_is_shown(tmp_path: Path):
    from viva.desktop_bridge.conversation_actions import _ask_request

    from viva.desktop_bridge.handlers import BridgeRequestError

    assert _ask_request({"question": "what?"}) == ("what?", True)
    assert _ask_request({"question": "what?", "mirrored": False}) == ("what?", False)
    with pytest.raises(BridgeRequestError):
        _ask_request({"question": "what?", "speak": True})
    with pytest.raises(BridgeRequestError):
        _ask_request({"question": "  "})
    with pytest.raises(BridgeRequestError):
        _ask_request({"question": "what?", "mirrored": "yes"})


def test_the_unconfigured_read_is_unavailable_rather_than_failed():
    """Nothing went wrong. A person is told what would make it possible."""
    said = unconfigured()

    assert said["state"] == "unavailable"
    assert said["sentence"] == moment("conversation_unconfigured")


def test_one_session_lives_as_long_as_the_vault_is_open(tmp_path: Path, monkeypatch):
    """Turns share context. A second session would be a second conversation
    wearing the first one's screen."""
    import viva.desktop_bridge.conversation_actions as actions
    import viva.speak as speak

    class _Session:
        def __init__(self) -> None:
            self.asked: list[str] = []

        def ask(self, question: str) -> _Turn:
            self.asked.append(question)
            return _Turn(question, _Result(text="Something."))

    built: list[_Session] = []

    def one(*_args, **_kwargs) -> _Session:
        built.append(_Session())
        return built[-1]

    monkeypatch.setattr(speak, "speak_spec", lambda: _SPEC)
    monkeypatch.setattr(actions, "_session_for", one)
    vault = Vault.open(tmp_path / "vault", "pw")
    talking = ConversationActions(vault)

    talking.ask({"question": "first"})
    talking.ask({"question": "second"})

    assert len(built) == 1
    assert built[0].asked == ["first", "second"]


def test_a_turn_that_refused_answers_as_a_refusal_with_vivas_own_sentence(
        tmp_path: Path, monkeypatch):
    import viva.desktop_bridge.conversation_actions as actions
    import viva.speak as speak

    class _Session:
        def ask(self, question: str) -> _Turn:
            return _Turn(question, _Result(
                text="", answered=False,
                refusal="I will not state that without something behind it."))

    monkeypatch.setattr(speak, "speak_spec", lambda: _SPEC)
    monkeypatch.setattr(actions, "_session_for", lambda *a, **k: _Session())
    vault = Vault.open(tmp_path / "vault", "pw")

    answered = ConversationActions(vault).ask({"question": "what?"})

    assert answered["kind"] == "refused"
    assert answered["message"] == "I will not state that without something behind it."
    assert answered["state"]["answered"] is False


def test_asking_with_no_mirror_hands_back_nothing_to_speak(
        tmp_path: Path, monkeypatch):
    """A caller that says its text is not shown gets nothing to speak, rather
    than a quieter answer."""
    import viva.desktop_bridge.conversation_actions as actions
    import viva.speak as speak

    class _Session:
        def ask(self, question: str) -> _Turn:
            return _Turn(question, _Result(text="You have some money.",
                                           grade="verified", figures=[FIGURE]))

    monkeypatch.setattr(speak, "speak_spec", lambda: _SPEC)
    monkeypatch.setattr(actions, "_session_for", lambda *a, **k: _Session())
    vault = Vault.open(tmp_path / "vault", "pw")

    answered = ConversationActions(vault).ask(
        {"question": "what?", "mirrored": False})

    assert answered["state"]["spoken"]["may_speak"] is False
    assert answered["state"]["text"] == "You have some money."


def test_the_words_a_figure_was_written_as_come_from_the_engines_own_mapping(
        tmp_path: Path, monkeypatch):
    """Not a second rendering of the same number: the mapping the engine uses
    to put a figure under its own sentence is the one this read asks."""
    import viva.desktop_bridge.conversation_actions as actions
    import viva.speak as speak

    class _Session:
        def ask(self, question: str) -> _Turn:
            return _Turn(question, _Result(
                text="You have about USD 1,200 on that account.",
                grade="verified", figures=[FIGURE],
                bindings={"amount": {"figure": "f1"}},
                written={"amount": "about USD 1,200"}))

    monkeypatch.setattr(speak, "speak_spec", lambda: _SPEC)
    monkeypatch.setattr(actions, "_session_for", lambda *a, **k: _Session())
    vault = Vault.open(tmp_path / "vault", "pw")

    answered = ConversationActions(vault).ask({"question": "what?"})

    assert answered["state"]["figures"][0]["written"] == "about USD 1,200"
