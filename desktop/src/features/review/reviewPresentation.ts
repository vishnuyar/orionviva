import type { ReviewSampleAnatomy, ReviewView } from "../../surface/types";

export type ReviewSelection =
  | { state: "empty"; reason: "queue_empty" | "no_selectable_identity" }
  | { state: "ready"; question: ReviewView }
  | { state: "missing"; requestedId: string }
  | { state: "conflicted_identity"; requestedId: string };

function identityCount(queue: readonly ReviewView[], id: string): number {
  return queue.filter((question) => question.id === id).length;
}

export function resolveReviewSelection(queue: readonly ReviewView[], requestedId: string): ReviewSelection {
  if (!requestedId.trim()) {
    if (!queue.length) return { state: "empty", reason: "queue_empty" };
    const firstUnique = queue.find((question) => question.id.trim() && identityCount(queue, question.id) === 1);
    return firstUnique ? { state: "ready", question: firstUnique } : { state: "empty", reason: "no_selectable_identity" };
  }
  const matches = queue.filter((question) => question.id === requestedId);
  if (!matches.length) return { state: "missing", requestedId };
  if (matches.length > 1) return { state: "conflicted_identity", requestedId };
  return { state: "ready", question: matches[0] };
}

export type AnatomyPresentation =
  | { state: "ready"; anatomy: ReviewSampleAnatomy; title: string; detail: string }
  | { state: "missing"; title: "Sample anatomy unavailable"; detail: string }
  | { state: "unrecognized"; title: "Sample action type unavailable"; detail: string };

export function anatomyPresentation(value: string | null | undefined): AnatomyPresentation {
  switch (value) {
    case "answer": return { state: "ready", anatomy: "answer", title: "Answer boundary", detail: "Answer entry is unavailable in this preview. This example does not collect or record an answer." };
    case "decline": return { state: "ready", anatomy: "decline", title: "Decline / set aside boundary", detail: "Decline and set aside are unavailable in this preview. This example does not suppress, defer, or record the question." };
    case "proposal": return { state: "ready", anatomy: "proposal", title: "Proposal — not applied", detail: "This fictional proposal describes a possible value. It remains unapplied and would require a separate explicit confirmation." };
    case "confirmation": return { state: "ready", anatomy: "confirmation", title: "Confirmation required", detail: "This is confirmation anatomy only. No yes is accepted and nothing is applied." };
    default:
      return value?.trim()
        ? { state: "unrecognized", title: "Sample action type unavailable", detail: "This fictional sample uses an action type this preview does not recognize. Nothing can be submitted, recorded, sent, or applied." }
        : { state: "missing", title: "Sample anatomy unavailable", detail: "This fictional sample does not supply action anatomy. Nothing can be submitted, recorded, sent, or applied." };
  }
}
