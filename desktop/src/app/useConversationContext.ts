import { useEffect, useRef, useState } from "react";
import type { AskActionState, AskContextMode } from "../surface/types";

// Retain conversation context for the open vault session across composer dismissal.
export function useConversationContext(requestId: number, askState: AskActionState) {
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
    if (askState.state === "working") return;
    pending.current = null;
    setContext({ requestId, mode: "new_question" });
  }
  function questionSubmitted(question: string, accountingCorrection = false) {
    pending.current = accountingCorrection ? null : { requestId, question, observedWorking: false };
  }
  return { contextMode: mode, startNewConversation, questionSubmitted };
}
