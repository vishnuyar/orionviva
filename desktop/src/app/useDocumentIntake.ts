import { useEffect, useRef, useState } from "react";
import { BridgeRefusal, BridgeTimeout, REQUEST_REFUSED } from "../bridge/contracts";
import type { BulkDocumentSession, DocumentActions, SurfaceDocument, RetainedReadingSelection } from "../surface/types";
import bulkCopy from "../features/documents/bulk-upload-v1.json";
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
  const selectionGeneration = requestId.current;
  const capturing = useRef(false);
  const choosing = useRef(false);
  const sweeping = useRef(false);
  const [bulkSession, setBulkSession] = useState<BulkDocumentSession | null>(null);
  const [retainedSelection, setRetainedSelection] = useState<readonly RetainedReadingSelection[]>([]);
  const retainedPending = useRef<readonly RetainedReadingSelection[]>(retainedSelection);
  const consumedTokens = useRef<readonly string[]>([]);
  const retainedBlocked = session.jobStatus === "unavailable" || session.captureAction.state === "working" || ((session.settings.state === "ready" || session.settings.state === "partial" || session.settings.state === "needs_input") && !session.settings.data.canSend);
  const retainedBlockedNow = useRef(retainedBlocked);
  retainedBlockedNow.current = retainedBlocked;
  const bulkRun = useRef<{ stop: boolean; gone: boolean; jobId: string | null; cancelled: boolean; knownJobs: Set<string>; actions: DocumentActions } | null>(null);
  const sessionJobs = useRef(session.jobs);
  sessionJobs.current = session.jobs;
  useEffect(() => {
    setBulkSession(null);
    retainedPending.current = []; setRetainedSelection([]); consumedTokens.current = [];
    return () => { retainedPending.current = []; consumedTokens.current = []; if (bulkRun.current) { bulkRun.current.stop = true; bulkRun.current.gone = true; } };
  }, [source]);
  useEffect(() => { retainedPending.current = []; setRetainedSelection([]); consumedTokens.current = []; }, [selectionGeneration]);
  const bulkCurrent = () => bulkRun.current;
  async function cancelActiveBulk() {
    const run = bulkCurrent();
    if (!run || run.gone || !run.stop || run.cancelled || !run.jobId) return;
    run.cancelled = true;
    try { await run.actions.cancel(run.jobId); }
    catch { /* The chunk reply remains authoritative; stopping never resubmits it. */ }
  }
  useEffect(() => {
    const run = bulkCurrent();
    if (!run || run.gone) return;
    const job = [...session.jobs].reverse().find((job) => job.operation === "viva.documents.upload_many" && job.state === "running" && !run.knownJobs.has(job.jobId));
    if (job) { run.jobId = job.jobId; void cancelActiveBulk(); }
  }, [session.jobs]);

  async function captureMany(actions: DocumentActions, paths: readonly string[], retained?: readonly RetainedReadingSelection[]): Promise<CaptureGesture> {
    if (!(retained ? actions.readRetained : actions.uploadMany) || !source || sourceIdentity.current !== source || session.jobStatus === "unavailable" || capturing.current) return "none";
    if (!paths.length) return "none";
    if (paths.length > 1000) return "over_limit";
    capturing.current = true;
    const activeRequest = requestId.current;
    const run = { stop: false, gone: false, jobId: null as string | null, cancelled: false, knownJobs: new Set(sessionJobs.current.map((job) => job.jobId)), actions };
    bulkRun.current = run;
    const current = () => !run.gone && bulkRun.current === run && requestId.current === activeRequest && sourceIdentity.current === source;
    let state: BulkDocumentSession = { mode: retained ? "retained" : undefined, state: "running", rows: paths.map((path, index) => ({ path, documentId: retained?.[index].documentId, status: "queued" })), jobIds: [] };
    const publish = () => { if (current()) setBulkSession({ ...state, rows: [...state.rows] }); };
    publish();
    dispatch({ type: "capturing", requestId: activeRequest });
    try {
      for (let offset = 0; offset < paths.length && current() && !run.stop; offset += 3) {
        const chunk = paths.slice(offset, offset + 3);
        run.jobId = null; run.cancelled = false;
        run.knownJobs = new Set([...sessionJobs.current.map((job) => job.jobId), ...state.jobIds]);
        state = { ...state, rows: state.rows.map((row, index) => index >= offset && index < offset + chunk.length ? { ...row, status: "working" } : row) };
        publish();
        try {
          const result = retained ? await actions.readRetained!(retained) : await actions.uploadMany!(chunk);
          if (!current()) return "bulk";
          const uncertain = result.rows.some((row) => row.reason === "outcome_unknown");
          if (uncertain || result.rows.some((row) => row.action === "cancelled")) run.stop = true;
          state = { ...state, state: uncertain ? "uncertain" : state.state, jobIds: [...state.jobIds, result.jobId], rows: state.rows.map((row, index) => {
            const outcome = result.rows[index - offset];
            return index >= offset && index < offset + chunk.length && outcome ? { ...row, status: outcome.reason === "outcome_unknown" ? "uncertain" : outcome.action, outcome } : uncertain && row.status === "queued" ? { ...row, status: "not_started" } : row;
          }) };
          publish();
        } catch (failure) {
          if (!current()) return "bulk";
          run.stop = true;
          if (failure instanceof BridgeRefusal && failure.code === REQUEST_REFUSED) {
            state = { ...state, state: "finished", rows: state.rows.map((row) => row.status === "working" ? { ...row, status: "refused" } : row.status === "queued" ? { ...row, status: "not_started" } : row) };
            publish();
            break;
          }
          state = { ...state, state: "uncertain", rows: state.rows.map((row) => row.status === "working" ? { ...row, status: "uncertain" } : row.status === "queued" ? { ...row, status: "not_started" } : row) };
          publish();
          const jobs = await actions.readJobs().catch(() => null);
          if (current()) dispatch(jobs?.state === "ready" ? { type: "jobs-read", requestId: activeRequest, jobs: jobs.data.jobs } : { type: "jobs-unavailable", requestId: activeRequest });
          break;
        }
      }
      if (!current()) return "bulk";
      if (state.state !== "uncertain") {
        state = { ...state, state: "finished", rows: state.rows.map((row) => row.status === "queued" ? { ...row, status: "not_started" } : row) };
        publish();
      }
      await refreshAfterAction(source, activeRequest).catch(() => undefined);
      if (current()) dispatch({ type: "captured", requestId: activeRequest, result: state.state === "uncertain" ? interrupted(bulkCopy.uncertain) : { state: "settled", outcome: { kind: "completed", message: retained ? "New readings finished. Review each result; finished does not mean posted." : bulkCopy.finished, reason: "" } } });
    } finally {
      if (bulkRun.current === run) { capturing.current = false; bulkRun.current = null; }
    }
    return "bulk";
  }


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

  // A single-file picker stays exact; multiple dropped paths use the bounded
  // selection queue where the source supports bulk reading.
  async function captureGesture(actions: DocumentActions, paths: readonly string[]): Promise<CaptureGesture> {
    const [first, second] = paths;
    if (first === undefined) return "none";
    if (second !== undefined) return actions.uploadMany ? captureMany(actions, paths) : "several";
    await capture(actions, first);
    return "one";
  }

  // A dropped file arrives from the host as a path, because the native layer
  // takes the drop before this side can see it. A drop can land while any
  // screen is open and what it writes is durable, so what became of it is
  // handed to the screen that can move a person to its receipt. Multiple paths
  // retain one session row each. The subscription lives with its source.
  useEffect(() => {
    if (!documentActions || !hostBridge?.subscribeToDroppedPaths) return undefined;
    let stop: (() => void) | null = null;
    let gone = false;
    const subscribedRequest = requestId.current;
    const current = () => !gone && requestId.current === subscribedRequest && sourceIdentity.current === source;
    void hostBridge.subscribeToDroppedPaths((paths) => {
      if (!paths.length || !current()) return;
      dropped.current?.(paths.length > 1000 ? "over_limit" : paths.length === 1 ? "one" : documentActions.uploadMany ? "bulk" : "several");
      if (current()) void captureGesture(documentActions, paths);
    })
      .then((unlisten) => { if (gone) unlisten(); else stop = unlisten; })
      .catch(() => undefined);
    return () => { gone = true; stop?.(); };
  }, [documentActions, hostBridge]);

  return {
    bulkSession,
    retainedSelection,
    retainedAvailable: Boolean(documentActions?.readRetained),
    retainedBlocked,
    canSelectRetained(document: SurfaceDocument) {
      return Boolean(document.retry?.state === "available" && document.retry.confirmationToken && !consumedTokens.current.includes(document.retry.confirmationToken) && !retainedPending.current.some((entry) => entry.documentId === document.id || entry.confirmationToken === document.retry?.confirmationToken) && retainedPending.current.length < 3 && !retainedBlocked && !capturing.current);
    },
    addRetainedReading(document: SurfaceDocument) {
      const retry = document.retry;
      if (!documentActions?.readRetained || requestId.current !== selectionGeneration || sourceIdentity.current !== source || retainedBlockedNow.current || capturing.current || !retry || retry.state !== "available" || !retry.confirmationToken || consumedTokens.current.includes(retry.confirmationToken) || retainedPending.current.length >= 3 || retainedPending.current.some((entry) => entry.documentId === document.id || entry.confirmationToken === retry.confirmationToken)) return;
      const next = [...retainedPending.current, { documentId: document.id, name: document.name, reason: retry.reason, confirmationToken: retry.confirmationToken }];
      retainedPending.current = next; setRetainedSelection(next);
    },
    removeRetainedReading(documentId: string) {
      const next = retainedPending.current.filter((entry) => entry.documentId !== documentId);
      retainedPending.current = next; setRetainedSelection(next);
    },
    confirmRetainedReadings() {
      // The rendered gesture owns this exact selection. Consume before any await.
      if (requestId.current !== selectionGeneration || retainedPending.current !== retainedSelection || !retainedSelection.length || retainedBlockedNow.current || capturing.current || sourceIdentity.current !== source || !documentActions?.readRetained) return;
      const selected = retainedSelection;
      retainedPending.current = []; setRetainedSelection([]);
      consumedTokens.current = selected.map((entry) => entry.confirmationToken);
      void captureMany(documentActions, selected.map((entry) => entry.name), selected);
    },
    bulkPickerAvailable: Boolean(documentActions?.uploadMany && hostBridge?.pickMultipleDocumentPaths),
    stopBulkDocuments() {
      const run = bulkCurrent();
      if (!run || run.gone) return;
      run.stop = true;
      setBulkSession((state) => state && state.state === "running" ? { ...state, state: "stopping" } : state);
      void cancelActiveBulk();
    },
    async chooseBulkDocuments(): Promise<CaptureGesture | "unopened"> {
      if (!documentActions?.uploadMany || !hostBridge?.pickMultipleDocumentPaths || session.jobStatus === "unavailable" || capturing.current || choosing.current) return "none";
      choosing.current = true;
      const activeRequest = requestId.current;
      const activeSource = source;
      let paths: readonly string[];
      try { paths = await hostBridge.pickMultipleDocumentPaths(); }
      catch (failure) {
        if (requestId.current !== activeRequest || sourceIdentity.current !== activeSource) return "none";
        return failure instanceof Error && failure.message === "selection_over_limit" ? "over_limit" : "unopened";
      }
      finally { choosing.current = false; }
      if (requestId.current !== activeRequest || sourceIdentity.current !== activeSource) return "none";
      return captureMany(documentActions, paths);
    },
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
      if (paths.length > 1) return "several";
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
