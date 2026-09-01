import type { ActionOutcome, ConversationData, ConversationGoalDraft, ConversationProposal, ConversationTurn, EvidenceLink, EvidenceRelation, PlanVerb, SpokenTurn, TurnFigure, TurnView } from "../types";
import { booleanValue, isRecord, textValue } from "./primitives";
import { adaptPlanDraftView } from "./plans";
import { adaptQuestions } from "./questions";

const OUTCOMES: readonly ActionOutcome[] = ["completed", "refused", "proposal", "waiting", "stale", "set_aside"];
const KINDS: readonly ConversationTurn["kind"][] = ["ask", "answer", "decline", "confirm"];
const RELATIONS: readonly EvidenceRelation[] = ["attests", "corroborates", "same_period", "same_account", "settles_question"];
const PLAN_VERBS: readonly PlanVerb[] = ["create", "change_terms", "reserve", "release", "pause", "resume", "set_aside"];

function goalDraft(raw: unknown): ConversationGoalDraft | null {
  if (!isRecord(raw) || !["ready", "needs_input", "refused"].includes(textValue(raw.kind))) return null;
  const verb = PLAN_VERBS.find((candidate) => candidate === raw.verb);
  if (!verb) return null;
  return { kind: raw.kind as ConversationGoalDraft["kind"], message: textValue(raw.message), reason: textValue(raw.reason), verb, draft: adaptPlanDraftView(raw.draft), reviewInPlans: booleanValue(raw.review_in_plans) === true };
}

function evidenceLink(raw: unknown): EvidenceLink | null {
  if (!isRecord(raw)) return null;
  const targetDocumentId = textValue(raw.document_id);
  const relation = RELATIONS.find((candidate) => candidate === raw.relation);
  if (!targetDocumentId || !relation) return null;
  return { targetDocumentId, label: textValue(raw.label), relation, page: textValue(raw.page) };
}

// One figure the sentence stated. A figure with no identity is dropped: it
// could not be tied back to anything, and a row that cannot be followed is a
// claim with no route out of it.
function figure(raw: unknown): TurnFigure | null {
  if (!isRecord(raw)) return null;
  const id = textValue(raw.id);
  if (!id) return null;
  return {
    id,
    evidenceId: textValue(raw.evidence_id),
    written: textValue(raw.written),
    grade: textValue(raw.grade),
    what: textValue(raw.what),
    recordIds: Array.isArray(raw.record_ids) ? raw.record_ids.map(textValue).filter((record) => record) : [],
    evidenceLinks: (Array.isArray(raw.evidence_links) ? raw.evidence_links : []).map(evidenceLink).filter((link): link is EvidenceLink => link !== null),
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
  const statuses = ["answered", "partial", "needs_clarification", "needs_assumption", "missing_data", "capability_gap", "outside_domain", "failed"] as const;
  const status = statuses.find((candidate) => candidate === raw.status)
    ?? (booleanValue(raw.answered) === true ? "answered" : "failed");
  const options = (Array.isArray(raw.options) ? raw.options : []).flatMap((item) => {
    if (!isRecord(item)) return [];
    const id = textValue(item.id), label = textValue(item.label);
    return id && label ? [{ id, label }] : [];
  });
  const missing = (Array.isArray(raw.missing) ? raw.missing : []).flatMap((item) => {
    if (!isRecord(item)) return [];
    const tag = textValue(item.tag) || textValue(item.reason);
    const label = textValue(item.label) || textValue(item.source);
    const question = textValue(item.question);
    return tag || label || question ? [{ tag, label, question }] : [];
  });
  return {
    question: textValue(raw.question),
    text,
    answered: booleanValue(raw.answered) === true,
    status,
    outcomeTag: textValue(raw.outcome_tag),
    refusal,
    grade: textValue(raw.grade),
    gradeSentence: textValue(raw.grade_sentence),
    figures: (Array.isArray(raw.figures) ? raw.figures : []).map(figure).filter((row): row is TurnFigure => row !== null),
    options,
    missing,
    spoken: spoken(raw.spoken),
    goalDraft: goalDraft(raw.goal_draft),
  };
}

function proposal(raw: unknown): ConversationProposal | null {
  if (!isRecord(raw)) return null;
  const id = textValue(raw.id);
  if (!id) return null;
  return { id, summary: textValue(raw.summary), status: textValue(raw.status), outcome: textValue(raw.outcome), message: textValue(raw.message), reason: textValue(raw.reason) };
}

function timelineTurn(raw: unknown): ConversationTurn | null {
  if (!isRecord(raw)) return null;
  const id = textValue(raw.id);
  const kind = KINDS.find((candidate) => candidate === raw.kind);
  const outcome = OUTCOMES.find((candidate) => candidate === raw.outcome);
  if (!id || !kind || !outcome) return null;
  return {
    id,
    kind,
    occurredAt: textValue(raw.occurred_at),
    prompt: textValue(raw.prompt),
    said: textValue(raw.said),
    questionId: textValue(raw.question_id),
    outcome,
    message: textValue(raw.message),
    reason: textValue(raw.reason),
    answer: adaptTurn(raw.answer),
    proposal: proposal(raw.proposal),
  };
}

export function adaptConversation(raw: unknown): ConversationData | null {
  if (!isRecord(raw) || !Array.isArray(raw.turns)) return null;
  const questions = adaptQuestions(raw);
  if (!questions) return null;
  const turns = raw.turns.map(timelineTurn);
  if (turns.some((turn) => turn === null)) return null;
  return { turns: turns as ConversationTurn[], questions };
}
