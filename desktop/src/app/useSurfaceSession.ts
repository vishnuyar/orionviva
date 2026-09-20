import { useSessionState } from "./useSessionState";
import { useSessionReads } from "./useSessionReads";
import { useVaultLifecycle } from "./useVaultLifecycle";
import { useSessionJobs } from "./useSessionJobs";
import { useDocumentIntake } from "./useDocumentIntake";
import { useFeatureActions } from "./useFeatureActions";
import type { CaptureGesture } from "./sessionCoordination";
import type { Destination, EvidenceLink, Notice } from "../surface/types";

export { authoritativeQuestionReread, priorityAttemptCanPublish } from "./sessionCoordination";
export type { CaptureGesture } from "./sessionCoordination";

// Coordinators share the reducer and identity refs; none owns a second session.
export function useSurfaceSession(onDropped?: (gesture: CaptureGesture) => void) {
  const context = useSessionState(onDropped);
  const reads = useSessionReads(context);
  const vault = useVaultLifecycle(context, reads);
  const jobs = useSessionJobs(context);
  const documents = useDocumentIntake(context, reads);
  const actions = useFeatureActions(context, reads);
  const { session, dispatch, questionGeneration, destinationGeneration, retryingDestination } = context;
  const { readOpenedSource, refreshAfterAction, ...publicReads } = reads;

  return {
    session,
    ...publicReads,
    ...vault,
    ...jobs,
    ...documents,
    ...actions,
    navigate(destination: Destination) { questionGeneration.current += 1; ++destinationGeneration.current; retryingDestination.current = null; dispatch({ type: "navigate", destination }); },
    openEvidence(link: EvidenceLink) { dispatch({ type: "select-document", id: link.targetDocumentId }); dispatch({ type: "navigate", destination: "documents" }); },
    selectDocument(id: string) { dispatch({ type: "select-document", id }); },
    selectQueue(id: string) { questionGeneration.current += 1; dispatch({ type: "select-queue", id }); },
    selectAccount(id: string) { dispatch({ type: "select-account", id }); },
    selectPrompt(id: string) { dispatch({ type: "select-prompt", id }); },
    setNotice(notice: Notice | null) { dispatch({ type: "notice", notice }); },
  };
}
