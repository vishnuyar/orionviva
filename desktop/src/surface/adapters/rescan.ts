import type { RescanChange, RescanReport } from "../types";
import { isRecord, optionalNonNegativeInteger, textValue } from "./primitives";

// One row of what a pass did. A row with no sentence is dropped: this side has
// no words for what a gap is, and a count on its own would be a number a person
// has to guess the meaning of.
function change(raw: unknown): RescanChange | null {
  if (!isRecord(raw)) return null;
  const id = textValue(raw.id);
  const count = optionalNonNegativeInteger(raw.count);
  const sentence = textValue(raw.sentence);
  if (!id || count === undefined || !sentence.trim()) return null;
  const movementIds = Array.isArray(raw.movement_ids)
    ? [...new Set(raw.movement_ids.map(textValue).filter(Boolean))].sort()
    : [];
  return { id, count, sentence, ...(movementIds.length ? { movementIds } : {}) };
}

function rows(raw: unknown): readonly RescanChange[] {
  return Array.isArray(raw) ? raw.map(change).filter((row): row is RescanChange => row !== null) : [];
}

// What a pass reported, read into the shape a screen holds. The panel sentence
// is required — a report without one is a report this side would have to
// narrate, which is the thing the reviewed read model exists to prevent.
export function adaptRescan(raw: unknown): RescanReport | null {
  if (!isRecord(raw)) return null;
  const sentence = textValue(raw.sentence);
  if (!sentence.trim()) return null;
  return {
    sentence,
    changes: rows(raw.changes),
    standing: rows(raw.standing),
    linkCount: optionalNonNegativeInteger(raw.link_count) ?? 0,
  };
}
