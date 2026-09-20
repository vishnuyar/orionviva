import { useEffect, useRef } from "react";
import { BridgeTimeout } from "../bridge/contracts";
import { priorityAttemptCanPublish, interrupted } from "./sessionCoordination";
import type { SessionCoordination } from "./useSessionState";

type Coordination = Pick<SessionCoordination,
  | "session"
  | "dispatch"
  | "requestId"
  | "activityLimit"
  | "priorityGeneration"
  | "jobsGeneration"
  | "documentActions"
  | "source"
  | "sourceIdentity"
>;

export function useSessionJobs(context: Coordination) {
  const {
    session,
    dispatch,
    requestId,
    activityLimit,
    priorityGeneration,
    jobsGeneration,
    documentActions,
    source,
    sourceIdentity,
  } = context;
  const cancelling = useRef(false);
  const recheckingJobs = useRef(false);
  const jobStream = session.source?.jobStream ?? null;

  // What the sidecar is doing, as it does it. It cannot arrive in a reply:
  // the reply comes when the work is over, and a channel that only speaks
  // after the fact reports nothing a person could act on. The source hands
  // over rows that were already read; a source whose host cannot deliver one
  // mid-job carries no stream, and nothing here waits for one.
  useEffect(() => {
    if (!jobStream) return undefined;
    let stop: (() => void) | null = null;
    let gone = false;
    const subscribedRequest = requestId.current;
    const subscribedSource = source;
    void jobStream((job) => {
      if (gone || requestId.current !== subscribedRequest
          || sourceIdentity.current !== subscribedSource) return;
      ++jobsGeneration.current;
      dispatch({ type: "job-progress", requestId: subscribedRequest, job });
      if (subscribedSource && ["completed", "failed", "cancelled"].includes(job.state)) {
        const activePriority = ++priorityGeneration.current;
        void (async () => {
          if (!subscribedSource.loadPriority) return;
          const current = () => priorityAttemptCanPublish(activePriority, priorityGeneration.current,
            subscribedRequest, requestId.current, sourceIdentity.current === subscribedSource);
          const latest = await subscribedSource.loadPriority(true);
          if (!current()) return;
          dispatch({ type: "priority-loaded", requestId: subscribedRequest,
                     source: subscribedSource, overview: latest.snapshot.overview,
                     disclosure: latest.snapshot.disclosure, revision: latest.revision,
                     freshness: latest.freshness, lifecycle: latest.lifecycle,
                     retryable: latest.retryable });
          if (latest.freshness !== "current" || !latest.revision) {
            dispatch({ type: "mutation-refresh-failed", requestId: subscribedRequest });
            return;
          }
          const reread = subscribedSource.loadCoherent
            ? await subscribedSource.loadCoherent(activityLimit.current, undefined, latest)
            : { snapshot: await subscribedSource.load(activityLimit.current), revision: latest.revision };
          if (!current()) return;
          if (reread.revision !== latest.revision) {
            dispatch({ type: "mutation-refresh-failed", requestId: subscribedRequest });
            return;
          }
          dispatch({ type: "mutation-loaded", requestId: subscribedRequest, snapshot: reread.snapshot, revision: reread.revision });
        })().catch(() => {
          if (priorityAttemptCanPublish(activePriority, priorityGeneration.current,
              subscribedRequest, requestId.current, sourceIdentity.current === subscribedSource)) {
            dispatch({ type: "mutation-refresh-failed", requestId: subscribedRequest });
          }
        });
      }
    })
      .then((unlisten) => { if (gone) unlisten(); else stop = unlisten; })
      .catch(() => undefined);
    return () => { gone = true; stop?.(); };
  }, [jobStream, source]);

  return {
    async cancelJob(jobId: string) {
      const actions = documentActions;
      if (!actions || !jobId.trim() || cancelling.current) return;
      cancelling.current = true;
      const nextRequestId = requestId.current;
      dispatch({ type: "cancelling", requestId: nextRequestId, jobId });
      try {
        const result = await actions.cancel(jobId);
        const read = await actions.readJobs();
        if (requestId.current === nextRequestId) {
          dispatch({ type: "cancelled", requestId: nextRequestId, jobId, result, jobs: read.state === "ready" ? read.data.jobs : session.jobs });
          dispatch(read.state === "ready" ? { type: "jobs-read", requestId: nextRequestId, jobs: read.data.jobs } : { type: "jobs-unavailable", requestId: nextRequestId });
        }
      } catch (failure) {
        if (requestId.current === nextRequestId) {
          dispatch({ type: "cancelled", requestId: nextRequestId, jobId, result: failure instanceof BridgeTimeout
            ? interrupted("Stopping the job stopped answering and may already have changed that job's stop request. Recheck that job's status before trying again. OrionViva did not retry it.")
            : { state: "unanswered" }, jobs: session.jobs });
          if (failure instanceof BridgeTimeout) dispatch({ type: "jobs-unavailable", requestId: nextRequestId });
        }
      } finally {
        cancelling.current = false;
      }
    },
    jobStatus: session.jobStatus,
    jobCheck: session.jobCheck,
    async recheckJobs() {
      const activeSource = source;
      if (!activeSource?.loadJobs || recheckingJobs.current) return;
      recheckingJobs.current = true;
      const activeRequest = requestId.current;
      dispatch({ type: "jobs-checking", requestId: activeRequest });
      try {
        const read = await activeSource.loadJobs();
        if (requestId.current !== activeRequest) return;
        if (read.state === "ready") dispatch({ type: "jobs-read", requestId: activeRequest, jobs: read.data.jobs });
        else dispatch({ type: "jobs-unavailable", requestId: activeRequest });
      } catch { if (requestId.current === activeRequest) dispatch({ type: "jobs-unavailable", requestId: activeRequest }); }
      finally { recheckingJobs.current = false; }
    },
  };
}
