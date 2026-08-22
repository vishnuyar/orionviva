import { isRecord, textValue } from "./primitives";
import type { UpdateLifecycleView } from "../types";

// What happens to this application when a new version exists, read off the
// engine's own answer. Every sentence here is the backend's: a shell composing
// its own would be writing the sentence that tells a person what an update does
// to their records, out of the reach of the pack that ships it.
//
// A read with no sentence is no read. Rendering a section headed "Updates" with
// nothing under it says a channel exists and is quiet, which is the one thing
// this read is here to deny.
export function adaptLifecycle(raw: unknown): UpdateLifecycleView | null {
  if (!isRecord(raw)) return null;
  const sentence = textValue(raw.sentence);
  const originSentence = textValue(raw.origin_sentence);
  if (!sentence.trim() || !originSentence.trim()) return null;
  const notes = Array.isArray(raw.notes) ? raw.notes : [];
  return {
    sentence,
    originSentence,
    revision: textValue(raw.revision),
    notes: notes.map((note) => (isRecord(note) ? { id: textValue(note.id), sentence: textValue(note.sentence) } : null))
      .filter((note): note is { id: string; sentence: string } => note !== null && note.id.trim() !== "" && note.sentence.trim() !== ""),
  };
}
