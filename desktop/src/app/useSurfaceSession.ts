import { useReducer, useRef, useState } from "react";
import { createDetectedBridgeClient } from "../bridge/client";
import { privateSource } from "../surface/sources";
import type { ActionResult, DeclineReason, Destination, EvidenceLink, ReviewActions, ReviewVerb } from "../surface/types";
import { initialSession, liveReadingSnapshot, sessionReducer } from "./session";

export function useSurfaceSession() {
  const [session, dispatch] = useReducer(sessionReducer, undefined, initialSession);
  const [hostBridge] = useState(createDetectedBridgeClient);
  const requestId = useRef(0);

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

  return {
    session,
    hostAvailable: Boolean(hostBridge),
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
    setNotice(notice: string | null) { dispatch({ type: "notice", notice }); },
  };
}
