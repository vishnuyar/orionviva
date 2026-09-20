import type { ActionResult, FeatureResult, SurfaceSnapshot } from "../surface/types";
import type { LazyDestination } from "./session";
import { hasAuthoritativeReviewConversationPair } from "./session";

export function dataBearing<T>(result: FeatureResult<T> | undefined): result is Extract<FeatureResult<T>, { data: T }> {
  return result?.state === "ready" || result?.state === "partial" || result?.state === "needs_input";
}

export function authoritativeQuestionReread(snapshot: SurfaceSnapshot | null): snapshot is SurfaceSnapshot {
  return hasAuthoritativeReviewConversationPair(snapshot);
}

export function priorityAttemptCanPublish(activeGeneration: number, latestGeneration: number, activeRequest: number, latestRequest: number, sameSource: boolean): boolean {
  return activeGeneration === latestGeneration && activeRequest === latestRequest && sameSource;
}

export function destinationReadFailed(destination: LazyDestination, snapshot: Partial<SurfaceSnapshot>): boolean {
  if (destination === "review") return snapshot.review?.state === "failed" || snapshot.conversation?.state === "failed";
  return snapshot[destination]?.state === "failed";
}

export function reviewHoldsQuestion(snapshot: SurfaceSnapshot, questionId: string): boolean {
  return dataBearing(snapshot.review) && snapshot.review.data.groups.some((group) => group.items.some((item) => item.target.questionId === questionId));
}

export function conversationHoldsQuestion(snapshot: SurfaceSnapshot, questionId: string): boolean {
  return dataBearing(snapshot.conversation) && snapshot.conversation.data.questions.queue.some((question) => question.id === questionId);
}

export function interrupted(message: string): Extract<ActionResult, { state: "interrupted" }> {
  return { state: "interrupted", message };
}

// What a gesture carrying files turned out to be. Only `one` reaches the
// vault; `several` is refused and `none` is a person changing their mind.
export type CaptureGesture = "none" | "one" | "several";
