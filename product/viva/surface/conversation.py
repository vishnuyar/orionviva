"""One turn of a conversation, ready to render — and ready to be spoken.

**Speech cannot carry a receipt.** A figure on a screen opens a drawer that
opens a document; a figure spoken aloud opens nothing. X2 requires that every
answer stating a graded money figure carries one line saying how well what it
stated is stood behind, and that the line is a whole reviewed sentence rather
than a frame with a word dropped into it. So this module answers what a spoken
answer owes when its evidence can only exist on a screen, and it answers it
here rather than leaving it to whichever surface speaks first.

Three decisions, and they are the design half of this item.

**The grade line is spoken.** It is a sentence about how well a number is stood
behind, and it is exactly the part a person cannot look up later if they only
heard the number.

**A citation is announced, never read out.** What a figure rests on is on the
screen, and saying so is honest; reading a document aloud would be theatre, and
a document read aloud is not evidence anyway.

**An answer is not spoken while its text mirror is not in front of the person.**
A figure spoken with nowhere to check it is a number somebody has to take on
trust, which is the one thing this product exists not to ask.

**Voice is a skin over this turn, never a second answering path.** VOICE-34
requires that text and voice share one session and one runtime, so what a voice
surface reads is exactly what a text surface reads: the same turn, the same
grade line, the same citations. Nothing here is an audio hook, and in
particular the `modality` a recorded exchange carries names the model-calling
protocol rather than anything about sound — a reader of this module that took
it for somewhere voice attaches would be wrong.

**Reaching a remote provider to speak or listen is not decided here.** It would
be a new outbound edge, and T6 is explicit that new outbound bytes of any kind
are a decision — a decision record plus a promise check — never an
implementation detail. This module therefore declares the local path and states
the other as undecided, in words, rather than leaving a surface to discover it.

A pure function of what one turn produced. It opens nothing, calls nothing and
knows nothing about how the payload travels.
"""

from __future__ import annotations

from typing import Any

from ..persona import STOOD_BEHIND_MOMENT, moment
from .models import PanelState

# What a spoken answer may carry. Each is a decision this module makes rather
# than a setting: a surface that could turn the grade line off would be able to
# speak a graded figure ungraded, which is the failure X2 exists to prevent.
SPEAK_TEXT = "text"
SPEAK_GRADE = "grade"
ANNOUNCE_CITATIONS = "citations"
SPOKEN_PARTS = (SPEAK_TEXT, SPEAK_GRADE, ANNOUNCE_CITATIONS)


def timeline(projection: Any, queue: dict[str, Any]) -> dict[str, Any]:
    """Compose durable turns, correction proposals, and open questions."""
    proposals = {
        row["proposal_id"]: row
        for row in projection.conversation_proposals()
    }
    proposals_by_turn: dict[str, list[dict[str, Any]]] = {}
    for proposal in proposals.values():
        proposals_by_turn.setdefault(
            str(proposal.get("turn_id") or ""), []).append(proposal)
    turns = [_timeline_turn(row, proposals, proposals_by_turn, projection) for row in
             projection.conversation_turns()]
    return {
        "state": PanelState.READY.value,
        "turns": turns,
        "questions": [dict(question) for question in queue.get("questions", [])],
        "total": int(queue.get("total", len(queue.get("questions", [])))),
        "tail": dict(queue.get("tail") or {"count": 0, "amount": ""}),
        "pending": dict(queue.get("pending") or {"count": 0}),
        "invite": str(queue.get("invite", "")),
        "answered_by_document": str(queue.get("answered_by_document", "")),
    }


def _timeline_turn(row: dict[str, Any],
                   proposals: dict[str, dict[str, Any]],
                   proposals_by_turn: dict[str, list[dict[str, Any]]],
                   projection: Any) -> dict[str, Any]:
    proposal_id = str(row.get("proposal_id") or "")
    proposal = proposals.get(proposal_id)
    if proposal is None:
        interrupted = proposals_by_turn.get(
            str(row.get("turn_id") or ""), [])
        if len(interrupted) == 1:
            proposal = interrupted[0]
            proposal_id = str(proposal.get("proposal_id") or "")
    shown_proposal = None
    if proposal is not None:
        shown_proposal = {
            "id": proposal_id,
            "summary": str(proposal.get("summary") or ""),
            "status": str(proposal.get("status") or ""),
            "outcome": str(proposal.get("outcome") or ""),
            "message": str(proposal.get("message") or ""),
            "reason": str(proposal.get("reason") or ""),
        }
    answer = dict(row.get("answer") or {})
    figures = []
    for figure in answer.get("figures", []):
        if not isinstance(figure, dict):
            continue
        figures.append(_figure_receipt(
            figure, projection, str(row.get("turn_id") or "")))
    if figures or "figures" in answer:
        answer["figures"] = figures
    return {
        "id": str(row.get("turn_id") or ""),
        "kind": str(row.get("kind") or ""),
        "occurred_at": str(row.get("occurred_at") or ""),
        "prompt": str(row.get("prompt") or ""),
        "said": str(row.get("said") or ""),
        "question_id": str(row.get("question_id") or ""),
        "outcome": str(row.get("outcome") or ""),
        "message": str(row.get("message") or ""),
        "reason": str(row.get("reason") or ""),
        "answer": answer,
        "proposal": shown_proposal,
    }


def conversation(turn: Any, shown: dict[str, str],
                 mirrored: bool = True, *, projection: Any = None,
                 turn_id: str = "") -> dict[str, Any]:
    """One turn, as a screen renders it and as a voice would speak it.

    ``shown`` maps a figure's identity to the words it was written as in the
    sentence, which is how the figure under the sentence is the figure in the
    sentence: its hedge, its currency and its conventions are the same string
    rather than a second rendering of the same number.

    ``mirrored`` is whether the text of this turn is in front of the person.
    A voice surface that has not put it there says so, and this refuses to hand
    back anything to speak."""
    result = getattr(turn, "result", None)
    if result is None:
        return {"state": PanelState.ABSENT.value, "reason": "no_turn"}
    figures = [_figure(figure, shown, projection, turn_id)
               for figure in getattr(result, "figures", [])]
    grade = getattr(result, "grade", "") or ""
    return {
        "state": PanelState.READY.value,
        "question": getattr(turn, "question", ""),
        "text": getattr(result, "text", ""),
        "answered": bool(getattr(result, "answered", False)),
        # A refusal is the pack's own sentence and travels as it was written.
        "refusal": getattr(result, "refusal", "") or "",
        "grade": grade,
        # The whole reviewed sentence for the grade, never a frame with a word
        # dropped into it. Empty when the answer stated no graded figure.
        "grade_sentence": moment(STOOD_BEHIND_MOMENT + grade) if grade else "",
        "figures": figures,
        "gaps": [dict(gap) for gap in getattr(result, "gaps", [])],
        "spoken": _spoken(getattr(result, "text", ""), grade, figures, mirrored),
    }


def _figure(figure: dict, shown: dict[str, str], projection: Any = None,
            turn_id: str = "") -> dict[str, Any]:
    """One figure the sentence stated, and the route back to what it rests on.

    `record_ids` is the route. It is carried whether or not anything is spoken,
    because the mirror is what makes a spoken figure checkable at all: the
    sentence a person hears and the sentence they can open are the same
    sentence."""
    identity = str(figure.get("id", ""))
    return _figure_receipt({
        "id": identity,
        # The words this figure was written as in the sentence, so the figure
        # under the sentence is the figure in it.
        "written": shown.get(identity, ""),
        "grade": figure.get("grade", "") or figure.get("kind", ""),
        "what": figure.get("what", ""),
        "record_ids": [str(record) for record in figure.get("record_ids", [])],
    }, projection, turn_id)


def _figure_receipt(figure: dict[str, Any], projection: Any,
                    turn_id: str) -> dict[str, Any]:
    """Add captured-document links and a turn-scoped selection identity.

    Record identities not known as captured documents remain audit-only.
    """
    identity = str(figure.get("id") or "")
    record_ids = [str(record) for record in figure.get("record_ids", [])]
    links = []
    if projection is not None:
        documents = set(projection.captured_docs())
        filenames = projection.captured_filenames()
        links = [{
            "document_id": record_id,
            "label": str(filenames.get(record_id) or ""),
            "relation": "attests",
            "page": "",
        } for record_id in record_ids if record_id in documents]
    evidence_id = (f"conversation:{turn_id}:{identity}"
                   if turn_id and identity else "")
    return {
        **figure,
        "id": identity,
        "record_ids": record_ids,
        "evidence_id": evidence_id,
        "evidence_links": links,
    }


def _spoken(text: str, grade: str, figures: list[dict],
            mirrored: bool) -> dict[str, Any]:
    """What a voice surface may say, and what it may not.

    Nothing here is composed by a surface: the words are the turn's, the grade
    line is the pack's, and the sentence announcing a citation is the pack's.
    A surface that assembled its own would be speaking a figure under wording
    nobody reviewed."""
    cited = [figure for figure in figures if figure["evidence_links"]]
    if not mirrored:
        return {
            "may_speak": False,
            "withheld": moment("conversation_spoken_withheld"),
            "parts": [],
            "text": "",
            "grade_sentence": "",
            "citation_sentence": "",
            "local_only": moment("conversation_voice_local_only"),
        }
    return {
        "may_speak": bool(text.strip()),
        "withheld": "",
        # Which parts of this turn a voice surface says. The grade is in the
        # list whenever there is one, because it is exactly the part a person
        # cannot look up later if they only heard the number.
        "parts": [part for part, present in (
            (SPEAK_TEXT, bool(text.strip())),
            (SPEAK_GRADE, bool(grade)),
            (ANNOUNCE_CITATIONS, bool(cited)),
        ) if present],
        "text": text,
        "grade_sentence": moment(STOOD_BEHIND_MOMENT + grade) if grade else "",
        # Announced, never read out. A document read aloud is not evidence.
        "citation_sentence": moment("conversation_spoken_citation") if cited else "",
        # Stated rather than left to be discovered: reaching a remote provider
        # to speak or listen is a new outbound edge and a decision nobody has
        # made, so a surface is told in words rather than finding out by
        # trying.
        "local_only": moment("conversation_voice_local_only"),
    }


def unconfigured() -> dict[str, Any]:
    """What a conversation says on a machine that names no model.

    It is `unavailable` rather than `failed`: nothing went wrong, and a person
    is told what would make it possible rather than that something broke."""
    return {
        "state": PanelState.UNAVAILABLE.value,
        "reason": "no_model_named",
        "sentence": moment("conversation_unconfigured"),
    }
