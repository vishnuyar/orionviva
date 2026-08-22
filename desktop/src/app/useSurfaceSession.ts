import { useEffect, useReducer, useRef, useState } from "react";
import { createDetectedBridgeClient } from "../bridge/client";
import { privateSource } from "../surface/sources";
import type { ActionResult, DeclineReason, Destination, DocumentActions, EvidenceLink, JobView, Notice, ReviewActions, ReviewVerb, TransferVerb, VaultTransferActions } from "../surface/types";
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
  const cancelling = useRef(false);
  const transferring = useRef(false);
  const sweeping = useRef(false);
  const documentActions = session.source.documentActions;
  const jobStream = session.source.jobStream;
  const transferActions = session.source.transferActions;
  const source = session.source;

  // What the engine behind this source says about itself, asked once per
  // source. Neither answer changes while one sidecar lives, so asking again
  // per screen would be putting a settled question over and over; a source
  // that is replaced is a different engine and is asked again.
  useEffect(() => {
    let gone = false;
    const asked = requestId.current;
    void source.describe()
      .then((description) => { if (!gone) dispatch({ type: "described", requestId: asked, description }); })
      .catch(() => undefined);
    return () => { gone = true; };
  }, [source]);

  // What the sidecar is doing, as it does it. It cannot arrive in a reply:
  // the reply comes when the work is over, and a channel that only speaks
  // after the fact reports nothing a person could act on. The source hands
  // over rows that were already read; a source whose host cannot deliver one
  // mid-job carries no stream, and nothing here waits for one.
  useEffect(() => {
    if (!jobStream) return undefined;
    let stop: (() => void) | null = null;
    let gone = false;
    void jobStream((job) => dispatch({ type: "job-progress", requestId: requestId.current, job }))
      .then((unlisten) => { if (gone) unlisten(); else stop = unlisten; })
      .catch(() => undefined);
    return () => { gone = true; stop?.(); };
  }, [jobStream]);

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

  // One whole-vault copy at a time, out or back. The sidecar answers one
  // request before it reads the next, so a second press while the first is in
  // flight would queue behind it and report against a file that has already
  // been written.
  async function runTransfer(verb: TransferVerb, run: (actions: VaultTransferActions) => Promise<ActionResult>) {
    if (!transferActions || transferring.current) return;
    transferring.current = true;
    const nextRequestId = requestId.current;
    dispatch({ type: "transferring", requestId: nextRequestId, verb });
    try {
      const result = await run(transferActions);
      if (requestId.current === nextRequestId) dispatch({ type: "transferred", requestId: nextRequestId, verb, result });
    } finally {
      transferring.current = false;
    }
  }

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
    // One stop at a time, and the registry read back afterwards. What the stop
    // reached is the sidecar's answer; which jobs are left is the registry's,
    // and neither is worked out here from the other.
    async cancelJob(jobId: string) {
      const actions = documentActions;
      if (!actions || !jobId.trim() || cancelling.current) return;
      cancelling.current = true;
      const nextRequestId = requestId.current;
      dispatch({ type: "cancelling", requestId: nextRequestId, jobId });
      try {
        const result = await actions.cancel(jobId);
        const read = await actions.readJobs();
        const jobs: readonly JobView[] = read.state === "ready" ? read.data.jobs : [];
        if (requestId.current === nextRequestId) dispatch({ type: "cancelled", requestId: nextRequestId, jobId, result, jobs });
      } finally {
        cancelling.current = false;
      }
    },
    transferAvailable: Boolean(transferActions),
    // One pass at a time, and the documents read taken again once the answer
    // is in: the pass writes, so what the screen shows can move under it.
    async rescanDocuments() {
      const actions = documentActions;
      if (!actions || sweeping.current) return;
      sweeping.current = true;
      const nextRequestId = requestId.current;
      dispatch({ type: "rescanning", requestId: nextRequestId });
      try {
        const { result, report } = await actions.rescan();
        const documents = await actions.reread();
        if (requestId.current === nextRequestId) dispatch({ type: "rescanned", requestId: nextRequestId, result, report, documents });
      } finally {
        sweeping.current = false;
      }
    },
    async exportVault(archive: string) {
      if (!archive.trim()) return;
      await runTransfer("export", (actions) => actions.export(archive.trim()));
    },
    async restoreVault(archive: string, directory: string, passphrase: string) {
      if (!archive.trim() || !directory.trim() || !passphrase) return;
      await runTransfer("restore", (actions) => actions.restore(archive.trim(), directory.trim(), passphrase));
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
