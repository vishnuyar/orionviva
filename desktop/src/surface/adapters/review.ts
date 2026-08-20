import type { ActionOutcome, ActionOutcomeView, ReviewData, ReviewView } from "../types";
import { isRecord, optionalNonNegativeInteger, textValue, uniqueRecordsById } from "./primitives";

// The closed vocabulary an action answers in. A kind outside it is a reply
// this interface cannot read, and is refused rather than mapped to the
// nearest word.
const OUTCOME_KINDS: readonly ActionOutcome[] = ["completed", "refused", "proposal", "waiting", "stale"];

export function adaptActionOutcome(raw: unknown): ActionOutcomeView | null {
  if (!isRecord(raw)) return null;
  const kind = OUTCOME_KINDS.find((candidate) => candidate === raw.kind);
  if (!kind) return null;
  const message = textValue(raw.message);
  const reason = textValue(raw.reason);
  // A refusal without its machine reason is the one shape the contract
  // forbids, so it is read as no outcome at all.
  if (kind === "refused" && !reason) return null;
  return { kind, message, reason };
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
  const queue: ReviewView[] = rows.map((item) => ({ id: textValue(item.id), label: textValue(item.text), detail: textValue(item.why), status: "", action: "", type: textValue(item.kind), evidence: textValue(item.why), state: "needs_input", outcome: null, disposition: null, count: optionalNonNegativeInteger(item.count), scope: textValue(item.scope) || undefined, currency: textValue(item.currency) || undefined, amount: textValue(item.amount) || undefined }));
  const total = optionalNonNegativeInteger(raw.total) as number;
  return { queue, count: total, meta: { total, tail, pending, invite: textValue(raw.invite), answeredByDocument: textValue(raw.answered_by_document) } };
}
