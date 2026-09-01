"""Final structural validation and rendering for a tool run."""

from __future__ import annotations

from .. import render
from ..persona import STOOD_BEHIND_MOMENT, moment
from .envelope import MONEY_KINDS, _named, weakest
from .runner import RunResult, _Ground, _diagnosed, _refused
from .runner_binding import (_bound, _boundaries, _covered, _line_of,
                             _named_reference, _stated_figures)
from .shape import Shape

# ------------------------------------------------------------------- the gate


def _labelled(entities) -> dict:
    """The things these entities are, as the one label each kind is told apart
    by, grouped by kind.

    It is the label the model was shown, taken from the same place the model
    took it from, so what a sentence names and what a figure's boundary names
    are one string rather than two spellings of one thing."""
    out: dict = {}
    for item in entities:
        out.setdefault(item["kind"], set()).add(_named(item)["label"])
    return out


def _misnamed(clause, references: dict, ground: _Ground):
    """The slice of a figure this clause states that the clause names a
    different thing for, as ``(slot, figure, cut entry, what was named)``, or
    None where every slice agrees with what the sentence names.

    An entity belongs to a figure when the figure's own boundary names it. The
    figure says which slice of a set it is; the sentence says which thing it is
    about, through a hole, which is a reference and never words; and those are
    two strings put there by code. Neither the sentence's words nor the read
    that emitted either half is read.

    Every axis of the cut is compared, because the cut is a set and a figure
    that is right about one axis of it and wrong about another is a figure
    about something else. A clause naming several things of one kind is
    answered by any of them: which of two things a number sits beside is the
    sentence's own order, and reading that would be reading the sentence.

    Two ways of agreeing are silence rather than a fault. A clause that names
    nothing of a slice's kind claims nothing about that slice, and a sentence
    that says which thing it is about only in its own words is prose nothing
    here checks. And a slice naming something no read of this run established
    is a set the run holds no thing for: nothing can be bound that would name
    it, so nothing can name it wrongly either.

    A figure stated as a line of a block is not compared. Every line is written
    beside the name of the slice it is, out of the same declaration this would
    compare it against, so a line says what it is about itself and there is no
    second declaration for it to disagree with."""
    bound = [references.get(slot.name) or {} for slot in clause.slots]
    named = _labelled(ground.entities[str(reference["entity"])]
                      for reference in bound if "entity" in reference)
    established = _labelled(ground.entities.values())
    for slot in clause.slots:
        reference = references.get(slot.name) or {}
        if "figure" not in reference:
            continue
        fig = ground.book[str(reference["figure"])]
        for item in (fig.get("boundary") or {}).get("cut") or []:
            here = named.get(item["kind"]) or set()
            value = str(item["value"])
            if not here or value not in established.get(item["kind"], set()):
                continue
            if value not in here:
                return slot, fig, item, sorted(here)
    return None


def _written_out(parts) -> str:
    """The whole answer as one piece of text, out of what each part wrote and
    whether that part is a block of lines.

    Sentences run on, the way sentences do. A block does not: it is a line per
    thing, so what sits either side of one begins on its own line. The read's
    own tail sentence therefore lands under the last row rather than beside it,
    which is what a person reading a list of ten needs it to do."""
    out, blocked = "", False
    for piece, block in parts:
        if not str(piece).strip():
            continue
        if out:
            out += "\n" if block or blocked else " "
        out += str(piece)
        blocked = block
    return out.strip()


def _gate(step: dict, transcript: list, ground: _Ground, shape: Shape,
          locale: str, *, tools, result_policy=None) -> RunResult:
    """The checks on a delivery, over the structure and never the sentence.

    `tools` names the registered tools, which is what decides whether an entry
    in the transcript is a read that can account for a turn that established
    nothing. It has no default: a caller that omitted it would drop the cause
    silently, and the turn would look like it had none to give."""
    dicts = [t.to_dict() for t in transcript]
    bindings = step.get("bindings")
    if not isinstance(bindings, dict):
        return _refused("bad_delivery", "The bindings must be an object naming "
                        "each hole in the shape.", dicts, len(transcript), shape)
    slots = shape.slots
    for name in bindings:
        if name not in slots:
            return _refused(
                "unshaped_binding",
                f"The delivery binds {name!r}, which is not a hole in the shape "
                "this turn committed to.", dicts, len(transcript), shape)

    # Which figures each hole stands beside, by the clause it is in. The holes
    # are resolved one at a time and the clause is what says which of this
    # run's figures a day or a span in it belongs to, so the clause each hole
    # came from travels with it into the resolution.
    beside = {slot.name: _stated_figures(clause, bindings, ground)
              for clause in shape.clauses for slot in clause.slots}

    written: dict = {}
    references: dict = {}
    gaps: list = []
    binding_issues: list = []
    spoken, dropped = [], []
    for clause in shape.clauses:
        unfilled = [slot for slot in clause.slots
                    if slot.name not in bindings]
        if unfilled:
            gaps.extend({"name": slot.name, "type": slot.type}
                        for slot in unfilled)
            dropped.append(unfilled[0].type)
            continue
        clause_written: dict = {}
        clause_references: dict = {}
        issue = None
        for slot in clause.slots:
            value, tag, detail = _bound(
                slot, bindings[slot.name], ground, locale,
                alongside=beside.get(slot.name, ()))
            if value is None:
                issue = (slot, tag, detail)
                break
            clause_written[slot.name] = value
            clause_references[slot.name] = _named_reference(
                slot, bindings[slot.name])
        if issue is not None:
            slot, tag, detail = issue
            binding_issues.append((tag, detail))
            gaps.append({"name": slot.name, "type": slot.type})
            dropped.append(slot.type)
            continue
        written.update(clause_written)
        references.update(clause_references)
        spoken.append(clause)
    if not spoken:
        if binding_issues:
            tag, detail = binding_issues[0]
            return _refused(tag, detail, dicts, len(transcript), shape)
        return _refused("nothing_established",
                        "Every clause of the answer rests on something this "
                        "run could not establish.", dicts, len(transcript),
                        shape, diagnosis=_diagnosed(transcript, tools))

    # The clause is the unit here, and it has to be: every hole above was
    # resolved on its own against everything this run established, so a figure
    # of one thing and a thing of the same kind can each be real and belong to
    # different sentences. What ties them together is that the figure's own
    # boundary names what the clause names. It runs over what survived the
    # drops, because a clause about to be dropped asserts nothing to be wrong
    # about.
    stood, subject_issues = [], []
    for clause in spoken:
        misnamed = _misnamed(clause, references, ground)
        if misnamed is None:
            stood.append(clause)
            continue
        slot, fig, item, named = misnamed
        subject_issues.append((
            f"The clause holding {slot.name!r} names the {item['kind']} "
            + ", ".join(repr(one) for one in named)
            + f", and {fig['what']!r} was taken over the {item['kind']} "
            f"{str(item['value'])!r} — the number is real and it is a number "
            "about something else."))
        gaps.append({"name": slot.name, "type": slot.type})
        dropped.append(slot.type)
    if not stood:
        return _refused("wrong_subject", subject_issues[0], dicts,
                        len(transcript), shape)
    spoken = stood

    # AnswerProgram commits which claims must survive and whether independent
    # optional claims may be omitted.  The legacy delivery path has no such
    # policy and keeps its established clause-level degradation behavior.
    policy = dict(result_policy or {})
    if result_policy is not None:
        spoken_ids = {clause.id for clause in spoken}
        missing_ids = [clause.id for clause in shape.clauses
                       if clause.id not in spoken_ids]
        required_missing = [clause_id for clause_id in
                            policy.get("required_clauses", [])
                            if clause_id not in spoken_ids]
        if required_missing or (missing_ids
                                and not policy.get("allow_partial", False)):
            reason = ("required clauses were not grounded: "
                      + ", ".join(required_missing)) if required_missing else (
                          "partial delivery is disabled; omitted clauses: "
                          + ", ".join(missing_ids))
            return _refused("nothing_established", reason, dicts,
                            len(transcript), shape,
                            diagnosis=_diagnosed(transcript, tools))

    # Only what survived asserts anything, so only what survived is answerable
    # for its records and its caveats. The holes are walked in the order the
    # sentence places them, which is the order a person reads it in.
    #
    # One figure can fill more than one hole — the same balance named in two
    # clauses of one answer. It is one figure and it is cited once.
    said = [s.name for c in spoken for s in c.slots]
    # And which figures each clause stated, in the order it stated them, so a
    # statement about where a figure's claim ends is placed under the sentence
    # that made it rather than in a pool at the end.
    per_clause: list = []
    cited, seen, as_numbers = [], set(), set()
    for clause in spoken:
        here: dict = {}
        for slot in clause.slots:
            reference = references[slot.name]
            as_rows = "read" in reference or "read_figures" in reference
            # A block of rows states every figure it wrote a line for, and
            # those are answerable exactly as a figure named in a sentence is:
            # for their records, for their caveats and for the answer's grade.
            # The figures of that read it wrote no line for — the read's own
            # total and its count — are not stated and are not cited.
            if as_rows:
                reading = str(reference.get("read")
                              or reference.get("read_figures"))
                stated = list(ground.readings[reading])
                if "read" in reference:
                    stated = [fid for fid in stated
                              if _line_of(ground.book[fid])]
            elif "figure" in reference:
                stated = [str(reference["figure"])]
            else:
                continue
            for fid in stated:
                if not as_rows:
                    as_numbers.add(fid)
                # A figure stated as a number of its own says its own slices in
                # that sentence, however many blocks of the same clause it also
                # appears in; one stated only as a line has already said them,
                # as the line's name.
                here[fid] = here[fid] and as_rows if fid in here else as_rows
                if fid in seen:
                    continue
                seen.add(fid)
                cited.append(ground.book[fid])
        per_clause.append([(ground.book[fid], as_rows)
                           for fid, as_rows in here.items()])

    for fig in cited:
        # A money figure with no record behind it is refused. The other kinds
        # rest on ledger events or on the person's own premise, and are not
        # checked for records here.
        if fig["kind"] in MONEY_KINDS and not fig["record_ids"]:
            return _refused("uncited_figure",
                            f"The figure {fig['what']!r} cites no record — "
                            "every figure about your money must stand on one.",
                            dicts, len(transcript), shape)

    # What the results said their own numbers do not cover, for every figure
    # the answer stated and did not already place a caveat for. In the order
    # the figures were stated, once each however many results wrote them, and
    # verbatim — a caveat re-worded is a caveat weakened.
    owed: list = []
    for fig in cited:
        for cid in ground.owed.get(fig["id"], ()):
            if cid not in owed:
                owed.append(cid)

    # How many of the accounts a person holds this answer covers, over every
    # figure the answer stated. It is one claim about the answer, so it is said
    # once and after the clauses, where the answer is what a person has just
    # read: two of these would be two counts of one thing, and one placed under
    # a clause would be a count of what that clause covers written in words
    # that are about the whole of it. An answer naming no account says nothing
    # here rather than saying it covers none, and an answer that cannot
    # enumerate what it covers says nothing here rather than a number it
    # cannot stand behind.
    #
    # It goes ahead of the limits: how far a claim reaches says what the claim
    # is about, and what the claim does not cover is read against that.
    covered, held = _covered(cited) or (0, 0)

    # How well what the answer stated is stood behind: the weakest grade among
    # every money figure it stated, lines of a block included, said in the
    # pack's one whole sentence for that word. It is the answer's own grade, so
    # what a person hears and what the result carries are one word.
    #
    # Whether it is said turns on whether any of those figures was stated as a
    # number in a sentence. Where every one of them is a line of a block, the
    # block has already stated this grade above itself. Where one was, the
    # block's figures are inside the set this speaks for, so this sentence can
    # only be weaker than or equal to the line above the block and the two can
    # never disagree.
    #
    # It lands after the boundaries and before the limits: a word about strength
    # heard before the extent of the claim has been stated invites reading it as
    # covering more than it does.
    graded = [f for f in cited if f["kind"] in MONEY_KINDS]
    stood_behind = weakest(f["grade"] for f in graded)
    stated_in_a_sentence = any(f["id"] in as_numbers for f in graded)

    parts: list = []
    for clause, figures in zip(spoken, per_clause):
        parts.append((clause.written(written),
                      any(isinstance(written[s.name], render.Rows)
                          for s in clause.slots)))
        parts += [(line, False) for line in _boundaries(figures, ground)]
    if covered and covered < held:
        parts.append((moment("boundary_accounts",
                             counted=render.count(covered),
                             held=render.count(held)), False))
    if stood_behind and stated_in_a_sentence:
        parts.append((moment(STOOD_BEHIND_MOMENT + stood_behind), False))
    if owed:
        parts.append((moment("answer_limits", limits=render.caveat(
            " ".join(ground.caveats[cid] for cid in owed))), False))
    for kind in dropped:
        # A clause nothing could fill is a disclosed gap, never a zero and
        # never a silence. What is missing is named by its kind, in the pack's
        # own words.
        parts.append((moment("answer_gap", what=moment(f"gap_{kind}")), False))
    return RunResult(
        answered=True, text=_written_out(parts),
        figures=[dict(f) for f in cited],
        grade=stood_behind,
        transcript=dicts, calls=len(transcript),
        shape=shape.to_dict(),
        bindings={n: references[n] for n in said},
        written={n: str(written[n]) for n in said}, gaps=gaps,
        caveats=[ground.caveats[cid] for cid in owed],
        disclosures=([
            f"evidence_grade:{stood_behind}"] if stood_behind else [])
        + [f"caveat:{cid}" for cid in owed]
        + [f"unbound:{kind}" for kind in dropped])
