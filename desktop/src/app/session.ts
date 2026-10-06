import type { SourceDescription, SurfaceSource } from "../surface/sources";
import type { ActionResult, ActivityActionResult, ActivityCorrectionState, ActivityCorrectionVerb, ActivityData, CancelActionState, CaptureActionState, Destination, FeatureResult, JobView, Notice, RescanActionState, RescanReport, QuestionActionState, QuestionQueueData, QuestionReferences, QuestionVerb, AskActionState, ReviewQuestionBinding, ReviewQuestionReferences, ReviewTarget, SettingsActionState, TrustActionState, SettingsProposal, SettingsView, TurnView, SurfaceSnapshot, TransferActionState, TransferVerb } from "../surface/types";
import { retainSelection } from "./selection";

export type SessionPhase = "opening" | "reading" | "settled";
export type LazyDestination = "documents" | "review" | "trust" | "activity" | "plans";
export type DestinationReadState = "idle" | "loading" | "retrying" | "absent" | "ready" | "partial" | "needs_input" | "unavailable" | "failed";
function emptyDestinationReads(): Record<LazyDestination, DestinationReadState> {
  return { documents: "idle", review: "idle", trust: "idle", activity: "idle", plans: "idle" };
}
export type SurfaceSession = {
  phase: SessionPhase;
  requestId: number;
  // No vault open yet. Every screen reads its own absent state from the
  // snapshot; this says which verbs exist, and before a vault there are none.
  source: SurfaceSource | null;
  readRevision: string;
  priorityLifecycle: string;
  priorityFreshness: "loading" | "current" | "stale" | "unavailable";
  priorityRetryable: boolean;
  priorityRetrying: boolean;
  priorityRetryOutcome: "succeeded" | "failed" | null;
  snapshot: SurfaceSnapshot;
  destination: Destination;
  destinationReads: Record<LazyDestination, DestinationReadState>;
  selectedDocument: string;
  selectedQueue: string;
  selectedAccount: string;
  selectedPrompt: string;
  notice: Notice | null;
  questionAction: QuestionActionState;
  activityAction: ActivityCorrectionState;
  captureAction: CaptureActionState;
  cancelAction: CancelActionState;
  // What the sidecar last said it was doing, newest last. Every row here was
  // written by the sidecar — a progress frame it produced, or the registry it
  // holds — and nothing on this side counts a step or names one.
  //
  // Operational job rows live beside the financial snapshot. Registry reads
  // restore bounded receipts; progress frames replace them during this process.
  jobs: readonly JobView[];
  jobStatus: "available" | "unavailable";
  jobCheck: "idle" | "checking" | "failed" | "succeeded";
  // Engine build identity and registry standing, requested once per source.
  description: SourceDescription;
  // The last export or restore receipt persists across destination navigation.
  transferAction: TransferActionState;
  // The last rescan receipt persists across destination navigation.
  rescanAction: RescanActionState;
  // Current settings and the proposal retained in the session across panel renders.
  settings: FeatureResult<SettingsView>;
  settingsAction: SettingsActionState;
  // The requested Viva turn, retained in the session when its drawer closes.
  askAction: AskActionState;
  // The last unattended-run or diagnostic receipt persists across destination navigation.
  trustAction: TrustActionState;
};

export type SessionAction =
  | { type: "opening"; requestId: number }
  | { type: "reading"; requestId: number; source: SurfaceSource; snapshot: SurfaceSnapshot }
  | { type: "loaded"; requestId: number; source?: SurfaceSource; snapshot: SurfaceSnapshot; jobs?: readonly JobView[]; jobStatus?: "available" | "unavailable" }
  | { type: "priority-loaded"; requestId: number; source: SurfaceSource; overview: SurfaceSnapshot["overview"]; disclosure: SurfaceSnapshot["disclosure"]; revision: string; freshness: "current" | "stale" | "unavailable"; lifecycle: string; retryable: boolean }
  | { type: "priority-retrying"; requestId: number }
  | { type: "priority-retry-failed"; requestId: number }
  | { type: "priority-retry-succeeded"; requestId: number }
  | { type: "secondary-loaded"; requestId: number; snapshot: SurfaceSnapshot }
  | { type: "destination-loading"; requestId: number; destination: LazyDestination }
  | { type: "destination-retrying"; requestId: number; destination: LazyDestination }
  | { type: "destination-failed"; requestId: number; destination: LazyDestination; snapshot?: Partial<SurfaceSnapshot> }
  | { type: "destination-loaded"; requestId: number; snapshot: Partial<SurfaceSnapshot>; destination?: LazyDestination }
  | { type: "mutation-loaded"; requestId: number; snapshot: SurfaceSnapshot; revision?: string; jobs?: readonly JobView[]; jobStatus?: "available" | "unavailable" }
  | { type: "mutation-refresh-failed"; requestId: number }
  | { type: "open-failed"; requestId: number; said: string }
  | { type: "remembered-open-finished"; requestId: number; said?: string }
  | { type: "load-failed"; requestId: number }
  | { type: "reset"; requestId: number }
  | { type: "navigate"; destination: Destination }
  | { type: "select-document"; id: string }
  | { type: "select-queue"; id: string }
  | { type: "select-account"; id: string }
  | { type: "select-prompt"; id: string }
  | { type: "question-acting"; requestId: number; questionId: string; verb: QuestionVerb }
  | { type: "question-acted"; requestId: number; questionId: string; verb: QuestionVerb; result: ActionResult; authoritative: boolean; resolved: boolean }
  | { type: "activity-correcting"; requestId: number; movementId: string; movementIds?: readonly string[]; verb: ActivityCorrectionVerb }
  | { type: "activity-outcome"; requestId: number; movementId: string; movementIds?: readonly string[]; verb: ActivityCorrectionVerb; result: ActivityActionResult }
  | { type: "activity-refreshed"; requestId: number; movementId: string; movementIds?: readonly string[]; verb: ActivityCorrectionVerb; result: ActivityActionResult; snapshot: SurfaceSnapshot; revision?: string; jobs?: readonly JobView[] }
  | { type: "activity-refresh-failed"; requestId: number; movementId: string; movementIds?: readonly string[]; verb: ActivityCorrectionVerb; result: ActivityActionResult }
  | { type: "activity-page-loaded"; requestId: number; activity: FeatureResult<ActivityData> }
  | { type: "activity-page-loading"; requestId: number }
  | { type: "activity-page-failed"; requestId: number }
  | { type: "activity-first-page-loaded"; requestId: number; activity: FeatureResult<ActivityData> }
  | { type: "capturing"; requestId: number }
  | { type: "captured"; requestId: number; result: ActionResult }
  | { type: "job-progress"; requestId: number; job: JobView }
  | { type: "jobs-read"; requestId: number; jobs: readonly JobView[] }
  | { type: "jobs-unavailable"; requestId: number }
  | { type: "jobs-checking"; requestId: number }
  | { type: "described"; requestId: number; description: SourceDescription }
  | { type: "trust-working"; requestId: number }
  | { type: "trust-settled"; requestId: number; result: ActionResult }
  | { type: "asking"; requestId: number; question: string }
  | { type: "asked"; requestId: number; question: string; result: ActionResult; turn: TurnView | null; authoritative: boolean }
  | { type: "settings-read"; settings: FeatureResult<SettingsView> }
  | { type: "settings-working" }
  | { type: "settings-proposed"; proposal: SettingsProposal }
  | { type: "settings-settled"; result: ActionResult; settings: FeatureResult<SettingsView> }
  | { type: "rescanning"; requestId: number }
  | { type: "rescanned"; requestId: number; result: ActionResult; report: RescanReport | null }
  | { type: "transferring"; requestId: number; verb: TransferVerb }
  | { type: "transferred"; requestId: number; verb: TransferVerb; result: ActionResult }
  | { type: "cancelling"; requestId: number; jobId: string }
  | { type: "cancelled"; requestId: number; jobId: string; result: ActionResult; jobs: readonly JobView[] }
  | { type: "notice"; notice: Notice | null };

function dataOf<T>(result: FeatureResult<T>): T | null {
  return result.state === "ready" || result.state === "partial" || result.state === "needs_input" ? result.data : null;
}

function destinationOutcome(snapshot: SurfaceSnapshot, destination: LazyDestination): DestinationReadState {
  const states = destination === "review"
    ? [snapshot.review?.state ?? "absent", snapshot.conversation?.state ?? "absent"]
    : [snapshot[destination]?.state ?? "absent"];
  for (const state of ["failed", "unavailable", "needs_input", "partial", "absent"] as const) {
    if (states.includes(state)) return state;
  }
  return "ready";
}

function selectedIds(snapshot: SurfaceSnapshot) {
  const overview = dataOf(snapshot.overview);
  const documents = dataOf(snapshot.documents);
  const conversation = dataOf(snapshot.conversation);
  return {
    documents: documents?.documents?.map((item) => item.id) ?? [],
    queue: conversation?.questions?.queue?.map((item) => item.id) ?? [],
    accounts: overview?.accounts?.map((item) => item.id) ?? [],
    prompts: [],
  };
}

function hasReadFailure(snapshot: SurfaceSnapshot) {
  return [snapshot.overview, snapshot.documents, snapshot.activity, snapshot.conversation, snapshot.review, snapshot.plans, snapshot.trust].some((result) => result?.state === "failed");
}

function everyVaultSurfaceFailed(snapshot: SurfaceSnapshot) {
  return [snapshot.overview, snapshot.documents, snapshot.activity, snapshot.conversation, snapshot.review, snapshot.plans, snapshot.trust]
    .every((result) => result?.state === "failed");
}

function dataBearing<T>(result: FeatureResult<T> | undefined): result is Extract<FeatureResult<T>, { data: T }> {
  return result?.state === "ready" || result?.state === "partial" || result?.state === "needs_input";
}

function invalidateActivity(result: FeatureResult<ActivityData>): FeatureResult<ActivityData> {
  return dataBearing(result) && result.data.page ? { ...result, data: { ...result.data,
    beyond: { count: result.data.page.remainingCount }, page: undefined,
    loadingMore: false, continuationFailed: false, continuationInvalidated: true } } : result;
}

function invalidateActivitySnapshot(snapshot: SurfaceSnapshot): SurfaceSnapshot {
  const activity = invalidateActivity(snapshot.activity);
  return activity === snapshot.activity ? snapshot : { ...snapshot, activity };
}



function sameReviewRefs(left: ReviewQuestionReferences, right: ReviewQuestionReferences): boolean {
  return left.movement === right.movement && left.document === right.document
    && left.documentId === right.documentId && left.account === right.account
    && left.movements.length === right.movements.length
    && left.movements.every((identity, index) => identity === right.movements[index])
    && left.candidates.length === right.candidates.length
    && left.candidates.every((identity, index) => identity === right.candidates[index]);
}

function sameReviewTarget(left: ReviewTarget, right: ReviewTarget): boolean {
  if (left.kind !== right.kind || left.questionId !== right.questionId) return false;
  if (left.kind === "conversation" || right.kind === "conversation") return left.kind === "conversation" && right.kind === "conversation" && left.disclosure === right.disclosure;
  return left.accountId === right.accountId
    && left.requestedMovementId === right.requestedMovementId
    && left.canonicalMovementId === right.canonicalMovementId
    && left.memberMovementIds.length === right.memberMovementIds.length
    && left.memberMovementIds.every((identity, index) => identity === right.memberMovementIds[index]);
}

function sameReviewBinding(left: ReviewQuestionBinding, right: ReviewQuestionBinding): boolean {
  return left.itemId === right.itemId && left.questionId === right.questionId
    && left.questionKind === right.questionKind && left.label === right.label
    && left.reason === right.reason && left.status === right.status
    && left.primaryAction === right.primaryAction
    && left.allowedActions.length === right.allowedActions.length
    && left.allowedActions.every((action, index) => action === right.allowedActions[index])
    && sameReviewRefs(left.refs, right.refs) && sameReviewTarget(left.target, right.target);
}

function normalizedQuestionRefs(question: { refs?: QuestionReferences }): ReviewQuestionReferences {
  return {
    movement: question.refs?.movement ?? "",
    movements: question.refs?.movements ?? [],
    candidates: question.refs?.candidates ?? [],
    document: question.refs?.document ?? "",
    documentId: question.refs?.doc_id ?? "",
    account: question.refs?.account ?? "",
  };
}

function reviewConversationSemanticallyMatch(snapshot: SurfaceSnapshot): boolean {
  if (!dataBearing(snapshot.review) || !dataBearing(snapshot.conversation)) return false;
  const review = snapshot.review.data;
  const conversation = snapshot.conversation.data.questions;
  const reviewIds = review.groups.flatMap((group) => group.items.map((item) => item.target.questionId));
  const conversationIds = conversation.queue.map((question) => question.id);
  if (reviewIds.some((id) => !id.trim()) || conversationIds.some((id) => !id.trim())) return false;
  if (new Set(reviewIds).size !== reviewIds.length || new Set(conversationIds).size !== conversationIds.length) return false;
  if (review.actionableCount !== conversation.meta.total
      || review.shownCount !== reviewIds.length
      || review.shownCount !== conversationIds.length
      || conversation.count !== conversation.meta.total
      || (conversation.meta.tail !== null && conversation.meta.tail.count !== review.remainingCount)) return false;
  const items = review.groups.flatMap((group) => group.items);
  return reviewIds.every((id, index) => id === conversationIds[index])
    && items.every((item, index) => {
      const question = conversation.queue[index];
      const binding = question?.reviewBinding;
      return Boolean(binding
        && item.id === `question:${question.id}`
        && item.label === question.label && item.reason === question.detail
        && item.binding.questionKind === question.type
        && item.binding.itemId === item.id && item.binding.questionId === question.id
        && item.binding.label === item.label && item.binding.reason === item.reason
        && item.binding.status === item.status && item.binding.primaryAction === item.primaryAction
        && item.binding.allowedActions.length === item.allowedActions.length
        && item.binding.allowedActions.every((action, actionIndex) => action === item.allowedActions[actionIndex])
        && sameReviewTarget(item.binding.target, item.target)
        && binding.label === question.label && binding.reason === question.detail
        && binding.questionKind === question.type
        && sameReviewRefs(binding.refs, normalizedQuestionRefs(question))
        && sameReviewBinding(item.binding, binding));
    });
}

// Review and Conversation replace the prior pair only when both reads are present
// and semantically match. Initial reads apply the same paired validation.
export function hasAuthoritativeReviewConversationPair(snapshot: SurfaceSnapshot | null): snapshot is SurfaceSnapshot {
  return Boolean(snapshot && !hasReadFailure(snapshot) && reviewConversationSemanticallyMatch(snapshot));
}

// The session before either a sample or private vault is explicitly opened.
export function initialSession(): SurfaceSession {
  return {
    phase: "settled",
    requestId: 0,
    source: null,
    readRevision: "",
    priorityLifecycle: "",
    priorityFreshness: "unavailable",
    priorityRetryable: false,
    priorityRetrying: false,
    priorityRetryOutcome: null,
    snapshot: unopenedSnapshot(),
    destination: "overview",
    destinationReads: emptyDestinationReads(),
    selectedDocument: "",
    selectedQueue: "",
    selectedAccount: "",
    selectedPrompt: "",
    notice: null,
    questionAction: { state: "idle" },
    activityAction: { state: "idle" },
    captureAction: { state: "idle" },
    cancelAction: { state: "idle" },
    jobs: [],
    jobStatus: "available",
    jobCheck: "idle",
    description: unasked(),
    transferAction: { state: "idle" },
    rescanAction: { state: "idle" },
    settings: { state: "absent", reason: "not_asked" },
    settingsAction: { state: "idle" },
    askAction: { state: "idle" },
    trustAction: { state: "idle" },
  };
}

// Initial engine state explicitly records that identity and registry have not been read.
export function unasked(): SourceDescription {
  return { identity: { state: "absent", reason: "not_asked" }, registry: { state: "absent", reason: "not_asked" }, lifecycle: { state: "absent", reason: "not_asked" } };
}

// Replace or append a job by identity. Progress frames preserve the steps supplied
// by an earlier registry read.
function withJob(jobs: readonly JobView[], job: JobView): readonly JobView[] {
  const held = jobs.find((candidate) => candidate.jobId === job.jobId);
  const merged = held && !job.steps.length ? { ...job, steps: held.steps } : job;
  return held ? jobs.map((candidate) => (candidate.jobId === job.jobId ? merged : candidate)) : [...jobs, merged];
}

// Absent and loading snapshots distinguish unopened vaults from pending reads.
export function unopenedSnapshot(): SurfaceSnapshot {
  return {
    disclosure: {
      title: "No vault open",
      subtitle: "Nothing has been read",
      detail: "Open your own vault, or open the sample vault to see what one looks like when it is full.",
    },
    overview: { state: "absent", reason: "no_vault" },
    documents: { state: "absent", reason: "no_vault" },
    activity: { state: "absent", reason: "no_vault" },
    conversation: { state: "absent", reason: "no_vault" },
    review: { state: "absent", reason: "no_vault" },
    plans: { state: "absent", reason: "no_vault" },
    trust: { state: "absent", reason: "no_vault" },
  };
}

export function liveReadingSnapshot(): SurfaceSnapshot {
  return {
    disclosure: {
      title: "Private vault",
      subtitle: "Opened on this device",
      detail: "The surfaces below are read from this vault. Features that are not connected stay hidden or say so.",
    },
    overview: { state: "absent", reason: "reading" },
    documents: { state: "absent", reason: "reading" },
    activity: { state: "absent", reason: "reading" },
    conversation: { state: "absent", reason: "reading" },
    review: { state: "absent", reason: "reading" },
    plans: { state: "absent", reason: "reading" },
    trust: { state: "absent", reason: "reading" },
  };
}

export function sessionReducer(state: SurfaceSession, action: SessionAction): SurfaceSession {
  switch (action.type) {
    case "opening":
      return { ...state, phase: "opening", requestId: action.requestId, destinationReads: emptyDestinationReads(), priorityFreshness: "loading", priorityRetryable: false, priorityRetrying: false, priorityRetryOutcome: null, notice: null, questionAction: { state: "idle" }, activityAction: { state: "idle" }, captureAction: { state: "idle" }, cancelAction: { state: "idle" }, jobs: [], jobStatus: "available", jobCheck: "idle", description: unasked(), transferAction: { state: "idle" }, rescanAction: { state: "idle" }, askAction: { state: "idle" }, trustAction: { state: "idle" } };
    case "reading":
      if (action.requestId !== state.requestId) return state;
      return {
        ...state,
        phase: "reading",
        // Retain the rendered snapshot until its complete replacement read is committed.
        source: state.source ?? action.source,
        snapshot: state.source ? state.snapshot : action.snapshot,
        destination: state.source ? state.destination : "overview",
        selectedDocument: state.source ? state.selectedDocument : "",
        selectedQueue: state.source ? state.selectedQueue : "",
        selectedAccount: state.source ? state.selectedAccount : "",
        selectedPrompt: state.source ? state.selectedPrompt : "",
        notice: null,
        questionAction: { state: "idle" },
        activityAction: { state: "idle" },
        captureAction: { state: "idle" },
        cancelAction: { state: "idle" },
        jobs: [],
        description: unasked(),
        transferAction: { state: "idle" },
        rescanAction: { state: "idle" },
        askAction: { state: "idle" },
        trustAction: { state: "idle" },
      };
    case "priority-loaded": {
      if (action.requestId !== state.requestId) return state;
      const sameSource = state.source === action.source;
      const retainComplete = sameSource
        && action.overview.state === "failed"
        && dataBearing(state.snapshot.overview);
      const snapshot = { ...(sameSource ? state.snapshot : liveReadingSnapshot()),
        overview: retainComplete ? state.snapshot.overview : action.overview, disclosure: action.disclosure };
      if (sameSource && ((state.readRevision && action.revision !== state.readRevision)
          || action.freshness !== "current")) snapshot.activity = invalidateActivity(snapshot.activity);
      const ids = selectedIds(snapshot);
      return {
        ...state, phase: "settled", source: action.source, snapshot,
        readRevision: retainComplete ? state.readRevision : action.revision,
        priorityFreshness: retainComplete ? "stale" : action.freshness,
        priorityLifecycle: action.lifecycle,
        priorityRetryable: retainComplete || action.retryable,
        priorityRetrying: false,
        selectedDocument: sameSource ? state.selectedDocument : "",
        selectedQueue: sameSource ? state.selectedQueue : "",
        selectedPrompt: sameSource ? state.selectedPrompt : "",
        selectedAccount: sameSource ? retainSelection(state.selectedAccount, ids.accounts) : "",
        notice: null,
      };
    }
    case "priority-retrying":
      return action.requestId === state.requestId && state.priorityRetryable && !state.priorityRetrying
        ? { ...state, priorityRetrying: true, priorityRetryOutcome: null }
        : state;
    case "priority-retry-failed":
      return action.requestId === state.requestId ? { ...state, priorityRetrying: false, priorityRetryOutcome: "failed" } : state;
    case "priority-retry-succeeded":
      return action.requestId === state.requestId ? { ...state, priorityRetrying: false, priorityRetryOutcome: "succeeded" } : state;
    case "secondary-loaded": {
      if (action.requestId !== state.requestId) return state;
      const combined = { ...action.snapshot, overview: state.snapshot.overview, disclosure: state.snapshot.disclosure };
      const dataPair = dataBearing(combined.review) && dataBearing(combined.conversation);
      const mismatchedPair = dataPair && !reviewConversationSemanticallyMatch(combined);
      const snapshot: SurfaceSnapshot = mismatchedPair ? {
        ...combined,
        review: { state: "failed", reason: "invalid_payload" },
        conversation: { state: "failed", reason: "invalid_payload" },
      } : combined;
      const ids = selectedIds(snapshot);
      return { ...state, snapshot,
        selectedDocument: retainSelection(state.selectedDocument, ids.documents),
        selectedQueue: retainSelection(state.selectedQueue, ids.queue),
        selectedAccount: retainSelection(state.selectedAccount, ids.accounts),
        notice: mismatchedPair
          ? { kind: "refused", text: "The vault opened, but Review and conversation disagreed about which questions are actionable. Neither queue is available." }
          : hasReadFailure(snapshot)
            ? { kind: "refused", text: "The private vault opened, but some surfaces could not be read. Your vault was not changed." }
            : state.notice };
    }
    case "destination-loading":
      return action.requestId === state.requestId
        ? { ...state, destinationReads: { ...state.destinationReads, [action.destination]: "loading" } }
        : state;
    case "destination-retrying":
      return action.requestId === state.requestId && state.destinationReads[action.destination] === "failed"
        ? { ...state, destinationReads: { ...state.destinationReads, [action.destination]: "retrying" } }
        : state;
    case "destination-failed": {
      if (action.requestId !== state.requestId) return state;
      const failed = { state: "failed" as const, reason: "read_failed" as const };
      const current = state.snapshot[action.destination];
      const replacement = current && (current.state === "ready" || current.state === "partial" || current.state === "needs_input")
        ? current : action.snapshot?.[action.destination] ?? failed;
      const snapshot: SurfaceSnapshot = { ...state.snapshot, [action.destination]: replacement };
      if (action.destination === "review" && !(dataBearing(state.snapshot.review) && dataBearing(state.snapshot.conversation))) {
        snapshot.review = action.snapshot?.review?.state === "failed" ? action.snapshot.review : failed;
        snapshot.conversation = action.snapshot?.conversation?.state === "failed" ? action.snapshot.conversation : failed;
      }
      return { ...state, snapshot, destinationReads: { ...state.destinationReads, [action.destination]: "failed" } };
    }
    case "destination-loaded": {
      if (action.requestId !== state.requestId) return state;
      const merged = { ...state.snapshot, ...action.snapshot };
      const dataPair = dataBearing(merged.review) && dataBearing(merged.conversation);
      const mismatchedPair = dataPair && !reviewConversationSemanticallyMatch(merged);
      const snapshot = mismatchedPair ? {
        ...merged,
        review: { state: "failed" as const, reason: "invalid_payload" as const },
        conversation: { state: "failed" as const, reason: "invalid_payload" as const },
      } : merged;
      const ids = selectedIds(snapshot);
      return { ...state, snapshot,
        destinationReads: action.destination ? { ...state.destinationReads, [action.destination]: destinationOutcome(snapshot, action.destination) } : state.destinationReads,
        selectedDocument: retainSelection(state.selectedDocument, ids.documents),
        selectedQueue: retainSelection(state.selectedQueue, ids.queue),
        selectedAccount: retainSelection(state.selectedAccount, ids.accounts) };
    }
    case "loaded": {
      if (action.requestId !== state.requestId) return state;
      const dataPair = dataBearing(action.snapshot.review) && dataBearing(action.snapshot.conversation);
      const mismatchedPair = dataPair && !reviewConversationSemanticallyMatch(action.snapshot);
      const allFailed = everyVaultSurfaceFailed(action.snapshot);
      const snapshot: SurfaceSnapshot = allFailed ? state.snapshot : mismatchedPair ? {
        ...action.snapshot,
        review: { state: "failed", reason: "invalid_payload" },
        conversation: { state: "failed", reason: "invalid_payload" },
      } : action.snapshot;
      const ids = selectedIds(snapshot);
      return {
        ...state,
        phase: "settled",
        source: allFailed ? state.source : action.source ?? state.source,
        snapshot,
        jobs: action.jobs ?? state.jobs,
        jobStatus: action.jobStatus ?? state.jobStatus,
        selectedDocument: retainSelection(state.selectedDocument, ids.documents),
        selectedQueue: retainSelection(state.selectedQueue, ids.queue),
        selectedAccount: retainSelection(state.selectedAccount, ids.accounts),
        selectedPrompt: retainSelection(state.selectedPrompt, ids.prompts),
        notice: mismatchedPair
          ? { kind: "refused", text: "The vault opened, but Review and conversation disagreed about which questions are actionable. Neither queue is available." }
          : allFailed
            ? { kind: "refused", text: "The vault connection was lost while its surfaces were being read. The selected vault has not been replaced, but it must be reopened before it can be used." }
            : hasReadFailure(action.snapshot) ? { kind: "refused", text: "The private vault opened, but some surfaces could not be read. Your vault was not changed." } : null,
      };
    }
    case "mutation-loaded": {
      if (action.requestId !== state.requestId) return state;
      const readFailed = hasReadFailure(action.snapshot);
      const pairUnavailable = !hasAuthoritativeReviewConversationPair(action.snapshot);
      const snapshot = readFailed || pairUnavailable ? invalidateActivitySnapshot(state.snapshot) : action.snapshot;
      const ids = selectedIds(snapshot);
      return {
        ...state,
        phase: "settled",
        snapshot,
        readRevision: snapshot === action.snapshot && action.revision ? action.revision : state.readRevision,
        destinationReads: snapshot === action.snapshot
          ? { documents: destinationOutcome(snapshot, "documents"), review: destinationOutcome(snapshot, "review"), trust: destinationOutcome(snapshot, "trust"), activity: destinationOutcome(snapshot, "activity"), plans: destinationOutcome(snapshot, "plans") }
          : state.destinationReads,
        jobs: action.jobs ?? state.jobs,
        jobStatus: action.jobStatus ?? state.jobStatus,
        selectedDocument: retainSelection(state.selectedDocument, ids.documents),
        selectedQueue: retainSelection(state.selectedQueue, ids.queue),
        selectedAccount: retainSelection(state.selectedAccount, ids.accounts),
        selectedPrompt: retainSelection(state.selectedPrompt, ids.prompts),
        notice: readFailed
          ? { kind: "refused", text: "The action finished, but some surfaces could not be read again. Anything still shown there may be stale." }
          : pairUnavailable
            ? { kind: "refused", text: "The action finished, but Review and conversation could not both be read again. Their prior questions and count remain on screen and may be stale." }
            : null,
      };
    }
    case "mutation-refresh-failed":
      if (action.requestId !== state.requestId) return state;
      return { ...state, snapshot: invalidateActivitySnapshot(state.snapshot), notice: { kind: "refused", text: "The action finished, but the full vault picture could not be read again. What is shown may be stale." } };
    case "open-failed":
      if (action.requestId !== state.requestId) return state;
      // Display a reviewed sidecar refusal when provided. Otherwise describe an
      // unanswered open without inferring a folder or passphrase rejection.
      return { ...state, phase: "settled", notice: { kind: "refused", text: action.said || "The local vault could not be opened. Nothing came back saying why — a wrong folder or a wrong passphrase would have said so." } };
    case "remembered-open-finished":
      if (action.requestId !== state.requestId) return state;
      return { ...state, phase: "settled", notice: action.said ? { kind: "refused", text: action.said } : null };
    case "load-failed":
      if (action.requestId !== state.requestId) return state;
      return { ...state, phase: "settled", notice: { kind: "refused", text: "The vault connection was lost while its surfaces were being read. The selected vault has not been replaced, but it must be reopened before it can be used." } };
    // Leaving a vault rebuilds the whole session from its initial state.
    case "reset": {
      const reset = initialSession();
      return { ...reset, requestId: action.requestId, notice: { kind: "acknowledged", text: "Closed. Nothing from that vault is on this screen." } };
    }
    // Leaving a review question or destination clears its action notice.
    // Capture receipts remain in the session across destination changes.
    case "navigate": return { ...state, destination: action.destination, questionAction: { state: "idle" } };
    case "select-document": return { ...state, selectedDocument: action.id };
    case "select-queue":
      return { ...state, selectedQueue: action.id, questionAction: { state: "idle" } };
    case "question-acting":
      if (action.requestId !== state.requestId) return state;
      return { ...state, questionAction: { state: "working", questionId: action.questionId, verb: action.verb } };
    case "question-acted": {
      if (action.requestId !== state.requestId || state.questionAction.state !== "working"
          || state.questionAction.questionId !== action.questionId || state.questionAction.verb !== action.verb) return state;
      return {
        ...state,
        questionAction: { state: "settled", questionId: action.questionId, verb: action.verb, result: action.result, authoritative: action.authoritative, resolved: action.resolved },
      };
    }
    case "activity-correcting":
      if (action.requestId !== state.requestId) return state;
      return { ...state, activityAction: { state: "working", movementId: action.movementId, movementIds: [...(action.movementIds ?? [action.movementId])], verb: action.verb } };
    case "activity-outcome":
      if (action.requestId !== state.requestId) return state;
      return { ...state, activityAction: { state: "refreshing", movementId: action.movementId, movementIds: [...(action.movementIds ?? [action.movementId])], verb: action.verb, result: action.result } };
    case "activity-refreshed": {
      if (action.requestId !== state.requestId) return state;
      if (!hasAuthoritativeReviewConversationPair(action.snapshot)) {
        return {
          ...state,
          jobs: action.jobs ?? state.jobs,
          notice: { kind: "refused", text: "The correction finished, but Review and conversation could not both be read again. Their prior questions and count remain on screen and may be stale." },
          activityAction: { state: "settled", movementId: action.movementId, movementIds: [...(action.movementIds ?? [action.movementId])], verb: action.verb, result: action.result, refresh: "failed" },
        };
      }
      const ids = selectedIds(action.snapshot);
      return {
        ...state,
        snapshot: action.snapshot,
        readRevision: action.revision || state.readRevision,
        jobs: action.jobs ?? state.jobs,
        selectedDocument: retainSelection(state.selectedDocument, ids.documents),
        selectedQueue: retainSelection(state.selectedQueue, ids.queue),
        selectedAccount: retainSelection(state.selectedAccount, ids.accounts),
        selectedPrompt: retainSelection(state.selectedPrompt, ids.prompts),
        activityAction: { state: "settled", movementId: action.movementId, movementIds: [...(action.movementIds ?? [action.movementId])], verb: action.verb, result: action.result, refresh: "refreshed" },
      };
    }
    case "activity-refresh-failed":
      if (action.requestId !== state.requestId) return state;
      return { ...state, snapshot: invalidateActivitySnapshot(state.snapshot), activityAction: { state: "settled", movementId: action.movementId, movementIds: [...(action.movementIds ?? [action.movementId])], verb: action.verb, result: action.result, refresh: "failed" } };
    case "activity-page-loading":
    case "activity-page-failed": {
      if (action.requestId !== state.requestId) return state;
      const held = state.snapshot.activity;
      return !dataBearing(held) ? state : { ...state, snapshot: { ...state.snapshot, activity: { ...held,
        data: { ...held.data, loadingMore: action.type === "activity-page-loading", continuationFailed: action.type === "activity-page-failed" } } } };
    }
    case "activity-first-page-loaded": {
      if (action.requestId !== state.requestId) return state;
      if (!dataBearing(action.activity) || (action.activity.data.page
          && action.activity.data.page.cumulativeCount !== action.activity.data.movements.length)) {
        return sessionReducer(state, { type: "activity-page-failed", requestId: action.requestId });
      }
      return { ...state, snapshot: { ...state.snapshot, activity: action.activity } };
    }
    case "activity-page-loaded": {
      if (action.requestId !== state.requestId) return state;
      const held = state.snapshot.activity, incoming = action.activity;
      if (!dataBearing(held)) return state;
      const previous = held.data.page;
      const next = dataBearing(incoming) ? incoming.data.page : undefined;
      const ids = new Set(held.data.movements.map((row) => row.id));
      if (!previous?.nextCursor || !next || !dataBearing(incoming) || next.revision !== previous.revision
          || incoming.data.movements.length === 0 || incoming.data.movements.length > 50
          || new Set(incoming.data.movements.map((row) => row.id)).size !== incoming.data.movements.length
          || next.focus !== previous.focus || next.cumulativeCount !== previous.cumulativeCount + incoming.data.movements.length
          || next.remainingCount + next.cumulativeCount !== previous.remainingCount + previous.cumulativeCount
          || next.nextCursor === previous.nextCursor || incoming.data.movements.some((row) => ids.has(row.id))) {
        return sessionReducer(state, { type: "activity-page-failed", requestId: action.requestId });
      }
      return { ...state, snapshot: { ...state.snapshot, activity: { ...incoming, data: { ...incoming.data,
        movements: [...held.data.movements, ...incoming.data.movements], loadingMore: false, continuationFailed: false } } } };
    }
    case "capturing":
      if (action.requestId !== state.requestId) return state;
      return { ...state, captureAction: { state: "working", result: state.captureAction.state === "idle" ? null : state.captureAction.result } };
    case "captured": {
      if (action.requestId !== state.requestId) return state;
      return {
        ...state,
        captureAction: { state: "settled", result: action.result },
      };
    }
    // Accept sidecar progress frames independently of the selected destination.
    // Each control selects the job it targets.
    case "described":
      if (action.requestId !== state.requestId) return state;
      return { ...state, description: action.description };
    case "trust-working":
      if (action.requestId !== state.requestId) return state;
      return { ...state, trustAction: { state: "working" } };
    case "trust-settled":
      if (action.requestId !== state.requestId) return state;
      return { ...state, trustAction: { state: "settled", result: action.result } };
    case "asking":
      if (action.requestId !== state.requestId) return state;
      return { ...state, askAction: { state: "working", question: action.question } };
    case "asked":
      if (action.requestId !== state.requestId || state.askAction.state !== "working" || state.askAction.question !== action.question) return state;
      return { ...state, askAction: { state: "settled", question: action.question, result: action.result, turn: action.turn, authoritative: action.authoritative } };
    // Machine settings survive vault opening and closing.
    case "settings-read": return { ...state, settings: action.settings };
    case "settings-working": return { ...state, settingsAction: { state: "working" } };
    case "settings-proposed": return { ...state, settingsAction: { state: "proposed", proposal: action.proposal } };
    case "settings-settled": return { ...state, settings: action.settings, settingsAction: { state: "settled", result: action.result } };
    case "rescanning":
      if (action.requestId !== state.requestId) return state;
      return { ...state, rescanAction: { state: "working" } };
    case "rescanned": {
      if (action.requestId !== state.requestId) return state;
      return {
        ...state,
        rescanAction: { state: "settled", result: action.result, report: action.report },
      };
    }
    case "transferring":
      if (action.requestId !== state.requestId) return state;
      return { ...state, transferAction: { state: "working", verb: action.verb } };
    case "transferred":
      if (action.requestId !== state.requestId) return state;
      return { ...state, transferAction: { state: "settled", verb: action.verb, result: action.result } };
    case "job-progress":
      if (action.requestId !== state.requestId) return state;
      return { ...state, jobs: withJob(state.jobs, action.job) };
    case "jobs-read":
      if (action.requestId !== state.requestId) return state;
      return { ...state, jobs: action.jobs, jobStatus: "available", jobCheck: "succeeded" };
    case "jobs-unavailable":
      if (action.requestId !== state.requestId) return state;
      return { ...state, jobStatus: "unavailable", jobCheck: state.jobCheck === "checking" ? "failed" : "idle" };
    case "jobs-checking":
      if (action.requestId !== state.requestId || state.jobCheck === "checking") return state;
      return { ...state, jobCheck: "checking" };
    case "cancelling":
      if (action.requestId !== state.requestId) return state;
      return { ...state, cancelAction: { state: "working", jobId: action.jobId } };
    case "cancelled":
      if (action.requestId !== state.requestId) return state;
      // Replace job rows with the authoritative registry read after a stop.
      return { ...state, jobs: action.jobs, cancelAction: { state: "settled", jobId: action.jobId, result: action.result } };
    case "select-account": return { ...state, selectedAccount: action.id };
    case "select-prompt": return { ...state, selectedPrompt: action.id };
    case "notice": return { ...state, notice: action.notice };
  }
}
