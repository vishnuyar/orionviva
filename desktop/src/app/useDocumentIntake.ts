import { useEffect, useRef } from "react";
import { BridgeTimeout } from "../bridge/contracts";
import type { DocumentActions } from "../surface/types";
import { interrupted } from "./sessionCoordination";
import type { CaptureGesture } from "./sessionCoordination";
import type { SessionCoordination } from "./useSessionState";
import type { useSessionReads } from "./useSessionReads";

type Coordination = Pick<SessionCoordination,
  | "session"
  | "dispatch"
  | "hostBridge"
  | "requestId"
  | "dropped"
  | "documentActions"
  | "source"
  | "sourceIdentity"
>;

export function useDocumentIntake(context: Coordination, { refreshAfterAction }: Pick<ReturnType<typeof useSessionReads>, "refreshAfterAction">) {
  const {
    session,
    dispatch,
    hostBridge,
    requestId,
    dropped,
    documentActions,
    source,
    sourceIdentity,
  } = context;
  const capturing = useRef(false);
  const choosing = useRef(false);
  const sweeping = useRef(false);

  // One document, one request, one answer. The vault is read again once the
  // answer is in, and that read is what the screen shows.
  async function capture(actions: DocumentActions, path: string) {
    if (sourceIdentity.current !== source || session.jobStatus === "unavailable" || capturing.current) return;
    capturing.current = true;
    const nextRequestId = requestId.current;
    dispatch({ type: "capturing", requestId: nextRequestId });
    try {
      const result = await actions.upload(path);
      const activeSource = source;
      if (!activeSource) return;
      await refreshAfterAction(activeSource, nextRequestId);
      if (requestId.current === nextRequestId) {
        dispatch({ type: "captured", requestId: nextRequestId, result });
      }
    } catch (failure) {
      if (requestId.current === nextRequestId) {
        dispatch({ type: "captured", requestId: nextRequestId, result: failure instanceof BridgeTimeout && failure.mayHaveWritten ? interrupted("Adding the statement stopped answering and may already have changed the vault. Inspect Statements and the document's activity before trying again. OrionViva did not retry it.") : { state: "unanswered" } });
        if (failure instanceof BridgeTimeout && failure.mayHaveWritten) dispatch({ type: "jobs-unavailable", requestId: nextRequestId });
      }
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
    const subscribedRequest = requestId.current;
    const current = () => !gone && requestId.current === subscribedRequest && sourceIdentity.current === source;
    void hostBridge.subscribeToDroppedPaths((paths) => {
      if (!paths.length || !current()) return;
      dropped.current?.(paths.length === 1 ? "one" : "several");
      if (current()) void captureGesture(documentActions, paths);
    })
      .then((unlisten) => { if (gone) unlisten(); else stop = unlisten; })
      .catch(() => undefined);
    return () => { gone = true; stop?.(); };
  }, [documentActions, hostBridge]);

  return {
    recoveryAvailable: Boolean(documentActions?.recover),
    async recoverDocument(jobId: string) {
      const actions = documentActions;
      const activeSource = source;
      if (!actions?.recover || !activeSource || capturing.current || session.jobStatus === "unavailable"
          || !session.jobs.some((job) => job.jobId === jobId && job.recovery?.state === "available")) return;
      capturing.current = true;
      const activeRequest = requestId.current;
      dispatch({ type: "capturing", requestId: activeRequest });
      try {
        const result = await actions.recover(jobId);
        await refreshAfterAction(activeSource, activeRequest);
        if (requestId.current === activeRequest) dispatch({ type: "captured", requestId: activeRequest, result });
      } catch (failure) {
        if (requestId.current === activeRequest) {
          dispatch({ type: "captured", requestId: activeRequest, result: failure instanceof BridgeTimeout && failure.mayHaveWritten
            ? interrupted("Reading the saved original stopped answering and may already have changed the vault. Recheck the job and inspect Statements before trying again. OrionViva did not retry it.")
            : { state: "unanswered" } });
          if (failure instanceof BridgeTimeout) dispatch({ type: "jobs-unavailable", requestId: activeRequest });
        }
      } finally { capturing.current = false; }
    },
    captureAvailable: Boolean(documentActions),
    filePickerAvailable: Boolean(documentActions && hostBridge?.pickDocumentPaths),
    // One picker at a time, and one capture at a time. The picker being open
    // is not the vault being busy, so it is held apart from the state the
    // screen renders.
    //
    // A picker that closed with nothing chosen and a picker that could not be
    // opened are answered differently: the first is a person changing their
    // mind, the second is a control that did not work, and only the second is
    // reported back.
    async chooseDocuments(): Promise<CaptureGesture | "unopened"> {
    if (!documentActions || !hostBridge?.pickDocumentPaths || session.jobStatus === "unavailable" || capturing.current || choosing.current) return "none";
      choosing.current = true;
      const activeRequest = requestId.current;
      const activeSource = source;
      let paths: readonly string[] = [];
      try { paths = await hostBridge.pickDocumentPaths(); }
      catch { choosing.current = false; return requestId.current === activeRequest && sourceIdentity.current === activeSource ? "unopened" : "none"; }
      choosing.current = false;
      if (requestId.current !== activeRequest || sourceIdentity.current !== activeSource) return "none";
      return captureGesture(documentActions, paths);
    },
    // One stop at a time, and the registry read back afterwards. What the stop
    // reached is the sidecar's answer; which jobs are left is the registry's,
    // and neither is worked out here from the other.
    // One pass at a time, and the documents read taken again once the answer
    // is in: the pass writes, so what the screen shows can move under it.
    async rescanDocuments() {
      const actions = documentActions;
      const activeSource = source;
      if (!actions || !activeSource || session.jobStatus === "unavailable" || sweeping.current) return;
      sweeping.current = true;
      const nextRequestId = requestId.current;
      dispatch({ type: "rescanning", requestId: nextRequestId });
      try {
        const { result, report } = await actions.rescan();
        await refreshAfterAction(activeSource, nextRequestId);
        if (requestId.current === nextRequestId) {
          dispatch({ type: "rescanned", requestId: nextRequestId, result, report });
        }
      } catch (failure) {
        if (requestId.current === nextRequestId) {
          if (failure instanceof BridgeTimeout) dispatch({ type: "jobs-unavailable", requestId: nextRequestId });
          dispatch({ type: "rescanned", requestId: nextRequestId, result: failure instanceof BridgeTimeout ? interrupted("Rescanning the vault stopped answering and may already have changed the vault. Inspect Statements, Activity, and Review before trying again. OrionViva did not retry it.") : { state: "unanswered" }, report: null });
        }
      } finally {
        sweeping.current = false;
      }
    },
  };
}
