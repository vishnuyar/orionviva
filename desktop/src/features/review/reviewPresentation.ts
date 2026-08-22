import { UNSPOKEN_REPLY, channelPresentation } from "../../components/actionChannel";
import type { ActionResult, ReviewSampleAnatomy, ReviewVerb, ReviewView } from "../../surface/types";

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
    case "answer": return { state: "ready", anatomy: "answer", title: "Answer boundary", detail: "This fictional question wants a sentence back. Answering is not connected in this version, here or in a private vault, so nothing can be read into a slot, recorded, or sent." };
    case "decline": return { state: "ready", anatomy: "decline", title: "Set-aside boundary", detail: "The sample vault takes a setting-aside and refuses it. Nothing here is suppressed, deferred, or recorded." };
    case "proposal": return { state: "ready", anatomy: "proposal", title: "Proposal — not applied", detail: "This fictional proposal describes a possible value. It remains unapplied and would require a separate explicit confirmation." };
    case "confirmation": return { state: "ready", anatomy: "confirmation", title: "Confirmation required", detail: "This is confirmation anatomy only. No yes is accepted and nothing is applied." };
    default:
      return value?.trim()
        ? { state: "unrecognized", title: "Sample action type unavailable", detail: "This fictional sample uses an action type this preview does not recognize. Nothing can be submitted, recorded, sent, or applied." }
        : { state: "missing", title: "Sample anatomy unavailable", detail: "This fictional sample does not supply action anatomy. Nothing can be submitted, recorded, sent, or applied." };
  }
}

export type OutcomePresentation = { title: string; detail: string };

// What each verb calls the thing it does, in the words its own controls used,
// so a title never names an act the person did not perform.
const verbWords: Record<ReviewVerb, { working: string; completed: string; refused: string; waiting: string }> = {
  answer: { working: "Reading your answer", completed: "Answered", refused: "Not answered", waiting: "Waiting on a document" },
  decline: { working: "Setting this question aside", completed: "Set aside", refused: "Not set aside", waiting: "Nothing set aside yet" },
};

export function workingPresentation(verb: ReviewVerb): OutcomePresentation {
  return { title: verbWords[verb].working, detail: "Waiting for your vault to answer. Nothing else is being read while it does." };
}

// What one review verb came back as, in words. The vault's own sentence is
// used wherever the vault answered; the machine reason a refusal carries is
// not, and neither is a bridge error code's message. A channel that never
// reached an answer is said in the words every screen uses for it.
export function outcomePresentation(verb: ReviewVerb, result: ActionResult): OutcomePresentation {
  const words = verbWords[verb];
  if (result.state !== "settled") return channelPresentation(result);
  const { kind, message } = result.outcome;
  const detail = message || UNSPOKEN_REPLY;
  switch (kind) {
    case "completed": return { title: words.completed, detail };
    case "refused": return { title: words.refused, detail };
    case "waiting": return { title: words.waiting, detail };
    case "proposal": return { title: "Held for a confirmation this screen cannot give", detail };
    case "stale": return { title: "Out of date", detail };
  }
}
