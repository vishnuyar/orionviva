import type { SourceDescription, SurfaceSource } from "../surface/sources";
import { demoSource, sampleSnapshot } from "../surface/sources";
import type { ActionResult, CancelActionState, CaptureActionState, Destination, DocumentsData, FeatureResult, JobView, Notice, RescanActionState, RescanReport, ReviewActionState, ReviewData, ReviewVerb, SurfaceSnapshot, TransferActionState, TransferVerb } from "../surface/types";
import { retainSelection } from "./selection";

export type SessionPhase = "opening" | "reading" | "settled";
export type SurfaceSession = {
  phase: SessionPhase;
  requestId: number;
  source: SurfaceSource;
  snapshot: SurfaceSnapshot;
  destination: Destination;
  selectedDocument: string;
  selectedQueue: string;
  selectedAccount: string;
  selectedPrompt: string;
  notice: Notice | null;
  reviewAction: ReviewActionState;
  captureAction: CaptureActionState;
  cancelAction: CancelActionState;
  // What the sidecar last said it was doing, newest last. Every row here was
  // written by the sidecar — a progress frame it produced, or the registry it
  // holds — and nothing on this side counts a step or names one.
  //
  // It lives in the session rather than in the snapshot because it is not a
  // read of the vault: it survives no restart, describes this process only,
  // and a snapshot claiming to hold it would be claiming the vault said
  // something it never said.
  jobs: readonly JobView[];
  // What the engine behind this source says about itself: which build answered,
  // and which destinations its own registry says a read reaches. It is asked
  // once per source, because neither answer changes while one sidecar lives.
  description: SourceDescription;
  // What became of the last whole-vault copy a person asked for, out or back.
  // It is not cleared by moving screens: it is a receipt for a file that now
  // exists, or for one that does not, and either outlives the screen a person
  // happened to be on.
  transferAction: TransferActionState;
  // What the last pass back over this vault said it did. It stays on the
  // screen after the pass: it is a receipt for events that were written, and
  // clearing it on the next navigation would take a record of a change away
  // from the person the change was made for.
  rescanAction: RescanActionState;
};

export type SessionAction =
  | { type: "opening"; requestId: number }
  | { type: "reading"; requestId: number; source: SurfaceSource; snapshot: SurfaceSnapshot }
  | { type: "loaded"; requestId: number; snapshot: SurfaceSnapshot }
  | { type: "open-failed"; requestId: number }
  | { type: "load-failed"; requestId: number }
  | { type: "reset"; requestId: number }
  | { type: "navigate"; destination: Destination }
  | { type: "select-document"; id: string }
  | { type: "select-queue"; id: string }
  | { type: "select-account"; id: string }
  | { type: "select-prompt"; id: string }
  | { type: "review-acting"; requestId: number; questionId: string; verb: ReviewVerb }
  | { type: "review-acted"; requestId: number; questionId: string; verb: ReviewVerb; result: ActionResult; review: FeatureResult<ReviewData> }
  | { type: "capturing"; requestId: number }
  | { type: "captured"; requestId: number; result: ActionResult; documents: FeatureResult<DocumentsData> }
  | { type: "job-progress"; requestId: number; job: JobView }
  | { type: "described"; requestId: number; description: SourceDescription }
  | { type: "rescanning"; requestId: number }
  | { type: "rescanned"; requestId: number; result: ActionResult; report: RescanReport | null; documents: FeatureResult<DocumentsData> }
  | { type: "transferring"; requestId: number; verb: TransferVerb }
  | { type: "transferred"; requestId: number; verb: TransferVerb; result: ActionResult }
  | { type: "cancelling"; requestId: number; jobId: string }
  | { type: "cancelled"; requestId: number; jobId: string; result: ActionResult; jobs: readonly JobView[] }
  | { type: "notice"; notice: Notice | null };

function dataOf<T>(result: FeatureResult<T>): T | null {
  return result.state === "ready" || result.state === "partial" || result.state === "needs_input" ? result.data : null;
}

function selectedIds(snapshot: SurfaceSnapshot) {
  const overview = dataOf(snapshot.overview);
  const documents = dataOf(snapshot.documents);
  const review = dataOf(snapshot.review);
  const conversation = dataOf(snapshot.conversation);
  return {
    documents: documents?.documents.map((item) => item.id) ?? [],
    queue: review?.queue.map((item) => item.id) ?? [],
    accounts: overview?.accounts.map((item) => item.id) ?? [],
    prompts: conversation?.prompts.map((item) => item.id) ?? [],
  };
}

function hasReadFailure(snapshot: SurfaceSnapshot) {
  return [snapshot.overview, snapshot.documents, snapshot.review].some((result) => result.state === "failed");
}

export function initialSession(): SurfaceSession {
  const ids = selectedIds(sampleSnapshot);
  return {
    phase: "settled",
    requestId: 0,
    source: demoSource,
    snapshot: sampleSnapshot,
    destination: "overview",
    selectedDocument: ids.documents[0] ?? "",
    selectedQueue: ids.queue[0] ?? "",
    selectedAccount: ids.accounts[0] ?? "",
    selectedPrompt: ids.prompts[0] ?? "",
    notice: null,
    reviewAction: { state: "idle" },
    captureAction: { state: "idle" },
    cancelAction: { state: "idle" },
    jobs: [],
    description: unasked(),
    transferAction: { state: "idle" },
    rescanAction: { state: "idle" },
  };
}

// What is known about the engine before anything has been asked. Not an empty
// answer and not a false one: a source that has not been asked yet says so, and
// nothing renders a destination as unserved on the strength of a question
// nobody put.
export function unasked(): SourceDescription {
  return { identity: { state: "absent", reason: "not_asked" }, registry: { state: "absent", reason: "not_asked" } };
}

// One job's row replaced by a newer statement about the same job, or appended
// when this is the first word about it. A frame carries no step list, so a
// frame about a job the registry already described keeps the list the registry
// gave it: a later statement about a job's progress is not a retraction of
// what it said it would do.
function withJob(jobs: readonly JobView[], job: JobView): readonly JobView[] {
  const held = jobs.find((candidate) => candidate.jobId === job.jobId);
  const merged = held && !job.steps.length ? { ...job, steps: held.steps } : job;
  return held ? jobs.map((candidate) => (candidate.jobId === job.jobId ? merged : candidate)) : [...jobs, merged];
}

export function liveReadingSnapshot(): SurfaceSnapshot {
  return {
    mode: "live",
    disclosure: {
      title: "Private vault",
      subtitle: "Opened on this device",
      detail: "The surfaces below are read from this vault. Features that are not connected stay hidden or say so.",
    },
    overview: { state: "absent", reason: "reading" },
    documents: { state: "absent", reason: "reading" },
    review: { state: "absent", reason: "reading" },
    activity: { state: "absent", reason: "reading" },
    conversation: { state: "absent", reason: "reading" },
    trust: { state: "absent", reason: "reading" },
  };
}

export function sessionReducer(state: SurfaceSession, action: SessionAction): SurfaceSession {
  switch (action.type) {
    case "opening":
      return { ...state, phase: "opening", requestId: action.requestId, notice: null, reviewAction: { state: "idle" }, captureAction: { state: "idle" }, cancelAction: { state: "idle" }, jobs: [], description: unasked(), transferAction: { state: "idle" }, rescanAction: { state: "idle" } };
    case "reading":
      if (action.requestId !== state.requestId || action.snapshot.mode !== action.source.mode) return state;
      return {
        ...state,
        phase: "reading",
        source: action.source,
        snapshot: action.snapshot,
        destination: "overview",
        selectedDocument: "",
        selectedQueue: "",
        selectedAccount: "",
        selectedPrompt: "",
        notice: { kind: "acknowledged", text: "Reading available surfaces from this device…" },
        reviewAction: { state: "idle" },
        captureAction: { state: "idle" },
        cancelAction: { state: "idle" },
        jobs: [],
        description: unasked(),
        transferAction: { state: "idle" },
        rescanAction: { state: "idle" },
      };
    case "loaded": {
      if (action.requestId !== state.requestId || action.snapshot.mode !== state.source.mode) return state;
      const ids = selectedIds(action.snapshot);
      return {
        ...state,
        phase: "settled",
        snapshot: action.snapshot,
        selectedDocument: retainSelection(state.selectedDocument, ids.documents),
        selectedQueue: retainSelection(state.selectedQueue, ids.queue),
        selectedAccount: retainSelection(state.selectedAccount, ids.accounts),
        selectedPrompt: retainSelection(state.selectedPrompt, ids.prompts),
        notice: hasReadFailure(action.snapshot) ? { kind: "refused", text: "The private vault opened, but some surfaces could not be read. Your vault was not changed." } : null,
      };
    }
    case "open-failed":
      if (action.requestId !== state.requestId) return state;
      return { ...state, phase: "settled", notice: { kind: "refused", text: "The local vault could not be opened. Check the directory and passphrase, then try again." } };
    case "load-failed":
      if (action.requestId !== state.requestId) return state;
      return { ...state, phase: "settled", notice: { kind: "refused", text: "The local vault opened, but its surface data could not be loaded." } };
    case "reset": {
      const reset = initialSession();
      return { ...reset, requestId: action.requestId, notice: { kind: "acknowledged", text: "Sample vault reset to the fictional data stored with the app." } };
    }
    // What was last done to a review question is said beside the question it
    // was done to, so leaving a question or leaving the screen it was on
    // clears it. A notice still standing after either would report an act on
    // something the person is no longer looking at.
    //
    // What became of a capture is not cleared. It is a receipt for something
    // durable that was written to the vault, and it belongs to the session
    // rather than to the screen a person happened to be on when it landed.
    case "navigate": return { ...state, destination: action.destination, reviewAction: { state: "idle" } };
    case "select-document": return { ...state, selectedDocument: action.id };
    case "select-queue":
      return { ...state, selectedQueue: action.id, reviewAction: { state: "idle" } };
    case "review-acting":
      if (action.requestId !== state.requestId) return state;
      return { ...state, reviewAction: { state: "working", questionId: action.questionId, verb: action.verb } };
    case "review-acted": {
      if (action.requestId !== state.requestId) return state;
      // The read that follows a write replaces only review. Nothing else was
      // asked for, so nothing else is claimed to have been re-read.
      const snapshot = { ...state.snapshot, review: action.review };
      const ids = selectedIds(snapshot);
      return {
        ...state,
        snapshot,
        selectedQueue: retainSelection(state.selectedQueue, ids.queue),
        reviewAction: { state: "settled", questionId: action.questionId, verb: action.verb, result: action.result },
      };
    }
    case "capturing":
      if (action.requestId !== state.requestId) return state;
      return { ...state, captureAction: { state: "working", result: state.captureAction.state === "idle" ? null : state.captureAction.result } };
    case "captured": {
      if (action.requestId !== state.requestId) return state;
      // The read that follows a capture replaces only documents. Nothing else
      // was asked for, so nothing else is claimed to have been read again.
      const snapshot = { ...state.snapshot, documents: action.documents };
      const ids = selectedIds(snapshot);
      return {
        ...state,
        snapshot,
        selectedDocument: retainSelection(state.selectedDocument, ids.documents),
        captureAction: { state: "settled", result: action.result },
      };
    }
    // A progress frame is the sidecar saying what it is doing right now, so it
    // is taken whatever screen a person is on. Nothing here decides whether
    // the job it names is the one a control belongs to; that is decided where
    // the control is.
    case "described":
      if (action.requestId !== state.requestId) return state;
      return { ...state, description: action.description };
    case "rescanning":
      if (action.requestId !== state.requestId) return state;
      return { ...state, rescanAction: { state: "working" } };
    case "rescanned": {
      if (action.requestId !== state.requestId) return state;
      // A pass writes links and heals, so the documents read that follows it
      // replaces only documents. Nothing else was asked for, so nothing else
      // is claimed to have been read again.
      const snapshot = { ...state.snapshot, documents: action.documents };
      const ids = selectedIds(snapshot);
      return {
        ...state,
        snapshot,
        selectedDocument: retainSelection(state.selectedDocument, ids.documents),
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
    case "cancelling":
      if (action.requestId !== state.requestId) return state;
      return { ...state, cancelAction: { state: "working", jobId: action.jobId } };
    case "cancelled":
      if (action.requestId !== state.requestId) return state;
      // The registry read that followed the stop replaces the rows outright.
      // A merge here would keep a job the registry has since forgotten, and a
      // row nothing holds is a claim about work with no source.
      return { ...state, jobs: action.jobs, cancelAction: { state: "settled", jobId: action.jobId, result: action.result } };
    case "select-account": return { ...state, selectedAccount: action.id };
    case "select-prompt": return { ...state, selectedPrompt: action.id };
    case "notice": return { ...state, notice: action.notice };
  }
}
