import type { ActionOutcome, ActionOutcomeView, DocumentIngestAction, DocumentReading, DocumentTerminalState, QuestionReferences, QuestionSlot, QuestionQueueData, QuestionView, ReviewQuestionReferences } from "../types";
import { isRecord, optionalNonNegativeInteger, textValue } from "./primitives";
import { adaptReviewBinding } from "./review";

// The closed vocabulary an action answers in. A kind outside it is a reply
// this interface cannot read, and is refused rather than mapped to the
// nearest word.
const OUTCOME_KINDS: readonly ActionOutcome[] = ["completed", "refused", "proposal", "waiting", "stale", "set_aside"];
const DOCUMENT_TERMINAL_STATES: readonly DocumentTerminalState[] = ["captured_only", "read_yielded_nothing", "held", "posted", "duplicate"];
const DOCUMENT_INGEST_ACTIONS: readonly DocumentIngestAction[] = ["posted", "parked", "duplicate", "conflict", "gap", "identity", "awaiting"];
const DOCUMENT_READINGS: readonly DocumentReading[] = ["never_read", "read_yielded_nothing", "read"];

function closedWord<T extends string>(value: unknown, words: readonly T[]): T | undefined {
  const word = textValue(value);
  return words.find((candidate) => candidate === word);
}

const QUESTION_SCALAR_REFS = ["movement", "document", "doc_id", "account"] as const;
const QUESTION_LIST_REFS = ["movements", "candidates"] as const;

function questionRefs(item: Record<string, unknown>): { valid: boolean; refs?: QuestionReferences } {
  if (!("refs" in item)) return { valid: true };
  if (!isRecord(item.refs)) return { valid: false };
  const refs: QuestionReferences = {};
  for (const key of QUESTION_SCALAR_REFS) {
    if (!(key in item.refs)) continue;
    const value = item.refs[key];
    if (typeof value !== "string" || !value.trim()) return { valid: false };
    refs[key] = value;
  }
  for (const key of QUESTION_LIST_REFS) {
    if (!(key in item.refs)) continue;
    const value = item.refs[key];
    if (!Array.isArray(value) || value.some((id) => typeof id !== "string" || !id.trim())) return { valid: false };
    const ids = value as string[];
    if (new Set(ids).size !== ids.length) return { valid: false };
    refs[key] = [...ids];
  }
  const source = refs.movement;
  if (source && refs.movements && !refs.movements.includes(source)) return { valid: false };
  if (refs.candidates !== undefined && !source) return { valid: false };
  if (source && refs.candidates?.includes(source)) return { valid: false };
  // Only a transfer question requires the complete source/candidate pair.
  // Other question kinds legitimately carry one movement, many movements, or
  // neither, so the transfer invariant must not narrow their raw references.
  if (textValue(item.kind) === "transfer"
      && (!source || refs.candidates === undefined || refs.candidates.length === 0)) return { valid: false };
  return { valid: true, refs };
}

function normalizedReviewRefs(refs: QuestionReferences | undefined): ReviewQuestionReferences {
  return {
    movement: refs?.movement ?? "",
    movements: refs?.movements ?? [],
    candidates: refs?.candidates ?? [],
    document: refs?.document ?? "",
    documentId: refs?.doc_id ?? "",
    account: refs?.account ?? "",
  };
}

function sameReviewRefs(left: ReviewQuestionReferences, right: ReviewQuestionReferences): boolean {
  return left.movement === right.movement && left.document === right.document
    && left.documentId === right.documentId && left.account === right.account
    && left.movements.length === right.movements.length
    && left.movements.every((identity, index) => identity === right.movements[index])
    && left.candidates.length === right.candidates.length
    && left.candidates.every((identity, index) => identity === right.candidates[index]);
}

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
  const state = isRecord(raw.state) ? raw.state : null;
  const jobId = state ? textValue(state.job_id) : "";
  const proposalId = state ? textValue(state.proposal_id) : "";
  const proposalSummary = state ? textValue(state.summary) : "";
  const hasTerminalState = state !== null && "terminal_state" in state;
  const hasIngestAction = state !== null && "ingest_action" in state;
  // A document receipt is readable only when both the terminal state and its
  // pipeline action are present and belong to their closed vocabularies.
  if (hasTerminalState !== hasIngestAction) return null;
  const terminalState = hasTerminalState ? closedWord(state.terminal_state, DOCUMENT_TERMINAL_STATES) : undefined;
  const ingestAction = hasIngestAction ? closedWord(state.ingest_action, DOCUMENT_INGEST_ACTIONS) : undefined;
  if ((hasTerminalState && !terminalState) || (hasIngestAction && !ingestAction)) return null;
  const hasReading = state !== null && "reading" in state;
  const reading = hasReading ? closedWord(state.reading, DOCUMENT_READINGS) : undefined;
  if (hasReading && !reading) return null;
  return { kind, message, reason,
    ...(jobId ? { jobId } : {}),
    ...(proposalId ? { proposalId, proposalSummary } : {}),
    ...(terminalState && ingestAction ? { terminalState, ingestAction } : {}),
    ...(reading ? { reading } : {}) };
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

export function adaptQuestions(raw: unknown): QuestionQueueData | null {
  if (!isRecord(raw) || !Array.isArray(raw.questions) || optionalNonNegativeInteger(raw.total) === undefined) return null;
  if (raw.questions.some((item) => !isRecord(item) || typeof item.id !== "string" || !item.id.trim())) return null;
  let tail: QuestionQueueData["meta"]["tail"] = null;
  if ("tail" in raw) {
    if (!isRecord(raw.tail)) return null;
    const count = optionalNonNegativeInteger(raw.tail.count);
    if (count === undefined) return null;
    tail = { count, amount: textValue(raw.tail.amount) };
  }
  let pending: QuestionQueueData["meta"]["pending"] = null;
  if ("pending" in raw) {
    if (!isRecord(raw.pending)) return null;
    const count = optionalNonNegativeInteger(raw.pending.count);
    if (count === undefined) return null;
    pending = { count };
  }
  const suppliedQuestions = raw.questions.map((item) => isRecord(item) ? item : {});
  if (suppliedQuestions.map(questionRefs).some((parsed) => !parsed.valid)) return null;
  const identities = suppliedQuestions.map((item) => textValue(item.id));
  if (new Set(identities).size !== identities.length) return null;
  const rows = suppliedQuestions;
  const parsedRefs = rows.map(questionRefs);
  if (parsedRefs.some((parsed) => !parsed.valid)) return null;
  const bindings = rows.map((item) => "review_binding" in item ? adaptReviewBinding(item.review_binding) : undefined);
  if (bindings.some((binding, index) => binding === null
      || (binding !== undefined && (
        typeof rows[index].kind !== "string" || typeof rows[index].text !== "string" || typeof rows[index].why !== "string"
        || binding.questionId !== rows[index].id || binding.questionKind !== rows[index].kind
        || binding.label !== rows[index].text || binding.reason !== rows[index].why
        || !sameReviewRefs(binding.refs, normalizedReviewRefs(parsedRefs[index].refs))
      )))) return null;
  const queue: QuestionView[] = rows.map((item, index) => ({ id: textValue(item.id), label: textValue(item.text), detail: textValue(item.why), status: "", action: "", type: textValue(item.kind), evidence: textValue(item.why), state: "needs_input", outcome: null, disposition: null, count: optionalNonNegativeInteger(item.count), scope: textValue(item.scope) || undefined, currency: textValue(item.currency) || undefined, amount: textValue(item.amount) || undefined, slots: adaptSlots(item.slots), ...(parsedRefs[index].refs === undefined ? {} : { refs: parsedRefs[index].refs }), ...(bindings[index] === undefined ? {} : { reviewBinding: bindings[index] as NonNullable<typeof bindings[number]> }) }));
  const total = optionalNonNegativeInteger(raw.total) as number;
  if (total < queue.length || (tail !== null && tail.count !== total - queue.length)) return null;
  return { queue, count: total, meta: { total, tail, pending, invite: textValue(raw.invite), answeredByDocument: textValue(raw.answered_by_document) } };
}
