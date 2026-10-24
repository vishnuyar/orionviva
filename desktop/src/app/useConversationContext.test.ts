import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { AskActionState } from "../surface/types";
import { useConversationContext } from "./useConversationContext";

const idle: AskActionState = { state: "idle" };
const working: AskActionState = { state: "working", question: "What changed?" };
const settled = (authoritative = true, kind: "completed" | "refused" = "completed"): AskActionState => ({ state: "settled", question: "What changed?", authoritative, result: { state: "settled", outcome: { kind, message: "Answer", reason: "" } }, turn: null });

describe("vault session conversation context", () => {
  it("continues only after observing its own authoritative settlement and retains a deliberate new boundary", () => {
    const view = renderHook(({ state }: { state: AskActionState }) => useConversationContext(1, state), { initialProps: { state: idle as AskActionState } });
    act(() => view.result.current.questionSubmitted("What changed?"));
    view.rerender({ state: settled() });
    expect(view.result.current.contextMode).toBe("new_question");
    view.rerender({ state: working });
    view.rerender({ state: settled(false) });
    expect(view.result.current.contextMode).toBe("new_question");
    view.rerender({ state: settled() });
    expect(view.result.current.contextMode).toBe("follow_up");
    act(() => view.result.current.startNewConversation());
    expect(view.result.current.contextMode).toBe("new_question");
    view.rerender({ state: settled() });
    expect(view.result.current.contextMode).toBe("new_question");
  });
  it("does not revive an old request across vaults or accounting corrections", () => {
    const view = renderHook(({ requestId, state }: { requestId: number; state: AskActionState }) => useConversationContext(requestId, state), { initialProps: { requestId: 1, state: idle as AskActionState } });
    act(() => view.result.current.questionSubmitted("What changed?"));
    view.rerender({ requestId: 1, state: working });
    act(() => view.result.current.startNewConversation());
    view.rerender({ requestId: 1, state: settled(true, "refused") });
    expect(view.result.current.contextMode).toBe("follow_up");
    view.rerender({ requestId: 2, state: idle });
    expect(view.result.current.contextMode).toBe("new_question");
    act(() => view.result.current.questionSubmitted("What changed?", true));
    view.rerender({ requestId: 2, state: working });
    view.rerender({ requestId: 2, state: settled() });
    expect(view.result.current.contextMode).toBe("new_question");
  });
});
