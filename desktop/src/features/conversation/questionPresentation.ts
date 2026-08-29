import { UNSPOKEN_REPLY, channelPresentation } from "../../components/actionChannel";
import type { ActionResult, QuestionVerb, QuestionView } from "../../surface/types";

export type ReviewSelection =
  | { state: "empty"; reason: "queue_empty" | "no_selectable_identity" }
  | { state: "ready"; question: QuestionView }
  | { state: "missing"; requestedId: string }
  | { state: "conflicted_identity"; requestedId: string };

function identityCount(queue: readonly QuestionView[], id: string): number {
  return queue.filter((question) => question.id === id).length;
}

export function resolveReviewSelection(queue: readonly QuestionView[], requestedId: string): ReviewSelection {
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


export type OutcomePresentation = { title: string; detail: string };

// What each verb calls the thing it does, in the words its own controls used,
// so a title never names an act the person did not perform.
const verbWords: Record<QuestionVerb, { working: string; completed: string; refused: string; waiting: string }> = {
  answer: { working: "Reading your answer", completed: "Answered", refused: "Not answered", waiting: "Waiting on a document" },
  confirm: { working: "Applying your decision", completed: "Decision recorded", refused: "Decision not recorded", waiting: "Waiting" },
  decline: { working: "Setting this question aside", completed: "Set aside", refused: "Not set aside", waiting: "Nothing set aside yet" },
};

export function workingPresentation(verb: QuestionVerb): OutcomePresentation {
  return { title: verbWords[verb].working, detail: "Waiting for your vault to answer. Nothing else is being read while it does." };
}

// What one question verb came back as, in words. The vault's own sentence is
// used wherever the vault answered; the machine reason a refusal carries is
// not, and neither is a bridge error code's message. A channel that never
// reached an answer is said in the words every screen uses for it.
export function outcomePresentation(verb: QuestionVerb, result: ActionResult): OutcomePresentation {
  const words = verbWords[verb];
  if (result.state !== "settled") return channelPresentation(result);
  const { kind, message } = result.outcome;
  const detail = message || UNSPOKEN_REPLY;
  switch (kind) {
    case "completed": return { title: words.completed, detail };
    case "refused": return { title: words.refused, detail };
    case "waiting": return { title: words.waiting, detail };
    case "proposal": return { title: "Held for your confirmation", detail: result.outcome.proposalSummary || detail };
    case "set_aside": return { title: "Question set aside", detail };
    case "stale": return { title: "Out of date", detail };
  }
}
