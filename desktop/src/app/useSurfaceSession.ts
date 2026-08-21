import { useEffect, useReducer, useRef, useState } from "react";
import { createDetectedBridgeClient } from "../bridge/client";
import { privateSource } from "../surface/sources";
import type { ActionResult, DeclineReason, Destination, DocumentActions, EvidenceLink, Notice, ReviewActions, ReviewVerb } from "../surface/types";
import { initialSession, liveReadingSnapshot, sessionReducer } from "./session";

// What a gesture carrying files turned out to be. Only `one` reaches the
// vault; `several` is refused and `none` is a person changing their mind.
export type CaptureGesture = "none" | "one" | "several";

export function useSurfaceSession(onDropped?: (gesture: CaptureGesture) => void) {
  const [session, dispatch] = useReducer(sessionReducer, undefined, initialSession);
  const [hostBridge] = useState(createDetectedBridgeClient);
  const requestId = useRef(0);
  const dropped = useRef(onDropped);
  dropped.current = onDropped;
  const capturing = useRef(false);
  const choosing = useRef(false);
  const documentActions = session.source.documentActions;

  // One review verb at a time. The sidecar answers one request before reading
  // the next, so a second press while the first is in flight would queue behind
  // it and report against a queue that has already moved.
  async function runReviewVerb(verb: ReviewVerb, questionId: string, run: (actions: ReviewActions) => Promise<ActionResult>) {
    const actions = session.source.reviewActions;
    if (!questionId.trim() || session.reviewAction.state === "working") return;
    const nextRequestId = requestId.current;
    dispatch({ type: "review-acting", requestId: nextRequestId, questionId, verb });
    const result = await run(actions);
    const review = await actions.reread();
    if (requestId.current !== nextRequestId) return;
    dispatch({ type: "review-acted", requestId: nextRequestId, questionId, verb, result, review });
  }

  // One document, one request, one answer. The vault is read again once the
  // answer is in, and that read is what the screen shows.
  async function capture(actions: DocumentActions, path: string) {
    if (capturing.current) return;
    capturing.current = true;
    const nextRequestId = requestId.current;
    dispatch({ type: "capturing", requestId: nextRequestId });
    try {
      const result = await actions.upload(path);
      const documents = await actions.reread();
      if (requestId.current === nextRequestId) dispatch({ type: "captured", requestId: nextRequestId, result, documents });
    } finally {
      capturing.current = false;
    }
  }

  // Both doors into capture pass through here: the file picker, and a file
  // dropped on this side. What a gesture carried is decided once, before any
  // frame is sent, and a gesture carrying more than one document is refused
  // rather than sealed — one reply carries one answer, and this build has no
  // channel that can report several of them as they happen.
  async function captureGesture(actions: DocumentActions, paths: readonly string[]): Promise<CaptureGesture> {
    const [first, second] = paths;
    if (first === undefined) return "none";
    if (second !== undefined) return "several";
    await capture(actions, first);
    return "one";
  }

  // A dropped file arrives from the host as a path, because the native layer
  // takes the drop before this side can see it. A drop can land while any
  // screen is open and what it writes is durable, so what became of it is
  // handed to the screen that can move a person to its receipt. More than one
  // path is refused before anything is sent. The subscription lives as long as
  // the source that can act on it.
  useEffect(() => {
    if (!documentActions || !hostBridge?.subscribeToDroppedPaths) return undefined;
    let stop: (() => void) | null = null;
    let gone = false;
    void hostBridge.subscribeToDroppedPaths((paths) => {
      if (!paths.length) return;
      dropped.current?.(paths.length === 1 ? "one" : "several");
      void captureGesture(documentActions, paths);
    })
      .then((unlisten) => { if (gone) unlisten(); else stop = unlisten; })
      .catch(() => undefined);
    return () => { gone = true; stop?.(); };
  }, [documentActions, hostBridge]);

  return {
    session,
    hostAvailable: Boolean(hostBridge),
    captureAvailable: Boolean(documentActions),
    filePickerAvailable: Boolean(documentActions && hostBridge?.pickDocumentPaths),
    pickerAvailable: Boolean(hostBridge?.pickVaultDirectory),
    async openVault(vaultDirectory: string, passphrase: string) {
      if (!hostBridge) return false;
      const nextRequestId = ++requestId.current;
      dispatch({ type: "opening", requestId: nextRequestId });
      try {
        await hostBridge.openVault(vaultDirectory, passphrase);
      } catch {
        if (requestId.current === nextRequestId) dispatch({ type: "open-failed", requestId: nextRequestId });
        return false;
      }
      if (requestId.current !== nextRequestId) return false;
      const source = privateSource(hostBridge);
      dispatch({ type: "reading", requestId: nextRequestId, source, snapshot: liveReadingSnapshot() });
      try {
        const snapshot = await source.load();
        if (requestId.current === nextRequestId) dispatch({ type: "loaded", requestId: nextRequestId, snapshot });
      } catch {
        if (requestId.current === nextRequestId) dispatch({ type: "load-failed", requestId: nextRequestId });
        return false;
      }
      return requestId.current === nextRequestId;
    },
    async pickVaultDirectory() { return hostBridge?.pickVaultDirectory?.() ?? null; },
    // One picker at a time, and one capture at a time. The picker being open
    // is not the vault being busy, so it is held apart from the state the
    // screen renders.
    //
    // A picker that closed with nothing chosen and a picker that could not be
    // opened are answered differently: the first is a person changing their
    // mind, the second is a control that did not work, and only the second is
    // reported back.
    async chooseDocuments(): Promise<CaptureGesture | "unopened"> {
      if (!documentActions || !hostBridge?.pickDocumentPaths || capturing.current || choosing.current) return "none";
      choosing.current = true;
      let paths: readonly string[] = [];
      try { paths = await hostBridge.pickDocumentPaths(); }
      catch { choosing.current = false; return "unopened"; }
      choosing.current = false;
      return captureGesture(documentActions, paths);
    },
    resetDemo() {
      const nextRequestId = ++requestId.current;
      dispatch({ type: "reset", requestId: nextRequestId });
    },
    navigate(destination: Destination) { dispatch({ type: "navigate", destination }); },
    openEvidence(link: EvidenceLink) { dispatch({ type: "select-document", id: link.targetDocumentId }); dispatch({ type: "navigate", destination: "documents" }); },
    selectDocument(id: string) { dispatch({ type: "select-document", id }); },
    selectQueue(id: string) { dispatch({ type: "select-queue", id }); },
    async declineQuestion(questionId: string, reason: DeclineReason) {
      await runReviewVerb("decline", questionId, (actions) => actions.decline(questionId, reason));
    },
    selectAccount(id: string) { dispatch({ type: "select-account", id }); },
    selectPrompt(id: string) { dispatch({ type: "select-prompt", id }); },
    setNotice(notice: Notice | null) { dispatch({ type: "notice", notice }); },
  };
}
