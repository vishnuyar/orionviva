import type { SpokenTurn, TurnFigure, TurnView } from "../types";
import { booleanValue, isRecord, textValue } from "./primitives";

// One figure the sentence stated. A figure with no identity is dropped: it
// could not be tied back to anything, and a row that cannot be followed is a
// claim with no route out of it.
function figure(raw: unknown): TurnFigure | null {
  if (!isRecord(raw)) return null;
  const id = textValue(raw.id);
  if (!id) return null;
  return {
    id,
    written: textValue(raw.written),
    grade: textValue(raw.grade),
    what: textValue(raw.what),
    recordIds: Array.isArray(raw.record_ids) ? raw.record_ids.map(textValue).filter((record) => record) : [],
  };
}

// What a voice may say. `maySpeak` is the read's own answer and is never
// inferred here from whether there is text: a turn whose text mirror is not in
// front of the person carries text and may not be spoken, and those two facts
// are exactly the pair this field exists to keep apart.
function spoken(raw: unknown): SpokenTurn {
  if (!isRecord(raw)) return { maySpeak: false, withheld: "", parts: [], text: "", gradeSentence: "", citationSentence: "", localOnly: "" };
  return {
    maySpeak: booleanValue(raw.may_speak) === true,
    withheld: textValue(raw.withheld),
    parts: Array.isArray(raw.parts) ? raw.parts.map(textValue).filter((part) => part) : [],
    text: textValue(raw.text),
    gradeSentence: textValue(raw.grade_sentence),
    citationSentence: textValue(raw.citation_sentence),
    localOnly: textValue(raw.local_only),
  };
}

// One turn, read into the shape a screen holds. A turn with neither an answer
// nor a refusal is read as no turn at all: there would be nothing to show and
// nothing to say about why.
export function adaptTurn(raw: unknown): TurnView | null {
  if (!isRecord(raw)) return null;
  const text = textValue(raw.text);
  const refusal = textValue(raw.refusal);
  if (!text.trim() && !refusal.trim()) return null;
  return {
    question: textValue(raw.question),
    text,
    answered: booleanValue(raw.answered) === true,
    refusal,
    grade: textValue(raw.grade),
    gradeSentence: textValue(raw.grade_sentence),
    figures: (Array.isArray(raw.figures) ? raw.figures : []).map(figure).filter((row): row is TurnFigure => row !== null),
    spoken: spoken(raw.spoken),
  };
}
