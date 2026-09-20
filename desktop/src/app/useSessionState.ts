import { useReducer, useRef, useState } from "react";
import { createDetectedBridgeClient } from "../bridge/client";
import type { LazyDestination } from "./session";
import { initialSession, sessionReducer } from "./session";
import type { CaptureGesture } from "./sessionCoordination";

// One reducer and one set of identity/generation refs are shared by all coordinators.
export function useSessionState(onDropped?: (gesture: CaptureGesture) => void) {
  const [session, dispatch] = useReducer(sessionReducer, undefined, initialSession);
  const [hostBridge] = useState(createDetectedBridgeClient);
  const requestId = useRef(0);
  const dropped = useRef(onDropped);
  dropped.current = onDropped;
  const questionGeneration = useRef(0);
  const activityLimit = useRef(50);
  // Full reads advance the revision that bounds asynchronous Activity pages.
  const surfaceRevision = useRef(0);
  const priorityGeneration = useRef(0);
  const secondaryGeneration = useRef(0);
  const jobsGeneration = useRef(0);
  const destinationGeneration = useRef(0);
  const retryingDestination = useRef<{ destination: LazyDestination; source: NonNullable<typeof session.source>; request: number; generation: number } | null>(null);
  const retryingPriority = useRef<{ request: number; generation: number } | null>(null);
  // Every verb this session has comes from the source, and before a vault is
  // open there is no source and therefore no verb. A screen asks whether it
  // has one; nothing here invents a verb that would have to refuse.
  const documentActions = session.source?.documentActions ?? null;
  const activityActions = session.source?.activityActions ?? null;
  const source = session.source;
  const sourceIdentity = useRef(source);
  sourceIdentity.current = source;

  return { session, dispatch, hostBridge, requestId, dropped, questionGeneration, activityLimit, surfaceRevision, priorityGeneration, secondaryGeneration, jobsGeneration, destinationGeneration, retryingDestination, retryingPriority, documentActions, activityActions, source, sourceIdentity };
}

export type SessionCoordination = ReturnType<typeof useSessionState>;
