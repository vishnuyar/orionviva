import type { SurfaceSource } from "../surface/sources";
import { demoSource, sampleSnapshot } from "../surface/sources";
import type { Destination, FeatureResult, SurfaceSnapshot } from "../surface/types";
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
  notice: string | null;
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
  | { type: "notice"; notice: string | null };

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
  };
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
      return { ...state, phase: "opening", requestId: action.requestId, notice: null };
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
        notice: "Reading available surfaces from this device…",
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
        notice: hasReadFailure(action.snapshot) ? "The private vault opened, but some surfaces could not be read. Your vault was not changed." : null,
      };
    }
    case "open-failed":
      if (action.requestId !== state.requestId) return state;
      return { ...state, phase: "settled", notice: "The local vault could not be opened. Check the directory and passphrase, then try again." };
    case "load-failed":
      if (action.requestId !== state.requestId) return state;
      return { ...state, phase: "settled", notice: "The local vault opened, but its surface data could not be loaded." };
    case "reset": {
      const reset = initialSession();
      return { ...reset, requestId: action.requestId, notice: "Sample vault reset to the fictional data stored with the app." };
    }
    case "navigate": return { ...state, destination: action.destination };
    case "select-document": return { ...state, selectedDocument: action.id };
    case "select-queue": return { ...state, selectedQueue: action.id };
    case "select-account": return { ...state, selectedAccount: action.id };
    case "select-prompt": return { ...state, selectedPrompt: action.id };
    case "notice": return { ...state, notice: action.notice };
  }
}
