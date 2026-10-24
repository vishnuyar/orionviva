import { useEffect, useRef, useState } from "react";
import type { AskActionState, AskContextMode, ConversationData, FeatureResult } from "../surface/types";

// Retain conversation context for the open vault session across composer dismissal.
export function useConversationContext(requestId: number, askState: AskActionState, history: FeatureResult<ConversationData> | null = null, blocked = false) {
  const turns = history?.state === "ready" ? history.data.turns : [];
  const historyEligible = turns.every((turn) => turn.id.trim() && turns.filter((candidate) => candidate.id === turn.id).length === 1) && turns.some((turn) => turn.kind === "ask" && turn.prompt.trim() && ["completed", "refused"].includes(turn.outcome) && (turn.answer?.text.trim() || turn.answer?.refusal.trim() || turn.message.trim()));
  const latest = useRef({ requestId, working: false, blocked, historyEligible });
  latest.current = { requestId, working: askState.state === "working", blocked, historyEligible };
  const [context, setContext] = useState<{ requestId: number; mode: AskContextMode }>({ requestId, mode: "new_question" });
  const pending = useRef<{ requestId: number; question: string; observedWorking: boolean } | null>(null);
  const mode = context.requestId === requestId ? context.mode : "new_question";
  useEffect(() => {
    const submission = pending.current;
    if (!submission) return;
    if (submission.requestId !== requestId) { pending.current = null; return; }
    if (askState.state === "working" && askState.question === submission.question) {
      submission.observedWorking = true;
      return;
    }
    if (askState.state === "settled" && submission.observedWorking && askState.question === submission.question
        && askState.authoritative === true && askState.result.state === "settled"
        && (askState.result.outcome.kind === "completed" || askState.result.outcome.kind === "refused")) {
      pending.current = null;
      setContext({ requestId, mode: "follow_up" });
    }
  }, [requestId, askState]);
  function startNewConversation() {
    if (latest.current.requestId !== requestId || latest.current.working) return;
    pending.current = null;
    setContext({ requestId, mode: "new_question" });
  }
  function continuePreviousConversation() {
    if (latest.current.requestId !== requestId || latest.current.working || latest.current.blocked || !latest.current.historyEligible) return;
    pending.current = null;
    setContext({ requestId, mode: "follow_up" });
  }
  function questionSubmitted(question: string, accountingCorrection = false) {
    pending.current = accountingCorrection ? null : { requestId, question, observedWorking: false };
  }
  return { contextMode: mode, canContinuePreviousConversation: historyEligible && !blocked, continuePreviousConversation, startNewConversation, questionSubmitted };
}
