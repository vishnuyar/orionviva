import type { ActivityData, MovementView } from "../types";
import { booleanValue, isRecord, optionalNonNegativeInteger, textValue } from "./primitives";

// The two words a direction can be, closed on both sides. A word outside the
// set is a movement this interface has not been taught to render, and the row
// is dropped rather than shown under the nearest one — a purchase reported as
// money arriving is exactly the defect that kept this read off a screen.
const DIRECTIONS = ["in", "out"] as const;

function movement(raw: unknown): MovementView | null {
  if (!isRecord(raw)) return null;
  const id = textValue(raw.id);
  const direction = DIRECTIONS.find((candidate) => candidate === raw.direction);
  if (!id || !direction) return null;
  return {
    id,
    date: textValue(raw.date),
    description: textValue(raw.description),
    account: textValue(raw.account),
    direction,
    exactValue: textValue(raw.exact_value),
    currency: textValue(raw.currency),
    display: textValue(raw.display),
    nature: textValue(raw.nature),
    sentence: textValue(raw.sentence),
    decidedBy: textValue(raw.decided_by),
    provisional: booleanValue(raw.provisional) === true,
    linked: booleanValue(raw.linked) === true,
  };
}

// What moved, read into the shape a screen holds. The panel's own sentence is
// required: a read with none is one this side would have to narrate, and
// narrating what a person's money did is the claim this interface must not
// make.
export function adaptActivity(raw: unknown): ActivityData | null {
  if (!isRecord(raw)) return null;
  const sentence = textValue(raw.sentence);
  if (!sentence.trim()) return null;
  const rows = Array.isArray(raw.items) ? raw.items : [];
  return {
    sentence,
    movements: rows.map(movement).filter((row): row is MovementView => row !== null),
    beyond: { count: (isRecord(raw.beyond) ? optionalNonNegativeInteger(raw.beyond.count) : undefined) ?? 0 },
  };
}
