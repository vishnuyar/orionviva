import type { ActionOutcome, ActionOutcomeView, QuestionSlot, ReviewData, ReviewView } from "../types";
import { isRecord, optionalNonNegativeInteger, textValue, uniqueRecordsById } from "./primitives";

// The closed vocabulary an action answers in. A kind outside it is a reply
// this interface cannot read, and is refused rather than mapped to the
// nearest word.
const OUTCOME_KINDS: readonly ActionOutcome[] = ["completed", "refused", "proposal", "waiting", "stale", "set_aside"];

export function adaptActionOutcome(raw: unknown): ActionOutcomeView | null {
  if (!isRecord(raw)) return null;
  const kind = OUTCOME_KINDS.find((candidate) => candidate === raw.kind);
  if (!kind) return null;
  const message = textValue(raw.message);
  const reason = textValue(raw.reason);
  // A refusal without its machine reason is the one shape the contract
  // forbids, so it is read as no outcome at all.
  if (kind === "refused" && !reason) return null;
  // The identity of the work this outcome came out of, where the reply named
  // one. It sits under `state` because that is where a reply puts what it is
  // reporting about, and it is read by name rather than by position.
  const jobId = isRecord(raw.state) ? textValue(raw.state.job_id) : "";
  return jobId ? { kind, message, reason, jobId } : { kind, message, reason };
}

// What a question needs back, as the queue declared it. `wants` is the queue's
// own sentence and `choices` is the closed vocabulary an answer must land in;
// neither is composed here, because a screen writing either would be writing
// the second half of a contract whose first half lives in the engine.
//
// A slot with no sentence is dropped. It would render as a field asking for
// something nobody said what it was.
function adaptSlots(raw: unknown): readonly QuestionSlot[] {
  if (!Array.isArray(raw)) return [];
  const found: (QuestionSlot | null)[] = raw.map((item) => {
    if (!isRecord(item)) return null;
    const name = textValue(item.name);
    const wants = textValue(item.wants);
    if (!name || !wants.trim()) return null;
    return {
      name,
      type: textValue(item.type),
      required: item.required === true,
      wants,
      choices: Array.isArray(item.choices) ? item.choices.map(textValue).filter((choice) => choice) : [],
    };
  });
  return found.filter((slot): slot is QuestionSlot => slot !== null);
}

export function adaptReview(raw: unknown): ReviewData | null {
  if (!isRecord(raw) || !Array.isArray(raw.questions) || optionalNonNegativeInteger(raw.total) === undefined) return null;
  if (raw.questions.some((item) => !isRecord(item) || !textValue(item.id))) return null;
  let tail: ReviewData["meta"]["tail"] = null;
  if ("tail" in raw) {
    if (!isRecord(raw.tail)) return null;
    const count = optionalNonNegativeInteger(raw.tail.count);
    if (count === undefined) return null;
    tail = { count, amount: textValue(raw.tail.amount) };
  }
  let pending: ReviewData["meta"]["pending"] = null;
  if ("pending" in raw) {
    if (!isRecord(raw.pending)) return null;
    const count = optionalNonNegativeInteger(raw.pending.count);
    if (count === undefined) return null;
    pending = { count };
  }
  const rows = uniqueRecordsById(raw.questions);
  const queue: ReviewView[] = rows.map((item) => ({ id: textValue(item.id), label: textValue(item.text), detail: textValue(item.why), status: "", action: "", type: textValue(item.kind), evidence: textValue(item.why), state: "needs_input", outcome: null, disposition: null, count: optionalNonNegativeInteger(item.count), scope: textValue(item.scope) || undefined, currency: textValue(item.currency) || undefined, amount: textValue(item.amount) || undefined, slots: adaptSlots(item.slots) }));
  const total = optionalNonNegativeInteger(raw.total) as number;
  return { queue, count: total, meta: { total, tail, pending, invite: textValue(raw.invite), answeredByDocument: textValue(raw.answered_by_document) } };
}
