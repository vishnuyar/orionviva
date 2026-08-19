import type { ReviewData, ReviewView } from "../types";
import { isRecord, optionalNonNegativeInteger, textValue, uniqueRecordsById } from "./primitives";

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
  const queue: ReviewView[] = rows.map((item) => ({ id: textValue(item.id), label: textValue(item.text), detail: textValue(item.why), status: "Read only", action: "", type: textValue(item.kind), evidence: textValue(item.why), state: "needs_input", outcome: null, disposition: null, readOnly: true, count: optionalNonNegativeInteger(item.count), scope: textValue(item.scope) || undefined, currency: textValue(item.currency) || undefined, amount: textValue(item.amount) || undefined }));
  const total = optionalNonNegativeInteger(raw.total) as number;
  return { queue, count: total, meta: { total, tail, pending, invite: textValue(raw.invite), answeredByDocument: textValue(raw.answered_by_document) } };
}
