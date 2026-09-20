import { useCallback, useEffect } from "react";
import type { AccountLedgerData, FeatureResult, SpendingBreakdownData, SpendingRequest } from "../surface/types";
import type { LazyDestination } from "./session";
import { liveReadingSnapshot } from "./session";
import { priorityAttemptCanPublish, destinationReadFailed } from "./sessionCoordination";
import type { SessionCoordination } from "./useSessionState";

type Coordination = Pick<SessionCoordination,
  | "session"
  | "dispatch"
  | "requestId"
  | "activityLimit"
  | "surfaceRevision"
  | "priorityGeneration"
  | "secondaryGeneration"
  | "jobsGeneration"
  | "destinationGeneration"
  | "retryingDestination"
  | "retryingPriority"
  | "activityActions"
  | "source"
  | "sourceIdentity"
>;

export function useSessionReads(context: Coordination) {
  const {
    session,
    dispatch,
    requestId,
    activityLimit,
    surfaceRevision,
    priorityGeneration,
    secondaryGeneration,
    jobsGeneration,
    destinationGeneration,
    retryingDestination,
    retryingPriority,
    activityActions,
    source,
    sourceIdentity,
  } = context;
  const accountLedgerReader = session.source?.accountLedgerReader ?? null;
  const spendingBreakdownReader = session.source?.spendingBreakdownReader ?? null;

  async function readOpenedSource(activeSource: NonNullable<typeof source>, activeRequest: number) {
    sourceIdentity.current = activeSource;
    retryingDestination.current = null;
    ++destinationGeneration.current;
    dispatch({ type: "reading", requestId: activeRequest, source: activeSource, snapshot: liveReadingSnapshot() });
    try {
      if (!activeSource.loadPriority || !activeSource.loadSecondary) throw new Error("priority_contract_unavailable");
      const loadSecondary = activeSource.loadSecondary;
      const activePriority = ++priorityGeneration.current;
      const activeSecondary = ++secondaryGeneration.current;
      // The active financial read is requested before supporting reads.
      const priorityWork = activeSource.loadPriority();
      const priority = await priorityWork;
      if (!priorityAttemptCanPublish(activePriority, priorityGeneration.current, activeRequest, requestId.current, sourceIdentity.current === activeSource)) return false;
      dispatch({ type: "priority-loaded", requestId: activeRequest, source: activeSource, overview: priority.snapshot.overview, disclosure: priority.snapshot.disclosure, revision: priority.revision, freshness: priority.freshness, lifecycle: priority.lifecycle, retryable: priority.retryable });
      if (priority.lifecycle === "rebuilding") {
        const watchGeneration = activePriority;
        void (async () => {
          for (let attempt = 0; attempt < 240; attempt += 1) {
            await new Promise((resolve) => globalThis.setTimeout(resolve, 250));
            if (!priorityAttemptCanPublish(watchGeneration, priorityGeneration.current, activeRequest, requestId.current, sourceIdentity.current === activeSource)) return;
            const refreshed = await activeSource.loadPriority!();
            if (!priorityAttemptCanPublish(watchGeneration, priorityGeneration.current, activeRequest, requestId.current, sourceIdentity.current === activeSource)) return;
            dispatch({ type: "priority-loaded", requestId: activeRequest, source: activeSource, overview: refreshed.snapshot.overview, disclosure: refreshed.snapshot.disclosure, revision: refreshed.revision, freshness: refreshed.freshness, lifecycle: refreshed.lifecycle, retryable: refreshed.retryable });
            if (refreshed.lifecycle !== "rebuilding") return;
          }
        })().catch(() => undefined);
      }
      void loadSecondary(activityLimit.current)
        .then((snapshot) => { if (requestId.current === activeRequest && secondaryGeneration.current === activeSecondary && sourceIdentity.current === activeSource) dispatch({ type: "secondary-loaded", requestId: activeRequest, snapshot }); })
        .catch(() => undefined);
      const activeJobs = ++jobsGeneration.current;
      const jobsWork = activeSource.loadJobs
        ? Promise.resolve().then(() => activeSource.loadJobs!()).catch(() => null)
        : Promise.resolve(null);
      void jobsWork.then((jobsRead) => {
        if (requestId.current !== activeRequest || sourceIdentity.current !== activeSource
            || jobsGeneration.current !== activeJobs || !activeSource.loadJobs) return;
        dispatch(jobsRead?.state === "ready"
          ? { type: "jobs-read", requestId: activeRequest, jobs: jobsRead.data.jobs }
          : { type: "jobs-unavailable", requestId: activeRequest });
      }).catch(() => { if (requestId.current === activeRequest && sourceIdentity.current === activeSource && jobsGeneration.current === activeJobs) dispatch({ type: "jobs-unavailable", requestId: activeRequest }); });
      return true;
    } catch {
      if (requestId.current === activeRequest) dispatch({ type: "load-failed", requestId: activeRequest });
      return false;
    }
  }

  async function refreshAfterAction(activeSource: NonNullable<typeof source>, activeRequest: number, stillCurrent: () => boolean = () => true) {
    ++surfaceRevision.current;
    try {
      const snapshotWork = activeSource.loadCoherent
        ? activeSource.loadCoherent(activityLimit.current)
        : activeSource.load(activityLimit.current).then((snapshot) => ({ snapshot, revision: "" }));
      const activeJobs = activeSource.loadJobs ? ++jobsGeneration.current : 0;
      const jobsWork = activeSource.loadJobs
        ? Promise.resolve().then(() => activeSource.loadJobs!()).catch(() => null)
        : null;
      const { snapshot, revision } = await snapshotWork;
      if (requestId.current === activeRequest && stillCurrent()
          && sourceIdentity.current === activeSource) {
        dispatch({ type: "mutation-loaded", requestId: activeRequest, snapshot, revision });
      }
      if (jobsWork) {
        void jobsWork.then((jobsRead) => {
          if (requestId.current !== activeRequest || !stillCurrent()
              || sourceIdentity.current !== activeSource
              || jobsGeneration.current !== activeJobs) return;
          dispatch(jobsRead?.state === "ready"
            ? { type: "jobs-read", requestId: activeRequest, jobs: jobsRead.data.jobs }
            : { type: "jobs-unavailable", requestId: activeRequest });
        }).catch(() => {
          if (requestId.current === activeRequest && stillCurrent()
              && sourceIdentity.current === activeSource
              && jobsGeneration.current === activeJobs) {
            dispatch({ type: "jobs-unavailable", requestId: activeRequest });
          }
        });
      }
      return snapshot;
    } catch {
      if (requestId.current === activeRequest && stillCurrent()) dispatch({ type: "mutation-refresh-failed", requestId: activeRequest });
      return null;
    }
  }

  // These reads are destination-local: opening a vault never queues them.
  useEffect(() => {
    if (!source?.loadDestination || !["documents", "review", "trust", "activity", "plans"].includes(session.destination)) return undefined;
    const destination = session.destination as LazyDestination;
    const activeRequest = requestId.current;
    const activeGeneration = ++destinationGeneration.current;
    let gone = false;
    dispatch({ type: "destination-loading", requestId: activeRequest, destination });
    void source.loadDestination(destination, activityLimit.current).then((snapshot) => {
      if (!gone && requestId.current === activeRequest && sourceIdentity.current === source && destinationGeneration.current === activeGeneration) {
        dispatch(destinationReadFailed(destination, snapshot)
          ? { type: "destination-failed", requestId: activeRequest, destination, snapshot }
          : { type: "destination-loaded", requestId: activeRequest, destination, snapshot });
      }
    }).catch(() => {
      if (!gone && requestId.current === activeRequest && sourceIdentity.current === source && destinationGeneration.current === activeGeneration) {
        dispatch({ type: "destination-failed", requestId: activeRequest, destination });
      }
    });
    return () => { gone = true; };
  }, [session.destination, source]);

  const readSpendingBreakdown = useCallback(async (request: SpendingRequest): Promise<FeatureResult<SpendingBreakdownData>> => {
    if (!spendingBreakdownReader) return { state: "absent", reason: "not_available" };
    const activeRequest = requestId.current;
    const activeRevision = surfaceRevision.current;
    const activeSource = source;
    const result = await spendingBreakdownReader.read(request);
    if (requestId.current !== activeRequest
        || surfaceRevision.current !== activeRevision
        || sourceIdentity.current !== activeSource) {
      return { state: "absent", reason: "stale_read" };
    }
    return result;
  }, [source, spendingBreakdownReader]);

  return {
    async retryDestinationRead(destination: LazyDestination) {
      const activeSource = source;
      const activeRequest = requestId.current;
      const held = retryingDestination.current;
      if (!activeSource?.loadDestination || session.destination !== destination || session.destinationReads[destination] !== "failed"
          || (held?.destination === destination && held.source === activeSource && held.request === activeRequest && held.generation === destinationGeneration.current)) return "ignored" as const;
      const activeGeneration = ++destinationGeneration.current;
      const retryToken = { destination, source: activeSource, request: activeRequest, generation: activeGeneration };
      retryingDestination.current = retryToken;
      dispatch({ type: "destination-retrying", requestId: activeRequest, destination });
      try {
        const snapshot = await activeSource.loadDestination(destination, activityLimit.current);
        if (requestId.current !== activeRequest || sourceIdentity.current !== activeSource || destinationGeneration.current !== activeGeneration) return "ignored" as const;
        if (destinationReadFailed(destination, snapshot)) {
          dispatch({ type: "destination-failed", requestId: activeRequest, destination, snapshot });
          return "failed" as const;
        }
        dispatch({ type: "destination-loaded", requestId: activeRequest, destination, snapshot });
        return "succeeded" as const;
      } catch {
        if (requestId.current !== activeRequest || sourceIdentity.current !== activeSource || destinationGeneration.current !== activeGeneration) return "ignored" as const;
        dispatch({ type: "destination-failed", requestId: activeRequest, destination });
        return "failed" as const;
      } finally {
        if (retryingDestination.current === retryToken) retryingDestination.current = null;
      }
    },
    async retryPriorityRead() {
      const activeSource = source;
      if (!activeSource?.loadPriority || !session.priorityRetryable || retryingPriority.current?.request === requestId.current) return "ignored" as const;
      const activeRequest = requestId.current;
      const activePriority = ++priorityGeneration.current;
      const retryToken = { request: activeRequest, generation: activePriority };
      retryingPriority.current = retryToken;
      dispatch({ type: "priority-retrying", requestId: activeRequest });
      try {
        const priority = await activeSource.loadPriority(true);
        if (!priorityAttemptCanPublish(activePriority, priorityGeneration.current, activeRequest, requestId.current, sourceIdentity.current === activeSource)) return "ignored" as const;
        dispatch({ type: "priority-loaded", requestId: activeRequest, source: activeSource, overview: priority.snapshot.overview, disclosure: priority.snapshot.disclosure, revision: priority.revision, freshness: priority.freshness, lifecycle: priority.lifecycle, retryable: priority.retryable });
        if (priority.freshness === "current") {
          dispatch({ type: "priority-retry-succeeded", requestId: activeRequest });
          return "succeeded" as const;
        }
        dispatch({ type: "priority-retry-failed", requestId: activeRequest });
        return "failed" as const;
      } catch {
        if (priorityAttemptCanPublish(activePriority, priorityGeneration.current, activeRequest, requestId.current, sourceIdentity.current === activeSource)) {
          dispatch({ type: "priority-retry-failed", requestId: activeRequest });
          return "failed" as const;
        }
        return "ignored" as const;
      } finally {
        if (retryingPriority.current === retryToken) retryingPriority.current = null;
      }
    },
    // Navigation can request the selected account on demand without placing a
    // potentially large ledger in the all-surface startup snapshot. Pages are
    // returned separately; this layer never merges or de-duplicates rows.
    async readAccountLedger(accountId: string, cursor?: string, limit?: number): Promise<FeatureResult<AccountLedgerData>> {
      if (!accountLedgerReader || !accountId.trim()) return { state: "absent", reason: "not_available" };
      const activeRequest = requestId.current;
      const activeRevision = surfaceRevision.current;
      const activeSource = source;
      const result = await accountLedgerReader.read(accountId, cursor, limit);
      if (requestId.current !== activeRequest
          || surfaceRevision.current !== activeRevision
          || sourceIdentity.current !== activeSource) {
        return { state: "absent", reason: "stale_read" };
      }
      return result;
    },
    readSpendingBreakdown,
    async loadMoreActivity() {
      const current = session.snapshot.activity;
      if (!activityActions || current.state !== "ready" || current.data.beyond.count < 1) return;
      const nextRequestId = requestId.current;
      const startedAtRevision = surfaceRevision.current;
      const nextLimit = current.data.movements.length + 50;
      try {
        const activity = await activityActions.read(nextLimit);
        if (requestId.current === nextRequestId && surfaceRevision.current === startedAtRevision) {
          if (activity.state === "ready" || activity.state === "partial" || activity.state === "needs_input") activityLimit.current = nextLimit;
          dispatch({ type: "activity-page-loaded", requestId: nextRequestId, activity });
        }
      } catch {
        if (requestId.current === nextRequestId && surfaceRevision.current === startedAtRevision) dispatch({ type: "notice", notice: { kind: "refused", text: "More activity could not be read. The movements already shown are unchanged." } });
      }
    },
    async ensureDestination(destination: "documents" | "review" | "trust" | "activity" | "plans") {
      const activeSource = source;
      const activeRequest = requestId.current;
      if (!activeSource?.loadDestination) return false;
      try {
        const snapshot = await activeSource.loadDestination(destination, activityLimit.current);
        if (requestId.current !== activeRequest || sourceIdentity.current !== activeSource) return false;
        if (destinationReadFailed(destination, snapshot)) {
          dispatch({ type: "destination-failed", requestId: activeRequest, destination, snapshot });
          return false;
        }
        dispatch({ type: "destination-loaded", requestId: activeRequest, destination, snapshot });
        return snapshot;
      } catch { return false; }
    },
    readOpenedSource, refreshAfterAction,
  };
}
